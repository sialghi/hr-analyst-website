# -*- coding: utf-8 -*-
"""Safely rebuild the local employee roster and clean-attendance recap."""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.config import get_today_jakarta
from app.employee_imports import normalize_text, parse_master_workbook, parse_recap_workbook
from app.leave_logic import record_leave_used, run_leave_quota_jobs
from app.models import (
    AttendanceRecapRecord,
    BusinessRule,
    Employee,
    LeaveRequest,
    Profile,
)


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
LOCAL_DATABASE = (BACKEND_DIR / "hr_app.db").resolve()
MASTER_PATH = PROJECT_DIR / "Data Master Karyawan.xlsx"
RECAP_PATH = PROJECT_DIR / "Rekap_Kehadiran_Bersih.xlsx"
PRESERVED_TABLES = ("users", "profiles", "business_rule", "holidays")
RESET_TABLES = (
    "attendance_reviews",
    "leave_balance_ledger",
    "attendance_recap_records",
    "attendance_daily",
    "leave_requests",
    "employee_adjustments",
    "absen_manual",
    "employment_contracts",
    "employee_import_candidates",
    "whatsapp_identities",
    "whatsapp_audit_logs",
    "whatsapp_processed_messages",
    "attendance_upload_batches",
    "employees",
)
LEAVE_MARKS = {
    "C": ("CUTI_TAHUNAN", 1.0),
    "CS": ("CUTI_SETENGAH_HARI", 0.5),
    "S": ("SAKIT", 1.0),
}
EMPLOYMENT_STATUS_MAP = {"Bulanan": "PKWTT", "Harian": "PHL"}


def validate_local_target(database_url: str, expected_path: Path = LOCAL_DATABASE) -> Path:
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database or parsed.database == ":memory:":
        raise ValueError("Target harus berupa file SQLite lokal, bukan database jarak jauh atau in-memory.")
    target = Path(parsed.database)
    if not target.is_absolute():
        target = Path.cwd() / target
    target = target.resolve()
    if target != expected_path.resolve():
        raise ValueError(f"Target ditolak; hanya database lokal yang diizinkan: {expected_path}")
    if not target.is_file():
        raise ValueError(f"Database lokal tidak ditemukan: {target}")
    return target


def _file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _master_indexes(master_rows: list[dict]) -> tuple[dict, dict, dict]:
    by_code = {row["employee_code"]: row for row in master_rows}
    by_nik: dict[str, list[dict]] = collections.defaultdict(list)
    by_name: dict[str, list[dict]] = collections.defaultdict(list)
    for row in master_rows:
        if row["nik"]:
            by_nik[row["nik"]].append(row)
        by_name[normalize_text(row["nama"])].append(row)
    return by_code, by_nik, by_name


def reconcile_recap_rows(master_rows: list[dict], recap_rows: list[dict]) -> list[dict]:
    """Resolve only by JIP ID, or by unique NIK/name when the source ID is blank."""
    by_code, by_nik, by_name = _master_indexes(master_rows)
    reconciled = []
    for row in recap_rows:
        master = None
        status = ""
        warning_parts = []
        if row["employee_code"]:
            master = by_code.get(row["employee_code"])
            status = "MATCHED_BY_JIP" if master else "UNRESOLVED_JIP_ID"
        else:
            nik_matches = by_nik.get(row["nik"], []) if row["nik"] else []
            if len(nik_matches) == 1:
                master = nik_matches[0]
                status = "MATCHED_BY_NIK"
            else:
                name_matches = by_name.get(normalize_text(row["nama"]), [])
                if len(name_matches) == 1:
                    master = name_matches[0]
                    status = "MATCHED_BY_NAME"
                    if len(nik_matches) > 1:
                        warning_parts.append("NIK tidak unik; digunakan nama persis yang unik.")
                else:
                    status = "UNRESOLVED_IDENTITY"

        if master:
            if normalize_text(row["nama"]) != normalize_text(master["nama"]):
                warning_parts.append("Nama Rekap berbeda dari Master.")
            if row["nik"] and row["nik"] != master["nik"]:
                warning_parts.append("NIK Rekap berbeda dari Master.")
        reconciled.append({
            "source": row,
            "master": master,
            "reconciliation_status": status,
            "identity_warning": " ".join(warning_parts) or None,
        })
    return reconciled


