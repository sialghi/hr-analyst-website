# -*- coding: utf-8 -*-
"""
loader.py
=========
Baca file-file log mesin absen mentah dan gabungkan jadi satu DataFrame.
REVISI v2: Ditambah fungsi baca file master karyawan, daftar tanggal merah,
dan deteksi nama tak dikenal.

Kenapa perlu deteksi header:
File asli yang sudah dicek TIDAK punya baris header (langsung data dari baris
pertama). Tapi supaya script tetap aman kalau suatu saat ada file dengan
header, kita deteksi otomatis: kalau kolom ke-4 (index 3, harusnya timestamp)
di baris pertama tidak bisa di-parse sebagai tanggal, anggap itu header dan
di-skip.
"""
import glob
import os
import pandas as pd
from . import config_runtime as config


def _looks_like_header(first_row_values):
    """Cek apakah baris pertama adalah header (bukan data timestamp asli)."""
    if len(first_row_values) < 4:
        return True
    kandidat_timestamp = first_row_values[3]
    try:
        pd.to_datetime(str(kandidat_timestamp), dayfirst=True)
        return False  # berhasil di-parse -> ini data, bukan header
    except (ValueError, TypeError):
        return True


def _baca_satu_file(path):
    """Baca satu file .xlsx / .csv / .xls, semua sheet kalau excel, kembalikan list DataFrame mentah."""
    hasil = []
    ext = os.path.splitext(path)[1].lower()

    if ext in (".xlsx", ".xlsm", ".xls"):
        semua_sheet = None
        # Coba auto-detect engine dulu
        try:
            semua_sheet = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
        except Exception:
            pass

        # Jika gagal (umum terjadi pada file .xls ekspor mesin absensi format BIFF mentah / HTML),
        # tentukan engine secara spesifik
        if semua_sheet is None:
            if ext == ".xls":
                try:
                    semua_sheet = pd.read_excel(path, sheet_name=None, header=None, dtype=str, engine="xlrd")
                except Exception:
                    # Alternatif: file .xls yang sebenarnya berformat HTML table
                    try:
                        df_list = pd.read_html(path)
                        semua_sheet = {f"Sheet{i+1}": d.astype(str) for i, d in enumerate(df_list)}
                    except Exception as e:
                        raise ValueError(f"Gagal membaca file .xls '{path}': {e}")
            else:
                try:
                    semua_sheet = pd.read_excel(path, sheet_name=None, header=None, dtype=str, engine="openpyxl")
                except Exception as e:
                    raise ValueError(f"Gagal membaca file Excel '{path}': {e}")

        for nama_sheet, df in semua_sheet.items():
            if df.empty:
                continue
            # Lewati sheet panduan / dokumentasi / keterangan bila ada
            sheet_lower = str(nama_sheet).strip().lower()
            if any(kwd in sheet_lower for kwd in ("panduan", "petunjuk", "readme", "keterangan", "template info", "format kolom")):
                continue
            baris_pertama = df.iloc[0].tolist()
            header_row = 0 if _looks_like_header(baris_pertama) else None
            if header_row == 0:
                df = df.iloc[1:].reset_index(drop=True)
            hasil.append((path, nama_sheet, df))
    elif ext == ".csv":
        df = pd.read_csv(path, header=None, dtype=str)
        baris_pertama = df.iloc[0].tolist()
        if _looks_like_header(baris_pertama):
            df = df.iloc[1:].reset_index(drop=True)
        hasil.append((path, "csv", df))
    else:
        raise ValueError(f"Format file tidak dikenali: {path}")

    return hasil


def load_raw_data(input_paths):
    """
    input_paths: bisa berupa:
      - path ke satu file
      - path ke folder (semua .xlsx/.xls/.csv di dalamnya akan dibaca)
      - list dari salah satu di atas

    Return: satu DataFrame mentah gabungan, kolom sesuai config.RAW_COLUMNS,
            plus kolom 'Sumber_File' untuk jejak audit.
    """
    if isinstance(input_paths, str):
        input_paths = [input_paths]

    file_list = []
    for p in input_paths:
        if os.path.isdir(p):
            file_list.extend(sorted(glob.glob(os.path.join(p, "*.xlsx"))))
            file_list.extend(sorted(glob.glob(os.path.join(p, "*.xls"))))
            file_list.extend(sorted(glob.glob(os.path.join(p, "*.csv"))))
        else:
            file_list.append(p)

    if not file_list:
        raise FileNotFoundError("Tidak ada file input yang ditemukan.")

    semua_df = []
    for path in file_list:
        for src_path, src_sheet, df in _baca_satu_file(path):
            n_kolom = df.shape[1]
            kolom_pakai = config.RAW_COLUMNS[:n_kolom] if n_kolom <= len(config.RAW_COLUMNS) else (
                config.RAW_COLUMNS + [f"Extra_{i}" for i in range(n_kolom - len(config.RAW_COLUMNS))]
            )
            df.columns = kolom_pakai
            df["Sumber_File"] = os.path.basename(src_path)
            df["Sumber_Sheet"] = src_sheet
            semua_df.append(df)

    gabungan = pd.concat(semua_df, ignore_index=True)
    # buang baris yang benar-benar kosong semua
    gabungan = gabungan.dropna(how="all", subset=[c for c in config.RAW_COLUMNS if c in gabungan.columns])
    return gabungan


