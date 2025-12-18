import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
import sys
from pathlib import Path
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app
from app.db import get_session


@pytest.fixture()
def engine():
    # Test database (in-memory SQLite, shared connection)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture()
def client(engine):
    # Override dependency
    def _get_session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _get_session_override

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
