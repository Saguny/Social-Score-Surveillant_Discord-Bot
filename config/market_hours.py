import datetime
from zoneinfo import ZoneInfo

NYSE_TZ = ZoneInfo("America/New_York")


def next_market_event() -> tuple[str, int, int]:
    now      = datetime.datetime.now(NYSE_TZ)
    open_dt  = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_dt = now.replace(hour=16, minute=0, second=0, microsecond=0)
    open_ts  = int(open_dt.timestamp())
    close_ts = int(close_dt.timestamp())
    now_ts   = int(now.timestamp())
    if now.weekday() < 5:
        if now_ts < open_ts:
            return "open", open_ts, open_ts
        if now_ts < close_ts:
            return "close", close_ts, open_ts
    days = 1
    while True:
        nxt = now.date() + datetime.timedelta(days=days)
        if nxt.weekday() < 5:
            nm  = datetime.datetime(nxt.year, nxt.month, nxt.day, 9, 30, tzinfo=NYSE_TZ)
            nts = int(nm.timestamp())
            return "open", nts, open_ts
        days += 1


def market_closed_message() -> str:
    _, next_open_ts, _ = next_market_event()
    return f"Market is closed. Opens <t:{next_open_ts}:R> (<t:{next_open_ts}:f>)."


def last_market_open_ts() -> int:
    now     = datetime.datetime.now(NYSE_TZ)
    open_dt = now.replace(hour=9, minute=30, second=0, microsecond=0)
    open_ts = int(open_dt.timestamp())
    now_ts  = int(now.timestamp())
    if now.weekday() < 5 and now_ts >= open_ts:
        return open_ts
    days = 1
    while True:
        prev = now.date() - datetime.timedelta(days=days)
        if prev.weekday() < 5:
            pm = datetime.datetime(prev.year, prev.month, prev.day, 9, 30, tzinfo=NYSE_TZ)
            return int(pm.timestamp())
        days += 1


def is_market_hours() -> bool:
    now = datetime.datetime.now(NYSE_TZ)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= mins < 16 * 60
