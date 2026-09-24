# -*- coding: utf-8 -*-
"""
data_process.py
================
Implementasi Bagian 3.3 di rencana. Semua fungsi di sini HANYA memproses
baris berstatus "Lengkap" dari hasil preprocessing (Aturan #11).

REVISI v2: Semua fungsi diparametrize per profil. Ditambah:
- hitung_uang_makan(): potongan telat + bonus tanggal merah
- hitung_bonus_lembur_rupiah(): bonus lembur dalam Rp
- hitung_rekap_profil_exclude(): rekap kehadiran untuk profil non-logic-utama
"""
import pandas as pd
import datetime
from . import config_runtime as config


def _durasi_ke_jam_desimal(td):
    return round(td.total_seconds() / 3600, 2)


def _get_profil_info(row):
    """Ambil dict profil dari config.PROFIL_JADWAL berdasarkan kolom 'Profil' di row."""
    kode = row.get("Profil", config.PROFIL_DEFAULT)
    return config.PROFIL_JADWAL.get(kode, config.PROFIL_JADWAL[config.PROFIL_DEFAULT])


def _format_durasi_teks(jam_desimal):
    menit_total = int(round(jam_desimal * 60))
    jam = menit_total // 60
    menit = menit_total % 60
    if jam > 0 and menit > 0:
        return f"{jam} jam {menit} menit"
    elif jam > 0:
        return f"{jam} jam"
    else:
        return f"{menit} menit"


def _find_approved_leave(nama, tgl, approved_leaves_dict, kategori_filter=None):
    """
    Cek apakah karyawan punya permohonan cuti / izin yang APPROVED pada tanggal tgl.
    kategori_filter: bisa berupa set/tuple/list string kategori (misal {'CUTI_TAHUNAN', 'SAKIT'}) atau string tunggal.
    """
    if not approved_leaves_dict:
        return None
    norm_name = config.normalisasi_nama(nama)
    daftar = approved_leaves_dict.get(norm_name, [])
    if not daftar:
        return None

    tgl_eval = tgl.date() if isinstance(tgl, datetime.datetime) else tgl

    for item in daftar:
        t_mulai = item["tanggal_mulai"]
        t_selesai = item["tanggal_selesai"]
        if t_mulai <= tgl_eval <= t_selesai:
            kat = item["kategori"]
            if kategori_filter:
                if isinstance(kategori_filter, (set, list, tuple)):
                    if kat in kategori_filter:
                        return item
                elif kat == kategori_filter:
                    return item
            else:
                return item
    return None


