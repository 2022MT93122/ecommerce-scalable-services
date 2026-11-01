import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_bootstrap = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _bootstrap.name + "/bootstrap.db"
from app.main import app
from app.db import Base, get_db


@pytest.fixture
def database(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "test.db"),
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    def override():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override
    yield sessions
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(database):
    with TestClient(app) as client:
        yield client
