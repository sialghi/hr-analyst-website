# -*- coding: utf-8 -*-
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import Base, engine, SessionLocal
from .routers import auth, profiles, rules, employees, holidays, process, chat, leaves, whatsapp

# Buat semua tabel kalau belum ada (untuk production sebaiknya pakai Alembic migration,
# tapi create_all() ini cukup aman & simpel untuk skala project ini).
Base.metadata.create_all(bind=engine)


def _run_migrations():
    """Migrasi otomatis untuk memastikan SEMUA kolom dari Base.metadata ada di database."""
    from sqlalchemy import inspect, text
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

        with engine.begin() as conn:
            for table_name, table in Base.metadata.tables.items():
                if table_name in existing_tables:
                    existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
                    for col in table.columns:
                        if col.name not in existing_cols:
                            col_type = col.type.compile(engine.dialect)
                            default_clause = ""
                            if col.default is not None and hasattr(col.default, "arg"):
                                val = col.default.arg
                                if isinstance(val, (int, float)):
                                    default_clause = f" DEFAULT {val}"
                                elif isinstance(val, bool):
                                    default_clause = f" DEFAULT {str(val).lower()}"
                                elif isinstance(val, str):
                                    default_clause = f" DEFAULT '{val}'"
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause}"
                            print(f"[MIGRATION] Adding column: {sql}")
                            try:
                                conn.execute(text(sql))
                            except Exception as col_err:
                                print(f"[MIGRATION ERROR on {col.name}]: {col_err}")
            if "employees" in existing_tables:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_employees_employee_code "
                    "ON employees (employee_code)"
                ))
            if "leave_requests" in existing_tables:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_leave_requests_import_key "
                    "ON leave_requests (import_key)"
                ))
    except Exception as e:
        print(f"[MIGRATION WARN] {e}")


_run_migrations()

# Backfill pemakaian cuti approved yang sudah ada sebelum ledger diaktifkan.
from .leave_logic import reconcile_approved_leave_ledger
with SessionLocal() as _startup_db:
    _reconciled = reconcile_approved_leave_ledger(_startup_db)
    if _reconciled:
        print(f"[LEAVE LEDGER] Reconciled {_reconciled} approved leave requests.")

app = FastAPI(title="HR Absensi Pipeline - Web API")

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "").strip()
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
if FRONTEND_ORIGIN and FRONTEND_ORIGIN != "*":
    for orig in FRONTEND_ORIGIN.split(","):
        cleaned = orig.strip().rstrip("/")
        if cleaned and cleaned not in origins:
            origins.append(cleaned)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if FRONTEND_ORIGIN != "*" else ["*"],
    allow_origin_regex=r"https?://.*" if FRONTEND_ORIGIN == "*" else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health_check():
    return {"status": "ok"}


@app.get("/health")
def health_status():
    return {"status": "ok"}


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
