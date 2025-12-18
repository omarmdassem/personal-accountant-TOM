from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user_id
from ..domain import BudgetType
from ..models import Category, Subcategory, Transaction
from ..money import MoneyParseError, cents_to_euros_str, euros_to_cents

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _load_transactions_page_data(db: Session, uid: int):
    categories = db.exec(
        select(Category).where(Category.user_id == uid).order_by(Category.name)
    ).all()

    subcategories = db.exec(
        select(Subcategory).where(Subcategory.user_id == uid).order_by(Subcategory.name)
    ).all()

    transactions = db.exec(
        select(Transaction)
        .where(Transaction.user_id == uid)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
    ).all()

    categories_by_id = {c.id: c for c in categories}
    subcategories_by_id = {s.id: s for s in subcategories}

    return categories, transactions, categories_by_id, subcategories_by_id


def _render_transactions_page(
    request: Request,
    uid: int,
    db: Session,
    error: str | None = None,
    status_code: int = 200,
):
    categories, transactions, categories_by_id, subcategories_by_id = _load_transactions_page_data(
        db, uid
    )

    return templates.TemplateResponse(
        "transactions.html",
        {
            "request": request,
            "title": "Transactions",
            "user_id": uid,
            "categories": categories,
            "transactions": transactions,
            "categories_by_id": categories_by_id,
            "subcategories_by_id": subcategories_by_id,
            "error": error,
            "cents_to_euros_str": cents_to_euros_str,
        },
        status_code=status_code,
    )


@router.get("/transactions")
def transactions_redirect():
    return RedirectResponse(url="/transaction", status_code=303)


@router.get("/transaction", response_class=HTMLResponse)
def list_transactions(
    request: Request,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)
    return _render_transactions_page(request, uid, db)


@router.post("/transaction")
def create_transaction(
    request: Request,
    # Must match HTML form field names:
    date: date | None = Form(None),
    type: str = Form(...),
    category_id: str = Form(""),
    subcategory_id: str = Form(""),
    description: str = Form(""),
    amount_eur: str = Form(...),
    currency: str = Form("EUR"),
    note: str = Form(""),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    if date is None:
        return _render_transactions_page(request, uid, db, error="Date is required.", status_code=400)

    type_norm = (type or "").strip().lower()
    if type_norm not in ("income", "expense"):
        return _render_transactions_page(
            request, uid, db, error="Type must be income or expense.", status_code=400
        )

    if not category_id.strip():
        return _render_transactions_page(request, uid, db, error="Category is required.", status_code=400)

    try:
        category_id_int = int(category_id)
    except ValueError:
        return _render_transactions_page(request, uid, db, error="Invalid category.", status_code=400)

    cat = db.exec(
        select(Category).where(Category.id == category_id_int, Category.user_id == uid)
    ).first()
    if not cat:
        return _render_transactions_page(request, uid, db, error="Invalid category.", status_code=400)

    sub_id: int | None = None
    if subcategory_id.strip():
        try:
            sub_id = int(subcategory_id)
        except ValueError:
            return _render_transactions_page(request, uid, db, error="Invalid subcategory.", status_code=400)

        sub = db.exec(
            select(Subcategory).where(
                Subcategory.id == sub_id,
                Subcategory.user_id == uid,
                Subcategory.category_id == category_id_int,
            )
        ).first()
        if not sub:
            return _render_transactions_page(
                request,
                uid,
                db,
                error="Invalid subcategory for selected category.",
                status_code=400,
            )

    try:
        amount_cents = euros_to_cents(amount_eur)
    except MoneyParseError as e:
        return _render_transactions_page(request, uid, db, error=str(e), status_code=400)

    t = Transaction(
        user_id=uid,
        date=date,
        type=BudgetType(type_norm),
        category_id=category_id_int,
        subcategory_id=sub_id,
        description=(description.strip() or None),
        amount_cents=amount_cents,
        currency=(currency.strip().upper() or "EUR"),
        note=(note.strip() or None),
    )

    db.add(t)
    db.commit()

    return RedirectResponse(url="/transaction", status_code=303)
