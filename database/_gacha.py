import time


def _row_to_char(row) -> dict:
    return {
        "name":                   row["name"],
        "title":                  row["title"],
        "faction":                row["faction"],
        "rarity":                 row["rarity"],
        "quote":                  row["quote"],
        "wiki":                   row["wiki"],
        "gender":                 row["gender"],
        "stats": {
            "authority": row["stat_authority"],
            "military":  row["stat_military"],
            "charisma":  row["stat_charisma"],
        },
        "image_urls":             list(row["image_urls"] or []),
        "submitted_by_username":  row["submitted_by_username"] if "submitted_by_username" in row.keys() else None,
    }


class GachaMixin:
    async def claim_character(self, guild_id: int, user_id: int, character_id: str) -> bool:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO gacha_claims (guild_id, user_id, character_id, claimed_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (guild_id, user_id, character_id) DO NOTHING
                    RETURNING 1
                    """,
                    guild_id, user_id, character_id, int(time.time()),
                )
                await conn.execute(
                    """
                    INSERT INTO gacha_character_stats (character_id, claim_count)
                    VALUES ($1, 1)
                    ON CONFLICT (character_id) DO UPDATE SET claim_count = gacha_character_stats.claim_count + 1
                    """,
                    character_id,
                )
                return row is not None

    async def get_character_rank(self, character_id: str) -> dict:
        """Returns global rank, total ranked characters, and claim count for a character."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                WITH ranked AS (
                    SELECT character_id, claim_count,
                           DENSE_RANK() OVER (ORDER BY claim_count DESC) AS rank,
                           COUNT(*) OVER () AS total
                    FROM gacha_character_stats
                )
                SELECT rank, total, claim_count
                FROM ranked
                WHERE character_id = $1
                """,
                character_id,
            )
            if row:
                return {"rank": row["rank"], "total": row["total"], "claims": row["claim_count"]}
            return {"rank": None, "total": None, "claims": 0}

    async def get_characters_rank_batch(self, character_ids: list[str]) -> dict[str, dict]:
        """Returns rank/claims for a list of character IDs in one query."""
        if not character_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH ranked AS (
                    SELECT character_id, claim_count,
                           DENSE_RANK() OVER (ORDER BY claim_count DESC) AS rank,
                           COUNT(*) OVER () AS total
                    FROM gacha_character_stats
                )
                SELECT character_id, rank, total, claim_count
                FROM ranked
                WHERE character_id = ANY($1)
                """,
                character_ids,
            )
            return {
                r["character_id"]: {"rank": r["rank"], "total": r["total"], "claims": r["claim_count"]}
                for r in rows
            }

    async def get_top_characters(self, limit: int = 10) -> list[dict]:
        """Global leaderboard — most claimed characters across all servers."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT character_id, claim_count,
                       DENSE_RANK() OVER (ORDER BY claim_count DESC) AS rank
                FROM gacha_character_stats
                ORDER BY claim_count DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(r) for r in rows]

    async def is_claimed_in_guild(self, guild_id: int, character_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM gacha_claims WHERE guild_id=$1 AND character_id=$2 LIMIT 1",
                guild_id, character_id,
            )
            return row is not None

    async def get_character_owner(self, guild_id: int, character_id: str) -> int | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM gacha_claims WHERE guild_id=$1 AND character_id=$2 LIMIT 1",
                guild_id, character_id,
            )
            return row["user_id"] if row else None

    async def get_user_collection(self, guild_id: int, user_id: int) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT character_id, claimed_at FROM gacha_claims "
                "WHERE guild_id = $1 AND user_id = $2 ORDER BY claimed_at DESC",
                guild_id, user_id,
            )
            return [dict(r) for r in rows]

    async def has_character(self, guild_id: int, user_id: int, character_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM gacha_claims WHERE guild_id = $1 AND user_id = $2 AND character_id = $3",
                guild_id, user_id, character_id,
            )
            return row is not None

    async def count_collection(self, guild_id: int, user_id: int) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM gacha_claims WHERE guild_id = $1 AND user_id = $2",
                guild_id, user_id,
            )
            return row["n"] if row else 0

    async def trade_characters(
        self,
        guild_id: int,
        user_a: int, char_a: str,
        user_b: int, char_b: str,
    ) -> bool:
        """Atomically swap char_a (owned by user_a) for char_b (owned by user_b).
        Returns False if either ownership check fails (race condition guard)."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                owns_a = await conn.fetchval(
                    "SELECT 1 FROM gacha_claims WHERE guild_id=$1 AND user_id=$2 AND character_id=$3",
                    guild_id, user_a, char_a,
                )
                owns_b = await conn.fetchval(
                    "SELECT 1 FROM gacha_claims WHERE guild_id=$1 AND user_id=$2 AND character_id=$3",
                    guild_id, user_b, char_b,
                )
                if not owns_a or not owns_b:
                    return False
                now = int(time.time())
                await conn.execute(
                    "DELETE FROM gacha_claims WHERE guild_id=$1 AND user_id=$2 AND character_id=$3",
                    guild_id, user_a, char_a,
                )
                await conn.execute(
                    "DELETE FROM gacha_claims WHERE guild_id=$1 AND user_id=$2 AND character_id=$3",
                    guild_id, user_b, char_b,
                )
                await conn.execute(
                    "INSERT INTO gacha_claims (guild_id, user_id, character_id, claimed_at) "
                    "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                    guild_id, user_b, char_a, now,
                )
                await conn.execute(
                    "INSERT INTO gacha_claims (guild_id, user_id, character_id, claimed_at) "
                    "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                    guild_id, user_a, char_b, now,
                )
                return True

    async def add_wishlist(self, guild_id: int, user_id: int, character_id: str, max_size: int = 10) -> str:
        """Insert only when current count < max_size. Returns 'added', 'duplicate', or 'full'."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                WITH cnt AS (
                    SELECT COUNT(*) AS n FROM gacha_wishlists WHERE guild_id = $1 AND user_id = $2
                )
                INSERT INTO gacha_wishlists (guild_id, user_id, character_id)
                SELECT $1, $2, $3 FROM cnt WHERE n < $4
                ON CONFLICT DO NOTHING
                RETURNING 1
                """,
                guild_id, user_id, character_id, max_size,
            )
            if row is not None:
                return "added"
            existing = await conn.fetchval(
                "SELECT 1 FROM gacha_wishlists WHERE guild_id=$1 AND user_id=$2 AND character_id=$3",
                guild_id, user_id, character_id,
            )
            return "duplicate" if existing else "full"

    async def remove_wishlist(self, guild_id: int, user_id: int, character_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM gacha_wishlists WHERE guild_id=$1 AND user_id=$2 AND character_id=$3 RETURNING 1",
                guild_id, user_id, character_id,
            )
            return row is not None

    async def get_wishlist(self, guild_id: int, user_id: int) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT character_id FROM gacha_wishlists WHERE guild_id=$1 AND user_id=$2",
                guild_id, user_id,
            )
            return [r["character_id"] for r in rows]

    async def gift_character(self, guild_id: int, from_user: int, to_user: int, character_id: str) -> bool:
        """Transfer character from from_user to to_user. Returns False if from_user doesn't own it."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                deleted = await conn.fetchval(
                    "DELETE FROM gacha_claims WHERE guild_id=$1 AND user_id=$2 AND character_id=$3 RETURNING 1",
                    guild_id, from_user, character_id,
                )
                if not deleted:
                    return False
                await conn.execute(
                    "INSERT INTO gacha_claims (guild_id, user_id, character_id, claimed_at) "
                    "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                    guild_id, to_user, character_id, int(time.time()),
                )
                return True

    async def divorce_character(self, guild_id: int, user_id: int, character_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM gacha_claims WHERE guild_id=$1 AND user_id=$2 AND character_id=$3 RETURNING 1",
                guild_id, user_id, character_id,
            )
            return row is not None

    async def get_harem_thumbnail(self, guild_id: int, user_id: int) -> str | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM gacha_preferences WHERE guild_id=$1 AND user_id=$2 AND key='thumbnail'",
                guild_id, user_id,
            )
            return row["value"] if row else None

    async def set_harem_thumbnail(self, guild_id: int, user_id: int, character_id: str) -> None:
        await self._pool.execute(
            """
            INSERT INTO gacha_preferences (guild_id, user_id, key, value)
            VALUES ($1, $2, 'thumbnail', $3)
            ON CONFLICT (guild_id, user_id, key) DO UPDATE SET value = EXCLUDED.value
            """,
            guild_id, user_id, character_id,
        )

    async def get_wishlist_watchers(self, guild_id: int, character_id: str) -> list[int]:
        """Returns user_ids who wishlisted this character in this guild."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id FROM gacha_wishlists WHERE guild_id=$1 AND character_id=$2",
                guild_id, character_id,
            )
            return [r["user_id"] for r in rows]

    # ── gacha_characters (character pool) ─────────────────────────────────────

    async def get_all_characters(self) -> dict[str, dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM gacha_characters WHERE enabled = TRUE ORDER BY character_id"
            )
        return {row["character_id"]: _row_to_char(row) for row in rows}

    async def get_gacha_character(self, character_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM gacha_characters WHERE character_id = $1",
                character_id,
            )
        return _row_to_char(row) if row else None

    async def upsert_gacha_character(
        self,
        character_id: str,
        data: dict,
        submitted_by_discord_id: int | None = None,
        submitted_by_username: str | None = None,
    ) -> None:
        s = data.get("stats", {})
        await self._pool.execute(
            """
            INSERT INTO gacha_characters
                (character_id, name, title, faction, rarity, quote, wiki, gender,
                 stat_authority, stat_military, stat_charisma, image_urls,
                 submitted_by_discord_id, submitted_by_username)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (character_id) DO UPDATE SET
                name                    = EXCLUDED.name,
                title                   = EXCLUDED.title,
                faction                 = EXCLUDED.faction,
                rarity                  = EXCLUDED.rarity,
                quote                   = EXCLUDED.quote,
                wiki                    = EXCLUDED.wiki,
                gender                  = EXCLUDED.gender,
                stat_authority          = EXCLUDED.stat_authority,
                stat_military           = EXCLUDED.stat_military,
                stat_charisma           = EXCLUDED.stat_charisma,
                image_urls              = EXCLUDED.image_urls,
                submitted_by_discord_id = COALESCE(gacha_characters.submitted_by_discord_id, EXCLUDED.submitted_by_discord_id),
                submitted_by_username   = COALESCE(gacha_characters.submitted_by_username,   EXCLUDED.submitted_by_username)
            """,
            character_id,
            data["name"], data["title"], data["faction"], data["rarity"],
            data.get("quote", ""), data.get("wiki", ""), data.get("gender"),
            s.get("authority", 50), s.get("military", 50), s.get("charisma", 50),
            data.get("image_urls") or [],
            submitted_by_discord_id, submitted_by_username,
        )

    async def update_gacha_character_images(self, character_id: str, image_urls: list[str]) -> None:
        await self._pool.execute(
            "UPDATE gacha_characters SET image_urls = $2 WHERE character_id = $1",
            character_id, image_urls,
        )

    async def get_characters_missing_images(self) -> list[tuple[str, str]]:
        """Returns (character_id, wiki) pairs for characters with no images."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT character_id, wiki FROM gacha_characters
                WHERE enabled = TRUE AND array_length(image_urls, 1) IS NULL AND wiki != ''
                ORDER BY character_id
                """
            )
        return [(row["character_id"], row["wiki"]) for row in rows]

    async def get_existing_character_ids(self) -> set[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT character_id FROM gacha_characters")
        return {row["character_id"] for row in rows}

    async def get_existing_wikis(self) -> set[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT wiki FROM gacha_characters WHERE wiki != ''")
        return {row["wiki"] for row in rows}

    async def set_gacha_character_enabled(self, character_id: str, enabled: bool) -> bool:
        """Soft-enable or soft-disable a character. Returns True if the row was found."""
        result = await self._pool.execute(
            "UPDATE gacha_characters SET enabled = $2 WHERE character_id = $1",
            character_id, enabled,
        )
        return result.split()[-1] != "0"

    async def find_gacha_character_id(self, name_or_id: str) -> str | None:
        """Resolve a character name or id to its character_id."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT character_id FROM gacha_characters WHERE character_id = $1 OR LOWER(name) = LOWER($1) LIMIT 1",
                name_or_id,
            )
        return row["character_id"] if row else None
