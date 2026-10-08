import datetime

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from migrate_local_to_postgres import replace_data, run


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


def _seed_source(engine):
    with Session(engine) as db:
        profile = models.Profile(code="OFFICE", nama="Office", cabang=["Jakarta"])
        db.add_all([
            profile,
            models.User(
                nama="HR",
                email="hr@example.test",
                hashed_password="hashed",
                role=models.RoleEnum.hr_master,
            ),
            models.BusinessRule(id=1),
            models.Holiday(tanggal=datetime.date(2026, 1, 1), keterangan="Holiday"),
        ])
        db.flush()

        employee = models.Employee(
            nama="Test Employee",
            employee_code="JIP-TEST",
            profile_code=profile.code,
            cabang="Jakarta",
        )
        batch = models.AttendanceUploadBatch(
            filename="attendance.xlsx",
            row_count=1,
            status="COMPLETED",
        )
        leave = models.LeaveRequest(
            nama="Test Employee",
            kategori="SAKIT",
            tanggal_mulai=datetime.date(2026, 1, 2),
            tanggal_selesai=datetime.date(2026, 1, 2),
            status="APPROVED",
        )
        db.add_all([employee, batch, leave])
        db.flush()
        db.add_all([
            models.EmployeeAdjustment(nama="Test Employee", bonus_lain=10),
            models.AbsenManual(nama="Test Employee", tahun=2026, bulan=1, jumlah=1),
            models.EmployeeImportCandidate(
                employee_code="JIP-NEXT",
                nama="Candidate",
                cabang="Jakarta",
                source_row=2,
                status="PENDING",
            ),
            models.EmploymentContract(
                employee_id=employee.id,
                contract_number=1,
                start_date=datetime.date(2026, 1, 1),
                end_date=datetime.date(2026, 12, 31),
                status="ACTIVE",
            ),
            models.WhatsAppIdentity(
                phone_number="+628123456789",
                employee_id=employee.id,
                status="ACTIVE",
            ),
            models.WhatsAppAuditLog(
                phone_number="+628123456789",
                employee_id=employee.id,
                event_type="LOGIN",
            ),
            models.WhatsAppProcessedMessage(message_id="wamid-test"),
            models.AttendanceDaily(
                employee_id=employee.id,
                attendance_date=datetime.date(2026, 1, 2),
                status="PRESENT",
                upload_batch=batch,
            ),
            models.AttendanceReview(
                employee_id=employee.id,
                attendance_date=datetime.date(2026, 1, 3),
                status="RESOLVED",
                leave_request=leave,
                upload_batch=batch,
            ),
            models.AttendanceRecapRecord(
                source_key="source-row-1",
                source_file_hash="source-hash",
                source_row=1,
                employee_id=employee.id,
                employee_code="JIP-TEST",
                source_payload={"source": "test"},
                reconciliation_status="MATCHED",
            ),
            models.LeaveBalanceLedger(
                employee_id=employee.id,
                year=2026,
                entry_type="GRANT_ANNUAL_RESET",
                amount=12,
                leave_request=leave,
            ),
        ])
        db.commit()

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE employees ADD COLUMN jenis_kontrak VARCHAR"))
        connection.execute(text("ALTER TABLE employees ADD COLUMN durasi_kontrak_bulan INTEGER"))
        connection.execute(text(
            "UPDATE employees SET jenis_kontrak='PKWT', durasi_kontrak_bulan=12 "
            "WHERE employee_code='JIP-TEST'"
        ))


def test_replacement_copies_all_mapped_tables_and_archives_legacy_columns():
    source_engine = _engine()
    target_engine = _engine()
    Base.metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)
    _seed_source(source_engine)
    with Session(target_engine) as db:
        old_profile = models.Profile(code="OLD", nama="Old profile")
        db.add(old_profile)
        db.flush()
        db.add(models.Employee(nama="Old employee", profile_code=old_profile.code))
        db.commit()

    try:
        with source_engine.connect() as source, target_engine.begin() as target:
            counts = replace_data(source, target)

        assert counts["employees"] == 1
        assert counts["leave_requests"] == 1
        assert counts["attendance_recap_records"] == 1
        assert counts["database_migration_archive"] == 1
        with Session(target_engine) as db:
            assert db.scalar(select(models.Employee.nama)) == "Test Employee"
            archive = db.scalar(select(models.DatabaseMigrationArchive))
            assert archive.source_table == "employees"
            assert archive.legacy_columns == {
                "jenis_kontrak": "PKWT",
                "durasi_kontrak_bulan": 12,
            }
            assert db.scalar(select(models.AttendanceDaily.status)) == "PRESENT"
            assert db.scalar(select(models.AttendanceRecapRecord.source_payload)) == {
                "source": "test"
            }
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_failed_transfer_transaction_leaves_existing_target_data_unchanged():
    source_engine = _engine()
    target_engine = _engine()
    Base.metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)
    _seed_source(source_engine)
    with Session(target_engine) as db:
        db.add(models.Profile(code="OLD", nama="Old profile"))
        db.flush()
        db.add(models.Employee(nama="Old employee", profile_code="OLD"))
        db.commit()

    try:
        with source_engine.connect() as source:
            with pytest.raises(RuntimeError, match="force rollback"):
                with target_engine.begin() as target:
                    replace_data(source, target)
                    raise RuntimeError("force rollback")
        with Session(target_engine) as db:
            assert db.scalar(select(models.Employee.nama)) == "Old employee"
            assert db.scalar(select(models.Profile.code)) == "OLD"
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_apply_requires_exact_target_confirmation_before_connecting(tmp_path, monkeypatch):
    source_path = tmp_path / "source.sqlite"
    source_path.touch()
    monkeypatch.setenv(
        "TEST_TARGET_URL",
        "postgresql://user:secret@example.test:5432/hr",
    )
    args = type(
        "Args",
        (),
        {
            "sqlite_file": str(source_path),
            "target_url_env": "TEST_TARGET_URL",
            "apply": True,
            "confirm_target": "example.test:5432/other",
        },
    )()

    with pytest.raises(RuntimeError, match="exactly match"):
        run(args)
