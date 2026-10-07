import datetime

import pytest
import io

from openpyxl import Workbook
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    AttendanceDaily,
    AttendanceRecapRecord,
    AttendanceReview,
    AttendanceUploadBatch,
    BusinessRule,
    Employee,
    Holiday,
    LeaveBalanceLedger,
    LeaveRequest,
    Profile,
    RoleEnum,
    User,
)
from rebuild_local_employee_data import (
    rebuild_database,
    reconcile_recap_rows,
    validate_local_target,
)
from app.employee_imports import parse_recap_workbook


def _employee(code, nama, nik, cabang, payroll_status, join_date):
    return {
        "employee_code": code,
        "nama": nama,
        "nik": nik,
        "join_date": join_date,
        "uang_makan_override": None,
        "jabatan": "Staff",
        "cabang": cabang,
        "payroll_status": payroll_status,
    }


def _recap(row, employee_code, nik, nama, mark, date):
    return {
        "source_row": row,
        "source_values": [
            {"header": "ID", "value": employee_code},
            {"header": "NIK", "value": nik},
            {"header": "Cabang", "value": "Cabang sumber"},
            {"header": "Nama", "value": nama},
            {"header": "Status", "value": "Bulanan"},
            {"header": "Tanggal", "value": date.isoformat()},
            {"header": "Keterangan (S/I/CS)", "value": mark},
        ],
        "employee_code": employee_code,
        "nik": nik,
        "cabang": "Cabang sumber",
        "nama": nama,
        "payroll_status": "Bulanan",
        "tanggal": date,
        "mark": mark,
    }


def test_target_guard_accepts_only_expected_local_sqlite_file(tmp_path):
    db_path = (tmp_path / "local.db").resolve()
    db_path.touch()
    database_url = f"sqlite:///{db_path.as_posix()}"

    assert validate_local_target(database_url, db_path) == db_path
    with pytest.raises(ValueError, match="Target harus berupa file SQLite lokal"):
        validate_local_target("sqlite:///:memory:", db_path)
    with pytest.raises(ValueError, match="Target harus berupa file SQLite lokal"):
        validate_local_target("postgresql://example.invalid/db", db_path)


def test_recap_reconciliation_trusts_jip_then_unique_nik_or_name():
    master = [
        _employee("JIP-1", "Nama Satu", "1111111111111111", "Cabang A", "Bulanan", None),
        _employee("JIP-2", "Nama Dua", "2222222222222222", "Cabang B", "Harian", None),
    ]
    recap = [
        _recap(2, "JIP-1", "9999999999999999", "Nama Berbeda", "C", datetime.date(2026, 1, 1)),
        _recap(3, None, "2222222222222222", "Nama Berbeda", "T", datetime.date(2026, 1, 2)),
        _recap(4, None, None, "Nama Dua", "CS", datetime.date(2026, 1, 3)),
        _recap(5, None, None, "Tidak Dikenal", "S", datetime.date(2026, 1, 4)),
        _recap(6, "JIP-UNKNOWN", "1111111111111111", "Nama Satu", "C", datetime.date(2026, 1, 5)),
    ]

    result = reconcile_recap_rows(master, recap)

    assert [item["reconciliation_status"] for item in result] == [
        "MATCHED_BY_JIP",
        "MATCHED_BY_NIK",
        "MATCHED_BY_NAME",
        "UNRESOLVED_IDENTITY",
        "UNRESOLVED_JIP_ID",
    ]
    assert result[0]["master"]["employee_code"] == "JIP-1"
    assert "Nama Rekap berbeda" in result[0]["identity_warning"]
    assert result[4]["master"] is None


def test_recap_parser_keeps_rows_with_blank_id_and_original_cells():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Rekap Kehadiran"
    sheet.append(["No", "ID", "NIK", "Cabang", "Nama", "Status", "Tanggal", "Keterangan (S/I/CS)"])
    sheet.append([1, None, "1234567890123456", " Cabang A ", "Nama A", "Bulanan", datetime.date(2026, 1, 1), "C"])
    contents = io.BytesIO()
    workbook.save(contents)

    rows, conflicts = parse_recap_workbook(contents.getvalue())

    assert not conflicts
    assert len(rows) == 1
    assert rows[0]["employee_code"] is None
    assert {"header": "ID", "value": None} in rows[0]["source_values"]
    assert {"header": "Cabang", "value": " Cabang A "} in rows[0]["source_values"]


