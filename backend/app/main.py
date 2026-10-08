# -*- coding: utf-8 -*-
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import Base, engine, SessionLocal
from .routers import auth, profiles, rules, employees, holidays, process, chat, leaves, whatsapp

# Keep SQLite developer/test setup compatible; PostgreSQL schema changes run via Alembic.
if engine.dialect.name == "sqlite":
    Base.metadata.create_all(bind=engine)

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
