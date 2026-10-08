# -*- coding: utf-8 -*-
import datetime
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query, File, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..employee_imports import normalize_text, parse_master_workbook, parse_recap_workbook

router = APIRouter(prefix="/employees", tags=["employees"])


from ..config import CONTRACT_REMINDER_DAYS, calculate_tenure, get_today_jakarta


def _name_reference_conflict(db: Session, employee: models.Employee, new_name: str) -> Optional[str]:
    old_key = normalize_text(employee.nama)
    new_key = normalize_text(new_name)
    if old_key == new_key:
        return None

    other_employees = db.query(models.Employee).filter(models.Employee.id != employee.id).all()
    if any(normalize_text(row.nama) in (old_key, new_key) for row in other_employees):
        return "Nama lama/baru dipakai karyawan lain; relasi berbasis nama perlu ditinjau."

    adjustments = db.query(models.EmployeeAdjustment).all()
    if any(normalize_text(row.nama) == new_key for row in adjustments):
        return "Penyesuaian karyawan dengan nama tujuan sudah ada."

    manual_rows = db.query(models.AbsenManual).all()
    old_manual = [row for row in manual_rows if normalize_text(row.nama) == old_key]
    target_periods = {
        (row.tahun, row.bulan)
        for row in manual_rows
        if normalize_text(row.nama) == new_key
    }
    if any((row.tahun, row.bulan) in target_periods for row in old_manual):
        return "Absen manual dengan nama tujuan sudah ada pada periode yang sama."
    return None


def _rename_employee_name_references(db: Session, old_name: str, new_name: str) -> None:
    old_key = normalize_text(old_name)
    if old_key == normalize_text(new_name):
        return
    for row in db.query(models.LeaveRequest).all():
        if normalize_text(row.nama) == old_key:
            row.nama = new_name
    for row in db.query(models.EmployeeAdjustment).all():
        if normalize_text(row.nama) == old_key:
            row.nama = new_name
    for row in db.query(models.AbsenManual).all():
        if normalize_text(row.nama) == old_key:
            row.nama = new_name


def _candidate_dict(candidate: models.EmployeeImportCandidate) -> dict:
    return {
        "id": candidate.id,
        "employee_code": candidate.employee_code,
        "nama": candidate.nama,
        "nik": candidate.nik,
        "join_date": candidate.join_date,
        "uang_makan_override": candidate.uang_makan_override,
        "jabatan": candidate.jabatan,
        "cabang": candidate.cabang,
        "payroll_status": candidate.payroll_status,
        "source_row": candidate.source_row,
        "status": candidate.status,
    }


@router.post("/import/master")
async def import_employee_master(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    deactivate_missing: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """Sinkronkan Master dengan pratinjau aman; karyawan baru menunggu review profil."""
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="File Master harus berformat .xlsx atau .xlsm.")
    try:
        rows, conflicts = parse_master_workbook(await file.read())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not rows and not conflicts:
        raise HTTPException(status_code=400, detail="Workbook Master tidak berisi data karyawan.")

    employees = db.query(models.Employee).all()
    by_code = {}
    by_nik = {}
    by_name = {}
    for employee in employees:
        if employee.employee_code:
            by_code.setdefault(employee.employee_code, []).append(employee)
        if employee.nik:
            by_nik.setdefault(employee.nik, []).append(employee)
        by_name.setdefault(normalize_text(employee.nama), []).append(employee)

    present_codes = {row["employee_code"] for row in rows}
    present_codes.update(
        conflict["employee_code"]
        for conflict in conflicts
        if conflict.get("employee_code")
    )
    plans = []
    matched_employee_ids = set()
    for row in rows:
        code = row["employee_code"]
        employee = None
        matched_by = None
        code_matches = by_code.get(code, [])
        if len(code_matches) > 1:
            conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "ID JIP duplikat di database."})
            continue
        if code_matches:
            employee, matched_by = code_matches[0], "employee_code"
        elif row["nik"]:
            nik_matches = by_nik.get(row["nik"], [])
            if len(nik_matches) > 1:
                conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "NIK terhubung ke lebih dari satu karyawan di database."})
                continue
            if nik_matches:
                employee, matched_by = nik_matches[0], "nik"
        if employee is None:
            name_matches = by_name.get(normalize_text(row["nama"]), [])
            if len(name_matches) > 1:
                conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "Nama cocok ke lebih dari satu karyawan di database."})
                continue
            if name_matches:
                employee, matched_by = name_matches[0], "nama"

        if employee is None:
            plans.append({"row": row, "employee": None, "matched_by": None})
            continue
        if employee.id in matched_employee_ids:
            conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "Karyawan database sudah dicocokkan dengan baris Master lain."})
            continue
        if employee.employee_code and employee.employee_code != code:
            conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "Karyawan yang cocok sudah memiliki ID JIP berbeda."})
            continue
        if row["nik"]:
            owners = [owner for owner in by_nik.get(row["nik"], []) if owner.id != employee.id]
            if owners:
                conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "NIK sudah dipakai karyawan lain di database."})
                continue
            if matched_by != "employee_code" and employee.nik and employee.nik != row["nik"]:
                conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "NIK berbeda dari karyawan yang cocok; perlu verifikasi manual."})
                continue
        if any(
            other.id != employee.id and normalize_text(other.nama) == normalize_text(row["nama"])
            for other in employees
        ):
            conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "Nama kanonis sudah dipakai karyawan lain."})
            continue
        rename_conflict = _name_reference_conflict(db, employee, row["nama"])
        if rename_conflict:
            conflicts.append({"row": row["source_row"], "employee_code": code, "reason": rename_conflict})
            continue
        plans.append({"row": row, "employee": employee, "matched_by": matched_by})
        matched_employee_ids.add(employee.id)

    candidate_by_code = {
        candidate.employee_code: candidate
        for candidate in db.query(models.EmployeeImportCandidate)
        .all()
    }
    updates = []
    new_candidates = []
    for plan in plans:
        row = plan["row"]
        employee = plan["employee"]
        if employee is None:
            new_candidates.append(row)
            continue
        changed = ["employee_code", "cabang", "active"]
        if normalize_text(employee.nama) != normalize_text(row["nama"]):
            changed.append("nama")
        if row["nik"] and employee.nik != row["nik"]:
            changed.append("nik")
        if row["join_date"] and employee.join_date != row["join_date"]:
            changed.append("join_date")
        if row["uang_makan_override"] is not None and employee.uang_makan_override != row["uang_makan_override"]:
            changed.append("uang_makan_override")
        if row["jabatan"] and employee.jabatan != row["jabatan"]:
            changed.append("jabatan")
        if row["payroll_status"] and employee.payroll_status != row["payroll_status"]:
            changed.append("payroll_status")
        updates.append({
            "row": row,
            "employee_id": employee.id,
            "matched_by": plan["matched_by"],
            "fields": changed,
        })

    removal_candidates = [
        employee for employee in employees
        if employee.employee_code and employee.employee_code not in present_codes
    ]
    deactivation_blocked = bool(deactivate_missing and conflicts)
    source_row_numbers = {
        row["source_row"] for row in rows
    } | {
        conflict["row"] for conflict in conflicts if conflict.get("row") is not None
    }

    if not dry_run:
        try:
            for plan in plans:
                row = plan["row"]
                employee = plan["employee"]
                if employee is None:
                    candidate = candidate_by_code.get(row["employee_code"])
                    if candidate is None:
                        candidate = models.EmployeeImportCandidate(employee_code=row["employee_code"])
                        db.add(candidate)
                        candidate_by_code[row["employee_code"]] = candidate
                    elif candidate.status != "PENDING":
                        candidate.status = "PENDING"
                        candidate.approved_employee_id = None
                    for field in (
                        "nama", "nik", "join_date", "uang_makan_override", "jabatan",
                        "cabang", "payroll_status", "source_row",
                    ):
                        setattr(candidate, field, row[field])
                    continue

                old_name = employee.nama
                if normalize_text(old_name) != normalize_text(row["nama"]):
                    _rename_employee_name_references(db, old_name, row["nama"])
                    employee.nama = row["nama"]
                employee.employee_code = row["employee_code"]
                employee.cabang = row["cabang"]
                employee.active = True
                if row["nik"]:
                    employee.nik = row["nik"]
                if row["join_date"]:
                    employee.join_date = row["join_date"]
                if row["uang_makan_override"] is not None:
                    employee.uang_makan_override = row["uang_makan_override"]
                if row["jabatan"]:
                    employee.jabatan = row["jabatan"]
                if row["payroll_status"]:
                    employee.payroll_status = row["payroll_status"]
                candidate = candidate_by_code.get(row["employee_code"])
                if candidate and candidate.status == "PENDING":
                    candidate.status = "APPROVED"
                    candidate.approved_employee_id = employee.id

            if deactivate_missing and not deactivation_blocked:
                for employee in removal_candidates:
                    employee.active = False
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Sinkronisasi dibatalkan karena konflik ID JIP/NIK yang unik.") from exc
        except Exception:
            db.rollback()
            raise
    else:
        db.rollback()

    return {
        "message": "Pratinjau selesai." if dry_run else "Sinkronisasi selesai; karyawan baru menunggu review HR.",
        "dry_run": dry_run,
        "total_source_rows": len(source_row_numbers),
        "total_updated": len(updates),
        "total_new_pending_review": len(new_candidates),
        "total_conflicts": len(conflicts),
        "total_missing_from_master": len(removal_candidates),
        "deactivate_missing_requested": deactivate_missing,
        "deactivation_blocked_by_conflicts": deactivation_blocked,
        "detail": {
            "updated": updates,
            "new_pending_review": [
                {"source_row": row["source_row"], "employee_code": row["employee_code"], "nama": row["nama"]}
                for row in new_candidates
            ],
            "conflicts": conflicts,
            "missing_from_master": [
                {"employee_id": employee.id, "employee_code": employee.employee_code, "nama": employee.nama}
                for employee in removal_candidates
            ],
        },
    }


