import io
import math
import random
import time
import asyncio
import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.achievements import unlock as unlock_achievement, check_milestone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.patches import Rectangle

from config.stocks import (
    ADR_STOCKS, ETF_TICKER, ETF_INFO, PENNY_STOCKS,
    ADR_TICKERS, ALL_TICKERS,
    LSE_STOCKS, TSE_STOCKS, LSE_TICKERS, TSE_TICKERS,
    REAL_STOCKS, REAL_TICKERS,
    FX_TICKERS, FX_FALLBACK_RATES, FX_REFRESH_INTERVAL,
    TURBO_LEVERAGES, TURBOS_PER_DAY, TURBO_MIN_COST,
    PRICE_UPDATE_INTERVAL,
    CIRCUIT_BREAKER_HALT_PCT, CIRCUIT_BREAKER_HALT_SECS, CIRCUIT_BREAKER_DAILY_PCT,
    PUMP_TRIGGER_PROB, PUMP_DURATION_SECS, PUMP_DRIFT_PER_TICK, PUMP_CRASH_PCT,
    _YF_PERIOD_MAP, _PERIOD_SECONDS,
)
from config.market_hours import (
    EXCHANGE_TZ, EXCHANGE_NAMES,
    is_market_hours,
    next_market_event,
    market_closed_message,
    last_market_open_ts,
    all_exchange_status,
)

_is_market_hours       = is_market_hours
_next_market_event     = next_market_event
_market_closed_message = market_closed_message
_last_market_open_ts    = last_market_open_ts

_NYSE_TZ        = ZoneInfo("America/New_York")  # DST-aware NYSE local time
PERIODS         = ["1D", "5D", "1M", "3M", "6M", "1Y"]
CHART_TYPES     = ["candlestick", "line"]
_BSE_THUMB      = "images/beijingStockExchange.png"
_PORTFOLIO_PERIODS = {
    "1D":  ("1d",  "5m",  86400),
    "7D":  ("7d",  "1h",  7 * 86400),
    "1M":  ("1mo", "1d",  30 * 86400),
    "6M":  ("6mo", "1d",  180 * 86400),
    "1Y":  ("1y",  "1d",  365 * 86400),
}
_CHART_CACHE_TTL = 45       # seconds before a cached chart is considered stale


def _ticker_info_name(ticker: str) -> str:
    if ticker in REAL_STOCKS:  return REAL_STOCKS[ticker]["name"]
    if ticker == ETF_TICKER:   return ETF_INFO["name"]
    return PENNY_STOCKS.get(ticker, {}).get("name", ticker)


def _turbo_value_factor(direction: str, entry: float, knockout: float, current: float) -> float:
    if direction == "LONG":
        return (current - knockout) / (entry - knockout)
    return (knockout - current) / (knockout - entry)


def _fmt_price(p: float) -> str:
    if p >= 100:  return f"¥{p:.2f}"
    if p >= 1:    return f"¥{p:.3f}"
    return f"¥{p:.4f}"


def _exchange_for(ticker: str) -> str:
    info = REAL_STOCKS.get(ticker)
    return info["exchange"] if info else "NYSE"


def _fmt_pct(pct: float) -> str:
    sign = "+" if pct >= 0 else "-"
    return f"{sign}{abs(pct):.2f}%"


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
    baseline: float | None = None,
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

    if ticker in REAL_STOCKS:
        bg_path = REAL_STOCKS[ticker]["bg"]
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

    ax = fig.add_axes([0.07, 0.13, 0.90, 0.82], zorder=2)
    ax.set_facecolor("none")
    ax.set_zorder(2)
    ax.margins(x=0, y=0.08)

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
        ax.fill_between(xs, closes, min(closes) * 0.998,
                        alpha=0.28, color="#26a69a", zorder=2)

    if entry_price is not None and n > 0:
        ax.axhline(y=entry_price, color="#ffffff", linewidth=1.2,
                   linestyle="--", alpha=0.75, zorder=5)
        ax.text(0.01, entry_price, "Entry", transform=ax.get_yaxis_transform(),
                color="#ffffff", fontsize=7, va="bottom", alpha=0.85)
    elif baseline is not None and baseline > 0 and n > 0:
        # Day-open reference line — same treatment as the portfolio chart's
        # baseline line, only shown when there's no entry/KO line to clash with.
        ax.axhline(y=baseline, color="#ffffff", linewidth=0.8,
                   linestyle="--", alpha=0.25, zorder=1)
        ax.text(0.01, baseline, "Open", transform=ax.get_yaxis_transform(),
                color="#aaaaaa", fontsize=7, va="bottom", alpha=0.7)

    if knockout is not None and n > 0:
        ax.axhline(y=knockout, color="#ff6b35", linewidth=1.4,
                   linestyle=":", alpha=0.90, zorder=5)
        ax.text(0.01, knockout, "KO", transform=ax.get_yaxis_transform(),
                color="#ff6b35", fontsize=7, va="bottom")

    if timestamps and n > 0:
        num_ticks = min(6, n)
        positions = [round(i * (n - 1) / (num_ticks - 1)) for i in range(num_ticks)] if num_ticks > 1 else [0]
        labels    = [timestamps[i] for i in positions]
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, color="#aaaaaa", fontsize=7.5, rotation=0, ha="center")
        ax.get_xticklabels()[-1].set_ha("right")
        ax.tick_params(axis="x", length=0, pad=3)
    else:
        ax.set_xticks([])

    ax.tick_params(axis="y", colors="#dddddd", labelsize=9, length=0, pad=3)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="y", color="white", alpha=0.10, linewidth=0.5, linestyle="--")

    if closes:
        last  = closes[-1]
        first = baseline if baseline is not None and baseline > 0 else closes[0]
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


