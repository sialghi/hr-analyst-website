# -*- coding: utf-8 -*-
"""Parsing and normalization helpers for employee workbooks."""
import datetime
import io
import re
from collections import Counter

import openpyxl


def normalize_text(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def normalize_header(value) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())


def _is_blank(value) -> bool:
    return value is None or (
        isinstance(value, str)
        and value.strip().casefold() in ("", "-", "none", "nan", "n/a")
    )


def _raw_source_value(value):
    if value is None:
        return None
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


def clean_nik(value):
    if _is_blank(value):
        return None
    text = str(value).strip().replace(" ", "")
    if text.endswith(".0"):
        text = text[:-2]
    if not text:
        return None
    return text if len(text) == 16 and text.isdigit() else False


def parse_date(value):
    if _is_blank(value):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return False


def parse_money(value):
    if _is_blank(value):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 and float(value).is_integer() else False
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+\.0+", text):
        return int(float(text))
    digits = re.sub(r"[.,\s]", "", text)
    return int(digits) if digits.isdigit() else False


def _read_workbook(content):
    try:
        return openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError("File Excel tidak valid atau rusak.") from exc


def _find_sheet_and_header(workbook, required_headers, preferred_sheet=None):
    sheets = list(workbook.worksheets)
    if preferred_sheet:
        sheets.sort(key=lambda sheet: sheet.title.casefold() != preferred_sheet.casefold())
    for sheet in sheets:
        for row_number, cells in enumerate(
            sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 10), values_only=True),
            start=1,
        ):
            headers = {
                normalize_header(value): index
                for index, value in enumerate(cells)
                if value is not None
            }
            if all(required in headers for required in required_headers):
                return sheet, row_number, headers
    raise ValueError("Format workbook tidak dikenali; kolom wajib tidak ditemukan.")


def parse_master_workbook(content):
    workbook = _read_workbook(content)
    sheet, header_row, headers = _find_sheet_and_header(
        workbook,
        ("id karyawan", "nama", "lokasi kerja"),
        preferred_sheet="Master ID",
    )
    aliases = {
        "employee_code": ("id karyawan",),
        "nama": ("nama",),
        "nik": ("nik",),
        "join_date": ("tanggal join", "tanggal masuk"),
        "uang_makan_override": ("um uang makan", "uang makan"),
        "jabatan": ("jabatan",),
        "cabang": ("lokasi kerja",),
        "payroll_status": ("status bulanan harian",),
    }
    column_indexes = {}
    for field, candidates in aliases.items():
        for candidate in candidates:
            if candidate in headers:
                column_indexes[field] = headers[candidate]
                break

    parsed_rows = []
    conflicts = []
    for row_number, values in enumerate(
        sheet.iter_rows(min_row=header_row + 1, values_only=True),
        start=header_row + 1,
    ):
        if not any(value is not None for value in values):
            continue
        def value_for(field):
            index = column_indexes.get(field)
            return values[index] if index is not None and index < len(values) else None

        employee_code = "" if _is_blank(value_for("employee_code")) else str(value_for("employee_code")).strip()
        nama = "" if _is_blank(value_for("nama")) else " ".join(str(value_for("nama")).split())
        cabang = "" if _is_blank(value_for("cabang")) else " ".join(str(value_for("cabang")).split())
        if not employee_code or not nama or not cabang:
            conflicts.append({"row": row_number, "employee_code": employee_code or None, "reason": "ID Karyawan, Nama, dan Lokasi Kerja wajib diisi."})
            continue

        nik = clean_nik(value_for("nik"))
        join_date = parse_date(value_for("join_date"))
        allowance = parse_money(value_for("uang_makan_override"))
        payroll_value = value_for("payroll_status")
        payroll_status = None if _is_blank(payroll_value) else " ".join(str(payroll_value).split()).title()
        row_errors = []
        if nik is False:
            row_errors.append("NIK harus 16 digit atau dikosongkan.")
        if join_date is False:
            row_errors.append("Tanggal Join tidak dikenali.")
        if allowance is False:
            row_errors.append("Nilai Uang Makan tidak valid.")
        if payroll_status and payroll_status not in ("Bulanan", "Harian"):
            row_errors.append("Status harus Bulanan atau Harian.")
        if row_errors:
            conflicts.append({"row": row_number, "employee_code": employee_code, "reason": " ".join(row_errors)})
            continue
        parsed_rows.append({
            "source_row": row_number,
            "employee_code": employee_code,
            "nama": nama,
            "nik": nik,
            "join_date": join_date,
            "uang_makan_override": allowance,
            "jabatan": None if _is_blank(value_for("jabatan")) else str(value_for("jabatan")).strip(),
            "cabang": cabang,
            "payroll_status": payroll_status,
        })

    code_counts = Counter(row["employee_code"] for row in parsed_rows)
    nik_counts = Counter(row["nik"] for row in parsed_rows if row["nik"])
    name_counts = Counter(normalize_text(row["nama"]) for row in parsed_rows)
    valid_rows = []
    for row in parsed_rows:
        reasons = []
        if code_counts[row["employee_code"]] > 1:
            reasons.append("ID Karyawan duplikat di workbook.")
        if row["nik"] and nik_counts[row["nik"]] > 1:
            reasons.append("NIK duplikat di workbook.")
        if name_counts[normalize_text(row["nama"])] > 1:
            reasons.append("Nama duplikat; pemrosesan absensi saat ini masih mencocokkan nama.")
        if reasons:
            conflicts.append({
                "row": row["source_row"],
                "employee_code": row["employee_code"],
                "reason": " ".join(reasons),
            })
        else:
            valid_rows.append(row)
    return valid_rows, conflicts