@router.get("/import/master/pending")
def list_employee_import_candidates(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    rows = (
        db.query(models.EmployeeImportCandidate)
        .filter(models.EmployeeImportCandidate.status == "PENDING")
        .order_by(models.EmployeeImportCandidate.employee_code)
        .all()
    )
    return [_candidate_dict(row) for row in rows]


@router.post("/import/master/pending/{candidate_id}/approve", response_model=schemas.EmployeeOut)
def approve_employee_import_candidate(
    candidate_id: int,
    payload: schemas.EmployeeImportApproval,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    candidate = db.query(models.EmployeeImportCandidate).filter(
        models.EmployeeImportCandidate.id == candidate_id,
        models.EmployeeImportCandidate.status == "PENDING",
    ).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Kandidat impor tidak ditemukan atau sudah diproses.")
    profile = db.query(models.Profile).filter(models.Profile.code == payload.profile_code).first()
    if not profile:
        raise HTTPException(status_code=400, detail=f"Profil '{payload.profile_code}' tidak ditemukan.")

    employment_status = _normalize_employment_status(payload.employment_status)
    if employment_status not in ("PKWTT", "PKWT", "PHL"):
        raise HTTPException(status_code=400, detail="Status kepegawaian harus PKWTT, PKWT, atau PHL.")
    join_date = payload.join_date or candidate.join_date
    if not join_date:
        raise HTTPException(status_code=400, detail="Tanggal Join wajib dilengkapi sebelum kandidat diaktifkan.")
    if candidate.nik and db.query(models.Employee).filter(models.Employee.nik == candidate.nik).first():
        raise HTTPException(status_code=409, detail="NIK kandidat sudah dipakai karyawan lain.")
    if db.query(models.Employee).filter(models.Employee.employee_code == candidate.employee_code).first():
        raise HTTPException(status_code=409, detail="ID JIP kandidat sudah terdaftar sebagai karyawan.")

    contract = None
    if employment_status == "PKWT":
        if not payload.contract_start_date or not payload.contract_end_date:
            raise HTTPException(status_code=400, detail="Tanggal mulai dan akhir kontrak wajib untuk PKWT.")
        if payload.contract_end_date <= payload.contract_start_date:
            raise HTTPException(status_code=400, detail="Tanggal akhir kontrak harus setelah tanggal mulai.")
        contract = (payload.contract_start_date, payload.contract_end_date)

    employee = models.Employee(
        employee_code=candidate.employee_code,
        nama=candidate.nama,
        nik=candidate.nik,
        profile_code=profile.code,
        cabang=candidate.cabang,
        jabatan=candidate.jabatan,
        payroll_status=candidate.payroll_status,
        uang_makan_override=candidate.uang_makan_override,
        join_date=join_date,
        employment_status=employment_status,
        active=True,
        profile_needs_review=False,
    )
    db.add(employee)
    db.flush()
    if contract:
        db.add(models.EmploymentContract(
            employee_id=employee.id,
            contract_number=1,
            start_date=contract[0],
            end_date=contract[1],
            status="ACTIVE",
            keterangan=payload.contract_keterangan or "Kontrak pertama (impor Master)",
        ))
    candidate.status = "APPROVED"
    candidate.approved_employee_id = employee.id
    db.commit()
    db.refresh(employee)
    _enrich_employee_data(employee)
    return employee


@router.post("/import/recap")
async def import_clean_attendance_recap(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """Impor kode cuti/sakit terverifikasi; T tidak menjadi hitungan scan/keterlambatan."""
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="File Rekap harus berformat .xlsx atau .xlsm.")
    try:
        rows, conflicts = parse_recap_workbook(await file.read())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    employee_by_code = {
        employee.employee_code: employee
        for employee in db.query(models.Employee).filter(models.Employee.employee_code.isnot(None)).all()
    }
    event_categories = {
        "C": ("CUTI_TAHUNAN", 1.0),
        "CS": ("CUTI_SETENGAH_HARI", 0.5),
        "S": ("SAKIT", 1.0),
    }
    existing_import_keys = {
        request.import_key
        for request in db.query(models.LeaveRequest).filter(models.LeaveRequest.import_key.isnot(None)).all()
    }
    all_leaves = db.query(models.LeaveRequest).all()
    seen_keys = set()
    prepared = []
    ignored_late = 0
    duplicates = 0

    for row in rows:
        code = row["employee_code"]
        employee = employee_by_code.get(code)
        if not employee:
            conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "ID JIP belum terdaftar di database; sinkronkan Master dahulu."})
            continue
        if row["nik"] and employee.nik and row["nik"] != employee.nik:
            conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "NIK Rekap berbeda dari Master/database."})
            continue
        if normalize_text(row["nama"]) != normalize_text(employee.nama):
            conflicts.append({"row": row["source_row"], "employee_code": code, "reason": "Nama Rekap berbeda dari Master/database."})
            continue
        if row["mark"] == "T":
            ignored_late += 1
            continue
        if row["mark"] not in event_categories:
            conflicts.append({"row": row["source_row"], "employee_code": code, "reason": f"Kode keterangan tidak dikenal: {row['mark'] or '(kosong)'}."})
            continue

        category, days = event_categories[row["mark"]]
        import_key = f"rekap-bersih:{code}:{row['tanggal'].isoformat()}:{category}"
        if import_key in seen_keys or import_key in existing_import_keys:
            duplicates += 1
            continue
        already_recorded = any(
            normalize_text(leave.nama) == normalize_text(employee.nama)
            and leave.tanggal_mulai == row["tanggal"]
            and leave.tanggal_selesai == row["tanggal"]
            and leave.kategori == category
            for leave in all_leaves
        )
        if already_recorded:
            duplicates += 1
            seen_keys.add(import_key)
            continue
        seen_keys.add(import_key)
        prepared.append({
            "source_row": row["source_row"],
            "employee": employee,
            "employee_code": code,
            "tanggal": row["tanggal"],
            "mark": row["mark"],
            "kategori": category,
            "jumlah_hari": days,
            "import_key": import_key,
        })

    source_row_numbers = {
        row["source_row"] for row in rows
    } | {
        conflict["row"] for conflict in conflicts if conflict.get("row") is not None
    }

    if not dry_run:
        from ..leave_logic import record_leave_used
        try:
            for item in prepared:
                leave = models.LeaveRequest(
                    import_key=item["import_key"],
                    nama=item["employee"].nama,
                    kategori=item["kategori"],
                    tanggal_mulai=item["tanggal"],
                    tanggal_selesai=item["tanggal"],
                    jumlah_hari=item["jumlah_hari"],
                    alasan=f"Diimpor dari Rekap Kehadiran Bersih ({item['mark']}).",
                    status="APPROVED",
                    catatan_hr="Histori impor dari Rekap Kehadiran Bersih.",
                    approved_by="Import Rekap Kehadiran Bersih",
                    approved_at=datetime.datetime.utcnow(),
                )
                db.add(leave)
                db.flush()
                if item["kategori"] in ("CUTI_TAHUNAN", "CUTI_SETENGAH_HARI"):
                    record_leave_used(
                        db,
                        item["employee"].id,
                        item["tanggal"].year,
                        item["jumlah_hari"],
                        leave.id,
                        f"{item['kategori']} {item['tanggal']} (import Rekap)",
                        commit=False,
                    )
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Impor dibatalkan karena ada baris Rekap yang sudah pernah diimpor.") from exc
        except Exception:
            db.rollback()
            raise
    else:
        db.rollback()

    return {
        "message": "Pratinjau selesai." if dry_run else "Impor Rekap selesai.",
        "dry_run": dry_run,
        "total_source_rows": len(source_row_numbers),
        "total_to_import": len(prepared),
        "total_duplicate_or_existing": duplicates,
        "total_t_ignored": ignored_late,
        "total_conflicts": len(conflicts),
        "detail": {
            "to_import": [
                {
                    "source_row": item["source_row"],
                    "employee_code": item["employee_code"],
                    "tanggal": item["tanggal"],
                    "kategori": item["kategori"],
                    "jumlah_hari": item["jumlah_hari"],
                }
                for item in prepared
            ],
            "conflicts": conflicts,
        },
    }


