from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, models
from app.database import Base, get_db
from app.main import app
from app.routers import whatsapp


@pytest.fixture
def client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client, test_session_factory
    finally:
        test_client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        engine.dispose()


def create_test_user(session_factory, email: str, role: models.RoleEnum) -> None:
    with session_factory() as db:
        db.add(
            models.User(
                nama="QA Synthetic User",
                email=email,
                hashed_password=auth.hash_password("qa-only-password"),
                role=role,
            )
        )
        db.commit()


def test_login_rejects_invalid_password(client):
    test_client, session_factory = client
    create_test_user(session_factory, "qa.hr@example.com", models.RoleEnum.hr_master)

    response = test_client.post(
        "/auth/login",
        json={"email": "qa.hr@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Email atau password salah."


def test_legacy_n8n_api_key_routes_and_leave_auth_bypass_are_removed(client):
    test_client, _ = client

    process_response = test_client.post(
        "/proses-absensi",
        headers={"X-API-Key": "synthetic-obsolete-key"},
    )
    holiday_response = test_client.post(
        "/upload-tanggal-merah",
        headers={"X-API-Key": "synthetic-obsolete-key"},
    )
    leave_response = test_client.post(
        "/leaves",
        headers={"X-API-Key": "synthetic-obsolete-key"},
        json={
            "nama": "Synthetic Employee",
            "kategori": "SAKIT",
            "tanggal_mulai": "2026-10-12",
            "tanggal_selesai": "2026-10-12",
            "alasan": "QA",
        },
    )

    assert process_response.status_code == 404
    assert holiday_response.status_code == 404
    assert leave_response.status_code == 401


def test_hr_staff_cannot_use_hr_master_user_management(client):
    test_client, session_factory = client
    create_test_user(session_factory, "qa.staff@example.com", models.RoleEnum.hr_staff)
    login = test_client.post(
        "/auth/login",
        json={"email": "qa.staff@example.com", "password": "qa-only-password"},
    )
    assert login.status_code == 200

    response = test_client.get(
        "/auth/users",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Hanya HR Master yang boleh melakukan aksi ini."


def test_whatsapp_webhook_verification_requires_the_configured_token(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(
        whatsapp,
        "get_env_var",
        lambda key, default="": "synthetic-verification-token"
        if key == "WHATSAPP_VERIFY_TOKEN"
        else default,
    )

    accepted = test_client.get(
        "/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "synthetic-verification-token",
            "hub.challenge": "synthetic-challenge",
        },
    )
    rejected = test_client.get(
        "/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "synthetic-challenge",
        },
    )

    assert accepted.status_code == 200
    assert accepted.text == "synthetic-challenge"
    assert rejected.status_code == 403


def test_whatsapp_webhook_ignores_malformed_payload(client):
    test_client, _ = client

    response = test_client.post(
        "/whatsapp/webhook",
        content="{",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


def test_whatsapp_webhook_processes_a_message_id_only_once(client, monkeypatch):
    test_client, _ = client
    processed = []

    async def fake_process_whatsapp_incoming(
        from_number: str,
        raw_text: str,
        interactive_id: str | None,
        db,
    ) -> None:
        processed.append((from_number, raw_text, interactive_id))
        db.commit()

    monkeypatch.setattr(
        whatsapp,
        "process_whatsapp_incoming",
        fake_process_whatsapp_incoming,
    )
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.synthetic.qa-001",
                                    "from": "6280000000000",
                                    "type": "text",
                                    "text": {"body": "menu"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    first = test_client.post("/whatsapp/webhook", json=payload)
    second = test_client.post("/whatsapp/webhook", json=payload)

    assert first.status_code == second.status_code == 200
    assert processed == [("6280000000000", "menu", None)]


def test_whatsapp_webhook_ignores_delivery_status_events(client, monkeypatch):
    test_client, _ = client
    process_message = AsyncMock()
    monkeypatch.setattr(whatsapp, "process_whatsapp_incoming", process_message)

    response = test_client.post(
        "/whatsapp/webhook",
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {"id": "wamid.synthetic.status", "status": "delivered"}
                                ]
                            }
                        }
                    ]
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    process_message.assert_not_awaited()
