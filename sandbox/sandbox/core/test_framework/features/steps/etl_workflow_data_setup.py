def safe_neq(value, blacklist):
    """True iff value is NOT in blacklist (None-safe)."""
    if blacklist is None:
        return value is not None
    if not isinstance(blacklist, (list, tuple, set)):
        blacklist = [blacklist]
    return value not in blacklist
