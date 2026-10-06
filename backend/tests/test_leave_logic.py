# -*- coding: utf-8 -*-
"""
test_leave_logic.py
===================
Unit tests untuk leave_logic.py — menggunakan unittest standar.
Test yang butuh DB menggunakan SQLite in-memory.

Jalankan:
  cd backend
  venv\\Scripts\\python -m unittest discover -s tests
"""
import datetime
import unittest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import Base, Employee, LeaveBalanceLedger, LeaveRequest
from app.leave_logic import (
    get_anniversary_date,
    get_first_anniversary,
    has_reached_anniversary,
    calculate_proportional_quota,
    get_ledger_balance,
    write_ledger_entry,
    grant_anniversary_quota,
    grant_annual_reset_quota,
    expire_previous_year_balance,
    record_leave_used,
    reverse_leave_used,
    reconcile_approved_leave_ledger,
    validate_annual_leave_request,
    run_leave_quota_jobs,
    ENTRY_GRANT_ANNIVERSARY,
    ENTRY_GRANT_ANNUAL_RESET,
    ENTRY_USED,
    ENTRY_REVERSED,
    ENTRY_EXPIRED,
)
from app.config import ANNUAL_LEAVE_QUOTA
from app.pipeline.service import _hitung_cuti_sakit_periode


