"""Request/response validation middleware for the rules engine."""

import html
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple, Union

logger = logging.getLogger(__name__)


class ValidationMode(Enum):
    STRICT = "strict"
    PERMISSIVE = "permissive"
    SANITIZE = "sanitize"
    REJECT = "reject"


class ContentType(Enum):
    JSON = "application/json"
    TEXT = "text/plain"
    HTML = "text/html"
    XML = "application/xml"
    FORM = "application/x-www-form-urlencoded"
    BINARY = "application/octet-stream"


@dataclass
class ValidationRule:
    field: str
    pattern: Optional[str] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    required: bool = False
    allowed_values: Optional[List[Any]] = None
    type_check: Optional[str] = None


@dataclass
class ValidationConfig:
    mode: ValidationMode = ValidationMode.SANITIZE
    max_request_size: int = 1048576
    max_depth: int = 10
    allowed_content_types: List[str] = field(default_factory=lambda: [
        "application/json", "text/plain", "application/x-www-form-urlencoded"
    ])
    strip_html: bool = True
    normalize_whitespace: bool = True
    sanitize_headers: bool = True
    validate_utf8: bool = True
    max_string_length: int = 65536
    blocked_patterns: List[str] = field(default_factory=lambda: [
        r"<script[^>]*>.*?</script>",
        r"on\w+\s*=",
        r"javascript\s*:",
        r"vbscript\s*:",
        r"expression\s*\(",
    ])
    metadata_fields: List[str] = field(default_factory=lambda: [
        "request_id", "timestamp", "client_ip", "user_agent",
        "content_type", "content_length", "route", "api_version"
    ])
    enable_request_enrichment: bool = True
    enable_response_formatting: bool = True
    enable_content_sanitization: bool = True
    strip_null_bytes: bool = True
    normalize_unicode: bool = True
    max_parameters: int = 100
    max_array_elements: int = 1000
    blocked_headers: List[str] = field(default_factory=lambda: [
        "x-forwarded-for", "x-real-ip", "x-forwarded-proto",
        "transfer-encoding", "proxy-", "x-auth-token"
    ])
    allowed_methods: List[str] = field(default_factory=lambda: [
        "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"
    ])
    validate_content_type: bool = True
    coerce_types: bool = False


@dataclass
class ValidatedRequest:
    original: Dict[str, Any]
    sanitized: Dict[str, Any]
    metadata: Dict[str, Any]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    valid: bool = True
    duration_ms: float = 0.0


@dataclass
class ValidatedResponse:
    original: Dict[str, Any]
    formatted: Dict[str, Any]
    status_code: int = 200
    headers: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    valid: bool = True


class HTMLSanitizer:
    def __init__(self, config: ValidationConfig):
        self.config = config
        self._blocked_regexes: List[Pattern] = [
            re.compile(p, re.IGNORECASE | re.DOTALL)
            for p in config.blocked_patterns
        ]

    def strip_html_tags(self, text: str) -> str:
        if not self.config.strip_html:
            return text
        text = re.sub(r"<[^>]*>", "", text)
        return text

    def remove_script_tags(self, text: str) -> str:
        for pattern in self._blocked_regexes:
            text = pattern.sub("", text)
        return text

    def sanitize_attribute(self, text: str) -> str:
        text = re.sub(r"on\w+\s*=\s*['\"][^'\"]*['\"]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"on\w+\s*=\s*\S+", "", text, flags=re.IGNORECASE)
        return text

    def sanitize_url(self, url: str) -> str:
        url = re.sub(r"javascript\s*:", "", url, flags=re.IGNORECASE)
        url = re.sub(r"vbscript\s*:", "", url, flags=re.IGNORECASE)
        url = re.sub(r"data\s*:", "", url, flags=re.IGNORECASE)
        return url

    def sanitize(self, text: str) -> str:
        text = self.strip_html_tags(text)
        text = self.remove_script_tags(text)
        text = self.sanitize_attribute(text)
        text = self.sanitize_url(text)
        text = html.escape(text)
        return text


class WhitespaceNormalizer:
    @staticmethod
    def normalize(text: str) -> str:
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"\r", "\n", text)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"\t", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        return text

    @staticmethod
    def normalize_lines(text: str, max_line_length: int = 1024) -> str:
        lines = text.split("\n")
        normalized = []
        for line in lines:
            if len(line) > max_line_length:
                line = line[:max_line_length] + "..."
            normalized.append(line)
        return "\n".join(normalized)

    @staticmethod
    def collapse_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def strip_control_chars(text: str) -> str:
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


