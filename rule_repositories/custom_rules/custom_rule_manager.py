"""
Custom rule manager for CRUD operations on custom rules.

Provides comprehensive management of user-defined custom rules including
creation, validation, versioning, search, bulk operations, and event hooks.
"""

import csv
import hashlib
import io
import json
import logging
import os
import re
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from collections import defaultdict, OrderedDict

import yaml

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)

logger = logging.getLogger(__name__)


class RuleValidationError(Exception):
    """Exception raised when a rule fails validation."""


class RuleNotFoundError(Exception):
    """Exception raised when a requested rule does not exist."""


class RuleConflictError(Exception):
    """Exception raised when a rule conflicts with existing rules."""


class VersionConflictError(Exception):
    """Exception raised on version mismatch during update."""


@dataclass
class RuleChangeEvent:
    """Event payload for rule change notifications."""

    event_type: str
    rule_id: str
    rule_name: str
    timestamp: datetime
    user_id: Optional[str] = None
    previous_version: Optional[str] = None
    new_version: Optional[str] = None
    changes: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BulkOperationResult:
    """Result of a bulk rule operation."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: Dict[str, str] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    operation_type: str = ""


class RuleFilterCriteria:
    """Filter criteria for searching and listing rules."""

    def __init__(
        self,
        name_pattern: Optional[str] = None,
        tier: Optional[RuleTier] = None,
        rule_type: Optional[RuleType] = None,
        severity: Optional[RuleSeverity] = None,
        status: Optional[RuleStatus] = None,
        tags: Optional[List[str]] = None,
        created_by: Optional[str] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        updated_after: Optional[datetime] = None,
        updated_before: Optional[datetime] = None,
        min_priority: Optional[int] = None,
        max_priority: Optional[int] = None,
        search_text: Optional[str] = None,
        version: Optional[str] = None,
    ):
        self.name_pattern = name_pattern
        self.tier = tier
        self.rule_type = rule_type
        self.severity = severity
        self.status = status
        self.tags = tags or []
        self.created_by = created_by
        self.created_after = created_after
        self.created_before = created_before
        self.updated_after = updated_after
        self.updated_before = updated_before
        self.min_priority = min_priority
        self.max_priority = max_priority
        self.search_text = search_text
        self.version = version

    def to_dict(self) -> Dict[str, Any]:
        """Convert filter criteria to dictionary for serialization."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if value is not None and value != []:
                if isinstance(value, Enum):
                    result[key] = value.value
                elif isinstance(value, datetime):
                    result[key] = value.isoformat()
                else:
                    result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleFilterCriteria":
        """Create filter criteria from dictionary."""
        enum_fields = {
            "tier": RuleTier,
            "rule_type": RuleType,
            "severity": RuleSeverity,
            "status": RuleStatus,
        }
        parsed = {}
        for key, value in data.items():
            if key in enum_fields and value is not None:
                try:
                    parsed[key] = enum_fields[key](value)
                except (ValueError, TypeError):
                    parsed[key] = value
            elif key in ("created_after", "created_before", "updated_after", "updated_before"):
                if value is not None:
                    try:
                        parsed[key] = datetime.fromisoformat(value)
                    except (ValueError, TypeError):
                        parsed[key] = value
            else:
                parsed[key] = value
        return cls(**parsed)


