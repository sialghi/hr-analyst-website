"""Safely replace PostgreSQL application data with a SQLite snapshot."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, create_engine, delete, func, inspect, select, text
from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = BACKEND_DIR / "hr_app.db"
ALLOWED_EXTRA_TARGET_TABLES = {"alembic_version"}
BATCH_SIZE = 500

sys.path.insert(0, str(BACKEND_DIR))
from app import models  # noqa: E402,F401 - registers every mapped table
from app.database import Base  # noqa: E402


def model_tables():
    return list(Base.metadata.sorted_tables)


def get_schema_differences(connection) -> list:
    migration_context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "compare_server_default": True},
    )
    return compare_metadata(migration_context, Base.metadata)


def get_foreign_key_violations(connection) -> list[str]:
    issues = []
    actual_tables = set(inspect(connection).get_table_names())
    for table in model_tables():
        if table.name not in actual_tables:
            continue
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                parent_table = foreign_key.column.table
                parent_column = foreign_key.column
                missing_parent = (
                    select(1)
                    .select_from(parent_table)
                    .where(parent_column == column)
                    .exists()
                )
                count = connection.execute(
                    select(func.count())
                    .select_from(table)
                    .where(column.is_not(None), ~missing_parent)
                ).scalar_one()
                if count:
                    issues.append(
                        f"{table.name}.{column.name} has {count} orphan reference(s)"
                    )
    return issues


def inspect_data(connection) -> dict[str, int]:
    source_tables = set(inspect(connection).get_table_names())
    return {
        table.name: (
            connection.execute(select(func.count()).select_from(table)).scalar_one()
            if table.name in source_tables
            else 0
        )
        for table in model_tables()
    }


def validate_source_schema(connection) -> None:
    inspector = inspect(connection)
    actual_tables = set(inspector.get_table_names())
    expected_tables = {table.name for table in model_tables()}
    optional_tables = {"database_migration_archive"}
    missing = expected_tables - actual_tables - optional_tables
    unexpected = actual_tables - expected_tables
    if missing or unexpected:
        raise RuntimeError(
            f"SQLite source table set differs from current models; "
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )

    for table in model_tables():
        if table.name not in actual_tables:
            continue
        actual_columns = {column["name"] for column in inspector.get_columns(table.name)}
        expected_columns = set(table.columns.keys())
        missing_columns = expected_columns - actual_columns
        if missing_columns:
            raise RuntimeError(
                f"SQLite source is missing current columns from {table.name}: "
                f"{sorted(missing_columns)}"
            )
        for column in table.columns:
            if column.nullable or column.primary_key:
                continue
            null_count = connection.execute(
                select(func.count())
                .select_from(table)
                .where(table.c[column.name].is_(None))
            ).scalar_one()
            if null_count:
                raise RuntimeError(
                    f"SQLite source has {null_count} NULL value(s) in required "
                    f"column {table.name}.{column.name}"
                )
    _validate_unique_values(connection)


def validate_schema(connection, *, allow_alembic_version: bool) -> None:
    inspector = inspect(connection)
    actual_tables = set(inspector.get_table_names())
    expected_tables = {table.name for table in model_tables()}
    allowed_extras = ALLOWED_EXTRA_TARGET_TABLES if allow_alembic_version else set()
    missing = expected_tables - actual_tables
    unexpected = actual_tables - expected_tables - allowed_extras
    if missing or unexpected:
        raise RuntimeError(
            f"Database table set differs from current models; "
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )

    for table in model_tables():
        actual_columns = {column["name"] for column in inspector.get_columns(table.name)}
        expected_columns = set(table.columns.keys())
        if actual_columns != expected_columns:
            raise RuntimeError(
                f"Schema mismatch in {table.name}; "
                f"missing columns={sorted(expected_columns - actual_columns)}, "
                f"unexpected columns={sorted(actual_columns - expected_columns)}"
            )

    differences = get_schema_differences(connection)
    if differences:
        summary = "; ".join(str(difference) for difference in differences[:8])
        raise RuntimeError(f"Database schema differs from ORM metadata: {summary}")
    _validate_unique_values(connection)


def _validate_unique_values(connection) -> None:
    actual_tables = set(inspect(connection).get_table_names())
    for table in model_tables():
        if table.name not in actual_tables:
            continue
        unique_column_sets = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if getattr(constraint, "unique", False)
        }
        unique_column_sets.update(
            tuple(column.name for column in index.columns)
            for index in table.indexes
            if index.unique
        )
        for column_names in unique_column_sets:
            columns = [table.c[name] for name in column_names]
            non_null = [column.is_not(None) for column in columns]
            duplicate = (
                select(*columns)
                .select_from(table)
                .where(*non_null)
                .group_by(*columns)
                .having(func.count() > 1)
                .limit(1)
            )
            if connection.execute(duplicate).first():
                raise RuntimeError(
                    f"Duplicate value violates unique key on {table.name}"
                    f"({', '.join(column_names)})"
                )


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    return str(value)


def collect_legacy_column_rows(connection) -> list[dict]:
    inspector = inspect(connection)
    actual_tables = set(inspector.get_table_names())
    archive_rows = []
    for model_table in model_tables():
        if model_table.name not in actual_tables:
            continue
        actual_columns = {column["name"] for column in inspector.get_columns(model_table.name)}
        legacy_columns = sorted(actual_columns - set(model_table.columns.keys()))
        if not legacy_columns:
            continue

        reflected = Table(model_table.name, MetaData(), autoload_with=connection)
        primary_key_names = inspector.get_pk_constraint(model_table.name).get(
            "constrained_columns", []
        )
        if not primary_key_names:
            raise RuntimeError(f"Cannot archive legacy columns without a primary key: {model_table.name}")
        selected_columns = [
            reflected.c[name] for name in [*primary_key_names, *legacy_columns]
        ]
        for row in connection.execute(select(*selected_columns)).mappings():
            legacy_data = {
                name: _json_safe(row[name])
                for name in legacy_columns
                if row[name] is not None
            }
            if not legacy_data:
                continue
            primary_key = {name: row[name] for name in primary_key_names}
            payload = json.dumps(
                legacy_data, sort_keys=True, separators=(",", ":"), default=_json_safe
            )
            primary_key_json = json.dumps(
                primary_key, sort_keys=True, separators=(",", ":"), default=_json_safe
            )
            archive_key = hashlib.sha256(
                f"{model_table.name}\0{primary_key_json}\0{payload}".encode("utf-8")
            ).hexdigest()
            archive_rows.append(
                {
                    "archive_key": archive_key,
                    "source_table": model_table.name,
                    "source_primary_key": primary_key_json,
                    "legacy_columns": legacy_data,
                }
            )
    return archive_rows


def replace_data(source_connection, target_connection) -> dict[str, int]:
    """Replace mapped table contents within the caller's target transaction."""
    tables = model_tables()
    source_counts = inspect_data(source_connection)
    source_issues = get_foreign_key_violations(source_connection)
    if source_issues:
        raise RuntimeError("SQLite source has invalid foreign keys: " + "; ".join(source_issues))
    archived_rows = collect_legacy_column_rows(source_connection)

    for table in reversed(tables):
        target_connection.execute(delete(table))

    source_table_names = set(inspect(source_connection).get_table_names())
    for table in tables:
        if table.name not in source_table_names:
            continue
        result = source_connection.execute(select(table))
        while batch := result.mappings().fetchmany(BATCH_SIZE):
            target_connection.execute(table.insert(), [dict(row) for row in batch])

    if archived_rows:
        existing_keys = set(
            target_connection.execute(
                select(models.DatabaseMigrationArchive.archive_key)
            ).scalars()
        )
        new_archived_rows = [
            row for row in archived_rows if row["archive_key"] not in existing_keys
        ]
        if new_archived_rows:
            target_connection.execute(
                models.DatabaseMigrationArchive.__table__.insert(),
                new_archived_rows,
            )

    target_counts = inspect_data(target_connection)
    expected_counts = dict(source_counts)
    expected_counts["database_migration_archive"] += len(
        [row for row in archived_rows if row["archive_key"] not in existing_keys]
    ) if archived_rows else 0
    if target_counts != expected_counts:
        mismatches = {
            name: (expected_counts[name], target_counts[name])
            for name in expected_counts
            if expected_counts[name] != target_counts[name]
        }
        raise RuntimeError(f"Post-copy row counts differ (expected, target): {mismatches}")

    target_issues = get_foreign_key_violations(target_connection)
    if target_issues:
        raise RuntimeError("PostgreSQL copy has invalid foreign keys: " + "; ".join(target_issues))

    if target_connection.dialect.name == "postgresql":
        _synchronize_postgres_sequences(target_connection, tables)
    return expected_counts


