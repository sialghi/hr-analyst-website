# -*- coding: utf-8 -*-
import datetime
import os
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Header, status, BackgroundTasks
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..leave_logic import (
    validate_annual_leave_request,
    record_leave_used,
    reverse_leave_used,
    get_ledger_balance,
    get_ledger_entries,
    get_ledger_granted,
    get_leave_balance_info,
    get_leave_request_days,
    ENTRY_USED,
    ENTRY_REVERSED,
    KATEGORI_POTONG_CUTI_MAP,
)
from .whatsapp import send_whatsapp_leave_status_notification

router = APIRouter(prefix="/leaves", tags=["leaves"])

BOT_API_KEY = os.environ.get("API_KEY", "").strip()

# ── Referensi kategori yang memotong kuota ────────────────────────────────────
# Dipindahkan ke leave_logic.py; di-import dari sana


def verify_bot_or_user(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth.get_current_user_optional),
):
    """
    Mengizinkan akses baik dari Web User yang sudah login (JWT)
    MAUPUN dari Bot Telegram / n8n via header X-API-Key.
    """
    if x_api_key and BOT_API_KEY and x_api_key == BOT_API_KEY:
        return "bot"
    if current_user:
        return current_user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autentikasi diperlukan (JWT User atau X-API-Key Bot)",
    )


def check_leave_overlap(
    db: Session,
    nama: str,
    tgl_mulai: datetime.date,
    tgl_selesai: datetime.date,
    exclude_id: Optional[int] = None,
):
    """
    Mengecek apakah karyawan sudah memiliki pengajuan (status PENDING atau APPROVED)
    yang bentrok/beririsan dengan rentang tgl_mulai s/d tgl_selesai.
    """
    q = db.query(models.LeaveRequest).filter(
        models.LeaveRequest.nama.ilike(nama.strip()),
        models.LeaveRequest.status.in_(["APPROVED", "PENDING"]),
        models.LeaveRequest.tanggal_mulai <= tgl_selesai,
        models.LeaveRequest.tanggal_selesai >= tgl_mulai,
    )
    if exclude_id:
        q = q.filter(models.LeaveRequest.id != exclude_id)
    return q.first()


def _get_employee_by_nama(db: Session, nama: str) -> Optional[models.Employee]:
    """Mencari karyawan berdasarkan nama (case-insensitive, exact match)."""
    return (
        db.query(models.Employee)
        .filter(models.Employee.nama.ilike(nama.strip()), models.Employee.active == True)
        .first()
    )


def get_annual_leave_stats(db: Session, nama: str, year: Optional[int] = None) -> dict:
    """
    Helper kompatibilitas untuk menghitung kuota cuti tahunan karyawan.
    Digunakan oleh WhatsApp bot dan endpoint terkait.
    """
    if not year:
        year = datetime.date.today().year

    emp = _get_employee_by_nama(db, nama)
    if not emp:
        return {
            "nama": nama.strip(),
            "total_quota": 0.0,
            "used_days": 0.0,
            "approved_days": 0.0,
            "pending_days": 0.0,
            "remaining_days": 0.0,
            "year": year,
            "is_eligible": False,
            "eligible_from": None,
            "error": "Karyawan tidak ditemukan",
        }

    info = get_leave_balance_info(db, emp, year)
    return {
        "nama": emp.nama,
        "total_quota": float(info.get("quota_granted", 0.0)),
        "used_days": float(info.get("quota_used", 0.0)),
        "approved_days": float(info.get("quota_used", 0.0)),
        "pending_days": 0.0,
        "remaining_days": float(info.get("quota_remaining", 0.0)),
        "year": year,
        "is_eligible": info.get("is_eligible", False),
        "eligible_from": info.get("eligible_from"),
        "error": info.get("error"),
    }



# ─────────────────────────────────────────────────────────────────────────────
# Endpoint: Info Saldo Cuti (dari Ledger)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/balance-info", response_model=schemas.LeaveBalanceInfoOut)
def get_leave_balance_info_endpoint(
    nama: str = Query(..., description="Nama Karyawan"),
    year: Optional[int] = Query(None, description="Tahun (default: tahun berjalan)"),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """
    Mengembalikan info saldo cuti tahunan dari LEDGER untuk satu karyawan:
    - join_date, anniversary, tanggal berhak cuti
    - kuota diberikan, dipakai, sisa
    - apakah sudah expired
    """
    if not year:
        year = datetime.date.today().year
    emp = _get_employee_by_nama(db, nama)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Karyawan '{nama}' tidak ditemukan.")
    return get_leave_balance_info(db, emp, year)


@router.get("/ledger", response_model=List[schemas.LeaveBalanceLedgerOut])
def get_leave_ledger(
    nama: str = Query(..., description="Nama Karyawan"),
    year: Optional[int] = Query(None, description="Tahun (default: tahun berjalan)"),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Riwayat ledger kuota cuti untuk karyawan tertentu (untuk audit HR)."""
    if not year:
        year = datetime.date.today().year
    emp = _get_employee_by_nama(db, nama)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Karyawan '{nama}' tidak ditemukan.")
    return get_ledger_entries(db, emp.id, year)


@router.post("/admin/run-quota-job", status_code=200)
def run_quota_job_manual(
    simulate_date: Optional[str] = Query(None, description="Simulasi tanggal (YYYY-MM-DD). Kosong = hari ini."),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """
    [HR Master Only] Jalankan leave quota job secara manual (untuk testing/backfill).
    Bisa mensimulasikan tanggal tertentu untuk menguji anniversary/reset.
    """
    from ..leave_logic import run_leave_quota_jobs
    if simulate_date:
        try:
            target = datetime.date.fromisoformat(simulate_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Format tanggal tidak valid. Gunakan YYYY-MM-DD.")
    else:
        from ..config import get_today_jakarta
        target = get_today_jakarta()

    result = run_leave_quota_jobs(db, target_date=target)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint: Annual Balance (kompatibilitas dengan UI lama)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/annual-balance")
def get_all_annual_leave_balances(
    year: Optional[int] = Query(None, description="Tahun rekap (default: tahun berjalan)"),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Rekap saldo kuota cuti tahunan untuk SELURUH karyawan (dari Ledger)."""
    if not year:
        year = datetime.date.today().year

    employees = db.query(models.Employee).filter(models.Employee.active == True).all()

    results = []
    for emp in employees:
        info = get_leave_balance_info(db, emp, year)
        # Map ke format yang sudah dipakai UI sebelumnya (backward compat)
        remaining = info["quota_remaining"]
        used = info["quota_used"]
        granted = info["quota_granted"]
        is_exceeded = remaining < 0
        results.append({
            "nama": emp.nama,
            "total_quota": granted,
            "used_days": used,
            "approved_days": used,
            "pending_days": 0.0,
            "remaining_days": max(0, remaining),
            "is_exceeded": is_exceeded,
            "excess_days": round(max(0, -remaining), 2),
            "year": year,
            # Tambahan dari ledger
            "join_date": info.get("join_date"),
            "eligible_from": info.get("eligible_from"),
            "anniversary_date": info.get("anniversary_date"),
            "has_quota": info.get("has_quota", False),
            "is_eligible": info.get("is_eligible", False),
            "error": info.get("error"),
        })

    # Juga tambahkan karyawan yang ada di LeaveRequest tapi tidak di Employee (data lama)
    leave_names = set(
        row[0] for row in db.query(models.LeaveRequest.nama).filter(
            models.LeaveRequest.tanggal_mulai >= datetime.date(year, 1, 1),
            models.LeaveRequest.tanggal_mulai <= datetime.date(year, 12, 31),
        ).all() if row[0]
    )
    emp_names = {e.nama for e in employees}
    for orphan_name in sorted(leave_names - emp_names):
        results.append({
            "nama": orphan_name,
            "total_quota": 0.0,
            "used_days": 0.0,
            "approved_days": 0.0,
            "pending_days": 0.0,
            "remaining_days": 0.0,
            "is_exceeded": False,
            "excess_days": 0.0,
            "year": year,
            "join_date": None,
            "eligible_from": None,
            "anniversary_date": None,
            "has_quota": False,
            "error": "Karyawan tidak ditemukan di database (data lama).",
        })

    results.sort(key=lambda x: x["nama"])
    return {
        "year": year,
        "total_employees": len(results),
        "data": results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint: Employee Detail (backward compat, dari ledger)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/employee-detail")
def get_employee_detail_leaves(
    nama: str = Query(..., description="Nama Karyawan"),
    year: Optional[int] = Query(None, description="Tahun (default: tahun berjalan)"),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Detail lengkap saldo, ledger, dan riwayat cuti 1 karyawan."""
    if not year:
        year = datetime.date.today().year

    emp = _get_employee_by_nama(db, nama)

    leaves = (
        db.query(models.LeaveRequest)
        .filter(
            models.LeaveRequest.nama.ilike(nama.strip()),
            models.LeaveRequest.tanggal_mulai >= datetime.date(year, 1, 1),
            models.LeaveRequest.tanggal_mulai <= datetime.date(year, 12, 31),
        )
        .order_by(models.LeaveRequest.tanggal_mulai.desc())
        .all()
    )

    # Saldo dari ledger jika ada employee record, fallback ke hitung manual
    if emp:
        balance_info = get_leave_balance_info(db, emp, year)
        total_quota = balance_info["quota_granted"]
        used_days = balance_info["quota_used"]
        remaining_days = balance_info["quota_remaining"]
        is_exceeded = remaining_days < 0
        excess_days = max(0, -remaining_days)
    else:
        # Fallback lama untuk data orphan
        KATEGORI_POTONG = {"CUTI_TAHUNAN": 1.0, "CUTI_SETENGAH_HARI": 0.5}
        used_days = 0.0
        for lv in leaves:
            if lv.status in ("APPROVED", "PENDING") and lv.kategori in KATEGORI_POTONG:
                used_days += lv.jumlah_hari if lv.jumlah_hari is not None else KATEGORI_POTONG[lv.kategori]
        total_quota = 12.0
        remaining_days = max(0.0, 12.0 - used_days)
        is_exceeded = used_days > 12.0
        excess_days = max(0.0, used_days - 12.0)
        balance_info = {}

    breakdown = {
        "cuti_tahunan": {"count": 0, "days": 0.0},
        "cuti_setengah": {"count": 0, "days": 0.0},
        "sakit": {"count": 0, "days": 0.0},
        "izin_pulang_cepat": {"count": 0, "days": 0.0},
        "izin_telat": {"count": 0, "days": 0.0},
        "absensi_jarak_jauh": {"count": 0, "days": 0.0},
        "lainnya": {"count": 0, "days": 0.0},
    }

    history = []
    for l in leaves:
        if l.status in ("APPROVED", "PENDING"):
            h_days = l.jumlah_hari if l.jumlah_hari is not None else (
                1.0 if l.kategori == "CUTI_TAHUNAN" else (0.5 if l.kategori == "CUTI_SETENGAH_HARI" else 1.0)
            )
            kat = l.kategori
            if kat == "CUTI_TAHUNAN":
                breakdown["cuti_tahunan"]["count"] += 1
                breakdown["cuti_tahunan"]["days"] += h_days
            elif kat == "CUTI_SETENGAH_HARI":
                breakdown["cuti_setengah"]["count"] += 1
                breakdown["cuti_setengah"]["days"] += h_days
            elif kat == "SAKIT":
                breakdown["sakit"]["count"] += 1
                breakdown["sakit"]["days"] += h_days
            elif kat == "IZIN_PULANG_CEPAT":
                breakdown["izin_pulang_cepat"]["count"] += 1
            elif kat == "IZIN_TELAT":
                breakdown["izin_telat"]["count"] += 1
            elif kat == "WORK_FROM_LOCATION":
                breakdown["absensi_jarak_jauh"]["count"] += 1
                breakdown["absensi_jarak_jauh"]["days"] += h_days
            else:
                breakdown["lainnya"]["count"] += 1
                breakdown["lainnya"]["days"] += h_days

        history.append({
            "id": l.id,
            "kategori": l.kategori,
            "tanggal_mulai": str(l.tanggal_mulai),
            "tanggal_selesai": str(l.tanggal_selesai),
            "jumlah_hari": l.jumlah_hari,
            "alasan": l.alasan,
            "status": l.status,
            "approved_by": l.approved_by,
        })

    return {
        "nama": nama.strip(),
        "year": year,
        "total_quota": total_quota,
        "used_days": round(used_days, 2),
        "remaining_days": round(remaining_days, 2),
        "is_exceeded": is_exceeded,
        "excess_days": round(excess_days, 2),
        "balance_info": balance_info,
        "breakdown": breakdown,
        "history": history,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint: Quota (backward compat)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/quota")
def get_leave_quota(
    nama: str = Query(..., description="Nama Karyawan"),
    year: Optional[int] = Query(None, description="Tahun (default: tahun berjalan)"),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Melihat sisa jatah kuota cuti tahunan karyawan."""
    if not year:
        year = datetime.date.today().year
    emp = _get_employee_by_nama(db, nama)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Karyawan '{nama}' tidak ditemukan.")
    info = get_leave_balance_info(db, emp, year)
    return {
        "nama": nama,
        "total_quota": info["quota_granted"],
        "used_days": info["quota_used"],
        "remaining_days": info["quota_remaining"],
        "is_exceeded": info["is_exceeded"],
        "year": year,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint: Daftar Pengajuan
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[schemas.LeaveRequestOut])
def list_leave_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    nama: Optional[str] = Query(default=None),
    kategori: Optional[str] = Query(default=None),
    cabang: Optional[str] = Query(default=None),
    tipe_absensi: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Melihat daftar permohonan cuti/izin (bisa difilter status, nama, kategori, cabang, tipe_absensi)."""
    q = db.query(models.LeaveRequest)
    if status_filter:
        q = q.filter(models.LeaveRequest.status == status_filter.upper())
    if nama:
        q = q.filter(models.LeaveRequest.nama.ilike(f"%{nama}%"))
    if kategori:
        q = q.filter(models.LeaveRequest.kategori == kategori.upper())
    if cabang:
        q = q.filter(models.LeaveRequest.location_cabang.ilike(f"%{cabang}%"))
    if tipe_absensi:
        q = q.filter(models.LeaveRequest.tipe_absensi == tipe_absensi.lower())
    return q.order_by(models.LeaveRequest.created_at.desc()).all()


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint: Buat Pengajuan Baru
# ─────────────────────────────────────────────────────────────────────────────

@router.post("", response_model=schemas.LeaveRequestOut)
def create_leave_request(
    payload: schemas.LeaveRequestCreate,
    db: Session = Depends(get_db),
    caller=Depends(verify_bot_or_user),
):
    """
    Mengajukan cuti / izin baru.
    Bisa dipanggil oleh staf HR di web, maupun oleh Bot Telegram / n8n via X-API-Key.

    Untuk CUTI_TAHUNAN dan CUTI_SETENGAH_HARI:
    - Validasi anniversary: tolak jika tanggal pengajuan sebelum anniversary pertama.
    - Validasi saldo: tolak jika melebihi sisa saldo.
    - Asumsi A2: Pemotongan dari kuota tahun tanggal_mulai.
    """
    kategori_norm = payload.kategori.upper().strip()
    valid_kategori = {"CUTI_TAHUNAN", "CUTI_SETENGAH_HARI", "SAKIT", "IZIN_PULANG_CEPAT", "IZIN_TELAT", "LAINNYA", "WORK_FROM_LOCATION"}
    if kategori_norm not in valid_kategori:
        kategori_norm = "LAINNYA"

    tipe_absensi = "remote_work" if kategori_norm == "WORK_FROM_LOCATION" else "normal"

    tgl_m = payload.tanggal_mulai
    tgl_s = payload.tanggal_selesai

    if tgl_s < tgl_m:
        raise HTTPException(status_code=400, detail="Tanggal selesai tidak boleh sebelum tanggal mulai.")

    # Pengecekan Tanggal Bentrok
    overlap = check_leave_overlap(db, payload.nama, tgl_m, tgl_s)
    if overlap:
        tgl_str = (
            overlap.tanggal_mulai.strftime("%d-%m-%Y")
            if overlap.tanggal_mulai == overlap.tanggal_selesai
            else f"{overlap.tanggal_mulai.strftime('%d-%m-%Y')} s/d {overlap.tanggal_selesai.strftime('%d-%m-%Y')}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"Pengajuan bentrok: {payload.nama} sudah memiliki pengajuan {overlap.kategori} (#{overlap.id}) yang aktif pada tanggal {tgl_str} (Status: {overlap.status}).",
        )

    # Pengecekan Kuota Cuti Tahunan (dari Ledger + validasi anniversary)
    if kategori_norm in KATEGORI_POTONG_CUTI_MAP:
        # Hitung hari yang diminta
        if payload.jumlah_hari is not None:
            requested_days = float(payload.jumlah_hari)
        else:
            bobot = KATEGORI_POTONG_CUTI_MAP[kategori_norm]
            range_days = (tgl_s - tgl_m).days + 1
            requested_days = range_days * bobot

        # Cari employee record
        emp = _get_employee_by_nama(db, payload.nama)
        if emp:
            ok, err_msg = validate_annual_leave_request(db, emp, tgl_m, requested_days)
            if not ok:
                raise HTTPException(status_code=400, detail=err_msg)
        # Jika employee tidak ditemukan (data lama/bot), lewati validasi anniversary

    leave = models.LeaveRequest(
        nama=payload.nama.strip(),
        telegram_user_id=payload.telegram_user_id,
        whatsapp_user_id=getattr(payload, "whatsapp_user_id", None),
        kategori=kategori_norm,
        tanggal_mulai=payload.tanggal_mulai,
        tanggal_selesai=payload.tanggal_selesai,
        jumlah_hari=payload.jumlah_hari,
        jam_izin=payload.jam_izin,
        alasan=payload.alasan,
        catatan_hr=payload.catatan_hr,
        tipe_absensi=tipe_absensi,
        location_cabang=payload.location_cabang,
        status="PENDING",
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint: Update Status (Approve / Reject)
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{leave_id}/status", response_model=schemas.LeaveRequestOut)
async def update_leave_status(
    leave_id: int,
    payload: schemas.LeaveRequestStatusUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_hr_master),
):
    """
    Approval / Reject pengajuan cuti.
    HANYA HR Master yang bisa mengubah status.

    Saat APPROVED: tulis entri USED ke ledger (jika cuti tahunan/CS).
    Saat REJECTED atau dikembalikan ke PENDING: balikkan USED via REVERSED.
    """
    leave = db.query(models.LeaveRequest).filter(models.LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Data pengajuan cuti/izin tidak ditemukan.")

    new_status = payload.status.upper().strip()
    if new_status not in ("APPROVED", "REJECTED", "PENDING"):
        raise HTTPException(status_code=400, detail="Status tidak valid. Gunakan APPROVED, REJECTED, atau PENDING.")

    prev_status = leave.status
    approver_name = f"HR Master ({current_user.nama})"
    leave.status = new_status
    if payload.catatan_hr is not None:
        leave.catatan_hr = payload.catatan_hr

    if new_status in ("APPROVED", "REJECTED"):
        leave.approved_by = approver_name
        leave.approved_at = datetime.datetime.utcnow()
    else:
        leave.approved_by = None
        leave.approved_at = None

    db.commit()
    db.refresh(leave)

    # ── Ledger Operations ──────────────────────────────────────────────────
    if leave.kategori in KATEGORI_POTONG_CUTI_MAP:
        emp = _get_employee_by_nama(db, leave.nama)
        if emp:
            days = get_leave_request_days(leave)
            year = leave.tanggal_mulai.year
            desc = f"{leave.kategori} {leave.tanggal_mulai} s/d {leave.tanggal_selesai}"

            if new_status == "APPROVED" and prev_status != "APPROVED":
                # Baru disetujui → catat USED
                record_leave_used(db, emp.id, year, days, leave.id, desc)
            elif new_status in ("REJECTED", "PENDING") and prev_status == "APPROVED":
                # Dibatalkan dari APPROVED → balikkan USED
                reverse_leave_used(db, emp.id, year, leave.id, desc)

    # ── WhatsApp Notification ──────────────────────────────────────────────
    if getattr(leave, "whatsapp_user_id", None) and new_status in ("APPROVED", "REJECTED"):
        background_tasks.add_task(
            send_whatsapp_leave_status_notification,
            whatsapp_user_id=leave.whatsapp_user_id,
            leave_id=leave.id,
            nama=leave.nama,
            kategori=leave.kategori,
            tanggal_mulai=leave.tanggal_mulai,
            tanggal_selesai=leave.tanggal_selesai,
            jam_izin=leave.jam_izin,
            alasan=leave.alasan,
            status=new_status,
            approved_by=approver_name,
            catatan_hr=leave.catatan_hr,
        )

    return leave


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint: Delete
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{leave_id}", status_code=204)
def delete_leave_request(
    leave_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """HANYA HR Master yang boleh menghapus data pengajuan cuti."""
    leave = db.query(models.LeaveRequest).filter(models.LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Data cuti tidak ditemukan.")

    # Balikkan USED jika cuti yang dihapus statusnya APPROVED
    if leave.status == "APPROVED" and leave.kategori in KATEGORI_POTONG_CUTI_MAP:
        emp = _get_employee_by_nama(db, leave.nama)
        if emp:
            days = leave.jumlah_hari if leave.jumlah_hari is not None else KATEGORI_POTONG_CUTI_MAP.get(leave.kategori, 1.0)
            year = leave.tanggal_mulai.year
            desc = f"{leave.kategori} {leave.tanggal_mulai} s/d {leave.tanggal_selesai} [DIHAPUS]"
            reverse_leave_used(db, emp.id, year, leave.id, desc)

    db.delete(leave)
    db.commit()
    return None