@router.get("/whatsapp-identities")
def list_whatsapp_identities(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """Daftar linking nomor WhatsApp untuk ditinjau HR."""
    rows = db.query(models.WhatsAppIdentity).order_by(models.WhatsAppIdentity.updated_at.desc()).all()
    return [{
        "id": row.id,
        "phone_number": row.phone_number,
        "employee_id": row.employee_id,
        "employee_name": row.employee.nama if row.employee else None,
        "employee_nik_last4": row.employee.nik[-4:] if row.employee and row.employee.nik else None,
        "status": row.status,
        "verified_at": row.verified_at,
        "last_seen_at": row.last_seen_at,
        "failed_attempts": row.failed_attempts,
    } for row in rows]


@router.patch("/whatsapp-identities/{identity_id}/revoke")
def revoke_whatsapp_identity(
    identity_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_hr_master),
):
    """Cabut linking WhatsApp; nomor dapat login ulang setelah proses verifikasi."""
    identity = db.query(models.WhatsAppIdentity).filter(models.WhatsAppIdentity.id == identity_id).first()
    if not identity:
        raise HTTPException(status_code=404, detail="Linking WhatsApp tidak ditemukan.")
    identity.status = "REVOKED"
    db.add(models.WhatsAppAuditLog(
        phone_number=identity.phone_number,
        employee_id=identity.employee_id,
        event_type="HR_REVOKE",
        detail=f"Linking dicabut oleh {current_user.nama or 'HR Master'}",
    ))
    db.commit()
    return {"status": "sukses", "identity_id": identity.id, "new_status": identity.status}