def _synchronize_postgres_sequences(connection, tables) -> None:
    for table in tables:
        for column in table.primary_key.columns:
            if column.autoincrement is False:
                continue
            sequence = connection.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": column.name},
            ).scalar_one_or_none()
            if sequence:
                connection.execute(
                    text(
                        "SELECT setval(CAST(:sequence_name AS regclass), "
                        "COALESCE(MAX(" + column.name + "), 1), "
                        "MAX(" + column.name + ") IS NOT NULL) FROM " + table.name
                    ),
                    {"sequence_name": sequence},
                )


def _source_engine(path: Path):
    sqlite_url = URL.create(
        "sqlite",
        database=f"file:{path.as_posix()}",
        query={"mode": "ro", "uri": "true"},
    )
    return create_engine(sqlite_url, connect_args={"check_same_thread": False})


def _target_url(environment_name: str):
    raw_url = os.environ.get(environment_name, "").strip()
    if not raw_url:
        raise RuntimeError(
            f"Environment variable {environment_name} is required; "
            "set it locally and do not paste credentials into chat."
        )
    url = make_url(raw_url)
    if url.drivername == "postgres":
        url = url.set(drivername="postgresql+psycopg2")
    elif url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg2")
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("The migration target must be a PostgreSQL database.")
    if not url.host or not url.database:
        raise RuntimeError("The target connection URL must specify a host and database.")
    return url


