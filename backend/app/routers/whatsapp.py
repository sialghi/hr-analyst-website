# -*- coding: utf-8 -*-
import os
import re
import uuid
import datetime
from typing import Optional, Dict, Any, List
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from pathlib import Path
from dotenv import load_dotenv

from .. import models
from ..database import get_db

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# Direktori penyimpanan foto bukti absensi jarak jauh
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "foto_absensi"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ===========================================================================
# KONFIGURASI DARI ENVIRONMENT
# ===========================================================================
def get_env_var(key: str, default: str = "") -> str:
    """Ambil env var dengan auto reload dari file .env jika belum terbaca."""
    val = os.environ.get(key, "").strip()
    if not val:
        load_dotenv(dotenv_path=env_path, override=True)
        val = os.environ.get(key, default).strip()
    return val

GRAPH_API_VERSION = "v21.0"

# State percakapan in-memory untuk form karyawan
# Format: user_states[phone_number] = {"step": str, "data": dict}
user_states: Dict[str, Dict[str, Any]] = {}

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
    "WORK_FROM_LOCATION": "📍 Absensi Jarak Jauh",
}


# ===========================================================================
# 1. PARSER TANGGAL & WAKTU
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
# 2. HELPER WHATSAPP CLOUD API (HTTPX)
# ===========================================================================

def get_whatsapp_api_url() -> str:
    phone_id = get_env_var("WHATSAPP_PHONE_NUMBER_ID")
    return f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_id}/messages"


MAX_MEDIA_BYTES = 10 * 1024 * 1024  # 10 MB


async def download_whatsapp_media(media_id: str, mime_type: str = "image/jpeg") -> Optional[str]:
    """
    Download media dari WhatsApp Cloud API menggunakan media_id.
    Simpan ke UPLOAD_DIR dan kembalikan path relatif (untuk disimpan di DB).
    Mengembalikan 'EXCEEDED_SIZE' jika ukuran melebihi 10MB.
    """
    token = get_env_var("WHATSAPP_ACCESS_TOKEN")
    if not token:
        print("[WhatsApp] WHATSAPP_ACCESS_TOKEN belum disetel, tidak bisa download media.")
        return None

    # 1. Ambil URL download dari Graph API
    meta_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{media_id}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            info_resp = await client.get(meta_url, headers=headers)
            if info_resp.status_code != 200:
                print(f"[WhatsApp] Gagal mendapat info media {media_id}: {info_resp.text}")
                return None
            media_info = info_resp.json()

            # Validasi ukuran awal dari metadata jika tersedia
            file_size_meta = media_info.get("file_size")
            if file_size_meta and int(file_size_meta) > MAX_MEDIA_BYTES:
                print(f"[WhatsApp] Media {media_id} ditolak karena melebihi 10MB: {file_size_meta} bytes")
                return "EXCEEDED_SIZE"

            download_url = media_info.get("url")
            if not download_url:
                return None

            # 2. Download file biner
            dl_resp = await client.get(download_url, headers=headers)
            if dl_resp.status_code != 200:
                print(f"[WhatsApp] Gagal download media: {dl_resp.status_code}")
                return None

            # Validasi ukuran aktual unduhan
            if len(dl_resp.content) > MAX_MEDIA_BYTES:
                print(f"[WhatsApp] Konten media {media_id} melebihi 10MB: {len(dl_resp.content)} bytes")
                return "EXCEEDED_SIZE"

            # Tentukan ekstensi dari mime_type (mendukung gambar & dokumen PDF)
            ext_map = {
                "image/jpeg": "jpg", "image/jpg": "jpg",
                "image/png": "png", "image/webp": "webp",
                "image/heic": "heic", "image/heif": "heic",
                "application/pdf": "pdf",
            }
            ext = ext_map.get(mime_type.lower(), "jpg")
            filename = f"{uuid.uuid4().hex}.{ext}"
            filepath = UPLOAD_DIR / filename

            filepath.write_bytes(dl_resp.content)
            rel_path = f"uploads/foto_absensi/{filename}"
            print(f"[WhatsApp] Berkas bukti tersimpan: {filepath} ({len(dl_resp.content)} bytes)")
            return rel_path

    except Exception as e:
        print(f"[WhatsApp] Error download media: {e}")
        return None


async def send_whatsapp_raw(payload: Dict[str, Any]) -> Optional[dict]:
    """Mengirim raw payload JSON ke Meta WhatsApp Cloud API."""
    token = get_env_var("WHATSAPP_ACCESS_TOKEN")
    phone_id = get_env_var("WHATSAPP_PHONE_NUMBER_ID")

    if not token or not phone_id:
        print("[WhatsApp] Warning: WHATSAPP_ACCESS_TOKEN atau WHATSAPP_PHONE_NUMBER_ID belum disetel di .env.")
        return None

    url = get_whatsapp_api_url()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            res_json = resp.json()
            if resp.status_code >= 400:
                print(f"[WhatsApp] API Error ({resp.status_code}): {res_json}")
            return res_json
    except Exception as e:
        print(f"[WhatsApp] Error send_whatsapp_raw: {e}")
        return None


async def send_whatsapp_text(to_number: str, message: str) -> Optional[dict]:
    """Mengirim pesan teks ke nomor WhatsApp (format nomor: 628xxxxxxxxxx)."""
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {"preview_url": False, "body": message},
    }
    return await send_whatsapp_raw(payload)


async def send_whatsapp_buttons(
    to_number: str,
    body_text: str,
    buttons: List[Dict[str, str]],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
) -> Optional[dict]:
    """
    Mengirim pesan interaktif dengan quick reply buttons (maksimal 3 tombol).
    buttons: list of {"id": "...", "title": "..."}
    """
    if not buttons:
        return await send_whatsapp_text(to_number, body_text)

    # WhatsApp API hanya mendukung maksimal 3 tombol
    formatted_buttons = []
    for btn in buttons[:3]:
        # title maksimal 20 karakter di WhatsApp API
        title = btn["title"][:20]
        formatted_buttons.append({
            "type": "reply",
            "reply": {"id": btn["id"], "title": title}
        })

    interactive_data: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": formatted_buttons},
    }
    if header_text:
        interactive_data["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive_data["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "interactive",
        "interactive": interactive_data,
    }
    return await send_whatsapp_raw(payload)


async def send_whatsapp_list(
    to_number: str,
    body_text: str,
    button_label: str,
    sections: List[Dict[str, Any]],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
) -> Optional[dict]:
    """
    Mengirim pesan interaktif menu dropdown / List (maksimal 10 item).
    sections: list of {"title": "...", "rows": [{"id": "...", "title": "...", "description": "..."}]}
    """
    interactive_data: Dict[str, Any] = {
        "type": "list",
        "body": {"text": body_text},
        "action": {
            "button": button_label[:20],
            "sections": sections,
        },
    }
    if header_text:
        interactive_data["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive_data["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "interactive",
        "interactive": interactive_data,
    }
    return await send_whatsapp_raw(payload)


# ===========================================================================
# 3. NOTIFIKASI HASIL APPROVAL DARI WEBSITE KE WHATSAPP KARYAWAN
# ===========================================================================

