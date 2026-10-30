import os
import shutil
from pathlib import Path

os.environ["ENVIRONMENT"] = "test"
os.environ["LOG_TO_FILES"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.equipment import models as equipment_models  # noqa: F401
from app.main import app
from app.monitoring import models as monitoring_models  # noqa: F401
from app.telemetry import models as telemetry_models  # noqa: F401


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(bind=engine)

    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db_session: Session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def equipment(client: TestClient) -> dict:
    """Создаёт одно оборудование с дефолтными полями."""
    response = client.post(
        "/equipment",
        json={
            "code": "COOLER-FIXTURE",
            "name": "Тестовое оборудование",
            "equipment_type": "cooling_unit",
            "location": "Цех № 1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(autouse=True, scope="session")
def _cleanup_logs_dir():
    """Удаляет logs/ после тестов в CI (локально — оставляет для отладки)."""
    yield
    if os.environ.get("CI"):
        logs = Path("logs")
        if logs.exists():
            shutil.rmtree(logs)
