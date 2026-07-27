import time


class AdminRolesMixin:
    """Per-Discord-account admin roles.

    ADMIN_TOKEN is a single shared secret, so it can authorise but never
    attribute or restrict. Roles are keyed to a Discord account instead: a
    reviewer is added here and signs in with Discord, and never needs the token.
    """

    async def get_admin_role(self, discord_id: int) -> str | None:
        row = await self._pool.fetchrow(
            "SELECT role FROM admin_roles WHERE discord_id = $1",
            discord_id,
        )
        return row["role"] if row else None

    async def list_admin_roles(self) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT discord_id, username, role, note, added_by, added_by_username, added_at
            FROM admin_roles
            ORDER BY
                CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,
                added_at ASC
            """
        )
        return [dict(r) for r in rows]

    async def set_admin_role(
        self,
        discord_id: int,
        role: str,
        username: str = "",
        note: str = "",
        added_by: int | None = None,
        added_by_username: str = "",
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO admin_roles
                (discord_id, username, role, note, added_by, added_by_username, added_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (discord_id) DO UPDATE SET
                role     = EXCLUDED.role,
                note     = EXCLUDED.note,
                username = CASE WHEN EXCLUDED.username <> '' THEN EXCLUDED.username
                                ELSE admin_roles.username END
            """,
            discord_id, username, role, note, added_by, added_by_username, int(time.time()),
        )

    async def remove_admin_role(self, discord_id: int) -> bool:
        row = await self._pool.fetchrow(
            "DELETE FROM admin_roles WHERE discord_id = $1 RETURNING 1",
            discord_id,
        )
        return row is not None

    async def count_admin_owners(self) -> int:
        row = await self._pool.fetchrow(
            "SELECT COUNT(*) AS n FROM admin_roles WHERE role = 'owner'"
        )
        return int(row["n"]) if row else 0

    async def touch_admin_username(self, discord_id: int, username: str) -> None:
        """Keep the stored username fresh so the team list does not go stale."""
        if not username:
            return
        await self._pool.execute(
            "UPDATE admin_roles SET username = $2 WHERE discord_id = $1 AND username <> $2",
            discord_id, username,
        )

    # ── audit trail ──────────────────────────────────────────────────────────
    async def log_admin_action(
        self,
        actor_id: int | None,
        actor_username: str,
        action: str,
        target: str = "",
        detail: str = "",
    ) -> None:
        try:
            await self._pool.execute(
                """
                INSERT INTO admin_audit (actor_id, actor_username, action, target, detail, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                actor_id, actor_username, action, target[:200], detail[:1000], int(time.time()),
            )
        except Exception:
            pass

    async def get_admin_audit(self, limit: int = 100) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT actor_id, actor_username, action, target, detail, created_at
            FROM admin_audit
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]
