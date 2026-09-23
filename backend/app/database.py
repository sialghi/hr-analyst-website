# -*- coding: utf-8 -*-
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Di production (Railway/Supabase) set DATABASE_URL ke connection string Postgres.
# Kalau tidak di-set atau masih contoh placeholder (user:password@host), fallback ke SQLite lokal.
raw_db_url = os.environ.get("DATABASE_URL", "").strip()
if not raw_db_url or "user:password@host" in raw_db_url:
    db_file = (Path(__file__).resolve().parent.parent / "hr_app.db").as_posix()
    DATABASE_URL = f"sqlite:///{db_file}"
else:
    DATABASE_URL = raw_db_url

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
