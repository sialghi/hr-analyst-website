# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..pipeline.service import jalankan_pipeline_db, jalankan_pipeline_db_json

router = APIRouter(tags=["process"])

API_KEY = os.environ.get("API_KEY")
ALLOWED_EXT = (".xlsx", ".xls", ".csv")

# In-memory store untuk file hasil proses (file_id -> {path, filename})
# Untuk production: gunakan Redis/S3/database. Cukup untuk skala kecil ini.
_file_store: dict[str, dict] = {}


def _cek_api_key(x_api_key):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API key tidak valid atau tidak ada.")


def _simpan_upload(f: UploadFile, folder: str, nama_file: str = None) -> str:
    ekstensi = os.path.splitext(f.filename or "")[1].lower()
    if ekstensi not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"File '{f.filename}' harus berformat .xlsx/.xls/.csv")
    path_tujuan = os.path.join(folder, nama_file or f.filename)
    with open(path_tujuan, "wb") as out:
        shutil.copyfileobj(f.file, out)
    return path_tujuan


def _jalankan_dan_kirim(files, db: Session, master_karyawan: UploadFile = None, tanggal_merah_override: UploadFile = None):
    if not files:
        raise HTTPException(status_code=400, detail="Tidak ada file absensi yang dikirim.")

    folder_kerja = tempfile.mkdtemp(prefix="hr_pipeline_")
    try:
        path_input_list = [_simpan_upload(f, folder_kerja) for f in files]

        path_master = None
        if master_karyawan:
            ext = os.path.splitext(master_karyawan.filename or "")[1].lower()
            path_master = _simpan_upload(master_karyawan, folder_kerja, f"master_karyawan{ext}")

        path_tgl_merah = None
        if tanggal_merah_override:
            ext = os.path.splitext(tanggal_merah_override.filename or "")[1].lower()
            path_tgl_merah = _simpan_upload(tanggal_merah_override, folder_kerja, f"tgl_merah_override{ext}")

        nama_dasar = os.path.splitext(files[0].filename or "")[0] if files else "Absensi"
        nama_download = f"Report Hasil_{nama_dasar}.xlsx"
        path_output = os.path.join(folder_kerja, f"Report_Hasil_{uuid.uuid4().hex[:8]}.xlsx")

        try:
            jalankan_pipeline_db(
                daftar_input=path_input_list,
                path_output=path_output,
                db=db,
                override_master_path=path_master,
                override_tanggal_merah_path=path_tgl_merah,
                verbose=False,
            )
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Gagal memproses data: {e}")

        return FileResponse(
            path_output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=nama_download,
        )
    finally:
        pass  # folder_kerja sengaja tidak dihapus langsung, biar FileResponse sempat mengirim filenya


# ===========================================================================
# 1) ENDPOINT MANUAL DARI WEB — mengembalikan JSON lengkap + file_id download
# ===========================================================================

@router.post("/proses-absensi-manual")
async def proses_absensi_manual(
    files: list[UploadFile] = File(..., description="Satu atau lebih file absensi mentah"),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Upload manual lewat web: master karyawan & tanggal merah otomatis dari database.
    Mengembalikan JSON terstruktur lengkap dengan data 14 sheet + file_id untuk download Excel.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Tidak ada file absensi yang dikirim.")

    folder_kerja = tempfile.mkdtemp(prefix="hr_pipeline_")
    path_input_list = [_simpan_upload(f, folder_kerja) for f in files]

    nama_dasar = os.path.splitext(files[0].filename or "")[0] if files else "Absensi"
    nama_download = f"Report Hasil_{nama_dasar}.xlsx"
    file_id = uuid.uuid4().hex
    path_output = os.path.join(folder_kerja, f"Report_Hasil_{file_id[:8]}.xlsx")

    try:
        result_data, _ = jalankan_pipeline_db_json(
            daftar_input=path_input_list,
            path_output=path_output,
            db=db,
            verbose=False,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Gagal memproses data: {e}")

    # Simpan referensi file untuk download nanti
    _file_store[file_id] = {"path": path_output, "filename": nama_download}

    # Tambahkan file_id & filename ke response
    result_data["file_id"] = file_id
    result_data["filename"] = nama_download

    return JSONResponse(content=result_data)


@router.get("/proses/download/{file_id}")
async def download_hasil_proses(
    file_id: str,
    _: models.User = Depends(auth.get_current_user),
):
    """Download file Excel hasil proses berdasarkan file_id."""
    entry = _file_store.get(file_id)
    if not entry or not os.path.exists(entry["path"]):
        raise HTTPException(status_code=404, detail="File tidak ditemukan atau sudah kedaluwarsa.")
    return FileResponse(
        entry["path"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=entry["filename"],
    )


@router.get("/proses/template")
def download_attendance_template(
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Mengunduh file template/contoh log absensi mentah (.xlsx atau .csv).
    Data contoh disesuaikan dengan karyawan aktif di master jika tersedia.
    """
    import io
    import pandas as pd
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    # Ambil sampel karyawan aktif dari database
    emps = db.query(models.Employee).filter(models.Employee.active == True).limit(5).all()
    if emps:
        sample_emps = [(e.nama, e.cabang or "OFFICE") for e in emps]
    else:
        sample_emps = [
            ("Budi Hartono", "BLOK C"),
            ("Andi Santanu", "BLOK C"),
            ("Dian Maulana", "BLOK C"),
            ("Ahmad Fauzi", "BANDUNG"),
        ]

    # Buat baris log contoh realistis (2 hari scan: normal, lembur, telat)
    rows = []
    for idx, (nama, cabang) in enumerate(sample_emps):
        if idx == 0:
            # Jam kerja normal
            rows.append([cabang, nama, "1", "02/03/2026 07:54:12", "C/Masuk", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "02/03/2026 16:05:30", "C/Keluar", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "03/03/2026 07:50:45", "C/Masuk", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "03/03/2026 16:12:18", "C/Keluar", "1", "", "Finger"])
        elif idx == 1:
            # Lembur (pulang malam)
            rows.append([cabang, nama, "1", "02/03/2026 07:58:00", "C/Masuk", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "02/03/2026 18:35:10", "C/Keluar", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "03/03/2026 07:48:22", "C/Masuk", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "03/03/2026 16:02:40", "C/Keluar", "1", "", "Finger"])
        elif idx == 2:
            # Telat sedikit (datang lewat 08:00)
            rows.append([cabang, nama, "1", "02/03/2026 08:22:15", "C/Masuk", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "02/03/2026 16:01:05", "C/Keluar", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "03/03/2026 07:55:00", "C/Masuk", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "03/03/2026 16:08:44", "C/Keluar", "1", "", "Finger"])
        else:
            rows.append([cabang, nama, "1", "02/03/2026 07:52:00", "C/Masuk", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "02/03/2026 16:06:00", "C/Keluar", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "03/03/2026 07:56:00", "C/Masuk", "1", "", "Finger"])
            rows.append([cabang, nama, "1", "03/03/2026 16:04:00", "C/Keluar", "1", "", "Finger"])

    columns = [
        "Cabang",
        "Nama",
        "ID_Mesin",
        "Timestamp_Raw",
        "Tipe_Asli_Raw",
        "Kode_Gerbang",
        "Kolom_Kosong",
        "Metode",
    ]

    df = pd.DataFrame(rows, columns=columns)

    if format == "csv":
        out_csv = io.StringIO()
        df.to_csv(out_csv, index=False)
        return Response(
            content=out_csv.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="template_absensi_mentah.csv"'},
        )

    # Format Excel (.xlsx) dengan 2 Sheet: Data Absensi & Panduan Kolom
    wb = Workbook()
    ws_data = wb.active
    ws_data.title = "Log Absensi"

    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=11, color="0F172A")
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    ws_data.append(columns)
    for col_num in range(1, len(columns) + 1):
        cell = ws_data.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)

    for r_idx, row_data in enumerate(rows, start=2):
        ws_data.append(row_data)
        use_zebra = (r_idx % 2 == 1)
        for c_idx in range(1, len(row_data) + 1):
            cell = ws_data.cell(row=r_idx, column=c_idx)
            cell.font = data_font
            cell.border = thin_border
            if use_zebra:
                cell.fill = zebra_fill
            if c_idx in (3, 6):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif c_idx == 4:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    for col in ws_data.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_data.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Sheet 2: Panduan & Penjelasan Format Kolom
    ws_guide = wb.create_sheet(title="Panduan Kolom")
    ws_guide.views.sheetView[0].showGridLines = True

    guide_headers = ["No", "Nama Kolom", "Wajib?", "Contoh Nilai", "Keterangan & Aturan"]
    guide_rows = [
        [1, "Cabang", "Ya", "BANDUNG / BLOK C / BLOK A", "Lokasi atau cabang tempat scan absensi dilakukan."],
        [2, "Nama", "Ya", "Budi Hartono", "Nama lengkap karyawan. WAJIB sama dengan nama di menu Master Karyawan."],
        [3, "ID_Mesin", "Opsional", "1", "Nomor atau ID unit mesin absensi."],
        [4, "Timestamp_Raw", "Ya", "02/03/2026 07:54:12", "Waktu scan. Format disarankan: DD/MM/YYYY HH:MM:SS atau YYYY-MM-DD HH:MM:SS."],
        [5, "Tipe_Asli_Raw", "Ya", "C/Masuk atau C/Keluar", "Arah scan asli mesin. Sistem juga mengoreksi otomatis jika label salah/terbalik."],
        [6, "Kode_Gerbang", "Opsional", "1", "Kode pintu gerbang / terminal."],
        [7, "Kolom_Kosong", "Opsional", "", "Kolom kosong bawaan format log mesin absensi."],
        [8, "Metode", "Opsional", "Finger / Face / Password", "Metode verifikasi absensi."],
    ]

    title_cell = ws_guide.cell(row=1, column=1, value="PANDUAN FORMAT LOG ABSENSI MENTAH (8 KOLOM)")
    title_cell.font = Font(name="Calibri", size=14, bold=True, color="1E293B")

    sub_cell = ws_guide.cell(
        row=2, column=1,
        value="File log mentah dapat berupa .xlsx, .xls, maupun .csv. Sistem otomatis mendeteksi file dengan atau tanpa baris header."
    )
    sub_cell.font = Font(name="Calibri", size=10, italic=True, color="64748B")

    ws_guide.append([])
    ws_guide.append(guide_headers)
    for col_num in range(1, len(guide_headers) + 1):
        cell = ws_guide.cell(row=4, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r_idx, grow in enumerate(guide_rows, start=5):
        ws_guide.append(grow)
        use_zebra = (r_idx % 2 == 1)
        for c_idx in range(1, len(grow) + 1):
            cell = ws_guide.cell(row=r_idx, column=c_idx)
            cell.font = data_font
            cell.border = thin_border
            if use_zebra:
                cell.fill = zebra_fill
            if c_idx in (1, 3):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    for col in ws_guide.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_guide.column_dimensions[col_letter].width = max(min(max_len + 4, 60), 10)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="template_absensi_mentah.xlsx"'},
    )


# ===========================================================================
# 2) ENDPOINT UNTUK N8N (tetap pakai X-API-Key, TIDAK butuh login web)
#    Path sengaja SAMA seperti versi lama supaya workflow n8n existing tetap jalan.
# ===========================================================================

@router.get("/")
def health_check():
    return {"status": "ok", "pesan": "HR Absensi Pipeline API (web version) jalan normal."}


@router.post("/proses-absensi")
async def proses_absensi(
    files: list[UploadFile] = File(..., description="Satu atau lebih file absensi mentah (.xlsx/.xls/.csv)"),
    master_karyawan: UploadFile = File(
        None, description="Opsional. Kalau kosong, master diambil otomatis dari database web."
    ),
    file_tanggal_merah_override: UploadFile = File(
        None, description="Opsional. Kalau kosong, tanggal merah diambil otomatis dari database web."
    ),
    x_api_key: str = Header(default=None),
    db: Session = Depends(get_db),
):
    _cek_api_key(x_api_key)
    return _jalankan_dan_kirim(files, db, master_karyawan=master_karyawan, tanggal_merah_override=file_tanggal_merah_override)


@router.post("/upload-tanggal-merah")
async def upload_tanggal_merah_legacy(
    file_tanggal_merah: UploadFile = File(...),
    x_api_key: str = Header(default=None),
    db: Session = Depends(get_db),
):
    """
    DIPERTAHANKAN untuk kompatibilitas workflow n8n lama. Sekarang isi file
    langsung di-parse dan disimpan ke tabel `holidays` di database (bukan lagi
    disimpan sbg file .xlsx di server), supaya konsisten dengan halaman
    'Tanggal Merah' di website.
    """
    _cek_api_key(x_api_key)
    from ..pipeline.loader import load_tanggal_merah

    ekstensi = os.path.splitext(file_tanggal_merah.filename or "")[1].lower()
    if ekstensi not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="File harus berformat .xlsx/.xls/.csv")

    folder_kerja = tempfile.mkdtemp(prefix="hr_tglmerah_")
    path_temp = _simpan_upload(file_tanggal_merah, folder_kerja)
    tanggal_merah_dict = load_tanggal_merah(path_temp)

    for tgl, ket in tanggal_merah_dict.items():
        existing = db.query(models.Holiday).filter(models.Holiday.tanggal == tgl).first()
        if existing:
            existing.keterangan = ket
        else:
            db.add(models.Holiday(tanggal=tgl, keterangan=ket))
    db.commit()

    return {"status": "sukses", "pesan": f"{len(tanggal_merah_dict)} tanggal merah berhasil disimpan ke database."}