def _legacy_employees(connection: sqlite3.Connection) -> list[dict]:
    columns = {row[1] for row in connection.execute('PRAGMA table_info("employees")')}
    required = {"id", "nama", "profile_code"}
    if not required.issubset(columns):
        raise ValueError(f"Kolom inti tabel employees tidak lengkap: {sorted(required - columns)}")
    optional = (
        "employee_code",
        "nik",
        "active",
        "employment_status",
        "profile_needs_review",
    )
    select_columns = ["id", "nama", "profile_code"]
    select_columns.extend(column for column in optional if column in columns)
    selected = ", ".join(f'"{column}"' for column in select_columns)
    return [
        dict(zip(select_columns, row))
        for row in connection.execute(f"SELECT {selected} FROM employees")
    ]


def _find_legacy_matches(master_rows: list[dict], legacy_rows: list[dict]) -> dict[str, dict]:
    by_nik: dict[str, list[dict]] = collections.defaultdict(list)
    by_name: dict[str, list[dict]] = collections.defaultdict(list)
    for old in legacy_rows:
        if old.get("nik"):
            by_nik[str(old["nik"]).strip()].append(old)
        by_name[normalize_text(old["nama"])].append(old)

    matches = {}
    for row in master_rows:
        nik_matches = by_nik.get(row["nik"], []) if row["nik"] else []
        if len(nik_matches) == 1:
            matches[row["employee_code"]] = nik_matches[0]
            continue
        name_matches = by_name.get(normalize_text(row["nama"]), [])
        if len(name_matches) == 1:
            matches[row["employee_code"]] = name_matches[0]
    return matches


def _table_fingerprint(connection: sqlite3.Connection, table_name: str) -> str:
    columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table_name}")')]
    rows = connection.execute(f'SELECT * FROM "{table_name}" ORDER BY rowid').fetchall()
    payload = json.dumps(
        {"columns": columns, "rows": rows},
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_preflight(path: Path, master_rows: list[dict]) -> dict:
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing_tables = (set(PRESERVED_TABLES) | set(RESET_TABLES)) - tables
        if missing_tables:
            raise ValueError(f"Tabel database lokal tidak lengkap: {sorted(missing_tables)}")
        legacy = _legacy_employees(connection)
        profile_codes = {row[0] for row in connection.execute("SELECT code FROM profiles")}
        rule_rows = connection.execute("SELECT profil_default FROM business_rule ORDER BY id").fetchall()
        default_profile = next((row[0] for row in rule_rows if row[0] in profile_codes), None)
        if not default_profile:
            raise ValueError("Profil default yang valid tidak ditemukan; reset dibatalkan.")
        preserved_hashes = {
            table: _table_fingerprint(connection, table)
            for table in PRESERVED_TABLES
        }
        table_counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in set(PRESERVED_TABLES) | set(RESET_TABLES)
        }
        legacy_matches = _find_legacy_matches(master_rows, legacy)
        return {
            "legacy_employee_count": len(legacy),
            "legacy_match_count": len(legacy_matches),
            "default_profile": default_profile,
            "profile_codes": profile_codes,
            "legacy_matches": legacy_matches,
            "preserved_hashes": preserved_hashes,
            "table_counts": table_counts,
        }
    finally:
        connection.close()


