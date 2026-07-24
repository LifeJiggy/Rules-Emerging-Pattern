"""Data and schema migration management with version tracking, rollback, and validation."""

import copy
import hashlib
import importlib
import inspect
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Type, Union

logger = logging.getLogger(__name__)


class MigrationType(str, Enum):
    SCHEMA = "schema"
    DATA = "data"
    INDEX = "index"
    CONFIG = "config"
    BACKUP = "backup"
    FULL = "full"


class MigrationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"
    VERIFIED = "verified"
    PARTIAL = "partial"


class MigrationDirection(str, Enum):
    UP = "up"
    DOWN = "down"


class MigrationError(Exception):
    pass


class MigrationNotFoundError(MigrationError):
    pass


class MigrationVersionError(MigrationError):
    pass


class MigrationConflictError(MigrationError):
    pass


class MigrationRollbackError(MigrationError):
    pass


class MigrationValidationError(MigrationError):
    pass


@dataclass
class MigrationRecord:
    """Record of a single migration execution."""
    id: str
    name: str
    version: str
    migration_type: MigrationType
    direction: MigrationDirection
    status: MigrationStatus
    timestamp: float
    duration_seconds: float = 0.0
    description: str = ""
    author: str = ""
    checksum: str = ""
    rollback_id: Optional[str] = None
    parent_version: Optional[str] = None
    target_version: Optional[str] = None
    affected_entities: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    verified_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "migration_type": self.migration_type.value,
            "direction": self.direction.value,
            "status": self.status.value,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "description": self.description,
            "author": self.author,
            "checksum": self.checksum,
            "rollback_id": self.rollback_id,
            "parent_version": self.parent_version,
            "target_version": self.target_version,
            "affected_entities": self.affected_entities,
            "error_message": self.error_message,
            "verified_at": self.verified_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MigrationRecord":
        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            migration_type=MigrationType(data.get("migration_type", "data")),
            direction=MigrationDirection(data.get("direction", "up")),
            status=MigrationStatus(data.get("status", "completed")),
            timestamp=data["timestamp"],
            duration_seconds=data.get("duration_seconds", 0.0),
            description=data.get("description", ""),
            author=data.get("author", ""),
            checksum=data.get("checksum", ""),
            rollback_id=data.get("rollback_id"),
            parent_version=data.get("parent_version"),
            target_version=data.get("target_version"),
            affected_entities=data.get("affected_entities", []),
            error_message=data.get("error_message"),
            verified_at=data.get("verified_at"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class MigrationScript:
    """A single migration script with up and down functions."""
    version: str
    name: str
    description: str
    migration_type: MigrationType
    up_function: Callable
    down_function: Optional[Callable] = None
    checksum: str = ""
    dependencies: List[str] = field(default_factory=list)
    author: str = ""
    created_at: float = 0.0
    validate_function: Optional[Callable] = None
    tags: List[str] = field(default_factory=list)

    def get_checksum(self) -> str:
        if self.checksum:
            return self.checksum
        source = ""
        try:
            source = inspect.getsource(self.up_function) + (inspect.getsource(self.down_function) if self.down_function else "")
        except (OSError, TypeError):
            source = f"{self.version}:{self.name}:{self.migration_type.value}"
        return hashlib.sha256(source.encode()).hexdigest()[:32]

    def validate(self, context: Dict[str, Any]) -> List[str]:
        if self.validate_function:
            try:
                errors = self.validate_function(context)
                if isinstance(errors, list):
                    return errors
            except Exception as e:
                return [str(e)]
        return []


@dataclass
class MigrationConfig:
    migration_dir: str = "migrations"
    history_file: str = "_migration_history.json"
    lock_timeout: float = 30.0
    auto_discover: bool = True
    validate_before_migration: bool = True
    validate_after_migration: bool = True
    allow_downgrade: bool = True
    max_retries: int = 3
    retry_delay: float = 1.0
    create_backup_before_migration: bool = True
    fail_on_warning: bool = True
    parallel_execution: bool = False
    max_parallel_migrations: int = 4
    script_prefix: str = "migration_"
    script_suffix: str = ".py"
    version_delimiter: str = "_"
    supported_formats: List[str] = field(default_factory=lambda: ["json", "yaml", "py"])
    history_max_entries: int = 1000
    verbose_logging: bool = False


class MigrationScriptLoader:
    """Discovers and loads migration scripts from the filesystem."""

    def __init__(self, config: MigrationConfig):
        self.config = config
        self._scripts: Dict[str, MigrationScript] = {}
        self._lock = threading.RLock()
        self._migration_dir = Path(self.config.migration_dir)

    def discover(self) -> Dict[str, MigrationScript]:
        with self._lock:
            self._scripts.clear()
            if not self._migration_dir.exists():
                logger.info("Migration directory not found: %s", self._migration_dir)
                return self._scripts
            for file_path in sorted(self._migration_dir.glob(f"{self.config.script_prefix}*{self.config.script_suffix}")):
                try:
                    script = self._load_script_from_file(file_path)
                    if script:
                        self._scripts[script.version] = script
                except Exception as e:
                    logger.warning("Failed to load migration script %s: %s", file_path, e)
            logger.info("Discovered %d migration scripts", len(self._scripts))
            return dict(self._scripts)

    def _load_script_from_file(self, file_path: Path) -> Optional[MigrationScript]:
        module_name = f"_migration_{file_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if not spec or not spec.loader:
            logger.warning("Could not load spec for %s", file_path)
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        version = getattr(module, "VERSION", file_path.stem.replace(self.config.script_prefix, ""))
        name = getattr(module, "NAME", file_path.stem)
        description = getattr(module, "DESCRIPTION", "")
        migration_type_str = getattr(module, "MIGRATION_TYPE", "data")
        migration_type = MigrationType(migration_type_str) if migration_type_str in [t.value for t in MigrationType] else MigrationType.DATA
        up_function = getattr(module, "up", None)
        down_function = getattr(module, "down", None)
        validate_function = getattr(module, "validate", None)
        if not up_function:
            logger.warning("Migration script %s has no 'up' function", file_path)
            return None
        deps = getattr(module, "DEPENDENCIES", [])
        author = getattr(module, "AUTHOR", "")
        tags = getattr(module, "TAGS", [])
        script = MigrationScript(
            version=version,
            name=name,
            description=description,
            migration_type=migration_type,
            up_function=up_function,
            down_function=down_function,
            dependencies=deps,
            author=author,
            created_at=file_path.stat().st_ctime,
            validate_function=validate_function,
            tags=tags,
        )
        script.checksum = script.get_checksum()
        return script

    def get_script(self, version: str) -> Optional[MigrationScript]:
        return self._scripts.get(version)

    def get_scripts_since(self, version: str) -> List[MigrationScript]:
        sorted_scripts = sorted(self._scripts.values(), key=lambda s: self._parse_version(s.version))
        found = False
        result = []
        for script in sorted_scripts:
            if script.version == version:
                found = True
                continue
            if found:
                result.append(script)
        return result

    def get_all_versions(self) -> List[str]:
        return sorted(self._scripts.keys(), key=lambda v: self._parse_version(v))

    @staticmethod
    def _parse_version(version: str) -> tuple:
        parts = re.split(r"[._-]", version)
        result = []
        for part in parts:
            try:
                result.append(int(part))
            except ValueError:
                result.append(part)
        return tuple(result)


class MigrationManager:
    """Data and schema migration management with version tracking, rollback, history, and validation."""

    def __init__(self, config: Optional[MigrationConfig] = None,
                 storage_path: Optional[str] = None):
        self.config = config or MigrationConfig()
        self._storage_path = Path(storage_path) if storage_path else Path.cwd()
        self._history_path = self._storage_path / self.config.history_file
        self._history: Dict[str, MigrationRecord] = {}
        self._lock = threading.RLock()
        self._loader = MigrationScriptLoader(self.config)
        self._current_version: Optional[str] = None
        self._total_migrations: int = 0
        self._total_rollbacks: int = 0
        self._total_errors: int = 0
        self._total_validations: int = 0
        self._last_migration_time: float = 0.0
        self._migration_dir = Path(self.config.migration_dir)
        self._migration_dir.mkdir(parents=True, exist_ok=True)
        self._load_history()
        if self.config.auto_discover:
            self._loader.discover()
        self._determine_current_version()
        logger.info("MigrationManager initialized (dir=%s, current_version=%s)",
                     self.config.migration_dir, self._current_version)

    def _load_history(self) -> None:
        if self._history_path.exists():
            try:
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                for record_id, record_dict in data.items():
                    self._history[record_id] = MigrationRecord.from_dict(record_dict)
                logger.info("Loaded %d migration history records", len(self._history))
            except Exception as e:
                logger.warning("Failed to load migration history: %s", e)

    def _save_history(self) -> None:
        self._storage_path.mkdir(parents=True, exist_ok=True)
        data = {rid: r.to_dict() for rid, r in self._history.items()}
        if len(data) > self.config.history_max_entries:
            sorted_records = sorted(data.items(), key=lambda x: x[1]["timestamp"])
            data = dict(sorted_records[-self.config.history_max_entries:])
        try:
            self._history_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save migration history: %s", e)

    def _determine_current_version(self) -> None:
        completed = [
            r for r in self._history.values()
            if r.direction == MigrationDirection.UP and r.status in (MigrationStatus.COMPLETED, MigrationStatus.VERIFIED)
        ]
        if completed:
            latest = max(completed, key=lambda r: r.timestamp)
            self._current_version = latest.target_version or latest.version
        else:
            self._current_version = None

    def get_current_version(self) -> Optional[str]:
        return self._current_version

    def register_script(self, script: MigrationScript) -> None:
        with self._lock:
            self._loader._scripts[script.version] = script
            logger.debug("Registered migration script v%s: %s", script.version, script.name)

    def discover_scripts(self) -> Dict[str, MigrationScript]:
        return self._loader.discover()

    def run_migration(self, target_version: Optional[str] = None,
                      migration_type: Optional[MigrationType] = None,
                      force: bool = False, dry_run: bool = False) -> List[MigrationRecord]:
        results = []
        with self._lock:
            pending = self._get_pending_migrations(target_version, migration_type)
            if not pending:
                logger.info("No pending migrations to run (current: %s)", self._current_version)
                return results
            if not force:
                self._validate_migration_plan(pending)
            for script in pending:
                if dry_run:
                    logger.info("[DRY RUN] Would run migration v%s: %s", script.version, script.name)
                    record = MigrationRecord(
                        id=f"dry_{uuid.uuid4().hex[:8]}",
                        name=script.name,
                        version=script.version,
                        migration_type=script.migration_type,
                        direction=MigrationDirection.UP,
                        status=MigrationStatus.SKIPPED,
                        timestamp=time.time(),
                        description=script.description,
                        checksum=script.get_checksum(),
                        target_version=script.version,
                    )
                    results.append(record)
                    continue
                record = self._execute_migration(script, MigrationDirection.UP)
                results.append(record)
                if record.status == MigrationStatus.FAILED:
                    logger.error("Migration v%s failed, stopping", script.version)
                    break
            if not dry_run:
                self._enforce_history_limit()
        return results

    def rollback_migration(self, target_version: Optional[str] = None,
                           steps: int = 1, force: bool = False) -> List[MigrationRecord]:
        if not self.config.allow_downgrade and not force:
            raise MigrationError("Downgrade not allowed by configuration")
        results = []
        with self._lock:
            completed = self._get_completed_migrations(target_version, steps)
            if not completed:
                logger.info("No migrations to rollback")
                return results
            for record, script in reversed(completed):
                if not script.down_function:
                    logger.warning("Migration v%s has no down function, skipping rollback", script.version)
                    continue
                rollback_record = self._execute_migration(script, MigrationDirection.DOWN)
                results.append(rollback_record)
                if rollback_record.status == MigrationStatus.FAILED:
                    logger.error("Rollback v%s failed, stopping", script.version)
                    break
            self._enforce_history_limit()
        return results

    def _get_pending_migrations(self, target_version: Optional[str] = None,
                                 migration_type: Optional[MigrationType] = None) -> List[MigrationScript]:
        all_scripts = sorted(self._loader._scripts.values(), key=lambda s: s.version)
        pending = []
        for script in all_scripts:
            script_up = any(
                r.version == script.version and r.direction == MigrationDirection.UP
                and r.status in (MigrationStatus.COMPLETED, MigrationStatus.VERIFIED)
                for r in self._history.values()
            )
            if script_up:
                continue
            if migration_type and script.migration_type != migration_type:
                continue
            pending.append(script)
            if target_version and script.version == target_version:
                break
        return pending

    def _get_completed_migrations(self, target_version: Optional[str] = None,
                                   steps: int = 1) -> List[Tuple[MigrationRecord, MigrationScript]]:
        completed = []
        for record in sorted(self._history.values(), key=lambda r: r.timestamp, reverse=True):
            if record.direction == MigrationDirection.UP and record.status in (MigrationStatus.COMPLETED, MigrationStatus.VERIFIED):
                script = self._loader.get_script(record.version)
                if script:
                    completed.append((record, script))
                    if len(completed) >= steps:
                        break
                    if target_version and record.version == target_version:
                        break
        return completed

    def _validate_migration_plan(self, pending: List[MigrationScript]) -> None:
        versions = set()
        for script in pending:
            if script.version in versions:
                raise MigrationConflictError(f"Duplicate migration version: {script.version}")
            versions.add(script.version)
            for dep in script.dependencies:
                dep_scripts = [s for s in self._loader._scripts.values() if s.version == dep]
                if not dep_scripts:
                    raise MigrationError(f"Migration v{script.version} depends on missing v{dep}")
                dep_completed = any(
                    r.version == dep and r.direction == MigrationDirection.UP
                    and r.status in (MigrationStatus.COMPLETED, MigrationStatus.VERIFIED)
                    for r in self._history.values()
                )
                if not dep_completed:
                    raise MigrationError(f"Migration v{script.version} depends on v{dep} which is not completed")

    def _execute_migration(self, script: MigrationScript, direction: MigrationDirection) -> MigrationRecord:
        record_id = f"mig_{uuid.uuid4().hex[:8]}"
        record = MigrationRecord(
            id=record_id,
            name=script.name,
            version=script.version,
            migration_type=script.migration_type,
            direction=direction,
            status=MigrationStatus.RUNNING,
            timestamp=time.time(),
            description=script.description,
            author=script.author,
            checksum=script.get_checksum(),
            target_version=script.version if direction == MigrationDirection.UP else None,
        )
        start_time = time.time()
        try:
            if self.config.create_backup_before_migration:
                self._create_pre_migration_backup(script.version)
            if self.config.validate_before_migration:
                errors = script.validate({"direction": direction.value, "version": script.version, "manager": self})
                if errors:
                    if self.config.fail_on_warning:
                        raise MigrationValidationError(f"Pre-migration validation failed: {errors}")
                    logger.warning("Pre-migration validation warnings: %s", errors)
            affected = []
            if direction == MigrationDirection.UP:
                result = script.up_function(self._get_migration_context())
            else:
                result = script.down_function(self._get_migration_context()) if script.down_function else None
            if isinstance(result, list):
                affected = result
            elif isinstance(result, dict):
                affected = result.get("affected", [])
            record.affected_entities = affected
            record.duration_seconds = time.time() - start_time
            if self.config.validate_after_migration:
                errors = script.validate({"direction": direction.value, "version": script.version, "manager": self, "after": True})
                if errors:
                    if self.config.fail_on_warning:
                        raise MigrationValidationError(f"Post-migration validation failed: {errors}")
                    logger.warning("Post-migration validation warnings: %s", errors)
            record.status = MigrationStatus.COMPLETED
            self._history[record_id] = record
            self._save_history()
            self._total_migrations += 1
            self._last_migration_time = time.time()
            if direction == MigrationDirection.UP:
                self._current_version = script.version
            logger.info("Migration %s v%s completed in %.2fs (%d entities)",
                         direction.value, script.version, record.duration_seconds, len(affected))
            return record
        except Exception as e:
            record.duration_seconds = time.time() - start_time
            record.status = MigrationStatus.FAILED
            record.error_message = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            self._history[record_id] = record
            self._save_history()
            self._total_errors += 1
            logger.error("Migration v%s %s failed: %s", script.version, direction.value, e)
            return record

    def _get_migration_context(self) -> Dict[str, Any]:
        return {
            "storage_path": str(self._storage_path),
            "migration_dir": str(self._migration_dir),
            "current_version": self._current_version,
            "history": {k: v.to_dict() for k, v in self._history.items()},
            "config": self.config,
        }

    def _create_pre_migration_backup(self, version: str) -> None:
        backup_dir = self._storage_path / "_pre_migration_backups" / f"pre_{version}_{int(time.time())}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for item in self._storage_path.iterdir():
            if item.is_file() and not item.name.startswith("_") and not item.name.startswith("."):
                try:
                    shutil.copy2(str(item), str(backup_dir / item.name))
                except Exception as e:
                    logger.warning("Pre-migration backup failed for %s: %s", item.name, e)
        logger.debug("Pre-migration backup created at %s", backup_dir)

    def verify_migration(self, record_id: str) -> bool:
        record = self._history.get(record_id)
        if not record:
            raise MigrationNotFoundError(f"Migration record {record_id} not found")
        script = self._loader.get_script(record.version)
        if not script:
            logger.warning("Migration script v%s not found for verification", record.version)
            return False
        errors = script.validate({"direction": record.direction.value, "version": record.version, "manager": self, "verify": True})
        if errors:
            record.status = MigrationStatus.FAILED
            record.error_message = f"Verification failed: {errors}"
            self._save_history()
            raise MigrationValidationError(f"Verification failed for {record_id}: {errors}")
        record.status = MigrationStatus.VERIFIED
        record.verified_at = time.time()
        self._save_history()
        logger.info("Migration %s verified", record_id)
        return True

    def verify_all(self) -> Dict[str, bool]:
        results = {}
        for record_id in list(self._history.keys()):
            try:
                results[record_id] = self.verify_migration(record_id)
            except Exception as e:
                results[record_id] = False
                logger.warning("Verification failed for %s: %s", record_id, e)
        return results

    def get_history(self, limit: Optional[int] = None, offset: int = 0,
                    status: Optional[MigrationStatus] = None,
                    migration_type: Optional[MigrationType] = None) -> List[MigrationRecord]:
        records = list(self._history.values())
        if status:
            records = [r for r in records if r.status == status]
        if migration_type:
            records = [r for r in records if r.migration_type == migration_type]
        records.sort(key=lambda r: r.timestamp, reverse=True)
        if offset:
            records = records[offset:]
        if limit:
            records = records[:limit]
        return records

    def get_migration_record(self, record_id: str) -> Optional[MigrationRecord]:
        return self._history.get(record_id)

    def create_migration_script(self, name: str, version: str,
                                 migration_type: MigrationType = MigrationType.DATA,
                                 author: str = "",
                                 description: str = "",
                                 up_code: Optional[str] = None,
                                 down_code: Optional[str] = None) -> Path:
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        script_name = f"{self.config.script_prefix}{version}_{safe_name}{self.config.script_suffix}"
        script_path = self._migration_dir / script_name
        up_content = up_code or """
def up(context):
    \"\"\"Up migration implementation.\"\"\"
    logger = context.get("logger")
    storage_path = context.get("storage_path")
    # TODO: Implement up migration
    return []
"""
        down_content = down_code or """
def down(context):
    \"\"\"Down migration implementation.\"\"\"
    logger = context.get("logger")
    storage_path = context.get("storage_path")
    # TODO: Implement down migration
    return []
"""
        validate_content = """
def validate(context):
    \"\"\"Validate migration state.\"\"\"
    return []
"""
        content = f'''"""
Migration: {name}
Version: {version}
Type: {migration_type.value}
Author: {author}
Description: {description}
"""

import logging

logger = logging.getLogger(__name__)

VERSION = "{version}"
NAME = "{name}"
DESCRIPTION = """{description}"""
MIGRATION_TYPE = "{migration_type.value}"
AUTHOR = "{author}"
DEPENDENCIES = []
TAGS = []

{up_content}

{down_content}

{validate_content}
'''
        script_path.write_text(content, encoding="utf-8")
        logger.info("Created migration script: %s", script_path)
        return script_path

    def validate_schema(self, schema: Dict[str, Any], data: Dict[str, Any],
                        strict: bool = False) -> List[str]:
        errors = []
        for field, expected_type in schema.items():
            if field not in data:
                if strict:
                    errors.append(f"Missing field: {field}")
                continue
            actual = data[field]
            if isinstance(expected_type, type):
                if not isinstance(actual, expected_type):
                    errors.append(f"Field '{field}' expected {expected_type.__name__}, got {type(actual).__name__}")
            elif isinstance(expected_type, dict):
                if isinstance(actual, dict):
                    errors.extend(self.validate_schema(expected_type, actual, strict))
                else:
                    errors.append(f"Field '{field}' expected dict, got {type(actual).__name__}")
            elif isinstance(expected_type, list):
                if isinstance(expected_type[0], type) if expected_type else True:
                    if isinstance(actual, list):
                        for item in actual:
                            if not isinstance(item, expected_type[0]):
                                errors.append(f"Field '{field}' items expected {expected_type[0].__name__}, got {type(item).__name__}")
                    else:
                        errors.append(f"Field '{field}' expected list, got {type(actual).__name__}")
        return errors

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            by_type = {}
            by_status = {}
            for record in self._history.values():
                by_type[record.migration_type.value] = by_type.get(record.migration_type.value, 0) + 1
                by_status[record.status.value] = by_status.get(record.status.value, 0) + 1
            return {
                "total_migrations": self._total_migrations,
                "total_rollbacks": self._total_rollbacks,
                "total_errors": self._total_errors,
                "total_validations": self._total_validations,
                "current_version": self._current_version,
                "history_count": len(self._history),
                "scripts_available": len(self._loader._scripts),
                "last_migration_time": datetime.fromtimestamp(self._last_migration_time).isoformat() if self._last_migration_time else None,
                "by_type": by_type,
                "by_status": by_status,
                "migration_dir": str(self._migration_dir),
                "allow_downgrade": self.config.allow_downgrade,
                "validate_before": self.config.validate_before_migration,
                "validate_after": self.config.validate_after_migration,
            }

    def _enforce_history_limit(self) -> None:
        if len(self._history) > self.config.history_max_entries:
            sorted_records = sorted(self._history.items(), key=lambda x: x[1].timestamp)
            to_remove = len(self._history) - self.config.history_max_entries
            for record_id, _ in sorted_records[:to_remove]:
                del self._history[record_id]
            self._save_history()

    def close(self) -> None:
        self._save_history()
        logger.info("MigrationManager closed")

    def __enter__(self) -> "MigrationManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __len__(self) -> int:
        return len(self._history)

    def __contains__(self, record_id: str) -> bool:
        return record_id in self._history

    def __repr__(self) -> str:
        return f"MigrationManager(dir={self.config.migration_dir}, scripts={len(self._loader._scripts)}, current_v={self._current_version})"