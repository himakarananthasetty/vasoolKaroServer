"""Stable error codes for the API error envelope.

Envelope: {"error": {"code": ..., "message": ..., ...extras}}
"""
from __future__ import annotations


class ApiError(Exception):
    status_code = 400
    code = "bad_request"
    message = "Invalid request."

    def __init__(self, message: str | None = None, **extra: object) -> None:
        self.message = message or self.message
        self.extra = extra
        super().__init__(self.message)

    def to_payload(self) -> dict:
        payload = {"error": {"code": self.code, "message": self.message}}
        payload["error"].update(self.extra)
        return payload


class ValidationError(ApiError):
    status_code = 400
    code = "invalid_input"
    message = "Invalid input."


class Unauthorized(ApiError):
    status_code = 401
    code = "unauthorized"
    message = "Authentication required."


class InvalidCredentials(Unauthorized):
    code = "invalid_credentials"
    message = "Invalid email or password."


class InvalidRefreshToken(Unauthorized):
    code = "invalid_refresh_token"
    message = "Invalid or expired refresh token."


class Forbidden(ApiError):
    status_code = 403
    code = "forbidden"
    message = "Not allowed."


class NotFound(ApiError):
    status_code = 404
    code = "not_found"
    message = "Resource not found."


class Conflict(ApiError):
    status_code = 409
    code = "conflict"
    message = "Conflict."


class EmailAlreadyRegistered(Conflict):
    code = "email_already_registered"
    message = "An account with this email already exists."


class WeakPassword(ValidationError):
    code = "weak_password"
    message = "Password must be at least 8 characters."


class BusinessNameRequired(ValidationError):
    code = "business_name_required"
    message = "Retailer accounts require a business name."


class DobLocked(ValidationError):
    code = "dob_locked"
    message = "Date of birth cannot be changed once set."


class MinimumAge(ValidationError):
    code = "minimum_age"
    message = "You must be at least 13 years old."


class EmailTaken(Conflict):
    pass


class PayoutAlreadyRequested(Conflict):
    code = "payout_already_requested"
    message = "You already have an open payout request."


class BelowMinimum(ApiError):
    status_code = 422
    code = "below_minimum"
    message = "Amount is below the payout minimum."


class NothingToPayout(ApiError):
    status_code = 422
    code = "nothing_to_payout"
    message = "No wallet balance available to pay out."


class PayoutNotRequested(Conflict):
    code = "not_requested"
    message = "Payout is not in the requested state."


class ReferenceInUse(Conflict):
    code = "reference_in_use"
    message = "Payment reference already used by a paid payout."


class SelfReferral(Conflict):
    code = "self_referral"
    message = "You cannot use your own referral code."


class MutualReferral(Conflict):
    code = "mutual_referral"
    message = "This referral relationship is not allowed."


class AlreadyRedeemed(Conflict):
    code = "already_redeemed"
    message = "Referral already redeemed between these accounts."


class CodeNotFound(NotFound):
    code = "code_not_found"
    message = "Referral code not found."


class ReferralLimit(ApiError):
    status_code = 422
    code = "referral_limit"
    message = "Referral invite limit reached."


class RateLimited(ApiError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests."

    def __init__(self, message: str | None = None, retry_after_seconds: int = 0) -> None:
        super().__init__(message, retry_after_seconds=retry_after_seconds)


class DeleteBlocked(Conflict):
    code = "delete_blocked"
    message = "Account cannot be deleted."

    def __init__(self, reason: str) -> None:
        super().__init__(self.message, reason=reason)