def make_employee(db, nama: str, join_date: datetime.date) -> Employee:
    emp = Employee(
        nama=nama,
        profile_code="OFFICE",
        employment_status="TETAP",
        join_date=join_date,
        active=True,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


class BaseDBTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()


class TestProportionalQuota(unittest.TestCase):
    def test_anniversary_january(self):
        """Anniversary Januari → 12 hari (semua bulan tersisa)"""
        join = datetime.date(2024, 1, 15)
        quota = calculate_proportional_quota(join, anniversary_year=2025)
        self.assertEqual(quota, 12)  # 13 - 1 = 12

    def test_anniversary_july(self):
        """Anniversary Juli → 6 hari (Jul-Des)"""
        join = datetime.date(2024, 7, 10)
        quota = calculate_proportional_quota(join, anniversary_year=2025)
        self.assertEqual(quota, 6)  # 13 - 7 = 6

    def test_anniversary_october(self):
        """Anniversary Oktober → 3 hari (Okt, Nov, Des)"""
        join = datetime.date(2025, 10, 5)
        quota = calculate_proportional_quota(join, anniversary_year=2026)
        self.assertEqual(quota, 3)  # 13 - 10 = 3

    def test_anniversary_december(self):
        """Anniversary Desember → 1 hari (minimum)"""
        join = datetime.date(2024, 12, 1)
        quota = calculate_proportional_quota(join, anniversary_year=2025)
        self.assertEqual(quota, 1)  # 13 - 12 = 1

    def test_anniversary_february(self):
        """Anniversary Februari → 11 hari"""
        join = datetime.date(2024, 2, 14)
        quota = calculate_proportional_quota(join, anniversary_year=2025)
        self.assertEqual(quota, 11)  # 13 - 2 = 11

    def test_cannot_exceed_annual_quota(self):
        """Kuota proporsional tidak boleh melebihi ANNUAL_LEAVE_QUOTA"""
        join = datetime.date(2024, 1, 1)
        quota = calculate_proportional_quota(join, anniversary_year=2025)
        self.assertLessEqual(quota, ANNUAL_LEAVE_QUOTA)


class TestAnniversaryDate(unittest.TestCase):
    def test_normal_date(self):
        join = datetime.date(2024, 5, 15)
        ann = get_anniversary_date(join, 2025)
        self.assertEqual(ann, datetime.date(2025, 5, 15))

    def test_feb_29_leap_to_non_leap(self):
        """Join 29 Feb 2024 → anniversary 2025 (non-kabisat) = 28 Feb"""
        join = datetime.date(2024, 2, 29)
        ann = get_anniversary_date(join, 2025)
        self.assertEqual(ann, datetime.date(2025, 2, 28))

    def test_feb_29_to_leap_year(self):
        """Join 29 Feb 2024 → anniversary 2028 (kabisat) = 29 Feb"""
        join = datetime.date(2024, 2, 29)
        ann = get_anniversary_date(join, 2028)
        self.assertEqual(ann, datetime.date(2028, 2, 29))

    def test_first_anniversary(self):
        join = datetime.date(2025, 10, 5)
        first_ann = get_first_anniversary(join)
        self.assertEqual(first_ann, datetime.date(2026, 10, 5))

    def test_has_reached_anniversary_true(self):
        join = datetime.date(2025, 10, 5)
        ref_date = datetime.date(2026, 10, 5)  # tepat di tanggal anniversary
        self.assertTrue(has_reached_anniversary(join, ref_date))

    def test_has_reached_anniversary_before(self):
        join = datetime.date(2025, 10, 5)
        ref_date = datetime.date(2026, 10, 4)  # sehari sebelum
        self.assertFalse(has_reached_anniversary(join, ref_date))

    def test_has_reached_anniversary_after(self):
        join = datetime.date(2025, 10, 5)
        ref_date = datetime.date(2027, 3, 1)  # jauh setelah
        self.assertTrue(has_reached_anniversary(join, ref_date))


class TestLedgerOperations(BaseDBTestCase):
    def test_initial_balance_is_zero(self):
        emp = make_employee(self.db, "Test User", datetime.date(2024, 1, 1))
        balance = get_ledger_balance(self.db, emp.id, 2025)
        self.assertEqual(balance, 0.0)

    def test_grant_anniversary_writes_ledger(self):
        join = datetime.date(2025, 7, 1)  # anniversary Juli 2026 → 6 hari
        emp = make_employee(self.db, "Budi", join)
        entry = grant_anniversary_quota(self.db, emp, 2026)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.entry_type, ENTRY_GRANT_ANNIVERSARY)
        self.assertEqual(entry.amount, 6.0)
        balance = get_ledger_balance(self.db, emp.id, 2026)
        self.assertEqual(balance, 6.0)

    def test_grant_anniversary_idempotent(self):
        """Menjalankan grant dua kali tidak menambah saldo dua kali"""
        join = datetime.date(2025, 7, 1)
        emp = make_employee(self.db, "Siti", join)
        grant_anniversary_quota(self.db, emp, 2026)
        result2 = grant_anniversary_quota(self.db, emp, 2026)  # Kedua kali harus None (skip)
        self.assertIsNone(result2)
        balance = get_ledger_balance(self.db, emp.id, 2026)
        self.assertEqual(balance, 6.0)  # Tetap 6, bukan 12

    def test_grant_annual_reset(self):
        """Karyawan >1 tahun dapat 12 hari saat reset tahunan"""
        join = datetime.date(2024, 1, 1)  # Anniversary Januari 2025 → sudah >1 tahun di 1 Jan 2026
        emp = make_employee(self.db, "Andi", join)
        entry = grant_annual_reset_quota(self.db, emp, 2026)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.entry_type, ENTRY_GRANT_ANNUAL_RESET)
        self.assertEqual(entry.amount, ANNUAL_LEAVE_QUOTA)
        balance = get_ledger_balance(self.db, emp.id, 2026)
        self.assertEqual(balance, ANNUAL_LEAVE_QUOTA)

    def test_grant_annual_reset_idempotent(self):
        """Reset tahunan idempotent"""
        join = datetime.date(2024, 1, 1)
        emp = make_employee(self.db, "Dewi", join)
        grant_annual_reset_quota(self.db, emp, 2026)
        result2 = grant_annual_reset_quota(self.db, emp, 2026)
        self.assertIsNone(result2)
        self.assertEqual(get_ledger_balance(self.db, emp.id, 2026), ANNUAL_LEAVE_QUOTA)

    def test_no_reset_if_anniversary_not_reached(self):
        """Karyawan yang anniversary-nya di tahun ini tidak dapat reset penuh sebelum anniversary"""
        join = datetime.date(2025, 6, 1)  # Anniversary pertama Juni 2026
        emp = make_employee(self.db, "Fajar", join)
        entry = grant_annual_reset_quota(self.db, emp, 2026)  # Reset 1 Jan 2026 → belum eligible
        self.assertIsNone(entry)


class TestExpireBalance(BaseDBTestCase):
    def test_expire_remaining_balance(self):
        # Sudah melewati anniversary pertama sebelum reset tahun 2025.
        join = datetime.date(2023, 1, 1)
        emp = make_employee(self.db, "Gita", join)
        # Beri 12 hari kuota 2025
        grant_annual_reset_quota(self.db, emp, 2025)
        # Pakai 4 hari
        write_ledger_entry(self.db, emp.id, 2025, ENTRY_USED, -4.0, "Cuti test")
        # Sisa = 8
        self.assertEqual(get_ledger_balance(self.db, emp.id, 2025), 8.0)
        # Hanguskan per 1 Jan 2026
        expired = expire_previous_year_balance(self.db, emp, 2025)
        self.assertIsNotNone(expired)
        self.assertEqual(expired.amount, -8.0)
        # Saldo setelah hangus = 0
        self.assertEqual(get_ledger_balance(self.db, emp.id, 2025), 0.0)

    def test_expire_idempotent(self):
        join = datetime.date(2024, 1, 1)
        emp = make_employee(self.db, "Hani", join)
        grant_annual_reset_quota(self.db, emp, 2025)
        expire_previous_year_balance(self.db, emp, 2025)
        result2 = expire_previous_year_balance(self.db, emp, 2025)  # Kedua kali → None
        self.assertIsNone(result2)


