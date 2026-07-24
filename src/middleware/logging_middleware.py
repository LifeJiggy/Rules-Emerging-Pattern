"""Structured logging middleware for the rules engine."""

import inspect
import json
import logging
import os
import sys
import time
import traceback
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)


class LogFormat(Enum):
    TEXT = "text"
    JSON = "json"
    STRUCTURED = "structured"


class LogEventType(Enum):
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"
    WARNING = "warning"
    AUDIT = "audit"
    METRIC = "metric"
    SYSTEM = "system"
    DEBUG = "debug"
    SECURITY = "security"
    PERFORMANCE = "performance"


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class ComponentLogConfig:
    level: LogLevel = LogLevel.INFO
    sampling_rate: float = 1.0
    mask_fields: List[str] = field(default_factory=lambda: [
        "password", "secret", "token", "authorization",
        "api_key", "access_key", "private_key", "session_id",
        "credit_card", "ssn", "phone", "email",
    ])
    enabled: bool = True
    include_body: bool = True
    include_headers: bool = True
    max_body_length: int = 4096


@dataclass
class LoggingConfig:
    format: LogFormat = LogFormat.JSON
    default_level: LogLevel = LogLevel.INFO
    enabled: bool = True
    log_to_file: bool = False
    log_to_stdout: bool = True
    log_directory: str = "logs"
    file_max_bytes: int = 10485760
    file_backup_count: int = 5
    use_rotation: bool = True
    rotation_interval: str = "midnight"
    component_configs: Dict[str, ComponentLogConfig] = field(default_factory=dict)
    global_mask_fields: List[str] = field(default_factory=lambda: [
        "password", "secret", "token", "authorization",
        "api_key", "access_key", "private_key", "session_id",
        "credit_card", "ssn", "phone", "email",
    ])
    include_timestamp: bool = True
    include_thread: bool = True
    include_process: bool = True
    include_hostname: bool = True
    timestamps_in_utc: bool = True
    correlation_id_header: str = "X-Correlation-ID"
    enable_sampling: bool = False
    default_sampling_rate: float = 1.0
    log_request_id: bool = True
    log_response_time: bool = True
    log_errors_with_stacktrace: bool = True
    sensitive_headers: List[str] = field(default_factory=lambda: [
        "authorization", "cookie", "set-cookie", "x-api-key",
        "proxy-authorization", "www-authenticate",
    ])
    redact_with: str = "***"
    max_log_line_length: int = 10000
    batch_size: int = 0
    batch_interval_ms: int = 1000
    async_logging: bool = False
    use_logger_context: bool = True
    component_field: str = "component"
    environment: str = "production"
    service_name: str = "rules-engine"
    log_sample_cache_size: int = 1000


@dataclass
class LogEntry:
    timestamp: str
    level: str
    component: str
    event_type: str
    message: str
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    duration_ms: Optional[float] = None
    status_code: Optional[int] = None
    method: Optional[str] = None
    route: Optional[str] = None
    ip_address: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    stacktrace: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None


