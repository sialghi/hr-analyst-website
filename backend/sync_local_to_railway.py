# -*- coding: utf-8 -*-
"""
Script Migrasi Database Local (SQLite) -> Railway (PostgreSQL)

Fitur:
- Membaca semua data dari hr_app.db lokal (SQLite).
- Menghubungkan ke PostgreSQL di Railway via Public Connection URL.
- Membuat tabel otomatis di PostgreSQL jika belum ada.
- Memindahkan data tabel berurutan sesuai relasi Foreign Key:
  profiles -> users -> business_rule -> holidays -> employees ->
  employment_contracts -> leave_requests -> employee_adjustments ->
  absen_manual -> leave_balance_ledger.
- Memperbarui PostgreSQL sequence (setval) agar ID auto-increment tidak konflik saat ada penambahan data baru di web.
- Data SQLite lokal tetap aman & tidak diubah sama sekali.

Penggunaan:
  .\\venv\\Scripts\\python.exe sync_local_to_railway.py --railway-url "postgresql://postgres:pass@roundhouse.proxy.rlwy.net:12345/railway"
"""

import sys
import os
import argparse
from pathlib import Path
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

# Tambahkan backend directory ke sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import Base
from app.models import (
    User, Profile, BusinessRule, Holiday, Employee,
    EmploymentContract, LeaveRequest, EmployeeAdjustment,
    AbsenManual, LeaveBalanceLedger,
)

# Urutan migrasi berdasarkan relasi foreign key
TABLE_MODELS = [
    ("profiles", Profile),
    ("users", User),
    ("business_rule", BusinessRule),
    ("holidays", Holiday),
    ("employees", Employee),
    ("employment_contracts", EmploymentContract),
    ("leave_requests", LeaveRequest),
    ("employee_adjustments", EmployeeAdjustment),
    ("absen_manual", AbsenManual),
    ("leave_balance_ledger", LeaveBalanceLedger),
]


