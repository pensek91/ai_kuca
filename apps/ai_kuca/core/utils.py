def as_float(value, fallback=None):
    try:
        if value in (None, "unknown", "unavailable"):
            return fallback
        return float(value)
    except Exception:
        return fallback


def is_truthy_state(value):
    return str(value).lower() in ("on", "open", "true", "1")