def _read_workbooks() -> tuple[list[dict], list[dict], str, str]:
    if not MASTER_PATH.is_file() or not RECAP_PATH.is_file():
        raise ValueError("Workbook sumber tidak ditemukan di root proyek.")
    master_bytes = MASTER_PATH.read_bytes()
    recap_bytes = RECAP_PATH.read_bytes()
    master_rows, master_conflicts = parse_master_workbook(master_bytes)
    recap_rows, recap_conflicts = parse_recap_workbook(recap_bytes)
    if master_conflicts or recap_conflicts:
        raise ValueError(
            "Workbook memiliki baris yang tidak lolos validasi. "
            f"Konflik Master={len(master_conflicts)}, Rekap={len(recap_conflicts)}."
        )
    if not master_rows or not recap_rows:
        raise ValueError("Workbook kosong; reset dibatalkan.")
    if len({row["employee_code"] for row in master_rows}) != len(master_rows):
        raise ValueError("ID JIP duplikat di Master; reset dibatalkan.")
    return master_rows, recap_rows, _file_hash(master_bytes), _file_hash(recap_bytes)


def _ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    with engine.begin() as connection:
        employee_columns = {column["name"] for column in inspector.get_columns("employees")}
        if "profile_needs_review" not in employee_columns:
            connection.execute(text(
                "ALTER TABLE employees ADD COLUMN profile_needs_review BOOLEAN NOT NULL DEFAULT 0"
            ))
        leave_columns = {column["name"] for column in inspector.get_columns("leave_requests")}
        if "import_key" not in leave_columns:
            connection.execute(text("ALTER TABLE leave_requests ADD COLUMN import_key VARCHAR"))
        recap_columns = {column["name"] for column in inspector.get_columns("attendance_recap_records")}
        if "source_payload" not in recap_columns:
            connection.execute(text(
                "ALTER TABLE attendance_recap_records ADD COLUMN source_payload JSON"
            ))


def _backup_database(path: Path) -> Path:
    backup_dir = BACKEND_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"hr_app.pre_employee_reset_{stamp}.db"
    source = sqlite3.connect(str(path))
    destination = sqlite3.connect(str(backup_path))
    try:
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Backup SQLite gagal verifikasi integritas: {integrity}")
    finally:
        destination.close()
        source.close()
    return backup_path


