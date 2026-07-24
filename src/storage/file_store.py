"""Generic file-based key-value store supporting JSON, YAML, and binary formats with atomic operations."""

import base64
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


class FileFormat(str, Enum):
    JSON = "json"
    YAML = "yaml"
    BINARY = "binary"
    TEXT = "text"
    PICKLE = "pickle"


class FileStoreError(Exception):
    pass


class KeyNotFoundError(FileStoreError):
    pass


class KeyExistsError(FileStoreError):
    pass


class FileLockError(FileStoreError):
    pass


class CorruptedDataError(FileStoreError):
    pass


@dataclass
class FileStoreConfig:
    base_path: str = "data/store"
    format: FileFormat = FileFormat.JSON
    pretty_print: bool = True
    auto_create_dirs: bool = True
    atomic_writes: bool = True
    enable_locking: bool = True
    lock_timeout: float = 10.0
    max_file_size_mb: int = 100
    max_keys: int = 100000
    compression_enabled: bool = False
    file_extension: str = ".json"
    encoding: str = "utf-8"
    sync_on_write: bool = True
    backup_on_overwrite: bool = False
    cache_enabled: bool = True
    cache_max_size: int = 1000
    cache_ttl: float = 60.0
    dir_depth: int = 2
    dir_branching: int = 256


class FileLock:
    """Per-file lock for concurrent access control."""

    def __init__(self, lock_timeout: float = 10.0):
        self._locks: Dict[str, threading.Lock] = {}
        self._owners: Dict[str, str] = {}
        self._timestamps: Dict[str, float] = {}
        self._global_lock = threading.Lock()
        self._lock_timeout = lock_timeout

    def acquire(self, key: str, owner: Optional[str] = None, timeout: Optional[float] = None) -> bool:
        effective_timeout = timeout or self._lock_timeout
        owner_id = owner or f"thread-{threading.get_ident()}"
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            file_lock = self._locks[key]
        acquired = file_lock.acquire(timeout=effective_timeout)
        if acquired:
            with self._global_lock:
                self._owners[key] = owner_id
                self._timestamps[key] = time.time()
            return True
        return False

    def release(self, key: str, owner: Optional[str] = None) -> None:
        owner_id = owner or f"thread-{threading.get_ident()}"
        with self._global_lock:
            if key in self._owners and self._owners[key] != owner_id:
                raise FileLockError(f"Lock on {key} owned by {self._owners[key]}, not {owner_id}")
            file_lock = self._locks.get(key)
            if file_lock:
                file_lock.release()
                self._owners.pop(key, None)
                self._timestamps.pop(key, None)

    def is_locked(self, key: str) -> bool:
        with self._global_lock:
            file_lock = self._locks.get(key)
            if file_lock:
                return file_lock.locked()
            return False

    def get_owner(self, key: str) -> Optional[str]:
        with self._global_lock:
            return self._owners.get(key)

    def force_release(self, key: str) -> None:
        with self._global_lock:
            file_lock = self._locks.get(key)
            if file_lock and file_lock.locked():
                try:
                    file_lock.release()
                except RuntimeError:
                    pass
            self._owners.pop(key, None)
            self._timestamps.pop(key, None)

    def release_stale_locks(self, max_age: float = 30.0) -> int:
        released = 0
        with self._global_lock:
            now = time.time()
            stale_keys = [k for k, ts in self._timestamps.items() if now - ts > max_age]
            for key in stale_keys:
                file_lock = self._locks.get(key)
                if file_lock and file_lock.locked():
                    try:
                        file_lock.release()
                        released += 1
                    except RuntimeError:
                        pass
                self._owners.pop(key, None)
                self._timestamps.pop(key, None)
        return released

    def clear(self) -> None:
        with self._global_lock:
            for file_lock in self._locks.values():
                try:
                    file_lock.release()
                except RuntimeError:
                    pass
            self._locks.clear()
            self._owners.clear()
            self._timestamps.clear()


