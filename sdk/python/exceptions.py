"""Custom exceptions for the Rules-Emerging-Pattern SDK."""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SDKError(Exception):
    """Base exception for all SDK errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        original_exception: Optional[Exception] = None,
    ):
        self.status_code = status_code
        self.response_body = response_body
        self.original_exception = original_exception
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "error_type": self.__class__.__name__,
            "message": str(self),
        }
        if self.status_code is not None:
            result["status_code"] = self.status_code
        if self.response_body is not None:
            result["response_body"] = self.response_body
        return result


class ConfigurationError(SDKError):
    """Raised when SDK configuration is invalid."""

    def __init__(self, message: str, field: Optional[str] = None):
        self.field = field
        detail = f"Configuration error for '{field}': {message}" if field else message
        super().__init__(detail)


class AuthenticationError(SDKError):
    """Raised when authentication fails."""

    def __init__(
        self,
        message: str = "Authentication failed. Check your API key.",
        status_code: int = 401,
    ):
        super().__init__(message, status_code=status_code)


class APIError(SDKError):
    """Raised when the API returns an error response."""

    def __init__(
        self,
        message: str,
        status_code: int,
        response_body: Optional[str] = None,
        endpoint: Optional[str] = None,
    ):
        self.endpoint = endpoint
        detail = f"API error at {endpoint}: {message}" if endpoint else message
        super().__init__(detail, status_code=status_code, response_body=response_body)


class RateLimitError(APIError):
    """Raised when API rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please retry after the specified cooldown.",
        retry_after: Optional[int] = None,
        status_code: int = 429,
    ):
        self.retry_after = retry_after
        if retry_after:
            message = f"{message} Retry after {retry_after} seconds."
        super().__init__(message, status_code=status_code)


class TimeoutError(SDKError):
    """Raised when a request times out."""

    def __init__(
        self,
        message: str = "Request timed out.",
        timeout_seconds: Optional[float] = None,
        operation: Optional[str] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.operation = operation
        detail = message
        if operation:
            detail = f"Operation '{operation}' timed out after {timeout_seconds}s"
        elif timeout_seconds:
            detail = f"Request timed out after {timeout_seconds}s"
        super().__init__(detail)


class ValidationError(SDKError):
    """Raised when input validation fails."""

    def __init__(
        self,
        message: str,
        errors: Optional[list] = None,
        field: Optional[str] = None,
    ):
        self.validation_errors = errors or []
        self.field = field
        detail = message
        if errors:
            detail = f"{message}: {', '.join(str(e) for e in errors[:5])}"
        super().__init__(detail)


class RuleNotFoundError(SDKError):
    """Raised when a requested rule is not found."""

    def __init__(
        self,
        rule_id: str,
        message: Optional[str] = None,
    ):
        self.rule_id = rule_id
        detail = message or f"Rule '{rule_id}' not found."
        super().__init__(detail, status_code=404)


class ConflictError(SDKError):
    """Raised when there is a conflict (e.g., duplicate rule)."""

    def __init__(
        self,
        message: str,
        conflict_type: Optional[str] = None,
        conflicting_ids: Optional[list] = None,
    ):
        self.conflict_type = conflict_type
        self.conflicting_ids = conflicting_ids or []
        super().__init__(message, status_code=409)


class ServerError(SDKError):
    """Raised when the server returns a 5xx error."""

    def __init__(
        self,
        message: str = "Internal server error.",
        status_code: int = 500,
        response_body: Optional[str] = None,
    ):
        super().__init__(message, status_code=status_code, response_body=response_body)


class ConnectionError(SDKError):
    """Raised when a connection cannot be established."""

    def __init__(
        self,
        message: str = "Failed to connect to the server.",
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        self.host = host
        self.port = port
        detail = message
        if host and port:
            detail = f"Failed to connect to {host}:{port}: {message}"
        elif host:
            detail = f"Failed to connect to {host}: {message}"
        super().__init__(detail)


class BatchOperationError(SDKError):
    """Raised when a batch operation has partial failures."""

    def __init__(
        self,
        message: str,
        succeeded: int = 0,
        failed: int = 0,
        errors: Optional[list] = None,
    ):
        self.succeeded = succeeded
        self.failed = failed
        self.batch_errors = errors or []
        detail = f"{message} (succeeded={succeeded}, failed={failed})"
        super().__init__(detail)


class SerializationError(SDKError):
    """Raised when serialization or deserialization fails."""

    def __init__(
        self,
        message: str,
        original_type: Optional[str] = None,
        target_type: Optional[str] = None,
    ):
        self.original_type = original_type
        self.target_type = target_type
        detail = message
        if original_type and target_type:
            detail = f"Cannot serialize {original_type} to {target_type}: {message}"
        super().__init__(detail)
