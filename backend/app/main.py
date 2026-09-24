# -*- coding: utf-8 -*-
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import auth, profiles, rules, employees, holidays, process, chat, leaves, telegram

# Buat semua tabel kalau belum ada (untuk production sebaiknya pakai Alembic migration,
# tapi create_all() ini cukup aman & simpel untuk skala project ini).
Base.metadata.create_all(bind=engine)

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
app.include_router(telegram.router)

