"""
Rule template discovery - filesystem discovery, package resource discovery,
metadata parsing, categorization, search, registration, and indexing.
"""

import fnmatch
import hashlib
import importlib.resources as pkg_resources
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union

import yaml

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)

from .template_engine import RuleTemplateEngine
from .template_validator import RuleTemplateValidator, ValidationReport
from .template_renderer import RuleTemplateRenderer

logger = logging.getLogger(__name__)


class DiscoverySource(str, Enum):
    """Source of a discovered template."""
    FILESYSTEM = "filesystem"
    PACKAGE_RESOURCE = "package_resource"
    REGISTRY = "registry"
    REMOTE_URL = "remote_url"
    API_ENDPOINT = "api_endpoint"
    DATABASE = "database"
    MANUAL = "manual"


class TemplateCategory(str, Enum):
    """Categories for organizing templates."""
    SAFETY = "safety"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    QUALITY = "quality"
    PERFORMANCE = "performance"
    CONTENT = "content"
    PATTERN = "pattern"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    CUSTOM = "custom"
    UNCATEGORIZED = "uncategorized"


@dataclass
class TemplateMetadata:
    """Metadata about a discovered template."""
    name: str
    file_path: Optional[str] = None
    source: DiscoverySource = DiscoverySource.FILESYSTEM
    category: TemplateCategory = TemplateCategory.UNCATEGORIZED
    version: str = "0.0.0"
    description: str = ""
    tags: List[str] = field(default_factory=list)
    tier: Optional[str] = None
    rule_type: Optional[str] = None
    severity: Optional[str] = None
    file_size_bytes: int = 0
    line_count: int = 0
    last_modified: Optional[datetime] = None
    content_hash: str = ""
    checksum: str = ""
    dependencies: List[str] = field(default_factory=list)
    registered: bool = False
    registration_time: Optional[datetime] = None
    source_module: Optional[str] = None
    error_message: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "file_path": self.file_path,
            "source": self.source.value,
            "category": self.category.value,
            "version": self.version,
            "description": self.description,
            "tags": self.tags,
            "tier": self.tier,
            "rule_type": self.rule_type,
            "severity": self.severity,
            "file_size_bytes": self.file_size_bytes,
            "line_count": self.line_count,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "content_hash": self.content_hash,
            "dependencies": self.dependencies,
            "registered": self.registered,
            "registration_time": self.registration_time.isoformat() if self.registration_time else None,
            "source_module": self.source_module,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateMetadata":
        """Create from dictionary."""
        data = dict(data)
        if "source" in data and isinstance(data["source"], str):
            data["source"] = DiscoverySource(data["source"])
        if "category" in data and isinstance(data["category"], str):
            data["category"] = TemplateCategory(data["category"])
        if "last_modified" in data and isinstance(data["last_modified"], str):
            data["last_modified"] = datetime.fromisoformat(data["last_modified"])
        if "registration_time" in data and isinstance(data["registration_time"], str):
            data["registration_time"] = datetime.fromisoformat(data["registration_time"])
        return cls(**data)


@dataclass
class DiscoveryResult:
    """Result of a discovery operation."""
    templates: Dict[str, TemplateMetadata] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    total_found: int = 0
    total_errors: int = 0
    discovery_time_ms: float = 0.0
    sources_checked: int = 0
    filters_applied: List[str] = field(default_factory=list)

    def add_template(self, metadata: TemplateMetadata) -> None:
        """Add a discovered template."""
        self.templates[metadata.name] = metadata
        self.total_found = len(self.templates)

    def add_error(self, source: str, error: str) -> None:
        """Add a discovery error."""
        self.errors[source] = error
        self.total_errors = len(self.errors)

    def merge(self, other: "DiscoveryResult") -> "DiscoveryResult":
        """Merge another discovery result."""
        self.templates.update(other.templates)
        self.errors.update(other.errors)
        self.total_found = len(self.templates)
        self.total_errors = len(self.errors)
        self.sources_checked += other.sources_checked
        self.filters_applied.extend(other.filters_applied)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_found": self.total_found,
            "total_errors": self.total_errors,
            "discovery_time_ms": self.discovery_time_ms,
            "sources_checked": self.sources_checked,
            "filters_applied": self.filters_applied,
            "templates": {k: v.to_dict() for k, v in self.templates.items()},
            "errors": dict(self.errors),
        }


