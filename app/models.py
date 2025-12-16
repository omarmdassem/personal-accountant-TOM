from datetime import datetime
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, String

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    email: str = Field(
        sa_column=Column(String, unique=True, index=True, nullable=False)
    )
    hashed_password: str

    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
