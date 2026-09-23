# -*- coding: utf-8 -*-
"""
seed.py
=======
Jalankan SEKALI setelah database pertama kali dibuat:

    python seed.py

Isinya:
1. Membuat 1 akun HR Master default (email & password dari environment
   variable, atau default di bawah kalau tidak di-set).
2. Mengimpor 7 profil jadwal ASLI dari config.py lama (Office, Gudang,
   Javapetco, dst) supaya HR Master tidak mulai dari nol -- tinggal edit
   lewat website kalau mau ubah aturannya.
3. Membuat 1 baris aturan bisnis global (uang makan, potongan, dst) dengan
   nilai default yang sama seperti config.py lama.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Muat file .env dari folder backend
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

from app.database import SessionLocal, Base, engine
from app import models
from app.auth import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# ---------------------------------------------------------------------------
# 1. Akun HR Master default
# ---------------------------------------------------------------------------
DEFAULT_EMAIL = os.environ.get("SEED_HR_MASTER_EMAIL", "admin@perusahaan.com")
DEFAULT_PASSWORD = os.environ.get("SEED_HR_MASTER_PASSWORD", "ubah-password-ini")

user = db.query(models.User).filter(models.User.email == DEFAULT_EMAIL).first()
if not user:
    db.add(models.User(
        nama="HR Master",
        email=DEFAULT_EMAIL,
        hashed_password=hash_password(DEFAULT_PASSWORD),
        role=models.RoleEnum.hr_master,
    ))
    db.commit()
    print(f"[OK] Akun HR Master dibuat: {DEFAULT_EMAIL} / {DEFAULT_PASSWORD}  <-- SEGERA GANTI PASSWORD INI")
else:
    user.hashed_password = hash_password(DEFAULT_PASSWORD)
    db.commit()
    print(f"[OK] Akun {DEFAULT_EMAIL} sudah ada. Password disinkronkan dengan .env: {DEFAULT_PASSWORD}")

# ---------------------------------------------------------------------------
# 2. Import 7 profil jadwal asli dari config.py lama
# ---------------------------------------------------------------------------
PROFIL_SEED = {
    "OFFICE": dict(
        nama="Office", cabang=["BANDUNG", "BLOK A", "BLOK C"],
        hari_kerja=["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"],
        jam_masuk={"default": "08:00"},
        jam_keluar={"Sabtu": "13:00", "default": "16:00"},
        patokan_lembur={"Sabtu": "13:00", "default": "16:00"},
        ikut_telat=True, ikut_lembur=True, ikut_kuota_hari_kerja=True,
        hari_kandidat_kuota=["Senin", "Selasa", "Rabu", "Kamis", "Jumat"],
        min_hari_kerja=4, ikut_bonus_tanggal_merah=True,
    ),
    "GUDANG": dict(
        nama="Gudang", cabang=["BANDUNG", "BLOK A", "BLOK C"],
        hari_kerja=["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"],
        jam_masuk={"default": "08:00"},
        jam_keluar={"default": "16:00"},
        patokan_lembur={"default": "16:00"},
        ikut_telat=True, ikut_lembur=True, ikut_kuota_hari_kerja=True,
        hari_kandidat_kuota=["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"],
        min_hari_kerja=4, ikut_bonus_tanggal_merah=True,
    ),
    "JAVAPETCO": dict(
        nama="Toko Javapetco",
        cabang=["GREENLAKE CITY", "KEBAYORAN LAMA", "PIK", "TANJUNG DUREN", "REEF+/PIK"],
        hari_kerja=["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"],
        jam_masuk={"default": "09:00"},
        jam_keluar={"default": "19:00"},
        patokan_lembur={"default": "19:00"},
        ikut_telat=True, ikut_lembur=True, ikut_kuota_hari_kerja=True,
        hari_kandidat_kuota=["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"],
        min_hari_kerja=4, ikut_bonus_tanggal_merah=False,
    ),
    "ANAK_KONTEN_LIVE": dict(
        nama="Anak Konten Live Stream", cabang=[], hari_kerja=[],
        jam_masuk=None, jam_keluar=None, patokan_lembur=None,
        ikut_telat=False, ikut_lembur=False, ikut_kuota_hari_kerja=False,
        hari_kandidat_kuota=[], min_hari_kerja=0, ikut_bonus_tanggal_merah=True,
    ),
    "ANAK_KONTEN_MARKETING": dict(
        nama="Anak Konten Marketing", cabang=[],
        hari_kerja=["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"],
        jam_masuk={"default": "09:00"},
        jam_keluar={"Sabtu": "16:00", "default": "17:00"},
        patokan_lembur={"Sabtu": "16:00", "default": "17:00"},
        ikut_telat=True, ikut_lembur=True, ikut_kuota_hari_kerja=False,
        hari_kandidat_kuota=[], min_hari_kerja=0, ikut_bonus_tanggal_merah=True,
    ),
    "SETUP_BLOK_C": dict(
        nama="Setup Blok C (Aquarium)", cabang=["BLOK C"],
        hari_kerja=["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"],
        jam_masuk={"default": "08:00"},
        jam_keluar={"default": "16:00"},
        patokan_lembur=None,
        ikut_telat=False, ikut_lembur=False, ikut_kuota_hari_kerja=False,
        hari_kandidat_kuota=[], min_hari_kerja=0, ikut_bonus_tanggal_merah=True,
    ),
    "OFFICE_BOY": dict(
        nama="Office Boy", cabang=[], hari_kerja=[],
        jam_masuk={"default": "07:00"},
        jam_keluar={"default": "15:00"},
        patokan_lembur=None,
        ikut_telat=False, ikut_lembur=False, ikut_kuota_hari_kerja=False,
        hari_kandidat_kuota=[], min_hari_kerja=0, ikut_bonus_tanggal_merah=False,
    ),
    "DRIVER": dict(
        nama="Driver", cabang=["JAVA CIPULIR"],
        hari_kerja=["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"],
        jam_masuk={"default": "08:00"},
        jam_keluar={"default": "16:00"},
        patokan_lembur={"default": "16:00"},
        ikut_telat=False, ikut_lembur=True, ikut_kuota_hari_kerja=False,
        hari_kandidat_kuota=[], min_hari_kerja=0, ikut_bonus_tanggal_merah=True,
        lembur_khusus={
            "hanya_hari": ["Minggu"], "threshold_jam": 4,
            "tarif_per_jam": 20000, "bonus_flat": 100000,
        },
    ),
}

for code, data in PROFIL_SEED.items():
    if db.query(models.Profile).filter(models.Profile.code == code).first():
        print(f"[SKIP] Profil {code} sudah ada.")
        continue
    db.add(models.Profile(code=code, **data))
    print(f"[OK] Profil {code} ditambahkan.")

# ---------------------------------------------------------------------------
# 3. Aturan bisnis global default
# ---------------------------------------------------------------------------
if not db.query(models.BusinessRule).first():
    db.add(models.BusinessRule())  # semua kolom sudah punya default di models.py
    print("[OK] Aturan bisnis global default dibuat.")
else:
    print("[SKIP] Aturan bisnis global sudah ada.")

db.commit()
db.close()
print("\nSelesai. Jalankan server dengan: uvicorn app.main:app --reload")
