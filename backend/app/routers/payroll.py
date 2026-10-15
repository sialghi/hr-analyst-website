# -*- coding: utf-8 -*-
"""
payroll.py
Router untuk Proses Slip Gaji:
  - Download template Excel/CSV
  - Upload & parse data penggajian → JSON ke session
  - Export rekapitulasi Excel
  - Generate PDF slip (via openpyxl / reportlab)
  - Kirim slip via WhatsApp (teks rincian + PDF Cloudinary)
"""
import io
import os
import uuid
import datetime
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, JSONResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..shared_store import _file_store  # reuse in-memory store
from ..cloudinary_helper import upload_to_cloudinary
from .whatsapp import (
    normalize_whatsapp_number,
    send_whatsapp_text,
    send_whatsapp_raw,
)

router = APIRouter(tags=["payroll"])

PAYROLL_ALLOWED_EXT = (".xlsx", ".xls", ".csv")
PAYROLL_PDF_MAX_BYTES = 10 * 1024 * 1024


def _one_year_from(value: datetime.datetime) -> datetime.datetime:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, month=2, day=28)

# ---------------------------------------------------------------------------
# Kolom template (input dari HR)
# ---------------------------------------------------------------------------
TEMPLATE_INPUT_COLS = [
    "ID Karyawan",
    "Nama",
    "No. Rekening",
    "Departemen",
    "Gaji Pokok",
    "Potongan Hari",
    "Potongan Nominal",
    "Uang Makan",
    "Hari Kerja",
    "Lembur",
    "Tunjangan",
    "Potongan Denda/SO",
    "Potongan Telat",
    "Potongan BPJS",
    "Potongan Lain",
    "Kasbon Bulan Ini",
    "Sisa Kasbon",
]

