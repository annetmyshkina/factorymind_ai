import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.core.database import SessionLocal, engine
from app.equipment.models import Equipment
from app.incidents.models import Incident, IncidentEvent
from app.notifications.models import NotificationOutbox
from app.notifications.queue import claim_next_notification

pytestmark = pytest.mark.skipif(
    os.environ.get("POSTGRES_INTEGRATION") != "1",
    reason="Тест notification SKIP LOCKED требует PostgreSQL",
)


def test_parallel_workers_claim_notification_only_once() -> None:
    assert engine.dialect.name == "postgresql"
    suffix = uuid4().hex[:20]
    with SessionLocal() as db:
        equipment = Equipment(
            code=f"NOTIFY-{suffix}",
            name="Notification concurrency",
            equipment_type="test",
            location="test",
        )
        db.add(equipment)
        db.flush()
        incident = Incident(
            equipment_id=equipment.id,
            title="Concurrent notification",
            severity="critical",
        )
        db.add(incident)
        db.flush()
        event = IncidentEvent(
            incident_id=incident.id,
            event_type="created",
            payload={"source": "automatic", "severity": "critical"},
        )
        db.add(event)
        db.flush()
        item = NotificationOutbox(
            event_type="incident_created",
            incident_id=incident.id,
            incident_event_id=event.id,
            payload={"incident_id": incident.id},
        )
        db.add(item)
        db.commit()
        equipment_id = equipment.id
        item_id = item.id

    barrier = Barrier(2)

    def claim(worker_id: str):
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            barrier.wait(timeout=5)
            return claim_next_notification(db, worker_id, lease_seconds=30)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = [
                future.result(timeout=10)
                for future in (
                    executor.submit(claim, "worker-a"),
                    executor.submit(claim, "worker-b"),
                )
            ]
        claimed = [item for item in claims if item is not None]
        assert len(claimed) == 1
        assert claimed[0].item_id == item_id
        with SessionLocal() as db:
            saved = db.get(NotificationOutbox, item_id)
            assert saved is not None
            assert saved.status == "running"
            assert saved.attempt_count == 1
    finally:
        with SessionLocal() as db:
            equipment = db.scalar(
                select(Equipment).where(Equipment.id == equipment_id),
            )
            if equipment is not None:
                db.delete(equipment)
                db.commit()
