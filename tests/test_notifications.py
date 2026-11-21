from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, settings
from app.equipment.models import Equipment
from app.incidents.models import Incident, IncidentEvent
from app.incidents.service import add_incident, change_status
from app.notifications import queue, worker
from app.notifications.errors import TelegramDeliveryError
from app.notifications.models import NotificationOutbox
from app.notifications.queue import (
    NotificationInput,
    claim_next_notification,
    execute_claimed_notification,
    recover_expired_notifications,
    render_notification,
)


class FakeTelegramClient:
    def __init__(
        self,
        *,
        error: TelegramDeliveryError | None = None,
    ) -> None:
        self.error = error
        self.messages: list[str] = []

    def send_message(self, text: str) -> str:
        self.messages.append(text)
        if self.error is not None:
            raise self.error
        return "telegram-42"


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, postgres_password="test", **overrides)


def _factory(db: Session):
    return sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )


def _enable_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_notifications_enabled", True)
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("test-token"))
    monkeypatch.setattr(settings, "telegram_chat_id", "test-chat")


def _create_equipment(db: Session, code: str = "NOTIFY-01") -> Equipment:
    equipment = Equipment(
        code=code,
        name="Notification test",
        equipment_type="test",
        location="test",
    )
    db.add(equipment)
    db.commit()
    return equipment


def _create_automatic_incident(
    db: Session,
    equipment_id: int,
    *,
    severity: str = "critical",
) -> Incident:
    incident = add_incident(
        db,
        equipment_id=equipment_id,
        title="Перегрев",
        severity=severity,
        source="automatic",
    )
    db.commit()
    return incident


def test_enabled_notifications_require_token_and_chat() -> None:
    with pytest.raises(ValidationError, match="TELEGRAM_BOT_TOKEN"):
        _settings(telegram_notifications_enabled=True)


@pytest.mark.parametrize(
    ("bot_token", "chat_id"),
    [("", "chat"), ("   ", "chat"), ("token", ""), ("token", "   ")],
)
def test_enabled_notifications_reject_blank_credentials(
    bot_token: str,
    chat_id: str,
) -> None:
    with pytest.raises(ValidationError, match="TELEGRAM_BOT_TOKEN"):
        _settings(
            telegram_notifications_enabled=True,
            telegram_bot_token=bot_token,
            telegram_chat_id=chat_id,
        )


def test_automatic_high_incident_is_enqueued_in_same_transaction(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_notifications(monkeypatch)
    equipment = _create_equipment(db_session)

    incident = add_incident(
        db_session,
        equipment_id=equipment.id,
        title="Вибрация",
        severity="high",
        source="automatic",
    )

    item = db_session.scalar(select(NotificationOutbox))
    assert item is not None
    assert item.status == "pending"
    assert item.event_type == "incident_created"
    assert item.incident_id == incident.id
    assert item.payload == {
        "incident_id": incident.id,
        "equipment_id": equipment.id,
        "equipment_code": equipment.code,
        "title": "Вибрация",
        "severity": "high",
        "status": "open",
    }
    event = db_session.get(IncidentEvent, item.incident_event_id)
    assert event is not None
    assert event.payload is not None
    assert event.payload["source"] == "automatic"

    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(Incident)) == 0
    assert db_session.scalar(select(func.count()).select_from(NotificationOutbox)) == 0


def test_disabled_manual_and_medium_incidents_are_not_enqueued(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    equipment = _create_equipment(db_session)
    add_incident(
        db_session,
        equipment_id=equipment.id,
        title="Disabled critical",
        severity="critical",
        source="automatic",
    )
    db_session.commit()

    _enable_notifications(monkeypatch)
    add_incident(
        db_session,
        equipment_id=equipment.id,
        title="Manual critical",
        severity="critical",
        source="manual",
    )
    add_incident(
        db_session,
        equipment_id=equipment.id,
        title="Automatic medium",
        severity="medium",
        source="automatic",
    )
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(NotificationOutbox)) == 0


