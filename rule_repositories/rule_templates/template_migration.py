"""
Rule template migration - version tracking, migration scripts, backward-compatible
upgrades, migration testing, rollback support, and changelog tracking.
"""

import copy
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

from rules_emerging_pattern.models.rule import Rule

from .template_engine import RuleTemplateEngine, TemplateError
from .template_validator import RuleTemplateValidator, ValidationReport, ValidationSeverity

logger = logging.getLogger(__name__)


class MigrationStatus(str, Enum):
    """Status of a migration operation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    PARTIALLY_COMPLETED = "partially_completed"
    SKIPPED = "skipped"


class MigrationType(str, Enum):
    """Type of migration being performed."""
    VERSION_BUMP = "version_bump"
    FIELD_ADDED = "field_added"
    FIELD_REMOVED = "field_removed"
    FIELD_RENAMED = "field_renamed"
    FIELD_TYPE_CHANGED = "field_type_changed"
    STRUCTURE_CHANGED = "structure_changed"
    SYNTAX_CHANGED = "syntax_changed"
    SCHEMA_UPGRADE = "schema_upgrade"
    BACKWARD_COMPAT = "backward_compat"
    CUSTOM = "custom"


class MigrationError(Exception):
    """Base exception for migration errors."""


class MigrationScriptError(MigrationError):
    """Raised when a migration script encounters an error."""


class RollbackError(MigrationError):
    """Raised when rollback fails."""


class VersionConflictError(MigrationError):
    """Raised when there is a version conflict during migration."""


@dataclass
class MigrationRecord:
    """Record of a single migration operation."""
    migration_id: str
    template_name: str
    source_version: str
    target_version: str
    migration_type: MigrationType
    status: MigrationStatus
    timestamp: datetime = field(default_factory=datetime.utcnow)
    duration_ms: float = 0.0
    applied_by: Optional[str] = None
    description: str = ""
    changelog_entry: str = ""
    rollback_available: bool = False
    rollback_script_id: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "migration_id": self.migration_id,
            "template_name": self.template_name,
            "source_version": self.source_version,
            "target_version": self.target_version,
            "migration_type": self.migration_type.value,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "applied_by": self.applied_by,
            "description": self.description,
            "changelog_entry": self.changelog_entry,
            "rollback_available": self.rollback_available,
            "rollback_script_id": self.rollback_script_id,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


@dataclass
class MigrationPlan:
    """Plan for migrating a template from one version to another."""
    template_name: str
    source_version: str
    target_version: str
    steps: List["MigrationStep"] = field(default_factory=list)
    prerequisites: List[str] = field(default_factory=list)
    estimated_risk: str = "low"
    dry_run_possible: bool = True
    requires_validation: bool = True
    parallel_safe: bool = False

    def add_step(self, step: "MigrationStep") -> None:
        """Add a migration step to the plan."""
        self.steps.append(step)

    def is_empty(self) -> bool:
        """Check if plan has no steps."""
        return len(self.steps) == 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "template_name": self.template_name,
            "source_version": self.source_version,
            "target_version": self.target_version,
            "steps": [s.to_dict() for s in self.steps],
            "prerequisites": self.prerequisites,
            "estimated_risk": self.estimated_risk,
            "dry_run_possible": self.dry_run_possible,
            "requires_validation": self.requires_validation,
            "parallel_safe": self.parallel_safe,
        }


@dataclass
class MigrationStep:
    """Single step within a migration plan."""
    step_id: str
    description: str
    migration_type: MigrationType
    migration_func: Optional[Callable[..., Any]] = None
    rollback_func: Optional[Callable[..., Any]] = None
    params: Dict[str, Any] = field(default_factory=dict)
    rollback_params: Dict[str, Any] = field(default_factory=dict)
    required: bool = True
    order: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "step_id": self.step_id,
            "description": self.description,
            "migration_type": self.migration_type.value,
            "required": self.required,
            "order": self.order,
            "params": self.params,
        }


class ChangelogEntry:
    """Entry in the template migration changelog."""

    def __init__(
        self,
        version: str,
        changes: List[str],
        date: Optional[datetime] = None,
        author: Optional[str] = None,
    ) -> None:
        self.version = version
        self.changes = changes
        self.date = date or datetime.utcnow()
        self.author = author

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "version": self.version,
            "changes": self.changes,
            "date": self.date.isoformat(),
            "author": self.author,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChangelogEntry":
        """Create from dictionary."""
        return cls(
            version=data["version"],
            changes=data["changes"],
            date=datetime.fromisoformat(data["date"]) if "date" in data else None,
            author=data.get("author"),
        )


class MigrationScript:
    """Script that performs a specific migration operation."""

    def __init__(
        self,
        script_id: str,
        source_version: str,
        target_version: str,
        description: str,
    ) -> None:
        self.script_id = script_id
        self.source_version = source_version
        self.target_version = target_version
        self.description = description
        self._migrate_func: Optional[Callable] = None
        self._rollback_func: Optional[Callable] = None
        self._validate_func: Optional[Callable] = None

    def set_migrate_func(self, func: Callable) -> None:
        """Set the migration function."""
        self._migrate_func = func

    def set_rollback_func(self, func: Callable) -> None:
        """Set the rollback function."""
        self._rollback_func = func

    def set_validate_func(self, func: Callable) -> None:
        """Set the validation function."""
        self._validate_func = func

    def execute(
        self,
        template_data: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute the migration script on template data."""
        if self._migrate_func is None:
            raise MigrationScriptError(
                f"No migrate function set for script '{self.script_id}'"
            )
        try:
            result = self._migrate_func(template_data, **(params or {}))
            return result
        except Exception as exc:
            raise MigrationScriptError(
                f"Script '{self.script_id}' execution failed: {exc}"
            ) from exc

    def rollback(
        self,
        template_data: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Rollback the migration script on template data."""
        if self._rollback_func is None:
            raise MigrationScriptError(
                f"No rollback function set for script '{self.script_id}'"
            )
        try:
            result = self._rollback_func(template_data, **(params or {}))
            return result
        except Exception as exc:
            raise MigrationScriptError(
                f"Rollback '{self.script_id}' execution failed: {exc}"
            ) from exc

    def validate(
        self,
        template_data: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Validate template data before/after migration."""
        if self._validate_func is None:
            return []
        try:
            errors = self._validate_func(template_data, **(params or {}))
            return errors if isinstance(errors, list) else [str(errors)]
        except Exception as exc:
            return [f"Validation error in '{self.script_id}': {exc}"]


class VersionComparator:
    """Compares and manipulates semantic version strings."""

    @staticmethod
    def parse(version: str) -> Tuple[int, int, int]:
        """Parse a semver string into (major, minor, patch)."""
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version.strip())
        if not match:
            raise ValueError(f"Invalid version format: '{version}'")
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    @staticmethod
    def compare(v1: str, v2: str) -> int:
        """Compare two versions: -1 if v1<v2, 0 if equal, 1 if v1>v2."""
        p1 = VersionComparator.parse(v1)
        p2 = VersionComparator.parse(v2)
        if p1 < p2:
            return -1
        if p1 > p2:
            return 1
        return 0

    @staticmethod
    def bump_major(version: str) -> str:
        """Bump the major version component."""
        major, minor, patch = VersionComparator.parse(version)
        return f"{major + 1}.0.0"

    @staticmethod
    def bump_minor(version: str) -> str:
        """Bump the minor version component."""
        major, minor, patch = VersionComparator.parse(version)
        return f"{major}.{minor + 1}.0"

    @staticmethod
    def bump_patch(version: str) -> str:
        """Bump the patch version component."""
        major, minor, patch = VersionComparator.parse(version)
        return f"{major}.{minor}.{patch + 1}"

    @staticmethod
    def satisfies(version: str, constraint: str) -> bool:
        """Check if version satisfies a constraint (e.g. '>=1.0.0')."""
        version_parts = VersionComparator.parse(version)

        match = re.match(
            r"^(>=|<=|>|<|==|!=|~>)\s*(\d+\.\d+\.\d+)$", constraint.strip()
        )
        if not match:
            raise ValueError(f"Invalid constraint format: '{constraint}'")

        operator = match.group(1)
        target = VersionComparator.parse(match.group(2))

        if operator == "==":
            return version_parts == target
        elif operator == "!=":
            return version_parts != target
        elif operator == ">":
            return version_parts > target
        elif operator == ">=":
            return version_parts >= target
        elif operator == "<":
            return version_parts < target
        elif operator == "<=":
            return version_parts <= target
        elif operator == "~>":
            return (
                version_parts >= target
                and version_parts[0] == target[0]
                and version_parts[1] >= target[1]
            )
        return False


