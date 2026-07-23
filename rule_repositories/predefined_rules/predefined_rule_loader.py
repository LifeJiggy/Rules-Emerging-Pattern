"""
Predefined rule loader for loading catalog rules from multiple sources.

Provides comprehensive loading, validation, dependency resolution, and
registration of predefined rules from YAML, JSON, and database sources.
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
    RuleContext,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)

logger = logging.getLogger(__name__)


class LoaderError(Exception):
    """Base exception for loader errors."""


class SourceNotFoundError(LoaderError):
    """Exception raised when a catalog source is not found."""


class ValidationError(LoaderError):
    """Exception raised when a rule fails validation during loading."""


class DependencyResolutionError(LoaderError):
    """Exception raised when rule dependencies cannot be resolved."""


class VersionMismatchError(LoaderError):
    """Exception raised when rule version does not match expected version."""


class RegistrationError(LoaderError):
    """Exception raised when rule registration fails."""


class LoadingStrategy(Enum):
    """Loading strategies for predefined rules."""
    EAGER = "eager"
    LAZY = "lazy"
    ON_DEMAND = "on_demand"
    BATCH = "batch"


class SourceType(Enum):
    """Types of catalog rule sources."""
    YAML_FILE = "yaml_file"
    JSON_FILE = "json_file"
    CSV_FILE = "csv_file"
    DATABASE = "database"
    EMBEDDED = "embedded"
    NETWORK = "network"


class DependencyType(Enum):
    """Types of rule dependencies."""
    REQUIRES = "requires"
    EXTENDS = "extends"
    CONFLICTS_WITH = "conflicts_with"
    PRECEDES = "precedes"
    FOLLOWS = "follows"


@dataclass
class CatalogSource:
    """Descriptor for a catalog rule source."""

    source_id: str
    source_type: SourceType
    path: str
    version: str = "1.0.0"
    enabled: bool = True
    priority: int = 100
    tags: List[str] = field(default_factory=list)
    connection_string: Optional[str] = None
    cache_ttl_seconds: int = 300
    retry_on_failure: bool = True
    max_retries: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Enum):
                result[key] = value.value
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CatalogSource":
        """Create from dictionary."""
        enum_fields = {"source_type": SourceType}
        parsed = {}
        for key, value in data.items():
            if key in enum_fields and value is not None:
                try:
                    parsed[key] = enum_fields[key](value)
                except (ValueError, TypeError):
                    parsed[key] = value
            else:
                parsed[key] = value
        return cls(**parsed)


@dataclass
class DependencySpec:
    """Specification for a rule dependency."""

    rule_id: str
    dependency_type: DependencyType
    version_constraint: Optional[str] = None
    optional: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LoadResult:
    """Result of loading a catalog source."""

    source_id: str
    success: bool
    rules_loaded: int = 0
    rules_failed: int = 0
    errors: List[str] = field(default_factory=list)
    loaded_rule_ids: List[str] = field(default_factory=list)
    failed_rule_ids: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    warnings: List[str] = field(default_factory=list)

    def merge(self, other: "LoadResult") -> None:
        """Merge another load result into this one."""
        self.rules_loaded += other.rules_loaded
        self.rules_failed += other.rules_failed
        self.errors.extend(other.errors)
        self.loaded_rule_ids.extend(other.loaded_rule_ids)
        self.failed_rule_ids.extend(other.failed_rule_ids)
        self.duration_ms += other.duration_ms
        self.warnings.extend(other.warnings)
        if not other.success:
            self.success = False


@dataclass
class BulkLoadResult:
    """Aggregated result for bulk loading operations."""

    total_sources: int = 0
    successful_sources: int = 0
    failed_sources: int = 0
    total_rules_loaded: int = 0
    total_rules_failed: int = 0
    source_results: Dict[str, LoadResult] = field(default_factory=dict)
    errors: Dict[str, List[str]] = field(default_factory=dict)

    def add_source_result(self, source_id: str, result: LoadResult) -> None:
        """Add a source load result."""
        self.source_results[source_id] = result
        self.total_sources += 1
        if result.success:
            self.successful_sources += 1
        else:
            self.failed_sources += 1
            self.errors[source_id] = result.errors
        self.total_rules_loaded += result.rules_loaded
        self.total_rules_failed += result.rules_failed

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of bulk load operation."""
        return {
            "total_sources": self.total_sources,
            "successful_sources": self.successful_sources,
            "failed_sources": self.failed_sources,
            "total_rules_loaded": self.total_rules_loaded,
            "total_rules_failed": self.total_rules_failed,
            "overall_success": self.failed_sources == 0,
        }


