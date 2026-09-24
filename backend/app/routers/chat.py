# -*- coding: utf-8 -*-
"""
chat.py
=======
Endpoint AI Chatbot untuk HR Analyst.
Menerima pertanyaan user + file_id dari hasil proses absensi,
lalu meneruskan ke Google AI Studio (Gemma 4 26B) dengan konteks
data absensi yang sudah diproses.
"""
import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import auth, models
from ..database import get_db
from ..shared_store import _file_store

# Pastikan .env selalu dimuat (database.py biasanya sudah memuatnya,
# tapi ini sebagai safety-net)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)

router = APIRouter(tags=["chat"])

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemma-4-26b-a4b-it")


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    file_id: str
    message: str
    history: list[dict[str, str]] = []  # [{role: "user"|"model", text: "..."}]


class ChatResponse(BaseModel):
    reply: str


# ---------------------------------------------------------------------------
# Helper: bangun system prompt dari result_data
# ---------------------------------------------------------------------------

def _rupiah(val: Any) -> str:
    try:
        return f"Rp {int(val):,}".replace(",", ".")
    except Exception:
        return str(val)


def _format_business_rules(rule: models.BusinessRule | None) -> str:
    if not rule:
        return "• Aturan bisnis global belum dikonfigurasi di database (menggunakan nilai default sistem)."

    return f"""- Jam Kerja Standar Global: Masuk pukul {rule.jam_masuk_standar or '08:00'}, Pulang pukul {rule.jam_keluar_standar or '16:00'}.
- Uang Makan Harian (Base): {_rupiah(rule.uang_makan_default)} per hari hadir kerja valid.
- Kebijakan Keterlambatan:
  * Toleransi Telat: Hari ke-{rule.toleransi_telat_hari_ke} keterlambatan dalam periode diberikan toleransi maksimal {rule.toleransi_telat_max_menit} menit (tidak ada potongan jika keterlambatan <= toleransi).
  * Kategori Telat Ringan (Masuk sebelum pukul {rule.batas_telat_ringan}): Dikenakan potongan flat sebesar {_rupiah(rule.potongan_telat_sedikit)} dari uang makan.
  * Kategori Telat Berat (Masuk setelah pukul {rule.batas_telat_berat}): Dikenakan potongan sebesar {int(rule.potongan_telat_banyak_persen * 100)}% dari uang makan hari tersebut.
- Kebijakan Pulang Duluan / Cepat:
  * Pulang Ringan (Pulang sebelum pukul {rule.batas_pulang_duluan_ringan}): Dikenakan potongan flat sebesar {_rupiah(rule.potongan_pulang_duluan_sedikit)}.
  * Pulang Berat (Pulang sebelum pukul {rule.batas_pulang_duluan_berat}): Dikenakan potongan sebesar {int(rule.potongan_pulang_duluan_banyak_persen * 100)}% dari uang makan hari tersebut.
- Kebijakan Perhitungan Lembur:
  * Tarif Lembur Standar: {_rupiah(rule.bonus_lembur_per_jam)} per jam bulat.
  * Logika Pembulatan Menit Lembur: Ambang batas pembulatan adalah menit ke-{rule.menit_pembulatan_lembur}.
    - Jika kelebihan menit >= {rule.menit_pembulatan_lembur} menit, dibulatkan ke atas menjadi 1 jam tambahan (contoh: 1 jam 35 menit -> dihitung 2 jam).
    - Jika kelebihan menit < {rule.menit_pembulatan_lembur} menit, sisa menit diabaikan/hangus (contoh: 1 jam 20 menit -> tetap dihitung 1 jam).
- Kuota Kehadiran & Alpa:
  * Minimal hari kerja normal: {rule.min_hari_kerja_per_minggu} hari per minggu.
  * Alpa Berulang: Terdeteksi jika karyawan tidak masuk {rule.min_minggu_berturut_alpa} minggu berturut-turut."""