class DiscoveryFilter:
    """Filter for template discovery queries."""

    def __init__(
        self,
        name_pattern: Optional[str] = None,
        category: Optional[TemplateCategory] = None,
        tier: Optional[RuleTier] = None,
        rule_type: Optional[RuleType] = None,
        severity: Optional[RuleSeverity] = None,
        tags: Optional[List[str]] = None,
        min_version: Optional[str] = None,
        max_version: Optional[str] = None,
        source: Optional[DiscoverySource] = None,
        registered_only: Optional[bool] = None,
        search_text: Optional[str] = None,
        custom_predicate: Optional[Callable[[TemplateMetadata], bool]] = None,
    ) -> None:
        self.name_pattern = name_pattern
        self.category = category
        self.tier = tier
        self.rule_type = rule_type
        self.severity = severity
        self.tags = tags
        self.min_version = min_version
        self.max_version = max_version
        self.source = source
        self.registered_only = registered_only
        self.search_text = search_text
        self.custom_predicate = custom_predicate

    def matches(self, metadata: TemplateMetadata) -> bool:
        """Check if template metadata matches this filter."""
        if self.name_pattern and not fnmatch.fnmatch(metadata.name, self.name_pattern):
            return False

        if self.category and metadata.category != self.category:
            return False

        if self.tier and metadata.tier and metadata.tier != self.tier.value:
            return False

        if self.rule_type and metadata.rule_type and metadata.rule_type != self.rule_type.value:
            return False

        if self.severity and metadata.severity and metadata.severity != self.severity.value:
            return False

        if self.tags:
            if not metadata.tags:
                return False
            if not any(tag in metadata.tags for tag in self.tags):
                return False

        if self.source and metadata.source != self.source:
            return False

        if self.registered_only is not None and metadata.registered != self.registered_only:
            return False

        if self.search_text:
            text = f"{metadata.name} {metadata.description} {' '.join(metadata.tags)}"
            if self.search_text.lower() not in text.lower():
                return False

        if self.custom_predicate and not self.custom_predicate(metadata):
            return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name_pattern": self.name_pattern,
            "category": self.category.value if self.category else None,
            "tier": self.tier.value if self.tier else None,
            "rule_type": self.rule_type.value if self.rule_type else None,
            "severity": self.severity.value if self.severity else None,
            "tags": self.tags,
            "search_text": self.search_text,
            "source": self.source.value if self.source else None,
        }


