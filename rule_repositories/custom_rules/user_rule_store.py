"""
User rule store for per-user rule storage and personalization.

Manages user-specific rule configurations, personalization of rule parameters,
inheritance from organizational defaults, and per-user usage tracking.
"""

import csv
import hashlib
import io
import json
import logging
import os
import time
import uuid
from collections import defaultdict, OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

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


class UserNotFoundError(Exception):
    """Exception raised when a user does not exist in the store."""


class UserRuleLimitError(Exception):
    """Exception raised when a user exceeds their rule limit."""


class StorageBackendError(Exception):
    """Exception raised on storage backend failures."""


class InheritanceCycleError(Exception):
    """Exception raised when inheritance hierarchy has a cycle."""


@dataclass
class UserProfile:
    """User profile for rule store configuration."""

    user_id: str
    username: str
    email: Optional[str] = None
    role: str = "viewer"
    organization_id: Optional[str] = None
    max_custom_rules: int = 100
    max_rule_sets: int = 20
    allowed_tiers: List[str] = field(default_factory=lambda: ["preference"])
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize profile to dictionary."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, Enum):
                result[key] = value.value
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        """Create profile from dictionary."""
        for key in ("created_at", "updated_at"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = datetime.fromisoformat(data[key])
                except (ValueError, TypeError):
                    data[key] = datetime.utcnow()
        return cls(**data)


@dataclass
class UserRuleOverride:
    """User-specific override for a rule parameter."""

    rule_id: str
    parameter: str
    original_value: Any
    overridden_value: Any
    applied_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    reason: Optional[str] = None
    approved_by: Optional[str] = None

    def is_expired(self) -> bool:
        """Check if the override has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """Serialize override to dictionary."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserRuleOverride":
        """Create override from dictionary."""
        for key in ("applied_at", "expires_at"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = datetime.fromisoformat(data[key])
                except (ValueError, TypeError):
                    data[key] = None if key == "expires_at" else datetime.utcnow()
        return cls(**data)


@dataclass
class UserUsageStats:
    """Usage statistics for a user."""

    user_id: str
    total_evaluations: int = 0
    rules_created: int = 0
    rules_modified: int = 0
    rules_deleted: int = 0
    overrides_applied: int = 0
    overrides_expired: int = 0
    last_active_at: Optional[datetime] = None
    first_active_at: datetime = field(default_factory=datetime.utcnow)
    monthly_evaluation_count: int = 0
    storage_bytes_used: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def record_evaluation(self) -> None:
        """Record a rule evaluation event."""
        self.total_evaluations += 1
        self.monthly_evaluation_count += 1
        self.last_active_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize stats to dictionary."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserUsageStats":
        """Create stats from dictionary."""
        for key in ("last_active_at", "first_active_at"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = datetime.fromisoformat(data[key])
                except (ValueError, TypeError):
                    data[key] = datetime.utcnow()
        return cls(**data)


class InheritanceMode(str, Enum):
    """Mode for rule inheritance from organization/global defaults."""

    NONE = "none"
    OVERRIDE = "override"
    MERGE = "merge"
    STRICT = "strict"


class ResolutionStrategy(str, Enum):
    """Strategy for resolving user vs default rule conflicts."""

    USER_PREFERENCE = "user_preference"
    DEFAULT_WINS = "default_wins"
    MOST_RESTRICTIVE = "most_restrictive"
    LEAST_RESTRICTIVE = "least_restrictive"
    CUSTOM = "custom"


class StorageBackendType(str, Enum):
    """Supported storage backends."""

    FILESYSTEM = "filesystem"
    DATABASE = "database"
    REDIS = "redis"
    S3 = "s3"
    MEMORY = "memory"


class UserRuleStore:
    """
    Per-user rule store with personalization, inheritance, and usage tracking.

    Supports multiple storage backends, user-specific overrides, and
    inheritance from organization or global defaults.
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        backend_type: str = "filesystem",
        inheritance_mode: str = "merge",
        config: Optional[Dict[str, Any]] = None,
    ):
        self._storage_path = storage_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "user_rules"
        )
        self._backend_type = StorageBackendType(backend_type)
        self._inheritance_mode = InheritanceMode(inheritance_mode)
        self._config = self._default_config()
        if config:
            self._config.update(config)

        self._profiles: Dict[str, UserProfile] = {}
        self._user_rules: Dict[str, Dict[str, Rule]] = defaultdict(dict)
        self._overrides: Dict[str, Dict[str, UserRuleOverride]] = defaultdict(dict)
        self._usage_stats: Dict[str, UserUsageStats] = {}
        self._default_rules: Dict[str, Rule] = {}
        self._org_defaults: Dict[str, Dict[str, Rule]] = defaultdict(dict)
        self._lock = RLock()
        self._resolver: Optional[Callable[[Rule, Rule, str], Rule]] = None

        self._load_state()
        logger.info(
            "UserRuleStore initialized (backend=%s, inheritance=%s)",
            self._backend_type.value,
            self._inheritance_mode.value,
        )

    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for the user rule store."""
        return {
            "max_user_profiles": 10000,
            "max_rules_per_user": 100,
            "max_overrides_per_user": 200,
            "max_rule_name_length": 200,
            "enable_usage_tracking": True,
            "enable_audit_log": True,
            "auto_save_profiles": True,
            "auto_save_rules": True,
            "cache_enabled": True,
            "cache_ttl_seconds": 300,
            "inheritance_depth_limit": 5,
            "override_expiry_check_interval": 3600,
            "storage_format": "json",
            "compress_storage": False,
            "allow_cross_user_sharing": False,
            "default_inheritance_mode": "merge",
            "default_resolution_strategy": "user_preference",
        }

    def create_user_profile(self, profile: UserProfile) -> UserProfile:
        """Create a new user profile in the store."""
        with self._lock:
            if profile.user_id in self._profiles:
                logger.warning("User profile already exists: %s", profile.user_id)
                return self._profiles[profile.user_id]

            if len(self._profiles) >= self._config["max_user_profiles"]:
                raise UserRuleLimitError(
                    f"Maximum user profiles reached ({self._config['max_user_profiles']})"
                )

            now = datetime.utcnow()
            profile.created_at = now
            profile.updated_at = now
            self._profiles[profile.user_id] = profile
            self._usage_stats[profile.user_id] = UserUsageStats(user_id=profile.user_id)

            if self._config["auto_save_profiles"]:
                self._save_user_profile(profile)
                self._save_usage_stats(self._usage_stats[profile.user_id])

            logger.info("Created user profile: %s (%s)", profile.username, profile.user_id)
            return deepcopy(profile)

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get a user profile by user ID."""
        with self._lock:
            profile = self._profiles.get(user_id)
            return deepcopy(profile) if profile else None

    def update_user_profile(self, user_id: str, updates: Dict[str, Any]) -> UserProfile:
        """Update a user profile with partial updates."""
        with self._lock:
            profile = self._profiles.get(user_id)
            if not profile:
                raise UserNotFoundError(f"User profile not found: {user_id}")

            for key, value in updates.items():
                if hasattr(profile, key) and key not in ("user_id", "created_at"):
                    setattr(profile, key, value)

            profile.updated_at = datetime.utcnow()

            if self._config["auto_save_profiles"]:
                self._save_user_profile(profile)

            logger.info("Updated user profile: %s", user_id)
            return deepcopy(profile)

    def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user and their rules."""
        with self._lock:
            profile = self._profiles.get(user_id)
            if not profile:
                raise UserNotFoundError(f"User profile not found: {user_id}")
            profile.is_active = False
            profile.updated_at = datetime.utcnow()
            for rule in self._user_rules.get(user_id, {}).values():
                rule.status = RuleStatus.INACTIVE
            if self._config["auto_save_profiles"]:
                self._save_user_profile(profile)
            logger.info("Deactivated user: %s", user_id)
            return True

    def add_user_rule(
        self,
        user_id: str,
        rule: Rule,
        skip_inheritance: bool = False,
    ) -> Rule:
        """Add a rule specific to a user."""
        with self._lock:
            profile = self._profiles.get(user_id)
            if not profile or not profile.is_active:
                raise UserNotFoundError(f"Active user profile not found: {user_id}")

            user_rules = self._user_rules[user_id]
            if len(user_rules) >= min(profile.max_custom_rules, self._config["max_rules_per_user"]):
                raise UserRuleLimitError(
                    f"User {user_id} has reached max rules "
                    f"({profile.max_custom_rules})"
                )

            rule.created_by = user_id
            rule.created_at = datetime.utcnow()
            rule.updated_at = datetime.utcnow()
            user_rules[rule.id] = rule

            if not skip_inheritance:
                self._apply_inheritance(user_id, rule)

            if self._config["auto_save_rules"]:
                self._save_user_rule(user_id, rule)

            self._record_user_action(user_id, "rule_created")
            logger.info("Added rule '%s' for user %s", rule.name, user_id)
            return deepcopy(rule)

    def get_user_rule(self, user_id: str, rule_id: str) -> Optional[Rule]:
        """Get a user-specific rule."""
        with self._lock:
            user_rules = self._user_rules.get(user_id, {})
            rule = user_rules.get(rule_id)
            if rule:
                return deepcopy(rule)
            profile = self._profiles.get(user_id)
            if profile and profile.organization_id:
                org_rule = self._org_defaults.get(profile.organization_id, {}).get(rule_id)
                if org_rule:
                    return deepcopy(org_rule)
            return self._default_rules.get(rule_id)

    def get_user_rules(self, user_id: str) -> Dict[str, Rule]:
        """Get all rules for a user, including inherited rules."""
        with self._lock:
            result = {}
            profile = self._profiles.get(user_id)
            if not profile:
                return result

            for rid, rule in self._default_rules.items():
                result[rid] = deepcopy(rule)

            if profile.organization_id:
                org_rules = self._org_defaults.get(profile.organization_id, {})
                for rid, rule in org_rules.items():
                    if rid not in result or self._inheritance_mode == InheritanceMode.OVERRIDE:
                        result[rid] = deepcopy(rule)

            user_rules = self._user_rules.get(user_id, {})
            for rid, rule in user_rules.items():
                if rid in result:
                    merged = self._merge_rules(result[rid], rule, user_id)
                    result[rid] = merged
                else:
                    result[rid] = deepcopy(rule)

            overrides = self._overrides.get(user_id, {})
            for rid, override in overrides.items():
                if override.is_expired():
                    continue
                if rid in result:
                    rule = result[rid]
                    if hasattr(rule, override.parameter):
                        setattr(rule, override.parameter, override.overridden_value)

            return result

    def update_user_rule(
        self,
        user_id: str,
        rule_id: str,
        updates: Dict[str, Any],
    ) -> Rule:
        """Update a user-specific rule."""
        with self._lock:
            user_rules = self._user_rules.get(user_id, {})
            rule = user_rules.get(rule_id)
            if not rule:
                raise KeyError(f"Rule {rule_id} not found for user {user_id}")

            for key, value in updates.items():
                if hasattr(rule, key) and key not in ("id", "created_at", "created_by"):
                    setattr(rule, key, value)

            rule.updated_at = datetime.utcnow()

            if self._config["auto_save_rules"]:
                self._save_user_rule(user_id, rule)

            self._record_user_action(user_id, "rule_updated")
            logger.info("Updated rule '%s' for user %s", rule.name, user_id)
            return deepcopy(rule)

    def delete_user_rule(self, user_id: str, rule_id: str) -> bool:
        """Delete a user-specific rule."""
        with self._lock:
            user_rules = self._user_rules.get(user_id, {})
            if rule_id not in user_rules:
                return False

            del user_rules[rule_id]
            self._overrides.get(user_id, {}).pop(rule_id, None)

            if self._config["auto_save_rules"]:
                self._delete_user_rule_file(user_id, rule_id)

            self._record_user_action(user_id, "rule_deleted")
            logger.info("Deleted rule '%s' for user %s", rule_id, user_id)
            return True

    def set_rule_override(
        self,
        user_id: str,
        rule_id: str,
        parameter: str,
        value: Any,
        reason: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> UserRuleOverride:
        """Set a user-specific override for a rule parameter."""
        with self._lock:
            rule = self.get_user_rule(user_id, rule_id)
            if not rule:
                raise KeyError(f"Rule {rule_id} not accessible for user {user_id}")

            original = getattr(rule, parameter, None)
            if original is None:
                raise ValueError(f"Parameter '{parameter}' not found on rule")

            expires_at = None
            if ttl_seconds is not None:
                expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

            override = UserRuleOverride(
                rule_id=rule_id,
                parameter=parameter,
                original_value=original,
                overridden_value=value,
                reason=reason,
                expires_at=expires_at,
            )

            self._overrides[user_id][f"{rule_id}:{parameter}"] = override
            setattr(rule, parameter, value)

            self._record_user_action(user_id, "override_set")
            logger.info(
                "Set override for user %s, rule %s, parameter %s",
                user_id, rule_id, parameter,
            )
            return override

    def remove_rule_override(self, user_id: str, rule_id: str, parameter: str) -> bool:
        """Remove a user-specific rule override."""
        with self._lock:
            key = f"{rule_id}:{parameter}"
            overrides = self._overrides.get(user_id, {})
            if key not in overrides:
                return False
            del overrides[key]
            self._record_user_action(user_id, "override_removed")
            return True

    def get_user_overrides(self, user_id: str) -> Dict[str, UserRuleOverride]:
        """Get all active overrides for a user."""
        with self._lock:
            overrides = self._overrides.get(user_id, {})
            active = {}
            for key, override in overrides.items():
                if not override.is_expired():
                    active[key] = deepcopy(override)
            return active

    def set_default_rules(self, rules: List[Rule]) -> int:
        """Set global default rules that apply to all users."""
        with self._lock:
            count = 0
            for rule in rules:
                self._default_rules[rule.id] = rule
                count += 1
            logger.info("Set %d default rules", count)
            return count

    def set_organization_rules(
        self,
        org_id: str,
        rules: List[Rule],
    ) -> int:
        """Set organization-level default rules."""
        with self._lock:
            org_rules = self._org_defaults[org_id]
            count = 0
            for rule in rules:
                org_rules[rule.id] = rule
                count += 1
            logger.info("Set %d organization rules for org %s", count, org_id)
            return count

    def set_inheritance_mode(self, mode: str) -> None:
        """Set the rule inheritance mode."""
        self._inheritance_mode = InheritanceMode(mode)
        logger.info("Inheritance mode set to %s", mode)

    def set_resolution_strategy(self, strategy: str) -> None:
        """Set the conflict resolution strategy."""
        self._config["default_resolution_strategy"] = strategy
        logger.info("Resolution strategy set to %s", strategy)

    def register_custom_resolver(
        self,
        resolver: Callable[[Rule, Rule, str], Rule],
    ) -> None:
        """Register a custom rule conflict resolver."""
        self._resolver = resolver

    def export_user_rules(
        self,
        user_id: str,
        format_type: str = "json",
    ) -> Union[str, List[Dict[str, Any]]]:
        """Export all rules for a user."""
        rules = self.get_user_rules(user_id)
        rule_dicts = [r.dict() for r in rules.values()]
        for rd in rule_dicts:
            for key in ("created_at", "updated_at"):
                if key in rd and isinstance(rd[key], datetime):
                    rd[key] = rd[key].isoformat()
        if format_type == "json":
            return json.dumps(rule_dicts, indent=2, default=str)
        elif format_type == "yaml":
            return yaml.dump(rule_dicts, default_flow_style=False)
        return rule_dicts

    def import_user_rules(
        self,
        user_id: str,
        rules_data: List[Dict[str, Any]],
        strategy: str = "merge",
    ) -> int:
        """Import rules for a user from dictionary data."""
        count = 0
        for data in rules_data:
            try:
                rule = Rule(**data)
                existing = self._user_rules.get(user_id, {}).get(rule.id)
                if existing and strategy == "skip":
                    continue
                self.add_user_rule(user_id, rule)
                count += 1
            except Exception as exc:
                logger.error("Failed to import rule for user %s: %s", user_id, exc)
        return count

    def get_user_usage_stats(self, user_id: str) -> Optional[UserUsageStats]:
        """Get usage statistics for a user."""
        with self._lock:
            stats = self._usage_stats.get(user_id)
            return deepcopy(stats) if stats else None

    def record_evaluation(self, user_id: str) -> None:
        """Record a rule evaluation for a user."""
        with self._lock:
            stats = self._usage_stats.get(user_id)
            if stats:
                stats.record_evaluation()
                if self._config["auto_save_profiles"]:
                    self._save_usage_stats(stats)

    def get_active_user_count(self) -> int:
        """Get count of active users."""
        with self._lock:
            return sum(1 for p in self._profiles.values() if p.is_active)

    def get_user_count_by_organization(self, org_id: str) -> int:
        """Get count of users belonging to an organization."""
        with self._lock:
            return sum(
                1 for p in self._profiles.values()
                if p.organization_id == org_id and p.is_active
            )

    def cleanup_expired_overrides(self) -> int:
        """Remove all expired overrides across all users."""
        with self._lock:
            total = 0
            for user_id, overrides in self._overrides.items():
                expired_keys = [
                    key for key, override in overrides.items()
                    if override.is_expired()
                ]
                for key in expired_keys:
                    del overrides[key]
                    total += 1
                if expired_keys:
                    self._usage_stats[user_id].overrides_expired += len(expired_keys)
            logger.info("Cleaned up %d expired overrides", total)
            return total

    def _apply_inheritance(self, user_id: str, rule: Rule) -> None:
        """Apply inheritance settings to a user rule."""
        if self._inheritance_mode == InheritanceMode.NONE:
            return
        profile = self._profiles.get(user_id)
        if not profile:
            return
        if profile.organization_id:
            org_rules = self._org_defaults.get(profile.organization_id, {})
            org_rule = org_rules.get(rule.id)
            if org_rule:
                rule.enforcement_level = org_rule.enforcement_level
                rule.severity = org_rule.severity
        if self._inheritance_mode == InheritanceMode.STRICT:
            rule.user_override = False

    def _merge_rules(self, default: Rule, user_rule: Rule, user_id: str) -> Rule:
        """Merge a default rule with a user rule."""
        merged = deepcopy(default)
        strategy = self._config["default_resolution_strategy"]

        if self._resolver:
            return self._resolver(default, user_rule, user_id)

        if strategy == "user_preference":
            for field in ("priority", "enforcement_level", "severity", "auto_block"):
                setattr(merged, field, getattr(user_rule, field, getattr(default, field)))
        elif strategy == "most_restrictive":
            severity_order = ["low", "medium", "high", "critical"]
            default_sev = default.severity.value
            user_sev = user_rule.severity.value
            if severity_order.index(user_sev) > severity_order.index(default_sev):
                merged.severity = user_rule.severity
            if user_rule.auto_block:
                merged.auto_block = True
            enforcement_order = ["fallback", "adaptive", "advisory", "strict"]
            default_enf = default.enforcement_level.value
            user_enf = user_rule.enforcement_level.value
            if enforcement_order.index(user_enf) > enforcement_order.index(default_enf):
                merged.enforcement_level = user_rule.enforcement_level
        elif strategy == "least_restrictive":
            severity_order = ["low", "medium", "high", "critical"]
            default_sev = default.severity.value
            user_sev = user_rule.severity.value
            if severity_order.index(user_sev) < severity_order.index(default_sev):
                merged.severity = user_rule.severity
            if not user_rule.auto_block:
                merged.auto_block = False

        merged.user_override = default.user_override and user_rule.user_override
        merged.tags = list(set(default.tags + user_rule.tags))
        merged.updated_at = datetime.utcnow()
        return merged

    def _record_user_action(self, user_id: str, action: str) -> None:
        """Record a user action for usage tracking."""
        if not self._config["enable_usage_tracking"]:
            return
        stats = self._usage_stats.get(user_id)
        if not stats:
            return
        if action == "rule_created":
            stats.rules_created += 1
        elif action == "rule_updated":
            stats.rules_modified += 1
        elif action == "rule_deleted":
            stats.rules_deleted += 1
        elif action == "override_set":
            stats.overrides_applied += 1
        stats.last_active_at = datetime.utcnow()
        if self._config["auto_save_profiles"]:
            self._save_usage_stats(stats)

    def _load_state(self) -> None:
        """Load all user data from storage."""
        self._load_user_profiles()
        self._load_user_rules()
        self._load_user_overrides()
        self._load_usage_stats()
        self._load_default_rules()

    def _load_user_profiles(self) -> None:
        """Load user profiles from storage."""
        profiles_path = Path(self._storage_path) / "profiles"
        if not profiles_path.exists():
            profiles_path.mkdir(parents=True, exist_ok=True)
            return
        for file_path in profiles_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile = UserProfile.from_dict(data)
                self._profiles[profile.user_id] = profile
            except Exception as exc:
                logger.error("Failed to load user profile from %s: %s", file_path, exc)

    def _load_user_rules(self) -> None:
        """Load user-specific rules from storage."""
        rules_path = Path(self._storage_path) / "rules"
        if not rules_path.exists():
            rules_path.mkdir(parents=True, exist_ok=True)
            return
        for user_dir in rules_path.iterdir():
            if not user_dir.is_dir():
                continue
            user_id = user_dir.name
            for file_path in user_dir.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    rule = Rule(**data)
                    self._user_rules[user_id][rule.id] = rule
                except Exception as exc:
                    logger.error(
                        "Failed to load user rule from %s: %s", file_path, exc
                    )

    def _load_user_overrides(self) -> None:
        """Load user overrides from storage."""
        overrides_path = Path(self._storage_path) / "overrides"
        if not overrides_path.exists():
            overrides_path.mkdir(parents=True, exist_ok=True)
            return
        for file_path in overrides_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for user_id, overrides_list in data.items():
                    for override_data in overrides_list:
                        override = UserRuleOverride.from_dict(override_data)
                        key = f"{override.rule_id}:{override.parameter}"
                        self._overrides[user_id][key] = override
            except Exception as exc:
                logger.error(
                    "Failed to load user overrides from %s: %s", file_path, exc
                )

    def _load_usage_stats(self) -> None:
        """Load usage statistics from storage."""
        stats_path = Path(self._storage_path) / "usage_stats"
        if not stats_path.exists():
            stats_path.mkdir(parents=True, exist_ok=True)
            return
        for file_path in stats_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                stats = UserUsageStats.from_dict(data)
                self._usage_stats[stats.user_id] = stats
            except Exception as exc:
                logger.error(
                    "Failed to load usage stats from %s: %s", file_path, exc
                )

    def _load_default_rules(self) -> None:
        """Load default global rules from storage."""
        defaults_path = Path(self._storage_path) / "defaults"
        if not defaults_path.exists():
            defaults_path.mkdir(parents=True, exist_ok=True)
            return
        for file_path in defaults_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                rule = Rule(**data)
                self._default_rules[rule.id] = rule
            except Exception as exc:
                logger.error(
                    "Failed to load default rule from %s: %s", file_path, exc
                )

    def _save_user_profile(self, profile: UserProfile) -> None:
        """Save a user profile to storage."""
        profiles_path = Path(self._storage_path) / "profiles"
        profiles_path.mkdir(parents=True, exist_ok=True)
        file_path = profiles_path / f"{profile.user_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, indent=2, default=str)

    def _save_user_rule(self, user_id: str, rule: Rule) -> None:
        """Save a user rule to storage."""
        rules_path = Path(self._storage_path) / "rules" / user_id
        rules_path.mkdir(parents=True, exist_ok=True)
        file_path = rules_path / f"{rule.id}.json"
        rule_dict = rule.dict()
        for key in ("created_at", "updated_at"):
            if key in rule_dict and isinstance(rule_dict[key], datetime):
                rule_dict[key] = rule_dict[key].isoformat()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(rule_dict, f, indent=2, default=str)

    def _save_usage_stats(self, stats: UserUsageStats) -> None:
        """Save usage statistics to storage."""
        stats_path = Path(self._storage_path) / "usage_stats"
        stats_path.mkdir(parents=True, exist_ok=True)
        file_path = stats_path / f"{stats.user_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(stats.to_dict(), f, indent=2, default=str)

    def _delete_user_rule_file(self, user_id: str, rule_id: str) -> None:
        """Delete a user rule file from storage."""
        file_path = Path(self._storage_path) / "rules" / user_id / f"{rule_id}.json"
        if file_path.exists():
            file_path.unlink()
