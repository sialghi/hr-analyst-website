# -*- coding: utf-8 -*-
import datetime
import io
import asyncio
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import (
    User, Employee, EmploymentContract, Profile, RoleEnum,
    LeaveRequest, LeaveBalanceLedger, EmployeeImportCandidate,
)
from app.config import CONTRACT_REMINDER_DAYS, calculate_tenure, get_today_jakarta
from app.auth import get_current_user, require_hr_master
from app.pipeline.loader import build_master_df_from_db
from app.routers import whatsapp

from sqlalchemy.pool import StaticPool
from openpyxl import Workbook

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


def override_auth():
    return User(id=1, nama="HR Master Tester", email="hr@test.com", role=RoleEnum.hr_master)


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_auth
app.dependency_overrides[require_hr_master] = override_auth

client = TestClient(app)


class TestContractManagement(unittest.TestCase):

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        db = TestingSessionLocal()
        p = Profile(code="OFFICE", nama="Office Staf", hari_kerja=["Senin", "Selasa", "Rabu", "Kamis", "Jumat"])
        db.add(p)
        db.commit()
        db.close()

    def test_1_calculate_tenure_logic(self):
        today = datetime.date(2026, 10, 1)

        # Joined 2 years 5 months ago (2024-05-01)
        t1 = calculate_tenure(datetime.date(2024, 5, 1), target_date=today)
        self.assertEqual(t1["years"], 2)
        self.assertEqual(t1["months"], 5)
        self.assertEqual(t1["display"], "2 tahun 5 bulan")

        # Joined 6 months ago (2026-04-01)
        t2 = calculate_tenure(datetime.date(2026, 4, 1), target_date=today)
        self.assertEqual(t2["years"], 0)
        self.assertEqual(t2["months"], 6)
        self.assertEqual(t2["display"], "6 bulan")

        # Empty join_date
        t3 = calculate_tenure(None)
        self.assertEqual(t3["display"], "-")

    def test_2_contract_date_validation_error(self):
        payload = {
            "nama": "Budi Kontrak Invalid",
            "profile_code": "OFFICE",
            "employment_status": "PKWT",
            "join_date": "2026-01-01",
            "contract_start_date": "2026-10-01",
            "contract_end_date": "2026-09-01",  # Invalid: end_date sebelum start_date
        }
        response = client.post("/employees", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("setelah tanggal mulai", response.json()["detail"])

    def test_3_expiring_contracts_h10_reminder(self):
        today = get_today_jakarta()

        # Karyawan 1: Kontrak berakhir 5 hari lagi (H-5) -> EXPIRING_SOON
        t1_start = today - datetime.timedelta(days=100)
        t1_end = today + datetime.timedelta(days=5)

        res1 = client.post("/employees", json={
            "nama": "Siti PKWT H-5",
            "profile_code": "OFFICE",
            "employment_status": "PKWT",
            "join_date": "2025-01-01",
            "contract_start_date": t1_start.isoformat(),
            "contract_end_date": t1_end.isoformat(),
        })
        self.assertEqual(res1.status_code, 200)

        # Karyawan 2: Kontrak berakhir 30 hari lagi -> ACTIVE (Aman)
        t2_start = today
        t2_end = today + datetime.timedelta(days=30)
        client.post("/employees", json={
            "nama": "Andi PKWT Aman",
            "profile_code": "OFFICE",
            "employment_status": "PKWT",
            "join_date": "2026-01-01",
            "contract_start_date": t2_start.isoformat(),
            "contract_end_date": t2_end.isoformat(),
        })

        # Query endpoint expiring contracts H-10
        exp_res = client.get("/employees/contracts/expiring")
        self.assertEqual(exp_res.status_code, 200)
        data = exp_res.json()

        self.assertEqual(data["reminder_days_config"], 10)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["data"][0]["nama"], "Siti PKWT H-5")
        self.assertEqual(data["data"][0]["days_left"], 5)
        self.assertEqual(data["data"][0]["status_label"], "EXPIRING_SOON")

    def test_4_pkwt_promotion_to_permanent(self):
        today = get_today_jakarta()
        t_start = today - datetime.timedelta(days=180)
        t_end = today + datetime.timedelta(days=180)

        # Create PKWT
        res = client.post("/employees", json={
            "nama": "Reno Promosi",
            "profile_code": "OFFICE",
            "employment_status": "PKWT",
            "join_date": "2026-01-01",
            "contract_start_date": t_start.isoformat(),
            "contract_end_date": t_end.isoformat(),
        })
        self.assertEqual(res.status_code, 200)
        emp_id = res.json()["id"]

        # Promote to PKWTT
        update_res = client.put(f"/employees/{emp_id}", json={
            "nama": "Reno Promosi",
            "profile_code": "OFFICE",
            "employment_status": "PKWTT",
            "join_date": "2026-01-01",
        })
        self.assertEqual(update_res.status_code, 200)
        updated_emp = update_res.json()

        self.assertEqual(updated_emp["employment_status"], "PKWTT")
        # Kontrak lama PKWT tersimpan di riwayat dengan status PROMOTED_TO_PERMANENT
        self.assertEqual(len(updated_emp["contracts"]), 1)
        self.assertEqual(updated_emp["contracts"][0]["status"], "PROMOTED_TO_PERMANENT")
        self.assertIn("Diangkat menjadi PKWTT", updated_emp["contracts"][0]["keterangan"])

    def test_5_contract_renewal(self):
        today = get_today_jakarta()
        t1_start = today - datetime.timedelta(days=100)
        t1_end = today + datetime.timedelta(days=10)

        res = client.post("/employees", json={
            "nama": "Dewi Perpanjangan",
            "profile_code": "OFFICE",
            "employment_status": "PKWT",
            "join_date": "2025-10-01",
            "contract_start_date": t1_start.isoformat(),
            "contract_end_date": t1_end.isoformat(),
        })
        emp_id = res.json()["id"]

        # Tambahkan perpanjangan kontrak baru (#2)
        t2_start = t1_end + datetime.timedelta(days=1)
        t2_end = t2_start + datetime.timedelta(days=180)

        renew_res = client.post(f"/employees/{emp_id}/contracts", json={
            "start_date": t2_start.isoformat(),
            "end_date": t2_end.isoformat(),
            "keterangan": "Perpanjangan Kontrak Ke-2 (6 Bulan)",
        })
        self.assertEqual(renew_res.status_code, 200)
        new_c = renew_res.json()
        self.assertEqual(new_c["contract_number"], 2)
        self.assertEqual(new_c["status"], "ACTIVE")

        # Fetch employee detail and verify history
        detail_res = client.get(f"/employees/{emp_id}")
        emp_data = detail_res.json()
        self.assertEqual(len(emp_data["contracts"]), 2)
        # Contract #2 ACTIVE, Contract #1 RENEWED
        statuses = {c["contract_number"]: c["status"] for c in emp_data["contracts"]}
        self.assertEqual(statuses[1], "RENEWED")
        self.assertEqual(statuses[2], "ACTIVE")

    def test_6_master_workbook_dry_run_and_apply(self):
        employee = Employee(
            nama="Rina Cabang",
            profile_code="OFFICE",
            employment_status="TETAP",
            active=True,
        )
        db = TestingSessionLocal()
        db.add(employee)
        db.commit()
        db.close()

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Hasil Merge"
        sheet.append([
            "No",
            "Nama (Summary)",
            "NIK",
            "Status Kepegawaian",
            "Tanggal Join",
            "Lokasi Kerja Valid",
            "Status Aktif (Master)",
        ])
        sheet.append([
            1,
            "Rina Cabang",
            "3201010101010001",
            "PKWTT",
            datetime.date(2024, 1, 15),
            "Cab. Bandung",
            "Aktif",
        ])
        output = io.BytesIO()
        workbook.save(output)
        output.seek(0)

        dry_run = client.post(
            "/employees/import/nik?dry_run=true",
            files={"file": ("master.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        self.assertEqual(dry_run.status_code, 200)
        self.assertTrue(dry_run.json()["dry_run"])
        self.assertEqual(dry_run.json()["total_updated"], 1)

        db = TestingSessionLocal()
        unchanged = db.query(Employee).filter(Employee.nama == "Rina Cabang").one()
        self.assertIsNone(unchanged.cabang)
        self.assertIsNone(unchanged.nik)
        self.assertEqual(unchanged.employment_status, "TETAP")
        db.close()

        output.seek(0)
        applied = client.post(
            "/employees/import/nik",
            files={"file": ("master.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        self.assertEqual(applied.status_code, 200)
        self.assertFalse(applied.json()["dry_run"])

        db = TestingSessionLocal()
        updated = db.query(Employee).filter(Employee.nama == "Rina Cabang").one()
        self.assertEqual(updated.cabang, "BANDUNG")
        self.assertEqual(updated.nik, "3201010101010001")
        self.assertEqual(updated.join_date, datetime.date(2024, 1, 15))
        self.assertEqual(updated.employment_status, "PKWTT")
        db.close()

    def test_7_meal_allowance_blank_is_zero_and_zero_does_not_fallback(self):
        db = TestingSessionLocal()
        db.add_all([
            Employee(nama="Andi Makan", profile_code="OFFICE", uang_makan_override=100000, active=True),
            Employee(nama="Budi Tanpa Makan", profile_code="OFFICE", uang_makan_override=None, active=True),
        ])
        db.commit()
        db.close()

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "HO"
        sheet.append(["Status", "Nama", "Uang Makan ", "Gaji Pokok "])
        sheet.append(["Office A", "Andi Makan", 0, None])
        sheet.append(["Office A", "Budi Tanpa Makan", None, None])
        output = io.BytesIO()
        workbook.save(output)
        output.seek(0)

        response = client.post(
            "/employees/import",
            files={"file": ("data-uangmakan-posisi.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated"], 2)

        db = TestingSessionLocal()
        employees = {
            e.nama: e
            for e in db.query(Employee).filter(Employee.nama.in_(["Andi Makan", "Budi Tanpa Makan"])).all()
        }
        self.assertEqual(employees["Andi Makan"].uang_makan_override, 0)
        self.assertEqual(employees["Budi Tanpa Makan"].uang_makan_override, 0)
        master = build_master_df_from_db(list(employees.values()))
        self.assertEqual(master.loc[master["Nama_Asli"] == "Andi Makan", "Uang_Makan"].iloc[0], 0)
        self.assertEqual(master.loc[master["Nama_Asli"] == "Budi Tanpa Makan", "Uang_Makan"].iloc[0], 0)
        db.close()

    def test_8_whatsapp_login_links_phone_to_nik_after_confirmation(self):
        db = TestingSessionLocal()
        employee = Employee(
            nama="Karyawan WhatsApp",
            nik="3201010101010001",
            profile_code="OFFICE",
            active=True,
        )
        db.add(employee)
        db.commit()
        db.refresh(employee)

        sent = []

        async def fake_send(to_number, message):
            sent.append((to_number, message))
            return {"mocked": True}

        async def fake_send_list(**kwargs):
            sent.append((kwargs["to_number"], kwargs))
            return {"mocked": True}

        original_send = whatsapp.send_whatsapp_text
        original_send_list = whatsapp.send_whatsapp_list
        whatsapp.send_whatsapp_text = fake_send
        whatsapp.send_whatsapp_list = fake_send_list
        whatsapp.user_states.pop("628123456789", None)
        try:
            asyncio.run(whatsapp.process_whatsapp_incoming("08123456789", "login", None, db))
            self.assertEqual(whatsapp.user_states["08123456789"]["step"], "login_waiting_nik")

            asyncio.run(whatsapp.process_whatsapp_incoming("08123456789", "3201010101010001", None, db))
            self.assertEqual(whatsapp.user_states["08123456789"]["step"], "login_confirmation")

            asyncio.run(whatsapp.process_whatsapp_incoming("08123456789", "YaKiN Dan SaDaR", None, db))
            identity = db.query(whatsapp.models.WhatsAppIdentity).one()
            self.assertEqual(identity.phone_number, "628123456789")
            self.assertEqual(identity.employee_id, employee.id)
            self.assertEqual(identity.status, "ACTIVE")
            login_menu = next(message for _, message in sent if isinstance(message, dict))
            self.assertEqual(
                [row["id"] for row in login_menu["sections"][0]["rows"]],
                ["menu_cuti", "menu_izin", "menu_wfl", "menu_status", "menu_profile"],
            )
            self.assertIn("Login berhasil", login_menu["body_text"])
        finally:
            whatsapp.send_whatsapp_text = original_send
            whatsapp.send_whatsapp_list = original_send_list
            whatsapp.user_states.pop("08123456789", None)
            db.close()

    def test_whatsapp_profile_shows_only_linked_employee_fields_without_nik(self):
        db = TestingSessionLocal()
        employee = Employee(
            nama="Profil WhatsApp",
            nik="3201010101010099",
            profile_code="OFFICE",
            cabang="Jakarta",
            employment_status="PKWT",
            active=True,
        )
        db.add(employee)
        db.flush()
        db.add(whatsapp.models.WhatsAppIdentity(
            phone_number="628123456789",
            employee_id=employee.id,
            status="ACTIVE",
        ))
        db.commit()
        sent = []

        async def fake_send(to_number, message):
            sent.append(message)
            return {"mocked": True}

        original_send = whatsapp.send_whatsapp_text
        whatsapp.send_whatsapp_text = fake_send
        whatsapp.user_states.pop("08123456789", None)
        try:
            asyncio.run(whatsapp.process_whatsapp_incoming(
                "08123456789", "", "menu_profile", db
            ))
            self.assertIn("Profil WhatsApp", sent[-1])
            self.assertIn("Jakarta", sent[-1])
            self.assertIn("PKWT", sent[-1])
            self.assertNotIn(employee.nik, sent[-1])
            self.assertNotIn("NIK", sent[-1])

            asyncio.run(whatsapp.process_whatsapp_incoming(
                "08123456789", "profil", None, db
            ))
            self.assertIn("Profil WhatsApp", sent[-1])
            self.assertNotIn(employee.nik, sent[-1])
        finally:
            whatsapp.send_whatsapp_text = original_send
            whatsapp.user_states.pop("08123456789", None)
            db.close()

    def test_whatsapp_cuti_and_izin_menu_routes_to_separate_categories(self):
        db = TestingSessionLocal()
        employee = Employee(
            nama="Menu WhatsApp",
            profile_code="OFFICE",
            active=True,
        )
        db.add(employee)
        db.flush()
        db.add(whatsapp.models.WhatsAppIdentity(
            phone_number="628123456789",
            employee_id=employee.id,
            status="ACTIVE",
        ))
        db.commit()
        sent_lists = []
        original_send_list = whatsapp.send_whatsapp_list
        original_check_quota = whatsapp.check_quota_and_prompt_date

        async def fake_send_list(**kwargs):
            sent_lists.append(kwargs)
            return {"mocked": True}

        async def fake_check_quota(to_number, nama, _db, is_wfl=False):
            whatsapp.user_states[to_number]["step"] = "input_tgl"

        whatsapp.send_whatsapp_list = fake_send_list
        whatsapp.check_quota_and_prompt_date = fake_check_quota
        whatsapp.user_states.pop("08123456789", None)
        try:
            asyncio.run(whatsapp.process_whatsapp_incoming(
                "08123456789", "", "menu_cuti", db
            ))
            self.assertEqual(
                whatsapp.user_states["08123456789"]["data"]["kategori"],
                "CUTI_TAHUNAN",
            )
            self.assertEqual(whatsapp.user_states["08123456789"]["step"], "input_tgl")

            asyncio.run(whatsapp.process_whatsapp_incoming(
                "08123456789", "", "menu_izin", db
            ))
            self.assertEqual(
                whatsapp.user_states["08123456789"]["data"]["allowed_categories"],
                ["SAKIT", "IZIN_TELAT", "IZIN_PULANG_CEPAT", "LAINNYA"],
            )
            self.assertEqual(
                [row["id"] for row in sent_lists[-1]["sections"][0]["rows"]],
                ["kat_SAKIT", "kat_IZIN_TELAT", "kat_IZIN_PULANG_CEPAT", "kat_LAINNYA"],
            )
            asyncio.run(whatsapp.process_whatsapp_incoming(
                "08123456789", "", "kat_IZIN_TELAT", db
            ))
            self.assertEqual(
                whatsapp.user_states["08123456789"]["data"]["kategori"],
                "IZIN_TELAT",
            )
        finally:
            whatsapp.send_whatsapp_list = original_send_list
            whatsapp.check_quota_and_prompt_date = original_check_quota
            whatsapp.user_states.pop("08123456789", None)
            db.close()

    def test_9_whatsapp_locks_all_messages_before_login(self):
        db = TestingSessionLocal()
        sent = []

        async def fake_send(to_number, message):
            sent.append(message)
            return {"mocked": True}

        original_send = whatsapp.send_whatsapp_text
        whatsapp.send_whatsapp_text = fake_send
        try:
            asyncio.run(whatsapp.process_whatsapp_incoming("081111111111", "menu", None, db))
            self.assertIn("belum login", sent[-1])
            self.assertNotIn("step", whatsapp.user_states.get("081111111111", {}))

            sent.clear()
            asyncio.run(whatsapp.process_whatsapp_incoming("081111111111", "cuti", None, db))
            self.assertIn("belum login", sent[-1])

            sent.clear()
            asyncio.run(whatsapp.process_whatsapp_incoming("081111111111", "profil", None, db))
            self.assertIn("belum login", sent[-1])

            sent.clear()
            asyncio.run(whatsapp.process_whatsapp_incoming("081111111111", "login", None, db))
            self.assertEqual(whatsapp.user_states["081111111111"]["step"], "login_waiting_nik")
        finally:
            whatsapp.send_whatsapp_text = original_send
            whatsapp.user_states.pop("081111111111", None)
            db.close()

    def test_10_whatsapp_message_claim_is_idempotent(self):
        db = TestingSessionLocal()
        self.assertTrue(whatsapp.claim_whatsapp_message(db, "wamid.TEST-001"))
        self.assertFalse(whatsapp.claim_whatsapp_message(db, "wamid.TEST-001"))
        self.assertTrue(whatsapp.claim_whatsapp_message(db, "wamid.TEST-002"))
        self.assertEqual(db.query(whatsapp.models.WhatsAppProcessedMessage).count(), 2)
        db.commit()
        db.close()

    def test_11_whatsapp_conversation_state_expires(self):
        db = TestingSessionLocal()
        sent = []

        async def fake_send(to_number, message):
            sent.append(message)
            return {"mocked": True}

        original_send = whatsapp.send_whatsapp_text
        whatsapp.send_whatsapp_text = fake_send
        whatsapp.user_states["628199999999"] = {
            "step": "login_waiting_nik",
            "data": {},
            "expires_at": datetime.datetime.utcnow() - datetime.timedelta(minutes=1),
        }
        try:
            asyncio.run(whatsapp.process_whatsapp_incoming("628199999999", "123", None, db))
            self.assertIn("belum login", sent[-1])
            self.assertNotIn("628199999999", whatsapp.user_states)
        finally:
            whatsapp.send_whatsapp_text = original_send
            whatsapp.user_states.pop("628199999999", None)
            db.close()

    def test_12_hr_can_audit_revoke_and_move_whatsapp_linking(self):
        db = TestingSessionLocal()
        first = Employee(
            nama="Karyawan Link Satu",
            employee_code="JIP-10001",
            nik="3201010101010002",
            profile_code="OFFICE",
            active=True,
        )
        second = Employee(
            nama="Karyawan Link Dua",
            employee_code="JIP-10002",
            nik="3201010101010003",
            profile_code="OFFICE",
            active=False,
        )
        db.add_all([first, second])
        db.commit()
        db.refresh(first)
        db.refresh(second)
        first_id = first.id
        second_id = second.id
        identity = whatsapp.models.WhatsAppIdentity(
            phone_number="628122233344",
            employee_id=first_id,
            status="ACTIVE",
        )
        target_identity = whatsapp.models.WhatsAppIdentity(
            phone_number="628122233355",
            employee_id=second_id,
            status="ACTIVE",
        )
        db.add_all([identity, target_identity])
        db.commit()
        db.refresh(identity)
        identity_id = identity.id
        target_identity_id = target_identity.id
        db.close()

        audit_res = client.get("/employees/whatsapp-audit")
        self.assertEqual(audit_res.status_code, 200)
        self.assertIsInstance(audit_res.json(), list)

        move_res = client.patch(
            f"/employees/whatsapp-identities/{identity_id}/move",
            json={"employee_code": "JIP-10002", "reason": "Nomor dikonfirmasi HR sebagai milik karyawan kedua"},
        )
        self.assertEqual(move_res.status_code, 409)

        db = TestingSessionLocal()
        db.query(whatsapp.models.WhatsAppIdentity).filter(
            whatsapp.models.WhatsAppIdentity.id == target_identity_id
        ).delete()
        db.commit()
        db.close()

        move_res = client.patch(
            f"/employees/whatsapp-identities/{identity_id}/move",
            json={"employee_code": "JIP-10002", "reason": "Nomor dikonfirmasi HR sebagai milik karyawan kedua"},
        )
        self.assertEqual(move_res.status_code, 200)
        self.assertEqual(move_res.json()["employee_id"], second_id)
        self.assertEqual(move_res.json()["employee_code"], "JIP-10002")
        self.assertEqual(client.patch(
            f"/employees/whatsapp-identities/{identity_id}/move",
            json={"employee_code": "JIP-UNKNOWN", "reason": "Kode tidak terdaftar"},
        ).status_code, 404)
        self.assertEqual(client.patch(
            f"/employees/whatsapp-identities/{identity_id}/move",
            json={"reason": "Kode karyawan tidak diberikan"},
        ).status_code, 400)

        revoke_res = client.patch(f"/employees/whatsapp-identities/{identity_id}/revoke")
        self.assertEqual(revoke_res.status_code, 200)
        self.assertEqual(revoke_res.json()["new_status"], "REVOKED")

        db = TestingSessionLocal()
        events = {
            row.event_type
            for row in db.query(whatsapp.models.WhatsAppAuditLog).all()
        }
        self.assertIn("HR_MOVE", events)
        self.assertIn("HR_REVOKE", events)
        db.close()


class TestEmployeeWorkbookImports(unittest.TestCase):

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        db = TestingSessionLocal()
        db.add(Profile(
            code="OFFICE",
            nama="Office",
            hari_kerja=["Senin", "Selasa", "Rabu", "Kamis", "Jumat"],
        ))
        db.commit()
        db.close()

    @staticmethod
    def _upload(workbook, filename):
        output = io.BytesIO()
        workbook.save(output)
        output.seek(0)
        return {"file": (filename, output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    @staticmethod
    def _master_workbook():
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Master ID"
        sheet.append([
            "ID Karyawan", "Kode Cabang", "No Urut", "Nama", "NIK",
            "Tanggal Join", "UM (Uang Makan)", "Jabatan", "Lokasi Kerja",
            "Sheet Asal", "Status (Bulanan/Harian)",
        ])
        sheet.append([
            "JIP-010001", "01", "0001", "Current Employee", "3201010101010001",
            datetime.date(2024, 1, 15), 65000, "Admin", "Gudang A", "Gudang A", "Bulanan",
        ])
        sheet.append([
            "JIP-010002", "01", "0002", "New Employee", "3201010101010002",
            datetime.date(2025, 2, 15), 70000, "Staff", "Gudang A", "Gudang A", "Harian",
        ])
        return workbook

    def test_master_dry_run_commit_and_review_new_employee(self):
        db = TestingSessionLocal()
        employee = Employee(
            nama="Old Employee",
            nik="3201010101010001",
            profile_code="OFFICE",
            employment_status="PKWT",
            active=False,
            cabang="OLD BRANCH",
        )
        db.add(employee)
        db.add(LeaveRequest(
            nama="Old Employee",
            kategori="SAKIT",
            tanggal_mulai=datetime.date(2025, 1, 1),
            tanggal_selesai=datetime.date(2025, 1, 1),
            status="APPROVED",
        ))
        db.commit()
        employee_id = employee.id
        db.close()

        workbook = self._master_workbook()
        dry = client.post(
            "/employees/import/master?dry_run=true",
            files=self._upload(workbook, "master.xlsx"),
        )
        self.assertEqual(dry.status_code, 200)
        self.assertEqual(dry.json()["total_updated"], 1)
        self.assertEqual(dry.json()["total_new_pending_review"], 1)
        self.assertEqual(dry.json()["total_conflicts"], 0)

        db = TestingSessionLocal()
        unchanged = db.query(Employee).filter(Employee.id == employee_id).one()
        self.assertIsNone(unchanged.employee_code)
        self.assertEqual(unchanged.cabang, "OLD BRANCH")
        self.assertEqual(db.query(EmployeeImportCandidate).count(), 0)
        db.close()

        applied = client.post(
            "/employees/import/master?dry_run=false",
            files=self._upload(workbook, "master.xlsx"),
        )
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.json()["total_updated"], 1)
        self.assertEqual(applied.json()["total_new_pending_review"], 1)

        db = TestingSessionLocal()
        updated = db.query(Employee).filter(Employee.id == employee_id).one()
        self.assertEqual(updated.employee_code, "JIP-010001")
        self.assertEqual(updated.nama, "Current Employee")
        self.assertEqual(updated.cabang, "Gudang A")
        self.assertTrue(updated.active)
        self.assertEqual(updated.profile_code, "OFFICE")
        self.assertEqual(updated.employment_status, "PKWT")
        self.assertEqual(db.query(LeaveRequest).one().nama, "Current Employee")
        candidate = db.query(EmployeeImportCandidate).filter(
            EmployeeImportCandidate.employee_code == "JIP-010002"
        ).one()
        candidate_id = candidate.id
        self.assertEqual(candidate.status, "PENDING")
        db.close()

        approved = client.post(
            f"/employees/import/master/pending/{candidate_id}/approve",
            json={"profile_code": "OFFICE", "employment_status": "PKWTT"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertTrue(approved.json()["active"])
        self.assertEqual(approved.json()["employee_code"], "JIP-010002")
        self.assertEqual(approved.json()["payroll_status"], "Harian")

        updated = client.put(
            f"/employees/{employee_id}",
            json={
                "nama": "Current Employee",
                "profile_code": "OFFICE",
                "employment_status": "PKWT",
                "join_date": "2024-01-15",
                "cabang": "Gudang A",
                "active": True,
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["employee_code"], "JIP-010001")
        db = TestingSessionLocal()
        preserved = db.query(Employee).filter(Employee.id == employee_id).one()
        self.assertEqual(preserved.jabatan, "Admin")
        self.assertEqual(preserved.payroll_status, "Bulanan")
        db.close()

    def test_recap_import_quarantines_missing_ids_and_is_idempotent(self):
        db = TestingSessionLocal()
        db.add(Employee(
            employee_code="JIP-020001",
            nama="Recap Employee",
            nik="3201010101010003",
            profile_code="OFFICE",
            active=True,
        ))
        db.commit()
        db.close()

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Rekap Kehadiran"
        sheet.append(["No", "ID", "NIK", "Cabang", "Nama", "Status", "Tanggal", "Keterangan (S/I/CS)"])
        sheet.append([1, "JIP-020001", "3201010101010003", "Kby. Lama", "Recap Employee", "Bulanan", datetime.date(2026, 1, 1), "C"])
        sheet.append([2, "JIP-020001", "3201010101010003", "Kby. Lama", "Recap Employee", "Bulanan", datetime.date(2026, 1, 2), "CS"])
        sheet.append([3, "JIP-020001", "3201010101010003", "Kby. Lama", "Recap Employee", "Bulanan", datetime.date(2026, 1, 3), "S"])
        sheet.append([4, "JIP-020001", "3201010101010003", "Kby. Lama", "Recap Employee", "Bulanan", datetime.date(2026, 1, 4), "T"])
        sheet.append([5, None, "3201010101010003", "Kby. Lama", "Recap Employee", "Bulanan", datetime.date(2026, 1, 5), "C"])

        dry = client.post(
            "/employees/import/recap?dry_run=true",
            files=self._upload(workbook, "recap.xlsx"),
        )
        self.assertEqual(dry.status_code, 200)
        self.assertEqual(dry.json()["total_to_import"], 3)
        self.assertEqual(dry.json()["total_t_ignored"], 1)
        self.assertEqual(dry.json()["total_conflicts"], 1)
        db = TestingSessionLocal()
        self.assertEqual(db.query(LeaveRequest).count(), 0)
        db.close()

        applied = client.post(
            "/employees/import/recap?dry_run=false",
            files=self._upload(workbook, "recap.xlsx"),
        )
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.json()["total_to_import"], 3)

        repeated = client.post(
            "/employees/import/recap?dry_run=false",
            files=self._upload(workbook, "recap.xlsx"),
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["total_to_import"], 0)
        self.assertEqual(repeated.json()["total_duplicate_or_existing"], 3)

        db = TestingSessionLocal()
        self.assertEqual(db.query(LeaveRequest).count(), 3)
        self.assertEqual(db.query(LeaveRequest).filter(LeaveRequest.kategori == "SAKIT").count(), 1)
        self.assertEqual(db.query(LeaveBalanceLedger).filter(LeaveBalanceLedger.entry_type == "USED").count(), 2)
        db.close()

    def test_missing_employee_deactivation_requires_explicit_apply_and_never_deletes(self):
        db = TestingSessionLocal()
        db.add_all([
            Employee(
                employee_code="JIP-010001",
                nama="Current Employee",
                nik="3201010101010001",
                profile_code="OFFICE",
                active=True,
            ),
            Employee(
                employee_code="JIP-OLD0001",
                nama="Former Employee",
                nik="3201010101010009",
                profile_code="OFFICE",
                active=True,
            ),
        ])
        db.commit()
        former_id = db.query(Employee).filter(Employee.employee_code == "JIP-OLD0001").one().id
        db.close()

        preview = client.post(
            "/employees/import/master?dry_run=true&deactivate_missing=true",
            files=self._upload(self._master_workbook(), "master.xlsx"),
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["total_missing_from_master"], 1)
        db = TestingSessionLocal()
        self.assertTrue(db.query(Employee).filter(Employee.id == former_id).one().active)
        db.close()

        applied = client.post(
            "/employees/import/master?dry_run=false&deactivate_missing=true",
            files=self._upload(self._master_workbook(), "master.xlsx"),
        )
        self.assertEqual(applied.status_code, 200)
        db = TestingSessionLocal()
        former = db.query(Employee).filter(Employee.id == former_id).one()
        self.assertFalse(former.active)
        self.assertEqual(former.employee_code, "JIP-OLD0001")
        db.close()


if __name__ == "__main__":
    unittest.main()
