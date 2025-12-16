from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..deps import current_user_id

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, uid=Depends(current_user_id)):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user_id": uid},
    )
