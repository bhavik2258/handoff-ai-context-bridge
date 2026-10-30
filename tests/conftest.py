import os
from pathlib import Path
from tempfile import mkdtemp

import pytest
from fastapi.testclient import TestClient


_TEST_DIRECTORY = Path(mkdtemp(prefix="handoff-tests-"))
_DATABASE_PATH = _TEST_DIRECTORY / "test.db"
_LOG_PATH = _TEST_DIRECTORY / "app.log"

os.environ["DATABASE_URL"] = f"sqlite:///{_DATABASE_PATH}"
os.environ["LOG_FILE"] = str(_LOG_PATH)


@pytest.fixture
def client():
    from app.database import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _LOG_PATH.unlink(missing_ok=True)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def log_path() -> Path:
    return _LOG_PATH
