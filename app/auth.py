from typing import Optional
from sqlmodel import Session, select
from .models import User

SESSION_USER_ID = "user_id"

def get_current_user_id(session: dict) -> Optional[int]:
    uid = session.get(SESSION_USER_ID)
    return int(uid) if uid is not None else None

def get_user_by_email(db: Session, email: str) -> User | None:
    return db.exec(select(User).where(User.email == email)).first()
