import time


class AnnouncementMixin:
    async def get_dashboard_announcement(self) -> dict:
        row = await self._pool.fetchrow(
            "SELECT enabled, message, severity, updated_at FROM dashboard_announcement WHERE id = 1"
        )
        if not row:
            return {"enabled": False, "message": "", "severity": "info", "updated_at": 0}
        return {
            "enabled": row["enabled"],
            "message": row["message"] or "",
            "severity": row["severity"] or "info",
            "updated_at": row["updated_at"],
        }

    async def set_dashboard_announcement(self, enabled: bool, message: str, severity: str):
        await self._pool.execute(
            """
            INSERT INTO dashboard_announcement (id, enabled, message, severity, updated_at)
            VALUES (1, $1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                message = EXCLUDED.message,
                severity = EXCLUDED.severity,
                updated_at = EXCLUDED.updated_at
            """,
            enabled, message, severity, int(time.time()),
        )