class SemVer:
    """Semantic versioning utilities for rule versions."""

    PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
    PATTERN_WITH_PRE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")

    @staticmethod
    def parse(version: str) -> Tuple[int, int, int, Optional[str]]:
        """Parse a semantic version string into components."""
        version = version.strip()
        pre_release = None
        if "-" in version:
            version, pre_release = version.split("-", 1)
        parts = version.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid semver: {version}")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        return major, minor, patch, pre_release

    @staticmethod
    def to_string(major: int, minor: int, patch: int, pre_release: Optional[str] = None) -> str:
        """Convert components to version string."""
        base = f"{major}.{minor}.{patch}"
        if pre_release:
            base = f"{base}-{pre_release}"
        return base

    @classmethod
    def compare(cls, v1: str, v2: str) -> int:
        """Compare two semver strings. Returns -1, 0, or 1."""
        m1, n1, p1, pr1 = cls.parse(v1)
        m2, n2, p2, pr2 = cls.parse(v2)
        if m1 != m2:
            return -1 if m1 < m2 else 1
        if n1 != n2:
            return -1 if n1 < n2 else 1
        if p1 != p2:
            return -1 if p1 < p2 else 1
        if pr1 != pr2:
            if pr1 is None:
                return 1
            if pr2 is None:
                return -1
            return -1 if pr1 < pr2 else 1
        return 0

    @classmethod
    def satisfies(cls, version: str, constraint: str) -> bool:
        """Check if a version satisfies a constraint (e.g., '>=1.0.0', '^1.2.3')."""
        constraint = constraint.strip()
        if constraint.startswith(">="):
            min_version = constraint[2:].strip()
            return cls.compare(version, min_version) >= 0
        elif constraint.startswith("<="):
            max_version = constraint[2:].strip()
            return cls.compare(version, max_version) <= 0
        elif constraint.startswith(">"):
            min_version = constraint[1:].strip()
            return cls.compare(version, min_version) > 0
        elif constraint.startswith("<"):
            max_version = constraint[1:].strip()
            return cls.compare(version, max_version) < 0
        elif constraint.startswith("^"):
            base_version = constraint[1:].strip()
            major, _, _, _ = cls.parse(base_version)
            v_major, _, _, _ = cls.parse(version)
            return v_major == major and cls.compare(version, base_version) >= 0
        elif constraint.startswith("~"):
            base_version = constraint[1:].strip()
            maj, minor, _, _ = cls.parse(base_version)
            v_maj, v_min, _, _ = cls.parse(version)
            return v_maj == maj and v_min == minor and cls.compare(version, base_version) >= 0
        else:
            return cls.compare(version, constraint) == 0

    @classmethod
    def bump_major(cls, version: str) -> str:
        """Bump major version."""
        major, minor, patch, pre = cls.parse(version)
        return cls.to_string(major + 1, 0, 0)

    @classmethod
    def bump_minor(cls, version: str) -> str:
        """Bump minor version."""
        major, minor, patch, pre = cls.parse(version)
        return cls.to_string(major, minor + 1, 0)

    @classmethod
    def bump_patch(cls, version: str) -> str:
        """Bump patch version."""
        major, minor, patch, pre = cls.parse(version)
        return cls.to_string(major, minor, patch + 1)

    @classmethod
    def is_valid(cls, version: str) -> bool:
        """Check if a string is a valid semantic version."""
        try:
            cls.parse(version)
            return True
        except (ValueError, IndexError):
            return False


