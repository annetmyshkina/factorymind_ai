import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, text

from app.core.database import SessionLocal, engine
from app.equipment.models import Equipment
from app.incidents.experience import search_similar_incidents
from app.incidents.feedback import confirm_incident_resolution
from app.incidents.models import Incident
from app.incidents.schemas import IncidentResolutionCreate
from app.incidents.service import change_status, create_incident

pytestmark = pytest.mark.skipif(
    os.environ.get("POSTGRES_INTEGRATION") != "1",
    reason="FTS подтверждённого опыта требует PostgreSQL",
)


def test_postgresql_searches_only_active_confirmed_experience() -> None:
    assert engine.dialect.name == "postgresql"
    suffix = uuid4().hex
    with SessionLocal() as db:
        equipment = Equipment(
            code=f"EXPERIENCE-{suffix}",
            name="Experience retrieval equipment",
            equipment_type=f"compressor-{suffix}",
            location="Integration test",
        )
        db.add(equipment)
        db.commit()
        db.refresh(equipment)
        equipment_id = equipment.id

        historical = create_incident(
            db,
            equipment_id=equipment.id,
            title="Historical overheating",
            severity="high",
        )
        change_status(db, historical, "in_progress")
        change_status(db, historical, "resolved")
        db.commit()
        resolution = confirm_incident_resolution(
            db,
            incident_id=historical.id,
            payload=IncidentResolutionCreate(
                checks_performed=["Проверено давление масла"],
                confirmed_cause="Загрязнение масляного фильтра",
                actions_taken=["Фильтр заменён"],
                outcome="Температура нормализовалась",
                actor="postgres-test",
            ),
        )
        target = create_incident(
            db,
            equipment_id=equipment.id,
            title="Current overheating",
            severity="high",
        )
        target_id = target.id
        historical_id = historical.id

        results = search_similar_incidents(
            db,
            incident_id=target.id,
            query="масляного фильтра",
        )
        index_exists = db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes "
                "WHERE indexname = 'ix_incident_resolutions_search')",
            ),
        )

    try:
        assert index_exists is True
        assert len(results) == 1
        assert results[0].resolution_id == resolution.id
        assert results[0].match_scope == "same_equipment"
        assert results[0].score > 0
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(Incident).where(Incident.id.in_([target_id, historical_id])),
            )
            db.execute(delete(Equipment).where(Equipment.id == equipment_id))
            db.commit()