class FilesystemDiscoverer:
    """Discovers templates from the filesystem using glob patterns."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.config = config or self._default_config()

    def _default_config(self) -> Dict[str, Any]:
        """Return default filesystem discovery configuration."""
        return {
            "include_patterns": ["*.yaml", "*.yml", "*.j2", "*.template", "*.json"],
            "exclude_patterns": ["*~", "*.bak", "*.swp", ".git/*", "__pycache__/*"],
            "follow_symlinks": False,
            "max_file_size_bytes": 10 * 1024 * 1024,
            "include_hidden": False,
            "recursive": True,
        }

    def discover(
        self,
        directory: str,
        filter_obj: Optional[DiscoveryFilter] = None,
    ) -> DiscoveryResult:
        """Discover templates in a directory."""
        result = DiscoveryResult()
        start_time = time.time()

        path = Path(directory)
        if not path.exists() or not path.is_dir():
            result.add_error(directory, f"Directory not found: {directory}")
            return result

        glob_pattern = "**/*" if self.config.get("recursive", True) else "*"

        for file_path in path.glob(glob_pattern):
            if not file_path.is_file():
                continue

            if not self._should_include(file_path):
                continue

            try:
                metadata = self._create_metadata(file_path)
                if filter_obj and not filter_obj.matches(metadata):
                    continue
                result.add_template(metadata)
            except Exception as exc:
                logger.warning("Error processing '%s': %s", file_path, exc)
                result.add_error(str(file_path), str(exc))

        result.sources_checked = 1
        result.discovery_time_ms = (time.time() - start_time) * 1000
        return result

    def discover_multiple(
        self,
        directories: List[str],
        filter_obj: Optional[DiscoveryFilter] = None,
    ) -> DiscoveryResult:
        """Discover templates in multiple directories."""
        result = DiscoveryResult()
        start_time = time.time()

        for directory in directories:
            dir_result = self.discover(directory, filter_obj)
            result.merge(dir_result)

        result.sources_checked = len(directories)
        result.discovery_time_ms = (time.time() - start_time) * 1000
        return result

    def _should_include(self, file_path: Path) -> bool:
        """Check if a file should be included based on config."""
        name = file_path.name

        if not self.config.get("include_hidden", False) and name.startswith("."):
            return False

        included = any(
            fnmatch.fnmatch(name, p) for p in self.config.get("include_patterns", ["*"])
        )
        if not included:
            return False

        excluded = any(
            fnmatch.fnmatch(str(file_path), p) or fnmatch.fnmatch(name, p)
            for p in self.config.get("exclude_patterns", [])
        )
        if excluded:
            return False

        if file_path.is_symlink() and not self.config.get("follow_symlinks", False):
            return False

        try:
            size = file_path.stat().st_size
            max_size = self.config.get("max_file_size_bytes", 10 * 1024 * 1024)
            if size > max_size:
                return False
        except OSError:
            return False

        return True

    def _create_metadata(self, file_path: Path) -> TemplateMetadata:
        """Create TemplateMetadata from a file path."""
        source = file_path.read_bytes()
        content_hash = hashlib.sha256(source).hexdigest()[:16]
        file_stat = file_path.stat()

        lines = source.decode("utf-8", errors="replace").split("\n")
        line_count = len(lines)

        metadata = TemplateMetadata(
            name=file_path.stem,
            file_path=str(file_path),
            source=DiscoverySource.FILESYSTEM,
            category=TemplateCategory.UNCATEGORIZED,
            file_size_bytes=file_stat.st_size,
            line_count=line_count,
            last_modified=datetime.fromtimestamp(file_stat.st_mtime),
            content_hash=content_hash,
            checksum=content_hash,
        )

        try:
            content = source.decode("utf-8")
            parsed = yaml.safe_load(content)
            if isinstance(parsed, dict):
                metadata.name = parsed.get("name", metadata.name)
                metadata.description = parsed.get("description", "")
                metadata.version = parsed.get("version", "0.0.0")
                metadata.tier = parsed.get("tier")
                metadata.rule_type = parsed.get("rule_type")
                metadata.severity = parsed.get("severity")
                metadata.tags = parsed.get("tags", [])

                if "category" in parsed:
                    try:
                        metadata.category = TemplateCategory(parsed["category"])
                    except ValueError:
                        metadata.category = TemplateCategory.UNCATEGORIZED

                if "imports" in parsed:
                    metadata.dependencies = parsed["imports"]

                if "metadata" in parsed and isinstance(parsed["metadata"], dict):
                    metadata.extra.update(parsed["metadata"])

        except (yaml.YAMLError, UnicodeDecodeError):
            pass

        return metadata


class PackageResourceDiscoverer:
    """Discovers templates from Python package resources."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or self._default_config()

    def _default_config(self) -> Dict[str, Any]:
        return {
            "package_patterns": {
                "rules_emerging_pattern": ["templates/**/*.yaml", "templates/**/*.yml"],
            },
            "include_patterns": ["*.yaml", "*.yml", "*.j2"],
        }

    def discover(
        self,
        filter_obj: Optional[DiscoveryFilter] = None,
    ) -> DiscoveryResult:
        """Discover templates from registered package resources."""
        result = DiscoveryResult()
        start_time = time.time()

        for package, patterns in self.config.get("package_patterns", {}).items():
            try:
                package_result = self._discover_package(package, patterns, filter_obj)
                result.merge(package_result)
            except Exception as exc:
                logger.warning("Error discovering templates in package '%s': %s", package, exc)
                result.add_error(package, str(exc))

        result.discovery_time_ms = (time.time() - start_time) * 1000
        return result

    def _discover_package(
        self,
        package: str,
        patterns: List[str],
        filter_obj: Optional[DiscoveryFilter] = None,
    ) -> DiscoveryResult:
        """Discover templates within a single package."""
        result = DiscoveryResult()

        try:
            pkg = __import__(package, fromlist=[""])
            pkg_path = Path(pkg.__file__).parent if hasattr(pkg, "__file__") else None
            if pkg_path is None or not pkg_path.exists():
                return result

            for pattern in patterns:
                for file_path in pkg_path.glob(pattern):
                    if not file_path.is_file():
                        continue

                    included = any(
                        fnmatch.fnmatch(file_path.name, p)
                        for p in self.config.get("include_patterns", ["*"])
                    )
                    if not included:
                        continue

                    try:
                        metadata = self._create_metadata(file_path, package)
                        if filter_obj and not filter_obj.matches(metadata):
                            continue
                        result.add_template(metadata)
                    except Exception as exc:
                        logger.warning("Error processing package resource '%s': %s", file_path, exc)
                        result.add_error(str(file_path), str(exc))

        except (ImportError, AttributeError) as exc:
            logger.warning("Could not load package '%s': %s", package, exc)
            result.add_error(package, str(exc))

        return result

    def _create_metadata(self, file_path: Path, package: str) -> TemplateMetadata:
        """Create TemplateMetadata from a package resource file."""
        source = file_path.read_bytes()
        content_hash = hashlib.sha256(source).hexdigest()[:16]

        metadata = TemplateMetadata(
            name=file_path.stem,
            file_path=str(file_path),
            source=DiscoverySource.PACKAGE_RESOURCE,
            category=TemplateCategory.UNCATEGORIZED,
            file_size_bytes=file_path.stat().st_size,
            content_hash=content_hash,
            source_module=package,
        )

        try:
            content = source.decode("utf-8")
            parsed = yaml.safe_load(content)
            if isinstance(parsed, dict):
                metadata.name = parsed.get("name", metadata.name)
                metadata.description = parsed.get("description", "")
                metadata.version = parsed.get("version", "0.0.0")
                metadata.tier = parsed.get("tier")
                metadata.rule_type = parsed.get("rule_type")
                metadata.severity = parsed.get("severity")
                metadata.tags = parsed.get("tags", [])
                if "category" in parsed:
                    try:
                        metadata.category = TemplateCategory(parsed["category"])
                    except ValueError:
                        metadata.category = TemplateCategory.UNCATEGORIZED
        except (yaml.YAMLError, UnicodeDecodeError):
            pass

        return metadata


