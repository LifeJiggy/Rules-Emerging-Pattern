"""Production-grade cache manager with TTL, LRU eviction, statistics, wildcard invalidation, and config-driven backend selection."""

import time
import threading
import logging
import heapq
import fnmatch
import weakref
import json
import os
import pickle
import tempfile
import hashlib
from typing import Any, Callable, Optional, Union, List, Dict, Tuple, Set, Iterator
from dataclasses import dataclass, field
from collections import OrderedDict, defaultdict
from enum import Enum, auto
from pathlib import Path

logger = logging.getLogger(__name__)


class EvictionPolicy(Enum):
    LRU = auto()
    FIFO = auto()
    TTL = auto()
    NONE = auto()


class CacheBackend(Enum):
    MEMORY = auto()
    DISK = auto()
    HYBRID = auto()


@dataclass
class CacheConfig:
    default_ttl: float = 300.0
    max_size: int = 10000
    max_memory_mb: float = 512.0
    eviction_policy: EvictionPolicy = EvictionPolicy.LRU
    backend: CacheBackend = CacheBackend.MEMORY
    cleanup_interval: float = 60.0
    disk_cache_path: Optional[str] = None
    disk_cache_max_mb: float = 2048.0
    enable_stats: bool = True
    serialization_protocol: int = pickle.HIGHEST_PROTOCOL
    key_max_length: int = 1024
    value_max_size_bytes: int = 50 * 1024 * 1024
    logger_name: str = "cache_manager"


@dataclass
class CacheEntry:
    key: str
    value: Any
    expiry: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    access_count: int = 0
    size_bytes: int = 0

    def is_expired(self) -> bool:
        if self.expiry is None:
            return False
        return time.time() > self.expiry

    def touch(self):
        self.accessed_at = time.time()
        self.access_count += 1

    def ttl_remaining(self) -> Optional[float]:
        if self.expiry is None:
            return None
        remaining = self.expiry - time.time()
        return max(0.0, remaining)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "expiry": self.expiry,
            "created_at": self.created_at,
            "accessed_at": self.accessed_at,
            "access_count": self.access_count,
            "size_bytes": self.size_bytes,
            "ttl_remaining": self.ttl_remaining(),
            "is_expired": self.is_expired(),
        }


class CacheStats:
    def __init__(self):
        self.hits: int = 0
        self.misses: int = 0
        self.evictions: int = 0
        self.expirations: int = 0
        self.sets: int = 0
        self.deletes: int = 0
        self.clears: int = 0
        self._lock = threading.RLock()

    def record_hit(self):
        with self._lock:
            self.hits += 1

    def record_miss(self):
        with self._lock:
            self.misses += 1

    def record_eviction(self):
        with self._lock:
            self.evictions += 1

    def record_expiration(self):
        with self._lock:
            self.expirations += 1

    def record_set(self):
        with self._lock:
            self.sets += 1

    def record_delete(self):
        with self._lock:
            self.deletes += 1

    def record_clear(self):
        with self._lock:
            self.clears += 1

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    @property
    def total_ops(self) -> int:
        return self.hits + self.misses + self.sets + self.deletes

    def reset(self):
        with self._lock:
            self.hits = 0
            self.misses = 0
            self.evictions = 0
            self.expirations = 0
            self.sets = 0
            self.deletes = 0
            self.clears = 0

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "expirations": self.expirations,
                "sets": self.sets,
                "deletes": self.deletes,
                "clears": self.clears,
                "hit_rate": self.hit_rate,
                "total_ops": self.total_ops,
            }


