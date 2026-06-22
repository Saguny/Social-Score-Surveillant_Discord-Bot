import hashlib
import os

_FALLBACK_SALT = "social-credit-bot-default-salt-change-me"


def _salt() -> str:
    return os.getenv("PSEUDONYM_SALT") or _FALLBACK_SALT


def _digest(kind: str, real_id) -> int:
    raw = f"{_salt()}:{kind}:{real_id}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def pseudonym_user(user_id) -> str:
    return f"User #{_digest('user', user_id) % 1_000_000:06d}"


def pseudonym_guild(guild_id) -> str:
    return f"Guild #{_digest('guild', guild_id) % 100_000:05d}"


def redact_global_stats(stats: dict) -> dict:
    mag = stats.get("most_active_guild") or {}
    if mag.get("guild_id"):
        stats["most_active_guild"] = {
            "guild_name": pseudonym_guild(mag["guild_id"]),
            "total": mag.get("total", 0),
        }
    else:
        stats["most_active_guild"] = {"guild_name": "", "total": 0}
    return stats


def using_fallback_salt() -> bool:
    return not os.getenv("PSEUDONYM_SALT")
