# -*- coding: utf-8 -*-
import datetime
import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Header, status, BackgroundTasks
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from .telegram import send_leave_status_notification_to_user

router = APIRouter(prefix="/leaves", tags=["leaves"])

BOT_API_KEY = os.environ.get("API_KEY", "").strip()


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


TOTAL_JATAH_CUTI_TAHUNAN = 12


def get_annual_leave_stats(db: Session, nama: str, year: Optional[int] = None):
    """Menghitung total kuota, hari yang dipakai (approved & pending), dan sisa kuota cuti tahunan."""
    if not year:
        year = datetime.date.today().year

    leaves = (
        db.query(models.LeaveRequest)
        .filter(
            models.LeaveRequest.nama.ilike(nama.strip()),
            models.LeaveRequest.kategori == "CUTI_TAHUNAN",
            models.LeaveRequest.status.in_(["APPROVED", "PENDING"]),
        )
        .all()
    )

    used_days = 0
    approved_days = 0
    pending_days = 0

    for l in leaves:
        if l.tanggal_mulai and l.tanggal_selesai and l.tanggal_mulai.year == year:
            num_days = (l.tanggal_selesai - l.tanggal_mulai).days + 1
            if num_days > 0:
                used_days += num_days
                if l.status == "APPROVED":
                    approved_days += num_days
                elif l.status == "PENDING":
                    pending_days += num_days

    remaining_days = max(0, TOTAL_JATAH_CUTI_TAHUNAN - used_days)
    return {
        "nama": nama.strip(),
        "total_quota": TOTAL_JATAH_CUTI_TAHUNAN,
        "used_days": used_days,
        "approved_days": approved_days,
        "pending_days": pending_days,
        "remaining_days": remaining_days,
        "year": year,
    }


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


@router.get("/quota")
def get_leave_quota(
    nama: str = Query(..., description="Nama Karyawan"),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Melihat sisa jatah kuota cuti tahunan karyawan."""
    return get_annual_leave_stats(db, nama)


@router.get("", response_model=list[schemas.LeaveRequestOut])
def list_leave_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    nama: Optional[str] = Query(default=None),
    kategori: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Melihat daftar permohonan cuti/izin (bisa difilter status, nama, kategori)."""
    q = db.query(models.LeaveRequest)
    if status_filter:
        q = q.filter(models.LeaveRequest.status == status_filter.upper())
    if nama:
        q = q.filter(models.LeaveRequest.nama.ilike(f"%{nama}%"))
    if kategori:
        q = q.filter(models.LeaveRequest.kategori == kategori.upper())
    return q.order_by(models.LeaveRequest.created_at.desc()).all()


@router.post("", response_model=schemas.LeaveRequestOut)
def create_leave_request(
    payload: schemas.LeaveRequestCreate,
    db: Session = Depends(get_db),
    caller=Depends(verify_bot_or_user),
):
    """
    Mengajukan cuti / izin baru.
    Bisa dipanggil oleh staf HR di web, maupun oleh Bot Telegram / n8n via X-API-Key.
    """
    # Normalisasi format kategori
    kategori_norm = payload.kategori.upper().strip()
    valid_kategori = {"CUTI_TAHUNAN", "SAKIT", "IZIN_PULANG_CEPAT", "IZIN_TELAT", "LAINNYA"}
    if kategori_norm not in valid_kategori:
        kategori_norm = "LAINNYA"

    tgl_m = payload.tanggal_mulai
    tgl_s = payload.tanggal_selesai

    if tgl_s < tgl_m:
        raise HTTPException(status_code=400, detail="Tanggal selesai tidak boleh sebelum tanggal mulai.")

    # Pengecekan Tanggal Bentrok / Overlap dengan pengajuan aktif sebelumnya
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

    # Pengecekan Jatah Kuota Cuti Tahunan (12 hari/tahun)
    if kategori_norm == "CUTI_TAHUNAN":
        requested_days = (tgl_s - tgl_m).days + 1
        stats = get_annual_leave_stats(db, payload.nama, year=tgl_m.year)
        if stats["remaining_days"] <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Jatah Cuti Tahunan untuk {payload.nama} tahun {tgl_m.year} sudah habis (12/12 hari telah digunakan/pending).",
            )
        if requested_days > stats["remaining_days"]:
            raise HTTPException(
                status_code=400,
                detail=f"Jumlah hari cuti yang diajukan ({requested_days} hari) melebihi sisa jatah kuota cuti tahunan ({stats['remaining_days']} hari).",
            )

    leave = models.LeaveRequest(
        nama=payload.nama.strip(),
        telegram_user_id=payload.telegram_user_id,
        kategori=kategori_norm,
        tanggal_mulai=payload.tanggal_mulai,
        tanggal_selesai=payload.tanggal_selesai,
        jam_izin=payload.jam_izin,
        alasan=payload.alasan,
        catatan_hr=payload.catatan_hr,
        status="PENDING",
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


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
    HANYA HR Master yang login di Website yang boleh mengubah status (approval lewat Telegram dinonaktifkan).
    Setelah status diubah, notifikasi otomatis dikirimkan ke Telegram pemohon
    HANYA pada telegram_user_id yang tersimpan pada pengajuan tersebut.
    """
    leave = db.query(models.LeaveRequest).filter(models.LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Data pengajuan cuti/izin tidak ditemukan.")

    new_status = payload.status.upper().strip()
    if new_status not in ("APPROVED", "REJECTED", "PENDING"):
        raise HTTPException(status_code=400, detail="Status tidak valid. Gunakan APPROVED, REJECTED, atau PENDING.")

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

    # Kirim kabar hasil respon HR Master KHUSUS ke ID Telegram si pengaju
    if leave.telegram_user_id and new_status in ("APPROVED", "REJECTED"):
        background_tasks.add_task(
            send_leave_status_notification_to_user,
            telegram_user_id=leave.telegram_user_id,
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
    db.delete(leave)
    db.commit()
    return None
