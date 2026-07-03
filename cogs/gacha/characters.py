_CHARS: dict[str, dict] = {}
_NAME_INDEX: dict[str, str] = {}


def load(chars: dict[str, dict]) -> None:
    global _CHARS, _NAME_INDEX
    _CHARS = chars
    _NAME_INDEX = {ch["name"].lower(): cid for cid, ch in _CHARS.items()}


def get(char_id: str) -> dict | None:
    return _CHARS.get(char_id)


def all_chars() -> dict[str, dict]:
    return _CHARS


def name_index() -> dict[str, str]:
    return _NAME_INDEX