class SensitiveDataMasker:
    def __init__(self, config: LoggingConfig):
        self.config = config
        self._mask_patterns: Dict[str, str] = {
            field: self.config.redact_with
            for field in config.global_mask_fields
        }

    def mask_value(self, value: str) -> str:
        if not value:
            return value
        if len(value) <= 4:
            return self.config.redact_with
        return value[:2] + self.config.redact_with + value[-2:]

    def mask_field_value(self, key: str, value: Any) -> Any:
        key_lower = key.lower()
        for sensitive in self.config.global_mask_fields:
            if sensitive in key_lower:
                if isinstance(value, str):
                    return self.mask_value(value)
                if isinstance(value, (int, float)):
                    return self.config.redact_with
                return value
        return value

    def mask_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        for key, value in data.items():
            if isinstance(value, dict):
                result[key] = self.mask_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self.mask_dict(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = self.mask_field_value(key, value)
        return result

    def mask_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        result = dict(headers)
        for header in self.config.sensitive_headers:
            header_lower = header.lower()
            for key in list(result.keys()):
                if key.lower() == header_lower:
                    result[key] = self.config.redact_with
        return result

    def mask_body(self, body: Any) -> Any:
        if isinstance(body, dict):
            return self.mask_dict(body)
        if isinstance(body, str):
            return body[: self.config.max_log_line_length]
        return body

    def add_mask_field(self, field: str) -> None:
        if field not in self.config.global_mask_fields:
            self.config.global_mask_fields.append(field)

    def remove_mask_field(self, field: str) -> None:
        self.config.global_mask_fields = [
            f for f in self.config.global_mask_fields if f != field
        ]


class LogSampler:
    def __init__(self, config: LoggingConfig):
        self.config = config
        self._counts: Dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def should_log(self, component: str, sampling_rate: Optional[float] = None) -> bool:
        if not self.config.enable_sampling:
            return True
        rate = sampling_rate or self.config.default_sampling_rate
        if rate >= 1.0:
            return True
        with self._lock:
            self._counts[component] += 1
            count = self._counts[component]
            if count > self.config.log_sample_cache_size:
                self._counts[component] = 0
            return (count % int(1.0 / rate)) == 0

    def reset_counts(self) -> None:
        with self._lock:
            self._counts.clear()

    def get_component_count(self, component: str) -> int:
        with self._lock:
            return self._counts.get(component, 0)


class LogRotator:
    def __init__(self, config: LoggingConfig):
        self.config = config
        self._handlers: Dict[str, logging.Handler] = {}

    def setup_rotation(self, logger_name: str, filename: str) -> logging.Handler:
        if not self.config.use_rotation:
            handler = logging.FileHandler(filename, encoding="utf-8")
        else:
            if self.config.rotation_interval == "midnight":
                handler = TimedRotatingFileHandler(
                    filename=filename,
                    when="midnight",
                    interval=1,
                    backupCount=self.config.file_backup_count,
                    encoding="utf-8",
                )
            else:
                handler = RotatingFileHandler(
                    filename=filename,
                    maxBytes=self.config.file_max_bytes,
                    backupCount=self.config.file_backup_count,
                    encoding="utf-8",
                )
        self._handlers[logger_name] = handler
        return handler

    def get_handler(self, logger_name: str) -> Optional[logging.Handler]:
        return self._handlers.get(logger_name)

    def close_all(self) -> None:
        for handler in self._handlers.values():
            handler.close()
        self._handlers.clear()


class JSONLogFormatter(logging.Formatter):
    def __init__(self, config: LoggingConfig):
        super().__init__()
        self.config = config

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if self.config.include_thread:
            log_data["thread"] = record.threadName
            log_data["thread_id"] = record.thread
        if self.config.include_process:
            log_data["process"] = record.processName
            log_data["process_id"] = record.process
        if self.config.include_hostname:
            log_data["hostname"] = os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "unknown")
        if record.exc_info and record.exc_info[0]:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "stacktrace": "".join(traceback.format_exception(*record.exc_info)),
            }
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)
        return json.dumps(log_data, default=str)