def hitung_telat(df_lengkap, approved_leaves=None):
    """
    Aturan #6 & #3.3.3 — REVISI v2: patokan jam masuk per profil.
    Hanya proses karyawan yang profilnya ikut_telat=True.

    REVISI v3: Toleransi keterlambatan 1x per periode.
    Kejadian telat pertama (ke-1) dengan durasi <= config.TOLERANSI_TELAT_MAX_MENIT (10 menit)
    diberikan toleransi (bebas denda).
    Jika telat ke-1 > 10 menit atau telat ke-2 dst -> langsung kena denda normal.

    REVISI v4 (Fitur Cuti & Izin):
    Jika karyawan memiliki pengajuan 'IZIN_TELAT' yang berstatus APPROVED untuk tanggal ini,
    maka keterlambatan DIEXEMPT (Ditoleransi dengan Izin Resmi - Bebas Denda Potongan Rp 0).
    """
    df = df_lengkap.copy()

    # Filter hanya profil yang ikut telat
    df = df[df["Profil"].apply(lambda p: config.PROFIL_JADWAL.get(p, config.PROFIL_JADWAL[config.PROFIL_DEFAULT])["ikut_telat"])]
    if df.empty:
        return pd.DataFrame(columns=[
            "Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Masuk", "Jam_Masuk_Standar",
            "Durasi_Telat_Jam", "Durasi_Telat_Format", "Kejadian_Ke", "Status_Toleransi", "Potongan_Telat_Rp"
        ])

    # Urutkan kronologis agar tracking kejadian telat ke-1, ke-2 akurat
    df = df.sort_values(by=["Nama", "Tanggal", "Jam_Masuk"]).reset_index(drop=True)

    telat_ke_per_nama = {}
    hasil_rows = []
    for idx, row in df.iterrows():
        profil = _get_profil_info(row)
        nama_hari = row["Hari"]
        jam_masuk_std = config.get_jam_profil(profil, "jam_masuk", nama_hari)

        if jam_masuk_std is None:
            continue  # profil tanpa jam masuk baku

        if row["Jam_Masuk"] > jam_masuk_std:
            nama_karyawan = row["Nama"]
            tanggal = row["Tanggal"]

            # Cek apakah ada izin telat resmi yang APPROVED
            izin_resmi = _find_approved_leave(nama_karyawan, tanggal, approved_leaves, kategori_filter="IZIN_TELAT")

            telat_ke_per_nama[nama_karyawan] = telat_ke_per_nama.get(nama_karyawan, 0) + 1
            ke = telat_ke_per_nama[nama_karyawan]

            jam_masuk_dt = datetime.datetime.combine(tanggal, row["Jam_Masuk"])
            batas_dt = datetime.datetime.combine(tanggal, jam_masuk_std)
            durasi_sec = (jam_masuk_dt - batas_dt).total_seconds()
            durasi = _durasi_ke_jam_desimal(jam_masuk_dt - batas_dt)
            menit_telat = durasi_sec / 60

            if izin_resmi:
                status_toleransi = f"Izin Resmi Disetujui ({izin_resmi.get('alasan') or 'Izin Datang Terlambat'}) - Bebas Denda"
                potongan = 0
            else:
                is_toleransi = (ke == config.TOLERANSI_TELAT_HARI_KE and menit_telat <= config.TOLERANSI_TELAT_MAX_MENIT)
                if is_toleransi:
                    status_toleransi = f"Ditoleransi (Telat ke-1 <= {config.TOLERANSI_TELAT_MAX_MENIT} m - Bebas Denda)"
                    potongan = 0
                else:
                    if ke == 1:
                        status_toleransi = f"Telat ke-1 > {config.TOLERANSI_TELAT_MAX_MENIT} m (Kena Denda)"
                    else:
                        status_toleransi = f"Telat ke-{ke} (Kena Denda)"

                    if row["Jam_Masuk"] <= config.BATAS_TELAT_RINGAN:
                        potongan = config.POTONGAN_TELAT_SEDIKIT
                    else:
                        potongan = config.POTONGAN_TELAT_SEDIKIT

            hasil_rows.append({
                "Cabang": row["Cabang"],
                "Nama": row["Nama"],
                "Profil": row["Profil"],
                "Tanggal": tanggal,
                "Hari": nama_hari,
                "Jam_Masuk": row["Jam_Masuk"],
                "Jam_Masuk_Standar": jam_masuk_std,
                "Durasi_Telat_Jam": durasi,
                "Durasi_Telat_Format": _format_durasi_teks(durasi),
                "Kejadian_Ke": ke,
                "Status_Toleransi": status_toleransi,
                "Potongan_Telat_Rp": potongan,
            })

    return pd.DataFrame(hasil_rows).reset_index(drop=True) if hasil_rows else pd.DataFrame(columns=[
        "Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Masuk", "Jam_Masuk_Standar",

        "Durasi_Telat_Jam", "Durasi_Telat_Format", "Kejadian_Ke", "Status_Toleransi", "Potongan_Telat_Rp"
    ])


def _hitung_jam_lembur_bulat(jam_keluar, jam_standar, tanggal):
    """
    Hitung jam lembur dengan pembulatan sesuai rumus:
      menit_lewat = (jam_keluar - jam_pulang_standar) dalam menit
      jam_penuh   = menit_lewat // 60
      sisa_menit  = menit_lewat % 60
      jam_lembur  = jam_penuh + (1 jika sisa_menit >= 31, else 0)
    """
    dt_keluar = datetime.datetime.combine(tanggal, jam_keluar)
    dt_standar = datetime.datetime.combine(tanggal, jam_standar)
    menit_lewat = int((dt_keluar - dt_standar).total_seconds() / 60)
    if menit_lewat <= 0:
        return 0, 0.0
    jam_penuh = menit_lewat // 60
    sisa_menit = menit_lewat % 60
    jam_lembur = jam_penuh + (1 if sisa_menit >= config.MENIT_PEMBULATAN_LEMBUR else 0)
    durasi_desimal = round(menit_lewat / 60, 2)
    return jam_lembur, durasi_desimal