class RuleDependencyResolver:
    """Resolves dependencies between predefined rules during loading."""

    def __init__(self) -> None:
        self._rules: Dict[str, Rule] = {}
        self._dependencies: Dict[str, List[DependencySpec]] = defaultdict(list)
        self._resolution_cache: Dict[str, List[str]] = {}

    def register_rule(self, rule: Rule, dependencies: Optional[List[DependencySpec]] = None) -> None:
        """Register a rule with optional dependencies."""
        self._rules[rule.id] = rule
        if dependencies:
            self._dependencies[rule.id] = dependencies
        self._resolution_cache.clear()

    def resolve(self, rule_id: str, visited: Optional[Set[str]] = None) -> List[str]:
        """Resolve all dependencies for a rule in load order."""
        if rule_id in self._resolution_cache:
            return self._resolution_cache[rule_id]

        if visited is None:
            visited = set()

        if rule_id in visited:
            raise DependencyResolutionError(f"Circular dependency detected for rule '{rule_id}'")

        visited.add(rule_id)
        result: List[str] = []
        dependencies = self._dependencies.get(rule_id, [])

        for dep in dependencies:
            if dep.dependency_type == DependencyType.REQUIRES:
                if dep.rule_id not in self._rules:
                    if not dep.optional:
                        raise DependencyResolutionError(
                            f"Required dependency '{dep.rule_id}' not found for rule '{rule_id}'"
                        )
                    continue
                if dep.rule_id not in result:
                    sub_deps = self.resolve(dep.rule_id, visited.copy())
                    for sub_dep in sub_deps:
                        if sub_dep not in result:
                            result.append(sub_dep)
                    if dep.rule_id not in result:
                        result.append(dep.rule_id)

            elif dep.dependency_type == DependencyType.EXTENDS:
                if dep.rule_id in self._rules and dep.rule_id not in result:
                    result.append(dep.rule_id)

            elif dep.dependency_type == DependencyType.PRECEDES:
                if dep.rule_id in self._rules and dep.rule_id not in result:
                    result.append(dep.rule_id)

        if rule_id not in result:
            result.append(rule_id)

        for dep in dependencies:
            if dep.dependency_type == DependencyType.FOLLOWS:
                if dep.rule_id in self._rules and dep.rule_id not in result:
                    result.append(rule_id)
                    result.append(dep.rule_id)

        self._resolution_cache[rule_id] = result
        return result

    def get_load_order(self, rule_ids: Optional[List[str]] = None) -> List[str]:
        """Get the optimal load order for rules respecting dependencies."""
        target_ids = rule_ids or list(self._rules.keys())
        all_ordered: List[str] = []
        visited_for_cycle: Set[str] = set()

        def dfs(current: str, path: Set[str]) -> None:
            if current in visited_for_cycle:
                return
            if current in path:
                raise DependencyResolutionError(
                    f"Circular dependency detected involving rule '{current}'"
                )
            path.add(current)
            deps = self._dependencies.get(current, [])
            for dep in deps:
                if dep.dependency_type in (DependencyType.REQUIRES, DependencyType.EXTENDS):
                    if dep.rule_id in self._rules and dep.rule_id not in visited_for_cycle:
                        dfs(dep.rule_id, path)
            if current not in visited_for_cycle:
                all_ordered.append(current)
                visited_for_cycle.add(current)
            path.remove(current)

        for rule_id in target_ids:
            if rule_id not in visited_for_cycle:
                dfs(rule_id, set())

        remaining = [rid for rid in target_ids if rid not in all_ordered]
        all_ordered.extend(remaining)
        return all_ordered

    def check_conflicts(self, rule_id: str) -> List[str]:
        """Check for dependency conflicts involving a rule."""
        conflicts: List[str] = []
        dependencies = self._dependencies.get(rule_id, [])
        for dep in dependencies:
            if dep.dependency_type == DependencyType.CONFLICTS_WITH:
                if dep.rule_id in self._rules:
                    conflicts.append(dep.rule_id)
        for other_id, other_deps in self._dependencies.items():
            if other_id == rule_id:
                continue
            for dep in other_deps:
                if dep.dependency_type == DependencyType.CONFLICTS_WITH and dep.rule_id == rule_id:
                    if other_id not in conflicts:
                        conflicts.append(other_id)
        return conflicts

    def clear(self) -> None:
        """Clear all registered rules and dependencies."""
        self._rules.clear()
        self._dependencies.clear()
        self._resolution_cache.clear()


