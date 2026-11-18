from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user
from src.core.db import get_db
from src.db.models import User
from src.todos import service
from src.todos.service import TodoCreateIn, TodoUpdateIn

router = APIRouter(prefix="/todos", tags=["todos"])


@router.get("")
def list_todos(
    month: str | None = Query(default=None, pattern="^\\d{4}-\\d{2}$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = service.list_todos(db, user, month=month)
    return {"items": [service.TodoOut.model_validate(r) for r in result["items"]]}


@router.post("", status_code=201)
def create_todo(
    body: TodoCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = service.create_todo(db, user, body)
    db.commit()
    return service.TodoOut.model_validate(row)


@router.patch("/{todo_id}")
def update_todo(
    todo_id: uuid.UUID,
    body: TodoUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = service.update_todo(db, user, todo_id, body)
    db.commit()
    return service.TodoOut.model_validate(row)


@router.delete("/{todo_id}", status_code=204)
def delete_todo(
    todo_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.delete_todo(db, user, todo_id)
    db.commit()
