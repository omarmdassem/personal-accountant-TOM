from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user_id
from ..models import Budget, Category
from ..domain import BudgetType
from ..validators import validate_budget, ValidationError
from ..money import euros_to_cents, cents_to_euros_str, MoneyParseError

router = APIRouter()
templates = Jinja2Templates(directory="templates")


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

    cats = db.exec(select(Category).where(Category.user_id == uid).order_by(Category.name)).all()
    budget_items = db.exec(
        select(Budget).where(Budget.user_id == uid).order_by(Budget.created_at.desc())
    ).all()

    return templates.TemplateResponse(
        "budget.html",
        {
            "request": request,
            "title": "Budget",
            "user_id": uid,
            "categories": cats,
            "budgets": budget_items,
            "error": None,
            "cents_to_euros_str": cents_to_euros_str,
        },
    )


@router.post("/budget")
def create_budget_one_time(
    request: Request,
    budget_type: BudgetType = Form(...),
    category_id: int = Form(...),
    amount_eur: str = Form(...),
    currency: str = Form("EUR"),
    one_time_date: date = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    try:
        amount_cents = euros_to_cents(amount_eur)
    except MoneyParseError as e:
        cats = db.exec(select(Category).where(Category.user_id == uid).order_by(Category.name)).all()
        budget_items = db.exec(
            select(Budget).where(Budget.user_id == uid).order_by(Budget.created_at.desc())
        ).all()
        return templates.TemplateResponse(
            "budget.html",
            {
                "request": request,
                "title": "Budget",
                "user_id": uid,
                "categories": cats,
                "budgets": budget_items,
                "error": str(e),
                "cents_to_euros_str": cents_to_euros_str,
            },
            status_code=400,
        )

    b = Budget(
        user_id=uid,
        type=budget_type,
        category_id=category_id,
        subcategory_id=None,
        amount_cents=amount_cents,
        currency=currency.strip().upper(),
        is_recurring=False,
        one_time_date=one_time_date,
        note=(note.strip() or None),
    )

    try:
        validate_budget(b)
    except ValidationError as e:
        cats = db.exec(select(Category).where(Category.user_id == uid).order_by(Category.name)).all()
        budget_items = db.exec(
            select(Budget).where(Budget.user_id == uid).order_by(Budget.created_at.desc())
        ).all()
        return templates.TemplateResponse(
            "budget.html",
            {
                "request": request,
                "title": "Budget",
                "user_id": uid,
                "categories": cats,
                "budgets": budget_items,
                "error": str(e),
                "cents_to_euros_str": cents_to_euros_str,
            },
            status_code=400,
        )

    db.add(b)
    db.commit()

    return RedirectResponse(url="/budget", status_code=303)
