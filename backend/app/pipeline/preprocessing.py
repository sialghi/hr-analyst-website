# -*- coding: utf-8 -*-
"""
preprocessing.py
=================
Implementasi Bagian 3.2 di rencana:
1. Normalisasi tanggal & jam
2. Koreksi label in/out yang salah (Aturan #7 & #8) — REVISI v2: patokan
   jam sekarang per profil, bukan hardcoded 08/16.
3. Deduplikasi scan ganda dalam rentang waktu sangat dekat
4. Agregasi per hari per karyawan (Jam Masuk = scan pertama, Jam Keluar = scan terakhir)
5. Hitung Absensi In / Absensi Out (Aturan #12, sebelum filter kelengkapan)
6. Flagging & pengeluaran data tidak lengkap (Aturan #11)
7. (BARU) Join profil dari master karyawan + tandai tanggal merah nasional
"""
import pandas as pd
from . import config_runtime as config


def _normalisasi_tipe_label(label_asli):
    """'C/Masuk' -> 'Masuk', 'C/Keluar' -> 'Keluar'. Toleran ke variasi spasi/kapital."""
    if pd.isna(label_asli):
        return None
    label = str(label_asli).strip()
    if "/" in label:
        label = label.split("/")[-1]
    label = label.strip().capitalize()
    if label not in ("Masuk", "Keluar"):
        return None  # label tak dikenal -> nanti akan tetap dikoreksi oleh jam kalau berlaku
    return label


def step1_normalisasi_datetime(df):
    """Aturan: normalisasi Timestamp_Raw ke datetime asli.

    Mendukung format campuran dalam satu kolom:
      - DD/MM/YYYY H:MM  (mayoritas data, dayfirst=True)
      - YYYY-MM-DD HH:MM:SS  (format ISO / Excel datetime object)
    Strategi: parse dua pass — pass pertama dayfirst=True, pass kedua
    dayfirst=False untuk baris yang gagal (menangkap format ISO).
    """
    df = df.copy()

    # --- Pass 1: mayoritas data biasanya DD/MM/YYYY ---
    df["Timestamp"] = pd.to_datetime(df["Timestamp_Raw"], dayfirst=True, errors="coerce")

    # --- Pass 2: baris yang gagal dicoba ulang dengan dayfirst=False (ISO) ---
    mask_gagal = df["Timestamp"].isna()
    if mask_gagal.any():
        retry = pd.to_datetime(
            df.loc[mask_gagal, "Timestamp_Raw"], dayfirst=False, errors="coerce"
        )
        df.loc[mask_gagal, "Timestamp"] = retry
        dipulihkan = mask_gagal.sum() - df["Timestamp"].isna().sum()
        if dipulihkan > 0:
            print(f"[INFO] {dipulihkan} baris dengan format timestamp alternatif (ISO) "
                  f"berhasil di-parse pada pass kedua.")

    # --- Baris yang tetap gagal setelah 2 pass → buang ---
    gagal_final = df["Timestamp"].isna().sum()
    if gagal_final > 0:
        print(f"[PERINGATAN] {gagal_final} baris gagal di-parse timestamp-nya dan akan diabaikan. "
              f"Cek kolom Timestamp_Raw pada baris tsb.")
        df = df.dropna(subset=["Timestamp"])

    df["Tanggal"] = df["Timestamp"].dt.date
    df["Jam"] = df["Timestamp"].dt.time
    df["Nama"] = df["Nama"].astype(str).str.strip()
    df["Cabang"] = df["Cabang"].astype(str).str.strip().str.upper()
    return df