def hitung_lembur(df_lengkap, tanggal_merah=None):
    """
    Aturan #4 & #3.3.1 — REVISI v2: patokan lembur per profil + bonus Rp.
    Hanya proses karyawan yang profilnya ikut_lembur=True.

    REVISI v3: Profil dengan field 'lembur_khusus' (mis. DRIVER) mendapat
    aturan lembur threshold yang HANYA berlaku di hari Minggu / tanggal merah:
    - Durasi lembur dihitung dari Clock In (Jam_Masuk) hingga Pulang (Jam_Keluar).
    - Jam Standar dikosongkan (None).
    - Ambang batas: < 4 jam = jam × Rp20.000, >= 4 jam = flat Rp100.000.
    Di hari biasa (Senin-Sabtu, bukan tanggal merah), pakai skema default (dari patokan_lembur).
    """
    if tanggal_merah is None:
        tanggal_merah = {}

    df = df_lengkap.copy()
    df = df[df["Profil"].apply(lambda p: config.PROFIL_JADWAL.get(p, config.PROFIL_JADWAL[config.PROFIL_DEFAULT])["ikut_lembur"])]
    if df.empty:
        return pd.DataFrame(columns=[
            "Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Keluar", "Jam_Keluar_Standar",
            "Durasi_Lembur_Jam", "Durasi_Lembur_Format", "Jam_Lembur_Bulat", "Bonus_Lembur_Rp"
        ])

    hasil_rows = []
    for idx, row in df.iterrows():
        profil = _get_profil_info(row)
        nama_hari = row["Hari"]
        tanggal = row["Tanggal"]
        is_tanggal_merah = tanggal in tanggal_merah
        lembur_khusus = profil.get("lembur_khusus")

        # Cek apakah hari ini berlaku aturan lembur khusus (Minggu atau Tanggal Merah)
        hari_khusus_qualify = False
        if lembur_khusus:
            hari_khusus_qualify = (nama_hari in lembur_khusus.get("hanya_hari", [])) or is_tanggal_merah

        if hari_khusus_qualify:
            # === LEMBUR KHUSUS (DRIVER pada Minggu / Tanggal Merah) ===
            # Durasi dihitung dari Clock In (Jam_Masuk) hingga Pulang (Jam_Keluar)
            # Jam Standar dikosongkan (None)
            if pd.isna(row.get("Jam_Masuk")) or pd.isna(row.get("Jam_Keluar")):
                continue

            dt_masuk = datetime.datetime.combine(tanggal, row["Jam_Masuk"])
            dt_keluar = datetime.datetime.combine(tanggal, row["Jam_Keluar"])
            menit_total = int((dt_keluar - dt_masuk).total_seconds() / 60)
            if menit_total <= 0:
                continue

            jam_penuh = menit_total // 60
            sisa_menit = menit_total % 60
            jam_lembur_bulat = jam_penuh + (1 if sisa_menit >= config.MENIT_PEMBULATAN_LEMBUR else 0)
            durasi_desimal = round(menit_total / 60, 2)

            threshold = lembur_khusus.get("threshold_jam", 4)
            if jam_lembur_bulat >= threshold:
                bonus_rp = lembur_khusus.get("bonus_flat", 100_000)
            else:
                bonus_rp = jam_lembur_bulat * lembur_khusus.get("tarif_per_jam", 20_000)

            hasil_rows.append({
                "Cabang": row["Cabang"],
                "Nama": row["Nama"],
                "Profil": row["Profil"],
                "Tanggal": tanggal,
                "Hari": nama_hari,
                "Jam_Keluar": row["Jam_Keluar"],
                "Jam_Keluar_Standar": None,  # Jam standar dikosongkan untuk hari Minggu / tanggal merah
                "Durasi_Lembur_Jam": durasi_desimal,
                "Durasi_Lembur_Format": _format_durasi_teks(durasi_desimal),
                "Jam_Lembur_Bulat": jam_lembur_bulat,
                "Bonus_Lembur_Rp": bonus_rp,
            })
        else:
            # === LEMBUR BIASA (Profil standar, atau DRIVER pada Senin-Sabtu biasa) ===
            patokan = config.get_jam_profil(profil, "patokan_lembur", nama_hari)
            if patokan is None:
                continue

            if row["Jam_Keluar"] > patokan:
                jam_lembur_bulat, durasi_desimal = _hitung_jam_lembur_bulat(
                    row["Jam_Keluar"], patokan, tanggal
                )
                bonus_rp = jam_lembur_bulat * config.BONUS_LEMBUR_PER_JAM
                hasil_rows.append({
                    "Cabang": row["Cabang"],
                    "Nama": row["Nama"],
                    "Profil": row["Profil"],
                    "Tanggal": tanggal,
                    "Hari": nama_hari,
                    "Jam_Keluar": row["Jam_Keluar"],
                    "Jam_Keluar_Standar": patokan,
                    "Durasi_Lembur_Jam": durasi_desimal,
                    "Durasi_Lembur_Format": _format_durasi_teks(durasi_desimal),
                    "Jam_Lembur_Bulat": jam_lembur_bulat,
                    "Bonus_Lembur_Rp": bonus_rp,
                })

    return pd.DataFrame(hasil_rows).reset_index(drop=True) if hasil_rows else pd.DataFrame(columns=[
        "Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Keluar", 
        "Jam_Keluar_Standar", "Durasi_Lembur_Jam", "Durasi_Lembur_Format", "Jam_Lembur_Bulat", "Bonus_Lembur_Rp"
    ])