def clean_postgres_url(raw_url: str) -> str:
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def main():
    parser = argparse.ArgumentParser(
        description="Migrasikan seluruh data dari database SQLite lokal ke PostgreSQL Railway."
    )
    parser.add_argument(
        "--railway-url", "-u",
        help="Public Connection URL PostgreSQL Railway (contoh: postgresql://postgres:pass@host:port/railway)",
        default=os.environ.get("RAILWAY_DATABASE_URL", "")
    )
    parser.add_argument(
        "--sqlite-file", "-s",
        help="Path file SQLite lokal (default: hr_app.db)",
        default=str(backend_dir / "hr_app.db")
    )
    parser.add_argument(
        "--truncate", "-t",
        action="store_true",
        help="Kosongkan data tabel di Railway terlebih dahulu sebelum copy (disarankan jika ingin replace penuh)"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Jalankan tanpa konfirmasi interaktif"
    )

    args = parser.parse_args()

    railway_url_input = args.railway_url
    if not railway_url_input:
        print("\n=== MIGRASI DATABASE LOKAL KE RAILWAY ===")
        print("Koneksi URL Railway belum diberikan.")
        print("Silakan buka Dashboard Railway -> Service PostgreSQL -> Tab 'Connect' -> Salin 'Public Networking' / 'TCP Proxy' Connection URL.")
        try:
            railway_url_input = input("\nMasukkan Railway Database URL: ").strip()
        except EOFError:
            railway_url_input = ""

    if not railway_url_input:
        print("[ERROR] URL database Railway wajib diisi.")
        sys.exit(1)

    sqlite_path = Path(args.sqlite_file).resolve()
    if not sqlite_path.exists():
        print(f"[ERROR] File SQLite lokal tidak ditemukan di: {sqlite_path}")
        sys.exit(1)

    target_url = clean_postgres_url(railway_url_input)
    source_url = f"sqlite:///{sqlite_path.as_posix()}"

    print("\n------------------------------------------------------------")
    print(f"Sumber (Lokal SQLite) : {sqlite_path}")
    # Sembunyikan password di log untuk keamanan
    display_target = target_url.split("@")[-1] if "@" in target_url else target_url
    print(f"Target (Railway PG)   : ...@{display_target}")
    print("------------------------------------------------------------\n")

    # Inisialisasi engine
    source_engine = create_engine(source_url, connect_args={"check_same_thread": False})
    SourceSession = sessionmaker(bind=source_engine)
    src_db = SourceSession()

    try:
        target_engine = create_engine(target_url, pool_pre_ping=True)
        # Test koneksi ke target
        with target_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[✓] Berhasil terhubung ke PostgreSQL Railway!")
    except Exception as e:
        print(f"[ERROR] Gagal terhubung ke PostgreSQL Railway: {e}")
        print("\nTips:")
        print("1. Pastikan Anda menyalin Public URL (bukan private internal .railway.internal).")
        print("2. Pada Railway, buka service Postgres -> Settings -> Networking -> Aktifkan 'Public Networking' / 'TCP Proxy'.")
        sys.exit(1)

    TargetSession = sessionmaker(bind=target_engine)
    tgt_db = TargetSession()

    # Hitung jumlah baris di SQLite
    print("\nMenghitung data di SQLite lokal:")
    counts = {}
    total_rows = 0
    for tbl_name, model_cls in TABLE_MODELS:
        cnt = src_db.query(model_cls).count()
        counts[tbl_name] = cnt
        total_rows += cnt
        print(f"  - {tbl_name:24}: {cnt:,} baris")

    print(f"\nTotal data yang akan dimigrasikan: {total_rows:,} baris.")

    if not args.yes:
        confirm = input("\nLanjutkan proses pemindahan data ke Railway? (y/N): ").strip().lower()
        if confirm != "y":
            print("Operasi dibatalkan.")
            sys.exit(0)

    # 1. Pastikan skema tabel sudah ada di PostgreSQL
    print("\n[1/3] Membuat/memverifikasi tabel di PostgreSQL Railway...")
    Base.metadata.create_all(bind=target_engine)
    print("  [✓] Skema tabel siap.")

    # 2. Opsional truncate jika diminta
    if args.truncate:
        print("\n[2/3] Mengosongkan data lama di Railway (Truncate cascade)...")
        with target_engine.connect() as conn:
            for tbl_name, _ in reversed(TABLE_MODELS):
                try:
                    conn.execute(text(f"TRUNCATE TABLE {tbl_name} RESTART IDENTITY CASCADE;"))
                    conn.commit()
                except Exception as e:
                    print(f"  [!] Truncate {tbl_name}: {e}")
        print("  [✓] Data lama di Railway telah dikosongkan.")
    else:
        print("\n[2/3] Menyiapkan migrasi data (mode replace/insert)...")

    # 3. Salin data per tabel
    print("\n[3/3] Menyalin data per tabel...")
    inspector = inspect(source_engine)

    for tbl_name, model_cls in TABLE_MODELS:
        cnt = counts[tbl_name]
        if cnt == 0:
            print(f"  - {tbl_name:24}: 0 baris (dilewati)")
            continue

        print(f"  - {tbl_name:24}: Menyalin {cnt:,} baris...", end=" ", flush=True)

        # Ambil kolom model
        col_names = [c.name for c in model_cls.__table__.columns]

        # Ambil semua data dari SQLite
        records = src_db.query(model_cls).all()

        # Jika tidak truncate, hapus tabel target dulu agar bersih dan tidak duplicate primary key
        with target_engine.connect() as conn:
            conn.execute(text(f"DELETE FROM {tbl_name};"))
            conn.commit()

        # Batch insert ke target
        batch_data = []
        for rec in records:
            row_dict = {}
            for col in col_names:
                row_dict[col] = getattr(rec, col)
            batch_data.append(row_dict)

        if batch_data:
            # Gunakan bulk insert via table insert statement
            table = model_cls.__table__
            with target_engine.connect() as conn:
                conn.execute(table.insert(), batch_data)
                conn.commit()

        print("SELESAI ✓")

    # 4. Sinkronisasi PostgreSQL sequence (ID auto-increment)
    print("\nMenyelaraskan sequence autoincrement ID di PostgreSQL...")
    with target_engine.connect() as conn:
        for tbl_name, model_cls in TABLE_MODELS:
            has_id = "id" in [c.name for c in model_cls.__table__.columns]
            if has_id and counts[tbl_name] > 0:
                try:
                    seq_query = text(f"""
                        SELECT setval(
                            pg_get_serial_sequence('{tbl_name}', 'id'),
                            COALESCE((SELECT MAX(id) FROM {tbl_name}), 1)
                        );
                    """)
                    conn.execute(seq_query)
                    conn.commit()
                except Exception as ex:
                    # Abaikan jika tabel tidak memakai serial sequence
                    pass

    print("\n============================================================")
    print("MIGRASI SELESAI DENGAN SUKSES! ✓")
    print("Seluruh data dari SQLite lokal telah berpindah ke PostgreSQL Railway.")
    print("Database lokal Anda (hr_app.db) tetap aman dan tidak berubah.")
    print("============================================================\n")

    src_db.close()
    tgt_db.close()


if __name__ == "__main__":
    main()
