from typing import Optional
from fastapi import Request

from .auth import get_current_user_id

def current_user_id(request: Request) -> Optional[int]:
    return get_current_user_id(request.session)