def _format_profiles(profiles: list[models.Profile]) -> str:
    if not profiles:
        return "• Belum ada profil jadwal yang terdaftar."

    lines = []
    for p in profiles:
        cb_str = ", ".join(p.cabang) if p.cabang else "Semua Cabang / Fleksibel"
        hk_str = ", ".join(p.hari_kerja) if p.hari_kerja else "Senin s/d Jumat"

        # Jam masuk & keluar
        jm = p.jam_masuk or {}
        jk = p.jam_keluar or {}
        jm_str = jm.get("default", "08:00") if isinstance(jm, dict) else str(jm or "08:00")
        jk_str = jk.get("default", "16:00") if isinstance(jk, dict) else str(jk or "16:00")
        if isinstance(jk, dict) and "Sabtu" in jk:
            jk_str += f" (Khusus Sabtu: {jk.get('Sabtu')})"

        lk_str = ""
        if p.lembur_khusus and isinstance(p.lembur_khusus, dict):
            lk = p.lembur_khusus
            hari_lk = ", ".join(lk.get("hanya_hari", []))
            lk_str = (
                f"\n     * Aturan Lembur Khusus: Berlaku hari [{hari_lk}], minimal {lk.get('threshold_jam', 0)} jam, "
                f"tarif {_rupiah(lk.get('tarif_per_jam', 0))}/jam, bonus flat {_rupiah(lk.get('bonus_flat', 0))}."
            )

        lines.append(
            f"• Profil [{p.code}] - {p.nama}:\n"
            f"   - Cabang yang Berlaku: {cb_str}\n"
            f"   - Hari Kerja: {hk_str}\n"
            f"   - Jam Kerja Standar: Masuk {jm_str} | Keluar/Pulang {jk_str}\n"
            f"   - Aturan Berpartisipasi: Kena Potongan Telat={'Ya' if p.ikut_telat else 'Tidak'}, "
            f"Dapat Lembur={'Ya' if p.ikut_lembur else 'Tidak'}, "
            f"Bonus Tanggal Merah={'Ya' if p.ikut_bonus_tanggal_merah else 'Tidak'}{lk_str}"
        )
    return "\n".join(lines)


def _format_holidays(holidays: list[models.Holiday]) -> str:
    if not holidays:
        return "• Tidak ada tanggal merah nasional khusus yang terdaftar."
    return "\n".join([f"• {h.tanggal} : {h.keterangan or 'Hari Libur Nasional'}" for h in holidays[:20]])


