# -*- coding: utf-8 -*-
"""
leave_logic.py — Engine kalkulasi kuota cuti tahunan berbasis anniversary.

Semua logika bisnis leave-quota dikumpulkan di sini agar mudah diuji dan diganti.
Modul ini TIDAK boleh mengimpor router; hanya boleh mengimpor models, config, database.
"""
from __future__ import annotations

import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import Employee, LeaveBalanceLedger, LeaveRequest
from .config import (
    ANNUAL_LEAVE_QUOTA,
    LEAVE_RESET_MONTH,
    LEAVE_RESET_DAY,
    LEAVE_MIN_TENURE_YEARS,
    get_today_jakarta,
)

# ─────────────────────────────────────────────────────────────────────────────
# Tipe entri ledger
# ─────────────────────────────────────────────────────────────────────────────
ENTRY_GRANT_ANNIVERSARY = "GRANT_ANNIVERSARY"
ENTRY_GRANT_ANNUAL_RESET = "GRANT_ANNUAL_RESET"
ENTRY_USED = "USED"
ENTRY_REVERSED = "REVERSED"
ENTRY_EXPIRED = "EXPIRED"

# Tipe yang hanya boleh ada 1 per (employee_id, year) — idempotency dijaga di app layer
SINGLETON_ENTRY_TYPES = {ENTRY_GRANT_ANNIVERSARY, ENTRY_GRANT_ANNUAL_RESET, ENTRY_EXPIRED}

# Kategori cuti yang memotong kuota tahunan beserta bobotnya (dalam hari)
KATEGORI_POTONG_CUTI_MAP: dict[str, float] = {
    "CUTI_TAHUNAN": 1.0,
    "CUTI_SETENGAH_HARI": 0.5,
}


# ─────────────────────────────────────────────────────────────────────────────
# Fungsi perhitungan anniversary
# ─────────────────────────────────────────────────────────────────────────────

def get_anniversary_date(join_date: datetime.date, target_year: int) -> datetime.date:
    """
    Menghitung tanggal anniversary (ulang tahun kerja) di target_year.

    Asumsi A1: Jika join 29 Februari, anniversary di tahun non-kabisat jatuh 28 Februari.
    """
    try:
        return join_date.replace(year=target_year)
    except ValueError:
        # join_date adalah 29 Februari, target_year bukan kabisat → fallback ke 28 Feb
        return datetime.date(target_year, 2, 28)


def get_first_anniversary(join_date: datetime.date) -> datetime.date:
    """
    Menghitung tanggal anniversary pertama (tepat 1 tahun sejak join_date).
    """
    return get_anniversary_date(join_date, join_date.year + 1)


def has_reached_anniversary(join_date: datetime.date, ref_date: Optional[datetime.date] = None) -> bool:
    """
    Apakah karyawan sudah melewati anniversary pertama pada ref_date?
    """
    if ref_date is None:
        ref_date = get_today_jakarta()
    return ref_date >= get_first_anniversary(join_date)


def calculate_proportional_quota(join_date: datetime.date, anniversary_year: int) -> int:
    """
    Menghitung kuota proporsional untuk tahun anniversary pertama.

    Rumus: kuota = 13 - bulan_anniversary (minimal 1, maksimal ANNUAL_LEAVE_QUOTA).
    Contoh:
      - Anniversary Oktober (bulan 10) → 13 - 10 = 3 hari (Okt, Nov, Des)
      - Anniversary Januari (bulan 1)  → 13 - 1  = 12 hari
      - Anniversary Juli (bulan 7)     → 13 - 7  = 6 hari
      - Anniversary Desember (bulan 12)→ 13 - 12 = 1 hari

    Asumsi A5: Berdasarkan bulan anniversary, bukan tanggal.
    Fungsi ini sengaja dipisah agar mudah diganti jika HR mengkonfirmasi aturan berbeda.
    """
    ann_date = get_anniversary_date(join_date, anniversary_year)
    quota = 13 - ann_date.month
    return max(1, min(quota, ANNUAL_LEAVE_QUOTA))