NUMERIC_COLS = {
    "Gaji Pokok", "Potongan Hari", "Potongan Nominal", "Uang Makan", "Hari Kerja",
    "Lembur", "Tunjangan", "Potongan Denda/SO", "Potongan Telat", "Potongan BPJS",
    "Potongan Lain", "Kasbon Bulan Ini", "Sisa Kasbon",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(val: Any) -> float:
    """Konversi nilai sel ke float; return 0.0 jika kosong/tidak valid."""
    if val is None or val == "" or val == "-":
        return 0.0
    try:
        if isinstance(val, str):
            val = val.replace(",", "").replace(".", "").strip()
            # Coba parse ulang dengan titik sebagai desimal
            return float(re.sub(r"[^\d\-]", "", val) or "0")
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _calculate_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Hitung Sub Total dan THP dari baris data payroll."""
    gp = _to_float(row.get("Gaji Pokok", row.get("GP")))
    um = _to_float(row.get("Uang Makan"))
    tunjangan = _to_float(row.get("Tunjangan"))
    lembur = _to_float(row.get("Lembur"))
    pot_nominal = _to_float(row.get("Potongan Nominal", row.get("Pot Nominal")))
    pot_denda = _to_float(row.get("Potongan Denda/SO", row.get("Pot Denda/SO")))
    pot_telat = _to_float(row.get("Potongan Telat", row.get("Pot Telat")))
    pot_bpjs = _to_float(row.get("Potongan BPJS", row.get("Pot BPJS")))
    pot_lain = _to_float(row.get("Potongan Lain", row.get("Pot Lain")))
    kasbon = _to_float(row.get("Kasbon Bulan Ini"))

    sub_total = gp + um + tunjangan + lembur
    total_potongan = pot_nominal + pot_denda + pot_telat + pot_bpjs + pot_lain + kasbon
    thp = sub_total - total_potongan

    return {
        **row,
        "Sub Total": sub_total,
        "Total Potongan": total_potongan,
        "THP": thp,
    }


def _parse_payroll_file(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """Parse file Excel/CSV ke list of dict, lalu hitung kalkulasi."""
    import pandas as pd

    ext = os.path.splitext(filename.lower())[1]
    try:
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Gagal membaca file: {e}")

    # Normalise header
    df.columns = [str(c).strip() for c in df.columns]

    # Normalize accepted names for the current employee identifier only.
    alias_map = {
        "new_employee_id": "ID Karyawan",
        "New Employee ID": "ID Karyawan",
        "ID Karyawan": "ID Karyawan",
        "Dept": "Departemen",
        "GP": "Gaji Pokok",
        "Pot Hari": "Potongan Hari",
        "Pot Nominal": "Potongan Nominal",
        "Pot Denda/SO": "Potongan Denda/SO",
        "Pot Telat": "Potongan Telat",
        "Pot BPJS": "Potongan BPJS",
        "Pot Lain": "Potongan Lain",
    }
    for old_col, new_col in alias_map.items():
        if old_col in df.columns and new_col not in df.columns:
            df.rename(columns={old_col: new_col}, inplace=True)

    # Hanya ambil kolom yang kita kenal; kolom kalkulasi dihitung ulang
    missing = [c for c in ["Nama", "No. Rekening", "Departemen"] if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Kolom wajib tidak ditemukan: {', '.join(missing)}. "
                   "Pastikan menggunakan template yang benar.",
        )

    rows = []
    for _, r in df.iterrows():
        row: Dict[str, Any] = {}
        for col in TEMPLATE_INPUT_COLS:
            raw = str(r.get(col, "") or "").strip()
            if col in NUMERIC_COLS:
                row[col] = _to_float(raw)
            else:
                row[col] = raw
        row = _calculate_row(row)
        rows.append(row)

    return rows


def _build_kpis(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    return {
        "total_thp": sum(r.get("THP", 0) for r in rows),
        "total_potongan": sum(r.get("Total Potongan", 0) for r in rows),
        "total_kasbon_aktif": sum(_to_float(r.get("Sisa Kasbon")) for r in rows),
        "total_karyawan": len(rows),
    }


def _new_employee_id_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _resolve_payroll_employee(db: Session, row: Dict[str, Any]) -> Dict[str, Any]:
    new_employee_id = _new_employee_id_key(row.get("ID Karyawan"))
    result = {
        "employee_id": row.get("_employee_id"),
        "new_employee_id": row.get("ID Karyawan"),
        "employee_name": row.get("Nama", ""),
        "phone_number": None,
        "status": "MISSING_NEW_EMPLOYEE_ID" if not new_employee_id else "EMPLOYEE_NOT_FOUND",
    }
    if not new_employee_id:
        return result

    matches = db.query(models.Employee).filter(
        func.lower(func.trim(models.Employee.new_employee_id)) == new_employee_id,
        models.Employee.deleted_at.is_(None),
    ).all()
    if not matches:
        return result
    if len(matches) > 1:
        result["status"] = "AMBIGUOUS_EMPLOYEE_CODE"
        return result

    employee = matches[0]
    if row.get("_employee_id") is not None and row["_employee_id"] != employee.id:
        result["status"] = "EMPLOYEE_MAPPING_CHANGED"
        return result
    result["employee_id"] = employee.id
    if not employee.active:
        result["status"] = "EMPLOYEE_INACTIVE"
        return result

    identities = db.query(models.WhatsAppIdentity).filter(
        models.WhatsAppIdentity.employee_id == employee.id,
        models.WhatsAppIdentity.status == "ACTIVE",
    ).all()
    if not identities:
        result["status"] = "WHATSAPP_NOT_LINKED"
        return result
    if len(identities) > 1:
        result["status"] = "MULTIPLE_ACTIVE_LINKS"
        return result

    result["phone_number"] = normalize_whatsapp_number(identities[0].phone_number)
    result["status"] = "ACTIVE"
    return result


def _wa_send_succeeded(result: Optional[Dict[str, Any]]) -> bool:
    return bool(
        result
        and not result.get("error")
        and isinstance(result.get("messages"), list)
        and result["messages"]
    )


def _record_payroll_delivery(
    db: Session,
    entry: Dict[str, Any],
    row_index: int,
    row: Dict[str, Any],
    current_user: models.User,
    recipient_phone: Optional[str],
    status: str = "PENDING",
) -> models.PayrollWhatsAppDelivery:
    delivery = models.PayrollWhatsAppDelivery(
        payroll_session_id=entry["session_id"],
        row_index=row_index,
        employee_id=row.get("_employee_id"),
        new_employee_id=row.get("ID Karyawan") or None,
        employee_name=row.get("Nama") or "(Nama tidak tersedia)",
        payroll_period=entry.get("periode", ""),
        recipient_phone=recipient_phone,
        requested_by_user_id=current_user.id,
        status=status,
        created_at=datetime.datetime.utcnow(),
        completed_at=datetime.datetime.utcnow() if status != "PENDING" else None,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


async def _send_payroll_slip(
    emp: Dict[str, Any],
    periode: str,
    wa_number: str,
    row_index: int,
    pdf_bytes: bytes,
) -> Dict[str, Any]:
    errors = []
    try:
        text_result = await send_whatsapp_text(wa_number, _build_wa_text(emp, periode))
        text_sent = _wa_send_succeeded(text_result)
        if not text_sent:
            errors.append("Pengiriman rincian teks gagal.")
    except Exception as exc:
        text_sent = False
        errors.append(f"Pengiriman rincian teks gagal: {exc}")

    pdf_sent = False
    try:
        safe_name = re.sub(r"[^\w\-]", "_", emp.get("Nama", f"karyawan_{row_index}"))
        pdf_filename = f"SlipGaji_{safe_name}_{periode}.pdf"
        cloudinary_url = upload_to_cloudinary(
            file_bytes=pdf_bytes,
            filename=pdf_filename,
            folder="hr_slip_gaji",
            resource_type="raw",
        )
        if not cloudinary_url:
            errors.append("PDF gagal diunggah untuk pengiriman WhatsApp.")
        else:
            doc_result = await send_whatsapp_raw({
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": wa_number,
                "type": "document",
                "document": {
                    "link": cloudinary_url,
                    "filename": pdf_filename,
                    "caption": f"Slip Gaji Resmi - {emp.get('Nama', '')} - Periode {periode}",
                },
            })
            pdf_sent = _wa_send_succeeded(doc_result)
            if not pdf_sent:
                errors.append("Pengiriman dokumen PDF gagal.")
    except Exception as exc:
        errors.append(f"Proses PDF gagal: {exc}")

    if text_sent and pdf_sent:
        status = "SENT"
    elif text_sent or pdf_sent:
        status = "PARTIAL"
    else:
        status = "FAILED"
    return {
        "status": status,
        "text_sent": text_sent,
        "pdf_sent": pdf_sent,
        "error_detail": " ".join(errors) or None,
    }


def _rupiah(val: float) -> str:
    """Format angka ke string ribuan tanpa Rp."""
    return f"{val:,.0f}".replace(",", ".")


def _build_wa_text(emp: Dict[str, Any], periode: str) -> str:
    gp = _to_float(emp.get("Gaji Pokok", emp.get("GP")))
    um = _to_float(emp.get("Uang Makan"))
    tunjangan = _to_float(emp.get("Tunjangan"))
    lembur = _to_float(emp.get("Lembur"))
    pot_denda = _to_float(emp.get("Potongan Denda/SO", emp.get("Pot Denda/SO")))
    pot_telat = _to_float(emp.get("Potongan Telat", emp.get("Pot Telat")))
    pot_bpjs = _to_float(emp.get("Potongan BPJS", emp.get("Pot BPJS")))
    pot_lain = _to_float(emp.get("Potongan Lain", emp.get("Pot Lain")))
    kasbon = _to_float(emp.get("Kasbon Bulan Ini"))
    sisa_kasbon = _to_float(emp.get("Sisa Kasbon"))
    total_pend = _to_float(emp.get("Sub Total"))
    total_pot = _to_float(emp.get("Total Potongan"))
    thp = _to_float(emp.get("THP"))

    lines = [
        "📋 *SLIP GAJI KARYAWAN*",
        "PT. Javareef Indonesia Perkasa",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"👤 *Nama*    : {emp.get('Nama', '-')}",
        f"🏢 *Dept*    : {emp.get('Departemen', emp.get('Dept', '-'))}",
        f"📅 *Periode* : {periode}",
        f"📆 *Hari Kerja* : {int(_to_float(emp.get('Hari Kerja')))} hari",
        "",
        "💼 *PENDAPATAN*",
        f"  • Gaji Pokok       : Rp {_rupiah(gp)}",
        f"  • Uang Makan       : Rp {_rupiah(um)}",
        f"  • Tunjangan        : Rp {_rupiah(tunjangan)}",
        f"  • Lembur           : Rp {_rupiah(lembur)}",
        f"  ─────────────────────",
        f"  *Total Pendapatan  : Rp {_rupiah(total_pend)}*",
        "",
        "✂️ *POTONGAN*",
        f"  • BPJS             : Rp {_rupiah(pot_bpjs)}",
        f"  • Pinjaman/Kasbon  : Rp {_rupiah(kasbon)}",
        f"  • Denda/SO         : Rp {_rupiah(pot_denda)}",
        f"  • Pot. Telat       : Rp {_rupiah(pot_telat)}",
        f"  • Pot. Tidak Hadir : Rp {_rupiah(_to_float(emp.get('Potongan Nominal', emp.get('Pot Nominal'))))}",
        f"  • Potongan Lain    : Rp {_rupiah(pot_lain)}",
        f"  ─────────────────────",
        f"  *Total Potongan    : Rp {_rupiah(total_pot)}*",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 *TOTAL DITERIMA : Rp {_rupiah(thp)}*",
        f"📌 *Sisa Pinjaman  : Rp {_rupiah(sisa_kasbon)}*",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "_Slip gaji ini diterbitkan secara resmi oleh HR PT. Javareef Indonesia Perkasa._",
    ]
    return "\n".join(lines)


def _generate_slip_pdf_bytes(emp: Dict[str, Any], periode: str) -> bytes:
    """
    Generate PDF slip gaji menggunakan reportlab.
    Jika reportlab tidak tersedia, kembalikan bytes kosong.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        styles = getSampleStyleSheet()
        SLATE = colors.HexColor("#0f172a")
        INDIGO = colors.HexColor("#4f46e5")
        ROSE = colors.HexColor("#e11d48")
        LIGHT = colors.HexColor("#f8fafc")

        title_style = ParagraphStyle(
            "title", fontSize=14, fontName="Helvetica-Bold",
            textColor=SLATE, alignment=TA_CENTER, spaceAfter=2,
        )
        sub_style = ParagraphStyle(
            "sub", fontSize=9, fontName="Helvetica",
            textColor=colors.HexColor("#64748b"), alignment=TA_CENTER, spaceAfter=6,
        )
        label_style = ParagraphStyle(
            "label", fontSize=9, fontName="Helvetica-Bold", textColor=SLATE,
        )
        val_style = ParagraphStyle(
            "val", fontSize=9, fontName="Helvetica", textColor=SLATE,
        )
        section_style = ParagraphStyle(
            "section", fontSize=9, fontName="Helvetica-Bold",
            textColor=colors.white, alignment=TA_CENTER,
        )
        thp_style = ParagraphStyle(
            "thp", fontSize=12, fontName="Helvetica-Bold",
            textColor=INDIGO, alignment=TA_CENTER,
        )
        sisa_style = ParagraphStyle(
            "sisa", fontSize=10, fontName="Helvetica-Bold",
            textColor=ROSE, alignment=TA_CENTER,
        )

        def rupiah(v):
            return f"Rp {_rupiah(_to_float(v))}"

        elements = []

        # ── Kop Surat ──
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "public", "logo.png")
        )
        if os.path.exists(logo_path):
            from reportlab.platypus import Image as RLImage
            logo_img = RLImage(logo_path, width=32 * mm, height=15 * mm)
            header_table = Table(
                [[
                    logo_img,
                    [
                        Paragraph("PT. JAVAREEF INDONESIA PERKASA", title_style),
                        Paragraph(
                            "Jl. Kav. DPR Blk. A No.306, RT.003/RW.001, Kenanga, Kec. Cipondoh, Kota Tangerang, Banten 15146",
                            sub_style,
                        ),
                    ],
                ]],
                colWidths=[36 * mm, 134 * mm],
            )
            header_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(header_table)
        else:
            elements.append(Paragraph("PT. JAVAREEF INDONESIA PERKASA", title_style))
            elements.append(Paragraph(
                "Jl. Kav. DPR Blk. A No.306, RT.003/RW.001, Kenanga, Kec. Cipondoh, Kota Tangerang, Banten 15146",
                sub_style,
            ))
        elements.append(HRFlowable(width="100%", thickness=2, color=SLATE))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=SLATE, spaceAfter=8))

        elements.append(Paragraph("SLIP GAJI KARYAWAN", ParagraphStyle(
            "sliptitle", fontSize=11, fontName="Helvetica-Bold",
            textColor=SLATE, alignment=TA_RIGHT, spaceAfter=8,
        )))

        # ── Info Karyawan ──
        info_data = [
            [Paragraph("Nama", label_style), Paragraph(f": {emp.get('Nama', '-')}", val_style),
             Paragraph("Periode", label_style), Paragraph(f": {periode}", val_style)],
            [Paragraph("Dept.", label_style), Paragraph(f": {emp.get('Departemen', emp.get('Dept', '-'))}", val_style),
             Paragraph("Hari Kerja", label_style), Paragraph(f": {int(_to_float(emp.get('Hari Kerja')))} hari", val_style)],
            [Paragraph("No. Rek.", label_style), Paragraph(f": {emp.get('No. Rekening', '-')}", val_style),
             Paragraph("", val_style), Paragraph("", val_style)],
        ]
        info_table = Table(info_data, colWidths=[35 * mm, 65 * mm, 35 * mm, 35 * mm])
        info_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 6 * mm))

        # ── Pendapatan & Potongan ──
        header_bg = INDIGO
        alt_bg = colors.HexColor("#eef2ff")

        pend_rows = [
            [Paragraph("PENDAPATAN", section_style), Paragraph("", section_style)],
            ["Gaji Pokok", rupiah(emp.get("Gaji Pokok", emp.get("GP")))],
            ["Uang Makan", rupiah(emp.get("Uang Makan"))],
            ["Tunjangan Jabatan", rupiah(emp.get("Tunjangan"))],
            ["Lembur", rupiah(emp.get("Lembur"))],
            ["THR", "-"],
            ["Lain-Lain", "-"],
            [Paragraph("Total Pendapatan", label_style), Paragraph(rupiah(emp.get("Sub Total")), label_style)],
        ]
        pot_rows = [
            [Paragraph("POTONGAN", section_style), Paragraph("", section_style)],
            ["BPJS Kes. & Ketenagakerjaan", rupiah(emp.get("Potongan BPJS", emp.get("Pot BPJS")))],
            ["Pinjaman / Kasbon", rupiah(emp.get("Kasbon Bulan Ini"))],
            ["Denda Keterlambatan / SO", rupiah(emp.get("Potongan Denda/SO", emp.get("Pot Denda/SO")))],
            ["Tidak Hadir / Prorata", rupiah(emp.get("Potongan Nominal", emp.get("Pot Nominal")))],
            ["Potongan Telat", rupiah(emp.get("Potongan Telat", emp.get("Pot Telat")))],
            ["Potongan Lain-Lain", rupiah(emp.get("Potongan Lain", emp.get("Pot Lain")))],
            [Paragraph("Total Potongan", label_style), Paragraph(rupiah(emp.get("Total Potongan")), label_style)],
        ]

        def make_detail_table(rows, header_color=header_bg):
            t = Table(rows, colWidths=[75 * mm, 8 * mm])
            style = [
                ("BACKGROUND", (0, 0), (-1, 0), header_color),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, alt_bg]),
                ("LINEBELOW", (0, -1), (-1, -1), 1.5, SLATE),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 1), (0, -2), 6),
            ]
            t.setStyle(TableStyle(style))
            return t

        combined = Table(
            [[make_detail_table(pend_rows), make_detail_table(pot_rows, colors.HexColor("#dc2626"))]],
            colWidths=[85 * mm, 85 * mm],
        )
        combined.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(combined)
        elements.append(Spacer(1, 8 * mm))

        # ── Total Diterima ──
        thp_val = _to_float(emp.get("THP"))
        sisa_val = _to_float(emp.get("Sisa Kasbon"))

        footer_table = Table([
            [
                Paragraph("TOTAL JUMLAH DITERIMA", ParagraphStyle(
                    "tfooter", fontSize=10, fontName="Helvetica-Bold", textColor=SLATE,
                )),
                Paragraph(f"Rp {_rupiah(thp_val)}", ParagraphStyle(
                    "tfooterval", fontSize=11, fontName="Helvetica-Bold",
                    textColor=INDIGO, alignment=TA_RIGHT,
                )),
            ],
            [
                Paragraph("Sisa Pinjaman", ParagraphStyle(
                    "sisa_lbl", fontSize=9, fontName="Helvetica-Oblique", textColor=ROSE,
                )),
                Paragraph(f"Rp {_rupiah(sisa_val)}", ParagraphStyle(
                    "sisa_val", fontSize=9, fontName="Helvetica-BoldOblique",
                    textColor=ROSE, alignment=TA_RIGHT,
                )),
            ],
        ], colWidths=[120 * mm, 50 * mm])
        footer_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, 0), 1.5, INDIGO),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(footer_table)
        elements.append(Spacer(1, 10 * mm))

        # ── Tanda Tangan ──
        sign_table = Table([
            ["", "", Paragraph("Penerima,", ParagraphStyle("sign_lbl", fontSize=9, alignment=TA_CENTER))],
            ["", "", Spacer(1, 15 * mm)],
            ["", "", Paragraph(f"( {emp.get('Nama', '___________________')} )", ParagraphStyle("sign_name", fontSize=9, fontName="Helvetica-Bold", alignment=TA_CENTER))],
        ], colWidths=[80 * mm, 40 * mm, 50 * mm])
        elements.append(sign_table)

        doc.build(elements)
        buf.seek(0)
        return buf.getvalue()

    except ImportError:
        print("[Payroll] reportlab tidak terinstall, skip PDF generation.")
        return b""
    except Exception as e:
        print(f"[Payroll] Gagal generate PDF: {e}")
        return b""


