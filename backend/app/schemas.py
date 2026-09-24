# -*- coding: utf-8 -*-
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from pydantic import BaseModel, EmailStr, Field

from .models import RoleEnum


# ---------- Auth ----------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: RoleEnum
    nama: str


class UserCreate(BaseModel):
    nama: str
    email: EmailStr
    password: str
    role: RoleEnum = RoleEnum.hr_staff


class UserOut(BaseModel):
    id: int
    nama: str
    email: EmailStr
    role: RoleEnum

    class Config:
        from_attributes = True


# ---------- Profile (aturan bisnis per divisi) ----------
class LemburKhusus(BaseModel):
    hanya_hari: List[str] = []
    threshold_jam: float
    tarif_per_jam: int
    bonus_flat: int


class ProfileBase(BaseModel):
    code: str = Field(..., description="Kode unik profil, mis. OFFICE, DRIVER")
    nama: str
    cabang: List[str] = []
    hari_kerja: List[str] = []
    jam_masuk: Optional[Dict[str, str]] = None    # {"default": "08:00", "Sabtu": "07:00"}
    jam_keluar: Optional[Dict[str, str]] = None
    patokan_lembur: Optional[Dict[str, str]] = None
    ikut_telat: bool = True
    ikut_lembur: bool = True
    ikut_kuota_hari_kerja: bool = True
    hari_kandidat_kuota: List[str] = []
    min_hari_kerja: int = 0
    ikut_bonus_tanggal_merah: bool = True
    lembur_khusus: Optional[LemburKhusus] = None


class ProfileCreate(ProfileBase):
    pass


class ProfileUpdate(ProfileBase):
    pass


class ProfileOut(ProfileBase):
    id: int
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Business Rule (aturan global) ----------
class BusinessRuleBase(BaseModel):
    profil_default: str = "OFFICE"
    jam_masuk_standar: str = "08:00"
    jam_keluar_standar: str = "16:00"
    dedup_threshold_menit: int = 2
    min_hari_kerja_per_minggu: int = 4
    min_minggu_berturut_alpa: int = 2
    uang_makan_default: int = 100_000
    potongan_telat_sedikit: int = 10_000
    potongan_telat_banyak_persen: float = 0.5
    batas_telat_ringan: str = "12:00"
    batas_telat_berat: str = "15:00"
    potongan_pulang_duluan_sedikit: int = 10_000
    potongan_pulang_duluan_banyak_persen: float = 0.5
    batas_pulang_duluan_ringan: str = "15:00"
    batas_pulang_duluan_berat: str = "16:00"
    bonus_lembur_per_jam: int = 10_000
    menit_pembulatan_lembur: int = 31
    toleransi_telat_hari_ke: int = 1
    toleransi_telat_max_menit: int = 10


class BusinessRuleUpdate(BusinessRuleBase):
    pass


class BusinessRuleOut(BusinessRuleBase):
    id: int
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Employee (master karyawan) ----------
class EmployeeBase(BaseModel):
    nama: str
    id_mesin: Optional[str] = None
    profile_code: str
    cabang: Optional[str] = None
    uang_makan_override: Optional[int] = None
    active: bool = True


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(EmployeeBase):
    pass


class EmployeeOut(EmployeeBase):
    id: int

    class Config:
        from_attributes = True


# ---------- Holiday (tanggal merah) ----------
class HolidayBase(BaseModel):
    tanggal: date
    keterangan: Optional[str] = None


class HolidayCreate(HolidayBase):
    pass


class HolidayOut(HolidayBase):
    id: int

    class Config:
        from_attributes = True


# ---------- Leave Request (cuti & izin) ----------
class LeaveRequestBase(BaseModel):
    nama: str
    telegram_user_id: Optional[str] = None
    kategori: str = "CUTI_TAHUNAN"  # CUTI_TAHUNAN, SAKIT, IZIN_PULANG_CEPAT, IZIN_TELAT, LAINNYA
    tanggal_mulai: date
    tanggal_selesai: date
    jam_izin: Optional[str] = None  # "HH:MM"
    alasan: Optional[str] = None
    catatan_hr: Optional[str] = None


class LeaveRequestCreate(LeaveRequestBase):
    pass


class LeaveRequestUpdate(BaseModel):
    nama: Optional[str] = None
    kategori: Optional[str] = None
    tanggal_mulai: Optional[date] = None
    tanggal_selesai: Optional[date] = None
    jam_izin: Optional[str] = None
    alasan: Optional[str] = None
    catatan_hr: Optional[str] = None


class LeaveRequestStatusUpdate(BaseModel):
    status: str  # APPROVED, REJECTED, PENDING
    catatan_hr: Optional[str] = None


class LeaveRequestOut(LeaveRequestBase):
    id: int
    status: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

