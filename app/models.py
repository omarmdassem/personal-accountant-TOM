from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, String, UniqueConstraint
from sqlmodel import SQLModel, Field

from .domain import BudgetType, RepeatUnit


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    email: str = Field(
        sa_column=Column(String, unique=True, index=True, nullable=False)
    )
    hashed_password: str

    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Category(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_category_user_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)

    name: str
    icon: str | None = None  # emoji or icon key
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Subcategory(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("category_id", "name", name="uq_subcategory_category_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)   # convenience + ownership
    category_id: int = Field(foreign_key="category.id", index=True)

    name: str
    icon: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Budget(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)

    type: BudgetType  # income/expense
    amount_cents: int
    currency: str  # e.g. "EUR"

    category_id: int = Field(foreign_key="category.id", index=True)
    subcategory_id: int | None = Field(default=None, foreign_key="subcategory.id", index=True)

    # Recurrence
    is_recurring: bool = False
    repeat_unit: RepeatUnit | None = None        # weekly/monthly/yearly
    repeat_interval: int | None = None           # every N units (1=every month/week/year)
    day_of_month: int | None = None              # for monthly/yearly patterns
    weekday: int | None = None                   # 0=Mon ... 6=Sun for weekly patterns

    # One-time budgets
    one_time_date: date | None = None

    # Optional window for recurring budgets
    start_date: date | None = None
    end_date: date | None = None

    note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ----------------------------
# Transactions
# ----------------------------
from datetime import datetime, date as _date
from typing import Optional

from sqlmodel import Field


class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(index=True)

    date: _date = Field(index=True)

    # Reuse BudgetType enum: "income" / "expense"
    type: BudgetType = Field(index=True)

    category_id: int = Field(index=True)
    subcategory_id: Optional[int] = Field(default=None, index=True)

    description: Optional[str] = None

    amount_cents: int
    currency: str = "EUR"

    note: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
