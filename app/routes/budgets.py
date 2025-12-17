from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user_id
from ..models import Budget, Category, Subcategory
from ..domain import BudgetType, RepeatUnit
from ..validators import validate_budget, ValidationError
from ..money import euros_to_cents, cents_to_euros_str, MoneyParseError

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _load_budget_page_data(db: Session, uid: int):
    categories = db.exec(
        select(Category).where(Category.user_id == uid).order_by(Category.name)
    ).all()

    subcategories = db.exec(
        select(Subcategory).where(Subcategory.user_id == uid).order_by(Subcategory.name)
    ).all()

    budgets = db.exec(
        select(Budget).where(Budget.user_id == uid).order_by(Budget.created_at.desc())
    ).all()

    categories_by_id = {c.id: c for c in categories}
    subcategories_by_id = {s.id: s for s in subcategories}

    return categories, budgets, categories_by_id, subcategories_by_id


def _render_budget_page(
    request: Request,
    uid: int,
    db: Session,
    error: str | None = None,
    status_code: int = 200,
):
    categories, budgets, categories_by_id, subcategories_by_id = _load_budget_page_data(db, uid)

    return templates.TemplateResponse(
        "budget.html",
        {
            "request": request,
            "title": "Budget",
            "user_id": uid,
            "categories": categories,
            "budgets": budgets,
            "categories_by_id": categories_by_id,
            "subcategories_by_id": subcategories_by_id,
            "error": error,
            "cents_to_euros_str": cents_to_euros_str,
        },
        status_code=status_code,
    )


@router.get("/budgets")
def budgets_redirect():
    return RedirectResponse(url="/budget", status_code=303)


@router.get("/budget", response_class=HTMLResponse)
def list_budget(
    request: Request,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    return _render_budget_page(request, uid, db)


@router.get("/budget/subcategories", response_class=HTMLResponse)
def budget_subcategories(
    request: Request,
    category_id: int | None = None,  # allow missing (page load before selection)
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return HTMLResponse("", status_code=401)

    if not category_id:
        return HTMLResponse('<option value="">(none)</option>', status_code=200)

    # Ensure category belongs to the user
    cat = db.exec(
        select(Category).where(Category.id == category_id, Category.user_id == uid)
    ).first()
    if not cat:
        return HTMLResponse('<option value="">(none)</option>', status_code=200)

    subs = db.exec(
        select(Subcategory)
        .where(Subcategory.user_id == uid, Subcategory.category_id == category_id)
        .order_by(Subcategory.name)
    ).all()

    options = ['<option value="">(none)</option>']
    for s in subs:
        label = f"{s.icon or ''} {s.name}".strip()
        options.append(f'<option value="{s.id}">{label}</option>')

    return HTMLResponse("\n".join(options), status_code=200)


@router.post("/budget")
def create_budget(
    request: Request,
    budget_type: BudgetType = Form(...),

    category_id: str = Form(""),          # validate ourselves (no JSON leak)
    subcategory_id: str = Form(""),

    amount_eur: str = Form(...),
    currency: str = Form("EUR"),

    # One-time (optional; required only if not recurring)
    one_time_date: date | None = Form(None),

    # Recurring
    is_recurring: str = Form(""),         # checkbox => "on"
    repeat_unit: str = Form(""),
    repeat_interval: str = Form(""),
    day_of_month: str = Form(""),
    weekday: str = Form(""),
    start_date: date | None = Form(None),
    end_date: date | None = Form(None),

    note: str = Form(""),

    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    # ---- category validation (prevents FastAPI JSON errors in browser) ----
    if not category_id.strip():
        return _render_budget_page(request, uid, db, error="Category is required.", status_code=400)

    try:
        category_id_int = int(category_id)
    except ValueError:
        return _render_budget_page(request, uid, db, error="Invalid category.", status_code=400)

    cat = db.exec(
        select(Category).where(Category.id == category_id_int, Category.user_id == uid)
    ).first()
    if not cat:
        return _render_budget_page(request, uid, db, error="Invalid category.", status_code=400)

    # ---- subcategory validation (optional) ----
    sub_id: int | None = None
    if subcategory_id.strip():
        try:
            sub_id = int(subcategory_id)
        except ValueError:
            return _render_budget_page(request, uid, db, error="Invalid subcategory.", status_code=400)

        sub = db.exec(
            select(Subcategory).where(
                Subcategory.id == sub_id,
                Subcategory.user_id == uid,
                Subcategory.category_id == category_id_int,
            )
        ).first()
        if not sub:
            return _render_budget_page(
                request, uid, db, error="Invalid subcategory for selected category.", status_code=400
            )

    # ---- money parsing ----
    try:
        amount_cents = euros_to_cents(amount_eur)
    except MoneyParseError as e:
        return _render_budget_page(request, uid, db, error=str(e), status_code=400)

    # ---- recurrence parsing ----
    recurring = is_recurring.strip().lower() in ("on", "true", "1", "yes")

    ru: RepeatUnit | None = None
    if recurring and repeat_unit.strip():
        try:
            ru = RepeatUnit(repeat_unit.strip().lower())
        except ValueError:
            return _render_budget_page(request, uid, db, error="Invalid repeat_unit.", status_code=400)

    ri: int | None = None
    if recurring and repeat_interval.strip():
        try:
            ri = int(repeat_interval)
        except ValueError:
            return _render_budget_page(request, uid, db, error="Interval must be a number.", status_code=400)

    dom: int | None = None
    if recurring and day_of_month.strip():
        try:
            dom = int(day_of_month)
        except ValueError:
            return _render_budget_page(request, uid, db, error="Day of month must be a number.", status_code=400)

    wd: int | None = None
    if recurring and weekday.strip():
        try:
            wd = int(weekday)
        except ValueError:
            return _render_budget_page(request, uid, db, error="Weekday must be a number.", status_code=400)

    # If NOT recurring, require date (nice error, not JSON)
    if not recurring and one_time_date is None:
        return _render_budget_page(
            request, uid, db, error="Date is required for one-time budget.", status_code=400
        )

    b = Budget(
        user_id=uid,
        type=budget_type,
        category_id=category_id_int,
        subcategory_id=sub_id,

        amount_cents=amount_cents,
        currency=currency.strip().upper(),

        is_recurring=recurring,

        # one-time
        one_time_date=None if recurring else one_time_date,

        # recurring
        repeat_unit=ru if recurring else None,
        repeat_interval=ri if recurring else None,
        day_of_month=dom if recurring else None,
        weekday=wd if recurring else None,
        start_date=start_date if recurring else None,
        end_date=end_date if recurring else None,

        note=(note.strip() or None),
    )

    try:
        validate_budget(b)
    except ValidationError as e:
        return _render_budget_page(request, uid, db, error=str(e), status_code=400)

    db.add(b)
    db.commit()

    return RedirectResponse(url="/budget", status_code=303)
