"""
Script Migrasi Database: Tambah kolom employment_status, join_date pada tabel employees
dan buat tabel employment_contracts.
Aman dijalankan berkali-kali.
"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "hr_app.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# 1. Cek & Tambah kolom pada tabel employees
cur.execute("PRAGMA table_info(employees)")
cols = [row[1] for row in cur.fetchall()]
print("Kolom employees saat ini:", cols)

if "employment_status" not in cols:
    cur.execute("ALTER TABLE employees ADD COLUMN employment_status VARCHAR DEFAULT 'TETAP'")
    print("[OK] Kolom employment_status berhasil ditambahkan (default: TETAP)")
else:
    print("[INFO] Kolom employment_status sudah ada")

if "join_date" not in cols:
    cur.execute("ALTER TABLE employees ADD COLUMN join_date DATE")
    print("[OK] Kolom join_date berhasil ditambahkan")
else:
    print("[INFO] Kolom join_date sudah ada")

# 2. Buat tabel employment_contracts jika belum ada
cur.execute("""
CREATE TABLE IF NOT EXISTS employment_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    contract_number INTEGER NOT NULL DEFAULT 1,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'ACTIVE',
    keterangan TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
);
""")
print("[OK] Tabel employment_contracts berhasil disiapkan")

# 3. Index untuk pencarian cepat
cur.execute("CREATE INDEX IF NOT EXISTS ix_employment_contracts_employee_id ON employment_contracts(employee_id);")

conn.commit()
conn.close()
print("\n[SUCCESS] Migrasi data kontrak karyawan selesai!")