# ---------------------------------------------------------------------------
# 1. Download Template
# ---------------------------------------------------------------------------

@router.get("/payroll/template")
def download_payroll_template(
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    _: models.User = Depends(auth.get_current_user),
):
    """Download template kosong Excel/CSV untuk upload data penggajian."""
    import pandas as pd
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    if format == "csv":
        csv_content = ",".join(TEMPLATE_INPUT_COLS) + "\n"
        return Response(
            content=csv_content.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="template_slip_gaji.csv"'},
        )

    # Excel dengan styling dan sheet panduan
    wb = Workbook()
    ws = wb.active
    ws.title = "Data Penggajian"

    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=11, color="0F172A")
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )
    required_fill = PatternFill(start_color="EEF2FF", end_color="EEF2FF", fill_type="solid")

    ws.append(TEMPLATE_INPUT_COLS)
    for col_num, col_name in enumerate(TEMPLATE_INPUT_COLS, start=1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)

    # 3 baris contoh kosong dengan format
    for row_idx in range(2, 5):
        for col_num, col_name in enumerate(TEMPLATE_INPUT_COLS, start=1):
            cell = ws.cell(row=row_idx, column=col_num)
            cell.font = data_font
            cell.border = thin_border
            cell.fill = required_fill
            if col_name in NUMERIC_COLS:
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "#,##0"
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    # Auto-width
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = max(max_len + 4, 14)
    ws.row_dimensions[1].height = 20

    # Sheet 2: Panduan
    ws2 = wb.create_sheet(title="Panduan Kolom")
    guide_headers = ["No", "Nama Kolom", "Tipe Data", "Wajib?", "Keterangan"]
    guide_rows = [
        [1, "ID Karyawan", "Teks", "Wajib untuk kirim WA", "ID Karyawan baru dari master; dipakai untuk mencocokkan linking WhatsApp."],
        [2, "Nama", "Teks", "Ya", "Nama lengkap karyawan sesuai master data."],
        [3, "No. Rekening", "Teks", "Ya", "Nomor rekening bank karyawan untuk transfer gaji."],
        [4, "Departemen", "Teks", "Ya", "Nama divisi/departemen karyawan."],
        [5, "Gaji Pokok", "Angka (Rp)", "Ya", "Gaji Pokok bulanan karyawan."],
        [6, "Potongan Hari", "Angka", "Opsional", "Jumlah hari tidak hadir (tanpa keterangan / alpha)."],
        [7, "Potongan Nominal", "Angka (Rp)", "Opsional", "Total nominal potongan karena tidak hadir (prorata)."],
        [8, "Uang Makan", "Angka (Rp)", "Opsional", "Total uang makan periode ini."],
        [9, "Hari Kerja", "Angka", "Opsional", "Jumlah hari kerja valid periode ini."],
        [10, "Lembur", "Angka (Rp)", "Opsional", "Total nominal bonus lembur."],
        [11, "Tunjangan", "Angka (Rp)", "Opsional", "Tunjangan jabatan / posisi."],
        [12, "Potongan Denda/SO", "Angka (Rp)", "Opsional", "Potongan denda / stock opname."],
        [13, "Potongan Telat", "Angka (Rp)", "Opsional", "Potongan karena keterlambatan."],
        [14, "Potongan BPJS", "Angka (Rp)", "Opsional", "Potongan BPJS Kesehatan & Ketenagakerjaan."],
        [15, "Potongan Lain", "Angka (Rp)", "Opsional", "Potongan lain-lain yang tidak masuk kategori di atas."],
        [16, "Kasbon Bulan Ini", "Angka (Rp)", "Opsional", "Angsuran kasbon/pinjaman yang dipotong bulan ini."],
        [17, "Sisa Kasbon", "Angka (Rp)", "Opsional", "Total sisa pinjaman aktif karyawan (piutang)."],
    ]
    guide_title = ws2.cell(row=1, column=1, value="PANDUAN FORMAT TEMPLATE DATA PENGGAJIAN (SLIP GAJI)")
    guide_title.font = Font(name="Calibri", size=13, bold=True, color="1E293B")
    ws2.append([])
    ws2.append(guide_headers)
    for c in range(1, len(guide_headers) + 1):
        cell = ws2.cell(row=3, column=c)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for r_idx, grow in enumerate(guide_rows, start=4):
        ws2.append(grow)
        for c in range(1, 6):
            cell = ws2.cell(row=r_idx, column=c)
            cell.font = data_font
            cell.border = thin_border
            if c in (1, 4):
                cell.alignment = Alignment(horizontal="center")
    for col in ws2.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws2.column_dimensions[get_column_letter(col[0].column)].width = max(min(max_len + 4, 60), 10)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="template_slip_gaji.xlsx"'},
    )


