# -*- coding: utf-8 -*-
from datetime import date, datetime
from typing import Optional, Dict, Any;
try:
    from zoneinfo import ZoneInfo
    JAKARTA_TZ = ZoneInfo("Asia/Jakarta")
except Exception:
    JAKARTA_TZ = None

# ── Konfigurasi Manajemen Kontrak Karyawan ──────────────────────────────────
# Jumlah hari reminder sebelum kontrak berakhir (H-10)
CONTRACT_REMINDER_DAYS = 10

# ── Konfigurasi Kuota Cuti Tahunan ──────────────────────────────────────────
# Kuota cuti tahunan penuh (hari) untuk karyawan yang sudah >1 tahun masa kerja
ANNUAL_LEAVE_QUOTA: int = 12

# Bulan & tanggal reset kuota tahunan (1 Januari = bulan 1, tanggal 1)
LEAVE_RESET_MONTH: int = 1
LEAVE_RESET_DAY: int = 1

# Masa kerja minimum (dalam tahun) agar karyawan berhak mendapat kuota penuh saat reset
LEAVE_MIN_TENURE_YEARS: int = 1


def get_today_jakarta() -> date:
    """Mengembalikan tanggal hari ini sesuai zona waktu Asia/Jakarta."""
    if JAKARTA_TZ:
        return datetime.now(JAKARTA_TZ).date()
    return date.today()


def calculate_tenure(join_date: Optional[date], target_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Menghitung masa kerja (tenure) karyawan dari `join_date` hingga `target_date` (default: hari ini di Asia/Jakarta).
    Return format: {"years": int, "months": int, "total_days": int, "display": "X tahun Y bulan"}
    """
    if not join_date:
        return {"years": 0, "months": 0, "total_days": 0, "display": "-"}

    if not target_date:
        target_date = get_today_jakarta()

    if target_date < join_date:
        return {"years": 0, "months": 0, "total_days": 0, "display": "0 bulan"}

    total_days = (target_date - join_date).days
    years = target_date.year - join_date.year
    months = target_date.month - join_date.month

    if target_date.day < join_date.day:
        months -= 1

    if months < 0:
        years -= 1
        months += 12

    parts = []
    if years > 0:
        parts.append(f"{years} tahun")
    if months > 0 or years == 0:
        parts.append(f"{months} bulan")

    display = " ".join(parts) if parts else "0 bulan"
    return {
        "years": max(0, years),
        "months": max(0, months),
        "total_days": total_days,
        "display": display,
    }


def calculate_phk_compensation(employment_status: str, join_date: Optional[date]) -> Dict[str, Any]:
    """
    Menyiapkan data kompensasi PHK berdasarkan status kepegawaian & masa kerja.
    TODO: Implementasikan rumus nominal kompensasi PHK lengkap (Pesangon, UPMK, UPH untuk Karyawan Tetap
    vs Uang Kompensasi PKWT sesuai PP 35/2021) setelah detail aturan kompensasi dikonfirmasi oleh HR Master.
    """
    tenure = calculate_tenure(join_date)
    return {
        "employment_status": employment_status,
        "join_date": join_date,
        "tenure_display": tenure["display"],
        "estimated_compensation": None,  # TODO: Tambahkan variabel kalkulasi nominal kompensasi saat aturan HR dikonfirmasi
        "note": "Data masa kerja ini digunakan sebagai acuan perhitungan kompensasi saat PHK. Kompensasi Karyawan Tetap dan PKWT dihitung berbeda.",
    }