def hitung_pulang_duluan(df_lengkap, approved_leaves=None):
    """
    Aturan #5 & #3.3.2 — REVISI v2: patokan jam keluar per profil.
    Hanya proses karyawan yang profilnya ikut_telat=True (profil dengan
    jam kerja baku).

    REVISI v3 (Fitur Cuti & Izin):
    Jika karyawan memiliki pengajuan 'IZIN_PULANG_CEPAT' yang APPROVED untuk tanggal ini,
    maka kepulangan lebih awal tidak dicatat sebagai anomali pelanggaran (dianulir).
    """
    df = df_lengkap.copy()
    # Pakai ikut_telat sebagai proxy: kalau profil punya jam baku, ikut perhitungan pulang duluan
    df = df[df["Profil"].apply(lambda p: config.PROFIL_JADWAL.get(p, config.PROFIL_JADWAL[config.PROFIL_DEFAULT])["ikut_telat"])]
    if df.empty:
        return pd.DataFrame(columns=[
            "Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Keluar", "Jam_Keluar_Standar", "Durasi_Kurang_Jam", "Durasi_Kurang_Format"
        ])

    hasil_rows = []
    for idx, row in df.iterrows():
        profil = _get_profil_info(row)
        nama_hari = row["Hari"]
        jam_keluar_std = config.get_jam_profil(profil, "jam_keluar", nama_hari)

        if jam_keluar_std is None:
            continue

        if row["Jam_Keluar"] < jam_keluar_std:
            nama_karyawan = row["Nama"]
            tanggal = row["Tanggal"]

            # Cek apakah ada izin pulang cepat resmi yang APPROVED
            izin_resmi = _find_approved_leave(nama_karyawan, tanggal, approved_leaves, kategori_filter="IZIN_PULANG_CEPAT")
            if izin_resmi:
                continue  # Dilewati / dianulir dari rekap pelanggaran pulang duluan

            dt_keluar = datetime.datetime.combine(tanggal, row["Jam_Keluar"])
            dt_batas = datetime.datetime.combine(tanggal, jam_keluar_std)
            durasi = _durasi_ke_jam_desimal(dt_batas - dt_keluar)
            hasil_rows.append({
                "Cabang": row["Cabang"],
                "Nama": nama_karyawan,
                "Profil": row["Profil"],
                "Tanggal": tanggal,
                "Hari": nama_hari,
                "Jam_Keluar": row["Jam_Keluar"],
                "Jam_Keluar_Standar": jam_keluar_std,
                "Durasi_Kurang_Jam": durasi,
                "Durasi_Kurang_Format": _format_durasi_teks(durasi),
            })

    return pd.DataFrame(hasil_rows).reset_index(drop=True) if hasil_rows else pd.DataFrame(columns=[
        "Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Keluar", "Jam_Keluar_Standar", "Durasi_Kurang_Jam", "Durasi_Kurang_Format"
    ])



