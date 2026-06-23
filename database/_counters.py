import time


class CountersMixin:
    async def get_counter(self, user_id: int, key: str) -> int:
        row = await self._pool.fetchrow(
            "SELECT value FROM user_counters WHERE user_id = $1 AND counter_key = $2",
            user_id, key,
        )
        return int(row["value"]) if row else 0

    async def set_counter(self, user_id: int, key: str, value: int) -> None:
        await self._pool.execute(
            """
            INSERT INTO user_counters (user_id, counter_key, value)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, counter_key) DO UPDATE SET value = $3
            """,
            user_id, key, value,
        )

    async def increment_counter(self, user_id: int, key: str, delta: int = 1) -> int:
        row = await self._pool.fetchrow(
            """
            INSERT INTO user_counters (user_id, counter_key, value)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, counter_key) DO UPDATE SET value = user_counters.value + $3
            RETURNING value
            """,
            user_id, key, delta,
        )
        return int(row["value"])

    async def bump_daily_streak(self, user_id: int, streak_key: str) -> tuple[int, int]:
        today = int(time.time()) // 86400
        last_day_key = f"{streak_key}:last_day"
        current_key = f"{streak_key}:current"
        best_key = f"{streak_key}:best"

        last_day = await self.get_counter(user_id, last_day_key)
        current = await self.get_counter(user_id, current_key)
        best = await self.get_counter(user_id, best_key)

        if last_day == today:
            return current, best

        current = current + 1 if last_day == today - 1 else 1
        await self.set_counter(user_id, current_key, current)
        await self.set_counter(user_id, last_day_key, today)

        if current > best:
            best = current
            await self.set_counter(user_id, best_key, best)

        return current, best

    async def get_top_by_counter(self, key: str, limit: int = 10):
        return await self._pool.fetch(
            "SELECT user_id, value FROM user_counters WHERE counter_key = $1 ORDER BY value DESC LIMIT $2",
            key, limit,
        )

    async def record_negative_action(self, user_id: int) -> None:
        await self.set_counter(user_id, "clean_streak:last_negative_at", int(time.time()))

    async def get_clean_streak_days(self, user_id: int) -> int | None:
        ts = await self.get_counter(user_id, "clean_streak:last_negative_at")
        if not ts:
            return None
        return (int(time.time()) - ts) // 86400