# ---------------------------------------------------------------------------
# 2. Upload & Proses
# ---------------------------------------------------------------------------

@router.post("/payroll/upload")
async def upload_payroll(
    file: UploadFile = File(..., description="File Excel atau CSV data penggajian"),
    periode: str = Query("", description="Label periode, contoh: Okt-26"),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """
    Upload file data penggajian, parse, hitung THP, kembalikan JSON session.
    Juga enrich nomor WhatsApp karyawan dari database WhatsAppIdentity.
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in PAYROLL_ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Format file tidak didukung: '{ext}'. Gunakan .xlsx, .xls, atau .csv.",
        )

    raw_bytes = await file.read()
    rows = _parse_payroll_file(raw_bytes, file.filename or "data.xlsx")

    if not rows:
        raise HTTPException(status_code=422, detail="File tidak mengandung data karyawan.")

    for row in rows:
        row["_employee_id"] = None
        resolved = _resolve_payroll_employee(db, row)
        row["_employee_id"] = resolved["employee_id"]
        row["_wa_number"] = resolved["phone_number"] or ""
        row["_wa_status"] = resolved["status"]
        row["_wa_available"] = resolved["status"] == "ACTIVE"

    session_id = uuid.uuid4().hex
    session_data = {
        "session_id": session_id,
        "rows": rows,
        "kpis": _build_kpis(rows),
        "periode": periode or datetime.datetime.now().strftime("%b-%y"),
        "filename": file.filename,
    }
    _file_store[f"payroll_{session_id}"] = session_data

    return JSONResponse(content={
        "session_id": session_id,
        "periode": session_data["periode"],
        "kpis": session_data["kpis"],
        "rows": rows,
    })


# ---------------------------------------------------------------------------
# 3. Recalculate (Live Edit Patch)
# ---------------------------------------------------------------------------

@router.patch("/payroll/{session_id}/row/{row_index}")
def patch_payroll_row(
    session_id: str,
    row_index: int,
    payload: Dict[str, Any],
    _: models.User = Depends(auth.get_current_user),
):
    """
    Update satu baris data payroll di session dan kembalikan kalkulasi terbaru.
    Digunakan oleh Live Edit di tabel frontend.
    """
    key = f"payroll_{session_id}"
    entry = _file_store.get(key)
    if not entry:
        raise HTTPException(status_code=404, detail="Sesi payroll tidak ditemukan atau sudah kedaluwarsa.")
    rows: List[Dict] = entry["rows"]
    if row_index < 0 or row_index >= len(rows):
        raise HTTPException(status_code=400, detail="Index baris tidak valid.")

    # Update field yang dikirim
    for field, value in payload.items():
        if field in TEMPLATE_INPUT_COLS:
            rows[row_index][field] = _to_float(value) if field in NUMERIC_COLS else value

    rows[row_index] = _calculate_row(rows[row_index])
    entry["kpis"] = _build_kpis(rows)

    return {
        "row": rows[row_index],
        "kpis": entry["kpis"],
    }


# ---------------------------------------------------------------------------
# 4. Export Excel Rekap
# ---------------------------------------------------------------------------

@router.get("/payroll/{session_id}/export-excel")
def export_payroll_excel(
    session_id: str,
    _: models.User = Depends(auth.get_current_user),
):
    """Generate dan download file Excel rekap penggajian dari session aktif."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    key = f"payroll_{session_id}"
    entry = _file_store.get(key)
    if not entry:
        raise HTTPException(status_code=404, detail="Sesi payroll tidak ditemukan atau sudah kedaluwarsa.")

    rows: List[Dict] = entry["rows"]
    periode = entry.get("periode", "")

    export_cols = TEMPLATE_INPUT_COLS + ["Sub Total", "THP"]
    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=11, color="0F172A")
    thp_font = Font(name="Calibri", size=11, bold=True, color="4F46E5")
    thin = Border(
        left=Side(style="thin", color="E2E8F0"), right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"), bottom=Side(style="thin", color="E2E8F0"),
    )
    zebra = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    thp_fill = PatternFill(start_color="EEF2FF", end_color="EEF2FF", fill_type="solid")

    wb = Workbook()
    ws = wb.active
    ws.title = f"Slip Gaji {periode}"

    # Title row
    ws.merge_cells("A1:S1")
    title_cell = ws.cell(row=1, column=1, value=f"REKAP PENGGAJIAN — PERIODE: {periode}")
    title_cell.font = Font(name="Calibri", size=13, bold=True, color="0F172A")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22

    ws.append(export_cols)
    for c_num in range(1, len(export_cols) + 1):
        cell = ws.cell(row=2, column=c_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 18

    for r_idx, row in enumerate(rows, start=3):
        use_zebra = r_idx % 2 == 0
        for c_num, col_name in enumerate(export_cols, start=1):
            val = row.get(col_name, "")
            cell = ws.cell(row=r_idx, column=c_num, value=val)
            cell.border = thin
            is_thp = col_name == "THP"
            cell.font = thp_font if is_thp else data_font
            if col_name in NUMERIC_COLS or col_name in ("Sub Total", "THP", "Total Potongan"):
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "#,##0"
                if is_thp:
                    cell.fill = thp_fill
                elif use_zebra:
                    cell.fill = zebra
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")
                if use_zebra:
                    cell.fill = zebra

    # Summary row
    kpis = entry["kpis"]
    summary_row = ws.max_row + 1
    ws.cell(row=summary_row, column=1, value="TOTAL").font = Font(name="Calibri", size=11, bold=True)
    thp_col = export_cols.index("THP") + 1
    thp_sum_cell = ws.cell(row=summary_row, column=thp_col, value=kpis.get("total_thp", 0))
    thp_sum_cell.font = Font(name="Calibri", size=11, bold=True, color="4F46E5")
    thp_sum_cell.number_format = "#,##0"
    thp_sum_cell.fill = PatternFill(start_color="C7D2FE", end_color="C7D2FE", fill_type="solid")

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = max(min(max_len + 3, 22), 10)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    safe_periode = re.sub(r"[^\w\-]", "_", periode)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Rekap_SlipGaji_{safe_periode}.xlsx"'},
    )


