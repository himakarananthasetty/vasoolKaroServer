from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user
from src.core.db import get_db
from src.db.models import User
from src.support import service
from src.support.service import SupportCreateIn

router = APIRouter(prefix="/support-requests", tags=["support"])


@router.get("")
def list_requests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = service.list_requests(db, user, page=page, page_size=page_size)
    return {
        "items": [service.SupportOut.model_validate(r) for r in result["items"]],
        "page": result["page"], "page_size": result["page_size"], "total": result["total"],
    }


@router.post("", status_code=201)
def create_request(
    body: SupportCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = service.create_request(db, user, body.topic, body.message)
    db.commit()
    return service.SupportOut.model_validate(row)
