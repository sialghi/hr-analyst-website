# -*- coding: utf-8 -*-
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=list[schemas.EmployeeOut])
def list_employees(
    profile_code: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    q = db.query(models.Employee)
    if profile_code:
        q = q.filter(models.Employee.profile_code == profile_code)
    return q.order_by(models.Employee.nama).all()


@router.post("", response_model=schemas.EmployeeOut)
def create_employee(
    payload: schemas.EmployeeCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """HANYA HR Master yang boleh menambahkan karyawan baru ke suatu profil."""
    profile = db.query(models.Profile).filter(models.Profile.code == payload.profile_code).first()
    if not profile:
        raise HTTPException(status_code=400, detail=f"Profil '{payload.profile_code}' tidak ditemukan.")

    emp = models.Employee(**payload.dict())
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@router.put("/{employee_id}", response_model=schemas.EmployeeOut)
def update_employee(
    employee_id: int,
    payload: schemas.EmployeeUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    emp = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan.")

    profile = db.query(models.Profile).filter(models.Profile.code == payload.profile_code).first()
    if not profile:
        raise HTTPException(status_code=400, detail=f"Profil '{payload.profile_code}' tidak ditemukan.")

    for field, value in payload.dict().items():
        setattr(emp, field, value)
    db.commit()
    db.refresh(emp)
    return emp


@router.delete("/{employee_id}")
def delete_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    emp = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan.")
    db.delete(emp)
    db.commit()
    return {"status": "sukses"}


# ---------------------------------------------------------------------------
# Helper: memetakan nilai kolom 'Status' dari file xlsx ke kode profil DB
# Sesuai data-uangmakan-posisi.xlsx yang punya nilai:
#   Gudang C, Gudang A, Gudang Bandung, Office A, Office C, Office Bandung,
#   Toko GLC, Toko Tanjung Duren, Toko IDD/PIK, Toko Reef Plus/PIK, Toko Ciledug,
#   Content Marketing, Host Live Streaming, Setup, Staff Stock Opname, Driver Java Cipulir
# ---------------------------------------------------------------------------
def _map_status_detail(status_raw: str) -> str:
    """Mapping Status (dari file Excel asli) → kode profil database."""
    s = str(status_raw).strip().lower()
    if "driver" in s:           return "DRIVER"
    if "gudang" in s:           return "GUDANG"
    if "office" in s:           return "OFFICE"
    if "toko" in s:             return "JAVAPETCO"
    if "marketing" in s:        return "ANAK_KONTEN_MARKETING"
    if "host live" in s or "live streaming" in s or "streaming" in s:
                                return "ANAK_KONTEN_LIVE"
    if "setup" in s:            return "SETUP_BLOK_C"
    if "opname" in s:           return "GUDANG"
    if "content" in s:          return "ANAK_KONTEN_MARKETING"
    return "OFFICE"


def _extract_cabang_from_status(status_raw: str) -> str | None:
    """
    Ekstrak cabang secara otomatis dari nilai Status.
    Contoh:
      'Gudang C'          → 'BLOK C'
      'Gudang A'          → 'BLOK A'
      'Gudang Bandung'    → 'BANDUNG'
      'Office C'          → 'BLOK C'
      'Office A'          → 'BLOK A'
      'Office Bandung'    → 'BANDUNG'
      'Toko GLC'          → 'GREENLAKE CITY'
      'Toko Tanjung Duren'→ 'TANJUNG DUREN'
      'Toko IDD/PIK'      → 'PIK'
      'Toko Reef Plus/PIK'→ 'REEF+/PIK'
      'Toko Ciledug'      → 'CILEDUG'
      'Driver Java Cipulir'→ 'JAVA CIPULIR'
    """
    s = str(status_raw).strip().lower()

    # Gudang
    if s == "gudang c":             return "BLOK C"
    if s == "gudang a":             return "BLOK A"
    if "gudang bandung" in s:       return "BANDUNG"
    if "gudang" in s:               return None          # gudang tanpa keterangan

    # Office
    if s == "office c":             return "BLOK C"
    if s == "office a":             return "BLOK A"
    if "office bandung" in s:       return "BANDUNG"
    if "office" in s:               return None

    # Toko (JAVAPETCO)
    if "glc" in s or "greenlake" in s:       return "GREENLAKE CITY"
    if "tanjung duren" in s:                  return "TANJUNG DUREN"
    if "idd" in s or ("pik" in s and "reef" not in s):  return "PIK"
    if "reef" in s:                           return "REEF+/PIK"
    if "ciledug" in s:                        return "CILEDUG"
    if "kebayoran" in s:                      return "KEBAYORAN LAMA"
    if "toko" in s:                           return None

    # Driver
    if "cipulir" in s:              return "JAVA CIPULIR"
    if "driver" in s:               return None

    return None


@router.get("/template")
def download_employee_template(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """Mengunduh file Excel template untuk import master karyawan."""
    import io
    import pandas as pd
    from fastapi.responses import Response

    # Ambil semua kode profil yang aktif untuk referensi
    profiles = db.query(models.Profile).order_by(models.Profile.code).all()

    # Template data contoh — format IDENTIK dengan file data-uangmakan-posisi.xlsx
    # Kolom: Status, Nama, Uang Makan, Gaji Pokok
    data = [
        {"Status": "Office A",          "Nama": "Budi Santoso",          "Uang Makan": 100000, "Gaji Pokok": ""},
        {"Status": "Gudang A",          "Nama": "Siti Aminah",           "Uang Makan": 80000,  "Gaji Pokok": ""},
        {"Status": "Gudang C",          "Nama": "Ahmad Fauzi",           "Uang Makan": 45000,  "Gaji Pokok": ""},
        {"Status": "Gudang Bandung",    "Nama": "Reni Kusuma",           "Uang Makan": 50000,  "Gaji Pokok": ""},
        {"Status": "Office C",          "Nama": "Dewi Rahayu",           "Uang Makan": 75000,  "Gaji Pokok": ""},
        {"Status": "Office Bandung",    "Nama": "Irfan Wijaya",          "Uang Makan": 75000,  "Gaji Pokok": ""},
        {"Status": "Toko GLC",          "Nama": "Bagus Setiawan",        "Uang Makan": 40000,  "Gaji Pokok": ""},
        {"Status": "Toko Tanjung Duren","Nama": "Agung Nugroho",         "Uang Makan": "",     "Gaji Pokok": ""},
        {"Status": "Toko IDD/PIK",      "Nama": "Aulia Putri",           "Uang Makan": 65000,  "Gaji Pokok": ""},
        {"Status": "Toko Reef Plus/PIK","Nama": "Andry Saputra",         "Uang Makan": 55000,  "Gaji Pokok": ""},
        {"Status": "Toko Ciledug",      "Nama": "Edi Kuswanto",          "Uang Makan": "",     "Gaji Pokok": ""},
        {"Status": "Content Marketing", "Nama": "Fahrul Azi",            "Uang Makan": 100000, "Gaji Pokok": ""},
        {"Status": "Host Live Streaming","Nama": "Intan Melani",          "Uang Makan": 60000,  "Gaji Pokok": ""},
        {"Status": "Setup",             "Nama": "Karlina",               "Uang Makan": 60000,  "Gaji Pokok": ""},
        {"Status": "Staff Stock Opname","Nama": "Hamdani",               "Uang Makan": 90000,  "Gaji Pokok": ""},
        {"Status": "Driver Java Cipulir","Nama": "Harry",                "Uang Makan": "",     "Gaji Pokok": ""},
    ]
    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="HO")
        # Sheet referensi pemetaan Status → Profil DB
        mapping_data = [
            {"Nilai Status di File": "Gudang A / Gudang C / Gudang Bandung", "Profil di Database": "GUDANG",               "Keterangan": "Semua varian Gudang"},
            {"Nilai Status di File": "Office A / Office C / Office Bandung",  "Profil di Database": "OFFICE",               "Keterangan": "Semua varian Office"},
            {"Nilai Status di File": "Toko GLC / Toko Tanjung Duren / Toko IDD/PIK / Toko Reef Plus/PIK / Toko Ciledug", "Profil di Database": "JAVAPETCO", "Keterangan": "Semua varian Toko"},
            {"Nilai Status di File": "Content Marketing",                     "Profil di Database": "ANAK_KONTEN_MARKETING","Keterangan": ""},
            {"Nilai Status di File": "Host Live Streaming",                   "Profil di Database": "ANAK_KONTEN_LIVE",    "Keterangan": ""},
            {"Nilai Status di File": "Setup",                                 "Profil di Database": "SETUP_BLOK_C",        "Keterangan": ""},
            {"Nilai Status di File": "Staff Stock Opname",                    "Profil di Database": "GUDANG",               "Keterangan": "Diperlakukan sbg Gudang"},
            {"Nilai Status di File": "Driver Java Cipulir",                   "Profil di Database": "DRIVER",               "Keterangan": ""},
        ]
        df_mapping = pd.DataFrame(mapping_data)
        df_mapping.to_excel(writer, index=False, sheet_name="Mapping Status ke Profil")
        # Sheet daftar profil tersedia di DB
        df_profil = pd.DataFrame([{"Kode Profil": p.code, "Nama Profil": p.nama} for p in profiles])
        df_profil.to_excel(writer, index=False, sheet_name="Daftar Profil DB")

    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="template_karyawan.xlsx"'
        },
    )


@router.post("/import")
async def import_employees(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """
    Import karyawan dari file Excel (.xlsx, .xls) atau CSV (.csv).
    Mendukung penambahan karyawan baru sekaligus update data jika nama sudah terdaftar.
    """
    import io
    import os
    import pandas as pd
    from ..pipeline.loader import map_status_to_profil

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(
            status_code=400,
            detail="Format file tidak didukung. Harap unggah file .xlsx, .xls, atau .csv",
        )

    try:
        contents = await file.read()
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(contents), dtype=str)
        else:
            df = pd.read_excel(io.BytesIO(contents), dtype=str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal membaca file: {str(e)}")

    if df.empty:
        raise HTTPException(status_code=400, detail="File kosong tidak memiliki data.")

    # -----------------------------------------------------------------------
    # Normalisasi nama kolom — toleran terhadap spasi trailing & variasi nama
    # Format utama yang didukung: Status | Nama | Uang Makan | Gaji Pokok
    # (sesuai file data-uangmakan-posisi.xlsx)
    # -----------------------------------------------------------------------
    col_map = {}
    for col in df.columns:
        cl = str(col).strip().lower().replace(" ", "_")
        if cl in ("nama", "nama_karyawan", "nama_lengkap", "name", "employee_name"):
            col_map["nama"] = col
        elif cl in ("status", "profil", "profile", "profile_code", "divisi", "posisi", "role"):
            col_map["profil"] = col
        elif cl in ("cabang", "branch", "lokasi", "site"):
            col_map["cabang"] = col
        elif cl in ("id_mesin", "id_mesin_absen", "pin", "no_mesin", "machine_id"):
            col_map["id_mesin"] = col
        elif cl in ("uang_makan", "uang_makan_", "uang_makan_override", "uangmakan", "uang_makan_khusus"):
            col_map["uang_makan"] = col
        elif cl in ("active", "aktif", "status_aktif", "is_active"):
            col_map["active"] = col
        # Kolom Gaji Pokok dari file asli — diabaikan saja, tidak disimpan ke DB

    if "nama" not in col_map:
        raise HTTPException(
            status_code=400,
            detail=f"File harus memiliki kolom 'Nama'. Kolom ditemukan: {list(df.columns)}",
        )

    # Ambil profil dan default rule dari DB
    profiles = db.query(models.Profile).all()
    valid_codes = {p.code.strip().upper(): p.code for p in profiles}
    name_to_code = {p.nama.strip().lower(): p.code for p in profiles}

    rule = db.query(models.BusinessRule).first()
    default_profile_code = rule.profil_default if rule and rule.profil_default in valid_codes else (
        profiles[0].code if profiles else "OFFICE"
    )

    # Cache existing employees by lowercase stripped name
    existing_employees = {emp.nama.strip().lower(): emp for emp in db.query(models.Employee).all()}

    total_rows = 0
    inserted = 0
    updated = 0
    skipped = 0
    errors = []

    for idx, row in df.iterrows():
        row_num = idx + 2  # baris Excel 1-based (header di baris 1)
        raw_nama = row.get(col_map["nama"])
        if pd.isna(raw_nama) or not str(raw_nama).strip():
            skipped += 1
            continue

        nama = str(raw_nama).strip()
        # Buang baris yang terlihat seperti header atau placeholder
        if nama.lower() in ("live stream", "nama", "nama karyawan"):
            skipped += 1
            continue

        total_rows += 1
        raw_status = ""

        # Tentukan profil & ekstrak cabang otomatis dari nilai Status
        profile_code = default_profile_code
        cabang_dari_status = None

        if "profil" in col_map and pd.notna(row.get(col_map["profil"])):
            raw_status = str(row[col_map["profil"]]).strip()
            prof_upper = raw_status.upper()
            prof_lower = raw_status.lower()

            if prof_upper in valid_codes:
                profile_code = valid_codes[prof_upper]
            elif prof_lower in name_to_code:
                profile_code = name_to_code[prof_lower]
            else:
                mapped = _map_status_detail(raw_status)
                if mapped in valid_codes:
                    profile_code = mapped
                else:
                    profile_code = default_profile_code

            # Ekstrak cabang dari nilai Status secara otomatis
            cabang_dari_status = _extract_cabang_from_status(raw_status)

        # Cabang: pakai kolom Cabang jika ada, fallback ke hasil ekstrak dari Status
        cabang = cabang_dari_status
        if "cabang" in col_map and pd.notna(row.get(col_map["cabang"])):
            c = str(row[col_map["cabang"]]).strip()
            if c:
                cabang = c

        # ID Mesin
        id_mesin = None
        if "id_mesin" in col_map and pd.notna(row.get(col_map["id_mesin"])):
            m = str(row[col_map["id_mesin"]]).strip()
            id_mesin = m if m else None

        # Uang Makan Override — baca dari kolom 'Uang Makan' (format angka)
        uang_makan_override = None
        if "uang_makan" in col_map and pd.notna(row.get(col_map["uang_makan"])):
            raw_um = str(row[col_map["uang_makan"]]).strip()
            # Bersihkan titik/koma sebagai pemisah ribuan
            raw_um_clean = raw_um.replace(",", "").replace(".", "").replace(" ", "")
            try:
                val = int(float(raw_um_clean)) if raw_um_clean else None
                if val is not None and val >= 0:
                    uang_makan_override = val
            except (ValueError, OverflowError):
                uang_makan_override = None

        # Active
        active = True
        if "active" in col_map and pd.notna(row.get(col_map["active"])):
            raw_act = str(row[col_map["active"]]).strip().lower()
            if raw_act in ("false", "0", "tidak", "nonaktif", "no", "off"):
                active = False

        nama_key = nama.lower()
        if nama_key in existing_employees:
            emp = existing_employees[nama_key]
            emp.profile_code = profile_code
            if cabang is not None:
                emp.cabang = cabang
            if id_mesin is not None:
                emp.id_mesin = id_mesin
            emp.uang_makan_override = uang_makan_override
            emp.active = active
            updated += 1
        else:
            new_emp = models.Employee(
                nama=nama,
                profile_code=profile_code,
                cabang=cabang,
                id_mesin=id_mesin,
                uang_makan_override=uang_makan_override,
                active=active,
            )
            db.add(new_emp)
            existing_employees[nama_key] = new_emp
            inserted += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan ke database: {str(e)}")

    return {
        "status": "sukses",
        "total": total_rows,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "pesan": f"Berhasil memproses {total_rows} karyawan: {inserted} baru, {updated} diperbarui.",
    }

