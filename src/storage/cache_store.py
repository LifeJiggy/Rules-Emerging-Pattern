"""Persistent cache with filesystem backend supporting TTL expiration, LRU eviction, and cross-restart persistence."""

import base64
import copy
import hashlib
import json
import logging
import os
import pickle
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


class EvictionPolicy(str, Enum):
    LRU = "lru"
    FIFO = "fifo"
    TTL = "ttl"
    HYBRID = "hybrid"


class CacheError(Exception):
    pass


class CacheKeyError(CacheError):
    pass


class CacheCorruptionError(CacheError):
    pass


@dataclass
class CacheStoreConfig:
    cache_dir: str = "cache/store"
    max_entries: int = 10000
    max_size_mb: int = 500
    default_ttl: float = 300.0
    eviction_policy: EvictionPolicy = EvictionPolicy.LRU
    eviction_batch_size: int = 100
    persistence_enabled: bool = True
    persistence_interval: float = 60.0
    sync_on_write: bool = True
    compression_enabled: bool = False
    index_file: str = "_index.json"
    shard_count: int = 16
    shard_prefix_length: int = 2
    cache_key_prefix: str = ""
    auto_rebuild_index: bool = True
    max_value_size_mb: int = 10
    enable_async_persist: bool = False
    stats_window_size: int = 1000


class CacheEntry:
    """Single cache entry with metadata."""

    def __init__(self, key: str, value: Any, ttl: Optional[float] = None,
                 tags: Optional[List[str]] = None, size: int = 0):
        self.key: str = key
        self.value: Any = value
        self.created_at: float = time.time()
        self.updated_at: float = time.time()
        self.last_access: float = time.time()
        self.access_count: int = 0
        self.ttl: Optional[float] = ttl
        self.tags: List[str] = tags or []
        self.size: int = size
        self.version: int = 1
        self.hit_count: int = 0
        self.compressed: bool = False

    @property
    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return (time.time() - self.updated_at) > self.ttl

    @property
    def age(self) -> float:
        return time.time() - self.created_at

    @property
    def idle_time(self) -> float:
        return time.time() - self.last_access

    def touch(self) -> None:
        self.last_access = time.time()
        self.access_count += 1

    def record_hit(self) -> None:
        self.hit_count += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_access": self.last_access,
            "access_count": self.access_count,
            "ttl": self.ttl,
            "tags": self.tags,
            "size": self.size,
            "version": self.version,
            "hit_count": self.hit_count,
            "compressed": self.compressed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], value: Any) -> "CacheEntry":
        entry = cls(data["key"], value)
        entry.created_at = data.get("created_at", entry.created_at)
        entry.updated_at = data.get("updated_at", entry.updated_at)
        entry.last_access = data.get("last_access", entry.last_access)
        entry.access_count = data.get("access_count", 0)
        entry.ttl = data.get("ttl")
        entry.tags = data.get("tags", [])
        entry.size = data.get("size", 0)
        entry.version = data.get("version", 1)
        entry.hit_count = data.get("hit_count", 0)
        entry.compressed = data.get("compressed", False)
        return entry


class LRUOrderedDict(OrderedDict):
    """OrderedDict with LRU semantics."""

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)

    def peek(self, key, default=None):
        try:
            return super().__getitem__(key)
        except KeyError:
            return default


