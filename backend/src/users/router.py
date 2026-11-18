from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user
from src.common.rate_limit import check_rate_limit
from src.core.config import get_settings
from src.core.db import get_db
from src.core.errors import ValidationError
from src.db.models import User
from src.users import service
from src.users.schemas import ProfileOut, ProfileUpdateIn

router = APIRouter(tags=["me"])


@router.get("/me", response_model=ProfileOut)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=ProfileOut)
def update_me(
    body: ProfileUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = service.update_profile(db, user, **body.model_dump(exclude_unset=True))
    db.commit()
    return updated


@router.post("/me/deactivate", status_code=204)
def deactivate_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service.deactivate(db, user)
    db.commit()


@router.post("/me/reactivate", status_code=204)
def reactivate_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service.reactivate(db, user)
    db.commit()


@router.post("/me/delete")
def delete_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_account(db, user)
    db.commit()
    return {"ok": True}


@router.get("/me/avatar")
def get_avatar(user: User = Depends(get_current_user)):
    if not user.avatar_path or not Path(user.avatar_path).is_file():
        raise HTTPException(status_code=404, detail="No avatar")
    media_type, _ = mimetypes.guess_type(user.avatar_path)
    return FileResponse(user.avatar_path, media_type=media_type or "application/octet-stream")


@router.delete("/me/avatar", status_code=204)
def remove_avatar(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_avatar(db, user)
    db.commit()


@router.put("/me/avatar", response_model=ProfileOut)
def upload_avatar(
    avatar: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_rate_limit(
        db,
        action="avatar_upload",
        subject_kind="user",
        subject_id=str(user.id),
        limit=10,
        window_seconds=3600,
    )
    content = avatar.file.read(get_settings().avatar_max_bytes + 1)
    if len(content) > get_settings().avatar_max_bytes:
        raise ValidationError("Avatar exceeds the 2 MB size limit.")
    service.save_avatar(db, user, avatar, content)
    db.commit()
    return user