def _build_system_prompt(
    result_data: dict,
    rules_text: str,
    profiles_text: str,
    holidays_text: str,
) -> str:
    kpis = result_data.get("kpis", {}) if result_data else {}
    sheets = {s["key"]: s for s in result_data.get("sheets", [])} if result_data else {}

    # --- KPI Global ---
    if kpis:
        kpi_lines = [
            f"- Total karyawan diproses: {kpis.get('total_karyawan', 0)}",
            f"- Total kejadian telat: {kpis.get('total_telat', 0)}",
            f"- Total jam lembur (bulat): {kpis.get('total_lembur', 0)} jam",
            f"- Total bonus lembur: {_rupiah(kpis.get('total_bonus_lembur', 0))}",
            f"- Total uang makan (akhir): {_rupiah(kpis.get('total_uang_makan', 0))}",
            f"- Total kejadian pulang duluan: {kpis.get('total_pulang_duluan', 0)}",
            f"- Jumlah nama perlu dicek (tidak ada di master): {kpis.get('jml_perlu_dicek', 0)}",
        ]
        kpi_section = "\n".join(kpi_lines)
    else:
        kpi_section = "(Belum ada data file absensi yang dimuat. Jawab berdasarkan aturan dan profil perusahaan di atas.)"

    # --- Summary Overview (ringkasan per karyawan) ---
    summary_sheet = sheets.get("summary", {})
    summary_rows = summary_sheet.get("data", {}).get("rows", [])

    emp_lines = []
    for row in summary_rows:
        nama = row.get("Nama", "?")
        cabang = row.get("Cabang", "?")
        profil = row.get("Profil", "STANDAR")
        telat = row.get("Jml Telat", 0)
        lembur_jam = row.get("Jam Lembur (Bulat)", 0)
        bonus_lembur = row.get("Total Bonus Lembur (Rp)", 0)
        pd = row.get("Jml Pulang Duluan", 0)
        tidak_masuk = row.get("Jumlah Hari Tidak Masuk", 0)
        uang_makan = row.get("Total Uang Makan Akhir (Rp)", 0)
        hari_kerja = row.get("Hari Kerja Valid", 0)
        emp_lines.append(
            f"  • {nama} [{cabang}, profil: {profil}]: "
            f"hari kerja={hari_kerja}, telat={telat}x, lembur={lembur_jam}jam ({_rupiah(bonus_lembur)}), "
            f"pulang duluan={pd}x, tidak masuk={tidak_masuk}hari, "
            f"uang makan akhir={_rupiah(uang_makan)}"
        )

    emp_section = "\n".join(emp_lines) if emp_lines else "(Tidak ada data karyawan dalam sesi ini)"

    prompt = f"""Kamu adalah HR Analyst AI Asisten Ahli untuk PT. Javareef Indonesia Perkasa.
Tugas utamamu adalah membantu staf HR dan manajemen untuk menganalisis absensi, menjawab pertanyaan tentang hasil kalkulasi (mengapa angka lembur/telat/uang makan didapatkan sekian), serta menjelaskan aturan jam kerja untuk setiap cabang dan divisi/profil.

=======================================================
1. ATURAN BISNIS PERUSAHAAN (LOGIKA PERHITUNGAN RESMI)
=======================================================
{rules_text}

=======================================================
2. PROFIL JADWAL KERJA & CABANG / DIVISI PERUSAHAAN
=======================================================
{profiles_text}

=======================================================
3. DAFTAR TANGGAL MERAH / HARI LIBUR NASIONAL
=======================================================
{holidays_text}

=======================================================
4. HASIL PEMROSESAN ABSENSI PERIODE INI
=======================================================
--- KPI Global ---
{kpi_section}

--- Ringkasan Karyawan ---
{emp_section}

=======================================================
PANDUAN MENJAWAB PERTANYAAN & ESTETIKA FORMAT (SANGAT PENTING):
=======================================================
1. Logika & Analisis Mendalam:
   - Ketika user bertanya "KENAPA" atau "MENGAPA" seorang karyawan mendapatkan nilai tertentu (misal: kenapa hari kerja valid sekian, kenapa lembur sekian, kenapa uang makan dipotong):
     * Jelaskan kronologi dan alasannya secara runut.
     * Contoh Kasus Absensi/Hari Valid: Jelaskan konsep pasangan absensi (Clock-In dan Clock-Out). Jika ada selisih catatan (misal 23 scan untuk 22 hari kerja valid), jelaskan bahwa 1 scan tidak memiliki pasangan (hanya masuk atau hanya pulang), sehingga tidak terhitung sebagai 1 hari kerja penuh.
     * Tunjukkan kalkulasi matematisnya secara transparan dan mudah dimengerti.
2. Estetika Penulisan & Kerapian Format:
   - HINDARI PENGGUNAAN TANDA BINTANG GANDA BERTUMPUK (JANGAN gunakan **** atau asteris bertumpuk yang membuat teks kotor dan sulit dibaca).
   - Gunakan format bold (**kata**) HANYA untuk penegasan kata kunci penting, nominal rupiah, atau nama orang.
   - Gunakan judul bagian terstruktur dengan '### 1. Judul Bagian', '### 2. Judul Bagian', dst.
   - Gunakan penomoran bertingkat: angka (1, 2, 3), huruf (a, b, c), atau butir poin (-) yang rapi untuk memisahkan setiap poin.
   - Berikan pemisah antar bagian dengan garis horizontal (---) dan jeda baris yang cukup antar paragraf.
3. Gaya Bahasa:
   - Gunakan Bahasa Indonesia yang sangat sopan, profesional, jelas, dan percaya diri.
   - Di bagian akhir, berikan kesimpulan ringkas yang siap disampaikan langsung ke karyawan, serta saran tindak lanjut untuk staf HR.

"""
    return prompt.strip()


