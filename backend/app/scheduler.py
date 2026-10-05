# -*- coding: utf-8 -*-
import asyncio
import os
import datetime
from typing import Set

from .config import CONTRACT_REMINDER_DAYS, get_today_jakarta, JAKARTA_TZ
from .database import SessionLocal
from .models import Employee
from .routers.employees import _enrich_employee_data
from .routers.whatsapp import send_whatsapp_text

# Cache deduplikasi: simpan key "YYYY-MM-DD:contract_id" agar tidak kirim notifikasi ganda pada hari yang sama
sent_notifications_today: Set[str] = set()


async def check_and_send_contract_reminders():
    """
    Fungsi mengecek kontrak yang akan habis (H-10) atau sudah expired,
    lalu mengirimkan ringkasan notifikasi ke nomor WhatsApp HR Master / Admin.
    Menjamin tidak ada notifikasi ganda untuk kontrak yang sama pada hari yang sama.
    """
    db = SessionLocal()
    try:
        today = get_today_jakarta()
        today_str = today.strftime("%Y-%m-%d")

        hr_phone = os.environ.get("HR_WHATSAPP_NUMBER", "").strip()
        if not hr_phone:
            print("[Scheduler] Info: HR_WHATSAPP_NUMBER belum diisi di .env, notifikasi WA otomatis dilewati.")
            return

        pkwt_emps = (
            db.query(Employee)
            .filter(Employee.employment_status == "PKWT", Employee.active == True)
            .all()
        )

        expiring_items = []
        for emp in pkwt_emps:
            _enrich_employee_data(emp)
            rem = emp.contract_reminder_status
            if rem and (rem["is_expiring"] or rem["is_expired"]):
                contract_id = rem["contract_id"]
                dedup_key = f"{today_str}:{contract_id}"

                if dedup_key not in sent_notifications_today:
                    expiring_items.append((emp, rem, dedup_key))

        if not expiring_items:
            print(f"[Scheduler] Daily check ({today_str}): Tidak ada kontrak baru yang perlu di-notify hari ini.")
            return

        # Format pesan notifikasi WhatsApp
        lines = [
            f"⚠️ *PERINGATAN KONTRAK KARYAWAN (H-{CONTRACT_REMINDER_DAYS})*",
            "━━━━━━━━━━━━━━━━━━",
            f"Halo HR, terdapat *{len(expiring_items)}* karyawan PKWT yang masa kontraknya segera berakhir / telah lewat:\n"
        ]

        for idx, (emp, rem, dedup_key) in enumerate(expiring_items, 1):
            c_num = rem["contract_number"]
            end_str = datetime.datetime.strptime(rem["end_date"], "%Y-%m-%d").strftime("%d-%m-%Y")
            days_left = rem["days_left"]

            if days_left < 0:
                time_badge = f"⛔ *BERAKHIR {abs(days_left)} HARI LALU* ({end_str})"
            elif days_left == 0:
                time_badge = f"⏰ *BERAKHIR HARI INI* ({end_str})"
            else:
                time_badge = f"⏳ *Sisa {days_left} Hari* (Berakhir {end_str})"

            lines.append(
                f"{idx}. *{emp.nama}* ({emp.cabang or 'Pusat'})\n"
                f"   • Kontrak: `#{c_num}`\n"
                f"   • Status: {time_badge}\n"
                f"   • Masa Kerja: _{emp.tenure_display}_"
            )

        lines.append("\n━━━━━━━━━━━━━━━━━━")
        lines.append("Buka Website HR pada menu *Karyawan* atau *Dashboard* untuk perpanjangan kontrak / pengangkatan Karyawan Tetap.")

        message_text = "\n".join(lines)
        print(f"[Scheduler] Mengirim notifikasi reminder {len(expiring_items)} kontrak ke WhatsApp HR: {hr_phone}")
        res = await send_whatsapp_text(hr_phone, message_text)

        # Jika sukses terkirim, catat dedup_key
        if res:
            for _, _, dedup_key in expiring_items:
                sent_notifications_today.add(dedup_key)

    except Exception as e:
        print(f"[Scheduler] Error check_and_send_contract_reminders: {e}")
    finally:
        db.close()


def run_leave_quota_jobs_sync():
    """
    Wrapper sinkron untuk menjalankan leave quota jobs dari async scheduler.
    Membuka sesi DB sendiri dan menutupnya setelah selesai.
    """
    from .leave_logic import run_leave_quota_jobs
    db = SessionLocal()
    try:
        today = get_today_jakarta()
        result = run_leave_quota_jobs(db, target_date=today)
        summary = result.get("summary", {})
        print(
            f"[Scheduler/LeaveQuota] {today}: "
            f"anniversary={summary.get('anniversary_grants_count', 0)}, "
            f"reset_grants={summary.get('reset_grants_count', 0)}, "
            f"expired={summary.get('expired_count', 0)}, "
            f"errors={summary.get('error_count', 0)}"
        )
        if result.get("errors"):
            for err in result["errors"]:
                print(f"[Scheduler/LeaveQuota] ERROR: {err}")
    except Exception as e:
        print(f"[Scheduler/LeaveQuota] Unexpected error: {e}")
    finally:
        db.close()


async def start_daily_contract_scheduler():
    """
    Background Loop: Berjalan terus dan mengecek sekali sehari (pada startup dan setiap 24 jam).
    Menggabungkan dua job:
    1. Kontrak reminder (WhatsApp notifikasi)
    2. Leave quota (anniversary grant + annual reset)
    """
    print("[Scheduler] Daily Job initialized (Asia/Jakarta) — kontrak reminder + leave quota.")
    while True:
        try:
            # Job 1: Kontrak reminder via WhatsApp
            await check_and_send_contract_reminders()
            # Job 2: Leave quota jobs (anniversary grant + 1 Jan reset)
            run_leave_quota_jobs_sync()
            # Sleep 24 jam (86400 detik)
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            print("[Scheduler] Daily Contract Scheduler stopped.")
            break
        except Exception as e:
            print(f"[Scheduler] Loop exception: {e}")
            await asyncio.sleep(3600)
