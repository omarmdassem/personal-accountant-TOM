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
