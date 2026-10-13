import csv
import io
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
from app.routers import payroll


@pytest.fixture
def payroll_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[auth.get_current_user] = lambda: models.User(
        id=1,
        nama="Payroll QA",
        email="payroll-qa@example.test",
        hashed_password="not-used",
        role=models.RoleEnum.hr_master,
    )
    with session_factory() as db:
        db.add(models.User(
            id=1,
            nama="Payroll QA",
            email="payroll-qa@example.test",
            hashed_password="not-used",
            role=models.RoleEnum.hr_master,
        ))
        db.commit()

    client = TestClient(app)
    try:
        yield client, session_factory
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        engine.dispose()


def add_employee(
    session_factory: sessionmaker,
    *,
    code: str,
    name: str = "Karyawan Sama",
    active: bool = True,
) -> int:
    with session_factory() as db:
        if not db.query(models.Profile).filter_by(code="OFFICE").first():
            db.add(models.Profile(code="OFFICE", nama="Office"))
            db.commit()
        employee = models.Employee(
            employee_code=code,
            nama=name,
            profile_code="OFFICE",
            active=active,
        )
        db.add(employee)
        db.commit()
        db.refresh(employee)
        return employee.id


def add_identity(session_factory: sessionmaker, employee_id: int, phone: str) -> int:
    with session_factory() as db:
        identity = models.WhatsAppIdentity(
            phone_number=phone,
            employee_id=employee_id,
            status="ACTIVE",
        )
        db.add(identity)
        db.commit()
        db.refresh(identity)
        return identity.id