class TemplateIndex:
    """Index for discovered templates with fast search and lookup."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._templates: Dict[str, TemplateMetadata] = {}
        self._name_index: Dict[str, str] = {}
        self._category_index: Dict[TemplateCategory, Set[str]] = {}
        self._tier_index: Dict[str, Set[str]] = {}
        self._type_index: Dict[str, Set[str]] = {}
        self._tag_index: Dict[str, Set[str]] = {}
        self._source_index: Dict[DiscoverySource, Set[str]] = {}

    def add(self, metadata: TemplateMetadata) -> None:
        """Add a template to the index."""
        with self._lock:
            self._templates[metadata.name] = metadata
            self._name_index[metadata.name.lower()] = metadata.name
            self._add_to_category_index(metadata)
            self._add_to_tier_index(metadata)
            self._add_to_type_index(metadata)
            self._add_to_tag_index(metadata)
            self._add_to_source_index(metadata)

    def _add_to_category_index(self, metadata: TemplateMetadata) -> None:
        """Add template to category index."""
        if metadata.category not in self._category_index:
            self._category_index[metadata.category] = set()
        self._category_index[metadata.category].add(metadata.name)

    def _add_to_tier_index(self, metadata: TemplateMetadata) -> None:
        """Add template to tier index."""
        if metadata.tier:
            if metadata.tier not in self._tier_index:
                self._tier_index[metadata.tier] = set()
            self._tier_index[metadata.tier].add(metadata.name)

    def _add_to_type_index(self, metadata: TemplateMetadata) -> None:
        """Add template to type index."""
        if metadata.rule_type:
            if metadata.rule_type not in self._type_index:
                self._type_index[metadata.rule_type] = set()
            self._type_index[metadata.rule_type].add(metadata.name)

    def _add_to_tag_index(self, metadata: TemplateMetadata) -> None:
        """Add template to tag index."""
        for tag in metadata.tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = set()
            self._tag_index[tag].add(metadata.name)

    def _add_to_source_index(self, metadata: TemplateMetadata) -> None:
        """Add template to source index."""
        if metadata.source not in self._source_index:
            self._source_index[metadata.source] = set()
        self._source_index[metadata.source].add(metadata.name)

    def remove(self, name: str) -> bool:
        """Remove a template from the index."""
        with self._lock:
            if name not in self._templates:
                return False
            metadata = self._templates.pop(name)
            self._name_index.pop(name.lower(), None)

            cat_idx = self._category_index.get(metadata.category, set())
            cat_idx.discard(name)
            if metadata.tier:
                tier_idx = self._tier_index.get(metadata.tier, set())
                tier_idx.discard(name)
            if metadata.rule_type:
                type_idx = self._type_index.get(metadata.rule_type, set())
                type_idx.discard(name)
            for tag in metadata.tags:
                tag_idx = self._tag_index.get(tag, set())
                tag_idx.discard(name)
            src_idx = self._source_index.get(metadata.source, set())
            src_idx.discard(name)

            return True

    def get(self, name: str) -> Optional[TemplateMetadata]:
        """Get template metadata by name."""
        with self._lock:
            return self._templates.get(name)

    def search(self, filter_obj: DiscoveryFilter) -> List[TemplateMetadata]:
        """Search the index using a filter."""
        with self._lock:
            results: List[TemplateMetadata] = []
            for metadata in self._templates.values():
                if filter_obj.matches(metadata):
                    results.append(metadata)
            return results

    def get_by_category(self, category: TemplateCategory) -> List[TemplateMetadata]:
        """Get all templates in a category."""
        with self._lock:
            names = self._category_index.get(category, set())
            return [self._templates[n] for n in names if n in self._templates]

    def get_by_tier(self, tier: RuleTier) -> List[TemplateMetadata]:
        """Get all templates for a tier."""
        with self._lock:
            names = self._tier_index.get(tier.value, set())
            return [self._templates[n] for n in names if n in self._templates]

    def get_by_type(self, rule_type: RuleType) -> List[TemplateMetadata]:
        """Get all templates of a rule type."""
        with self._lock:
            names = self._type_index.get(rule_type.value, set())
            return [self._templates[n] for n in names if n in self._templates]

    def get_by_tag(self, tag: str) -> List[TemplateMetadata]:
        """Get all templates with a specific tag."""
        with self._lock:
            names = self._tag_index.get(tag, set())
            return [self._templates[n] for n in names if n in self._templates]

    def get_by_source(self, source: DiscoverySource) -> List[TemplateMetadata]:
        """Get all templates from a discovery source."""
        with self._lock:
            names = self._source_index.get(source, set())
            return [self._templates[n] for n in names if n in self._templates]

    def list_all(self) -> List[TemplateMetadata]:
        """List all indexed templates."""
        with self._lock:
            return list(self._templates.values())

    def count(self) -> int:
        """Get the total number of indexed templates."""
        with self._lock:
            return len(self._templates)

    def clear(self) -> None:
        """Clear the entire index."""
        with self._lock:
            self._templates.clear()
            self._name_index.clear()
            self._category_index.clear()
            self._tier_index.clear()
            self._type_index.clear()
            self._tag_index.clear()
            self._source_index.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        with self._lock:
            return {
                "total_templates": len(self._templates),
                "categories": {k.value: len(v) for k, v in self._category_index.items()},
                "tiers": {k: len(v) for k, v in self._tier_index.items()},
                "types": {k: len(v) for k, v in self._type_index.items()},
                "tags": len(self._tag_index),
                "sources": {k.value: len(v) for k, v in self._source_index.items()},
            }

    def export_index(self, file_path: str) -> None:
        """Export the index to a JSON file."""
        with self._lock:
            data = {
                "templates": {k: v.to_dict() for k, v in self._templates.items()},
                "stats": self.get_stats(),
            }
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )


class RuleTemplateDiscovery:
    """Main orchestrator for template discovery, registration, and indexing."""

    def __init__(
        self,
        engine: Optional[RuleTemplateEngine] = None,
        validator: Optional[RuleTemplateValidator] = None,
        renderer: Optional[RuleTemplateRenderer] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.engine = engine or RuleTemplateEngine()
        self.validator = validator
        self.renderer = renderer
        self.config = config or self._default_config()
        self._lock = RLock()

        self._index = TemplateIndex()
        self._filesystem_discoverer = FilesystemDiscoverer(
            self.config.get("filesystem_config", {})
        )
        self._package_discoverer = PackageResourceDiscoverer(
            self.config.get("package_config", {})
        )
        self._discovery_paths: List[str] = []
        self._registered_templates: Dict[str, TemplateMetadata] = {}
        self._discovery_hooks: Dict[str, List[Callable]] = {
            "before_discover": [],
            "after_discover": [],
            "before_register": [],
            "after_register": [],
        }

    def _default_config(self) -> Dict[str, Any]:
        """Return the default discovery configuration."""
        return {
            "discovery_paths": [],
            "include_patterns": ["*.yaml", "*.yml", "*.j2", "*.template"],
            "exclude_patterns": ["*~", "*.bak", "*.swp"],
            "recursive": True,
            "auto_register": True,
            "validate_on_discovery": False,
            "follow_symlinks": False,
            "max_file_size_bytes": 10 * 1024 * 1024,
            "reindex_on_startup": False,
            "watch_for_changes": False,
            "filesystem_config": {},
            "package_config": {},
        }

    def add_discovery_path(self, path: str) -> None:
        """Add a directory to the discovery paths."""
        with self._lock:
            norm_path = os.path.abspath(os.path.normpath(path))
            if norm_path not in self._discovery_paths:
                self._discovery_paths.append(norm_path)
                if self.engine:
                    self.engine.add_template_directory(norm_path)

    def remove_discovery_path(self, path: str) -> None:
        """Remove a directory from the discovery paths."""
        with self._lock:
            norm_path = os.path.abspath(os.path.normpath(path))
            if norm_path in self._discovery_paths:
                self._discovery_paths.remove(norm_path)

    def set_discovery_paths(self, paths: List[str]) -> None:
        """Set the full list of discovery paths."""
        with self._lock:
            self._discovery_paths = [
                os.path.abspath(os.path.normpath(p)) for p in paths
            ]
            for path in self._discovery_paths:
                if self.engine:
                    self.engine.add_template_directory(path)

    def discover_all(
        self,
        filter_obj: Optional[DiscoveryFilter] = None,
    ) -> DiscoveryResult:
        """Discover templates from all configured sources."""
        result = DiscoveryResult()
        start_time = time.time()

        self._execute_hooks("before_discover", result)

        if self._discovery_paths:
            fs_result = self._filesystem_discoverer.discover_multiple(
                self._discovery_paths, filter_obj
            )
            result.merge(fs_result)

        pkg_result = self._package_discoverer.discover(filter_obj)
        result.merge(pkg_result)

        if self.config.get("auto_register"):
            for metadata in result.templates.values():
                try:
                    self.register_template(metadata)
                except Exception as exc:
                    logger.warning("Auto-register failed for '%s': %s", metadata.name, exc)

        result.discovery_time_ms = (time.time() - start_time) * 1000
        self._execute_hooks("after_discover", result)
        return result

    def discover_filesystem(
        self,
        directory: Optional[str] = None,
        filter_obj: Optional[DiscoveryFilter] = None,
    ) -> DiscoveryResult:
        """Discover templates from the filesystem."""
        directories = [directory] if directory else self._discovery_paths
        result = self._filesystem_discoverer.discover_multiple(directories, filter_obj)

        if self.config.get("auto_register"):
            for metadata in result.templates.values():
                try:
                    self.register_template(metadata)
                except Exception as exc:
                    logger.warning("Auto-register failed for '%s': %s", metadata.name, exc)

        return result

    def discover_package(
        self,
        filter_obj: Optional[DiscoveryFilter] = None,
    ) -> DiscoveryResult:
        """Discover templates from package resources."""
        result = self._package_discoverer.discover(filter_obj)

        if self.config.get("auto_register"):
            for metadata in result.templates.values():
                try:
                    self.register_template(metadata)
                except Exception as exc:
                    logger.warning("Auto-register failed for '%s': %s", metadata.name, exc)

        return result

    def register_template(self, metadata: TemplateMetadata) -> bool:
        """Register a template in the discovery index."""
        self._execute_hooks("before_register", metadata)

        with self._lock:
            if metadata.name in self._registered_templates:
                existing = self._registered_templates[metadata.name]
                if existing.content_hash == metadata.content_hash:
                    if not existing.registered:
                        existing.registered = True
                        existing.registration_time = datetime.utcnow()
                    return True

            metadata.registered = True
            metadata.registration_time = datetime.utcnow()
            self._registered_templates[metadata.name] = metadata
            self._index.add(metadata)

            if metadata.file_path and self.engine:
                if metadata.file_path not in self.engine.template_dirs:
                    dir_path = os.path.dirname(metadata.file_path)
                    self.engine.add_template_directory(dir_path)

            self._execute_hooks("after_register", metadata)
            logger.info("Registered template '%s' (version %s)", metadata.name, metadata.version)
            return True

    def unregister_template(self, name: str) -> bool:
        """Unregister a template from the discovery index."""
        with self._lock:
            removed = self._index.remove(name)
            if removed:
                self._registered_templates.pop(name, None)
                logger.info("Unregistered template '%s'", name)
            return removed

    def search_templates(
        self,
        filter_obj: DiscoveryFilter,
    ) -> List[TemplateMetadata]:
        """Search registered templates."""
        return self._index.search(filter_obj)

    def get_template(self, name: str) -> Optional[TemplateMetadata]:
        """Get registered template metadata by name."""
        return self._index.get(name)

    def list_templates(self) -> List[TemplateMetadata]:
        """List all registered templates."""
        return self._index.list_all()

    def list_categories(self) -> Dict[TemplateCategory, int]:
        """Get count of templates per category."""
        stats = self._index.get_stats()
        raw = stats.get("categories", {})
        result: Dict[TemplateCategory, int] = {}
        for cat_name, count in raw.items():
            try:
                cat = TemplateCategory(cat_name)
                result[cat] = count
            except ValueError:
                continue
        return result

    def get_index_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        return self._index.get_stats()

    def refresh_index(self) -> int:
        """Rebuild the index from registered templates."""
        with self._lock:
            self._index.clear()
            for metadata in self._registered_templates.values():
                self._index.add(metadata)
            return self._index.count()

    def load_template_source(self, name: str) -> Optional[str]:
        """Load the source content of a registered template."""
        metadata = self._index.get(name)
        if metadata is None:
            return None

        if metadata.file_path and os.path.isfile(metadata.file_path):
            try:
                return Path(metadata.file_path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.error("Failed to load template '%s': %s", name, exc)
                return None

        if metadata.source_module:
            try:
                pkg = __import__(metadata.source_module, fromlist=[""])
                pkg_path = Path(pkg.__file__).parent
                if metadata.file_path:
                    full_path = Path(metadata.file_path)
                    if full_path.exists():
                        return full_path.read_text(encoding="utf-8")
                    rel_path = full_path.name
                    for found in pkg_path.rglob(rel_path):
                        return found.read_text(encoding="utf-8")
            except (ImportError, OSError) as exc:
                logger.error("Failed to load from package '%s': %s", metadata.source_module, exc)

        return None

    def register_discovery_hook(
        self, hook_type: str, hook: Callable
    ) -> None:
        """Register a hook for discovery lifecycle events."""
        if hook_type in self._discovery_hooks:
            self._discovery_hooks[hook_type].append(hook)

    def _execute_hooks(self, hook_type: str, data: Any) -> None:
        """Execute all hooks of a given type."""
        for hook in self._discovery_hooks.get(hook_type, []):
            try:
                hook(data)
            except Exception as exc:
                logger.warning("Hook '%s' failed in '%s': %s", hook.__name__, hook_type, exc)

    def get_discovery_config(self) -> Dict[str, Any]:
        """Get current discovery configuration."""
        return dict(self.config)

    def update_discovery_config(self, updates: Dict[str, Any]) -> None:
        """Update discovery configuration."""
        with self._lock:
            self.config.update(updates)
            self._filesystem_discoverer.config.update(
                self.config.get("filesystem_config", {})
            )
            self._package_discoverer.config.update(
                self.config.get("package_config", {})
            )

    def export_registry(self, file_path: str) -> None:
        """Export the template registry to a JSON file."""
        self._index.export_index(file_path)

    def import_registry(self, file_path: str) -> int:
        """Import templates from a registry JSON file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Registry file not found: {file_path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        templates_data = data.get("templates", {})
        count = 0
        for name, meta_dict in templates_data.items():
            try:
                metadata = TemplateMetadata.from_dict(meta_dict)
                self.register_template(metadata)
                count += 1
            except Exception as exc:
                logger.error("Failed to import template '%s': %s", name, exc)

        return count