async def send_whatsapp_leave_status_notification(
    whatsapp_user_id: str,
    leave_id: int,
    nama: str,
    kategori: str,
    tanggal_mulai: datetime.date,
    tanggal_selesai: datetime.date,
    jam_izin: Optional[str],
    alasan: Optional[str],
    status: str,
    approved_by: Optional[str],
    catatan_hr: Optional[str] = None,
):
    """
    Kirim notifikasi hasil respon HR Master LANGSUNG ke nomor WhatsApp milik pengaju.
    Dipanggil otomatis saat HR Master menekan Approve / Reject di Website HR Analyst.
    """
    if not whatsapp_user_id or not str(whatsapp_user_id).strip():
        print(f"[WhatsApp] Pengajuan #{leave_id} tidak memiliki whatsapp_user_id. Notifikasi dilewati.")
        return

    target_number = str(whatsapp_user_id).strip()
    kat_name = KATEGORI_NAME_MAP.get(kategori, kategori)
    is_same = tanggal_mulai == tanggal_selesai
    periode = (
        tanggal_mulai.strftime("%d %b %Y")
        if is_same
        else f"{tanggal_mulai.strftime('%d %b %Y')} s/d {tanggal_selesai.strftime('%d %b %Y')}"
    )

    jam_info = f"⏰ *Jam Izin:* {jam_izin}\n" if jam_izin else ""
    catatan_info = f"💬 *Catatan HR:* _{catatan_hr}_\n" if catatan_hr else ""
    verifikator = approved_by or "HR Master"

    if status.upper() == "APPROVED":
        msg = (
            f"🎉 *KABAR BAIK! Pengajuan Disetujui*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Halo *{nama}*, pengajuan cuti/izin Anda telah *DISETUJUI* oleh HR Master melalui Website HR.\n\n"
            f"🆔 *ID Pengajuan:* `#{leave_id}`\n"
            f"📋 *Kategori:* {kat_name}\n"
            f"📅 *Periode:* {periode}\n"
            f"{jam_info}"
            f"📝 *Alasan:* {alasan or '-'}\n"
            f"👤 *Disetujui oleh:* {verifikator}\n"
            f"{catatan_info}"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"✅ *Status absensi Anda akan otomatis disesuaikan oleh sistem pipeline HR.*"
        )
    elif status.upper() == "REJECTED":
        msg = (
            f"⚠️ *PEMBERITAHUAN: Pengajuan Ditolak*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Halo *{nama}*, mohon maaf pengajuan cuti/izin Anda *DITOLAK* oleh HR Master melalui Website HR.\n\n"
            f"🆔 *ID Pengajuan:* `#{leave_id}`\n"
            f"📋 *Kategori:* {kat_name}\n"
            f"📅 *Periode:* {periode}\n"
            f"{jam_info}"
            f"📝 *Alasan:* {alasan or '-'}\n"
            f"👤 *Diverifikasi oleh:* {verifikator}\n"
            f"{catatan_info}"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Silakan hubungi HR jika membutuhkan informasi atau koordinasi lebih lanjut."
        )
    else:
        return

    print(f"[WhatsApp] Mengirim notifikasi status #{leave_id} ({status}) ke WhatsApp: {target_number} ({nama})")
    await send_whatsapp_text(target_number, msg)


# ===========================================================================
# 4. LOGIKA PERCAKAPAN FORMULIR CHATBOT WHATSAPP
# ===========================================================================

async def send_welcome_menu(to_number: str):
    """Menampilkan pesan selamat datang dan pilihan menu utama bot."""
    body_text = (
        f"👋 *Selamat datang di WhatsApp Bot HR Absensi & Cuti!*\n\n"
        f"Layanan ini memudahkan karyawan untuk mengajukan permohonan cuti, "
        f"sakit, izin jam kerja, maupun absensi bekerja di luar kantor.\n\n"
        f"Semua pengajuan akan diteruskan langsung ke sistem Website HR Analyst "
        f"untuk diverifikasi oleh HR Master.\n\n"
        f"Silakan pilih menu di bawah atau ketik perintah:\n"
        f"• *Cuti* : Pengajuan Cuti Tahunan / Sakit / Izin\n"
        f"• *Absen Luar* : Pengajuan Absensi Jarak Jauh\n"
        f"• *Status* : Cek riwayat pengajuan Anda\n"
        f"• *Batal* : Membatalkan pengisian form"
    )

    sections = [
        {
            "title": "Menu Utama HR",
            "rows": [
                {
                    "id": "menu_cuti",
                    "title": "🏖️ Ajukan Cuti/Izin",
                    "description": "Cuti Tahunan, Sakit SKD, Izin Telat/Pulang",
                },
                {
                    "id": "menu_wfl",
                    "title": "📍 Absen Jarak Jauh",
                    "description": "Bekerja di luar kantor / tugas luar",
                },
                {
                    "id": "menu_status",
                    "title": "📊 Cek Status Saya",
                    "description": "Lihat 5 riwayat pengajuan terakhir",
                },
                {
                    "id": "menu_help",
                    "title": "❓ Bantuan",
                    "description": "Panduan lengkap penggunaan bot",
                },
            ],
        }
    ]

    await send_whatsapp_list(
        to_number=to_number,
        body_text=body_text,
        button_label="Pilih Menu HR",
        sections=sections,
        header_text="HR BOT ASSISTANT",
    )


async def send_help_guide(to_number: str):
    guide_text = (
        f"ℹ️ *PANDUAN LENGKAP BOT WHATSAPP HR*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 *Pengajuan Cuti / Izin:*\n"
        f"1. Ketik *Cuti* atau pilih menu *Ajukan Cuti/Izin*.\n"
        f"2. Pilih jenis kategori (Cuti Tahunan, Sakit, Izin Telat, Pulang Cepat, Lainnya).\n"
        f"3. Pilih Cabang & Nama Karyawan sesuai master data HR.\n"
        f"4. Masukkan tanggal (contoh: `2026-10-05` atau `besok` / `hari ini`).\n"
        f"5. Jika izin telat/pulang awal, masukkan jam (contoh: `09:30`).\n"
        f"6. Tuliskan alasan singkat, lalu konfirmasi pengiriman.\n\n"
        f"📌 *Absensi Jarak Jauh (Tugas Luar):*\n"
        f"1. Ketik *Absen Luar* atau pilih menu *Absen Jarak Jauh*.\n"
        f"2. Pilih Cabang & Nama Karyawan.\n"
        f"3. Masukkan tanggal bertugas di luar kantor.\n"
        f"4. Tuliskan alasan penugasan / keterangan tugas.\n"
        f"5. Kirim *Foto Bukti* kehadiran di lokasi tugas (JPEG/PNG/WEBP/HEIC).\n"
        f"6. Klik *Ya, Kirim* pada kartu konfirmasi pengajuan.\n\n"
        f"📌 *Perintah Cepat:*\n"
        f"• Ketik *Status* untuk melihat status pengajuan Anda.\n"
        f"• Ketik *Batal* kapan saja untuk mengulang dari awal."
    )
    await send_whatsapp_text(to_number, guide_text)


async def start_cuti_flow(to_number: str):
    """Langkah 1: Pilih Kategori Cuti / Izin."""
    user_states[to_number] = {"step": "pilih_kategori", "data": {}}

    body = (
        "Langkah 1 dari 5:\n"
        "Silakan pilih *Kategori Pengajuan* yang Anda butuhkan:\n\n"
        "1. 🏖️ Cuti Tahunan (Full Day)\n"
        "2. 🏥 Sakit / SKD (Full Day)\n"
        "3. ⏰ Izin Datang Terlambat\n"
        "4. 🏃 Izin Pulang Lebih Awal\n"
        "5. 📝 Izin Lainnya\n\n"
        "_Tip: Anda bisa klik tombol 'Pilih Kategori' atau balas angka 1-5._"
    )

    sections = [
        {
            "title": "Jenis Izin / Cuti",
            "rows": [
                {"id": "kat_CUTI_TAHUNAN", "title": "Cuti Tahunan", "description": "Full Day cuti tahunan"},
                {"id": "kat_SAKIT", "title": "Sakit / SKD", "description": "Full Day sakit dengan surat dokter"},
                {"id": "kat_IZIN_TELAT", "title": "Izin Datang Telat", "description": "Izin jam masuk terlambat"},
                {"id": "kat_IZIN_PULANG_CEPAT", "title": "Izin Pulang Awal", "description": "Izin pulang sebelum jam keluar"},
                {"id": "kat_LAINNYA", "title": "Izin Lainnya", "description": "Keperluan mendesak lainnya"},
            ],
        }
    ]

    await send_whatsapp_list(
        to_number=to_number,
        body_text=body,
        button_label="Pilih Kategori",
        sections=sections,
        header_text="Pengajuan Cuti & Izin",
    )


async def start_wfl_flow(to_number: str, db: Session):
    """Mulai alur Absensi Jarak Jauh (WORK_FROM_LOCATION)."""
    user_states[to_number] = {
        "step": "wfl_pilih_cabang",
        "data": {
            "kategori": "WORK_FROM_LOCATION",
            "tipe_absensi": "remote_work",
        },
    }
    await prompt_pilih_cabang(to_number, db, is_wfl=True)


async def prompt_pilih_cabang(to_number: str, db: Session, is_wfl: bool = False, page: int = 1):
    """Langkah 2: Menampilkan daftar cabang karyawan dengan pagination."""
    cabang_records = (
        db.query(models.Employee.cabang)
        .filter(models.Employee.active == True)
        .distinct()
        .all()
    )
    cabang_list = sorted([c[0] for c in cabang_records if c[0]])

    prefix = "wfl_cab_" if is_wfl else "cab_"
    state_step = "wfl_pilih_cabang" if is_wfl else "pilih_cabang"
    user_states[to_number]["step"] = state_step

    title_text = "Absensi Jarak Jauh" if is_wfl else "Pengajuan Cuti/Izin"
    total_cab = len(cabang_list)

    if total_cab <= 9:
        body = (
            f"*{title_text}*\n\n"
            f"Langkah berikutnya: Silakan pilih *Cabang Karyawan* tempat Anda bertugas:\n\n"
            f"Pilih salah satu cabang dari menu daftar di bawah atau ketik nama cabang Anda.\n"
            f"_(Ketik 'manual' jika ingin mengetik nama karyawan langsung)_"
        )
        rows = []
        for cb_name in cabang_list:
            rows.append({
                "id": f"{prefix}{cb_name}",
                "title": f"🏢 {cb_name}"[:24],
                "description": f"Cabang {cb_name}"[:72],
            })
        rows.append({
            "id": f"{prefix}MANUAL",
            "title": "✏️ Ketik Nama Manual",
            "description": "Ketik nama lengkap karyawan manual",
        })
        sections = [{"title": "Daftar Cabang", "rows": rows}]
        await send_whatsapp_list(
            to_number=to_number,
            body_text=body,
            button_label="Pilih Cabang",
            sections=sections,
        )
        return

    import math
    PER_PAGE = 7
    total_pages = math.ceil(total_cab / PER_PAGE)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE
    page_cabs = cabang_list[start_idx:end_idx]

    body = (
        f"*{title_text}*\n\n"
        f"Silakan pilih *Cabang Karyawan* (Hal {page}/{total_pages}):\n\n"
        f"Pilih dari daftar tombol di bawah, atau langsung ketik nama cabang Anda."
    )
    rows = []
    for cb_name in page_cabs:
        rows.append({
            "id": f"{prefix}{cb_name}",
            "title": f"🏢 {cb_name}"[:24],
            "description": f"Cabang {cb_name}"[:72],
        })
    if page < total_pages:
        rows.append({
            "id": f"{prefix}PAGE_{page + 1}",
            "title": f"▶️ Hal {page + 1} ({total_cab - end_idx} Lainnya)",
            "description": "Lihat cabang di halaman berikutnya",
        })
    if page > 1:
        rows.append({
            "id": f"{prefix}PAGE_{page - 1}",
            "title": f"◀️ Kembali ke Hal {page - 1}",
            "description": "Lihat cabang di halaman sebelumnya",
        })
    rows.append({
        "id": f"{prefix}MANUAL",
        "title": "✏️ Ketik Nama Manual",
        "description": "Ketik nama lengkap karyawan manual",
    })
    sections = [{"title": f"Daftar Cabang (Hal {page})", "rows": rows[:10]}]
    await send_whatsapp_list(
        to_number=to_number,
        body_text=body,
        button_label="Pilih Cabang",
        sections=sections,
    )


async def prompt_pilih_karyawan(to_number: str, cabang: str, db: Session, is_wfl: bool = False, page: int = 1):
    """Langkah 3: Menampilkan daftar karyawan di cabang tertentu dengan pagination dan pencarian."""
    emps = (
        db.query(models.Employee)
        .filter(models.Employee.cabang == cabang, models.Employee.active == True)
        .order_by(models.Employee.nama.asc())
        .all()
    )

    prefix = "wfl_emp_" if is_wfl else "emp_"
    state_step = "wfl_pilih_karyawan" if is_wfl else "pilih_karyawan"
    user_states[to_number]["step"] = state_step
    user_states[to_number]["data"]["cabang"] = cabang

    if not emps:
        # Jika cabang tidak punya karyawan terdaftar, minta ketik manual
        user_states[to_number]["step"] = "wfl_input_nama" if is_wfl else "input_nama"
        await send_whatsapp_text(
            to_number,
            f"Tidak ada karyawan terdaftar otomatis di cabang *{cabang}*.\n\n"
            f"Silakan ketik *Nama Lengkap Karyawan* sesuai yang terdaftar di HR:"
        )
        return

    total_emps = len(emps)
    if total_emps <= 9:
        body = (
            f"🏢 Cabang: *{cabang}* ({total_emps} Karyawan)\n\n"
            f"Silakan pilih *Nama Karyawan* dari daftar berikut, atau ketik nama Anda langsung:"
        )
        rows = []
        for emp in emps:
            rows.append({
                "id": f"{prefix}{emp.id}",
                "title": f"👤 {emp.nama}"[:24],
                "description": f"{cabang} - ID Mesin: {emp.id_mesin or '-'}"[:72],
            })
        rows.append({
            "id": f"{prefix}MANUAL",
            "title": "✏️ Ketik Nama Manual",
            "description": "Ketik nama manual jika nama tidak tercantum",
        })
        sections = [{"title": f"Karyawan {cabang}", "rows": rows}]
        await send_whatsapp_list(
            to_number=to_number,
            body_text=body,
            button_label="Pilih Karyawan",
            sections=sections,
        )
        return

    # Pagination: maks 7 item per halaman agar muat tombol Next/Prev dan Manual (Maks 10 baris WhatsApp)
    import math
    PER_PAGE = 7
    total_pages = math.ceil(total_emps / PER_PAGE)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE
    page_emps = emps[start_idx:end_idx]

    body = (
        f"🏢 Cabang: *{cabang}* ({total_emps} Karyawan)\n"
        f"📄 Halaman *{page} dari {total_pages}* (Urutan {start_idx + 1}-{min(end_idx, total_emps)})\n\n"
        f"Silakan pilih dari menu tombol di bawah, ATAU Anda bisa langsung *ketik nama* Anda (contoh: *Yustari* atau *Zainudin*):"
    )

    rows = []
    for emp in page_emps:
        rows.append({
            "id": f"{prefix}{emp.id}",
            "title": f"👤 {emp.nama}"[:24],
            "description": f"{cabang} - ID Mesin: {emp.id_mesin or '-'}"[:72],
        })
    if page < total_pages:
        rows.append({
            "id": f"{prefix}PAGE_{page + 1}",
            "title": f"▶️ Hal {page + 1} ({total_emps - end_idx} Lainnya)",
            "description": f"Lihat karyawan halaman {page + 1}",
        })
    if page > 1:
        rows.append({
            "id": f"{prefix}PAGE_{page - 1}",
            "title": f"◀️ Kembali ke Hal {page - 1}",
            "description": f"Lihat karyawan halaman {page - 1}",
        })
    rows.append({
        "id": f"{prefix}MANUAL",
        "title": "✏️ Ketik Nama Manual",
        "description": "Ketik nama manual jika nama tidak tercantum",
    })

    sections = [{"title": f"Karyawan {cabang} (Hal {page})", "rows": rows[:10]}]
    await send_whatsapp_list(
        to_number=to_number,
        body_text=body,
        button_label="Daftar Karyawan",
        sections=sections,
    )


