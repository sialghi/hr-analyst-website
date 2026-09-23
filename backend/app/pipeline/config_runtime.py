# -*- coding: utf-8 -*-
"""
config_runtime.py
==================
Pengganti config.py statis yang asli.

KONSEP PENTING:
Modul ini dipakai oleh loader.py / preprocessing.py / data_process.py lewat
`import config_runtime as config` lalu diakses sebagai `config.NAMA_VARIABEL`.
Karena diakses lewat atribut modul (bukan `from config import NAMA`), setiap
kali kita memanggil `reload_from_db(...)`, semua kode pipeline lain otomatis
melihat nilai TERBARU tanpa perlu restart server atau import ulang.

Nilai di bawah ini adalah DEFAULT (sama persis dengan config.py asli) yang
dipakai sebagai fallback SEBELUM database pernah diisi (mis. saat pertama
kali `seed.py` dijalankan).
"""
import datetime

# --- Aturan jam kerja normal (LEGACY fallback) ---
JAM_MASUK_STANDAR = datetime.time(8, 0)
JAM_KELUAR_STANDAR = datetime.time(16, 0)

# --- minimal hari kerja per minggu (LEGACY fallback) ---
MIN_HARI_KERJA_PER_MINGGU = 4
HARI_KERJA_TERDAFTAR = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat"]

# --- Preprocessing: dedup scan ganda ---
DEDUP_THRESHOLD_MENIT = 2

# --- Rekap alpa berulang ---
MIN_MINGGU_BERTURUT_ALPA = 2

# --- Skor Kedisiplinan (disimpan untuk kompatibilitas, tidak diedit di web ini) ---
SKOR_AWAL = 100
PENALTI_PER_TELAT = 3
PENALTI_PER_PULANG_DULUAN = 3
PENALTI_PER_MINGGU_BERMASALAH = 8
BONUS_PER_LEMBUR = 1

NAMA_HARI_ID = {
    0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis",
    4: "Jumat", 5: "Sabtu", 6: "Minggu",
}
HARI_KE_WEEKDAY = {v: k for k, v in NAMA_HARI_ID.items()}

RAW_COLUMNS = [
    "Cabang", "Nama", "ID_Mesin", "Timestamp_Raw", "Tipe_Asli_Raw",
    "Kode_Gerbang", "Kolom_Kosong", "Metode",
]

# --- Profil jadwal: akan DIISI oleh reload_from_db() dari tabel `profiles` ---
PROFIL_JADWAL = {}
PROFIL_DEFAULT = "OFFICE"

# --- Uang Makan & potongan (akan DIISI oleh reload_from_db() dari tabel `business_rules`) ---
UANG_MAKAN_DEFAULT = 100_000
POTONGAN_TELAT_SEDIKIT = 10_000
POTONGAN_TELAT_BANYAK_PERSEN = 0.5
BATAS_TELAT_RINGAN = datetime.time(12, 0)
BATAS_TELAT_BERAT = datetime.time(15, 0)

POTONGAN_PULANG_DULUAN_SEDIKIT = 10_000
POTONGAN_PULANG_DULUAN_BANYAK_PERSEN = 0.5
BATAS_PULANG_DULUAN_RINGAN = datetime.time(15, 0)
BATAS_PULANG_DULUAN_BERAT = datetime.time(16, 0)

BONUS_LEMBUR_PER_JAM = 10_000
MENIT_PEMBULATAN_LEMBUR = 31

TOLERANSI_TELAT_HARI_KE = 1
TOLERANSI_TELAT_MAX_MENIT = 10


def get_jam_profil(profil_dict, key, nama_hari):
    """Ambil jam dari profil berdasarkan key dan nama hari. (unchanged logic)"""
    jam_map = profil_dict.get(key)
    if jam_map is None:
        return None
    if isinstance(jam_map, dict):
        return jam_map.get(nama_hari, jam_map.get("default"))
    return jam_map


def normalisasi_nama(nama):
    """Normalisasi nama karyawan: strip whitespace + lowercase."""
    if nama is None:
        return ""
    return str(nama).strip().lower()


def _parse_time(value):
    """Terima 'HH:MM' (str) atau datetime.time atau None -> datetime.time atau None."""
    if value is None:
        return None
    if isinstance(value, datetime.time):
        return value
    if isinstance(value, str):
        h, m = value.split(":")
        return datetime.time(int(h), int(m))
    raise ValueError(f"Format jam tidak dikenali: {value!r}")


def _jam_map_from_json(raw):
    """
    raw: None, atau dict {"default": "08:00", "Sabtu": "13:00", ...} (dari DB/JSON)
    -> dict {"default": time(8,0), "Sabtu": time(13,0), ...} atau None
    """
    if raw is None:
        return None
    return {k: _parse_time(v) for k, v in raw.items()}