def test_resolved_and_closed_transitions_are_separate_notifications(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_notifications(monkeypatch)
    equipment = _create_equipment(db_session)
    incident = _create_automatic_incident(db_session, equipment.id)

    change_status(db_session, incident, "in_progress")
    change_status(db_session, incident, "resolved")
    change_status(db_session, incident, "closed")
    db_session.commit()

    items = list(
        db_session.scalars(select(NotificationOutbox).order_by(NotificationOutbox.id)),
    )
    assert [item.event_type for item in items] == [
        "incident_created",
        "incident_resolved",
        "incident_closed",
    ]
    assert len({item.incident_event_id for item in items}) == 3


def test_successful_delivery_marks_item_sent(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_notifications(monkeypatch)
    equipment = _create_equipment(db_session)
    _create_automatic_incident(db_session, equipment.id)
    factory = _factory(db_session)
    with factory() as db:
        claim = claim_next_notification(db, "worker-a", lease_seconds=30)
    assert claim is not None
    client = FakeTelegramClient()

    assert execute_claimed_notification(
        factory,
        claim,
        client,  # type: ignore[arg-type]
        notification_settings=_settings(
            public_app_base_url="https://factory.example/ui/",
        ),
    )

    db_session.expire_all()
    item = db_session.get(NotificationOutbox, claim.item_id)
    assert item is not None
    assert item.status == "sent"
    assert item.external_message_id == "telegram-42"
    assert item.sent_at is not None
    assert item.worker_id is None
    assert "https://factory.example/ui/#incidents" in client.messages[0]


def test_retryable_error_returns_item_to_pending_with_backoff(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_notifications(monkeypatch)
    equipment = _create_equipment(db_session)
    _create_automatic_incident(db_session, equipment.id)
    factory = _factory(db_session)
    with factory() as db:
        claim = claim_next_notification(db, "worker-a", lease_seconds=30)
    assert claim is not None
    client = FakeTelegramClient(
        error=TelegramDeliveryError("temporary", retryable=True),
    )

    execute_claimed_notification(
        factory,
        claim,
        client,  # type: ignore[arg-type]
        notification_settings=_settings(notification_retry_base_seconds=5),
    )

    db_session.expire_all()
    item = db_session.get(NotificationOutbox, claim.item_id)
    assert item is not None
    assert item.status == "pending"
    assert item.attempt_count == 1
    assert item.next_retry_at is not None
    assert 4 <= (item.next_retry_at - datetime.now(UTC)).total_seconds() <= 5
    assert item.error == "temporary"


def test_non_retryable_error_fails_immediately(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_notifications(monkeypatch)
    equipment = _create_equipment(db_session)
    _create_automatic_incident(db_session, equipment.id)
    factory = _factory(db_session)
    with factory() as db:
        claim = claim_next_notification(db, "worker-a", lease_seconds=30)
    assert claim is not None

    execute_claimed_notification(
        factory,
        claim,
        FakeTelegramClient(  # type: ignore[arg-type]
            error=TelegramDeliveryError("unauthorized", retryable=False),
        ),
        notification_settings=_settings(),
    )

    db_session.expire_all()
    item = db_session.get(NotificationOutbox, claim.item_id)
    assert item is not None
    assert item.status == "failed"
    assert item.next_retry_at is None
    assert item.error == "unauthorized"


def test_expired_lease_requeues_and_rejects_old_owner(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_notifications(monkeypatch)
    equipment = _create_equipment(db_session)
    _create_automatic_incident(db_session, equipment.id)
    factory = _factory(db_session)
    with factory() as db:
        old_claim = claim_next_notification(db, "worker-old", lease_seconds=30)
        assert old_claim is not None
        item = db.get(NotificationOutbox, old_claim.item_id)
        assert item is not None
        item.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    with factory() as db:
        assert recover_expired_notifications(db) == 1
        item = db.get(NotificationOutbox, old_claim.item_id)
        assert item is not None
        item.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        new_claim = claim_next_notification(db, "worker-new", lease_seconds=30)
    assert new_claim is not None

    new_client = FakeTelegramClient()
    assert execute_claimed_notification(
        factory,
        new_claim,
        new_client,  # type: ignore[arg-type]
        notification_settings=_settings(),
    )
    assert not execute_claimed_notification(
        factory,
        old_claim,
        FakeTelegramClient(),  # type: ignore[arg-type]
        notification_settings=_settings(),
    )

    db_session.expire_all()
    item = db_session.get(NotificationOutbox, old_claim.item_id)
    assert item is not None
    assert item.status == "sent"
    assert item.external_message_id == "telegram-42"


def test_render_notification_without_public_link() -> None:
    text = render_notification(
        NotificationInput(
            event_type="incident_resolved",
            payload={
                "equipment_code": "CMP-01",
                "incident_id": 17,
                "title": "Перегрев",
                "severity": "critical",
                "status": "resolved",
            },
        ),
    )

    assert "Инцидент разрешён" in text
    assert "CMP-01" in text
    assert "Карточка:" not in text


def test_worker_loop_stops_cleanly(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_event = Event()
    recovered: list[bool] = []

    def recover(db: Session) -> int:
        recovered.append(True)
        return 0

    def process(*args, **kwargs) -> bool:
        stop_event.set()
        return False

    monkeypatch.setattr(worker, "SessionLocal", _factory(db_session))
    monkeypatch.setattr(worker, "recover_expired_notifications", recover)
    monkeypatch.setattr(worker, "process_next_notification", process)
    monkeypatch.setattr(worker, "update_queue_metrics", lambda db: None)

    worker.run_worker(
        stop_event,
        FakeTelegramClient(),  # type: ignore[arg-type]
        worker_id="notification-worker-test",
    )

    assert recovered == [True]


def test_queue_metrics_include_absent_statuses(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_notifications(monkeypatch)
    equipment = _create_equipment(db_session)
    _create_automatic_incident(db_session, equipment.id)

    queue.update_queue_metrics(db_session)

    from prometheus_client import REGISTRY

    assert (
        REGISTRY.get_sample_value(
            "factorymind_notification_queue_items",
            {"status": "pending"},
        )
        == 1
    )
    assert (
        REGISTRY.get_sample_value(
            "factorymind_notification_queue_items",
            {"status": "sent"},
        )
        == 0
    )
