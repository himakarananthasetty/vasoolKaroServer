from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.errors import NotFound, ValidationError
from src.db.models import Todo, User


class TodoCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_on: date

    @field_validator("title")
    @classmethod
    def strip(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 200):
            raise ValueError("title must be 1-200 characters")
        return v


class TodoUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_on: date | None = None
    completed: bool | None = None


class TodoOut(BaseModel):
    id: uuid.UUID
    title: str
    due_on: date
    completed: bool
    created_at: object

    model_config = {"from_attributes": True}


def list_todos(db: Session, user: User, *, month: str | None) -> dict:
    if month:
        try:
            year, mon = (int(x) for x in month.split("-"))
        except ValueError as exc:
            raise ValidationError("month must be in YYYY-MM format.") from exc
        start = date(year, mon, 1)
        next_month = date(year + (mon == 12), 1 if mon == 12 else mon + 1, 1)
        stmt = (
            select(Todo)
            .where(Todo.user_id == user.id, Todo.due_on >= start, Todo.due_on < next_month)
            .order_by(Todo.created_at.asc())
        )
    else:
        stmt = select(Todo).where(Todo.user_id == user.id).order_by(Todo.created_at.asc())
    rows = db.scalars(stmt).all()
    return {"items": rows}


def create_todo(db: Session, user: User, body: TodoCreateIn) -> Todo:
    row = Todo(user_id=user.id, title=body.title, due_on=body.due_on)
    db.add(row)
    db.flush()
    return row


def update_todo(db: Session, user: User, todo_id: uuid.UUID, body: TodoUpdateIn) -> Todo:
    row = db.scalar(select(Todo).where(Todo.id == todo_id, Todo.user_id == user.id))
    if row is None:
        raise NotFound()
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        row.title = data["title"].strip()
    if "due_on" in data and data["due_on"] is not None:
        row.due_on = data["due_on"]
    if "completed" in data and data["completed"] is not None:
        row.completed = data["completed"]
    db.flush()
    return row


def delete_todo(db: Session, user: User, todo_id: uuid.UUID) -> None:
    row = db.scalar(select(Todo).where(Todo.id == todo_id, Todo.user_id == user.id))
    if row is None:
        raise NotFound()
    db.delete(row)
    db.flush()