class BuiltinMigrationScripts:
    """Collection of built-in migration scripts."""

    @staticmethod
    def add_field(
        template_data: Dict[str, Any],
        field_name: str,
        default_value: Any = None,
        field_type: str = "string",
    ) -> Dict[str, Any]:
        """Add a new field to the template data."""
        if "version" not in template_data:
            template_data["version"] = "1.0.0"
        result = copy.deepcopy(template_data)
        if field_name not in result:
            result[field_name] = default_value
            logger.info("Added field '%s' with default %s", field_name, default_value)
        return result

    @staticmethod
    def remove_field(
        template_data: Dict[str, Any],
        field_name: str,
    ) -> Dict[str, Any]:
        """Remove a field from template data."""
        result = copy.deepcopy(template_data)
        if field_name in result:
            del result[field_name]
            logger.info("Removed field '%s'", field_name)
        return result

    @staticmethod
    def rename_field(
        template_data: Dict[str, Any],
        old_name: str,
        new_name: str,
        keep_old: bool = False,
    ) -> Dict[str, Any]:
        """Rename a field in template data."""
        result = copy.deepcopy(template_data)
        if old_name in result:
            result[new_name] = result[old_name]
            if not keep_old:
                del result[old_name]
            logger.info("Renamed field '%s' to '%s'", old_name, new_name)
        return result

    @staticmethod
    def change_field_type(
        template_data: Dict[str, Any],
        field_name: str,
        new_type: str,
    ) -> Dict[str, Any]:
        """Change the type annotation of a field."""
        if field_name not in template_data:
            logger.warning("Field '%s' not found for type change", field_name)
            return template_data
        result = copy.deepcopy(template_data)
        if "variables" in result:
            for var in result["variables"]:
                if var.get("name") == field_name:
                    var["type"] = new_type
                    break
        if "_field_types" not in result:
            result["_field_types"] = {}
        result["_field_types"][field_name] = new_type
        return result

    @staticmethod
    def wrap_in_namespace(
        template_data: Dict[str, Any],
        namespace: str,
    ) -> Dict[str, Any]:
        """Wrap template data in a namespace key."""
        result = {namespace: copy.deepcopy(template_data)}
        if "version" in template_data:
            result["version"] = template_data["version"]
        return result

    @staticmethod
    def flatten_namespace(
        template_data: Dict[str, Any],
        namespace: str,
    ) -> Dict[str, Any]:
        """Flatten a namespace key into the root."""
        if namespace in template_data and isinstance(template_data[namespace], dict):
            result = copy.deepcopy(template_data[namespace])
            for key, value in template_data.items():
                if key != namespace:
                    result[key] = copy.deepcopy(value)
            return result
        return copy.deepcopy(template_data)

    @staticmethod
    def update_field_to_enum(
        template_data: Dict[str, Any],
        field_name: str,
        old_value: str,
        new_value: str,
    ) -> Dict[str, Any]:
        """Update a specific field value from old to new enum variant."""
        result = copy.deepcopy(template_data)
        if field_name in result and str(result[field_name]) == old_value:
            result[field_name] = new_value
            logger.info("Updated '%s' from '%s' to '%s'", field_name, old_value, new_value)
        return result

    @staticmethod
    def add_tag_prefix(
        template_data: Dict[str, Any],
        prefix: str,
    ) -> Dict[str, Any]:
        """Add a prefix to all existing tags."""
        result = copy.deepcopy(template_data)
        if "tags" in result and isinstance(result["tags"], list):
            result["tags"] = [f"{prefix}:{tag}" for tag in result["tags"]]
        return result

    @staticmethod
    def restructure_patterns(
        template_data: Dict[str, Any],
        pattern_key: str = "pattern",
    ) -> Dict[str, Any]:
        """Restructure a single pattern field to a patterns list."""
        result = copy.deepcopy(template_data)
        if pattern_key in result and "patterns" not in result:
            result["patterns"] = [result[pattern_key]]
            del result[pattern_key]
            logger.info("Restructured '%s' to 'patterns' list", pattern_key)
        return result

    @staticmethod
    def add_metadata_field(
        template_data: Dict[str, Any],
        key: str,
        value: Any,
    ) -> Dict[str, Any]:
        """Add a metadata field to the template."""
        result = copy.deepcopy(template_data)
        if "metadata" not in result:
            result["metadata"] = {}
        result["metadata"][key] = value
        return result

    @staticmethod
    def convert_version_format(
        template_data: Dict[str, Any],
        source_format: str = "legacy",
    ) -> Dict[str, Any]:
        """Convert from a legacy version format to semver."""
        result = copy.deepcopy(template_data)
        version = result.get("version", "")
        if source_format == "legacy" and re.match(r"^v?(\d+)$", version):
            match = re.match(r"^v?(\d+)$", version)
            if match:
                result["version"] = f"{match.group(1)}.0.0"
        elif source_format == "major_minor" and re.match(r"^(\d+)\.(\d+)$", version):
            match = re.match(r"^(\d+)\.(\d+)$", version)
            if match:
                result["version"] = f"{match.group(1)}.{match.group(2)}.0"
        return result


