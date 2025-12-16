from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from ..db import get_session
from ..models import User
from ..security import hash_password
from ..auth import get_user_by_email, SESSION_USER_ID

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request, "error": None})

@router.post("/signup")
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    email = email.strip().lower()

    existing = get_user_by_email(db, email)
    if existing:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": "Email already registered."},
            status_code=400,
        )

    user = User(email=email, hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    request.session[SESSION_USER_ID] = user.id
    return RedirectResponse(url="/", status_code=303)
