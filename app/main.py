from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from .db import engine
from starlette.middleware.sessions import SessionMiddleware
from .config import settings
from .init_db import init_db

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "title": "Personal Accountant"})


@app.get("/ping", response_class=HTMLResponse)
def ping():
    return f"<p>✅ Server time: {datetime.now().isoformat(timespec='seconds')}</p>"


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}

@app.on_event("startup")
def on_startup():
    init_db()