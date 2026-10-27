from datetime import datetime

_UNITS = (("TB", 10**12), ("GB", 10**9), ("MB", 10**6), ("KB", 10**3))


def format_size(n: int) -> str:
    for unit, factor in _UNITS:
        if n >= factor:
            value = n / factor
            text = f"{value:.0f}" if value >= 100 else f"{value:.1f}".removesuffix(".0")
            return f"{text} {unit}"
    return f"{n} B"


def format_speed(bytes_per_second: float) -> str:
    return f"{format_size(int(bytes_per_second))}/s"


def format_date(dt: datetime) -> str:
    return dt.strftime("%d %b %Y, %H:%M")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'} ago"


def format_ago(dt: datetime | None, now: datetime | None = None) -> str:
    if dt is None:
        return "Never"
    delta = (now or datetime.now()) - dt
    seconds = delta.total_seconds()
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return _plural(int(seconds // 60), "minute")
    if delta.days == 0:
        return _plural(int(seconds // 3600), "hour")
    if delta.days == 1:
        return "Yesterday"
    if delta.days < 30:
        return f"{delta.days} days ago"
    return dt.strftime("%d %b %Y")


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "Estimating…"
    if seconds < 60:
        return "Under 1 min"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"About {minutes} min"
    return f"About {minutes // 60} h {minutes % 60} min"