async def check_quota_and_prompt_date(to_number: str, nama: str, db: Session, is_wfl: bool = False):
    """Validasi kuota cuti tahunan dan minta input tanggal mulai."""
    from .leaves import get_annual_leave_stats

    user_states[to_number]["data"]["nama"] = nama
    kat_selected = user_states[to_number]["data"].get("kategori", "")

    if is_wfl:
        user_states[to_number]["step"] = "wfl_input_tgl"
        await send_whatsapp_text(
            to_number,
            f"👤 Karyawan: *{nama}*\n"
            f"🏢 Cabang: *{user_states[to_number]['data'].get('cabang', '-') }*\n\n"
            f"Silakan masukkan *Tanggal Bertugas Jarak Jauh*:\n"
            f"Format: `YYYY-MM-DD` atau `DD-MM-YYYY`\n"
            f"_(Contoh: `2026-10-05` atau ketik `hari ini` / `besok`)_:"
        )
        return

    # Hitung kuota cuti tahunan
    stats = get_annual_leave_stats(db, nama)
    user_states[to_number]["data"]["quota_stats"] = stats

    quota_msg = (
        f"📊 *Informasi Kuota Cuti Tahunan ({stats['year']}):*\n"
        f"• Total Jatah: *{int(stats['total_quota'])} Hari*\n"
        f"• Terpakai: *{int(stats['used_days'])} Hari*\n"
        f"• Sisa Jatah: *{int(stats['remaining_days'])} Hari*\n\n"
    )

    if kat_selected == "CUTI_TAHUNAN":
        if not stats.get("is_eligible", True):
            user_states.pop(to_number, None)
            tgl_berhak = stats.get("eligible_from")
            tgl_info = f" (Mulai berhak cuti: *{tgl_berhak.strftime('%d-%m-%Y')}*)" if tgl_berhak else ""
            await send_whatsapp_text(
                to_number,
                f"⛔ *MAAF: BELUM MEMILIKI HAK CUTI*\n\n"
                f"Halo *{nama}*, hak Cuti Tahunan baru dapat diajukan setelah genap 1 tahun masa kerja{tgl_info}.\n\n"
                f"Pengajuan cuti tahunan belum dapat diproses. "
                f"Silakan ketik *Cuti* jika ingin mengajukan izin jenis lain (Sakit / Izin Telat / Pulang Cepat)."
            )
            return

        if stats["remaining_days"] <= 0:
            user_states.pop(to_number, None)
            await send_whatsapp_text(
                to_number,
                f"⛔ *MAAF: JATAH CUTI TAHUNAN HABIS*\n\n"
                f"Halo *{nama}*, kuota Cuti Tahunan Anda untuk tahun *{stats['year']}* sudah habis "
                f"(Telah digunakan: *{int(stats['used_days'])}/{int(stats['total_quota'])} Hari*).\n\n"
                f"Pengajuan cuti tahunan tidak dapat dilanjutkan. "
                f"Silakan ketik *Cuti* jika ingin mengajukan izin jenis lain (Sakit / Izin Telat / Pulang Cepat)."
            )
            return

    user_states[to_number]["step"] = "input_tgl_mulai"
    await send_whatsapp_text(
        to_number,
        f"👤 Karyawan dipilih: *{nama}*\n\n"
        f"{quota_msg}"
        f"Langkah berikutnya: Masukkan *Tanggal Mulai*\n"
        f"Format: `YYYY-MM-DD` atau `DD-MM-YYYY`\n"
        f"_(Contoh: `2026-10-05` atau ketik `hari ini` / `besok`)_:"
    )


async def send_confirmation_card(to_number: str, is_wfl: bool = False):
    """Menampilkan ringkasan pengajuan dan tombol konfirmasi Kirim / Batal."""
    data = user_states[to_number]["data"]
    nama = data.get("nama")
    kategori = data.get("kategori")
    kat_name = KATEGORI_NAME_MAP.get(kategori, kategori)
    tgl_mulai = data.get("tanggal_mulai")
    tgl_selesai = data.get("tanggal_selesai")
    jam_izin = data.get("jam_izin")
    alasan = data.get("alasan")
    cabang = data.get("cabang")

    is_same = tgl_mulai == tgl_selesai
    periode = (
        tgl_mulai.strftime("%d %b %Y")
        if is_same
        else f"{tgl_mulai.strftime('%d %b %Y')} s/d {tgl_selesai.strftime('%d %b %Y')}"
    )

    cabang_line = f"🏢 *Cabang/Lokasi:* {cabang}\n" if cabang else ""
    jam_line = f"⏰ *Jam Izin:* {jam_izin}\n" if jam_izin else ""
    if kategori == "SAKIT" and data.get("foto_bukti"):
        is_pdf = data.get("foto_bukti", "").lower().endswith(".pdf")
        dok_label = "Dokumen PDF" if is_pdf else "Foto/Gambar"
        foto_line = f"📄 *Surat Dokter (SKD):* 🟢 Terlampir ({dok_label})\n"
    elif data.get("foto_bukti"):
        foto_line = "📸 *Foto Bukti:* 🟢 Terlampir (Foto Bukti Diterima)\n"
    else:
        foto_line = ""

    summary = (
        f"📋 *RINGKASAN PENGAJUAN*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Nama:* {nama}\n"
        f"📋 *Kategori:* {kat_name}\n"
        f"{cabang_line}"
        f"📅 *Periode:* {periode}\n"
        f"{jam_line}"
        f"📝 *Alasan:* {alasan}\n"
        f"{foto_line}"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Apakah data pengajuan di atas sudah benar dan siap dikirim ke HR?"
    )

    buttons = [
        {"id": "confirm_submit", "title": "✅ Ya, Kirim"},
        {"id": "cancel_submit", "title": "❌ Batalkan"},
    ]

    user_states[to_number]["step"] = "konfirmasi"
    await send_whatsapp_buttons(
        to_number=to_number,
        body_text=summary,
        buttons=buttons,
        header_text="Konfirmasi Pengajuan",
        footer_text="Klik tombol atau ketik 'ya' / 'batal'",
    )


# ===========================================================================
# 5. CORE UPDATE HANDLER DARI WHATSAPP
# ===========================================================================

