def float_safe(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0