@router.get("/whatsapp-audit")
def list_whatsapp_audit(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """Histori login, logout, kegagalan, dan perubahan linking WhatsApp."""
    rows = (
        db.query(models.WhatsAppAuditLog)
        .order_by(models.WhatsAppAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{
        "id": row.id,
        "phone_number": row.phone_number,
        "employee_id": row.employee_id,
        "employee_name": row.employee.nama if row.employee else None,
        "event_type": row.event_type,
        "detail": row.detail,
        "created_at": row.created_at,
    } for row in rows]


@router.patch("/whatsapp-identities/{identity_id}/move")
def move_whatsapp_identity(
    identity_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_hr_master),
):
    """Pindahkan linking ke karyawan lain setelah verifikasi manual oleh HR."""
    target_employee_code = str(payload.get("employee_code") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if not target_employee_code or not reason:
        raise HTTPException(status_code=400, detail="employee_code dan alasan pemindahan wajib diisi.")

    identity = db.query(models.WhatsAppIdentity).filter(models.WhatsAppIdentity.id == identity_id).first()
    target = db.query(models.Employee).filter(
        models.Employee.employee_code == target_employee_code,
    ).first()
    if not identity:
        raise HTTPException(status_code=404, detail="Linking WhatsApp tidak ditemukan.")
    if not target:
        raise HTTPException(status_code=404, detail="Kode Karyawan tujuan tidak ditemukan.")

    conflict = db.query(models.WhatsAppIdentity).filter(
        models.WhatsAppIdentity.employee_id == target.id,
        models.WhatsAppIdentity.status == "ACTIVE",
        models.WhatsAppIdentity.id != identity.id,
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="Karyawan tujuan sudah memiliki linking WhatsApp aktif.")

    previous_employee_id = identity.employee_id
    identity.employee_id = target.id
    identity.status = "ACTIVE"
    identity.verified_at = datetime.datetime.utcnow()
    identity.failed_attempts = 0
    identity.locked_until = None
    db.add(models.WhatsAppAuditLog(
        phone_number=identity.phone_number,
        employee_id=target.id,
        event_type="HR_MOVE",
        detail=(
            f"Linking dipindahkan dari employee_id={previous_employee_id} "
            f"ke employee_id={target.id} oleh {current_user.nama or 'HR Master'}: {reason}"
        ),
    ))
    db.commit()
    return {
        "status": "sukses",
        "identity_id": identity.id,
        "employee_id": target.id,
        "employee_code": target.employee_code,
        "new_status": identity.status,
    }


def _normalize_employment_status(value: Optional[str]) -> str:
    """Normalisasi status kepegawaian agar label baru aman untuk data lama."""
    normalized = (value or "PKWTT").upper().strip()
    aliases = {
        "TETAP": "PKWTT",
        "KARYAWAN_TETAP": "PKWTT",
        "PKWTT": "PKWTT",
        "PKWT": "PKWT",
        "PHL": "PHL",
    }
    return aliases.get(normalized, normalized)


def _enrich_employee_data(emp: models.Employee) -> models.Employee:
    """Helper untuk menghitung tenure & contract_reminder_status pada objek Employee."""
    emp.employment_status = _normalize_employment_status(emp.employment_status)
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
        q = q.filter(models.Employee.employment_status == _normalize_employment_status(employment_status))

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
    """Mengunduh file Excel template untuk import master karyawan (lengkap NIK, Tanggal Masuk & Waktu Berakhir)."""
    import io
    import pandas as pd
    from fastapi.responses import Response

    # Ambil semua kode profil yang aktif untuk referensi
    profiles = db.query(models.Profile).order_by(models.Profile.code).all()

    # Template data contoh — format sesuai contoh-template.xlsx
    # Kolom: Status, Nama, Uang Makan, Gaji Pokok, NIK, Tanggal Masuk, Waktu Berakhir, BPJS Kesehatan, BPJS TK
    data = [
        {"Status": "Gudang C",           "Nama": "Andi Santanu",          "Uang Makan": 95000,  "Gaji Pokok": "", "NIK": "3207152809990002", "Tanggal Masuk": "2021-11-01", "Waktu Berakhir": "",           "BPJS Kesehatan": 53994, "BPJS TK": 161982},
        {"Status": "Gudang C",           "Nama": "Dian Maulana",          "Uang Makan": 30000,  "Gaji Pokok": "", "NIK": "3674021209020002", "Tanggal Masuk": "2024-12-03", "Waktu Berakhir": "2025-12-03", "BPJS Kesehatan": 53994, "BPJS TK": 161982},
        {"Status": "Office A",           "Nama": "Budi Santoso",          "Uang Makan": 100000, "Gaji Pokok": "", "NIK": "3201011508950001", "Tanggal Masuk": "2022-01-15", "Waktu Berakhir": "",           "BPJS Kesehatan": 53994, "BPJS TK": 161982},
        {"Status": "Gudang A",           "Nama": "Siti Aminah",           "Uang Makan": 80000,  "Gaji Pokok": "", "NIK": "3201024503980003", "Tanggal Masuk": "2023-05-10", "Waktu Berakhir": "2025-05-10", "BPJS Kesehatan": 53994, "BPJS TK": 161982},
        {"Status": "Office C",           "Nama": "Dewi Rahayu",           "Uang Makan": 75000,  "Gaji Pokok": "", "NIK": "3201036012970004", "Tanggal Masuk": "2024-02-01", "Waktu Berakhir": "",           "BPJS Kesehatan": 72000, "BPJS TK": 216000},
        {"Status": "Toko GLC",           "Nama": "Bagus Setiawan",        "Uang Makan": 40000,  "Gaji Pokok": "", "NIK": "3201041109960005", "Tanggal Masuk": "2024-06-15", "Waktu Berakhir": "2025-06-15", "BPJS Kesehatan": 53994, "BPJS TK": 161982},
        {"Status": "Content Marketing",  "Nama": "Fahrul Azi",            "Uang Makan": 100000, "Gaji Pokok": "", "NIK": "3201052004990006", "Tanggal Masuk": "2024-01-10", "Waktu Berakhir": "",           "BPJS Kesehatan": 76000, "BPJS TK": 228000},
        {"Status": "Driver Java Cipulir","Nama": "Harry",                 "Uang Makan": "",     "Gaji Pokok": "", "NIK": "3201060507940007", "Tanggal Masuk": "2023-09-01", "Waktu Berakhir": "",           "BPJS Kesehatan": 57299, "BPJS TK": 171896},
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
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """
    Upload file Excel untuk update massal master karyawan:
    cabang, NIK, Join Date, status kepegawaian, dan Waktu Berakhir Kontrak.

    Aturan:
    - Match karyawan berdasarkan nama (case-insensitive, strip whitespace).
    - Hanya kolom yang diisi yang diupdate (kolom kosong tidak menghapus data lama).
    - Status harus PKWTT, PKWT, atau PHL.
    - Nilai cabang workbook dinormalisasi ke nomenklatur database.
    - Waktu Berakhir hanya diproses jika karyawan berstatus PKWT.
    - dry_run=true hanya mengembalikan preview tanpa commit.
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

    # Template lama memiliki header di baris ke-3, sedangkan workbook master
    # baru memiliki header di baris pertama. Cari baris header secara adaptif.
    header_row_idx = None
    header_row = []
    for candidate_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=min(ws.max_row, 10)), start=1):
        candidate = [str(c.value or "").strip().lower() for c in row]
        if any("nama" in h for h in candidate) and (
            any("nik" in h for h in candidate)
            or any("status kepegawaian" in h for h in candidate)
            or any("tanggal join" in h for h in candidate)
        ):
            header_row_idx = candidate_idx
            header_row = candidate
            break

    if header_row_idx is None:
        raise HTTPException(
            status_code=400,
            detail="Format file tidak dikenali. Pastikan file memiliki kolom Nama, NIK, Status Kepegawaian, atau Tanggal Join.",
        )
    
    def col_idx(keyword: str) -> int:
        """Cari indeks kolom berdasarkan keyword (0-based)."""
        for i, h in enumerate(header_row):
            if keyword in h:
                return i
        return -1

    idx_nama   = col_idx("nama")
    idx_nik    = col_idx("nik")
    idx_join   = col_idx("join")
    if idx_join < 0:
        idx_join = col_idx("tanggal join")
    idx_end    = col_idx("berakhir")
    idx_status = col_idx("status kepegawaian")
    idx_cabang = col_idx("lokasi kerja")
    if idx_cabang < 0:
        idx_cabang = col_idx("cabang")

    if idx_nama < 0 or idx_nik < 0:
        raise HTTPException(
            status_code=400,
            detail="Format file tidak dikenali. Pastikan file memiliki kolom Nama dan NIK."
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
        "invalid_status": [],
        "unmapped_branch": [],
    }

    branch_mapping = {
        "gudang a": "BLOK A",
        "gudang c": "BLOK C",
        "kebayoran lama": "KEBAYORAN LAMA",
        "reef plus": "REEF+/PIK",
        "cab. bandung": "BANDUNG",
        "cab bandung": "BANDUNG",
        "bandung": "BANDUNG",
        "glc": "GREENLAKE CITY",
        "tj. duren": "TANJUNG DUREN",
        "tj duren": "TANJUNG DUREN",
        "tanjung duren": "TANJUNG DUREN",
    }

    for row in ws.iter_rows(min_row=header_row_idx + 1):
        vals = [cell.value for cell in row]
        required_indexes = [idx_nama, idx_nik, idx_join, idx_status, idx_cabang, idx_end]
        if len(vals) <= max(required_indexes):
            continue

        nama_raw = vals[idx_nama]
        if not nama_raw:
            continue

        nama_key = str(nama_raw).strip()
        nik_raw = vals[idx_nik] if idx_nik >= 0 else None
        join_raw = vals[idx_join] if idx_join >= 0 else None
        end_raw = vals[idx_end] if idx_end >= 0 else None
        status_raw = vals[idx_status] if idx_status >= 0 else None
        branch_raw = vals[idx_cabang] if idx_cabang >= 0 else None

        # Skip jika semua kolom yang perlu diisi kosong
        if not any(value not in (None, "") for value in (nik_raw, join_raw, end_raw, status_raw, branch_raw)):
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
        pending_updates = {}

        # -- Update Cabang --
        if branch_raw not in (None, ""):
            branch_key = str(branch_raw).strip().lower()
            branch_value = branch_mapping.get(branch_key)
            if branch_value:
                pending_updates["cabang"] = branch_value
                updated_fields.append(f"Cabang → {branch_value}")
            else:
                results["unmapped_branch"].append({
                    "nama": nama_key,
                    "lokasi": str(branch_raw).strip(),
                })

        # -- Update Status Kepegawaian --
        if status_raw not in (None, ""):
            status_value = str(status_raw).strip().upper()
            if status_value == "TETAP":
                status_value = "PKWTT"
            if status_value not in ("PKWTT", "PKWT", "PHL"):
                results["invalid_status"].append({
                    "nama": nama_key,
                    "status": str(status_raw).strip(),
                })
            else:
                pending_updates["employment_status"] = status_value
                updated_fields.append(f"Status → {status_value}")

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
                    pending_updates["nik"] = clean
                    updated_fields.append("NIK")

        # -- Update Join Date --
        join_date_parsed = parse_date(join_raw)
        if join_date_parsed:
            pending_updates["join_date"] = join_date_parsed
            updated_fields.append("Join Date")

        # -- Update Waktu Berakhir Kontrak (hanya PKWT) --
        effective_status = pending_updates.get("employment_status", _normalize_employment_status(emp.employment_status))
        if end_raw and effective_status == "PKWT":
            end_date_parsed = parse_date(end_raw)
            if end_date_parsed:
                active_c = next(
                    (c for c in emp.contracts if c.status == "ACTIVE"), None
                )
                if active_c:
                    active_c.end_date = end_date_parsed
                    updated_fields.append("Waktu Berakhir Kontrak")

        if updated_fields:
            if not dry_run:
                for field, value in pending_updates.items():
                    setattr(emp, field, value)
            results["updated"].append({
                "nama": emp.nama,
                "fields": ", ".join(updated_fields),
            })

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "message": "Import selesai.",
        "dry_run": dry_run,
        "total_updated": len(results["updated"]),
        "total_skipped": len(results["skipped"]),
        "total_not_found": len(results["not_found"]),
        "total_nik_conflict": len(results["nik_conflict"]),
        "total_invalid_nik": len(results["invalid_nik"]),
        "total_invalid_status": len(results["invalid_status"]),
        "total_unmapped_branch": len(results["unmapped_branch"]),
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

    emp_status = _normalize_employment_status(payload.employment_status)
    if emp_status not in ("PKWTT", "PKWT", "PHL"):
        raise HTTPException(status_code=400, detail="Status kepegawaian harus 'PKWTT', 'PKWT', atau 'PHL'.")

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

    emp.employment_status = _normalize_employment_status(emp.employment_status)
    new_status = _normalize_employment_status(payload.employment_status)
    if new_status not in ("PKWTT", "PKWT", "PHL"):
        raise HTTPException(status_code=400, detail="Status kepegawaian harus 'PKWTT', 'PKWT', atau 'PHL'.")

    # Jika diubah dari PKWT ke PKWTT (Pengangkatan Karyawan Tetap)
    if emp.employment_status == "PKWT" and new_status == "PKWTT":
        for c in emp.contracts:
            if c.status == "ACTIVE":
                c.status = "PROMOTED_TO_PERMANENT"
                c.keterangan = (c.keterangan or "") + " [Diangkat menjadi PKWTT]"

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

    emp_dict = payload.dict(
        exclude={"contract_start_date", "contract_end_date", "contract_keterangan"},
        exclude_unset=True,
    )
    if "employment_status" in emp_dict:
        emp_dict["employment_status"] = _normalize_employment_status(emp_dict["employment_status"])
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
    # Format utama yang didukung: Status | Nama | Uang Makan | Gaji Pokok | NIK | Tanggal Masuk | Waktu Berakhir
    # (sesuai file contoh-template.xlsx)
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
        elif cl in ("nik", "no_nik", "nik_ktp", "no_ktp"):
            col_map["nik"] = col
        elif any(k in cl for k in ("tanggal_masuk", "join_date", "tgl_masuk", "tgl_bergabung", "join", "masuk")):
            col_map["join_date"] = col
        elif any(k in cl for k in ("waktu_berakhir", "akhir_kontrak", "selesai_kontrak", "berakhir", "expiring")):
            col_map["contract_end"] = col
        elif any(k in cl for k in ("bpjs_kesehatan", "bpjs_kes", "potongan_bpjs_kesehatan", "kesehatan")):
            col_map["bpjs_kesehatan"] = col
        elif any(k in cl for k in ("bpjs_tk", "bpjs_ketenagakerjaan", "potongan_bpjs_tk", "jamsostek", "bpjstk")):
            col_map["bpjs_tk"] = col
        elif cl in ("active", "aktif", "status_aktif", "is_active"):
            col_map["active"] = col

    if "nama" not in col_map:
        raise HTTPException(
            status_code=400,
            detail=f"File harus memiliki kolom 'Nama'. Kolom ditemukan: {list(df.columns)}",
        )

    import datetime
    from datetime import date as date_type

    def parse_date_val(val):
        if pd.isna(val) or not val:
            return None
        if isinstance(val, (date_type, datetime.datetime)):
            return val.date() if isinstance(val, datetime.datetime) else val
        s = str(val).strip()
        if not s or s.lower() in ("none", "nat", "nan", "-"):
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def clean_nik_val(val):
        if pd.isna(val) or not val:
            return None
        s = str(val).strip().replace(" ", "")
        if s.endswith(".0"):
            s = s[:-2]
        if len(s) != 16 or not s.isdigit():
            return None
        return s

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
            if nama.lower() == "live stream":
                errors.append({
                    "row": row_num,
                    "nama": nama,
                    "reason": "Nama tidak ditemukan di master karyawan",
                })
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

        # Uang Makan Override
        uang_makan_override = None
        if "uang_makan" in col_map:
            raw_um = row.get(col_map["uang_makan"])
            raw_um_text = "" if pd.isna(raw_um) else str(raw_um).strip()
            try:
                if not raw_um_text:
                    val = 0
                elif raw_um_text.endswith(".0"):
                    val = int(float(raw_um_text))
                else:
                    raw_um_clean = raw_um_text.replace(",", "").replace(".", "").replace(" ", "")
                    val = int(float(raw_um_clean))
                uang_makan_override = val if val >= 0 else 0
            except (ValueError, OverflowError):
                uang_makan_override = 0

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

        # NIK
        nik_val = None
        if "nik" in col_map and pd.notna(row.get(col_map["nik"])):
            nik_val = clean_nik_val(row[col_map["nik"]])

        # Join Date (Tanggal Masuk)
        join_date_val = None
        if "join_date" in col_map and pd.notna(row.get(col_map["join_date"])):
            join_date_val = parse_date_val(row[col_map["join_date"]])

        # Waktu Berakhir Kontrak
        contract_end_val = None
        if "contract_end" in col_map and pd.notna(row.get(col_map["contract_end"])):
            contract_end_val = parse_date_val(row[col_map["contract_end"]])

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
            if uang_makan_override is not None:
                emp.uang_makan_override = uang_makan_override
            if bpjs_kesehatan is not None:
                emp.bpjs_kesehatan = bpjs_kesehatan
            if bpjs_tk is not None:
                emp.bpjs_tk = bpjs_tk
            if nik_val is not None:
                emp.nik = nik_val
            if join_date_val is not None:
                emp.join_date = join_date_val

            if contract_end_val is not None:
                emp.employment_status = "PKWT"
                active_c = next((c for c in emp.contracts if c.status == "ACTIVE"), None)
                if active_c:
                    active_c.end_date = contract_end_val
                else:
                    new_c = models.EmploymentContract(
                        employee_id=emp.id,
                        contract_number=len(emp.contracts) + 1,
                        start_date=join_date_val or emp.join_date or datetime.date.today(),
                        end_date=contract_end_val,
                        status="ACTIVE",
                        keterangan="Import dari Excel",
                    )
                    db.add(new_c)

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
                nik=nik_val,
                join_date=join_date_val,
                employment_status="PKWT" if contract_end_val else "PKWTT",
                active=active,
            )
            db.add(new_emp)
            db.flush()

            if contract_end_val:
                new_c = models.EmploymentContract(
                    employee_id=new_emp.id,
                    contract_number=1,
                    start_date=join_date_val or datetime.date.today(),
                    end_date=contract_end_val,
                    status="ACTIVE",
                    keterangan="Import dari Excel",
                )
                db.add(new_c)

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
