# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/holidays", tags=["holidays"])


@router.get("", response_model=list[schemas.HolidayOut])
def list_holidays(db: Session = Depends(get_db), _: models.User = Depends(auth.get_current_user)):
    return db.query(models.Holiday).order_by(models.Holiday.tanggal).all()


@router.post("", response_model=schemas.HolidayOut)
def add_holiday(
    payload: schemas.HolidayCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    existing = db.query(models.Holiday).filter(models.Holiday.tanggal == payload.tanggal).first()
    if existing:
        raise HTTPException(status_code=400, detail="Tanggal tsb sudah terdaftar sebagai tanggal merah.")
    h = models.Holiday(**payload.dict())
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


@router.delete("/{holiday_id}")
def delete_holiday(holiday_id: int, db: Session = Depends(get_db), _: models.User = Depends(auth.require_hr_master)):
    h = db.query(models.Holiday).filter(models.Holiday.id == holiday_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Tanggal merah tidak ditemukan.")
    db.delete(h)
    db.commit()
    return {"status": "sukses"}


@router.get("/template")
def download_holiday_template(
    _: models.User = Depends(auth.require_hr_master),
):
    """Mengunduh file Excel template untuk import tanggal merah."""
    import io
    import pandas as pd
    from fastapi.responses import Response

    data = [
        {"Tanggal": "2026-01-01", "Keterangan": "Tahun Baru Masehi"},
        {"Tanggal": "2026-03-31", "Keterangan": "Hari Raya Idul Fitri 1447 H"},
        {"Tanggal": "2026-05-01", "Keterangan": "Hari Buruh Internasional"},
        {"Tanggal": "2026-08-17", "Keterangan": "Hari Kemerdekaan RI"},
        {"Tanggal": "2026-12-25", "Keterangan": "Hari Raya Natal"},
    ]
    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Tanggal Merah")

    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="template_tanggal_merah.xlsx"'
        },
    )


@router.post("/import")
async def import_holidays(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """
    Import daftar tanggal merah dari file Excel (.xlsx, .xls) atau CSV (.csv).
    Mendukung format tanggal YYYY-MM-DD maupun DD/MM/YYYY.
    Jika tanggal sudah ada, keterangan akan diperbarui. Jika belum ada, akan ditambahkan.
    """
    import io
    import os
    import pandas as pd

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
            df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal membaca file: {str(e)}")

    if df.empty:
        raise HTTPException(status_code=400, detail="File kosong tidak memiliki data.")

    # Normalisasi kolom
    col_tanggal = None
    col_keterangan = None
    for col in df.columns:
        cl = str(col).strip().lower().replace(" ", "_")
        if cl in ("tanggal", "date", "tgl", "hari_libur", "libur"):
            col_tanggal = col
        elif cl in ("keterangan", "deskripsi", "nama_libur", "description", "ket", "event"):
            col_keterangan = col

    if not col_tanggal:
        raise HTTPException(
            status_code=400,
            detail=f"File harus memiliki kolom 'Tanggal'. Kolom ditemukan: {list(df.columns)}",
        )

    # Parse tanggal
    parsed_dates = pd.to_datetime(df[col_tanggal], dayfirst=True, errors="coerce")

    total_rows = 0
    inserted = 0
    updated = 0
    skipped = 0
    errors = []

    for idx, (p_date, orig_date) in enumerate(zip(parsed_dates, df[col_tanggal])):
        row_num = idx + 2
        if pd.isna(p_date):
            if pd.notna(orig_date) and str(orig_date).strip():
                errors.append(f"Baris {row_num}: Format tanggal '{orig_date}' tidak dapat dikenali.")
            skipped += 1
            continue

        tgl = p_date.date()
        total_rows += 1

        ket = None
        if col_keterangan and pd.notna(df.iloc[idx][col_keterangan]):
            k_val = str(df.iloc[idx][col_keterangan]).strip()
            ket = k_val if k_val else None

        existing = db.query(models.Holiday).filter(models.Holiday.tanggal == tgl).first()
        if existing:
            if ket is not None:
                existing.keterangan = ket
            updated += 1
        else:
            h = models.Holiday(tanggal=tgl, keterangan=ket)
            db.add(h)
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
        "pesan": f"Berhasil memproses {total_rows} tanggal merah: {inserted} baru, {updated} diperbarui.",
    }