class StructuredLogFormatter:
    def __init__(self, config: LoggingConfig):
        self.config = config

    def format_entry(self, entry: LogEntry) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "timestamp": entry.timestamp,
            "level": entry.level,
            "component": entry.component,
            "event_type": entry.event_type,
            "message": entry.message,
        }
        if self.config.log_request_id and entry.request_id:
            data["request_id"] = entry.request_id
        if entry.correlation_id:
            data["correlation_id"] = entry.correlation_id
        if entry.duration_ms is not None:
            data["duration_ms"] = entry.duration_ms
        if entry.status_code is not None:
            data["status_code"] = entry.status_code
        if entry.method:
            data["method"] = entry.method
        if entry.route:
            data["route"] = entry.route
        if entry.ip_address:
            data["ip_address"] = entry.ip_address
        if entry.user_id:
            data["user_id"] = entry.user_id
        if entry.session_id:
            data["session_id"] = entry.session_id
        if entry.error:
            data["error"] = entry.error
        if entry.stacktrace:
            data["stacktrace"] = entry.stacktrace
        if entry.metadata:
            data["metadata"] = entry.metadata
        if entry.extra:
            data.update(entry.extra)
        data["environment"] = self.config.environment
        data["service"] = self.config.service_name
        return data

    def format_json(self, entry: LogEntry) -> str:
        data = self.format_entry(entry)
        return json.dumps(data, default=str)

    def format_text(self, entry: LogEntry) -> str:
        parts = [
            f"[{entry.timestamp}]",
            f"[{entry.level}]",
            f"[{entry.component}]",
            entry.message,
        ]
        if entry.duration_ms is not None:
            parts.append(f"({entry.duration_ms:.1f}ms)")
        if entry.error:
            parts.append(f"ERROR: {entry.error}")
        return " ".join(parts)


