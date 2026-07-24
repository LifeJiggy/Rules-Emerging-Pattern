"""
API middleware components for request logging, request validation,
rate limiting, CORS handling, error handling, request ID tracking,
and response timing.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
import traceback
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import (
    Rule,
    RuleTier,
    RuleType,
    RuleSeverity,
    RuleStatus,
    RuleContext,
    RuleEvaluationRequest,
)
from rules_emerging_pattern.models.validation import (
    ValidationResult,
    Violation,
    ViolationType,
    ActionTaken,
    Suggestion,
)
from rules_emerging_pattern.models.conflict import (
    RuleConflict,
    ConflictType,
)

logger = logging.getLogger(__name__)


class MiddlewareType(str, Enum):
    """Types of middleware supported."""
    PRE_REQUEST = "pre_request"
    POST_REQUEST = "post_request"
    ERROR_HANDLER = "error_handler"
    RESPONSE_FORMATTER = "response_formatter"


class LogLevel(str, Enum):
    """Log levels for middleware logging."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class RequestContext:
    """Contextual information for a single request."""
    request_id: str
    method: str
    path: str
    query_params: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[Any] = None
    client_ip: Optional[str] = None
    user_id: Optional[str] = None
    user_agent: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    duration_ms: float = 0.0
    status_code: int = 200
    response_size: int = 0
    error: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)

    def complete(self, status_code: int, response_size: int = 0) -> None:
        self.completed_at = time.time()
        self.duration_ms = (self.completed_at - self.started_at) * 1000
        self.status_code = status_code
        self.response_size = response_size

    def set_error(self, error: str) -> None:
        self.error = error
        self.status_code = 500

    def to_log_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "method": self.method,
            "path": self.path,
            "status_code": self.status_code,
            "duration_ms": round(self.duration_ms, 2),
            "client_ip": self.client_ip,
            "user_id": self.user_id,
            "user_agent": self.user_agent,
            "response_size": self.response_size,
            "error": self.error,
            "tags": self.tags,
        }


