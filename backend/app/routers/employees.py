# -*- coding: utf-8 -*-
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/employees", tags=["employees"])


from ..config import CONTRACT_REMINDER_DAYS, calculate_tenure, get_today_jakarta


def _enrich_employee_data(emp: models.Employee) -> models.Employee:
    """Helper untuk menghitung tenure & contract_reminder_status pada objek Employee."""
    emp.tenure_display = calculate_tenure(emp.join_date)["display"]

    today = get_today_jakarta()
    if emp.employment_status == "PKWT" and emp.contracts:
        active_contract = next((c for c in emp.contracts if c.status == "ACTIVE"), emp.contracts[0] if emp.contracts else None)
        if active_contract:
            days_left = (active_contract.end_date - today).days
            if days_left < 0:
                status_label = "EXPIRED"
                badge_color = "red"
                msg = f"Kontrak #{active_contract.contract_number} telah berakhir {abs(days_left)} hari lalu ({active_contract.end_date.strftime('%d-%m-%Y')})"
            elif days_left <= CONTRACT_REMINDER_DAYS:
                status_label = "EXPIRING_SOON"
                badge_color = "amber"
                msg = f"Sisa {days_left} hari! Kontrak #{active_contract.contract_number} berakhir {active_contract.end_date.strftime('%d-%m-%Y')}"
            else:
                status_label = "ACTIVE"
                badge_color = "green"
                msg = f"Kontrak #{active_contract.contract_number} Aktif ({days_left} hari tersisa)"

            emp.contract_reminder_status = {
                "contract_id": active_contract.id,
                "contract_number": active_contract.contract_number,
                "start_date": active_contract.start_date.isoformat(),
                "end_date": active_contract.end_date.isoformat(),
                "days_left": days_left,
                "status_label": status_label,
                "badge_color": badge_color,
                "message": msg,
                "is_expired": days_left < 0,
                "is_expiring": 0 <= days_left <= CONTRACT_REMINDER_DAYS,
            }
        else:
            emp.contract_reminder_status = None
    else:
        emp.contract_reminder_status = None

    return emp


