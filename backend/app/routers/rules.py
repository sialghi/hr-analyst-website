# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/rules", tags=["rules"])


def _get_or_create_singleton(db: Session) -> models.BusinessRule:
    rule = db.query(models.BusinessRule).first()
    if not rule:
        rule = models.BusinessRule()
        db.add(rule)
        db.commit()
        db.refresh(rule)
    return rule


@router.get("", response_model=schemas.BusinessRuleOut)
def get_rules(db: Session = Depends(get_db), _: models.User = Depends(auth.get_current_user)):
    """Semua user login boleh melihat aturan global (uang makan, potongan, dsb)."""
    return _get_or_create_singleton(db)


@router.put("", response_model=schemas.BusinessRuleOut)
def update_rules(
    payload: schemas.BusinessRuleUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_hr_master),
):
    """HANYA HR Master yang boleh mengubah aturan bisnis global."""
    rule = _get_or_create_singleton(db)
    for field, value in payload.dict().items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule
