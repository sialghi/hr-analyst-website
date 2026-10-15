import io

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.branches import (
    employee_id_serial_in_use,
    next_employee_id,
    validate_new_employee_id,
)
from app.database import Base
from app.employee_imports import parse_employee_workbook, parse_master_workbook


@pytest.fixture
def branch_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(models.Profile(code="OFFICE", nama="Office"))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_next_employee_id_uses_global_highest_serial_across_branches(branch_session):
    branch_session.add_all(
        [
            models.Employee(
                nama="Existing",
                new_employee_id="JIP-030010",
                profile_code="OFFICE",
                cabang="Cab. Bandung",
            ),
            models.EmployeeImportCandidate(
                nama="Candidate",
                new_employee_id="JIP-020012",
                cabang="Gudang C",
                source_row=2,
            ),
            models.EmployeeIdSequence(id=1, next_serial=2),
        ]
    )
    branch_session.commit()

    assert next_employee_id(branch_session, "Cab. Bandung") == "JIP-030013"
    assert branch_session.get(models.EmployeeIdSequence, 1).next_serial == 14


def test_next_employee_id_uses_global_serial_for_different_branches(branch_session):
    assert next_employee_id(branch_session, "Gudang A") == "JIP-010001"
    assert next_employee_id(branch_session, "GLC") == "JIP-040002"


def test_next_employee_id_starts_at_one_when_no_serial_is_used(branch_session):
    assert next_employee_id(branch_session, "GLC") == "JIP-040001"


def test_next_employee_id_rejects_noncanonical_branch(branch_session):
    with pytest.raises(ValueError, match="tidak termasuk daftar"):
        next_employee_id(branch_session, "Testing 123")


def test_validate_new_employee_id_checks_branch_prefix_and_format():
    assert validate_new_employee_id("JIP-090123", "Kebayoran Lama")
    assert not validate_new_employee_id("JIP-010123", "Kebayoran Lama")
    assert not validate_new_employee_id("JIP-09012", "Kebayoran Lama")


def test_employee_id_serial_in_use_detects_cross_branch_collisions(branch_session):
    branch_session.add(
        models.Employee(
            nama="Existing",
            new_employee_id="JIP-020180",
            profile_code="OFFICE",
            cabang="Gudang C",
        )
    )
    branch_session.commit()

    assert employee_id_serial_in_use(branch_session, "JIP-010180")
    assert not employee_id_serial_in_use(branch_session, "JIP-010181")


def test_employee_import_rejects_duplicate_serials_across_branches():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data Karyawan"
    sheet.append([
        "ID Karyawan", "Nama Karyawan", "Cabang", "Kode Profil",
        "Status Kepegawaian",
    ])
    sheet.append(["JIP-010180", "Pegawai A", "Gudang A", "OFFICE", "PKWTT"])
    sheet.append(["JIP-020180", "Pegawai B", "Gudang C", "OFFICE", "PKWTT"])
    content = io.BytesIO()
    workbook.save(content)

    rows, errors = parse_employee_workbook(content.getvalue(), "employees.xlsx")

    assert rows == []
    assert len(errors) == 2
    assert all("unik lintas cabang" in item["reason"] for item in errors)


def test_master_import_rejects_duplicate_serials_across_branches():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Master ID"
    sheet.append(["ID Karyawan", "Nama", "Lokasi Kerja"])
    sheet.append(["JIP-010180", "Pegawai A", "Gudang A"])
    sheet.append(["JIP-020180", "Pegawai B", "Gudang C"])
    content = io.BytesIO()
    workbook.save(content)

    rows, conflicts = parse_master_workbook(content.getvalue())

    assert rows == []
    assert len(conflicts) == 2
    assert all("unik lintas cabang" in item["reason"] for item in conflicts)
