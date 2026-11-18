from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)
    account_type: str = Field(default="shopper", pattern="^(shopper|retailer)$")
    business_name: str | None = Field(default=None, max_length=80)
    date_of_birth: date | None = None

    @field_validator("full_name", "business_name")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordRecoveryIn(BaseModel):
    email: EmailStr


class PasswordRecoveryConfirmIn(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    account_type: str
    business_name: str | None
    phone_number: str | None
    date_of_birth: date | None
    address: str | None
    avatar_path: str | None
    referral_code: str
    referred_by: uuid.UUID | None
    notify_offers: bool
    notify_receipts: bool
    marketing_opt_in: bool
    personalised_offers: bool
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: ProfileOut
