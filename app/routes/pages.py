from datetime import datetime
from sqlalchemy import text
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..db import engine
from ..auth import get_current_user_id

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    uid = get_current_user_id(request.session)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "title": "Personal Accountant", "user_id": uid},
    )

@router.get("/ping", response_class=HTMLResponse)
def ping():
    return f"<p>✅ Server time: {datetime.now().isoformat(timespec='seconds')}</p>"

@router.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