def _render_portfolio_chart(timeline: list, cost_basis: float = 0.0) -> bytes:
    """Equity curve: [(label_str, total_value), ...] — Trade Republic style."""
    labels = [t[0] for t in timeline]
    values = [float(t[1]) for t in timeline]
    n      = len(values)

    fig   = plt.figure(figsize=(8, 4), dpi=110, facecolor="none")
    ax_bg = fig.add_axes([0, 0, 1, 1], zorder=0)
    ax_bg.set_in_layout(False)
    ax_bg.axis("off")
    ax_bg.set_facecolor("#0d0d12")

    ax = fig.add_axes([0.07, 0.13, 0.90, 0.82], zorder=2)
    ax.set_facecolor("none")
    ax.set_zorder(2)
    ax.margins(x=0, y=0.08)

    if n > 1:
        last      = values[-1]
        baseline  = cost_basis if cost_basis > 0 else values[0]
        up        = last >= baseline
        color     = "#26a69a" if up else "#ef5350"
        xs        = list(range(n))
        ax.plot(xs, values, color=color, linewidth=2.2, zorder=3)
        ax.fill_between(xs, values, min(values) * 0.998, alpha=0.22, color=color, zorder=2)

        pct  = (last - baseline) / baseline * 100 if baseline > 0 else 0.0
        sign = "+" if pct >= 0 else ""
        ax.text(0.98, 0.96, f"¥{int(last):,}  {sign}{pct:.2f}%",
                transform=ax.transAxes, ha="right", va="top",
                color=color, fontsize=10, fontweight="bold", zorder=10)

        ax.axhline(y=baseline, color="white", linewidth=0.8, linestyle="--", alpha=0.25, zorder=1)
    else:
        ax.text(0.5, 0.5, "Insufficient history", ha="center", va="center",
                color="#888888", fontsize=10, transform=ax.transAxes)

    # x-axis time labels — always pin last tick to final data point
    if labels and n > 1:
        num_ticks = min(6, n)
        positions = [round(i * (n - 1) / (num_ticks - 1)) for i in range(num_ticks)] if num_ticks > 1 else [0]
        ax.set_xticks(positions)
        ax.set_xticklabels([labels[i] for i in positions], color="#aaaaaa", fontsize=7.5, ha="center")
        ax.get_xticklabels()[-1].set_ha("right")
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


class PortfolioPeriodView(discord.ui.View):
    def __init__(self, cog, guild_id, user_id, cost_basis, embed, bse_bytes):
        super().__init__(timeout=300)
        self._cog        = cog
        self._guild_id   = guild_id
        self._user_id    = user_id
        self._cost_basis = cost_basis
        self._embed      = embed
        self._bse_bytes  = bse_bytes
        for label in _PORTFOLIO_PERIODS:
            btn          = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(label)
            self.add_item(btn)

    def _make_cb(self, period_label: str):
        async def callback(itr: discord.Interaction):
            await itr.response.defer()
            _, _, secs = _PORTFOLIO_PERIODS[period_label]
            since_ts = int(time.time()) - secs
            timeline = await self._cog._build_portfolio_timeline(
                self._guild_id, self._user_id, since_ts,
            )
            loop     = asyncio.get_running_loop()
            port_png = await loop.run_in_executor(
                None, _render_portfolio_chart, timeline, self._cost_basis,
            )
            new_attachments = []
            if self._bse_bytes:
                new_attachments.append(discord.File(io.BytesIO(self._bse_bytes), filename="bse.png"))
            new_attachments.append(discord.File(io.BytesIO(port_png), filename="portfolio.png"))
            await itr.edit_original_response(embed=self._embed, attachments=new_attachments, view=self)
        return callback