class PredefinedRuleSourceParser:
    """Parses rule definitions from various source formats."""

    SUPPORTED_FORMATS = {"json", "yaml", "yml", "csv"}

    def __init__(self, strict_mode: bool = True) -> None:
        self.strict_mode = strict_mode

    def parse_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Parse a rule file and return list of rule dictionaries."""
        path = Path(file_path)
        if not path.exists():
            raise SourceNotFoundError(f"Source file not found: {file_path}")

        suffix = path.suffix.lower()
        if suffix == ".json":
            return self._parse_json_file(path)
        elif suffix in (".yaml", ".yml"):
            return self._parse_yaml_file(path)
        elif suffix == ".csv":
            return self._parse_csv_file(path)
        else:
            raise ValueError(f"Unsupported file format: {suffix}. Supported: {self.SUPPORTED_FORMATS}")

    def _parse_json_file(self, path: Path) -> List[Dict[str, Any]]:
        """Parse rules from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            rules = data.get("rules", data.get("rule_definitions", []))
            if isinstance(rules, dict):
                return list(rules.values())
            return rules if isinstance(rules, list) else [data]
        elif isinstance(data, list):
            return data
        return []

    def _parse_yaml_file(self, path: Path) -> List[Dict[str, Any]]:
        """Parse rules from a YAML file."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            return []
        if isinstance(data, dict):
            rules = data.get("rules", data.get("rule_definitions", []))
            if isinstance(rules, dict):
                return list(rules.values())
            return rules if isinstance(rules, list) else [data]
        elif isinstance(data, list):
            return data
        return []

    def _parse_csv_file(self, path: Path) -> List[Dict[str, Any]]:
        """Parse rules from a CSV file."""
        rules: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rule_dict: Dict[str, Any] = {}
                for key, value in row.items():
                    key_trimmed = key.strip()
                    value_trimmed = value.strip() if value else ""
                    if value_trimmed:
                        if key_trimmed in ("priority", "timeout_ms", "cache_ttl_seconds"):
                            try:
                                rule_dict[key_trimmed] = int(value_trimmed)
                            except ValueError:
                                rule_dict[key_trimmed] = value_trimmed
                        elif key_trimmed in ("auto_block", "user_override", "override_justification_required"):
                            rule_dict[key_trimmed] = value_trimmed.lower() in ("true", "1", "yes")
                        elif key_trimmed in ("tags", "exceptions"):
                            rule_dict[key_trimmed] = [t.strip() for t in value_trimmed.split(";") if t.strip()]
                        elif key_trimmed == "patterns":
                            try:
                                rule_dict[key_trimmed] = json.loads(value_trimmed)
                            except json.JSONDecodeError:
                                rule_dict[key_trimmed] = [{"type": "custom", "keywords": [value_trimmed]}]
                        else:
                            rule_dict[key_trimmed] = value_trimmed
                rules.append(rule_dict)
        return rules

    def parse_string(self, content: str, format_type: str) -> List[Dict[str, Any]]:
        """Parse rule definitions from a string content."""
        fmt = format_type.lower().strip(".")
        if fmt == "json":
            data = json.loads(content)
        elif fmt in ("yaml", "yml"):
            data = yaml.safe_load(content)
        else:
            raise ValueError(f"Unsupported format for string parsing: {fmt}")

        if isinstance(data, dict):
            rules = data.get("rules", data.get("rule_definitions", []))
            if isinstance(rules, dict):
                return list(rules.values())
            return rules if isinstance(rules, list) else [data]
        elif isinstance(data, list):
            return data
        return []

    def dict_to_rule(self, data: Dict[str, Any]) -> Rule:
        """Convert a dictionary to a Rule object with validation."""
        patterns_data = data.pop("patterns", [])
        rule = Rule(**data)
        parsed_patterns: List[RulePattern] = []
        for pat_data in patterns_data:
            if isinstance(pat_data, dict):
                parsed_patterns.append(RulePattern(**pat_data))
            elif isinstance(pat_data, RulePattern):
                parsed_patterns.append(pat_data)
        rule.patterns = parsed_patterns
        return rule

    def validate_rule_dict(self, data: Dict[str, Any]) -> List[str]:
        """Validate a rule dictionary for required fields and types."""
        errors: List[str] = []
        required_fields = {"id", "name", "tier", "rule_type", "severity", "enforcement_level"}
        for field_name in required_fields:
            if field_name not in data:
                errors.append(f"Missing required field: {field_name}")
            elif not isinstance(data[field_name], str) or len(data[field_name].strip()) == 0:
                errors.append(f"Required field '{field_name}' must be a non-empty string")

        if "version" in data and data["version"]:
            if not SemVer.is_valid(data["version"]):
                errors.append(f"Invalid version format: '{data['version']}'")

        if "patterns" in data and isinstance(data["patterns"], list):
            for i, pattern in enumerate(data["patterns"]):
                if isinstance(pattern, dict):
                    if "type" not in pattern:
                        errors.append(f"Pattern at index {i} is missing 'type' field")

        valid_tiers = {t.value for t in RuleTier}
        if "tier" in data and data["tier"] not in valid_tiers:
            errors.append(f"Invalid tier: '{data['tier']}'. Must be one of {valid_tiers}")

        return errors


class PredefinedRuleLoader:
    """Main loader for predefined rules from catalog sources.

    Handles loading rules from multiple source types, version checking,
    dependency resolution, and registration with the system.
    """

    def __init__(
        self,
        sources: Optional[List[CatalogSource]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._sources: Dict[str, CatalogSource] = {}
        self._rules: Dict[str, Rule] = {}
        self._config = self._default_config()
        if config:
            self._config.update(config)
        self._source_parser = PredefinedRuleSourceParser(
            strict_mode=self._config.get("strict_mode", True)
        )
        self._dependency_resolver = RuleDependencyResolver()
        self._loading_strategy = LoadingStrategy(self._config.get("loading_strategy", "eager"))
        self._loaded_sources: Set[str] = set()
        self._load_errors: Dict[str, List[str]] = defaultdict(list)
        self._register_hooks: Dict[str, List[Callable[[Rule], None]]] = defaultdict(list)
        self._lock = RLock()
        self._load_stats: Dict[str, Any] = {
            "total_load_attempts": 0,
            "total_load_successes": 0,
            "total_load_failures": 0,
            "total_rules_loaded": 0,
            "total_rules_failed": 0,
        }

        if sources:
            for source in sources:
                self.register_source(source)

        logger.info(
            "PredefinedRuleLoader initialized with %d sources, strategy=%s",
            len(self._sources),
            self._loading_strategy.value,
        )

    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for the loader."""
        return {
            "strict_mode": True,
            "loading_strategy": "eager",
            "auto_register": True,
            "validate_on_load": True,
            "resolve_dependencies": True,
            "check_versions": True,
            "allow_partial_load": False,
            "enable_cache": True,
            "cache_ttl_seconds": 300,
            "max_retries": 3,
            "retry_delay_seconds": 1.0,
            "fail_on_version_mismatch": True,
            "fail_on_missing_dependency": True,
            "log_loaded_rules": True,
            "parallel_loading": False,
            "max_parallel_sources": 5,
            "source_discovery_enabled": True,
            "discovery_paths": [],
            "discovery_recursive": True,
            "allowed_formats": ["json", "yaml", "yml", "csv"],
        }

    def register_source(self, source: CatalogSource) -> None:
        """Register a catalog source for rule loading."""
        with self._lock:
            if source.source_id in self._sources:
                logger.warning("Overwriting existing source: %s", source.source_id)
            self._sources[source.source_id] = source
            logger.debug("Registered source: %s (type=%s)", source.source_id, source.source_type.value)

    def unregister_source(self, source_id: str) -> bool:
        """Remove a registered catalog source."""
        with self._lock:
            if source_id in self._sources:
                del self._sources[source_id]
                self._loaded_sources.discard(source_id)
                self._load_errors.pop(source_id, None)
                logger.info("Unregistered source: %s", source_id)
                return True
            return False

    def get_source(self, source_id: str) -> Optional[CatalogSource]:
        """Get a registered source by ID."""
        return self._sources.get(source_id)

    def list_sources(self) -> List[CatalogSource]:
        """List all registered catalog sources."""
        return list(self._sources.values())

    def set_loading_strategy(self, strategy: LoadingStrategy) -> None:
        """Set the loading strategy for rules."""
        with self._lock:
            self._loading_strategy = strategy
            logger.info("Loading strategy set to: %s", strategy.value)

    def load_all(self) -> BulkLoadResult:
        """Load rules from all registered and enabled sources."""
        with self._lock:
            bulk_result = BulkLoadResult()
            enabled_sources = [s for s in self._sources.values() if s.enabled]
            if not enabled_sources:
                logger.warning("No enabled sources to load from")
                return bulk_result

            logger.info("Loading rules from %d sources", len(enabled_sources))
            for source in enabled_sources:
                try:
                    result = self._load_source(source)
                    bulk_result.add_source_result(source.source_id, result)
                    if result.success:
                        self._loaded_sources.add(source.source_id)
                    else:
                        self._load_errors[source.source_id] = result.errors
                except Exception as exc:
                    error_result = LoadResult(
                        source_id=source.source_id,
                        success=False,
                        errors=[str(exc)],
                    )
                    bulk_result.add_source_result(source.source_id, error_result)
                    self._load_errors[source.source_id] = [str(exc)]
                    logger.error("Failed to load source '%s': %s", source.source_id, exc)

            self._load_stats["total_load_attempts"] += 1
            if bulk_result.failed_sources == 0:
                self._load_stats["total_load_successes"] += 1
            else:
                self._load_stats["total_load_failures"] += 1
            self._load_stats["total_rules_loaded"] += bulk_result.total_rules_loaded
            self._load_stats["total_rules_failed"] += bulk_result.total_rules_failed

            logger.info(
                "Loaded %d rules from %d sources (%d failed)",
                bulk_result.total_rules_loaded,
                bulk_result.successful_sources,
                bulk_result.failed_sources,
            )
            return bulk_result

    def load_source(self, source_id: str) -> LoadResult:
        """Load rules from a specific source by ID."""
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return LoadResult(
                    source_id=source_id,
                    success=False,
                    errors=[f"Source not found: {source_id}"],
                )
            if not source.enabled:
                return LoadResult(
                    source_id=source_id,
                    success=False,
                    errors=[f"Source is disabled: {source_id}"],
                )
            result = self._load_source(source)
            if result.success:
                self._loaded_sources.add(source_id)
                self._load_stats["total_rules_loaded"] += result.rules_loaded
            else:
                self._load_errors[source_id] = result.errors
                self._load_stats["total_rules_failed"] += result.rules_failed
            return result

    def _load_source(self, source: CatalogSource) -> LoadResult:
        """Internal method to load rules from a single source."""
        start_time = time.time()
        result = LoadResult(source_id=source.source_id, success=True)

        try:
            if source.source_type == SourceType.YAML_FILE:
                rule_dicts = self._source_parser.parse_file(source.path)
            elif source.source_type == SourceType.JSON_FILE:
                rule_dicts = self._source_parser.parse_file(source.path)
            elif source.source_type == SourceType.CSV_FILE:
                rule_dicts = self._source_parser.parse_file(source.path)
            elif source.source_type == SourceType.EMBEDDED:
                rule_dicts = self._load_embedded_source(source)
            elif source.source_type == SourceType.DATABASE:
                rule_dicts = self._load_from_database(source)
            else:
                raise ValueError(f"Unsupported source type: {source.source_type}")

            if not rule_dicts:
                result.warnings.append(f"No rules found in source '{source.source_id}'")
                result.duration_ms = (time.time() - start_time) * 1000
                return result

            for rule_data in rule_dicts:
                try:
                    if self._config.get("validate_on_load", True):
                        validation_errors = self._source_parser.validate_rule_dict(rule_data)
                        if validation_errors:
                            error_msg = "; ".join(validation_errors)
                            result.errors.append(f"Rule '{rule_data.get('id', 'unknown')}': {error_msg}")
                            result.rules_failed += 1
                            result.failed_rule_ids.append(rule_data.get("id", "unknown"))
                            if not self._config.get("allow_partial_load", False):
                                result.success = False
                            continue

                    rule = self._source_parser.dict_to_rule(rule_data)

                    if self._config.get("check_versions", True):
                        existing = self._rules.get(rule.id)
                        if existing:
                            if SemVer.compare(rule.version, existing.version) < 0:
                                msg = (
                                    f"Rule '{rule.id}' version {rule.version} is older "
                                    f"than existing {existing.version}"
                                )
                                if self._config.get("fail_on_version_mismatch", True):
                                    result.errors.append(msg)
                                    result.rules_failed += 1
                                    result.failed_rule_ids.append(rule.id)
                                    if not self._config.get("allow_partial_load", False):
                                        result.success = False
                                    continue
                                else:
                                    result.warnings.append(msg)

                    self._rules[rule.id] = rule
                    result.rules_loaded += 1
                    result.loaded_rule_ids.append(rule.id)

                    if self._config.get("auto_register", True):
                        self._trigger_register_hooks(rule)

                except Exception as exc:
                    error_id = rule_data.get("id", "unknown")
                    result.errors.append(f"Failed to parse rule '{error_id}': {exc}")
                    result.rules_failed += 1
                    result.failed_rule_ids.append(error_id)
                    if not self._config.get("allow_partial_load", False):
                        result.success = False

            if self._config.get("resolve_dependencies", True) and result.rules_loaded > 0:
                self._resolve_and_order_rules(result)

        except Exception as exc:
            result.success = False
            result.errors.append(f"Source load failed: {exc}")
            logger.error("Failed to load source '%s': %s", source.source_id, exc)

        result.duration_ms = (time.time() - start_time) * 1000

        if self._config.get("log_loaded_rules", True):
            logger.info(
                "Loaded source '%s': %d rules loaded, %d failed (%.1fms)",
                source.source_id,
                result.rules_loaded,
                result.rules_failed,
                result.duration_ms,
            )

        return result

    def _load_embedded_source(self, source: CatalogSource) -> List[Dict[str, Any]]:
        """Load rules from an embedded data source."""
        metadata = source.metadata
        embedded_data = metadata.get("rules_data") or metadata.get("data")
        if embedded_data is None:
            raise ValueError(f"Embedded source '{source.source_id}' has no data in metadata")
        if isinstance(embedded_data, list):
            return embedded_data
        if isinstance(embedded_data, str):
            format_type = metadata.get("format", "json")
            return self._source_parser.parse_string(embedded_data, format_type)
        if isinstance(embedded_data, dict):
            rules = embedded_data.get("rules", [])
            return list(rules.values()) if isinstance(rules, dict) else rules
        return []

    def _load_from_database(self, source: CatalogSource) -> List[Dict[str, Any]]:
        """Load rules from a database source."""
        conn_string = source.connection_string
        if not conn_string:
            raise ValueError(f"Database source '{source.source_id}' has no connection string")
        logger.warning(
            "Database source '%s' requires external DB adapter. Returning empty.", source.source_id
        )
        return []

    def _resolve_and_order_rules(self, result: LoadResult) -> None:
        """Resolve dependencies and reorder loaded rules."""
        try:
            for rule_id in result.loaded_rule_ids:
                rule = self._rules.get(rule_id)
                if rule:
                    deps: List[DependencySpec] = []
                    for dep_id in rule.exceptions:
                        deps.append(DependencySpec(
                            rule_id=dep_id,
                            dependency_type=DependencyType.REQUIRES,
                            optional=True,
                        ))
                    self._dependency_resolver.register_rule(rule, deps)

            load_order = self._dependency_resolver.get_load_order(result.loaded_rule_ids)
            result.loaded_rule_ids = load_order

            for rule_id in result.loaded_rule_ids:
                conflicts = self._dependency_resolver.check_conflicts(rule_id)
                if conflicts:
                    result.warnings.append(
                        f"Rule '{rule_id}' conflicts with: {', '.join(conflicts)}"
                    )

        except DependencyResolutionError as exc:
            result.warnings.append(f"Dependency resolution issue: {exc}")

    def load_single(self, rule_data: Dict[str, Any]) -> Optional[Rule]:
        """Load a single rule from a dictionary."""
        try:
            if self._config.get("validate_on_load", True):
                errors = self._source_parser.validate_rule_dict(rule_data)
                if errors:
                    logger.error("Rule validation failed: %s", "; ".join(errors))
                    return None

            rule = self._source_parser.dict_to_rule(rule_data)

            existing = self._rules.get(rule.id)
            if existing and self._config.get("check_versions", True):
                if SemVer.compare(rule.version, existing.version) < 0:
                    logger.warning(
                        "Rule '%s' version %s is older than existing %s",
                        rule.id, rule.version, existing.version,
                    )
                    if self._config.get("fail_on_version_mismatch", True):
                        return None

            self._rules[rule.id] = rule
            self._trigger_register_hooks(rule)

            if self._config.get("resolve_dependencies", True):
                deps: List[DependencySpec] = []
                for dep_id in rule.exceptions:
                    deps.append(DependencySpec(
                        rule_id=dep_id,
                        dependency_type=DependencyType.REQUIRES,
                        optional=True,
                    ))
                self._dependency_resolver.register_rule(rule, deps)

            logger.debug("Loaded single rule: %s (%s)", rule.id, rule.version)
            return rule

        except Exception as exc:
            logger.error("Failed to load single rule: %s", exc)
            return None

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        """Get a loaded rule by ID."""
        return self._rules.get(rule_id)

    def get_rules(self, tier: Optional[RuleTier] = None) -> List[Rule]:
        """Get all loaded rules, optionally filtered by tier."""
        if tier:
            return [r for r in self._rules.values() if r.tier == tier]
        return list(self._rules.values())

    def get_rules_by_type(self, rule_type: RuleType) -> List[Rule]:
        """Get loaded rules filtered by type."""
        return [r for r in self._rules.values() if r.rule_type == rule_type]

    def get_rules_by_source(self, source_id: str) -> List[Rule]:
        """Get rules that were loaded from a specific source."""
        source = self._sources.get(source_id)
        if not source:
            return []
        return [r for r in self._rules.values() if source_id in getattr(r, "tags", [])]

    def get_load_statistics(self) -> Dict[str, Any]:
        """Get loading statistics."""
        stats = dict(self._load_stats)
        stats["total_rules_in_memory"] = len(self._rules)
        stats["total_sources_registered"] = len(self._sources)
        stats["total_sources_loaded"] = len(self._loaded_sources)
        stats["loading_strategy"] = self._loading_strategy.value
        stats["rules_by_tier"] = {
            tier.value: len(self.get_rules(tier)) for tier in RuleTier
        }
        return stats

    def register_hook(self, event: str, callback: Callable[[Rule], None]) -> None:
        """Register a callback for rule load events."""
        valid_events = {"rule.loaded", "rule.updated", "rule.registered"}
        if event not in valid_events and not event.startswith("rule."):
            raise ValueError(f"Invalid event type: {event}. Must be one of {valid_events}")
        self._register_hooks[event].append(callback)

    def unregister_hook(self, event: str, callback: Callable[[Rule], None]) -> bool:
        """Remove a previously registered hook."""
        hooks = self._register_hooks.get(event, [])
        if callback in hooks:
            hooks.remove(callback)
            return True
        return False

    def _trigger_register_hooks(self, rule: Rule) -> None:
        """Trigger all registered hooks for a rule."""
        for hook in list(self._register_hooks.get("rule.loaded", [])):
            try:
                hook(rule)
            except Exception as exc:
                logger.error("Hook failed for rule.loaded: %s", exc)
        for hook in list(self._register_hooks.get("rule.registered", [])):
            try:
                hook(rule)
            except Exception as exc:
                logger.error("Hook failed for rule.registered: %s", exc)

    def reload_source(self, source_id: str) -> LoadResult:
        """Reload a specific source, clearing previously loaded rules from it."""
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return LoadResult(
                    source_id=source_id,
                    success=False,
                    errors=[f"Source not found: {source_id}"],
                )

            removed_ids: List[str] = []
            for rule_id in list(self._rules.keys()):
                if source_id in self._rules[rule_id].tags:
                    removed_ids.append(rule_id)
                    del self._rules[rule_id]

            self._loaded_sources.discard(source_id)
            logger.info("Reloading source '%s', removed %d cached rules", source_id, len(removed_ids))
            return self.load_source(source_id)

    def reload_all(self) -> BulkLoadResult:
        """Reload all sources."""
        with self._lock:
            self._rules.clear()
            self._loaded_sources.clear()
            self._dependency_resolver.clear()
            logger.info("Cleared all rules and dependencies, reloading all sources")
            return self.load_all()

    def discover_sources(self, discovery_path: Optional[str] = None) -> List[CatalogSource]:
        """Auto-discover catalog source files in the filesystem."""
        discovered: List[CatalogSource] = []
        paths = [discovery_path] if discovery_path else self._config.get("discovery_paths", [])

        for search_path in paths:
            path = Path(search_path)
            if not path.exists():
                logger.debug("Discovery path does not exist: %s", search_path)
                continue

            pattern = "**/*" if self._config.get("discovery_recursive", True) else "*"
            for file_path in path.glob(pattern):
                if not file_path.is_file():
                    continue
                suffix = file_path.suffix.lower().lstrip(".")
                if suffix not in self._config.get("allowed_formats", []):
                    continue

                source_id = f"discovered:{file_path.stem}"
                if suffix in ("yaml", "yml"):
                    source_type = SourceType.YAML_FILE
                elif suffix == "json":
                    source_type = SourceType.JSON_FILE
                elif suffix == "csv":
                    source_type = SourceType.CSV_FILE
                else:
                    continue

                source = CatalogSource(
                    source_id=source_id,
                    source_type=source_type,
                    path=str(file_path),
                    tags=["auto_discovered"],
                )
                self._sources[source_id] = source
                discovered.append(source)
                logger.debug("Discovered source: %s (%s)", source_id, file_path)

        if discovered:
            logger.info("Discovered %d new catalog sources", len(discovered))
        return discovered

    def get_errors(self, source_id: Optional[str] = None) -> Dict[str, List[str]]:
        """Get load errors, optionally filtered by source."""
        if source_id:
            return {source_id: self._load_errors.get(source_id, [])}
        return dict(self._load_errors)

    def clear_errors(self, source_id: Optional[str] = None) -> None:
        """Clear load errors."""
        if source_id:
            self._load_errors.pop(source_id, None)
        else:
            self._load_errors.clear()

    def get_summary(self) -> Dict[str, Any]:
        """Get a comprehensive summary of the loader state."""
        rules_by_tier: Dict[str, int] = defaultdict(int)
        rules_by_type: Dict[str, int] = defaultdict(int)
        rules_by_status: Dict[str, int] = defaultdict(int)
        for rule in self._rules.values():
            rules_by_tier[rule.tier.value] += 1
            rules_by_type[rule.rule_type.value] += 1
            rules_by_status[rule.status.value] += 1

        return {
            "total_rules": len(self._rules),
            "total_sources": len(self._sources),
            "loaded_sources": len(self._loaded_sources),
            "loading_strategy": self._loading_strategy.value,
            "rules_by_tier": dict(rules_by_tier),
            "rules_by_type": dict(rules_by_type),
            "rules_by_status": dict(rules_by_status),
            "sources": [
                {
                    "source_id": s.source_id,
                    "source_type": s.source_type.value,
                    "enabled": s.enabled,
                    "loaded": s.source_id in self._loaded_sources,
                }
                for s in self._sources.values()
            ],
            "load_stats": self._load_stats,
            "has_errors": any(self._load_errors.values()),
            "error_count": sum(len(errs) for errs in self._load_errors.values()),
        }
