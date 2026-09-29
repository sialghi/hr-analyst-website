"""
Script migrasi: tambah kolom tipe_absensi dan location_cabang ke tabel leave_requests.
Aman dijalankan berkali-kali (cek dulu sebelum ALTER).
"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "hr_app.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("PRAGMA table_info(leave_requests)")
cols = [row[1] for row in cur.fetchall()]
print("Kolom saat ini:", cols)

if "tipe_absensi" not in cols:
    cur.execute("ALTER TABLE leave_requests ADD COLUMN tipe_absensi VARCHAR DEFAULT 'normal'")
    print("✅ Kolom tipe_absensi berhasil ditambahkan")
else:
    print("ℹ️  tipe_absensi sudah ada, dilewati")

if "location_cabang" not in cols:
    cur.execute("ALTER TABLE leave_requests ADD COLUMN location_cabang VARCHAR")
    print("✅ Kolom location_cabang berhasil ditambahkan")
else:
    print("ℹ️  location_cabang sudah ada, dilewati")

conn.commit()
conn.close()
print("\nMigrasi selesai. Restart backend sekarang.")