@router.get("", response_model=list[schemas.EmployeeOut])
def list_employees(
    profile_code: Optional[str] = Query(default=None),
    employment_status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    q = db.query(models.Employee)
    if profile_code:
        q = q.filter(models.Employee.profile_code == profile_code)
    if employment_status:
        q = q.filter(models.Employee.employment_status == employment_status.upper())

    employees = q.order_by(models.Employee.nama).all()
    for emp in employees:
        _enrich_employee_data(emp)
    return employees


@router.get("/contracts/expiring")
def get_expiring_contracts(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """
    Mengambil daftar karyawan PKWT yang kontraknya berakhir dalam H-10 (atau sudah lewat)
    dan belum diperpanjang / belum diangkat menjadi TETAP.
    Diurutkan dari yang paling dekat tanggal berakhirnya.
    """
    pkwt_emps = (
        db.query(models.Employee)
        .filter(models.Employee.employment_status == "PKWT", models.Employee.active == True)
        .all()
    )

    expiring_list = []
    for emp in pkwt_emps:
        _enrich_employee_data(emp)
        rem = emp.contract_reminder_status
        if rem and (rem["is_expiring"] or rem["is_expired"]):
            expiring_list.append({
                "employee_id": emp.id,
                "nama": emp.nama,
                "cabang": emp.cabang,
                "profile_code": emp.profile_code,
                "join_date": emp.join_date,
                "tenure_display": emp.tenure_display,
                "contract_id": rem["contract_id"],
                "contract_number": rem["contract_number"],
                "start_date": rem["start_date"],
                "end_date": rem["end_date"],
                "days_left": rem["days_left"],
                "status_label": rem["status_label"],
                "is_expired": rem["is_expired"],
                "message": rem["message"],
            })

    expiring_list.sort(key=lambda x: x["days_left"])
    return {
        "reminder_days_config": CONTRACT_REMINDER_DAYS,
        "total": len(expiring_list),
        "data": expiring_list,
    }


# ─────────────────────────────────────────────────────────────
# Employee Adjustments (Bonus Lain / Potongan Lain)
# ─────────────────────────────────────────────────────────────

@router.get("/adjustments", response_model=list[schemas.EmployeeAdjustmentOut])
def list_adjustments(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Mendapatkan semua data penyesuaian (bonus/potongan lain-lain) karyawan."""
    return db.query(models.EmployeeAdjustment).order_by(models.EmployeeAdjustment.nama).all()


@router.patch("/adjustments", response_model=schemas.EmployeeAdjustmentOut)
def upsert_adjustment(
    payload: schemas.EmployeeAdjustmentUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Membuat atau memperbarui data penyesuaian karyawan (upsert by nama)."""
    nama_key = payload.nama.strip()
    if not nama_key:
        raise HTTPException(status_code=400, detail="Nama karyawan wajib diisi.")

    adj = db.query(models.EmployeeAdjustment).filter(
        models.EmployeeAdjustment.nama == nama_key
    ).first()

    if adj is None:
        adj = models.EmployeeAdjustment(
            nama=nama_key,
            bonus_lain=payload.bonus_lain if payload.bonus_lain is not None else 0.0,
            potongan_lain=payload.potongan_lain if payload.potongan_lain is not None else 0.0,
            catatan=payload.catatan,
        )
        db.add(adj)
    else:
        if payload.bonus_lain is not None:
            adj.bonus_lain = payload.bonus_lain
        if payload.potongan_lain is not None:
            adj.potongan_lain = payload.potongan_lain
        if payload.catatan is not None:
            adj.catatan = payload.catatan

    db.commit()
    db.refresh(adj)
    return adj


# ─────────────────────────────────────────────────────────────
# Absen Manual (Hari Kerja Manual per Periode)
# ─────────────────────────────────────────────────────────────

@router.put("/absen-manual", response_model=schemas.AbsenManualOut)
def upsert_absen_manual(
    payload: schemas.AbsenManualUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """Membuat atau memperbarui jumlah hari absen manual karyawan untuk periode tertentu (upsert)."""
    nama_key = payload.nama.strip()
    if not nama_key:
        raise HTTPException(status_code=400, detail="Nama karyawan wajib diisi.")

    record = db.query(models.AbsenManual).filter(
        models.AbsenManual.nama == nama_key,
        models.AbsenManual.tahun == payload.tahun,
        models.AbsenManual.bulan == payload.bulan,
    ).first()

    if record is None:
        record = models.AbsenManual(
            nama=nama_key,
            tahun=payload.tahun,
            bulan=payload.bulan,
            jumlah=payload.jumlah,
        )
        db.add(record)
    else:
        record.jumlah = payload.jumlah

    db.commit()
    db.refresh(record)
    return record


# ─────────────────────────────────────────────────────────────
# Template Karyawan
# ─────────────────────────────────────────────────────────────

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
        {"Status": "Office A",          "Nama": "Budi Santoso",          "Uang Makan": 100000, "BPJS Kesehatan": 53994, "BPJS TK": 161982, "Gaji Pokok": ""},
        {"Status": "Gudang A",          "Nama": "Siti Aminah",           "Uang Makan": 80000,  "BPJS Kesehatan": 53994, "BPJS TK": 161982, "Gaji Pokok": ""},
        {"Status": "Gudang C",          "Nama": "Ahmad Fauzi",           "Uang Makan": 45000,  "BPJS Kesehatan": 67980, "BPJS TK": 203850, "Gaji Pokok": ""},
        {"Status": "Gudang Bandung",    "Nama": "Reni Kusuma",           "Uang Makan": 50000,  "BPJS Kesehatan": 53994, "BPJS TK": 161982, "Gaji Pokok": ""},
        {"Status": "Office C",          "Nama": "Dewi Rahayu",           "Uang Makan": 75000,  "BPJS Kesehatan": 72000, "BPJS TK": 216000, "Gaji Pokok": ""},
        {"Status": "Office Bandung",    "Nama": "Irfan Wijaya",          "Uang Makan": 75000,  "BPJS Kesehatan": 53994, "BPJS TK": 161982, "Gaji Pokok": ""},
        {"Status": "Toko GLC",          "Nama": "Bagus Setiawan",        "Uang Makan": 40000,  "BPJS Kesehatan": 53994, "BPJS TK": 161982, "Gaji Pokok": ""},
        {"Status": "Toko Tanjung Duren","Nama": "Agung Nugroho",         "Uang Makan": "",     "BPJS Kesehatan": 53994, "BPJS TK": 161982, "Gaji Pokok": ""},
        {"Status": "Toko IDD/PIK",      "Nama": "Aulia Putri",           "Uang Makan": 65000,  "BPJS Kesehatan": 53994, "BPJS TK": 161982, "Gaji Pokok": ""},
        {"Status": "Toko Reef Plus/PIK","Nama": "Andry Saputra",         "Uang Makan": 55000,  "BPJS Kesehatan": 53994, "BPJS TK": 161982, "Gaji Pokok": ""},
        {"Status": "Toko Ciledug",      "Nama": "Edi Kuswanto",          "Uang Makan": "",     "BPJS Kesehatan": 73000, "BPJS TK": 219000, "Gaji Pokok": ""},
        {"Status": "Content Marketing", "Nama": "Fahrul Azi",            "Uang Makan": 100000, "BPJS Kesehatan": 76000, "BPJS TK": 228000, "Gaji Pokok": ""},
        {"Status": "Host Live Streaming","Nama": "Intan Melani",          "Uang Makan": 60000,  "BPJS Kesehatan": 53994, "BPJS TK": 161982, "Gaji Pokok": ""},
        {"Status": "Setup",             "Nama": "Karlina",               "Uang Makan": 60000,  "BPJS Kesehatan": 53994, "BPJS TK": 161982, "Gaji Pokok": ""},
        {"Status": "Staff Stock Opname","Nama": "Hamdani",               "Uang Makan": 90000,  "BPJS Kesehatan": 55550, "BPJS TK": 166650, "Gaji Pokok": ""},
        {"Status": "Driver Java Cipulir","Nama": "Harry",                "Uang Makan": "",     "BPJS Kesehatan": 57299, "BPJS TK": 171896, "Gaji Pokok": ""},
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


# ─────────────────────────────────────────────────────────────
# Template & Import NIK / Join Date / Waktu Berakhir Kontrak
# ─────────────────────────────────────────────────────────────

@router.get("/template/nik-import")
def download_nik_import_template(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """
    Download template Excel berisi SELURUH karyawan aktif dari database.
    Kolom: Nama (read-only ref), NIK, Join Date, Waktu Berakhir Kontrak.
    HR cukup mengisi kolom yang kosong lalu upload kembali.
    """
    import io
    import openpyxl
    from openpyxl.styles import (
        PatternFill, Font, Alignment, Border, Side, Protection
    )
    from openpyxl.utils import get_column_letter
    from fastapi.responses import Response

    employees = (
        db.query(models.Employee)
        .filter(models.Employee.active == True)
        .order_by(models.Employee.cabang, models.Employee.nama)
        .all()
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Import NIK & Tanggal"

    # ── Warna & style ──────────────────────────────────────────
    HEADER_FILL   = PatternFill("solid", fgColor="1E3A5F")   # biru tua
    LOCKED_FILL   = PatternFill("solid", fgColor="D9E2F3")   # biru muda (read-only)
    INPUT_FILL    = PatternFill("solid", fgColor="FFFDE7")   # kuning muda (isi di sini)
    HEADER_FONT   = Font(bold=True, color="FFFFFF", size=11)
    LOCKED_FONT   = Font(color="333333", size=10)
    INPUT_FONT    = Font(color="1A1A1A", size=10)
    CENTER        = Alignment(horizontal="center", vertical="center", wrap_text=False)
    BORDER_THIN   = Border(
        left=Side(style="thin", color="BBBBBB"),
        right=Side(style="thin", color="BBBBBB"),
        top=Side(style="thin", color="BBBBBB"),
        bottom=Side(style="thin", color="BBBBBB"),
    )

    # ── Baris judul ────────────────────────────────────────────
    ws.merge_cells("A1:F1")
    title_cell = ws["A1"]
    title_cell.value = "TEMPLATE IMPORT NIK, JOIN DATE & WAKTU BERAKHIR KONTRAK"
    title_cell.font = Font(bold=True, color="1E3A5F", size=13)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells("A2:F2")
    note_cell = ws["A2"]
    note_cell.value = (
        "Petunjuk: Isi kolom NIK, Join Date, dan Waktu Berakhir Kontrak. "
        "Kolom No & Nama JANGAN DIUBAH. Format tanggal: YYYY-MM-DD (contoh: 2024-04-15). "
        "Kolom 'Waktu Berakhir' hanya untuk karyawan PKWT."
    )
    note_cell.font = Font(italic=True, color="555555", size=9)
    note_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 28

    # ── Header kolom ───────────────────────────────────────────
    headers = ["No", "Cabang", "Nama Karyawan", "NIK (16 digit KTP)", "Join Date (YYYY-MM-DD)", "Waktu Berakhir Kontrak (YYYY-MM-DD)"]
    col_widths = [5, 18, 30, 22, 26, 34]

    for col_idx, (header, width) in enumerate(zip(headers, col_widths), start=1):
        cell = ws.cell(row=3, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        cell.border = BORDER_THIN
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[3].height = 22

    # ── Data karyawan ──────────────────────────────────────────
    for row_idx, emp in enumerate(employees, start=4):
        # Ambil tanggal berakhir kontrak aktif (jika PKWT)
        contract_end = None
        if emp.employment_status == "PKWT" and emp.contracts:
            active_c = next((c for c in emp.contracts if c.status == "ACTIVE"), None)
            if active_c:
                contract_end = active_c.end_date.isoformat()

        row_data = [
            row_idx - 3,                  # No
            emp.cabang or "",             # Cabang
            emp.nama,                     # Nama (read-only)
            emp.nik or "",                # NIK (isi)
            emp.join_date.isoformat() if emp.join_date else "",  # Join Date
            contract_end or "",           # Waktu Berakhir
        ]

        for col_idx, value in enumerate(row_data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = BORDER_THIN
            cell.font = LOCKED_FONT

            if col_idx <= 3:
                # Kolom No, Cabang, Nama → background biru muda (read-only visual)
                cell.fill = LOCKED_FILL
                cell.alignment = CENTER if col_idx == 1 else Alignment(vertical="center")
            else:
                # Kolom NIK, Join Date, Waktu Berakhir → kuning (input)
                cell.fill = INPUT_FILL
                cell.font = INPUT_FONT
                cell.alignment = CENTER

        ws.row_dimensions[row_idx].height = 18

    # ── Sheet petunjuk ─────────────────────────────────────────
    ws2 = wb.create_sheet("Petunjuk")
    petunjuk = [
        ["PETUNJUK PENGISIAN TEMPLATE"],
        [],
        ["Kolom", "Keterangan"],
        ["No", "Nomor urut. JANGAN DIUBAH."],
        ["Cabang", "Cabang karyawan. JANGAN DIUBAH."],
        ["Nama Karyawan", "Nama karyawan. JANGAN DIUBAH. Sistem akan mencari berdasarkan nama ini."],
        ["NIK (16 digit KTP)", "Nomor Induk Kependudukan 16 digit. Kosongkan jika tidak ada."],
        ["Join Date", "Tanggal mulai kerja. Format: YYYY-MM-DD (contoh: 2024-04-15). Kosongkan jika tidak ingin mengubah."],
        ["Waktu Berakhir Kontrak", "Tanggal berakhir kontrak (khusus karyawan PKWT). Format: YYYY-MM-DD. Kosongkan jika tidak relevan."],
        [],
        ["CATATAN PENTING:"],
        ["• Kolom No, Cabang, dan Nama TIDAK BOLEH diubah. Sistem membaca berdasarkan nama."],
        ["• Baris yang kolom NIK, Join Date, dan Waktu Berakhir-nya SEMUA kosong akan dilewati (tidak diproses)."],
        ["• Jika karyawan sudah punya NIK di database, kolom NIK akan terisi otomatis saat download template."],
        ["• Waktu Berakhir Kontrak hanya berlaku jika karyawan sudah terdaftar sebagai PKWT di sistem."],
        ["• File ini hanya bisa diupload oleh HR Master."],
    ]
    for r_idx, row_vals in enumerate(petunjuk, start=1):
        for c_idx, val in enumerate(row_vals, start=1):
            cell = ws2.cell(row=r_idx, column=c_idx, value=val)
            if r_idx == 1:
                cell.font = Font(bold=True, size=13, color="1E3A5F")
            elif r_idx == 3:
                cell.font = Font(bold=True)
    ws2.column_dimensions["A"].width = 30
    ws2.column_dimensions["B"].width = 80

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="template_import_nik.xlsx"'
        },
    )


@router.post("/import/nik")
def import_nik_from_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """
    Upload file Excel hasil isi template NIK untuk update massal:
    NIK, Join Date, dan Waktu Berakhir Kontrak karyawan.

    Aturan:
    - Match karyawan berdasarkan nama (case-insensitive, strip whitespace).
    - Hanya kolom yang diisi yang diupdate (kolom kosong dilewati).
    - Waktu Berakhir hanya diproses jika karyawan berstatus PKWT.
    - Mengembalikan ringkasan hasil: diupdate, dilewati, tidak ditemukan.
    """
    import io
    import openpyxl
    from datetime import date as date_type

    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File harus berformat Excel (.xlsx atau .xls).")

    content = file.file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="File Excel tidak valid atau rusak.")

    # Cari sheet utama (bukan sheet Petunjuk)
    sheet_name = next(
        (s for s in wb.sheetnames if "petunjuk" not in s.lower()),
        wb.sheetnames[0]
    )
    ws = wb[sheet_name]

    # Baca header dari baris ke-3 (baris 1-2 adalah judul & catatan)
    header_row = [str(c.value or "").strip().lower() for c in ws[3]]
    
    def col_idx(keyword: str) -> int:
        """Cari indeks kolom berdasarkan keyword (0-based)."""
        for i, h in enumerate(header_row):
            if keyword in h:
                return i
        return -1

    idx_nama   = col_idx("nama")
    idx_nik    = col_idx("nik")
    idx_join   = col_idx("join")
    idx_end    = col_idx("berakhir")

    if idx_nama < 0 or idx_nik < 0:
        raise HTTPException(
            status_code=400,
            detail="Format file tidak dikenali. Pastikan menggunakan template resmi yang diunduh dari sistem."
        )

    def parse_date(val) -> Optional[date_type]:
        if not val:
            return None
        if isinstance(val, (date_type,)):
            return val
        if hasattr(val, "date"):  # datetime object
            return val.date()
        s = str(val).strip()
        if not s or s == "None":
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                import datetime
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def clean_nik(val) -> Optional[str]:
        if not val:
            return None
        s = str(val).strip().replace(" ", "")
        # Hapus desimal jika Excel simpan sebagai float (misal: 1234567890123456.0)
        if s.endswith(".0"):
            s = s[:-2]
        if len(s) != 16 or not s.isdigit():
            return None
        return s

    results = {
        "updated": [],
        "skipped": [],    # baris kosong / tidak ada data baru
        "not_found": [],  # nama tidak cocok
        "nik_conflict": [],  # NIK sudah dipakai karyawan lain
        "invalid_nik": [],   # format NIK salah
    }

    for row in ws.iter_rows(min_row=4):
        vals = [cell.value for cell in row]
        if len(vals) <= max(idx_nama, idx_nik):
            continue

        nama_raw = vals[idx_nama]
        if not nama_raw:
            continue

        nama_key = str(nama_raw).strip()
        nik_raw  = vals[idx_nik]  if idx_nik  >= 0 else None
        join_raw = vals[idx_join] if idx_join >= 0 else None
        end_raw  = vals[idx_end]  if idx_end  >= 0 else None

        # Skip jika semua kolom yang perlu diisi kosong
        if not nik_raw and not join_raw and not end_raw:
            results["skipped"].append(nama_key)
            continue

        # Cari karyawan di DB (case-insensitive)
        emp = db.query(models.Employee).filter(
            models.Employee.nama.ilike(nama_key)
        ).first()

        if not emp:
            results["not_found"].append(nama_key)
            continue

        updated_fields = []

        # -- Update NIK --
        if nik_raw:
            clean = clean_nik(nik_raw)
            if not clean:
                results["invalid_nik"].append({"nama": nama_key, "nik_raw": str(nik_raw)})
            else:
                # Cek duplikat NIK
                conflict = db.query(models.Employee).filter(
                    models.Employee.nik == clean,
                    models.Employee.id != emp.id,
                ).first()
                if conflict:
                    results["nik_conflict"].append({
                        "nama": nama_key,
                        "nik": clean,
                        "konflik_dengan": conflict.nama,
                    })
                else:
                    emp.nik = clean
                    updated_fields.append("NIK")

        # -- Update Join Date --
        join_date_parsed = parse_date(join_raw)
        if join_date_parsed:
            emp.join_date = join_date_parsed
            updated_fields.append("Join Date")

        # -- Update Waktu Berakhir Kontrak (hanya PKWT) --
        if end_raw and emp.employment_status == "PKWT":
            end_date_parsed = parse_date(end_raw)
            if end_date_parsed:
                active_c = next(
                    (c for c in emp.contracts if c.status == "ACTIVE"), None
                )
                if active_c:
                    active_c.end_date = end_date_parsed
                    updated_fields.append("Waktu Berakhir Kontrak")

        if updated_fields:
            results["updated"].append({
                "nama": emp.nama,
                "fields": ", ".join(updated_fields),
            })

    db.commit()

    return {
        "message": "Import selesai.",
        "total_updated": len(results["updated"]),
        "total_skipped": len(results["skipped"]),
        "total_not_found": len(results["not_found"]),
        "total_nik_conflict": len(results["nik_conflict"]),
        "total_invalid_nik": len(results["invalid_nik"]),
        "detail": results,
    }


@router.get("/{employee_id}", response_model=schemas.EmployeeOut)
def get_employee_detail(
    employee_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    emp = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan.")
    _enrich_employee_data(emp)
    return emp


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

    emp_status = (payload.employment_status or "TETAP").upper().strip()
    if emp_status not in ("TETAP", "PKWT"):
        raise HTTPException(status_code=400, detail="Status kepegawaian harus 'TETAP' atau 'PKWT'.")

    # Validasi join_date: Wajib untuk semua karyawan baru
    if not payload.join_date:
        raise HTTPException(status_code=400, detail="Tanggal masuk / bergabung (join_date) wajib diisi untuk semua karyawan.")

    # Validasi & Handling Kontrak untuk karyawan PKWT
    contract_data = None
    if emp_status == "PKWT":
        if not payload.contract_start_date or not payload.contract_end_date:
            raise HTTPException(
                status_code=400,
                detail="Untuk karyawan PKWT, Tanggal Mulai Kontrak & Tanggal Selesai Kontrak wajib diisi."
            )
        if payload.contract_end_date <= payload.contract_start_date:
            raise HTTPException(
                status_code=400,
                detail="Tanggal selesai kontrak (contract_end_date) harus setelah tanggal mulai kontrak (contract_start_date)."
            )
        contract_data = {
            "start_date": payload.contract_start_date,
            "end_date": payload.contract_end_date,
            "keterangan": payload.contract_keterangan or "Kontrak Pertama (PKWT-1)",
        }

    emp_dict = payload.dict(exclude={"contract_start_date", "contract_end_date", "contract_keterangan"})
    emp_dict["employment_status"] = emp_status
    emp = models.Employee(**emp_dict)
    db.add(emp)
    db.commit()
    db.refresh(emp)

    if contract_data:
        contract = models.EmploymentContract(
            employee_id=emp.id,
            contract_number=1,
            start_date=contract_data["start_date"],
            end_date=contract_data["end_date"],
            status="ACTIVE",
            keterangan=contract_data["keterangan"],
        )
        db.add(contract)
        db.commit()
        db.refresh(emp)

    _enrich_employee_data(emp)
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

    new_status = (payload.employment_status or "TETAP").upper().strip()
    if new_status not in ("TETAP", "PKWT"):
        raise HTTPException(status_code=400, detail="Status kepegawaian harus 'TETAP' atau 'PKWT'.")

    # Jika diubah dari PKWT ke TETAP (Pengangkatan Karyawan Tetap)
    if emp.employment_status == "PKWT" and new_status == "TETAP":
        for c in emp.contracts:
            if c.status == "ACTIVE":
                c.status = "PROMOTED_TO_PERMANENT"
                c.keterangan = (c.keterangan or "") + " [Diangkat menjadi Karyawan Tetap]"

    # Jika status PKWT & ada input tanggal kontrak baru/update
    if new_status == "PKWT":
        if payload.contract_start_date and payload.contract_end_date:
            if payload.contract_end_date <= payload.contract_start_date:
                raise HTTPException(
                    status_code=400,
                    detail="Tanggal selesai kontrak (contract_end_date) harus setelah tanggal mulai kontrak."
                )
            active_c = next((c for c in emp.contracts if c.status == "ACTIVE"), None)
            if active_c:
                active_c.start_date = payload.contract_start_date
                active_c.end_date = payload.contract_end_date
                if payload.contract_keterangan:
                    active_c.keterangan = payload.contract_keterangan
            else:
                next_num = len(emp.contracts) + 1
                new_c = models.EmploymentContract(
                    employee_id=emp.id,
                    contract_number=next_num,
                    start_date=payload.contract_start_date,
                    end_date=payload.contract_end_date,
                    status="ACTIVE",
                    keterangan=payload.contract_keterangan or f"Kontrak PKWT #{next_num}",
                )
                db.add(new_c)

    emp_dict = payload.dict(exclude={"contract_start_date", "contract_end_date", "contract_keterangan"})
    for field, value in emp_dict.items():
        setattr(emp, field, value)

    db.commit()
    db.refresh(emp)
    _enrich_employee_data(emp)
    return emp


@router.post("/{employee_id}/contracts", response_model=schemas.EmploymentContractOut)
def add_contract_renewal(
    employee_id: int,
    payload: schemas.EmploymentContractCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """
    Menambahkan perpanjangan kontrak baru (Kontrak ke-2, ke-3, dst.) untuk karyawan PKWT.
    Kontrak lama akan ditandai RENEWED, dan kontrak baru dibuat dengan status ACTIVE.
    """
    emp = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan.")

    if payload.end_date <= payload.start_date:
        raise HTTPException(
            status_code=400,
            detail="Tanggal selesai kontrak (end_date) harus setelah tanggal mulai kontrak (start_date)."
        )

    # Tandai kontrak aktif sebelumnya sebagai RENEWED
    for c in emp.contracts:
        if c.status == "ACTIVE":
            c.status = "RENEWED"

    next_number = max([c.contract_number for c in emp.contracts], default=0) + 1

    # Pastikan status kepegawaian PKWT
    emp.employment_status = "PKWT"

    new_contract = models.EmploymentContract(
        employee_id=emp.id,
        contract_number=next_number,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status="ACTIVE",
        keterangan=payload.keterangan or f"Perpanjangan Kontrak ke-{next_number}",
    )
    db.add(new_contract)
    db.commit()
    db.refresh(new_contract)
    return new_contract


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
        elif any(k in cl for k in ("bpjs_kesehatan", "bpjs_kes", "potongan_bpjs_kesehatan", "kesehatan")):
            col_map["bpjs_kesehatan"] = col
        elif any(k in cl for k in ("bpjs_tk", "bpjs_ketenagakerjaan", "potongan_bpjs_tk", "jamsostek", "bpjstk")):
            col_map["bpjs_tk"] = col
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

        # BPJS Kesehatan & BPJS TK
        bpjs_kesehatan = None
        if "bpjs_kesehatan" in col_map and pd.notna(row.get(col_map["bpjs_kesehatan"])):
            raw_val = str(row[col_map["bpjs_kesehatan"]]).strip().replace(",", "").replace(".", "")
            try:
                bpjs_kesehatan = int(float(raw_val)) if raw_val else 0
            except (ValueError, OverflowError):
                bpjs_kesehatan = 0

        bpjs_tk = None
        if "bpjs_tk" in col_map and pd.notna(row.get(col_map["bpjs_tk"])):
            raw_val = str(row[col_map["bpjs_tk"]]).strip().replace(",", "").replace(".", "")
            try:
                bpjs_tk = int(float(raw_val)) if raw_val else 0
            except (ValueError, OverflowError):
                bpjs_tk = 0

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
            if bpjs_kesehatan is not None:
                emp.bpjs_kesehatan = bpjs_kesehatan
            if bpjs_tk is not None:
                emp.bpjs_tk = bpjs_tk
            emp.active = active
            updated += 1
        else:
            new_emp = models.Employee(
                nama=nama,
                profile_code=profile_code,
                cabang=cabang,
                id_mesin=id_mesin,
                uang_makan_override=uang_makan_override,
                bpjs_kesehatan=bpjs_kesehatan or 0,
                bpjs_tk=bpjs_tk or 0,
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