def test_rebuild_is_transactional_and_preserves_configuration():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSession()
    try:
        db.add_all([
            Profile(code="OFFICE", nama="Office"),
            Profile(code="DRIVER", nama="Driver"),
            BusinessRule(profil_default="OFFICE"),
            User(nama="HR", email="hr@example.test", hashed_password="hash", role=RoleEnum.hr_master),
            Holiday(tanggal=datetime.date(2026, 1, 1), keterangan="Libur"),
        ])
        db.flush()
        old_employee = Employee(
            employee_code="OLD-1",
            nama="Nama Lama",
            nik="1111111111111111",
            profile_code="DRIVER",
            employment_status="PHL",
            active=True,
        )
        db.add(old_employee)
        batch = AttendanceUploadBatch(filename="old.xlsx")
        db.add(batch)
        old_leave = LeaveRequest(
            nama="Nama Lama",
            kategori="CUTI_TAHUNAN",
            tanggal_mulai=datetime.date(2025, 1, 1),
            tanggal_selesai=datetime.date(2025, 1, 1),
            status="APPROVED",
        )
        db.add(old_leave)
        db.flush()
        db.add_all([
            AttendanceDaily(
                employee_id=old_employee.id,
                attendance_date=datetime.date(2025, 1, 1),
                status="PRESENT",
                upload_batch_id=batch.id,
            ),
            AttendanceReview(
                employee_id=old_employee.id,
                attendance_date=datetime.date(2025, 1, 2),
                leave_request_id=old_leave.id,
                upload_batch_id=batch.id,
            ),
            LeaveBalanceLedger(
                employee_id=old_employee.id,
                year=2025,
                entry_type="USED",
                amount=-1,
                leave_request_id=old_leave.id,
            ),
        ])
        db.commit()

        master = [
            _employee(
                "JIP-1",
                "Nama Satu",
                "1111111111111111",
                "Cabang A",
                "Bulanan",
                datetime.date(2020, 1, 1),
            ),
            _employee(
                "JIP-2",
                "Nama Dua",
                "2222222222222222",
                "Cabang B",
                "Harian",
                datetime.date(2020, 1, 1),
            ),
        ]
        recap = [
            _recap(2, "JIP-1", "9999999999999999", "Nama Satu Lama", "C", datetime.date(2026, 1, 1)),
            _recap(3, None, "2222222222222222", "Nama Dua Lama", "T", datetime.date(2026, 1, 2)),
            _recap(4, None, None, "Nama Dua", "CS", datetime.date(2026, 1, 3)),
            _recap(5, None, None, "Tidak Dikenal", "S", datetime.date(2026, 1, 4)),
        ]
        result = rebuild_database(
            db,
            master,
            recap,
            "master-hash",
            "recap-hash",
            datetime.date(2026, 10, 23),
        )

        employees = {row.employee_code: row for row in db.query(Employee).all()}
        assert set(employees) == {"JIP-1", "JIP-2"}
        assert employees["JIP-1"].profile_code == "DRIVER"
        assert employees["JIP-1"].employment_status == "PKWTT"
        assert not employees["JIP-1"].profile_needs_review
        assert employees["JIP-2"].profile_code == "OFFICE"
        assert employees["JIP-2"].profile_needs_review
        assert not employees["JIP-2"].active

        raw_records = db.query(AttendanceRecapRecord).all()
        assert len(raw_records) == 4
        assert sum(row.employee_id is None for row in raw_records) == 1
        jip_row = next(row for row in raw_records if row.employee_code == "JIP-1")
        assert jip_row.source_nama == "Nama Satu Lama"
        assert jip_row.canonical_nama == "Nama Satu"
        assert jip_row.source_cabang == "Cabang sumber"
        assert jip_row.canonical_cabang == "Cabang A"
        assert jip_row.source_payload[3] == {"header": "Nama", "value": "Nama Satu Lama"}
        assert db.query(LeaveRequest).count() == 2
        assert db.query(LeaveRequest).filter(LeaveRequest.kategori == "SAKIT").count() == 0
        assert db.query(LeaveBalanceLedger).filter(LeaveBalanceLedger.entry_type == "USED").count() == 2
        assert db.query(AttendanceDaily).count() == 0
        assert db.query(AttendanceReview).count() == 0
        assert db.query(AttendanceUploadBatch).count() == 0
        assert result["linked_recap_records"] == 3
        assert result["unresolved_recap_records"] == 1
        assert result["leave_requests"] == 2
        assert db.query(User).count() == 1
        assert db.query(Holiday).count() == 1
        assert db.query(Profile).count() == 2
        assert db.query(BusinessRule).one().profil_default == "OFFICE"

        repeated = rebuild_database(
            db,
            master,
            recap,
            "master-hash",
            "recap-hash",
            datetime.date(2026, 10, 23),
        )
        assert repeated["profile_review"] == 1
        assert db.query(Employee).count() == 2
        assert db.query(AttendanceRecapRecord).count() == 4
        assert db.query(LeaveRequest).count() == 2
        assert db.query(LeaveBalanceLedger).filter(LeaveBalanceLedger.entry_type == "USED").count() == 2
        assert db.query(Employee).filter(Employee.employee_code == "JIP-2").one().profile_needs_review
    finally:
        db.close()
        test_engine.dispose()
