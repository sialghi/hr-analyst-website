import csv
import asyncio
import datetime
import io
from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, models, scheduler
from app.database import Base, get_db
from app.main import app
from app.routers import payroll, whatsapp

PREVIEW_PDF = b"%PDF-1.7\npreview-rendered-slip\n%%EOF"


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
            new_employee_id=code,
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


def payroll_csv(*rows: dict[str, str], include_id: bool = True) -> bytes:
    fields = ["ID Karyawan"] if include_id else []
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


def archive_payroll(client: TestClient, session_id: str, *pdfs: bytes):
    files = [
        ("pdfs", (f"SlipGaji_{index}.pdf", pdf_bytes, "application/pdf"))
        for index, pdf_bytes in enumerate(pdfs)
    ]
    return client.post(f"/payroll/{session_id}/archive-all", files=files)


def send_preview_pdf(client: TestClient, url: str, pdf: bytes = PREVIEW_PDF):
    return client.post(
        url,
        files={"pdf": ("preview.pdf", pdf, "application/pdf")},
    )


def test_payroll_template_includes_new_employee_id_and_upload_matches_whatsapp_by_id(payroll_client):
    client, session_factory = payroll_client
    first_id = add_employee(session_factory, code="EMP-001")
    second_id = add_employee(session_factory, code="EMP-002")
    add_identity(session_factory, second_id, "628123456789")

    template = client.get("/payroll/template?format=csv")
    assert template.status_code == 200
    assert template.text.lstrip("\ufeff").splitlines()[0].startswith("ID Karyawan,")

    session = upload_payroll(client, payroll_csv(
        {
            "ID Karyawan": "EMP-001",
            "Nama": "Karyawan Sama",
            "No. Rekening": "111",
            "Departemen": "Operasional",
            "Gaji Pokok": "4000000",
        },
        {
            "ID Karyawan": " emp-002 ",
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


def test_payroll_upload_without_id_still_previews_but_cannot_be_sent(payroll_client):
    client, _ = payroll_client
    session = upload_payroll(client, payroll_csv(
        {
            "Nama": "Nama Tanpa Kode",
            "No. Rekening": "123",
            "Departemen": "Operasional",
            "Gaji Pokok": "4000000",
        },
        include_id=False,
    ))

    row = session["rows"][0]
    assert row["_employee_id"] is None
    assert row["_wa_available"] is False
    assert row["_wa_status"] == "MISSING_NEW_EMPLOYEE_ID"


def test_payroll_send_revalidates_link_after_upload_and_logs_blocked_attempt(payroll_client, monkeypatch):
    client, session_factory = payroll_client
    employee_id = add_employee(session_factory, code="EMP-003")
    identity_id = add_identity(session_factory, employee_id, "628111222333")
    session = upload_payroll(client, payroll_csv({
        "ID Karyawan": "EMP-003",
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
    response = send_preview_pdf(client, f"/payroll/{session['session_id']}/send-whatsapp/0")

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
        "ID Karyawan": "EMP-004",
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
    uploaded_pdfs = []

    async def fake_send_text(number: str, message: str):
        sent_text.append((number, message))
        return {"messages": [{"id": "text-message-id"}]}

    async def fake_send_raw(payload: dict):
        sent_documents.append(payload)
        return {"messages": [{"id": "document-message-id"}]}

    monkeypatch.setattr(payroll, "send_whatsapp_text", fake_send_text)
    monkeypatch.setattr(payroll, "send_whatsapp_raw", fake_send_raw)
    monkeypatch.setattr(
        payroll,
        "upload_to_cloudinary",
        lambda **kwargs: (
            uploaded_pdfs.append(kwargs["file_bytes"])
            or "https://synthetic.example/slip.pdf"
        ),
    )

    response = send_preview_pdf(client, f"/payroll/{session['session_id']}/send-whatsapp/0")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "SENT"
    assert response.json()["wa_number"] == "628100000002"
    assert sent_text[0][0] == "628100000002"
    assert "TOTAL DITERIMA" in sent_text[0][1]
    assert sent_documents[0]["to"] == "628100000002"
    assert uploaded_pdfs == [PREVIEW_PDF]
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
        "ID Karyawan": "EMP-008",
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
    monkeypatch.setattr(
        payroll,
        "upload_to_cloudinary",
        lambda **_: "https://synthetic.example/slip.pdf",
    )

    response = send_preview_pdf(client, f"/payroll/{session['session_id']}/send-whatsapp/0")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PARTIAL"
    assert "provider timeout" in response.json()["detail"]
    with session_factory() as db:
        delivery = db.query(models.PayrollWhatsAppDelivery).one()
        assert delivery.status == "PARTIAL"
        assert delivery.text_status == "FAILED"
        assert delivery.pdf_status == "SENT"


def test_payroll_send_rejects_invalid_preview_pdf_without_contacting_providers(
    payroll_client,
    monkeypatch,
):
    client, session_factory = payroll_client
    employee_id = add_employee(session_factory, code="EMP-009")
    add_identity(session_factory, employee_id, "628100000009")
    session = upload_payroll(client, payroll_csv({
        "ID Karyawan": "EMP-009",
        "Nama": "Karyawan Sama",
        "No. Rekening": "999",
        "Departemen": "Operasional",
        "Gaji Pokok": "4000000",
    }))
    send_text = AsyncMock()
    monkeypatch.setattr(payroll, "send_whatsapp_text", send_text)

    response = send_preview_pdf(
        client,
        f"/payroll/{session['session_id']}/send-whatsapp/0",
        b"not-a-pdf",
    )

    assert response.status_code == 400
    send_text.assert_not_awaited()
    with session_factory() as db:
        assert db.query(models.PayrollWhatsAppDelivery).count() == 0


def test_legacy_bulk_send_is_disabled_to_require_preview_rendered_pdfs(payroll_client):
    client, _ = payroll_client

    response = client.post("/payroll/session/send-whatsapp-all")

    assert response.status_code == 409
    assert "pratinjau" in response.json()["detail"]


def test_archive_all_saves_final_pdfs_and_replaces_same_period(payroll_client):
    client, session_factory = payroll_client
    employee_id = add_employee(session_factory, code="EMP-ARCHIVE", name="Karyawan Arsip")
    session = upload_payroll(client, payroll_csv({
        "ID Karyawan": "EMP-ARCHIVE",
        "Nama": "Karyawan Arsip",
        "No. Rekening": "1234567890",
        "Departemen": "QA",
        "Gaji Pokok": "5000000",
    }))

    first = archive_payroll(client, session["session_id"], b"%PDF-first")

    assert first.status_code == 200, first.text
    assert first.json()["saved_count"] == 1
    assert first.json()["replaced_count"] == 0
    with session_factory() as db:
        archived = db.query(models.PayrollSlipArchive).filter_by(employee_id=employee_id).one()
        original_id = archived.id
        original_saved_at = archived.saved_at
        assert archived.payroll_period == "Okt-26"
        assert archived.pdf_bytes == b"%PDF-first"
        assert archived.expires_at > archived.saved_at

    second = archive_payroll(client, session["session_id"], b"%PDF-updated")

    assert second.status_code == 200, second.text
    assert second.json()["saved_count"] == 1
    assert second.json()["replaced_count"] == 1
    with session_factory() as db:
        archived = db.query(models.PayrollSlipArchive).filter_by(employee_id=employee_id).one()
        assert archived.id == original_id
        assert archived.pdf_bytes == b"%PDF-updated"
        assert archived.saved_at >= original_saved_at


def test_archive_all_rejects_unmatched_payroll_rows_without_partial_save(payroll_client):
    client, session_factory = payroll_client
    session = upload_payroll(client, payroll_csv({
        "ID Karyawan": "EMP-MISSING",
        "Nama": "Tidak Dikenal",
        "No. Rekening": "1234567890",
        "Departemen": "QA",
        "Gaji Pokok": "5000000",
    }))

    response = archive_payroll(client, session["session_id"], b"%PDF-missing-employee")

    assert response.status_code == 422
    assert "cocok dengan karyawan" in response.json()["detail"]
    with session_factory() as db:
        assert db.query(models.PayrollSlipArchive).count() == 0


def test_whatsapp_payslip_selection_only_sends_the_linked_employees_archive(
    payroll_client,
    monkeypatch,
):
    _, session_factory = payroll_client
    employee_id = add_employee(session_factory, code="EMP-WA-ARCHIVE", name="Pemilik Slip")
    other_employee_id = add_employee(session_factory, code="EMP-WA-OTHER", name="Karyawan Lain")
    phone = "628123456789"
    add_identity(session_factory, employee_id, phone)
    now = datetime.datetime.utcnow()
    with session_factory() as db:
        own_archive = models.PayrollSlipArchive(
            employee_id=employee_id,
            payroll_period="Okt-26",
            employee_name="Pemilik Slip",
            pdf_bytes=b"%PDF-owned",
            saved_at=now,
            expires_at=now + datetime.timedelta(days=365),
        )
        other_archive = models.PayrollSlipArchive(
            employee_id=other_employee_id,
            payroll_period="Sep-26",
            employee_name="Karyawan Lain",
            pdf_bytes=b"%PDF-other",
            saved_at=now,
            expires_at=now + datetime.timedelta(days=365),
        )
        db.add_all([own_archive, other_archive])
        db.commit()
        own_archive_id = own_archive.id
        other_archive_id = other_archive.id

    send_list = AsyncMock()
    send_pdf = AsyncMock(return_value={"messages": [{"id": "wamid.test"}]})
    send_text = AsyncMock()
    monkeypatch.setattr(whatsapp, "send_whatsapp_list", send_list)
    monkeypatch.setattr(whatsapp, "send_whatsapp_pdf", send_pdf)
    monkeypatch.setattr(whatsapp, "send_whatsapp_text", send_text)

    with session_factory() as db:
        asyncio.run(whatsapp.process_whatsapp_incoming(phone, "slip gaji", None, db))
        assert send_list.await_count == 1
        menu_rows = send_list.await_args.kwargs["sections"][0]["rows"]
        assert menu_rows[0]["id"] == f"slip_archive_{own_archive_id}"
        asyncio.run(whatsapp.process_whatsapp_incoming(
            phone,
            "",
            f"slip_archive_{own_archive_id}",
            db,
        ))
        asyncio.run(whatsapp.process_whatsapp_incoming(
            phone,
            "",
            f"slip_archive_{other_archive_id}",
            db,
        ))

    send_pdf.assert_awaited_once()
    assert send_pdf.await_args.args[1] == b"%PDF-owned"
    assert send_text.await_count == 1


def test_whatsapp_pdf_delivery_uploads_private_media_then_sends_document(monkeypatch):
    calls = []

    class MockResponse:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class MockAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/media"):
                return MockResponse({"id": "media-id"})
            return MockResponse({"messages": [{"id": "wamid.test"}]})

    monkeypatch.setattr(
        whatsapp,
        "get_env_var",
        lambda name: {"WHATSAPP_ACCESS_TOKEN": "test-token", "WHATSAPP_PHONE_NUMBER_ID": "phone-id"}.get(name, ""),
    )
    monkeypatch.setattr(whatsapp.httpx, "AsyncClient", MockAsyncClient)

    result = asyncio.run(whatsapp.send_whatsapp_pdf(
        "08123456789",
        b"%PDF-private",
        "SlipGaji_Test.pdf",
        "Slip gaji periode tes",
    ))

    assert result == {"messages": [{"id": "wamid.test"}]}
    assert len(calls) == 2
    assert calls[0][1]["data"] == {"messaging_product": "whatsapp"}
    assert calls[0][1]["files"]["file"][1] == b"%PDF-private"
    assert calls[1][1]["json"]["to"] == "628123456789"
    assert calls[1][1]["json"]["document"]["id"] == "media-id"
    assert calls[1][1]["json"]["document"]["filename"] == "SlipGaji_Test.pdf"


def test_expired_payroll_slips_are_deleted_by_daily_cleanup(payroll_client, monkeypatch):
    _, session_factory = payroll_client
    employee_id = add_employee(session_factory, code="EMP-ARCHIVE-EXPIRY")
    now = datetime.datetime.utcnow()
    with session_factory() as db:
        db.add_all([
            models.PayrollSlipArchive(
                employee_id=employee_id,
                payroll_period="Expired",
                employee_name="Karyawan Sama",
                pdf_bytes=b"%PDF-expired",
                saved_at=now - datetime.timedelta(days=366),
                expires_at=now - datetime.timedelta(seconds=1),
            ),
            models.PayrollSlipArchive(
                employee_id=employee_id,
                payroll_period="Current",
                employee_name="Karyawan Sama",
                pdf_bytes=b"%PDF-current",
                saved_at=now,
                expires_at=now + datetime.timedelta(days=365),
            ),
        ])
        db.commit()

    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    scheduler.run_expired_payroll_slip_cleanup_sync()

    with session_factory() as db:
        remaining = db.query(models.PayrollSlipArchive).all()
        assert [archive.payroll_period for archive in remaining] == ["Current"]
