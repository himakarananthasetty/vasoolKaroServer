from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileUpdateIn(BaseModel):
    """Field allow-list — mirrors the old column-level grants."""

    full_name: str | None = Field(default=None, max_length=120)
    phone_number: str | None = Field(default=None, max_length=20)
    date_of_birth: date | None = None
    address: str | None = Field(default=None, max_length=200)
    notify_offers: bool | None = None
    notify_receipts: bool | None = None
    marketing_opt_in: bool | None = None
    personalised_offers: bool | None = None

    @field_validator("full_name", "phone_number", "address")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: object
    email: str
    full_name: str | None
    account_type: str
    business_name: str | None
    phone_number: str | None
    date_of_birth: date | None
    address: str | None
    avatar_path: str | None
    referral_code: str
    referred_by: object | None
    notify_offers: bool
    notify_receipts: bool
    marketing_opt_in: bool
    personalised_offers: bool
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime
