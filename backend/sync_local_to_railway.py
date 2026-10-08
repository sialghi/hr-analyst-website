"""Deprecated unsafe migrator; use migrate_local_to_postgres.py instead."""
import sys


if __name__ == "__main__":
    print(
        "This legacy migration command has been disabled because it can partially "
        "delete production data and omits current tables. Use "
        "migrate_local_to_postgres.py, which defaults to a read-only dry run.",
        file=sys.stderr,
    )
    raise SystemExit(2)
