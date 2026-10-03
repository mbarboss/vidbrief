"""Durations written the way people say them."""


def describe_duration(seconds: int) -> str:
    """Render a duration limit exactly, e.g. ``2 hours``, ``90 minutes`` or ``90 seconds``."""
    if seconds >= 3600 and seconds % 3600 == 0:
        return _plural(seconds // 3600, "hour")
    if seconds >= 60 and seconds % 60 == 0:
        return _plural(seconds // 60, "minute")
    return _plural(seconds, "second")


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
