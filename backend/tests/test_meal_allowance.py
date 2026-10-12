import datetime

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.pipeline import config_runtime
from app.pipeline.data_process import hitung_uang_makan


def _attendance_row(name, branch, date, check_in=datetime.time(8, 0), check_out=datetime.time(16, 0)):
    return {
        "Cabang": branch,
        "Nama": name,
        "Profil": "OFFICE",
        "Tanggal": date,
        "Hari": "Senin",
        "Jam_Masuk": check_in,
        "Jam_Keluar": check_out,
    }


def _set_zero_default_profile(monkeypatch):
    monkeypatch.setattr(config_runtime, "UANG_MAKAN_DEFAULT", 0)
    monkeypatch.setattr(config_runtime, "PROFIL_DEFAULT", "OFFICE")
    monkeypatch.setattr(config_runtime, "PROFIL_JADWAL", {
        "OFFICE": {
            "ikut_telat": True,
            "ikut_bonus_tanggal_merah": True,
            "jam_masuk": {"default": datetime.time(8, 0)},
            "jam_keluar": {"default": datetime.time(16, 0)},
        },
    })


def test_new_global_meal_allowance_rule_defaults_to_zero():
    assert schemas.BusinessRuleBase().uang_makan_default == 0

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add(models.BusinessRule())
        session.flush()
        saved_rule = session.query(models.BusinessRule).one()
        assert saved_rule.uang_makan_default == 0
    finally:
        session.close()
        engine.dispose()


def test_empty_employee_override_uses_zero_for_all_branches(monkeypatch):
    _set_zero_default_profile(monkeypatch)
    holiday = datetime.date(2026, 10, 12)
    rows = pd.DataFrame([
        _attendance_row("Regular Branch", "BANDUNG", holiday),
        _attendance_row("IDD Branch", "PIK IDD", holiday),
    ])

    result = hitung_uang_makan(rows, tanggal_merah={holiday: "Libur"})

    assert result["Uang_Makan_Base"].tolist() == [0, 0]
    assert result["Bonus_Tanggal_Merah"].tolist() == [0, 0]
    assert result["Total_Uang_Makan"].tolist() == [0, 0]


def test_zero_default_deductions_never_create_negative_allowance(monkeypatch):
    _set_zero_default_profile(monkeypatch)
    row = _attendance_row(
        "Late Employee",
        "BANDUNG",
        datetime.date(2026, 10, 12),
        check_in=datetime.time(9, 0),
        check_out=datetime.time(14, 0),
    )

    result = hitung_uang_makan(pd.DataFrame([row]))

    assert result.loc[0, "Uang_Makan_Base"] == 0
    assert result.loc[0, "Potongan_Telat"] == 0
    assert result.loc[0, "Potongan_Pulang_Duluan"] == 0
    assert result.loc[0, "Total_Uang_Makan"] == 0


def test_explicit_employee_override_remains_in_effect(monkeypatch):
    _set_zero_default_profile(monkeypatch)
    row = _attendance_row(
        "Override Employee",
        "BANDUNG",
        datetime.date(2026, 10, 12),
    )

    result = hitung_uang_makan(
        pd.DataFrame([row]),
        master_dict={"override employee": {"Uang_Makan": 25_000}},
    )

    assert result.loc[0, "Uang_Makan_Base"] == 25_000
    assert result.loc[0, "Total_Uang_Makan"] == 25_000


def test_existing_profile_and_idd_holiday_rules_remain_for_explicit_override(monkeypatch):
    _set_zero_default_profile(monkeypatch)
    holiday = datetime.date(2026, 10, 12)
    rows = pd.DataFrame([
        _attendance_row("Regular Branch Override", "BANDUNG", holiday),
        _attendance_row("IDD Branch Override", "PIK IDD", holiday),
    ])
    master = {
        "regular branch override": {"Uang_Makan": 25_000},
        "idd branch override": {"Uang_Makan": 25_000},
    }

    result = hitung_uang_makan(
        rows,
        master_dict=master,
        tanggal_merah={holiday: "Libur"},
    )

    totals_by_branch = result.set_index("Cabang")["Total_Uang_Makan"].to_dict()
    assert totals_by_branch == {"BANDUNG": 25_000, "PIK IDD": 50_000}