class EntryMetadata:
    """Metadata for a stored entry."""

    def __init__(self, key: str, size: int = 0, format: FileFormat = FileFormat.JSON):
        self.key: str = key
        self.size: int = size
        self.format: FileFormat = format
        self.created_at: float = time.time()
        self.updated_at: float = time.time()
        self.access_count: int = 0
        self.version: int = 1
        self.checksum: str = ""
        self.tags: List[str] = []
        self.ttl: Optional[float] = None
        self.compressed: bool = False

    def touch(self) -> None:
        self.updated_at = time.time()
        self.access_count += 1

    def increment_version(self) -> None:
        self.version += 1

    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return (time.time() - self.updated_at) > self.ttl

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "size": self.size,
            "format": self.format.value,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "updated_at": datetime.fromtimestamp(self.updated_at).isoformat(),
            "access_count": self.access_count,
            "version": self.version,
            "checksum": self.checksum,
            "tags": self.tags,
            "ttl": self.ttl,
            "compressed": self.compressed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntryMetadata":
        meta = cls(data["key"])
        meta.size = data.get("size", 0)
        meta.format = FileFormat(data.get("format", "json"))
        meta.created_at = datetime.fromisoformat(data["created_at"]).timestamp() if isinstance(data.get("created_at"), str) else data.get("created_at", meta.created_at)
        meta.updated_at = datetime.fromisoformat(data["updated_at"]).timestamp() if isinstance(data.get("updated_at"), str) else data.get("updated_at", meta.updated_at)
        meta.access_count = data.get("access_count", 0)
        meta.version = data.get("version", 1)
        meta.checksum = data.get("checksum", "")
        meta.tags = data.get("tags", [])
        meta.ttl = data.get("ttl")
        meta.compressed = data.get("compressed", False)
        return meta


