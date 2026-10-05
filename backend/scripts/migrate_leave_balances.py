# -*- coding: utf-8 -*-
"""
migrate_leave_balances.py
=========================
Skrip migrasi satu kali untuk membangun ledger saldo cuti dari data historis.

CARA PAKAI:
  # Preview dulu (tidak menulis ke DB):
  cd backend
  python -m scripts.migrate_leave_balances --preview

  # Apply ke DB setelah review:
  python -m scripts.migrate_leave_balances --apply

  # Untuk tahun tertentu:
  python -m scripts.migrate_leave_balances --preview --year 2026

AMAN dijalankan berulang — idempotent.
Data lama (LeaveRequest) TIDAK dihapus atau diubah.

Logika migrasi:
1. Untuk setiap karyawan aktif yang punya join_date:
   - Hitung apakah sudah berhak cuti di tahun target.
   - Jika anniversary sudah lewat → buat GRANT_ANNIVERSARY atau GRANT_ANNUAL_RESET.
2. Untuk setiap LeaveRequest APPROVED yang memotong kuota tahunan:
   - Buat entri USED di ledger (jika belum ada).
3. Tampilkan preview tabel hasil untuk HR review.
"""
import sys
import os
import datetime

# Tambahkan root project ke path agar bisa impor app.*
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.models import Employee, LeaveRequest, LeaveBalanceLedger
from app.leave_logic import (
    get_first_anniversary,
    get_anniversary_date,
    calculate_proportional_quota,
    get_ledger_balance,
    has_singleton_entry,
    write_ledger_entry,
    record_leave_used,
    ENTRY_GRANT_ANNIVERSARY,
    ENTRY_GRANT_ANNUAL_RESET,
    ENTRY_USED,
    KATEGORI_POTONG_CUTI_MAP,
)
from app.config import ANNUAL_LEAVE_QUOTA, get_today_jakarta