def step2_koreksi_label(df, master_dict=None):
    """
    Aturan #7 & #8 — REVISI v2: patokan jam per profil karyawan.

    Logika:
    - jam scan > jam_keluar_profil -> SELALU dianggap Keluar
    - jam scan < jam_masuk_profil  -> SELALU dianggap Masuk
    - di antara keduanya           -> ikuti label asli (setelah dinormalisasi)

    Kalau karyawan tidak ada di master, pakai fallback OFFICE (08:00-16:00).
    """
    df = df.copy()
    label_normal = df["Tipe_Asli_Raw"].apply(_normalisasi_tipe_label)

    def tentukan_tipe_final(row_jam, label_asli_normal, nama_karyawan, nama_hari):
        # Cari profil karyawan
        profil_kode = config.PROFIL_DEFAULT
        if master_dict:
            nama_n = config.normalisasi_nama(nama_karyawan)
            info = master_dict.get(nama_n)
            if info:
                profil_kode = info["Profil"]

        profil = config.PROFIL_JADWAL[profil_kode]
        jam_masuk_std = config.get_jam_profil(profil, "jam_masuk", nama_hari)
        jam_keluar_std = config.get_jam_profil(profil, "jam_keluar", nama_hari)

        # Kalau profil tidak punya patokan jam (fleksibel), ikuti label asli apa adanya
        if jam_masuk_std is None and jam_keluar_std is None:
            return label_asli_normal

        # Pakai fallback global kalau salah satu None
        if jam_masuk_std is None:
            jam_masuk_std = config.JAM_MASUK_STANDAR
        if jam_keluar_std is None:
            jam_keluar_std = config.JAM_KELUAR_STANDAR

        if row_jam > jam_keluar_std:
            return "Keluar"
        if row_jam < jam_masuk_std:
            return "Masuk"
        # di dalam rentang jam kerja: ikuti label asli
        return label_asli_normal

    # Hitung nama hari per baris
    nama_hari_per_baris = df["Tanggal"].apply(
        lambda d: config.NAMA_HARI_ID[pd.Timestamp(d).weekday()]
    )

    df["Tipe_Final"] = [
        tentukan_tipe_final(j, lbl, nama, hari)
        for j, lbl, nama, hari in zip(df["Jam"], label_normal, df["Nama"], nama_hari_per_baris)
    ]

    # kalau di rentang normal tapi label asli tidak dikenali/kosong, buang baris
    # tsb dari perhitungan (bukan data yang bisa dipercaya arah-nya) tapi tetap
    # disimpan untuk audit.
    df["Tipe_Final_Valid"] = df["Tipe_Final"].isin(["Masuk", "Keluar"])
    return df


def step3_dedup_scan_ganda(df):
    """
    Buang scan duplikat: orang yang sama, tanggal yang sama, tipe (arah) yang
    sama, dan jaraknya <= config.DEDUP_THRESHOLD_MENIT dari scan sebelumnya yang
    sejenis dianggap 1 kejadian (mesin nge-double catat).

    Catatan: karena agregasi akhir memakai scan TERCEPAT untuk Masuk dan
    TERLAMBAT untuk Keluar, langkah ini murni untuk kebersihan data /
    menghindari drift kecil - tidak mengubah hasil Jam Masuk/Jam Keluar final,
    tapi PENTING untuk keakuratan hitung "jumlah kejadian" jika suatu saat
    dipakai (mis. hitung berapa kali scan per hari).
    """
    df = df.copy()
    df = df.sort_values(["Nama", "Tanggal", "Tipe_Final", "Timestamp"])
    selisih = df.groupby(["Nama", "Tanggal", "Tipe_Final"], dropna=False)["Timestamp"].diff().dt.total_seconds().div(60)
    mask_simpan = ~(selisih <= config.DEDUP_THRESHOLD_MENIT)
    df = df[mask_simpan]
    return df.reset_index(drop=True)


