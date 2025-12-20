from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user_id
from ..models import Category, Subcategory, Budget, Transaction

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _redirect_login():
    return RedirectResponse(url="/login", status_code=303)


def _categories_for_user(db: Session, uid: int) -> list[Category]:
    return db.exec(
        select(Category).where(Category.user_id == uid).order_by(Category.name)
    ).all()


def _subcategories_for_category(db: Session, uid: int, category_id: int) -> list[Subcategory]:
    return db.exec(
        select(Subcategory)
        .where(Subcategory.user_id == uid, Subcategory.category_id == category_id)
        .order_by(Subcategory.name)
    ).all()


@router.get("/categories", response_class=HTMLResponse)
def categories_page(
    request: Request,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return _redirect_login()

    categories = _categories_for_user(db, uid)
    return templates.TemplateResponse(
        "categories.html",
        {"request": request, "title": "Categories", "user_id": uid, "categories": categories, "error": None},
    )


@router.post("/categories", response_class=HTMLResponse)
def create_category(
    request: Request,
    name: str = Form(...),
    icon: str = Form(""),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return _redirect_login()

    name = (name or "").strip()
    icon = (icon or "").strip() or None

    if not name:
        categories = _categories_for_user(db, uid)
        return templates.TemplateResponse(
            "categories.html",
            {"request": request, "title": "Categories", "user_id": uid, "categories": categories, "error": "Name is required."},
            status_code=400,
        )

    existing = db.exec(
        select(Category).where(Category.user_id == uid, Category.name == name)
    ).first()
    if existing:
        categories = _categories_for_user(db, uid)
        return templates.TemplateResponse(
            "categories.html",
            {"request": request, "title": "Categories", "user_id": uid, "categories": categories, "error": "Category already exists."},
            status_code=400,
        )

    c = Category(user_id=uid, name=name, icon=icon)
    db.add(c)
    db.commit()

    # return list page (tests expect 200 + content)
    categories = _categories_for_user(db, uid)
    return templates.TemplateResponse(
        "categories.html",
        {"request": request, "title": "Categories", "user_id": uid, "categories": categories, "error": None},
    )


@router.get("/categories/{category_id}/edit", response_class=HTMLResponse)
def edit_category_form(
    request: Request,
    category_id: int,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return _redirect_login()

    cat = db.exec(select(Category).where(Category.id == category_id, Category.user_id == uid)).first()
    if not cat:
        return RedirectResponse(url="/categories", status_code=303)

    return templates.TemplateResponse(
        "category_edit.html",
        {"request": request, "title": "Edit Category", "user_id": uid, "category": cat, "error": None},
    )


@router.post("/categories/{category_id}/edit", response_class=HTMLResponse)
def edit_category_submit(
    request: Request,
    category_id: int,
    name: str = Form(...),
    icon: str = Form(""),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return _redirect_login()

    cat = db.exec(select(Category).where(Category.id == category_id, Category.user_id == uid)).first()
    if not cat:
        return RedirectResponse(url="/categories", status_code=303)

    name = (name or "").strip()
    icon = (icon or "").strip() or None

    if not name:
        return templates.TemplateResponse(
            "category_edit.html",
            {"request": request, "title": "Edit Category", "user_id": uid, "category": cat, "error": "Name is required."},
            status_code=400,
        )

    duplicate = db.exec(
        select(Category).where(Category.user_id == uid, Category.name == name, Category.id != category_id)
    ).first()
    if duplicate:
        return templates.TemplateResponse(
            "category_edit.html",
            {"request": request, "title": "Edit Category", "user_id": uid, "category": cat, "error": "Another category with this name already exists."},
            status_code=400,
        )

    cat.name = name
    cat.icon = icon
    db.add(cat)
    db.commit()

    return RedirectResponse(url="/categories", status_code=303)


@router.post("/categories/{category_id}/delete")
def delete_category_hard(
    category_id: int,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    """
    HARD DELETE:
    - deletes budgets + transactions for this category (and its subcategories)
    - deletes subcategories
    - deletes the category
    """
    if not uid:
        return _redirect_login()

    cat = db.exec(select(Category).where(Category.id == category_id, Category.user_id == uid)).first()
    if not cat:
        return RedirectResponse(url="/categories", status_code=303)

    # subcategories
    subs = _subcategories_for_category(db, uid, category_id)
    sub_ids = [s.id for s in subs]

    # delete budgets/transactions by subcategory first
    if sub_ids:
        budgets_sub = db.exec(
            select(Budget).where(Budget.user_id == uid, Budget.subcategory_id.in_(sub_ids))
        ).all()
        for b in budgets_sub:
            db.delete(b)

        tx_sub = db.exec(
            select(Transaction).where(Transaction.user_id == uid, Transaction.subcategory_id.in_(sub_ids))
        ).all()
        for t in tx_sub:
            db.delete(t)

    # delete budgets/transactions by category
    budgets_cat = db.exec(
        select(Budget).where(Budget.user_id == uid, Budget.category_id == category_id)
    ).all()
    for b in budgets_cat:
        db.delete(b)

    tx_cat = db.exec(
        select(Transaction).where(Transaction.user_id == uid, Transaction.category_id == category_id)
    ).all()
    for t in tx_cat:
        db.delete(t)

    # delete subcategories
    for s in subs:
        db.delete(s)

    # delete category
    db.delete(cat)

    db.commit()
    return RedirectResponse(url="/categories", status_code=303)


@router.get("/categories/{category_id}/subcategories", response_class=HTMLResponse)
def subcategories_page(
    request: Request,
    category_id: int,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return _redirect_login()

    cat = db.exec(select(Category).where(Category.id == category_id, Category.user_id == uid)).first()
    if not cat:
        return RedirectResponse(url="/categories", status_code=303)

    subs = _subcategories_for_category(db, uid, category_id)
    return templates.TemplateResponse(
        "subcategories.html",
        {"request": request, "title": "Subcategories", "user_id": uid, "category": cat, "subcategories": subs, "error": None},
    )


@router.post("/categories/{category_id}/subcategories", response_class=HTMLResponse)
def create_subcategory(
    request: Request,
    category_id: int,
    name: str = Form(...),
    icon: str = Form(""),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return _redirect_login()

    cat = db.exec(select(Category).where(Category.id == category_id, Category.user_id == uid)).first()
    if not cat:
        return RedirectResponse(url="/categories", status_code=303)

    name = (name or "").strip()
    icon = (icon or "").strip() or None

    subs = _subcategories_for_category(db, uid, category_id)

    if not name:
        return templates.TemplateResponse(
            "subcategories.html",
            {"request": request, "title": "Subcategories", "user_id": uid, "category": cat, "subcategories": subs, "error": "Name is required."},
            status_code=400,
        )

    existing = db.exec(
        select(Subcategory).where(Subcategory.user_id == uid, Subcategory.category_id == category_id, Subcategory.name == name)
    ).first()
    if existing:
        return templates.TemplateResponse(
            "subcategories.html",
            {"request": request, "title": "Subcategories", "user_id": uid, "category": cat, "subcategories": subs, "error": "Subcategory already exists."},
            status_code=400,
        )

    s = Subcategory(user_id=uid, category_id=category_id, name=name, icon=icon)
    db.add(s)
    db.commit()

    subs = _subcategories_for_category(db, uid, category_id)
    return templates.TemplateResponse(
        "subcategories.html",
        {"request": request, "title": "Subcategories", "user_id": uid, "category": cat, "subcategories": subs, "error": None},
    )


@router.get("/categories/{category_id}/subcategories/{subcategory_id}/edit", response_class=HTMLResponse)
def edit_subcategory_form(
    request: Request,
    category_id: int,
    subcategory_id: int,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return _redirect_login()

    cat = db.exec(select(Category).where(Category.id == category_id, Category.user_id == uid)).first()
    if not cat:
        return RedirectResponse(url="/categories", status_code=303)

    sub = db.exec(
        select(Subcategory).where(
            Subcategory.id == subcategory_id,
            Subcategory.user_id == uid,
            Subcategory.category_id == category_id,
        )
    ).first()
    if not sub:
        return RedirectResponse(url=f"/categories/{category_id}/subcategories", status_code=303)

    return templates.TemplateResponse(
        "subcategory_edit.html",
        {"request": request, "title": "Edit Subcategory", "user_id": uid, "category": cat, "subcategory": sub, "error": None},
    )


@router.post("/categories/{category_id}/subcategories/{subcategory_id}/edit", response_class=HTMLResponse)
def edit_subcategory_submit(
    request: Request,
    category_id: int,
    subcategory_id: int,
    name: str = Form(...),
    icon: str = Form(""),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return _redirect_login()

    cat = db.exec(select(Category).where(Category.id == category_id, Category.user_id == uid)).first()
    if not cat:
        return RedirectResponse(url="/categories", status_code=303)

    sub = db.exec(
        select(Subcategory).where(
            Subcategory.id == subcategory_id,
            Subcategory.user_id == uid,
            Subcategory.category_id == category_id,
        )
    ).first()
    if not sub:
        return RedirectResponse(url=f"/categories/{category_id}/subcategories", status_code=303)

    name = (name or "").strip()
    icon = (icon or "").strip() or None

    if not name:
        return templates.TemplateResponse(
            "subcategory_edit.html",
            {"request": request, "title": "Edit Subcategory", "user_id": uid, "category": cat, "subcategory": sub, "error": "Name is required."},
            status_code=400,
        )

    duplicate = db.exec(
        select(Subcategory).where(
            Subcategory.user_id == uid,
            Subcategory.category_id == category_id,
            Subcategory.name == name,
            Subcategory.id != subcategory_id,
        )
    ).first()
    if duplicate:
        return templates.TemplateResponse(
            "subcategory_edit.html",
            {"request": request, "title": "Edit Subcategory", "user_id": uid, "category": cat, "subcategory": sub, "error": "Another subcategory with this name already exists."},
            status_code=400,
        )

    sub.name = name
    sub.icon = icon
    db.add(sub)
    db.commit()

    return RedirectResponse(url=f"/categories/{category_id}/subcategories", status_code=303)


@router.post("/categories/{category_id}/subcategories/{subcategory_id}/delete")
def delete_subcategory_hard(
    category_id: int,
    subcategory_id: int,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    """
    HARD DELETE:
    - deletes budgets + transactions that use this subcategory
    - deletes the subcategory
    """
    if not uid:
        return _redirect_login()

    sub = db.exec(
        select(Subcategory).where(
            Subcategory.id == subcategory_id,
            Subcategory.user_id == uid,
            Subcategory.category_id == category_id,
        )
    ).first()
    if not sub:
        return RedirectResponse(url=f"/categories/{category_id}/subcategories", status_code=303)

    budgets_sub = db.exec(
        select(Budget).where(Budget.user_id == uid, Budget.subcategory_id == subcategory_id)
    ).all()
    for b in budgets_sub:
        db.delete(b)

    tx_sub = db.exec(
        select(Transaction).where(Transaction.user_id == uid, Transaction.subcategory_id == subcategory_id)
    ).all()
    for t in tx_sub:
        db.delete(t)

    db.delete(sub)
    db.commit()

    return RedirectResponse(url=f"/categories/{category_id}/subcategories", status_code=303)