class ContentSanitizer:
    def __init__(self, config: ValidationConfig):
        self.config = config
        self.html_sanitizer = HTMLSanitizer(config)
        self.whitespace = WhitespaceNormalizer()

    def sanitize_string(self, value: str) -> str:
        if self.config.strip_null_bytes:
            value = value.replace("\x00", "")
        if self.config.normalize_unicode:
            value = value.encode("utf-8", errors="replace").decode("utf-8")
        if self.config.strip_html:
            value = self.html_sanitizer.sanitize(value)
        if self.config.normalize_whitespace:
            value = self.whitespace.normalize(value)
        if self.config.max_string_length and len(value) > self.config.max_string_length:
            value = value[: self.config.max_string_length]
        return value

    def sanitize_value(self, value: Any, depth: int = 0) -> Any:
        if depth > self.config.max_depth:
            return None
        if isinstance(value, str):
            return self.sanitize_string(value)
        elif isinstance(value, dict):
            return {
                k: self.sanitize_value(v, depth + 1)
                for k, v in value.items()
                if isinstance(k, str)
            }
        elif isinstance(value, list):
            result = []
            for item in value[: self.config.max_array_elements]:
                result.append(self.sanitize_value(item, depth + 1))
            return result
        elif isinstance(value, (int, float, bool)):
            return value
        elif value is None:
            return None
        else:
            try:
                return str(value)
            except Exception:
                return None

    def sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        sanitized = {}
        blocked_lower = [h.lower() for h in self.config.blocked_headers]
        for key, value in headers.items():
            key_lower = key.lower()
            if any(b in key_lower for b in blocked_lower):
                logger.warning("Blocked header stripped: %s", key)
                continue
            sanitized[key] = self.sanitize_string(value)
        return sanitized


class TypeCoercer:
    def __init__(self, config: ValidationConfig):
        self.config = config

    def coerce(self, value: Any, target_type: str) -> Any:
        if not self.config.coerce_types:
            return value
        try:
            if target_type == "int":
                return int(value)
            elif target_type == "float":
                return float(value)
            elif target_type == "bool":
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes", "on")
                return bool(value)
            elif target_type == "str":
                return str(value)
            elif target_type == "list":
                if isinstance(value, list):
                    return value
                return [value]
            elif target_type == "dict":
                if isinstance(value, dict):
                    return value
                if isinstance(value, str):
                    return json.loads(value)
                return {}
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            logger.warning("Type coercion failed for %s -> %s: %s", value, target_type, e)
            return value
        return value


