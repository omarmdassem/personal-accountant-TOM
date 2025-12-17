from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user_id
from ..models import Category

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