class TestLeaveLedgerReconciliation(BaseDBTestCase):
    def test_backfills_approved_leave_once_with_date_range(self):
        emp = make_employee(self.db, "Agus Triyana", datetime.date(2023, 7, 16))
        leave = LeaveRequest(
            nama=emp.nama,
            kategori="CUTI_TAHUNAN",
            tanggal_mulai=datetime.date(2026, 10, 3),
            tanggal_selesai=datetime.date(2026, 10, 7),
            status="APPROVED",
        )
        self.db.add(leave)
        self.db.commit()

        self.assertEqual(reconcile_approved_leave_ledger(self.db), 1)
        self.assertEqual(get_ledger_balance(self.db, emp.id, 2026), -5.0)
        self.assertEqual(reconcile_approved_leave_ledger(self.db), 0)
        self.assertEqual(
            self.db.query(LeaveBalanceLedger)
            .filter(LeaveBalanceLedger.leave_request_id == leave.id)
            .count(),
            1,
        )

    def test_no_expire_if_no_balance(self):
        """Tidak menulis EXPIRED jika saldo sudah 0"""
        join = datetime.date(2024, 1, 1)
        emp = make_employee(self.db, "Ivan", join)
        # Tidak ada grant → saldo 0
        result = expire_previous_year_balance(self.db, emp, 2025)
        self.assertIsNone(result)


class TestValidateLeaveRequest(BaseDBTestCase):
    def test_reject_before_anniversary(self):
        """Pengajuan sebelum anniversary pertama harus ditolak"""
        join = datetime.date(2025, 10, 5)
        emp = make_employee(self.db, "Joko", join)
        tanggal_mulai = datetime.date(2026, 10, 4)  # Sehari sebelum anniversary
        ok, msg = validate_annual_leave_request(self.db, emp, tanggal_mulai, 1.0)
        self.assertFalse(ok)
        self.assertTrue("2026" in msg and ("10" in msg or "Oktober" in msg or "October" in msg))

    def test_approve_on_anniversary_day(self):
        """Pengajuan tepat di hari anniversary boleh, asalkan ada kuota"""
        join = datetime.date(2025, 10, 5)
        emp = make_employee(self.db, "Kartini", join)
        # Beri kuota terlebih dahulu (simulasi scheduler sudah jalan)
        grant_anniversary_quota(self.db, emp, 2026)
        tanggal_mulai = datetime.date(2026, 10, 5)  # Tepat di anniversary
        ok, msg = validate_annual_leave_request(self.db, emp, tanggal_mulai, 1.0)
        self.assertTrue(ok, f"Harusnya OK tapi: {msg}")

    def test_reject_if_no_quota(self):
        """Tolak jika saldo 0 (belum dapat grant)"""
        join = datetime.date(2024, 1, 1)
        emp = make_employee(self.db, "Lukman", join)
        # Tidak ada grant → saldo 0
        tanggal_mulai = datetime.date(2025, 3, 1)
        ok, msg = validate_annual_leave_request(self.db, emp, tanggal_mulai, 1.0)
        self.assertFalse(ok)

    def test_reject_if_exceeds_balance(self):
        """Tolak jika hari diminta melebihi sisa saldo"""
        join = datetime.date(2025, 7, 1)  # Anniversary Juli 2026 → 6 hari
        emp = make_employee(self.db, "Maya", join)
        grant_anniversary_quota(self.db, emp, 2026)  # 6 hari
        tanggal_mulai = datetime.date(2026, 10, 5)
        ok, msg = validate_annual_leave_request(self.db, emp, tanggal_mulai, 7.0)  # Minta 7
        self.assertFalse(ok)
        self.assertTrue("7.0" in msg or "6.0" in msg)

    def test_reject_no_join_date(self):
        """Tolak jika join_date belum diisi dan tidak ada kontrak"""
        emp = Employee(nama="Nino", profile_code="OFFICE", employment_status="TETAP", active=True)
        self.db.add(emp)
        self.db.commit()
        self.db.refresh(emp)
        ok, msg = validate_annual_leave_request(self.db, emp, datetime.date(2026, 1, 1), 1.0)
        self.assertFalse(ok)
        self.assertIn("join_date", msg.lower())


