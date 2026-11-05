import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.core.database import SessionLocal, engine
from app.equipment.models import Equipment
from app.incidents.automation import (
    ACTIVE_INCIDENT_STATUSES,
    ensure_incident_for_deviation,
)
from app.incidents.models import Incident, IncidentDeviation
from app.monitoring.models import EquipmentDeviation

pytestmark = pytest.mark.skipif(
    os.environ.get("POSTGRES_INTEGRATION") != "1",
    reason="Тест конкурентных блокировок требует PostgreSQL",
)


def test_parallel_deviations_share_one_automatic_incident() -> None:
    assert engine.dialect.name == "postgresql"

    equipment_code = f"CONCURRENT-{uuid4().hex[:20]}"
    with SessionLocal() as db:
        equipment = Equipment(
            code=equipment_code,
            name="Concurrency test",
            equipment_type="test",
            location="test",
        )
        db.add(equipment)
        db.commit()
        equipment_id = equipment.id

    barrier = Barrier(2)

    def create_incident_from_deviation(observed_value: float) -> int:
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            deviation = EquipmentDeviation(
                equipment_id=equipment_id,
                metric_name="temperature_c",
                observed_value=observed_value,
                threshold_value=80.0,
                message="Concurrency test",
            )
            db.add(deviation)
            db.flush()
            barrier.wait(timeout=5)

            incident = ensure_incident_for_deviation(db, deviation)
            incident_id = incident.id
            db.commit()
            return incident_id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(create_incident_from_deviation, value)
                for value in (90.0, 91.0)
            ]
            incident_ids = [future.result(timeout=10) for future in futures]

        with SessionLocal() as db:
            active_incidents = list(
                db.scalars(
                    select(Incident).where(
                        Incident.equipment_id == equipment_id,
                        Incident.status.in_(ACTIVE_INCIDENT_STATUSES),
                    )
                )
            )
            link_count = db.scalar(
                select(func.count())
                .select_from(IncidentDeviation)
                .join(Incident)
                .where(Incident.equipment_id == equipment_id),
            )

        assert len(set(incident_ids)) == 1
        assert len(active_incidents) == 1
        assert link_count == 2
    finally:
        with SessionLocal() as db:
            equipment = db.scalar(
                select(Equipment).where(Equipment.id == equipment_id),
            )
            if equipment is not None:
                db.delete(equipment)
                db.commit()