def hitung_uang_makan(df_lengkap, master_dict=None, tanggal_merah=None, approved_leaves=None):
    """
    BARU v2: Hitung uang makan per karyawan per hari.

    Aturan:
    - Hari kerja biasa: uang makan = Rp100.000 (atau override dari master)
    - Potongan telat (hanya untuk profil ikut_telat, hanya di hari kerja biasa):
      * Jam masuk ≤ 12:00 → potongan Rp10.000
      * Jam masuk 12:00-15:00 → potongan 50% uang makan
    - Potongan pulang duluan (hanya untuk profil ikut_telat, hanya di hari kerja biasa):
      * Pulang < 15:00 → potongan 50% uang makan
      * Pulang 15:00 - sebelum 16:00 → potongan Rp10.000
    - Tanggal merah (profil ikut_bonus_tanggal_merah, scan lengkap):
      * Karyawan yang MASUK hanya dapat bonus Rp100.000 (tidak dapat base uang makan
        karena tanggal merah bukan hari kerja biasa)
    - Fitur Cuti & Izin (REVISI v3):
      * Jika ada IZIN_TELAT (APPROVED), potongan telat = 0.
      * Jika ada IZIN_PULANG_CEPAT (APPROVED), potongan pulang duluan = 0.

    Return DataFrame: Nama, Profil, Tanggal, Hari, Uang_Makan_Base,
                       Potongan_Telat, Potongan_Pulang_Duluan, Bonus_Tanggal_Merah, Total_Uang_Makan
    """
    if master_dict is None:
        master_dict = {}
    if tanggal_merah is None:
        tanggal_merah = {}

    hasil_rows = []
    # Urutkan berdasarkan Nama dan Tanggal agar tracking kronologis telat ke-1, ke-2 benar
    df_sorted = df_lengkap.sort_values(by=["Nama", "Tanggal", "Jam_Masuk"]).reset_index(drop=True)
    telat_count_per_nama = {}

    for _, row in df_sorted.iterrows():
        profil_kode = row.get("Profil", config.PROFIL_DEFAULT)
        profil = config.PROFIL_JADWAL.get(profil_kode, config.PROFIL_JADWAL[config.PROFIL_DEFAULT])
        nama_hari = row["Hari"]

        # Uang makan base (dari master override atau default)
        nama_n = config.normalisasi_nama(row["Nama"])
        info_master = master_dict.get(nama_n, {})
        uang_makan_nominal = info_master.get("Uang_Makan", config.UANG_MAKAN_DEFAULT)
        status_raw = str(info_master.get("Status_Raw", "")).lower()
        cabang_raw = str(row.get("Cabang", "")).lower()
        is_idd = "idd" in status_raw or "idd" in cabang_raw

        tgl = row["Tanggal"]
        is_tanggal_merah = tgl in tanggal_merah

        # --- Logika tanggal merah vs hari biasa ---
        if is_tanggal_merah and is_idd:
            # Khusus Toko IDD (PIK): kalau tanggal merah dikali 2 uang makan (base + bonus = 2x)
            # Tanpa potongan telat / pulang duluan
            uang_base = uang_makan_nominal
            potongan = 0
            potongan_pulang = 0
            bonus_merah = uang_makan_nominal  # Total Uang Makan = 2 × uang_makan_nominal
        elif is_tanggal_merah and profil["ikut_bonus_tanggal_merah"]:
            # Tanggal merah: TIDAK dapat base uang makan (bukan hari kerja biasa)
            # Hanya dapat bonus karena masuk di hari libur → total = 100k
            uang_base = 0
            potongan = 0  # Tidak ada potongan telat di tanggal merah
            potongan_pulang = 0  # Tidak ada potongan pulang duluan di tanggal merah
            bonus_merah = uang_makan_nominal
        else:
            # Hari kerja biasa: dapat base uang makan seperti biasa (toko non-IDD di tanggal merah juga masuk sini)
            uang_base = uang_makan_nominal
            bonus_merah = 0

            # Cek izin resmi approved untuk tanggal ini
            izin_telat_resmi = _find_approved_leave(row["Nama"], tgl, approved_leaves, kategori_filter="IZIN_TELAT")
            izin_pulang_resmi = _find_approved_leave(row["Nama"], tgl, approved_leaves, kategori_filter="IZIN_PULANG_CEPAT")

            # --- Potongan telat (hanya di hari kerja biasa) ---
            potongan = 0
            if profil["ikut_telat"]:
                jam_masuk_std = config.get_jam_profil(profil, "jam_masuk", nama_hari)
                if jam_masuk_std and row["Jam_Masuk"] > jam_masuk_std:
                    nama_karyawan = row["Nama"]
                    telat_count_per_nama[nama_karyawan] = telat_count_per_nama.get(nama_karyawan, 0) + 1
                    ke = telat_count_per_nama[nama_karyawan]

                    if izin_telat_resmi:
                        # Bebas potongan jika ada izin telat resmi yang disetujui
                        potongan = 0
                    else:
                        # Hitung durasi menit keterlambatan
                        jam_masuk_dt = datetime.datetime.combine(tgl, row["Jam_Masuk"])
                        batas_dt = datetime.datetime.combine(tgl, jam_masuk_std)
                        menit_telat = (jam_masuk_dt - batas_dt).total_seconds() / 60

                        # Cek toleransi keterlambatan: 1x per periode, max 10 menit untuk telat pertama
                        if ke == config.TOLERANSI_TELAT_HARI_KE and menit_telat <= config.TOLERANSI_TELAT_MAX_MENIT:
                            potongan = 0  # Ditoleransi, bebas potongan
                        else:
                            # Karyawan telat kena potongan
                            if row["Jam_Masuk"] <= config.BATAS_TELAT_RINGAN:
                                # Telat ringan: 00:01 - jam 12:00
                                potongan = config.POTONGAN_TELAT_SEDIKIT
                            elif row["Jam_Masuk"] <= config.BATAS_TELAT_BERAT:
                                # Telat berat: 12:00 - 15:00
                                potongan = int(uang_base * config.POTONGAN_TELAT_BANYAK_PERSEN)

            # --- Potongan pulang duluan (hanya di hari kerja biasa) ---
            potongan_pulang = 0
            if profil["ikut_telat"]:  # pakai ikut_telat sebagai proxy profil jam baku
                jam_keluar_std = config.get_jam_profil(profil, "jam_keluar", nama_hari)
                if jam_keluar_std and row["Jam_Keluar"] < jam_keluar_std:
                    if izin_pulang_resmi:
                        # Bebas potongan jika ada izin pulang cepat resmi yang disetujui
                        potongan_pulang = 0
                    else:
                        # Karyawan pulang duluan — hitung besaran potongan
                        if row["Jam_Keluar"] < config.BATAS_PULANG_DULUAN_RINGAN:
                            # Pulang sebelum 15:00 → potongan 50%
                            potongan_pulang = int(uang_base * config.POTONGAN_PULANG_DULUAN_BANYAK_PERSEN)
                        elif row["Jam_Keluar"] < config.BATAS_PULANG_DULUAN_BERAT:
                            # Pulang 15:00 - sebelum 16:00 → potongan Rp10.000
                            potongan_pulang = config.POTONGAN_PULANG_DULUAN_SEDIKIT

        total = uang_base - potongan - potongan_pulang + bonus_merah

        hasil_rows.append({
            "Cabang": row["Cabang"],
            "Nama": row["Nama"],
            "Profil": profil_kode,
            "Tanggal": tgl,
            "Hari": nama_hari,
            "Uang_Makan_Base": uang_base,
            "Potongan_Telat": potongan,
            "Potongan_Pulang_Duluan": potongan_pulang,
            "Bonus_Tanggal_Merah": bonus_merah,
            "Total_Uang_Makan": total,
        })

    if not hasil_rows:
        return pd.DataFrame(columns=[
            "Cabang", "Nama", "Profil", "Tanggal", "Hari",
            "Uang_Makan_Base", "Potongan_Telat", "Potongan_Pulang_Duluan",
            "Bonus_Tanggal_Merah", "Total_Uang_Makan"
        ])

    return pd.DataFrame(hasil_rows).reset_index(drop=True)


