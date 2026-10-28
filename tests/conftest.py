import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.equipment import models as equipment_models  # noqa: F401
from app.main import app
from app.telemetry import models as telemetry_models  # noqa: F401


@pytest.fixture
def client():
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

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


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
    """Удаляет logs/ после тестовой сессии."""
    yield
    logs = Path("logs")
    if logs.exists():
        shutil.rmtree(logs)
