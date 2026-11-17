"""Опциональная раздача собранного web-интерфейса."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def mount_frontend(
    app: FastAPI,
    *,
    dist_path: Path = DEFAULT_FRONTEND_DIST,
) -> bool:
    """Монтирует SPA на /ui, только если frontend уже собран."""
    if not (dist_path / "index.html").is_file():
        return False

    app.mount(
        "/ui",
        StaticFiles(directory=dist_path, html=True),
        name="frontend",
    )
    return True
