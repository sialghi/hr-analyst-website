"""
Script migrasi: tambah kolom whatsapp_user_id ke tabel leave_requests.
Aman dijalankan berkali-kali.
"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "hr_app.db")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(leave_requests)")
    cols = [row[1] for row in cur.fetchall()]
    if "whatsapp_user_id" not in cols:
        cur.execute("ALTER TABLE leave_requests ADD COLUMN whatsapp_user_id VARCHAR")
        print("✅ Kolom whatsapp_user_id berhasil ditambahkan")
    else:
        print("ℹ️  Kolom whatsapp_user_id sudah ada")
    conn.commit()
    conn.close()