class FileStore:
    """Generic file-based key-value store with atomic read/write, directory management, and concurrent access control."""

    def __init__(self, config: Optional[FileStoreConfig] = None):
        self.config = config or FileStoreConfig()
        self._base_path = Path(self.config.base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)
        self._lock_manager = FileLock(lock_timeout=self.config.lock_timeout) if self.config.enable_locking else None
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._metadata: Dict[str, EntryMetadata] = {}
        self._global_lock = threading.RLock()
        self._write_count: int = 0
        self._read_count: int = 0
        self._error_count: int = 0
        self._load_count: int = 0
        self._metadata_path = self._base_path / "_metadata.json"
        self._load_metadata()
        logger.info("FileStore initialized at %s (format: %s)", self.config.base_path, self.config.format.value)

    def _key_to_path(self, key: str) -> Path:
        hashed = hashlib.md5(key.encode()).hexdigest()
        parts = [hashed[i:i+2] for i in range(0, min(self.config.dir_depth * 2, len(hashed)), 2)]
        return self._base_path.joinpath(*parts) / f"{key}{self.config.file_extension}"

    def _ensure_dir(self, path: Path) -> None:
        if self.config.auto_create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)

    def _compute_checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:32]

    def _serialize(self, value: Any, fmt: FileFormat) -> bytes:
        if fmt == FileFormat.JSON:
            content = json.dumps(value, indent=2 if self.config.pretty_print else None, default=str, ensure_ascii=False)
            return content.encode(self.config.encoding)
        elif fmt == FileFormat.YAML:
            content = yaml.dump(value, default_flow_style=False, sort_keys=False)
            return content.encode(self.config.encoding)
        elif fmt == FileFormat.BINARY:
            if isinstance(value, bytes):
                return value
            if isinstance(value, str):
                return value.encode(self.config.encoding)
            return json.dumps(value, default=str).encode(self.config.encoding)
        elif fmt == FileFormat.TEXT:
            return str(value).encode(self.config.encoding)
        else:
            raise FileStoreError(f"Unsupported format: {fmt}")

    def _deserialize(self, data: bytes, fmt: FileFormat) -> Any:
        if fmt == FileFormat.JSON:
            return json.loads(data.decode(self.config.encoding))
        elif fmt == FileFormat.YAML:
            return yaml.safe_load(data.decode(self.config.encoding))
        elif fmt == FileFormat.BINARY:
            return data
        elif fmt == FileFormat.TEXT:
            return data.decode(self.config.encoding)
        else:
            raise FileStoreError(f"Unsupported format: {fmt}")

    def _atomic_write(self, path: Path, data: bytes) -> None:
        tmp_path = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
        try:
            tmp_path.write_bytes(data)
            if self.config.sync_on_write:
                pass
            shutil.move(str(tmp_path), str(path))
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def _acquire_lock(self, key: str) -> bool:
        if self._lock_manager:
            return self._lock_manager.acquire(key)
        return True

    def _release_lock(self, key: str) -> None:
        if self._lock_manager:
            self._lock_manager.release(key)

    def _load_metadata(self) -> None:
        if self._metadata_path.exists():
            try:
                data = json.loads(self._metadata_path.read_text(encoding="utf-8"))
                for key, meta_dict in data.items():
                    self._metadata[key] = EntryMetadata.from_dict(meta_dict)
                self._load_count += 1
                logger.debug("Loaded metadata for %d entries", len(self._metadata))
            except Exception as e:
                logger.warning("Failed to load metadata: %s", e)

    def _save_metadata(self) -> None:
        data = {key: meta.to_dict() for key, meta in self._metadata.items()}
        try:
            content = json.dumps(data, indent=2, default=str, ensure_ascii=False)
            self._metadata_path.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save metadata: %s", e)

    def put(self, key: str, value: Any, fmt: Optional[FileFormat] = None,
            overwrite: bool = True, ttl: Optional[float] = None,
            tags: Optional[List[str]] = None) -> None:
        self._global_lock.acquire()
        try:
            if not overwrite and self.exists(key):
                raise KeyExistsError(f"Key '{key}' already exists")
            if len(self._metadata) >= self.config.max_keys:
                raise FileStoreError(f"Max keys ({self.config.max_keys}) reached")
            effective_fmt = fmt or self.config.format
            data = self._serialize(value, effective_fmt)
            file_size = len(data)
            if file_size > self.config.max_file_size_mb * 1024 * 1024:
                raise FileStoreError(f"Data size {file_size} exceeds max file size {self.config.max_file_size_mb}MB")
            path = self._key_to_path(key)
            self._ensure_dir(path)
            if self.config.atomic_writes:
                self._atomic_write(path, data)
            else:
                path.write_bytes(data)
            checksum = self._compute_checksum(data)
            meta = self._metadata.get(key)
            if meta:
                meta.size = file_size
                meta.format = effective_fmt
                meta.updated_at = time.time()
                meta.increment_version()
                meta.checksum = checksum
                meta.compressed = self.config.compression_enabled
                if ttl is not None:
                    meta.ttl = ttl
                if tags is not None:
                    meta.tags = tags
            else:
                meta = EntryMetadata(key, file_size, effective_fmt)
                meta.checksum = checksum
                meta.compressed = self.config.compression_enabled
                if ttl is not None:
                    meta.ttl = ttl
                if tags is not None:
                    meta.tags = tags
                self._metadata[key] = meta
            meta.touch()
            if self.config.cache_enabled:
                self._cache[key] = (value, time.time())
            if len(self._cache) > self.config.cache_max_size:
                self._evict_cache()
            self._write_count += 1
            self._save_metadata()
        finally:
            self._global_lock.release()
        logger.debug("Stored key '%s' (fmt=%s, size=%d)", key, effective_fmt.value, len(data))

    def get(self, key: str, default: Any = None, fmt: Optional[FileFormat] = None) -> Any:
        if self.config.cache_enabled:
            cached = self._cache.get(key)
            if cached:
                value, timestamp = cached
                if time.time() - timestamp < self.config.cache_ttl:
                    meta = self._metadata.get(key)
                    if meta and not meta.is_expired():
                        self._read_count += 1
                        return value
        if not self._acquire_lock(key):
            raise FileLockError(f"Could not acquire lock for key '{key}'")
        try:
            path = self._key_to_path(key)
            if not path.exists():
                return default
            if not path.is_file():
                return default
            meta = self._metadata.get(key)
            if meta and meta.is_expired():
                self.delete(key)
                return default
            data = path.read_bytes()
            if meta:
                expected_checksum = meta.checksum
                if expected_checksum and self._compute_checksum(data) != expected_checksum:
                    raise CorruptedDataError(f"Checksum mismatch for key '{key}'")
            effective_fmt = fmt or (meta.format if meta else self.config.format)
            try:
                value = self._deserialize(data, effective_fmt)
            except Exception as e:
                raise CorruptedDataError(f"Failed to deserialize key '{key}': {e}") from e
            if meta:
                meta.touch()
            if self.config.cache_enabled:
                self._cache[key] = (value, time.time())
                if len(self._cache) > self.config.cache_max_size:
                    self._evict_cache()
            self._read_count += 1
            return value
        except KeyNotFoundError:
            return default
        finally:
            self._release_lock(key)

    def get_binary(self, key: str, default: Optional[bytes] = None) -> Optional[bytes]:
        return self.get(key, default=default, fmt=FileFormat.BINARY)

    def get_text(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self.get(key, default=default, fmt=FileFormat.TEXT)

    def get_json(self, key: str, default: Optional[Any] = None) -> Any:
        return self.get(key, default=default, fmt=FileFormat.JSON)

    def get_yaml(self, key: str, default: Optional[Any] = None) -> Any:
        return self.get(key, default=default, fmt=FileFormat.YAML)

    def exists(self, key: str) -> bool:
        meta = self._metadata.get(key)
        if meta and meta.is_expired():
            return False
        path = self._key_to_path(key)
        return path.exists() and path.is_file()

    def delete(self, key: str) -> bool:
        self._global_lock.acquire()
        try:
            path = self._key_to_path(key)
            if not path.exists():
                return False
            path.unlink(missing_ok=True)
            self._metadata.pop(key, None)
            self._cache.pop(key, None)
            self._write_count += 1
            self._save_metadata()
            logger.debug("Deleted key '%s'", key)
            return True
        except OSError as e:
            self._error_count += 1
            raise FileStoreError(f"Failed to delete key '{key}': {e}") from e
        finally:
            self._global_lock.release()

    def delete_many(self, keys: List[str]) -> int:
        deleted = 0
        for key in keys:
            try:
                if self.delete(key):
                    deleted += 1
            except Exception as e:
                logger.warning("Failed to delete key '%s': %s", key, e)
        return deleted

    def list_keys(self, prefix: Optional[str] = None, suffix: Optional[str] = None,
                  limit: Optional[int] = None, offset: int = 0) -> List[str]:
        keys = list(self._metadata.keys())
        if prefix:
            keys = [k for k in keys if k.startswith(prefix)]
        if suffix:
            keys = [k for k in keys if k.endswith(suffix)]
        keys.sort()
        if offset:
            keys = keys[offset:]
        if limit:
            keys = keys[:limit]
        return keys

    def list_by_tag(self, tag: str) -> List[str]:
        return [key for key, meta in self._metadata.items() if tag in meta.tags]

    def get_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        meta = self._metadata.get(key)
        if meta:
            return meta.to_dict()
        return None

    def get_size(self, key: str) -> Optional[int]:
        meta = self._metadata.get(key)
        if meta:
            return meta.size
        path = self._key_to_path(key)
        if path.exists():
            return path.stat().st_size
        return None

    def update_ttl(self, key: str, ttl: float) -> bool:
        meta = self._metadata.get(key)
        if meta:
            meta.ttl = ttl
            self._save_metadata()
            return True
        return False

    def update_tags(self, key: str, tags: List[str]) -> bool:
        meta = self._metadata.get(key)
        if meta:
            meta.tags = tags
            self._save_metadata()
            return True
        return False

    def add_tag(self, key: str, tag: str) -> bool:
        meta = self._metadata.get(key)
        if meta:
            if tag not in meta.tags:
                meta.tags.append(tag)
                self._save_metadata()
            return True
        return False

    def remove_tag(self, key: str, tag: str) -> bool:
        meta = self._metadata.get(key)
        if meta and tag in meta.tags:
            meta.tags.remove(tag)
            self._save_metadata()
            return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        total_size = 0
        file_count = 0
        for key, meta in self._metadata.items():
            total_size += meta.size
            file_count += 1
        format_counts: Dict[str, int] = {}
        for meta in self._metadata.values():
            fmt = meta.format.value
            format_counts[fmt] = format_counts.get(fmt, 0) + 1
        expired = sum(1 for meta in self._metadata.values() if meta.is_expired())
        return {
            "total_keys": len(self._metadata),
            "total_files": file_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "read_count": self._read_count,
            "write_count": self._write_count,
            "error_count": self._error_count,
            "cache_size": len(self._cache),
            "max_keys": self.config.max_keys,
            "format_counts": format_counts,
            "expired_entries": expired,
            "base_path": str(self._base_path),
            "format": self.config.format.value,
        }

    def _evict_cache(self) -> None:
        if len(self._cache) <= self.config.cache_max_size:
            return
        sorted_items = sorted(self._cache.items(), key=lambda x: x[1][1])
        to_remove = len(self._cache) - self.config.cache_max_size
        for key, _ in sorted_items[:to_remove]:
            del self._cache[key]

    def clear_cache(self) -> None:
        self._cache.clear()

    def clear(self) -> int:
        self._global_lock.acquire()
        try:
            count = 0
            for key in list(self._metadata.keys()):
                path = self._key_to_path(key)
                if path.exists():
                    path.unlink(missing_ok=True)
                    count += 1
            self._metadata.clear()
            self._cache.clear()
            self._write_count = 0
            self._read_count = 0
            self._save_metadata()
            logger.info("Cleared store, removed %d files", count)
            return count
        finally:
            self._global_lock.release()

    def export_store(self, file_path: str, format: Optional[str] = None,
                     keys: Optional[List[str]] = None) -> int:
        export_path = Path(file_path)
        fmt = format or export_path.suffix.lstrip(".")
        export_keys = keys or self.list_keys()
        data = {}
        for key in export_keys:
            try:
                value = self.get(key)
                if value is not None:
                    data[key] = value
            except Exception as e:
                logger.warning("Failed to export key '%s': %s", key, e)
        try:
            if fmt == "json":
                content = json.dumps(data, indent=2, default=str, ensure_ascii=False)
            elif fmt in ("yaml", "yml"):
                content = yaml.dump(data, default_flow_style=False, sort_keys=False)
            else:
                content = json.dumps(data, indent=2, default=str, ensure_ascii=False)
            export_path.write_text(content, encoding="utf-8")
            logger.info("Exported %d keys to %s", len(data), file_path)
            return len(data)
        except Exception as e:
            raise FileStoreError(f"Export failed: {e}") from e

    def import_store(self, file_path: str, format: Optional[str] = None,
                     overwrite: bool = False) -> Tuple[int, int]:
        import_path = Path(file_path)
        if not import_path.exists():
            raise FileStoreError(f"Import file not found: {file_path}")
        fmt = format or import_path.suffix.lstrip(".")
        try:
            content = import_path.read_text(encoding="utf-8")
            if fmt == "json":
                data = json.loads(content)
            elif fmt in ("yaml", "yml"):
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)
            if not isinstance(data, dict):
                raise FileStoreError("Import data must be a dictionary of key-value pairs")
            success = 0
            errors = 0
            for key, value in data.items():
                try:
                    self.put(key, value, overwrite=overwrite)
                    success += 1
                except Exception as e:
                    errors += 1
                    logger.warning("Failed to import key '%s': %s", key, e)
            logger.info("Imported %d keys from %s (%d errors)", success, file_path, errors)
            return success, errors
        except Exception as e:
            raise FileStoreError(f"Import failed: {e}") from e

    def snapshot(self) -> Dict[str, Any]:
        data = {}
        for key in self.list_keys():
            try:
                value = self.get(key)
                if value is not None:
                    data[key] = value
            except Exception:
                pass
        return data

    def restore_snapshot(self, snapshot: Dict[str, Any], overwrite: bool = True) -> int:
        count = 0
        for key, value in snapshot.items():
            try:
                self.put(key, value, overwrite=overwrite)
                count += 1
            except Exception as e:
                logger.warning("Failed to restore key '%s': %s", key, e)
        return count

    def compact(self, remove_expired: bool = True) -> Dict[str, Any]:
        self._global_lock.acquire()
        try:
            before_count = len(self._metadata)
            before_size = sum(meta.size for meta in self._metadata.values())
            if remove_expired:
                expired_keys = [key for key, meta in self._metadata.items() if meta.is_expired()]
                for key in expired_keys:
                    self.delete(key)
            self._save_metadata()
            after_count = len(self._metadata)
            after_size = sum(meta.size for meta in self._metadata.values())
            return {
                "entries_before": before_count,
                "entries_after": after_count,
                "size_before": before_size,
                "size_after": after_size,
                "size_reduced": before_size - after_size,
                "expired_removed": len(expired_keys) if remove_expired else 0,
            }
        finally:
            self._global_lock.release()

    def close(self) -> None:
        self._global_lock.acquire()
        try:
            self._save_metadata()
            self._cache.clear()
            if self._lock_manager:
                self._lock_manager.clear()
            logger.info("FileStore closed")
        finally:
            self._global_lock.release()

    def __enter__(self) -> "FileStore":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __contains__(self, key: str) -> bool:
        return self.exists(key)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise KeyNotFoundError(f"Key '{key}' not found")
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        self.put(key, value, overwrite=True)

    def __delitem__(self, key: str) -> None:
        if not self.delete(key):
            raise KeyNotFoundError(f"Key '{key}' not found")

    def __len__(self) -> int:
        return len(self._metadata)

    def __iter__(self) -> Iterator[str]:
        return iter(self.list_keys())

    def __repr__(self) -> str:
        return f"FileStore(path={self.config.base_path}, keys={len(self._metadata)})"