def run_migration(year: int, dry_run: bool = True):
    """
    Menjalankan migrasi untuk tahun tertentu.

    Args:
        year: Tahun target migrasi (mis. 2026)
        dry_run: True = hanya preview, False = tulis ke DB
    """
    db = SessionLocal()
    mode = "PREVIEW (--preview)" if dry_run else "APPLY (--apply)"
    print(f"\n{'='*60}")
    print(f"Migrasi Saldo Cuti Tahunan — Tahun {year} [{mode}]")
    print(f"{'='*60}\n")

    today = get_today_jakarta()

    # ── Step 1: Ambil semua karyawan aktif ─────────────────────────────────
    employees = (
        db.query(Employee)
        .filter(Employee.active == True)
        .order_by(Employee.nama)
        .all()
    )
    print(f"Total karyawan aktif: {len(employees)}")

    grant_rows = []
    used_rows = []
    skipped_rows = []

    # ── Step 2: Hitung grant untuk setiap karyawan ─────────────────────────
    for emp in employees:
        if not emp.join_date:
            skipped_rows.append({
                "nama": emp.nama,
                "alasan": "join_date belum diisi",
            })
            continue

        first_ann = get_first_anniversary(emp.join_date)
        ann_this_year = get_anniversary_date(emp.join_date, year)

        is_first_year = (first_ann.year == year)
        reset_date = datetime.date(year, 1, 1)
        has_passed_anniversary = first_ann <= today

        if not has_passed_anniversary and first_ann.year > year:
            # Karyawan bergabung di tahun 'year' atau lebih baru — belum berhak
            skipped_rows.append({
                "nama": emp.nama,
                "alasan": f"Belum anniversary (join {emp.join_date}, ann pertama {first_ann})",
            })
            continue

        if is_first_year:
            # Tahun anniversary pertama — kuota proporsional
            entry_type = ENTRY_GRANT_ANNIVERSARY
            quota = calculate_proportional_quota(emp.join_date, year)
            note = f"Kuota proporsional anniversary {ann_this_year.strftime('%d %B %Y')} ({quota} hari)"
        else:
            # Tahun kedua dan seterusnya — kuota penuh
            entry_type = ENTRY_GRANT_ANNUAL_RESET
            quota = ANNUAL_LEAVE_QUOTA
            note = f"Kuota penuh reset {year} — {quota} hari"

        # Cek sudah ada di ledger?
        already_exists = has_singleton_entry(db, emp.id, year, entry_type)

        grant_rows.append({
            "nama": emp.nama,
            "join_date": str(emp.join_date),
            "anniversary": str(ann_this_year),
            "entry_type": entry_type,
            "quota": quota,
            "note": note,
            "already_in_ledger": already_exists,
        })

    # ── Step 3: Ambil semua APPROVED LeaveRequest yang memotong kuota ───────
    approved_leaves = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.status == "APPROVED",
            LeaveRequest.kategori.in_(list(KATEGORI_POTONG_CUTI_MAP.keys())),
            LeaveRequest.tanggal_mulai >= datetime.date(year, 1, 1),
            LeaveRequest.tanggal_mulai <= datetime.date(year, 12, 31),
        )
        .order_by(LeaveRequest.nama, LeaveRequest.tanggal_mulai)
        .all()
    )

    for lv in approved_leaves:
        days = lv.jumlah_hari if lv.jumlah_hari is not None else KATEGORI_POTONG_CUTI_MAP.get(lv.kategori, 1.0)
        # Cek sudah ada USED untuk leave_request_id ini?
        existing_used = (
            db.query(LeaveBalanceLedger)
            .filter(
                LeaveBalanceLedger.leave_request_id == lv.id,
                LeaveBalanceLedger.entry_type == ENTRY_USED,
            )
            .first()
        )
        # Cari employee
        emp_match = next((e for e in employees if e.nama.strip().lower() == lv.nama.strip().lower()), None)
        used_rows.append({
            "nama": lv.nama,
            "tanggal": str(lv.tanggal_mulai),
            "kategori": lv.kategori,
            "days": days,
            "leave_id": lv.id,
            "employee_id": emp_match.id if emp_match else None,
            "already_in_ledger": existing_used is not None,
        })

    # ── Step 4: Tampilkan preview ───────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("PREVIEW GRANT (quota diberikan):")
    print(f"{'─'*60}")
    for row in grant_rows:
        status = "[SUDAH ADA]" if row["already_in_ledger"] else "[AKAN DITULIS]"
        print(
            f"  {status:15s} {row['nama'][:30]:30s} | {row['entry_type']:22s} "
            f"| +{row['quota']:5.1f} hari | ann {row['anniversary']}"
        )

    print(f"\n{'─'*60}")
    print("PREVIEW USED (pemakaian yang sudah approved):")
    print(f"{'─'*60}")
    for row in used_rows:
        status = "[SUDAH ADA]" if row["already_in_ledger"] else "[AKAN DITULIS]"
        emp_status = f"emp_id={row['employee_id']}" if row["employee_id"] else "KARYAWAN TIDAK DITEMUKAN"
        print(
            f"  {status:15s} {row['nama'][:25]:25s} | {row['tanggal']} | {row['kategori']:20s} "
            f"| -{row['days']:4.1f} hari | lv#{row['leave_id']} | {emp_status}"
        )

    if skipped_rows:
        print(f"\n{'─'*60}")
        print("DILEWATI (tidak diproses):")
        print(f"{'─'*60}")
        for row in skipped_rows:
            print(f"  SKIP  {row['nama'][:35]:35s} — {row['alasan']}")

    new_grants = sum(1 for r in grant_rows if not r["already_in_ledger"])
    new_used = sum(1 for r in used_rows if not r["already_in_ledger"])
    print(f"\n{'='*60}")
    print(f"RINGKASAN:")
    print(f"  Grants baru akan ditulis : {new_grants}")
    print(f"  USED baru akan ditulis   : {new_used}")
    print(f"  Dilewati                 : {len(skipped_rows)}")
    print(f"  Total Leave APPROVED     : {len(used_rows)}")
    print(f"{'='*60}")

    # ── Step 5: Apply ke DB (jika bukan dry_run) ────────────────────────────
    if dry_run:
        print("\n[PREVIEW MODE] Tidak ada yang ditulis ke database.")
        print("Jalankan dengan --apply untuk menerapkan perubahan.\n")
        db.close()
        return

    print("\nMenulis ke database...")
    written_grants = 0
    written_used = 0
    errors = []

    for row in grant_rows:
        if row["already_in_ledger"]:
            continue
        try:
            emp_match = next((e for e in employees if e.nama.strip() == row["nama"].strip()), None)
            if not emp_match:
                errors.append(f"Employee tidak ditemukan untuk grant: {row['nama']}")
                continue
            write_ledger_entry(
                db=db,
                employee_id=emp_match.id,
                year=year,
                entry_type=row["entry_type"],
                amount=float(row["quota"]),
                note=row["note"],
                commit=True,
            )
            written_grants += 1
        except Exception as e:
            errors.append(f"Grant error [{row['nama']}]: {e}")

    for row in used_rows:
        if row["already_in_ledger"] or not row["employee_id"]:
            continue
        try:
            write_ledger_entry(
                db=db,
                employee_id=row["employee_id"],
                year=year,
                entry_type=ENTRY_USED,
                amount=-row["days"],
                note=f"Migrasi: {row['kategori']} {row['tanggal']} (lv#{row['leave_id']})",
                leave_request_id=row["leave_id"],
                commit=True,
            )
            written_used += 1
        except Exception as e:
            errors.append(f"USED error [lv#{row['leave_id']} {row['nama']}]: {e}")

    print(f"\nSelesai!")
    print(f"  Grants ditulis : {written_grants}")
    print(f"  USED ditulis   : {written_used}")
    if errors:
        print(f"  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")
    else:
        print("  Tidak ada error.")

    db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrasi saldo cuti tahunan ke ledger")
    parser.add_argument("--year", type=int, default=get_today_jakarta().year, help="Tahun target migrasi")
    parser.add_argument("--preview", action="store_true", help="Mode preview (tidak menulis ke DB)")
    parser.add_argument("--apply", action="store_true", help="Apply ke DB")
    args = parser.parse_args()

    if not args.preview and not args.apply:
        print("Gunakan --preview atau --apply. Contoh:")
        print("  python -m scripts.migrate_leave_balances --preview")
        print("  python -m scripts.migrate_leave_balances --apply --year 2026")
        sys.exit(1)

    dry_run = not args.apply
    run_migration(year=args.year, dry_run=dry_run)
