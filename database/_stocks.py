import time
import asyncio

from config.rules import (
    PORTFOLIO_SCORE_MIN_GAIN_PCT,
    PORTFOLIO_SCORE_SCALE,
    PORTFOLIO_SCORE_DAILY_CAP,
)


class StocksMixin:
    async def get_all_stocks(self) -> list:
        return await self._pool.fetch("SELECT * FROM stocks")

    async def upsert_stock_price(self, ticker: str, price: float, open_price: float):
        await self._pool.execute(
            """
            INSERT INTO stocks (ticker, price, open_price, updated_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (ticker) DO UPDATE SET price = $2, open_price = $3, updated_at = $4
            """,
            ticker, price, open_price, int(time.time()),
        )

    async def add_price_bar(self, ticker: str, ts: int, open_: float, high: float, low: float, close: float):
        await self._pool.execute(
            "INSERT INTO stock_price_history (ticker, ts, open, high, low, close) VALUES ($1, $2, $3, $4, $5, $6)",
            ticker, ts, open_, high, low, close,
        )

    async def batch_upsert_stock_prices(self, updates: list) -> None:
        if not updates:
            return
        now = int(time.time())
        await self._pool.executemany(
            """INSERT INTO stocks (ticker, price, open_price, updated_at)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (ticker) DO UPDATE SET price = $2, open_price = $3, updated_at = $4""",
            [(t, p, o, now) for t, p, o in updates],
        )

    async def batch_add_price_bars(self, bars: list) -> None:
        if not bars:
            return
        await self._pool.executemany(
            "INSERT INTO stock_price_history (ticker, ts, open, high, low, close) VALUES ($1, $2, $3, $4, $5, $6)",
            bars,
        )

    async def batch_close_knocked_positions(self, positions: list) -> None:
        if not positions:
            return
        now = int(time.time())
        pos_updates  = [(-int(p["cost"]), now, int(p["position_id"])) for p in positions]
        user_updates = [(-int(p["cost"]), int(p["guild_id"]), int(p["user_id"])) for p in positions]
        await asyncio.gather(
            self._pool.executemany(
                "UPDATE turbo_positions SET status = 'knocked', pnl = $1, closed_at = $2 WHERE id = $3",
                pos_updates,
            ),
            self._pool.executemany(
                "UPDATE users SET turbo_knocked = turbo_knocked + 1, turbo_profit = turbo_profit + $1 WHERE guild_id = $2 AND user_id = $3",
                user_updates,
            ),
        )

    async def get_price_history(self, ticker: str, since: int) -> list:
        return await self._pool.fetch(
            "SELECT ts, open, high, low, close FROM stock_price_history WHERE ticker = $1 AND ts > $2 ORDER BY ts",
            ticker, since,
        )

    async def get_latest_prices_from_history(self) -> dict[str, float]:
        rows = await self._pool.fetch(
            """
            SELECT DISTINCT ON (ticker) ticker, close
            FROM stock_price_history
            WHERE close > 0
            ORDER BY ticker, ts DESC
            """
        )
        return {r["ticker"]: float(r["close"]) for r in rows}

    async def get_all_portfolios(self) -> list:
        return await self._pool.fetch("SELECT guild_id, user_id, ticker, shares FROM portfolios")

    async def get_portfolio_user_yuan(self) -> list:
        return await self._pool.fetch(
            """
            SELECT DISTINCT u.guild_id, u.user_id, u.yuan
            FROM users u
            WHERE EXISTS (SELECT 1 FROM portfolios p WHERE p.guild_id = u.guild_id AND p.user_id = u.user_id)
            """
        )

    async def batch_insert_portfolio_history(self, records: list) -> None:
        if not records:
            return
        await self._pool.executemany(
            "INSERT INTO portfolio_history (guild_id, user_id, ts, value) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            records,
        )

    async def get_portfolio_history(self, guild_id: int, user_id: int, since_ts: int) -> list:
        return await self._pool.fetch(
            "SELECT ts, value FROM portfolio_history WHERE guild_id = $1 AND user_id = $2 AND ts >= $3 ORDER BY ts",
            guild_id, user_id, since_ts,
        )

    async def get_portfolio_day_open(self, guild_id: int, user_id: int, day_start: int):
        return await self._pool.fetchrow(
            "SELECT value FROM portfolio_history WHERE guild_id = $1 AND user_id = $2 AND ts >= $3 ORDER BY ts ASC LIMIT 1",
            guild_id, user_id, day_start,
        )

    async def prune_portfolio_history(self) -> None:
        cutoff = int(time.time()) - 366 * 86400
        await self._pool.execute("DELETE FROM portfolio_history WHERE ts < $1", cutoff)

    async def apply_portfolio_score_bonus(self) -> None:
        rows = await self._pool.fetch(
            """
            SELECT p.guild_id, p.user_id,
                   SUM(p.shares * p.avg_cost) AS cost_basis,
                   SUM(p.shares * s.price)    AS current_value
            FROM portfolios p
            JOIN stocks s ON s.ticker = p.ticker
            GROUP BY p.guild_id, p.user_id
            """
        )
        now     = int(time.time())
        updates = []
        history = []
        for row in rows:
            cost_basis = float(row["cost_basis"])
            if cost_basis <= 0:
                continue
            gain_pct = (float(row["current_value"]) - cost_basis) / cost_basis
            if gain_pct < PORTFOLIO_SCORE_MIN_GAIN_PCT:
                continue
            delta    = min(gain_pct * PORTFOLIO_SCORE_SCALE, PORTFOLIO_SCORE_DAILY_CAP)
            guild_id = int(row["guild_id"])
            user_id  = int(row["user_id"])
            updates.append((delta, guild_id, user_id))
            history.append((guild_id, user_id, delta, "portfolio gains", now))
        if not updates:
            return
        await asyncio.gather(
            self._pool.executemany(
                """
                UPDATE users SET
                    score         = GREATEST(600.0, LEAST(1300.0, score + $1)),
                    highest_score = GREATEST(highest_score, GREATEST(600.0, LEAST(1300.0, score + $1)))
                WHERE guild_id = $2 AND user_id = $3
                """,
                updates,
            ),
            self._pool.executemany(
                "INSERT INTO score_history (guild_id, user_id, delta, reason, timestamp) VALUES ($1, $2, $3, $4, $5)",
                history,
            ),
        )

    async def get_portfolio(self, guild_id: int, user_id: int) -> list:
        return await self._pool.fetch(
            "SELECT ticker, shares, avg_cost, opened_at FROM portfolios WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def buy_stock(self, guild_id: int, user_id: int, ticker: str, shares: float) -> dict | None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                price_row = await conn.fetchrow(
                    "SELECT price FROM stocks WHERE ticker = $1", ticker,
                )
                if not price_row:
                    return None
                price      = float(price_row["price"])
                total_cost = int(price * shares)
                if total_cost < 1:
                    return None
                user = await conn.fetchrow(
                    "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                if not user or user["yuan"] < total_cost:
                    return None
                await conn.execute(
                    "UPDATE users SET yuan = yuan - $1, total_yuan_spent = total_yuan_spent + $1, stock_trades = stock_trades + 1 WHERE guild_id = $2 AND user_id = $3",
                    total_cost, guild_id, user_id,
                )
                await conn.execute(
                    """
                    INSERT INTO portfolios (guild_id, user_id, ticker, shares, avg_cost, opened_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (guild_id, user_id, ticker) DO UPDATE SET
                        avg_cost  = (portfolios.shares * portfolios.avg_cost + EXCLUDED.shares * EXCLUDED.avg_cost)
                                    / (portfolios.shares + EXCLUDED.shares),
                        shares    = portfolios.shares + EXCLUDED.shares,
                        opened_at = COALESCE(portfolios.opened_at, EXCLUDED.opened_at)
                    """,
                    guild_id, user_id, ticker, shares, price, int(time.time()),
                )
        return {"price": price, "total_cost": total_cost}

    async def sell_stock(self, guild_id: int, user_id: int, ticker: str, shares: float, price: float) -> dict | None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                pos = await conn.fetchrow(
                    "SELECT shares, avg_cost FROM portfolios WHERE guild_id = $1 AND user_id = $2 AND ticker = $3",
                    guild_id, user_id, ticker,
                )
                if not pos or float(pos["shares"]) < shares - 1e-9:
                    return None
                proceeds  = int(price * shares)
                pnl       = int((price - float(pos["avg_cost"])) * shares)
                remaining = float(pos["shares"]) - shares
                if remaining < 1e-9:
                    await conn.execute(
                        "DELETE FROM portfolios WHERE guild_id = $1 AND user_id = $2 AND ticker = $3",
                        guild_id, user_id, ticker,
                    )
                else:
                    await conn.execute(
                        "UPDATE portfolios SET shares = $1 WHERE guild_id = $2 AND user_id = $3 AND ticker = $4",
                        remaining, guild_id, user_id, ticker,
                    )
                await conn.execute(
                    "UPDATE users SET yuan = yuan + $1, stock_trades = stock_trades + 1, stock_profit = stock_profit + $2 WHERE guild_id = $3 AND user_id = $4",
                    proceeds, pnl, guild_id, user_id,
                )
        return {"proceeds": proceeds, "pnl": pnl}

    async def mark_exchange_traded(self, guild_id: int, user_id: int, bit: int) -> int:
        row = await self._pool.fetchrow(
            "UPDATE users SET traded_exchanges = traded_exchanges | $1 WHERE guild_id = $2 AND user_id = $3 RETURNING traded_exchanges",
            bit, guild_id, user_id,
        )
        return row["traded_exchanges"] if row else 0

    async def replace_daily_turbos(self, day: int, turbo_list: list) -> None:
        if not turbo_list:
            return
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM turbos WHERE day = $1 AND id NOT IN (SELECT DISTINCT turbo_id FROM turbo_positions WHERE turbo_id IS NOT NULL)", day)
                await conn.executemany(
                    "INSERT INTO turbos (ticker, direction, leverage, entry_price, knockout, day) VALUES ($1, $2, $3, $4, $5, $6)",
                    [(t["ticker"], t["direction"], t["leverage"], t["entry_price"], t["knockout"], t["day"]) for t in turbo_list],
                )

    async def get_daily_turbos(self, day: int) -> list:
        return await self._pool.fetch(
            "SELECT * FROM turbos WHERE day = $1 ORDER BY id", day,
        )

    async def get_turbo(self, turbo_id: int):
        return await self._pool.fetchrow("SELECT * FROM turbos WHERE id = $1", turbo_id)

    async def open_turbo_position(self, guild_id: int, user_id: int, turbo_id: int, cost: int) -> bool:
        now = int(time.time())
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                user = await conn.fetchrow(
                    "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                if not user or user["yuan"] < cost:
                    return False
                await conn.execute(
                    "UPDATE users SET yuan = yuan - $1, total_yuan_spent = total_yuan_spent + $1, turbo_opened = turbo_opened + 1 WHERE guild_id = $2 AND user_id = $3",
                    cost, guild_id, user_id,
                )
                await conn.execute(
                    "INSERT INTO turbo_positions (guild_id, user_id, turbo_id, cost, opened_at) VALUES ($1, $2, $3, $4, $5)",
                    guild_id, user_id, turbo_id, cost, now,
                )
        return True

    async def get_open_turbo_positions(self, guild_id: int, user_id: int) -> list:
        return await self._pool.fetch(
            """
            SELECT tp.id AS position_id, tp.turbo_id, tp.cost,
                   t.ticker, t.direction, t.leverage, t.entry_price, t.knockout
            FROM turbo_positions tp
            JOIN turbos t ON tp.turbo_id = t.id
            WHERE tp.guild_id = $1 AND tp.user_id = $2 AND tp.status = 'open'
            ORDER BY tp.opened_at
            """,
            guild_id, user_id,
        )

    async def get_turbo_position(self, guild_id: int, user_id: int, position_id: int):
        return await self._pool.fetchrow(
            "SELECT * FROM turbo_positions WHERE id = $1 AND guild_id = $2 AND user_id = $3",
            position_id, guild_id, user_id,
        )

    async def get_all_open_turbo_positions(self) -> list:
        return await self._pool.fetch(
            """
            SELECT tp.id AS position_id, tp.guild_id, tp.user_id, tp.cost,
                   t.ticker, t.direction, t.entry_price, t.knockout
            FROM turbo_positions tp
            JOIN turbos t ON tp.turbo_id = t.id
            WHERE tp.status = 'open'
            """
        )

    async def close_turbo_position(self, position_id: int, pnl: int, status: str) -> bool:
        result = await self._pool.execute(
            "UPDATE turbo_positions SET status = $1, pnl = $2, closed_at = $3 WHERE id = $4 AND status = 'open'",
            status, pnl, int(time.time()), position_id,
        )
        return result.split()[-1] != "0"

    async def update_turbo_stats(self, guild_id: int, user_id: int, knocked: bool, pnl: int) -> None:
        await self._pool.execute(
            "UPDATE users SET turbo_knocked = turbo_knocked + $1, turbo_profit = turbo_profit + $2 WHERE guild_id = $3 AND user_id = $4",
            int(knocked), pnl, guild_id, user_id,
        )

    async def get_market_leaderboard(self, guild_id: int) -> dict:
        top_portfolio = await self._pool.fetch(
            """
            SELECT p.user_id, COALESCE(SUM(p.shares * s.price), 0) AS portfolio_value
            FROM portfolios p
            JOIN stocks s ON p.ticker = s.ticker
            WHERE p.guild_id = $1
            GROUP BY p.user_id
            ORDER BY portfolio_value DESC
            LIMIT 3
            """,
            guild_id,
        )
        top_realized = await self._pool.fetch(
            """
            SELECT user_id, (stock_profit + turbo_profit) AS total_pnl
            FROM users
            WHERE guild_id = $1 AND has_chatted = 1 AND (stock_profit + turbo_profit) > 0
            ORDER BY total_pnl DESC
            LIMIT 3
            """,
            guild_id,
        )
        return {"top_portfolio": top_portfolio, "top_realized": top_realized}