def rebuild_database(
    db: Session,
    master_rows: list[dict],
    recap_rows: list[dict],
    master_hash: str,
    recap_hash: str,
    effective_date: datetime.date,
    expected_matches: dict[str, dict] | None = None,
    expected_preserved_hashes: dict[str, str] | None = None,
) -> dict:
    """Replace employee-linked data in one transaction, preserving global configuration."""
    reconciled = reconcile_recap_rows(master_rows, recap_rows)
    if db.in_transaction():
        db.rollback()
    with db.begin():
        if expected_preserved_hashes is not None:
            raw_connection = db.connection().connection.driver_connection
            current_hashes = {
                table: _table_fingerprint(raw_connection, table)
                for table in PRESERVED_TABLES
            }
            if current_hashes != expected_preserved_hashes:
                raise RuntimeError("Akun/profil/aturan/tanggal merah berubah sejak preflight.")

        legacy_rows = db.query(Employee).all()
        legacy_by_code = _find_legacy_matches(master_rows, [
            {
                "id": employee.id,
                "nama": employee.nama,
                "nik": employee.nik,
                "profile_code": employee.profile_code,
                "active": employee.active,
                "employment_status": employee.employment_status,
                "profile_needs_review": employee.profile_needs_review,
            }
            for employee in legacy_rows
        ])
        if expected_matches is not None:
            if set(legacy_by_code) != set(expected_matches):
                raise RuntimeError("Data karyawan berubah sejak preflight; reset dibatalkan.")
            for code, expected in expected_matches.items():
                current = legacy_by_code[code]
                if any(
                    current.get(field) != expected.get(field)
                    for field in (
                        "id",
                        "nama",
                        "nik",
                        "profile_code",
                        "active",
                        "employment_status",
                        "profile_needs_review",
                    )
                ):
                    raise RuntimeError(f"Data karyawan {code} berubah sejak preflight; reset dibatalkan.")

        old_by_id = {
            employee.id: {
                "profile_code": employee.profile_code,
                "active": employee.active,
                "employment_status": employee.employment_status,
                "profile_needs_review": employee.profile_needs_review,
            }
            for employee in legacy_rows
        }
        rule = db.query(BusinessRule).order_by(BusinessRule.id).first()
        profiles = {profile.code for profile in db.query(Profile).all()}
        default_profile = rule.profil_default if rule and rule.profil_default in profiles else None
        if not default_profile:
            raise RuntimeError("Profil default tidak valid; reset dibatalkan.")

        deleted_counts = {}
        for table_name in RESET_TABLES:
            result = db.execute(text(f'DELETE FROM "{table_name}"'))
            deleted_counts[table_name] = result.rowcount
        db.expunge_all()
        db.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_leave_requests_import_key "
            "ON leave_requests (import_key)"
        ))
        db.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_attendance_recap_records_source_key "
            "ON attendance_recap_records (source_key)"
        ))
        db.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_employees_employee_code "
            "ON employees (employee_code)"
        ))
        db.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_employees_nik ON employees (nik)"
        ))

        employee_by_code = {}
        review_codes = set()
        for row in master_rows:
            legacy = legacy_by_code.get(row["employee_code"])
            old = old_by_id.get(legacy["id"]) if legacy else None
            payroll_status = row["payroll_status"]
            employment_status = EMPLOYMENT_STATUS_MAP.get(payroll_status)
            if not employment_status and old and old["employment_status"] in {"PKWTT", "PKWT", "PHL"}:
                employment_status = old["employment_status"]
            if not employment_status:
                employment_status = "PKWTT"
            old_profile_valid = bool(old and old["profile_code"] in profiles)
            profile_code = old["profile_code"] if old_profile_valid else default_profile
            needs_review = bool(
                legacy is None
                or (old and old["profile_needs_review"])
                or (old and not old_profile_valid)
            )
            if needs_review:
                review_codes.add(row["employee_code"])

            employee = Employee(
                employee_code=row["employee_code"],
                nama=row["nama"],
                nik=row["nik"],
                profile_code=profile_code,
                profile_needs_review=needs_review,
                active=True if needs_review else (bool(old["active"]) if old else True),
                cabang=row["cabang"],
                jabatan=row["jabatan"],
                payroll_status=payroll_status,
                uang_makan_override=row["uang_makan_override"],
                employment_status=employment_status,
                join_date=row["join_date"],
            )
            db.add(employee)
            employee_by_code[row["employee_code"]] = employee
        db.flush()

        quota_result = run_leave_quota_jobs(db, target_date=effective_date, commit=False)
        if quota_result["errors"]:
            raise RuntimeError("Gagal membangun kuota cuti: " + "; ".join(quota_result["errors"]))

        if review_codes:
            db.query(Employee).filter(Employee.employee_code.in_(review_codes)).update(
                {Employee.active: False},
                synchronize_session=False,
            )

        raw_records = []
        imported_leaves = []
        for item in reconciled:
            source = item["source"]
            master = item["master"]
            linked_employee = employee_by_code.get(master["employee_code"]) if master else None
            raw_records.append(AttendanceRecapRecord(
                source_key=f"{recap_hash}:{source['source_row']}",
                source_file_hash=recap_hash,
                source_row=source["source_row"],
                employee_id=linked_employee.id if linked_employee else None,
                employee_code=source["employee_code"],
                source_nik=source["nik"],
                source_cabang=source["cabang"] or None,
                source_nama=source["nama"] or None,
                source_payroll_status=source["payroll_status"],
                source_payload=source.get("source_values") or {
                    "employee_code": source["employee_code"],
                    "nik": source["nik"],
                    "cabang": source["cabang"],
                    "nama": source["nama"],
                    "payroll_status": source["payroll_status"],
                    "tanggal": source["tanggal"].isoformat() if source["tanggal"] else None,
                    "mark": source["mark"],
                },
                attendance_date=source["tanggal"],
                mark=source["mark"] or None,
                canonical_nama=master["nama"] if master else None,
                canonical_cabang=master["cabang"] if master else None,
                reconciliation_status=item["reconciliation_status"],
                identity_warning=item["identity_warning"],
            ))

            leave_mapping = LEAVE_MARKS.get(source["mark"])
            if linked_employee and leave_mapping:
                category, days = leave_mapping
                leave = LeaveRequest(
                    import_key=f"clean-recap:{recap_hash}:{source['source_row']}",
                    nama=master["nama"],
                    kategori=category,
                    tanggal_mulai=source["tanggal"],
                    tanggal_selesai=source["tanggal"],
                    jumlah_hari=days,
                    alasan=f"Diimpor dari Rekap Kehadiran Bersih ({source['mark']}).",
                    status="APPROVED",
                    catatan_hr="Histori dari Rekap Kehadiran Bersih.",
                    approved_by="Import Rekap Kehadiran Bersih",
                    approved_at=datetime.datetime.utcnow(),
                )
                db.add(leave)
                imported_leaves.append((leave, linked_employee.id, source["tanggal"].year, category, days))

        db.add_all(raw_records)
        db.flush()
        for leave, employee_id, year, category, days in imported_leaves:
            db.flush()
            if category in ("CUTI_TAHUNAN", "CUTI_SETENGAH_HARI"):
                record_leave_used(
                    db,
                    employee_id,
                    year,
                    days,
                    leave.id,
                    f"{category} {leave.tanggal_mulai} (import Rekap)",
                    commit=False,
                )

    return {
        "employees": len(master_rows),
        "recap_records": len(raw_records),
        "linked_recap_records": sum(bool(item["master"]) for item in reconciled),
        "unresolved_recap_records": sum(not item["master"] for item in reconciled),
        "leave_requests": len(imported_leaves),
        "profile_review": len(review_codes),
        "quota_jobs": quota_result["summary"],
        "deleted_counts": deleted_counts,
    }


