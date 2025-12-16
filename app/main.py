from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .init_db import init_db
from .routes.pages import router as pages_router
from .routes.auth import router as auth_router
from .routes.dashboard import router as dashboard_router

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

@app.on_event("startup")
def on_startup():
    init_db()

app.include_router(pages_router)
app.include_router(auth_router)
app.include_router(dashboard_router)