async def process_whatsapp_incoming(
    from_number: str,
    raw_text: str,
    interactive_id: Optional[str],
    db: Session,
):
    """
    Memproses pesan masuk dari WhatsApp:
    Mendukung interaksi tombol/list (interactive_id) MAUPUN ketikan teks langsung.
    """
    from .leaves import check_leave_overlap, get_annual_leave_stats

    # Utamakan interactive_id dari tombol/list jika ada, fallback ke teks
    action_key = (interactive_id or "").strip()
    text = (raw_text or "").strip()
    lower_text = text.lower()

    # -----------------------------------------------------------------------
    # PERINTAH GLOBAL (Dapat dipanggil kapan saja)
    # -----------------------------------------------------------------------
    if action_key == "menu_help" or lower_text in ("/help", "help", "bantuan"):
        await send_help_guide(from_number)
        return

    if action_key == "cancel_submit" or lower_text in ("/batal", "batal", "cancel"):
        if from_number in user_states:
            user_states.pop(from_number, None)
            await send_whatsapp_text(from_number, "❌ Pengisian formulir telah dibatalkan.")
        else:
            await send_whatsapp_text(from_number, "ℹ️ Tidak ada formulir yang sedang berjalan. Ketik *Cuti* untuk mengajukan baru.")
        return

    if action_key == "menu_status" or lower_text in ("/status", "status", "cek status"):
        leaves = (
            db.query(models.LeaveRequest)
            .filter(models.LeaveRequest.whatsapp_user_id == from_number)
            .order_by(models.LeaveRequest.created_at.desc())
            .limit(5)
            .all()
        )

        if not leaves:
            await send_whatsapp_text(
                from_number,
                "Belum ada riwayat pengajuan cuti/izin dari nomor WhatsApp Anda.\n\n"
                "Ketik *Cuti* atau *Absen Luar* untuk membuat pengajuan baru."
            )
            return

        lines = ["📊 *Riwayat 5 Pengajuan Terakhir Anda:*\n━━━━━━━━━━━━━━━━━━"]
        for idx, lv in enumerate(leaves, 1):
            kat_name = KATEGORI_NAME_MAP.get(lv.kategori, lv.kategori)
            status_badge = (
                "⏳ PENDING"
                if lv.status == "PENDING"
                else ("✅ DISETUJUI" if lv.status == "APPROVED" else "❌ DITOLAK")
            )
            is_same = lv.tanggal_mulai == lv.tanggal_selesai
            periode = (
                lv.tanggal_mulai.strftime("%d/%m/%Y")
                if is_same
                else f"{lv.tanggal_mulai.strftime('%d/%m/%Y')} - {lv.tanggal_selesai.strftime('%d/%m/%Y')}"
            )
            jam_str = f" ({lv.jam_izin})" if lv.jam_izin else ""
            lines.append(
                f"{idx}. `#{lv.id}` *{kat_name}*\n"
                f"   📅 {periode}{jam_str}\n"
                f"   Status: *{status_badge}*\n"
                f"   Alasan: _{lv.alasan or '-'}_"
            )
        lines.append("━━━━━━━━━━━━━━━━━━\n_Persetujuan dilakukan oleh HR Master melalui Website HR._")
        await send_whatsapp_text(from_number, "\n\n".join(lines))
        return

    if action_key == "menu_wfl" or lower_text in ("/absen_luar", "absen luar", "tugas luar", "wfl"):
        await start_wfl_flow(from_number, db)
        return

    if action_key == "menu_cuti" or lower_text in ("/cuti", "cuti", "/izin", "izin"):
        await start_cuti_flow(from_number)
        return

    # Jika user menyapa awal atau belum ada state
    if lower_text in ("/start", "start", "/menu", "menu", "halo", "hai", "p", "hi", "selamat pagi", "selamat siang"):
        user_states.pop(from_number, None)
        await send_welcome_menu(from_number)
        return

    # -----------------------------------------------------------------------
    # FORM STEP CONVERSATION HANDLER
    # -----------------------------------------------------------------------
    state = user_states.get(from_number)
    if not state:
        await send_welcome_menu(from_number)
        return

    step = state.get("step")

    # STEP 1: PILIH KATEGORI (CUTI / IZIN)
    if step == "pilih_kategori":
        chosen_kat = None
        if action_key.startswith("kat_"):
            chosen_kat = action_key.replace("kat_", "")
        elif text in ("1", "2", "3", "4", "5"):
            chosen_kat = KATEGORI_MAP[text][0]
        elif "cuti" in lower_text:
            chosen_kat = "CUTI_TAHUNAN"
        elif "sakit" in lower_text:
            chosen_kat = "SAKIT"
        elif "telat" in lower_text:
            chosen_kat = "IZIN_TELAT"
        elif "pulang" in lower_text:
            chosen_kat = "IZIN_PULANG_CEPAT"
        elif "lain" in lower_text:
            chosen_kat = "LAINNYA"

        if not chosen_kat:
            await send_whatsapp_text(
                from_number,
                "Pilihan kategori tidak valid. Silakan pilih dari menu atau ketik angka 1 sampai 5:"
            )
            return

        user_states[from_number]["data"]["kategori"] = chosen_kat
        await prompt_pilih_cabang(from_number, db, is_wfl=False)
        return

    # STEP 2: PILIH CABANG (CUTI BIASA)
    if step == "pilih_cabang":
        cab_val = None
        if action_key.startswith("cab_"):
            cab_val = action_key.replace("cab_", "")
            if cab_val.startswith("PAGE_"):
                page_target = int(cab_val.replace("PAGE_", ""))
                await prompt_pilih_cabang(from_number, db, is_wfl=False, page=page_target)
                return
        else:
            cab_val = text.strip()

        if cab_val.upper() in ("MANUAL", "KETIK MANUAL"):
            user_states[from_number]["step"] = "input_nama"
            await send_whatsapp_text(from_number, "Silakan ketik *Nama Lengkap Karyawan* sesuai yang terdaftar di HR:")
            return

        await prompt_pilih_karyawan(from_number, cab_val, db, is_wfl=False, page=1)
        return

    # STEP 3: PILIH KARYAWAN (CUTI BIASA)
    if step == "pilih_karyawan":
        cabang = user_states[from_number]["data"].get("cabang", "")
        if action_key.startswith("emp_"):
            emp_id_str = action_key.replace("emp_", "")
            if emp_id_str.startswith("PAGE_"):
                page_target = int(emp_id_str.replace("PAGE_", ""))
                await prompt_pilih_karyawan(from_number, cabang, db, is_wfl=False, page=page_target)
                return
            if emp_id_str == "MANUAL":
                user_states[from_number]["step"] = "input_nama"
                await send_whatsapp_text(from_number, "Silakan ketik *Nama Lengkap Karyawan* sesuai yang terdaftar di HR:")
                return
            try:
                emp = db.query(models.Employee).filter(models.Employee.id == int(emp_id_str)).first()
                nama_fix = emp.nama if emp else "Karyawan"
            except Exception:
                nama_fix = "Karyawan"
            await check_quota_and_prompt_date(from_number, nama_fix, db, is_wfl=False)
            return
        else:
            # Ketik nama langsung -> Smart search pencocokan nama di database
            nama_query = text.strip()
            matched_emp = None
            if cabang:
                # 1. Coba exact match di cabang tersebut
                matched_emp = db.query(models.Employee).filter(
                    models.Employee.cabang == cabang,
                    models.Employee.active == True,
                    models.Employee.nama.ilike(nama_query)
                ).first()
                # 2. Coba partial match di cabang tersebut
                if not matched_emp:
                    matched_emp = db.query(models.Employee).filter(
                        models.Employee.cabang == cabang,
                        models.Employee.active == True,
                        models.Employee.nama.ilike(f"%{nama_query}%")
                    ).first()

            # 3. Fallback: coba cari di seluruh cabang
            if not matched_emp:
                matched_emp = db.query(models.Employee).filter(
                    models.Employee.active == True,
                    models.Employee.nama.ilike(f"%{nama_query}%")
                ).first()

            nama_fix = matched_emp.nama if matched_emp else nama_query
            await check_quota_and_prompt_date(from_number, nama_fix, db, is_wfl=False)
            return

    # STEP 3B: INPUT NAMA MANUAL
    if step == "input_nama":
        nama_input = text.strip()
        if not nama_input:
            await send_whatsapp_text(from_number, "Nama tidak boleh kosong. Silakan ketik nama lengkap karyawan:")
            return
        await check_quota_and_prompt_date(from_number, nama_input, db, is_wfl=False)
        return

    # STEP 4: INPUT TANGGAL MULAI
    if step == "input_tgl_mulai":
        parsed = parse_date_input(text)
        if not parsed:
            await send_whatsapp_text(
                from_number,
                "Format tanggal tidak dikenali.\n"
                "Gunakan format `YYYY-MM-DD` (contoh: `2026-10-05`) atau ketik `hari ini` / `besok`:"
            )
            return

        user_states[from_number]["data"]["tanggal_mulai"] = parsed
        kat = user_states[from_number]["data"].get("kategori")

        # Jika Izin Telat atau Pulang Cepat: otomatis 1 hari saja
        if kat in ("IZIN_TELAT", "IZIN_PULANG_CEPAT"):
            user_states[from_number]["data"]["tanggal_selesai"] = parsed
            user_states[from_number]["step"] = "input_jam_izin"
            jam_label = "Jam Kedatangan (Datang Terlambat)" if kat == "IZIN_TELAT" else "Jam Pulang (Pulang Cepat)"
            await send_whatsapp_text(
                from_number,
                f"Tanggal izin: *{parsed.strftime('%d %b %Y')}*\n\n"
                f"Langkah berikutnya: Masukkan *{jam_label}*\n"
                f"Format: `HH:MM` (contoh: `09:30` atau `14:00`):"
            )
            return

        # Cuti Tahunan / Sakit / Lainnya: minta tanggal selesai
        user_states[from_number]["step"] = "input_tgl_selesai"
        await send_whatsapp_text(
            from_number,
            f"Tanggal mulai: *{parsed.strftime('%d %b %Y')}*\n\n"
            f"Masukkan *Tanggal Selesai* cuti/izin\n"
            f"_(Jika hanya 1 hari, ketik `sama` atau tanggal yang sama)_:"
        )
        return

    # STEP 5: INPUT TANGGAL SELESAI
    if step == "input_tgl_selesai":
        tgl_mulai = user_states[from_number]["data"].get("tanggal_mulai")
        if lower_text in ("sama", "1 hari", "sehari"):
            parsed = tgl_mulai
        else:
            parsed = parse_date_input(text)

        if not parsed:
            await send_whatsapp_text(from_number, "Format tanggal selesai tidak valid. Contoh: `2026-10-06` atau ketik `sama`:")
            return

        if parsed < tgl_mulai:
            await send_whatsapp_text(
                from_number,
                f"Tanggal selesai ({parsed}) tidak boleh lebih awal dari tanggal mulai ({tgl_mulai}).\n"
                f"Silakan masukkan kembali tanggal selesai yang benar:"
            )
            return

        user_states[from_number]["data"]["tanggal_selesai"] = parsed
        user_states[from_number]["step"] = "input_alasan"
        await send_whatsapp_text(
            from_number,
            f"Periode: *{tgl_mulai.strftime('%d %b %Y')}* s/d *{parsed.strftime('%d %b %Y')}*\n\n"
            f"Tuliskan *Alasan Pengajuan* secara singkat dan jelas:"
        )
        return

    # STEP 5B: INPUT JAM IZIN (TELAT / PULANG CEPAT)
    if step == "input_jam_izin":
        parsed_time = parse_time_input(text)
        if not parsed_time:
            await send_whatsapp_text(from_number, "Format jam tidak valid. Gunakan format `HH:MM` (contoh: `09:30` atau `14:00`):")
            return

        user_states[from_number]["data"]["jam_izin"] = parsed_time
        user_states[from_number]["step"] = "input_alasan"
        await send_whatsapp_text(
            from_number,
            f"Jam izin: *{parsed_time}*\n\n"
            f"Tuliskan *Alasan Pengajuan* secara singkat dan jelas:"
        )
        return

    # STEP 6: INPUT ALASAN
    if step == "input_alasan":
        if not text:
            await send_whatsapp_text(from_number, "Alasan tidak boleh kosong. Silakan tuliskan alasan pengajuan Anda:")
            return

        user_states[from_number]["data"]["alasan"] = text.strip()
        kat = user_states[from_number]["data"].get("kategori")

        # Jika kategori SAKIT, wajib unggah Surat Keterangan Sakit / Surat Dokter (Foto atau PDF max 10MB)
        if kat == "SAKIT":
            user_states[from_number]["step"] = "sakit_upload_surat"
            await send_whatsapp_text(
                from_number,
                "📄 *Langkah Wajib: Unggah Surat Keterangan Sakit (SKD)*\n\n"
                "Silakan kirimkan berkas *Surat Dokter / Surat Keterangan Sakit* Anda.\n\n"
                "📌 *Ketentuan Berkas:*\n"
                "• Format: Foto/Gambar (JPEG, PNG, WEBP, HEIC) atau Dokumen PDF\n"
                "• Ukuran maksimal: *10 MB*\n\n"
                "_(Kirim langsung berkas berupa foto atau dokumen PDF. Ketik *Batal* jika ingin membatalkan)_"
            )
            return

        await send_confirmation_card(from_number, is_wfl=False)
        return

    # STEP 6B: UNGGAH SURAT KETERANGAN SAKIT (Jika user mengirimkan teks biasa)
    if step == "sakit_upload_surat":
        await send_whatsapp_text(
            from_number,
            "📄 Anda belum melampirkan berkas Surat Keterangan Sakit.\n\n"
            "Silakan kirimkan berkas berupa *Foto (JPEG/PNG/WEBP/HEIC)* atau *Dokumen PDF* surat dokter Anda (maks. 10 MB).\n\n"
            "_(Ketik *Batal* jika ingin membatalkan pengajuan)_"
        )
        return

    # -----------------------------------------------------------------------
    # ABSENSI JARAK JAUH (WORK FROM LOCATION) STEPS
    # -----------------------------------------------------------------------
    if step == "wfl_pilih_cabang":
        cab_val = None
        if action_key.startswith("wfl_cab_"):
            cab_val = action_key.replace("wfl_cab_", "")
            if cab_val.startswith("PAGE_"):
                page_target = int(cab_val.replace("PAGE_", ""))
                await prompt_pilih_cabang(from_number, db, is_wfl=True, page=page_target)
                return
        else:
            cab_val = text.strip()

        if cab_val.upper() in ("MANUAL", "KETIK MANUAL"):
            user_states[from_number]["step"] = "wfl_input_nama"
            await send_whatsapp_text(from_number, "Silakan ketik *Nama Lengkap Karyawan* yang bertugas di luar kantor:")
            return
        await prompt_pilih_karyawan(from_number, cab_val, db, is_wfl=True, page=1)
        return

    if step == "wfl_pilih_karyawan":
        cabang = user_states[from_number]["data"].get("cabang", "")
        if action_key.startswith("wfl_emp_"):
            emp_id_str = action_key.replace("wfl_emp_", "")
            if emp_id_str.startswith("PAGE_"):
                page_target = int(emp_id_str.replace("PAGE_", ""))
                await prompt_pilih_karyawan(from_number, cabang, db, is_wfl=True, page=page_target)
                return
            if emp_id_str == "MANUAL":
                user_states[from_number]["step"] = "wfl_input_nama"
                await send_whatsapp_text(from_number, "Silakan ketik *Nama Lengkap Karyawan*:")
                return
            try:
                emp = db.query(models.Employee).filter(models.Employee.id == int(emp_id_str)).first()
                nama_fix = emp.nama if emp else "Karyawan"
            except Exception:
                nama_fix = "Karyawan"
            await check_quota_and_prompt_date(from_number, nama_fix, db, is_wfl=True)
            return
        else:
            # Ketik nama langsung -> Smart search pencocokan nama di database
            nama_query = text.strip()
            matched_emp = None
            if cabang:
                matched_emp = db.query(models.Employee).filter(
                    models.Employee.cabang == cabang,
                    models.Employee.active == True,
                    models.Employee.nama.ilike(nama_query)
                ).first()
                if not matched_emp:
                    matched_emp = db.query(models.Employee).filter(
                        models.Employee.cabang == cabang,
                        models.Employee.active == True,
                        models.Employee.nama.ilike(f"%{nama_query}%")
                    ).first()

            if not matched_emp:
                matched_emp = db.query(models.Employee).filter(
                    models.Employee.active == True,
                    models.Employee.nama.ilike(f"%{nama_query}%")
                ).first()

            nama_fix = matched_emp.nama if matched_emp else nama_query
            await check_quota_and_prompt_date(from_number, nama_fix, db, is_wfl=True)
            return

    if step == "wfl_input_nama":
        nama_input = text.strip()
        if not nama_input:
            await send_whatsapp_text(from_number, "Nama tidak boleh kosong:")
            return
        await check_quota_and_prompt_date(from_number, nama_input, db, is_wfl=True)
        return

    if step == "wfl_input_tgl":
        parsed = parse_date_input(text)
        if not parsed:
            await send_whatsapp_text(from_number, "Format tanggal tidak dikenali. Contoh: `2026-10-05` atau ketik `hari ini` / `besok`:")
            return
        user_states[from_number]["data"]["tanggal_mulai"] = parsed
        user_states[from_number]["data"]["tanggal_selesai"] = parsed
        user_states[from_number]["step"] = "wfl_input_alasan"
        await send_whatsapp_text(
            from_number,
            f"Tanggal: *{parsed.strftime('%d %b %Y')}*\n\n"
            f"Tuliskan *Keterangan Tugas / Alasan Absen Jarak Jauh*:"
        )
        return

    if step == "wfl_input_alasan":
        if not text:
            await send_whatsapp_text(from_number, "Keterangan tugas tidak boleh kosong:")
            return
        user_states[from_number]["data"]["alasan"] = text.strip()
        # Setelah alasan, minta upload foto bukti
        user_states[from_number]["step"] = "wfl_upload_foto"
        await send_whatsapp_text(
            from_number,
            "📸 *Langkah Terakhir: Foto Bukti Absensi*\n\n"
            "Silakan kirimkan *foto bukti* kehadiran Anda di lokasi tugas.\n"
            "_(Format yang diterima: JPEG, PNG, WEBP, HEIC)_\n\n"
            "Foto akan tersimpan di sistem HR untuk keperluan verifikasi."
        )
        return

    # STEP UPLOAD FOTO BUKTI (WFL saja)
    # Catatan: handler ini dipanggil jika step == "wfl_upload_foto" dan ada image_data
    # (ditangani di webhook, lalu memanggil process_whatsapp_incoming dengan image_data)
    # Jika user kirim teks bukan gambar saat di step ini:
    if step == "wfl_upload_foto":
        await send_whatsapp_text(
            from_number,
            "📸 Anda belum mengirimkan foto.\n\n"
            "Silakan kirim *foto / gambar* sebagai bukti absensi Anda di lokasi tugas.\n"
            "_(Ketik *Batal* jika ingin membatalkan pengajuan)_"
        )
        return

    # STEP KONFIRMASI (SUBMIT KE DATABASE)
    if step == "konfirmasi":
        is_confirm = action_key == "confirm_submit" or lower_text in ("ya", "kirim", "yes", "ok", "oke", "1")
        if not is_confirm:
            await send_whatsapp_text(
                from_number,
                "Silakan klik tombol *Ya, Kirim* atau ketik *Ya* untuk mengirim pengajuan, atau *Batal* untuk membatalkan."
            )
            return

        form_data = user_states[from_number]["data"]
        nama = form_data.get("nama")
        kategori = form_data.get("kategori", "CUTI_TAHUNAN")
        tgl_mulai = form_data.get("tanggal_mulai")
        tgl_selesai = form_data.get("tanggal_selesai")
        jam_izin = form_data.get("jam_izin")
        alasan = form_data.get("alasan")
        cabang = form_data.get("cabang")
        tipe_absensi = form_data.get("tipe_absensi", "normal")

        # 1. Pengecekan Overlap / Tanggal Bentrok
        if nama and tgl_mulai and tgl_selesai:
            overlap = check_leave_overlap(db, nama, tgl_mulai, tgl_selesai)
            if overlap:
                user_states.pop(from_number, None)
                tgl_str = (
                    overlap.tanggal_mulai.strftime("%d-%m-%Y")
                    if overlap.tanggal_mulai == overlap.tanggal_selesai
                    else f"{overlap.tanggal_mulai.strftime('%d-%m-%Y')} s/d {overlap.tanggal_selesai.strftime('%d-%m-%Y')}"
                )
                kat_name = KATEGORI_NAME_MAP.get(overlap.kategori, overlap.kategori)
                await send_whatsapp_text(
                    from_number,
                    f"⛔ *PENGAJUAN DITOLAK SISTEM: TANGGAL BENTROK*\n\n"
                    f"Halo *{nama}*, Anda sudah memiliki pengajuan aktif pada tanggal tersebut:\n"
                    f"• ID: `#{overlap.id}` ({kat_name})\n"
                    f"• Periode: {tgl_str}\n"
                    f"• Status: {overlap.status}\n\n"
                    f"Pengajuan ganda tidak dapat diproses. Ketik *Cuti* untuk mencoba kembali."
                )
                return

        # 2. Pengecekan Kuota Cuti Tahunan
        if kategori == "CUTI_TAHUNAN" and tgl_mulai and tgl_selesai:
            requested_days = (tgl_selesai - tgl_mulai).days + 1
            stats = get_annual_leave_stats(db, nama, year=tgl_mulai.year)
            if not stats.get("is_eligible", True):
                user_states.pop(from_number, None)
                tgl_berhak = stats.get("eligible_from")
                tgl_info = f" (Mulai berhak: *{tgl_berhak.strftime('%d-%m-%Y')}*)" if tgl_berhak else ""
                await send_whatsapp_text(
                    from_number,
                    f"⛔ *PENGAJUAN DITOLAK SISTEM*\n\n"
                    f"Halo *{nama}*, Anda belum berhak mengajukan Cuti Tahunan karena belum genap 1 tahun bekerja{tgl_info}."
                )
                return
            if stats["remaining_days"] <= 0:
                user_states.pop(from_number, None)
                await send_whatsapp_text(
                    from_number,
                    f"⛔ *PENGAJUAN DITOLAK SISTEM*\n\n"
                    f"Jatah Cuti Tahunan untuk *{nama}* tahun {tgl_mulai.year} sudah habis ({int(stats['used_days'])}/{int(stats['total_quota'])} Hari terpakai)."
                )
                return
            if requested_days > stats["remaining_days"]:
                user_states.pop(from_number, None)
                await send_whatsapp_text(
                    from_number,
                    f"⛔ *PENGAJUAN DITOLAK SISTEM*\n\n"
                    f"Jumlah hari cuti yang Anda ajukan (*{requested_days} Hari*) melebihi sisa jatah Cuti Tahunan Anda (*{int(stats['remaining_days'])} Hari*)."
                )
                return

        # 3. Simpan ke Database
        leave = models.LeaveRequest(
            nama=nama,
            whatsapp_user_id=str(from_number),
            kategori=kategori,
            tanggal_mulai=tgl_mulai,
            tanggal_selesai=tgl_selesai,
            jam_izin=jam_izin,
            alasan=alasan,
            tipe_absensi=tipe_absensi,
            location_cabang=cabang,
            foto_bukti=form_data.get("foto_bukti"),
            status="PENDING",
        )
        db.add(leave)
        db.commit()
        db.refresh(leave)

        # Bersihkan state percakapan
        user_states.pop(from_number, None)

        # Kirim bukti pengajuan berhasil
        kat_label = KATEGORI_NAME_MAP.get(kategori, kategori)
        success_msg = (
            f"✅ *PENGAJUAN BERHASIL DIKIRIM!*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 *ID Pengajuan:* `#{leave.id}`\n"
            f"👤 *Nama:* {nama}\n"
            f"📋 *Kategori:* {kat_label}\n"
            f"⏳ *Status:* PENDING\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Pengajuan Anda telah tercatat di sistem Website HR Analyst.\n"
            f"Mohon menunggu persetujuan resmi dari HR Master melalui Website HR.\n\n"
            f"Kabar persetujuan akan otomatis dikirimkan ke nomor WhatsApp Anda."
        )
        await send_whatsapp_text(from_number, success_msg)
        return


