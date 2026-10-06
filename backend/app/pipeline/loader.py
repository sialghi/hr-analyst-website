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
import re
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
        hasil["Uang_Makan"] = pd.to_numeric(raw_uang, errors="coerce").fillna(0).astype(int)
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
            "Uang_Makan": (
                emp.uang_makan_override
                if emp.uang_makan_override is not None
                else config.UANG_MAKAN_DEFAULT
            ),
            "BPJS_Kesehatan": getattr(emp, "bpjs_kesehatan", 0) or 0,
            "BPJS_TK": getattr(emp, "bpjs_tk", 0) or 0,
        })
    df = pd.DataFrame(rows, columns=["Nama_Asli", "Nama_Normal", "Profil", "Status_Raw", "Uang_Makan", "BPJS_Kesehatan", "BPJS_TK"])
    df = df[df["Nama_Normal"] != ""].reset_index(drop=True)
    duplikat = df[df["Nama_Normal"].duplicated(keep=False)]
    if not duplikat.empty:
        df = df.drop_duplicates(subset="Nama_Normal", keep="last").reset_index(drop=True)
    return df


def build_tanggal_merah_from_db(holidays):
    """BARU (web version): bangun dict tanggal merah dari list model Holiday (DB)."""
    return {h.tanggal: (h.keterangan or "") for h in holidays}


def build_approved_leaves_from_db(leaves):
    """
    BARU: Bangun dict lookup cuti & izin yang disetujui (APPROVED).
    Format return:
    {
       normalisasi_nama(nama): [
           {
               "kategori": leave.kategori,
               "tanggal_mulai": leave.tanggal_mulai,
               "tanggal_selesai": leave.tanggal_selesai,
               "jam_izin": leave.jam_izin,
               "alasan": leave.alasan,
           },
           ...
       ]
    }
    """
    lookup = {}
    for lv in leaves:
        if lv.status != "APPROVED":
            continue
        norm_name = config.normalisasi_nama(lv.nama)
        if not norm_name:
            continue
        if norm_name not in lookup:
            lookup[norm_name] = []
        lookup[norm_name].append({
            "kategori": lv.kategori,
            "tanggal_mulai": lv.tanggal_mulai,
            "tanggal_selesai": lv.tanggal_selesai,
            "jam_izin": lv.jam_izin,
            "alasan": lv.alasan,
        })
    return lookup



def build_bpjs_dict(path: str) -> dict:
    """
    Baca file BPJS (Excel/CSV) dan bangun dict lookup potongan BPJS per karyawan.

    Kolom yang dicari (case-insensitive, toleran spasi):
      - 'Nama Tenaga Kerja' (atau variasi: 'Nama', 'Nama Karyawan')
      - 'Potongan BPJS Kesehatan' (atau 'BPJS Kesehatan', 'Kesehatan')
      - 'Potongan BPJS TK'       (atau 'BPJS TK', 'Jamsostek')

    Return:
      {
        normalisasi_nama(nama): {
            "bpjs_kesehatan": int,
            "bpjs_tk": int,
        },
        ...
      }
    Jika file tidak ditemukan atau kolom tidak dikenali, return dict kosong.
    """
    if not path or not os.path.exists(path):
        return {}

    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv":
            df = pd.read_csv(path)
        else:
            df = pd.read_excel(path)
    except Exception as e:
        print(f"[BPJS] Gagal membaca file '{path}': {e}")
        return {}

    df.columns = [str(c).strip() for c in df.columns]

    # Deteksi kolom nama & BPJS secara fleksibel (case-insensitive)
    col_nama = None
    col_kesehatan = None
    col_tk = None
    for col in df.columns:
        cl = col.lower().replace(" ", "_")
        if col_nama is None and any(k in cl for k in ("nama_tenaga_kerja", "nama_karyawan", "nama")):
            col_nama = col
        if col_kesehatan is None and "kesehatan" in cl:
            col_kesehatan = col
        if col_tk is None and ("_tk" in cl or "jamsostek" in cl or cl == "bpjs_tk" or cl == "potongan_bpjs_tk"):
            col_tk = col

    if col_nama is None or col_kesehatan is None or col_tk is None:
        print(f"[BPJS] Kolom tidak lengkap di '{path}'. "
              f"Ditemukan: {list(df.columns)}. Butuh kolom Nama, BPJS Kesehatan, BPJS TK.")
        return {}

    hasil = {}
    for _, row in df.iterrows():
        nama_raw = row.get(col_nama)
        if nama_raw is None or (isinstance(nama_raw, float) and pd.isna(nama_raw)):
            continue
        nama_raw = str(nama_raw).strip()
        if not nama_raw:
            continue
        norm = config.normalisasi_nama(nama_raw)
        if not norm:
            continue
        try:
            kes = int(float(str(row[col_kesehatan]).replace(",", "").strip() or 0))
        except (ValueError, TypeError):
            kes = 0
        try:
            tk = int(float(str(row[col_tk]).replace(",", "").strip() or 0))
        except (ValueError, TypeError):
            tk = 0
        info = {"bpjs_kesehatan": kes, "bpjs_tk": tk}
        hasil[norm] = info

        # Tambahkan varian nama (misal m. -> muhammad, pembersihan tanda baca)
        clean = re.sub(r'\bm[\.\s]+', 'muhammad ', norm)
        clean = re.sub(r'[^a-z0-9\s]', '', clean).strip()
        clean = re.sub(r'\s+', ' ', clean)
        if clean and clean not in hasil:
            hasil[clean] = info

    return hasil