def parse_recap_workbook(content):
    workbook = _read_workbook(content)
    sheet, header_row, headers = _find_sheet_and_header(
        workbook,
        ("id", "nik", "cabang", "nama", "status", "tanggal"),
        preferred_sheet="Rekap Kehadiran",
    )
    aliases = {
        "employee_code": "id",
        "nik": "nik",
        "cabang": "cabang",
        "nama": "nama",
        "status": "status",
        "tanggal": "tanggal",
        "mark": "keterangan s i cs",
    }
    column_indexes = {
        field: headers[header]
        for field, header in aliases.items()
        if header in headers
    }
    if "mark" not in column_indexes:
        raise ValueError("Kolom Keterangan (S/I/CS) tidak ditemukan.")

    rows = []
    conflicts = []
    source_headers = next(
        sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True)
    )
    for row_number, values in enumerate(
        sheet.iter_rows(min_row=header_row + 1, values_only=True),
        start=header_row + 1,
    ):
        if not any(value is not None for value in values):
            continue
        def value_for(field):
            index = column_indexes.get(field)
            return values[index] if index is not None and index < len(values) else None

        employee_code = "" if _is_blank(value_for("employee_code")) else str(value_for("employee_code")).strip()
        nama = "" if _is_blank(value_for("nama")) else " ".join(str(value_for("nama")).split())
        mark = "" if _is_blank(value_for("mark")) else " ".join(str(value_for("mark")).split()).upper()
        date_value = parse_date(value_for("tanggal"))
        nik = clean_nik(value_for("nik"))
        row = {
            "source_row": row_number,
            "source_values": [
                {"header": str(header), "value": _raw_source_value(values[index] if index < len(values) else None)}
                for index, header in enumerate(source_headers)
                if header is not None
            ],
            "employee_code": employee_code or None,
            "nik": None if nik is False else nik,
            "cabang": " ".join(str(value_for("cabang") or "").split()),
            "nama": nama,
            "payroll_status": None if _is_blank(value_for("status")) else " ".join(str(value_for("status")).split()).title(),
            "tanggal": None if date_value is False else date_value,
            "mark": mark,
        }
        row_errors = []
        if not nama:
            row_errors.append("Nama kosong.")
        if nik is False:
            row_errors.append("NIK tidak valid.")
        if date_value is False or date_value is None:
            row_errors.append("Tanggal tidak valid.")
        if row_errors:
            conflicts.append({"row": row_number, "employee_code": employee_code or None, "reason": " ".join(row_errors)})
        else:
            rows.append(row)
    return rows, conflicts