class TestUnpaidLeaveSummary(unittest.TestCase):
    def test_partial_unpaid_leave_is_split_into_paid_and_unpaid(self):
        leaves = {
            "andi": [{
                "kategori": "CUTI_TAHUNAN",
                "tanggal_mulai": datetime.date(2026, 1, 5),
                "tanggal_selesai": datetime.date(2026, 1, 8),
                "unpaid_leave_days": 2.0,
            }]
        }
        cuti, sakit, unpaid = _hitung_cuti_sakit_periode(
            leaves,
            "Andi",
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 31),
        )
        self.assertEqual((cuti, sakit, unpaid), (2.0, 0.0, 2.0))

    def test_unpaid_leave_only_appears_in_unpaid_summary(self):
        leaves = {
            "andi": [{
                "kategori": "UNPAID_LEAVE",
                "tanggal_mulai": datetime.date(2026, 2, 10),
                "tanggal_selesai": datetime.date(2026, 2, 12),
                "unpaid_leave_days": 3.0,
            }]
        }
        cuti, sakit, unpaid = _hitung_cuti_sakit_periode(
            leaves,
            "Andi",
            datetime.date(2026, 2, 1),
            datetime.date(2026, 2, 28),
        )
        self.assertEqual((cuti, sakit, unpaid), (0.0, 0.0, 3.0))


class TestSchedulerIdempotency(BaseDBTestCase):
    def test_anniversary_grant_idempotent_across_runs(self):
        """Menjalankan run_leave_quota_jobs dua kali pada hari yang sama tidak menambah kuota ganda"""
        join = datetime.date(2025, 10, 1)  # Anniversary 1 Okt 2026
        emp = make_employee(self.db, "Onar", join)
        target = datetime.date(2026, 10, 1)

        result1 = run_leave_quota_jobs(self.db, target_date=target)
        result2 = run_leave_quota_jobs(self.db, target_date=target)

        balance = get_ledger_balance(self.db, emp.id, 2026)
        # Hanya 1 × 3 hari (Oktober = 13-10=3)
        self.assertEqual(balance, 3.0)
        self.assertEqual(len(result1["anniversary_grants"]), 1)
        self.assertEqual(len(result2["anniversary_grants"]), 0)

    def test_annual_reset_idempotent_across_runs(self):
        """Reset 1 Januari idempotent"""
        join = datetime.date(2024, 6, 1)  # Anniversary Juni 2025 → sudah >1 tahun di 1 Jan 2026
        emp = make_employee(self.db, "Putri", join)
        target = datetime.date(2026, 1, 1)

        run_leave_quota_jobs(self.db, target_date=target)
        run_leave_quota_jobs(self.db, target_date=target)

        balance = get_ledger_balance(self.db, emp.id, 2026)
        self.assertEqual(balance, ANNUAL_LEAVE_QUOTA)  # Tepat 12, bukan 24


class TestReverseUsed(BaseDBTestCase):
    def test_reverse_used_restores_balance(self):
        join = datetime.date(2024, 6, 1)
        emp = make_employee(self.db, "Raka", join)
        # Beri kuota via anniversary (Juni 2025 → 7 hari)
        grant_anniversary_quota(self.db, emp, 2025)  # Juni = 13-6=7 hari
        self.assertEqual(get_ledger_balance(self.db, emp.id, 2025), 7.0)
        record_leave_used(self.db, emp.id, 2025, 3.0, leave_request_id=999, leave_desc="test")
        self.assertEqual(get_ledger_balance(self.db, emp.id, 2025), 4.0)

        reverse_leave_used(self.db, emp.id, 2025, leave_request_id=999, leave_desc="test reject")
        self.assertEqual(get_ledger_balance(self.db, emp.id, 2025), 7.0)

    def test_reverse_idempotent(self):
        """Reverse dua kali tidak mengembalikan dua kali"""
        join = datetime.date(2024, 6, 1)
        emp = make_employee(self.db, "Sari", join)
        grant_anniversary_quota(self.db, emp, 2025)  # 7 hari
        record_leave_used(self.db, emp.id, 2025, 3.0, leave_request_id=888)

        reverse_leave_used(self.db, emp.id, 2025, leave_request_id=888)
        result2 = reverse_leave_used(self.db, emp.id, 2025, leave_request_id=888)
        self.assertIsNone(result2)  # Skip pada run kedua
        self.assertEqual(get_ledger_balance(self.db, emp.id, 2025), 7.0)


if __name__ == "__main__":
    unittest.main()
