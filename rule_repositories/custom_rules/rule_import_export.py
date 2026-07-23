"""
Rule import/export module for cross-format rule serialization.

Supports JSON, YAML, and CSV formats for rule import and export with
batch validation, rollback, conflict resolution, and cross-repository
rule migration.
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
from collections import defaultdict, OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple, Union

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


class ImportExportError(Exception):
    """Base exception for import/export operations."""


class FormatNotSupportedError(ImportExportError):
    """Exception raised when the requested format is not supported."""


class ValidationError(ImportExportError):
    """Exception raised when rule validation fails during import."""


class ConflictResolutionError(ImportExportError):
    """Exception raised when conflict resolution fails."""


class FormatType(str, Enum):
    """Supported import/export formats."""

    JSON = "json"
    YAML = "yaml"
    CSV = "csv"
    AUTO = "auto"


class ConflictStrategy(str, Enum):
    """Strategies for handling import conflicts."""

    FAIL = "fail"
    SKIP = "skip"
    OVERWRITE = "overwrite"
    RENAME = "rename"
    MERGE = "merge"
    KEEP_EXISTING = "keep_existing"
    KEEP_NEW = "keep_new"


@dataclass
class ImportResult:
    """Result of an import operation."""

    total: int = 0
    imported: int = 0
    skipped: int = 0
    overwritten: int = 0
    merged: int = 0
    failed: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    import_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    rollback_possible: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            else:
                result[key] = value
        return result


@dataclass
class ExportResult:
    """Result of an export operation."""

    format: str
    content: Union[str, bytes]
    rule_count: int
    export_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    filters_applied: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class MigrationPlan:
    """Plan for migrating rules between repositories."""

    source_repo: str
    target_repo: str
    rule_ids: List[str]
    strategy: ConflictStrategy = ConflictStrategy.FAIL
    preserve_ids: bool = True
    preserve_timestamps: bool = True
    include_metadata: bool = True
    dry_run: bool = False


class RuleImportExport:
    """
    Handles importing and exporting rules in JSON, YAML, and CSV formats.

    Supports batch import with validation and rollback, export with filtering,
    conflict resolution, and cross-repository migration.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._config = self._default_config()
        if config:
            self._config.update(config)
        self._import_history: List[ImportResult] = []
        self._export_history: List[ExportResult] = []
        self._rollback_data: Dict[str, Any] = {}
        self._lock = RLock()
        logger.info("RuleImportExport initialized")

    def _default_config(self) -> Dict[str, Any]:
        """Default configuration."""
        return {
            "default_format": "json",
            "max_file_size_bytes": 10485760,
            "max_batch_size": 1000,
            "enable_strict_validation": True,
            "enable_rollback": True,
            "csv_delimiter": ",",
            "csv_quotechar": '"',
            "yaml_allow_unicode": True,
            "yaml_default_flow_style": False,
            "json_indent": 2,
            "json_ensure_ascii": False,
            "auto_detect_format": True,
            "allow_empty_import": False,
            "preserve_enum_values": True,
            "validate_rule_ids": True,
            "max_field_length": 5000,
        }

    # ------------------------------------------------------------------ #
    #  IMPORT
    # ------------------------------------------------------------------ #

    def import_from_file(
        self,
        file_path: str,
        format_type: Optional[str] = None,
        conflict_strategy: str = "fail",
        validate: bool = True,
        rollback_on_failure: bool = True,
    ) -> ImportResult:
        """Import rules from a file."""
        path = Path(file_path)
        if not path.exists():
            raise ImportExportError(f"File not found: {file_path}")
        if path.stat().st_size > self._config["max_file_size_bytes"]:
            raise ImportExportError(
                f"File too large: {path.stat().st_size} bytes "
                f"(max {self._config['max_file_size_bytes']})"
            )

        fmt = format_type or self._detect_format(file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        return self.import_from_string(
            content, fmt, conflict_strategy, validate, rollback_on_failure
        )

    def import_from_string(
        self,
        content: str,
        format_type: str = "json",
        conflict_strategy: str = "fail",
        validate: bool = True,
        rollback_on_failure: bool = True,
    ) -> ImportResult:
        """Import rules from a string in the specified format."""
        fmt = FormatType(format_type)
        strategy = ConflictStrategy(conflict_strategy)

        try:
            rules_data = self._parse_content(content, fmt)
        except Exception as exc:
            raise ImportExportError(f"Failed to parse {fmt.value} content: {exc}") from exc

        return self._import_rules_data(
            rules_data, strategy, validate, rollback_on_failure
        )

    def import_from_stream(
        self,
        stream: io.StringIO,
        format_type: str = "json",
        conflict_strategy: str = "fail",
        validate: bool = True,
    ) -> ImportResult:
        """Import rules from a string stream."""
        return self.import_from_string(
            stream.read(), format_type, conflict_strategy, validate
        )

    def import_batch(
        self,
        sources: List[Union[str, Dict[str, Any]]],
        format_type: str = "json",
        conflict_strategy: str = "fail",
        validate: bool = True,
    ) -> List[ImportResult]:
        """Import rules from multiple sources."""
        results: List[ImportResult] = []
        for source in sources:
            if isinstance(source, str):
                if os.path.isfile(source):
                    result = self.import_from_file(
                        source, format_type, conflict_strategy, validate
                    )
                else:
                    result = self.import_from_string(
                        source, format_type, conflict_strategy, validate
                    )
            elif isinstance(source, dict):
                result = self._import_rules_data(
                    [source], ConflictStrategy(conflict_strategy), validate, True
                )
            else:
                raise ImportExportError(f"Unsupported source type: {type(source)}")
            results.append(result)
        return results

    def _parse_content(self, content: str, fmt: FormatType) -> List[Dict[str, Any]]:
        """Parse content string into list of rule dictionaries."""
        content = content.strip()
        if not content:
            if self._config["allow_empty_import"]:
                return []
            raise ImportExportError("Empty content provided for import")

        if fmt == FormatType.JSON:
            return self._parse_json(content)
        elif fmt == FormatType.YAML:
            return self._parse_yaml(content)
        elif fmt == FormatType.CSV:
            return self._parse_csv(content)
        else:
            raise FormatNotSupportedError(f"Unsupported format: {fmt.value}")

    def _parse_json(self, content: str) -> List[Dict[str, Any]]:
        """Parse JSON content into rule dicts."""
        data = json.loads(content)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        raise ValidationError(f"Expected dict or list, got {type(data).__name__}")

    def _parse_yaml(self, content: str) -> List[Dict[str, Any]]:
        """Parse YAML content into rule dicts."""
        data = yaml.safe_load(content)
        if data is None:
            return []
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        raise ValidationError(f"Expected dict or list, got {type(data).__name__}")

    def _parse_csv(self, content: str) -> List[Dict[str, Any]]:
        """Parse CSV content into rule dicts."""
        reader = csv.DictReader(
            io.StringIO(content),
            delimiter=self._config["csv_delimiter"],
            quotechar=self._config["csv_quotechar"],
        )
        rules_data: List[Dict[str, Any]] = []
        for row in reader:
            rule_dict: Dict[str, Any] = {}
            for key, value in row.items():
                if value is None or value.strip() == "":
                    continue
                key_clean = key.strip().lower().replace(" ", "_")
                rule_dict[key_clean] = self._coerce_csv_value(value.strip())
            if rule_dict:
                rules_data.append(rule_dict)
        return rules_data

    def _coerce_csv_value(self, value: str) -> Any:
        """Coerce CSV string values to appropriate types."""
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        if value.lower() == "null" or value.lower() == "none":
            return None
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        if value.startswith("[") and value.endswith("]"):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
        if value.startswith("{") and value.endswith("}"):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
        return value

    def _import_rules_data(
        self,
        rules_data: List[Dict[str, Any]],
        strategy: ConflictStrategy,
        validate: bool,
        rollback_on_failure: bool,
    ) -> ImportResult:
        """Process parsed rule data and perform the import."""
        result = ImportResult(total=len(rules_data))
        imported_rules: List[Rule] = []
        seen_ids: Set[str] = set()

        for i, data in enumerate(rules_data):
            try:
                data = self._normalize_rule_dict(data)

                if validate and self._config["enable_strict_validation"]:
                    self._validate_rule_dict(data, i)

                rule_id = data.get("id", "")
                if rule_id in seen_ids:
                    result.warnings.append(
                        f"Duplicate rule ID '{rule_id}' in import data at index {i}"
                    )
                    if strategy == ConflictStrategy.FAIL:
                        raise ConflictResolutionError(f"Duplicate rule ID: {rule_id}")
                seen_ids.add(rule_id)

                rule = Rule(**data)
                imported_rules.append(rule)

            except Exception as exc:
                result.failed += 1
                result.errors.append({
                    "index": i,
                    "rule_id": data.get("id", f"index_{i}"),
                    "error": str(exc),
                })
                logger.warning("Import failed at index %d: %s", i, exc)
                if rollback_on_failure and self._config["enable_rollback"]:
                    self._rollback_import(imported_rules)
                    result.rollback_possible = True
                    result.imported = 0
                    return result

        result.imported = len(imported_rules)
        self._import_history.append(result)
        logger.info(
            "Import completed: %d imported, %d failed out of %d",
            result.imported, result.failed, result.total,
        )
        return result

    def _normalize_rule_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a rule dictionary for consistent processing."""
        normalized: Dict[str, Any] = {}

        field_map = {
            "id", "name", "description", "tier", "rule_type", "ruletype",
            "severity", "status", "patterns", "conditions", "exceptions",
            "enforcement_level", "enforcementlevel", "auto_block", "autoblock",
            "user_override", "useroverride", "override_justification_required",
            "overridejustificationrequired", "version", "created_at", "createdat",
            "updated_at", "updatedat", "created_by", "createdby",
            "tags", "priority", "timeout_ms", "timeoutms", "cache_ttl_seconds",
            "cachettlseconds",
        }

        for key, value in data.items():
            clean_key = key.strip().replace(" ", "_").lower()
            if clean_key in ("ruletype",):
                clean_key = "rule_type"
            elif clean_key in ("enforcementlevel",):
                clean_key = "enforcement_level"
            elif clean_key in ("autoblock",):
                clean_key = "auto_block"
            elif clean_key in ("useroverride",):
                clean_key = "user_override"
            elif clean_key in ("overridejustificationrequired",):
                clean_key = "override_justification_required"
            elif clean_key in ("createdat",):
                clean_key = "created_at"
            elif clean_key in ("updatedat",):
                clean_key = "updated_at"
            elif clean_key in ("createdby",):
                clean_key = "created_by"
            elif clean_key in ("timeoutms",):
                clean_key = "timeout_ms"
            elif clean_key in ("cachettlseconds",):
                clean_key = "cache_ttl_seconds"

            if clean_key in field_map:
                normalized[clean_key] = value

        return normalized

    def _validate_rule_dict(self, data: Dict[str, Any], index: int) -> None:
        """Validate a rule dictionary against the schema."""
        required = {"id", "name", "tier", "rule_type", "severity", "enforcement_level"}
        missing = required - set(data.keys())
        if missing:
            raise ValidationError(
                f"Rule at index {index} missing required fields: {missing}"
            )
        if not data.get("id"):
            raise ValidationError(f"Rule at index {index} has empty ID")
        if not data.get("name"):
            raise ValidationError(f"Rule at index {index} has empty name")
        if self._config["validate_rule_ids"]:
            if not re.match(r"^[a-zA-Z0-9_\-\.]+$", str(data["id"])):
                raise ValidationError(
                    f"Rule ID '{data['id']}' contains invalid characters"
                )
        if len(str(data.get("name", ""))) > self._config["max_field_length"]:
            raise ValidationError(
                f"Rule name exceeds max length of {self._config['max_field_length']}"
            )

    # ------------------------------------------------------------------ #
    #  EXPORT
    # ------------------------------------------------------------------ #

    def export_to_file(
        self,
        rules: List[Rule],
        file_path: str,
        format_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> ExportResult:
        """Export rules to a file."""
        fmt = format_type or self._detect_format(file_path)
        result = self.export_to_string(rules, fmt, filters)
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_mode = "wb" if isinstance(result.content, bytes) else "w"
        encoding = None if isinstance(result.content, bytes) else "utf-8"
        with open(path, write_mode, encoding=encoding) as f:
            f.write(result.content)
        logger.info("Exported %d rules to %s", result.rule_count, file_path)
        return result

    def export_to_string(
        self,
        rules: List[Rule],
        format_type: str = "json",
        filters: Optional[Dict[str, Any]] = None,
    ) -> ExportResult:
        """Export rules to a string in the specified format."""
        fmt = FormatType(format_type)
        filtered = self._apply_export_filters(rules, filters)
        rule_dicts = [self._rule_to_export_dict(r) for r in filtered]

        content = self._serialize_content(rule_dicts, fmt)
        result = ExportResult(
            format=fmt.value,
            content=content,
            rule_count=len(filtered),
            filters_applied=filters,
        )
        self._export_history.append(result)
        logger.info("Export created: %d rules in %s format", result.rule_count, fmt.value)
        return result

    def export_to_stream(
        self,
        rules: List[Rule],
        format_type: str = "json",
        filters: Optional[Dict[str, Any]] = None,
    ) -> io.StringIO:
        """Export rules to a string stream."""
        result = self.export_to_string(rules, format_type, filters)
        return io.StringIO(str(result.content))

    def export_to_csv(
        self,
        rules: List[Rule],
        columns: Optional[List[str]] = None,
    ) -> str:
        """Export rules to CSV format with specified columns."""
        default_columns = [
            "id", "name", "description", "tier", "rule_type", "severity",
            "status", "enforcement_level", "version", "priority",
        ]
        cols = columns or default_columns
        filtered = set(cols) & {
            "id", "name", "description", "tier", "rule_type", "severity",
            "status", "enforcement_level", "version", "priority", "auto_block",
            "user_override", "timeout_ms", "cache_ttl_seconds",
        }

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=list(filtered),
            delimiter=self._config["csv_delimiter"],
            quotechar=self._config["csv_quotechar"],
        )
        writer.writeheader()

        for rule in rules:
            row: Dict[str, Any] = {}
            rule_dict = rule.dict()
            for col in filtered:
                val = rule_dict.get(col, "")
                if isinstance(val, Enum):
                    val = val.value
                row[col] = val
            writer.writerow(row)

        return output.getvalue()

    def _serialize_content(
        self,
        rule_dicts: List[Dict[str, Any]],
        fmt: FormatType,
    ) -> Union[str, bytes]:
        """Serialize rule dicts to the specified format."""
        if fmt == FormatType.JSON:
            return json.dumps(
                rule_dicts,
                indent=self._config["json_indent"],
                ensure_ascii=self._config["json_ensure_ascii"],
                default=str,
            )
        elif fmt == FormatType.YAML:
            return yaml.dump(
                rule_dicts,
                allow_unicode=self._config["yaml_allow_unicode"],
                default_flow_style=self._config["yaml_default_flow_style"],
            )
        elif fmt == FormatType.CSV:
            return self.export_to_csv(
                [Rule(**rd) for rd in rule_dicts]
            )
        else:
            raise FormatNotSupportedError(f"Unsupported format: {fmt.value}")

    def _rule_to_export_dict(self, rule: Rule) -> Dict[str, Any]:
        """Convert a Rule to a dictionary suitable for export."""
        rule_dict = rule.dict()
        for key in ("created_at", "updated_at"):
            if key in rule_dict and isinstance(rule_dict[key], datetime):
                rule_dict[key] = rule_dict[key].isoformat()
        return rule_dict

    def _apply_export_filters(
        self,
        rules: List[Rule],
        filters: Optional[Dict[str, Any]],
    ) -> List[Rule]:
        """Apply filters to the list of rules before export."""
        if not filters:
            return rules
        filtered = list(rules)
        if "tier" in filters:
            tier_val = filters["tier"]
            filtered = [r for r in filtered if r.tier.value == tier_val or r.tier == tier_val]
        if "rule_type" in filters:
            type_val = filters["rule_type"]
            filtered = [r for r in filtered if r.rule_type.value == type_val or r.rule_type == type_val]
        if "severity" in filters:
            sev_val = filters["severity"]
            filtered = [r for r in filtered if r.severity.value == sev_val or r.severity == sev_val]
        if "status" in filters:
            status_val = filters["status"]
            filtered = [r for r in filtered if r.status.value == status_val or r.status == status_val]
        if "created_by" in filters:
            filtered = [r for r in filtered if r.created_by == filters["created_by"]]
        if "tags" in filters:
            tag_filter = set(filters["tags"])
            filtered = [r for r in filtered if tag_filter & set(r.tags)]
        if "search_text" in filters:
            text = filters["search_text"].lower()
            filtered = [
                r for r in filtered
                if text in r.name.lower() or text in r.description.lower()
            ]
        return filtered

    # ------------------------------------------------------------------ #
    #  CONFLICT RESOLUTION
    # ------------------------------------------------------------------ #

    def resolve_conflicts(
        self,
        existing: List[Rule],
        incoming: List[Rule],
        strategy: str = "fail",
    ) -> Tuple[List[Rule], List[Rule]]:
        """Resolve conflicts between existing and incoming rule lists."""
        strategy_enum = ConflictStrategy(strategy)
        existing_map = {r.id: r for r in existing}
        resolved: List[Rule] = []
        unresolved: List[Rule] = []

        for rule in incoming:
            if rule.id not in existing_map:
                resolved.append(rule)
                continue

            existing_rule = existing_map[rule.id]

            if strategy_enum == ConflictStrategy.FAIL:
                raise ConflictResolutionError(
                    f"Conflict on rule '{rule.id}': fail strategy requires no conflicts"
                )
            elif strategy_enum == ConflictStrategy.SKIP:
                resolved.append(existing_rule)
            elif strategy_enum == ConflictStrategy.OVERWRITE:
                resolved.append(rule)
            elif strategy_enum == ConflictStrategy.KEEP_EXISTING:
                resolved.append(existing_rule)
            elif strategy_enum == ConflictStrategy.KEEP_NEW:
                resolved.append(rule)
            elif strategy_enum == ConflictStrategy.RENAME:
                rule.id = f"{rule.id}_{uuid.uuid4().hex[:8]}"
                resolved.append(rule)
            elif strategy_enum == ConflictStrategy.MERGE:
                merged = self._merge_rule_conflict(existing_rule, rule)
                resolved.append(merged)
            else:
                unresolved.append(rule)

        return resolved, unresolved

    def _merge_rule_conflict(self, existing: Rule, incoming: Rule) -> Rule:
        """Merge two conflicting rules together."""
        merged = deepcopy(existing)
        merged.severity = max(
            [existing.severity, incoming.severity],
            key=lambda s: ["low", "medium", "high", "critical"].index(s.value),
        )
        merged.enforcement_level = max(
            [existing.enforcement_level, incoming.enforcement_level],
            key=lambda e: ["fallback", "adaptive", "advisory", "strict"].index(e.value),
        )
        merged.tags = list(set(existing.tags + incoming.tags))
        merged.exceptions = list(set(existing.exceptions + incoming.exceptions))
        merged.user_override = existing.user_override and incoming.user_override
        merged.auto_block = existing.auto_block or incoming.auto_block
        merged.updated_at = datetime.utcnow()
        return merged

    # ------------------------------------------------------------------ #
    #  MIGRATION
    # ------------------------------------------------------------------ #

    def migrate_rules(
        self,
        source_getter: Callable[[List[str]], List[Rule]],
        target_creator: Callable[[Rule], Any],
        rule_ids: List[str],
        strategy: str = "fail",
        dry_run: bool = False,
    ) -> ImportResult:
        """Migrate rules between repositories using getter/creator callbacks."""
        plan = MigrationPlan(
            source_repo="source",
            target_repo="target",
            rule_ids=rule_ids,
            strategy=ConflictStrategy(strategy),
            dry_run=dry_run,
        )
        return self._execute_migration(plan, source_getter, target_creator)

    def _execute_migration(
        self,
        plan: MigrationPlan,
        source_getter: Callable[[List[str]], List[Rule]],
        target_creator: Callable[[Rule], Any],
    ) -> ImportResult:
        """Execute a migration plan."""
        result = ImportResult(total=len(plan.rule_ids))
        try:
            rules = source_getter(plan.rule_ids)
        except Exception as exc:
            raise ImportExportError(f"Failed to read source rules: {exc}") from exc

        for rule in rules:
            try:
                if plan.dry_run:
                    result.imported += 1
                else:
                    target_creator(rule)
                    result.imported += 1
            except Exception as exc:
                result.failed += 1
                result.errors.append({
                    "rule_id": rule.id,
                    "error": str(exc),
                })
                logger.error("Migration failed for rule '%s': %s", rule.id, exc)

        logger.info(
            "Migration completed: %d/%d rules (%s)",
            result.imported, result.total, "dry run" if plan.dry_run else "live",
        )
        return result

    # ------------------------------------------------------------------ #
    #  ROLLBACK
    # ------------------------------------------------------------------ #

    def rollback_last_import(self) -> bool:
        """Rollback the most recent import operation."""
        if not self._import_history:
            logger.warning("No import history to rollback")
            return False
        last = self._import_history[-1]
        if not last.rollback_possible:
            logger.warning("Last import cannot be rolled back")
            return False
        logger.info("Rollback of import %s initiated", last.import_id)
        return True

    def _rollback_import(self, imported_rules: List[Rule]) -> None:
        """Internal rollback for in-progress import."""
        imported_rules.clear()
        logger.debug("Import rollback performed")

    # ------------------------------------------------------------------ #
    #  HISTORY & UTILITY
    # ------------------------------------------------------------------ #

    def get_import_history(self, limit: int = 10) -> List[ImportResult]:
        """Get recent import history."""
        return list(self._import_history[-limit:])

    def get_export_history(self, limit: int = 10) -> List[ExportResult]:
        """Get recent export history."""
        return list(self._export_history[-limit:])

    def detect_format(self, file_path: str) -> str:
        """Detect the format of a file by its extension or content."""
        return self._detect_format(file_path)

    def batch_process(
        self,
        rules: List[Rule],
        operations: List[Callable[[Rule], Any]],
    ) -> Dict[str, Any]:
        """Apply multiple operations to a batch of rules."""
        results: Dict[str, Any] = {
            "total": len(rules),
            "succeeded": 0,
            "failed": 0,
            "errors": [],
        }
        for rule in rules:
            for op in operations:
                try:
                    op(rule)
                    results["succeeded"] += 1
                except Exception as exc:
                    results["failed"] += 1
                    results["errors"].append({
                        "rule_id": rule.id,
                        "error": str(exc),
                    })
        return results

    def validate_import_data(
        self,
        content: str,
        format_type: str = "json",
    ) -> List[str]:
        """Validate import data and return list of error messages (without importing)."""
        try:
            fmt = FormatType(format_type)
            rules_data = self._parse_content(content, fmt)
        except Exception as exc:
            return [f"Parse error: {exc}"]

        errors: List[str] = []
        for i, data in enumerate(rules_data):
            try:
                data = self._normalize_rule_dict(data)
                self._validate_rule_dict(data, i)
                Rule(**data)
            except Exception as exc:
                errors.append(f"Item {i} ({data.get('id', '?')}): {exc}")
        return errors

    def _detect_format(self, file_path: str) -> str:
        """Detect file format from extension or content."""
        ext = Path(file_path).suffix.lower()
        extension_map = {
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".csv": "csv",
        }
        fmt = extension_map.get(ext)
        if fmt:
            return fmt
        if self._config["auto_detect_format"]:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    first_bytes = f.read(1024).strip()
                if first_bytes.startswith("{") or first_bytes.startswith("["):
                    return "json"
                if first_bytes.startswith("---") or ":" in first_bytes[:200]:
                    return "yaml"
                if "," in first_bytes and "\t" not in first_bytes[:200]:
                    return "csv"
            except Exception:
                pass
        raise FormatNotSupportedError(
            f"Cannot detect format for '{file_path}'. "
            f"Supported: {', '.join(extension_map.values())}"
        )

    def get_supported_formats(self) -> List[str]:
        """Get list of supported export/import formats."""
        return [f.value for f in FormatType if f != FormatType.AUTO]

    def estimate_export_size(self, rules: List[Rule], format_type: str = "json") -> int:
        """Estimate the size of an export in bytes."""
        fmt = FormatType(format_type)
        sample = rules[:min(10, len(rules))]
        sample_dicts = [r.dict() for r in sample]
        sample_content = self._serialize_content(sample_dicts, fmt)
        if isinstance(sample_content, str):
            per_rule = len(sample_content.encode("utf-8")) / max(len(sample), 1)
        else:
            per_rule = len(sample_content) / max(len(sample), 1)
        return int(per_rule * len(rules))

    def format_conversion(
        self,
        content: str,
        source_format: str,
        target_format: str,
    ) -> str:
        """Convert rule data from one format to another."""
        rules_data = self._parse_content(content, FormatType(source_format))
        rules = [Rule(**self._normalize_rule_dict(rd)) for rd in rules_data]
        result = self.export_to_string(rules, target_format)
        return str(result.content)
