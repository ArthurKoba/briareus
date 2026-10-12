"""Application errors; HTTP adaptation must preserve Admin API v1 envelope."""

from __future__ import annotations


class PlatformError(Exception):
    code = "platform_error"
    status_code = 400


class AccessDenied(PlatformError):
    code = "project_access_denied"
    status_code = 403


class AuthenticationRequired(PlatformError):
    code = "authentication_required"
    status_code = 401


class ResourceMissing(PlatformError):
    code = "not_found"
    status_code = 404


class Conflict(PlatformError):
    code = "conflict"
    status_code = 409


class InvalidInput(PlatformError):
    code = "invalid_request"


class IdempotencyConflict(Conflict):
    code = "idempotency_key_conflict"


class OperationInProgress(Conflict):
    code = "operation_in_progress"


class InvalidInvitation(InvalidInput):
    code = "invalid_invitation"


class LastSuperuser(Conflict):
    code = "last_superuser"


class AuthenticationRateLimited(PlatformError):
    code = "authentication_rate_limited"
    status_code = 429


class PersistenceTimeout(PlatformError):
    code = "database_operation_timeout"
    status_code = 503
