import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text

from app.core.database import SessionLocal, engine
from app.equipment.models import Equipment
from app.incidents.feedback import (
    IncidentResolutionConflictError,
    confirm_incident_resolution,
)
from app.incidents.models import Incident, IncidentResolution, IncidentResolutionEvent
from app.incidents.schemas import IncidentResolutionCreate
from app.incidents.service import change_status, create_incident

pytestmark = pytest.mark.skipif(
    os.environ.get("POSTGRES_INTEGRATION") != "1",
    reason="Конкурентное подтверждение результата требует PostgreSQL",
)


def test_parallel_confirmation_creates_one_active_resolution() -> None:
    assert engine.dialect.name == "postgresql"
    suffix = uuid4().hex
    with SessionLocal() as db:
        equipment = Equipment(
            code=f"FEEDBACK-{suffix}",
            name="Feedback concurrency equipment",
            equipment_type="test-unit",
            location="Integration test",
        )
        db.add(equipment)
        db.commit()
        db.refresh(equipment)
        equipment_id = equipment.id
        incident = create_incident(
            db,
            equipment_id=equipment.id,
            title="Concurrent resolution",
            severity="medium",
        )
        change_status(db, incident, "in_progress")
        change_status(db, incident, "resolved")
        db.commit()
        incident_id = incident.id

    barrier = Barrier(2)

    def confirm(actor: str) -> str:
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            barrier.wait(timeout=5)
            try:
                confirm_incident_resolution(
                    db,
                    incident_id=incident_id,
                    payload=IncidentResolutionCreate(
                        checks_performed=["Проверка выполнена"],
                        actions_taken=["Действие выполнено"],
                        outcome="Оборудование работает штатно",
                        actor=actor,
                    ),
                )
            except IncidentResolutionConflictError:
                return "conflict"
            return "created"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = sorted(
                future.result(timeout=10)
                for future in (
                    executor.submit(confirm, "engineer-1"),
                    executor.submit(confirm, "engineer-2"),
                )
            )

        with SessionLocal() as db:
            resolution_count = db.scalar(
                select(func.count()).select_from(IncidentResolution),
            )
            active_count = db.scalar(
                select(func.count())
                .select_from(IncidentResolution)
                .where(IncidentResolution.is_active.is_(True)),
            )
            event_count = db.scalar(
                select(func.count()).select_from(IncidentResolutionEvent),
            )

        assert results == ["conflict", "created"]
        assert resolution_count == 1
        assert active_count == 1
        assert event_count == 1
    finally:
        with SessionLocal() as db:
            db.execute(delete(Incident).where(Incident.id == incident_id))
            db.execute(delete(Equipment).where(Equipment.id == equipment_id))
            db.commit()
