"""
Rule version manager for versioning predefined rules across catalog releases.

Provides semantic versioning support, version migration between releases,
changelog generation, backward compatibility checking, version rollback,
deprecation management, and config-driven version policy.
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
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple, Union
from collections import defaultdict, OrderedDict

import yaml

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)

logger = logging.getLogger(__name__)


class VersionBumpType(str, Enum):
    """Types of version bumps."""
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    PRE_RELEASE = "pre_release"


class VersionState(str, Enum):
    """Lifecycle states for a version."""
    DRAFT = "draft"
    RELEASED = "released"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"


class CompatibilityLevel(str, Enum):
    """Levels of backward compatibility."""
    FULL = "full"
    PARTIAL = "partial"
    BREAKING = "breaking"
    UNKNOWN = "unknown"


class MigrationStatus(str, Enum):
    """Status of a version migration."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


@dataclass
class VersionInfo:
    """Information about a specific version."""

    version: str
    state: VersionState = VersionState.DRAFT
    released_at: Optional[datetime] = None
    released_by: Optional[str] = None
    changelog: List[Dict[str, Any]] = field(default_factory=list)
    compatibility: CompatibilityLevel = CompatibilityLevel.UNKNOWN
    dependencies: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        result: Dict[str, Any] = {
            "version": self.version,
            "state": self.state.value,
            "changelog": self.changelog,
            "compatibility": self.compatibility.value,
            "dependencies": self.dependencies,
            "metadata": self.metadata,
        }
        if self.released_at:
            result["released_at"] = self.released_at.isoformat()
        if self.released_by:
            result["released_by"] = self.released_by
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VersionInfo":
        """Create from dictionary."""
        info = cls(
            version=data.get("version", "0.0.0"),
            state=VersionState(data.get("state", "draft")),
            changelog=data.get("changelog", []),
            compatibility=CompatibilityLevel(data.get("compatibility", "unknown")),
            dependencies=data.get("dependencies", {}),
            metadata=data.get("metadata", {}),
        )
        if data.get("released_at"):
            try:
                info.released_at = datetime.fromisoformat(data["released_at"])
            except (ValueError, TypeError):
                pass
        info.released_by = data.get("released_by")
        return info


@dataclass
class MigrationStep:
    """A single step in a version migration."""

    step_id: str
    description: str
    migration_type: str
    source_version: str
    target_version: str
    action: Callable[[Dict[str, Any]], Dict[str, Any]]
    rollback_action: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    requires_approval: bool = False
    timeout_seconds: int = 60

    def execute(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the migration step."""
        return self.action(data)

    def rollback(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the rollback action if available."""
        if self.rollback_action:
            return self.rollback_action(data)
        raise NotImplementedError("No rollback action defined for this step")


@dataclass
class MigrationPlan:
    """A complete migration plan between versions."""

    plan_id: str
    source_version: str
    target_version: str
    steps: List[MigrationStep] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: MigrationStatus = MigrationStatus.PENDING
    requires_approval: bool = False
    estimated_duration_seconds: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: MigrationStep) -> None:
        """Add a step to the migration plan."""
        self.steps.append(step)
        self.estimated_duration_seconds += step.timeout_seconds

    def estimate_duration(self) -> int:
        """Estimate total migration duration in seconds."""
        return sum(step.timeout_seconds for step in self.steps)


@dataclass
class DeprecationNotice:
    """Notice about a rule or version being deprecated."""

    rule_id: str
    version_deprecated: str
    deprecation_date: datetime
    removal_version: str
    migration_path: str
    reason: str
    alternative_rule_id: Optional[str] = None
    notice_period_days: int = 90

    def days_until_removal(self) -> int:
        """Get days remaining until the removal version."""
        return self.notice_period_days - (datetime.utcnow() - self.deprecation_date).days

    def is_past_removal(self) -> bool:
        """Check if the removal date has passed."""
        return self.days_until_removal() <= 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "rule_id": self.rule_id,
            "version_deprecated": self.version_deprecated,
            "deprecation_date": self.deprecation_date.isoformat(),
            "removal_version": self.removal_version,
            "migration_path": self.migration_path,
            "reason": self.reason,
            "alternative_rule_id": self.alternative_rule_id,
            "notice_period_days": self.notice_period_days,
        }