class CacheStore:
    """Persistent cache with filesystem backend, TTL-based expiration, LRU eviction, and restart persistence."""

    def __init__(self, config: Optional[CacheStoreConfig] = None):
        self.config = config or CacheStoreConfig()
        self._cache_dir = Path(self.config.cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._entries: LRUOrderedDict = LRUOrderedDict()
        self._index: Dict[str, Dict[str, Any]] = {}
        self._tags_index: Dict[str, Set[str]] = {}
        self._lock = threading.RLock()
        self._persist_timer: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._hit_count: int = 0
        self._miss_count: int = 0
        self._eviction_count: int = 0
        self._write_count: int = 0
        self._read_count: int = 0
        self._error_count: int = 0
        self._current_size: int = 0
        self._load_count: int = 0
        self._index_path = self._cache_dir / self.config.index_file
        self._last_persist_time: float = 0.0
        if self.config.persistence_enabled:
            self._load_persistent()
            if self.config.enable_async_persist:
                self._start_async_persist()
        logger.info("CacheStore initialized at %s (max=%d, ttl=%s, policy=%s)",
                     self.config.cache_dir, self.config.max_entries,
                     self.config.default_ttl, self.config.eviction_policy.value)

    def _shard_path(self, key: str) -> Path:
        hashed = hashlib.md5(key.encode()).hexdigest()
        shard = hashed[:self.config.shard_prefix_length]
        return self._cache_dir / shard

    def _entry_path(self, key: str) -> Path:
        shard_dir = self._shard_path(key)
        safe_key = base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")
        return shard_dir / f"{safe_key}.cache"

    def _serialize_value(self, value: Any) -> bytes:
        try:
            return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            raise CacheError(f"Failed to serialize value: {e}") from e

    def _deserialize_value(self, data: bytes) -> Any:
        try:
            return pickle.loads(data)
        except Exception as e:
            raise CacheCorruptionError(f"Failed to deserialize value: {e}") from e

    def _atomic_write(self, path: Path, data: bytes) -> None:
        tmp_path = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
        try:
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_bytes(data)
            if path.exists():
                path.unlink()
            shutil.move(str(tmp_path), str(path))
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def _write_entry_file(self, entry: CacheEntry) -> None:
        value_data = self._serialize_value(entry.value)
        meta = entry.to_dict()
        combined = {
            "_meta": meta,
            "_value_bytes": base64.b64encode(value_data).decode(),
        }
        content = json.dumps(combined, ensure_ascii=False)
        path = self._entry_path(entry.key)
        self._atomic_write(path, content.encode("utf-8"))

    def _read_entry_file(self, key: str) -> Optional[CacheEntry]:
        path = self._entry_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            meta_dict = data.get("_meta", {})
            value_bytes = base64.b64decode(data.get("_value_bytes", ""))
            value = self._deserialize_value(value_bytes)
            return CacheEntry.from_dict(meta_dict, value)
        except Exception as e:
            logger.warning("Failed to read cache entry '%s': %s", key, e)
            return None

    def _load_persistent(self) -> int:
        count = 0
        for shard_dir in self._cache_dir.iterdir():
            if not shard_dir.is_dir() or shard_dir.name.startswith("."):
                continue
            for cache_file in shard_dir.glob("*.cache"):
                key = self._decode_key_from_filename(cache_file.stem)
                if key is None:
                    continue
                try:
                    entry = self._read_entry_file(key)
                    if entry:
                        if entry.is_expired:
                            cache_file.unlink(missing_ok=True)
                            continue
                        self._entries[key] = entry
                        self._current_size += entry.size
                        for tag in entry.tags:
                            self._tags_index.setdefault(tag, set()).add(key)
                        count += 1
                except Exception as e:
                    logger.warning("Skipping corrupted cache file %s: %s", cache_file, e)
        if self.config.auto_rebuild_index:
            self._rebuild_index()
        self._load_count = count
        logger.info("Loaded %d entries from persistent cache", count)
        return count

    @staticmethod
    def _encode_key_for_filename(key: str) -> str:
        return base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")

    @staticmethod
    def _decode_key_from_filename(stem: str) -> Optional[str]:
        try:
            padding = 4 - (len(stem) % 4)
            if padding != 4:
                stem += "=" * padding
            return base64.urlsafe_b64decode(stem).decode()
        except Exception:
            return None

    def _rebuild_index(self) -> None:
        self._index.clear()
        for key, entry in self._entries.items():
            self._index[key] = entry.to_dict()

    def _enforce_limits(self) -> None:
        while len(self._entries) > self.config.max_entries:
            self._evict_one()
        while self._current_size > self.config.max_size_mb * 1024 * 1024:
            self._evict_one()

    def _evict_one(self) -> Optional[str]:
        if not self._entries:
            return None
        if self.config.eviction_policy == EvictionPolicy.LRU:
            key, entry = next(iter(self._entries.items()))
        elif self.config.eviction_policy == EvictionPolicy.FIFO:
            key, entry = next(iter(self._entries.items()))
        elif self.config.eviction_policy == EvictionPolicy.TTL:
            key = min(self._entries.keys(), key=lambda k: self._entries[k].updated_at + (self._entries[k].ttl or float("inf")))
            entry = self._entries[key]
        else:
            key, entry = next(iter(self._entries.items()))
        self._remove_entry(key)
        return key

    def _remove_entry(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry:
            self._current_size -= entry.size
            self._eviction_count += 1
            for tag in entry.tags:
                tag_set = self._tags_index.get(tag)
                if tag_set:
                    tag_set.discard(key)
                    if not tag_set:
                        del self._tags_index[tag]
            self._delete_entry_file(key)

    def _delete_entry_file(self, key: str) -> None:
        path = self._entry_path(key)
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            logger.warning("Failed to delete cache file %s: %s", path, e)

    def _start_async_persist(self) -> None:
        self._shutdown_event.clear()
        self._persist_timer = threading.Thread(
            target=self._async_persist_loop,
            name="cache-persist",
            daemon=True
        )
        self._persist_timer.start()

    def _async_persist_loop(self) -> None:
        while not self._shutdown_event.is_set():
            self._shutdown_event.wait(self.config.persistence_interval)
            if self._shutdown_event.is_set():
                break
            try:
                self.persist()
            except Exception as e:
                logger.error("Async persist failed: %s", e)

    def get(self, key: str, default: Any = None) -> Any:
        self._read_count += 1
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = self._read_entry_file(key)
                if entry is None:
                    self._miss_count += 1
                    return default
                if entry.is_expired:
                    self._remove_entry(key)
                    self._miss_count += 1
                    return default
                self._entries[key] = entry
                self._current_size += entry.size
            entry.touch()
            entry.record_hit()
            self._entries.move_to_end(key)
            self._hit_count += 1
            return entry.value

    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        results = {}
        for key in keys:
            value = self.get(key)
            if value is not None:
                results[key] = value
        return results

    def set(self, key: str, value: Any, ttl: Optional[float] = None,
            tags: Optional[List[str]] = None) -> None:
        with self._lock:
            value_bytes = self._serialize_value(value)
            size = len(value_bytes)
            max_bytes = self.config.max_value_size_mb * 1024 * 1024
            if size > max_bytes:
                raise CacheError(f"Value size {size} exceeds max {max_bytes}")
            effective_ttl = ttl if ttl is not None else self.config.default_ttl
            old_entry = self._entries.get(key)
            if old_entry:
                self._current_size -= old_entry.size
                for tag in old_entry.tags:
                    tag_set = self._tags_index.get(tag)
                    if tag_set:
                        tag_set.discard(key)
                        if not tag_set:
                            del self._tags_index[tag]
            entry = CacheEntry(key, value, effective_ttl, tags, size)
            self._entries[key] = entry
            self._current_size += size
            self._write_count += 1
            for tag in (tags or []):
                self._tags_index.setdefault(tag, set()).add(key)
            if self.config.sync_on_write:
                self._write_entry_file(entry)
            self._enforce_limits()
            logger.debug("Cache set: %s (ttl=%s, size=%d)", key, effective_ttl, size)

    def set_many(self, items: Dict[str, Any], ttl: Optional[float] = None,
                 tags: Optional[List[str]] = None) -> None:
        for key, value in items.items():
            self.set(key, value, ttl=ttl, tags=tags)

    def delete(self, key: str) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                if self._entry_path(key).exists():
                    self._delete_entry_file(key)
                    return True
                return False
            self._remove_entry(key)
            logger.debug("Cache delete: %s", key)
            return True

    def delete_many(self, keys: List[str]) -> int:
        deleted = 0
        for key in keys:
            if self.delete(key):
                deleted += 1
        return deleted

    def delete_by_tag(self, tag: str) -> int:
        with self._lock:
            keys = list(self._tags_index.get(tag, set()))
            for key in keys:
                self._remove_entry(key)
            return len(keys)

    def delete_expired(self) -> int:
        with self._lock:
            expired = [key for key, entry in self._entries.items() if entry.is_expired]
            for key in expired:
                self._remove_entry(key)
            return len(expired)

    def has(self, key: str) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry:
                if entry.is_expired:
                    self._remove_entry(key)
                    return False
                return True
            entry = self._read_entry_file(key)
            if entry and not entry.is_expired:
                return True
            return False

    def get_or_set(self, key: str, factory: Callable[[], Any],
                   ttl: Optional[float] = None) -> Any:
        value = self.get(key)
        if value is not None:
            return value
        value = factory()
        self.set(key, value, ttl=ttl)
        return value

    def get_ttl(self, key: str) -> Optional[float]:
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry.ttl is not None:
                remaining = entry.ttl - (time.time() - entry.updated_at)
                return max(0.0, remaining)
            return None

    def update_ttl(self, key: str, ttl: float) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry:
                entry.ttl = ttl
                if self.config.sync_on_write:
                    self._write_entry_file(entry)
                return True
            return False

    def get_tags(self, key: str) -> List[str]:
        with self._lock:
            entry = self._entries.get(key)
            if entry:
                return list(entry.tags)
            return []

    def add_tag(self, key: str, tag: str) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry and tag not in entry.tags:
                entry.tags.append(tag)
                self._tags_index.setdefault(tag, set()).add(key)
                if self.config.sync_on_write:
                    self._write_entry_file(entry)
                return True
            return False

    def remove_tag(self, key: str, tag: str) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry and tag in entry.tags:
                entry.tags.remove(tag)
                tag_set = self._tags_index.get(tag)
                if tag_set:
                    tag_set.discard(key)
                    if not tag_set:
                        del self._tags_index[tag]
                if self.config.sync_on_write:
                    self._write_entry_file(entry)
                return True
            return False

    def find_by_tag(self, tag: str) -> List[str]:
        with self._lock:
            return list(self._tags_index.get(tag, set()))

    def list_keys(self, prefix: Optional[str] = None, limit: Optional[int] = None,
                  offset: int = 0) -> List[str]:
        with self._lock:
            keys = list(self._entries.keys())
            if prefix:
                keys = [k for k in keys if k.startswith(prefix)]
            keys.sort()
            if offset:
                keys = keys[offset:]
            if limit:
                keys = keys[:limit]
            return keys

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            self._tags_index.clear()
            self._current_size = 0
            for shard_dir in self._cache_dir.iterdir():
                if shard_dir.is_dir() and not shard_dir.name.startswith("."):
                    for cache_file in shard_dir.glob("*.cache"):
                        cache_file.unlink(missing_ok=True)
            logger.info("Cache cleared, removed %d entries", count)
            return count

    def persist(self) -> None:
        with self._lock:
            count = 0
            for key, entry in list(self._entries.items()):
                try:
                    self._write_entry_file(entry)
                    count += 1
                except Exception as e:
                    logger.error("Failed to persist entry '%s': %s", key, e)
            self._last_persist_time = time.time()
            logger.debug("Persisted %d cache entries", count)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total_hits = self._hit_count
            total_misses = self._miss_count
            total_requests = total_hits + total_misses
            hit_rate = (total_hits / total_requests * 100) if total_requests > 0 else 0.0
            tag_count = len(self._tags_index)
            expired_count = sum(1 for e in self._entries.values() if e.is_expired)
            return {
                "entries": len(self._entries),
                "current_size_bytes": self._current_size,
                "current_size_mb": round(self._current_size / (1024 * 1024), 2),
                "max_entries": self.config.max_entries,
                "max_size_mb": self.config.max_size_mb,
                "usage_percent": round(len(self._entries) / self.config.max_entries * 100, 1) if self.config.max_entries else 0,
                "hit_count": total_hits,
                "miss_count": total_misses,
                "hit_rate": round(hit_rate, 2),
                "eviction_count": self._eviction_count,
                "write_count": self._write_count,
                "read_count": self._read_count,
                "error_count": self._error_count,
                "load_count": self._load_count,
                "tag_count": tag_count,
                "expired_entries": expired_count,
                "eviction_policy": self.config.eviction_policy.value,
                "default_ttl": self.config.default_ttl,
                "persistence_enabled": self.config.persistence_enabled,
                "cache_dir": str(self._cache_dir),
            }

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {key: entry.value for key, entry in self._entries.items()}

    def export_cache(self, file_path: str, format: Optional[str] = None,
                     keys: Optional[List[str]] = None) -> int:
        export_path = Path(file_path)
        fmt = format or export_path.suffix.lstrip(".")
        with self._lock:
            export_keys = keys or list(self._entries.keys())
            data = {}
            for key in export_keys:
                entry = self._entries.get(key)
                if entry:
                    data[key] = entry.value
        try:
            if fmt == "json":
                content = json.dumps(data, indent=2, default=str, ensure_ascii=False)
            elif fmt in ("yaml", "yml"):
                content = yaml.dump(data, default_flow_style=False, sort_keys=False)
            else:
                content = json.dumps(data, indent=2, default=str, ensure_ascii=False)
            export_path.write_text(content, encoding="utf-8")
            logger.info("Exported %d cache entries to %s", len(data), file_path)
            return len(data)
        except Exception as e:
            raise CacheError(f"Export failed: {e}") from e

    def import_cache(self, file_path: str, format: Optional[str] = None,
                     overwrite: bool = True, ttl: Optional[float] = None) -> Tuple[int, int]:
        import_path = Path(file_path)
        if not import_path.exists():
            raise CacheError(f"Import file not found: {file_path}")
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
                raise CacheError("Import data must be a dictionary")
            success = 0
            errors = 0
            for key, value in data.items():
                try:
                    if overwrite or not self.has(key):
                        self.set(key, value, ttl=ttl)
                        success += 1
                    else:
                        errors += 1
                except Exception as e:
                    errors += 1
                    logger.warning("Import failed for key '%s': %s", key, e)
            logger.info("Imported %d entries from %s (%d errors)", success, file_path, errors)
            return success, errors
        except Exception as e:
            raise CacheError(f"Import failed: {e}") from e

    def warmup(self, data: Dict[str, Any], ttl: Optional[float] = None) -> int:
        count = 0
        for key, value in data.items():
            try:
                self.set(key, value, ttl=ttl)
                count += 1
            except Exception as e:
                logger.warning("Warmup failed for key '%s': %s", key, e)
        logger.info("Cache warmed up with %d entries", count)
        return count

    def touch(self, key: str) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry:
                entry.touch()
                if self.config.sync_on_write:
                    self._write_entry_file(entry)
                return True
            return False

    def close(self) -> None:
        self._shutdown_event.set()
        if self._persist_timer and self._persist_timer.is_alive():
            self._persist_timer.join(timeout=5)
        if self.config.persistence_enabled:
            self.persist()
        with self._lock:
            self._entries.clear()
            self._tags_index.clear()
        logger.info("CacheStore closed")

    def __enter__(self) -> "CacheStore":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise CacheKeyError(f"Key '{key}' not found in cache")
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        if not self.delete(key):
            raise CacheKeyError(f"Key '{key}' not found in cache")

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(list(self._entries.keys()))

    def __repr__(self) -> str:
        return f"CacheStore(dir={self.config.cache_dir}, entries={len(self._entries)}, policy={self.config.eviction_policy.value})"