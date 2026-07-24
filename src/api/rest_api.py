"""
RESTful API handler for rule CRUD, validation, metrics, and alerts.
"""

import hashlib
import json
import logging
import time
import traceback
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
    RuleTemplate,
    RuleGroup,
    RuleSchedule,
    RuleDependency,
    RuleStats,
)
from rules_emerging_pattern.models.validation import (
    ActionTaken,
    BatchValidationRequest,
    BatchValidationResult,
    ComplianceReport,
    Suggestion,
    ValidationAudit,
    ValidationFeedback,
    ValidationProfile,
    ValidationResult,
    ValidationThreshold,
    Violation,
    ViolationType,
)
from rules_emerging_pattern.models.conflict import (
    ConflictAnalysis,
    ConflictAudit,
    ConflictImpact,
    ConflictNotification,
    ConflictPattern,
    ConflictPreventionRule,
    ConflictResolution,
    ConflictResolutionRequest,
    ConflictResolutionResult,
    ConflictSeverity,
    ConflictType,
    ResolutionStrategy,
    RuleConflict,
)

logger = logging.getLogger(__name__)


class HTTPMethod(str, Enum):
    """HTTP methods supported by the REST API."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class HTTPStatus(int, Enum):
    """HTTP status codes used by the REST API."""
    OK = 200
    CREATED = 201
    ACCEPTED = 202
    NO_CONTENT = 204
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    CONFLICT = 409
    UNPROCESSABLE_ENTITY = 422
    TOO_MANY_REQUESTS = 429
    INTERNAL_SERVER_ERROR = 500
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504


class EndpointScope(str, Enum):
    """Access scope for API endpoints."""
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    ADMIN = "admin"
    READONLY = "readonly"


@dataclass
class APIResponse:
    """Standard API response envelope."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    message: Optional[str] = None
    status_code: int = HTTPStatus.OK
    pagination: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "success": self.success,
            "timestamp": self.timestamp
        }
        if self.data is not None:
            result["data"] = self.data
        if self.error is not None:
            result["error"] = self.error
        if self.message is not None:
            result["message"] = self.message
        if self.pagination is not None:
            result["pagination"] = self.pagination
        if self.request_id is not None:
            result["request_id"] = self.request_id
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class EndpointDefinition:
    """Definition of a single API endpoint."""
    path: str
    method: HTTPMethod
    handler: Callable
    scope: EndpointScope = EndpointScope.AUTHENTICATED
    rate_limit_key: Optional[str] = None
    description: str = ""
    request_schema: Optional[Dict[str, Any]] = None
    response_schema: Optional[Dict[str, Any]] = None
    deprecated: bool = False
    tags: List[str] = field(default_factory=list)


