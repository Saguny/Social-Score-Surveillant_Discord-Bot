import io
import math
import random
import time
import asyncio

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

PERIODS     = ["1D", "5D", "1M", "3M", "6M", "1Y"]
CHART_TYPES = ["candlestick", "line"]


def _turbo_value_factor(direction: str, entry: float, knockout: float, current: float) -> float:
    if direction == "LONG":
        return (current - knockout) / (entry - knockout)
    return (knockout - current) / (knockout - entry)


def _fmt_price(p: float) -> str:
    if p >= 100:
        return f"${p:.2f}"
    if p >= 1:
        return f"${p:.3f}"
    return f"${p:.4f}"


def _fmt_pct(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def _yf_last_price(ticker: str) -> float | None:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        p = info.last_price
        return float(p) if p else None
    except Exception:
        return None


def _yf_history(ticker: str, period: str, interval: str):
    import yfinance as yf
    return yf.Ticker(ticker).history(period=period, interval=interval)


def _render_chart(ticker: str, opens: list, highs: list, lows: list, closes: list, chart_type: str) -> io.BytesIO:
    if ticker in ADR_STOCKS:
        bg_path = ADR_STOCKS[ticker]["bg"]
    elif ticker == ETF_TICKER:
        bg_path = ETF_INFO["bg"]
    else:
        bg_path = "images/stocks/Pennystocks.png"

    fig = plt.figure(figsize=(8, 4), dpi=100, facecolor="none")

    ax_bg = fig.add_axes([0, 0, 1, 1], zorder=0)
    ax_bg.set_in_layout(False)
    ax_bg.axis("off")
    try:
        img = mpimg.imread(bg_path)
        ax_bg.imshow(img, aspect="auto", extent=[0, 1, 0, 1], transform=ax_bg.transAxes)
    except Exception:
        ax_bg.set_facecolor("#111111")
    ax_bg.add_patch(Rectangle((0, 0), 1, 1, transform=ax_bg.transAxes, color="black", alpha=0.82, zorder=1))

    ax = fig.add_axes([0.08, 0.12, 0.88, 0.78], zorder=2)
    ax.set_facecolor("none")
    ax.set_zorder(2)
    ax.margins(x=0.01)

    n  = len(closes)
    xs = list(range(n))

    if chart_type == "candlestick" and n > 0:
        for i in range(n):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            clr = "#26a69a" if c >= o else "#ef5350"
            ax.plot([i, i], [l, h], color=clr, linewidth=0.8, zorder=3)
            body = abs(c - o) or (h - l) * 0.002
            ax.bar(i, body, bottom=min(o, c), color=clr, width=0.7, zorder=3)
    elif n > 0:
        ax.plot(xs, closes, color="#26a69a", linewidth=1.5, zorder=3)
        ax.fill_between(xs, closes, min(closes) * 0.999, alpha=0.15, color="#26a69a", zorder=2)

    ax.set_xticks([])
    ax.tick_params(axis="y", colors="white", labelsize=8, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="y", color="white", alpha=0.1, linewidth=0.5)

    if closes:
        last  = closes[-1]
        first = closes[0]
        pct   = (last - first) / first * 100 if first > 0 else 0.0
        sign  = "+" if pct >= 0 else ""
        ax.text(
            0.98, 0.96, f"{_fmt_price(last)}  {sign}{pct:.2f}%",
            transform=ax.transAxes, ha="right", va="top",
            color="white", fontsize=10, fontweight="bold", zorder=10,
        )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, transparent=True)
    plt.close(fig)
    buf.seek(0)
    return buf


