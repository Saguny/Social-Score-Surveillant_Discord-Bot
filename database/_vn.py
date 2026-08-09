import json
import time

PARTY_SIZE = 3


class VNMixin:
    async def get_vn_arcs_with_stories(self) -> list[dict]:
        """Arcs that have at least one published episode, with episode count."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT a.id, a.title, a.description, a.exclusive_char_id,
                       COUNT(s.id) AS episode_count
                FROM vn_arcs a
                JOIN vn_stories s ON s.arc_id = a.id
                WHERE s.status = 'published'
                GROUP BY a.id, a.title, a.description, a.exclusive_char_id
                ORDER BY a.id
                """
            )
        return [dict(r) for r in rows]

    async def set_arc_exclusive_char(self, arc_id: int, character_id: str | None) -> None:
        await self._pool.execute(
            "UPDATE vn_arcs SET exclusive_char_id = $1 WHERE id = $2",
            character_id, arc_id,
        )

    async def get_vn_arc(self, arc_id: int) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM vn_arcs WHERE id = $1", arc_id)
        return dict(row) if row else None

    async def get_vn_arc_stories(self, arc_id: int) -> list[dict]:
        """Published stories in an arc ordered by episode_number."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM vn_stories WHERE arc_id = $1 AND status = 'published' "
                "ORDER BY episode_number",
                arc_id,
            )
        return [dict(r) for r in rows]

    async def get_next_arc_episode(self, arc_id: int, current_episode: int) -> dict | None:
        """Next published story in the arc after current_episode."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM vn_stories WHERE arc_id = $1 AND episode_number > $2 "
                "AND status = 'published' ORDER BY episode_number LIMIT 1",
                arc_id, current_episode,
            )
        return dict(row) if row else None

    async def get_vn_stories_published(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, title, description, party_size, entry_scene "
                "FROM vn_stories WHERE status = 'published' ORDER BY created_at"
            )
        return [dict(r) for r in rows]

    async def get_vn_story(self, story_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM vn_stories WHERE id = $1", story_id)
        if not row:
            return None
        d = dict(row)
        if isinstance(d.get("test_party"), str):
            d["test_party"] = json.loads(d["test_party"])
        return d

    async def get_vn_scene(self, story_id: str, scene_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM vn_scenes WHERE story_id = $1 AND id = $2",
                story_id, scene_id,
            )
        if not row:
            return None
        d = dict(row)
        for field in ("chars", "choices", "conditions"):
            if isinstance(d.get(field), str):
                d[field] = json.loads(d[field])
        return d

    async def get_vn_background_by_key(self, r2_key: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT public_url FROM vn_backgrounds WHERE r2_key = $1", r2_key
            )
        return dict(row) if row else None

    async def get_vn_ui_asset(self, asset_id: int) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT public_url FROM vn_ui_assets WHERE id = $1", asset_id
            )
        return dict(row) if row else None

    async def get_vn_config(self) -> dict | None:
        """Returns the global VN layout config row (id=1), or None if the table doesn't exist."""
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM vn_config WHERE id = 1")
            return dict(row) if row else None
        except Exception:
            return None

    # ── guild party ───────────────────────────────────────────────────────────

    async def get_vn_party(self, guild_id: int, user_id: int) -> list:
        """Returns a list of PARTY_SIZE character_ids (or None for empty slots)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT party FROM vn_party WHERE guild_id=$1 AND user_id=$2",
                guild_id, user_id,
            )
        if not row:
            return [None] * PARTY_SIZE
        party = row["party"]
        if isinstance(party, str):
            party = json.loads(party)
        # Pad / trim to PARTY_SIZE
        party = list(party)
        while len(party) < PARTY_SIZE:
            party.append(None)
        return party[:PARTY_SIZE]

    async def set_vn_party(self, guild_id: int, user_id: int, party: list) -> None:
        """Saves the full party list (length PARTY_SIZE, None for empty slots)."""
        await self._pool.execute(
            """
            INSERT INTO vn_party (guild_id, user_id, party)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET party = EXCLUDED.party
            """,
            guild_id, user_id, json.dumps(party),
        )

    async def get_vn_party_chars(self, character_ids: list) -> dict:
        """
        Party characters keyed by character_id, in the flat shape the VN code
        reads: `character_id`, `faction`, and `stat_*` at the top level.

        Deliberately not `get_gacha_character`, whose `_row_to_char` nests stats
        under "stats" and drops character_id entirely — reading `stat_authority`
        off one of those rows silently yields None, which zeroes every roll
        modifier. One query for the whole party instead of one per slot.
        """
        wanted = [cid for cid in (character_ids or []) if cid]
        if not wanted:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT character_id, name, title, faction, rarity, image_urls,
                       stat_military, stat_authority, stat_charisma
                FROM gacha_characters
                WHERE character_id = ANY($1)
                """,
                wanted,
            )
        return {r["character_id"]: dict(r) for r in rows}

    async def get_harem_for_party(self, guild_id: int, user_id: int, limit: int = 24) -> list[dict]:
        """Returns character details for a user's guild collection (joined with gacha_characters)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT gc.character_id, gc.name, gc.title, gc.rarity, gc.image_urls,
                       gc.stat_military, gc.stat_authority, gc.stat_charisma
                FROM gacha_claims cl
                JOIN gacha_characters gc ON cl.character_id = gc.character_id
                WHERE cl.guild_id = $1 AND cl.user_id = $2 AND gc.enabled = TRUE
                ORDER BY cl.claimed_at DESC
                LIMIT $3
                """,
                guild_id, user_id, limit,
            )
        return [dict(r) for r in rows]

    # ── story progress ────────────────────────────────────────────────────────

    async def get_vn_progress(self, guild_id: int, user_id: int, story_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT scene_id, party FROM vn_progress "
                "WHERE guild_id=$1 AND user_id=$2 AND story_id=$3",
                guild_id, user_id, story_id,
            )
        if not row:
            return None
        d = dict(row)
        if isinstance(d["party"], str):
            d["party"] = json.loads(d["party"])
        return d

    async def save_vn_progress(
        self, guild_id: int, user_id: int, story_id: str, scene_id: str, party: list
    ) -> None:
        now = int(time.time())
        await self._pool.execute(
            """
            INSERT INTO vn_progress (guild_id, user_id, story_id, scene_id, party, started_at, updated_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $6)
            ON CONFLICT (guild_id, user_id, story_id) DO UPDATE
                SET scene_id = EXCLUDED.scene_id, updated_at = EXCLUDED.updated_at
            """,
            guild_id, user_id, story_id, scene_id, json.dumps(party), now,
        )

    # ── active run ────────────────────────────────────────────────────────────

    async def get_active_vn_run(self, guild_id: int, user_id: int, story_id: str) -> dict | None:
        """The in-flight run for this episode, or None. Survives past completions."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT scene_id, party, vars FROM vn_progress "
                "WHERE guild_id=$1 AND user_id=$2 AND story_id=$3 AND run_active = TRUE",
                guild_id, user_id, story_id,
            )
        if not row:
            return None
        d = dict(row)
        for field in ("party", "vars"):
            if isinstance(d.get(field), str):
                d[field] = json.loads(d[field])
        return d

    async def start_vn_run(
        self, guild_id: int, user_id: int, story_id: str, scene_id: str, party: list
    ) -> None:
        """Begin a fresh run, clearing any run variables from a previous attempt."""
        now = int(time.time())
        await self._pool.execute(
            """
            INSERT INTO vn_progress
                (guild_id, user_id, story_id, scene_id, party, vars, started_at, updated_at, run_active)
            VALUES ($1, $2, $3, $4, $5::jsonb, '{}'::jsonb, $6, $6, TRUE)
            ON CONFLICT (guild_id, user_id, story_id) DO UPDATE
                SET scene_id   = EXCLUDED.scene_id,
                    party      = EXCLUDED.party,
                    vars       = '{}'::jsonb,
                    updated_at = EXCLUDED.updated_at,
                    run_active = TRUE
            """,
            guild_id, user_id, story_id, scene_id, json.dumps(party), now,
        )

    async def save_vn_run(
        self, guild_id: int, user_id: int, story_id: str, scene_id: str, run_vars: dict
    ) -> None:
        """Checkpoint the run after a transition. No-op if the run isn't active."""
        await self._pool.execute(
            """
            UPDATE vn_progress
            SET scene_id = $4, vars = $5::jsonb, updated_at = $6
            WHERE guild_id=$1 AND user_id=$2 AND story_id=$3 AND run_active = TRUE
            """,
            guild_id, user_id, story_id, scene_id, json.dumps(run_vars or {}), int(time.time()),
        )

    async def set_vn_run_party(
        self, guild_id: int, user_id: int, story_id: str, party: list
    ) -> None:
        """Repair the frozen party of an in-flight run. Only used when it was empty."""
        await self._pool.execute(
            "UPDATE vn_progress SET party = $4::jsonb, updated_at = $5 "
            "WHERE guild_id=$1 AND user_id=$2 AND story_id=$3 AND run_active = TRUE",
            guild_id, user_id, story_id, json.dumps(party), int(time.time()),
        )

    async def end_vn_run(self, guild_id: int, user_id: int, story_id: str) -> None:
        await self._pool.execute(
            "UPDATE vn_progress SET run_active = FALSE, updated_at = $4 "
            "WHERE guild_id=$1 AND user_id=$2 AND story_id=$3",
            guild_id, user_id, story_id, int(time.time()),
        )

    async def get_vn_completion(self, guild_id: int, user_id: int, story_id: str) -> dict | None:
        """Returns completion record if the episode has been finished, else None."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT completed_at, ending_type FROM vn_progress "
                "WHERE guild_id=$1 AND user_id=$2 AND story_id=$3 AND completed_at IS NOT NULL",
                guild_id, user_id, story_id,
            )
        return dict(row) if row else None

    async def vn_complete_episode(
        self, guild_id: int, user_id: int, story_id: str, ending_type: str, scene_id: str
    ) -> bool:
        """Mark an episode complete. Returns True if this is the first completion."""
        now = int(time.time())
        async with self._pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT completed_at FROM vn_progress "
                "WHERE guild_id=$1 AND user_id=$2 AND story_id=$3",
                guild_id, user_id, story_id,
            )
            is_first = existing is None or existing["completed_at"] is None
            await conn.execute(
                """
                INSERT INTO vn_progress
                    (guild_id, user_id, story_id, scene_id, party, started_at, updated_at, completed_at, ending_type)
                VALUES ($1, $2, $3, $4, '[]', $5, $5, $5, $6)
                ON CONFLICT (guild_id, user_id, story_id) DO UPDATE
                    SET completed_at = COALESCE(vn_progress.completed_at, EXCLUDED.completed_at),
                        ending_type  = COALESCE(vn_progress.ending_type,  EXCLUDED.ending_type),
                        updated_at   = EXCLUDED.updated_at,
                        run_active   = FALSE
                """,
                guild_id, user_id, story_id, scene_id, now, ending_type,
            )
        return is_first

    # ── ending collection ─────────────────────────────────────────────────────

    async def record_vn_ending(
        self, guild_id: int, user_id: int, story_id: str, scene_id: str, ending_type: str | None
    ) -> bool:
        """Record an ending scene as seen. Returns True only the first time."""
        row = await self._pool.fetchrow(
            """
            INSERT INTO vn_endings (guild_id, user_id, story_id, scene_id, ending_type, seen_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (guild_id, user_id, story_id, scene_id) DO NOTHING
            RETURNING 1
            """,
            guild_id, user_id, story_id, scene_id, ending_type, int(time.time()),
        )
        return row is not None

    async def count_story_endings(self, story_id: str) -> int:
        """How many ending scenes this story has."""
        val = await self._pool.fetchval(
            "SELECT COUNT(*) FROM vn_scenes WHERE story_id = $1 AND scene_type = 'ending'",
            story_id,
        )
        return int(val or 0)

    async def count_vn_endings_seen(self, guild_id: int, user_id: int, story_id: str) -> int:
        val = await self._pool.fetchval(
            "SELECT COUNT(*) FROM vn_endings WHERE guild_id=$1 AND user_id=$2 AND story_id=$3",
            guild_id, user_id, story_id,
        )
        return int(val or 0)

    async def get_vn_ending_rarity(self, guild_id: int, story_id: str, scene_id: str) -> tuple[int, int]:
        """(how many here found this ending, how many here have finished this episode at all)."""
        row = await self._pool.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM vn_endings
                 WHERE guild_id = $1 AND story_id = $2 AND scene_id = $3) AS discoverers,
                (SELECT COUNT(DISTINCT user_id) FROM vn_endings
                 WHERE guild_id = $1 AND story_id = $2) AS players
            """,
            guild_id, story_id, scene_id,
        )
        if not row:
            return 0, 0
        return int(row["discoverers"] or 0), int(row["players"] or 0)

    async def get_vn_ending_catalog(self, guild_id: int, user_id: int) -> list[dict]:
        """Every published ending scene, with this user's discovery state and guild rarity."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.story_id, s.id AS scene_id, s.label, s.ending_type,
                       st.title AS story_title, st.episode_number, st.arc_id,
                       (mine.user_id IS NOT NULL) AS found,
                       COALESCE(d.discoverers, 0) AS discoverers,
                       COALESCE(pl.players, 0)    AS players
                FROM vn_scenes s
                JOIN vn_stories st ON st.id = s.story_id AND st.status = 'published'
                LEFT JOIN vn_endings mine
                    ON mine.story_id = s.story_id AND mine.scene_id = s.id
                    AND mine.guild_id = $1 AND mine.user_id = $2
                LEFT JOIN (
                    SELECT story_id, scene_id, COUNT(*) AS discoverers
                    FROM vn_endings WHERE guild_id = $1 GROUP BY story_id, scene_id
                ) d ON d.story_id = s.story_id AND d.scene_id = s.id
                LEFT JOIN (
                    SELECT story_id, COUNT(DISTINCT user_id) AS players
                    FROM vn_endings WHERE guild_id = $1 GROUP BY story_id
                ) pl ON pl.story_id = s.story_id
                WHERE s.scene_type = 'ending'
                ORDER BY st.arc_id, st.episode_number, s.id
                """,
                guild_id, user_id,
            )
        return [dict(r) for r in rows]

    async def get_vn_arc_progress(self, guild_id: int, user_id: int, arc_id: int) -> list[dict]:
        """Per-episode completion and ending-collection state for one arc."""
        by_arc = await self.get_vn_episode_progress(guild_id, user_id, [arc_id])
        return by_arc.get(arc_id, [])

    async def get_vn_episode_progress(
        self, guild_id: int, user_id: int, arc_ids: list | None = None
    ) -> dict:
        """
        Episode progress grouped by arc_id. One query for every arc rather than
        one per arc, so `/vn progress` costs the same whether there are 2 arcs
        or 20.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.arc_id, s.id, s.title, s.episode_number,
                       (p.completed_at IS NOT NULL) AS completed,
                       p.ending_type,
                       COALESCE(e.seen, 0)  AS endings_seen,
                       COALESCE(t.total, 0) AS endings_total
                FROM vn_stories s
                LEFT JOIN vn_progress p
                    ON p.story_id = s.id AND p.guild_id = $1 AND p.user_id = $2
                LEFT JOIN (
                    SELECT story_id, COUNT(*) AS seen FROM vn_endings
                    WHERE guild_id = $1 AND user_id = $2 GROUP BY story_id
                ) e ON e.story_id = s.id
                LEFT JOIN (
                    SELECT story_id, COUNT(*) AS total FROM vn_scenes
                    WHERE scene_type = 'ending' GROUP BY story_id
                ) t ON t.story_id = s.id
                WHERE s.status = 'published'
                  AND ($3::bigint[] IS NULL OR s.arc_id = ANY($3))
                ORDER BY s.arc_id, s.episode_number
                """,
                guild_id, user_id, arc_ids,
            )
        out: dict = {}
        for row in rows:
            out.setdefault(row["arc_id"], []).append(dict(row))
        return out

    async def get_vn_arcs_progress(self, guild_id: int, user_id: int) -> list[dict]:
        """Arcs with at least one published episode, annotated with the user's progress."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT a.id, a.title, a.description, a.exclusive_char_id,
                       COUNT(s.id)          AS episode_count,
                       COUNT(p.completed_at) AS completed_count,
                       COALESCE(SUM(e.seen), 0)  AS endings_seen,
                       COALESCE(SUM(t.total), 0) AS endings_total
                FROM vn_arcs a
                JOIN vn_stories s ON s.arc_id = a.id AND s.status = 'published'
                LEFT JOIN vn_progress p
                    ON p.story_id = s.id AND p.guild_id = $1 AND p.user_id = $2
                    AND p.completed_at IS NOT NULL
                LEFT JOIN (
                    SELECT story_id, COUNT(*) AS seen FROM vn_endings
                    WHERE guild_id = $1 AND user_id = $2 GROUP BY story_id
                ) e ON e.story_id = s.id
                LEFT JOIN (
                    SELECT story_id, COUNT(*) AS total FROM vn_scenes
                    WHERE scene_type = 'ending' GROUP BY story_id
                ) t ON t.story_id = s.id
                GROUP BY a.id, a.title, a.description, a.exclusive_char_id
                ORDER BY a.id
                """,
                guild_id, user_id,
            )
        return [dict(r) for r in rows]

    async def spend_user_counter(self, user_id: int, key: str) -> int:
        """Atomically decrement a user counter if > 0. Returns new value, or -1 if already 0."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                WITH dec AS (
                    UPDATE user_counters
                    SET value = value - 1
                    WHERE user_id = $1 AND counter_key = $2 AND value > 0
                    RETURNING value
                )
                SELECT COALESCE((SELECT value FROM dec), -1) AS result
                """,
                user_id, key,
            )
        return row["result"]

    async def vn_arc_all_complete(self, guild_id: int, user_id: int, arc_id: int) -> bool:
        """Returns True if every published episode in the arc has a completion record."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS total,
                       COUNT(p.completed_at) AS completed
                FROM vn_stories s
                LEFT JOIN vn_progress p
                    ON p.guild_id = $1 AND p.user_id = $2 AND p.story_id = s.id
                    AND p.completed_at IS NOT NULL
                WHERE s.arc_id = $3 AND s.status = 'published'
                """,
                guild_id, user_id, arc_id,
            )
        return row is not None and row["total"] > 0 and row["total"] == row["completed"]

    async def reset_vn_progress(self, guild_id: int, user_id: int, story_id: str) -> None:
        await self._pool.execute(
            "DELETE FROM vn_progress WHERE guild_id=$1 AND user_id=$2 AND story_id=$3",
            guild_id, user_id, story_id,
        )
