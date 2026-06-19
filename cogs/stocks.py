import io
import math
import random
import time
import asyncio
import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.patches import Rectangle

from config.stocks import (
    ADR_STOCKS, ETF_TICKER, ETF_INFO, PENNY_STOCKS,
    ADR_TICKERS, PENNY_TICKERS, ALL_TICKERS,
    TURBO_LEVERAGES, TURBOS_PER_DAY, TURBO_MIN_COST,
    PRICE_UPDATE_INTERVAL,
    CIRCUIT_BREAKER_HALT_PCT, CIRCUIT_BREAKER_HALT_SECS, CIRCUIT_BREAKER_DAILY_PCT,
    PUMP_TRIGGER_PROB, PUMP_DURATION_SECS, PUMP_DRIFT_PER_TICK, PUMP_CRASH_PCT,
    _YF_PERIOD_MAP, _PERIOD_SECONDS,
)

PERIODS         = ["1D", "5D", "1M", "3M", "6M", "1Y"]
CHART_TYPES     = ["candlestick", "line"]
_BSE_THUMB      = "images/beijingStockExchange.png"
_ADR_CLOSED_VOL = 0.0006   # per-tick micro-drift for ADRs when market is closed
_CHART_CACHE_TTL = 45       # seconds before a cached chart is considered stale


def _ticker_info_name(ticker: str) -> str:
    if ticker in ADR_STOCKS:  return ADR_STOCKS[ticker]["name"]
    if ticker == ETF_TICKER:   return ETF_INFO["name"]
    return PENNY_STOCKS.get(ticker, {}).get("name", ticker)


def _next_market_event() -> tuple[str, int, int]:
    """Returns (event, next_ts, today_open_ts) where event is 'open' or 'close'."""
    now    = datetime.datetime.now(datetime.timezone.utc)
    midnight = datetime.datetime(now.year, now.month, now.day, tzinfo=datetime.timezone.utc)
    open_ts  = int((midnight + datetime.timedelta(hours=14, minutes=30)).timestamp())
    close_ts = int((midnight + datetime.timedelta(hours=21)).timestamp())
    now_ts   = int(now.timestamp())
    if now.weekday() < 5:
        if now_ts < open_ts:
            return "open", open_ts, open_ts
        if now_ts < close_ts:
            return "close", close_ts, open_ts
    days = 1
    while True:
        nxt = now.date() + datetime.timedelta(days=days)
        if nxt.weekday() < 5:
            nm   = datetime.datetime(nxt.year, nxt.month, nxt.day, tzinfo=datetime.timezone.utc)
            nts  = int((nm + datetime.timedelta(hours=14, minutes=30)).timestamp())
            return "open", nts, open_ts
        days += 1


def _is_market_hours() -> bool:
    now = datetime.datetime.utcnow()
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 14 * 60 + 30 <= mins < 21 * 60


def _turbo_value_factor(direction: str, entry: float, knockout: float, current: float) -> float:
    if direction == "LONG":
        return (current - knockout) / (entry - knockout)
    return (knockout - current) / (knockout - entry)


def _fmt_price(p: float) -> str:
    if p >= 100:  return f"${p:.2f}"
    if p >= 1:    return f"${p:.3f}"
    return f"${p:.4f}"


def _fmt_pct(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def _yf_price_info(ticker: str) -> tuple:
    """Returns (last_price, day_open). Kept at module level for executor pickling."""
    try:
        import yfinance as yf
        fi    = yf.Ticker(ticker).fast_info
        last  = float(fi.last_price) if fi.last_price else None
        open_ = None
        for attr in ("open", "day_open", "regular_market_open"):
            v = getattr(fi, attr, None)
            if v:
                open_ = float(v)
                break
        return last, open_
    except Exception:
        return None, None


def _yf_history(ticker: str, period: str, interval: str):
    import yfinance as yf
    return yf.Ticker(ticker).history(period=period, interval=interval)


def _render_chart(
    ticker: str,
    opens: list, highs: list, lows: list, closes: list,
    chart_type: str,
    entry_price: float | None = None,
    knockout: float | None = None,
    direction: str | None = None,
    timestamps: list | None = None,
) -> bytes:
    # Drop NaN rows (yfinance sometimes returns them at period boundaries)
    clean = [
        (o, h, l, c, (timestamps[i] if timestamps else None))
        for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes))
        if not (math.isnan(float(c)) or math.isnan(float(o)) or math.isnan(float(h)) or math.isnan(float(l)))
    ]
    if clean:
        opens  = [r[0] for r in clean]
        highs  = [r[1] for r in clean]
        lows   = [r[2] for r in clean]
        closes = [r[3] for r in clean]
        timestamps = [r[4] for r in clean] if timestamps else None

    if ticker in ADR_STOCKS:
        bg_path = ADR_STOCKS[ticker]["bg"]
    elif ticker == ETF_TICKER:
        bg_path = ETF_INFO["bg"]
    else:
        bg_path = None

    fig = plt.figure(figsize=(8, 4), dpi=110, facecolor="none")

    ax_bg = fig.add_axes([0, 0, 1, 1], zorder=0)
    ax_bg.set_in_layout(False)
    ax_bg.axis("off")

    bg_loaded = False
    if bg_path:
        try:
            img = mpimg.imread(bg_path)
            ax_bg.imshow(img, aspect="auto", extent=[0, 1, 0, 1], transform=ax_bg.transAxes)
            ax_bg.add_patch(Rectangle((0, 0), 1, 1, transform=ax_bg.transAxes,
                                      color="black", alpha=0.80, zorder=1))
            bg_loaded = True
        except Exception:
            pass

    if not bg_loaded:
        ax_bg.set_facecolor("#0d0d12")
        ax_bg.add_patch(Rectangle((0, 0), 1, 1, transform=ax_bg.transAxes,
                                  color="#8B0000", alpha=0.18, zorder=1))

    ax = fig.add_axes([0.09, 0.17, 0.87, 0.75], zorder=2)
    ax.set_facecolor("none")
    ax.set_zorder(2)
    ax.margins(x=0.01, y=0.12)

    n  = len(closes)
    xs = list(range(n))

    if chart_type == "candlestick" and n > 0:
        for i in range(n):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            clr = "#26a69a" if c >= o else "#ef5350"
            ax.plot([i, i], [l, h], color=clr, linewidth=1.1, zorder=3)
            body = abs(c - o) or (h - l) * 0.01
            ax.bar(i, body, bottom=min(o, c), color=clr, width=0.65, zorder=4)
    elif n > 0:
        ax.plot(xs, closes, color="#26a69a", linewidth=2.2, zorder=3)
        ax.fill_between(xs, closes, min(closes) * 0.999,
                        alpha=0.28, color="#26a69a", zorder=2)

    if entry_price is not None and n > 0:
        ax.axhline(y=entry_price, color="#ffffff", linewidth=1.2,
                   linestyle="--", alpha=0.75, zorder=5)
        ax.text(0.01, entry_price, "Entry", transform=ax.get_yaxis_transform(),
                color="#ffffff", fontsize=7, va="bottom", alpha=0.85)

    if knockout is not None and n > 0:
        ax.axhline(y=knockout, color="#ff6b35", linewidth=1.4,
                   linestyle=":", alpha=0.90, zorder=5)
        ax.text(0.01, knockout, "KO", transform=ax.get_yaxis_transform(),
                color="#ff6b35", fontsize=7, va="bottom")

    if timestamps and n > 0:
        num_ticks = min(6, n)
        step      = max(1, n // num_ticks)
        positions = list(range(0, n, step))[:num_ticks]
        labels    = [timestamps[i] for i in positions]
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, color="#aaaaaa", fontsize=7.5, rotation=0)
        ax.tick_params(axis="x", length=0, pad=3)
    else:
        ax.set_xticks([])

    ax.tick_params(axis="y", colors="#dddddd", labelsize=9, length=0, pad=3)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="y", color="white", alpha=0.10, linewidth=0.5, linestyle="--")

    if closes:
        last  = closes[-1]
        first = closes[0]
        pct   = (last - first) / first * 100 if first > 0 else 0.0
        sign  = "+" if pct >= 0 else ""
        clr   = "#26a69a" if pct >= 0 else "#ef5350"
        ax.text(
            0.98, 0.96, f"{_fmt_price(last)}  {sign}{pct:.2f}%",
            transform=ax.transAxes, ha="right", va="top",
            color=clr, fontsize=10, fontweight="bold", zorder=10,
        )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, transparent=True)
    plt.close(fig)
    return buf.getvalue()


