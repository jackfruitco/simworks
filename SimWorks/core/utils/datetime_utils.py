def to_ms(value):
    """
    Convert a datetime or timedelta to milliseconds (int).
    Returns None if value is None.
    """
    if value is None:
        return None
    if hasattr(value, "timestamp"):  # datetime
        return int(value.timestamp() * 1000)
    if hasattr(value, "total_seconds"):  # timedelta
        return int(value.total_seconds() * 1000)
    raise TypeError(f"Cannot convert {type(value)} to milliseconds.")