class RuleSchemaValidator:
    """Validates rules against a schema definition."""

    REQUIRED_FIELDS = {"id", "name", "tier", "rule_type", "severity", "enforcement_level"}
    OPTIONAL_FIELDS = {
        "description", "status", "patterns", "conditions", "exceptions",
        "auto_block", "user_override", "override_justification_required",
        "version", "created_at", "updated_at", "created_by", "tags",
        "priority", "timeout_ms", "cache_ttl_seconds",
    }
    ALL_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

    VALID_TIERS = {t.value for t in RuleTier}
    VALID_TYPES = {t.value for t in RuleType}
    VALID_SEVERITIES = {s.value for s in RuleSeverity}
    VALID_STATUSES = {s.value for s in RuleStatus}
    VALID_ENFORCEMENT_LEVELS = {e.value for e in EnforcementLevel}

    SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

    def __init__(self, strict_mode: bool = True):
        self.strict_mode = strict_mode
        self._custom_validators: List[Callable[[Rule], Optional[str]]] = []

    def register_validator(self, validator: Callable[[Rule], Optional[str]]) -> None:
        """Register a custom validator function."""
        self._custom_validators.append(validator)

    def validate(self, rule: Rule) -> List[str]:
        """Validate a rule object against the schema. Returns list of error messages."""
        errors: List[str] = []

        field_errors = self._validate_required_fields(rule)
        errors.extend(field_errors)

        enum_errors = self._validate_enums(rule)
        errors.extend(enum_errors)

        semver_errors = self._validate_semver(rule)
        errors.extend(semver_errors)

        range_errors = self._validate_ranges(rule)
        errors.extend(range_errors)

        pattern_errors = self._validate_patterns(rule)
        errors.extend(pattern_errors)

        business_errors = self._validate_business_rules(rule)
        errors.extend(business_errors)

        for validator in self._custom_validators:
            try:
                error = validator(rule)
                if error:
                    errors.append(error)
            except Exception as exc:
                errors.append(f"Custom validator failed: {exc}")

        return errors

    def _validate_required_fields(self, rule: Rule) -> List[str]:
        """Validate that all required fields are present and non-empty."""
        errors: List[str] = []
        rule_dict = rule.dict() if hasattr(rule, "dict") else rule.__dict__
        for field_name in self.REQUIRED_FIELDS:
            value = getattr(rule, field_name, None)
            if value is None:
                errors.append(f"Missing required field: {field_name}")
            elif isinstance(value, str) and len(value.strip()) == 0:
                errors.append(f"Required field '{field_name}' cannot be empty")
        return errors

    def _validate_enums(self, rule: Rule) -> List[str]:
        """Validate enum field values."""
        errors: List[str] = []
        enum_checks = [
            ("tier", rule.tier, self.VALID_TIERS),
            ("rule_type", rule.rule_type, self.VALID_TYPES),
            ("severity", rule.severity, self.VALID_SEVERITIES),
            ("status", rule.status, self.VALID_STATUSES),
            ("enforcement_level", rule.enforcement_level, self.VALID_ENFORCEMENT_LEVELS),
        ]
        for field_name, value, valid_set in enum_checks:
            str_value = value.value if isinstance(value, Enum) else str(value)
            if str_value not in valid_set:
                errors.append(
                    f"Invalid {field_name}: '{str_value}'. Must be one of {valid_set}"
                )
        return errors

    def _validate_semver(self, rule: Rule) -> List[str]:
        """Validate semantic versioning format."""
        errors: List[str] = []
        if rule.version and not self.SEMVER_PATTERN.match(rule.version):
            errors.append(
                f"Invalid version format: '{rule.version}'. Must be semantic version (x.y.z)"
            )
        return errors

    def _validate_ranges(self, rule: Rule) -> List[str]:
        """Validate numeric field ranges."""
        errors: List[str] = []
        if not (1 <= rule.priority <= 1000):
            errors.append(f"Priority must be between 1 and 1000, got {rule.priority}")
        if not (1 <= rule.timeout_ms <= 10000):
            errors.append(f"timeout_ms must be between 1 and 10000, got {rule.timeout_ms}")
        if not (0 <= rule.cache_ttl_seconds <= 86400):
            errors.append(
                f"cache_ttl_seconds must be between 0 and 86400, got {rule.cache_ttl_seconds}"
            )
        return errors

    def _validate_patterns(self, rule: Rule) -> List[str]:
        """Validate rule patterns."""
        errors: List[str] = []
        if rule.patterns:
            for i, pattern in enumerate(rule.patterns):
                if not pattern.keywords and not pattern.regex_patterns and not pattern.ml_model:
                    errors.append(
                        f"Pattern at index {i} must have at least one of: "
                        "keywords, regex_patterns, or ml_model"
                    )
                if not (0.0 <= pattern.confidence_threshold <= 1.0):
                    errors.append(
                        f"Pattern at index {i} has invalid confidence_threshold: "
                        f"{pattern.confidence_threshold}"
                    )
                for regex in pattern.regex_patterns:
                    try:
                        re.compile(regex)
                    except re.error as exc:
                        errors.append(
                            f"Pattern at index {i} has invalid regex '{regex}': {exc}"
                        )
        return errors

    def _validate_business_rules(self, rule: Rule) -> List[str]:
        """Validate business logic rules."""
        errors: List[str] = []
        if rule.tier == RuleTier.SAFETY and rule.enforcement_level == EnforcementLevel.ADAPTIVE:
            errors.append(
                "Safety tier rules cannot have ADAPTIVE enforcement level"
            )
        if rule.tier == RuleTier.SAFETY and rule.user_override:
            errors.append(
                "Safety tier rules cannot allow user override"
            )
        if rule.tier == RuleTier.OPERATIONAL and rule.enforcement_level == EnforcementLevel.FALLBACK:
            errors.append(
                "Operational tier rules should not use FALLBACK enforcement level"
            )
        return errors

    def is_valid(self, rule: Rule) -> bool:
        """Quick validity check returning boolean."""
        return len(self.validate(rule)) == 0


