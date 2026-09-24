# -*- coding: utf-8 -*-
"""
service.py
==========
Versi web dari main.py::jalankan_pipeline() yang asli. Logic perhitungan
(loader/preprocessing/data_process/excel_writer) TIDAK diubah sama sekali -
yang berubah hanya SUMBER config, master karyawan, dan tanggal merah:
sekarang dari database (bisa diedit HR Master), bukan file statis.
"""
import os
import pandas as pd
from sqlalchemy.orm import Session

from . import config_runtime as config
from .loader import (
    load_raw_data, load_master_karyawan, load_tanggal_merah,
    build_master_dict, cari_nama_tidak_dikenal,
    build_master_df_from_db, build_tanggal_merah_from_db,
    build_approved_leaves_from_db,
)
from .preprocessing import jalankan_preprocessing
from .data_process import (
    hitung_telat, hitung_lembur, hitung_pulang_duluan,
    hitung_rekap_tidak_masuk, hitung_rekap_alpa_berulang,
    hitung_uang_makan, hitung_rekap_profil_exclude,
)
from .excel_writer import tulis_laporan_excel
from .. import models

CATATAN_ASUMSI = [
    "Aturan jam kerja, telat, dan lembur bergantung pada PROFIL masing-masing karyawan, "
    "dan diambil LANGSUNG dari pengaturan HR Master di website (bukan lagi file config statis).",
    "Scan di hari Sabtu/Minggu tetap dihitung utk status Telat/Lembur/Pulang Duluan (jika profil tsb "
    "punya jam baku di hari tsb), tapi tidak dihitung sebagai 'hari kerja valid' jika profil tsb "
    "hanya punya kuota Senin-Jumat.",
    "Kalau nama sama muncul di lebih dari satu cabang, cabang yang ditampilkan di Summary Overview "
    "adalah cabang yang PALING SERING muncul utk orang tsb.",
    "Minggu di awal/akhir periode data yang datanya belum genap tetap dievaluasi apa adanya.",
]


