"""Rule cache with TTL, LRU eviction, tier-based invalidation, and statistics."""

import logging
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class EvictionPolicy(Enum):
    LRU = "lru"
    FIFO = "fifo"
    TTL = "ttl"


@dataclass
class CacheEntry:
    rule_id: str
    rule: Any
    created_at: float = 0.0
    expires_at: float = 0.0
    last_access: float = 0.0
    access_count: int = 0
    tier: Optional[str] = None
    size_bytes: int = 0


@dataclass
class CacheConfig:
    max_size: int = 10000
    default_ttl: float = 300.0
    eviction_policy: EvictionPolicy = EvictionPolicy.LRU
    enable_stats: bool = True
    warm_on_start: bool = False
    warm_provider: Optional[Callable[[], Dict[str, Any]]] = None
    memory_limit_mb: float = 512.0
    tier_ttl_overrides: Dict[str, float] = field(default_factory=dict)
    cleanup_interval: float = 60.0
    max_entry_size_bytes: int = 1048576


class RuleCache:
    """In-memory rule cache with TTL, LRU eviction, and tier-based invalidation."""

    def __init__(self, config: Optional[CacheConfig] = None) -> None:
        self._config = config or CacheConfig()
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._tier_index: Dict[str, Set[str]] = {}
        self._lock = threading.RLock()
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0
        self._total_inserts: int = 0
        self._total_deletes: int = 0
        self._memory_usage: int = 0
        self._last_cleanup: float = time.time()
        self._start_time: float = time.time()
        self._running = True
        self._cleanup_thread: Optional[threading.Thread] = None
        if self._config.cleanup_interval > 0:
            self._start_cleanup_thread()
        if self._config.warm_on_start and self._config.warm_provider is not None:
            self.warm()

    def _start_cleanup_thread(self) -> None:
        def _cleanup_loop() -> None:
            while self._running:
                time.sleep(self._config.cleanup_interval)
                try:
                    self._evict_expired()
                except Exception as exc:
                    logger.error("Cleanup error: %s", exc)

        self._cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def stop(self) -> None:
        """Stop the background cleanup thread."""
        self._running = False

    def _evict_expired(self) -> int:
        now = time.time()
        expired: List[str] = []
        with self._lock:
            for rule_id, entry in self._cache.items():
                if entry.expires_at > 0 and now >= entry.expires_at:
                    expired.append(rule_id)
            for rule_id in expired:
                self._remove_entry(rule_id)
        if expired:
            logger.debug("Evicted %d expired entries", len(expired))
        return len(expired)

    def _remove_entry(self, rule_id: str) -> None:
        entry = self._cache.pop(rule_id, None)
        if entry is None:
            return
        self._memory_usage -= entry.size_bytes
        if entry.tier and entry.tier in self._tier_index:
            self._tier_index[entry.tier].discard(rule_id)
            if not self._tier_index[entry.tier]:
                del self._tier_index[entry.tier]
        self._evictions += 1

    def _enforce_lru(self) -> None:
        while len(self._cache) > self._config.max_size:
            rule_id, entry = self._cache.popitem(last=False)
            self._memory_usage -= entry.size_bytes
            if entry.tier and entry.tier in self._tier_index:
                self._tier_index[entry.tier].discard(rule_id)
                if not self._tier_index[entry.tier]:
                    del self._tier_index[entry.tier]

    def _enforce_fifo(self) -> None:
        while len(self._cache) > self._config.max_size:
            rule_id, entry = self._cache.popitem(last=False)
            self._memory_usage -= entry.size_bytes
            if entry.tier and entry.tier in self._tier_index:
                self._tier_index[entry.tier].discard(rule_id)
                if not self._tier_index[entry.tier]:
                    del self._tier_index[entry.tier]

    def _enforce_ttl(self) -> None:
        self._evict_expired()
        while len(self._cache) > self._config.max_size:
            rule_id, entry = self._cache.popitem(last=False)
            self._memory_usage -= entry.size_bytes
            if entry.tier and entry.tier in self._tier_index:
                self._tier_index[entry.tier].discard(rule_id)
                if not self._tier_index[entry.tier]:
                    del self._tier_index[entry.tier]

    def _enforce_memory_limit(self) -> None:
        limit_bytes = int(self._config.memory_limit_mb * 1024 * 1024)
        with self._lock:
            while self._memory_usage > limit_bytes and self._cache:
                rule_id, entry = self._cache.popitem(last=False)
                self._memory_usage -= entry.size_bytes
                if entry.tier and entry.tier in self._tier_index:
                    self._tier_index[entry.tier].discard(rule_id)
                    if not self._tier_index[entry.tier]:
                        del self._tier_index[entry.tier]
                self._evictions += 1

    def _get_ttl(self, rule_id: str, ttl: Optional[float], tier: Optional[str]) -> float:
        if ttl is not None:
            return ttl
        if tier and tier in self._config.tier_ttl_overrides:
            return self._config.tier_ttl_overrides[tier]
        return self._config.default_ttl

    def get(self, rule_id: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(rule_id)
            if entry is None:
                self._misses += 1
                return None
            now = time.time()
            if entry.expires_at > 0 and now >= entry.expires_at:
                self._remove_entry(rule_id)
                self._misses += 1
                return None
            if self._config.eviction_policy == EvictionPolicy.LRU:
                self._cache.move_to_end(rule_id)
            entry.last_access = now
            entry.access_count += 1
            self._hits += 1
            return entry.rule

    def get_entry(self, rule_id: str) -> Optional[CacheEntry]:
        with self._lock:
            entry = self._cache.get(rule_id)
            if entry is None:
                self._misses += 1
                return None
            now = time.time()
            if entry.expires_at > 0 and now >= entry.expires_at:
                self._remove_entry(rule_id)
                self._misses += 1
                return None
            if self._config.eviction_policy == EvictionPolicy.LRU:
                self._cache.move_to_end(rule_id)
            entry.last_access = now
            entry.access_count += 1
            self._hits += 1
            return entry

    def get_many(self, rule_ids: List[str]) -> Dict[str, Optional[Any]]:
        result: Dict[str, Optional[Any]] = {}
        with self._lock:
            for rid in rule_ids:
                result[rid] = self.get(rid)
        return result

    def set(self, rule_id: str, rule: Any, ttl: Optional[float] = None, tier: Optional[str] = None) -> None:
        now = time.time()
        effective_ttl = self._get_ttl(rule_id, ttl, tier)
        expires_at = now + effective_ttl if effective_ttl > 0 else 0.0
        size_bytes = self._estimate_size(rule)
        entry = CacheEntry(
            rule_id=rule_id,
            rule=rule,
            created_at=now,
            expires_at=expires_at,
            last_access=now,
            access_count=0,
            tier=tier,
            size_bytes=size_bytes,
        )
        with self._lock:
            old = self._cache.get(rule_id)
            if old:
                self._memory_usage -= old.size_bytes
                if old.tier and old.tier in self._tier_index:
                    self._tier_index[old.tier].discard(rule_id)
            self._cache[rule_id] = entry
            self._memory_usage += size_bytes
            self._total_inserts += 1
            if tier:
                self._tier_index.setdefault(tier, set()).add(rule_id)
            if self._config.eviction_policy == EvictionPolicy.LRU:
                self._enforce_lru()
            elif self._config.eviction_policy == EvictionPolicy.FIFO:
                self._enforce_fifo()
            elif self._config.eviction_policy == EvictionPolicy.TTL:
                self._enforce_ttl()
            self._enforce_memory_limit()

    def set_many(self, rules: Dict[str, Any], ttl: Optional[float] = None, tier: Optional[str] = None) -> int:
        count = 0
        for rule_id, rule in rules.items():
            self.set(rule_id, rule, ttl=ttl, tier=tier)
            count += 1
        return count

    def _estimate_size(self, obj: Any) -> int:
        try:
            raw = str(obj).encode("utf-8")
            return len(raw)
        except Exception:
            return 1024

    def delete(self, rule_id: str) -> bool:
        with self._lock:
            if rule_id not in self._cache:
                return False
            self._remove_entry(rule_id)
            self._total_deletes += 1
            return True

    def delete_many(self, rule_ids: List[str]) -> int:
        count = 0
        with self._lock:
            for rid in rule_ids:
                if self.delete(rid):
                    count += 1
        return count

    def clear(self) -> int:
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._tier_index.clear()
            self._memory_usage = 0
            self._total_deletes += count
            logger.info("Cleared cache (%d entries)", count)
            return count

    def invalidate_by_tier(self, tier: str) -> int:
        with self._lock:
            rule_ids = self._tier_index.pop(tier, set())
            count = 0
            for rid in list(rule_ids):
                if rid in self._cache:
                    self._remove_entry(rid)
                    self._total_deletes += 1
                    count += 1
            logger.info("Invalidated %d entries for tier '%s'", count, tier)
            return count

    def invalidate_by_tiers(self, tiers: List[str]) -> int:
        total = 0
        for tier in tiers:
            total += self.invalidate_by_tier(tier)
        return total

    def invalidate_by_prefix(self, prefix: str) -> int:
        with self._lock:
            to_remove = [rid for rid in self._cache if rid.startswith(prefix)]
            for rid in to_remove:
                self._remove_entry(rid)
                self._total_deletes += 1
            return len(to_remove)

    def invalidate_by_predicate(self, predicate: Callable[[str, Any], bool]) -> int:
        with self._lock:
            to_remove = [rid for rid, entry in self._cache.items() if predicate(rid, entry.rule)]
            for rid in to_remove:
                self._remove_entry(rid)
                self._total_deletes += 1
            return len(to_remove)

    def exists(self, rule_id: str) -> bool:
        with self._lock:
            entry = self._cache.get(rule_id)
            if entry is None:
                return False
            if entry.expires_at > 0 and time.time() >= entry.expires_at:
                self._remove_entry(rule_id)
                return False
            return True

    def touch(self, rule_id: str) -> bool:
        with self._lock:
            entry = self._cache.get(rule_id)
            if entry is None:
                return False
            now = time.time()
            if entry.expires_at > 0 and now >= entry.expires_at:
                self._remove_entry(rule_id)
                return False
            entry.last_access = now
            entry.access_count += 1
            if self._config.eviction_policy == EvictionPolicy.LRU:
                self._cache.move_to_end(rule_id)
            return True

    def update_ttl(self, rule_id: str, ttl: float) -> bool:
        with self._lock:
            entry = self._cache.get(rule_id)
            if entry is None:
                return False
            now = time.time()
            entry.expires_at = now + ttl if ttl > 0 else 0.0
            return True

    def get_tier_size(self, tier: str) -> int:
        with self._lock:
            return len(self._tier_index.get(tier, set()))

    def get_tier_ids(self, tier: str) -> List[str]:
        with self._lock:
            return list(self._tier_index.get(tier, set()))

    def get_all_tiers(self) -> Dict[str, int]:
        with self._lock:
            return {t: len(ids) for t, ids in self._tier_index.items()}

    def warm(self, provider: Optional[Callable[[], Dict[str, Any]]] = None) -> int:
        provider = provider or self._config.warm_provider
        if provider is None:
            logger.warning("No warm provider configured")
            return 0
        try:
            rules = provider()
            count = 0
            for rule_id, rule in rules.items():
                self.set(rule_id, rule)
                count += 1
            logger.info("Cache warmed with %d entries", count)
            return count
        except Exception as exc:
            logger.error("Cache warming failed: %s", exc)
            return 0

    def warm_from_dict(self, rules: Dict[str, Any], ttl: Optional[float] = None, tier: Optional[str] = None) -> int:
        count = 0
        for rule_id, rule in rules.items():
            self.set(rule_id, rule, ttl=ttl, tier=tier)
            count += 1
        logger.info("Cache warmed from dict with %d entries", count)
        return count

    def warm_from_list(self, rules: List[Tuple[str, Any]], ttl: Optional[float] = None, tier: Optional[str] = None) -> int:
        count = 0
        for rule_id, rule in rules:
            self.set(rule_id, rule, ttl=ttl, tier=tier)
            count += 1
        return count

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            hit_ratio = self._hits / total if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "max_size": self._config.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": round(hit_ratio, 4),
                "evictions": self._evictions,
                "total_inserts": self._total_inserts,
                "total_deletes": self._total_deletes,
                "memory_usage_bytes": self._memory_usage,
                "memory_usage_mb": round(self._memory_usage / (1024 * 1024), 2),
                "memory_limit_mb": self._config.memory_limit_mb,
                "tier_count": len(self._tier_index),
                "eviction_policy": self._config.eviction_policy.value,
                "default_ttl": self._config.default_ttl,
                "uptime_seconds": round(time.time() - self._start_time, 2),
            }

    def reset_stats(self) -> None:
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._total_inserts = 0
            self._total_deletes = 0

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._cache.keys())

    def values(self) -> List[Any]:
        with self._lock:
            return [e.rule for e in self._cache.values()]

    def items(self) -> List[Tuple[str, Any]]:
        with self._lock:
            return [(rid, e.rule) for rid, e in self._cache.items()]

    def items_with_metadata(self) -> List[Tuple[str, Any, CacheEntry]]:
        with self._lock:
            return [(rid, e.rule, e) for rid, e in self._cache.items()]

    def get_expired_entries(self) -> List[str]:
        now = time.time()
        expired: List[str] = []
        with self._lock:
            for rid, entry in self._cache.items():
                if entry.expires_at > 0 and now >= entry.expires_at:
                    expired.append(rid)
        return expired

    def prune_expired(self) -> int:
        expired = self.get_expired_entries()
        count = 0
        with self._lock:
            for rid in expired:
                if rid in self._cache:
                    self._remove_entry(rid)
                    count += 1
        logger.debug("Pruned %d expired entries", count)
        return count

    def set_max_size(self, max_size: int) -> None:
        with self._lock:
            self._config.max_size = max_size
            if self._config.eviction_policy == EvictionPolicy.LRU:
                self._enforce_lru()
            elif self._config.eviction_policy == EvictionPolicy.FIFO:
                self._enforce_fifo()
            elif self._config.eviction_policy == EvictionPolicy.TTL:
                self._enforce_ttl()

    def set_default_ttl(self, ttl: float) -> None:
        with self._lock:
            self._config.default_ttl = ttl

    def get_config(self) -> CacheConfig:
        return self._config

    def update_config(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)

    def contains(self, rule_id: str) -> bool:
        return self.exists(rule_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def __contains__(self, rule_id: str) -> bool:
        return self.exists(rule_id)

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"RuleCache(size={stats['size']}/{stats['max_size']}, "
            f"hit_ratio={stats['hit_ratio']}, "
            f"evictions={stats['evictions']}, "
            f"memory={stats['memory_usage_mb']}MB)"
        )

    def snapshot(self) -> Dict[str, Any]:
        stats = self.get_stats()
        keys_snapshot = self.keys()
        return {
            "stats": stats,
            "keys": keys_snapshot,
            "config": {
                "max_size": self._config.max_size,
                "default_ttl": self._config.default_ttl,
                "eviction_policy": self._config.eviction_policy.value,
                "memory_limit_mb": self._config.memory_limit_mb,
                "cleanup_interval": self._config.cleanup_interval,
            },
        }

    def export_to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        with self._lock:
            for rid, entry in self._cache.items():
                result[rid] = {
                    "rule": entry.rule,
                    "created_at": entry.created_at,
                    "expires_at": entry.expires_at,
                    "tier": entry.tier,
                    "access_count": entry.access_count,
                }
        return result

    def import_from_dict(self, data: Dict[str, Any], reset: bool = False) -> int:
        if reset:
            self.clear()
        count = 0
        for rid, info in data.items():
            self.set(
                rid,
                info.get("rule"),
                ttl=info.get("ttl"),
                tier=info.get("tier"),
            )
            count += 1
        return count

    def get_oldest_entries(self, n: int = 10) -> List[Tuple[str, Any]]:
        with self._lock:
            items = list(self._cache.items())
            items.sort(key=lambda x: x[1].last_access)
            return [(rid, e.rule) for rid, e in items[:n]]

    def get_hottest_entries(self, n: int = 10) -> List[Tuple[str, Any]]:
        with self._lock:
            items = list(self._cache.items())
            items.sort(key=lambda x: x[1].access_count, reverse=True)
            return [(rid, e.rule) for rid, e in items[:n]]

    def get_fresh_entries(self, max_age: float = 60.0) -> List[Tuple[str, Any]]:
        now = time.time()
        with self._lock:
            return [(rid, e.rule) for rid, e in self._cache.items() if now - e.created_at <= max_age]

    def batch_get_or_compute(
        self,
        rule_ids: List[str],
        compute_fn: Callable[[str], Any],
        ttl: Optional[float] = None,
        tier: Optional[str] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        missing: List[str] = []
        with self._lock:
            for rid in rule_ids:
                val = self.get(rid)
                if val is not None:
                    result[rid] = val
                else:
                    missing.append(rid)
        for rid in missing:
            try:
                val = compute_fn(rid)
                self.set(rid, val, ttl=ttl, tier=tier)
                result[rid] = val
            except Exception as exc:
                logger.error("Compute failed for %s: %s", rid, exc)
        return result

    def get_or_compute(
        self,
        rule_id: str,
        compute_fn: Callable[[], Any],
        ttl: Optional[float] = None,
        tier: Optional[str] = None,
    ) -> Any:
        cached = self.get(rule_id)
        if cached is not None:
            return cached
        try:
            val = compute_fn()
            self.set(rule_id, val, ttl=ttl, tier=tier)
            return val
        except Exception as exc:
            logger.error("Compute failed for %s: %s", rule_id, exc)
            raise

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return {rid: e.rule for rid, e in self._cache.items()}

    def filter_by_tier(self, tier: str) -> Dict[str, Any]:
        with self._lock:
            ids = self._tier_index.get(tier, set())
            return {rid: self._cache[rid].rule for rid in ids if rid in self._cache}

    def filter_by_predicate(self, predicate: Callable[[str, Any], bool]) -> Dict[str, Any]:
        with self._lock:
            return {rid: e.rule for rid, e in self._cache.items() if predicate(rid, e.rule)}

    def count_by_tier(self) -> Dict[str, int]:
        with self._lock:
            return {t: len(ids) for t, ids in self._tier_index.items()}

    def count_expired(self) -> int:
        return len(self.get_expired_entries())

    def get_memory_usage(self) -> int:
        with self._lock:
            return self._memory_usage

    def get_memory_usage_mb(self) -> float:
        return round(self.get_memory_usage() / (1024 * 1024), 2)

    def get_hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def get_miss_rate(self) -> float:
        total = self._hits + self._misses
        return self._misses / total if total > 0 else 0.0

    def is_full(self) -> bool:
        with self._lock:
            return len(self._cache) >= self._config.max_size

    def is_over_memory_limit(self) -> bool:
        limit_bytes = int(self._config.memory_limit_mb * 1024 * 1024)
        with self._lock:
            return self._memory_usage > limit_bytes

    def remaining_capacity(self) -> int:
        with self._lock:
            return max(0, self._config.max_size - len(self._cache))

    def remaining_memory_mb(self) -> float:
        limit_bytes = int(self._config.memory_limit_mb * 1024 * 1024)
        with self._lock:
            remaining = limit_bytes - self._memory_usage
            return round(max(0, remaining) / (1024 * 1024), 2)

    def defragment(self) -> int:
        with self._lock:
            self._cache = OrderedDict(self._cache)
            return len(self._cache)

    def scan_expired(self) -> List[str]:
        return self.get_expired_entries()

    def batch_touch(self, rule_ids: List[str]) -> int:
        count = 0
        for rid in rule_ids:
            if self.touch(rid):
                count += 1
        return count

    def batch_update_ttl(self, rule_ids: List[str], ttl: float) -> int:
        count = 0
        for rid in rule_ids:
            if self.update_ttl(rid, ttl):
                count += 1
        return count

    def get_entry_counts_by_tier(self) -> Dict[str, int]:
        return self.count_by_tier()

    def apply_policy(self, policy: EvictionPolicy) -> None:
        with self._lock:
            self._config.eviction_policy = policy

    def set_memory_limit(self, limit_mb: float) -> None:
        with self._lock:
            self._config.memory_limit_mb = limit_mb
            self._enforce_memory_limit()

    def get_cold_entries(self, threshold: float = 3600.0) -> List[Tuple[str, Any]]:
        now = time.time()
        with self._lock:
            return [(rid, e.rule) for rid, e in self._cache.items() if now - e.last_access > threshold]

    def get_hot_entries(self, min_access: int = 10) -> List[Tuple[str, Any]]:
        with self._lock:
            return [(rid, e.rule) for rid, e in self._cache.items() if e.access_count >= min_access]

    def compute_memory_savings(self) -> Dict[str, Any]:
        with self._lock:
            if not self._cache:
                return {"savings_bytes": 0, "savings_mb": 0.0, "entries_saved": 0}
            avg_size = self._memory_usage / len(self._cache)
            saved = avg_size * (self._total_inserts - len(self._cache))
            return {
                "savings_bytes": int(saved),
                "savings_mb": round(saved / (1024 * 1024), 2),
                "entries_saved": max(0, self._total_inserts - len(self._cache)),
            }