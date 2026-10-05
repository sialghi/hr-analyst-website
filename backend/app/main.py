# -*- coding: utf-8 -*-
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import auth, profiles, rules, employees, holidays, process, chat, leaves, whatsapp

# Buat semua tabel kalau belum ada (untuk production sebaiknya pakai Alembic migration,
# tapi create_all() ini cukup aman & simpel untuk skala project ini).
Base.metadata.create_all(bind=engine)


def _run_migrations():
    """Migrasi otomatis untuk memastikan kolom-kolom baru ditambahkan ke tabel yang sudah ada."""
    from sqlalchemy import inspect, text
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        with engine.begin() as conn:
            if "leave_requests" in tables:
                cols = {c["name"] for c in inspector.get_columns("leave_requests")}
                new_cols = {
                    "whatsapp_user_id": "VARCHAR",
                    "telegram_user_id": "VARCHAR",
                    "tipe_absensi": "VARCHAR DEFAULT 'normal'",
                    "location_cabang": "VARCHAR",
                    "foto_bukti": "VARCHAR",
                    "jam_izin": "VARCHAR",
                    "catatan_hr": "VARCHAR",
                    "approved_by": "VARCHAR",
                    "approved_at": "TIMESTAMP",
                }
                for col_name, col_type in new_cols.items():
                    if col_name not in cols:
                        conn.execute(text(f"ALTER TABLE leave_requests ADD COLUMN {col_name} {col_type}"))

            if "employees" in tables:
                cols_emp = {c["name"] for c in inspector.get_columns("employees")}
                new_emp_cols = {
                    "tanggal_masuk": "DATE",
                    "jenis_kontrak": "VARCHAR DEFAULT 'PKWT'",
                    "durasi_kontrak_bulan": "INTEGER DEFAULT 12",
                    "tanggal_berakhir_kontrak": "DATE",
                    "reminder_sent_at": "TIMESTAMP",
                }
                for col_name, col_type in new_emp_cols.items():
                    if col_name not in cols_emp:
                        conn.execute(text(f"ALTER TABLE employees ADD COLUMN {col_name} {col_type}"))
    except Exception as e:
        print(f"[MIGRATION WARN] {e}")


_run_migrations()

app = FastAPI(title="HR Absensi Pipeline - Web API")

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*").strip()
origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
if FRONTEND_ORIGIN and FRONTEND_ORIGIN != "*" and "nama-app-anda" not in FRONTEND_ORIGIN:
    origins.append(FRONTEND_ORIGIN)
elif FRONTEND_ORIGIN == "*":
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(profiles.router)
app.include_router(rules.router)
app.include_router(employees.router)
app.include_router(holidays.router)
app.include_router(leaves.router)
app.include_router(process.router)
app.include_router(chat.router)
app.include_router(whatsapp.router)

# Serve uploaded foto bukti absensi jarak jauh via /uploads/...
_uploads_dir = Path(__file__).resolve().parent.parent / "uploads"
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")


@app.on_event("startup")
async def startup_event():
    import asyncio
    from .scheduler import start_daily_contract_scheduler
    asyncio.create_task(start_daily_contract_scheduler())

