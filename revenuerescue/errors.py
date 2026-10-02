"""Stable machine-readable error envelopes for agent/API clients."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceError:
    code: str
    message: str
    retryable: bool = False
    details: dict | None = None

    def as_dict(self) -> dict:
        payload = {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            },
        }
        if self.details:
            payload["error"]["details"] = self.details
        return payload


def invalid_input(message: str, **details) -> dict:
    return ServiceError("INVALID_INPUT", message, False, details or None).as_dict()


def unauthorized(message: str = "unauthorized") -> dict:
    return ServiceError("UNAUTHORIZED", message, False).as_dict()


def not_found(resource: str, identifier: str | None = None) -> dict:
    details = {"resource": resource}
    if identifier:
        details["id"] = identifier
    return ServiceError(
        "NOT_FOUND",
        f"{resource} not found",
        False,
        details,
    ).as_dict()


def rate_limited(retry_after_seconds: int = 60) -> dict:
    return ServiceError(
        "RATE_LIMITED",
        "rate limit exceeded",
        True,
        {"retry_after_seconds": retry_after_seconds},
    ).as_dict()


def internal_error(message: str = "internal service error") -> dict:
    return ServiceError("INTERNAL_ERROR", message, True).as_dict()


def not_ready(problems: list[str]) -> dict:
    return ServiceError(
        "NOT_READY",
        "service is not ready",
        True,
        {"problems": problems},
    ).as_dict()