class RuleTemplateMigration:
    """Manages template version migrations with tracking, rollback, and testing."""

    def __init__(
        self,
        engine: Optional[RuleTemplateEngine] = None,
        validator: Optional[RuleTemplateValidator] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.engine = engine or RuleTemplateEngine()
        self.validator = validator
        self.config = config or self._default_config()
        self._lock = RLock()
        self._migration_history: List[MigrationRecord] = []
        self._migration_scripts: Dict[str, MigrationScript] = {}
        self._changelog: Dict[str, List[ChangelogEntry]] = {}
        self._register_builtin_scripts()

    def _default_config(self) -> Dict[str, Any]:
        """Return the default migration configuration."""
        return {
            "max_migration_retries": 3,
            "auto_rollback_on_failure": True,
            "backup_before_migration": True,
            "validate_after_migration": True,
            "require_validation_pass": True,
            "max_migration_history": 1000,
            "migration_timeout_seconds": 300,
            "allow_downgrade": True,
            "version_check_enabled": True,
            "changelog_enabled": True,
            "backup_directory": None,
        }

    def _register_builtin_scripts(self) -> None:
        """Register built-in migration scripts."""
        builtins = [
            ("add_field", "0.0.0", "1.0.0", "Add a new field", BuiltinMigrationScripts.add_field),
            ("remove_field", "0.0.0", "1.0.0", "Remove a field", BuiltinMigrationScripts.remove_field),
            ("rename_field", "0.0.0", "1.0.0", "Rename a field", BuiltinMigrationScripts.rename_field),
            ("change_field_type", "0.0.0", "1.0.0", "Change field type", BuiltinMigrationScripts.change_field_type),
            ("wrap_namespace", "1.0.0", "2.0.0", "Wrap in namespace", BuiltinMigrationScripts.wrap_in_namespace),
            ("flatten_namespace", "2.0.0", "1.0.0", "Flatten namespace", BuiltinMigrationScripts.flatten_namespace),
            ("update_enum", "0.0.0", "1.0.0", "Update enum value", BuiltinMigrationScripts.update_field_to_enum),
            ("add_tag_prefix", "1.0.0", "1.1.0", "Add tag prefix", BuiltinMigrationScripts.add_tag_prefix),
            ("restructure_patterns", "1.0.0", "1.1.0", "Restructure patterns", BuiltinMigrationScripts.restructure_patterns),
            ("add_metadata", "0.0.0", "1.0.0", "Add metadata field", BuiltinMigrationScripts.add_metadata_field),
            ("convert_version", "0.0.0", "1.0.0", "Convert version format", BuiltinMigrationScripts.convert_version_format),
        ]
        for script_id, src_ver, tgt_ver, desc, func in builtins:
            script = MigrationScript(script_id, src_ver, tgt_ver, desc)
            script.set_migrate_func(func)
            script.set_rollback_func(BuiltinMigrationScripts.remove_field)
            self.register_script(script)

    def register_script(self, script: MigrationScript) -> None:
        """Register a migration script."""
        with self._lock:
            self._migration_scripts[script.script_id] = script

    def get_script(self, script_id: str) -> Optional[MigrationScript]:
        """Get a registered migration script by ID."""
        return self._migration_scripts.get(script_id)

    def list_scripts(self) -> List[Dict[str, Any]]:
        """List all registered migration scripts."""
        return [
            {
                "id": s.script_id,
                "source_version": s.source_version,
                "target_version": s.target_version,
                "description": s.description,
            }
            for s in self._migration_scripts.values()
        ]

    def create_migration_plan(
        self,
        template_data: Dict[str, Any],
        target_version: str,
    ) -> MigrationPlan:
        """Create a migration plan from current version to target version."""
        current_version = template_data.get("version", "0.0.0")
        template_name = template_data.get("name", "<unknown>")

        plan = MigrationPlan(
            template_name=template_name,
            source_version=current_version,
            target_version=target_version,
        )

        if current_version == target_version:
            return plan

        comparison = VersionComparator.compare(current_version, target_version)
        if comparison > 0 and not self.config.get("allow_downgrade"):
            raise VersionConflictError(
                f"Downgrade from {current_version} to {target_version} is not allowed"
            )

        intermediate_versions = self._resolve_migration_path(current_version, target_version)

        step_order = 0
        for version in intermediate_versions:
            matching_scripts = [
                s for s in self._migration_scripts.values()
                if s.source_version == version
            ]
            matching_scripts.sort(key=lambda s: s.script_id)
            for script in matching_scripts:
                step = MigrationStep(
                    step_id=script.script_id,
                    description=script.description,
                    migration_type=MigrationType.VERSION_BUMP,
                    migration_func=script._migrate_func,
                    rollback_func=script._rollback_func,
                    order=step_order,
                )
                plan.add_step(step)
                step_order += 1

        return plan

    def _resolve_migration_path(
        self,
        source_version: str,
        target_version: str,
    ) -> List[str]:
        """Resolve the chain of intermediate versions for migration."""
        comparison = VersionComparator.compare(source_version, target_version)
        if comparison == 0:
            return []

        available_versions: Set[str] = set()
        for script in self._migration_scripts.values():
            available_versions.add(script.source_version)
            available_versions.add(script.target_version)

        source_parts = VersionComparator.parse(source_version)
        target_parts = VersionComparator.parse(target_version)
        direction = 1 if comparison < 0 else -1

        path: List[str] = []
        current = source_parts
        while current != target_parts:
            next_version = (
                current[0] + direction,
                current[1] if direction > 0 else 0,
                current[2] if direction > 0 else 0,
            )
            if direction < 0:
                next_version = current
                next_major = current[0]
                next_minor = current[1] - 1
                next_patch = 0
                if next_minor < 0:
                    next_major -= 1
                    next_minor = 0
                next_version = (next_major, next_minor, next_patch)

            version_str = f"{next_version[0]}.{next_version[1]}.{next_version[2]}"
            path.append(version_str)

            if direction > 0 and VersionComparator.compare(version_str, target_version) >= 0:
                break
            if direction < 0 and VersionComparator.compare(version_str, target_version) <= 0:
                break
            current = VersionComparator.parse(version_str)

        return path

    def execute_migration(
        self,
        template_data: Dict[str, Any],
        target_version: str,
        template_name: str = "<unknown>",
        dry_run: bool = False,
    ) -> MigrationRecord:
        """Execute a migration plan on template data."""
        plan = self.create_migration_plan(template_data, target_version)
        template_name = template_data.get("name", template_name)

        record = MigrationRecord(
            migration_id=uuid.uuid4().hex[:16],
            template_name=template_name,
            source_version=template_data.get("version", "0.0.0"),
            target_version=target_version,
            migration_type=MigrationType.VERSION_BUMP,
            status=MigrationStatus.PENDING,
        )

        if plan.is_empty():
            record.status = MigrationStatus.SKIPPED
            record.description = "No migration needed - versions match"
            self._record_migration(record)
            return record

        if dry_run:
            record.status = MigrationStatus.PENDING
            record.description = "Dry run - no changes applied"
            for step in plan.steps:
                try:
                    step.migration_func(copy.deepcopy(template_data), **step.params)
                except Exception as exc:
                    record.error_message = f"Step '{step.step_id}' would fail: {exc}"
                    break
            return record

        backup = copy.deepcopy(template_data) if self.config.get("backup_before_migration") else None
        start_time = time.time()

        try:
            record.status = MigrationStatus.IN_PROGRESS
            current_data = copy.deepcopy(template_data)

            for step in plan.steps:
                try:
                    current_data = step.migration_func(
                        current_data, **step.params
                    ) or current_data
                    logger.info("Migration step '%s' completed", step.step_id)
                except Exception as exc:
                    raise MigrationScriptError(
                        f"Step '{step.step_id}' failed: {exc}"
                    ) from exc

            current_data["version"] = target_version

            if self.config.get("validate_after_migration") and self.validator:
                validation = self.validator.validate_data(current_data, template_name)
                if not validation.passed and self.config.get("require_validation_pass"):
                    raise MigrationError(
                        f"Post-migration validation failed: "
                        f"{len(validation.findings)} errors"
                    )

            record.status = MigrationStatus.COMPLETED
            record.duration_ms = (time.time() - start_time) * 1000
            record.description = f"Migrated from {record.source_version} to {target_version}"

            if self.config.get("changelog_enabled"):
                self._add_changelog_entry(
                    template_name,
                    target_version,
                    [f"Migrated from {record.source_version} to {target_version}"],
                )

        except Exception as exc:
            record.status = MigrationStatus.FAILED
            record.error_message = str(exc)
            record.duration_ms = (time.time() - start_time) * 1000

            if self.config.get("auto_rollback_on_failure") and backup is not None:
                try:
                    current_data = backup
                    record.status = MigrationStatus.ROLLED_BACK
                    record.description = f"Auto-rolled back to {record.source_version}"
                    logger.warning("Auto-rolled back migration for '%s'", template_name)
                except Exception as rollback_exc:
                    raise RollbackError(
                        f"Migration failed and rollback also failed: "
                        f"{exc}; rollback error: {rollback_exc}"
                    ) from rollback_exc
            else:
                raise MigrationError(f"Migration failed: {exc}") from exc

        self._record_migration(record)
        return record

    def rollback_migration(
        self,
        migration_id: str,
        template_data: Dict[str, Any],
    ) -> MigrationRecord:
        """Rollback a specific migration by ID."""
        with self._lock:
            record = None
            for r in self._migration_history:
                if r.migration_id == migration_id:
                    record = r
                    break

            if record is None:
                raise MigrationError(f"Migration record '{migration_id}' not found")

            if record.status == MigrationStatus.ROLLED_BACK:
                raise MigrationError(f"Migration '{migration_id}' already rolled back")

            rollback_record = MigrationRecord(
                migration_id=uuid.uuid4().hex[:16],
                template_name=record.template_name,
                source_version=record.target_version,
                target_version=record.source_version,
                migration_type=record.migration_type,
                status=MigrationStatus.IN_PROGRESS,
            )

            try:
                plan = self.create_migration_plan(
                    template_data, record.source_version
                )
                current_data = copy.deepcopy(template_data)

                for step in reversed(plan.steps):
                    if step.rollback_func:
                        current_data = step.rollback_func(
                            current_data, **step.rollback_params
                        ) or current_data

                current_data["version"] = record.source_version

                rollback_record.status = MigrationStatus.COMPLETED
                record.status = MigrationStatus.ROLLED_BACK
                rollback_record.description = (
                    f"Rolled back from {record.target_version} to {record.source_version}"
                )

            except Exception as exc:
                rollback_record.status = MigrationStatus.FAILED
                rollback_record.error_message = str(exc)
                raise RollbackError(f"Rollback failed: {exc}") from exc

            self._record_migration(rollback_record)
            return rollback_record

    def _record_migration(self, record: MigrationRecord) -> None:
        """Record a migration in the history."""
        with self._lock:
            self._migration_history.append(record)
            max_history = self.config.get("max_migration_history", 1000)
            if len(self._migration_history) > max_history:
                self._migration_history = self._migration_history[-max_history:]

    def _add_changelog_entry(
        self,
        template_name: str,
        version: str,
        changes: List[str],
        author: Optional[str] = None,
    ) -> None:
        """Add a changelog entry for a template version."""
        if template_name not in self._changelog:
            self._changelog[template_name] = []
        entry = ChangelogEntry(version=version, changes=changes, author=author)
        self._changelog[template_name].append(entry)

    def get_migration_history(
        self,
        template_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[MigrationRecord]:
        """Get migration history, optionally filtered by template."""
        with self._lock:
            if template_name:
                filtered = [
                    r for r in self._migration_history
                    if r.template_name == template_name
                ]
            else:
                filtered = list(self._migration_history)
            return filtered[-limit:]

    def get_changelog(
        self,
        template_name: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get the changelog for templates."""
        result: Dict[str, List[Dict[str, Any]]] = {}
        with self._lock:
            if template_name:
                entries = self._changelog.get(template_name, [])
                result[template_name] = [e.to_dict() for e in entries]
            else:
                for name, entries in self._changelog.items():
                    result[name] = [e.to_dict() for e in entries]
        return result

    def test_migration(
        self,
        template_data: Dict[str, Any],
        target_version: str,
        test_cases: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Test a migration without applying it permanently."""
        result: Dict[str, Any] = {
            "source_version": template_data.get("version", "0.0.0"),
            "target_version": target_version,
            "test_results": [],
            "passed": True,
        }

        plan = self.create_migration_plan(template_data, target_version)
        if plan.is_empty():
            result["message"] = "No migration needed - versions match"
            return result

        test_data = copy.deepcopy(template_data)

        for step in plan.steps:
            step_result = {"step_id": step.step_id, "success": False}
            try:
                migrated = step.migration_func(test_data, **step.params)
                test_data = migrated or test_data
                step_result["success"] = True

                if step.rollback_func:
                    rollback_data = step.rollback_func(
                        copy.deepcopy(test_data), **step.rollback_params
                    )
                    step_result["rollback_works"] = rollback_data is not None

            except Exception as exc:
                step_result["error"] = str(exc)
                result["passed"] = False

            result["test_results"].append(step_result)

        if test_cases:
            for idx, test_case in enumerate(test_cases):
                case_result = {"test_case": idx, "passed": True}
                test_data_copy = copy.deepcopy(template_data)
                for step in plan.steps:
                    try:
                        test_data_copy = step.migration_func(
                            test_data_copy, **(step.params)
                        ) or test_data_copy
                    except Exception as exc:
                        case_result["passed"] = False
                        case_result["error"] = str(exc)
                        break

                if "expected_output" in test_case:
                    for key, expected in test_case["expected_output"].items():
                        actual = test_data_copy.get(key)
                        if actual != expected:
                            case_result["passed"] = False
                            case_result.setdefault("mismatches", {})[key] = {
                                "expected": expected,
                                "actual": actual,
                            }

                result["test_results"].append(case_result)
                if not case_result.get("passed", True):
                    result["passed"] = False

        return result

    def get_migration_config(self) -> Dict[str, Any]:
        """Get current migration configuration."""
        return dict(self.config)

    def update_migration_config(self, updates: Dict[str, Any]) -> None:
        """Update migration configuration."""
        with self._lock:
            self.config.update(updates)

    def export_migration_history(self, file_path: str) -> None:
        """Export migration history to a JSON file."""
        history = [r.to_dict() for r in self._migration_history]
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(history, indent=2, default=str), encoding="utf-8"
        )
        logger.info("Exported %d migration records to %s", len(history), file_path)

    def import_migration_history(self, file_path: str) -> int:
        """Import migration history from a JSON file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Migration history file not found: {file_path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        count = 0
        for entry in data:
            record = MigrationRecord(
                migration_id=entry["migration_id"],
                template_name=entry["template_name"],
                source_version=entry["source_version"],
                target_version=entry["target_version"],
                migration_type=MigrationType(entry["migration_type"]),
                status=MigrationStatus(entry["status"]),
                timestamp=datetime.fromisoformat(entry["timestamp"]),
                duration_ms=entry.get("duration_ms", 0.0),
                applied_by=entry.get("applied_by"),
                description=entry.get("description", ""),
                changelog_entry=entry.get("changelog_entry", ""),
                rollback_available=entry.get("rollback_available", False),
                rollback_script_id=entry.get("rollback_script_id"),
                error_message=entry.get("error_message"),
                metadata=entry.get("metadata", {}),
            )
            self._record_migration(record)
            count += 1
        logger.info("Imported %d migration records from %s", count, file_path)
        return count
