from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user_id
from ..models import Budget, Category, Subcategory, Transaction
from ..money import cents_to_euros_str
from ..domain import BudgetType  # for display normalization


router = APIRouter()
templates = Jinja2Templates(directory="templates")


@dataclass(frozen=True)
class DashboardFilters:
    year: int
    month: int  # 1..12


def _month_start(y: int, m: int) -> date:
    return date(y, m, 1)


def _next_month_start(d: date) -> date:
    # first day of next month
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _months_diff(a: date, b: date) -> int:
    """How many whole months from a -> b (b can be >= a)."""
    return (b.year - a.year) * 12 + (b.month - a.month)


def _as_str_type(t) -> str:
    # handles Enum values like BudgetType.EXPENSE or TransactionType.EXPENSE
    if hasattr(t, "value"):
        return str(t.value)
    return str(t)


def _budget_planned_amount_for_month(b: Budget, month_start: date, month_end: date) -> int:
    """
    Returns planned amount_cents contributed by this budget in [month_start, month_end] inclusive.
    MVP supports:
      - one-time: if one_time_date in month
      - recurring monthly/yearly/weekly (reasonable approximations)
    """
    # One-time
    if not getattr(b, "is_recurring", False):
        d = getattr(b, "one_time_date", None)
        if d and month_start <= d <= month_end:
            return int(b.amount_cents or 0)
        return 0

    # Recurring window check
    start_d = getattr(b, "start_date", None)
    end_d = getattr(b, "end_date", None)
    if start_d and month_end < start_d:
        return 0
    if end_d and month_start > end_d:
        return 0

    ru = getattr(b, "repeat_unit", None)
    ru_val = ru.value if hasattr(ru, "value") else (str(ru) if ru else "")
    interval = int(getattr(b, "repeat_interval", 1) or 1)

    # MONTHLY: count = 1 if this month matches interval (based on start_date), else 0
    if ru_val == "monthly":
        if start_d:
            diff = _months_diff(start_d, month_start)
            if diff < 0:
                return 0
            if diff % interval != 0:
                return 0
        return int(b.amount_cents or 0)

    # YEARLY: include if month matches start_date month (or if start_date missing, treat as every year in current month)
    if ru_val == "yearly":
        if start_d and start_d.month != month_start.month:
            return 0
        # interval in years: approximate by checking year difference when start_date present
        if start_d:
            year_diff = month_start.year - start_d.year
            if year_diff < 0:
                return 0
            if (year_diff % interval) != 0:
                return 0
        return int(b.amount_cents or 0)

    # WEEKLY: approximate occurrences of weekday in this month
    if ru_val == "weekly":
        weekday = getattr(b, "weekday", None)
        if weekday is None:
            return 0

        # Count how many times that weekday appears in month
        cur = month_start
        # move to first matching weekday
        while cur.weekday() != int(weekday) and cur <= month_end:
            cur += timedelta(days=1)

        occurrences = 0
        while cur <= month_end:
            occurrences += 1
            cur += timedelta(days=7)

        # interval in weeks: approximate by dividing occurrences
        if interval > 1:
            occurrences = (occurrences + (interval - 1)) // interval

        return int(b.amount_cents or 0) * occurrences

    # Unknown repeat_unit => treat as 0 (safe)
    return 0