def _profile_row_to_dict(p):
    """Konversi 1 row model Profile (SQLAlchemy) -> dict format PROFIL_JADWAL[...] asli."""
    lembur_khusus = None
    if p.lembur_khusus:
        lk = p.lembur_khusus
        lembur_khusus = {
            "hanya_hari": lk.get("hanya_hari", []),
            "threshold_jam": lk.get("threshold_jam"),
            "tarif_per_jam": lk.get("tarif_per_jam"),
            "bonus_flat": lk.get("bonus_flat"),
        }
    return {
        "nama": p.nama,
        "cabang": p.cabang or [],
        "hari_kerja": p.hari_kerja or [],
        "jam_masuk": _jam_map_from_json(p.jam_masuk),
        "jam_keluar": _jam_map_from_json(p.jam_keluar),
        "patokan_lembur": _jam_map_from_json(p.patokan_lembur),
        "ikut_telat": p.ikut_telat,
        "ikut_lembur": p.ikut_lembur,
        "ikut_kuota_hari_kerja": p.ikut_kuota_hari_kerja,
        "hari_kandidat_kuota": p.hari_kandidat_kuota or [],
        "min_hari_kerja": p.min_hari_kerja,
        "ikut_bonus_tanggal_merah": p.ikut_bonus_tanggal_merah,
        **({"lembur_khusus": lembur_khusus} if lembur_khusus else {}),
    }


def reload_from_db(db):
    """
    Baca semua profil (tabel `profiles`) dan aturan global (tabel `business_rule`,
    1 baris singleton) dari database, lalu timpa semua variabel modul ini.

    Dipanggil di AWAL setiap kali pipeline mau dijalankan (upload manual ATAUPUN
    lewat endpoint n8n), jadi perubahan yang disimpan HR Master lewat web SELALU
    langsung terpakai tanpa perlu restart server.
    """
    global PROFIL_JADWAL, PROFIL_DEFAULT
    global UANG_MAKAN_DEFAULT, POTONGAN_TELAT_SEDIKIT, POTONGAN_TELAT_BANYAK_PERSEN
    global BATAS_TELAT_RINGAN, BATAS_TELAT_BERAT
    global POTONGAN_PULANG_DULUAN_SEDIKIT, POTONGAN_PULANG_DULUAN_BANYAK_PERSEN
    global BATAS_PULANG_DULUAN_RINGAN, BATAS_PULANG_DULUAN_BERAT
    global BONUS_LEMBUR_PER_JAM, MENIT_PEMBULATAN_LEMBUR
    global TOLERANSI_TELAT_HARI_KE, TOLERANSI_TELAT_MAX_MENIT
    global DEDUP_THRESHOLD_MENIT, MIN_HARI_KERJA_PER_MINGGU, MIN_MINGGU_BERTURUT_ALPA
    global JAM_MASUK_STANDAR, JAM_KELUAR_STANDAR

    # Import di dalam fungsi supaya tidak circular-import dengan models.py
    from .. import models

    profil_rows = db.query(models.Profile).all()
    PROFIL_JADWAL = {p.code: _profile_row_to_dict(p) for p in profil_rows}

    rule = db.query(models.BusinessRule).first()
    if rule is not None:
        PROFIL_DEFAULT = rule.profil_default
        UANG_MAKAN_DEFAULT = rule.uang_makan_default
        POTONGAN_TELAT_SEDIKIT = rule.potongan_telat_sedikit
        POTONGAN_TELAT_BANYAK_PERSEN = rule.potongan_telat_banyak_persen
        BATAS_TELAT_RINGAN = _parse_time(rule.batas_telat_ringan)
        BATAS_TELAT_BERAT = _parse_time(rule.batas_telat_berat)
        POTONGAN_PULANG_DULUAN_SEDIKIT = rule.potongan_pulang_duluan_sedikit
        POTONGAN_PULANG_DULUAN_BANYAK_PERSEN = rule.potongan_pulang_duluan_banyak_persen
        BATAS_PULANG_DULUAN_RINGAN = _parse_time(rule.batas_pulang_duluan_ringan)
        BATAS_PULANG_DULUAN_BERAT = _parse_time(rule.batas_pulang_duluan_berat)
        BONUS_LEMBUR_PER_JAM = rule.bonus_lembur_per_jam
        MENIT_PEMBULATAN_LEMBUR = rule.menit_pembulatan_lembur
        TOLERANSI_TELAT_HARI_KE = rule.toleransi_telat_hari_ke
        TOLERANSI_TELAT_MAX_MENIT = rule.toleransi_telat_max_menit
        DEDUP_THRESHOLD_MENIT = rule.dedup_threshold_menit
        MIN_HARI_KERJA_PER_MINGGU = rule.min_hari_kerja_per_minggu
        MIN_MINGGU_BERTURUT_ALPA = rule.min_minggu_berturut_alpa
        JAM_MASUK_STANDAR = _parse_time(rule.jam_masuk_standar)
        JAM_KELUAR_STANDAR = _parse_time(rule.jam_keluar_standar)
