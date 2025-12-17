from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user_id
from ..models import Budget, Category, Subcategory
from ..domain import BudgetType
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
    category_id: int,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return HTMLResponse("", status_code=401)

    # Ensure the category belongs to the user
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
def create_budget_one_time(
    request: Request,
    budget_type: BudgetType = Form(...),
    category_id: int = Form(...),
    subcategory_id: str = Form(""),
    amount_eur: str = Form(...),
    currency: str = Form("EUR"),
    one_time_date: date = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    # Validate category belongs to user
    cat = db.exec(
        select(Category).where(Category.id == category_id, Category.user_id == uid)
    ).first()
    if not cat:
        return _render_budget_page(request, uid, db, error="Invalid category.", status_code=400)

    # Parse optional subcategory id
    sub_id = int(subcategory_id) if subcategory_id.strip() else None

    # Validate subcategory belongs to selected category + user
    if sub_id is not None:
        sub = db.exec(
            select(Subcategory).where(
                Subcategory.id == sub_id,
                Subcategory.user_id == uid,
                Subcategory.category_id == category_id,
            )
        ).first()
        if not sub:
            return _render_budget_page(
                request, uid, db, error="Invalid subcategory for selected category.", status_code=400
            )

    # Convert EUR string -> cents
    try:
        amount_cents = euros_to_cents(amount_eur)
    except MoneyParseError as e:
        return _render_budget_page(request, uid, db, error=str(e), status_code=400)

    b = Budget(
        user_id=uid,
        type=budget_type,
        category_id=category_id,
        subcategory_id=sub_id,
        amount_cents=amount_cents,
        currency=currency.strip().upper(),
        is_recurring=False,
        one_time_date=one_time_date,
        note=(note.strip() or None),
    )

    try:
        validate_budget(b)
    except ValidationError as e:
        return _render_budget_page(request, uid, db, error=str(e), status_code=400)

    db.add(b)
    db.commit()

    return RedirectResponse(url="/budget", status_code=303)