def _label_minggu(tanggal, hari_terakhir_offset=4):
    """Label minggu 'DD-DD Bulan YYYY' berbasis minggu kalender.

    hari_terakhir_offset: 4 = Jumat (default, Senin-Jumat),
                          6 = Minggu (full week, Senin-Minggu).
    """
    d = pd.Timestamp(tanggal)
    senin = d - pd.Timedelta(days=d.weekday())
    hari_akhir = senin + pd.Timedelta(days=hari_terakhir_offset)
    bulan_id = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
                "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
    if senin.month == hari_akhir.month:
        label = f"{senin.day}-{hari_akhir.day} {bulan_id[hari_akhir.month-1]} {hari_akhir.year}"
    else:
        label = (f"{senin.day} {bulan_id[senin.month-1]}-"
                 f"{hari_akhir.day} {bulan_id[hari_akhir.month-1]} {hari_akhir.year}")
    return label, senin.date()


def hitung_rekap_tidak_masuk(df_preprocessing_semua, approved_leaves=None):
    """
    Aturan #2, #3, #3.3.4 — REVISI v2: hari kandidat dan kuota diambil dari
    profil. Hanya proses karyawan dengan ikut_kuota_hari_kerja=True.

    df_preprocessing_semua: hasil agregasi harian SEBELUM filter #11 (perlu
    tahu Status_Data utk membedakan Lengkap vs Tidak Lengkap vs tidak ada
    scan sama sekali).

    REVISI v3 (Fitur Cuti & Izin):
    Jika karyawan memiliki pengajuan cuti resmi (CUTI_TAHUNAN, SAKIT, LAINNYA) yang APPROVED
    pada hari kerja kandidat, hari tersebut dihitung sebagai hari valid (tidak alpa),
    sehingga kuota hari kerja terpenuhi dan tidak masuk rekap alpa/tidak masuk tanpa izin.

    Return kolom termasuk '_senin_minggu' (tanggal Senin asli, dipakai utk
    deteksi "berturut-turut" di hitung_rekap_alpa_berulang) - kolom ini
    disembunyikan sebelum ditulis ke Excel.
    """
    df = df_preprocessing_semua.copy()
    df["Tanggal"] = pd.to_datetime(df["Tanggal"])

    hasil_rows = []
    # proses per Nama (Aturan #9: identitas = Nama saja)
    for nama, grup_nama in df.groupby("Nama"):
        profil_kode = grup_nama["Profil"].iloc[0] if "Profil" in grup_nama.columns else config.PROFIL_DEFAULT
        profil = config.PROFIL_JADWAL.get(profil_kode, config.PROFIL_JADWAL[config.PROFIL_DEFAULT])

        # Skip profil yang tidak ikut kuota hari kerja
        if not profil["ikut_kuota_hari_kerja"]:
            continue

        hari_kandidat = profil.get("hari_kandidat_kuota", config.HARI_KERJA_TERDAFTAR)
        min_hari = profil.get("min_hari_kerja", config.MIN_HARI_KERJA_PER_MINGGU)

        if not hari_kandidat or min_hari <= 0:
            continue

        # Konversi hari kandidat ke weekday numbers
        weekday_kandidat = [config.HARI_KE_WEEKDAY[h] for h in hari_kandidat if h in config.HARI_KE_WEEKDAY]

        # Tentukan offset hari terakhir untuk label minggu:
        # Jika hari kandidat mencakup Minggu (weekday 6) → full week (Senin-Minggu)
        # Jika hanya sampai Sabtu (weekday 5) → Senin-Sabtu
        # Default → Senin-Jumat
        if weekday_kandidat:
            hari_terakhir_offset = max(weekday_kandidat)
        else:
            hari_terakhir_offset = 4  # default Jumat

        hanya_kandidat = grup_nama[
            grup_nama["Tanggal"].dt.weekday.isin(weekday_kandidat)
        ].copy()

        if hanya_kandidat.empty:
            continue

        hanya_kandidat["Label_Minggu"], hanya_kandidat["Senin_Minggu"] = zip(
            *hanya_kandidat["Tanggal"].apply(lambda t: _label_minggu(t, hari_terakhir_offset))
        )

        for (label_minggu, senin_minggu), grup_minggu in hanya_kandidat.groupby(
            ["Label_Minggu", "Senin_Minggu"]
        ):
            hari_lengkap = grup_minggu[grup_minggu["Status_Data"] == "Lengkap"]
            tanggal_lengkap_set = set(hari_lengkap["Tanggal"].dt.date.unique())

            cabang_dominan = grup_minggu["Cabang"].value_counts().idxmax()
            tanggal_senin = pd.Timestamp(senin_minggu)
            hari_tidak_masuk = []
            keterangan_detail = []
            hari_cuti_resmi = 0
            
            bulan_id = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
                        "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
                        
            for nama_hari_k in hari_kandidat:
                offset = config.HARI_KE_WEEKDAY.get(nama_hari_k, -1)
                if offset < 0:
                    continue
                tgl_hari_itu = (tanggal_senin + pd.Timedelta(days=offset)).date()
                
                format_tgl = f"{tgl_hari_itu.day} {bulan_id[tgl_hari_itu.month - 1]}"
                nama_hari_tgl = f"{nama_hari_k} ({format_tgl})"
                
                # Cek apakah tanggal ini ada scan lengkap
                if tgl_hari_itu in tanggal_lengkap_set:
                    continue

                # Cek apakah karyawan memiliki cuti/sakit/izin resmi yang disetujui (APPROVED)
                cuti_resmi = _find_approved_leave(nama, tgl_hari_itu, approved_leaves, kategori_filter={"CUTI_TAHUNAN", "SAKIT", "LAINNYA"})
                if cuti_resmi:
                    hari_cuti_resmi += 1
                    continue  # Hari ini diakui sebagai cuti/izin resmi berizin, tidak dihitung alpa/tidak masuk

                # Jika tidak ada cuti resmi dan scan tidak lengkap / tidak ada
                baris_hari_itu = grup_minggu[grup_minggu["Tanggal"].dt.date == tgl_hari_itu]
                if baris_hari_itu.empty:
                    hari_tidak_masuk.append(nama_hari_tgl)
                else:
                    status = baris_hari_itu.iloc[0]["Status_Data"]
                    if status != "Lengkap":
                        hari_tidak_masuk.append(f"{nama_hari_tgl}*")
                        keterangan_detail.append(
                            f"*{nama_hari_tgl}: ada scan tapi data tidak lengkap -> dihitung tidak masuk"
                        )

            # Total hari valid = hari dengan scan lengkap + hari dengan cuti/sakit resmi
            jml_hari_valid = len(tanggal_lengkap_set) + hari_cuti_resmi

            if jml_hari_valid >= min_hari:
                continue  # Kuota hari kerja terpenuhi, tidak perlu dicatat sebagai anomali

            hasil_rows.append({
                "Cabang": cabang_dominan,
                "Nama": nama,
                "Profil": profil_kode,
                "Minggu": label_minggu,
                "Jml_Hari_Valid": jml_hari_valid,
                "Jml_Hari_Tidak_Masuk": len(hari_tidak_masuk),
                "Hari_Tidak_Masuk": ", ".join(hari_tidak_masuk) if hari_tidak_masuk else "-",
                "Keterangan": (
                    f"Kurang dari {min_hari} hari kerja (hanya {jml_hari_valid} hari valid"
                    + (f" termasuk {hari_cuti_resmi} cuti/izin resmi" if hari_cuti_resmi > 0 else "")
                    + ")."
                    + (" " + " ".join(keterangan_detail) if keterangan_detail else "")
                ),
                "_senin_minggu": senin_minggu,
            })

    hasil = pd.DataFrame(hasil_rows)
    if not hasil.empty:
        hasil = hasil.sort_values(["Nama", "_senin_minggu"]).reset_index(drop=True)
    else:
        hasil = pd.DataFrame(columns=[
            "Cabang", "Nama", "Profil", "Minggu", "Jml_Hari_Valid",
            "Jml_Hari_Tidak_Masuk", "Hari_Tidak_Masuk", "Keterangan", "_senin_minggu"
        ])
    return hasil