def _render_portfolio_chart(timeline: list) -> bytes:
    """Equity curve: [(label_str, total_value), ...] — Trade Republic style."""
    labels = [t[0] for t in timeline]
    values = [float(t[1]) for t in timeline]
    n      = len(values)

    fig   = plt.figure(figsize=(8, 4), dpi=110, facecolor="none")
    ax_bg = fig.add_axes([0, 0, 1, 1], zorder=0)
    ax_bg.set_in_layout(False)
    ax_bg.axis("off")
    ax_bg.set_facecolor("#0d0d12")

    ax = fig.add_axes([0.09, 0.17, 0.87, 0.75], zorder=2)
    ax.set_facecolor("none")
    ax.set_zorder(2)
    ax.margins(x=0.01, y=0.12)

    if n > 1:
        first, last = values[0], values[-1]
        up    = last >= first
        color = "#26a69a" if up else "#ef5350"
        xs    = list(range(n))
        ax.plot(xs, values, color=color, linewidth=2.2, zorder=3)
        ax.fill_between(xs, values, min(values) * 0.998, alpha=0.22, color=color, zorder=2)

        pct  = (last - first) / first * 100 if first > 0 else 0.0
        sign = "+" if pct >= 0 else ""
        ax.text(0.98, 0.96, f"¥{int(last):,}  {sign}{pct:.2f}%",
                transform=ax.transAxes, ha="right", va="top",
                color=color, fontsize=10, fontweight="bold", zorder=10)

        # start-of-day reference line
        ax.axhline(y=first, color="white", linewidth=0.8, linestyle="--", alpha=0.25, zorder=1)
    else:
        ax.text(0.5, 0.5, "Insufficient history", ha="center", va="center",
                color="#888888", fontsize=10, transform=ax.transAxes)

    # x-axis time labels
    if labels and n > 1:
        step      = max(1, n // 6)
        positions = list(range(0, n, step))[:6]
        ax.set_xticks(positions)
        ax.set_xticklabels([labels[i] for i in positions], color="#aaaaaa", fontsize=7.5)
        ax.tick_params(axis="x", length=0, pad=3)
    else:
        ax.set_xticks([])

    ax.tick_params(axis="y", colors="#dddddd", labelsize=9, length=0, pad=3)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="y", color="white", alpha=0.08, linewidth=0.5, linestyle="--")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, transparent=True)
    plt.close(fig)
    return buf.getvalue()