def _target_identity(url) -> str:
    port = url.port or 5432
    return f"{url.host}:{port}/{url.database}"


def _expected_alembic_head() -> str:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head()


def _verify_target_revision(connection) -> None:
    inspector = inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        raise RuntimeError("Target schema is not initialized; run `alembic upgrade head` first.")
    revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    expected = _expected_alembic_head()
    if revisions != [expected]:
        raise RuntimeError(
            f"Target schema revision {revisions} is not current ({expected}); "
            "upgrade and verify the schema before copying data."
        )


def _create_target_backup(url, destination: Path) -> None:
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise RuntimeError(
            "pg_dump is required for a full target backup. Install PostgreSQL client tools "
            "before applying; the database has not been changed."
        )
    if destination.exists():
        raise RuntimeError(f"Backup path already exists; choose a new path: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    child_env = os.environ.copy()
    child_env.update(
        {
            "PGHOST": url.host,
            "PGPORT": str(url.port or 5432),
            "PGUSER": url.username or "",
            "PGPASSWORD": url.password or "",
            "PGDATABASE": url.database,
        }
    )
    sslmode = url.query.get("sslmode")
    if sslmode:
        child_env["PGSSLMODE"] = str(sslmode)
    command = [
        pg_dump,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(destination.resolve()),
    ]
    result = subprocess.run(command, env=child_env, capture_output=True, text=True)
    if result.returncode:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            "pg_dump failed; no target data was changed. "
            "Check PostgreSQL client/network settings locally."
        )
    with destination.open("rb") as backup:
        if backup.read(5) != b"PGDMP":
            raise RuntimeError("The target backup is not a valid custom-format pg_dump archive.")
    print(f"Verified PostgreSQL target backup: {destination.resolve()}")