# ─────────────────────────────────────────────────────────────────────────────
# Perhitungan saldo dari ledger
# ─────────────────────────────────────────────────────────────────────────────

def get_ledger_balance(db: Session, employee_id: int, year: int) -> float:
    """
    Menghitung saldo cuti dari ledger untuk karyawan + tahun tertentu.
    Saldo = SUM(amount) dari semua entri ledger.
    """
    result = (
        db.query(func.sum(LeaveBalanceLedger.amount))
        .filter(
            LeaveBalanceLedger.employee_id == employee_id,
            LeaveBalanceLedger.year == year,
        )
        .scalar()
    )
    return float(result or 0.0)


def get_ledger_entries(db: Session, employee_id: int, year: int) -> list[LeaveBalanceLedger]:
    """Semua entri ledger untuk karyawan + tahun, diurutkan dari terbaru."""
    return (
        db.query(LeaveBalanceLedger)
        .filter(
            LeaveBalanceLedger.employee_id == employee_id,
            LeaveBalanceLedger.year == year,
        )
        .order_by(LeaveBalanceLedger.created_at.asc())
        .all()
    )


def get_ledger_granted(db: Session, employee_id: int, year: int) -> float:
    """Total kuota yang pernah diberikan (semua GRANT) pada tahun tertentu."""
    result = (
        db.query(func.sum(LeaveBalanceLedger.amount))
        .filter(
            LeaveBalanceLedger.employee_id == employee_id,
            LeaveBalanceLedger.year == year,
            LeaveBalanceLedger.entry_type.in_([ENTRY_GRANT_ANNIVERSARY, ENTRY_GRANT_ANNUAL_RESET]),
        )
        .scalar()
    )
    return float(result or 0.0)


def has_singleton_entry(db: Session, employee_id: int, year: int, entry_type: str) -> bool:
    """Cek apakah entri singleton (GRANT/EXPIRED) sudah ada untuk menghindari duplikasi."""
    return (
        db.query(LeaveBalanceLedger)
        .filter(
            LeaveBalanceLedger.employee_id == employee_id,
            LeaveBalanceLedger.year == year,
            LeaveBalanceLedger.entry_type == entry_type,
        )
        .first()
        is not None
    )


# ─────────────────────────────────────────────────────────────────────────────
# Operasi ledger
# ─────────────────────────────────────────────────────────────────────────────