class StockChartView(discord.ui.View):
    """Period-switcher buttons for /stocks chart — mirrors PortfolioPeriodView."""

    def __init__(self, cog, ticker: str, chart_type: str, embed: discord.Embed, bse_bytes: bytes | None):
        super().__init__(timeout=300)
        self._cog        = cog
        self._ticker     = ticker
        self._chart_type = chart_type
        self._embed      = embed
        self._bse_bytes  = bse_bytes
        for label in PERIODS:
            btn          = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(label)
            self.add_item(btn)

    def _make_cb(self, period: str):
        async def callback(itr: discord.Interaction):
            await itr.response.defer()
            try:
                buf = await self._cog._build_chart(self._ticker, period, self._chart_type)
            except Exception as e:
                await itr.followup.send(f"Chart unavailable: {e}", ephemeral=True)
                return
            new_attachments = []
            if self._bse_bytes:
                new_attachments.append(discord.File(io.BytesIO(self._bse_bytes), filename="bse.png"))
            new_attachments.append(discord.File(buf, filename="chart.png"))
            await itr.edit_original_response(embed=self._embed, attachments=new_attachments, view=self)
        return callback


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
        self._chart_cache: dict[tuple, tuple]   = {}  # key -> (png_bytes, timestamp)
        self._fx_rates: dict[str, float]        = dict(FX_FALLBACK_RATES)
        self._fx_last_refresh: float            = 0.0
        self._price_task.start()

    def cog_unload(self):
        self._price_task.cancel()

    def _make_bse_file(self) -> discord.File | None:
        try:
            return discord.File(_BSE_THUMB, filename="bse.png")
        except Exception:
            return None

    async def _refresh_fx_rates(self, force: bool = False):
        now = time.time()
        if not force and now - self._fx_last_refresh < FX_REFRESH_INTERVAL:
            return
        loop = asyncio.get_running_loop()
        results = await asyncio.gather(
            *[loop.run_in_executor(None, _yf_price_info, sym) for sym in FX_TICKERS.values()],
            return_exceptions=True,
        )
        for currency, res in zip(FX_TICKERS.keys(), results):
            if isinstance(res, Exception):
                continue
            price, _ = res
            if price and price > 0:
                self._fx_rates[currency] = price
        self._fx_last_refresh = now

    def _to_yuan(self, ticker: str, native_price: float) -> float:
        info = REAL_STOCKS.get(ticker)
        if not info:
            return native_price
        currency = info["currency"]
        rate = self._fx_rates.get(
            "GBP" if currency == "GBX" else currency,
            FX_FALLBACK_RATES.get("GBP" if currency == "GBX" else currency, 1.0),
        )
        if currency == "GBX":
            return (native_price / 100.0) * rate
        return native_price * rate

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

        await self._refresh_fx_rates(force=True)

        results = await asyncio.gather(
            *[loop.run_in_executor(None, _yf_price_info, t) for t in REAL_TICKERS],
            return_exceptions=True,
        )
        price_updates = []
        for ticker, res in zip(REAL_TICKERS, results):
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

        await self._refresh_fx_rates()

        price_updates: list[tuple] = []   # (ticker, price, open_price)
        price_bars: list[tuple]    = []   # (ticker, ts, open, high, low, close)

        open_exchanges = {ex: is_market_hours(ex) for ex in EXCHANGE_TZ}

        active_tickers = [
            t for t in REAL_TICKERS
            if open_exchanges[REAL_STOCKS[t]["exchange"]]
            and t not in self._daily_locked
            and not (t in self._halted and now < self._halted[t])
        ]

        fetched: dict = {}
        if active_tickers:
            fetch_results = await asyncio.gather(
                *[loop.run_in_executor(None, _yf_price_info, t) for t in active_tickers],
                return_exceptions=True,
            )
            fetched = dict(zip(active_tickers, fetch_results))

        real_pcts: dict[str, float] = {}
        for ticker in REAL_TICKERS:
            old = self._prices.get(ticker, 0.0)
            if old <= 0:
                continue

            exchange = REAL_STOCKS[ticker]["exchange"]
            if not open_exchanges[exchange] or ticker in self._daily_locked or (
                ticker in self._halted and now < self._halted[ticker]
            ):
                price_bars.append((ticker, now, old, old, old, old))
                continue

            res = fetched.get(ticker)
            yf_price = None
            if res is not None and not isinstance(res, Exception):
                yf_price, _ = res

            new_price = yf_price if (yf_price and yf_price > 0) else old

            pct      = (new_price - old) / old
            day_open = self._day_opens.get(ticker, new_price)
            day_pct  = (new_price - day_open) / day_open if day_open > 0 else 0.0

            if abs(day_pct) >= CIRCUIT_BREAKER_DAILY_PCT:
                self._daily_locked.add(ticker)
                price_bars.append((ticker, now, old, old, old, old))
            elif abs(pct) >= CIRCUIT_BREAKER_HALT_PCT:
                self._halted[ticker] = now + CIRCUIT_BREAKER_HALT_SECS
                asyncio.create_task(self._grant_held_through_halt(ticker))
                price_bars.append((ticker, now, old, old, old, old))
            else:
                self._prices[ticker] = new_price
                real_pcts[ticker]    = pct
                price_updates.append((ticker, new_price, day_open))
                price_bars.append((ticker, now, old,
                                   max(old, new_price), min(old, new_price), new_price))

        nyse_open = open_exchanges["NYSE"]
        old_etf   = self._prices.get(ETF_TICKER, ETF_INFO["base_price"])
        if not nyse_open or ETF_TICKER in self._daily_locked:
            price_bars.append((ETF_TICKER, now, old_etf, old_etf, old_etf, old_etf))
        elif real_pcts:
            avg_pct = sum(real_pcts.values()) / len(real_pcts)
            new_etf = max(0.01, old_etf * (1 + avg_pct))
            self._prices[ETF_TICKER] = new_etf
            etf_open = self._day_opens.get(ETF_TICKER, new_etf)
            price_updates.append((ETF_TICKER, new_etf, etf_open))
            price_bars.append((ETF_TICKER, now, old_etf,
                               max(old_etf, new_etf), min(old_etf, new_etf), new_etf))
        else:
            price_bars.append((ETF_TICKER, now, old_etf, old_etf, old_etf, old_etf))

        updates_per_day = 86400 / PRICE_UPDATE_INTERVAL
        for ticker, cfg in PENNY_STOCKS.items():
            old = self._prices.get(ticker, cfg["base_price"])
            if not nyse_open or ticker in self._daily_locked or (
                ticker in self._halted and now < self._halted[ticker]
            ):
                price_bars.append((ticker, now, old, old, old, old))
                continue

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
                price_bars.append((ticker, now, old, old, old, old))
            else:
                self._prices[ticker] = new_price
                price_updates.append((ticker, new_price, day_open))
                price_bars.append((ticker, now, old,
                                   max(old, new_price), min(old, new_price), new_price))

        all_stock_positions = await self.bot.db.get_all_portfolios()
        all_turbo_positions = await self.bot.db.get_all_open_turbo_positions()

        user_values: dict[tuple[int, int], float] = {}
        for p in all_stock_positions:
            key   = (int(p["guild_id"]), int(p["user_id"]))
            yuan_price = self._to_yuan(p["ticker"], self._prices.get(p["ticker"], 0.0))
            user_values[key] = user_values.get(key, 0.0) + yuan_price * float(p["shares"])
        for tp in all_turbo_positions:
            key     = (int(tp["guild_id"]), int(tp["user_id"]))
            current = self._prices.get(tp["ticker"], float(tp["entry_price"]))
            factor  = max(0.0, _turbo_value_factor(
                tp["direction"], float(tp["entry_price"]), float(tp["knockout"]), current
            ))
            user_values[key] = user_values.get(key, 0.0) + int(tp["cost"]) * factor

        history_records = [
            (gid, uid, now, int(val))
            for (gid, uid), val in user_values.items()
            if val > 0
        ]

        await asyncio.gather(
            self.bot.db.batch_upsert_stock_prices(price_updates),
            self.bot.db.batch_add_price_bars(price_bars),
            self.bot.db.batch_insert_portfolio_history(history_records),
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

    async def _grant_held_through_halt(self, ticker: str):
        portfolios = await self.bot.db.get_all_portfolios()
        for row in portfolios:
            if row["ticker"] != ticker or float(row["shares"]) <= 0:
                continue
            guild = self.bot.get_guild(row["guild_id"])
            member = guild.get_member(row["user_id"]) if guild else None
            if member:
                await unlock_achievement(self.bot, guild, member, "held_through_halt")

    async def _check_realized_profit(self, guild, user):
        row = await self.bot.db.get_user(guild.id, user.id)
        if not row:
            return
        realized = (row.get("stock_profit", 0) or 0) + (row.get("turbo_profit", 0) or 0)
        if realized >= 50_000:
            await unlock_achievement(self.bot, guild, user, "realized_50k_profit")

    async def _track_exchange_trade(self, guild, user, exchange: str):
        streak, _ = await self.bot.db.bump_daily_streak(user.id, "stock_invest_streak")
        await check_milestone(self.bot, guild, user, "stock_invest_streak", streak)

        bit = {"NYSE": 1, "LSE": 2, "TSE": 4}.get(exchange, 0)
        if not bit:
            return
        combined = await self.bot.db.mark_exchange_traded(guild.id, user.id, bit)
        if combined == 7:
            await unlock_achievement(self.bot, guild, user, "global_trader")

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
            for pos in knocked:
                guild = self.bot.get_guild(pos["guild_id"])
                member = guild.get_member(pos["user_id"]) if guild else None
                if member:
                    await unlock_achievement(self.bot, guild, member, "knocked_out")

    # ── Portfolio timeline builder ────────────────────────────────────────────

    async def _build_portfolio_timeline(
        self, guild_id: int, user_id: int, since_ts: int | None = None,
    ) -> list[tuple[str, float]]:
        now = int(time.time())
        if since_ts is None:
            since_ts = now - 86400
        rows = await self.bot.db.get_portfolio_history(guild_id, user_id, since_ts)
        if not rows:
            return []
        label_fmt = "%H:%M" if since_ts > now - 2 * 86400 else "%b %d"
        return [
            (datetime.datetime.fromtimestamp(r["ts"], tz=_NYSE_TZ).strftime(label_fmt), float(r["value"]))
            for r in rows
        ]

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

        day_open = self._day_opens.get(ticker)
        exchange = _exchange_for(ticker)

        if ticker in REAL_TICKERS:
            yf_period, yf_interval = _YF_PERIOD_MAP[period]
            df = await loop.run_in_executor(None, _yf_history, ticker, yf_period, yf_interval)
            if df is None or df.empty:
                raise ValueError("No data from yfinance")
            if period == "1D":
                open_ts = _last_market_open_ts(exchange)
                df = df[df.index.astype("int64") // 10**9 >= open_ts]
                if df.empty:
                    raise ValueError("No price history yet for this period.")
            opens      = [self._to_yuan(ticker, float(v)) for v in df["Open"]]
            highs      = [self._to_yuan(ticker, float(v)) for v in df["High"]]
            lows       = [self._to_yuan(ticker, float(v)) for v in df["Low"]]
            closes     = [self._to_yuan(ticker, float(v)) for v in df["Close"]]
            try:
                timestamps = [t.strftime(ts_fmt) for t in df.index]
            except Exception:
                timestamps = None
        else:
            since = _last_market_open_ts(exchange) if period == "1D" else int(time.time()) - _PERIOD_SECONDS[period]
            rows  = await self.bot.db.get_price_history(ticker, since)
            if not rows:
                raise ValueError("No price history yet for this period.")
            opens      = [float(r["open"])  for r in rows]
            highs      = [float(r["high"])  for r in rows]
            lows       = [float(r["low"])   for r in rows]
            closes     = [float(r["close"]) for r in rows]
            timestamps = [datetime.datetime.fromtimestamp(int(r["ts"]), tz=_NYSE_TZ).strftime(ts_fmt) for r in rows]

        if ticker in REAL_TICKERS and day_open is not None:
            day_open = self._to_yuan(ticker, day_open)

        # Only use the official day-open as the chart's baseline when the chart
        # is actually showing the since-open window; longer periods should still
        # compare against their own first plotted point.
        baseline = day_open if period == "1D" else None

        png = await loop.run_in_executor(
            None, _render_chart, ticker, opens, highs, lows, closes,
            chart_type, entry_price, knockout, direction, timestamps, baseline,
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
            yuan_price = self._to_yuan(ticker, price)
            label    = f"{ticker} · {name} · {_fmt_price(yuan_price)} ({sign}{pct:.1f}%)"
            choices.append(app_commands.Choice(name=label[:100], value=ticker))
        return choices[:25]

    # ── /stocks commands ──────────────────────────────────────────────────────

    @app_commands.command(name="market", description="Live prices, market status and trading hours · 北京证券交易所")
    async def market_overview(self, interaction: discord.Interaction):
        await interaction.response.defer()
        now_ts = int(time.time())

        exchange_status = all_exchange_status()
        lines = []
        for exchange, st in exchange_status.items():
            tag      = "🟢 Open" if st["open"] else "🔴 Closed"
            event_lbl = "Closes" if st["next_event"] == "close" else "Opens"
            lines.append(f"**{EXCHANGE_NAMES[exchange]}** ({exchange})  {tag} · {event_lbl} <t:{st['next_ts']}:R>")
        any_open = any(st["open"] for st in exchange_status.values())

        embed = discord.Embed(
            title="北京证券交易所 · Beijing Stock Exchange",
            description="\n".join(lines),
            color=0x26A69A if any_open else 0xCC0000,
        )

        def _group_lines(stocks_dict: dict) -> list[str]:
            out = []
            for ticker, info in stocks_dict.items():
                native    = self._prices.get(ticker, 0.0)
                day_open  = self._day_opens.get(ticker, native)
                pct       = (native - day_open) / day_open * 100 if day_open > 0 else 0.0
                arrow     = "▲" if pct >= 0 else "▼"
                price     = self._to_yuan(ticker, native)
                open_yuan = self._to_yuan(ticker, day_open)
                status_tag = ""
                if not exchange_status[info["exchange"]]["open"]:
                    status_tag = " 🔴"
                elif ticker in self._daily_locked:
                    status_tag = " ⏸"
                elif ticker in self._halted and now_ts < self._halted[ticker]:
                    status_tag = " ⏳"
                out.append(
                    f"`{ticker}` **{info['name_zh']}**  {_fmt_price(price)}  {arrow} {_fmt_pct(pct)}"
                    f"  · open {_fmt_price(open_yuan)}{status_tag}"
                )
            return out

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

        embed.add_field(name="New York · China ADRs", value="\n".join(_group_lines(ADR_STOCKS)), inline=False)
        embed.add_field(name="London Stock Exchange", value="\n".join(_group_lines(LSE_STOCKS)), inline=False)
        embed.add_field(name="Tokyo Stock Exchange", value="\n".join(_group_lines(TSE_STOCKS)), inline=False)
        embed.add_field(
            name=f"ETF · {ETF_TICKER} · {ETF_INFO['name_zh']}",
            value=f"{_fmt_price(etf_price)}  {etf_arrow} {_fmt_pct(etf_pct)}  · open {_fmt_price(etf_open)}  · tracks the 11-ticker basket",
            inline=False,
        )
        embed.add_field(name="Penny Stocks · Simulated", value="\n".join(penny_lines), inline=False)
        embed.set_footer(text=f"Prices update every {PRICE_UPDATE_INTERVAL}s · /stocks chart <ticker> for graphs")

        bse = self._make_bse_file()
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        await interaction.followup.send(embed=embed, **({"file": bse} if bse else {}))

    @stocks.command(name="chart", description="View a price chart for any stock")
    @app_commands.describe(ticker="Ticker symbol", chart_type="Chart style")
    @app_commands.choices(
        chart_type=[app_commands.Choice(name=c, value=c) for c in CHART_TYPES],
    )
    async def stocks_chart(
        self,
        interaction: discord.Interaction,
        ticker: str,
        chart_type: str = "line",
    ):
        await interaction.response.defer()
        ticker = ticker.upper()
        if ticker not in ALL_TICKERS:
            return await interaction.followup.send(
                f"Unknown ticker. Available: {', '.join(ALL_TICKERS)}", ephemeral=True
            )

        try:
            buf = await self._build_chart(ticker, "1D", chart_type)
        except Exception as e:
            return await interaction.followup.send(f"Chart unavailable: {e}", ephemeral=True)

        native   = self._prices.get(ticker, 0.0)
        day_open = self._day_opens.get(ticker, native)
        pct      = (native - day_open) / day_open * 100 if day_open > 0 else 0.0
        color    = 0x26A69A if pct >= 0 else 0xEF5350
        price    = self._to_yuan(ticker, native)

        info  = (REAL_STOCKS.get(ticker) or (ETF_INFO if ticker == ETF_TICKER else None)
                 or PENNY_STOCKS.get(ticker) or {})
        embed = discord.Embed(title=f"{info.get('name_zh', ticker)} · {ticker}", color=color)
        embed.add_field(name="Price",      value=_fmt_price(price), inline=True)
        embed.add_field(name="Day Change", value=_fmt_pct(pct),     inline=True)
        if ticker in REAL_STOCKS:
            embed.add_field(name="Exchange", value=EXCHANGE_NAMES[REAL_STOCKS[ticker]["exchange"]], inline=True)

        now = int(time.time())
        if ticker in self._pump_state:
            embed.add_field(name="Status", value="🔥 PUMP EVENT · Price surging", inline=False)
        elif ticker in self._daily_locked:
            embed.add_field(name="Status", value="⏸ Circuit breaker · daily limit hit", inline=False)
        elif ticker in self._halted and now < self._halted[ticker]:
            embed.add_field(name="Status", value="⏳ Temporarily halted", inline=False)

        embed.set_image(url="attachment://chart.png")
        bse_bytes = None
        try:
            with open(_BSE_THUMB, "rb") as f:
                bse_bytes = f.read()
        except Exception:
            pass
        bse = discord.File(io.BytesIO(bse_bytes), filename="bse.png") if bse_bytes else None
        if bse:
            embed.set_thumbnail(url="attachment://bse.png")
        chart_file = discord.File(buf, filename="chart.png")
        view = StockChartView(self, ticker, chart_type, embed, bse_bytes)
        await interaction.followup.send(
            embed=embed,
            files=([bse, chart_file] if bse else [chart_file]),
            view=view,
        )

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
        exchange = _exchange_for(ticker)
        if not is_market_hours(exchange):
            return await interaction.followup.send(market_closed_message(exchange), ephemeral=True)
        if shares <= 0:
            return await interaction.followup.send("Shares must be positive.", ephemeral=True)

        now = int(time.time())
        if ticker in self._daily_locked:
            return await interaction.followup.send("Trading is suspended for this stock today.", ephemeral=True)
        if ticker in self._halted and now < self._halted[ticker]:
            return await interaction.followup.send("This stock is temporarily halted.", ephemeral=True)

        native = self._prices.get(ticker, 0.0)
        if native <= 0:
            return await interaction.followup.send("Price data unavailable.", ephemeral=True)
        price = self._to_yuan(ticker, native)

        total = int(math.ceil(price * shares))
        if total < 1:
            return await interaction.followup.send("Order too small.", ephemeral=True)

        ok = await self.bot.db.buy_stock(interaction.guild_id, interaction.user.id, ticker, shares, price, total)
        if not ok:
            return await interaction.followup.send(f"Insufficient yuan. Cost: ¥{total:,}", ephemeral=True)

        await unlock_achievement(self.bot, interaction.guild, interaction.user, "first_trade")
        await self._track_exchange_trade(interaction.guild, interaction.user, exchange)

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
        exchange = _exchange_for(ticker)
        if not is_market_hours(exchange):
            return await interaction.followup.send(market_closed_message(exchange), ephemeral=True)
        if shares <= 0:
            return await interaction.followup.send("Shares must be positive.", ephemeral=True)

        native = self._prices.get(ticker, 0.0)
        if native <= 0:
            return await interaction.followup.send("Price data unavailable.", ephemeral=True)
        price = self._to_yuan(ticker, native)

        result = await self.bot.db.sell_stock(interaction.guild_id, interaction.user.id, ticker, shares, price)
        if result is None:
            return await interaction.followup.send("Insufficient shares in your portfolio.", ephemeral=True)

        proceeds = result["proceeds"]
        pnl      = result["pnl"]
        sign     = "+" if pnl >= 0 else ""
        color    = 0x26A69A if pnl >= 0 else 0xEF5350

        await unlock_achievement(self.bot, interaction.guild, interaction.user, "first_trade")
        await self._check_realized_profit(interaction.guild, interaction.user)
        await self._track_exchange_trade(interaction.guild, interaction.user, exchange)

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
            price  = self._to_yuan(ticker, self._prices.get(ticker, 0.0))
            value  = price * shares
            pnl    = int((price - avg) * shares)
            sign   = "+" if pnl >= 0 else "-"
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
            sign      = "+" if pnl >= 0 else "-"
            total_value += value
            unrealized  += pnl
            sym = "🟢" if direction == "LONG" else "🔴"
            turbo_lines.append(
                f"{sym} **#{pos['position_id']}** {direction} {leverage}x `{t_ticker}` "
                f"· ¥{value:,} ({sign}¥{abs(pnl):,})"
            )

        realized   = (user_row.get("stock_profit", 0) or 0) + (user_row.get("turbo_profit", 0) or 0)
        unr_sign   = "+" if unrealized >= 0 else "-"
        unr_color  = "🟢" if unrealized >= 0 else "🔴"
        real_sign  = "+" if realized  >= 0 else "-"
        real_color = "🟢" if realized  >= 0 else "🔴"

        cost_basis = (
            sum(float(p["avg_cost"]) * float(p["shares"]) for p in positions) +
            sum(float(tp["cost"]) for tp in tp_rows)
        )

        # Build equity curve timeline and render
        timeline = await self._build_portfolio_timeline(interaction.guild_id, interaction.user.id)
        now_label = datetime.datetime.now(_NYSE_TZ).strftime("%H:%M")
        if timeline:
            timeline.append((now_label, total_value))
        loop     = asyncio.get_running_loop()
        port_png = await loop.run_in_executor(
            None, _render_portfolio_chart, timeline, cost_basis
        )

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

        bse_bytes = None
        try:
            with open(_BSE_THUMB, "rb") as f:
                bse_bytes = f.read()
        except Exception:
            pass

        if bse_bytes:
            embed.set_thumbnail(url="attachment://bse.png")
        embed.set_image(url="attachment://portfolio.png")

        view  = PortfolioPeriodView(self, interaction.guild_id, interaction.user.id, cost_basis, embed, bse_bytes)
        files = []
        if bse_bytes:
            files.append(discord.File(io.BytesIO(bse_bytes), filename="bse.png"))
        files.append(discord.File(io.BytesIO(port_png), filename="portfolio.png"))
        await interaction.followup.send(embed=embed, files=files, view=view)

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

        tickers = sorted(set(t["ticker"] for t in rows))
        prices  = self._prices

        def _build_embed(ticker: str) -> discord.Embed:
            ticker_rows = [t for t in rows if t["ticker"] == ticker]
            embed = discord.Embed(title=f"涡轮证书 · {ticker}", color=0xCC0000)
            for direction in ("LONG", "SHORT"):
                dir_rows = [t for t in ticker_rows if t["direction"] == direction]
                if not dir_rows:
                    continue
                lines = []
                for t in dir_rows:
                    price   = prices.get(ticker, float(t["entry_price"]))
                    factor  = max(0.0, _turbo_value_factor(direction, float(t["entry_price"]), float(t["knockout"]), price))
                    ko_dist = abs(price - float(t["knockout"])) / price * 100 if price > 0 else 0.0
                    ko_yuan = self._to_yuan(ticker, float(t["knockout"]))
                    lines.append(
                        f"`#{t['id']}` {t['leverage']}x · KO {_fmt_price(ko_yuan)} · {ko_dist:.1f}% away · factor {factor:.3f}"
                    )
                embed.add_field(name=direction, value="\n".join(lines), inline=True)
            embed.set_footer(text=f"Min ¥{TURBO_MIN_COST:,} · /turbos open <id> <yuan> · /turbos chart <id>")
            return embed

        class TickerSelect(discord.ui.View):
            def __init__(self_v):
                super().__init__(timeout=180)
                opts = [discord.SelectOption(label=t, value=t) for t in tickers]
                sel  = discord.ui.Select(placeholder="Select a stock…", options=opts)
                sel.callback = self_v._on_select
                self_v.add_item(sel)
                self_v._sel = sel

            async def _on_select(self_v, itr: discord.Interaction):
                ticker = self_v._sel.values[0]
                await itr.response.edit_message(embed=_build_embed(ticker), view=self_v)

        view  = TickerSelect()
        await interaction.followup.send(embed=_build_embed(tickers[0]), view=view, ephemeral=True)

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
                                          entry_price=self._to_yuan(ticker, entry),
                                          knockout=self._to_yuan(ticker, knockout),
                                          direction=direction)
        except Exception as e:
            return await interaction.followup.send(f"Chart unavailable: {e}", ephemeral=True)

        sym   = "🟢" if direction == "LONG" else "🔴"
        embed = discord.Embed(
            title=f"{sym} Turbo #{turbo_id} · {direction} {leverage}x {ticker}",
            description=_ticker_info_name(ticker),
            color=color,
        )
        embed.add_field(name="Current",     value=_fmt_price(self._to_yuan(ticker, price)),    inline=True)
        embed.add_field(name="Entry",       value=_fmt_price(self._to_yuan(ticker, entry)),    inline=True)
        embed.add_field(name="Knockout",    value=_fmt_price(self._to_yuan(ticker, knockout)), inline=True)
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

        ticker   = turbo["ticker"]
        exchange = _exchange_for(ticker)
        if not is_market_hours(exchange):
            return await interaction.followup.send(market_closed_message(exchange), ephemeral=True)
        if ticker in self._daily_locked:
            return await interaction.followup.send("Underlying stock is locked today.", ephemeral=True)

        ok = await self.bot.db.open_turbo_position(interaction.guild_id, interaction.user.id, turbo_id, cost)
        if not ok:
            return await interaction.followup.send(f"Insufficient yuan. Need ¥{cost:,}", ephemeral=True)

        await unlock_achievement(self.bot, interaction.guild, interaction.user, "first_turbo")
        await self._track_exchange_trade(interaction.guild, interaction.user, exchange)

        entry    = float(turbo["entry_price"])
        knockout = float(turbo["knockout"])
        price    = self._prices.get(ticker, entry)
        factor   = max(0.0, _turbo_value_factor(turbo["direction"], entry, knockout, price))
        color    = 0x26A69A if turbo["direction"] == "LONG" else 0xEF5350
        ko_dist  = abs(price - knockout) / price * 100 if price > 0 else 0.0

        embed = discord.Embed(title="持仓开立 · Position Opened", color=color)
        embed.add_field(name="Certificate",   value=f"#{turbo_id} {turbo['direction']} {turbo['leverage']}x {ticker}", inline=False)
        embed.add_field(name="Entry Price",   value=_fmt_price(self._to_yuan(ticker, entry)),    inline=True)
        embed.add_field(name="Knockout",      value=_fmt_price(self._to_yuan(ticker, knockout)), inline=True)
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

        exchange = _exchange_for(turbo["ticker"])
        if not is_market_hours(exchange):
            return await interaction.followup.send(market_closed_message(exchange), ephemeral=True)

        entry    = float(turbo["entry_price"])
        knockout = float(turbo["knockout"])
        current  = self._prices.get(turbo["ticker"], entry)
        factor   = _turbo_value_factor(turbo["direction"], entry, knockout, current)
        proceeds = max(0, int(int(row["cost"]) * factor))
        pnl      = proceeds - int(row["cost"])

        await self.bot.db.close_turbo_position(position_id, pnl, "closed")
        await self.bot.db.add_yuan(interaction.guild_id, interaction.user.id, proceeds)
        await self.bot.db.update_turbo_stats(interaction.guild_id, interaction.user.id, knocked=False, pnl=pnl)
        await self._check_realized_profit(interaction.guild, interaction.user)

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