class VersionPolicy:
    """Config-driven version policy for rule version management."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = {
            "version_prefix": "",
            "strict_semver": True,
            "allow_pre_release": True,
            "max_version_history": 50,
            "min_notice_period_days": 30,
            "require_changelog": True,
            "require_compatibility_check": True,
            "auto_deprecate_older_versions": True,
            "max_major_versions_behind": 3,
            "migration_timeout_seconds": 300,
            "rollback_enabled": True,
            "max_rollback_attempts": 3,
            "backup_before_migration": True,
            "parallel_step_execution": False,
        }
        if config:
            self._config.update(config)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a policy value."""
        return self._config.get(key, default)

    def validate_version_format(self, version: str) -> bool:
        """Validate that a version string conforms to policy."""
        pattern = r"^\d+\.\d+\.\d+$"
        if self._config.get("allow_pre_release", True):
            pattern = r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$"
        return bool(re.match(pattern, version))


class RuleVersionManager:
    """Manager for versioning predefined rules across catalog releases.

    Handles semantic versioning, version migration, changelog generation,
    backward compatibility checking, version rollback, and deprecation management.
    """

    def __init__(
        self,
        catalog_name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._catalog_name = catalog_name
        self._policy = VersionPolicy(config)
        self._versions: Dict[str, VersionInfo] = {}
        self._current_version: Optional[str] = None
        self._migration_plans: Dict[str, MigrationPlan] = {}
        self._migration_history: List[Dict[str, Any]] = []
        self._deprecation_notices: Dict[str, DeprecationNotice] = {}
        self._version_snapshots: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock()
        self._migration_handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
        self._compat_cache: Dict[Tuple[str, str], CompatibilityLevel] = {}

        self._initialize()
        logger.info(
            "RuleVersionManager initialized for '%s' (current: %s)",
            self._catalog_name,
            self._current_version or "none",
        )

    def _initialize(self) -> None:
        """Initialize the version manager with a starting version."""
        initial_version = VersionInfo(
            version="1.0.0",
            state=VersionState.RELEASED,
            released_at=datetime.utcnow(),
            changelog=[{
                "type": "initial",
                "description": f"Initial release of {self._catalog_name}",
                "date": datetime.utcnow().isoformat(),
            }],
            compatibility=CompatibilityLevel.FULL,
        )
        self._versions["1.0.0"] = initial_version
        self._current_version = "1.0.0"

    def get_current_version(self) -> str:
        """Get the current version string."""
        return self._current_version or "0.0.0"

    def get_version_info(self, version: Optional[str] = None) -> Optional[VersionInfo]:
        """Get version info for a specific version."""
        key = version or self._current_version
        return self._versions.get(key) if key else None

    def list_versions(
        self,
        state: Optional[VersionState] = None,
        include_draft: bool = False,
    ) -> List[VersionInfo]:
        """List all versions, optionally filtered by state."""
        versions = list(self._versions.values())
        if state:
            versions = [v for v in versions if v.state == state]
        if not include_draft:
            versions = [v for v in versions if v.state != VersionState.DRAFT]
        versions.sort(key=lambda v: self._parse_version_key(v.version), reverse=True)
        return versions

    def _parse_version_key(self, version: str) -> Tuple[int, int, int, int]:
        """Parse version into a sortable key tuple."""
        try:
            parts = version.split("-")[0].split(".")
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            pre = 1 if "-" in version else 0
            return (major, minor, patch, pre)
        except (ValueError, IndexError):
            return (0, 0, 0, 0)

    def bump_version(
        self,
        bump_type: VersionBumpType,
        pre_release_tag: Optional[str] = None,
        changelog_entries: Optional[List[Dict[str, Any]]] = None,
        released_by: Optional[str] = None,
    ) -> str:
        """Create a new version by bumping the current version."""
        with self._lock:
            current = self._current_version or "0.0.0"
            new_version = self._calculate_bump(current, bump_type, pre_release_tag)

            if new_version in self._versions:
                raise ValueError(f"Version {new_version} already exists")

            compatibility = self._determine_compatibility(current, new_version, bump_type)

            changelog = changelog_entries or [{
                "type": bump_type.value,
                "description": f"{bump_type.value.capitalize()} bump from {current} to {new_version}",
                "date": datetime.utcnow().isoformat(),
            }]

            if self._current_version:
                old_info = self._versions.get(self._current_version)
                if old_info:
                    old_info.state = VersionState.SUPERSEDED

            version_info = VersionInfo(
                version=new_version,
                state=VersionState.RELEASED,
                released_at=datetime.utcnow(),
                released_by=released_by,
                changelog=changelog,
                compatibility=compatibility,
            )
            self._versions[new_version] = version_info
            self._current_version = new_version

            self._create_version_snapshot(new_version)

            logger.info(
                "Version bumped: %s -> %s (%s)",
                current, new_version, bump_type.value,
            )
            return new_version

    def _calculate_bump(
        self,
        current: str,
        bump_type: VersionBumpType,
        pre_release_tag: Optional[str] = None,
    ) -> str:
        """Calculate the new version string after a bump."""
        try:
            main_part = current.split("-")[0] if "-" in current else current
            parts = main_part.split(".")
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

            if bump_type == VersionBumpType.MAJOR:
                major += 1
                minor = 0
                patch = 0
            elif bump_type == VersionBumpType.MINOR:
                minor += 1
                patch = 0
            elif bump_type == VersionBumpType.PATCH:
                patch += 1
            elif bump_type == VersionBumpType.PRE_RELEASE:
                if "-" in current:
                    pre_parts = current.split("-")
                    base = pre_parts[0]
                    tag = pre_release_tag or "dev"
                    if len(pre_parts) > 1 and pre_parts[1].startswith(tag):
                        try:
                            num = int(pre_parts[1].replace(tag, ""))
                            return f"{base}-{tag}{num + 1}"
                        except ValueError:
                            return f"{base}-{tag}1"
                    return f"{base}-{tag}1"
                else:
                    tag = pre_release_tag or "dev"
                    return f"{current}-{tag}1"
            else:
                raise ValueError(f"Unknown bump type: {bump_type}")

            return f"{major}.{minor}.{patch}"
        except (ValueError, IndexError) as exc:
            raise ValueError(f"Invalid current version format: {current}") from exc

    def _determine_compatibility(
        self,
        source: str,
        target: str,
        bump_type: VersionBumpType,
    ) -> CompatibilityLevel:
        """Determine compatibility level based on version bump."""
        if bump_type == VersionBumpType.MAJOR:
            return CompatibilityLevel.BREAKING
        elif bump_type == VersionBumpType.MINOR:
            return CompatibilityLevel.PARTIAL
        elif bump_type == VersionBumpType.PATCH:
            return CompatibilityLevel.FULL
        elif bump_type == VersionBumpType.PRE_RELEASE:
            return CompatibilityLevel.UNKNOWN
        return CompatibilityLevel.UNKNOWN

    def create_migration_plan(
        self,
        source_version: str,
        target_version: str,
    ) -> MigrationPlan:
        """Create a migration plan from source to target version."""
        with self._lock:
            if source_version not in self._versions:
                raise ValueError(f"Source version {source_version} not found")
            if target_version not in self._versions:
                raise ValueError(f"Target version {target_version} not found")

            plan_id = f"migrate_{source_version}_to_{target_version}_{uuid.uuid4().hex[:8]}"
            plan = MigrationPlan(
                plan_id=plan_id,
                source_version=source_version,
                target_version=target_version,
            )

            source_info = self._versions[source_version]
            target_info = self._versions[target_version]
            source_compat = source_info.compatibility
            target_compat = target_info.compatibility

            plan.add_step(MigrationStep(
                step_id=f"{plan_id}_validation",
                description=f"Validate migration readiness from {source_version} to {target_version}",
                migration_type="validation",
                source_version=source_version,
                target_version=target_version,
                action=lambda data: self._migration_validation(data, source_version, target_version),
                rollback_action=lambda data: data,
                timeout_seconds=30,
            ))

            if target_compat == CompatibilityLevel.BREAKING:
                plan.add_step(MigrationStep(
                    step_id=f"{plan_id}_breaking",
                    description="Handle breaking changes",
                    migration_type="breaking_changes",
                    source_version=source_version,
                    target_version=target_version,
                    action=lambda data: self._handle_breaking_changes(data, source_version, target_version),
                    requires_approval=True,
                    timeout_seconds=120,
                ))

            plan.add_step(MigrationStep(
                step_id=f"{plan_id}_data_migration",
                description=f"Migrate data structures from {source_version} to {target_version}",
                migration_type="data_migration",
                source_version=source_version,
                target_version=target_version,
                action=lambda data: self._migrate_data(data, source_version, target_version),
                rollback_action=lambda data: self._rollback_data(data, source_version, target_version),
                timeout_seconds=60,
            ))

            plan.estimated_duration_seconds = plan.estimate_duration()

            version_path = self._resolve_version_path(source_version, target_version)
            if version_path:
                for intermediate_version in version_path:
                    plan.add_step(MigrationStep(
                        step_id=f"{plan_id}_step_{intermediate_version}",
                        description=f"Incremental migration through {intermediate_version}",
                        migration_type="incremental",
                        source_version=source_version,
                        target_version=intermediate_version,
                        action=lambda data, v=intermediate_version: self._incremental_migration(data, v),
                        timeout_seconds=30,
                    ))

            self._migration_plans[plan_id] = plan
            logger.info(
                "Created migration plan %s: %s -> %s (%d steps)",
                plan_id, source_version, target_version, len(plan.steps),
            )
            return plan

    def _resolve_version_path(self, source: str, target: str) -> List[str]:
        """Resolve the version path through intermediate versions."""
        all_versions = sorted(
            [v for v in self._versions.keys() if v not in (source, target)],
            key=lambda v: self._parse_version_key(v),
        )
        path: List[str] = []
        source_key = self._parse_version_key(source)
        target_key = self._parse_version_key(target)

        for version in all_versions:
            v_key = self._parse_version_key(version)
            if source_key < v_key < target_key:
                path.append(version)

        return path

    def _migration_validation(
        self,
        data: Dict[str, Any],
        source: str,
        target: str,
    ) -> Dict[str, Any]:
        """Validate migration readiness."""
        source_info = self._versions.get(source)
        target_info = self._versions.get(target)
        if not source_info or not target_info:
            raise ValueError("Source or target version not found")

        compat = self.check_compatibility(source, target)
        data["_migration_compatibility"] = compat.value
        data["_migration_validated"] = True
        return data

    def _handle_breaking_changes(
        self,
        data: Dict[str, Any],
        source: str,
        target: str,
    ) -> Dict[str, Any]:
        """Handle breaking changes during migration."""
        breaking_items: List[Dict[str, Any]] = []
        for key, value in data.items():
            if isinstance(value, dict):
                if "version" in value and value["version"] == source:
                    breaking_items.append({"key": key, "old_value": value})
                    value["version"] = target
                    value["_migrated"] = True
        data["_breaking_changes_handled"] = len(breaking_items)
        return data

    def _migrate_data(
        self,
        data: Dict[str, Any],
        source: str,
        target: str,
    ) -> Dict[str, Any]:
        """Migrate data structures between versions."""
        source_key = self._parse_version_key(source)
        target_key = self._parse_version_key(target)

        rules = data.get("rules", [])
        for rule in rules:
            if isinstance(rule, dict):
                rule["_migration_log"] = rule.get("_migration_log", [])
                rule["_migration_log"].append({
                    "from": source,
                    "to": target,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                if source_key[0] < target_key[0]:
                    self._apply_major_migration(rule, source_key, target_key)
                elif source_key[1] < target_key[1]:
                    self._apply_minor_migration(rule, source_key, target_key)
                elif source_key[2] < target_key[2]:
                    self._apply_patch_migration(rule, source_key, target_key)

        data["rules"] = rules
        data["_migrated"] = True
        return data

    def _apply_major_migration(self, rule: Dict[str, Any], source: Tuple, target: Tuple) -> None:
        """Apply major version data migration to a rule dict."""
        deprecated_keys = ["legacy_field", "old_naming"]
        for key in deprecated_keys:
            if key in rule:
                new_key = key.replace("legacy_", "").replace("old_", "")
                rule[new_key] = rule.pop(key)
        if "compatibility_mode" in rule:
            rule["compatibility_mode"] = "updated"

    def _apply_minor_migration(self, rule: Dict[str, Any], source: Tuple, target: Tuple) -> None:
        """Apply minor version data migration to a rule dict."""
        if "tags" in rule and isinstance(rule["tags"], list):
            rule["tags"] = list(set(rule["tags"]))
        if "version" in rule:
            rule["version"] = f"{target[0]}.{target[1]}.{target[2]}"

    def _apply_patch_migration(self, rule: Dict[str, Any], source: Tuple, target: Tuple) -> None:
        """Apply patch version data migration to a rule dict."""
        if "version" in rule:
            rule["version"] = f"{target[0]}.{target[1]}.{target[2]}"

    def _rollback_data(
        self,
        data: Dict[str, Any],
        source: str,
        target: str,
    ) -> Dict[str, Any]:
        """Rollback data migration."""
        rules = data.get("rules", [])
        for rule in rules:
            if isinstance(rule, dict):
                migration_log = rule.get("_migration_log", [])
                if migration_log:
                    migration_log.pop()
                rule["version"] = source
        data["rules"] = rules
        data["_rolled_back"] = True
        return data

    def _incremental_migration(
        self,
        data: Dict[str, Any],
        target_version: str,
    ) -> Dict[str, Any]:
        """Perform incremental migration through an intermediate version."""
        data["_intermediate_version"] = target_version
        return data

    def execute_migration(
        self,
        plan_id: str,
        data: Dict[str, Any],
        approve_breaking: bool = False,
    ) -> Dict[str, Any]:
        """Execute a migration plan against data."""
        with self._lock:
            plan = self._migration_plans.get(plan_id)
            if not plan:
                raise ValueError(f"Migration plan not found: {plan_id}")

            if plan.status == MigrationStatus.COMPLETED:
                raise ValueError(f"Migration plan {plan_id} already completed")

            result = deepcopy(data)
            plan.status = MigrationStatus.IN_PROGRESS
            step_results: List[Dict[str, Any]] = []

            try:
                for i, step in enumerate(plan.steps):
                    if step.requires_approval and not approve_breaking:
                        plan.status = MigrationStatus.PENDING
                        logger.warning(
                            "Migration step %d requires approval: %s", i, step.description
                        )
                        raise ValueError(
                            f"Step '{step.description}' requires approval. "
                            "Set approve_breaking=True to proceed."
                        )

                    logger.info(
                        "Executing migration step %d/%d: %s",
                        i + 1, len(plan.steps), step.description,
                    )
                    step_result = step.execute(result)
                    step_results.append({
                        "step_id": step.step_id,
                        "description": step.description,
                        "success": True,
                    })
                    result = step_result

                plan.status = MigrationStatus.COMPLETED
                plan.metadata["completed_at"] = datetime.utcnow().isoformat()

                self._migration_history.append({
                    "plan_id": plan_id,
                    "source": plan.source_version,
                    "target": plan.target_version,
                    "completed_at": datetime.utcnow().isoformat(),
                    "step_results": step_results,
                })

                logger.info(
                    "Migration %s completed: %s -> %s",
                    plan_id, plan.source_version, plan.target_version,
                )
                result["_migration_plan_id"] = plan_id
                return result

            except Exception as exc:
                plan.status = MigrationStatus.FAILED
                logger.error("Migration %s failed: %s", plan_id, exc)
                if self._policy.get("rollback_enabled", True):
                    logger.info("Attempting rollback for migration %s", plan_id)
                    result = self._rollback_migration(plan, result)
                plan.metadata["error"] = str(exc)
                result["_migration_error"] = str(exc)
                raise

    def _rollback_migration(
        self,
        plan: MigrationPlan,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Rollback a failed migration."""
        result = deepcopy(data)
        for step in reversed(plan.steps):
            if step.rollback_action:
                try:
                    result = step.rollback_action(result)
                except Exception as exc:
                    logger.error("Rollback step %s failed: %s", step.step_id, exc)
        plan.status = MigrationStatus.ROLLED_BACK
        plan.metadata["rolled_back_at"] = datetime.utcnow().isoformat()
        self._migration_history.append({
            "plan_id": plan.plan_id,
            "status": "rolled_back",
            "rolled_back_at": datetime.utcnow().isoformat(),
        })
        logger.info("Migration %s rolled back successfully", plan.plan_id)
        return result

    def get_migration_plan(self, plan_id: str) -> Optional[MigrationPlan]:
        """Get a migration plan by ID."""
        return self._migration_plans.get(plan_id)

    def list_migration_plans(self) -> List[MigrationPlan]:
        """List all migration plans."""
        return list(self._migration_plans.values())

    def get_migration_history(self) -> List[Dict[str, Any]]:
        """Get history of all executed migrations."""
        return list(self._migration_history)

    def check_compatibility(self, source: str, target: str) -> CompatibilityLevel:
        """Check backward compatibility between two versions."""
        cache_key = (source, target)
        if cache_key in self._compat_cache:
            return self._compat_cache[cache_key]

        source_info = self._versions.get(source)
        target_info = self._versions.get(target)
        if not source_info or not target_info:
            return CompatibilityLevel.UNKNOWN

        source_key = self._parse_version_key(source)
        target_key = self._parse_version_key(target)

        if source_key[0] != target_key[0]:
            result = CompatibilityLevel.BREAKING
        elif source_key[1] != target_key[1]:
            result = CompatibilityLevel.PARTIAL
        elif source_key[2] != target_key[2]:
            result = CompatibilityLevel.FULL
        else:
            result = CompatibilityLevel.FULL

        self._compat_cache[cache_key] = result
        return result

    def get_breaking_changes_between(self, source: str, target: str) -> List[str]:
        """Get list of breaking changes between two versions."""
        breaking_changes: List[str] = []
        source_key = self._parse_version_key(source)
        target_key = self._parse_version_key(target)

        if source_key[0] < target_key[0]:
            for v_key in self._versions:
                if self._parse_version_key(v_key) > source_key and self._parse_version_key(v_key) <= target_key:
                    v_info = self._versions[v_key]
                    for entry in v_info.changelog:
                        if entry.get("type") in ("major", "breaking"):
                            breaking_changes.append(
                                f"[{v_key}] {entry.get('description', 'Unknown change')}"
                            )
        return breaking_changes

    def deprecate_version(
        self,
        version: str,
        removal_version: str,
        reason: str,
        migration_path: str,
        alternative_rule_id: Optional[str] = None,
    ) -> DeprecationNotice:
        """Deprecate a specific version."""
        with self._lock:
            if version not in self._versions:
                raise ValueError(f"Version {version} not found")

            version_info = self._versions[version]
            version_info.state = VersionState.DEPRECATED

            notice = DeprecationNotice(
                rule_id=self._catalog_name,
                version_deprecated=version,
                deprecation_date=datetime.utcnow(),
                removal_version=removal_version,
                migration_path=migration_path,
                reason=reason,
                alternative_rule_id=alternative_rule_id,
            )
            self._deprecation_notices[version] = notice
            logger.info(
                "Deprecated version %s, removal in %s: %s",
                version, removal_version, reason,
            )
            return notice

    def get_deprecation_notices(self, active_only: bool = True) -> List[DeprecationNotice]:
        """Get all deprecation notices."""
        notices = list(self._deprecation_notices.values())
        if active_only:
            notices = [n for n in notices if not n.is_past_removal()]
        return notices

    def get_deprecation_notice(self, version: str) -> Optional[DeprecationNotice]:
        """Get deprecation notice for a specific version."""
        return self._deprecation_notices.get(version)

    def rollback_to_version(self, version: str, reason: str) -> str:
        """Rollback the current version to a previous version."""
        with self._lock:
            if version not in self._versions:
                raise ValueError(f"Target version {version} not found")

            current = self._current_version
            if not current:
                raise ValueError("No current version to rollback from")

            version_info = self._versions[version]
            if version_info.state in (VersionState.DEPRECATED, VersionState.ROLLED_BACK):
                raise ValueError(f"Cannot rollback to deprecated or rolled-back version {version}")

            if self._current_version:
                old_info = self._versions.get(self._current_version)
                if old_info:
                    old_info.state = VersionState.ROLLED_BACK

            rollback_info = VersionInfo(
                version=f"{version}-rollback-{int(time.time())}",
                state=VersionState.RELEASED,
                released_at=datetime.utcnow(),
                changelog=[{
                    "type": "rollback",
                    "description": f"Rollback from {current} to {version}: {reason}",
                    "date": datetime.utcnow().isoformat(),
                    "original_version": current,
                    "rollback_target": version,
                }],
                compatibility=CompatibilityLevel.UNKNOWN,
            )
            self._versions[rollback_info.version] = rollback_info
            self._current_version = rollback_info.version

            logger.warning(
                "Rolled back from %s to %s (new version: %s): %s",
                current, version, rollback_info.version, reason,
            )
            return rollback_info.version

    def generate_changelog(
        self,
        from_version: Optional[str] = None,
        to_version: Optional[str] = None,
        format_type: str = "markdown",
    ) -> str:
        """Generate a changelog string for a version range."""
        source = from_version or "1.0.0"
        target = to_version or self._current_version or "1.0.0"

        entries: List[Dict[str, Any]] = []
        for v_key in sorted(self._versions.keys(), key=lambda v: self._parse_version_key(v)):
            v_key_parsed = self._parse_version_key(v_key)
            source_parsed = self._parse_version_key(source)
            target_parsed = self._parse_version_key(target)
            if source_parsed <= v_key_parsed <= target_parsed:
                v_info = self._versions[v_key]
                for entry in v_info.changelog:
                    entries.append({
                        "version": v_key,
                        **entry,
                    })

        if format_type == "markdown":
            return self._format_changelog_markdown(entries)
        elif format_type == "json":
            return json.dumps(entries, indent=2, default=str)
        elif format_type == "yaml":
            return yaml.dump(entries, default_flow_style=False)
        else:
            return self._format_changelog_markdown(entries)

    def _format_changelog_markdown(self, entries: List[Dict[str, Any]]) -> str:
        """Format changelog entries as markdown."""
        lines: List[str] = ["# Changelog", ""]
        current_version: Optional[str] = None

        for entry in entries:
            if entry.get("version") != current_version:
                current_version = entry.get("version")
                lines.append(f"## [{current_version}]")
                lines.append("")

            entry_type = entry.get("type", "change").capitalize()
            description = entry.get("description", "No description")
            lines.append(f"- **{entry_type}**: {description}")

        return "\n".join(lines)

    def _create_version_snapshot(self, version: str) -> None:
        """Create a snapshot of the current version state."""
        self._version_snapshots[version] = {
            "version": version,
            "created_at": datetime.utcnow().isoformat(),
            "snapshot_id": uuid.uuid4().hex,
        }

    def get_version_snapshot(self, version: str) -> Optional[Dict[str, Any]]:
        """Get a version snapshot."""
        return self._version_snapshots.get(version)

    def get_migration_handlers(self) -> Dict[str, Callable]:
        """Get registered migration handlers."""
        return dict(self._migration_handlers)

    def register_migration_handler(
        self,
        name: str,
        handler: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> None:
        """Register a custom migration handler."""
        self._migration_handlers[name] = handler
        logger.debug("Registered migration handler: %s", name)

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about version management."""
        total_versions = len(self._versions)
        released = sum(1 for v in self._versions.values() if v.state == VersionState.RELEASED)
        deprecated = sum(1 for v in self._versions.values() if v.state == VersionState.DEPRECATED)
        superseded = sum(1 for v in self._versions.values() if v.state == VersionState.SUPERSEDED)
        migrated_plans = sum(1 for p in self._migration_plans.values() if p.status == MigrationStatus.COMPLETED)
        failed_plans = sum(1 for p in self._migration_plans.values() if p.status == MigrationStatus.FAILED)

        return {
            "catalog_name": self._catalog_name,
            "current_version": self._current_version,
            "total_versions": total_versions,
            "released_versions": released,
            "deprecated_versions": deprecated,
            "superseded_versions": superseded,
            "total_migration_plans": len(self._migration_plans),
            "completed_migrations": migrated_plans,
            "failed_migrations": failed_plans,
            "active_deprecation_notices": len(self.get_deprecation_notices(active_only=True)),
            "total_snapshots": len(self._version_snapshots),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the version manager state to a dictionary."""
        return {
            "catalog_name": self._catalog_name,
            "current_version": self._current_version,
            "versions": {k: v.to_dict() for k, v in self._versions.items()},
            "migration_history": self._migration_history,
            "deprecation_notices": {k: v.to_dict() for k, v in self._deprecation_notices.items()},
            "snapshots": self._version_snapshots,
        }

    @classmethod
    def from_dict(cls, catalog_name: str, data: Dict[str, Any]) -> "RuleVersionManager":
        """Create a version manager from a dictionary."""
        manager = cls(catalog_name)
        manager._versions = {
            k: VersionInfo.from_dict(v) for k, v in data.get("versions", {}).items()
        }
        manager._current_version = data.get("current_version")
        manager._migration_history = data.get("migration_history", [])
        for version, notice_data in data.get("deprecation_notices", {}).items():
            manager._deprecation_notices[version] = DeprecationNotice(**notice_data)
        return manager

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_json(cls, catalog_name: str, json_str: str) -> "RuleVersionManager":
        """Create from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(catalog_name, data)
