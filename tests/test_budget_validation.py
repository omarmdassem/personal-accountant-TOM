import pytest
from datetime import date

from app.models import Budget
from app.domain import BudgetType, RepeatUnit
from app.validators import validate_budget, ValidationError

def _base_budget():
    return Budget(
        user_id=1,
        type=BudgetType.EXPENSE,
        amount_cents=1000,
        currency="EUR",
        category_id=1,
        subcategory_id=None,
    )

def test_one_time_requires_date():
    b = _base_budget()
    b.is_recurring = False
    b.one_time_date = None
    with pytest.raises(ValidationError):
        validate_budget(b)

def test_one_time_ok():
    b = _base_budget()
    b.is_recurring = False
    b.one_time_date = date(2025, 1, 1)
    validate_budget(b)

def test_recurring_monthly_requires_fields():
    b = _base_budget()
    b.is_recurring = True
    b.repeat_unit = RepeatUnit.MONTHLY
    b.repeat_interval = 1
    b.day_of_month = 1
    b.one_time_date = None
    validate_budget(b)

def test_recurring_weekly_requires_weekday():
    b = _base_budget()
    b.is_recurring = True
    b.repeat_unit = RepeatUnit.WEEKLY
    b.repeat_interval = 1
    b.weekday = None
    with pytest.raises(ValidationError):
        validate_budget(b)

def test_recurring_cannot_have_one_time_date():
    b = _base_budget()
    b.is_recurring = True
    b.repeat_unit = RepeatUnit.MONTHLY
    b.repeat_interval = 1
    b.day_of_month = 1
    b.one_time_date = date(2025, 1, 1)
    with pytest.raises(ValidationError):
        validate_budget(b)
