"""Машинная авторизация HTTP-телеметрии."""

import hashlib
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.models import User, UserRole
from app.auth.security import create_access_token, hash_password
from app.equipment.models import EquipmentAPIKey

TELEMETRY = {"temperature_c": 61.5, "vibration_mm_s": 2.1}


def _issue_key(client: TestClient, equipment_id: int) -> dict:
    response = client.post(
        f"/equipment/{equipment_id}/api-keys",
        json={"name": "Линия № 1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_equipment(client: TestClient, code: str) -> dict:
    response = client.post(
        "/equipment",
        json={
            "code": code,
            "name": f"Оборудование {code}",
            "equipment_type": "test",
            "location": "Лаборатория",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_issues_key_once_and_database_stores_only_digest(
    client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    created = _issue_key(client, equipment["id"])

    assert created["api_key"].startswith(f"{created['key_prefix']}_")
    assert created["is_active"] is True
    assert created["last_used_at"] is None

    saved = db_session.get(EquipmentAPIKey, created["id"])
    assert saved is not None
    assert (
        saved.secret_hash
        == hashlib.sha256(
            created["api_key"].encode("utf-8"),
        ).hexdigest()
    )
    assert created["api_key"] not in saved.secret_hash

    listed = client.get(f"/equipment/{equipment['id']}/api-keys")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "api_key" not in listed.json()[0]
    assert "secret_hash" not in listed.json()[0]
    assert listed.json()[0]["key_prefix"] == created["key_prefix"]


def test_equipment_key_posts_telemetry_and_updates_last_use(
    client: TestClient,
    unauthenticated_client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    created = _issue_key(client, equipment["id"])

    response = unauthenticated_client.post(
        f"/equipment/{equipment['id']}/telemetry",
        headers={"X-API-Key": created["api_key"]},
        json=TELEMETRY,
    )

    assert response.status_code == 201, response.text
    db_session.expire_all()
    saved = db_session.get(EquipmentAPIKey, created["id"])
    assert saved is not None
    assert saved.last_used_at is not None


def test_equipment_key_cannot_write_for_another_equipment(
    client: TestClient,
    unauthenticated_client: TestClient,
    equipment: dict,
) -> None:
    other = _create_equipment(client, "OTHER-KEY-TARGET")
    created = _issue_key(client, equipment["id"])

    response = unauthenticated_client.post(
        f"/equipment/{other['id']}/telemetry",
        headers={"X-API-Key": created["api_key"]},
        json=TELEMETRY,
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Ключ не разрешён для этого оборудования",
    }


def test_revoked_key_is_rejected_and_revoke_is_idempotent(
    client: TestClient,
    unauthenticated_client: TestClient,
    equipment: dict,
) -> None:
    created = _issue_key(client, equipment["id"])
    replacement = _issue_key(client, equipment["id"])
    path = f"/equipment/{equipment['id']}/api-keys/{created['id']}/revoke"

    revoked = client.post(path)
    repeated = client.post(path)
    response = unauthenticated_client.post(
        f"/equipment/{equipment['id']}/telemetry",
        headers={"X-API-Key": created["api_key"]},
        json=TELEMETRY,
    )
    replacement_response = unauthenticated_client.post(
        f"/equipment/{equipment['id']}/telemetry",
        headers={"X-API-Key": replacement["api_key"]},
        json=TELEMETRY,
    )

    assert revoked.status_code == 200
    assert revoked.json()["is_active"] is False
    assert revoked.json()["revoked_at"] is not None
    assert revoked.json()["revoked_by_user_id"] is not None
    assert repeated.status_code == 200
    assert repeated.json()["revoked_at"] == revoked.json()["revoked_at"]
    assert response.status_code == 401
    assert replacement_response.status_code == 201


def test_expired_and_malformed_keys_are_rejected(
    client: TestClient,
    unauthenticated_client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    created = _issue_key(client, equipment["id"])
    saved = db_session.get(EquipmentAPIKey, created["id"])
    assert saved is not None
    saved.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    for raw_key in (created["api_key"], "not-a-factorymind-key"):
        response = unauthenticated_client.post(
            f"/equipment/{equipment['id']}/telemetry",
            headers={"X-API-Key": raw_key},
            json=TELEMETRY,
        )
        assert response.status_code == 401
        assert response.json() == {
            "detail": "Требуются действующие учётные данные",
        }


def test_key_creation_validates_expiration_and_requires_admin(
    client: TestClient,
    unauthenticated_client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    past = client.post(
        f"/equipment/{equipment['id']}/api-keys",
        json={
            "name": "Истёкший ключ",
            "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        },
    )
    assert past.status_code == 422

    operator = User(
        username="api-key-operator",
        password_hash=hash_password("correct-password"),
        role=UserRole.OPERATOR,
        is_active=True,
    )
    db_session.add(operator)
    db_session.commit()
    token, _ = create_access_token(operator.id)
    forbidden = unauthenticated_client.post(
        f"/equipment/{equipment['id']}/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Недоступный ключ"},
    )
    assert forbidden.status_code == 403


def test_telemetry_write_without_credentials_is_rejected(
    unauthenticated_client: TestClient,
    equipment: dict,
) -> None:
    response = unauthenticated_client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json=TELEMETRY,
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_operator_jwt_can_write_telemetry_but_viewer_cannot(
    unauthenticated_client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    users = []
    for username, role in (
        ("telemetry-operator", UserRole.OPERATOR),
        ("telemetry-viewer", UserRole.VIEWER),
    ):
        user = User(
            username=username,
            password_hash=hash_password("correct-password"),
            role=role,
            is_active=True,
        )
        db_session.add(user)
        users.append(user)
    db_session.commit()

    responses = []
    for user in users:
        token, _ = create_access_token(user.id)
        responses.append(
            unauthenticated_client.post(
                f"/equipment/{equipment['id']}/telemetry",
                headers={"Authorization": f"Bearer {token}"},
                json=TELEMETRY,
            ),
        )

    assert responses[0].status_code == 201
    assert responses[1].status_code == 403