# ===========================================================================
# 6. FASTAPI WEBHOOK ENDPOINTS (META DEVELOPER)
# ===========================================================================

@router.get("/webhook")
async def verify_webhook(request: Request):
    """
    Endpoint verifikasi handshake dari Meta for Developers.
    Meta akan mengirim HTTP GET dengan query params:
    hub.mode, hub.verify_token, hub.challenge.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    verify_token = get_env_var("WHATSAPP_VERIFY_TOKEN", "hr_analyst_wa_verify_token")

    if mode == "subscribe" and token == verify_token:
        print("[WhatsApp Webhook] Handshake verifikasi Meta berhasil!")
        # Meta mewajibkan respons teks polos dengan isi challenge
        return Response(content=challenge, media_type="text/plain")

    print(f"[WhatsApp Webhook] Handshake verifikasi gagal! Token query: {token}, Token env: {verify_token}")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@router.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint penerima pesan & event WhatsApp dari Meta Cloud API (HTTP POST).
    """
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}

    # Ekstraksi payload terstruktur Meta
    entry_list = payload.get("entry", [])
    for entry in entry_list:
        changes = entry.get("changes", [])
        for ch in changes:
            value = ch.get("value", {})
            messages = value.get("messages", [])
            if not messages:
                # Event delivery status (sent, delivered, read) - abaikan
                continue

            msg = messages[0]
            from_number = msg.get("from")  # nomor pengirim, misal '6281234567890'
            msg_type = msg.get("type")

            raw_text = ""
            interactive_id = None

            if msg_type == "text":
                raw_text = msg.get("text", {}).get("body", "")

            elif msg_type == "interactive":
                inter = msg.get("interactive", {})
                inter_type = inter.get("type")
                if inter_type == "button_reply":
                    interactive_id = inter.get("button_reply", {}).get("id")
                    raw_text = inter.get("button_reply", {}).get("title", "")
                elif inter_type == "list_reply":
                    interactive_id = inter.get("list_reply", {}).get("id")
                    raw_text = inter.get("list_reply", {}).get("title", "")

            elif (msg_type == "image" or msg_type == "document") and from_number:
                # Pesan berupa berkas foto atau dokumen (SKD / Absen Jarak Jauh)
                state = user_states.get(from_number)
                step_now = state.get("step") if state else None

                # 1. KASUS: UNGGAH SURAT KETERANGAN SAKIT (SKD) - Gambar atau PDF maks 10MB
                if state and step_now == "sakit_upload_surat":
                    msg_data = msg.get("image") or msg.get("document", {})
                    media_id = msg_data.get("id")
                    mime_type = msg_data.get("mime_type", "image/jpeg").lower()
                    doc_filename = msg_data.get("filename", "")

                    is_image = mime_type.startswith("image/") or msg_type == "image"
                    is_pdf = mime_type == "application/pdf" or doc_filename.lower().endswith(".pdf")

                    if not (is_image or is_pdf):
                        await send_whatsapp_text(
                            from_number,
                            "⚠️ Format berkas tidak didukung.\n"
                            "Mohon kirimkan Surat Keterangan Sakit berupa *Foto (JPEG, PNG, WEBP, HEIC)* atau *Dokumen PDF* (maks. 10 MB)."
                        )
                        continue

                    # Cek ukuran file awal jika tersedia di metadata
                    file_size = msg_data.get("file_size")
                    if file_size and int(file_size) > MAX_MEDIA_BYTES:
                        size_mb = int(file_size) / (1024 * 1024)
                        await send_whatsapp_text(
                            from_number,
                            f"⚠️ Ukuran berkas terlalu besar ({size_mb:.1f} MB).\n"
                            f"Maksimal ukuran file surat dokter adalah *10 MB*. Silakan kirimkan file yang lebih kecil."
                        )
                        continue

                    tipe_label = "Dokumen PDF" if is_pdf else "Foto"
                    await send_whatsapp_text(from_number, f"⏳ {tipe_label} surat keterangan sakit diterima, sedang menyimpan ke sistem HR...")
                    saved_path = await download_whatsapp_media(media_id, "application/pdf" if is_pdf else mime_type)

                    if saved_path == "EXCEEDED_SIZE":
                        await send_whatsapp_text(
                            from_number,
                            "⚠️ Ukuran berkas melebihi batas maksimal 10 MB.\n"
                            "Silakan kompres berkas Anda dan kirimkan kembali di bawah 10 MB."
                        )
                    elif saved_path:
                        user_states[from_number]["data"]["foto_bukti"] = saved_path
                        user_states[from_number]["step"] = "konfirmasi"
                        await send_confirmation_card(from_number, is_wfl=False)
                    else:
                        await send_whatsapp_text(
                            from_number,
                            "⚠️ Gagal mengunduh/menyimpan surat sakit dari WhatsApp. Silakan coba kirim ulang berkas Anda."
                        )

                # 2. KASUS: UNGGAH FOTO ABSENSI JARAK JAUH (WFL)
                elif state and step_now == "wfl_upload_foto":
                    msg_data = msg.get("image") or msg.get("document", {})
                    media_id = msg_data.get("id")
                    mime_type = msg_data.get("mime_type", "image/jpeg").lower()

                    if media_id and (mime_type.startswith("image/") or msg_type == "image"):
                        await send_whatsapp_text(from_number, "⏳ Foto bukti diterima, sedang menyimpan ke sistem...")
                        saved_path = await download_whatsapp_media(media_id, mime_type)
                        if saved_path == "EXCEEDED_SIZE":
                            await send_whatsapp_text(
                                from_number,
                                "⚠️ Ukuran foto melebihi batas maksimal 10 MB. Silakan kirim foto dengan ukuran lebih kecil."
                            )
                        elif saved_path:
                            user_states[from_number]["data"]["foto_bukti"] = saved_path
                            user_states[from_number]["step"] = "konfirmasi"
                            await send_confirmation_card(from_number, is_wfl=True)
                        else:
                            await send_whatsapp_text(
                                from_number,
                                "⚠️ Gagal mengunduh/menyimpan foto dari WhatsApp. Silakan coba kirim ulang foto Anda."
                            )
                    else:
                        await send_whatsapp_text(
                            from_number,
                            "⚠️ Berkas yang dikirim bukan format gambar (JPEG, PNG, WEBP, HEIC).\n"
                            "Silakan kirimkan berkas berupa *foto/gambar* bukti kehadiran Anda."
                        )

                # 3. KASUS LAIN: TIDAK SEDANG DI STEP UNGGAH BERKAS
                else:
                    await send_whatsapp_text(
                        from_number,
                        "ℹ️ Foto / dokumen hanya diterima saat proses pengajuan Surat Sakit atau Absensi Jarak Jauh.\n"
                        "Ketik *Cuti* atau *Absen Luar* untuk memulai pengajuan baru."
                    )
                continue  # Tidak perlu panggil process_whatsapp_incoming

            if from_number:
                await process_whatsapp_incoming(
                    from_number=from_number,
                    raw_text=raw_text,
                    interactive_id=interactive_id,
                    db=db,
                )

    # Selalu kembalikan 200 OK ke Meta
    return {"status": "success"}