def _get_employee_detail(result_data: dict, nama_cari: str, db: Session | None = None) -> str:
    """Ambil detail rekap individu jika nama karyawan disebut dalam pertanyaan."""
    sheets = {s["key"]: s for s in result_data.get("sheets", [])} if result_data else {}
    nama_lower = nama_cari.lower()

    def filter_rows(key: str) -> list[dict]:
        sheet = sheets.get(key, {})
        rows = sheet.get("data", {}).get("rows", [])
        return [r for r in rows if nama_lower in str(r.get("Nama", "")).lower()]

    detail_parts = []

    # Cek info master di database jika ada
    if db:
        try:
            emp = db.query(models.Employee).filter(models.Employee.nama.ilike(f"%{nama_cari}%")).first()
            if emp:
                um_info = _rupiah(emp.uang_makan_override) if emp.uang_makan_override else "Mengikuti Aturan Global"
                detail_parts.append(
                    f"Master Karyawan: Nama={emp.nama}, Cabang={emp.cabang or 'Standar'}, "
                    f"Profil Jadwal={emp.profile_code}, Uang Makan Base={um_info}"
                )

            # Cek riwayat cuti/izin resmi di database
            leaves = (
                db.query(models.LeaveRequest)
                .filter(models.LeaveRequest.nama.ilike(f"%{nama_cari}%"))
                .order_by(models.LeaveRequest.tanggal_mulai.desc())
                .all()
            )
            if leaves:
                detail_parts.append(f"Riwayat Cuti/Izin Resmi Tercatat ({len(leaves)} pengajuan):")
                for lv in leaves[:5]:
                    jam_info = f" (Pukul {lv.jam_izin})" if lv.jam_izin else ""
                    detail_parts.append(
                        f"  - [{lv.status}] {lv.kategori}: {lv.tanggal_mulai} s/d {lv.tanggal_selesai}{jam_info} "
                        f"- Alasan: {lv.alasan or '-'} (Disetujui: {lv.approved_by or '-'})"
                    )
        except Exception:
            pass

    telat_rows = filter_rows("telat")

    if telat_rows:
        detail_parts.append(f"Detail Kejadian Telat ({len(telat_rows)} kali):")
        for r in telat_rows[:10]:
            detail_parts.append(
                f"  - {r.get('Tanggal','')} {r.get('Hari','')}: "
                f"masuk {r.get('Jam Masuk','?')} (standar {r.get('Jam Standar','?')}), "
                f"durasi telat {r.get('Durasi Telat','?')}, potongan {_rupiah(r.get('Potongan (Rp)', 0))}"
            )

    lembur_rows = filter_rows("lembur")
    if lembur_rows:
        detail_parts.append(f"Detail Kejadian Lembur ({len(lembur_rows)} kali):")
        for r in lembur_rows[:10]:
            detail_parts.append(
                f"  - {r.get('Tanggal','')} {r.get('Hari','')}: "
                f"keluar {r.get('Jam Keluar','?')}, durasi lembur {r.get('Durasi Lembur','?')}, "
                f"jam bulat {r.get('Jam Lembur (Bulat)', '?')} jam, bonus {_rupiah(r.get('Bonus Lembur (Rp)', 0))}"
            )

    pd_rows = filter_rows("pulang_duluan")
    if pd_rows:
        detail_parts.append(f"Detail Pulang Duluan ({len(pd_rows)} kali):")
        for r in pd_rows[:10]:
            detail_parts.append(
                f"  - {r.get('Tanggal','')} {r.get('Hari','')}: "
                f"keluar {r.get('Jam Keluar','?')} (standar {r.get('Jam Standar','?')}), "
                f"durasi {r.get('Durasi Pulang Duluan','?')}, potongan {_rupiah(r.get('Potongan (Rp)', 0))}"
            )

    um_rows = filter_rows("uang_makan")
    if um_rows:
        total_um = sum(r.get("Total Uang Makan (Rp)", 0) or 0 for r in um_rows)
        detail_parts.append(f"Rincian Uang Makan Harian ({len(um_rows)} hari hadir, total diterima {_rupiah(total_um)}):")
        for r in um_rows[:8]:
            detail_parts.append(
                f"  - {r.get('Tanggal','')} {r.get('Hari','')}: "
                f"base {_rupiah(r.get('Uang Makan (Rp)', 0))}, "
                f"pot. telat {_rupiah(r.get('Potongan Telat (Rp)', 0))}, "
                f"pot. pd {_rupiah(r.get('Potongan Pulang Duluan (Rp)', 0))}, "
                f"total bersih {_rupiah(r.get('Total Uang Makan (Rp)', 0))}"
            )
        if len(um_rows) > 8:
            detail_parts.append(f"  ... (dan {len(um_rows) - 8} hari lainnya)")

    tm_rows = filter_rows("tidak_masuk")
    if tm_rows:
        detail_parts.append(f"Rekap Hari Tidak Masuk / Alpa:")
        for r in tm_rows[:5]:
            detail_parts.append(
                f"  - Minggu {r.get('Minggu','?')}: "
                f"{r.get('Jml Hari Tidak Masuk', 0)} hari tidak masuk "
                f"({r.get('Hari yang Tidak Masuk', '-')})"
            )

    return "\n".join(detail_parts) if detail_parts else ""


# ---------------------------------------------------------------------------
# Helper: deteksi nama karyawan dari pesan user
# ---------------------------------------------------------------------------