class CustomRuleManager:
    """Manager for CRUD operations on custom rules with versioning and validation."""

    def __init__(
        self,
        storage_path: Optional[str] = None,
        schema_validator: Optional[RuleSchemaValidator] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._storage_path = storage_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "custom_rules"
        )
        self._schema_validator = schema_validator or RuleSchemaValidator()
        self._config = self._default_config()
        if config:
            self._config.update(config)
        self._rules: Dict[str, Rule] = {}
        self._version_history: Dict[str, List[Rule]] = defaultdict(list)
        self._index_by_tier: Dict[RuleTier, Set[str]] = defaultdict(set)
        self._index_by_type: Dict[RuleType, Set[str]] = defaultdict(set)
        self._index_by_status: Dict[RuleStatus, Set[str]] = defaultdict(set)
        self._index_by_severity: Dict[RuleSeverity, Set[str]] = defaultdict(set)
        self._index_by_tag: Dict[str, Set[str]] = defaultdict(set)
        self._index_by_creator: Dict[str, Set[str]] = defaultdict(set)
        self._event_hooks: Dict[str, List[Callable[[RuleChangeEvent], None]]] = defaultdict(list)
        self._lock = RLock()
        self._load_rules()
        logger.info(
            "CustomRuleManager initialized with %d rules at %s",
            len(self._rules),
            self._storage_path,
        )

    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for the rule manager."""
        return {
            "auto_save": True,
            "version_history_limit": 50,
            "max_rules_per_user": 1000,
            "max_rule_name_length": 200,
            "max_rule_description_length": 2000,
            "max_tags_per_rule": 20,
            "max_patterns_per_rule": 50,
            "max_keywords_per_pattern": 100,
            "max_regex_per_pattern": 20,
            "allow_duplicate_names": False,
            "strict_validation": True,
            "auto_index": True,
            "backup_on_update": True,
            "event_notifications": True,
            "storage_format": "json",
            "compression": False,
            "cache_enabled": True,
            "cache_ttl_seconds": 300,
            "max_cache_size": 1000,
        }

    def create_rule(
        self,
        rule: Rule,
        user_id: Optional[str] = None,
        skip_validation: bool = False,
    ) -> Rule:
        """Create a new custom rule."""
        if not skip_validation:
            errors = self._schema_validator.validate(rule)
            if errors:
                error_msg = "; ".join(errors)
                logger.error("Rule validation failed for '%s': %s", rule.name, error_msg)
                raise RuleValidationError(f"Rule validation failed: {error_msg}")

        with self._lock:
            if rule.id in self._rules:
                raise RuleConflictError(
                    f"Rule with ID '{rule.id}' already exists"
                )
            if not self._config["allow_duplicate_names"]:
                for existing in self._rules.values():
                    if existing.name == rule.name:
                        raise RuleConflictError(
                            f"Rule with name '{rule.name}' already exists"
                        )

            now = datetime.utcnow()
            rule.created_at = now
            rule.updated_at = now
            if user_id:
                rule.created_by = user_id

            rule.version = "1.0.0"
            self._rules[rule.id] = rule
            self._update_indexes(rule)
            self._version_history[rule.id].append(deepcopy(rule))

            if self._config["auto_save"]:
                self._save_rule(rule)

            if self._config["event_notifications"]:
                self._emit_event(
                    RuleChangeEvent(
                        event_type="rule.created",
                        rule_id=rule.id,
                        rule_name=rule.name,
                        timestamp=now,
                        user_id=user_id,
                        new_version=rule.version,
                    )
                )

            logger.info("Created rule '%s' (ID: %s, version: %s)", rule.name, rule.id, rule.version)
            return rule

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        """Get a rule by its ID."""
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule is None:
                logger.debug("Rule not found: %s", rule_id)
            return deepcopy(rule) if rule else None

    def update_rule(
        self,
        rule_id: str,
        updates: Dict[str, Any],
        user_id: Optional[str] = None,
        expected_version: Optional[str] = None,
    ) -> Rule:
        """Update an existing rule with partial or full updates."""
        with self._lock:
            existing = self._rules.get(rule_id)
            if not existing:
                raise RuleNotFoundError(f"Rule not found: {rule_id}")

            if expected_version and existing.version != expected_version:
                raise VersionConflictError(
                    f"Version mismatch: expected {expected_version}, "
                    f"current {existing.version}"
                )

            old_rule = deepcopy(existing)

            for key, value in updates.items():
                if hasattr(existing, key) and key not in ("id", "created_at", "created_by"):
                    setattr(existing, key, value)

            existing.updated_at = datetime.utcnow()
            existing.version = self._bump_version(existing.version)

            if not self._schema_validator.is_valid(existing):
                errors = self._schema_validator.validate(existing)
                raise RuleValidationError(f"Updated rule invalid: {'; '.join(errors)}")

            self._rules[rule_id] = existing
            self._rebuild_indexes()

            version_history = self._version_history[rule_id]
            version_history.append(deepcopy(existing))
            limit = self._config["version_history_limit"]
            if len(version_history) > limit:
                self._version_history[rule_id] = version_history[-limit:]

            if self._config["auto_save"]:
                self._save_rule(existing)
                if self._config["backup_on_update"]:
                    self._backup_rule(old_rule)

            if self._config["event_notifications"]:
                self._emit_event(
                    RuleChangeEvent(
                        event_type="rule.updated",
                        rule_id=rule_id,
                        rule_name=existing.name,
                        timestamp=existing.updated_at,
                        user_id=user_id,
                        previous_version=old_rule.version,
                        new_version=existing.version,
                        changes=self._compute_changes(old_rule, existing),
                    )
                )

            logger.info(
                "Updated rule '%s' (ID: %s) from %s to %s",
                existing.name, rule_id, old_rule.version, existing.version,
            )
            return deepcopy(existing)

    def delete_rule(
        self,
        rule_id: str,
        user_id: Optional[str] = None,
        hard_delete: bool = False,
    ) -> bool:
        """Delete a rule. Soft delete by default (marks as DEPRECATED)."""
        with self._lock:
            rule = self._rules.get(rule_id)
            if not rule:
                raise RuleNotFoundError(f"Rule not found: {rule_id}")

            if hard_delete:
                del self._rules[rule_id]
                self._version_history.pop(rule_id, None)
                self._rebuild_indexes()
                if self._config["auto_save"]:
                    self._delete_rule_file(rule_id)
                logger.info("Hard-deleted rule '%s' (ID: %s)", rule.name, rule_id)
            else:
                rule.status = RuleStatus.DEPRECATED
                rule.updated_at = datetime.utcnow()
                if self._config["auto_save"]:
                    self._save_rule(rule)
                logger.info("Soft-deleted rule '%s' (ID: %s)", rule.name, rule_id)

            if self._config["event_notifications"]:
                self._emit_event(
                    RuleChangeEvent(
                        event_type="rule.deleted" if hard_delete else "rule.deprecated",
                        rule_id=rule_id,
                        rule_name=rule.name,
                        timestamp=datetime.utcnow(),
                        user_id=user_id,
                        previous_version=rule.version,
                    )
                )

            return True

    def list_rules(self, criteria: Optional[RuleFilterCriteria] = None) -> List[Rule]:
        """List rules optionally filtered by criteria."""
        with self._lock:
            rules = list(self._rules.values())
            if criteria:
                rules = self._apply_filters(rules, criteria)
            sorted_rules = sorted(rules, key=lambda r: (r.tier.value, -r.priority, r.name))
            return [deepcopy(r) for r in sorted_rules]

    def search_rules(self, query: str) -> List[Rule]:
        """Search rules by text in name, description, and tags."""
        with self._lock:
            query_lower = query.lower()
            results: List[Rule] = []
            for rule in self._rules.values():
                if query_lower in rule.name.lower():
                    results.append(rule)
                    continue
                if query_lower in rule.description.lower():
                    results.append(rule)
                    continue
                for tag in rule.tags:
                    if query_lower in tag.lower():
                        results.append(rule)
                        break
            return [deepcopy(r) for r in results]

    def get_rule_version_history(self, rule_id: str) -> List[Rule]:
        """Get version history for a specific rule."""
        with self._lock:
            if rule_id not in self._rules:
                raise RuleNotFoundError(f"Rule not found: {rule_id}")
            return [deepcopy(r) for r in self._version_history.get(rule_id, [])]

    def rollback_rule(self, rule_id: str, version_index: int) -> Rule:
        """Rollback a rule to a previous version by index."""
        with self._lock:
            if rule_id not in self._rules:
                raise RuleNotFoundError(f"Rule not found: {rule_id}")
            history = self._version_history.get(rule_id, [])
            if not history or version_index < 0 or version_index >= len(history):
                raise ValueError(
                    f"Invalid version index {version_index}. "
                    f"Available versions: 0-{len(history) - 1}"
                )

            target_version = deepcopy(history[version_index])
            target_version.updated_at = datetime.utcnow()
            target_version.version = self._bump_version(target_version.version)

            self._rules[rule_id] = target_version
            history.append(deepcopy(target_version))
            limit = self._config["version_history_limit"]
            if len(history) > limit:
                self._version_history[rule_id] = history[-limit:]

            if self._config["auto_save"]:
                self._save_rule(target_version)

            logger.info(
                "Rolled back rule '%s' to version index %d, new version %s",
                target_version.name, version_index, target_version.version,
            )
            return deepcopy(target_version)

    def bulk_create(
        self,
        rules: List[Rule],
        user_id: Optional[str] = None,
        stop_on_error: bool = False,
    ) -> BulkOperationResult:
        """Create multiple rules in bulk."""
        result = BulkOperationResult(total=len(rules), operation_type="create")
        for rule in rules:
            try:
                created = self.create_rule(rule, user_id)
                result.succeeded += 1
                result.results[rule.id] = {"status": "created", "version": created.version}
            except (RuleValidationError, RuleConflictError) as exc:
                result.failed += 1
                result.errors[rule.id] = str(exc)
                logger.warning("Bulk create failed for rule '%s': %s", rule.id, exc)
                if stop_on_error:
                    break
        return result

    def bulk_update(
        self,
        updates: Dict[str, Dict[str, Any]],
        user_id: Optional[str] = None,
    ) -> BulkOperationResult:
        """Update multiple rules in bulk."""
        result = BulkOperationResult(total=len(updates), operation_type="update")
        for rule_id, fields in updates.items():
            try:
                updated = self.update_rule(rule_id, fields, user_id)
                result.succeeded += 1
                result.results[rule_id] = {"status": "updated", "version": updated.version}
            except (RuleNotFoundError, RuleValidationError, VersionConflictError) as exc:
                result.failed += 1
                result.errors[rule_id] = str(exc)
                logger.warning("Bulk update failed for rule '%s': %s", rule_id, exc)
        return result

    def bulk_delete(
        self,
        rule_ids: List[str],
        user_id: Optional[str] = None,
        hard_delete: bool = False,
    ) -> BulkOperationResult:
        """Delete multiple rules in bulk."""
        result = BulkOperationResult(total=len(rule_ids), operation_type="delete")
        for rule_id in rule_ids:
            try:
                self.delete_rule(rule_id, user_id, hard_delete)
                result.succeeded += 1
                result.results[rule_id] = {"status": "deleted"}
            except RuleNotFoundError as exc:
                result.failed += 1
                result.errors[rule_id] = str(exc)
        return result

    def bulk_activate(self, rule_ids: List[str], user_id: Optional[str] = None) -> BulkOperationResult:
        """Activate multiple rules."""
        updates = {rid: {"status": RuleStatus.ACTIVE} for rid in rule_ids}
        return self.bulk_update(updates, user_id)

    def bulk_deactivate(self, rule_ids: List[str], user_id: Optional[str] = None) -> BulkOperationResult:
        """Deactivate multiple rules."""
        updates = {rid: {"status": RuleStatus.INACTIVE} for rid in rule_ids}
        return self.bulk_update(updates, user_id)

    def import_rules(
        self,
        rules_data: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        strategy: str = "fail_on_conflict",
    ) -> BulkOperationResult:
        """Import rules from dictionary data with conflict resolution."""
        result = BulkOperationResult(total=len(rules_data), operation_type="import")
        for data in rules_data:
            try:
                rule = Rule(**data)
                existing = self._rules.get(rule.id)
                if existing:
                    if strategy == "skip":
                        result.skipped = getattr(result, "skipped", 0) + 1
                        result.results[rule.id] = {"status": "skipped"}
                        continue
                    elif strategy == "overwrite":
                        self.update_rule(rule.id, data, user_id)
                        result.succeeded += 1
                        result.results[rule.id] = {"status": "updated"}
                        continue
                    elif strategy == "rename":
                        rule.id = f"{rule.id}_{uuid.uuid4().hex[:8]}"
                self.create_rule(rule, user_id)
                result.succeeded += 1
                result.results[rule.id] = {"status": "created"}
            except Exception as exc:
                result.failed += 1
                result.errors.get(data.get("id", "unknown"), str(exc))
                logger.error("Import failed for rule '%s': %s", data.get("id", "unknown"), exc)
        return result

    def export_rules(
        self,
        criteria: Optional[RuleFilterCriteria] = None,
        format_type: str = "json",
    ) -> Union[str, List[Dict[str, Any]]]:
        """Export rules matching criteria in the specified format."""
        rules = self.list_rules(criteria)
        rule_dicts = [rule.dict() for rule in rules]
        for rd in rule_dicts:
            for key in ("created_at", "updated_at"):
                if key in rd and isinstance(rd[key], datetime):
                    rd[key] = rd[key].isoformat()
        if format_type == "json":
            return json.dumps(rule_dicts, indent=2, default=str)
        elif format_type == "yaml":
            return yaml.dump(rule_dicts, default_flow_style=False)
        else:
            return rule_dicts

    def register_event_hook(
        self,
        event_type: str,
        callback: Callable[[RuleChangeEvent], None],
    ) -> None:
        """Register a callback for a specific event type."""
        valid_types = {"rule.created", "rule.updated", "rule.deleted", "rule.deprecated", "rule.*"}
        if event_type not in valid_types and not event_type.startswith("rule."):
            raise ValueError(f"Invalid event type: {event_type}. Must be one of {valid_types}")
        self._event_hooks[event_type].append(callback)

    def unregister_event_hook(
        self,
        event_type: str,
        callback: Callable[[RuleChangeEvent], None],
    ) -> bool:
        """Remove a previously registered event hook."""
        hooks = self._event_hooks.get(event_type, [])
        if callback in hooks:
            hooks.remove(callback)
            return True
        return False

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about managed rules."""
        with self._lock:
            total = len(self._rules)
            active = sum(1 for r in self._rules.values() if r.status == RuleStatus.ACTIVE)
            inactive = sum(1 for r in self._rules.values() if r.status == RuleStatus.INACTIVE)
            deprecated = sum(1 for r in self._rules.values() if r.status == RuleStatus.DEPRECATED)
            testing = sum(1 for r in self._rules.values() if r.status == RuleStatus.TESTING)
            by_tier = defaultdict(int)
            by_type = defaultdict(int)
            by_severity = defaultdict(int)
            for rule in self._rules.values():
                by_tier[rule.tier.value] += 1
                by_type[rule.rule_type.value] += 1
                by_severity[rule.severity.value] += 1
            return {
                "total_rules": total,
                "active_rules": active,
                "inactive_rules": inactive,
                "deprecated_rules": deprecated,
                "testing_rules": testing,
                "rules_by_tier": dict(by_tier),
                "rules_by_type": dict(by_type),
                "rules_by_severity": dict(by_severity),
                "version_history_count": sum(len(h) for h in self._version_history.values()),
                "total_event_hooks": sum(len(h) for h in self._event_hooks.values()),
            }

    def reload(self) -> int:
        """Reload all rules from storage."""
        with self._lock:
            self._rules.clear()
            self._version_history.clear()
            self._clear_indexes()
            count = self._load_rules()
            logger.info("Reloaded %d rules from storage", count)
            return count

    def _load_rules(self) -> int:
        """Load rules from storage directory."""
        storage_path = Path(self._storage_path)
        count = 0
        if not storage_path.exists():
            storage_path.mkdir(parents=True, exist_ok=True)
            logger.info("Created storage directory: %s", storage_path)
            return 0
        for file_path in storage_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                rule = Rule(**data)
                self._rules[rule.id] = rule
                self._update_indexes(rule)
                self._version_history[rule.id].append(deepcopy(rule))
                count += 1
            except Exception as exc:
                logger.error("Failed to load rule from %s: %s", file_path, exc)
        return count

    def _save_rule(self, rule: Rule) -> None:
        """Save a single rule to storage."""
        storage_path = Path(self._storage_path)
        storage_path.mkdir(parents=True, exist_ok=True)
        file_path = storage_path / f"{rule.id}.json"
        rule_dict = rule.dict()
        for key in ("created_at", "updated_at"):
            if key in rule_dict and isinstance(rule_dict[key], datetime):
                rule_dict[key] = rule_dict[key].isoformat()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(rule_dict, f, indent=2, default=str)

    def _delete_rule_file(self, rule_id: str) -> None:
        """Delete a rule's storage file."""
        file_path = Path(self._storage_path) / f"{rule_id}.json"
        if file_path.exists():
            file_path.unlink()

    def _backup_rule(self, rule: Rule) -> None:
        """Create a backup of a rule before update."""
        backup_dir = Path(self._storage_path) / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{rule.id}_{rule.version}_{timestamp}.json"
        rule_dict = rule.dict()
        for key in ("created_at", "updated_at"):
            if key in rule_dict and isinstance(rule_dict[key], datetime):
                rule_dict[key] = rule_dict[key].isoformat()
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(rule_dict, f, indent=2, default=str)

    def _update_indexes(self, rule: Rule) -> None:
        """Update all indexes for a rule."""
        if not self._config["auto_index"]:
            return
        self._index_by_tier[rule.tier].add(rule.id)
        self._index_by_type[rule.rule_type].add(rule.id)
        self._index_by_status[rule.status].add(rule.id)
        self._index_by_severity[rule.severity].add(rule.id)
        for tag in rule.tags:
            self._index_by_tag[tag].add(rule.id)
        if rule.created_by:
            self._index_by_creator[rule.created_by].add(rule.id)

    def _rebuild_indexes(self) -> None:
        """Rebuild all indexes from scratch."""
        self._clear_indexes()
        for rule in self._rules.values():
            self._update_indexes(rule)

    def _clear_indexes(self) -> None:
        """Clear all indexes."""
        self._index_by_tier.clear()
        self._index_by_type.clear()
        self._index_by_status.clear()
        self._index_by_severity.clear()
        self._index_by_tag.clear()
        self._index_by_creator.clear()

    def _apply_filters(self, rules: List[Rule], criteria: RuleFilterCriteria) -> List[Rule]:
        """Apply filter criteria to a list of rules."""
        filtered = rules
        if criteria.name_pattern:
            pattern = re.compile(criteria.name_pattern, re.IGNORECASE)
            filtered = [r for r in filtered if pattern.search(r.name)]
        if criteria.tier:
            filtered = [r for r in filtered if r.tier == criteria.tier]
        if criteria.rule_type:
            filtered = [r for r in filtered if r.rule_type == criteria.rule_type]
        if criteria.severity:
            filtered = [r for r in filtered if r.severity == criteria.severity]
        if criteria.status:
            filtered = [r for r in filtered if r.status == criteria.status]
        if criteria.tags:
            filtered = [
                r for r in filtered
                if any(tag in r.tags for tag in criteria.tags)
            ]
        if criteria.created_by:
            filtered = [r for r in filtered if r.created_by == criteria.created_by]
        if criteria.created_after:
            filtered = [r for r in filtered if r.created_at >= criteria.created_after]
        if criteria.created_before:
            filtered = [r for r in filtered if r.created_at <= criteria.created_before]
        if criteria.updated_after:
            filtered = [r for r in filtered if r.updated_at >= criteria.updated_after]
        if criteria.updated_before:
            filtered = [r for r in filtered if r.updated_at <= criteria.updated_before]
        if criteria.min_priority is not None:
            filtered = [r for r in filtered if r.priority >= criteria.min_priority]
        if criteria.max_priority is not None:
            filtered = [r for r in filtered if r.priority <= criteria.max_priority]
        if criteria.search_text:
            text = criteria.search_text.lower()
            filtered = [
                r for r in filtered
                if text in r.name.lower()
                or text in r.description.lower()
                or any(text in t.lower() for t in r.tags)
            ]
        if criteria.version:
            filtered = [r for r in filtered if r.version == criteria.version]
        return filtered

    def _emit_event(self, event: RuleChangeEvent) -> None:
        """Emit a rule change event to all registered hooks."""
        hooks = list(self._event_hooks.get(event.event_type, []))
        hooks.extend(self._event_hooks.get("rule.*", []))
        for hook in hooks:
            try:
                hook(event)
            except Exception as exc:
                logger.error("Event hook failed for %s: %s", event.event_type, exc)

    def _bump_version(self, version: str) -> str:
        """Bump the patch version number."""
        parts = version.split(".")
        if len(parts) == 3:
            parts[2] = str(int(parts[2]) + 1)
        return ".".join(parts)

    def _compute_changes(self, old: Rule, new: Rule) -> Dict[str, Any]:
        """Compute changes between two rule versions."""
        changes: Dict[str, Any] = {}
        for field in ("name", "description", "tier", "rule_type", "severity", "status",
                      "enforcement_level", "auto_block", "user_override", "priority",
                      "timeout_ms", "cache_ttl_seconds"):
            old_val = getattr(old, field, None)
            new_val = getattr(new, field, None)
            if old_val != new_val:
                old_str = old_val.value if isinstance(old_val, Enum) else str(old_val)
                new_str = new_val.value if isinstance(new_val, Enum) else str(new_val)
                changes[field] = {"from": old_str, "to": new_str}
        return changes
