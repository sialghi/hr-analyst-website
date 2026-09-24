# -*- coding: utf-8 -*-
import os
import re
import datetime
from typing import Optional, Dict, Any
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db, SessionLocal

router = APIRouter(prefix="/telegram", tags=["telegram"])

# Konfigurasi dari Environment
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_HR_CHAT_ID = os.environ.get("TELEGRAM_HR_CHAT_ID", "").strip()
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()

# State percakapan in-memory untuk formulir karyawan
# format: user_states[chat_id] = {"step": str, "data": dict}
user_states: Dict[int, Dict[str, Any]] = {}

KATEGORI_MAP = {
    "1": ("CUTI_TAHUNAN", "🏖️ Cuti Tahunan (Full Day)"),
    "2": ("SAKIT", "🏥 Sakit / SKD (Full Day)"),
    "3": ("IZIN_TELAT", "⏰ Izin Datang Terlambat"),
    "4": ("IZIN_PULANG_CEPAT", "🏃 Izin Pulang Lebih Awal"),
    "5": ("LAINNYA", "📝 Izin Lainnya"),
}

KATEGORI_NAME_MAP = {
    "CUTI_TAHUNAN": "🏖️ Cuti Tahunan",
    "SAKIT": "🏥 Sakit (SKD)",
    "IZIN_TELAT": "⏰ Izin Datang Terlambat",
    "IZIN_PULANG_CEPAT": "🏃 Izin Pulang Lebih Awal",
    "LAINNYA": "📝 Izin Lainnya",
}


# ===========================================================================
# 1. HELPER TELEGRAM API (httpx)
# ===========================================================================

def get_telegram_api_url(method: str) -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN).strip()
    return f"https://api.telegram.org/bot{token}/{method}"


async def send_telegram_message(
    chat_id: int | str,
    text: str,
    parse_mode: str = "Markdown",
    reply_markup: Optional[dict] = None,
) -> Optional[dict]:
    """Mengirim pesan teks ke chat Telegram via Bot API."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN).strip()
    if not token:
        print("[Telegram] Warning: TELEGRAM_BOT_TOKEN belum disetel.")
        return None

    url = get_telegram_api_url("sendMessage")
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.json()
    except Exception as e:
        print(f"[Telegram] Error send_telegram_message: {e}")
        return None


async def edit_telegram_message(
    chat_id: int | str,
    message_id: int,
    text: str,
    parse_mode: str = "Markdown",
    reply_markup: Optional[dict] = None,
) -> Optional[dict]:
    """Mengedit pesan yang sudah ada (misal setelah tombol approval diklik)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN).strip()
    if not token:
        return None

    url = get_telegram_api_url("editMessageText")
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.json()
    except Exception as e:
        print(f"[Telegram] Error edit_telegram_message: {e}")
        return None


