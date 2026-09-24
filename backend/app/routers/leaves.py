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
