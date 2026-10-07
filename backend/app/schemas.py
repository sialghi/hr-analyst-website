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


# ---------- Employment Contract (kontrak kerja PKWT) ----------
class EmploymentContractBase(BaseModel):
    contract_number: int = 1
    start_date: date
    end_date: date
    status: str = "ACTIVE"  # ACTIVE, EXPIRED, PROMOTED_TO_PERMANENT, RENEWED
    keterangan: Optional[str] = None


class EmploymentContractCreate(BaseModel):
    start_date: date
    end_date: date
    keterangan: Optional[str] = None


class EmploymentContractOut(EmploymentContractBase):
    id: int
    employee_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Employee (master karyawan) ----------
class EmployeeBase(BaseModel):
    nama: str
    employee_code: Optional[str] = None
    nik: Optional[str] = None             # NIK KTP 16 digit
    id_mesin: Optional[str] = None
    profile_code: str
    cabang: Optional[str] = None
    jabatan: Optional[str] = None
    payroll_status: Optional[str] = None
    uang_makan_override: Optional[int] = None
    bpjs_kesehatan: Optional[int] = 0
    bpjs_tk: Optional[int] = 0
    active: bool = True

    # Status Kepegawaian & Data Kontrak
    employment_status: str = "PKWTT"  # "PKWTT", "PKWT", atau "PHL"
    join_date: Optional[date] = None   # Tanggal masuk / bergabung

    # Input helper saat membuat/mengubah karyawan PKWT
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    contract_keterangan: Optional[str] = None

    # Aturan Khusus per Karyawan (Cascading Override)
    has_custom_rules: bool = False
    jam_masuk_override: Optional[str] = None        # "HH:MM", null = ikut profil
    jam_keluar_override: Optional[str] = None       # "HH:MM", null = ikut profil
    toleransi_telat_menit_override: Optional[int] = None  # null = ikut global
    bonus_lembur_per_jam_override: Optional[int] = None   # null = ikut global


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(EmployeeBase):
    pass


class EmployeeOut(EmployeeBase):
    id: int
    contracts: List[EmploymentContractOut] = []
    tenure_display: Optional[str] = None
    contract_reminder_status: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class EmployeeImportApproval(BaseModel):
    profile_code: str
    employment_status: str
    join_date: Optional[date] = None
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    contract_keterangan: Optional[str] = None


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
    whatsapp_user_id: Optional[str] = None
    kategori: str = "CUTI_TAHUNAN"  # CUTI_TAHUNAN, CUTI_SETENGAH_HARI, SAKIT, IZIN_PULANG_CEPAT, IZIN_TELAT, LAINNYA, WORK_FROM_LOCATION
    tanggal_mulai: date
    tanggal_selesai: date
    jumlah_hari: Optional[float] = None   # Explicit override: 0.5 untuk setengah hari, None = hitung dari rentang tanggal
    jam_izin: Optional[str] = None  # "HH:MM"
    alasan: Optional[str] = None
    catatan_hr: Optional[str] = None
    # --- Absensi Jarak Jauh ---
    tipe_absensi: Optional[str] = "normal"       # "normal" atau "remote_work"
    location_cabang: Optional[str] = None        # cabang karyawan saat absen jarak jauh


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
    tipe_absensi: Optional[str] = "normal"
    location_cabang: Optional[str] = None
    jumlah_hari: Optional[float] = None
    unpaid_leave_days: float = 0.0
    foto_bukti: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Employee Adjustment (bonus/potongan tentatif) ----------
class EmployeeAdjustmentUpdate(BaseModel):
    nama: str
    bonus_lain: Optional[float] = 0.0
    potongan_lain: Optional[float] = 0.0
    catatan: Optional[str] = None


class EmployeeAdjustmentOut(BaseModel):
    id: int
    nama: str
    bonus_lain: float
    potongan_lain: float
    catatan: Optional[str] = None
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Employee Adjustment (bonus/potongan lain) ----------
class EmployeeAdjustmentUpdate(BaseModel):
    nama: str
    bonus_lain: Optional[float] = None
    potongan_lain: Optional[float] = None
    catatan: Optional[str] = None


class EmployeeAdjustmentOut(BaseModel):
    id: int
    nama: str
    bonus_lain: float
    potongan_lain: float
    catatan: Optional[str] = None
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Absen Manual (hari kerja manual per periode) ----------
class AbsenManualUpdate(BaseModel):
    nama: str
    tahun: int = Field(..., ge=2000, le=2100)
    bulan: int = Field(..., ge=1, le=12)
    jumlah: int = Field(default=0, ge=0, le=31)


class AbsenManualOut(BaseModel):
    id: int
    nama: str
    tahun: int
    bulan: int
    jumlah: int
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Leave Balance Ledger ----------
class LeaveBalanceLedgerOut(BaseModel):
    id: int
    employee_id: int
    year: int
    entry_type: str   # GRANT_ANNIVERSARY, GRANT_ANNUAL_RESET, USED, REVERSED, EXPIRED
    amount: float
    leave_request_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class LeaveBalanceInfoOut(BaseModel):
    """Response schema untuk endpoint GET /leaves/balance-info."""
    employee_id: Optional[int] = None
    nama: str
    join_date: Optional[str] = None
    year: int
    has_quota: bool
    is_eligible: bool = False
    quota_granted: float
    quota_used: float
    quota_remaining: float
    is_exceeded: bool = False
    anniversary_date: Optional[str] = None
    next_anniversary: Optional[str] = None
    is_first_year: bool = False
    eligible_from: Optional[str] = None
    expired_date: Optional[str] = None
    error: Optional[str] = None
