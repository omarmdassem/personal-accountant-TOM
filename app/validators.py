from .models import Budget
from .domain import RepeatUnit

class ValidationError(ValueError):
    pass

def validate_budget(b: Budget) -> None:
    if b.is_recurring:
        if b.one_time_date is not None:
            raise ValidationError("Recurring budget must not have one_time_date.")

        if b.repeat_unit is None:
            raise ValidationError("Recurring budget requires repeat_unit.")
        if not b.repeat_interval or b.repeat_interval < 1:
            raise ValidationError("Recurring budget requires repeat_interval >= 1.")

        if b.repeat_unit == RepeatUnit.WEEKLY:
            if b.weekday is None or not (0 <= b.weekday <= 6):
                raise ValidationError("Weekly recurring budget requires weekday (0=Mon..6=Sun).")
            if b.day_of_month is not None:
                raise ValidationError("Weekly recurring budget must not have day_of_month.")

        if b.repeat_unit in (RepeatUnit.MONTHLY, RepeatUnit.YEARLY):
            if b.day_of_month is None or not (1 <= b.day_of_month <= 31):
                raise ValidationError("Monthly/Yearly recurring budget requires day_of_month (1..31).")
            if b.weekday is not None:
                raise ValidationError("Monthly/Yearly recurring budget must not have weekday.")
    else:
        if b.one_time_date is None:
            raise ValidationError("One-time budget requires one_time_date.")
        # recurrence fields should be empty
        if any([b.repeat_unit, b.repeat_interval, b.day_of_month, b.weekday, b.start_date, b.end_date]):
            raise ValidationError("One-time budget must not have recurrence fields.")

def validate_transaction(t) -> None:
    """
    Basic transaction validation (DB-independent).
    Expects a Transaction-like object with attributes:
      - date, type, category_id, amount_cents, currency, description
      - optional: subcategory_id, note
    """
    # date
    if getattr(t, "date", None) is None:
        raise ValidationError("Date is required.")

    # type
    tx_type = getattr(t, "type", None)
    if tx_type is None:
        raise ValidationError("Type is required (income/expense).")
    tx_type_val = getattr(tx_type, "value", str(tx_type))
    if str(tx_type_val) not in ("income", "expense"):
        raise ValidationError("Type must be 'income' or 'expense'.")

    # category
    cat_id = getattr(t, "category_id", None)
    if cat_id is None or (isinstance(cat_id, int) and cat_id <= 0):
        raise ValidationError("Category is required.")

    # amount
    amount_cents = getattr(t, "amount_cents", None)
    if amount_cents is None:
        raise ValidationError("Amount is required.")
    try:
        amount_int = int(amount_cents)
    except Exception:
        raise ValidationError("Amount is invalid.")
    if amount_int <= 0:
        raise ValidationError("Amount must be greater than 0.")

    # currency
    currency = (getattr(t, "currency", None) or "").strip().upper()
    if not currency:
        raise ValidationError("Currency is required.")

    # description
    desc = (getattr(t, "description", None) or "").strip()
    if not desc:
        raise ValidationError("Description is required.")

