# -*- coding: utf-8 -*-
"""
Bot Telegram Polling Runner (Local / Development)
Gunakan script ini untuk menjalankan Bot Telegram secara lokal tanpa memerlukan domain publik / webhook!

Cara penggunaan:
1. Pastikan TELEGRAM_BOT_TOKEN dan TELEGRAM_HR_CHAT_ID sudah diisi di backend/.env
2. Jalankan perintah:
   python bot_polling.py
"""

import os
import sys
import time
import asyncio
import httpx
from dotenv import load_dotenv

# Tambahkan path backend ke sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

load_dotenv(os.path.join(backend_dir, ".env"))

from app.database import SessionLocal
from app.routers.telegram import process_telegram_update

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


async def run_polling():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN belum disetel di backend/.env!")
        print("Silakan buat bot melalui @BotFather di Telegram dan salin token ke backend/.env.")
        return

    # Hapus webhook lama agar long polling bisa menerima pesan
    del_webhook_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(del_webhook_url, json={"drop_pending_updates": False})
            print(f"🧹 Webhook reset: {r.json().get('description', 'OK')}")
        except Exception as e:
            print(f"⚠️ Peringatan saat reset webhook: {e}")

    # Ambil info bot
    me_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
    async with httpx.AsyncClient() as client:
        try:
            me_resp = await client.get(me_url)
            me_data = me_resp.json()
            if me_data.get("ok"):
                bot_user = me_data["result"]
                print(f"🤖 Bot aktif: @{bot_user.get('username')} ({bot_user.get('first_name')})")
            else:
                print(f"❌ Token bot tidak valid: {me_data}")
                return
        except Exception as e:
            print(f"❌ Gagal menghubungkan ke Telegram: {e}")
            return

    hr_chat_id = os.environ.get("TELEGRAM_HR_CHAT_ID", "").strip()
    if hr_chat_id:
        print(f"👑 HR Master Chat ID terdaftar: {hr_chat_id}")
    else:
        print("ℹ️ TELEGRAM_HR_CHAT_ID belum disetel. Untuk mengetahui Chat ID Anda, kirim pesan /start ke bot.")

    print("\n🚀 Bot polling berjalan... Menunggu pesan dari karyawan / HR Master...")
    print("Tekan Ctrl + C untuk menghentikan.\n")

    offset = 0
    poll_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"

    async with httpx.AsyncClient(timeout=35.0) as client:
        while True:
            try:
                params = {"offset": offset, "timeout": 25}
                resp = await client.get(poll_url, params=params)
                data = resp.json()

                if not data.get("ok"):
                    print(f"⚠️ getUpdates error: {data}")
                    await asyncio.sleep(3)
                    continue

                updates = data.get("result", [])
                for u in updates:
                    offset = u["update_id"] + 1

                    # Log chat info untuk mempermudah user mengetahui chat_id-nya
                    if "message" in u:
                        m = u["message"]
                        user = m.get("from", {})
                        chat = m.get("chat", {})
                        print(f"📩 Pesan dari {user.get('first_name')} (Chat ID: {chat.get('id')}): {m.get('text')}")
                    elif "callback_query" in u:
                        cb = u["callback_query"]
                        print(f"🔘 Klik tombol dari {cb.get('from', {}).get('first_name')}: {cb.get('data')}")

                    # Proses update dengan session database
                    db = SessionLocal()
                    try:
                        await process_telegram_update(u, db)
                    except Exception as err:
                        print(f"❌ Error memproses update: {err}")
                    finally:
                        db.close()

            except httpx.ReadTimeout:
                # Normal saat long-polling tidak ada pesan
                continue
            except asyncio.CancelledError:
                break
            except Exception as ex:
                print(f"⚠️ Polling loop error: {ex}")
                await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(run_polling())
    except KeyboardInterrupt:
        print("\n👋 Bot polling dihentikan.")