def step4_5_6_agregasi_harian(df, master_dict=None, tanggal_merah=None):
    """
    Agregasi per (Nama, Tanggal):
      - Cabang -> modus (cabang yang paling sering muncul utk org itu di hari itu)
      - Jam Masuk -> scan Masuk tercepat (Aturan #9: identifier = Nama saja,
        jadi digabung lintas cabang)
      - Jam Keluar -> scan Keluar paling akhir
      - Absensi In / Absensi Out dihitung DI SINI (Aturan #12) sebelum filter
        kelengkapan diterapkan.
      - Status Data: Lengkap jika keduanya ada, Tidak Lengkap jika cuma salah satu.
      - (BARU) Profil: dari master karyawan
      - (BARU) Is_Tanggal_Merah: boolean
      - (BARU) Kategori_Hari: "Kerja" / "Weekend" / "Libur" berdasarkan profil
    """
    if tanggal_merah is None:
        tanggal_merah = {}

    df_valid = df[df["Tipe_Final_Valid"]].copy()

    baris_masuk = df_valid[df_valid["Tipe_Final"] == "Masuk"]
    baris_keluar = df_valid[df_valid["Tipe_Final"] == "Keluar"]

    jam_masuk = (
        baris_masuk.groupby(["Nama", "Tanggal"])["Timestamp"].min().rename("Jam_Masuk_DT")
    )
    jam_keluar = (
        baris_keluar.groupby(["Nama", "Tanggal"])["Timestamp"].max().rename("Jam_Keluar_DT")
    )

    # cabang dominan per (Nama, Tanggal) -> pakai semua baris (masuk & keluar)
    cabang_harian = (
        df_valid.groupby(["Nama", "Tanggal"])["Cabang"]
        .agg(lambda s: s.value_counts().idxmax())
        .rename("Cabang")
    )

    hasil = pd.concat([cabang_harian, jam_masuk, jam_keluar], axis=1).reset_index()

    hasil["Hari"] = hasil["Tanggal"].apply(
        lambda d: config.NAMA_HARI_ID[pd.Timestamp(d).weekday()]
    )

    # --- REVISI v2: Join profil dari master ---
    def _get_profil(nama):
        if master_dict:
            nama_n = config.normalisasi_nama(nama)
            info = master_dict.get(nama_n)
            if info:
                return info["Profil"]
        return config.PROFIL_DEFAULT

    hasil["Profil"] = hasil["Nama"].apply(_get_profil)

    # --- REVISI v2: Tandai tanggal merah ---
    hasil["Is_Tanggal_Merah"] = hasil["Tanggal"].apply(lambda d: d in tanggal_merah)
    hasil["Keterangan_Tanggal_Merah"] = hasil["Tanggal"].apply(
        lambda d: tanggal_merah.get(d, "")
    )

    # --- Kategori Hari: berdasarkan profil ---
    def _kategori_hari(row):
        tgl = row["Tanggal"]
        profil = config.PROFIL_JADWAL.get(row["Profil"], config.PROFIL_JADWAL[config.PROFIL_DEFAULT])
        nama_hari = row["Hari"]

        # Cek apakah karyawan Toko IDD (PIK)
        is_idd = False
        if master_dict:
            nama_n = config.normalisasi_nama(row["Nama"])
            info = master_dict.get(nama_n, {})
            if "idd" in str(info.get("Status_Raw", "")).lower() or "idd" in str(row.get("Cabang", "")).lower():
                is_idd = True

        # Kalau tanggal merah → "Tanggal Merah" (profil yang ikut bonus tanggal merah ATAU karyawan Toko IDD)
        if tgl in tanggal_merah and (profil.get("ikut_bonus_tanggal_merah", True) or is_idd):
            return "Tanggal Merah"

        # Kalau profil punya daftar hari kerja, cek apakah hari ini termasuk
        if profil["hari_kerja"]:
            if nama_hari in profil["hari_kerja"]:
                return "Kerja"
            else:
                return "Weekend"
        else:
            # Profil fleksibel (tidak ada hari kerja terdefinisi) — anggap semua hari = kerja
            return "Kerja"

    hasil["Kategori_Hari"] = hasil.apply(_kategori_hari, axis=1)

    def status_data(row):
        ada_masuk = pd.notna(row["Jam_Masuk_DT"])
        ada_keluar = pd.notna(row["Jam_Keluar_DT"])
        if ada_masuk and ada_keluar:
            return "Lengkap"
        return "Tidak Lengkap"

    hasil["Status_Data"] = hasil.apply(status_data, axis=1)

    def catatan(row):
        ada_masuk = pd.notna(row["Jam_Masuk_DT"])
        ada_keluar = pd.notna(row["Jam_Keluar_DT"])
        if ada_masuk and not ada_keluar:
            return "Hanya ada scan Masuk (tidak ada scan Keluar)"
        if ada_keluar and not ada_masuk:
            return "Hanya ada scan Keluar (tidak ada scan Masuk)"
        return None

    hasil["Catatan"] = hasil.apply(catatan, axis=1)

    hasil["Jam_Masuk"] = hasil["Jam_Masuk_DT"].dt.time
    hasil["Jam_Keluar"] = hasil["Jam_Keluar_DT"].dt.time

    hasil = hasil.sort_values(["Cabang", "Nama", "Tanggal"]).reset_index(drop=True)
    return hasil[[
        "Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Masuk", "Jam_Keluar",
        "Status_Data", "Kategori_Hari", "Is_Tanggal_Merah", "Keterangan_Tanggal_Merah",
        "Catatan", "Jam_Masuk_DT", "Jam_Keluar_DT",
    ]]


def jalankan_preprocessing(df_mentah, master_dict=None, tanggal_merah=None):
    """Pipeline lengkap step 1-6, return DataFrame hasil agregasi harian per karyawan.

    REVISI v2: terima master_dict dan tanggal_merah sebagai parameter.
    """
    df = step1_normalisasi_datetime(df_mentah)
    df = step2_koreksi_label(df, master_dict=master_dict)
    df = step3_dedup_scan_ganda(df)
    hasil_harian = step4_5_6_agregasi_harian(df, master_dict=master_dict, tanggal_merah=tanggal_merah)
    return hasil_harian
