# -*- coding: utf-8 -*-
import datetime
import enum

from sqlalchemy import (
    Column, Integer, String, Boolean, Float, Date, DateTime, ForeignKey, JSON, Enum,
    UniqueConstraint,
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
    bpjs_kesehatan = Column(Integer, nullable=True, default=0)
    bpjs_tk = Column(Integer, nullable=True, default=0)
    active = Column(Boolean, default=True)

    # ── Status Kepegawaian & Data Kontrak ────────────────────────────────────
    # employment_status: "TETAP" (karyawan tetap) atau "PKWT" (karyawan kontrak)
    employment_status = Column(String, nullable=False, default="TETAP")
    # join_date: Tanggal mulai bergabung / masuk perusahaan (Wajib diisi untuk hitungan kompensasi PHK)
    join_date = Column(Date, nullable=True)

    # ── Aturan Khusus per Karyawan (Cascading Override) ──────────────────────
    # Flag toggle: jika False, semua field _override di bawah diabaikan (NULL = ikut divisi/global)
    has_custom_rules = Column(Boolean, default=False, nullable=False)

    # Jam kerja override (format "HH:MM", null = ikut profil)
    jam_masuk_override = Column(String, nullable=True)
    jam_keluar_override = Column(String, nullable=True)

    # Toleransi keterlambatan override (null = ikut global)
    toleransi_telat_menit_override = Column(Integer, nullable=True)

    # Lembur override (null = ikut global)
    bonus_lembur_per_jam_override = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    profile = relationship("Profile", back_populates="employees")
    contracts = relationship("EmploymentContract", back_populates="employee", cascade="all, delete-orphan", order_by="EmploymentContract.contract_number.desc()")


class EmploymentContract(Base):
    """
    Riwayat Kontrak Kerja Karyawan (PKWT).
    Mendukung perpanjangan (kontrak ke-1, ke-2, dst.) dan audit histori saat karyawan diangkat jadi TETAP.
    Status:
      - ACTIVE: Kontrak berjalan
      - EXPIRED: Masa kontrak telah habis
      - PROMOTED_TO_PERMANENT: Karyawan diangkat menjadi Karyawan Tetap
      - RENEWED: Kontrak telah diperpanjang ke periode berikutnya
    """
    __tablename__ = "employment_contracts"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_number = Column(Integer, nullable=False, default=1)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE")
    keterangan = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    employee = relationship("Employee", back_populates="contracts")


class Holiday(Base):
    """Pengganti template_tanggal_merah.xlsx — daftar tanggal merah nasional."""
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True, index=True)
    tanggal = Column(Date, unique=True, nullable=False)
    keterangan = Column(String, nullable=True)