def payroll_csv(*rows: dict[str, str], include_code: bool = True) -> bytes:
    fields = ["Kode Karyawan"] if include_code else []
    fields += ["Nama", "No. Rekening", "Departemen", "Gaji Pokok"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


def upload_payroll(client: TestClient, data: bytes) -> dict:
    response = client.post(
        "/payroll/upload?periode=Okt-26",
        files={"file": ("payroll.csv", data, "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_payroll_template_includes_employee_code_and_upload_matches_whatsapp_by_code(payroll_client):
    client, session_factory = payroll_client
    first_id = add_employee(session_factory, code="EMP-001")
    second_id = add_employee(session_factory, code="EMP-002")
    add_identity(session_factory, second_id, "628123456789")

    template = client.get("/payroll/template?format=csv")
    assert template.status_code == 200
    assert template.text.lstrip("\ufeff").splitlines()[0].startswith("Kode Karyawan,")

    session = upload_payroll(client, payroll_csv(
        {
            "Kode Karyawan": "EMP-001",
            "Nama": "Karyawan Sama",
            "No. Rekening": "111",
            "Departemen": "Operasional",
            "Gaji Pokok": "4000000",
        },
        {
            "Kode Karyawan": " emp-002 ",
            "Nama": "Karyawan Sama",
            "No. Rekening": "222",
            "Departemen": "Operasional",
            "Gaji Pokok": "5000000",
        },
    ))

    first, second = session["rows"]
    assert first["_employee_id"] == first_id
    assert first["_wa_status"] == "WHATSAPP_NOT_LINKED"
    assert first["_wa_number"] == ""
    assert second["_employee_id"] == second_id
    assert second["_wa_status"] == "ACTIVE"
    assert second["_wa_number"] == "628123456789"


def test_payroll_upload_without_code_still_previews_but_cannot_be_sent(payroll_client):
    client, _ = payroll_client
    session = upload_payroll(client, payroll_csv(
        {
            "Nama": "Nama Tanpa Kode",
            "No. Rekening": "123",
            "Departemen": "Operasional",
            "Gaji Pokok": "4000000",
        },
        include_code=False,
    ))

    row = session["rows"][0]
    assert row["_employee_id"] is None
    assert row["_wa_available"] is False
    assert row["_wa_status"] == "MISSING_EMPLOYEE_CODE"


def test_payroll_send_revalidates_link_after_upload_and_logs_blocked_attempt(payroll_client, monkeypatch):
    client, session_factory = payroll_client
    employee_id = add_employee(session_factory, code="EMP-003")
    identity_id = add_identity(session_factory, employee_id, "628111222333")
    session = upload_payroll(client, payroll_csv({
        "Kode Karyawan": "EMP-003",
        "Nama": "Karyawan Sama",
        "No. Rekening": "333",
        "Departemen": "Operasional",
        "Gaji Pokok": "4000000",
    }))

    with session_factory() as db:
        db.query(models.WhatsAppIdentity).filter_by(id=identity_id).one().status = "REVOKED"
        db.commit()

    send_text = AsyncMock(return_value={"messages": [{"id": "should-not-send"}]})
    monkeypatch.setattr(payroll, "send_whatsapp_text", send_text)
    response = client.post(
        f"/payroll/{session['session_id']}/send-whatsapp/0",
    )

    assert response.status_code == 409
    send_text.assert_not_awaited()
    with session_factory() as db:
        delivery = db.query(models.PayrollWhatsAppDelivery).one()
        assert delivery.employee_id == employee_id
        assert delivery.status == "SKIPPED"
        assert delivery.recipient_phone is None
        assert delivery.requested_by_user_id == 1


def test_payroll_send_uses_current_employee_identity_and_persists_text_pdf_results(
    payroll_client,
    monkeypatch,
):
    client, session_factory = payroll_client
    first_id = add_employee(session_factory, code="EMP-004")
    second_id = add_employee(session_factory, code="EMP-005")
    identity_id = add_identity(session_factory, first_id, "628100000001")
    session = upload_payroll(client, payroll_csv({
        "Kode Karyawan": "EMP-004",
        "Nama": "Karyawan Sama",
        "No. Rekening": "444",
        "Departemen": "Operasional",
        "Gaji Pokok": "4000000",
    }))

    with session_factory() as db:
        db.query(models.WhatsAppIdentity).filter_by(id=identity_id).one().employee_id = second_id
        db.commit()
        db.add(models.WhatsAppIdentity(
            phone_number="628100000002",
            employee_id=first_id,
            status="ACTIVE",
        ))
        db.commit()

    sent_text = []
    sent_documents = []

    async def fake_send_text(number: str, message: str):
        sent_text.append((number, message))
        return {"messages": [{"id": "text-message-id"}]}

    async def fake_send_raw(payload: dict):
        sent_documents.append(payload)
        return {"messages": [{"id": "document-message-id"}]}

    monkeypatch.setattr(payroll, "send_whatsapp_text", fake_send_text)
    monkeypatch.setattr(payroll, "send_whatsapp_raw", fake_send_raw)
    monkeypatch.setattr(payroll, "_generate_slip_pdf_bytes", lambda *_: b"synthetic-pdf")
    monkeypatch.setattr(
        payroll,
        "upload_to_cloudinary",
        lambda **_: "https://synthetic.example/slip.pdf",
    )

    response = client.post(
        f"/payroll/{session['session_id']}/send-whatsapp/0",
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "SENT"
    assert response.json()["wa_number"] == "628100000002"
    assert sent_text[0][0] == "628100000002"
    assert "TOTAL DITERIMA" in sent_text[0][1]
    assert sent_documents[0]["to"] == "628100000002"
    with session_factory() as db:
        delivery = db.query(models.PayrollWhatsAppDelivery).one()
        assert delivery.employee_id == first_id
        assert delivery.recipient_phone == "628100000002"
        assert delivery.status == "SENT"
        assert delivery.text_status == "SENT"
        assert delivery.pdf_status == "SENT"
        assert delivery.requested_by_user_id == 1

    history = client.get(f"/payroll/{session['session_id']}/send-history")
    assert history.status_code == 200
    assert history.json()[0]["status"] == "SENT"


def test_payroll_text_provider_exception_is_recorded_as_partial_delivery(
    payroll_client,
    monkeypatch,
):
    client, session_factory = payroll_client
    employee_id = add_employee(session_factory, code="EMP-008")
    add_identity(session_factory, employee_id, "628100000008")
    session = upload_payroll(client, payroll_csv({
        "Kode Karyawan": "EMP-008",
        "Nama": "Karyawan Sama",
        "No. Rekening": "888",
        "Departemen": "Operasional",
        "Gaji Pokok": "4000000",
    }))

    async def raise_text_error(_number: str, _message: str):
        raise RuntimeError("provider timeout")

    async def fake_send_raw(_payload: dict):
        return {"messages": [{"id": "document-message-id"}]}

    monkeypatch.setattr(payroll, "send_whatsapp_text", raise_text_error)
    monkeypatch.setattr(payroll, "send_whatsapp_raw", fake_send_raw)
    monkeypatch.setattr(payroll, "_generate_slip_pdf_bytes", lambda *_: b"synthetic-pdf")
    monkeypatch.setattr(
        payroll,
        "upload_to_cloudinary",
        lambda **_: "https://synthetic.example/slip.pdf",
    )

    response = client.post(
        f"/payroll/{session['session_id']}/send-whatsapp/0",
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PARTIAL"
    assert "provider timeout" in response.json()["detail"]
    with session_factory() as db:
        delivery = db.query(models.PayrollWhatsAppDelivery).one()
        assert delivery.status == "PARTIAL"
        assert delivery.text_status == "FAILED"
        assert delivery.pdf_status == "SENT"


def test_payroll_bulk_send_skips_unlinked_rows_and_logs_each_outcome(
    payroll_client,
    monkeypatch,
):
    client, session_factory = payroll_client
    linked_id = add_employee(session_factory, code="EMP-006")
    add_employee(session_factory, code="EMP-007")
    add_identity(session_factory, linked_id, "628100000006")
    session = upload_payroll(client, payroll_csv(
        {
            "Kode Karyawan": "EMP-006",
            "Nama": "Karyawan Sama",
            "No. Rekening": "666",
            "Departemen": "Operasional",
            "Gaji Pokok": "4000000",
        },
        {
            "Kode Karyawan": "EMP-007",
            "Nama": "Karyawan Sama",
            "No. Rekening": "777",
            "Departemen": "Operasional",
            "Gaji Pokok": "5000000",
        },
    ))
    sent_numbers = []

    async def fake_send_text(number: str, _message: str):
        sent_numbers.append(number)
        return {"messages": [{"id": "bulk-text"}]}

    async def fake_send_raw(_payload: dict):
        return {"messages": [{"id": "bulk-pdf"}]}

    monkeypatch.setattr(payroll, "send_whatsapp_text", fake_send_text)
    monkeypatch.setattr(payroll, "send_whatsapp_raw", fake_send_raw)
    monkeypatch.setattr(payroll, "_generate_slip_pdf_bytes", lambda *_: b"synthetic-pdf")
    monkeypatch.setattr(
        payroll,
        "upload_to_cloudinary",
        lambda **_: "https://synthetic.example/slip.pdf",
    )

    preview = client.get(f"/payroll/{session['session_id']}/whatsapp-recipients")
    assert [row["status"] for row in preview.json()["recipients"]] == [
        "ACTIVE",
        "WHATSAPP_NOT_LINKED",
    ]

    response = client.post(f"/payroll/{session['session_id']}/send-whatsapp-all")

    assert response.status_code == 200, response.text
    assert response.json()["sent"] == 1
    assert response.json()["skip"] == 1
    assert response.json()["results"][1]["status"] == "SKIP"
    assert sent_numbers == ["628100000006"]
    with session_factory() as db:
        deliveries = db.query(models.PayrollWhatsAppDelivery).order_by(
            models.PayrollWhatsAppDelivery.row_index,
        ).all()
        assert [item.status for item in deliveries] == ["SENT", "SKIPPED"]
