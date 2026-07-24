"""Backup management for rule sets and configurations with scheduling, rotation, and verification."""

import copy
import hashlib
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


class BackupType(str, Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"


class BackupSchedule(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ON_CHANGE = "on_change"
    MANUAL = "manual"
    HOURLY = "hourly"


class BackupStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"
    CORRUPTED = "corrupted"


class BackupError(Exception):
    pass


class BackupNotFoundError(BackupError):
    pass


class BackupVerificationError(BackupError):
    pass


class BackupRestoreError(BackupError):
    pass


@dataclass
class BackupPolicy:
    schedule: BackupSchedule = BackupSchedule.DAILY
    retention_days: int = 30
    max_full_backups: int = 10
    max_incremental_per_full: int = 20
    compression_enabled: bool = True
    compression_level: int = 6
    verify_after_backup: bool = True
    verify_checksum: bool = True
    backup_source_dirs: List[str] = field(default_factory=lambda: ["storage/rules", "config"])
    exclude_patterns: List[str] = field(default_factory=lambda: ["*.tmp", "_metadata.json", "_index.json"])
    include_patterns: List[str] = field(default_factory=lambda: ["*.json", "*.yaml", "*.yml"])
    remote_enabled: bool = False
    remote_url: Optional[str] = None
    encrypt_backups: bool = False
    encryption_key: Optional[str] = None
    min_backup_interval_hours: float = 1.0
    max_backup_size_mb: int = 1000
    fail_on_warning: bool = False
    notify_on_failure: bool = True
    notify_on_success: bool = False


@dataclass
class BackupManifest:
    """Metadata for a single backup."""
    id: str
    type: BackupType
    schedule: BackupSchedule
    status: BackupStatus
    timestamp: float
    size_bytes: int
    file_count: int
    checksum: str
    parent_backup_id: Optional[str] = None
    base_backup_id: Optional[str] = None
    source_paths: List[str] = field(default_factory=list)
    compressed: bool = False
    encrypted: bool = False
    version: str = "1.0"
    error_message: Optional[str] = None
    verified_at: Optional[float] = None
    duration_seconds: float = 0.0
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def age_days(self) -> float:
        return (time.time() - self.timestamp) / 86400

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "schedule": self.schedule.value,
            "status": self.status.value,
            "timestamp": self.timestamp,
            "size_bytes": self.size_bytes,
            "file_count": self.file_count,
            "checksum": self.checksum,
            "parent_backup_id": self.parent_backup_id,
            "base_backup_id": self.base_backup_id,
            "source_paths": self.source_paths,
            "compressed": self.compressed,
            "encrypted": self.encrypted,
            "version": self.version,
            "error_message": self.error_message,
            "verified_at": self.verified_at,
            "duration_seconds": self.duration_seconds,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackupManifest":
        return cls(
            id=data["id"],
            type=BackupType(data["type"]),
            schedule=BackupSchedule(data.get("schedule", "manual")),
            status=BackupStatus(data.get("status", "completed")),
            timestamp=data["timestamp"],
            size_bytes=data.get("size_bytes", 0),
            file_count=data.get("file_count", 0),
            checksum=data.get("checksum", ""),
            parent_backup_id=data.get("parent_backup_id"),
            base_backup_id=data.get("base_backup_id"),
            source_paths=data.get("source_paths", []),
            compressed=data.get("compressed", False),
            encrypted=data.get("encrypted", False),
            version=data.get("version", "1.0"),
            error_message=data.get("error_message"),
            verified_at=data.get("verified_at"),
            duration_seconds=data.get("duration_seconds", 0.0),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


class BackupManager:
    """Backup management for rule sets and configurations with scheduling, rotation, verification, and restoration."""

    def __init__(self, backup_dir: str = "backups", policy: Optional[BackupPolicy] = None):
        self._backup_dir = Path(backup_dir)
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self.policy = policy or BackupPolicy()
        self._manifests: Dict[str, BackupManifest] = {}
        self._lock = threading.RLock()
        self._scheduler_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._callback_lock = threading.Lock()
        self._on_backup_start: List[Callable] = []
        self._on_backup_complete: List[Callable] = []
        self._on_backup_failed: List[Callable] = []
        self._on_restore_start: List[Callable] = []
        self._on_restore_complete: List[Callable] = []
        self._on_restore_failed: List[Callable] = []
        self._total_backups: int = 0
        self._total_restores: int = 0
        self._total_errors: int = 0
        self._last_backup_time: float = 0.0
        self._last_restore_time: float = 0.0
        self._manifest_path = self._backup_dir / "_manifests.json"
        self._load_manifests()
        if self.policy.schedule != BackupSchedule.MANUAL:
            self._start_scheduler()
        logger.info("BackupManager initialized at %s (policy=%s, retention=%dd)",
                     backup_dir, self.policy.schedule.value, self.policy.retention_days)

    def _load_manifests(self) -> None:
        if self._manifest_path.exists():
            try:
                data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
                for backup_id, manifest_dict in data.items():
                    self._manifests[backup_id] = BackupManifest.from_dict(manifest_dict)
                logger.info("Loaded %d backup manifests", len(self._manifests))
            except Exception as e:
                logger.warning("Failed to load manifests: %s", e)

    def _save_manifests(self) -> None:
        data = {bid: m.to_dict() for bid, m in self._manifests.items()}
        try:
            self._manifest_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save manifests: %s", e)

    def _start_scheduler(self) -> None:
        self._shutdown_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="backup-scheduler",
            daemon=True
        )
        self._scheduler_thread.start()
        logger.info("Backup scheduler started (schedule=%s)", self.policy.schedule.value)

    def _scheduler_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                interval = self._get_schedule_interval_seconds()
                self._shutdown_event.wait(interval)
                if self._shutdown_event.is_set():
                    break
                if self._should_run_backup():
                    self.create_backup(schedule=self.policy.schedule)
            except Exception as e:
                logger.error("Scheduler error: %s", e)

    def _get_schedule_interval_seconds(self) -> float:
        mapping = {
            BackupSchedule.HOURLY: 3600,
            BackupSchedule.DAILY: 86400,
            BackupSchedule.WEEKLY: 604800,
            BackupSchedule.MONTHLY: 2592000,
            BackupSchedule.ON_CHANGE: 300,
            BackupSchedule.MANUAL: 86400,
        }
        return mapping.get(self.policy.schedule, 86400)

    def _should_run_backup(self) -> bool:
        if not self._last_backup_time:
            return True
        elapsed = time.time() - self._last_backup_time
        min_interval = self.policy.min_backup_interval_hours * 3600
        if elapsed < min_interval:
            return False
        if self.policy.schedule == BackupSchedule.ON_CHANGE:
            return self._detect_changes_since_last_backup()
        schedule_interval = self._get_schedule_interval_seconds()
        return elapsed >= schedule_interval

    def _detect_changes_since_last_backup(self) -> bool:
        if not self._last_backup_time:
            return True
        for source_dir in self.policy.backup_source_dirs:
            src_path = Path(source_dir)
            if not src_path.exists():
                continue
            for file_path in src_path.rglob("*"):
                if file_path.is_file() and self._should_include_file(file_path):
                    try:
                        if file_path.stat().st_mtime > self._last_backup_time:
                            return True
                    except OSError:
                        continue
        return False

    def _should_include_file(self, file_path: Path) -> bool:
        rel = file_path.name
        for pattern in self.policy.exclude_patterns:
            if Path(rel).match(pattern):
                return False
        if self.policy.include_patterns:
            for pattern in self.policy.include_patterns:
                if Path(rel).match(pattern):
                    return True
            return False
        return True

    def _collect_source_files(self, base_backup_id: Optional[str] = None) -> List[Tuple[str, Path]]:
        files: List[Tuple[str, Path]] = []
        base_manifest = self._manifests.get(base_backup_id) if base_backup_id else None
        base_files: Set[str] = set()
        if base_manifest and base_manifest.type == BackupType.FULL:
            base_files = set(base_manifest.metadata.get("file_paths", []))
        for source_dir in self.policy.backup_source_dirs:
            src_path = Path(source_dir)
            if not src_path.exists():
                logger.warning("Source directory not found: %s", source_dir)
                continue
            for file_path in src_path.rglob("*"):
                if file_path.is_file() and self._should_include_file(file_path):
                    rel_path = str(file_path.relative_to(src_path.parent if src_path.parent else src_path))
                    if base_backup_id and rel_path in base_files:
                        try:
                            current_mtime = file_path.stat().st_mtime
                            base_mtime = base_manifest.metadata.get("file_mtimes", {}).get(rel_path, 0)
                            if current_mtime == base_mtime:
                                continue
                        except OSError:
                            pass
                    files.append((rel_path, file_path))
        return files

    def _compute_checksum(self, file_path: Path) -> str:
        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()[:64]
        except Exception as e:
            logger.warning("Failed to compute checksum for %s: %s", file_path, e)
            return ""

    def create_backup(self, backup_type: BackupType = BackupType.FULL,
                      schedule: Optional[BackupSchedule] = None,
                      tags: Optional[List[str]] = None,
                      source_paths: Optional[List[str]] = None) -> BackupManifest:
        schedule = schedule or self.policy.schedule
        source_paths = source_paths or self.policy.backup_source_dirs
        backup_id = f"backup_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        manifest = BackupManifest(
            id=backup_id,
            type=backup_type,
            schedule=schedule,
            status=BackupStatus.RUNNING,
            timestamp=time.time(),
            size_bytes=0,
            file_count=0,
            checksum="",
            source_paths=source_paths,
            compressed=self.policy.compression_enabled,
            encrypted=self.policy.encrypt_backups,
        )
        if backup_type == BackupType.INCREMENTAL or backup_type == BackupType.DIFFERENTIAL:
            base = self._find_latest_full_backup()
            if base:
                manifest.base_backup_id = base.id
                if backup_type == BackupType.INCREMENTAL:
                    incremental_chain = self._get_incremental_chain(base.id)
                    manifest.parent_backup_id = incremental_chain[-1].id if incremental_chain else base.id
        start_time = time.time()
        try:
            for cb in self._on_backup_start:
                self._safe_call(cb, manifest)
            backup_path = self._backup_dir / backup_id
            backup_path.mkdir(parents=True, exist_ok=True)
            files = self._collect_source_files(manifest.base_backup_id)
            file_paths = []
            file_mtimes = {}
            manifest.file_count = 0
            manifest.size_bytes = 0
            for rel_path, abs_path in files:
                dest_path = backup_path / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(str(abs_path), str(dest_path))
                    file_paths.append(rel_path)
                    file_mtimes[rel_path] = abs_path.stat().st_mtime
                    manifest.file_count += 1
                    manifest.size_bytes += dest_path.stat().st_size
                except Exception as e:
                    logger.warning("Failed to backup %s: %s", abs_path, e)
            manifest.metadata["file_paths"] = file_paths
            manifest.metadata["file_mtimes"] = file_mtimes
            manifest.tags = tags or []
            if self.policy.compression_enabled:
                archive_path = self._compress_backup(backup_path, backup_id)
                if archive_path:
                    manifest.size_bytes = archive_path.stat().st_size
                    manifest.compressed = True
            if self.policy.verify_checksum:
                manifest.checksum = self._compute_checksum(backup_path if not self.policy.compression_enabled else archive_path)
            manifest.duration_seconds = time.time() - start_time
            manifest.status = BackupStatus.COMPLETED
            with self._lock:
                self._manifests[backup_id] = manifest
                self._save_manifests()
                self._total_backups += 1
                self._last_backup_time = time.time()
            if self.policy.verify_after_backup:
                try:
                    self.verify_backup(backup_id)
                except BackupVerificationError as e:
                    logger.warning("Backup verification warning: %s", e)
            self._enforce_retention_policy()
            for cb in self._on_backup_complete:
                self._safe_call(cb, manifest)
            logger.info("Backup %s created: type=%s, files=%d, size=%dMB",
                         backup_id, backup_type.value, manifest.file_count,
                         manifest.size_bytes // (1024 * 1024))
            return manifest
        except Exception as e:
            manifest.status = BackupStatus.FAILED
            manifest.error_message = str(e)
            manifest.duration_seconds = time.time() - start_time
            with self._lock:
                self._manifests[backup_id] = manifest
                self._save_manifests()
                self._total_errors += 1
            for cb in self._on_backup_failed:
                self._safe_call(cb, manifest, e)
            raise BackupError(f"Backup failed: {e}") from e

    def _compress_backup(self, backup_path: Path, backup_id: str) -> Optional[Path]:
        archive_path = self._backup_dir / f"{backup_id}.tar.gz"
        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(backup_path, arcname=backup_id)
            shutil.rmtree(backup_path, ignore_errors=True)
            logger.debug("Compressed backup %s to %s", backup_id, archive_path)
            return archive_path
        except Exception as e:
            logger.error("Failed to compress backup %s: %s", backup_id, e)
            return None

    def _find_latest_full_backup(self) -> Optional[BackupManifest]:
        full_backups = [
            m for m in self._manifests.values()
            if m.type == BackupType.FULL and m.status in (BackupStatus.COMPLETED, BackupStatus.VERIFIED)
        ]
        if not full_backups:
            return None
        return max(full_backups, key=lambda m: m.timestamp)

    def _get_incremental_chain(self, base_id: str) -> List[BackupManifest]:
        chain = []
        current_id = base_id
        while True:
            children = [
                m for m in self._manifests.values()
                if m.parent_backup_id == current_id
                and m.type == BackupType.INCREMENTAL
                and m.status in (BackupStatus.COMPLETED, BackupStatus.VERIFIED)
            ]
            if not children:
                break
            next_backup = max(children, key=lambda m: m.timestamp)
            chain.append(next_backup)
            current_id = next_backup.id
        return chain

    def restore_backup(self, backup_id: str, restore_path: Optional[str] = None,
                       overwrite: bool = False) -> int:
        manifest = self._manifests.get(backup_id)
        if not manifest:
            raise BackupNotFoundError(f"Backup {backup_id} not found")
        if manifest.status == BackupStatus.CORRUPTED:
            raise BackupRestoreError(f"Cannot restore corrupted backup {backup_id}")
        restore_root = Path(restore_path) if restore_path else self._backup_dir.parent
        start_time = time.time()
        try:
            for cb in self._on_restore_start:
                self._safe_call(cb, manifest)
            backup_path = self._backup_dir / backup_id
            archive_path = self._backup_dir / f"{backup_id}.tar.gz"
            if archive_path.exists():
                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(path=self._backup_dir)
                backup_path = self._backup_dir / backup_id
            if not backup_path.exists() or not backup_path.is_dir():
                raise BackupRestoreError(f"Backup data not found for {backup_id}")
            restored = 0
            for rel_path in manifest.metadata.get("file_paths", []):
                src = backup_path / rel_path
                if not src.exists():
                    logger.warning("File missing in backup: %s", rel_path)
                    continue
                dest = restore_root / rel_path
                if dest.exists() and not overwrite:
                    logger.debug("Skipping existing file: %s", dest)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(str(src), str(dest))
                    restored += 1
                except Exception as e:
                    logger.warning("Failed to restore %s: %s", rel_path, e)
            if manifest.type == BackupType.INCREMENTAL or manifest.type == BackupType.DIFFERENTIAL:
                chain = [manifest]
                if manifest.parent_backup_id:
                    parent = self._manifests.get(manifest.parent_backup_id)
                    while parent:
                        chain.append(parent)
                        parent = self._manifests.get(parent.parent_backup_id) if parent.parent_backup_id else None
                for backup in reversed(chain):
                    if backup.id == manifest.id:
                        continue
                    for rel_path in backup.metadata.get("file_paths", []):
                        src = (self._backup_dir / backup.id) / rel_path
                        if not src.exists():
                            continue
                        dest = restore_root / rel_path
                        if dest.exists() and not overwrite:
                            continue
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.copy2(str(src), str(dest))
                            restored += 1
                        except Exception as e:
                            logger.warning("Failed to restore %s from chain: %s", rel_path, e)
            if archive_path.exists() and backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)
            with self._lock:
                self._total_restores += 1
                self._last_restore_time = time.time()
            for cb in self._on_restore_complete:
                self._safe_call(cb, manifest, restored)
            logger.info("Restored %d files from backup %s to %s", restored, backup_id, restore_root)
            return restored
        except Exception as e:
            self._total_errors += 1
            for cb in self._on_restore_failed:
                self._safe_call(cb, manifest, str(e))
            raise BackupRestoreError(f"Restore failed: {e}") from e

    def verify_backup(self, backup_id: str) -> bool:
        manifest = self._manifests.get(backup_id)
        if not manifest:
            raise BackupNotFoundError(f"Backup {backup_id} not found")
        backup_path = self._backup_dir / backup_id
        archive_path = self._backup_dir / f"{backup_id}.tar.gz"
        if archive_path.exists():
            if self.policy.verify_checksum:
                checksum = self._compute_checksum(archive_path)
                if manifest.checksum and checksum != manifest.checksum:
                    manifest.status = BackupStatus.CORRUPTED
                    manifest.verified_at = time.time()
                    self._save_manifests()
                    raise BackupVerificationError(f"Checksum mismatch for {backup_id}: expected {manifest.checksum}, got {checksum}")
            manifest.status = BackupStatus.VERIFIED
            manifest.verified_at = time.time()
            self._save_manifests()
            return True
        if not backup_path.exists():
            raise BackupNotFoundError(f"Backup data not found for {backup_id}")
        expected_count = manifest.file_count
        actual_count = 0
        total_size = 0
        for file_path in backup_path.rglob("*"):
            if file_path.is_file():
                actual_count += 1
                total_size += file_path.stat().st_size
        if expected_count > 0 and actual_count < expected_count:
            if self.policy.fail_on_warning:
                manifest.status = BackupStatus.CORRUPTED
                self._save_manifests()
                raise BackupVerificationError(f"File count mismatch: expected {expected_count}, got {actual_count}")
            logger.warning("Backup %s: file count mismatch (expected %d, got %d)", backup_id, expected_count, actual_count)
        manifest.status = BackupStatus.VERIFIED
        manifest.verified_at = time.time()
        manifest.size_bytes = total_size
        self._save_manifests()
        logger.info("Backup %s verified: %d files, %dMB", backup_id, actual_count, total_size // (1024 * 1024))
        return True

    def verify_all_backups(self) -> Dict[str, bool]:
        results = {}
        for backup_id in list(self._manifests.keys()):
            try:
                results[backup_id] = self.verify_backup(backup_id)
            except Exception as e:
                results[backup_id] = False
                logger.warning("Backup %s verification failed: %s", backup_id, e)
        return results

    def delete_backup(self, backup_id: str) -> bool:
        with self._lock:
            if backup_id not in self._manifests:
                return False
            backup_path = self._backup_dir / backup_id
            archive_path = self._backup_dir / f"{backup_id}.tar.gz"
            if backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)
            if archive_path.exists():
                archive_path.unlink(missing_ok=True)
            del self._manifests[backup_id]
            self._save_manifests()
            logger.info("Deleted backup %s", backup_id)
            return True

    def list_backups(self, backup_type: Optional[BackupType] = None,
                     status: Optional[BackupStatus] = None,
                     schedule: Optional[BackupSchedule] = None,
                     tags: Optional[List[str]] = None,
                     limit: Optional[int] = None, offset: int = 0) -> List[BackupManifest]:
        result = list(self._manifests.values())
        if backup_type:
            result = [m for m in result if m.type == backup_type]
        if status:
            result = [m for m in result if m.status == status]
        if schedule:
            result = [m for m in result if m.schedule == schedule]
        if tags:
            result = [m for m in result if any(t in m.tags for t in tags)]
        result.sort(key=lambda m: m.timestamp, reverse=True)
        if offset:
            result = result[offset:]
        if limit:
            result = result[:limit]
        return result

    def get_backup(self, backup_id: str) -> Optional[BackupManifest]:
        return self._manifests.get(backup_id)

    def get_latest_backup(self, backup_type: Optional[BackupType] = None) -> Optional[BackupManifest]:
        backups = self.list_backups(backup_type=backup_type, limit=1)
        return backups[0] if backups else None

    def _enforce_retention_policy(self) -> int:
        with self._lock:
            now = time.time()
            deleted = 0
            full_backups = sorted(
                [m for m in self._manifests.values() if m.type == BackupType.FULL],
                key=lambda m: m.timestamp, reverse=True
            )
            expired_full = full_backups[self.policy.max_full_backups:] if len(full_backups) > self.policy.max_full_backups else []
            for manifest in expired_full:
                self.delete_backup(manifest.id)
                deleted += 1
            all_backups = sorted(
                self._manifests.values(),
                key=lambda m: m.timestamp, reverse=True
            )
            retention_cutoff = now - (self.policy.retention_days * 86400)
            for manifest in all_backups:
                if manifest.timestamp < retention_cutoff:
                    self.delete_backup(manifest.id)
                    deleted += 1
            if deleted:
                logger.info("Retention policy removed %d backups", deleted)
            return deleted

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total_size = sum(m.size_bytes for m in self._manifests.values())
            return {
                "total_backups": len(self._manifests),
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "total_restores": self._total_restores,
                "total_errors": self._total_errors,
                "last_backup_time": datetime.fromtimestamp(self._last_backup_time).isoformat() if self._last_backup_time else None,
                "last_restore_time": datetime.fromtimestamp(self._last_restore_time).isoformat() if self._last_restore_time else None,
                "by_type": {t.value: sum(1 for m in self._manifests.values() if m.type == t) for t in BackupType},
                "by_status": {s.value: sum(1 for m in self._manifests.values() if m.status == s) for s in BackupStatus},
                "policy": {
                    "schedule": self.policy.schedule.value,
                    "retention_days": self.policy.retention_days,
                    "max_full_backups": self.policy.max_full_backups,
                    "compression_enabled": self.policy.compression_enabled,
                    "verify_after_backup": self.policy.verify_after_backup,
                },
                "backup_dir": str(self._backup_dir),
            }

    def run_scheduled_backup(self) -> Optional[BackupManifest]:
        if not self._should_run_backup():
            logger.debug("Scheduled backup skipped - not due yet")
            return None
        return self.create_backup(schedule=self.policy.schedule)

    def add_on_backup_start(self, callback: Callable) -> None:
        with self._callback_lock:
            self._on_backup_start.append(callback)

    def add_on_backup_complete(self, callback: Callable) -> None:
        with self._callback_lock:
            self._on_backup_complete.append(callback)

    def add_on_backup_failed(self, callback: Callable) -> None:
        with self._callback_lock:
            self._on_backup_failed.append(callback)

    def add_on_restore_start(self, callback: Callable) -> None:
        with self._callback_lock:
            self._on_restore_start.append(callback)

    def add_on_restore_complete(self, callback: Callable) -> None:
        with self._callback_lock:
            self._on_restore_complete.append(callback)

    def add_on_restore_failed(self, callback: Callable) -> None:
        with self._callback_lock:
            self._on_restore_failed.append(callback)

    def remove_callback(self, callback: Callable) -> None:
        with self._callback_lock:
            for lst in [self._on_backup_start, self._on_backup_complete, self._on_backup_failed,
                        self._on_restore_start, self._on_restore_complete, self._on_restore_failed]:
                if callback in lst:
                    lst.remove(callback)

    @staticmethod
    def _safe_call(callback: Callable, *args, **kwargs) -> None:
        try:
            callback(*args, **kwargs)
        except Exception as e:
            logger.error("Callback error: %s", e)

    def close(self) -> None:
        self._shutdown_event.set()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=5)
        self._save_manifests()
        logger.info("BackupManager closed")

    def __enter__(self) -> "BackupManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __len__(self) -> int:
        return len(self._manifests)

    def __contains__(self, backup_id: str) -> bool:
        return backup_id in self._manifests

    def __getitem__(self, backup_id: str) -> BackupManifest:
        manifest = self._manifests.get(backup_id)
        if not manifest:
            raise BackupNotFoundError(f"Backup {backup_id} not found")
        return manifest

    def __repr__(self) -> str:
        return f"BackupManager(dir={self._backup_dir}, backups={len(self._manifests)}, schedule={self.policy.schedule.value})"