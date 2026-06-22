import datetime
from zoneinfo import ZoneInfo

EXCHANGE_TZ = {
    "NYSE": ZoneInfo("America/New_York"),
    "LSE":  ZoneInfo("Europe/London"),
    "TSE":  ZoneInfo("Asia/Tokyo"),
}

EXCHANGE_SESSIONS = {
    "NYSE": [((9, 30), (16, 0))],
    "LSE":  [((8, 0), (16, 30))],
    "TSE":  [((9, 0), (11, 30)), ((12, 30), (15, 0))],
}

EXCHANGE_NAMES = {
    "NYSE": "New York Stock Exchange",
    "LSE":  "London Stock Exchange",
    "TSE":  "Tokyo Stock Exchange",
}

NYSE_TZ = EXCHANGE_TZ["NYSE"]


def _session_bounds(now: datetime.datetime, session: tuple) -> tuple[datetime.datetime, datetime.datetime]:
    (oh, om), (ch, cm) = session
    open_dt  = now.replace(hour=oh, minute=om, second=0, microsecond=0)
    close_dt = now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    return open_dt, close_dt


def is_market_hours(exchange: str = "NYSE") -> bool:
    tz  = EXCHANGE_TZ[exchange]
    now = datetime.datetime.now(tz)
    if now.weekday() >= 5:
        return False
    for session in EXCHANGE_SESSIONS[exchange]:
        open_dt, close_dt = _session_bounds(now, session)
        if open_dt <= now < close_dt:
            return True
    return False


def next_market_event(exchange: str = "NYSE") -> tuple[str, int, int]:
    tz       = EXCHANGE_TZ[exchange]
    now      = datetime.datetime.now(tz)
    sessions = EXCHANGE_SESSIONS[exchange]
    today_first_open, _ = _session_bounds(now, sessions[0])

    if now.weekday() < 5:
        for session in sessions:
            open_dt, close_dt = _session_bounds(now, session)
            if now < open_dt:
                return "open", int(open_dt.timestamp()), int(today_first_open.timestamp())
            if now < close_dt:
                return "close", int(close_dt.timestamp()), int(today_first_open.timestamp())

    days = 1
    while True:
        nxt = now.date() + datetime.timedelta(days=days)
        if nxt.weekday() < 5:
            (oh, om), _ = sessions[0]
            nm = datetime.datetime(nxt.year, nxt.month, nxt.day, oh, om, tzinfo=tz)
            return "open", int(nm.timestamp()), int(today_first_open.timestamp())
        days += 1


def market_closed_message(exchange: str = "NYSE") -> str:
    _, next_open_ts, _ = next_market_event(exchange)
    name = EXCHANGE_NAMES.get(exchange, exchange)
    return f"{name} is closed. Opens <t:{next_open_ts}:R> (<t:{next_open_ts}:f>)."


def last_market_open_ts(exchange: str = "NYSE") -> int:
    tz       = EXCHANGE_TZ[exchange]
    now      = datetime.datetime.now(tz)
    sessions = EXCHANGE_SESSIONS[exchange]
    first_open, _ = _session_bounds(now, sessions[0])
    if now.weekday() < 5 and now >= first_open:
        return int(first_open.timestamp())
    days = 1
    while True:
        prev = now.date() - datetime.timedelta(days=days)
        if prev.weekday() < 5:
            (oh, om), _ = sessions[0]
            pm = datetime.datetime(prev.year, prev.month, prev.day, oh, om, tzinfo=tz)
            return int(pm.timestamp())
        days += 1


def all_exchange_status() -> dict[str, dict]:
    status = {}
    for exchange in EXCHANGE_TZ:
        open_now = is_market_hours(exchange)
        event, ts, _ = next_market_event(exchange)
        status[exchange] = {"open": open_now, "next_event": event, "next_ts": ts}
    return status