def get_bpjs_info(bpjs_dict: dict, nama_master: str, master_dict: dict = None) -> dict:
    """
    Cari informasi BPJS (Kesehatan & TK) untuk nama_master dari bpjs_dict.
    Jika tidak ada di bpjs_dict (file BPJS), fallback ke data master DB (master_dict).
    """
    res = {}
    if bpjs_dict and nama_master:
        norm = config.normalisasi_nama(nama_master)
        if norm in bpjs_dict:
            res = bpjs_dict[norm]
        else:
            clean = re.sub(r'\bm[\.\s]+', 'muhammad ', norm)
            clean = re.sub(r'[^a-z0-9\s]', '', clean).strip()
            clean = re.sub(r'\s+', ' ', clean)
            if clean in bpjs_dict:
                res = bpjs_dict[clean]
            else:
                tokens_master = set(clean.split())
                if len(tokens_master) >= 2:
                    for k, v in bpjs_dict.items():
                        tokens_k = set(k.split())
                        if len(tokens_k) >= 2 and (tokens_master.issubset(tokens_k) or tokens_k.issubset(tokens_master)):
                            res = v
                            break

                if not res and len(clean) >= 8:
                    from difflib import SequenceMatcher
                    for k, v in bpjs_dict.items():
                        if len(k) >= 8 and SequenceMatcher(None, clean, k).ratio() >= 0.88:
                            res = v
                            break

    if res and (res.get("bpjs_kesehatan", 0) or res.get("bpjs_tk", 0)):
        return res

    # Fallback: ambil data BPJS dari DB master jika tersimpan
    if master_dict and nama_master:
        norm = config.normalisasi_nama(nama_master)
        if norm in master_dict:
            m_info = master_dict[norm]
            return {
                "bpjs_kesehatan": m_info.get("BPJS_Kesehatan", 0) or res.get("bpjs_kesehatan", 0),
                "bpjs_tk": m_info.get("BPJS_TK", 0) or res.get("bpjs_tk", 0),
            }

    return res or {"bpjs_kesehatan": 0, "bpjs_tk": 0}



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
          "BPJS_Kesehatan": int,
          "BPJS_TK": int,
      }
    """
    master_dict = {}
    for _, row in df_master.iterrows():
        master_dict[row["Nama_Normal"]] = {
            "Nama_Asli": row["Nama_Asli"],
            "Profil": row["Profil"],
            "Uang_Makan": row["Uang_Makan"],
            "Status_Raw": row.get("Status_Raw", ""),
            "BPJS_Kesehatan": row.get("BPJS_Kesehatan", 0) or 0,
            "BPJS_TK": row.get("BPJS_TK", 0) or 0,
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


def build_remote_absences_from_db(db) -> dict:
    """
    BARU: Bangun dict lookup Absensi Jarak Jauh yang sudah APPROVED untuk digunakan pipeline.

    Hanya memuat LeaveRequest dengan:
      - kategori  = "WORK_FROM_LOCATION"
      - status    = "APPROVED"

    Return format:
    {
        normalisasi_nama(nama): [
            {
                "tanggal"  : datetime.date,   # setiap tanggal dalam range mulai..selesai
                "cabang"   : str,             # location_cabang
                "alasan"   : str,
                "leave_id" : int,
            },
            ...
        ]
    }
    Satu entry per *hari* (range di-expand), sehingga pipeline tinggal cek per tanggal.
    """
    import datetime as _dt
    from .. import models as _models

    rows = db.query(_models.LeaveRequest).filter(
        _models.LeaveRequest.kategori == "WORK_FROM_LOCATION",
        _models.LeaveRequest.status == "APPROVED",
    ).all()

    lookup: dict = {}
    for lv in rows:
        norm_name = config.normalisasi_nama(lv.nama)
        if not norm_name:
            continue
        if norm_name not in lookup:
            lookup[norm_name] = []

        # Expand range tanggal_mulai..tanggal_selesai menjadi per-hari
        delta = (lv.tanggal_selesai - lv.tanggal_mulai).days
        for d in range(delta + 1):
            tgl = lv.tanggal_mulai + _dt.timedelta(days=d)
            lookup[norm_name].append({
                "tanggal"   : tgl,
                "cabang"    : lv.location_cabang or "",
                "alasan"    : lv.alasan or "",
                "leave_id"  : lv.id,
                "_nama_asli": str(lv.nama).strip(),
            })

    return lookup