def _load_dashboard_data(db: Session, uid: int, month_start: date, next_month: date):
    cats = db.exec(select(Category).where(Category.user_id == uid).order_by(Category.name)).all()
    subs = db.exec(select(Subcategory).where(Subcategory.user_id == uid).order_by(Subcategory.name)).all()

    categories_by_id = {c.id: c for c in cats}
    subcategories_by_id = {s.id: s for s in subs}

    txs = db.exec(
        select(Transaction)
        .where(Transaction.user_id == uid, Transaction.date >= month_start, Transaction.date < next_month)
        .order_by(Transaction.date.desc())
    ).all()

    budgets = db.exec(select(Budget).where(Budget.user_id == uid).order_by(Budget.created_at.desc())).all()

    return cats, subs, txs, budgets, categories_by_id, subcategories_by_id


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    today = date.today()
    y = int(year or today.year)
    m = int(month or today.month)
    if m < 1 or m > 12:
        m = today.month

    filters = DashboardFilters(year=y, month=m)

    ms = _month_start(y, m)
    nm = _next_month_start(ms)
    me = nm - timedelta(days=1)

    cats, subs, txs, budgets, categories_by_id, subcategories_by_id = _load_dashboard_data(db, uid, ms, nm)

    # -------- ACTUALS (transactions) --------
    actual_income = 0
    actual_expense = 0

    actual_by_cat_expense: dict[str, int] = {}
    actual_by_cat_income: dict[str, int] = {}
    daily_net: dict[str, int] = {}  # YYYY-MM-DD -> cents

    for t in txs:
        ttype = _as_str_type(getattr(t, "type", ""))
        amt = int(getattr(t, "amount_cents", 0) or 0)
        cat = categories_by_id.get(getattr(t, "category_id", None))
        cat_name = cat.name if cat else f"Category {getattr(t,'category_id', '')}"

        dkey = t.date.isoformat()
        daily_net.setdefault(dkey, 0)

        if ttype == "income":
            actual_income += amt
            actual_by_cat_income[cat_name] = actual_by_cat_income.get(cat_name, 0) + amt
            daily_net[dkey] += amt
        else:
            actual_expense += amt
            actual_by_cat_expense[cat_name] = actual_by_cat_expense.get(cat_name, 0) + amt
            daily_net[dkey] -= amt

    actual_net = actual_income - actual_expense

    # -------- PLANNED (budgets) --------
    planned_income = 0
    planned_expense = 0
    planned_by_cat_expense: dict[str, int] = {}
    planned_by_cat_income: dict[str, int] = {}

    for b in budgets:
        btype = _as_str_type(getattr(b, "type", ""))
        amt = _budget_planned_amount_for_month(b, ms, me)
        if amt == 0:
            continue

        cat = categories_by_id.get(getattr(b, "category_id", None))
        cat_name = cat.name if cat else f"Category {getattr(b,'category_id', '')}"

        if btype == "income":
            planned_income += amt
            planned_by_cat_income[cat_name] = planned_by_cat_income.get(cat_name, 0) + amt
        else:
            planned_expense += amt
            planned_by_cat_expense[cat_name] = planned_by_cat_expense.get(cat_name, 0) + amt

    planned_net = planned_income - planned_expense

    # -------- CHART DATA --------
    # Expense by category: union of categories in actual/planned
    expense_cats = sorted(set(planned_by_cat_expense.keys()) | set(actual_by_cat_expense.keys()))
    chart_expense = {
        "labels": expense_cats,
        "planned": [planned_by_cat_expense.get(c, 0) / 100.0 for c in expense_cats],
        "actual": [actual_by_cat_expense.get(c, 0) / 100.0 for c in expense_cats],
    }

    # Daily net trend: fill all days in month
    labels_days = []
    values_days = []
    cur = ms
    while cur <= me:
        k = cur.isoformat()
        labels_days.append(k)
        values_days.append((daily_net.get(k, 0)) / 100.0)
        cur += timedelta(days=1)

    chart_daily_net = {"labels": labels_days, "values": values_days}

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Dashboard",
            "user_id": uid,
            "filters": filters,
            "month_start": ms,
            "month_end": me,
            "cents_to_euros_str": cents_to_euros_str,
            "actual_income": actual_income,
            "actual_expense": actual_expense,
            "actual_net": actual_net,
            "planned_income": planned_income,
            "planned_expense": planned_expense,
            "planned_net": planned_net,
            "chart_expense_json": json.dumps(chart_expense),
            "chart_daily_net_json": json.dumps(chart_daily_net),
        },
    )
