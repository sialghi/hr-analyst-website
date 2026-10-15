"""Canonical employee branches and their JIP employee-code prefixes."""

import re
from typing import Optional

BRANCH_CODES = {
    "Cab. Bandung": "03",
    "GLC": "04",
    "Gudang A": "01",
    "Gudang C": "02",
    "IDD PIK": "07",
    "Kebayoran Lama": "09",
    "Reef Plus": "08",
    "Setup": "06",
    "Tj. Duren": "05",
}

BRANCH_NAMES = tuple(BRANCH_CODES)
BRANCH_PREFIXES = frozenset(BRANCH_CODES.values())
EMPLOYEE_ID_PATTERN = re.compile(r"JIP-(\d{2})(\d{4})", re.IGNORECASE)


def normalized_branch(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return " ".join(value.split())


def branch_code_for(value: Optional[str]) -> Optional[str]:
    branch = normalized_branch(value)
    return BRANCH_CODES.get(branch) if branch else None


def validate_new_employee_id(value: str, branch: str) -> bool:
    prefix = branch_code_for(branch)
    if not prefix:
        return False
    match = EMPLOYEE_ID_PATTERN.fullmatch(value.strip())
    return bool(match and match.group(1) == prefix and 1 <= int(match.group(2)) <= 9999)


def employee_id_serial(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = EMPLOYEE_ID_PATTERN.fullmatch(value.strip())
    if not match or match.group(1) not in BRANCH_PREFIXES:
        return None
    serial = int(match.group(2))
    return serial if serial > 0 else None


def employee_id_serial_in_use(
    db,
    value: str,
    *,
    exclude_employee_id: Optional[int] = None,
    exclude_candidate_id: Optional[int] = None,
) -> bool:
    from .models import Employee, EmployeeImportCandidate

    serial = employee_id_serial(value)
    if serial is None:
        return False

    employee_query = db.query(Employee)
    if exclude_employee_id:
        employee_query = employee_query.filter(Employee.id != exclude_employee_id)
    for employee in employee_query.all():
        if employee_id_serial(employee.new_employee_id) == serial:
            return True

    candidate_query = db.query(EmployeeImportCandidate)
    if exclude_candidate_id:
        candidate_query = candidate_query.filter(EmployeeImportCandidate.id != exclude_candidate_id)
    for candidate in candidate_query.all():
        if (
            exclude_employee_id is not None
            and candidate.approved_employee_id == exclude_employee_id
            and candidate.new_employee_id.strip().casefold() == value.strip().casefold()
        ):
            continue
        if employee_id_serial(candidate.new_employee_id) == serial:
            return True
    return False


def lock_employee_id_sequence(db):
    from .models import EmployeeIdSequence

    sequence = (
        db.query(EmployeeIdSequence)
        .filter(EmployeeIdSequence.id == 1)
        .with_for_update()
        .first()
    )
    if sequence is None:
        sequence = EmployeeIdSequence(id=1, next_serial=1)
        db.add(sequence)
        db.flush()
    return sequence


def advance_employee_id_sequence(db, sequence, serials=()) -> None:
    serials = [serial for serial in serials if serial is not None]
    sequence.next_serial = max([sequence.next_serial, *(serial + 1 for serial in serials)])


def next_employee_id(db, branch: str) -> str:
    from .models import Employee, EmployeeImportCandidate

    prefix = branch_code_for(branch)
    if not prefix:
        raise ValueError(f"Cabang '{branch}' tidak termasuk daftar cabang yang diizinkan.")

    sequence = lock_employee_id_sequence(db)
    existing_ids = [
        value
        for (value,) in db.query(Employee.new_employee_id).all()
    ]
    existing_ids.extend(
        value
        for (value,) in db.query(EmployeeImportCandidate.new_employee_id).all()
    )
    max_used = max((employee_id_serial(value) or 0 for value in existing_ids), default=0)
    serial = max(sequence.next_serial, max_used + 1)
    if serial > 9999:
        raise ValueError(f"Nomor ID karyawan untuk cabang {branch} sudah mencapai batas 9999.")

    sequence.next_serial = serial + 1
    return f"JIP-{prefix}{serial:04d}"