def write_ledger_entry(
    db: Session,
    employee_id: int,
    year: int,
    entry_type: str,
    amount: float,
    note: str = "",
    leave_request_id: Optional[int] = None,
    commit: bool = True,
) -> Optional[LeaveBalanceLedger]:
    """
    Menulis satu entri ke ledger.
    Untuk tipe SINGLETON, cek duplikasi terlebih dahulu — kembalikan None jika sudah ada.
    """
    if entry_type in SINGLETON_ENTRY_TYPES and has_singleton_entry(db, employee_id, year, entry_type):
        return None  # Idempotent — sudah ada, skip

    entry = LeaveBalanceLedger(
        employee_id=employee_id,
        year=year,
        entry_type=entry_type,
        amount=amount,
        note=note,
        leave_request_id=leave_request_id,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    return entry


def grant_anniversary_quota(db: Session, employee: Employee, year: int, commit: bool = True) -> Optional[LeaveBalanceLedger]:
    """
    Memberikan kuota proporsional untuk tahun anniversary.
    Idempotent — jika sudah ada GRANT_ANNIVERSARY untuk tahun ini, tidak menulis lagi.
    """
    if not employee.join_date:
        return None
    quota = calculate_proportional_quota(employee.join_date, year)
    ann_date = get_anniversary_date(employee.join_date, year)
    return write_ledger_entry(
        db=db,
        employee_id=employee.id,
        year=year,
        entry_type=ENTRY_GRANT_ANNIVERSARY,
        amount=float(quota),
        note=f"Kuota proporsional anniversary {ann_date.strftime('%d %B %Y')} ({quota} hari: bulan {ann_date.month}–12)",
        commit=commit,
    )


def grant_annual_reset_quota(db: Session, employee: Employee, year: int, commit: bool = True) -> Optional[LeaveBalanceLedger]:
    """
    Memberikan kuota penuh ANNUAL_LEAVE_QUOTA untuk reset tahunan (1 Januari).

    Syarat: anniversary pertama karyawan harus jatuh di tahun SEBELUM year
    (first_ann.year < year). Artinya:
    - Join April 2025 → anniversary April 2026 → Reset Tahunan baru diberikan 1 Jan 2027
    - Join Jan 2025  → anniversary Jan 2026  → Reset Tahunan diberikan 1 Jan 2027

    Karyawan yang anniversarynya di tahun yang sama dengan year (misal anniversary 2026
    dan year=2026) hanya mendapat kuota proporsional via grant_anniversary_quota, BUKAN reset ini.

    Idempotent — jika sudah ada GRANT_ANNUAL_RESET untuk tahun ini, tidak menulis lagi.
    """
    if not employee.join_date:
        return None
    first_ann = get_first_anniversary(employee.join_date)
    # Anniversary pertama HARUS sudah lewat di tahun sebelumnya (bukan tahun yang sama)
    # Agar karyawan benar-benar sudah menyelesaikan satu siklus penuh sebelum mendapat reset
    if first_ann.year >= year:
        return None  # Belum berhak: anniversary pertama belum atau baru di tahun ini
    return write_ledger_entry(
        db=db,
        employee_id=employee.id,
        year=year,
        entry_type=ENTRY_GRANT_ANNUAL_RESET,
        amount=float(ANNUAL_LEAVE_QUOTA),
        note=f"Reset kuota tahunan {year} (sesuai Rekap {year})",
        commit=commit,
    )


def expire_previous_year_balance(db: Session, employee: Employee, prev_year: int, commit: bool = True) -> Optional[LeaveBalanceLedger]:
    """
    Menghanguskan sisa saldo tahun sebelumnya pada saat reset 1 Januari.
    Idempotent — jika EXPIRED untuk prev_year sudah ada, tidak menulis lagi.
    """
    remaining = get_ledger_balance(db, employee.id, prev_year)
    if remaining <= 0:
        # Tidak ada sisa yang perlu dihanguskan
        return None
    return write_ledger_entry(
        db=db,
        employee_id=employee.id,
        year=prev_year,
        entry_type=ENTRY_EXPIRED,
        amount=-remaining,
        note=f"Saldo hangus per 1 Januari {prev_year + 1} ({remaining:.1f} hari)",
        commit=commit,
    )


def record_leave_used(
    db: Session,
    employee_id: int,
    year: int,
    days: float,
    leave_request_id: int,
    leave_desc: str = "",
    commit: bool = True,
) -> LeaveBalanceLedger:
    """Mencatat pemakaian cuti (USED) saat pengajuan disetujui."""
    return write_ledger_entry(
        db=db,
        employee_id=employee_id,
        year=year,
        entry_type=ENTRY_USED,
        amount=-days,
        note=f"Cuti disetujui: {leave_desc}",
        leave_request_id=leave_request_id,
        commit=commit,
    )


def get_leave_request_days(leave_request: LeaveRequest) -> float:
    """Menghitung bobot hari cuti dari nilai tersimpan atau rentang tanggal."""
    if leave_request.jumlah_hari is not None:
        return float(leave_request.jumlah_hari)
    weight = KATEGORI_POTONG_CUTI_MAP.get(leave_request.kategori, 1.0)
    date_range = (leave_request.tanggal_selesai - leave_request.tanggal_mulai).days + 1
    return float(date_range * weight)


def reconcile_approved_leave_ledger(db: Session) -> int:
    """
    Backfill pemakaian untuk pengajuan approved yang dibuat sebelum ledger aktif.
    Idempoten berdasarkan leave_request_id agar aman dijalankan setiap startup.
    """
    approved_leaves = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.status == "APPROVED",
            LeaveRequest.kategori.in_(KATEGORI_POTONG_CUTI_MAP),
        )
        .all()
    )
    created = 0
    for leave in approved_leaves:
        employee = (
            db.query(Employee)
            .filter(Employee.nama.ilike(leave.nama.strip()), Employee.active == True)
            .first()
        )
        if not employee:
            continue
        existing = (
            db.query(LeaveBalanceLedger)
            .filter(
                LeaveBalanceLedger.leave_request_id == leave.id,
                LeaveBalanceLedger.entry_type == ENTRY_USED,
            )
            .first()
        )
        if existing:
            continue
        record_leave_used(
            db,
            employee.id,
            leave.tanggal_mulai.year,
            get_leave_request_days(leave),
            leave.id,
            f"{leave.kategori} {leave.tanggal_mulai} s/d {leave.tanggal_selesai} (rekonsiliasi)",
            commit=False,
        )
        created += 1
    if created:
        db.commit()
    return created


