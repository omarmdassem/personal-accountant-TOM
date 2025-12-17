from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

class MoneyParseError(ValueError):
    pass

def euros_to_cents(value: str) -> int:
    """
    Accepts strings like: "12", "12.3", "12.30", " 12.30 "
    Returns integer cents.
    """
    if value is None:
        raise MoneyParseError("Amount is required.")

    s = value.strip().replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise MoneyParseError("Amount must be a number (e.g., 12.99).")

    if d < 0:
        raise MoneyParseError("Amount must be >= 0.")

    cents = (d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)

def cents_to_euros_str(cents: int) -> str:
    d = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))
    return f"{d}"