class StocksCog(commands.Cog, name="Stocks"):
    stocks = app_commands.Group(name="stocks", description="Beijing Stock Exchange · 北京证券交易所")
    turbos = app_commands.Group(name="turbos", description="Turbo certificate positions · 涡轮证书")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._prices: dict[str, float]         = {}
        self._day_opens: dict[str, float]       = {}
        self._halted: dict[str, float]          = {}
        self._daily_locked: set[str]            = set()
        self._pump_state: dict[str, dict]       = {}
        self._last_turbo_day: int               = 0
        self._chart_cache: dict[tuple, tuple]   = {}  # key → (png_bytes, timestamp)
        self._price_task.start()

    def cog_unload(self):
        self._price_task.cancel()

    def _make_bse_file(self) -> discord.File | None:
        try:
            return discord.File(_BSE_THUMB, filename="bse.png")
        except Exception:
            return None

    @tasks.loop(seconds=PRICE_UPDATE_INTERVAL)
    async def _price_task(self):
        try:
            await self._tick()
        except Exception as e:
            print(f"[stocks] tick error: {e}")

    @_price_task.before_loop
    async def _before_price_task(self):
        await self.bot.wait_until_ready()
        await self._initialize_prices()

    # ── Startup ───────────────────────────────────────────────────────────────

    async def _initialize_prices(self):
        rows = await self.bot.db.get_all_stocks()
        for row in rows:
            self._prices[row["ticker"]]    = float(row["price"])
            self._day_opens[row["ticker"]] = float(row["open_price"])

        loop = asyncio.get_running_loop()

        # Fetch all ADR prices in parallel
        results = await asyncio.gather(
            *[loop.run_in_executor(None, _yf_price_info, t) for t in ADR_TICKERS],
            return_exceptions=True,
        )
        price_updates = []
        for ticker, res in zip(ADR_TICKERS, results):
            if isinstance(res, Exception):
                continue
            price, yf_open = res
            if price and price > 0:
                self._prices[ticker] = price
                if yf_open and yf_open > 0:
                    self._day_opens[ticker] = yf_open
                elif self._day_opens.get(ticker, 0) <= 0:
                    self._day_opens[ticker] = price
                price_updates.append((ticker, price, self._day_opens[ticker]))

        if price_updates:
            await self.bot.db.batch_upsert_stock_prices(price_updates)

        if self._prices.get(ETF_TICKER, 0) <= 0:
            base = ETF_INFO["base_price"]
            self._prices[ETF_TICKER]    = base
            self._day_opens[ETF_TICKER] = base

        for t, cfg in PENNY_STOCKS.items():
            if self._prices.get(t, 0) <= 0:
                self._prices[t]    = cfg["base_price"]
                self._day_opens[t] = cfg["base_price"]

    # ── Tick ──────────────────────────────────────────────────────────────────

    async def _tick(self):
        now       = int(time.time())
        today_day = now // 86400
        loop      = asyncio.get_running_loop()

        if today_day != self._last_turbo_day:
            await self._reset_daily(today_day)
            self._last_turbo_day = today_day

        price_updates: list[tuple] = []   # (ticker, price, open_price)
        price_bars: list[tuple]    = []   # (ticker, ts, open, high, low, close)

        # Fetch all ADR prices in parallel
        adr_results = await asyncio.gather(
            *[loop.run_in_executor(None, _yf_price_info, t) for t in ADR_TICKERS],
            return_exceptions=True,
        )

        adr_pcts: dict[str, float] = {}
        for ticker, res in zip(ADR_TICKERS, adr_results):
            if ticker in self._daily_locked:
                continue
            if ticker in self._halted and now < self._halted[ticker]:
                continue

            old = self._prices.get(ticker, 0.0)
            if old <= 0:
                continue

            yf_price = None
            if not isinstance(res, Exception):
                yf_price, _ = res

            new_price = yf_price if (yf_price and yf_price > 0) else old
            if new_price == old:
                new_price = max(0.01, old * (1 + random.gauss(0, _ADR_CLOSED_VOL)))

            pct      = (new_price - old) / old
            day_open = self._day_opens.get(ticker, new_price)
            day_pct  = (new_price - day_open) / day_open if day_open > 0 else 0.0

            if abs(day_pct) >= CIRCUIT_BREAKER_DAILY_PCT:
                self._daily_locked.add(ticker)
            elif abs(pct) >= CIRCUIT_BREAKER_HALT_PCT:
                self._halted[ticker] = now + CIRCUIT_BREAKER_HALT_SECS
            else:
                self._prices[ticker] = new_price
                adr_pcts[ticker]     = pct
                price_updates.append((ticker, new_price, day_open))

        # ETF tracks ADR average
        if adr_pcts and ETF_TICKER not in self._daily_locked:
            avg_pct = sum(adr_pcts.values()) / len(adr_pcts)
            old_etf = self._prices.get(ETF_TICKER, ETF_INFO["base_price"])
            new_etf = max(0.01, old_etf * (1 + avg_pct))
            self._prices[ETF_TICKER] = new_etf
            etf_open = self._day_opens.get(ETF_TICKER, new_etf)
            price_updates.append((ETF_TICKER, new_etf, etf_open))
            price_bars.append((ETF_TICKER, now, old_etf,
                               max(old_etf, new_etf), min(old_etf, new_etf), new_etf))

        # Penny stock random walk
        updates_per_day = 86400 / PRICE_UPDATE_INTERVAL
        for ticker, cfg in PENNY_STOCKS.items():
            if ticker in self._daily_locked:
                continue
            if ticker in self._halted and now < self._halted[ticker]:
                continue

            old          = self._prices.get(ticker, cfg["base_price"])
            per_tick_vol = cfg["daily_vol"] / math.sqrt(updates_per_day)
            drift        = random.gauss(0, per_tick_vol)

            if ticker in self._pump_state:
                pump = self._pump_state[ticker]
                if now >= pump["started_at"] + PUMP_DURATION_SECS:
                    new_price = pump["peak_price"] * PUMP_CRASH_PCT
                    del self._pump_state[ticker]
                else:
                    drift    += PUMP_DRIFT_PER_TICK
                    new_price = max(0.001, old * (1 + drift))
                    self._pump_state[ticker]["peak_price"] = max(pump["peak_price"], new_price)
            else:
                if random.random() < PUMP_TRIGGER_PROB:
                    self._pump_state[ticker] = {"started_at": now, "peak_price": old}
                new_price = max(0.001, old * (1 + drift))

            day_open = self._day_opens.get(ticker, new_price)
            day_pct  = (new_price - day_open) / day_open if day_open > 0 else 0.0
            if abs(day_pct) >= CIRCUIT_BREAKER_DAILY_PCT:
                self._daily_locked.add(ticker)
            else:
                self._prices[ticker] = new_price
                price_updates.append((ticker, new_price, day_open))
                price_bars.append((ticker, now, old,
                                   max(old, new_price), min(old, new_price), new_price))

        # Single-round-trip DB writes for the whole tick
        await asyncio.gather(
            self.bot.db.batch_upsert_stock_prices(price_updates),
            self.bot.db.batch_add_price_bars(price_bars),
        )

        await self._check_knockouts()

    async def _reset_daily(self, today_day: int):
        for ticker in ALL_TICKERS:
            self._day_opens[ticker] = self._prices.get(ticker, 0.0)
        self._daily_locked.clear()
        self._halted.clear()
        self._chart_cache.clear()

        rng        = random.Random(today_day)
        candidates = [
            (t, d, lev)
            for t in ALL_TICKERS
            for d in ("LONG", "SHORT")
            for lev in TURBO_LEVERAGES
        ]
        selected   = rng.sample(candidates, min(TURBOS_PER_DAY, len(candidates)))
        turbo_list = []
        for ticker, direction, leverage in selected:
            entry = self._prices.get(ticker, 0.0)
            if entry <= 0:
                continue
            ko = entry * (1 - 1 / leverage) if direction == "LONG" else entry * (1 + 1 / leverage)
            turbo_list.append({
                "ticker": ticker, "direction": direction, "leverage": leverage,
                "entry_price": entry, "knockout": ko, "day": today_day,
            })
        await self.bot.db.replace_daily_turbos(today_day, turbo_list)

    async def _check_knockouts(self):
        positions = await self.bot.db.get_all_open_turbo_positions()
        knocked   = []
        for pos in positions:
            current = self._prices.get(pos["ticker"])
            if current is None:
                continue
            factor = _turbo_value_factor(pos["direction"], float(pos["entry_price"]),
                                         float(pos["knockout"]), current)
            if factor <= 0:
                knocked.append(pos)
        if knocked:
            await self.bot.db.batch_close_knocked_positions(knocked)

    # ── Portfolio timeline builder ────────────────────────────────────────────

    async def _build_portfolio_timeline(
        self, stock_positions: list, turbo_positions: list
    ) -> list[tuple[str, float]]:
        loop     = asyncio.get_running_loop()
        since_ts = int(time.time()) - 86400

        adr_tickers   = [p["ticker"] for p in stock_positions if p["ticker"] in ADR_TICKERS]
        other_tickers = [p["ticker"] for p in stock_positions if p["ticker"] not in ADR_TICKERS]

        # Fetch all price histories in parallel
        adr_dfs, db_rows_list = await asyncio.gather(
            asyncio.gather(*[
                loop.run_in_executor(None, _yf_history, t, "1d", "5m")
                for t in adr_tickers
            ]) if adr_tickers else asyncio.coroutine(lambda: [])(),
            asyncio.gather(*[
                self.bot.db.get_price_history(t, since_ts)
                for t in other_tickers
            ]) if other_tickers else asyncio.coroutine(lambda: [])(),
            return_exceptions=False,
        )

        # Build per-ticker price series: {ticker: [(unix_ts, price), ...]}
        series: dict[str, list[tuple[float, float]]] = {}

        for ticker, df in zip(adr_tickers, adr_dfs or []):
            if df is None or df.empty:
                continue
            pts = [
                (float(idx.timestamp()), float(c))
                for idx, c in zip(df.index, df["Close"])
                if not math.isnan(float(c))
            ]
            if pts:
                series[ticker] = pts

        for ticker, rows in zip(other_tickers, db_rows_list or []):
            if rows:
                series[ticker] = [(float(r["ts"]), float(r["close"])) for r in rows]

        if not series:
            return []

        # Use timestamps from the longest series as the reference grid
        base_ticker = max(series, key=lambda t: len(series[t]))
        base_pts    = series[base_ticker]

        def _price_at(pts: list[tuple[float, float]], target: float) -> float:
            return min(pts, key=lambda x: abs(x[0] - target))[1]

        shares_map = {p["ticker"]: float(p["shares"]) for p in stock_positions}

        timeline: list[tuple[str, float]] = []
        for ts, _ in base_pts:
            total = 0.0
            for ticker, shares in shares_map.items():
                pts   = series.get(ticker)
                price = _price_at(pts, ts) if pts else self._prices.get(ticker, 0.0)
                total += price * shares
            for tp in turbo_positions:
                t_ticker = tp["ticker"]
                pts      = series.get(t_ticker)
                cur_p    = _price_at(pts, ts) if pts else self._prices.get(t_ticker, float(tp["entry_price"]))
                factor   = max(0.0, _turbo_value_factor(
                    tp["direction"], float(tp["entry_price"]), float(tp["knockout"]), cur_p
                ))
                total += int(tp["cost"]) * factor
            label = datetime.datetime.utcfromtimestamp(ts).strftime("%H:%M")
            timeline.append((label, total))

        return timeline

    # ── Chart builder (with byte cache) ──────────────────────────────────────

    async def _build_chart(
        self, ticker: str, period: str, chart_type: str,
        entry_price: float | None = None,
        knockout: float | None = None,
        direction: str | None = None,
    ) -> io.BytesIO:
        cache_key = (ticker, period, chart_type, entry_price, knockout)
        now       = time.time()
        cached    = self._chart_cache.get(cache_key)
        if cached and (now - cached[1]) < _CHART_CACHE_TTL:
            return io.BytesIO(cached[0])
        if len(self._chart_cache) > 200:
            stale = [k for k, v in self._chart_cache.items() if (now - v[1]) >= _CHART_CACHE_TTL]
            for k in stale:
                del self._chart_cache[k]

        loop = asyncio.get_running_loop()
        ts_fmt = "%H:%M" if period == "1D" else ("%a %H:%M" if period == "5D" else ("%b %d" if period in ("1M", "3M") else "%b '%y"))

        if ticker in ADR_TICKERS:
            yf_period, yf_interval = _YF_PERIOD_MAP[period]
            df = await loop.run_in_executor(None, _yf_history, ticker, yf_period, yf_interval)
            if df is None or df.empty:
                raise ValueError("No data from yfinance")
            opens      = [float(v) for v in df["Open"]]
            highs      = [float(v) for v in df["High"]]
            lows       = [float(v) for v in df["Low"]]
            closes     = [float(v) for v in df["Close"]]
            try:
                timestamps = [t.strftime(ts_fmt) for t in df.index]
            except Exception:
                timestamps = None
        else:
            since = int(time.time()) - _PERIOD_SECONDS[period]
            rows  = await self.bot.db.get_price_history(ticker, since)
            if not rows:
                raise ValueError("No price history yet for this period.")
            opens      = [float(r["open"])  for r in rows]
            highs      = [float(r["high"])  for r in rows]
            lows       = [float(r["low"])   for r in rows]
            closes     = [float(r["close"]) for r in rows]
            timestamps = [datetime.datetime.utcfromtimestamp(int(r["ts"])).strftime(ts_fmt) for r in rows]

        png = await loop.run_in_executor(
            None, _render_chart, ticker, opens, highs, lows, closes,
            chart_type, entry_price, knockout, direction, timestamps,
        )
        self._chart_cache[cache_key] = (png, now)
        return io.BytesIO(png)

    # ── Autocomplete ──────────────────────────────────────────────────────────

    async def _ticker_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        cu      = current.upper()
        choices = []
        for ticker in ALL_TICKERS:
            name = _ticker_info_name(ticker)
            if cu and cu not in ticker and cu.lower() not in name.lower():
                continue
            price    = self._prices.get(ticker, 0.0)
            day_open = self._day_opens.get(ticker, price)
            pct      = (price - day_open) / day_open * 100 if day_open > 0 else 0.0
            sign     = "+" if pct >= 0 else ""
            label    = f"{ticker} · {name} · {_fmt_price(price)} ({sign}{pct:.1f}%)"
            choices.append(app_commands.Choice(name=label[:100], value=ticker))
        return choices[:25]

    # ── /stocks commands ──────────────────────────────────────────────────────

    @app_commands.command(name="market", description="Live prices, market status and trading hours · 北京证券交易所")
    async def market_overview(self, interaction: discord.Interaction):
        await interaction.response.defer()
        now_ts = int(time.time())

        event, next_ts, today_open_ts = _next_market_event()
        is_open   = _is_market_hours()
        status    = "🟢 Open" if is_open else "🔴 Closed"
        event_lbl = "Closes" if event == "close" else "Opens"
        midnight  = datetime.datetime(
            datetime.datetime.utcnow().year,
            datetime.datetime.utcnow().month,
            datetime.datetime.utcnow().day,
            tzinfo=datetime.timezone.utc,
        )
        close_ts = int((midnight + datetime.timedelta(hours=21)).timestamp())

        embed = discord.Embed(
            title="北京证券交易所 · Beijing Stock Exchange",
            description=(
                f"{status} · {event_lbl} <t:{next_ts}:R>\n"
                f"Hours: <t:{today_open_ts}:t> – <t:{close_ts}:t> · Mon–Fri · NYSE hours"
            ),
            color=0x26A69A if is_open else 0xCC0000,
        )

        adr_lines = []
        for ticker, info in ADR_STOCKS.items():
            price    = self._prices.get(ticker, 0.0)
            day_open = self._day_opens.get(ticker, price)
            pct      = (price - day_open) / day_open * 100 if day_open > 0 else 0.0
            arrow    = "▲" if pct >= 0 else "▼"
            status_tag = ""
            if ticker in self._daily_locked:
                status_tag = " ⏸"
            elif ticker in self._halted and now_ts < self._halted[ticker]:
                status_tag = " ⏳"
            adr_lines.append(
                f"`{ticker}` **{info['name_zh']}**  {_fmt_price(price)}  {arrow} {_fmt_pct(pct)}"
                f"  · open {_fmt_price(day_open)}{status_tag}"
            )

        etf_price = self._prices.get(ETF_TICKER, ETF_INFO["base_price"])
        etf_open  = self._day_opens.get(ETF_TICKER, etf_price)
        etf_pct   = (etf_price - etf_open) / etf_open * 100 if etf_open > 0 else 0.0
        etf_arrow = "▲" if etf_pct >= 0 else "▼"

        penny_lines = []
        for ticker, info in PENNY_STOCKS.items():
            price    = self._prices.get(ticker, info["base_price"])
            day_open = self._day_opens.get(ticker, price)
            pct      = (price - day_open) / day_open * 100 if day_open > 0 else 0.0
            arrow    = "▲" if pct >= 0 else "▼"
            vol_pct  = int(info["daily_vol"] * 100)
            tag      = " 🔥 **PUMP**" if ticker in self._pump_state else (
                       " ⏸" if ticker in self._daily_locked else f"  · vol ~{vol_pct}%/day")
            penny_lines.append(
                f"`{ticker}` **{info['name_zh']}**  {_fmt_price(price)}  {arrow} {_fmt_pct(pct)}{tag}"
            )

        embed.add_field(name="China ADRs · Real-time", value="\n".join(adr_lines), inline=False)
        embed.add_field(
            name=f"ETF · {ETF_TICKER} · {ETF_INFO['name_zh']}",
            value=f"{_fmt_price(etf_price)}  {etf_arrow} {_fmt_pct(etf_pct)}  · open {_fmt_price(etf_open)}  · tracks ADR basket",
            inline=False,
        )
        embed.add_field(name="Penny Stocks · Simulated", value="\n".join(penny_lines), inline=False)
        embed.set_footer(text=f"Prices update every {PRICE_UPDATE_INTERVAL}s · /stocks chart <ticker> for graphs")

        bse = self._make_bse_file()
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        await interaction.followup.send(embed=embed, **({"file": bse} if bse else {}))

    @stocks.command(name="chart", description="View a price chart for any stock")
    @app_commands.describe(ticker="Ticker symbol", period="Time period", chart_type="Chart style")
    @app_commands.choices(
        period=[app_commands.Choice(name=p, value=p) for p in PERIODS],
        chart_type=[app_commands.Choice(name=c, value=c) for c in CHART_TYPES],
    )
    async def stocks_chart(
        self,
        interaction: discord.Interaction,
        ticker: str,
        period: str = "1D",
        chart_type: str = "line",
    ):
        await interaction.response.defer()
        ticker = ticker.upper()
        if ticker not in ALL_TICKERS:
            return await interaction.followup.send(
                f"Unknown ticker. Available: {', '.join(ALL_TICKERS)}", ephemeral=True
            )

        try:
            buf = await self._build_chart(ticker, period, chart_type)
        except Exception as e:
            return await interaction.followup.send(f"Chart unavailable: {e}", ephemeral=True)

        price    = self._prices.get(ticker, 0.0)
        day_open = self._day_opens.get(ticker, price)
        pct      = (price - day_open) / day_open * 100 if day_open > 0 else 0.0
        color    = 0x26A69A if pct >= 0 else 0xEF5350

        info  = (ADR_STOCKS.get(ticker) or (ETF_INFO if ticker == ETF_TICKER else None)
                 or PENNY_STOCKS.get(ticker) or {})
        embed = discord.Embed(title=f"{info.get('name_zh', ticker)} · {ticker}", color=color)
        embed.add_field(name="Price",      value=_fmt_price(price), inline=True)
        embed.add_field(name="Day Change", value=_fmt_pct(pct),     inline=True)
        embed.add_field(name="Period",     value=period,            inline=True)

        now = int(time.time())
        if ticker in self._pump_state:
            embed.add_field(name="Status", value="🔥 PUMP EVENT · Price surging", inline=False)
        elif ticker in self._daily_locked:
            embed.add_field(name="Status", value="⏸ Circuit breaker · daily limit hit", inline=False)
        elif ticker in self._halted and now < self._halted[ticker]:
            embed.add_field(name="Status", value="⏳ Temporarily halted", inline=False)

        embed.set_image(url="attachment://chart.png")
        bse = self._make_bse_file()
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        chart_file = discord.File(buf, filename="chart.png")
        await interaction.followup.send(embed=embed, files=([bse, chart_file] if bse else [chart_file]))

    @stocks_chart.autocomplete("ticker")
    async def _chart_ticker_ac(self, interaction: discord.Interaction, current: str):
        return await self._ticker_autocomplete(interaction, current)

    @stocks.command(name="buy", description="Buy shares of a stock")
    @app_commands.describe(ticker="Stock ticker", shares="Number of shares (decimals OK)")
    async def stocks_buy(self, interaction: discord.Interaction, ticker: str, shares: float):
        await interaction.response.defer(ephemeral=True)
        ticker = ticker.upper()
        if ticker not in ALL_TICKERS:
            return await interaction.followup.send("Unknown ticker.", ephemeral=True)
        if shares <= 0:
            return await interaction.followup.send("Shares must be positive.", ephemeral=True)

        now = int(time.time())
        if ticker in self._daily_locked:
            return await interaction.followup.send("Trading is suspended for this stock today.", ephemeral=True)
        if ticker in self._halted and now < self._halted[ticker]:
            return await interaction.followup.send("This stock is temporarily halted.", ephemeral=True)

        price = self._prices.get(ticker, 0.0)
        if price <= 0:
            return await interaction.followup.send("Price data unavailable.", ephemeral=True)

        total = int(math.ceil(price * shares))
        if total < 1:
            return await interaction.followup.send("Order too small.", ephemeral=True)

        ok = await self.bot.db.buy_stock(interaction.guild_id, interaction.user.id, ticker, shares, price, total)
        if not ok:
            return await interaction.followup.send(f"Insufficient yuan. Cost: ¥{total:,}", ephemeral=True)

        embed = discord.Embed(title="订单确认 · Order Confirmed", color=0x26A69A)
        embed.add_field(name="Bought", value=f"{shares:g} × {ticker}", inline=True)
        embed.add_field(name="Price",  value=_fmt_price(price),        inline=True)
        embed.add_field(name="Total",  value=f"¥{total:,}",            inline=True)
        bse = self._make_bse_file()
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        await interaction.followup.send(embed=embed, **({"file": bse} if bse else {}))

    @stocks_buy.autocomplete("ticker")
    async def _buy_ticker_ac(self, interaction: discord.Interaction, current: str):
        return await self._ticker_autocomplete(interaction, current)

    @stocks.command(name="sell", description="Sell shares of a stock")
    @app_commands.describe(ticker="Stock ticker", shares="Shares to sell")
    async def stocks_sell(self, interaction: discord.Interaction, ticker: str, shares: float):
        await interaction.response.defer(ephemeral=True)
        ticker = ticker.upper()
        if ticker not in ALL_TICKERS:
            return await interaction.followup.send("Unknown ticker.", ephemeral=True)
        if shares <= 0:
            return await interaction.followup.send("Shares must be positive.", ephemeral=True)

        price = self._prices.get(ticker, 0.0)
        if price <= 0:
            return await interaction.followup.send("Price data unavailable.", ephemeral=True)

        result = await self.bot.db.sell_stock(interaction.guild_id, interaction.user.id, ticker, shares, price)
        if result is None:
            return await interaction.followup.send("Insufficient shares in your portfolio.", ephemeral=True)

        proceeds = result["proceeds"]
        pnl      = result["pnl"]
        sign     = "+" if pnl >= 0 else ""
        color    = 0x26A69A if pnl >= 0 else 0xEF5350

        embed = discord.Embed(title="出售确认 · Sale Confirmed", color=color)
        embed.add_field(name="Sold",     value=f"{shares:g} × {ticker}",  inline=True)
        embed.add_field(name="Price",    value=_fmt_price(price),          inline=True)
        embed.add_field(name="Proceeds", value=f"¥{proceeds:,}",           inline=True)
        embed.add_field(name="P&L",      value=f"{sign}¥{abs(pnl):,}",    inline=True)
        bse = self._make_bse_file()
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        await interaction.followup.send(embed=embed, **({"file": bse} if bse else {}))

    @stocks_sell.autocomplete("ticker")
    async def _sell_ticker_ac(self, interaction: discord.Interaction, current: str):
        return await self._ticker_autocomplete(interaction, current)

    @stocks.command(name="portfolio", description="View your investment portfolio")
    async def stocks_portfolio(self, interaction: discord.Interaction):
        await interaction.response.defer()

        positions = await self.bot.db.get_portfolio(interaction.guild_id, interaction.user.id)
        tp_rows   = await self.bot.db.get_open_turbo_positions(interaction.guild_id, interaction.user.id)
        user_row  = await self.bot.db.get_user(interaction.guild_id, interaction.user.id)

        if not positions and not tp_rows:
            return await interaction.followup.send("You have no open positions.", ephemeral=True)

        total_value = 0.0
        unrealized  = 0
        stock_lines = []

        for pos in positions:
            ticker = pos["ticker"]
            shares = float(pos["shares"])
            avg    = float(pos["avg_cost"])
            price  = self._prices.get(ticker, 0.0)
            value  = price * shares
            pnl    = int((price - avg) * shares)
            sign   = "+" if pnl >= 0 else ""
            pct    = (price - avg) / avg * 100 if avg > 0 else 0.0
            total_value += value
            unrealized  += pnl
            stock_lines.append(
                f"`{ticker:<4}` {shares:g} sh · {_fmt_price(price)} · "
                f"¥{int(value):,} ({sign}¥{abs(pnl):,} / {_fmt_pct(pct)})"
            )

        turbo_lines = []
        for pos in tp_rows:
            t_ticker  = pos["ticker"]
            direction = pos["direction"]
            leverage  = pos["leverage"]
            entry     = float(pos["entry_price"])
            knockout  = float(pos["knockout"])
            cost      = int(pos["cost"])
            current   = self._prices.get(t_ticker, entry)
            factor    = _turbo_value_factor(direction, entry, knockout, current)
            value     = max(0, int(cost * factor))
            pnl       = value - cost
            sign      = "+" if pnl >= 0 else ""
            total_value += value
            unrealized  += pnl
            sym = "🟢" if direction == "LONG" else "🔴"
            turbo_lines.append(
                f"{sym} **#{pos['position_id']}** {direction} {leverage}x `{t_ticker}` "
                f"· ¥{value:,} ({sign}¥{abs(pnl):,})"
            )

        realized   = (user_row.get("stock_profit", 0) or 0) + (user_row.get("turbo_profit", 0) or 0)
        unr_sign   = "+" if unrealized >= 0 else ""
        unr_color  = "🟢" if unrealized >= 0 else "🔴"
        real_sign  = "+" if realized  >= 0 else ""
        real_color = "🟢" if realized  >= 0 else "🔴"

        # Build equity curve timeline and render (in parallel with embed construction)
        timeline = await self._build_portfolio_timeline(positions, tp_rows)
        loop     = asyncio.get_running_loop()
        port_png = await loop.run_in_executor(None, _render_portfolio_chart, timeline)

        embed_color = 0x26A69A if unrealized >= 0 else 0xEF5350
        display_name = await self.bot.format_user_full(interaction.user, interaction.guild_id)
        embed = discord.Embed(title=f"{display_name}'s Portfolio", color=embed_color)
        if stock_lines:
            embed.add_field(name="Stocks", value="\n".join(stock_lines), inline=False)
        if turbo_lines:
            embed.add_field(name="Turbo Certificates", value="\n".join(turbo_lines), inline=False)
        embed.add_field(name="Total Value",    value=f"¥{int(total_value):,}",                       inline=True)
        embed.add_field(name="Unrealized P&L", value=f"{unr_color} {unr_sign}¥{abs(unrealized):,}", inline=True)
        embed.add_field(name="Realized P&L",   value=f"{real_color} {real_sign}¥{abs(realized):,}", inline=True)

        bse = self._make_bse_file()
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        embed.set_image(url="attachment://portfolio.png")

        files = []
        if bse:
            files.append(bse)
        files.append(discord.File(io.BytesIO(port_png), filename="portfolio.png"))
        await interaction.followup.send(embed=embed, files=files)

    # ── /turbos commands ──────────────────────────────────────────────────────

    @turbos.command(name="list", description="View today's available turbo certificates")
    async def turbos_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        today = int(time.time()) // 86400
        rows  = await self.bot.db.get_daily_turbos(today)
        if not rows:
            return await interaction.followup.send(
                "No turbos generated yet today. Try again in a moment.", ephemeral=True
            )

        long_rows  = [t for t in rows if t["direction"] == "LONG"]
        short_rows = [t for t in rows if t["direction"] == "SHORT"]

        def _fmt_row(t):
            price   = self._prices.get(t["ticker"], float(t["entry_price"]))
            factor  = max(0.0, _turbo_value_factor(
                t["direction"], float(t["entry_price"]), float(t["knockout"]), price
            ))
            ko_dist = abs(price - float(t["knockout"])) / price * 100 if price > 0 else 0.0
            return (
                f"`#{t['id']}` **{t['ticker']}** {t['leverage']}x\n"
                f"KO {_fmt_price(float(t['knockout']))} · {ko_dist:.1f}% away · factor {factor:.3f}"
            )

        def _chunked_fields(name: str, turbo_rows: list, embed: discord.Embed):
            chunk, chunk_len = [], 0
            part = 1
            for t in turbo_rows:
                line = _fmt_row(t)
                sep = 2 if chunk else 0
                if chunk and chunk_len + sep + len(line) > 1020:
                    label = name if part == 1 else f"{name} (cont.)"
                    embed.add_field(name=label, value="\n\n".join(chunk), inline=False)
                    chunk, chunk_len, part = [], 0, part + 1
                chunk.append(line)
                chunk_len += sep + len(line)
            if chunk:
                label = name if part == 1 else f"{name} (cont.)"
                embed.add_field(name=label, value="\n\n".join(chunk), inline=False)

        embed = discord.Embed(title="涡轮证书 · Daily Turbos", color=0xCC0000)
        if long_rows:
            _chunked_fields("LONG", long_rows, embed)
        if short_rows:
            _chunked_fields("SHORT", short_rows, embed)
        embed.set_footer(text=f"Min ¥{TURBO_MIN_COST:,} · /turbos open <id> <yuan> · /turbos chart <id>")

        bse = self._make_bse_file()
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        await interaction.followup.send(embed=embed, ephemeral=True, **({"file": bse} if bse else {}))

    @turbos.command(name="chart", description="Chart the underlying stock with entry and knockout levels")
    @app_commands.describe(turbo_id="Turbo ID from /turbos list", period="Time period")
    @app_commands.choices(period=[app_commands.Choice(name=p, value=p) for p in PERIODS])
    async def turbos_chart(
        self,
        interaction: discord.Interaction,
        turbo_id: int,
        period: str = "1D",
    ):
        await interaction.response.defer()
        today = int(time.time()) // 86400
        turbo = await self.bot.db.get_turbo(turbo_id)
        if not turbo or int(turbo["day"]) != today:
            return await interaction.followup.send("Turbo not found or expired.", ephemeral=True)

        ticker    = turbo["ticker"]
        direction = turbo["direction"]
        entry     = float(turbo["entry_price"])
        knockout  = float(turbo["knockout"])
        leverage  = turbo["leverage"]
        price     = self._prices.get(ticker, entry)
        factor    = max(0.0, _turbo_value_factor(direction, entry, knockout, price))
        ko_dist   = abs(price - knockout) / price * 100 if price > 0 else 0.0
        color     = 0x26A69A if direction == "LONG" else 0xEF5350

        try:
            buf = await self._build_chart(ticker, period, "line",
                                          entry_price=entry, knockout=knockout, direction=direction)
        except Exception as e:
            return await interaction.followup.send(f"Chart unavailable: {e}", ephemeral=True)

        sym   = "🟢" if direction == "LONG" else "🔴"
        embed = discord.Embed(
            title=f"{sym} Turbo #{turbo_id} · {direction} {leverage}x {ticker}",
            description=_ticker_info_name(ticker),
            color=color,
        )
        embed.add_field(name="Current",     value=_fmt_price(price),    inline=True)
        embed.add_field(name="Entry",       value=_fmt_price(entry),    inline=True)
        embed.add_field(name="Knockout",    value=_fmt_price(knockout), inline=True)
        embed.add_field(name="KO Distance", value=f"{ko_dist:.1f}%",   inline=True)
        embed.add_field(name="Factor",      value=f"{factor:.4f}",      inline=True)
        embed.add_field(name="Period",      value=period,               inline=True)
        embed.set_image(url="attachment://chart.png")

        bse = self._make_bse_file()
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        chart_file = discord.File(buf, filename="chart.png")
        await interaction.followup.send(embed=embed, files=([bse, chart_file] if bse else [chart_file]))

    @turbos.command(name="open", description="Open a turbo certificate position")
    @app_commands.describe(turbo_id="Turbo ID from /turbos list", cost="Yuan to invest")
    async def turbos_open(self, interaction: discord.Interaction, turbo_id: int, cost: int):
        await interaction.response.defer(ephemeral=True)
        if cost < TURBO_MIN_COST:
            return await interaction.followup.send(f"Minimum investment: ¥{TURBO_MIN_COST:,}", ephemeral=True)

        today = int(time.time()) // 86400
        turbo = await self.bot.db.get_turbo(turbo_id)
        if not turbo or int(turbo["day"]) != today:
            return await interaction.followup.send("Turbo not found or expired.", ephemeral=True)

        ticker = turbo["ticker"]
        if ticker in self._daily_locked:
            return await interaction.followup.send("Underlying stock is locked today.", ephemeral=True)

        ok = await self.bot.db.open_turbo_position(interaction.guild_id, interaction.user.id, turbo_id, cost)
        if not ok:
            return await interaction.followup.send(f"Insufficient yuan. Need ¥{cost:,}", ephemeral=True)

        entry    = float(turbo["entry_price"])
        knockout = float(turbo["knockout"])
        price    = self._prices.get(ticker, entry)
        factor   = max(0.0, _turbo_value_factor(turbo["direction"], entry, knockout, price))
        color    = 0x26A69A if turbo["direction"] == "LONG" else 0xEF5350
        ko_dist  = abs(price - knockout) / price * 100 if price > 0 else 0.0

        embed = discord.Embed(title="持仓开立 · Position Opened", color=color)
        embed.add_field(name="Certificate",   value=f"#{turbo_id} {turbo['direction']} {turbo['leverage']}x {ticker}", inline=False)
        embed.add_field(name="Entry Price",   value=_fmt_price(entry),          inline=True)
        embed.add_field(name="Knockout",      value=_fmt_price(knockout),       inline=True)
        embed.add_field(name="KO Distance",   value=f"{ko_dist:.1f}%",          inline=True)
        embed.add_field(name="Invested",      value=f"¥{cost:,}",               inline=True)
        embed.add_field(name="Current Value", value=f"¥{int(cost * factor):,}", inline=True)
        bse = self._make_bse_file()
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        await interaction.followup.send(embed=embed, **({"file": bse} if bse else {}))

    @turbos.command(name="close", description="Close an open turbo position")
    @app_commands.describe(position_id="Position ID from /stocks portfolio")
    async def turbos_close(self, interaction: discord.Interaction, position_id: int):
        await interaction.response.defer(ephemeral=True)

        row = await self.bot.db.get_turbo_position(interaction.guild_id, interaction.user.id, position_id)
        if not row or row["status"] != "open":
            return await interaction.followup.send("Position not found or already closed.", ephemeral=True)

        turbo = await self.bot.db.get_turbo(int(row["turbo_id"]))
        if not turbo:
            return await interaction.followup.send("Associated turbo data missing.", ephemeral=True)

        entry    = float(turbo["entry_price"])
        knockout = float(turbo["knockout"])
        current  = self._prices.get(turbo["ticker"], entry)
        factor   = _turbo_value_factor(turbo["direction"], entry, knockout, current)
        proceeds = max(0, int(int(row["cost"]) * factor))
        pnl      = proceeds - int(row["cost"])

        await self.bot.db.close_turbo_position(position_id, pnl, "closed")
        await self.bot.db.add_yuan(interaction.guild_id, interaction.user.id, proceeds)
        await self.bot.db.update_turbo_stats(interaction.guild_id, interaction.user.id, knocked=False, pnl=pnl)

        sign  = "+" if pnl >= 0 else ""
        color = 0x26A69A if pnl >= 0 else 0xEF5350
        embed = discord.Embed(title="持仓平仓 · Position Closed", color=color)
        embed.add_field(name="Proceeds", value=f"¥{proceeds:,}",        inline=True)
        embed.add_field(name="P&L",      value=f"{sign}¥{abs(pnl):,}", inline=True)
        bse = self._make_bse_file()
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        await interaction.followup.send(embed=embed, **({"file": bse} if bse else {}))


async def setup(bot: commands.Bot):
    await bot.add_cog(StocksCog(bot))