def _verify_result(
    path: Path,
    master_rows: list[dict],
    recap_rows: list[dict],
    recap_hash: str,
    preserved_hashes: dict[str, str],
    expected_matches: dict[str, dict],
    default_profile: str,
) -> dict:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in PRESERVED_TABLES + RESET_TABLES
        }
        raw_count = connection.execute(
            "SELECT COUNT(*) FROM attendance_recap_records"
        ).fetchone()[0]
        if counts["employees"] != len(master_rows):
            raise RuntimeError(f"Verifikasi jumlah karyawan gagal: {counts['employees']}.")
        if raw_count != len(recap_rows):
            raise RuntimeError(f"Verifikasi baris Rekap gagal: {raw_count}.")
        empty_tables = (
            "attendance_reviews",
            "attendance_daily",
            "employee_adjustments",
            "absen_manual",
            "employment_contracts",
            "employee_import_candidates",
            "whatsapp_identities",
            "whatsapp_audit_logs",
            "whatsapp_processed_messages",
            "attendance_upload_batches",
        )
        if any(counts[table] for table in empty_tables):
            raise RuntimeError("Masih ada data histori lama yang seharusnya sudah di-reset.")
        stored_rows = connection.execute(
            "SELECT source_row, source_file_hash, source_payload "
            "FROM attendance_recap_records ORDER BY source_row"
        ).fetchall()
        expected_rows = sorted(row["source_row"] for row in recap_rows)
        if [row[0] for row in stored_rows] != expected_rows or any(
            row[1] != recap_hash for row in stored_rows
        ):
            raise RuntimeError("Baris atau checksum Rekap sumber tidak lengkap.")
        expected_payloads = {
            row["source_row"]: row.get("source_values")
            or {
                "employee_code": row["employee_code"],
                "nik": row["nik"],
                "cabang": row["cabang"],
                "nama": row["nama"],
                "payroll_status": row["payroll_status"],
                "tanggal": row["tanggal"].isoformat() if row["tanggal"] else None,
                "mark": row["mark"],
            }
            for row in recap_rows
        }
        if any(json.loads(row[2]) != expected_payloads[row[0]] for row in stored_rows):
            raise RuntimeError("Nilai asli Rekap tidak tersimpan lengkap.")

        expected_by_code = {row["employee_code"]: row for row in master_rows}
        expected_review_count = (
            len(master_rows) - len(expected_matches)
            + sum(bool(row.get("profile_needs_review")) for row in expected_matches.values())
        )
        employee_rows = connection.execute(
            "SELECT employee_code, nama, nik, cabang, jabatan, payroll_status, "
            "employment_status, join_date, profile_code, active, profile_needs_review "
            "FROM employees"
        ).fetchall()
        if len({row[0] for row in employee_rows}) != len(master_rows):
            raise RuntimeError("ID JIP karyawan tidak unik setelah import.")
        for employee in employee_rows:
            source = expected_by_code.get(employee[0])
            if not source:
                raise RuntimeError(f"ID JIP tak dikenal tersimpan: {employee[0]}")
            expected_status = EMPLOYMENT_STATUS_MAP.get(source["payroll_status"], employee[6])
            if (
                employee[1] != source["nama"]
                or employee[2] != source["nik"]
                or employee[3] != source["cabang"]
                or employee[4] != source["jabatan"]
                or employee[5] != source["payroll_status"]
                or employee[6] != expected_status
                or employee[7] != (source["join_date"].isoformat() if source["join_date"] else None)
            ):
                raise RuntimeError(f"Data Master tidak cocok untuk ID JIP {employee[0]}.")
            if employee[10] and employee[9]:
                raise RuntimeError(f"Profil sementara {employee[0]} tidak dinonaktifkan.")
            expected_profile = (
                expected_matches[employee[0]]["profile_code"]
                if employee[0] in expected_matches
                else default_profile
            )
            if employee[8] != expected_profile:
                raise RuntimeError(f"Profil karyawan {employee[0]} tidak sesuai hasil pencocokan.")
        actual_review_count = connection.execute(
            "SELECT COUNT(*) FROM employees WHERE profile_needs_review = 1"
        ).fetchone()[0]
        if actual_review_count != expected_review_count:
            raise RuntimeError("Jumlah profil sementara yang perlu ditinjau tidak sesuai.")

        raw_code_counts = dict(connection.execute(
            "SELECT mark, COUNT(*) FROM attendance_recap_records GROUP BY mark"
        ).fetchall())
        expected_code_counts = dict(collections.Counter(row["mark"] or None for row in recap_rows))
        if raw_code_counts != expected_code_counts:
            raise RuntimeError("Distribusi kode Rekap tidak sesuai dengan file sumber.")
        unresolved = connection.execute(
            "SELECT COUNT(*) FROM attendance_recap_records WHERE employee_id IS NULL"
        ).fetchone()[0]
        linked_leaves = sum(
            1 for row in reconcile_recap_rows(master_rows, recap_rows)
            if row["master"] and row["source"]["mark"] in LEAVE_MARKS
        )
        leave_count = connection.execute("SELECT COUNT(*) FROM leave_requests").fetchone()[0]
        if leave_count != linked_leaves:
            raise RuntimeError(f"Jumlah histori cuti/sakit tidak sesuai: {leave_count} vs {linked_leaves}.")
        expected_used = sum(
            1
            for item in reconcile_recap_rows(master_rows, recap_rows)
            if item["master"] and item["source"]["mark"] in ("C", "CS")
        )
        actual_used = connection.execute(
            "SELECT COUNT(*) FROM leave_balance_ledger WHERE entry_type = 'USED'"
        ).fetchone()[0]
        if actual_used != expected_used:
            raise RuntimeError(f"Jumlah pemakaian ledger cuti tidak sesuai: {actual_used} vs {expected_used}.")
        allowed_ledger_types = {"GRANT_ANNIVERSARY", "GRANT_ANNUAL_RESET", "USED"}
        ledger_types = {
            row[0] for row in connection.execute(
                "SELECT DISTINCT entry_type FROM leave_balance_ledger"
            )
        }
        if not ledger_types.issubset(allowed_ledger_types):
            raise RuntimeError(f"Tipe ledger lama tersisa: {sorted(ledger_types - allowed_ledger_types)}.")
        used_for_t = connection.execute(
            "SELECT COUNT(*) FROM leave_balance_ledger l "
            "JOIN leave_requests r ON r.id = l.leave_request_id "
            "WHERE l.entry_type = 'USED' AND r.alasan LIKE '%(T)%'"
        ).fetchone()[0]
        if used_for_t:
            raise RuntimeError("Kode T tidak boleh masuk ke ledger pemakaian cuti.")

        current_hashes = {table: _table_fingerprint(connection, table) for table in PRESERVED_TABLES}
        if current_hashes != preserved_hashes:
            raise RuntimeError("Isi akun/profil/aturan/tanggal merah berubah selama reset.")
        fk_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        if fk_issues:
            raise RuntimeError(f"Verifikasi foreign key gagal: {fk_issues[:5]}")
        return {
            "employees": len(employee_rows),
            "recap_records": raw_count,
            "linked_recap_records": raw_count - unresolved,
            "unresolved_recap_records": unresolved,
            "leave_requests": leave_count,
            "raw_marks": raw_code_counts,
            "preserved_tables": {table: counts[table] for table in PRESERVED_TABLES},
        }
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Backup lalu jalankan reset/import pada backend/hr_app.db lokal.",
    )
    args = parser.parse_args(argv)

    try:
        path = validate_local_target(engine.url.render_as_string(hide_password=False))
        master_rows, recap_rows, master_hash, recap_hash = _read_workbooks()
        preflight = _read_preflight(path, master_rows)
        reconciled = reconcile_recap_rows(master_rows, recap_rows)
        resolution_counts = collections.Counter(
            item["reconciliation_status"] for item in reconciled
        )
        profile_review_count = (
            len(master_rows) - preflight["legacy_match_count"]
            + sum(
                bool(row.get("profile_needs_review"))
                for row in preflight["legacy_matches"].values()
            )
        )
        identity_warnings = collections.Counter(
            part
            for item in reconciled
            if item["identity_warning"]
            for part in item["identity_warning"].split(". ")
        )
        print(f"Database lokal: {path}")
        print(f"Master: {len(master_rows)} karyawan; SHA-256 {master_hash}")
        print(f"Rekap: {len(recap_rows)} baris; SHA-256 {recap_hash}")
        print(f"Rekonsiliasi Rekap: {dict(resolution_counts)}")
        print(f"Catatan identitas Rekap: {dict(identity_warnings)}")
        print(
            "Database saat ini: "
            f"{preflight['legacy_employee_count']} karyawan; "
            f"{preflight['table_counts']['attendance_daily']} ringkasan absensi; "
            f"{preflight['table_counts']['leave_requests']} pengajuan; "
            f"{preflight['table_counts']['leave_balance_ledger']} ledger cuti."
        )
        print(
            f"Profil dicocokkan dari data lama untuk {preflight['legacy_match_count']} karyawan; "
            f"{len(master_rows) - preflight['legacy_match_count']} tidak memiliki pasangan lama; "
            f"{profile_review_count} akan perlu review. Default profil: {preflight['default_profile']}."
        )
        if not args.apply:
            print("Pratinjau saja; database belum diubah. Jalankan ulang dengan --apply untuk reset.")
            return 0

        backup_path = _backup_database(path)
        print(f"Backup terverifikasi: {backup_path}")
        _ensure_schema()
        with SessionLocal() as db:
            summary = rebuild_database(
                db,
                master_rows,
                recap_rows,
                master_hash,
                recap_hash,
                get_today_jakarta(),
                expected_matches=preflight["legacy_matches"],
                expected_preserved_hashes=preflight["preserved_hashes"],
            )
        verified = _verify_result(
            path,
            master_rows,
            recap_rows,
            recap_hash,
            preflight["preserved_hashes"],
            preflight["legacy_matches"],
            preflight["default_profile"],
        )
        print(f"Ringkasan rebuild: {json.dumps(summary, ensure_ascii=False, default=str)}")
        print(f"Verifikasi akhir: {json.dumps(verified, ensure_ascii=False, default=str)}")
        return 0
    except Exception as exc:
        print(f"RESET DIBATALKAN/ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
