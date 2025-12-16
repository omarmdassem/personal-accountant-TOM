from sqlmodel import SQLModel
from .db import engine
from . import models  # noqa: F401

def init_db() -> None:
    SQLModel.metadata.create_all(engine)