class LoggingMiddleware:
    def __init__(self, config: Optional[LoggingConfig] = None):
        self.config = config or LoggingConfig()
        self.masker = SensitiveDataMasker(self.config)
        self.sampler = LogSampler(self.config)
        self.rotator = LogRotator(self.config)
        self.formatter = StructuredLogFormatter(self.config)
        self._correlation_id: Optional[str] = None
        self._request_count = 0
        self._error_count = 0
        self._start_time = time.time()
        self._component_loggers: Dict[str, logging.Logger] = {}
        self._setup_logging()
        logger.info(
            "LoggingMiddleware initialized with format=%s, level=%s",
            self.config.format.value, self.config.default_level.value,
        )

    def _setup_logging(self) -> None:
        root_logger = logging.getLogger()
        if self.config.default_level == LogLevel.DEBUG:
            root_logger.setLevel(logging.DEBUG)
        elif self.config.default_level == LogLevel.INFO:
            root_logger.setLevel(logging.INFO)
        elif self.config.default_level == LogLevel.WARNING:
            root_logger.setLevel(logging.WARNING)
        elif self.config.default_level == LogLevel.ERROR:
            root_logger.setLevel(logging.ERROR)
        elif self.config.default_level == LogLevel.CRITICAL:
            root_logger.setLevel(logging.CRITICAL)

        if self.config.log_to_stdout:
            console_handler = logging.StreamHandler(sys.stdout)
            if self.config.format == LogFormat.JSON:
                console_handler.setFormatter(JSONLogFormatter(self.config))
            else:
                console_handler.setFormatter(logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                ))
            root_logger.addHandler(console_handler)

        if self.config.log_to_file:
            os.makedirs(self.config.log_directory, exist_ok=True)
            file_path = os.path.join(
                self.config.log_directory,
                f"{self.config.service_name}.log",
            )
            file_handler = self.rotator.setup_rotation("root", file_path)
            if self.config.format == LogFormat.JSON:
                file_handler.setFormatter(JSONLogFormatter(self.config))
            else:
                file_handler.setFormatter(logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                ))
            root_logger.addHandler(file_handler)

    def get_component_logger(self, component: str) -> logging.Logger:
        if component not in self._component_loggers:
            comp_logger = logging.getLogger(f"{__name__}.{component}")
            comp_config = self.config.component_configs.get(component, ComponentLogConfig())
            level = comp_config.level.value
            if level == "DEBUG":
                comp_logger.setLevel(logging.DEBUG)
            elif level == "INFO":
                comp_logger.setLevel(logging.INFO)
            elif level == "WARNING":
                comp_logger.setLevel(logging.WARNING)
            elif level == "ERROR":
                comp_logger.setLevel(logging.ERROR)
            self._component_loggers[component] = comp_logger
        return self._component_loggers[component]

    def log_request(self, request: Dict[str, Any], component: str = "core") -> str:
        correlation_id = request.get("headers", {}).get(
            self.config.correlation_id_header,
            str(uuid.uuid4()),
        )
        self._correlation_id = correlation_id
        self._request_count += 1

        comp_config = self.config.component_configs.get(component, ComponentLogConfig())
        if not comp_config.enabled:
            return correlation_id
        if not self.sampler.should_log(component, comp_config.sampling_rate):
            return correlation_id

        method = request.get("method", "UNKNOWN")
        route = request.get("route", "unknown")
        ip = request.get("headers", {}).get("X-Forwarded-For", request.get("headers", {}).get("X-Real-IP", "unknown"))
        user_id = request.get("user_id")

        headers = None
        if comp_config.include_headers and "headers" in request:
            headers = self.masker.mask_headers(request["headers"])
        body = None
        if comp_config.include_body and "body" in request:
            body = self.masker.mask_body(request["body"])
            if isinstance(body, (dict, list)):
                body_str = json.dumps(body, default=str)
                if len(body_str) > comp_config.max_body_length:
                    body = body_str[: comp_config.max_body_length] + "..."
            elif isinstance(body, str) and len(body) > comp_config.max_body_length:
                body = body[: comp_config.max_body_length] + "..."

        metadata: Dict[str, Any] = {}
        if headers:
            metadata["headers"] = headers
        if body is not None:
            metadata["body"] = body
        if user_id:
            metadata["user_id"] = user_id

        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=LogLevel.INFO.value,
            component=component,
            event_type=LogEventType.REQUEST.value,
            message=f"{method} {route}",
            correlation_id=correlation_id,
            method=method,
            route=route,
            ip_address=ip,
            user_id=user_id,
            metadata=metadata if metadata else None,
        )

        structured = self.formatter.format_entry(entry)
        comp_logger = self.get_component_logger(component)
        comp_logger.info("Request: %s %s", method, route, extra={"extra_fields": structured})
        return correlation_id

    def log_response(
        self,
        response: Dict[str, Any],
        request: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
        component: str = "core",
    ) -> None:
        comp_config = self.config.component_configs.get(component, ComponentLogConfig())
        if not comp_config.enabled:
            return
        if not self.sampler.should_log(component, comp_config.sampling_rate):
            return

        status_code = response.get("status_code", 200)
        method = request.get("method", "UNKNOWN") if request else "UNKNOWN"
        route = request.get("route", "unknown") if request else "unknown"
        user_id = request.get("user_id") if request else None

        if status_code >= 400:
            self._error_count += 1

        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=LogLevel.ERROR.value if status_code >= 500 else LogLevel.WARNING.value if status_code >= 400 else LogLevel.INFO.value,
            component=component,
            event_type=LogEventType.RESPONSE.value,
            message=f"{method} {route} -> {status_code}",
            correlation_id=self._correlation_id,
            status_code=status_code,
            duration_ms=duration_ms,
            method=method,
            route=route,
            user_id=user_id,
            error=response.get("error") if status_code >= 400 else None,
        )

        structured = self.formatter.format_entry(entry)
        comp_logger = self.get_component_logger(component)
        if status_code >= 500:
            comp_logger.error("Response: %s %s -> %s", method, route, status_code, extra={"extra_fields": structured})
        elif status_code >= 400:
            comp_logger.warning("Response: %s %s -> %s", method, route, status_code, extra={"extra_fields": structured})
        else:
            comp_logger.info("Response: %s %s -> %s", method, route, status_code, extra={"extra_fields": structured})

    def log_error(
        self,
        error: Union[str, Exception],
        component: str = "core",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._error_count += 1
        comp_config = self.config.component_configs.get(component, ComponentLogConfig())
        if not comp_config.enabled:
            return

        error_message = str(error)
        stacktrace_str = None
        if isinstance(error, Exception) and self.config.log_errors_with_stacktrace:
            stacktrace_str = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=LogLevel.ERROR.value,
            component=component,
            event_type=LogEventType.ERROR.value,
            message=f"Error in {component}: {error_message}",
            correlation_id=self._correlation_id,
            error=error_message,
            stacktrace=stacktrace_str,
            metadata=metadata,
        )

        structured = self.formatter.format_entry(entry)
        comp_logger = self.get_component_logger(component)
        comp_logger.error("Error: %s", error_message, extra={"extra_fields": structured})

    def log_security_event(
        self,
        event: str,
        component: str = "security",
        severity: str = "warning",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=severity.upper(),
            component=component,
            event_type=LogEventType.SECURITY.value,
            message=event,
            correlation_id=self._correlation_id,
            metadata=metadata,
        )

        structured = self.formatter.format_entry(entry)
        comp_logger = self.get_component_logger(component)
        if severity.upper() == "CRITICAL":
            comp_logger.critical("Security: %s", event, extra={"extra_fields": structured})
        elif severity.upper() == "ERROR":
            comp_logger.error("Security: %s", event, extra={"extra_fields": structured})
        else:
            comp_logger.warning("Security: %s", event, extra={"extra_fields": structured})

    def log_performance(
        self,
        operation: str,
        duration_ms: float,
        component: str = "performance",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta = {"duration_ms": duration_ms}
        if metadata:
            meta.update(metadata)
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=LogLevel.INFO.value,
            component=component,
            event_type=LogEventType.PERFORMANCE.value,
            message=f"{operation} took {duration_ms:.2f}ms",
            correlation_id=self._correlation_id,
            duration_ms=duration_ms,
            metadata=meta,
        )

        structured = self.formatter.format_entry(entry)
        comp_logger = self.get_component_logger(component)
        comp_logger.info("Performance: %s %.2fms", operation, duration_ms, extra={"extra_fields": structured})

    def log_audit(
        self,
        action: str,
        user_id: str,
        resource: str,
        component: str = "audit",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=LogLevel.INFO.value,
            component=component,
            event_type=LogEventType.AUDIT.value,
            message=f"Audit: {action} on {resource} by {user_id}",
            correlation_id=self._correlation_id,
            user_id=user_id,
            metadata={"action": action, "resource": resource, **(metadata or {})},
        )

        structured = self.formatter.format_entry(entry)
        comp_logger = self.get_component_logger(component)
        comp_logger.info("Audit: %s %s %s", action, resource, user_id, extra={"extra_fields": structured})

    def log_metric(
        self,
        metric_name: str,
        value: float,
        component: str = "metrics",
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=LogLevel.INFO.value,
            component=component,
            event_type=LogEventType.METRIC.value,
            message=f"Metric: {metric_name} = {value}",
            correlation_id=self._correlation_id,
            metadata={"metric": metric_name, "value": value, "tags": tags or {}},
        )

        structured = self.formatter.format_entry(entry)
        comp_logger = self.get_component_logger(component)
        comp_logger.info("Metric: %s = %s", metric_name, value, extra={"extra_fields": structured})

    def log_system_event(
        self,
        event: str,
        component: str = "system",
        level: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=level.upper(),
            component=component,
            event_type=LogEventType.SYSTEM.value,
            message=event,
            correlation_id=self._correlation_id,
            metadata=metadata,
        )

        structured = self.formatter.format_entry(entry)
        comp_logger = self.get_component_logger(component)
        log_method = getattr(comp_logger, level.lower(), comp_logger.info)
        log_method("System: %s", event, extra={"extra_fields": structured})

    def log_raw(
        self,
        level: str,
        message: str,
        component: str = "core",
        **kwargs: Any,
    ) -> None:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=level.upper(),
            component=component,
            event_type=LogEventType.SYSTEM.value,
            message=message,
            correlation_id=self._correlation_id,
            extra=kwargs if kwargs else None,
        )

        structured = self.formatter.format_entry(entry)
        comp_logger = self.get_component_logger(component)
        log_method = getattr(comp_logger, level.lower(), comp_logger.info)
        log_method(message, extra={"extra_fields": structured})

    def mask_sensitive(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.masker.mask_dict(data)

    def mask_string(self, value: str) -> str:
        return self.masker.mask_value(value)

    def set_correlation_id(self, correlation_id: str) -> None:
        self._correlation_id = correlation_id

    def get_correlation_id(self) -> Optional[str]:
        return self._correlation_id

    def add_mask_field(self, field: str) -> None:
        self.masker.add_mask_field(field)

    def remove_mask_field(self, field: str) -> None:
        self.masker.remove_mask_field(field)

    def configure_component(
        self,
        component: str,
        level: Optional[LogLevel] = None,
        sampling_rate: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        if component not in self.config.component_configs:
            self.config.component_configs[component] = ComponentLogConfig()
        comp_config = self.config.component_configs[component]
        if level is not None:
            comp_config.level = level
        if sampling_rate is not None:
            comp_config.sampling_rate = sampling_rate
        if enabled is not None:
            comp_config.enabled = enabled

    def enable_component_logging(self, component: str) -> None:
        self.configure_component(component, enabled=True)

    def disable_component_logging(self, component: str) -> None:
        self.configure_component(component, enabled=False)

    def set_sampling_rate(self, component: str, rate: float) -> None:
        self.configure_component(component, sampling_rate=rate)

    def reset_sampling(self) -> None:
        self.sampler.reset_counts()

    def get_stats(self) -> Dict[str, Any]:
        uptime = time.time() - self._start_time
        return {
            "requests": self._request_count,
            "errors": self._error_count,
            "uptime_seconds": round(uptime, 2),
            "format": self.config.format.value,
            "enabled": self.config.enabled,
            "log_to_file": self.config.log_to_file,
            "log_to_stdout": self.config.log_to_stdout,
            "use_rotation": self.config.use_rotation,
            "sampling_enabled": self.config.enable_sampling,
            "components_configured": len(self.config.component_configs),
            "mask_fields": len(self.config.global_mask_fields),
            "start_time": datetime.fromtimestamp(self._start_time, tz=timezone.utc).isoformat(),
        }

    def get_component_config(self, component: str) -> Optional[ComponentLogConfig]:
        return self.config.component_configs.get(component)

    def list_components(self) -> List[str]:
        return list(self.config.component_configs.keys())

    def update_config(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    def reset_config(self) -> None:
        self.config = LoggingConfig()
        self.masker = SensitiveDataMasker(self.config)
        self.sampler = LogSampler(self.config)
        self.rotator = LogRotator(self.config)
        self.formatter = StructuredLogFormatter(self.config)

    def flush(self) -> None:
        for handler in logging.getLogger().handlers:
            handler.flush()

    def close(self) -> None:
        self.rotator.close_all()

    def export_stats_json(self) -> str:
        return json.dumps(self.get_stats(), indent=2)

    def get_request_count(self) -> int:
        return self._request_count

    def get_error_count(self) -> int:
        return self._error_count

    def get_uptime(self) -> float:
        return time.time() - self._start_time

    def format_log_entry(self, entry: LogEntry) -> str:
        return self.formatter.format_json(entry)

    def format_log_text(self, entry: LogEntry) -> str:
        return self.formatter.format_text(entry)

    def create_log_entry(
        self,
        level: str,
        component: str,
        message: str,
        event_type: str = "system",
        **kwargs: Any,
    ) -> LogEntry:
        return LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=level.upper(),
            component=component,
            event_type=event_type,
            message=message,
            correlation_id=self._correlation_id,
            **kwargs,
        )

    def log_batch(self, entries: List[LogEntry]) -> None:
        for entry in entries:
            self.formatter.format_json(entry)

    def should_sample(self, component: str, rate: Optional[float] = None) -> bool:
        return self.sampler.should_log(component, rate)

    def current_timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def __repr__(self) -> str:
        return (
            f"LoggingMiddleware(format={self.config.format.value}, "
            f"level={self.config.default_level.value}, "
            f"requests={self._request_count}, errors={self._error_count})"
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