def _detect_employee_name(message: str, result_data: dict, db: Session | None = None) -> str | None:
    """Cek apakah pesan menyebut nama karyawan yang ada di data atau di database."""
    sheets = {s["key"]: s for s in result_data.get("sheets", [])} if result_data else {}
    summary_rows = sheets.get("summary", {}).get("data", {}).get("rows", [])
    msg_lower = message.lower()

    # Cek dari hasil pemrosesan dulu
    for row in summary_rows:
        nama = str(row.get("Nama", ""))
        if nama and len(nama) >= 3 and nama.lower() in msg_lower:
            return nama

    # Cek dari master karyawan database
    if db:
        try:
            employees = db.query(models.Employee.nama).all()
            for (emp_nama,) in employees:
                if emp_nama and len(emp_nama) >= 3 and emp_nama.lower() in msg_lower:
                    return emp_nama
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(
    body: ChatRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    """
    Kirim pertanyaan ke AI chatbot.
    Mendukung pertanyaan seputar hasil proses absensi (jika file_id disertakan),
    maupun aturan bisnis, profil cabang, jam kerja, dan kebijakan perusahaan.
    """
    # Pastikan file .env selalu termuat ulang di runtime
    load_dotenv(dotenv_path=_env_path, override=True)
    api_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if not api_key or api_key in ("masukkan-api-key-anda-di-sini", ""):
        raise HTTPException(
            status_code=503,
            detail="AI chatbot belum dikonfigurasi. Pastikan GOOGLE_AI_API_KEY sudah di-set di .env backend.",
        )

    model_name = os.environ.get("GEMINI_MODEL", "gemma-4-26b-a4b-it")
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    # Ambil data hasil pemrosesan jika file_id ada
    entry = _file_store.get(body.file_id) if body.file_id else None
    result_data = entry.get("result_data", {}) if entry else {}

    # Ambil aturan bisnis, profil cabang, dan libur nasional langsung dari database
    try:
        rule = db.query(models.BusinessRule).first()
        profiles = db.query(models.Profile).all()
        holidays = db.query(models.Holiday).order_by(models.Holiday.tanggal).all()
    except Exception:
        rule = None
        profiles = []
        holidays = []

    rules_text = _format_business_rules(rule)
    profiles_text = _format_profiles(profiles)
    holidays_text = _format_holidays(holidays)

    # Bangun system prompt komprehensif
    system_prompt = _build_system_prompt(
        result_data=result_data,
        rules_text=rules_text,
        profiles_text=profiles_text,
        holidays_text=holidays_text,
    )

    # Jika ada nama karyawan disebut, tambahkan detail individu
    nama_emp = _detect_employee_name(body.message, result_data, db=db)
    extra_context = ""
    if nama_emp:
        detail = _get_employee_detail(result_data, nama_emp, db=db)
        if detail:
            extra_context = f"\n\n=== REKAP RINCIAN DETAIL KARYAWAN: {nama_emp.upper()} ===\n{detail}"

    full_system = system_prompt + extra_context


    # Bangun conversation: history + pesan baru
    contents = []

    # Tambahkan histori percakapan sebelumnya (maks 10 pasang agar tidak terlalu panjang)
    for turn in body.history[-20:]:
        role = turn.get("role", "user")
        text = turn.get("text", "")
        if role in ("user", "model") and text:
            contents.append({"role": role, "parts": [{"text": text}]})

    # Tambahkan pesan user saat ini
    contents.append({"role": "user", "parts": [{"text": body.message}]})

    payload = {
        "system_instruction": {"parts": [{"text": full_system}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 1024,
            "topP": 0.9,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                gemini_url,
                params={"key": api_key},
                json=payload,
            )

        if resp.status_code != 200:
            error_body = resp.text[:500]
            raise HTTPException(
                status_code=502,
                detail=f"Google AI API error {resp.status_code}: {error_body}",
            )

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise HTTPException(status_code=502, detail="AI tidak memberikan respons. Coba ulangi pertanyaan.")

        parts = candidates[0].get("content", {}).get("parts", [])
        # Gemma 4/Gemini models can have reasoning/thought parts (thought: True).
        # We only want the actual answer text (where thought is False or not present).
        text_parts = [p.get("text", "") for p in parts if not p.get("thought", False)]
        if text_parts:
            reply_text = "".join(text_parts).strip()
        elif parts:
            # Fallback if all parts marked as thought
            reply_text = parts[-1].get("text", "Maaf, tidak ada respons dari AI.").strip()
        else:
            reply_text = "Maaf, tidak ada respons dari AI."

        return ChatResponse(reply=reply_text)

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Permintaan ke AI timeout. Coba lagi.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan: {e}")
