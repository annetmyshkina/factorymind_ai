from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend import mount_frontend


def test_frontend_is_not_mounted_without_build(tmp_path: Path) -> None:
    app = FastAPI()

    assert mount_frontend(app, dist_path=tmp_path) is False


def test_frontend_serves_built_spa(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        "<title>FactoryMind Operations</title>",
        encoding="utf-8",
    )
    app = FastAPI()

    assert mount_frontend(app, dist_path=tmp_path) is True

    response = TestClient(app).get("/ui/")
    assert response.status_code == 200
    assert "FactoryMind Operations" in response.text
