import importlib.util
from pathlib import Path
from types import SimpleNamespace


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "a61d9f3c4b20_use_employee_code_column.py"
)
SPEC = importlib.util.spec_from_file_location(
    "employee_code_column_migration",
    MIGRATION_PATH,
)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def test_constraint_backed_employee_code_index_is_not_dropped(monkeypatch):
    indexes = [
        {
            "name": "employees_employee_code_key",
            "column_names": ["employee_code"],
            "unique": True,
            "duplicates_constraint": "employees_employee_code_key",
        },
        {
            "name": "ix_employees_employee_code",
            "column_names": ["employee_code"],
            "unique": True,
        },
    ]
    inspector = SimpleNamespace(
        get_unique_constraints=lambda table_name: [
            {"name": "employees_employee_code_key", "column_names": ["employee_code"]}
        ],
        get_indexes=lambda table_name: indexes,
    )
    dropped = []
    monkeypatch.setattr(MIGRATION.sa, "inspect", lambda connection: inspector)
    monkeypatch.setattr(
        MIGRATION.op,
        "drop_index",
        lambda name, table_name: dropped.append((name, table_name)),
    )

    MIGRATION._drop_employee_id_indexes(object(), "employees")

    assert dropped == [("ix_employees_employee_code", "employees")]
