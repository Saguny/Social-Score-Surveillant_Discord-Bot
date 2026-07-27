import time

_DEFAULTS = {
    "bg_image_url":   "https://safebooru.org//images/72/99a7c64eac6f712be2177d05ed6bc7be4fd5477e.jpg",
    "bg_position":    "center top",
    "bg_scrim":       86,
    "bg_blur":        0,
    "credit_name":    "Talz_ruwa72",
    "credit_url":     "https://x.com/Talz_ruwa72/status/2081338816431009800",
    "updated_at":     0,
}


class AppearanceMixin:
    """Site-wide look, editable from the admin panel.

    Singleton row (id pinned to 1) so a read is a single indexed lookup and
    there is no "which row wins" question — same shape as bureau_treasury and
    dashboard_announcement.
    """

    async def get_appearance(self) -> dict:
        row = await self._pool.fetchrow(
            """
            SELECT bg_image_url, bg_position, bg_scrim, bg_blur,
                   credit_name, credit_url, updated_at
            FROM site_appearance WHERE id = 1
            """
        )
        if not row:
            return dict(_DEFAULTS)
        return {
            "bg_image_url": row["bg_image_url"] or "",
            "bg_position":  row["bg_position"] or "center top",
            "bg_scrim":     int(row["bg_scrim"]),
            "bg_blur":      int(row["bg_blur"]),
            "credit_name":  row["credit_name"] or "",
            "credit_url":   row["credit_url"] or "",
            "updated_at":   int(row["updated_at"]),
        }

    async def set_appearance(
        self,
        bg_image_url: str,
        bg_position: str,
        bg_scrim: int,
        bg_blur: int,
        credit_name: str,
        credit_url: str,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO site_appearance
                (id, bg_image_url, bg_position, bg_scrim, bg_blur, credit_name, credit_url, updated_at)
            VALUES (1, $1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (id) DO UPDATE SET
                bg_image_url = EXCLUDED.bg_image_url,
                bg_position  = EXCLUDED.bg_position,
                bg_scrim     = EXCLUDED.bg_scrim,
                bg_blur      = EXCLUDED.bg_blur,
                credit_name  = EXCLUDED.credit_name,
                credit_url   = EXCLUDED.credit_url,
                updated_at   = EXCLUDED.updated_at
            """,
            bg_image_url, bg_position, bg_scrim, bg_blur,
            credit_name, credit_url, int(time.time()),
        )

    async def reset_appearance(self) -> None:
        await self.set_appearance(
            _DEFAULTS["bg_image_url"], _DEFAULTS["bg_position"],
            _DEFAULTS["bg_scrim"], _DEFAULTS["bg_blur"],
            _DEFAULTS["credit_name"], _DEFAULTS["credit_url"],
        )