def hitung_rekap_alpa_berulang(rekap_tidak_masuk):
    """
    Fitur tambahan #2: deteksi karyawan yang minggu bermasalahnya (<4 hari
    kerja valid) terjadi >= config.MIN_MINGGU_BERTURUT_ALPA kali BERTURUT-TURUT,
    yaitu minggu-minggu kalender yang berdekatan langsung (selisih 7 hari
    dari Senin ke Senin), bukan cuma total kejadian dalam periode data.
    """
    kolom_output = ["Nama", "Jml_Minggu_Beruntun", "Periode_Minggu", "Keterangan"]
    if rekap_tidak_masuk.empty:
        return pd.DataFrame(columns=kolom_output)

    hasil_rows = []
    for nama, grup in rekap_tidak_masuk.groupby("Nama", sort=False):
        grup = grup.sort_values("_senin_minggu")
        senin_list = grup["_senin_minggu"].tolist()
        label_list = grup["Minggu"].tolist()

        streak_label = [label_list[0]]
        streak_len = 1
        for i in range(1, len(senin_list)):
            selisih_hari = (senin_list[i] - senin_list[i - 1]).days
            if selisih_hari == 7:
                streak_len += 1
                streak_label.append(label_list[i])
            else:
                if streak_len >= config.MIN_MINGGU_BERTURUT_ALPA:
                    hasil_rows.append({
                        "Nama": nama,
                        "Jml_Minggu_Beruntun": streak_len,
                        "Periode_Minggu": "; ".join(streak_label),
                        "Keterangan": (
                            f"Bermasalah (<{config.MIN_HARI_KERJA_PER_MINGGU} hari kerja) "
                            f"{streak_len} minggu berturut-turut."
                        ),
                    })
                streak_label = [label_list[i]]
                streak_len = 1
        # cek streak terakhir setelah loop selesai
        if streak_len >= config.MIN_MINGGU_BERTURUT_ALPA:
            hasil_rows.append({
                "Nama": nama,
                "Jml_Minggu_Beruntun": streak_len,
                "Periode_Minggu": "; ".join(streak_label),
                "Keterangan": (
                    f"Bermasalah (<{config.MIN_HARI_KERJA_PER_MINGGU} hari kerja) "
                    f"{streak_len} minggu berturut-turut."
                ),
            })

    return pd.DataFrame(hasil_rows, columns=kolom_output) if hasil_rows else pd.DataFrame(columns=kolom_output)