async def answer_callback_query(callback_query_id: str, text: Optional[str] = None) -> None:
    """Menjawab interaksi tombol inline keyboard agar icon loading Telegram berhenti."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN).strip()
    if not token:
        return

    url = get_telegram_api_url("answerCallbackQuery")
    payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        print(f"[Telegram] Error answer_callback_query: {e}")


# ===========================================================================
# 2. DATE & INPUT PARSER
# ===========================================================================

def parse_date_input(text: str) -> Optional[datetime.date]:
    """Mendukung format YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, 'hari ini', 'besok', 'lusa'."""
    clean = text.strip().lower()
    today = datetime.date.today()

    if clean in ("hari ini", "today", "now"):
        return today
    if clean in ("besok", "tomorrow"):
        return today + datetime.timedelta(days=1)
    if clean in ("lusa",):
        return today + datetime.timedelta(days=2)

    # Format YYYY-MM-DD
    m1 = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", clean)
    if m1:
        try:
            return datetime.date(int(m1.group(1)), int(m1.group(2)), int(m1.group(3)))
        except ValueError:
            return None

    # Format DD-MM-YYYY atau DD/MM/YYYY
    m2 = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", clean)
    if m2:
        try:
            return datetime.date(int(m2.group(3)), int(m2.group(2)), int(m2.group(1)))
        except ValueError:
            return None

    return None


def parse_time_input(text: str) -> Optional[str]:
    """Mendukung format HH:MM (contoh: 09:30, 14.00)."""
    clean = text.strip().replace(".", ":")
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", clean)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        return f"{hh:02d}:{mm:02d}"
    return None


# ===========================================================================
# 3. NOTIFIKASI KE HR MASTER (DENGAN TOMBOL APPROVAL)
# ===========================================================================

async def notify_hr_master_new_leave(leave: models.LeaveRequest):
    """Kirim notifikasi pengajuan baru ke HR Master lengkap dengan tombol Setujui / Tolak."""
    hr_chat_id = os.environ.get("TELEGRAM_HR_CHAT_ID", TELEGRAM_HR_CHAT_ID).strip()
    if not hr_chat_id:
        print("[Telegram] Warning: TELEGRAM_HR_CHAT_ID belum disetel. Notifikasi HR tidak terkirim.")
        return

    kat_name = KATEGORI_NAME_MAP.get(leave.kategori, leave.kategori)
    is_same = leave.tanggal_mulai == leave.tanggal_selesai
    periode = (
        leave.tanggal_mulai.strftime("%d %b %Y")
        if is_same
        else f"{leave.tanggal_mulai.strftime('%d %b %Y')} s/d {leave.tanggal_selesai.strftime('%d %b %Y')}"
    )

    jam_info = f"⏰ *Jam Izin:* {leave.jam_izin}\n" if leave.jam_izin else ""

    text = (
        f"🔔 *PENGAJUAN CUTI / IZIN BARU*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 *ID Pengajuan:* `#{leave.id}`\n"
        f"👤 *Nama Karyawan:* *{leave.nama}*\n"
        f"📋 *Kategori:* {kat_name}\n"
        f"📅 *Periode:* {periode}\n"
        f"{jam_info}"
        f"📝 *Alasan:* {leave.alasan or '-'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Silakan berikan keputusan persetujuan:"
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Setujui", "callback_data": f"approve_{leave.id}"},
                {"text": "❌ Tolak", "callback_data": f"reject_{leave.id}"},
            ]
        ]
    }

    await send_telegram_message(hr_chat_id, text, reply_markup=reply_markup)


# ===========================================================================
# 4. BOT CORE UPDATE PROCESSOR (Bisa dipanggil Webhook maupun Polling)
# ===========================================================================

async def process_telegram_update(update: dict, db: Session):
    """
    Memproses satu payload Update dari Telegram:
    - Menangani Callback Query (tombol persetujuan HR Master)
    - Menangani Pesan Teks Karyawan (percakapan pengajuan cuti/izin)
    """
    # -----------------------------------------------------------------------
    # A. MENANGANI TOMBOL INTERAKTIF (CALLBACK QUERY)
    # -----------------------------------------------------------------------
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb.get("id")
        data = cb.get("data", "")
        from_user = cb.get("from", {})
        sender_id = str(from_user.get("id", ""))
        sender_name = from_user.get("first_name", "") or from_user.get("username", "HR")
        message = cb.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        msg_id = message.get("message_id")

        await answer_callback_query(cb_id)

        # 1. Approval / Reject dari HR Master
        if data.startswith("approve_") or data.startswith("reject_"):
            is_approve = data.startswith("approve_")
            leave_id_str = data.split("_", 1)[1]
            try:
                leave_id = int(leave_id_str)
            except ValueError:
                return

            leave = db.query(models.LeaveRequest).filter(models.LeaveRequest.id == leave_id).first()
            if not leave:
                await send_telegram_message(chat_id, f"⚠️ Pengajuan ID `#{leave_id}` tidak ditemukan di database.")
                return

            # Perbarui status di database
            new_status = "APPROVED" if is_approve else "REJECTED"
            approver_title = f"HR Master ({sender_name})"
            leave.status = new_status
            leave.approved_by = approver_title
            leave.approved_at = datetime.datetime.utcnow()
            db.commit()
            db.refresh(leave)

            # Update pesan di chat HR (hilangkan tombol agar tidak diklik ganda)
            status_badge = "✅ *DISETUJUI*" if is_approve else "❌ *DITOLAK*"
            kat_name = KATEGORI_NAME_MAP.get(leave.kategori, leave.kategori)
            is_same = leave.tanggal_mulai == leave.tanggal_selesai
            periode = (
                leave.tanggal_mulai.strftime("%d %b %Y")
                if is_same
                else f"{leave.tanggal_mulai.strftime('%d %b %Y')} s/d {leave.tanggal_selesai.strftime('%d %b %Y')}"
            )
            jam_info = f"⏰ *Jam Izin:* {leave.jam_izin}\n" if leave.jam_izin else ""

            updated_text = (
                f"📋 *STATUS PENGAJUAN CUTI / IZIN*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🆔 *ID Pengajuan:* `#{leave.id}`\n"
                f"👤 *Nama Karyawan:* *{leave.nama}*\n"
                f"📋 *Kategori:* {kat_name}\n"
                f"📅 *Periode:* {periode}\n"
                f"{jam_info}"
                f"📝 *Alasan:* {leave.alasan or '-'}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"Keputusan: {status_badge}\n"
                f"Oleh: *{approver_title}*\n"
                f"Waktu: {leave.approved_at.strftime('%d-%m-%Y %H:%M:%S')} UTC"
            )

            await edit_telegram_message(chat_id, msg_id, updated_text, reply_markup=None)

            # Kirim notifikasi hasil ke Karyawan (jika ada telegram_user_id)
            if leave.telegram_user_id:
                if is_approve:
                    karyawan_msg = (
                        f"🎉 *KABAR BAIK! Pengajuan Cuti/Izin Disetujui*\n\n"
                        f"Halo *{leave.nama}*, pengajuan *{kat_name}* Anda untuk tanggal *{periode}* "
                        f"telah *DISETUJUI* oleh HR Master.\n\n"
                        f"Status absensi Anda akan otomatis disesuaikan oleh sistem pipeline HR."
                    )
                else:
                    karyawan_msg = (
                        f"⚠️ *PEMBERITAHUAN: Pengajuan Cuti/Izin Ditolak*\n\n"
                        f"Halo *{leave.nama}*, mohon maaf pengajuan *{kat_name}* Anda untuk tanggal *{periode}* "
                        f"*DITOLAK* oleh HR Master.\n\n"
                        f"Silakan hubungi HR jika membutuhkan informasi lebih lanjut."
                    )
                await send_telegram_message(leave.telegram_user_id, karyawan_msg)

        # 2. Pilihan Kategori Cuti oleh Karyawan (via inline keyboard)
        elif data.startswith("kat_"):
            kat_code = data.replace("kat_", "")
            if chat_id in user_states:
                user_states[chat_id]["data"]["kategori"] = kat_code
                user_states[chat_id]["step"] = "pilih_cabang"
                kat_label = KATEGORI_NAME_MAP.get(kat_code, kat_code)

                # Ambil daftar cabang unik dari master karyawan
                cabang_records = (
                    db.query(models.Employee.cabang)
                    .filter(models.Employee.active == True)
                    .distinct()
                    .all()
                )
                cabang_list = sorted([c[0] for c in cabang_records if c[0]])

                keyboard = []
                row = []
                for cb_name in cabang_list:
                    row.append({"text": f"🏢 {cb_name}", "callback_data": f"cab_{cb_name}"})
                    if len(row) == 2:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)
                keyboard.append([{"text": "✏️ Ketik Nama Manual", "callback_data": "cab_MANUAL"}])

                reply_markup = {"inline_keyboard": keyboard}
                await send_telegram_message(
                    chat_id,
                    f"Anda memilih kategori: *{kat_label}*\n\n"
                    f"Langkah 2: Silakan pilih *Cabang Karyawan*:",
                    reply_markup=reply_markup,
                )

        # 3. Pilihan Cabang oleh Karyawan
        elif data.startswith("cab_"):
            cab_selected = data.replace("cab_", "")
            if chat_id in user_states:
                if cab_selected == "MANUAL":
                    user_states[chat_id]["step"] = "input_nama"
                    await send_telegram_message(
                        chat_id,
                        "Silakan ketik *Nama Lengkap Karyawan* sesuai yang terdaftar di HR:"
                    )
                else:
                    user_states[chat_id]["data"]["cabang"] = cab_selected
                    user_states[chat_id]["step"] = "pilih_karyawan"

                    emps = (
                        db.query(models.Employee)
                        .filter(models.Employee.cabang == cab_selected, models.Employee.active == True)
                        .order_by(models.Employee.nama.asc())
                        .all()
                    )

                    keyboard = []
                    row = []
                    for emp in emps:
                        row.append({"text": f"👤 {emp.nama}", "callback_data": f"emp_{emp.id}"})
                        if len(row) == 2:
                            keyboard.append(row)
                            row = []
                    if row:
                        keyboard.append(row)
                    keyboard.append([{"text": "✏️ Ketik Nama Manual", "callback_data": "cab_MANUAL"}])

                    reply_markup = {"inline_keyboard": keyboard}
                    await send_telegram_message(
                        chat_id,
                        f"Cabang: *{cab_selected}*\n\n"
                        f"Langkah 3: Silakan pilih *Nama Karyawan* dari daftar berikut:",
                        reply_markup=reply_markup,
                    )

        # 4. Pilihan Nama Karyawan oleh Karyawan (via inline keyboard)
        elif data.startswith("emp_"):
            emp_id_str = data.replace("emp_", "")
            if chat_id in user_states:
                try:
                    emp_id = int(emp_id_str)
                    emp = db.query(models.Employee).filter(models.Employee.id == emp_id).first()
                    nama_fix = emp.nama if emp else "Karyawan"
                    cab_info = f" ({emp.cabang})" if emp and emp.cabang else ""
                except Exception:
                    nama_fix = "Karyawan"
                    cab_info = ""

                user_states[chat_id]["data"]["nama"] = nama_fix
                user_states[chat_id]["step"] = "input_tgl_mulai"

                await send_telegram_message(
                    chat_id,
                    f"Karyawan dipilih: *{nama_fix}*{cab_info}\n\n"
                    f"Langkah 4: Masukkan *Tanggal Mulai*\n"
                    f"Format: `YYYY-MM-DD` atau `DD-MM-YYYY`\n"
                    f"(Anda juga bisa ketik: `hari ini` atau `besok`):",
                )

        # 3. Konfirmasi Pengajuan Karyawan
        elif data == "confirm_submit":
            if chat_id in user_states:
                form_data = user_states[chat_id]["data"]
                nama = form_data.get("nama")
                kategori = form_data.get("kategori", "CUTI_TAHUNAN")
                tgl_mulai = form_data.get("tanggal_mulai")
                tgl_selesai = form_data.get("tanggal_selesai")
                jam_izin = form_data.get("jam_izin")
                alasan = form_data.get("alasan")

                # Simpan ke Database
                leave = models.LeaveRequest(
                    nama=nama,
                    telegram_user_id=str(chat_id),
                    kategori=kategori,
                    tanggal_mulai=tgl_mulai,
                    tanggal_selesai=tgl_selesai,
                    jam_izin=jam_izin,
                    alasan=alasan,
                    status="PENDING",
                )
                db.add(leave)
                db.commit()
                db.refresh(leave)

                # Reset state percakapan
                user_states.pop(chat_id, None)

                # Edit pesan konfirmasi
                await edit_telegram_message(
                    chat_id,
                    msg_id,
                    f"✅ *Pengajuan Berhasil Dikirim!*\n\n"
                    f"ID Pengajuan Anda: `#{leave.id}`\n"
                    f"Status saat ini: ⏳ *PENDING*\n\n"
                    f"Pengajuan telah diteruskan ke HR Master untuk diverifikasi. "
                    f"Anda akan menerima notifikasi otomatis saat disetujui.",
                    reply_markup=None,
                )

                # Kirim notifikasi instan ke HR Master
                await notify_hr_master_new_leave(leave)

        elif data == "cancel_submit":
            user_states.pop(chat_id, None)
            await edit_telegram_message(chat_id, msg_id, "❌ Pengajuan telah dibatalkan.", reply_markup=None)

        return

    # -----------------------------------------------------------------------
    # B. MENANGANI PESAN TEKS (COMMANDS & CONVERSATION)
    # -----------------------------------------------------------------------
    if "message" not in update:
        return

    msg = update["message"]
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    if not chat_id or not text:
        return

    lower_text = text.lower()

    # Perintah /start
    if lower_text == "/start":
        user_states.pop(chat_id, None)
        welcome_text = (
            f"👋 *Selamat datang di Bot HR Absensi & Cuti!*\n\n"
            f"Bot ini digunakan untuk mempermudah karyawan mengajukan cuti/izin resmi, "
            f"serta memfasilitasi persetujuan instan oleh HR Master.\n\n"
            f"*Perintah yang tersedia:*\n"
            f"• `/cuti` atau `/izin` : Ajukan cuti / sakit / izin telat / pulang cepat\n"
            f"• `/status` : Cek status permohonan cuti Anda\n"
            f"• `/batal` : Batalkan pengisian form yang sedang berjalan\n"
            f"• `/help` : Panduan penggunaan bot\n"
        )
        hr_chat_id = os.environ.get("TELEGRAM_HR_CHAT_ID", TELEGRAM_HR_CHAT_ID).strip()
        if hr_chat_id and str(chat_id) == hr_chat_id:
            welcome_text += (
                f"\n👑 *Menu Khusus HR Master:*\n"
                f"• `/pending` : Lihat daftar pengajuan yang masih menunggu persetujuan\n"
            )

        await send_telegram_message(chat_id, welcome_text)
        return

    # Perintah /help
    if lower_text == "/help":
        await send_telegram_message(
            chat_id,
            f"ℹ️ *PANDUAN PENGGUNAAN BOT HR*\n\n"
            f"1. Ketik `/cuti` untuk memulai formulir pengajuan.\n"
            f"2. Pilih jenis permohonan (Cuti Tahunan, Sakit, Izin Telat, Izin Pulang Cepat).\n"
            f"3. Masukkan nama lengkap karyawan.\n"
            f"4. Masukkan tanggal mulai & selesai.\n"
            f"5. Jika izin telat/pulang awal, masukkan jam izin (contoh: `09:30` atau `14:00`).\n"
            f"6. Tuliskan alasan singkat permohonan.\n"
            f"7. Konfirmasi pengiriman pengajuan.\n\n"
            f"Setelah diajukan, HR Master akan menerima notifikasi tombol persetujuan secara instan.",
        )
        return

    # Perintah /batal
    if lower_text == "/batal":
        if chat_id in user_states:
            user_states.pop(chat_id, None)
            await send_telegram_message(chat_id, "Pengisian formulir telah dibatalkan.")
        else:
            await send_telegram_message(chat_id, "Tidak ada formulir yang sedang berjalan.")
        return

    # Perintah /pending (Khusus HR Master)
    if lower_text == "/pending":
        hr_chat_id = os.environ.get("TELEGRAM_HR_CHAT_ID", TELEGRAM_HR_CHAT_ID).strip()
        if hr_chat_id and str(chat_id) != hr_chat_id:
            await send_telegram_message(chat_id, "⛔ Perintah ini hanya dapat diakses oleh HR Master.")
            return

        pendings = (
            db.query(models.LeaveRequest)
            .filter(models.LeaveRequest.status == "PENDING")
            .order_by(models.LeaveRequest.created_at.asc())
            .limit(10)
            .all()
        )

        if not pendings:
            await send_telegram_message(chat_id, "🎉 Tidak ada pengajuan cuti/izin yang sedang PENDING.")
            return

        await send_telegram_message(chat_id, f"📋 Ditemukan *{len(pendings)}* pengajuan cuti/izin PENDING:")

        for item in pendings:
            kat_name = KATEGORI_NAME_MAP.get(item.kategori, item.kategori)
            is_same = item.tanggal_mulai == item.tanggal_selesai
            periode = (
                item.tanggal_mulai.strftime("%d %b %Y")
                if is_same
                else f"{item.tanggal_mulai.strftime('%d %b %Y')} s/d {item.tanggal_selesai.strftime('%d %b %Y')}"
            )
            jam_info = f"⏰ Jam: {item.jam_izin}\n" if item.jam_izin else ""

            item_text = (
                f"🆔 *ID #{item.id}* - *{item.nama}*\n"
                f"📋 {kat_name}\n"
                f"📅 {periode}\n"
                f"{jam_info}"
                f"📝 Alasan: {item.alasan or '-'}"
            )
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Setujui", "callback_data": f"approve_{item.id}"},
                        {"text": "❌ Tolak", "callback_data": f"reject_{item.id}"},
                    ]
                ]
            }
            await send_telegram_message(chat_id, item_text, reply_markup=reply_markup)
        return

    # Perintah /status
    if lower_text == "/status":
        leaves = (
            db.query(models.LeaveRequest)
            .filter(models.LeaveRequest.telegram_user_id == str(chat_id))
            .order_by(models.LeaveRequest.created_at.desc())
            .limit(5)
            .all()
        )

        if not leaves:
            await send_telegram_message(
                chat_id,
                "Belum ada riwayat pengajuan cuti/izin dari akun Telegram Anda. "
                "Ketik `/cuti` untuk mengajukan.",
            )
            return

        lines = ["📊 *Riwayat 5 Pengajuan Terakhir Anda:*\n"]
        for idx, lv in enumerate(leaves, 1):
            kat_name = KATEGORI_NAME_MAP.get(lv.kategori, lv.kategori)
            status_icon = (
                "⏳ Pending"
                if lv.status == "PENDING"
                else ("✅ Disetujui" if lv.status == "APPROVED" else "❌ Ditolak")
            )
            is_same = lv.tanggal_mulai == lv.tanggal_selesai
            periode = (
                lv.tanggal_mulai.strftime("%d/%m/%Y")
                if is_same
                else f"{lv.tanggal_mulai.strftime('%d/%m/%Y')} - {lv.tanggal_selesai.strftime('%d/%m/%Y')}"
            )
            lines.append(
                f"{idx}. *{kat_name}* (#{lv.id})\n"
                f"   📅 {periode} | Status: *{status_icon}*"
            )

        await send_telegram_message(chat_id, "\n".join(lines))
        return

    # Perintah /cuti atau /izin
    if lower_text in ("/cuti", "/izin"):
        user_states[chat_id] = {"step": "pilih_kategori", "data": {}}
        reply_markup = {
            "inline_keyboard": [
                [{"text": "🏖️ Cuti Tahunan", "callback_data": "kat_CUTI_TAHUNAN"}],
                [{"text": "🏥 Sakit (SKD)", "callback_data": "kat_SAKIT"}],
                [{"text": "⏰ Izin Datang Terlambat", "callback_data": "kat_IZIN_TELAT"}],
                [{"text": "🏃 Izin Pulang Cepat", "callback_data": "kat_IZIN_PULANG_CEPAT"}],
                [{"text": "📝 Izin Lainnya", "callback_data": "kat_LAINNYA"}],
            ]
        }
        await send_telegram_message(
            chat_id,
            "📝 *FORMULIR PENGAJUAN CUTI & IZIN*\n\n"
            "Langkah 1: Silakan pilih *Kategori Permohonan* Anda:",
            reply_markup=reply_markup,
        )
        return

    # -----------------------------------------------------------------------
    # C. ALUR STATE MACHINE FORMULIR
    # -----------------------------------------------------------------------
    state = user_states.get(chat_id)
    if not state:
        await send_telegram_message(
            chat_id,
            "Ketik `/cuti` untuk mengajukan cuti/izin, atau `/help` untuk panduan.",
        )
        return

    step = state.get("step")

    # Step: Input Nama Karyawan
    if step == "input_nama":
        input_nama = text.strip()
        if len(input_nama) < 3:
            await send_telegram_message(chat_id, "Nama terlalu pendek. Silakan masukkan nama lengkap:")
            return

        # Opsional: verifikasi dengan master karyawan di DB
        emp = db.query(models.Employee).filter(models.Employee.nama.ilike(f"%{input_nama}%")).first()
        nama_fix = emp.nama if emp else input_nama

        state["data"]["nama"] = nama_fix
        state["step"] = "input_tgl_mulai"

        await send_telegram_message(
            chat_id,
            f"Nama Karyawan: *{nama_fix}*\n\n"
            f"Langkah 3: Masukkan *Tanggal Mulai*\n"
            f"Format: `YYYY-MM-DD` atau `DD-MM-YYYY`\n"
            f"(Anda juga bisa ketik: `hari ini` atau `besok`):",
        )
        return

    # Step: Input Tanggal Mulai
    if step == "input_tgl_mulai":
        parsed_date = parse_date_input(text)
        if not parsed_date:
            await send_telegram_message(
                chat_id,
                "⚠️ Format tanggal tidak dikenali. Silakan ketik tanggal seperti: `2026-09-25` atau `25-09-2026`:",
            )
            return

        state["data"]["tanggal_mulai"] = parsed_date
        kat = state["data"].get("kategori")

        # Jika izin telat atau izin pulang cepat, otomatis selesai di hari yang sama
        if kat in ("IZIN_TELAT", "IZIN_PULANG_CEPAT"):
            state["data"]["tanggal_selesai"] = parsed_date
            state["step"] = "input_jam_izin"
            contoh_jam = "09:30" if kat == "IZIN_TELAT" else "14:00"
            await send_telegram_message(
                chat_id,
                f"Tanggal: *{parsed_date.strftime('%d %B %Y')}*\n\n"
                f"Langkah 4: Masukkan *Jam Izin* (Format `HH:MM`)\n"
                f"Contoh: `{contoh_jam}` :",
            )
            return

        state["step"] = "input_tgl_selesai"
        await send_telegram_message(
            chat_id,
            f"Tanggal Mulai: *{parsed_date.strftime('%d %B %Y')}*\n\n"
            f"Langkah 4: Masukkan *Tanggal Selesai*\n"
            f"(Ketik `sama` jika hanya 1 hari):",
        )
        return

    # Step: Input Tanggal Selesai
    if step == "input_tgl_selesai":
        tgl_mulai = state["data"]["tanggal_mulai"]
        if text.strip().lower() in ("sama", "1 hari", "-"):
            parsed_date = tgl_mulai
        else:
            parsed_date = parse_date_input(text)

        if not parsed_date:
            await send_telegram_message(
                chat_id,
                "⚠️ Format tanggal selesai tidak dikenali. Ketik `sama` atau format `YYYY-MM-DD`:",
            )
            return

        if parsed_date < tgl_mulai:
            await send_telegram_message(
                chat_id,
                "⚠️ Tanggal selesai tidak boleh lebih awal dari tanggal mulai. Silakan masukkan ulang:",
            )
            return

        state["data"]["tanggal_selesai"] = parsed_date
        state["step"] = "input_alasan"

        await send_telegram_message(
            chat_id,
            f"Tanggal Selesai: *{parsed_date.strftime('%d %B %Y')}*\n\n"
            f"Langkah 5: Tuliskan *Alasan / Keterangan* pengajuan:",
        )
        return

    # Step: Input Jam Izin
    if step == "input_jam_izin":
        jam = parse_time_input(text)
        if not jam:
            await send_telegram_message(
                chat_id,
                "⚠️ Format jam tidak valid. Masukkan dalam format `HH:MM` (contoh: `09:30` atau `14:00`):",
            )
            return

        state["data"]["jam_izin"] = jam
        state["step"] = "input_alasan"

        await send_telegram_message(
            chat_id,
            f"Jam Izin: *{jam}*\n\n"
            f"Langkah 5: Tuliskan *Alasan / Keterangan* permohonan izin:",
        )
        return

    # Step: Input Alasan & Konfirmasi
    if step == "input_alasan":
        state["data"]["alasan"] = text.strip()
        data = state["data"]

        kat_name = KATEGORI_NAME_MAP.get(data.get("kategori"), data.get("kategori"))
        t_mulai = data.get("tanggal_mulai")
        t_selesai = data.get("tanggal_selesai")
        is_same = t_mulai == t_selesai
        periode_str = (
            t_mulai.strftime("%d %B %Y")
            if is_same
            else f"{t_mulai.strftime('%d %B %Y')} s/d {t_selesai.strftime('%d %B %Y')}"
        )
        jam_str = f"\n⏰ *Jam Izin:* {data.get('jam_izin')}" if data.get("jam_izin") else ""

        summary_text = (
            f"📄 *RINGKASAN PENGAJUAN ANDA*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Nama Karyawan:* {data.get('nama')}\n"
            f"📋 *Kategori:* {kat_name}\n"
            f"📅 *Periode:* {periode_str}"
            f"{jam_str}\n"
            f"📝 *Alasan:* {data.get('alasan')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Apakah data di atas sudah benar?"
        )

        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Kirim Pengajuan", "callback_data": "confirm_submit"},
                    {"text": "❌ Batalkan", "callback_data": "cancel_submit"},
                ]
            ]
        }

        state["step"] = "waiting_confirmation"
        await send_telegram_message(chat_id, summary_text, reply_markup=reply_markup)
        return


# ===========================================================================
# 5. FASTAPI ROUTE ENDPOINTS
# ===========================================================================

@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_telegram_bot_api_secret_token: Optional[str] = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
):
    """
    Endpoint Webhook utama untuk menerima payload dari Telegram Bot.
    """
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_WEBHOOK_SECRET).strip()
    if secret and x_telegram_bot_api_secret_token != secret:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    try:
        update_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    await process_telegram_update(update_data, db)
    return {"status": "ok"}


@router.get("/set-webhook")
async def set_telegram_webhook(url: str):
    """
    Helper untuk mendaftarkan URL Webhook ke Telegram API.
    Contoh: GET /telegram/set-webhook?url=https://backend-anda.railway.app/telegram/webhook
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN).strip()
    if not token:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN belum disetel di .env")

    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_WEBHOOK_SECRET).strip()
    tg_url = get_telegram_api_url("setWebhook")
    payload = {"url": url}
    if secret:
        payload["secret_token"] = secret

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(tg_url, json=payload)
        return resp.json()


@router.get("/webhook-info")
async def get_telegram_webhook_info():
    """
    Helper untuk mengecek status webhook aktif dari Telegram API.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN).strip()
    if not token:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN belum disetel di .env")

    tg_url = get_telegram_api_url("getWebhookInfo")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(tg_url)
        return resp.json()