class CacheManager:
    """Thread-safe cache manager with TTL, LRU eviction, wildcard invalidation, and config-driven backends."""

    def __init__(self, config: Optional[CacheConfig] = None):
        self.config = config or CacheConfig()
        self._store: Dict[str, CacheEntry] = OrderedDict()
        self._store_lock = threading.RLock()
        self._stats = CacheStats()
        self._cleanup_event = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._disk_path: Optional[Path] = None
        self._ttl_heap: List[Tuple[float, str]] = []
        self._listeners: Dict[str, List[Callable]] = defaultdict(list)
        self._shutdown_flag = threading.Event()

        if self.config.backend in (CacheBackend.DISK, CacheBackend.HYBRID):
            self._init_disk_backend()

        if self.config.cleanup_interval > 0:
            self._start_cleanup_thread()

    def _init_disk_backend(self):
        if self.config.disk_cache_path:
            self._disk_path = Path(self.config.disk_cache_path)
        else:
            self._disk_path = Path(tempfile.gettempdir()) / "cache_manager" / "disk_cache"
        self._disk_path.mkdir(parents=True, exist_ok=True)
        self._disk_index_path = self._disk_path / "_index.json"
        self._disk_index: Dict[str, float] = {}
        self._load_disk_index()
        logger.info("Disk cache initialized at %s", self._disk_path)

    def _load_disk_index(self):
        if self._disk_index_path and self._disk_index_path.exists():
            try:
                data = json.loads(self._disk_index_path.read_text(encoding="utf-8"))
                self._disk_index = {k: v for k, v in data.items() if v > time.time() or v == 0}
            except Exception as e:
                logger.warning("Failed to load disk index: %s", e)
                self._disk_index = {}

    def _save_disk_index(self):
        if self._disk_index_path:
            try:
                self._disk_index_path.write_text(
                    json.dumps(self._disk_index, indent=2), encoding="utf-8"
                )
            except Exception as e:
                logger.warning("Failed to save disk index: %s", e)

    def _disk_path_for(self, key: str) -> Path:
        hashed = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._disk_path / f"{hashed}.cache" if self._disk_path else Path()

    def get(self, key: str, default: Any = None) -> Any:
        if not isinstance(key, str) or len(key) > self.config.key_max_length:
            return default
        entry = self._get_from_memory(key)
        if entry is not None:
            if entry.is_expired():
                self._delete_from_memory(key)
                self._stats.record_miss()
                return default
            entry.touch()
            self._stats.record_hit()
            return entry.value
        if self.config.backend in (CacheBackend.DISK, CacheBackend.HYBRID):
            value = self._get_from_disk(key)
            if value is not None:
                self._stats.record_hit()
                return value
        self._stats.record_miss()
        return default

    def _get_from_memory(self, key: str) -> Optional[CacheEntry]:
        with self._store_lock:
            return self._store.get(key)

    def _delete_from_memory(self, key: str):
        with self._store_lock:
            self._store.pop(key, None)

    def _get_from_disk(self, key: str) -> Any:
        if not self._disk_path:
            return None
        expiry = self._disk_index.get(key)
        if expiry is not None and 0 < expiry < time.time():
            self._disk_index.pop(key, None)
            disk_path = self._disk_path_for(key)
            if disk_path.exists():
                disk_path.unlink(missing_ok=True)
            return None
        disk_path = self._disk_path_for(key)
        if disk_path.exists():
            try:
                data = disk_path.read_bytes()
                return pickle.loads(data)
            except Exception as e:
                logger.warning("Failed to read disk cache for '%s': %s", key, e)
                disk_path.unlink(missing_ok=True)
        return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        if not isinstance(key, str) or len(key) > self.config.key_max_length:
            raise ValueError(f"Key must be a string with max length {self.config.key_max_length}")
        actual_ttl = ttl if ttl is not None else self.config.default_ttl
        expiry = time.time() + actual_ttl if actual_ttl > 0 else None
        size = self._estimate_size(value)
        entry = CacheEntry(key=key, value=value, expiry=expiry, size_bytes=size)
        with self._store_lock:
            self._enforce_limits()
            self._store[key] = entry
            if expiry is not None:
                heapq.heappush(self._ttl_heap, (expiry, key))
            self._store.move_to_end(key)
        self._stats.record_set()
        self._notify("set", key, value)

    def _estimate_size(self, value: Any) -> int:
        try:
            return len(pickle.dumps(value, protocol=self.config.serialization_protocol))
        except Exception:
            return 1024

    def has(self, key: str) -> bool:
        entry = self._get_from_memory(key)
        if entry is not None:
            if entry.is_expired():
                self._delete_from_memory(key)
                self._stats.record_expiration()
                return False
            return True
        if self.config.backend in (CacheBackend.DISK, CacheBackend.HYBRID):
            return key in self._disk_index
        return False

    def delete(self, key: str) -> bool:
        removed = False
        with self._store_lock:
            if key in self._store:
                del self._store[key]
                removed = True
        if self.config.backend in (CacheBackend.DISK, CacheBackend.HYBRID):
            disk_path = self._disk_path_for(key)
            if disk_path.exists():
                disk_path.unlink(missing_ok=True)
            self._disk_index.pop(key, None)
            removed = True
        if removed:
            self._stats.record_delete()
            self._notify("delete", key, None)
        return removed

    def clear(self) -> None:
        with self._store_lock:
            self._store.clear()
            self._ttl_heap.clear()
        if self._disk_path and self._disk_path.exists():
            for f in self._disk_path.iterdir():
                if f.suffix == ".cache":
                    f.unlink(missing_ok=True)
            self._disk_index.clear()
            self._save_disk_index()
        self._stats.record_clear()
        self._notify("clear", "*", None)
        logger.info("Cache cleared")

    def get_or_compute(self, key: str, factory_func: Callable[[], Any], ttl: Optional[float] = None) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory_func()
        self.set(key, value, ttl)
        return value

    def invalidate_pattern(self, pattern: str) -> int:
        count = 0
        with self._store_lock:
            keys_to_delete = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
            for key in keys_to_delete:
                del self._store[key]
                count += 1
        if self.config.backend in (CacheBackend.DISK, CacheBackend.HYBRID):
            disk_keys = [k for k in self._disk_index if fnmatch.fnmatch(k, pattern)]
            for key in disk_keys:
                disk_path = self._disk_path_for(key)
                if disk_path.exists():
                    disk_path.unlink(missing_ok=True)
                del self._disk_index[key]
                count += 1
        if count > 0:
            logger.info("Invalidated %d keys matching pattern '%s'", count, pattern)
            self._notify("invalidate", pattern, None)
        return count

    def touch(self, key: str, ttl: Optional[float] = None) -> bool:
        with self._store_lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            entry.touch()
            if ttl is not None:
                entry.expiry = time.time() + ttl if ttl > 0 else None
                if entry.expiry is not None:
                    heapq.heappush(self._ttl_heap, (entry.expiry, key))
            return True

    def get_with_ttl(self, key: str) -> Tuple[Optional[Any], Optional[float]]:
        entry = self._get_from_memory(key)
        if entry is None:
            return None, None
        if entry.is_expired():
            self._delete_from_memory(key)
            self._stats.record_expiration()
            return None, None
        entry.touch()
        self._stats.record_hit()
        return entry.value, entry.ttl_remaining()

    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        result = {}
        for key in keys:
            value = self.get(key)
            if value is not None:
                result[key] = value
        return result

    def set_many(self, mapping: Dict[str, Any], ttl: Optional[float] = None):
        for key, value in mapping.items():
            self.set(key, value, ttl)

    def delete_many(self, keys: List[str]) -> int:
        count = 0
        for key in keys:
            if self.delete(key):
                count += 1
        return count

    def _enforce_limits(self):
        while len(self._store) >= self.config.max_size:
            self._evict_one()

    def _evict_one(self):
        if not self._store:
            return
        policy = self.config.eviction_policy
        if policy == EvictionPolicy.LRU:
            self._store.popitem(last=False)
        elif policy == EvictionPolicy.FIFO:
            self._store.popitem(last=False)
        elif policy == EvictionPolicy.TTL:
            self._evict_ttl()
        elif policy == EvictionPolicy.NONE:
            return
        self._stats.record_eviction()

    def _evict_ttl(self):
        now = time.time()
        while self._ttl_heap:
            expiry, key = self._ttl_heap[0]
            if expiry <= now:
                heapq.heappop(self._ttl_heap)
                self._store.pop(key, None)
                return
            break
        self._store.popitem(last=False)

    def _start_cleanup_thread(self):
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            return
        self._shutdown_flag.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="cache-cleanup",
            daemon=True
        )
        self._cleanup_thread.start()
        logger.debug("Cleanup thread started (interval=%ss)", self.config.cleanup_interval)

    def _cleanup_loop(self):
        while not self._shutdown_flag.is_set():
            self._shutdown_flag.wait(self.config.cleanup_interval)
            if self._shutdown_flag.is_set():
                break
            try:
                self._run_cleanup()
            except Exception as e:
                logger.error("Cache cleanup error: %s", e)

    def _run_cleanup(self):
        now = time.time()
        expired_keys = []
        with self._store_lock:
            while self._ttl_heap and self._ttl_heap[0][0] <= now:
                expiry, key = heapq.heappop(self._ttl_heap)
                entry = self._store.get(key)
                if entry and entry.is_expired():
                    del self._store[key]
                    expired_keys.append(key)
                    self._stats.record_expiration()
        if self.config.backend in (CacheBackend.DISK, CacheBackend.HYBRID):
            expired_disk = [k for k, v in self._disk_index.items() if 0 < v < now]
            for key in expired_disk:
                disk_path = self._disk_path_for(key)
                if disk_path.exists():
                    disk_path.unlink(missing_ok=True)
                del self._disk_index[key]
            if expired_disk:
                self._save_disk_index()
        if expired_keys:
            logger.debug("Cleaned up %d expired entries", len(expired_keys))

    @property
    def size(self) -> int:
        with self._store_lock:
            return len(self._store)

    @property
    def hit_rate(self) -> float:
        return self._stats.hit_rate

    def keys(self) -> List[str]:
        with self._store_lock:
            return list(self._store.keys())

    def values(self) -> List[Any]:
        with self._store_lock:
            return [e.value for e in self._store.values() if not e.is_expired()]

    def items(self) -> List[Tuple[str, Any]]:
        with self._store_lock:
            return [(k, e.value) for k, e in self._store.items() if not e.is_expired()]

    def get_stats(self) -> Dict[str, Any]:
        stats = self._stats.snapshot()
        stats["size"] = self.size
        stats["max_size"] = self.config.max_size
        stats["config"] = {
            "default_ttl": self.config.default_ttl,
            "eviction_policy": self.config.eviction_policy.name,
            "backend": self.config.backend.name,
            "cleanup_interval": self.config.cleanup_interval,
        }
        return stats

    def get_entry_info(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self._get_from_memory(key)
        if entry is None:
            return None
        return entry.to_dict()

    def get_oldest(self) -> Optional[Tuple[str, Any]]:
        with self._store_lock:
            if not self._store:
                return None
            key, entry = next(iter(self._store.items()))
            return (key, entry.value)

    def get_newest(self) -> Optional[Tuple[str, Any]]:
        with self._store_lock:
            if not self._store:
                return None
            key, entry = self._store.popitem(last=True)
            self._store[key] = entry
            return (key, entry.value)

    def pop(self, key: str, default: Any = None) -> Any:
        value = self.get(key)
        if value is not None:
            self.delete(key)
            return value
        return default

    def update_ttl(self, key: str, ttl: float) -> bool:
        return self.touch(key, ttl)

    def contains(self, key: str) -> bool:
        return self.has(key)

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any):
        self.set(key, value)

    def __delitem__(self, key: str):
        if not self.delete(key):
            raise KeyError(key)

    def __len__(self) -> int:
        return self.size

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __repr__(self) -> str:
        return f"CacheManager(size={self.size}/{self.config.max_size}, hits={self._stats.hits}, misses={self._stats.misses})"

    def subscribe(self, event: str, callback: Callable):
        self._listeners[event].append(callback)

    def unsubscribe(self, event: str, callback: Callable):
        self._listeners[event] = [cb for cb in self._listeners[event] if cb != callback]

    def _notify(self, event: str, key: str, value: Any):
        for cb in self._listeners.get(event, []):
            try:
                cb(event, key, value)
            except Exception as e:
                logger.error("Listener error for event '%s': %s", event, e)

    def persist(self, path: Optional[Union[str, Path]] = None) -> None:
        if path is None:
            path = Path(tempfile.gettempdir()) / "cache_manager" / "snapshot.pkl"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {}
        with self._store_lock:
            for key, entry in self._store.items():
                if not entry.is_expired():
                    snapshot[key] = {
                        "value": entry.value,
                        "expiry": entry.expiry,
                        "created_at": entry.created_at,
                    }
        path.write_bytes(pickle.dumps(snapshot, protocol=self.config.serialization_protocol))
        logger.info("Cache persisted to %s (%d entries)", path, len(snapshot))

    def restore(self, path: Optional[Union[str, Path]] = None) -> int:
        if path is None:
            path = Path(tempfile.gettempdir()) / "cache_manager" / "snapshot.pkl"
        path = Path(path)
        if not path.exists():
            logger.warning("No cache snapshot found at %s", path)
            return 0
        snapshot = pickle.loads(path.read_bytes())
        count = 0
        with self._store_lock:
            for key, data in snapshot.items():
                expiry = data.get("expiry")
                if expiry is not None and expiry <= time.time():
                    continue
                entry = CacheEntry(
                    key=key,
                    value=data["value"],
                    expiry=expiry,
                    created_at=data.get("created_at", time.time()),
                )
                self._store[key] = entry
                if expiry is not None:
                    heapq.heappush(self._ttl_heap, (expiry, key))
                count += 1
        logger.info("Restored %d entries from %s", count, path)
        return count

    def set_config(self, config: CacheConfig):
        old_interval = self.config.cleanup_interval
        self.config = config
        if config.cleanup_interval != old_interval and config.cleanup_interval > 0:
            self._start_cleanup_thread()

    def update_config(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                logger.warning("Unknown config key: %s", key)
        if "cleanup_interval" in kwargs and kwargs["cleanup_interval"] > 0:
            self._start_cleanup_thread()

    def reset_stats(self):
        self._stats.reset()

    def reset(self):
        self.clear()
        self._stats.reset()
        logger.info("Cache fully reset")

    def close(self):
        self._shutdown_flag.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)
        if self.config.backend in (CacheBackend.DISK, CacheBackend.HYBRID):
            self._save_disk_index()
        logger.info("Cache manager shut down")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_or_compute_many(self, keys: List[str], factory_map: Dict[str, Callable],
                            ttl: Optional[float] = None) -> Dict[str, Any]:
        result = {}
        compute_keys = []
        for key in keys:
            val = self.get(key)
            if val is not None:
                result[key] = val
            else:
                compute_keys.append(key)
        for key in compute_keys:
            fn = factory_map.get(key)
            if fn:
                val = fn()
                self.set(key, val, ttl)
                result[key] = val
        return result

    def compute_if_absent(self, key: str, factory_func: Callable[[], Any],
                          ttl: Optional[float] = None) -> Any:
        return self.get_or_compute(key, factory_func, ttl)

    def compute_if_present(self, key: str, remapping_func: Callable[[Any], Any],
                           ttl: Optional[float] = None) -> Optional[Any]:
        value = self.get(key)
        if value is None:
            return None
        new_value = remapping_func(value)
        if new_value is not None:
            self.set(key, new_value, ttl)
        else:
            self.delete(key)
        return new_value

    def get_stale(self, max_age: float) -> List[Tuple[str, CacheEntry]]:
        now = time.time()
        stale = []
        with self._store_lock:
            for key, entry in self._store.items():
                age = now - entry.created_at
                if age > max_age:
                    stale.append((key, entry))
        return stale

    def rekey(self, old_key: str, new_key: str) -> bool:
        entry = self._get_from_memory(old_key)
        if entry is None:
            return False
        if entry.is_expired():
            return False
        with self._store_lock:
            self._store[new_key] = entry
            del self._store[old_key]
        return True

    def get_batch(self, keys: List[str], default: Any = None) -> List[Any]:
        return [self.get(k, default) for k in keys]
