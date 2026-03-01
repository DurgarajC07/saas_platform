"""
Application exception hierarchy.

All custom exceptions inherit from AppException and carry:
  - status_code  → HTTP status
  - code         → machine-readable error code for API consumers
  - message      → human-readable description

Raise these from service/repository layers; the exception handler
registered in main.py converts them to uniform JSON responses.
"""


class AppException(Exception):
    """Base class for all application-level exceptions."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.__class__.message
        super().__init__(self.message)


class NotFoundException(AppException):
    status_code = 404
    code = "NOT_FOUND"
    message = "The requested resource was not found"


class BadRequestException(AppException):
    status_code = 400
    code = "BAD_REQUEST"
    message = "The request is invalid or malformed"


class UnauthorizedException(AppException):
    status_code = 401
    code = "UNAUTHORIZED"
    message = "Authentication credentials are missing or invalid"


class ForbiddenException(AppException):
    status_code = 403
    code = "FORBIDDEN"
    message = "You do not have permission to perform this action"


class ConflictException(AppException):
    status_code = 409
    code = "CONFLICT"
    message = "A resource with the same identifier already exists"


class ValidationException(AppException):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "Request data failed validation"


class RateLimitException(AppException):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many requests — please slow down"


class ServiceUnavailableException(AppException):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"
    message = "The service is temporarily unavailable"