def jalankan_pipeline_db(
    daftar_input,
    path_output: str,
    db: Session,
    override_master_path: str = None,
    override_tanggal_merah_path: str = None,
    verbose: bool = False,
):
    """
    daftar_input             : list path file absensi mentah yang sudah di-upload
    path_output               : path file .xlsx tujuan
    db                         : SQLAlchemy session (dipakai untuk reload config, master, tanggal merah)
    override_master_path      : opsional, path file master karyawan (utk kompatibilitas n8n lama).
                                 Kalau None -> master diambil dari tabel `employees` di database.
    override_tanggal_merah_path: opsional, path file tanggal merah (utk kompatibilitas n8n lama).
                                 Kalau None -> diambil dari tabel `holidays` di database.
    """
    def log(msg):
        if verbose:
            print(msg)

    folder_output = os.path.dirname(os.path.abspath(path_output))
    os.makedirs(folder_output, exist_ok=True)

    # --- 0. SELALU reload config paling baru dari database sebelum menghitung apa pun ---
    log("[0/5] Memuat aturan bisnis terbaru dari database...")
    config.reload_from_db(db)
    if not config.PROFIL_JADWAL:
        raise ValueError(
            "Belum ada profil/aturan bisnis di database. Minta HR Master membuat profil dulu di halaman Aturan Bisnis."
        )

    # --- 1. Master karyawan & tanggal merah ---
    log("[1/5] Membaca master karyawan & tanggal merah...")
    if override_master_path:
        df_master = load_master_karyawan(override_master_path)
    else:
        employees = db.query(models.Employee).filter(models.Employee.active == True).all()  # noqa: E712
        df_master = build_master_df_from_db(employees)

    if override_tanggal_merah_path:
        tanggal_merah_set = load_tanggal_merah(override_tanggal_merah_path)
    else:
        holidays = db.query(models.Holiday).all()
        tanggal_merah_set = build_tanggal_merah_from_db(holidays)

    master_dict = build_master_dict(df_master)
    log(f"      -> {len(master_dict)} karyawan di master, {len(tanggal_merah_set)} tanggal merah dikenali.")

    # --- 1b. Cuti & izin yang sudah APPROVED ---
    leaves = db.query(models.LeaveRequest).filter(models.LeaveRequest.status == "APPROVED").all()
    approved_leaves = build_approved_leaves_from_db(leaves)
    log(f"      -> {len(leaves)} pengajuan cuti/izin APPROVED ditemukan.")

    log(f"[2/5] Membaca data absensi mentah dari: {daftar_input}")
    df_mentah = load_raw_data(daftar_input)
    log(f"      -> {len(df_mentah)} baris scan mentah terbaca.")

    df_perlu_dicek = cari_nama_tidak_dikenal(df_mentah, master_dict)
    if not df_perlu_dicek.empty:
        log(f"      -> PERINGATAN: {len(df_perlu_dicek)} nama di absensi TIDAK DITEMUKAN di master!")

    log("[3/5] Preprocessing...")
    df_prep = jalankan_preprocessing(df_mentah, master_dict=master_dict, tanggal_merah=tanggal_merah_set)

    log("[4/5] Data Process (telat/lembur/uang makan/tidak masuk)...")
    df_lengkap = df_prep[df_prep["Status_Data"] == "Lengkap"]
    df_telat = hitung_telat(df_lengkap, approved_leaves=approved_leaves)
    df_lembur = hitung_lembur(df_lengkap, tanggal_merah=tanggal_merah_set)
    df_pulang_duluan = hitung_pulang_duluan(df_lengkap, approved_leaves=approved_leaves)
    df_uang_makan = hitung_uang_makan(df_lengkap, master_dict=master_dict, tanggal_merah=tanggal_merah_set, approved_leaves=approved_leaves)
    df_profil_exclude = hitung_rekap_profil_exclude(df_lengkap)

    df_tidak_masuk = hitung_rekap_tidak_masuk(df_prep, approved_leaves=approved_leaves)
    df_alpa_berulang = hitung_rekap_alpa_berulang(df_tidak_masuk)

    df_tidak_masuk_export = df_tidak_masuk.drop(columns=["_senin_minggu"], errors="ignore")

    log(f"[5/5] Menulis laporan Excel ke: {path_output}")
    tulis_laporan_excel(
        path_output, df_mentah, df_prep, df_telat, df_lembur,
        df_pulang_duluan, df_tidak_masuk_export, df_alpa_berulang,
        CATATAN_ASUMSI,
        df_uang_makan=df_uang_makan,
        df_profil_exclude=df_profil_exclude,
        df_perlu_dicek=df_perlu_dicek,
    )
    log("Selesai.")
    return path_output


# ---------------------------------------------------------------------------
#  Versi JSON: menjalankan pipeline & mengembalikan dict terstruktur
# ---------------------------------------------------------------------------

def _safe_val(v):
    """Bersihkan NaN / NaT / Timestamp agar aman di-JSON-serialize."""
    if v is None:
        return None
    if isinstance(v, float) and (pd.isna(v) or v != v):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d %H:%M:%S") if not pd.isna(v) else None
    if hasattr(v, 'isoformat'):
        return v.isoformat()
    return v


def _df_to_records(df, kolom_map=None, kolom_types=None):
    """Ubah DataFrame jadi list[dict] yang JSON-safe, dengan header rename opsional.
    kolom_types: dict mapping nama kolom OUTPUT -> 'currency'|'number'|'text'|'time'|'date'
    """
    if df is None or df.empty:
        headers_out = list((kolom_map or {}).values()) or list(df.columns if df is not None else [])
        types_out = {h: (kolom_types or {}).get(h, "text") for h in headers_out}
        return {"headers": headers_out, "types": types_out, "rows": []}

    if kolom_map:
        cols_present = {k: v for k, v in kolom_map.items() if k in df.columns}
        df_show = df[list(cols_present.keys())].rename(columns=cols_present)
    else:
        df_show = df.copy()

    headers = list(df_show.columns)
    types = {h: (kolom_types or {}).get(h, "text") for h in headers}
    rows = []
    for _, row in df_show.iterrows():
        rows.append({h: _safe_val(row[h]) for h in headers})
    return {"headers": headers, "types": types, "rows": rows}


def _compute_summary_overview_json(df_prep, df_telat, df_lembur, df_pulang_duluan,
                                     df_tidak_masuk, df_uang_makan):
    """Hitung Summary Overview identik dengan formula Excel, tapi di Python."""
    if "Profil" in df_prep.columns:
        daftar = (
            df_prep.groupby("Nama").agg(
                Cabang=("Cabang", lambda s: s.value_counts().idxmax()),
                Profil=("Profil", "first"),
            ).reset_index()[["Cabang", "Nama", "Profil"]]
            .sort_values(["Cabang", "Nama"])
        )
    else:
        daftar = (
            df_prep.groupby("Nama")["Cabang"]
            .agg(lambda s: s.value_counts().idxmax())
            .reset_index()
            .rename(columns={"Cabang": "Cabang"})[["Cabang", "Nama"]]
            .sort_values(["Cabang", "Nama"])
        )
        daftar["Profil"] = ""

    rows = []
    for _, emp in daftar.iterrows():
        nama = emp["Nama"]
        prep_emp = df_prep[df_prep["Nama"] == nama]
        telat_emp = df_telat[df_telat["Nama"] == nama] if not df_telat.empty else pd.DataFrame()
        lembur_emp = df_lembur[df_lembur["Nama"] == nama] if not df_lembur.empty else pd.DataFrame()
        pd_emp = df_pulang_duluan[df_pulang_duluan["Nama"] == nama] if not df_pulang_duluan.empty else pd.DataFrame()
        tm_emp = df_tidak_masuk[df_tidak_masuk["Nama"] == nama] if not df_tidak_masuk.empty else pd.DataFrame()
        um_emp = df_uang_makan[df_uang_makan["Nama"] == nama] if df_uang_makan is not None and not df_uang_makan.empty else pd.DataFrame()

        absensi_in = int(prep_emp["Jam_Masuk"].notna().sum()) if "Jam_Masuk" in prep_emp.columns else 0
        absensi_out = int(prep_emp["Jam_Keluar"].notna().sum()) if "Jam_Keluar" in prep_emp.columns else 0
        hari_kerja_valid = int(((prep_emp.get("Status_Data", pd.Series()) == "Lengkap") & (prep_emp.get("Kategori_Hari", pd.Series()) == "Kerja")).sum())
        masuk_tgl_merah = int((prep_emp.get("Kategori_Hari", pd.Series()) == "Tanggal Merah").sum())

        jml_telat = len(telat_emp)
        total_durasi_telat = float(telat_emp["Durasi_Telat_Jam"].sum()) if "Durasi_Telat_Jam" in telat_emp.columns and not telat_emp.empty else 0
        jml_lembur = len(lembur_emp)
        total_jam_lembur_bulat = int(lembur_emp["Jam_Lembur_Bulat"].sum()) if "Jam_Lembur_Bulat" in lembur_emp.columns and not lembur_emp.empty else 0
        total_bonus_lembur = float(lembur_emp["Bonus_Lembur_Rp"].sum()) if "Bonus_Lembur_Rp" in lembur_emp.columns and not lembur_emp.empty else 0
        jml_pulang_duluan = len(pd_emp)
        total_durasi_pd = float(pd_emp["Durasi_Kurang_Jam"].sum()) if "Durasi_Kurang_Jam" in pd_emp.columns and not pd_emp.empty else 0
        minggu_bermasalah = len(tm_emp)
        jml_hari_tidak_masuk = int(tm_emp["Jml_Hari_Tidak_Masuk"].sum()) if "Jml_Hari_Tidak_Masuk" in tm_emp.columns and not tm_emp.empty else 0

        uang_makan_harian = float(um_emp["Uang_Makan_Base"].sum()) if "Uang_Makan_Base" in um_emp.columns and not um_emp.empty else 0
        potongan_telat = float(um_emp["Potongan_Telat"].sum()) if "Potongan_Telat" in um_emp.columns and not um_emp.empty else 0
        potongan_pd_rp = float(um_emp["Potongan_Pulang_Duluan"].sum()) if "Potongan_Pulang_Duluan" in um_emp.columns and not um_emp.empty else 0
        bonus_tgl_merah_rp = float(um_emp["Bonus_Tanggal_Merah"].sum()) if "Bonus_Tanggal_Merah" in um_emp.columns and not um_emp.empty else 0
        total_uang_makan = float(um_emp["Total_Uang_Makan"].sum()) if "Total_Uang_Makan" in um_emp.columns and not um_emp.empty else 0

        def _fmt_durasi(jam):
            if jam <= 0:
                return "0 menit"
            j = int(jam)
            m = round((jam - j) * 60)
            if j > 0 and m > 0:
                return f"{j} jam {m} menit"
            elif j > 0:
                return f"{j} jam"
            return f"{m} menit"

        rows.append({
            "Cabang": emp["Cabang"],
            "Nama": nama,
            "Profil": emp.get("Profil", ""),
            "Absensi In": absensi_in,
            "Absensi Out": absensi_out,
            "Hari Kerja Valid": hari_kerja_valid,
            "Masuk Tanggal Merah": masuk_tgl_merah,
            "Jml Telat": jml_telat,
            "Total Durasi Telat": _fmt_durasi(total_durasi_telat),
            "Jml Lembur": jml_lembur,
            "Jam Lembur (Bulat)": total_jam_lembur_bulat,
            "Total Bonus Lembur (Rp)": total_bonus_lembur,
            "Jml Pulang Duluan": jml_pulang_duluan,
            "Total Durasi Pulang Duluan": _fmt_durasi(total_durasi_pd),
            "Minggu Bermasalah": minggu_bermasalah,
            "Jumlah Hari Tidak Masuk": jml_hari_tidak_masuk,
            "Uang Makan Harian (Rp)": uang_makan_harian,
            "Potongan Telat (Rp)": potongan_telat,
            "Potongan Pulang Duluan (Rp)": potongan_pd_rp,
            "Bonus Tanggal Merah (Rp)": bonus_tgl_merah_rp,
            "Total Uang Makan Akhir (Rp)": total_uang_makan,
        })

    headers = [
        "Cabang", "Nama", "Profil", "Absensi In", "Absensi Out", "Hari Kerja Valid",
        "Masuk Tanggal Merah", "Jml Telat", "Total Durasi Telat", "Jml Lembur",
        "Jam Lembur (Bulat)", "Total Bonus Lembur (Rp)", "Jml Pulang Duluan",
        "Total Durasi Pulang Duluan", "Minggu Bermasalah", "Jumlah Hari Tidak Masuk",
        "Uang Makan Harian (Rp)", "Potongan Telat (Rp)", "Potongan Pulang Duluan (Rp)",
        "Bonus Tanggal Merah (Rp)", "Total Uang Makan Akhir (Rp)",
    ]
    types = {
        "Cabang": "text", "Nama": "text", "Profil": "text",
        "Absensi In": "number", "Absensi Out": "number",
        "Hari Kerja Valid": "number", "Masuk Tanggal Merah": "number",
        "Jml Telat": "number", "Total Durasi Telat": "text",
        "Jml Lembur": "number", "Jam Lembur (Bulat)": "number",
        "Total Bonus Lembur (Rp)": "currency", "Jml Pulang Duluan": "number",
        "Total Durasi Pulang Duluan": "text",
        "Minggu Bermasalah": "number", "Jumlah Hari Tidak Masuk": "number",
        "Uang Makan Harian (Rp)": "currency", "Potongan Telat (Rp)": "currency",
        "Potongan Pulang Duluan (Rp)": "currency", "Bonus Tanggal Merah (Rp)": "currency",
        "Total Uang Makan Akhir (Rp)": "currency",
    }
    return {"headers": headers, "types": types, "rows": rows}, daftar


