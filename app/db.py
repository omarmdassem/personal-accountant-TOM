from typing import Generator
from sqlmodel import Session, create_engine
from .config import settings

engine = create_engine(settings.database_url, echo=settings.sql_echo)

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