class LeaveRequest(Base):
    """
    Pengajuan Cuti / Izin Karyawan.
    Bisa dibuat manual oleh HR Master/Staff di web, atau otomatis via Bot Telegram / n8n.
    Status: PENDING, APPROVED, REJECTED
    Kategori:
      - CUTI_TAHUNAN       (full day cuti tahunan — memotong 1 hari kuota)
      - CUTI_SETENGAH_HARI (setengah hari cuti — memotong 0.5 hari kuota, kode "CS" di Excel)
      - SAKIT              (full day sakit — tidak memotong kuota cuti)
      - IZIN_PULANG_CEPAT  (izin keluar lebih awal, jam_izin = misal 14:00)
      - IZIN_TELAT         (izin datang terlambat, jam_izin = misal 09:30)
      - LAINNYA
      - WORK_FROM_LOCATION (absensi jarak jauh — karyawan bekerja di luar kantor,
        tidak ada data fingerprint, hari tsb dihitung sebagai Hari Kerja Valid jika APPROVED)
    """
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String, nullable=False, index=True)
    telegram_user_id = Column(String, nullable=True)
    whatsapp_user_id = Column(String, nullable=True)
    kategori = Column(String, nullable=False)  # CUTI_TAHUNAN, CUTI_SETENGAH_HARI, SAKIT, IZIN_PULANG_CEPAT, IZIN_TELAT, LAINNYA, WORK_FROM_LOCATION
    tanggal_mulai = Column(Date, nullable=False)
    tanggal_selesai = Column(Date, nullable=False)
    # jumlah_hari: Jumlah hari cuti yang dipakai. Biasanya (tanggal_selesai - tanggal_mulai).days + 1,
    # tapi untuk CUTI_SETENGAH_HARI nilainya 0.5. Null berarti dihitung otomatis dari rentang tanggal.
    jumlah_hari = Column(Float, nullable=True)
    jam_izin = Column(String, nullable=True)  # Format HH:MM untuk izin jam kerja
    alasan = Column(String, nullable=True)
    status = Column(String, nullable=False, default="PENDING")  # PENDING, APPROVED, REJECTED
    catatan_hr = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)

    # --- Absensi Jarak Jauh (WORK_FROM_LOCATION) ---
    # tipe_absensi: "normal" untuk cuti/izin biasa, "remote_work" untuk absensi jarak jauh
    tipe_absensi = Column(String, nullable=True, default="normal")
    # location_cabang: cabang karyawan saat absen jarak jauh (untuk filtering di website & pipeline)
    location_cabang = Column(String, nullable=True)
    # foto_bukti: path relatif foto bukti absensi jarak jauh (JPEG/PNG/dll)
    foto_bukti = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class EmployeeAdjustment(Base):
    """
    Penyesuaian tentatif per karyawan (Total Bonus Lain-lain & Total Potongan Lain-lain).
    Independen, tidak terikat ke rumus penjumlahan manapun, bisa di-edit oleh HR Master di website
    dan akan langsung dicetak pada kolom Excel Summary Overview.
    """
    __tablename__ = "employee_adjustments"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String, unique=True, nullable=False, index=True)
    bonus_lain = Column(Float, default=0.0)
    potongan_lain = Column(Float, default=0.0)
    catatan = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class AbsenManual(Base):
    """
    Jumlah hari absen manual per karyawan per periode (tahun + bulan).
    Nilai ini ditambahkan ke Absensi In, Absensi Out, Hari Kerja Valid,
    dan uang makan (jumlah hari x tarif uang makan karyawan) saat pipeline berjalan.
    Bisa diisi oleh HR Master maupun HR Staff dari halaman Proses Absensi.
    """
    __tablename__ = "absen_manual"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String, nullable=False, index=True)
    tahun = Column(Integer, nullable=False)
    bulan = Column(Integer, nullable=False)
    jumlah = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("nama", "tahun", "bulan", name="uq_absen_manual_nama_periode"),
    )


class LeaveBalanceLedger(Base):
    """
    Ledger riwayat saldo cuti tahunan per karyawan.
    Saldo aktif = SUM(amount) WHERE year=X AND employee_id=Y.

    Tipe entri (entry_type):
      - GRANT_ANNIVERSARY   : Kuota proporsional saat anniversary (setahun pertama)
      - GRANT_ANNUAL_RESET  : Kuota penuh 12 hari saat reset 1 Januari (karyawan >1 tahun)
      - USED                : Pemotongan saat cuti disetujui (amount negatif)
      - REVERSED            : Pembalikan USED saat cuti dibatalkan/ditolak (amount positif)
      - EXPIRED             : Hangus sisa saldo saat reset 1 Januari (amount negatif)

    Idempotency:
      - GRANT_ANNIVERSARY & GRANT_ANNUAL_RESET dijamin unik per (employee_id, year, entry_type)
        via unique constraint — aman dijalankan berkali-kali.
      - USED & REVERSED terikat ke leave_request_id yang spesifik.
      - EXPIRED juga dijamin unik per (employee_id, year, entry_type).
    """
    __tablename__ = "leave_balance_ledger"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    entry_type = Column(String, nullable=False)  # GRANT_ANNIVERSARY, GRANT_ANNUAL_RESET, USED, REVERSED, EXPIRED
    amount = Column(Float, nullable=False)        # positif = tambah, negatif = kurang
    leave_request_id = Column(Integer, ForeignKey("leave_requests.id", ondelete="SET NULL"), nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    employee = relationship("Employee")
    leave_request = relationship("LeaveRequest")