def _compute_perbandingan_cabang_json(summary_rows, df_telat, df_lembur, df_pulang_duluan, df_tidak_masuk):
    """Hitung Perbandingan Cabang identik dengan formula Excel."""
    cabang_set = sorted(set(r["Cabang"] for r in summary_rows))
    rows = []
    for cabang in cabang_set:
        jml_kary = sum(1 for r in summary_rows if r["Cabang"] == cabang)
        telat_cab = df_telat[df_telat["Cabang"] == cabang] if not df_telat.empty else pd.DataFrame()
        lembur_cab = df_lembur[df_lembur["Cabang"] == cabang] if not df_lembur.empty else pd.DataFrame()
        pd_cab = df_pulang_duluan[df_pulang_duluan["Cabang"] == cabang] if not df_pulang_duluan.empty else pd.DataFrame()
        tm_cab = df_tidak_masuk[df_tidak_masuk["Cabang"] == cabang] if "Cabang" in df_tidak_masuk.columns and not df_tidak_masuk.empty else pd.DataFrame()

        total_telat_dur = float(telat_cab["Durasi_Telat_Jam"].sum()) if "Durasi_Telat_Jam" in telat_cab.columns and not telat_cab.empty else 0
        total_jam_lembur_bulat_cab = int(lembur_cab["Jam_Lembur_Bulat"].sum()) if "Jam_Lembur_Bulat" in lembur_cab.columns and not lembur_cab.empty else 0

        def _fmt(jam):
            if jam <= 0:
                return "0 menit"
            j = int(jam)
            m = round((jam - j) * 60)
            if j > 0 and m > 0:
                return f"{j} jam {m} menit"
            elif j > 0:
                return f"{j} jam"
            return f"{m} menit"

        rows.append({
            "Cabang": cabang,
            "Jml Karyawan": jml_kary,
            "Total Kejadian Telat": len(telat_cab),
            "Total Durasi Telat": _fmt(total_telat_dur),
            "Total Kejadian Lembur": len(lembur_cab),
            "Jam Lembur (Bulat)": total_jam_lembur_bulat_cab,
            "Total Kejadian Pulang Duluan": len(pd_cab),
            "Minggu Bermasalah": len(tm_cab),
        })

    headers = ["Cabang", "Jml Karyawan", "Total Kejadian Telat", "Total Durasi Telat",
               "Total Kejadian Lembur", "Jam Lembur (Bulat)",
               "Total Kejadian Pulang Duluan", "Minggu Bermasalah"]
    types = {"Cabang": "text", "Jml Karyawan": "number",
             "Total Kejadian Telat": "number", "Total Durasi Telat": "text",
             "Total Kejadian Lembur": "number", "Jam Lembur (Bulat)": "number",
             "Total Kejadian Pulang Duluan": "number", "Minggu Bermasalah": "number"}
    return {"headers": headers, "types": types, "rows": rows}


