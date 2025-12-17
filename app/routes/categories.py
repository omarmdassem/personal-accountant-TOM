from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user_id
from ..models import Category
from ..models import Subcategory 

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/categories", response_class=HTMLResponse)
def list_categories(
    request: Request,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    cats = db.exec(select(Category).where(Category.user_id == uid).order_by(Category.name)).all()
    return templates.TemplateResponse(
        "categories.html",
        {"request": request, "title": "Categories", "user_id": uid, "categories": cats, "error": None},
    )

@router.post("/categories")
def create_category(
    request: Request,
    name: str = Form(...),
    icon: str = Form(""),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    name = name.strip()
    icon = (icon or "").strip() or None

    if not name:
        return templates.TemplateResponse(
            "categories.html",
            {"request": request, "title": "Categories", "user_id": uid, "categories": [], "error": "Name is required."},
            status_code=400,
        )

    cat = Category(user_id=uid, name=name, icon=icon)
    db.add(cat)
    try:
        db.commit()
    except Exception:
        db.rollback()
        # likely unique constraint violation (same name for same user)
        cats = db.exec(select(Category).where(Category.user_id == uid).order_by(Category.name)).all()
        return templates.TemplateResponse(
            "categories.html",
            {"request": request, "title": "Categories", "user_id": uid, "categories": cats, "error": "Category name already exists."},
            status_code=400,
        )

    return RedirectResponse(url="/categories", status_code=303)

@router.get("/categories/{category_id}", response_class=HTMLResponse)
def category_detail(
    category_id: int,
    request: Request,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    cat = db.exec(
        select(Category).where(Category.id == category_id, Category.user_id == uid)
    ).first()
    if not cat:
        return RedirectResponse(url="/categories", status_code=303)

    subs = db.exec(
        select(Subcategory)
        .where(Subcategory.user_id == uid, Subcategory.category_id == category_id)
        .order_by(Subcategory.name)
    ).all()

    return templates.TemplateResponse(
        "category_detail.html",
        {
            "request": request,
            "title": f"Category: {cat.name}",
            "user_id": uid,
            "category": cat,
            "subcategories": subs,
            "error": None,
        },
    )


@router.post("/categories/{category_id}/subcategories")
def create_subcategory(
    category_id: int,
    request: Request,
    name: str = Form(...),
    icon: str = Form(""),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    cat = db.exec(
        select(Category).where(Category.id == category_id, Category.user_id == uid)
    ).first()
    if not cat:
        return RedirectResponse(url="/categories", status_code=303)

    name = name.strip()
    icon = (icon or "").strip() or None
    if not name:
        return RedirectResponse(url=f"/categories/{category_id}", status_code=303)

    sub = Subcategory(user_id=uid, category_id=category_id, name=name, icon=icon)
    db.add(sub)
    try:
        db.commit()
    except Exception:
        db.rollback()
        subs = db.exec(
            select(Subcategory)
            .where(Subcategory.user_id == uid, Subcategory.category_id == category_id)
            .order_by(Subcategory.name)
        ).all()
        return templates.TemplateResponse(
            "category_detail.html",
            {
                "request": request,
                "title": f"Category: {cat.name}",
                "user_id": uid,
                "category": cat,
                "subcategories": subs,
                "error": "Subcategory name already exists in this category.",
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/categories/{category_id}", status_code=303)
