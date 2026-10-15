"""Preview or backfill canonical new employee IDs in the local SQLite database."""

import argparse
import csv
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_DATABASE = BACKEND_DIR / "hr_app.db"
DEFAULT_BACKUP = BACKEND_DIR / "backups" / "hr_app-pre-new-employee-id.db"
DEFAULT_ROSTER = REPO_ROOT / "employees_202610131457_new_employee_id.csv"
BRANCH_PREFIXES = {
    "Gudang A": "01",
    "Gudang C": "02",
    "Cab. Bandung": "03",
    "GLC": "04",
    "Tj. Duren": "05",
    "Setup": "06",
    "IDD PIK": "07",
    "Reef Plus": "08",
    "Kebayoran Lama": "09",
}


class BackfillError(Exception):
    pass


def read_roster(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            required = {"id", "employee_code", "new_employee_id", "nik", "cabang"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                missing = sorted(required - set(reader.fieldnames or []))
                raise BackfillError(f"CSV kehilangan kolom wajib: {', '.join(missing)}.")
            rows = []
            seen_ids: set[str] = set()
            seen_new_ids: set[str] = set()
            for row_number, row in enumerate(reader, start=2):
                source_id = (row.get("id") or "").strip()
                old_id = (row.get("employee_code") or "").strip()
                new_id = (row.get("new_employee_id") or "").strip().upper()
                branch = " ".join((row.get("cabang") or "").split())
                if not source_id.isdigit() or not old_id or not new_id:
                    raise BackfillError(f"Baris {row_number} memiliki ID sumber/kode kosong atau tidak valid.")
                if branch not in BRANCH_PREFIXES:
                    raise BackfillError(f"Baris {row_number} memiliki cabang di luar daftar kanonis.")
                if not re.fullmatch(rf"JIP-{BRANCH_PREFIXES[branch]}\d{{4}}", new_id):
                    raise BackfillError(f"Baris {row_number} memiliki new_employee_id dengan prefix yang salah.")
                if source_id in seen_ids:
                    raise BackfillError(f"ID sumber duplikat pada baris {row_number}.")
                if new_id.casefold() in seen_new_ids:
                    raise BackfillError(f"new_employee_id duplikat pada baris {row_number}.")
                seen_ids.add(source_id)
                seen_new_ids.add(new_id.casefold())
                rows.append({
                    "source_row": str(row_number),
                    "source_id": source_id,
                    "old_id": old_id,
                    "new_id": new_id,
                    "nik": re.sub(r"\D", "", row.get("nik") or ""),
                    "branch": branch,
                })
    except (OSError, csv.Error, UnicodeDecodeError) as exc:
        raise BackfillError(f"Gagal membaca roster CSV: {exc}") from exc
    if not rows:
        raise BackfillError("Roster CSV tidak berisi karyawan.")
    return rows


def table_names(db: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}


def build_plan(db: sqlite3.Connection, roster: list[dict[str, str]]) -> dict:
    tables = table_names(db)
    if "employees" not in tables:
        raise BackfillError("Database lokal tidak memiliki tabel employees.")
    employee_cols = columns(db, "employees")
    required_employee_cols = {"id", "employee_code", "nik", "cabang"}
    if not required_employee_cols.issubset(employee_cols):
        raise BackfillError("Skema employees tidak sesuai; diperlukan id, employee_code, nik, cabang.")

    employees = {
        str(row["id"]): dict(row)
        for row in db.execute("SELECT id, employee_code, nik, cabang FROM employees")
    }
    issues = []
    matches = []
    matched_ids: set[str] = set()
    new_id_owners: dict[str, str] = {}
    for row in roster:
        employee = employees.get(row["source_id"])
        if employee is None:
            issues.append(f"CSV row {row['source_row']}: employee database ID tidak ditemukan.")
            continue
        db_nik = re.sub(r"\D", "", employee.get("nik") or "")
        if row["nik"] and db_nik and row["nik"] != db_nik:
            issues.append(f"CSV row {row['source_row']}: NIK tidak cocok dengan employee database ID.")
            continue
        if row["source_id"] in matched_ids:
            issues.append(f"CSV row {row['source_row']}: employee database dipetakan lebih dari sekali.")
            continue
        current_new_id = (
            db.execute(
                "SELECT new_employee_id FROM employees WHERE id = ?",
                (int(row["source_id"]),),
            ).fetchone()[0]
            if "new_employee_id" in employee_cols
            else None
        )
        if current_new_id and current_new_id.strip().casefold() != row["new_id"].casefold():
            issues.append(f"CSV row {row['source_row']}: new_employee_id database telah terisi nilai berbeda.")
            continue
        owner = new_id_owners.get(row["new_id"].casefold())
        if owner and owner != row["source_id"]:
            issues.append(f"CSV row {row['source_row']}: new_employee_id sudah dipetakan ke employee lain.")
            continue
        new_id_owners[row["new_id"].casefold()] = row["source_id"]
        matched_ids.add(row["source_id"])
        matches.append({**row, "employee": employee})

    outside_roster = sorted(set(employees) - matched_ids)
    if outside_roster:
        issues.append(f"{len(outside_roster)} employee database tidak ada di roster; apply ditolak.")
    if len(employees) != len(roster):
        issues.append(
            f"Jumlah database ({len(employees)}) berbeda dari jumlah roster ({len(roster)}); apply ditolak."
        )
    if "employee_import_candidates" in tables:
        candidate_count = db.execute("SELECT COUNT(*) FROM employee_import_candidates").fetchone()[0]
        if candidate_count:
            issues.append(
                f"Ada {candidate_count} kandidat impor; petakan/review kandidat sebelum backfill lokal."
            )

    serial_max: dict[str, int] = defaultdict(int)
    branch_counts: Counter[str] = Counter()
    for row in roster:
        prefix = BRANCH_PREFIXES[row["branch"]]
        serial_max[prefix] = max(serial_max[prefix], int(row["new_id"][-4:]))
        branch_counts[row["branch"]] += 1

    return {
        "matches": matches,
        "issues": issues,
        "outside_roster_count": len(outside_roster),
        "branch_counts": branch_counts,
        "sequence_next": {prefix: serial + 1 for prefix, serial in serial_max.items()},
        "tables": tables,
        "employee_cols": employee_cols,
    }


def validate_backup(path: Path) -> None:
    if not path.is_file() or path.resolve() == DEFAULT_DATABASE.resolve():
        raise BackfillError("Backup database lokal tidak ditemukan atau menunjuk ke database aktif.")
    try:
        backup = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        try:
            result = backup.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                raise BackfillError("Backup database gagal melewati PRAGMA quick_check.")
        finally:
            backup.close()
    except sqlite3.Error as exc:
        raise BackfillError("Backup database tidak dapat dibuka sebagai SQLite.") from exc


def add_column_if_missing(db: sqlite3.Connection, table: str, name: str) -> None:
    if name not in columns(db, table):
        db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" VARCHAR')


def apply_plan(db: sqlite3.Connection, plan: dict) -> None:
    tables = plan["tables"]
    add_column_if_missing(db, "employees", "new_employee_id")
    add_column_if_missing(db, "employee_import_candidates", "new_employee_id")
    if "payroll_whatsapp_deliveries" in tables:
        add_column_if_missing(db, "payroll_whatsapp_deliveries", "new_employee_id")
    if "attendance_recap_records" in tables:
        add_column_if_missing(db, "attendance_recap_records", "new_employee_id")

    sequence_tables = table_names(db)
    if "employee_code_sequences" in sequence_tables and "employee_id_sequences" not in sequence_tables:
        db.execute('ALTER TABLE "employee_code_sequences" RENAME TO "employee_id_sequences"')
    db.execute(
        "CREATE TABLE IF NOT EXISTS employee_id_sequences "
        "(branch_code VARCHAR(2) PRIMARY KEY NOT NULL, next_serial INTEGER NOT NULL)"
    )

    for match in plan["matches"]:
        db.execute(
            "UPDATE employees SET new_employee_id = ?, cabang = ? WHERE id = ?",
            (match["new_id"], match["branch"], int(match["source_id"])),
        )

    if "employee_import_candidates" in tables and "approved_employee_id" in columns(db, "employee_import_candidates"):
        for match in plan["matches"]:
            db.execute(
                "UPDATE employee_import_candidates SET new_employee_id = ? "
                "WHERE approved_employee_id = ?",
                (match["new_id"], int(match["source_id"])),
            )
    for table in ("payroll_whatsapp_deliveries", "attendance_recap_records"):
        if table in tables and {"employee_id", "new_employee_id"}.issubset(columns(db, table)):
            db.execute(
                f'UPDATE "{table}" SET new_employee_id = ('
                "SELECT employees.new_employee_id FROM employees "
                f'WHERE employees.id = "{table}".employee_id) '
                "WHERE employee_id IS NOT NULL"
            )

    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_employees_new_employee_id "
        "ON employees(new_employee_id)"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_employee_import_candidates_new_employee_id "
        "ON employee_import_candidates(new_employee_id)"
    )
    for table in ("payroll_whatsapp_deliveries", "attendance_recap_records"):
        if table in tables:
            db.execute(
                f'CREATE INDEX IF NOT EXISTS ix_{table}_new_employee_id '
                f'ON "{table}"(new_employee_id)'
            )

    for prefix, next_serial in plan["sequence_next"].items():
        db.execute(
            "INSERT INTO employee_id_sequences (branch_code, next_serial) VALUES (?, ?) "
            "ON CONFLICT(branch_code) DO UPDATE SET "
            "next_serial = MAX(employee_id_sequences.next_serial, excluded.next_serial)",
            (prefix, next_serial),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--csv", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--apply", action="store_true", help="Write only to the fixed local SQLite database.")
    parser.add_argument("--confirm-local", action="store_true", help="Confirm this is the local development database.")
    parser.add_argument("--backup-file", type=Path, default=DEFAULT_BACKUP)
    args = parser.parse_args()

    try:
        database_path = args.database.resolve()
        if database_path != DEFAULT_DATABASE.resolve():
            raise BackfillError("Script hanya menerima backend/hr_app.db; target lain ditolak.")
        roster = read_roster(args.csv)
        if args.apply:
            if not args.confirm_local:
                raise BackfillError("--confirm-local wajib untuk menerapkan perubahan lokal.")
            validate_backup(args.backup_file)
            if not database_path.is_file():
                raise BackfillError("Database lokal tidak ditemukan.")
            db = sqlite3.connect(database_path)
        else:
            if not database_path.is_file():
                raise BackfillError("Database lokal tidak ditemukan.")
            db = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)

        try:
            db.row_factory = sqlite3.Row
            plan = build_plan(db, roster)
            print(f"Target lokal: {database_path}")
            print(f"Roster: {len(roster)}; database employees: {len(plan['matches']) + plan['outside_roster_count']}")
            print(f"Employee dicocokkan berdasarkan ID database: {len(plan['matches'])}/{len(roster)}")
            print(f"Karyawan di luar roster: {plan['outside_roster_count']}")
            print("Jumlah per cabang:")
            for branch in BRANCH_PREFIXES:
                print(f"  {branch}: {plan['branch_counts'].get(branch, 0)}")
            print("ID baru dan cabang cocok: " + ("ya" if not plan["issues"] else "belum"))
            for issue in plan["issues"]:
                print(f"CONFLICT: {issue}")
            if plan["issues"]:
                return 1
            if not args.apply:
                print("PREVIEW SAJA: database lokal tidak diubah.")
                return 0

            try:
                db.execute("BEGIN IMMEDIATE")
                apply_plan(db, plan)
                db.commit()
            except Exception:
                db.rollback()
                raise
            print(f"Backfill lokal berhasil untuk {len(plan['matches'])} karyawan.")
            return 0
        finally:
            db.close()
    except (BackfillError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