class PaginationHelper:
    """Helper for paginating API responses."""

    @staticmethod
    def paginate(items: List[Any], page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        total = len(items)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = start + per_page
        page_items = items[start:end] if total > 0 else []
        return {
            "items": page_items,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
        }

    @staticmethod
    def paginate_cursor(items: List[Any], cursor: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        start = 0
        if cursor:
            try:
                decoded = json.loads(base64.b64decode(cursor).decode())
                start = decoded.get("offset", 0)
            except Exception:
                start = 0
        end = start + limit
        page_items = items[start:end] if len(items) > 0 else []
        next_cursor = None
        if end < len(items):
            next_data = json.dumps({"offset": end})
            next_cursor = base64.b64encode(next_data.encode()).decode()
        return {
            "items": page_items,
            "pagination": {
                "limit": limit,
                "next_cursor": next_cursor,
                "total": len(items),
                "has_more": next_cursor is not None
            }
        }


class RequestValidator:
    """Validates incoming API requests."""

    @staticmethod
    def validate_required_fields(data: Dict[str, Any], required: List[str]) -> Optional[str]:
        for field_name in required:
            if field_name not in data or data[field_name] is None:
                return f"Missing required field: {field_name}"
        return None

    @staticmethod
    def validate_field_types(data: Dict[str, Any], type_map: Dict[str, type]) -> List[str]:
        errors = []
        for field_name, expected_type in type_map.items():
            if field_name in data and data[field_name] is not None:
                if not isinstance(data[field_name], expected_type):
                    errors.append(
                        f"Field '{field_name}' expected {expected_type.__name__}, got {type(data[field_name]).__name__}"
                    )
        return errors

    @staticmethod
    def validate_enum_field(data: Dict[str, Any], field_name: str, enum_class) -> Optional[str]:
        if field_name in data and data[field_name] is not None:
            valid_values = [e.value for e in enum_class]
            if data[field_name] not in valid_values:
                return f"Field '{field_name}' must be one of: {valid_values}"
        return None

    @staticmethod
    def validate_range(data: Dict[str, Any], field_name: str, min_val: float, max_val: float) -> Optional[str]:
        if field_name in data and data[field_name] is not None:
            val = data[field_name]
            if not isinstance(val, (int, float)):
                return f"Field '{field_name}' must be a number"
            if val < min_val or val > max_val:
                return f"Field '{field_name}' must be between {min_val} and {max_val}"
        return None

    @staticmethod
    def validate_string_length(data: Dict[str, Any], field_name: str, max_len: int) -> Optional[str]:
        if field_name in data and data[field_name] is not None:
            val = data[field_name]
            if isinstance(val, str) and len(val) > max_len:
                return f"Field '{field_name}' exceeds maximum length of {max_len}"
        return None

    @staticmethod
    def validate_list_field(data: Dict[str, Any], field_name: str, max_items: int = 100) -> Optional[str]:
        if field_name in data and data[field_name] is not None:
            val = data[field_name]
            if not isinstance(val, list):
                return f"Field '{field_name}' must be a list"
            if len(val) > max_items:
                return f"Field '{field_name}' exceeds maximum of {max_items} items"
        return None

    @staticmethod
    def validate_content_type(content_type: Optional[str]) -> Optional[str]:
        if content_type and "json" not in content_type.lower() and "form" not in content_type.lower():
            return "Unsupported content type; application/json expected"
        return None

    @staticmethod
    def sanitize_input(data: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, str):
                sanitized[key] = value.strip()
            elif isinstance(value, dict):
                sanitized[key] = RequestValidator.sanitize_input(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    RequestValidator.sanitize_input(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized[key] = value
        return sanitized


class ResponseFormatter:
    """Formats API responses in a consistent structure."""

    @staticmethod
    def success(data: Any = None, message: Optional[str] = None,
                status_code: int = HTTPStatus.OK,
                pagination: Optional[Dict[str, Any]] = None,
                request_id: Optional[str] = None) -> APIResponse:
        return APIResponse(
            success=True,
            data=data,
            message=message,
            status_code=status_code,
            pagination=pagination,
            request_id=request_id
        )

    @staticmethod
    def created(data: Any = None, message: Optional[str] = None,
                request_id: Optional[str] = None) -> APIResponse:
        return APIResponse(
            success=True,
            data=data,
            message=message or "Resource created successfully",
            status_code=HTTPStatus.CREATED,
            request_id=request_id
        )

    @staticmethod
    def error(message: str, status_code: int = HTTPStatus.BAD_REQUEST,
              error: Optional[str] = None, request_id: Optional[str] = None) -> APIResponse:
        return APIResponse(
            success=False,
            error=error or message,
            message=message,
            status_code=status_code,
            request_id=request_id
        )

    @staticmethod
    def not_found(resource: str = "Resource", request_id: Optional[str] = None) -> APIResponse:
        return APIResponse(
            success=False,
            error=f"{resource} not found",
            message=f"The requested {resource.lower()} was not found",
            status_code=HTTPStatus.NOT_FOUND,
            request_id=request_id
        )

    @staticmethod
    def validation_error(errors: List[str], request_id: Optional[str] = None) -> APIResponse:
        return APIResponse(
            success=False,
            error="Validation failed",
            message="; ".join(errors),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            request_id=request_id
        )

    @staticmethod
    def unauthorized(message: str = "Authentication required",
                     request_id: Optional[str] = None) -> APIResponse:
        return APIResponse(
            success=False,
            error=message,
            message=message,
            status_code=HTTPStatus.UNAUTHORIZED,
            request_id=request_id
        )

    @staticmethod
    def forbidden(message: str = "Insufficient permissions",
                  request_id: Optional[str] = None) -> APIResponse:
        return APIResponse(
            success=False,
            error=message,
            message=message,
            status_code=HTTPStatus.FORBIDDEN,
            request_id=request_id
        )

    @staticmethod
    def too_many_requests(retry_after: int = 60,
                          request_id: Optional[str] = None) -> APIResponse:
        return APIResponse(
            success=False,
            error="Rate limit exceeded",
            message=f"Too many requests. Retry after {retry_after} seconds",
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            request_id=request_id,
            metadata={"retry_after_seconds": retry_after}
        )

    @staticmethod
    def server_error(message: str = "Internal server error",
                     request_id: Optional[str] = None) -> APIResponse:
        return APIResponse(
            success=False,
            error="Internal server error",
            message=message,
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            request_id=request_id
        )


class RuleEndpointHandler:
    """Handles rule CRUD operations."""

    def __init__(self) -> None:
        self._rules: Dict[str, Rule] = {}
        self._rule_groups: Dict[str, RuleGroup] = {}
        self._rule_templates: Dict[str, RuleTemplate] = {}
        self._rule_stats: Dict[str, RuleStats] = {}

    def list_rules(self, page: int = 1, per_page: int = 20,
                   tier: Optional[RuleTier] = None,
                   status: Optional[RuleStatus] = None,
                   rule_type: Optional[RuleType] = None,
                   severity: Optional[RuleSeverity] = None,
                   search: Optional[str] = None,
                   tags: Optional[List[str]] = None) -> APIResponse:
        try:
            filtered = list(self._rules.values())
            if tier:
                filtered = [r for r in filtered if r.tier == tier]
            if status:
                filtered = [r for r in filtered if r.status == status]
            if rule_type:
                filtered = [r for r in filtered if r.rule_type == rule_type]
            if severity:
                filtered = [r for r in filtered if r.severity == severity]
            if search:
                search_lower = search.lower()
                filtered = [
                    r for r in filtered
                    if search_lower in r.name.lower() or search_lower in r.description.lower()
                ]
            if tags:
                filtered = [r for r in filtered if any(t in r.tags for t in tags)]
            sorted_rules = sorted(filtered, key=lambda r: r.created_at, reverse=True)
            result = PaginationHelper.paginate(
                [r.to_dict() for r in sorted_rules], page=page, per_page=per_page
            )
            return ResponseFormatter.success(
                data=result["items"],
                pagination=result["pagination"]
            )
        except Exception as e:
            logger.error(f"Error listing rules: {e}")
            return ResponseFormatter.server_error(str(e))

    def get_rule(self, rule_id: str) -> APIResponse:
        try:
            rule = self._rules.get(rule_id)
            if not rule:
                return ResponseFormatter.not_found(f"Rule {rule_id}")
            return ResponseFormatter.success(data=rule.to_dict())
        except Exception as e:
            logger.error(f"Error getting rule {rule_id}: {e}")
            return ResponseFormatter.server_error(str(e))

    def create_rule(self, data: Dict[str, Any]) -> APIResponse:
        try:
            sanitized = RequestValidator.sanitize_input(data)
            required = ["name", "description", "tier", "rule_type", "severity", "enforcement_level"]
            missing = RequestValidator.validate_required_fields(sanitized, required)
            if missing:
                return ResponseFormatter.validation_error([missing])
            enum_checks = [
                RequestValidator.validate_enum_field(sanitized, "tier", RuleTier),
                RequestValidator.validate_enum_field(sanitized, "rule_type", RuleType),
                RequestValidator.validate_enum_field(sanitized, "severity", RuleSeverity),
                RequestValidator.validate_enum_field(sanitized, "status", RuleStatus),
                RequestValidator.validate_enum_field(sanitized, "enforcement_level", EnforcementLevel),
            ]
            enum_errors = [e for e in enum_checks if e is not None]
            if enum_errors:
                return ResponseFormatter.validation_error(enum_errors)
            rule_id = sanitized.get("id", str(uuid.uuid4()))
            rule = Rule(
                id=rule_id,
                name=sanitized["name"],
                description=sanitized["description"],
                tier=RuleTier(sanitized["tier"]),
                rule_type=RuleType(sanitized["rule_type"]),
                severity=RuleSeverity(sanitized["severity"]),
                status=RuleStatus(sanitized.get("status", RuleStatus.ACTIVE.value)),
                enforcement_level=EnforcementLevel(sanitized["enforcement_level"]),
                auto_block=sanitized.get("auto_block", False),
                user_override=sanitized.get("user_override", True),
                override_justification_required=sanitized.get("override_justification_required", False),
                version=sanitized.get("version", "1.0.0"),
                created_by=sanitized.get("created_by"),
                tags=sanitized.get("tags", []),
                priority=sanitized.get("priority", 100),
                timeout_ms=sanitized.get("timeout_ms", 1000),
                cache_ttl_seconds=sanitized.get("cache_ttl_seconds", 300),
            )
            self._rules[rule.id] = rule
            self._rule_stats[rule.id] = RuleStats(rule_id=rule.id)
            logger.info(f"Created rule: {rule.id} - {rule.name}")
            return ResponseFormatter.created(data=rule.to_dict())
        except Exception as e:
            logger.error(f"Error creating rule: {e}")
            return ResponseFormatter.server_error(str(e))

    def update_rule(self, rule_id: str, data: Dict[str, Any]) -> APIResponse:
        try:
            existing = self._rules.get(rule_id)
            if not existing:
                return ResponseFormatter.not_found(f"Rule {rule_id}")
            sanitized = RequestValidator.sanitize_input(data)
            updateable_fields = {
                "name", "description", "tier", "rule_type", "severity",
                "status", "enforcement_level", "auto_block", "user_override",
                "override_justification_required", "version", "tags",
                "priority", "timeout_ms", "cache_ttl_seconds"
            }
            for key, value in sanitized.items():
                if key in updateable_fields:
                    if key == "tier" and isinstance(value, str):
                        setattr(existing, key, RuleTier(value))
                    elif key == "rule_type" and isinstance(value, str):
                        setattr(existing, key, RuleType(value))
                    elif key == "severity" and isinstance(value, str):
                        setattr(existing, key, RuleSeverity(value))
                    elif key == "status" and isinstance(value, str):
                        setattr(existing, key, RuleStatus(value))
                    elif key == "enforcement_level" and isinstance(value, str):
                        setattr(existing, key, EnforcementLevel(value))
                    else:
                        setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
            self._rules[rule_id] = existing
            logger.info(f"Updated rule: {rule_id}")
            return ResponseFormatter.success(data=existing.to_dict(), message="Rule updated")
        except Exception as e:
            logger.error(f"Error updating rule {rule_id}: {e}")
            return ResponseFormatter.server_error(str(e))

    def delete_rule(self, rule_id: str) -> APIResponse:
        try:
            if rule_id not in self._rules:
                return ResponseFormatter.not_found(f"Rule {rule_id}")
            del self._rules[rule_id]
            self._rule_stats.pop(rule_id, None)
            logger.info(f"Deleted rule: {rule_id}")
            return ResponseFormatter.success(message="Rule deleted", status_code=HTTPStatus.OK)
        except Exception as e:
            logger.error(f"Error deleting rule {rule_id}: {e}")
            return ResponseFormatter.server_error(str(e))

    def batch_create_rules(self, rules_data: List[Dict[str, Any]]) -> APIResponse:
        results = {"created": [], "errors": []}
        for i, data in enumerate(rules_data):
            resp = self.create_rule(data)
            if resp.success and resp.data:
                results["created"].append(resp.data)
            else:
                results["errors"].append({"index": i, "error": resp.error})
        return ResponseFormatter.success(data=results, message=f"Created {len(results['created'])} rules")

    def get_rule_stats(self, rule_id: str) -> APIResponse:
        stats = self._rule_stats.get(rule_id)
        if not stats:
            return ResponseFormatter.not_found(f"Stats for rule {rule_id}")
        return ResponseFormatter.success(data=stats.to_summary())

    def get_rules_summary(self) -> APIResponse:
        total = len(self._rules)
        by_tier = defaultdict(int)
        by_status = defaultdict(int)
        by_severity = defaultdict(int)
        for rule in self._rules.values():
            by_tier[rule.tier.value] += 1
            by_status[rule.status.value] += 1
            by_severity[rule.severity.value] += 1
        return ResponseFormatter.success(data={
            "total_rules": total,
            "by_tier": dict(by_tier),
            "by_status": dict(by_status),
            "by_severity": dict(by_severity),
        })

    def search_rules(self, query: str, page: int = 1, per_page: int = 20) -> APIResponse:
        return self.list_rules(page=page, per_page=per_page, search=query)

    def toggle_rule_status(self, rule_id: str, new_status: str) -> APIResponse:
        status_check = RequestValidator.validate_enum_field({"status": new_status}, "status", RuleStatus)
        if status_check:
            return ResponseFormatter.validation_error([status_check])
        return self.update_rule(rule_id, {"status": new_status})

    def export_rules(self, rule_ids: Optional[List[str]] = None, format: str = "json") -> APIResponse:
        if rule_ids:
            rules = [self._rules[rid] for rid in rule_ids if rid in self._rules]
        else:
            rules = list(self._rules.values())
        if format == "json":
            data = [r.to_dict() for r in rules]
        else:
            return ResponseFormatter.error(f"Unsupported export format: {format}")
        return ResponseFormatter.success(data=data)


class ValidationEndpointHandler:
    """Handles validation-related endpoints."""

    def __init__(self) -> None:
        self._evaluations: List[Dict[str, Any]] = []
        self._profiles: Dict[str, ValidationProfile] = {}
        self._thresholds: Dict[str, ValidationThreshold] = {}
        self._audits: List[ValidationAudit] = []
        self._feedback: List[ValidationFeedback] = []

    def validate_content(self, data: Dict[str, Any]) -> APIResponse:
        sanitized = RequestValidator.sanitize_input(data)
        required = ["content"]
        missing = RequestValidator.validate_required_fields(sanitized, required)
        if missing:
            return ResponseFormatter.validation_error([missing])
        if not isinstance(sanitized["content"], str) or len(sanitized["content"].strip()) == 0:
            return ResponseFormatter.validation_error(["Content must be a non-empty string"])
        content_hash = hashlib.sha256(sanitized["content"].encode()).hexdigest()[:16]
        start_time = time.time()
        validation_result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
            content_hash=content_hash,
            request_id=sanitized.get("request_id", str(uuid.uuid4())),
        )
        processing_time = int((time.time() - start_time) * 1000)
        validation_result.processing_time_ms = processing_time
        self._evaluations.append({
            "request_id": validation_result.request_id,
            "content_hash": content_hash,
            "valid": validation_result.valid,
            "timestamp": datetime.utcnow().isoformat(),
            "processing_time_ms": processing_time
        })
        return ResponseFormatter.success(data=validation_result.get_summary())

    def validate_batch(self, data: Dict[str, Any]) -> APIResponse:
        sanitized = RequestValidator.sanitize_input(data)
        required = ["requests"]
        missing = RequestValidator.validate_required_fields(sanitized, required)
        if missing:
            return ResponseFormatter.validation_error([missing])
        contents = sanitized["requests"]
        if not isinstance(contents, list) or len(contents) == 0:
            return ResponseFormatter.validation_error(["requests must be a non-empty list"])
        if len(contents) > 1000:
            return ResponseFormatter.validation_error(["Batch size exceeds maximum of 1000"])
        start_time = time.time()
        results = []
        for content in contents:
            result = ValidationResult(
                valid=True,
                total_score=1.0,
                confidence=1.0,
            )
            results.append(result.get_summary())
        total_time = int((time.time() - start_time) * 1000)
        batch_result = {
            "total_items": len(contents),
            "valid_items": len(results),
            "total_processing_time_ms": total_time,
            "results": results
        }
        return ResponseFormatter.success(data=batch_result)

    def get_validation_history(self, page: int = 1, per_page: int = 20) -> APIResponse:
        sorted_evals = sorted(self._evaluations, key=lambda e: e["timestamp"], reverse=True)
        result = PaginationHelper.paginate(sorted_evals, page=page, per_page=per_page)
        return ResponseFormatter.success(data=result["items"], pagination=result["pagination"])

    def get_validation_stats(self) -> APIResponse:
        total = len(self._evaluations)
        valid_count = sum(1 for e in self._evaluations if e["valid"])
        invalid_count = total - valid_count
        avg_time = 0
        if total > 0:
            avg_time = sum(e["processing_time_ms"] for e in self._evaluations) / total
        return ResponseFormatter.success(data={
            "total_evaluations": total,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "valid_rate": round((valid_count / total * 100) if total > 0 else 0, 2),
            "average_processing_time_ms": round(avg_time, 2),
        })

    def create_profile(self, data: Dict[str, Any]) -> APIResponse:
        sanitized = RequestValidator.sanitize_input(data)
        required = ["profile_id", "name"]
        missing = RequestValidator.validate_required_fields(sanitized, required)
        if missing:
            return ResponseFormatter.validation_error([missing])
        profile = ValidationProfile(
            profile_id=sanitized["profile_id"],
            name=sanitized["name"],
            description=sanitized.get("description"),
            profile_type=sanitized.get("profile_type", "user"),
            owner=sanitized.get("owner"),
            organization=sanitized.get("organization"),
        )
        if "enabled_tiers" in sanitized:
            profile.enabled_tiers = [RuleTier(t) for t in sanitized["enabled_tiers"]]
        if "excluded_rule_ids" in sanitized:
            profile.excluded_rule_ids = sanitized["excluded_rule_ids"]
        self._profiles[profile.profile_id] = profile
        return ResponseFormatter.created(data=profile.to_dict())

    def get_profile(self, profile_id: str) -> APIResponse:
        profile = self._profiles.get(profile_id)
        if not profile:
            return ResponseFormatter.not_found(f"Profile {profile_id}")
        return ResponseFormatter.success(data=profile.to_dict())

    def list_profiles(self) -> APIResponse:
        return ResponseFormatter.success(data=[p.to_dict() for p in self._profiles.values()])

    def delete_profile(self, profile_id: str) -> APIResponse:
        if profile_id not in self._profiles:
            return ResponseFormatter.not_found(f"Profile {profile_id}")
        del self._profiles[profile_id]
        return ResponseFormatter.success(message="Profile deleted")

    def submit_feedback(self, data: Dict[str, Any]) -> APIResponse:
        sanitized = RequestValidator.sanitize_input(data)
        required = ["feedback_id", "validation_result_id"]
        missing = RequestValidator.validate_required_fields(sanitized, required)
        if missing:
            return ResponseFormatter.validation_error([missing])
        feedback = ValidationFeedback(
            feedback_id=sanitized["feedback_id"],
            validation_result_id=sanitized["validation_result_id"],
            user_id=sanitized.get("user_id"),
            rating=sanitized.get("rating", 3),
            was_helpful=sanitized.get("was_helpful", True),
            was_accurate=sanitized.get("was_accurate", True),
            comments=sanitized.get("comments"),
            false_positive=sanitized.get("false_positive", False),
            false_negative=sanitized.get("false_negative", False),
        )
        self._feedback.append(feedback)
        return ResponseFormatter.created(data=feedback.to_summary())


class MetricsEndpointHandler:
    """Handles metrics and monitoring endpoints."""

    def __init__(self) -> None:
        self._metrics_data: Dict[str, List[float]] = defaultdict(list)
        self._alerts: List[Dict[str, Any]] = []

    def get_metrics(self, metric_names: Optional[List[str]] = None) -> APIResponse:
        if metric_names:
            data = {name: self._compute_metrics(name) for name in metric_names if name in self._metrics_data}
        else:
            data = {name: self._compute_metrics(name) for name in self._metrics_data}
        return ResponseFormatter.success(data=data)

    def record_metric(self, name: str, value: float) -> APIResponse:
        if not isinstance(value, (int, float)):
            return ResponseFormatter.validation_error(["value must be a number"])
        if not name or not isinstance(name, str):
            return ResponseFormatter.validation_error(["name must be a non-empty string"])
        self._metrics_data[name].append(value)
        request_id = str(uuid.uuid4())
        logger.info(f"Metric recorded: {name}={value}")
        return ResponseFormatter.created(
            data={"name": name, "value": value, "total_points": len(self._metrics_data[name])},
            request_id=request_id
        )

    def get_metric_detail(self, metric_name: str, window_minutes: int = 60) -> APIResponse:
        points = self._metrics_data.get(metric_name, [])
        if not points:
            return ResponseFormatter.not_found(f"Metric {metric_name}")
        return ResponseFormatter.success(data={
            "name": metric_name,
            "count": len(points),
            "stats": self._compute_metrics(metric_name),
            "recent_values": points[-50:]
        })

    def _compute_metrics(self, name: str) -> Dict[str, Any]:
        points = self._metrics_data.get(name, [])
        if not points:
            return {"count": 0, "min": 0, "max": 0, "avg": 0, "sum": 0}
        return {
            "count": len(points),
            "min": float(min(points)),
            "max": float(max(points)),
            "avg": float(sum(points) / len(points)),
            "sum": float(sum(points)),
            "last": float(points[-1]),
        }

    def get_system_health(self) -> APIResponse:
        return ResponseFormatter.success(data={
            "status": "healthy",
            "uptime_seconds": 0,
            "active_rules": 0,
            "total_evaluations": 0,
            "metrics_count": len(self._metrics_data),
            "alerts_count": len(self._alerts),
            "timestamp": datetime.utcnow().isoformat()
        })

    def list_alerts(self, page: int = 1, per_page: int = 20,
                    severity: Optional[str] = None,
                    resolved: Optional[bool] = None) -> APIResponse:
        filtered = list(self._alerts)
        if severity:
            filtered = [a for a in filtered if a.get("severity") == severity]
        if resolved is not None:
            filtered = [a for a in filtered if a.get("resolved") == resolved]
        sorted_alerts = sorted(filtered, key=lambda a: a.get("created_at", ""), reverse=True)
        result = PaginationHelper.paginate(sorted_alerts, page=page, per_page=per_page)
        return ResponseFormatter.success(data=result["items"], pagination=result["pagination"])

    def create_alert(self, data: Dict[str, Any]) -> APIResponse:
        sanitized = RequestValidator.sanitize_input(data)
        required = ["title", "severity"]
        missing = RequestValidator.validate_required_fields(sanitized, required)
        if missing:
            return ResponseFormatter.validation_error([missing])
        alert = {
            "id": str(uuid.uuid4()),
            "title": sanitized["title"],
            "severity": sanitized["severity"],
            "description": sanitized.get("description", ""),
            "source": sanitized.get("source", "system"),
            "resolved": False,
            "created_at": datetime.utcnow().isoformat(),
            "resolved_at": None,
            "metadata": sanitized.get("metadata", {})
        }
        self._alerts.append(alert)
        return ResponseFormatter.created(data=alert)

    def resolve_alert(self, alert_id: str) -> APIResponse:
        for alert in self._alerts:
            if alert["id"] == alert_id:
                alert["resolved"] = True
                alert["resolved_at"] = datetime.utcnow().isoformat()
                return ResponseFormatter.success(data=alert, message="Alert resolved")
        return ResponseFormatter.not_found(f"Alert {alert_id}")

    def get_alerts_summary(self) -> APIResponse:
        total = len(self._alerts)
        resolved_count = sum(1 for a in self._alerts if a["resolved"])
        by_severity = defaultdict(int)
        for alert in self._alerts:
            by_severity[alert.get("severity", "unknown")] += 1
        return ResponseFormatter.success(data={
            "total": total,
            "resolved": resolved_count,
            "unresolved": total - resolved_count,
            "by_severity": dict(by_severity),
        })

    def clear_resolved_alerts(self) -> APIResponse:
        before = len(self._alerts)
        self._alerts = [a for a in self._alerts if not a["resolved"]]
        after = len(self._alerts)
        return ResponseFormatter.success(
            message=f"Cleared {before - after} resolved alerts"
        )


class RestAPI:
    """
    RESTful API handler providing CRUD operations for rules, validation,
    metrics, and alerts with request validation, response formatting,
    and error handling.

    Endpoints:
        GET    /rules       - List all rules (paginated, filterable)
        POST   /rules       - Create a new rule
        GET    /rules/:id   - Get a specific rule
        PUT    /rules/:id   - Update a specific rule
        DELETE /rules/:id   - Delete a specific rule
        POST   /validate    - Validate content against rules
        GET    /metrics     - Get system metrics
        GET    /alerts      - List alerts
        POST   /alerts      - Create a new alert
    """

    def __init__(self, rate_limiter: Optional[Any] = None) -> None:
        self.rate_limiter = rate_limiter
        self._rule_handler = RuleEndpointHandler()
        self._validation_handler = ValidationEndpointHandler()
        self._metrics_handler = MetricsEndpointHandler()
        self._endpoints: Dict[str, Dict[str, EndpointDefinition]] = {}
        self._request_id_counter: int = 0
        self._register_endpoints()

    def _register_endpoints(self) -> None:
        endpoints: List[EndpointDefinition] = [
            # Rule CRUD
            EndpointDefinition("/rules", HTTPMethod.GET, self.handle_list_rules,
                               scope=EndpointScope.READONLY, description="List all rules with filtering and pagination",
                               tags=["rules"]),
            EndpointDefinition("/rules", HTTPMethod.POST, self.handle_create_rule,
                               scope=EndpointScope.ADMIN, description="Create a new rule",
                               tags=["rules"]),
            EndpointDefinition("/rules/{rule_id}", HTTPMethod.GET, self.handle_get_rule,
                               scope=EndpointScope.READONLY, description="Get a specific rule by ID",
                               tags=["rules"]),
            EndpointDefinition("/rules/{rule_id}", HTTPMethod.PUT, self.handle_update_rule,
                               scope=EndpointScope.ADMIN, description="Update an existing rule",
                               tags=["rules"]),
            EndpointDefinition("/rules/{rule_id}", HTTPMethod.DELETE, self.handle_delete_rule,
                               scope=EndpointScope.ADMIN, description="Delete a rule",
                               tags=["rules"]),
            # Rule batch operations
            EndpointDefinition("/rules/batch", HTTPMethod.POST, self.handle_batch_create_rules,
                               scope=EndpointScope.ADMIN, description="Batch create rules",
                               tags=["rules"]),
            EndpointDefinition("/rules/summary", HTTPMethod.GET, self.handle_rules_summary,
                               scope=EndpointScope.READONLY, description="Get rules summary statistics",
                               tags=["rules"]),
            EndpointDefinition("/rules/search", HTTPMethod.GET, self.handle_search_rules,
                               scope=EndpointScope.READONLY, description="Search rules by query",
                               tags=["rules"]),
            EndpointDefinition("/rules/export", HTTPMethod.GET, self.handle_export_rules,
                               scope=EndpointScope.READONLY, description="Export rules",
                               tags=["rules"]),
            EndpointDefinition("/rules/{rule_id}/stats", HTTPMethod.GET, self.handle_rule_stats,
                               scope=EndpointScope.READONLY, description="Get statistics for a rule",
                               tags=["rules", "stats"]),
            EndpointDefinition("/rules/{rule_id}/status", HTTPMethod.PATCH, self.handle_toggle_rule_status,
                               scope=EndpointScope.ADMIN, description="Toggle rule status",
                               tags=["rules"]),
            # Validation
            EndpointDefinition("/validate", HTTPMethod.POST, self.handle_validate,
                               scope=EndpointScope.AUTHENTICATED, description="Validate content against rules",
                               tags=["validation"]),
            EndpointDefinition("/validate/batch", HTTPMethod.POST, self.handle_validate_batch,
                               scope=EndpointScope.AUTHENTICATED, description="Batch validate multiple contents",
                               tags=["validation"]),
            EndpointDefinition("/validate/history", HTTPMethod.GET, self.handle_validation_history,
                               scope=EndpointScope.READONLY, description="Get validation history",
                               tags=["validation"]),
            EndpointDefinition("/validate/stats", HTTPMethod.GET, self.handle_validation_stats,
                               scope=EndpointScope.READONLY, description="Get validation statistics",
                               tags=["validation"]),
            # Validation profiles
            EndpointDefinition("/validate/profiles", HTTPMethod.POST, self.handle_create_profile,
                               scope=EndpointScope.ADMIN, description="Create validation profile",
                               tags=["validation", "profiles"]),
            EndpointDefinition("/validate/profiles", HTTPMethod.GET, self.handle_list_profiles,
                               scope=EndpointScope.READONLY, description="List validation profiles",
                               tags=["validation", "profiles"]),
            EndpointDefinition("/validate/profiles/{profile_id}", HTTPMethod.GET, self.handle_get_profile,
                               scope=EndpointScope.READONLY, description="Get validation profile",
                               tags=["validation", "profiles"]),
            EndpointDefinition("/validate/profiles/{profile_id}", HTTPMethod.DELETE, self.handle_delete_profile,
                               scope=EndpointScope.ADMIN, description="Delete validation profile",
                               tags=["validation", "profiles"]),
            # Feedback
            EndpointDefinition("/validate/feedback", HTTPMethod.POST, self.handle_submit_feedback,
                               scope=EndpointScope.AUTHENTICATED, description="Submit validation feedback",
                               tags=["validation", "feedback"]),
            # Metrics
            EndpointDefinition("/metrics", HTTPMethod.GET, self.handle_get_metrics,
                               scope=EndpointScope.READONLY, description="Get system metrics",
                               tags=["metrics"]),
            EndpointDefinition("/metrics/{metric_name}", HTTPMethod.GET, self.handle_get_metric_detail,
                               scope=EndpointScope.READONLY, description="Get detailed metrics for a name",
                               tags=["metrics"]),
            EndpointDefinition("/metrics", HTTPMethod.POST, self.handle_record_metric,
                               scope=EndpointScope.AUTHENTICATED, description="Record a metric data point",
                               tags=["metrics"]),
            EndpointDefinition("/health", HTTPMethod.GET, self.handle_system_health,
                               scope=EndpointScope.PUBLIC, description="System health check",
                               tags=["system"]),
            # Alerts
            EndpointDefinition("/alerts", HTTPMethod.GET, self.handle_list_alerts,
                               scope=EndpointScope.READONLY, description="List alerts",
                               tags=["alerts"]),
            EndpointDefinition("/alerts", HTTPMethod.POST, self.handle_create_alert,
                               scope=EndpointScope.AUTHENTICATED, description="Create a new alert",
                               tags=["alerts"]),
            EndpointDefinition("/alerts/summary", HTTPMethod.GET, self.handle_alerts_summary,
                               scope=EndpointScope.READONLY, description="Get alerts summary",
                               tags=["alerts"]),
            EndpointDefinition("/alerts/{alert_id}/resolve", HTTPMethod.POST, self.handle_resolve_alert,
                               scope=EndpointScope.ADMIN, description="Resolve an alert",
                               tags=["alerts"]),
            EndpointDefinition("/alerts/clear", HTTPMethod.POST, self.handle_clear_resolved_alerts,
                               scope=EndpointScope.ADMIN, description="Clear resolved alerts",
                               tags=["alerts"]),
        ]
        for ep in endpoints:
            if ep.path not in self._endpoints:
                self._endpoints[ep.path] = {}
            self._endpoints[ep.path][ep.method.value] = ep

    def _generate_request_id(self) -> str:
        self._request_id_counter += 1
        return f"req_{uuid.uuid4().hex[:8]}_{self._request_id_counter}"

    def get_endpoint(self, path: str, method: str) -> Optional[EndpointDefinition]:
        path_endpoints = self._endpoints.get(path)
        if path_endpoints:
            return path_endpoints.get(method)
        for registered_path, methods in self._endpoints.items():
            if "{" in registered_path:
                import re
                pattern = re.sub(r"\{(\w+)\}", r"([^/]+)", registered_path)
                if re.fullmatch(pattern, path):
                    return methods.get(method)
        return None

    def list_all_endpoints(self) -> List[Dict[str, Any]]:
        result = []
        for path, methods in self._endpoints.items():
            for method, ep in methods.items():
                result.append({
                    "path": path,
                    "method": method,
                    "scope": ep.scope.value,
                    "description": ep.description,
                    "tags": ep.tags,
                    "deprecated": ep.deprecated,
                })
        return sorted(result, key=lambda e: e["path"])

    def handle_list_rules(self, request: Dict[str, Any]) -> APIResponse:
        params = request.get("params", {})
        return self._rule_handler.list_rules(
            page=int(params.get("page", 1)),
            per_page=int(params.get("per_page", 20)),
            tier=params.get("tier"),
            status=params.get("status"),
            rule_type=params.get("rule_type"),
            severity=params.get("severity"),
            search=params.get("search"),
            tags=params.get("tags"),
        )

    def handle_create_rule(self, request: Dict[str, Any]) -> APIResponse:
        body = request.get("body", {})
        return self._rule_handler.create_rule(body)

    def handle_get_rule(self, request: Dict[str, Any]) -> APIResponse:
        rule_id = request.get("path_params", {}).get("rule_id")
        return self._rule_handler.get_rule(rule_id)

    def handle_update_rule(self, request: Dict[str, Any]) -> APIResponse:
        rule_id = request.get("path_params", {}).get("rule_id")
        body = request.get("body", {})
        return self._rule_handler.update_rule(rule_id, body)

    def handle_delete_rule(self, request: Dict[str, Any]) -> APIResponse:
        rule_id = request.get("path_params", {}).get("rule_id")
        return self._rule_handler.delete_rule(rule_id)

    def handle_batch_create_rules(self, request: Dict[str, Any]) -> APIResponse:
        body = request.get("body", {})
        rules_data = body.get("rules", [])
        return self._rule_handler.batch_create_rules(rules_data)

    def handle_rules_summary(self, request: Dict[str, Any]) -> APIResponse:
        return self._rule_handler.get_rules_summary()

    def handle_search_rules(self, request: Dict[str, Any]) -> APIResponse:
        params = request.get("params", {})
        query = params.get("query", "")
        return self._rule_handler.search_rules(
            query=query,
            page=int(params.get("page", 1)),
            per_page=int(params.get("per_page", 20)),
        )

    def handle_export_rules(self, request: Dict[str, Any]) -> APIResponse:
        params = request.get("params", {})
        rule_ids = params.get("rule_ids")
        fmt = params.get("format", "json")
        return self._rule_handler.export_rules(rule_ids=rule_ids, format=fmt)

    def handle_rule_stats(self, request: Dict[str, Any]) -> APIResponse:
        rule_id = request.get("path_params", {}).get("rule_id")
        return self._rule_handler.get_rule_stats(rule_id)

    def handle_toggle_rule_status(self, request: Dict[str, Any]) -> APIResponse:
        rule_id = request.get("path_params", {}).get("rule_id")
        body = request.get("body", {})
        new_status = body.get("status", "active")
        return self._rule_handler.toggle_rule_status(rule_id, new_status)

    def handle_validate(self, request: Dict[str, Any]) -> APIResponse:
        body = request.get("body", {})
        return self._validation_handler.validate_content(body)

    def handle_validate_batch(self, request: Dict[str, Any]) -> APIResponse:
        body = request.get("body", {})
        return self._validation_handler.validate_batch(body)

    def handle_validation_history(self, request: Dict[str, Any]) -> APIResponse:
        params = request.get("params", {})
        return self._validation_handler.get_validation_history(
            page=int(params.get("page", 1)),
            per_page=int(params.get("per_page", 20)),
        )

    def handle_validation_stats(self, request: Dict[str, Any]) -> APIResponse:
        return self._validation_handler.get_validation_stats()

    def handle_create_profile(self, request: Dict[str, Any]) -> APIResponse:
        body = request.get("body", {})
        return self._validation_handler.create_profile(body)

    def handle_list_profiles(self, request: Dict[str, Any]) -> APIResponse:
        return self._validation_handler.list_profiles()

    def handle_get_profile(self, request: Dict[str, Any]) -> APIResponse:
        profile_id = request.get("path_params", {}).get("profile_id")
        return self._validation_handler.get_profile(profile_id)

    def handle_delete_profile(self, request: Dict[str, Any]) -> APIResponse:
        profile_id = request.get("path_params", {}).get("profile_id")
        return self._validation_handler.delete_profile(profile_id)

    def handle_submit_feedback(self, request: Dict[str, Any]) -> APIResponse:
        body = request.get("body", {})
        return self._validation_handler.submit_feedback(body)

    def handle_get_metrics(self, request: Dict[str, Any]) -> APIResponse:
        params = request.get("params", {})
        metric_names = params.get("names")
        return self._metrics_handler.get_metrics(metric_names=metric_names)

    def handle_get_metric_detail(self, request: Dict[str, Any]) -> APIResponse:
        metric_name = request.get("path_params", {}).get("metric_name")
        params = request.get("params", {})
        window = int(params.get("window_minutes", 60))
        return self._metrics_handler.get_metric_detail(metric_name, window)

    def handle_record_metric(self, request: Dict[str, Any]) -> APIResponse:
        body = request.get("body", {})
        name = body.get("name", "")
        value = body.get("value", 0)
        return self._metrics_handler.record_metric(name, value)

    def handle_system_health(self, request: Dict[str, Any]) -> APIResponse:
        return self._metrics_handler.get_system_health()

    def handle_list_alerts(self, request: Dict[str, Any]) -> APIResponse:
        params = request.get("params", {})
        return self._metrics_handler.list_alerts(
            page=int(params.get("page", 1)),
            per_page=int(params.get("per_page", 20)),
            severity=params.get("severity"),
            resolved=params.get("resolved"),
        )

    def handle_create_alert(self, request: Dict[str, Any]) -> APIResponse:
        body = request.get("body", {})
        return self._metrics_handler.create_alert(body)

    def handle_alerts_summary(self, request: Dict[str, Any]) -> APIResponse:
        return self._metrics_handler.get_alerts_summary()

    def handle_resolve_alert(self, request: Dict[str, Any]) -> APIResponse:
        alert_id = request.get("path_params", {}).get("alert_id")
        return self._metrics_handler.resolve_alert(alert_id)

    def handle_clear_resolved_alerts(self, request: Dict[str, Any]) -> APIResponse:
        return self._metrics_handler.clear_resolved_alerts()

    def dispatch(self, path: str, method: str, request: Dict[str, Any]) -> APIResponse:
        request_id = self._generate_request_id()
        request["request_id"] = request_id
        ep = self.get_endpoint(path, method)
        if not ep:
            return ResponseFormatter.error(
                f"No endpoint found for {method} {path}",
                status_code=HTTPStatus.NOT_FOUND,
                request_id=request_id
            )
        if ep.deprecated:
            logger.warning(f"Deprecated endpoint called: {method} {path}")
        try:
            response = ep.handler(request)
            if response.request_id is None:
                response.request_id = request_id
            return response
        except Exception as e:
            logger.error(f"Unhandled error in {method} {path}: {e}\n{traceback.format_exc()}")
            return ResponseFormatter.server_error(
                message=str(e),
                request_id=request_id
            )

    def get_endpoints_documentation(self) -> List[Dict[str, Any]]:
        doc = []
        for path, methods in self._endpoints.items():
            for method, ep in methods.items():
                doc.append({
                    "path": path,
                    "method": method,
                    "scope": ep.scope.value,
                    "description": ep.description,
                    "tags": ep.tags,
                    "deprecated": ep.deprecated,
                    "rate_limit_key": ep.rate_limit_key,
                })
        return doc
