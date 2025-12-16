from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from .db import engine

app = FastAPI()
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