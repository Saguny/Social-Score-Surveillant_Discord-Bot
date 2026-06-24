import time
import asyncio


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

    async def is_leaderboard_visible(self, user_id: int) -> bool:
        return bool(await self.get_counter(user_id, "leaderboard_visible"))

    async def set_leaderboard_visible(self, user_id: int, visible: bool) -> None:
        await self.set_counter(user_id, "leaderboard_visible", 1 if visible else 0)

    async def set_leaderboard_display_name(self, user_id: int, display_name: str) -> None:
        await self._pool.execute(
            """
            INSERT INTO leaderboard_profiles (user_id, display_name, updated_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
                SET display_name = EXCLUDED.display_name, updated_at = EXCLUDED.updated_at
            """,
            user_id, display_name, int(time.time()),
        )

    async def get_leaderboard_display_names(self, user_ids: list) -> dict:
        if not user_ids:
            return {}
        from config.shop import COSMETIC_META
        from config.ranks import prestige_stars
        from config.achievements import ACHIEVEMENTS

        profile_rows = await self._pool.fetch(
            """
            SELECT lp.user_id, lp.display_name
            FROM leaderboard_profiles lp
            JOIN user_counters uc
              ON uc.user_id = lp.user_id AND uc.counter_key = 'leaderboard_visible'
            WHERE lp.user_id = ANY($1) AND uc.value = 1
            """,
            user_ids,
        )
        if not profile_rows:
            return {}

        visible_uids = [r["user_id"] for r in profile_rows]
        base_names = {r["user_id"]: r["display_name"] for r in profile_rows}
        now = int(time.time())

        badge_rows, pref_rows, prestige_rows, ec_rows = await asyncio.gather(
            self._pool.fetch(
                "SELECT user_id, badge FROM cosmetic_badges WHERE user_id = ANY($1) AND (expires_at IS NULL OR expires_at > $2)",
                visible_uids, now,
            ),
            self._pool.fetch(
                "SELECT user_id, badge_id FROM badge_preferences WHERE user_id = ANY($1)",
                visible_uids,
            ),
            self._pool.fetch(
                "SELECT user_id, value FROM user_counters WHERE user_id = ANY($1) AND counter_key = 'prestige_level' AND value > 0",
                visible_uids,
            ),
            self._pool.fetch(
                "SELECT user_id FROM eternal_chairmen WHERE user_id = ANY($1)",
                visible_uids,
            ),
        )

        owned: dict[int, set] = {}
        for r in badge_rows:
            owned.setdefault(r["user_id"], set()).add(r["badge"])
        prefs = {r["user_id"]: r["badge_id"] for r in pref_rows}
        prestiges = {r["user_id"]: int(r["value"]) for r in prestige_rows}
        ec_set = {r["user_id"] for r in ec_rows}

        _ORDER = ["voter", "verified", "figure", "influencer", "associate", "asset"]

        def _fw(s: str) -> str:
            out = []
            for c in s:
                if 'a' <= c <= 'z' or 'A' <= c <= 'Z':
                    out.append(chr(ord(c) + 0xFEE0))
                elif c == ' ':
                    out.append('　')
                else:
                    out.append(c)
            return ''.join(out)

        def _sfx(badge_id: str) -> str:
            return COSMETIC_META[badge_id]["suffix"] if badge_id in COSMETIC_META else badge_id

        result = {}
        for uid, base in base_names.items():
            level = prestiges.get(uid, 0)
            stars = f" {prestige_stars(level)}" if level > 0 else ""

            if uid in ec_set:
                result[uid] = f"{base} 【{_fw('Winnie the Pooh')}】{stars}"
                continue

            badge_set = owned.get(uid, set())
            if not badge_set:
                result[uid] = f"{base}{stars}"
                continue

            pref = prefs.get(uid)
            if pref and pref in badge_set:
                result[uid] = f"{base} {_sfx(pref)}{stars}"
                continue

            for badge_id in reversed(_ORDER):
                if badge_id in badge_set:
                    result[uid] = f"{base} {_sfx(badge_id)}{stars}"
                    break
            else:
                for data in ACHIEVEMENTS.values():
                    bid = data.get("badge")
                    if bid and bid in badge_set:
                        result[uid] = f"{base} {_sfx(bid)}{stars}"
                        break
                else:
                    result[uid] = f"{base}{stars}"

        return result