# ===========================================================================
#  REVISI v2 — Loader untuk file master karyawan & tanggal merah
# ===========================================================================

def map_status_to_profil(status_raw):
    s = str(status_raw).lower()
    if "driver" in s: return "DRIVER"
    if "gudang" in s: return "GUDANG"
    if "office" in s: return "OFFICE"
    if "toko" in s: return "JAVAPETCO"
    if "marketing" in s: return "ANAK_KONTEN_MARKETING"
    if "host live" in s or "streaming" in s: return "ANAK_KONTEN_LIVE"
    if "setup" in s: return "SETUP_BLOK_C"
    if "opname" in s: return "GUDANG"
    return "OFFICE"

def load_master_karyawan(path):
    """
    Baca file master karyawan (Excel/CSV).
    Mendukung format 'Status', 'Nama', 'Uang Makan' 
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(path, dtype=str)
    else:
        df = pd.read_excel(path, dtype=str)

    # Normalisasi nama kolom (toleran terhadap spasi/kapital di header)
    df.columns = [c.strip() for c in df.columns]

    # Cari kolom wajib (case-insensitive)
    col_map = {}
    for col in df.columns:
        cl = col.lower().replace(" ", "_")
        if cl == "nama":
            col_map["Nama"] = col
        elif cl in ("profil", "status", "posisi"):
            col_map["Profil"] = col
        elif cl in ("uang_makan_override", "uang_makan"):
            col_map["Uang_Makan_Override"] = col

    if "Nama" not in col_map:
        raise ValueError(
            f"File master karyawan harus punya kolom 'Nama'. "
            f"Kolom yang ditemukan: {list(df.columns)}"
        )
    if "Profil" not in col_map:
        # Fallback if no Profil/Status column found, fake it
        df["_Profil_Dummy"] = "OFFICE"
        col_map["Profil"] = "_Profil_Dummy"

    hasil = pd.DataFrame()
    hasil["Nama_Asli"] = df[col_map["Nama"]].astype(str).str.strip()
    hasil["Nama_Normal"] = hasil["Nama_Asli"].apply(config.normalisasi_nama)
    
    # Map raw Status to valid Profil
    raw_profil = df[col_map["Profil"]]
    hasil["Profil"] = raw_profil.apply(map_status_to_profil)
    hasil["Status_Raw"] = raw_profil.astype(str).str.strip()

    # Uang makan override
    if "Uang_Makan_Override" in col_map:
        raw_uang = df[col_map["Uang_Makan_Override"]]
        hasil["Uang_Makan"] = pd.to_numeric(raw_uang, errors="coerce").fillna(config.UANG_MAKAN_DEFAULT).astype(int)
    else:
        hasil["Uang_Makan"] = config.UANG_MAKAN_DEFAULT

    # Buang baris dengan nama kosong
    hasil = hasil[hasil["Nama_Normal"] != ""].reset_index(drop=True)

    # Cek duplikat nama (setelah normalisasi)
    duplikat = hasil[hasil["Nama_Normal"].duplicated(keep=False)]
    if not duplikat.empty:
        nama_duplikat = duplikat["Nama_Asli"].unique().tolist()
        print(f"[PERINGATAN] Nama duplikat ditemukan di file master (setelah normalisasi): "
              f"{nama_duplikat}. Hanya entri TERAKHIR yang dipakai.")
        hasil = hasil.drop_duplicates(subset="Nama_Normal", keep="last").reset_index(drop=True)

    return hasil


def build_master_df_from_db(employees):
    """
    BARU (web version): bangun DataFrame master karyawan langsung dari daftar
    object model Employee (database), dengan bentuk output IDENTIK dengan
    yang dihasilkan load_master_karyawan() dari file Excel/CSV.

    employees: list of models.Employee (punya .nama, .profile_code, .uang_makan_override)
    """
    rows = []
    for emp in employees:
        if not emp.active:
            continue
        nama_asli = str(emp.nama).strip()
        rows.append({
            "Nama_Asli": nama_asli,
            "Nama_Normal": config.normalisasi_nama(nama_asli),
            "Profil": emp.profile_code,
            "Status_Raw": emp.profile_code,
            "Uang_Makan": emp.uang_makan_override if emp.uang_makan_override else config.UANG_MAKAN_DEFAULT,
        })
    df = pd.DataFrame(rows, columns=["Nama_Asli", "Nama_Normal", "Profil", "Status_Raw", "Uang_Makan"])
    df = df[df["Nama_Normal"] != ""].reset_index(drop=True)
    duplikat = df[df["Nama_Normal"].duplicated(keep=False)]
    if not duplikat.empty:
        df = df.drop_duplicates(subset="Nama_Normal", keep="last").reset_index(drop=True)
    return df


def build_tanggal_merah_from_db(holidays):
    """BARU (web version): bangun dict tanggal merah dari list model Holiday (DB)."""
    return {h.tanggal: (h.keterangan or "") for h in holidays}


def load_tanggal_merah(path):
    """
    Baca daftar tanggal merah nasional dari file Excel/CSV.
    Kolom wajib: Tanggal
    Kolom opsional: Keterangan

    Return: dict {datetime.date: str_keterangan}
    """
    if not os.path.exists(path):
        print(f"[INFO] File tanggal merah tidak ditemukan di: {path}. "
              f"Semua hari dianggap hari biasa (tidak ada tanggal merah).")
        return {}

    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(path, dtype=str)
    else:
        df = pd.read_excel(path)

    # Normalisasi nama kolom
    df.columns = [c.strip() for c in df.columns]

    # Cari kolom Tanggal (case-insensitive)
    col_tanggal = None
    col_keterangan = None
    for col in df.columns:
        cl = col.lower().strip()
        if cl == "tanggal":
            col_tanggal = col
        elif cl == "keterangan":
            col_keterangan = col

    if col_tanggal is None:
        raise ValueError(
            f"File tanggal merah harus punya kolom 'Tanggal'. "
            f"Kolom yang ditemukan: {list(df.columns)}"
        )

    df["_tanggal_parsed"] = pd.to_datetime(df[col_tanggal], dayfirst=True, errors="coerce")
    gagal = df["_tanggal_parsed"].isna().sum()
    if gagal > 0:
        print(f"[PERINGATAN] {gagal} baris di file tanggal merah gagal di-parse tanggalnya.")
    df = df.dropna(subset=["_tanggal_parsed"])

    hasil = {}
    for _, row in df.iterrows():
        tgl = row["_tanggal_parsed"].date()
        ket = str(row[col_keterangan]).strip() if col_keterangan and pd.notna(row.get(col_keterangan)) else ""
        hasil[tgl] = ket

    return hasil


def build_master_dict(df_master):
    """
    Dari DataFrame master karyawan, bangun dict untuk lookup cepat:
      nama_normal -> {
          "Nama_Asli": str,
          "Profil": str,
          "Uang_Makan": int,
      }
    """
    master_dict = {}
    for _, row in df_master.iterrows():
        master_dict[row["Nama_Normal"]] = {
            "Nama_Asli": row["Nama_Asli"],
            "Profil": row["Profil"],
            "Uang_Makan": row["Uang_Makan"],
            "Status_Raw": row.get("Status_Raw", ""),
        }
    return master_dict


def cari_nama_tidak_dikenal(df_absensi, master_dict):
    """
    Cari nama-nama di data absensi yang TIDAK ada di file master karyawan.

    df_absensi  : DataFrame mentah atau preprocessing (harus ada kolom 'Nama')
    master_dict : dict dari build_master_dict()

    Return: DataFrame dengan kolom [Nama, Cabang, Jumlah_Scan] —
            nama yang tidak ketemu, sorted by jumlah scan (terbanyak di atas).
    """
    df = df_absensi.copy()
    df["_nama_normal"] = df["Nama"].apply(config.normalisasi_nama)

    nama_master = set(master_dict.keys())
    mask_tidak_dikenal = ~df["_nama_normal"].isin(nama_master)

    if not mask_tidak_dikenal.any():
        return pd.DataFrame(columns=["Nama", "Cabang", "Jumlah_Scan"])

    df_asing = df[mask_tidak_dikenal]

    # Agregasi: per nama asli, cabang dominan, jumlah scan
    hasil = (
        df_asing.groupby("Nama")
        .agg(
            Cabang=("Cabang", lambda s: s.value_counts().idxmax() if len(s) > 0 else ""),
            Jumlah_Scan=("Nama", "count"),
        )
        .reset_index()
        .sort_values("Jumlah_Scan", ascending=False)
        .reset_index(drop=True)
    )
    return hasil
