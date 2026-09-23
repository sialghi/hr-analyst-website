# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _profile_to_out(p: models.Profile) -> schemas.ProfileOut:
    return schemas.ProfileOut(
        id=p.id, code=p.code, nama=p.nama, cabang=p.cabang or [], hari_kerja=p.hari_kerja or [],
        jam_masuk=p.jam_masuk, jam_keluar=p.jam_keluar, patokan_lembur=p.patokan_lembur,
        ikut_telat=p.ikut_telat, ikut_lembur=p.ikut_lembur, ikut_kuota_hari_kerja=p.ikut_kuota_hari_kerja,
        hari_kandidat_kuota=p.hari_kandidat_kuota or [], min_hari_kerja=p.min_hari_kerja,
        ikut_bonus_tanggal_merah=p.ikut_bonus_tanggal_merah, lembur_khusus=p.lembur_khusus,
        updated_at=p.updated_at,
    )


@router.get("", response_model=list[schemas.ProfileOut])
def list_profiles(db: Session = Depends(get_db), _: models.User = Depends(auth.get_current_user)):
    """Semua user login (HR Master maupun HR Staff) boleh MELIHAT aturan bisnis."""
    return [_profile_to_out(p) for p in db.query(models.Profile).order_by(models.Profile.nama).all()]


@router.get("/{code}", response_model=schemas.ProfileOut)
def get_profile(code: str, db: Session = Depends(get_db), _: models.User = Depends(auth.get_current_user)):
    p = db.query(models.Profile).filter(models.Profile.code == code).first()
    if not p:
        raise HTTPException(status_code=404, detail="Profil tidak ditemukan.")
    return _profile_to_out(p)


@router.post("", response_model=schemas.ProfileOut)
def create_profile(
    payload: schemas.ProfileCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """HANYA HR Master yang boleh membuat profil/divisi baru."""
    existing = db.query(models.Profile).filter(models.Profile.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Kode profil '{payload.code}' sudah dipakai.")

    p = models.Profile(
        code=payload.code, nama=payload.nama, cabang=payload.cabang, hari_kerja=payload.hari_kerja,
        jam_masuk=payload.jam_masuk, jam_keluar=payload.jam_keluar, patokan_lembur=payload.patokan_lembur,
        ikut_telat=payload.ikut_telat, ikut_lembur=payload.ikut_lembur,
        ikut_kuota_hari_kerja=payload.ikut_kuota_hari_kerja, hari_kandidat_kuota=payload.hari_kandidat_kuota,
        min_hari_kerja=payload.min_hari_kerja, ikut_bonus_tanggal_merah=payload.ikut_bonus_tanggal_merah,
        lembur_khusus=payload.lembur_khusus.dict() if payload.lembur_khusus else None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _profile_to_out(p)


@router.put("/{code}", response_model=schemas.ProfileOut)
def update_profile(
    code: str,
    payload: schemas.ProfileUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """HANYA HR Master yang boleh mengubah aturan bisnis suatu profil (jam kerja, lembur, dst)."""
    p = db.query(models.Profile).filter(models.Profile.code == code).first()
    if not p:
        raise HTTPException(status_code=404, detail="Profil tidak ditemukan.")

    p.nama = payload.nama
    p.cabang = payload.cabang
    p.hari_kerja = payload.hari_kerja
    p.jam_masuk = payload.jam_masuk
    p.jam_keluar = payload.jam_keluar
    p.patokan_lembur = payload.patokan_lembur
    p.ikut_telat = payload.ikut_telat
    p.ikut_lembur = payload.ikut_lembur
    p.ikut_kuota_hari_kerja = payload.ikut_kuota_hari_kerja
    p.hari_kandidat_kuota = payload.hari_kandidat_kuota
    p.min_hari_kerja = payload.min_hari_kerja
    p.ikut_bonus_tanggal_merah = payload.ikut_bonus_tanggal_merah
    p.lembur_khusus = payload.lembur_khusus.dict() if payload.lembur_khusus else None

    db.commit()
    db.refresh(p)
    return _profile_to_out(p)


@router.delete("/{code}")
def delete_profile(code: str, db: Session = Depends(get_db), _: models.User = Depends(auth.require_hr_master)):
    p = db.query(models.Profile).filter(models.Profile.code == code).first()
    if not p:
        raise HTTPException(status_code=404, detail="Profil tidak ditemukan.")

    n_emp = db.query(models.Employee).filter(models.Employee.profile_code == code).count()
    if n_emp > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Tidak bisa dihapus: masih ada {n_emp} karyawan terdaftar di profil ini. Pindahkan dulu karyawannya.",
        )

    db.delete(p)
    db.commit()
    return {"status": "sukses"}