class RequestIDMiddleware:
    """Middleware for generating and tracking request IDs."""

    def __init__(self, header_name: str = "X-Request-ID",
                 include_in_response: bool = True) -> None:
        self._header_name = header_name
        self._include_in_response = include_in_response
        self._counter: int = 0

    def process_request(self, request: Dict[str, Any]) -> str:
        request_id = request.get("headers", {}).get(self._header_name.lower())
        if not request_id:
            self._counter += 1
            request_id = f"req_{uuid.uuid4().hex[:12]}_{self._counter}"
        request["request_id"] = request_id
        return request_id

    def process_response(self, response: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        if self._include_in_response:
            if "headers" not in response:
                response["headers"] = {}
            response["headers"][self._header_name] = request_id
        return response

    def get_request_id(self, request: Dict[str, Any]) -> Optional[str]:
        return request.get("request_id") or request.get("headers", {}).get(self._header_name.lower())

    def generate_batch_id(self) -> str:
        return f"batch_{uuid.uuid4().hex[:16]}"

    def extract_trace_id(self, request: Dict[str, Any]) -> Optional[str]:
        return request.get("headers", {}).get("x-trace-id") or request.get("headers", {}).get("traceparent")


class ResponseTimingMiddleware:
    """Middleware for tracking request/response timing."""

    def __init__(self) -> None:
        self._timings: Dict[str, float] = {}

    def start_timer(self, request_id: str) -> None:
        self._timings[request_id] = time.time()

    def stop_timer(self, request_id: str) -> float:
        start = self._timings.pop(request_id, None)
        if start is None:
            return 0.0
        return (time.time() - start) * 1000

    def get_timing(self, request_id: str) -> Optional[float]:
        start = self._timings.get(request_id)
        if start is None:
            return None
        return (time.time() - start) * 1000

    def add_timing_header(self, response: Dict[str, Any], duration_ms: float) -> Dict[str, Any]:
        if "headers" not in response:
            response["headers"] = {}
        response["headers"]["X-Response-Time-Ms"] = str(round(duration_ms, 2))
        return response

    def get_average_timing(self) -> float:
        if not self._timings:
            return 0.0
        return sum(self._timings.values()) / len(self._timings)

    def clear_timings(self) -> None:
        self._timings.clear()

    def get_timing_statistics(self) -> Dict[str, Any]:
        values = list(self._timings.values())
        if not values:
            return {"count": 0, "avg": 0, "min": 0, "max": 0}
        return {
            "count": len(values),
            "avg": round(sum(values) / len(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }


class RequestLoggingMiddleware:
    """Middleware for logging incoming requests and outgoing responses."""

    def __init__(self, log_body: bool = False, log_headers: bool = True,
                 log_query_params: bool = True,
                 max_body_log_length: int = 1000) -> None:
        self._log_body = log_body
        self._log_headers = log_headers
        self._log_query_params = log_query_params
        self._max_body_log_length = max_body_log_length
        self._request_logs: deque = deque(maxlen=10000)

    def log_request(self, request: Dict[str, Any], request_id: str) -> RequestContext:
        method = request.get("method", "GET")
        path = request.get("path", "/")
        headers = request.get("headers", {})
        ctx = RequestContext(
            request_id=request_id,
            method=method,
            path=path,
            query_params=request.get("params", {}),
            headers=headers,
            body=request.get("body"),
            client_ip=self._extract_client_ip(headers),
            user_id=request.get("user_id"),
            user_agent=headers.get("user-agent"),
        )
        log_parts = [f"[{request_id}] {method} {path}"]
        if self._log_query_params and ctx.query_params:
            log_parts.append(f"params={ctx.query_params}")
        if self._log_headers:
            sanitized_headers = self._sanitize_headers(headers)
            log_parts.append(f"headers={sanitized_headers}")
        if self._log_body and ctx.body:
            body_str = json.dumps(ctx.body, default=str)[:self._max_body_log_length]
            log_parts.append(f"body={body_str}")
        logger.info(" ".join(log_parts))
        return ctx

    def log_response(self, ctx: RequestContext, response: Dict[str, Any]) -> None:
        status_code = response.get("status_code", 200)
        response_size = len(json.dumps(response.get("body", {}), default=str))
        ctx.complete(status_code, response_size)
        log_level = LogLevel.INFO
        if status_code >= 500:
            log_level = LogLevel.ERROR
        elif status_code >= 400:
            log_level = LogLevel.WARNING
        log_data = ctx.to_log_dict()
        log_func = getattr(logger, log_level.value, logger.info)
        log_func(f"[{ctx.request_id}] {ctx.method} {ctx.path} -> {status_code} in {ctx.duration_ms:.1f}ms")
        self._request_logs.append(log_data)

    def log_error(self, ctx: RequestContext, error: Exception) -> None:
        ctx.set_error(str(error))
        ctx.complete(500, 0)
        log_data = ctx.to_log_dict()
        self._request_logs.append(log_data)
        logger.error(f"[{ctx.request_id}] Error: {error}\n{traceback.format_exc()}")

    def _extract_client_ip(self, headers: Dict[str, str]) -> Optional[str]:
        for header in ["x-forwarded-for", "x-real-ip", "x-client-ip", "remote-addr"]:
            value = headers.get(header)
            if value:
                if "," in value:
                    return value.split(",")[0].strip()
                return value
        return None

    def _sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        sensitive = ["authorization", "cookie", "set-cookie", "x-api-key", "token", "secret"]
        sanitized = {}
        for key, value in headers.items():
            if key.lower() in sensitive:
                sanitized[key] = "***"
            else:
                sanitized[key] = value
        return sanitized

    def get_recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self._request_logs)[-limit:]

    def get_logs_by_status(self, status_code: int, limit: int = 50) -> List[Dict[str, Any]]:
        return [log for log in self._request_logs if log["status_code"] == status_code][-limit:]

    def get_error_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [log for log in self._request_logs if log["status_code"] >= 500][-limit:]

    def get_log_statistics(self) -> Dict[str, Any]:
        total = len(self._request_logs)
        if total == 0:
            return {"total": 0}
        by_status = defaultdict(int)
        total_duration = 0.0
        for log_entry in self._request_logs:
            by_status[log_entry["status_code"]] += 1
            total_duration += log_entry["duration_ms"]
        return {
            "total": total,
            "by_status": dict(by_status),
            "avg_duration_ms": round(total_duration / total, 2),
            "error_rate": round(by_status.get(500, 0) / total * 100, 2) if total > 0 else 0,
        }

    def clear_logs(self) -> None:
        self._request_logs.clear()


class RequestValidationMiddleware:
    """Middleware for validating incoming requests."""

    def __init__(self) -> None:
        self._allowed_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        self._max_body_size = 1024 * 1024 * 10
        self._allowed_content_types = {"application/json", "multipart/form-data", "application/x-www-form-urlencoded"}

    def validate_method(self, method: str) -> Optional[str]:
        if method.upper() not in self._allowed_methods:
            return f"HTTP method '{method}' not allowed"
        return None

    def validate_content_type(self, content_type: Optional[str]) -> Optional[str]:
        if content_type and content_type not in self._allowed_content_types:
            if not content_type.startswith("application/json"):
                return f"Unsupported content type: {content_type}"
        return None

    def validate_body_size(self, body: Optional[Any]) -> Optional[str]:
        if body is not None:
            body_str = json.dumps(body, default=str)
            if len(body_str) > self._max_body_size:
                return f"Request body exceeds maximum size of {self._max_body_size} bytes"
        return None

    def validate_path(self, path: str) -> Optional[str]:
        if not path or not path.startswith("/"):
            return "Invalid request path"
        if len(path) > 2048:
            return "Request path exceeds maximum length"
        return None

    def validate_query_params(self, params: Dict[str, str]) -> List[str]:
        errors = []
        for key, value in params.items():
            if len(key) > 256:
                errors.append(f"Query parameter key exceeds maximum length: {key}")
            if len(value) > 2048:
                errors.append(f"Query parameter value exceeds maximum length for: {key}")
        return errors

    def validate_json_body(self, body: Optional[Any]) -> Optional[str]:
        if body is not None and not isinstance(body, dict):
            return "Request body must be a JSON object"
        return None

    def validate_required_headers(self, headers: Dict[str, str],
                                   required: Optional[List[str]] = None) -> List[str]:
        errors = []
        if required:
            for header in required:
                if header.lower() not in {k.lower(): v for k, v in headers.items()}:
                    errors.append(f"Missing required header: {header}")
        return errors

    def validate_request(self, request: Dict[str, Any]) -> List[str]:
        errors = []
        method = request.get("method", "")
        path = request.get("path", "")
        headers = request.get("headers", {})
        body = request.get("body")
        content_type = headers.get("content-type")

        method_error = self.validate_method(method)
        if method_error:
            errors.append(method_error)

        path_error = self.validate_path(path)
        if path_error:
            errors.append(path_error)

        content_type_error = self.validate_content_type(content_type)
        if content_type_error:
            errors.append(content_type_error)

        body_size_error = self.validate_body_size(body)
        if body_size_error:
            errors.append(body_size_error)

        json_body_error = self.validate_json_body(body)
        if json_body_error:
            errors.append(json_body_error)

        if "params" in request:
            query_errors = self.validate_query_params(request["params"])
            errors.extend(query_errors)

        return errors

    def sanitize_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = dict(request)
        if "body" in sanitized and isinstance(sanitized["body"], dict):
            sanitized["body"] = self._sanitize_dict(sanitized["body"])
        if "params" in sanitized:
            sanitized["params"] = {k: str(v)[:2048] for k, v in sanitized["params"].items()}
        return sanitized

    def _sanitize_dict(self, data: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
        if depth > 10:
            return {}
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, str):
                sanitized[key] = self._sanitize_string(value)
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_dict(value, depth + 1)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_dict(item, depth + 1) if isinstance(item, dict)
                    else self._sanitize_string(str(item)) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                sanitized[key] = value
        return sanitized

    def _sanitize_string(self, value: str) -> str:
        return value.strip()[:10000]

    def update_allowed_methods(self, methods: Set[str]) -> None:
        self._allowed_methods = methods

    def update_max_body_size(self, size_bytes: int) -> None:
        self._max_body_size = size_bytes


class RateLimitingMiddleware:
    """Middleware for rate limiting requests based on various criteria."""

    def __init__(self, default_max_requests: int = 100,
                 default_window_seconds: int = 60) -> None:
        self._default_max_requests = default_max_requests
        self._default_window_seconds = default_window_seconds
        self._rate_limits: Dict[str, deque] = defaultdict(lambda: deque(maxlen=default_max_requests))
        self._custom_limits: Dict[str, Tuple[int, int]] = {}
        self._blocked_ips: Set[str] = set()
        self._blocked_users: Set[str] = set()
        self._violation_tracker: Dict[str, int] = defaultdict(int)

    def check_rate_limit(self, key: str, max_requests: Optional[int] = None,
                         window_seconds: Optional[int] = None) -> Tuple[bool, int]:
        max_r = max_requests or self._default_max_requests
        window = window_seconds or self._default_window_seconds
        now = time.time()
        window_start = now - window
        history = self._rate_limits[key]
        while history and history[0] < window_start:
            history.popleft()
        if len(history) >= max_r:
            retry_after = int(window - (now - history[0])) if history else window
            return False, retry_after
        history.append(now)
        return True, 0

    def record_request(self, key: str) -> None:
        self._rate_limits[key].append(time.time())

    def check_ip_rate_limit(self, ip: str) -> Tuple[bool, int]:
        if ip in self._blocked_ips:
            return False, -1
        return self.check_rate_limit(f"ip:{ip}")

    def check_user_rate_limit(self, user_id: str) -> Tuple[bool, int]:
        if user_id in self._blocked_users:
            return False, -1
        return self.check_rate_limit(f"user:{user_id}")

    def check_route_rate_limit(self, method: str, path: str) -> Tuple[bool, int]:
        route_key = f"{method}:{path}"
        custom = self._custom_limits.get(route_key)
        if custom:
            return self.check_rate_limit(f"route:{route_key}", max_requests=custom[0], window_seconds=custom[1])
        return self.check_rate_limit(f"route:{route_key}")

    def set_custom_rate_limit(self, route_key: str, max_requests: int, window_seconds: int) -> None:
        self._custom_limits[route_key] = (max_requests, window_seconds)

    def block_ip(self, ip: str) -> None:
        self._blocked_ips.add(ip)
        logger.warning(f"IP blocked: {ip}")

    def unblock_ip(self, ip: str) -> bool:
        return self._blocked_ips.discard(ip)

    def block_user(self, user_id: str) -> None:
        self._blocked_users.add(user_id)
        logger.warning(f"User blocked: {user_id}")

    def unblock_user(self, user_id: str) -> bool:
        return self._blocked_users.discard(user_id)

    def record_violation(self, key: str) -> None:
        self._violation_tracker[key] += 1

    def get_violation_count(self, key: str) -> int:
        return self._violation_tracker.get(key, 0)

    def is_ip_blocked(self, ip: str) -> bool:
        return ip in self._blocked_ips

    def is_user_blocked(self, user_id: str) -> bool:
        return user_id in self._blocked_users

    def get_rate_limit_status(self, key: str) -> Dict[str, Any]:
        history = list(self._rate_limits.get(key, []))
        now = time.time()
        window_start = now - self._default_window_seconds
        recent = [t for t in history if t > window_start]
        return {
            "key": key,
            "current_count": len(recent),
            "max_requests": self._default_max_requests,
            "window_seconds": self._default_window_seconds,
            "remaining": max(0, self._default_max_requests - len(recent)),
            "is_limited": len(recent) >= self._default_max_requests,
        }

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "default_max_requests": self._default_max_requests,
            "default_window_seconds": self._default_window_seconds,
            "active_rate_limits": len(self._rate_limits),
            "blocked_ips": len(self._blocked_ips),
            "blocked_users": len(self._blocked_users),
            "custom_limits": len(self._custom_limits),
            "violations": dict(self._violation_tracker),
        }

    def reset(self) -> None:
        self._rate_limits.clear()
        self._violation_tracker.clear()


class CORSHandlingMiddleware:
    """Middleware for handling Cross-Origin Resource Sharing (CORS)."""

    def __init__(self, allowed_origins: Optional[List[str]] = None,
                 allowed_methods: Optional[List[str]] = None,
                 allowed_headers: Optional[List[str]] = None,
                 allow_credentials: bool = True,
                 max_age: int = 3600) -> None:
        self._allowed_origins = allowed_origins or ["*"]
        self._allowed_methods = allowed_methods or ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
        self._allowed_headers = allowed_headers or [
            "Content-Type", "Authorization", "X-Request-ID", "X-API-Key",
            "Accept", "Origin", "X-Requested-With",
        ]
        self._allow_credentials = allow_credentials
        self._max_age = max_age
        self._exposed_headers: List[str] = [
            "X-Request-ID", "X-Response-Time-Ms", "Content-Length", "Content-Type",
        ]

    def handle_preflight(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if request.get("method", "").upper() != "OPTIONS":
            return None
        headers = request.get("headers", {})
        origin = headers.get("origin", "")
        request_method = headers.get("access-control-request-method", "")
        request_headers = headers.get("access-control-request-headers", "")

        if not self._is_origin_allowed(origin):
            return {"status_code": 403, "body": {"error": "Origin not allowed"}}

        if request_method and request_method not in self._allowed_methods:
            return {"status_code": 403, "body": {"error": f"Method {request_method} not allowed"}}

        response_headers = self._build_cors_headers(origin)
        return {
            "status_code": 200,
            "headers": response_headers,
            "body": {},
        }

    def add_cors_headers(self, response: Dict[str, Any],
                          request_origin: Optional[str] = None) -> Dict[str, Any]:
        if "headers" not in response:
            response["headers"] = {}
        if request_origin and self._is_origin_allowed(request_origin):
            cors_headers = self._build_cors_headers(request_origin)
            response["headers"].update(cors_headers)
        elif "*" in self._allowed_origins:
            response["headers"]["Access-Control-Allow-Origin"] = "*"
        return response

    def _is_origin_allowed(self, origin: str) -> bool:
        if "*" in self._allowed_origins:
            return True
        if origin in self._allowed_origins:
            return True
        for allowed in self._allowed_origins:
            if allowed.startswith("*.") and origin.endswith(allowed[1:]):
                return True
            if allowed.endswith("*") and origin.startswith(allowed[:-1]):
                return True
        return False

    def _build_cors_headers(self, origin: str) -> Dict[str, str]:
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": ", ".join(self._allowed_methods),
            "Access-Control-Allow-Headers": ", ".join(self._allowed_headers),
            "Access-Control-Max-Age": str(self._max_age),
        }
        if self._allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"
        if self._exposed_headers:
            headers["Access-Control-Expose-Headers"] = ", ".join(self._exposed_headers)
        return headers

    def update_allowed_origins(self, origins: List[str]) -> None:
        self._allowed_origins = origins

    def add_allowed_origin(self, origin: str) -> None:
        if origin not in self._allowed_origins:
            self._allowed_origins.append(origin)

    def get_allowed_origins(self) -> List[str]:
        return self._allowed_origins.copy()


class ErrorHandlingMiddleware:
    """Middleware for handling and formatting errors."""

    def __init__(self, include_traceback: bool = False) -> None:
        self._include_traceback = include_traceback
        self._error_handlers: Dict[type, Callable] = {}

    def handle_error(self, error: Exception, request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        for exc_type, handler in self._error_handlers.items():
            if isinstance(error, exc_type):
                return handler(error, request)
        return self._default_error_handler(error, request)

    def register_handler(self, exception_type: type, handler: Callable) -> None:
        self._error_handlers[exception_type] = handler

    def _default_error_handler(self, error: Exception,
                                request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        error_message = str(error) if str(error) else "Internal server error"
        status_code = 500
        if isinstance(error, ValueError):
            status_code = 400
        elif isinstance(error, PermissionError):
            status_code = 403
        elif isinstance(error, KeyError):
            status_code = 404
        body = {"error": error_message, "status_code": status_code}
        if self._include_traceback:
            body["traceback"] = traceback.format_exc()
        logger.error(f"Error handled: {error_message}")
        return {
            "status_code": status_code,
            "body": body,
            "headers": {"Content-Type": "application/json"},
        }

    def format_validation_error(self, errors: List[str]) -> Dict[str, Any]:
        return {
            "status_code": 422,
            "body": {
                "error": "Validation failed",
                "details": errors,
                "status_code": 422,
            },
            "headers": {"Content-Type": "application/json"},
        }

    def format_not_found(self, resource: str = "Resource") -> Dict[str, Any]:
        return {
            "status_code": 404,
            "body": {
                "error": f"{resource} not found",
                "status_code": 404,
            },
            "headers": {"Content-Type": "application/json"},
        }

    def format_unauthorized(self, message: str = "Unauthorized") -> Dict[str, Any]:
        return {
            "status_code": 401,
            "body": {
                "error": message,
                "status_code": 401,
            },
            "headers": {"Content-Type": "application/json"},
        }

    def format_forbidden(self, message: str = "Forbidden") -> Dict[str, Any]:
        return {
            "status_code": 403,
            "body": {
                "error": message,
                "status_code": 403,
            },
            "headers": {"Content-Type": "application/json"},
        }

    def format_rate_limited(self, retry_after: int = 60) -> Dict[str, Any]:
        return {
            "status_code": 429,
            "body": {
                "error": "Rate limit exceeded",
                "retry_after_seconds": retry_after,
                "status_code": 429,
            },
            "headers": {
                "Content-Type": "application/json",
                "Retry-After": str(retry_after),
            },
        }


class APIMiddleware:
    """
    API middleware pipeline providing request logging, request validation,
    rate limiting, CORS handling, error handling, request ID tracking,
    and response timing.

    Middleware components are executed in a configurable pipeline order.
    """

    def __init__(self) -> None:
        self._request_id = RequestIDMiddleware()
        self._timing = ResponseTimingMiddleware()
        self._logging = RequestLoggingMiddleware()
        self._validation = RequestValidationMiddleware()
        self._rate_limiting = RateLimitingMiddleware()
        self._cors = CORSHandlingMiddleware()
        self._error_handler = ErrorHandlingMiddleware()
        self._pipeline: List[MiddlewareType] = [
            MiddlewareType.PRE_REQUEST,
            MiddlewareType.POST_REQUEST,
            MiddlewareType.ERROR_HANDLER,
            MiddlewareType.RESPONSE_FORMATTER,
        ]

    @property
    def request_id(self) -> RequestIDMiddleware:
        return self._request_id

    @property
    def timing(self) -> ResponseTimingMiddleware:
        return self._timing

    @property
    def logging(self) -> RequestLoggingMiddleware:
        return self._logging

    @property
    def validation(self) -> RequestValidationMiddleware:
        return self._validation

    @property
    def rate_limiting(self) -> RateLimitingMiddleware:
        return self._rate_limiting

    @property
    def cors(self) -> CORSHandlingMiddleware:
        return self._cors

    @property
    def error_handler(self) -> ErrorHandlingMiddleware:
        return self._error_handler

    async def process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        request_id = self._request_id.process_request(request)
        self._timing.start_timer(request_id)
        ctx = self._logging.log_request(request, request_id)
        request["_ctx"] = ctx
        return request

    async def process_response(self, response: Dict[str, Any],
                                request: Dict[str, Any]) -> Dict[str, Any]:
        ctx: Optional[RequestContext] = request.get("_ctx")
        request_id = request.get("request_id", "")
        duration_ms = self._timing.stop_timer(request_id)
        response = self._timing.add_timing_header(response, duration_ms)
        response = self._request_id.process_response(response, request_id)
        request_origin = request.get("headers", {}).get("origin")
        response = self._cors.add_cors_headers(response, request_origin)
        if ctx:
            self._logging.log_response(ctx, response)
        return response

    async def process_error(self, error: Exception,
                             request: Dict[str, Any]) -> Dict[str, Any]:
        ctx: Optional[RequestContext] = request.get("_ctx")
        response = self._error_handler.handle_error(error, request)
        request_id = request.get("request_id", "")
        duration_ms = self._timing.stop_timer(request_id)
        response = self._timing.add_timing_header(response, duration_ms)
        response = self._request_id.process_response(response, request_id)
        if ctx:
            self._logging.log_error(ctx, error)
        return response

    async def handle_preflight(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._cors.handle_preflight(request)

    async def validate_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        errors = self._validation.validate_request(request)
        if errors:
            return self._error_handler.format_validation_error(errors)
        return None

    async def check_rate_limit(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ip = request.get("headers", {}).get("x-forwarded-for", "unknown")
        user_id = request.get("user_id")
        method = request.get("method", "GET")
        path = request.get("path", "/")

        ip_allowed, ip_retry = self._rate_limiting.check_ip_rate_limit(ip)
        if not ip_allowed:
            return self._error_handler.format_rate_limited(ip_retry if ip_retry > 0 else 60)

        if user_id:
            user_allowed, user_retry = self._rate_limiting.check_user_rate_limit(user_id)
            if not user_allowed:
                return self._error_handler.format_rate_limited(user_retry if user_retry > 0 else 60)

        route_allowed, route_retry = self._rate_limiting.check_route_rate_limit(method, path)
        if not route_allowed:
            return self._error_handler.format_rate_limited(route_retry if route_retry > 0 else 60)

        return None

    async def process_request_pipeline(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        preflight = await self.handle_preflight(request)
        if preflight:
            return preflight
        request = await self.process_request(request)
        validation_error = await self.validate_request(request)
        if validation_error:
            return validation_error
        rate_limit_error = await self.check_rate_limit(request)
        if rate_limit_error:
            return rate_limit_error
        return None

    async def process_response_pipeline(self, response: Dict[str, Any],
                                         request: Dict[str, Any]) -> Dict[str, Any]:
        return await self.process_response(response, request)

    async def process_error_pipeline(self, error: Exception,
                                      request: Dict[str, Any]) -> Dict[str, Any]:
        return await self.process_error(error, request)

    def get_middleware_statistics(self) -> Dict[str, Any]:
        return {
            "request_id": {"total_generated": len(self._request_id._timings) if hasattr(self._request_id, '_timings') else 0},
            "timing": self._timing.get_timing_statistics(),
            "logging": self._logging.get_log_statistics(),
            "rate_limiting": self._rate_limiting.get_statistics(),
            "cors": {
                "allowed_origins": self._cors.get_allowed_origins(),
                "allowed_methods": self._cors._allowed_methods,
            },
        }

    def reset(self) -> None:
        self._timing.clear_timings()
        self._logging.clear_logs()
        self._rate_limiting.reset()

    def set_pipeline_order(self, order: List[MiddlewareType]) -> None:
        self._pipeline = order
