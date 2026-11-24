"""Контракты входа, отзыва доступа и ролевой авторизации."""

from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.models import User, UserRole
from app.auth.security import ALGORITHM, create_access_token, hash_password
from app.auth.service import authenticate_user, ensure_bootstrap_admin
from app.core.config import settings


def _create_user(
    db: Session,
    *,
    username: str,
    role: UserRole,
    active: bool = True,
) -> User:
    user = User(
        username=username,
        password_hash=hash_password("correct-password"),
        role=role,
        is_active=active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _bearer(user: User) -> dict[str, str]:
    token, _ = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def test_login_and_current_user(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    user = _create_user(
        db_session,
        username="engineer",
        role=UserRole.ENGINEER,
    )

    response = unauthenticated_client.post(
        "/auth/token",
        data={"username": "engineer", "password": "correct-password"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == settings.auth_access_token_minutes * 60

    claims = jwt.decode(
        payload["access_token"],
        options={"verify_signature": False},
    )
    assert claims["sub"] == str(user.id)
    assert "role" not in claims

    me = unauthenticated_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["username"] == "engineer"
    assert me.json()["role"] == "engineer"


def test_login_uses_generic_error_for_unknown_user_and_wrong_password(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    _create_user(db_session, username="operator", role=UserRole.OPERATOR)

    unknown = unauthenticated_client.post(
        "/auth/token",
        data={"username": "missing", "password": "wrong"},
    )
    wrong_password = unauthenticated_client.post(
        "/auth/token",
        data={"username": "operator", "password": "wrong"},
    )

    assert unknown.status_code == 401
    assert wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()


def test_login_rejects_oversized_credentials(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post(
        "/auth/token",
        data={"username": "x" * 65, "password": "x" * 129},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Неверный логин или пароль"}


def test_protected_api_rejects_missing_and_invalid_tokens(
    unauthenticated_client: TestClient,
) -> None:
    missing = unauthenticated_client.get("/equipment")
    invalid = unauthenticated_client.get(
        "/equipment",
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"


def test_health_remains_public(unauthenticated_client: TestClient) -> None:
    assert unauthenticated_client.get("/health").status_code == 200


def test_deactivated_user_loses_access_before_token_expiry(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    user = _create_user(db_session, username="viewer", role=UserRole.VIEWER)
    headers = _bearer(user)
    assert unauthenticated_client.get("/equipment", headers=headers).status_code == 200

    user.is_active = False
    db_session.commit()

    assert unauthenticated_client.get("/equipment", headers=headers).status_code == 401


def test_expired_token_is_rejected(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    user = _create_user(db_session, username="expired", role=UserRole.VIEWER)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "type": "access",
            "iss": settings.auth_jwt_issuer,
            "aud": settings.auth_jwt_audience,
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        settings.auth_jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )

    response = unauthenticated_client.get(
        "/equipment",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_viewer_can_read_but_cannot_mutate(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    viewer = _create_user(db_session, username="read-only", role=UserRole.VIEWER)
    headers = _bearer(viewer)

    assert unauthenticated_client.get("/equipment", headers=headers).status_code == 200
    forbidden = unauthenticated_client.post(
        "/equipment",
        headers=headers,
        json={
            "code": "AUTH-001",
            "name": "Auth test",
            "equipment_type": "test",
            "location": "Lab",
        },
    )
    assert forbidden.status_code == 403


def test_operator_can_update_incident_but_cannot_create_monitoring_rule(
    client: TestClient,
    unauthenticated_client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    incident = client.post(
        "/incidents",
        json={
            "equipment_id": equipment["id"],
            "title": "Role check",
            "severity": "medium",
        },
    ).json()
    operator = _create_user(
        db_session,
        username="shift-operator",
        role=UserRole.OPERATOR,
    )
    headers = _bearer(operator)

    updated = unauthenticated_client.patch(
        f"/incidents/{incident['id']}",
        headers=headers,
        json={"assigned_to": "shift-operator"},
    )
    forbidden = unauthenticated_client.post(
        f"/equipment/{equipment['id']}/monitoring-rules",
        headers=headers,
        json={
            "name": "Forbidden rule",
            "metric_name": "temperature_c",
            "operator": "gt",
            "threshold_value": 90,
        },
    )

    assert updated.status_code == 200
    assert forbidden.status_code == 403


def test_admin_can_create_list_and_deactivate_user(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    created = client.post(
        "/auth/users",
        json={
            "username": "new-operator",
            "password": "secure-password",
            "full_name": "New Operator",
            "role": "operator",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "operator"

    duplicate = client.post(
        "/auth/users",
        json={
            "username": "new-operator",
            "password": "another-password",
            "role": "viewer",
        },
    )
    assert duplicate.status_code == 409

    login_response = unauthenticated_client.post(
        "/auth/token",
        data={"username": "new-operator", "password": "secure-password"},
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert unauthenticated_client.get("/equipment", headers=headers).status_code == 200

    users = client.get("/auth/users")
    assert users.status_code == 200
    assert {item["username"] for item in users.json()} == {
        "new-operator",
        "test-admin",
    }

    disabled = client.patch(
        f"/auth/users/{created.json()['id']}",
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert unauthenticated_client.get("/equipment", headers=headers).status_code == 401


def test_non_admin_cannot_manage_users(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    engineer = _create_user(
        db_session,
        username="ordinary-engineer",
        role=UserRole.ENGINEER,
    )

    response = unauthenticated_client.get(
        "/auth/users",
        headers=_bearer(engineer),
    )

    assert response.status_code == 403


def test_admin_cannot_deactivate_or_demote_self(
    client: TestClient,
    admin_user: User,
) -> None:
    deactivate = client.patch(
        f"/auth/users/{admin_user.id}",
        json={"is_active": False},
    )
    demote = client.patch(
        f"/auth/users/{admin_user.id}",
        json={"role": "viewer"},
    )

    assert deactivate.status_code == 409
    assert demote.status_code == 409


def test_user_update_rejects_null_only_payload(
    client: TestClient,
    admin_user: User,
) -> None:
    response = client.patch(
        f"/auth/users/{admin_user.id}",
        json={"role": None, "is_active": None, "password": None},
    )

    assert response.status_code == 422


def test_bootstrap_admin_is_idempotent_and_does_not_replace_password(
    db_session: Session,
) -> None:
    created_user, created = ensure_bootstrap_admin(
        db_session,
        username="bootstrap-admin",
        password="initial-password",
    )
    existing_user, created_again = ensure_bootstrap_admin(
        db_session,
        username="bootstrap-admin",
        password="replacement-password",
    )

    assert created is True
    assert created_again is False
    assert existing_user.id == created_user.id
    assert (
        authenticate_user(db_session, "bootstrap-admin", "initial-password") is not None
    )
    assert (
        authenticate_user(db_session, "bootstrap-admin", "replacement-password") is None
    )