def reverse_leave_used(
    db: Session,
    employee_id: int,
    year: int,
    leave_request_id: int,
    leave_desc: str = "",
    commit: bool = True,
) -> Optional[LeaveBalanceLedger]:
    """
    Membalikkan USED entry saat cuti dibatalkan/ditolak.
    Cari entri USED yang terkait leave_request_id, lalu buat REVERSED senilai kebalikannya.
    Idempotent — jika REVERSED untuk leave_request_id ini sudah ada, skip.
    """
    # Cek apakah REVERSED sudah ada
    existing_reversed = (
        db.query(LeaveBalanceLedger)
        .filter(
            LeaveBalanceLedger.leave_request_id == leave_request_id,
            LeaveBalanceLedger.entry_type == ENTRY_REVERSED,
        )
        .first()
    )
    if existing_reversed:
        return None

    # Cari entri USED
    used_entry = (
        db.query(LeaveBalanceLedger)
        .filter(
            LeaveBalanceLedger.leave_request_id == leave_request_id,
            LeaveBalanceLedger.entry_type == ENTRY_USED,
        )
        .first()
    )
    if not used_entry:
        return None

    return write_ledger_entry(
        db=db,
        employee_id=employee_id,
        year=year,
        entry_type=ENTRY_REVERSED,
        amount=-used_entry.amount,  # Kebalikan dari USED (positif)
        note=f"Cuti dibatalkan/ditolak: {leave_desc}",
        leave_request_id=leave_request_id,
        commit=commit,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Info saldo komprehensif untuk endpoint API
# ─────────────────────────────────────────────────────────────────────────────

def get_leave_balance_info(
    db: Session,
    employee: Employee,
    year: Optional[int] = None,
) -> dict:
    """
    Mengembalikan info saldo cuti lengkap untuk satu karyawan.
    Ini adalah fungsi utama yang dipanggil oleh endpoint API dan validasi pengajuan.
    """
    if year is None:
        year = get_today_jakarta().year

    today = get_today_jakarta()
    effective_join = employee.join_date
    if not effective_join and getattr(employee, "contracts", None):
        contract_starts = [c.start_date for c in employee.contracts if getattr(c, "start_date", None)]
        if contract_starts:
            effective_join = min(contract_starts)

    if not effective_join:
        return {
            "employee_id": employee.id,
            "nama": employee.nama,
            "join_date": None,
            "year": year,
            "has_quota": False,
            "is_eligible": False,
            "quota_granted": 0.0,
            "quota_used": 0.0,
            "quota_remaining": 0.0,
            "anniversary_date": None,
            "next_anniversary": None,
            "is_first_year": False,
            "eligible_from": None,
            "expired_date": None,
            "error": "join_date belum diisi. Hubungi HR Master.",
        }

    first_ann = get_first_anniversary(effective_join)
    has_reached = has_reached_anniversary(effective_join, today)

    # Anniversary untuk tahun 'year'
    ann_this_year = get_anniversary_date(effective_join, year)

    # Saldo dari ledger
    balance = get_ledger_balance(db, employee.id, year)
    granted = get_ledger_granted(db, employee.id, year)

    # Apakah ini tahun anniversary pertama?
    is_first_year = (first_ann.year == year)

    # Tanggal mulai bisa cuti (anniversary pertama)
    eligible_from = first_ann

    # Tanggal hangus saldo (31 Des tahun ini)
    expired_date = datetime.date(year, 12, 31)

    # Anniversary berikutnya (untuk ditampilkan di UI)
    next_ann = get_anniversary_date(effective_join, today.year + 1) if has_reached else first_ann

    # Status eligibilitas: apakah masa kerja >= 1 tahun per hari ini
    is_eligible = (today >= first_ann)
    has_quota = (granted > 0) or (is_eligible and year >= first_ann.year)

    return {
        "employee_id": employee.id,
        "nama": employee.nama,
        "join_date": effective_join.isoformat(),
        "year": year,
        "has_quota": has_quota,
        "is_eligible": is_eligible,
        "quota_granted": round(granted, 2),
        "quota_used": round(granted - balance, 2),
        "quota_remaining": round(balance, 2),
        "is_exceeded": balance < 0,
        "anniversary_date": ann_this_year.isoformat(),
        "next_anniversary": next_ann.isoformat(),
        "is_first_year": is_first_year,
        "eligible_from": eligible_from.isoformat(),
        "expired_date": expired_date.isoformat(),
        "error": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Validasi pengajuan cuti
# ─────────────────────────────────────────────────────────────────────────────

def validate_annual_leave_request(
    db: Session,
    employee: Employee,
    tanggal_mulai: datetime.date,
    requested_days: float,
) -> Tuple[bool, str]:
    """
    Memvalidasi apakah pengajuan cuti tahunan bisa diterima.
    Return: (ok: bool, error_message: str)

    Asumsi A2: Pemotongan kuota berdasarkan tahun tanggal_mulai.
    """
    join_date = employee.join_date
    if not join_date and getattr(employee, "contracts", None):
        contract_starts = [c.start_date for c in employee.contracts if getattr(c, "start_date", None)]
        if contract_starts:
            join_date = min(contract_starts)

    if not join_date:
        return False, (
            f"Karyawan '{employee.nama}' belum memiliki join_date. "
            "Harap lengkapi data karyawan terlebih dahulu."
        )

    first_ann = get_first_anniversary(join_date)

    # Cek apakah sudah melewati anniversary pertama
    if tanggal_mulai < first_ann:
        return False, (
            f"Cuti tahunan baru bisa diajukan mulai "
            f"{first_ann.strftime('%d %B %Y')} "
            f"(anniversary 1 tahun sejak bergabung {join_date.strftime('%d %B %Y')})."
        )

    year = tanggal_mulai.year
    balance = get_ledger_balance(db, employee.id, year)

    if balance <= 0:
        return False, (
            f"Saldo cuti tahunan {employee.nama} untuk tahun {year} sudah habis "
            f"(sisa: {balance:.1f} hari)."
        )

    if requested_days > balance:
        return False, (
            f"Jumlah hari yang diminta ({requested_days:.1f} hari) melebihi "
            f"sisa saldo cuti tahunan ({balance:.1f} hari) untuk tahun {year}."
        )

    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler Jobs — dijalankan harian oleh scheduler.py & endpoint admin
# ─────────────────────────────────────────────────────────────────────────────

def run_leave_quota_jobs(db: Session, target_date: Optional[datetime.date] = None) -> dict:
    """
    Menjalankan semua leave quota jobs untuk target_date.
    Idempotent — aman dijalankan berkali-kali pada hari yang sama.

    Jobs:
    1. Karyawan yang anniversary pertamanya di tahun berjalan 'year' (first_ann.year == year):
       Berikan kuota proporsional anniversary saat target_date >= first_ann.
       TIDAK mendapat Reset Tahunan di tahun yang sama.
       Contoh: join April 2025 → anniversary April 2026 → dapat 9 hari (bukan 12).

    2. Karyawan yang anniversary pertamanya di tahun SEBELUM year (first_ann.year < year):
       Berikan kuota tahunan penuh 12 hari setiap 1 Januari.
       Hanguskan saldo tahun lalu jika tepat 1 Jan.
       Contoh: join April 2025 → anniversary April 2026 → Reset 12 hari baru 1 Jan 2027.
    """
    if target_date is None:
        target_date = get_today_jakarta()

    year = target_date.year
    result = {
        "target_date": target_date.isoformat(),
        "jobs_run": ["anniversary_check", "annual_quota_check"],
        "anniversary_grants": [],
        "reset_expired": [],
        "reset_grants": [],
        "errors": [],
    }

    # Ambil semua karyawan aktif
    employees = (
        db.query(Employee)
        .filter(Employee.active == True)
        .all()
    )

    is_reset_day = (
        target_date.month == LEAVE_RESET_MONTH
        and target_date.day == LEAVE_RESET_DAY
    )

    for emp in employees:
        join_date = emp.join_date
        if not join_date and getattr(emp, "contracts", None):
            contract_starts = [c.start_date for c in emp.contracts if getattr(c, "start_date", None)]
            if contract_starts:
                join_date = min(contract_starts)
                emp.join_date = join_date
                db.commit()

        if not join_date:
            continue

        try:
            first_ann = get_first_anniversary(join_date)

            # Kasus 1: Karyawan sudah melewati tahun anniversary pertama (mis. join 2024 -> anniversary 2025 -> sekarang 2026)
            if first_ann.year < year:
                # 1a. Jika tepat tanggal reset 1 Januari, hanguskan sisa saldo tahun lalu
                if is_reset_day:
                    prev_year = year - 1
                    expired_entry = expire_previous_year_balance(db, emp, prev_year)
                    if expired_entry:
                        result["reset_expired"].append({
                            "employee_id": emp.id,
                            "nama": emp.nama,
                            "prev_year": prev_year,
                            "amount_expired": expired_entry.amount,
                        })

                # 1b. Berikan kuota reset tahunan penuh 12 hari (idempotent)
                reset_entry = grant_annual_reset_quota(db, emp, year)
                if reset_entry:
                    result["reset_grants"].append({
                        "employee_id": emp.id,
                        "nama": emp.nama,
                        "year": year,
                        "quota_granted": reset_entry.amount,
                    })

            # Kasus 2: Anniversary pertama karyawan jatuh di tahun berjalan 'year'
            elif first_ann.year == year:
                # Hanya berikan jika tanggal target sudah tiba atau melewati tanggal anniversary pertama
                if target_date >= first_ann:
                    ann_entry = grant_anniversary_quota(db, emp, year)
                    if ann_entry:
                        result["anniversary_grants"].append({
                            "employee_id": emp.id,
                            "nama": emp.nama,
                            "anniversary_date": first_ann.isoformat(),
                            "quota_granted": ann_entry.amount,
                        })

        except Exception as e:
            result["errors"].append(f"Quota grant error [{emp.nama}]: {e}")

    # Summary counts
    result["summary"] = {
        "total_employees_processed": len(employees),
        "anniversary_grants_count": len(result["anniversary_grants"]),
        "expired_count": len(result["reset_expired"]),
        "reset_grants_count": len(result["reset_grants"]),
        "error_count": len(result["errors"]),
        "is_reset_day": is_reset_day,
    }

    print(f"[LeaveQuota] Job ran for {target_date}: {result['summary']}")
    return result