def hitung_rekap_profil_exclude(df_lengkap):
    """
    BARU v2: Rekap kehadiran sederhana untuk profil yang di-exclude dari
    logic utama (Anak Konten Live Stream, Setup Blok C, Office Boy).

    Tidak ada kolom telat/lembur — hanya:
    - Nama, Profil, Tanggal, Hari, Jam_Masuk, Jam_Keluar, Total_Jam_Kerja
    """
    # Ambil profil yang TIDAK ikut logic utama (ikut_telat=False DAN ikut_lembur=False
    # DAN ikut_kuota_hari_kerja=False)
    profil_exclude = [
        kode for kode, p in config.PROFIL_JADWAL.items()
        if not p["ikut_telat"] and not p["ikut_lembur"] and not p["ikut_kuota_hari_kerja"]
    ]

    df = df_lengkap[df_lengkap["Profil"].isin(profil_exclude)].copy()
    if df.empty:
        return pd.DataFrame(columns=[
            "Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Masuk", "Jam_Keluar", "Total_Jam_Kerja"
        ])

    def _total_jam(row):
        if pd.notna(row["Jam_Masuk"]) and pd.notna(row["Jam_Keluar"]):
            dt_masuk = datetime.datetime.combine(row["Tanggal"], row["Jam_Masuk"])
            dt_keluar = datetime.datetime.combine(row["Tanggal"], row["Jam_Keluar"])
            return round((dt_keluar - dt_masuk).total_seconds() / 3600, 2)
        return None

    df["Total_Jam_Kerja"] = df.apply(_total_jam, axis=1)

    return df[[
        "Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Masuk", "Jam_Keluar", "Total_Jam_Kerja"
    ]].reset_index(drop=True)