class StocksCog(commands.Cog, name="Stocks"):
    stocks = app_commands.Group(name="stocks", description="Beijing Stock Exchange · 北京证券交易所")
    turbos = app_commands.Group(name="turbos", description="Turbo certificate positions · 涡轮证书")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._prices: dict[str, float]    = {}
        self._day_opens: dict[str, float] = {}
        self._halted: dict[str, float]    = {}
        self._daily_locked: set[str]      = set()
        self._pump_state: dict[str, dict] = {}
        self._last_turbo_day: int         = 0
        self._price_task.start()

    def cog_unload(self):
        self._price_task.cancel()

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

    async def _initialize_prices(self):
        rows = await self.bot.db.get_all_stocks()
        for row in rows:
            self._prices[row["ticker"]]    = float(row["price"])
            self._day_opens[row["ticker"]] = float(row["open_price"])

        loop = asyncio.get_running_loop()
        for ticker in ADR_TICKERS:
            try:
                price = await loop.run_in_executor(None, _yf_last_price, ticker)
                if price and price > 0:
                    self._prices[ticker] = price
                    if self._day_opens.get(ticker, 0) <= 0:
                        self._day_opens[ticker] = price
                    await self.bot.db.upsert_stock_price(ticker, price, self._day_opens[ticker])
            except Exception:
                pass

        if self._prices.get(ETF_TICKER, 0) <= 0:
            base = ETF_INFO["base_price"]
            self._prices[ETF_TICKER]    = base
            self._day_opens[ETF_TICKER] = base

        for t, cfg in PENNY_STOCKS.items():
            if self._prices.get(t, 0) <= 0:
                self._prices[t]    = cfg["base_price"]
                self._day_opens[t] = cfg["base_price"]

    async def _tick(self):
        now       = int(time.time())
        today_day = now // 86400
        loop      = asyncio.get_running_loop()

        if today_day != self._last_turbo_day:
            await self._reset_daily(today_day)
            self._last_turbo_day = today_day

        adr_pcts: dict[str, float] = {}
        for ticker in ADR_TICKERS:
            if ticker in self._daily_locked:
                continue
            if ticker in self._halted and now < self._halted[ticker]:
                continue
            try:
                price = await loop.run_in_executor(None, _yf_last_price, ticker)
                if price and price > 0:
                    old      = self._prices.get(ticker, price)
                    pct      = (price - old) / old if old > 0 else 0.0
                    day_open = self._day_opens.get(ticker, price)
                    day_pct  = (price - day_open) / day_open if day_open > 0 else 0.0
                    if abs(day_pct) >= CIRCUIT_BREAKER_DAILY_PCT:
                        self._daily_locked.add(ticker)
                    elif abs(pct) >= CIRCUIT_BREAKER_HALT_PCT:
                        self._halted[ticker] = now + CIRCUIT_BREAKER_HALT_SECS
                    else:
                        self._prices[ticker] = price
                        adr_pcts[ticker] = pct
                        await self.bot.db.upsert_stock_price(ticker, price, day_open)
            except Exception:
                pass

        if adr_pcts and ETF_TICKER not in self._daily_locked:
            avg_pct = sum(adr_pcts.values()) / len(adr_pcts)
            old_etf = self._prices.get(ETF_TICKER, ETF_INFO["base_price"])
            new_etf = max(0.01, old_etf * (1 + avg_pct))
            self._prices[ETF_TICKER] = new_etf
            etf_open = self._day_opens.get(ETF_TICKER, new_etf)
            asyncio.create_task(
                self.bot.db.add_price_bar(ETF_TICKER, now, old_etf, max(old_etf, new_etf), min(old_etf, new_etf), new_etf)
            )
            await self.bot.db.upsert_stock_price(ETF_TICKER, new_etf, etf_open)

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
                asyncio.create_task(
                    self.bot.db.add_price_bar(ticker, now, old, max(old, new_price), min(old, new_price), new_price)
                )
                await self.bot.db.upsert_stock_price(ticker, new_price, day_open)

        await self._check_knockouts()

    async def _reset_daily(self, today_day: int):
        for ticker in ALL_TICKERS:
            self._day_opens[ticker] = self._prices.get(ticker, 0.0)
        self._daily_locked.clear()
        self._halted.clear()

        rng = random.Random(today_day)
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
        for pos in positions:
            ticker  = pos["ticker"]
            current = self._prices.get(ticker)
            if current is None:
                continue
            factor = _turbo_value_factor(pos["direction"], float(pos["entry_price"]), float(pos["knockout"]), current)
            if factor <= 0:
                cost = int(pos["cost"])
                await self.bot.db.close_turbo_position(int(pos["position_id"]), -cost, "knocked")
                await self.bot.db.update_turbo_stats(int(pos["guild_id"]), int(pos["user_id"]), knocked=True, pnl=-cost)

    # ── /stocks commands ──────────────────────────────────────────────────────

    @stocks.command(name="list", description="View all current stock prices")
    async def stocks_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        now   = int(time.time())
        embed = discord.Embed(title="北京证券交易所 · Beijing Stock Exchange", color=0xCC0000)

        adr_lines = []
        for ticker, info in ADR_STOCKS.items():
            price    = self._prices.get(ticker, 0.0)
            day_open = self._day_opens.get(ticker, price)
            pct      = (price - day_open) / day_open * 100 if day_open > 0 else 0.0
            arrow    = "▲" if pct >= 0 else "▼"
            locked   = " ⏸" if ticker in self._daily_locked else (
                " ⏳" if (ticker in self._halted and now < self._halted[ticker]) else ""
            )
            adr_lines.append(f"`{ticker:<4}` {_fmt_price(price)}  {arrow} {_fmt_pct(pct)}{locked}")

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
            pump     = " 🔥 PUMP" if ticker in self._pump_state else ""
            locked   = " ⏸" if ticker in self._daily_locked else ""
            penny_lines.append(f"`{ticker:<4}` {_fmt_price(price)}  {arrow} {_fmt_pct(pct)}{pump}{locked}")

        embed.add_field(name="ADR Stocks", value="\n".join(adr_lines), inline=True)
        embed.add_field(
            name=f"ETF · {ETF_TICKER}",
            value=f"`{ETF_TICKER}` {_fmt_price(etf_price)}  {etf_arrow} {_fmt_pct(etf_pct)}",
            inline=True,
        )
        embed.add_field(name="Penny Stocks", value="\n".join(penny_lines), inline=False)
        embed.set_footer(text=f"Updates every {PRICE_UPDATE_INTERVAL}s · /stocks chart <ticker> for graphs")
        await interaction.followup.send(embed=embed)

    @stocks.command(name="chart", description="View a price chart for any stock")
    @app_commands.describe(
        ticker="Ticker symbol (e.g. BABA, XMNG, CNXF)",
        period="Time period",
        chart_type="Chart style",
    )
    @app_commands.choices(
        period=[app_commands.Choice(name=p, value=p) for p in PERIODS],
        chart_type=[app_commands.Choice(name=c, value=c) for c in CHART_TYPES],
    )
    async def stocks_chart(
        self,
        interaction: discord.Interaction,
        ticker: str,
        period: str = "1D",
        chart_type: str = "candlestick",
    ):
        await interaction.response.defer()
        ticker = ticker.upper()
        if ticker not in ALL_TICKERS:
            return await interaction.followup.send(
                f"Unknown ticker. Available: {', '.join(ALL_TICKERS)}", ephemeral=True
            )

        price    = self._prices.get(ticker, 0.0)
        day_open = self._day_opens.get(ticker, price)
        pct      = (price - day_open) / day_open * 100 if day_open > 0 else 0.0
        color    = 0x26A69A if pct >= 0 else 0xEF5350

        try:
            buf = await self._build_chart(ticker, period, chart_type)
        except Exception as e:
            return await interaction.followup.send(f"Chart unavailable: {e}", ephemeral=True)

        info = (
            ADR_STOCKS.get(ticker) or
            (ETF_INFO if ticker == ETF_TICKER else None) or
            PENNY_STOCKS.get(ticker) or {}
        )
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
        file = discord.File(buf, filename="chart.png")
        await interaction.followup.send(embed=embed, file=file)

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
        await interaction.followup.send(embed=embed)

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
        embed.add_field(name="Sold",     value=f"{shares:g} × {ticker}",     inline=True)
        embed.add_field(name="Price",    value=_fmt_price(price),             inline=True)
        embed.add_field(name="Proceeds", value=f"¥{proceeds:,}",             inline=True)
        embed.add_field(name="P&L",      value=f"{sign}¥{abs(pnl):,}",      inline=True)
        await interaction.followup.send(embed=embed)

    @stocks.command(name="portfolio", description="View your investment portfolio")
    async def stocks_portfolio(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        positions = await self.bot.db.get_portfolio(interaction.guild_id, interaction.user.id)
        tp_rows   = await self.bot.db.get_open_turbo_positions(interaction.guild_id, interaction.user.id)
        user_row  = await self.bot.db.get_user(interaction.guild_id, interaction.user.id)

        if not positions and not tp_rows:
            return await interaction.followup.send("You have no open positions.", ephemeral=True)

        total_value = 0.0
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
            stock_lines.append(
                f"`{ticker:<4}` {shares:g} sh · {_fmt_price(price)} · ¥{int(value):,} ({sign}¥{abs(pnl):,} / {_fmt_pct(pct)})"
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
            sym = "🟢" if direction == "LONG" else "🔴"
            turbo_lines.append(
                f"{sym} **#{pos['position_id']}** {direction} {leverage}x `{t_ticker}` · ¥{value:,} ({sign}¥{abs(pnl):,})"
            )

        realized = (user_row.get("stock_profit", 0) or 0) + (user_row.get("turbo_profit", 0) or 0)

        embed = discord.Embed(title="投资组合 · Portfolio", color=0xCC0000)
        if stock_lines:
            embed.add_field(name="Stocks", value="\n".join(stock_lines), inline=False)
        if turbo_lines:
            embed.add_field(name="Turbo Certificates", value="\n".join(turbo_lines), inline=False)
        embed.add_field(name="Total Value",  value=f"¥{int(total_value):,}", inline=True)
        embed.add_field(name="Realized P&L", value=f"¥{realized:,}",         inline=True)
        await interaction.followup.send(embed=embed)

    # ── /turbos commands ──────────────────────────────────────────────────────

    @turbos.command(name="list", description="View today's available turbo certificates")
    async def turbos_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        today = int(time.time()) // 86400
        rows  = await self.bot.db.get_daily_turbos(today)
        if not rows:
            return await interaction.followup.send("No turbos generated yet today. Try again in a moment.", ephemeral=True)

        lines = []
        for t in rows:
            price   = self._prices.get(t["ticker"], float(t["entry_price"]))
            factor  = max(0.0, _turbo_value_factor(t["direction"], float(t["entry_price"]), float(t["knockout"]), price))
            sym     = "🟢" if t["direction"] == "LONG" else "🔴"
            ko_dist = abs(price - float(t["knockout"])) / price * 100 if price > 0 else 0.0
            lines.append(
                f"**#{t['id']}** {sym} {t['direction']} {t['leverage']}x `{t['ticker']}` "
                f"· KO: {_fmt_price(float(t['knockout']))} ({ko_dist:.1f}% away) · factor: {factor:.3f}"
            )

        embed = discord.Embed(
            title="涡轮证书 · Daily Turbos",
            color=0xCC0000,
            description="\n".join(lines),
        )
        embed.set_footer(text=f"Use /turbos open <id> <yuan> · Minimum ¥{TURBO_MIN_COST:,}")
        await interaction.followup.send(embed=embed)

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
        embed.add_field(name="Certificate", value=f"#{turbo_id} {turbo['direction']} {turbo['leverage']}x {ticker}", inline=False)
        embed.add_field(name="Entry Price",   value=_fmt_price(entry),             inline=True)
        embed.add_field(name="Knockout",      value=_fmt_price(knockout),          inline=True)
        embed.add_field(name="KO Distance",   value=f"{ko_dist:.1f}%",             inline=True)
        embed.add_field(name="Invested",      value=f"¥{cost:,}",                  inline=True)
        embed.add_field(name="Current Value", value=f"¥{int(cost * factor):,}",    inline=True)
        await interaction.followup.send(embed=embed)

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
        embed.add_field(name="Proceeds", value=f"¥{proceeds:,}",          inline=True)
        embed.add_field(name="P&L",      value=f"{sign}¥{abs(pnl):,}",   inline=True)
        await interaction.followup.send(embed=embed)

    # ── Chart builder ──────────────────────────────────────────────────────────

    async def _build_chart(self, ticker: str, period: str, chart_type: str) -> io.BytesIO:
        loop = asyncio.get_running_loop()
        if ticker in ADR_TICKERS:
            yf_period, yf_interval = _YF_PERIOD_MAP[period]
            df = await loop.run_in_executor(None, _yf_history, ticker, yf_period, yf_interval)
            if df is None or df.empty:
                raise ValueError("No data from yfinance")
            opens  = df["Open"].tolist()
            highs  = df["High"].tolist()
            lows   = df["Low"].tolist()
            closes = df["Close"].tolist()
        else:
            since = int(time.time()) - _PERIOD_SECONDS[period]
            rows  = await self.bot.db.get_price_history(ticker, since)
            if not rows:
                raise ValueError("No price history yet for this period.")
            opens  = [float(r["open"])  for r in rows]
            highs  = [float(r["high"])  for r in rows]
            lows   = [float(r["low"])   for r in rows]
            closes = [float(r["close"]) for r in rows]

        return await loop.run_in_executor(None, _render_chart, ticker, opens, highs, lows, closes, chart_type)


async def setup(bot: commands.Bot):
    await bot.add_cog(StocksCog(bot))