def jalankan_pipeline_db_json(
    daftar_input,
    path_output: str,
    db: Session,
    override_master_path: str = None,
    override_tanggal_merah_path: str = None,
    verbose: bool = False,
):
    """Jalankan pipeline lengkap, tulis Excel, DAN kembalikan dict terstruktur untuk JSON response."""
    def log(msg):
        if verbose:
            print(msg)

    folder_output = os.path.dirname(os.path.abspath(path_output))
    os.makedirs(folder_output, exist_ok=True)

    # --- 0. Reload config ---
    log("[0/5] Memuat aturan bisnis terbaru dari database...")
    config.reload_from_db(db)
    if not config.PROFIL_JADWAL:
        raise ValueError(
            "Belum ada profil/aturan bisnis di database. Minta HR Master membuat profil dulu di halaman Aturan Bisnis."
        )

    # --- 1. Master karyawan & tanggal merah ---
    log("[1/5] Membaca master karyawan & tanggal merah...")
    if override_master_path:
        df_master = load_master_karyawan(override_master_path)
    else:
        employees = db.query(models.Employee).filter(models.Employee.active == True).all()  # noqa: E712
        df_master = build_master_df_from_db(employees)

    if override_tanggal_merah_path:
        tanggal_merah_set = load_tanggal_merah(override_tanggal_merah_path)
    else:
        holidays = db.query(models.Holiday).all()
        tanggal_merah_set = build_tanggal_merah_from_db(holidays)

    master_dict = build_master_dict(df_master)

    # --- 1b. Cuti & izin yang sudah APPROVED ---
    leaves = db.query(models.LeaveRequest).filter(models.LeaveRequest.status == "APPROVED").all()
    approved_leaves = build_approved_leaves_from_db(leaves)

    log(f"[2/5] Membaca data absensi mentah dari: {daftar_input}")
    df_mentah = load_raw_data(daftar_input)
    df_perlu_dicek = cari_nama_tidak_dikenal(df_mentah, master_dict)

    log("[3/5] Preprocessing...")
    df_prep = jalankan_preprocessing(df_mentah, master_dict=master_dict, tanggal_merah=tanggal_merah_set)

    log("[4/5] Data Process...")
    df_lengkap = df_prep[df_prep["Status_Data"] == "Lengkap"]
    df_telat = hitung_telat(df_lengkap, approved_leaves=approved_leaves)
    df_lembur = hitung_lembur(df_lengkap, tanggal_merah=tanggal_merah_set)
    df_pulang_duluan = hitung_pulang_duluan(df_lengkap, approved_leaves=approved_leaves)
    df_uang_makan = hitung_uang_makan(df_lengkap, master_dict=master_dict, tanggal_merah=tanggal_merah_set, approved_leaves=approved_leaves)
    df_profil_exclude = hitung_rekap_profil_exclude(df_lengkap)
    df_tidak_masuk = hitung_rekap_tidak_masuk(df_prep, approved_leaves=approved_leaves)
    df_alpa_berulang = hitung_rekap_alpa_berulang(df_tidak_masuk)
    df_tidak_masuk_export = df_tidak_masuk.drop(columns=["_senin_minggu"], errors="ignore")

    log(f"[5/5] Menulis laporan Excel ke: {path_output}")
    tulis_laporan_excel(
        path_output, df_mentah, df_prep, df_telat, df_lembur,
        df_pulang_duluan, df_tidak_masuk_export, df_alpa_berulang,
        CATATAN_ASUMSI,
        df_uang_makan=df_uang_makan,
        df_profil_exclude=df_profil_exclude,
        df_perlu_dicek=df_perlu_dicek,
    )
    log("Excel selesai ditulis. Menyiapkan data JSON...")

    # --- Bangun sheet-sheet JSON ---
    summary_data, daftar_karyawan = _compute_summary_overview_json(
        df_prep, df_telat, df_lembur, df_pulang_duluan, df_tidak_masuk_export, df_uang_makan
    )

    perbandingan_data = _compute_perbandingan_cabang_json(
        summary_data["rows"], df_telat, df_lembur, df_pulang_duluan, df_tidak_masuk_export
    )

    # Kolom maps untuk sheet-sheet rekap (sama persis dengan excel_writer.py)
    kolom_telat = {
        "Cabang": "Cabang", "Nama": "Nama", "Profil": "Profil",
        "Tanggal": "Tanggal", "Hari": "Hari",
        "Jam_Masuk": "Jam Masuk", "Jam_Masuk_Standar": "Jam Standar",
        "Durasi_Telat_Format": "Durasi Telat",
        "Kejadian_Ke": "Telat Ke-", "Status_Toleransi": "Status Toleransi",
        "Potongan_Telat_Rp": "Potongan (Rp)",
    }
    kolom_telat = {k: v for k, v in kolom_telat.items() if k in df_telat.columns}
    types_telat = {"Potongan (Rp)": "currency", "Telat Ke-": "number"}

    kolom_lembur = {
        "Cabang": "Cabang", "Nama": "Nama", "Profil": "Profil",
        "Tanggal": "Tanggal", "Hari": "Hari",
        "Jam_Keluar": "Jam Keluar", "Jam_Keluar_Standar": "Jam Standar",
        "Durasi_Lembur_Format": "Durasi Lembur",
        "Jam_Lembur_Bulat": "Jam Lembur (bulat)",
        "Bonus_Lembur_Rp": "Bonus Lembur (Rp)",
    }
    kolom_lembur = {k: v for k, v in kolom_lembur.items() if k in df_lembur.columns}
    types_lembur = {"Bonus Lembur (Rp)": "currency", "Jam Lembur (bulat)": "number"}

    # Tambahkan flag highlight untuk lembur hari Minggu driver
    lembur_records = _df_to_records(df_lembur, kolom_lembur, types_lembur)
    for row in lembur_records["rows"]:
        hari = row.get("Hari", "")
        profil = str(row.get("Profil", "")).upper()
        nama = str(row.get("Nama", "")).lower()
        row["_highlight"] = (hari == "Minggu" and ("DRIVER" in profil or "harry" in nama))

    kolom_pd = {
        "Cabang": "Cabang", "Nama": "Nama", "Profil": "Profil",
        "Tanggal": "Tanggal", "Hari": "Hari",
        "Jam_Keluar": "Jam Keluar",
        "Durasi_Kurang_Format": "Durasi Kurang",
    }
    kolom_pd = {k: v for k, v in kolom_pd.items() if k in df_pulang_duluan.columns}

    kolom_tm = {
        "Cabang": "Cabang", "Nama": "Nama", "Profil": "Profil", "Minggu": "Minggu",
        "Jml_Hari_Valid": "Jml Hari Valid", "Jml_Hari_Tidak_Masuk": "Jml Hari Tidak Masuk",
        "Hari_Tidak_Masuk": "Hari yang Tidak Masuk", "Keterangan": "Keterangan",
    }
    types_tm = {"Jml Hari Valid": "number", "Jml Hari Tidak Masuk": "number"}

    kolom_tl = ["Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Masuk", "Jam_Keluar", "Catatan"]
    kolom_tl_ada = [c for c in kolom_tl if c in df_prep.columns]
    df_tidak_lengkap = df_prep[df_prep["Status_Data"] == "Tidak Lengkap"][kolom_tl_ada].rename(
        columns={"Jam_Masuk": "Jam Masuk", "Jam_Keluar": "Jam Keluar"}
    )

    kolom_alpa = {
        "Nama": "Nama", "Jml_Minggu_Beruntun": "Jml Minggu Beruntun",
        "Periode_Minggu": "Periode Minggu", "Keterangan": "Keterangan",
    }
    types_alpa = {"Jml Minggu Beruntun": "number"}

    kolom_um = {
        "Cabang": "Cabang", "Nama": "Nama", "Profil": "Profil",
        "Tanggal": "Tanggal", "Hari": "Hari",
        "Uang_Makan_Base": "Uang Makan (Rp)",
        "Potongan_Telat": "Potongan Telat (Rp)",
        "Potongan_Pulang_Duluan": "Potongan Pulang Duluan (Rp)",
        "Bonus_Tanggal_Merah": "Bonus Tanggal Merah (Rp)",
        "Total_Uang_Makan": "Total Uang Makan (Rp)",
    }
    types_um = {
        "Uang Makan (Rp)": "currency", "Potongan Telat (Rp)": "currency",
        "Potongan Pulang Duluan (Rp)": "currency", "Bonus Tanggal Merah (Rp)": "currency",
        "Total Uang Makan (Rp)": "currency",
    }

    kolom_pe = {
        "Cabang": "Cabang", "Nama": "Nama", "Profil": "Profil",
        "Tanggal": "Tanggal", "Hari": "Hari",
        "Jam_Masuk": "Jam Masuk", "Jam_Keluar": "Jam Keluar",
        "Total_Jam_Kerja": "Total Jam Kerja",
    }

    kolom_dc = {"Nama": "Nama", "Cabang": "Cabang", "Jumlah_Scan": "Jumlah Scan"}
    types_dc = {"Jumlah Scan": "number"}

    # Preprocessing view
    kolom_prep_tampil = ["Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Masuk", "Jam_Keluar",
                         "Status_Data", "Kategori_Hari", "Is_Tanggal_Merah", "Catatan"]
    kolom_prep_ada = [c for c in kolom_prep_tampil if c in df_prep.columns]
    kolom_prep_map = {c: c for c in kolom_prep_ada}
    kolom_prep_map.update({
        "Jam_Masuk": "Jam Masuk", "Jam_Keluar": "Jam Keluar",
        "Status_Data": "Status Data", "Kategori_Hari": "Kategori Hari",
        "Is_Tanggal_Merah": "Tanggal Merah",
    })
    kolom_prep_map = {k: v for k, v in kolom_prep_map.items() if k in kolom_prep_ada}

    # Data mentah
    data_mentah_records = _df_to_records(df_mentah)

    # Readme
    readme_lines = CATATAN_ASUMSI[:]

    # Build sheets list
    sheets = [
        {"key": "summary",         "title": "Summary Overview",         "data": summary_data},
        {"key": "telat",           "title": "Rekap Telat",              "data": _df_to_records(df_telat, kolom_telat, types_telat)},
        {"key": "lembur",          "title": "Rekap Lembur",             "data": lembur_records},
        {"key": "pulang_duluan",   "title": "Rekap Pulang Duluan",      "data": _df_to_records(df_pulang_duluan, kolom_pd)},
        {"key": "tidak_masuk",     "title": "Rekap Tidak Masuk",        "data": _df_to_records(df_tidak_masuk_export, kolom_tm, types_tm)},
        {"key": "tidak_lengkap",   "title": "Data Tidak Lengkap",       "data": _df_to_records(df_tidak_lengkap)},
        {"key": "uang_makan",      "title": "Uang Makan",              "data": _df_to_records(df_uang_makan, kolom_um, types_um) if df_uang_makan is not None else _df_to_records(pd.DataFrame(), kolom_um, types_um)},
        {"key": "perbandingan",    "title": "Perbandingan Cabang",      "data": perbandingan_data},
        {"key": "profil_exclude",  "title": "Rekap per Profil",         "data": _df_to_records(df_profil_exclude, kolom_pe) if df_profil_exclude is not None else _df_to_records(pd.DataFrame(), kolom_pe)},
        {"key": "alpa_berulang",   "title": "Alpa Berulang",            "data": _df_to_records(df_alpa_berulang, kolom_alpa, types_alpa)},
        {"key": "perlu_dicek",     "title": "Perlu Dicek",              "data": _df_to_records(df_perlu_dicek, kolom_dc, types_dc) if df_perlu_dicek is not None else _df_to_records(pd.DataFrame(), kolom_dc, types_dc)},
        {"key": "preprocessing",   "title": "Preprocessing",            "data": _df_to_records(df_prep[kolom_prep_ada], kolom_prep_map)},
        {"key": "data_mentah",     "title": "Data Mentah",              "data": data_mentah_records},
        {"key": "readme",          "title": "README & Panduan",         "data": {"headers": [], "types": {}, "rows": [], "catatan": readme_lines}},
    ]

    # KPI summary
    total_karyawan = len(summary_data["rows"])
    total_telat = sum(r.get("Jml Telat", 0) for r in summary_data["rows"])
    total_lembur_k = sum(r.get("Jam Lembur (Bulat)", 0) for r in summary_data["rows"])
    total_bonus_lembur = sum(r.get("Total Bonus Lembur (Rp)", 0) for r in summary_data["rows"])
    total_uang_makan = sum(r.get("Total Uang Makan Akhir (Rp)", 0) for r in summary_data["rows"])
    total_pulang_duluan = sum(r.get("Jml Pulang Duluan", 0) for r in summary_data["rows"])
    jml_perlu_dicek = len(df_perlu_dicek) if df_perlu_dicek is not None else 0

    cabang_list = sorted(daftar_karyawan["Cabang"].unique().tolist()) if not daftar_karyawan.empty else []
    profil_list = sorted(daftar_karyawan["Profil"].unique().tolist()) if "Profil" in daftar_karyawan.columns else []

    result = {
        "kpis": {
            "total_karyawan": total_karyawan,
            "total_telat": total_telat,
            "total_lembur": total_lembur_k,
            "total_bonus_lembur": total_bonus_lembur,
            "total_uang_makan": total_uang_makan,
            "total_pulang_duluan": total_pulang_duluan,
            "jml_perlu_dicek": jml_perlu_dicek,
            "total_baris_scan": len(df_mentah),
        },
        "sheets": sheets,
        "cabang_list": cabang_list,
        "profil_list": profil_list,
    }

    log("Selesai. Data JSON siap dikirim.")
    return result, path_output
