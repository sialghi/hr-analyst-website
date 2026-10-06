# -*- coding: utf-8 -*-
import datetime
import io
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import User, Employee, EmploymentContract, Profile, RoleEnum
from app.config import CONTRACT_REMINDER_DAYS, calculate_tenure, get_today_jakarta
from app.auth import get_current_user, require_hr_master
from app.pipeline.loader import build_master_df_from_db

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


if __name__ == "__main__":
    unittest.main()