def run(args) -> int:
    source_path = Path(args.sqlite_file).resolve()
    if not source_path.is_file():
        raise RuntimeError(f"SQLite source file not found: {source_path}")

    target_url = _target_url(args.target_url_env)
    target_identity = _target_identity(target_url)
    print(f"Source SQLite: {source_path}")
    print(f"Target PostgreSQL: {target_identity}")
    if args.apply and args.confirm_target != target_identity:
        raise RuntimeError(
            "Apply requires --confirm-target to exactly match the displayed "
            "host:port/database identity."
        )

    source_engine = _source_engine(source_path)
    target_engine = create_engine(target_url, pool_pre_ping=True)
    try:
        with source_engine.connect() as source_connection:
            if source_connection.dialect.name != "sqlite":
                raise RuntimeError("The source must be SQLite.")
            validate_source_schema(source_connection)
            source_counts = inspect_data(source_connection)
            source_issues = get_foreign_key_violations(source_connection)
            if source_issues:
                raise RuntimeError("SQLite source has invalid foreign keys: " + "; ".join(source_issues))
            legacy_archive_count = len(collect_legacy_column_rows(source_connection))

            with target_engine.connect() as target_connection:
                database_name = target_connection.execute(text("SELECT current_database()")).scalar_one()
                if database_name != target_url.database:
                    raise RuntimeError("Connected database identity does not match the URL.")
                _verify_target_revision(target_connection)
                validate_schema(target_connection, allow_alembic_version=True)
                target_counts = inspect_data(target_connection)

            print("\nRows by table (source -> current target):")
            for table in model_tables():
                print(f"  {table.name}: {source_counts[table.name]:,} -> {target_counts[table.name]:,}")
            if legacy_archive_count:
                print(
                    f"  Additional legacy values to preserve in "
                    f"database_migration_archive: {legacy_archive_count:,} row(s)"
                )

            if not args.apply:
                print("\nDry run only. No backup or database changes were made.")
                return 0

            backup_path = Path(args.backup_file).resolve()
            _create_target_backup(target_url, backup_path)

            with target_engine.begin() as target_connection:
                _verify_target_revision(target_connection)
                validate_schema(target_connection, allow_alembic_version=True)
                copied_counts = replace_data(source_connection, target_connection)

            with target_engine.connect() as target_connection:
                final_counts = inspect_data(target_connection)
                if final_counts != copied_counts:
                    raise RuntimeError(
                        "Committed row counts changed after migration. "
                        "Keep the backup and restore it before reopening writes."
                    )
            print("\nMigration committed and every mapped table count/foreign key verified.")
            print(f"Keep this rollback archive safe: {backup_path.resolve()}")
            return 0
    finally:
        source_engine.dispose()
        target_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or safely replace PostgreSQL data from a SQLite snapshot."
    )
    parser.add_argument(
        "--sqlite-file",
        default=str(DEFAULT_SOURCE),
        help="SQLite source (default: backend/hr_app.db)",
    )
    parser.add_argument(
        "--target-url-env",
        default="RAILWAY_DATABASE_URL",
        help="Name of environment variable containing the PostgreSQL URL (default: RAILWAY_DATABASE_URL)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up PostgreSQL and replace all mapped application tables transactionally.",
    )
    parser.add_argument(
        "--confirm-target",
        default="",
        help="Required with --apply; must equal the displayed host:port/database identity.",
    )
    parser.add_argument(
        "--backup-file",
        default=str(
            BACKEND_DIR
            / "backups"
            / f"railway_pre_migration_{datetime.datetime.now():%Y%m%d_%H%M%S}.dump"
        ),
        help="Path for a new custom-format pg_dump archive (must not already exist).",
    )
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as exc:
        print(f"Migration stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