# ---------------------------------------------------------------------------
# 5. Download PDF Slip per Karyawan
# ---------------------------------------------------------------------------

@router.get("/payroll/{session_id}/slip-pdf/{row_index}")
def download_slip_pdf(
    session_id: str,
    row_index: int,
    _: models.User = Depends(auth.get_current_user),
):
    """Download PDF slip gaji untuk satu karyawan."""
    key = f"payroll_{session_id}"
    entry = _file_store.get(key)
    if not entry:
        raise HTTPException(status_code=404, detail="Sesi payroll tidak ditemukan.")
    rows: List[Dict] = entry["rows"]
    if row_index < 0 or row_index >= len(rows):
        raise HTTPException(status_code=400, detail="Index baris tidak valid.")

    emp = rows[row_index]
    periode = entry.get("periode", "")
    pdf_bytes = _generate_slip_pdf_bytes(emp, periode)

    if not pdf_bytes:
        raise HTTPException(
            status_code=500,
            detail="Gagal generate PDF. Pastikan library 'reportlab' terinstall di server.",
        )

    safe_name = re.sub(r"[^\w\-]", "_", emp.get("Nama", f"karyawan_{row_index}"))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="SlipGaji_{safe_name}_{periode}.pdf"'},
    )


@router.post("/payroll/{session_id}/archive-all")
async def archive_all_payroll_slips(
    session_id: str,
    pdfs: List[UploadFile] = File(..., description="PDF slip hasil render dari pratinjau final"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Simpan PDF final semua slip pada periode payroll di database."""
    entry = _file_store.get(f"payroll_{session_id}")
    if not entry:
        raise HTTPException(status_code=404, detail="Sesi payroll tidak ditemukan atau sudah kedaluwarsa.")

    rows: List[Dict[str, Any]] = entry.get("rows") or []
    period = str(entry.get("periode") or "").strip()
    if not rows:
        raise HTTPException(status_code=422, detail="Tidak ada slip gaji untuk disimpan.")
    if not period or len(period) > 100:
        raise HTTPException(status_code=422, detail="Periode payroll tidak valid.")
    if len(pdfs) != len(rows):
        raise HTTPException(
            status_code=422,
            detail="Jumlah PDF tidak cocok dengan jumlah karyawan pada sesi payroll.",
        )

    employee_ids = [row.get("_employee_id") for row in rows]
    if any(not isinstance(employee_id, int) for employee_id in employee_ids):
        raise HTTPException(
            status_code=422,
            detail="Semua baris payroll harus cocok dengan karyawan yang terdaftar di database sebelum disimpan.",
        )
    if len(set(employee_ids)) != len(employee_ids):
        raise HTTPException(
            status_code=422,
            detail="Ada karyawan yang muncul lebih dari sekali pada periode ini; perbaiki data payroll terlebih dahulu.",
        )
    if any(_resolve_payroll_employee(db, row)["employee_id"] != row["_employee_id"] for row in rows):
        raise HTTPException(
            status_code=422,
            detail="Pemetaan ID karyawan berubah sejak file payroll diunggah. Unggah ulang data sebelum menyimpan.",
        )

    existing_employee_ids = {
        employee.id
        for employee in db.query(models.Employee.id)
        .filter(models.Employee.id.in_(employee_ids))
        .all()
    }
    if existing_employee_ids != set(employee_ids):
        raise HTTPException(status_code=422, detail="Data karyawan payroll sudah tidak tersedia.")

    rendered_slips = []
    for row, uploaded_pdf in zip(rows, pdfs):
        if uploaded_pdf.content_type not in (None, "application/pdf"):
            raise HTTPException(status_code=400, detail="Semua arsip harus berupa file PDF.")
        pdf_bytes = await uploaded_pdf.read(PAYROLL_PDF_MAX_BYTES + 1)
        if not pdf_bytes.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=400,
                detail=f"PDF slip untuk {row.get('Nama') or 'karyawan'} tidak valid.",
            )
        if len(pdf_bytes) > PAYROLL_PDF_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Ukuran PDF slip {row.get('Nama') or 'karyawan'} melebihi batas 10 MB.",
            )
        rendered_slips.append((row, pdf_bytes))

    saved_at = datetime.datetime.utcnow()
    expires_at = _one_year_from(saved_at)
    try:
        existing_slips = {
            slip.employee_id: slip
            for slip in db.query(models.PayrollSlipArchive)
            .filter(
                models.PayrollSlipArchive.employee_id.in_(employee_ids),
                models.PayrollSlipArchive.payroll_period == period,
            )
            .all()
        }
        replaced_count = 0
        for row, pdf_bytes in rendered_slips:
            employee_id = row["_employee_id"]
            archived_slip = existing_slips.get(employee_id)
            if archived_slip:
                archived_slip.employee_name = str(row.get("Nama") or "Karyawan")
                archived_slip.pdf_bytes = pdf_bytes
                archived_slip.saved_by_user_id = current_user.id
                archived_slip.saved_at = saved_at
                archived_slip.expires_at = expires_at
                replaced_count += 1
            else:
                db.add(models.PayrollSlipArchive(
                    employee_id=employee_id,
                    payroll_period=period,
                    employee_name=str(row.get("Nama") or "Karyawan"),
                    pdf_bytes=pdf_bytes,
                    saved_by_user_id=current_user.id,
                    saved_at=saved_at,
                    expires_at=expires_at,
                ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Arsip periode ini berubah bersamaan. Muat ulang payroll lalu coba simpan kembali.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Gagal menyimpan arsip slip gaji ke database.") from exc

    return {
        "status": "SAVED",
        "periode": period,
        "saved_count": len(rendered_slips),
        "replaced_count": replaced_count,
        "expires_at": expires_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# 6. Preview linking and delivery history
# ---------------------------------------------------------------------------

@router.get("/payroll/{session_id}/whatsapp-recipients")
def preview_payroll_whatsapp_recipients(
    session_id: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    key = f"payroll_{session_id}"
    entry = _file_store.get(key)
    if not entry:
        raise HTTPException(status_code=404, detail="Sesi payroll tidak ditemukan atau sudah kedaluwarsa.")

    recipients = []
    for row_index, row in enumerate(entry["rows"]):
        resolved = _resolve_payroll_employee(db, row)
        recipients.append({
            "row_index": row_index,
            "employee_id": resolved["employee_id"],
            "new_employee_id": row.get("ID Karyawan", ""),
            "nama": row.get("Nama", ""),
            "wa_number": resolved["phone_number"],
            "status": resolved["status"],
        })
    return {"periode": entry.get("periode", ""), "recipients": recipients}


@router.get("/payroll/{session_id}/send-history")
def list_payroll_whatsapp_history(
    session_id: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    rows = (
        db.query(models.PayrollWhatsAppDelivery)
        .filter(models.PayrollWhatsAppDelivery.payroll_session_id == session_id)
        .order_by(models.PayrollWhatsAppDelivery.created_at.desc())
        .all()
    )
    return [{
        "id": row.id,
        "row_index": row.row_index,
        "employee_id": row.employee_id,
        "new_employee_id": row.new_employee_id,
        "legacy_employee_code": None,
        "nama": row.employee_name,
        "periode": row.payroll_period,
        "wa_number": row.recipient_phone,
        "status": row.status,
        "text_status": row.text_status,
        "pdf_status": row.pdf_status,
        "error_detail": row.error_detail,
        "requested_by_user_id": row.requested_by_user_id,
        "created_at": row.created_at,
        "completed_at": row.completed_at,
    } for row in rows]


def _finish_delivery(
    db: Session,
    delivery: models.PayrollWhatsAppDelivery,
    result: Dict[str, Any],
) -> None:
    delivery.status = result["status"]
    delivery.text_status = "SENT" if result["text_sent"] else "FAILED"
    delivery.pdf_status = "SENT" if result["pdf_sent"] else "FAILED"
    delivery.error_detail = result["error_detail"]
    delivery.completed_at = datetime.datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# 7. Kirim WhatsApp per Karyawan
# ---------------------------------------------------------------------------

@router.post("/payroll/{session_id}/send-whatsapp/{row_index}")
async def send_slip_whatsapp(
    session_id: str,
    row_index: int,
    pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Revalidasi linking lalu kirim teks dan PDF yang dirender dari pratinjau slip.
    """
    if pdf.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Berkas yang dikirim harus berformat PDF.")
    pdf_bytes = await pdf.read(PAYROLL_PDF_MAX_BYTES + 1)
    if len(pdf_bytes) > PAYROLL_PDF_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Ukuran PDF slip melebihi batas 10 MB.")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Berkas PDF slip tidak valid.")

    key = f"payroll_{session_id}"
    entry = _file_store.get(key)
    if not entry:
        raise HTTPException(status_code=404, detail="Sesi payroll tidak ditemukan.")
    rows: List[Dict] = entry["rows"]
    if row_index < 0 or row_index >= len(rows):
        raise HTTPException(status_code=400, detail="Index baris tidak valid.")

    emp = rows[row_index]
    resolved = _resolve_payroll_employee(db, emp)
    if resolved["status"] != "ACTIVE":
        audit_row = {**emp, "_employee_id": resolved["employee_id"]}
        _record_payroll_delivery(
            db,
            entry,
            row_index,
            audit_row,
            current_user,
            resolved["phone_number"],
            status="SKIPPED",
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Pengiriman diblokir untuk {emp.get('Nama', 'karyawan ini')}: "
                f"{resolved['status']}. Periksa ID Karyawan dan linking WhatsApp aktif."
            ),
        )

    periode = entry.get("periode", "")
    wa_number = resolved["phone_number"]
    audit_row = {**emp, "_employee_id": resolved["employee_id"]}
    delivery = _record_payroll_delivery(
        db, entry, row_index, audit_row, current_user, wa_number,
    )
    result = await _send_payroll_slip(emp, periode, wa_number, row_index, pdf_bytes)
    _finish_delivery(db, delivery, result)
    return {
        "status": result["status"],
        "nama": emp.get("Nama"),
        "wa_number": wa_number,
        "text_sent": result["text_sent"],
        "pdf_sent": result["pdf_sent"],
        "detail": result["error_detail"],
        "delivery_id": delivery.id,
    }


# ---------------------------------------------------------------------------
# 7. Kirim WhatsApp ke Semua Karyawan
# ---------------------------------------------------------------------------

@router.post("/payroll/{session_id}/send-whatsapp-all")
async def send_slip_whatsapp_all(
    session_id: str,
    _: models.User = Depends(auth.get_current_user),
):
    """Bulk legacy endpoint disabled to prevent sending PDFs outside the preview renderer."""
    raise HTTPException(
        status_code=409,
        detail="Buat PDF dari pratinjau untuk setiap karyawan, lalu gunakan endpoint pengiriman individual.",
    )