class RequestEnricher:
    def __init__(self, config: ValidationConfig):
        self.config = config

    def enrich(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not self.config.enable_request_enrichment:
            return request
        metadata = {}
        metadata["request_id"] = str(uuid.uuid4())
        metadata["timestamp"] = datetime.utcnow().isoformat() + "Z"
        metadata["received_at"] = time.time()
        metadata["processing_deadline"] = time.time() + 30.0
        if "headers" in request and isinstance(request["headers"], dict):
            metadata["client_ip"] = request["headers"].get("X-Forwarded-For", request["headers"].get("X-Real-IP", "unknown"))
            metadata["user_agent"] = request["headers"].get("User-Agent", "unknown")
            metadata["content_type"] = request["headers"].get("Content-Type", "unknown")
            content_length = request["headers"].get("Content-Length", "0")
            try:
                metadata["content_length"] = int(content_length)
            except (ValueError, TypeError):
                metadata["content_length"] = 0
        if "route" in request:
            metadata["route"] = request["route"]
        metadata["api_version"] = request.get("api_version", "v1")
        metadata["origin"] = request.get("origin", "unknown")
        metadata["protocol"] = request.get("protocol", "http")
        metadata["method"] = request.get("method", "GET")
        enriched = dict(request)
        enriched["_metadata"] = metadata
        return enriched


class ResponseFormatter:
    def __init__(self, config: ValidationConfig):
        self.config = config

    def format_success(self, data: Any, status_code: int = 200) -> ValidatedResponse:
        body = {
            "success": True,
            "data": data,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        return ValidatedResponse(
            original=data if isinstance(data, dict) else {"data": data},
            formatted=body,
            status_code=status_code,
            headers={"Content-Type": "application/json"},
        )

    def format_error(self, message: str, status_code: int = 400, details: Optional[Dict[str, Any]] = None) -> ValidatedResponse:
        body = {
            "success": False,
            "error": message,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        if details:
            body["details"] = details
        return ValidatedResponse(
            original={"error": message, "details": details},
            formatted=body,
            status_code=status_code,
            headers={"Content-Type": "application/json"},
        )

    def format_validation_error(self, errors: List[str]) -> ValidatedResponse:
        return self.format_error(
            message="Validation failed",
            status_code=422,
            details={"validation_errors": errors},
        )

    def format_paginated(self, data: List[Any], total: int, page: int, per_page: int) -> ValidatedResponse:
        body = {
            "success": True,
            "data": data,
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": max(1, (total + per_page - 1) // per_page),
            },
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        return ValidatedResponse(
            original={"data": data, "total": total, "page": page, "per_page": per_page},
            formatted=body,
            status_code=200,
            headers={"Content-Type": "application/json"},
        )

    def format_response(self, response: Dict[str, Any]) -> ValidatedResponse:
        if not self.config.enable_response_formatting:
            return ValidatedResponse(
                original=response,
                formatted=response,
                status_code=response.get("status_code", 200),
            )
        if "error" in response or "errors" in response:
            return self.format_error(
                message=response.get("error", str(response.get("errors", []))),
                status_code=response.get("status_code", 400),
            )
        return self.format_success(
            data=response.get("data", response),
            status_code=response.get("status_code", 200),
        )


class ValidationMiddleware:
    def __init__(self, config: Optional[ValidationConfig] = None):
        self.config = config or ValidationConfig()
        self.sanitizer = ContentSanitizer(self.config)
        self.coercer = TypeCoercer(self.config)
        self.enricher = RequestEnricher(self.config)
        self.formatter = ResponseFormatter(self.config)
        self._rules: Dict[str, List[ValidationRule]] = {}
        self._chain: List[Dict[str, Any]] = []
        logger.info(
            "ValidationMiddleware initialized with mode=%s, strip_html=%s",
            self.config.mode.value, self.config.strip_html,
        )

    def add_rule(self, route: str, rule: ValidationRule) -> None:
        if route not in self._rules:
            self._rules[route] = []
        self._rules[route].append(rule)
        logger.debug("Added validation rule for route=%s field=%s", route, rule.field)

    def add_rules(self, route: str, rules: List[ValidationRule]) -> None:
        for rule in rules:
            self.add_rule(route, rule)

    def add_middleware(self, name: str, handler: Callable, order: int = 0, enabled: bool = True) -> None:
        entry = {"name": name, "handler": handler, "order": order, "enabled": enabled}
        self._chain.append(entry)
        self._chain.sort(key=lambda x: x["order"])
        logger.debug("Added middleware '%s' at order %d", name, order)

    def remove_middleware(self, name: str) -> bool:
        before = len(self._chain)
        self._chain = [m for m in self._chain if m["name"] != name]
        return len(self._chain) < before

    def get_chain(self) -> List[Dict[str, Any]]:
        return list(self._chain)

    def clear_chain(self) -> None:
        self._chain.clear()
        logger.debug("Middleware chain cleared")

    def enable_middleware(self, name: str) -> bool:
        for m in self._chain:
            if m["name"] == name:
                m["enabled"] = True
                return True
        return False

    def disable_middleware(self, name: str) -> bool:
        for m in self._chain:
            if m["name"] == name:
                m["enabled"] = False
                return True
        return False

    def validate_request(self, request: Dict[str, Any]) -> ValidatedRequest:
        start = time.time()
        errors: List[str] = []
        warnings: List[str] = []
        sanitized: Dict[str, Any] = {}
        metadata: Dict[str, Any] = {}

        if not isinstance(request, dict):
            errors.append("Request must be a dictionary")
            return ValidatedRequest(
                original={}, sanitized={}, metadata={},
                errors=errors, valid=False, duration_ms=0.0,
            )

        if self.config.enable_request_enrichment:
            enriched = self.enricher.enrich(request)
            metadata = enriched.get("_metadata", {})
            request = {k: v for k, v in enriched.items() if k != "_metadata"}

        method = request.get("method", "GET").upper()
        if method not in self.config.allowed_methods:
            errors.append(f"HTTP method '{method}' not allowed")

        headers = request.get("headers", {})
        if isinstance(headers, dict) and self.config.sanitize_headers:
            headers = self.sanitizer.sanitize_headers(headers)

        body = request.get("body", {})
        if body is not None and self.config.enable_content_sanitization:
            try:
                sanitized_body = self.sanitizer.sanitize_value(body)
                if sanitized_body is not None:
                    sanitized["body"] = sanitized_body
                else:
                    errors.append("Body sanitization produced empty result")
            except Exception as e:
                errors.append(f"Body sanitization failed: {e}")
                sanitized["body"] = body
        else:
            sanitized["body"] = body

        query = request.get("query", {})
        if isinstance(query, dict):
            sanitized_query = {}
            for k, v in query.items():
                if len(sanitized_query) >= self.config.max_parameters:
                    warnings.append(f"Max query parameters ({self.config.max_parameters}) exceeded, truncating")
                    break
                if self.config.enable_content_sanitization:
                    sanitized_query[k] = self.sanitizer.sanitize_value(v)
                else:
                    sanitized_query[k] = v
            sanitized["query"] = sanitized_query
        else:
            sanitized["query"] = query

        params = request.get("params", {})
        if isinstance(params, dict):
            sanitized_params = {}
            for k, v in params.items():
                if len(sanitized_params) >= self.config.max_parameters:
                    warnings.append(f"Max path params ({self.config.max_parameters}) exceeded, truncating")
                    break
                if self.config.enable_content_sanitization:
                    sanitized_params[k] = self.sanitizer.sanitize_value(v)
                else:
                    sanitized_params[k] = v
            sanitized["params"] = sanitized_params
        else:
            sanitized["params"] = params

        route = request.get("route", "")
        if route in self._rules:
            for rule in self._rules[route]:
                field_value = self._get_nested(sanitized, rule.field)
                if rule.required and field_value is None:
                    errors.append(f"Required field '{rule.field}' is missing")
                    continue
                if field_value is not None:
                    if rule.min_length is not None and isinstance(field_value, (str, list)):
                        if len(field_value) < rule.min_length:
                            errors.append(f"Field '{rule.field}' too short (min={rule.min_length})")
                    if rule.max_length is not None and isinstance(field_value, (str, list)):
                        if len(field_value) > rule.max_length:
                            errors.append(f"Field '{rule.field}' too long (max={rule.max_length})")
                    if rule.pattern is not None and isinstance(field_value, str):
                        if not re.match(rule.pattern, field_value):
                            errors.append(f"Field '{rule.field}' does not match pattern '{rule.pattern}'")
                    if rule.allowed_values is not None and field_value not in rule.allowed_values:
                        errors.append(f"Field '{rule.field}' has invalid value '{field_value}'")
                    if rule.type_check is not None:
                        coerced = self.coercer.coerce(field_value, rule.type_check)
                        sanitized = self._set_nested(sanitized, rule.field, coerced)

        content_type = headers.get("Content-Type", "").split(";")[0].strip()
        if self.config.validate_content_type and content_type:
            if content_type not in self.config.allowed_content_types:
                errors.append(f"Content-Type '{content_type}' not allowed")

        body_size = 0
        try:
            body_str = json.dumps(request.get("body", {}))
            body_size = len(body_str.encode("utf-8"))
        except (TypeError, UnicodeEncodeError):
            body_size = len(str(request.get("body", "")))
        if body_size > self.config.max_request_size:
            errors.append(f"Request body size {body_size} exceeds max {self.config.max_request_size}")

        duration = (time.time() - start) * 1000

        validated = ValidatedRequest(
            original=request,
            sanitized=sanitized,
            metadata=metadata,
            errors=errors,
            warnings=warnings,
            valid=len(errors) == 0,
            duration_ms=round(duration, 3),
        )

        if validated.valid and self._chain:
            validated = self._run_chain(validated)

        return validated

    def _run_chain(self, request: ValidatedRequest) -> ValidatedRequest:
        current = request
        for entry in self._chain:
            if not entry["enabled"]:
                continue
            try:
                result = entry["handler"](current)
                if isinstance(result, ValidatedRequest):
                    current = result
                if not current.valid:
                    logger.warning("Middleware '%s' marked request invalid", entry["name"])
                    break
            except Exception as e:
                logger.error("Middleware '%s' failed: %s", entry["name"], e)
                current.errors.append(f"Middleware '{entry['name']}' failed: {e}")
                current.valid = False
                break
        return current

    def post_process(self, result: ValidatedResponse) -> ValidatedResponse:
        if not result.valid:
            return self.formatter.format_validation_error(result.errors)
        formatted = self.formatter.format_response(result.formatted)
        formatted.headers["X-Request-Id"] = str(uuid.uuid4())
        formatted.headers["X-Processed-At"] = datetime.utcnow().isoformat() + "Z"
        return formatted

    def process_request(self, request: Dict[str, Any]) -> ValidatedRequest:
        logger.debug("Processing request: method=%s route=%s", request.get("method"), request.get("route"))
        validated = self.validate_request(request)
        if not validated.valid:
            logger.warning("Request validation failed: %s", validated.errors)
        else:
            logger.debug("Request validated in %.3fms", validated.duration_ms)
        return validated

    def process_response(self, response: Dict[str, Any]) -> ValidatedResponse:
        logger.debug("Processing response: status=%s", response.get("status_code"))
        formatted = self.formatter.format_response(response)
        return formatted

    def sanitize_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        validated = self.validate_request(request)
        return validated.sanitized

    def sanitize_string(self, text: str) -> str:
        return self.sanitizer.sanitize_string(text)

    def validate_json_schema(self, data: Dict[str, Any], schema: Dict[str, Any]) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        self._validate_schema(data, schema, errors, "$")
        return len(errors) == 0, errors

    def _validate_schema(self, data: Any, schema: Dict[str, Any], errors: List[str], path: str) -> None:
        if "type" in schema:
            expected = schema["type"]
            if expected == "object" and not isinstance(data, dict):
                errors.append(f"{path}: expected object, got {type(data).__name__}")
                return
            if expected == "array" and not isinstance(data, list):
                errors.append(f"{path}: expected array, got {type(data).__name__}")
                return
            if expected == "string" and not isinstance(data, str):
                errors.append(f"{path}: expected string, got {type(data).__name__}")
                return
            if expected == "number" and not isinstance(data, (int, float)):
                errors.append(f"{path}: expected number, got {type(data).__name__}")
                return
            if expected == "integer" and not isinstance(data, int):
                errors.append(f"{path}: expected integer, got {type(data).__name__}")
                return
            if expected == "boolean" and not isinstance(data, bool):
                errors.append(f"{path}: expected boolean, got {type(data).__name__}")
                return
        if "required" in schema and isinstance(data, dict):
            for field in schema["required"]:
                if field not in data:
                    errors.append(f"{path}: missing required field '{field}'")
        if "properties" in schema and isinstance(data, dict):
            for key, prop_schema in schema["properties"].items():
                if key in data:
                    self._validate_schema(data[key], prop_schema, errors, f"{path}.{key}")
        if "items" in schema and isinstance(data, list):
            for i, item in enumerate(data):
                self._validate_schema(item, schema["items"], errors, f"{path}[{i}]")
        if "enum" in schema and data is not None:
            if data not in schema["enum"]:
                errors.append(f"{path}: value '{data}' not in enum {schema['enum']}")
        if "minimum" in schema and isinstance(data, (int, float)):
            if data < schema["minimum"]:
                errors.append(f"{path}: value {data} less than minimum {schema['minimum']}")
        if "maximum" in schema and isinstance(data, (int, float)):
            if data > schema["maximum"]:
                errors.append(f"{path}: value {data} greater than maximum {schema['maximum']}")
        if "minLength" in schema and isinstance(data, str):
            if len(data) < schema["minLength"]:
                errors.append(f"{path}: length {len(data)} less than minLength {schema['minLength']}")
        if "maxLength" in schema and isinstance(data, str):
            if len(data) > schema["maxLength"]:
                errors.append(f"{path}: length {len(data)} greater than maxLength {schema['maxLength']}")
        if "pattern" in schema and isinstance(data, str):
            if not re.match(schema["pattern"], data):
                errors.append(f"{path}: does not match pattern '{schema['pattern']}'")

    def _get_nested(self, data: Dict[str, Any], path: str) -> Any:
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _set_nested(self, data: Dict[str, Any], path: str, value: Any) -> Dict[str, Any]:
        parts = path.split(".")
        current = data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
        return data

    def get_config(self) -> ValidationConfig:
        return self.config

    def update_config(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info("ValidationConfig.%s updated to %s", key, value)

    def reset_config(self) -> None:
        self.config = ValidationConfig()
        self.sanitizer = ContentSanitizer(self.config)
        self.coercer = TypeCoercer(self.config)
        self.enricher = RequestEnricher(self.config)
        self.formatter = ResponseFormatter(self.config)
        logger.info("ValidationConfig reset to defaults")

    def validate_batch(self, requests: List[Dict[str, Any]]) -> List[ValidatedRequest]:
        results = []
        for req in requests:
            results.append(self.validate_request(req))
        return results

    def get_stats(self) -> Dict[str, Any]:
        return {
            "mode": self.config.mode.value,
            "strip_html": self.config.strip_html,
            "normalize_whitespace": self.config.normalize_whitespace,
            "max_request_size": self.config.max_request_size,
            "max_depth": self.config.max_depth,
            "enrichment_enabled": self.config.enable_request_enrichment,
            "response_formatting_enabled": self.config.enable_response_formatting,
            "sanitization_enabled": self.config.enable_content_sanitization,
            "rules_count": sum(len(rules) for rules in self._rules.values()),
            "chain_length": len(self._chain),
            "blocked_patterns_count": len(self.config.blocked_patterns),
            "allowed_methods": self.config.allowed_methods,
            "allowed_content_types": self.config.allowed_content_types,
        }

    def validate_content_type(self, content_type: str) -> bool:
        base = content_type.split(";")[0].strip()
        return base in self.config.allowed_content_types

    def validate_utf8(self, data: bytes) -> bool:
        if not self.config.validate_utf8:
            return True
        try:
            data.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False

    def normalize_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(request)
        if "method" in normalized:
            normalized["method"] = normalized["method"].upper()
        if "headers" in normalized and isinstance(normalized["headers"], dict):
            normalized["headers"] = {k.title(): v for k, v in normalized["headers"].items()}
        return normalized

    def check_blocked_patterns(self, text: str) -> List[str]:
        matches = []
        for pattern in self.config.blocked_patterns:
            compiled = re.compile(pattern, re.IGNORECASE | re.DOTALL)
            found = compiled.findall(text)
            if found:
                matches.append(pattern)
        return matches

    def strip_sensitive_fields(self, data: Dict[str, Any], sensitive_keys: Optional[List[str]] = None) -> Dict[str, Any]:
        if sensitive_keys is None:
            sensitive_keys = ["password", "secret", "token", "api_key", "authorization"]
        result = dict(data)
        for key in list(result.keys()):
            key_lower = key.lower()
            if any(s in key_lower for s in sensitive_keys):
                result[key] = "***REDACTED***"
            elif isinstance(result[key], dict):
                result[key] = self.strip_sensitive_fields(result[key], sensitive_keys)
        return result

    def extract_metadata(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return self.enricher.enrich(request).get("_metadata", {})

    def format_as_json(self, data: Any, pretty: bool = False) -> str:
        if pretty:
            return json.dumps(data, indent=2, default=str)
        return json.dumps(data, default=str)

    def parse_body(self, body: Union[str, bytes, Dict[str, Any], None]) -> Dict[str, Any]:
        if body is None:
            return {}
        if isinstance(body, dict):
            return body
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        if isinstance(body, str):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"text": body}
        return {}

    def deep_validate(self, request: Dict[str, Any], depth: int = 0) -> List[str]:
        errors = []
        if depth > self.config.max_depth:
            errors.append("Maximum validation depth exceeded")
            return errors
        if not isinstance(request, dict):
            errors.append("Root element must be a dictionary")
            return errors
        for key, value in request.items():
            if not isinstance(key, str):
                errors.append(f"Key '{key}' is not a string")
            if isinstance(value, dict):
                errors.extend(self.deep_validate(value, depth + 1))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        errors.extend(self.deep_validate(item, depth + 1))
        return errors

    def validate_method(self, method: str) -> bool:
        return method.upper() in self.config.allowed_methods

    def validate_size(self, data: Union[str, bytes, Dict[str, Any], List[Any]]) -> bool:
        try:
            if isinstance(data, (str, bytes)):
                size = len(data)
            else:
                size = len(json.dumps(data).encode("utf-8"))
            return size <= self.config.max_request_size
        except (TypeError, ValueError):
            return False

    def __repr__(self) -> str:
        return (
            f"ValidationMiddleware(mode={self.config.mode.value}, "
            f"rules={sum(len(r) for r in self._rules.values())}, "
            f"chain={len(self._chain)})"
        )
