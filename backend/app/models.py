# -*- coding: utf-8 -*-
import datetime
import enum

from sqlalchemy import (
    Column, Integer, String, Boolean, Float, Date, DateTime, ForeignKey, JSON, Enum
)
from sqlalchemy.orm import relationship

from .database import Base


class RoleEnum(str, enum.Enum):
    hr_master = "hr_master"
    hr_staff = "hr_staff"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(RoleEnum), nullable=False, default=RoleEnum.hr_staff)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Profile(Base):
    """Setara PROFIL_JADWAL[kode] di config.py asli. Bisa ditambah/diubah/dihapus HR Master."""
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)  # e.g. "OFFICE", "DRIVER"
    nama = Column(String, nullable=False)                            # nama tampilan
    cabang = Column(JSON, default=list)                              # list[str]
    hari_kerja = Column(JSON, default=list)                          # list[str] nama hari
    jam_masuk = Column(JSON, nullable=True)                          # {"default": "08:00", "Sabtu": "..."} atau null
    jam_keluar = Column(JSON, nullable=True)
    patokan_lembur = Column(JSON, nullable=True)
    ikut_telat = Column(Boolean, default=True)
    ikut_lembur = Column(Boolean, default=True)
    ikut_kuota_hari_kerja = Column(Boolean, default=True)
    hari_kandidat_kuota = Column(JSON, default=list)
    min_hari_kerja = Column(Integer, default=0)
    ikut_bonus_tanggal_merah = Column(Boolean, default=True)
    # aturan lembur khusus opsional, mis. profil DRIVER: {"hanya_hari": ["Minggu"], "threshold_jam": 4, "tarif_per_jam": 20000, "bonus_flat": 100000}
    lembur_khusus = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    employees = relationship("Employee", back_populates="profile")


class BusinessRule(Base):
    """Aturan global (bukan per-profil). Didesain sebagai singleton (1 baris saja, id=1)."""
    __tablename__ = "business_rule"

    id = Column(Integer, primary_key=True, index=True)

    profil_default = Column(String, default="OFFICE")
    jam_masuk_standar = Column(String, default="08:00")   # disimpan sbg "HH:MM"
    jam_keluar_standar = Column(String, default="16:00")

    dedup_threshold_menit = Column(Integer, default=2)
    min_hari_kerja_per_minggu = Column(Integer, default=4)
    min_minggu_berturut_alpa = Column(Integer, default=2)

    uang_makan_default = Column(Integer, default=100_000)
    potongan_telat_sedikit = Column(Integer, default=10_000)
    potongan_telat_banyak_persen = Column(Float, default=0.5)
    batas_telat_ringan = Column(String, default="12:00")
    batas_telat_berat = Column(String, default="15:00")

    potongan_pulang_duluan_sedikit = Column(Integer, default=10_000)
    potongan_pulang_duluan_banyak_persen = Column(Float, default=0.5)
    batas_pulang_duluan_ringan = Column(String, default="15:00")
    batas_pulang_duluan_berat = Column(String, default="16:00")

    bonus_lembur_per_jam = Column(Integer, default=10_000)
    menit_pembulatan_lembur = Column(Integer, default=31)

    toleransi_telat_hari_ke = Column(Integer, default=1)
    toleransi_telat_max_menit = Column(Integer, default=10)

    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class Employee(Base):
    """Master karyawan. HR Master bisa tambah karyawan baru & assign ke profil tertentu."""
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String, nullable=False, index=True)
    id_mesin = Column(String, nullable=True)  # ID di mesin absensi, opsional
    profile_code = Column(String, ForeignKey("profiles.code"), nullable=False)
    cabang = Column(String, nullable=True)
    uang_makan_override = Column(Integer, nullable=True)  # null -> pakai default global
    active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    profile = relationship("Profile", back_populates="employees")


class Holiday(Base):
    """Pengganti template_tanggal_merah.xlsx — daftar tanggal merah nasional."""
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True, index=True)
    tanggal = Column(Date, unique=True, nullable=False)
    keterangan = Column(String, nullable=True)
