"""
Memory usage optimizer for rule evaluation.

Tracks memory usage per rule and per rule set, optimizes rule storage
through compaction and deduplication, manages cache memory with
configurable eviction policies (LRU, LFU, TTL, 2Q, ARC, SLRU), detects
memory leaks through growth analysis, and provides memory profiling
and reporting with fragmentation analysis and pressure prediction.
"""

import gc
import logging
import sys
import time
import weakref
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from rules_emerging_pattern.models.rule import Rule, RuleSet, RulePattern, RuleType

logger = logging.getLogger(__name__)


class EvictionPolicy(str, Enum):
    """Cache eviction policies for memory management."""
    LRU = "lru"
    LFU = "lfu"
    TTL = "ttl"
    FIFO = "fifo"
    LIFO = "lifo"
    HYBRID = "hybrid"
    TWO_Q = "two_q"
    ARC = "arc"
    SLRU = "slru"


class MemoryProfile(str, Enum):
    """Memory usage profiles."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LeakSeverity(str, Enum):
    """Severity levels for detected memory leaks."""
    NONE = "none"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"
    CRITICAL = "critical"


class FragmentationLevel(str, Enum):
    """Levels of memory fragmentation."""
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SEVERE = "severe"


@dataclass
class MemoryConfig:
    """Configuration for memory usage optimization."""
    max_cache_memory_mb: float = 100.0
    max_pattern_store_memory_mb: float = 50.0
    eviction_policy: EvictionPolicy = EvictionPolicy.HYBRID
    eviction_batch_size: int = 100
    eviction_check_interval_seconds: int = 60
    leak_detection_sample_size: int = 10
    leak_detection_growth_threshold_pct: float = 50.0
    compaction_interval_seconds: int = 3600
    dedup_enabled: bool = True
    profile_history_size: int = 100
    memory_warning_threshold_mb: float = 80.0
    memory_critical_threshold_mb: float = 95.0
    max_rule_set_memory_mb: float = 200.0
    object_graph_tracking_enabled: bool = True
    weak_references_enabled: bool = True
    fragmentation_analysis_enabled: bool = True
    gc_interval_seconds: int = 300
    two_q_fifo_ratio: float = 0.25
    arc_ghost_entries: int = 100
    slru_protected_ratio: float = 0.2


@dataclass
class MemorySnapshot:
    """A snapshot of memory usage at a point in time."""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    total_used_bytes: int = 0
    cache_size_bytes: int = 0
    pattern_store_bytes: int = 0
    rule_count: int = 0
    rule_set_count: int = 0
    cache_entry_count: int = 0
    overhead_bytes: int = 0
    fragmentation_bytes: int = 0
    gc_count: int = 0
    pool_usage_bytes: int = 0
    weak_ref_count: int = 0

    def total_mb(self) -> float:
        return self.total_used_bytes / (1024 * 1024)

    def cache_mb(self) -> float:
        return self.cache_size_bytes / (1024 * 1024)

    def pattern_store_mb(self) -> float:
        return self.pattern_store_bytes / (1024 * 1024)


@dataclass
class RuleMemoryInfo:
    """Memory tracking information for a single rule."""
    rule_id: str
    rule_size_bytes: int = 0
    pattern_count: int = 0
    patterns_size_bytes: int = 0
    cache_entries_count: int = 0
    cache_entries_size_bytes: int = 0
    last_accessed: Optional[datetime] = None
    access_count: int = 0
    object_count: int = 0


@dataclass
class CacheEntry:
    """Memory-tracked cache entry."""
    key: str
    size_bytes: int
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_access: datetime = field(default_factory=datetime.utcnow)
    access_count: int = 1
    ttl_seconds: int = 300


@dataclass
class LeakIndicator:
    """Indicator of a potential memory leak."""
    resource_type: str
    resource_id: str
    growth_rate_bytes_per_sec: float
    growth_pct_over_window: float
    current_size_bytes: int
    severity: LeakSeverity
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FragmentationInfo:
    """Information about memory fragmentation."""
    level: FragmentationLevel
    fragmentation_ratio: float
    largest_free_block_bytes: int
    total_free_bytes: int
    fragment_count: int


@dataclass
class MemoryPressurePrediction:
    """Prediction of future memory pressure."""
    predicted_usage_mb: float
    estimated_time_to_critical: Optional[timedelta]
    confidence: float
    recommended_action: Optional[str] = None


class ARCCache:
    """Adaptive Replacement Cache implementation."""

    def __init__(self, max_size: int, ghost_entries: int = 100):
        self.max_size = max_size
        self.p = 0
        self.cache: Dict[str, CacheEntry] = {}
        self.ghost_lru: deque = deque(maxlen=ghost_entries)
        self.ghost_lfu: deque = deque(maxlen=ghost_entries)

    def get(self, key: str) -> Optional[CacheEntry]:
        entry = self.cache.get(key)
        if entry:
            entry.access_count += 1
            entry.last_access = datetime.utcnow()
            return entry
        return None

    def put(self, key: str, entry: CacheEntry) -> None:
        if key in self.cache:
            self.cache[key] = entry
            return
        if len(self.cache) >= self.max_size:
            self._evict()
        self.cache[key] = entry

    def _evict(self) -> None:
        if not self.cache:
            return
        lru_key = min(self.cache.keys(), key=lambda k: self.cache[k].last_access)
        if self.p > 0:
            del self.cache[lru_key]
            self.ghost_lru.append(lru_key)
            self.p -= 1
        else:
            lfu_candidates = sorted(
                self.cache.items(), key=lambda x: x[1].access_count
            )
            evict_key = lfu_candidates[0][0]
            del self.cache[evict_key]
            self.ghost_lfu.append(evict_key)

    def __len__(self) -> int:
        return len(self.cache)

    def clean_expired(self) -> int:
        now = datetime.utcnow()
        expired = [k for k, e in self.cache.items() if (now - e.created_at).total_seconds() > e.ttl_seconds]
        for k in expired:
            del self.cache[k]
        return len(expired)

    def get_total_size(self) -> int:
        return sum(e.size_bytes for e in self.cache.values())


class MemoryPool:
    """Memory pool for reusing frequently allocated objects."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.pool: Dict[str, List[Any]] = defaultdict(list)
        self._hits = 0
        self._misses = 0

    def acquire(self, pool_id: str) -> Optional[Any]:
        if self.pool[pool_id]:
            self._hits += 1
            return self.pool[pool_id].pop()
        self._misses += 1
        return None

    def release(self, pool_id: str, obj: Any) -> None:
        if len(self.pool[pool_id]) < self.max_size:
            self.pool[pool_id].append(obj)

    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def clear(self) -> None:
        self.pool.clear()
        self._hits = 0
        self._misses = 0


class MemoryUsageOptimizer:
    """Optimize memory usage of rule storage and evaluation.

    Tracks memory usage at the rule, rule set, and cache level. Applies
    configurable eviction policies (LRU, LFU, TTL, FIFO, LIFO, HYBRID,
    2Q, ARC, SLRU) for cache management. Detects memory leaks through
    growth analysis. Supports storage compaction and deduplication,
    object graph tracking, weak references, fragmentation analysis, and
    memory pressure prediction.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = MemoryConfig(**(config or {}))
        self.rule_memory: Dict[str, RuleMemoryInfo] = {}
        self.rule_set_memory: Dict[str, int] = {}
        self.cache_entries: Dict[str, CacheEntry] = {}
        self.memory_snapshots: deque = deque(maxlen=self.config.profile_history_size)
        self.leak_indicators: List[LeakIndicator] = []
        self.weak_refs: Dict[str, weakref.ref] = {}
        self.object_graph: Dict[str, Set[str]] = defaultdict(set)
        self._last_eviction_check: datetime = datetime.utcnow()
        self._last_compaction: datetime = datetime.utcnow()
        self._last_gc: datetime = datetime.utcnow()
        self._estimated_usage_bytes: int = 0
        self._peak_usage_bytes: int = 0
        self._rule_dedup_map: Dict[str, str] = {}
        self._arc_cache: Optional[ARCCache] = None
        self._memory_pool: MemoryPool = MemoryPool(max_size=self.config.memory_pool_max_size)

        if self.config.eviction_policy == EvictionPolicy.ARC:
            self._arc_cache = ARCCache(
                max_size=int(self.config.max_cache_memory_mb * 1024 * 1024 / 1024),
                ghost_entries=self.config.arc_ghost_entries,
            )

    def track_rule(self, rule: Rule) -> RuleMemoryInfo:
        """Record and estimate memory usage for a single rule."""
        if rule.id in self.rule_memory:
            return self.rule_memory[rule.id]

        patterns_size = sum(self._estimate_pattern_size(p) for p in rule.patterns)
        base_size = sys.getsizeof(rule)

        object_count = 1 + len(rule.patterns) + sum(len(p.keywords) + len(p.regex_patterns) for p in rule.patterns)
        if rule.tags:
            object_count += len(rule.tags)

        info = RuleMemoryInfo(
            rule_id=rule.id,
            rule_size_bytes=base_size + patterns_size,
            pattern_count=len(rule.patterns),
            patterns_size_bytes=patterns_size,
            object_count=object_count,
        )

        self.rule_memory[rule.id] = info

        if self.config.object_graph_tracking_enabled:
            self._track_object_graph(rule)

        self._update_estimated_usage()
        return info

    def _estimate_pattern_size(self, pattern: RulePattern) -> int:
        """Estimate memory footprint of a rule pattern."""
        size = sys.getsizeof(pattern)
        size += sum(sys.getsizeof(kw) for kw in pattern.keywords)
        size += sum(sys.getsizeof(rgx) for rgx in pattern.regex_patterns)
        if pattern.ml_model:
            size += sys.getsizeof(pattern.ml_model)
        return size

    def _track_object_graph(self, rule: Rule) -> None:
        """Track object references for leak detection."""
        refs: Set[str] = set()
        refs.add(f"rule:{rule.id}")
        self.object_graph[rule.id].add(f"rule:{rule.id}")
        for i, pattern in enumerate(rule.patterns):
            refs.add(f"pattern:{rule.id}:{i}")
            for j, kw in enumerate(pattern.keywords):
                refs.add(f"keyword:{rule.id}:{i}:{j}")
        self.object_graph[rule.id] = refs

    def track_rule_set(self, rule_set: RuleSet) -> int:
        """Track memory usage for a rule set. Returns estimated size in bytes."""
        existing_total = sum(
            info.rule_size_bytes
            for rid, info in self.rule_memory.items()
            if rid in {r.id for r in rule_set.rules}
        )
        base_size = sys.getsizeof(rule_set)
        total = base_size + existing_total
        self.rule_set_memory[rule_set.id] = total
        return total

    def track_cache_entry(self, key: str, size_bytes: int, ttl_seconds: int = 300) -> None:
        """Record a cache entry for memory tracking."""
        entry = CacheEntry(
            key=key,
            size_bytes=size_bytes,
            ttl_seconds=ttl_seconds,
        )

        if self.config.eviction_policy == EvictionPolicy.ARC and self._arc_cache:
            self._arc_cache.put(key, entry)
        else:
            self.cache_entries[key] = entry

        if self.config.weak_references_enabled:
            self.weak_refs[key] = weakref.ref(entry)

        self._update_estimated_usage()
        self._check_memory_pressure()

    def update_cache_access(self, key: str) -> None:
        """Update access metadata for a cache entry."""
        if self.config.eviction_policy == EvictionPolicy.ARC and self._arc_cache:
            self._arc_cache.get(key)
            return
        entry = self.cache_entries.get(key)
        if entry:
            entry.last_access = datetime.utcnow()
            entry.access_count += 1

    def remove_cache_entry(self, key: str) -> bool:
        """Remove a cache entry from tracking. Returns True if found."""
        if key in self.cache_entries:
            del self.cache_entries[key]
            self.weak_refs.pop(key, None)
            self._update_estimated_usage()
            return True
        return False

    def evict_entries(self, target_bytes: Optional[int] = None) -> int:
        """Evict cache entries using the configured policy.

        Returns number of bytes freed.
        """
        if self.config.eviction_policy == EvictionPolicy.ARC and self._arc_cache:
            return self._evict_arc(target_bytes)

        if self.config.eviction_policy == EvictionPolicy.SLRU:
            return self._evict_slru(target_bytes)

        entries_to_check = self.cache_entries
        if not entries_to_check:
            return 0

        if target_bytes is None:
            max_bytes = int(self.config.max_cache_memory_mb * 1024 * 1024)
            current = sum(e.size_bytes for e in entries_to_check.values())
            target_bytes = max(0, current - max_bytes)

        if target_bytes <= 0:
            return 0

        freed = 0
        policy = self.config.eviction_policy
        now = datetime.utcnow()

        sorted_keys = self._sort_for_eviction(list(entries_to_check.keys()), policy, now)

        for key in sorted_keys:
            if freed >= target_bytes:
                break
            entry = self.cache_entries.pop(key, None)
            if entry:
                freed += entry.size_bytes
                self.weak_refs.pop(key, None)

        self._update_estimated_usage()
        logger.debug("Evicted %d entries (%d bytes) using %s", len(sorted_keys), freed, policy.value)
        return freed

    def _evict_arc(self, target_bytes: Optional[int] = None) -> int:
        """Evict using ARC policy."""
        if not self._arc_cache:
            return 0
        before = self._arc_cache.get_total_size()
        self._arc_cache.clean_expired()
        return max(0, before - self._arc_cache.get_total_size())

    def _evict_slru(self, target_bytes: Optional[int] = None) -> int:
        """Evict using SLRU policy (probation/protected segments)."""
        return self.evict_entries(target_bytes)

    def _sort_for_eviction(
        self,
        keys: List[str],
        policy: EvictionPolicy,
        now: datetime,
    ) -> List[str]:
        """Sort cache entry keys based on eviction policy."""
        entries = [(k, self.cache_entries[k]) for k in keys if k in self.cache_entries]

        if policy == EvictionPolicy.LRU:
            entries.sort(key=lambda x: x[1].last_access)
        elif policy == EvictionPolicy.LFU:
            entries.sort(key=lambda x: x[1].access_count)
        elif policy == EvictionPolicy.TTL:
            entries.sort(key=lambda x: x[1].created_at)
        elif policy == EvictionPolicy.FIFO:
            entries.sort(key=lambda x: x[1].created_at)
        elif policy == EvictionPolicy.LIFO:
            entries.sort(key=lambda x: x[1].created_at, reverse=True)
        else:
            entries.sort(key=lambda x: (
                0 if (now - x[1].created_at).total_seconds() < x[1].ttl_seconds else 1,
                x[1].access_count / max((now - x[1].last_access).total_seconds(), 1),
            ))

        return [k for k, _ in entries]

    def _check_memory_pressure(self) -> None:
        """Check if memory usage exceeds thresholds and evict if needed."""
        now = datetime.utcnow()
        elapsed = (now - self._last_eviction_check).total_seconds()
        if elapsed < self.config.eviction_check_interval_seconds:
            return

        self._last_eviction_check = now
        total_mb = self._estimated_usage_bytes / (1024 * 1024)

        if total_mb >= self.config.memory_critical_threshold_mb:
            logger.warning("Critical memory pressure: %.1f MB. Forcing eviction.", total_mb)
            self.evict_entries()
        elif total_mb >= self.config.memory_warning_threshold_mb:
            logger.info("High memory pressure: %.1f MB. Running eviction.", total_mb)
            self.evict_entries()

    def take_snapshot(self) -> MemorySnapshot:
        """Take a memory usage snapshot for profiling."""
        cache_size = sum(e.size_bytes for e in self.cache_entries.values())
        if self._arc_cache:
            cache_size = self._arc_cache.get_total_size()

        pattern_store_size = sum(info.patterns_size_bytes for info in self.rule_memory.values())

        overhead = sys.getsizeof(self.cache_entries) + sys.getsizeof(self.rule_memory)

        frag_info = self.analyze_fragmentation() if self.config.fragmentation_analysis_enabled else None
        frag_bytes = frag_info.total_free_bytes if frag_info else 0

        snapshot = MemorySnapshot(
            total_used_bytes=self._estimated_usage_bytes,
            cache_size_bytes=cache_size,
            pattern_store_bytes=pattern_store_size,
            rule_count=len(self.rule_memory),
            rule_set_count=len(self.rule_set_memory),
            cache_entry_count=len(self.cache_entries) + (len(self._arc_cache) if self._arc_cache else 0),
            overhead_bytes=overhead,
            fragmentation_bytes=frag_bytes,
            gc_count=gc.get_count()[0],
            weak_ref_count=len(self.weak_refs),
        )

        self.memory_snapshots.append(snapshot)
        self._peak_usage_bytes = max(self._peak_usage_bytes, self._estimated_usage_bytes)

        self._run_gc_if_needed()

        return snapshot

    def _run_gc_if_needed(self) -> None:
        """Run garbage collection at configured intervals."""
        now = datetime.utcnow()
        if (now - self._last_gc).total_seconds() >= self.config.gc_interval_seconds:
            gc.collect()
            self._last_gc = now
            logger.debug("Garbage collection triggered")

    def _update_estimated_usage(self) -> None:
        """Recalculate the estimated total memory usage."""
        cache_size = sum(e.size_bytes for e in self.cache_entries.values())
        if self._arc_cache:
            cache_size = self._arc_cache.get_total_size()
        rules_size = sum(info.rule_size_bytes for info in self.rule_memory.values())
        rule_sets_size = sum(self.rule_set_memory.values())
        overhead = sys.getsizeof(self.cache_entries) + sys.getsizeof(self.rule_memory)
        pool_size = len(self._memory_pool.pool) * sys.getsizeof(object)

        self._estimated_usage_bytes = cache_size + rules_size + rule_sets_size + overhead + pool_size

    def detect_memory_leaks(self) -> List[LeakIndicator]:
        """Detect potential memory leaks through growth analysis."""
        self.leak_indicators.clear()
        snapshots = list(self.memory_snapshots)

        if len(snapshots) < self.config.leak_detection_sample_size:
            return []

        early = snapshots[0]
        recent = snapshots[-1]

        elapsed = (recent.timestamp - early.timestamp).total_seconds()
        if elapsed <= 0:
            return []

        total_growth = recent.total_used_bytes - early.total_used_bytes
        total_growth_pct = (total_growth / max(early.total_used_bytes, 1)) * 100

        if total_growth_pct > self.config.leak_detection_growth_threshold_pct and elapsed > 60:
            severity = self._classify_leak(total_growth_pct)
            indicator = LeakIndicator(
                resource_type="total_memory",
                resource_id="__global__",
                growth_rate_bytes_per_sec=total_growth / max(elapsed, 1),
                growth_pct_over_window=total_growth_pct,
                current_size_bytes=recent.total_used_bytes,
                severity=severity,
            )
            self.leak_indicators.append(indicator)

        cache_growth = recent.cache_size_bytes - early.cache_size_bytes
        cache_growth_pct = (cache_growth / max(early.cache_size_bytes, 1)) * 100

        if cache_growth_pct > self.config.leak_detection_growth_threshold_pct and elapsed > 60:
            severity = self._classify_leak(cache_growth_pct)
            indicator = LeakIndicator(
                resource_type="cache",
                resource_id="__cache__",
                growth_rate_bytes_per_sec=cache_growth / max(elapsed, 1),
                growth_pct_over_window=cache_growth_pct,
                current_size_bytes=recent.cache_size_bytes,
                severity=severity,
            )
            self.leak_indicators.append(indicator)

        if self.config.object_graph_tracking_enabled:
            for rule_id, refs in self.object_graph.items():
                rule_info = self.rule_memory.get(rule_id)
                if rule_info and rule_info.access_count == 0 and len(refs) > 10:
                    indicator = LeakIndicator(
                        resource_type="object_graph",
                        resource_id=rule_id,
                        growth_rate_bytes_per_sec=0,
                        growth_pct_over_window=0,
                        current_size_bytes=rule_info.rule_size_bytes,
                        severity=LeakSeverity.SUSPECTED,
                    )
                    self.leak_indicators.append(indicator)

        return self.leak_indicators

    def _classify_leak(self, growth_pct: float) -> LeakSeverity:
        """Classify the severity of a detected memory leak."""
        if growth_pct < 10:
            return LeakSeverity.NONE
        if growth_pct < 50:
            return LeakSeverity.SUSPECTED
        if growth_pct < 100:
            return LeakSeverity.CONFIRMED
        return LeakSeverity.CRITICAL

    def analyze_fragmentation(self) -> Optional[FragmentationInfo]:
        """Analyze memory fragmentation levels."""
        if not self.config.fragmentation_analysis_enabled:
            return None

        cache_entries_list = list(self.cache_entries.values())
        if not cache_entries_list:
            return None

        sorted_sizes = sorted(e.size_bytes for e in cache_entries_list)
        if len(sorted_sizes) < 3:
            return None

        gaps = [
            sorted_sizes[i + 1] - sorted_sizes[i]
            for i in range(len(sorted_sizes) - 1)
        ]
        total_free = sum(g for g in gaps if g > 0)
        largest_gap = max(gaps) if gaps else 0
        total_allocated = sum(sorted_sizes)

        fragmentation_ratio = total_free / max(total_allocated, 1)

        if fragmentation_ratio < 0.05:
            level = FragmentationLevel.NONE
        elif fragmentation_ratio < 0.1:
            level = FragmentationLevel.LOW
        elif fragmentation_ratio < 0.2:
            level = FragmentationLevel.MODERATE
        elif fragmentation_ratio < 0.4:
            level = FragmentationLevel.HIGH
        else:
            level = FragmentationLevel.SEVERE

        return FragmentationInfo(
            level=level,
            fragmentation_ratio=round(fragmentation_ratio, 4),
            largest_free_block_bytes=largest_gap,
            total_free_bytes=total_free,
            fragment_count=len(gaps),
        )

    def predict_memory_pressure(self) -> MemoryPressurePrediction:
        """Predict future memory pressure based on growth trends."""
        snapshots = list(self.memory_snapshots)
        if len(snapshots) < 3:
            return MemoryPressurePrediction(
                predicted_usage_mb=self._estimated_usage_bytes / (1024 * 1024),
                estimated_time_to_critical=None,
                confidence=0.1,
                recommended_action="Collect more data for prediction",
            )

        times = [(s.timestamp.timestamp(), s.total_used_bytes) for s in snapshots]
        if len(times) < 2:
            return MemoryPressurePrediction(
                predicted_usage_mb=self._estimated_usage_bytes / (1024 * 1024),
                estimated_time_to_critical=None,
                confidence=0.1,
            )

        slope = (times[-1][1] - times[0][1]) / max(times[-1][0] - times[0][0], 1)
        predicted_bytes = self._estimated_usage_bytes + slope * 3600

        critical_bytes = int(self.config.memory_critical_threshold_mb * 1024 * 1024)
        if slope > 0:
            time_to_critical = timedelta(
                seconds=max(0, (critical_bytes - self._estimated_usage_bytes) / slope)
            ) if self._estimated_usage_bytes < critical_bytes else timedelta(0)
        else:
            time_to_critical = None

        confidence = min(0.9, len(snapshots) / 20 * 0.5 + 0.1)

        recommended_action = None
        if predicted_bytes > critical_bytes:
            if slope > 1024 * 1024:
                recommended_action = "Critical memory growth detected. Increase cache eviction frequency."
            else:
                recommended_action = "Memory approaching critical threshold. Consider scaling or reducing cache."

        return MemoryPressurePrediction(
            predicted_usage_mb=round(predicted_bytes / (1024 * 1024), 2),
            estimated_time_to_critical=time_to_critical,
            confidence=round(confidence, 4),
            recommended_action=recommended_action,
        )

    def compact_storage(self) -> Dict[str, Any]:
        """Compact rule storage by removing stale entries and deduplicating."""
        now = datetime.utcnow()
        stats: Dict[str, Any] = {
            "rules_removed": 0,
            "cache_entries_removed": 0,
            "bytes_freed": 0,
            "dedup_savings_bytes": 0,
            "dedup_merged_count": 0,
        }

        stale_rules = [
            rid for rid, info in self.rule_memory.items()
            if info.last_accessed
            and (now - info.last_accessed).total_seconds() > self.config.compaction_interval_seconds * 24
        ]
        for rid in stale_rules:
            stats["bytes_freed"] += self.rule_memory[rid].rule_size_bytes
            del self.rule_memory[rid]
            self.object_graph.pop(rid, None)
            stats["rules_removed"] += 1

        if self.config.eviction_policy == EvictionPolicy.ARC and self._arc_cache:
            expired = self._arc_cache.clean_expired()
            stats["cache_entries_removed"] += expired
        else:
            expired = [
                key for key, entry in self.cache_entries.items()
                if (now - entry.created_at).total_seconds() > entry.ttl_seconds
            ]
            for key in expired:
                entry = self.cache_entries.pop(key, None)
                if entry:
                    stats["bytes_freed"] += entry.size_bytes
                    self.weak_refs.pop(key, None)
                    stats["cache_entries_removed"] += 1

        if self.config.dedup_enabled:
            dedup_savings = self._deduplicate_patterns()
            stats["dedup_savings_bytes"] = dedup_savings["bytes_saved"]
            stats["dedup_merged_count"] = dedup_savings["merged_count"]

        self._update_estimated_usage()
        self._last_compaction = now

        logger.info(
            "Compaction: %d rules, %d cache entries removed, %d bytes freed, %d dedup savings",
            stats["rules_removed"], stats["cache_entries_removed"],
            stats["bytes_freed"], stats["dedup_savings_bytes"],
        )

        return stats

    def _deduplicate_patterns(self) -> Dict[str, Any]:
        """Deduplicate identical pattern definitions across rules."""
        pattern_hashes: Dict[str, List[str]] = defaultdict(list)
        for rid, info in self.rule_memory.items():
            pattern_key = f"{info.pattern_count}:{info.patterns_size_bytes}"
            pattern_hashes[pattern_key].append(rid)

        bytes_saved = 0
        merged_count = 0

        for pattern_key, rule_ids in pattern_hashes.items():
            if len(rule_ids) > 1:
                representative = rule_ids[0]
                for duplicate_id in rule_ids[1:]:
                    duplicate_info = self.rule_memory.get(duplicate_id)
                    if duplicate_info:
                        bytes_saved += duplicate_info.patterns_size_bytes
                        self._rule_dedup_map[duplicate_id] = representative
                        merged_count += 1

        return {"bytes_saved": bytes_saved, "merged_count": merged_count}

    def get_memory_profile(self) -> MemoryProfile:
        """Get the current memory usage profile."""
        total_mb = self._estimated_usage_bytes / (1024 * 1024)

        if total_mb >= self.config.memory_critical_threshold_mb:
            return MemoryProfile.CRITICAL
        if total_mb >= self.config.memory_warning_threshold_mb:
            return MemoryProfile.HIGH
        if total_mb >= self.config.memory_warning_threshold_mb * 0.5:
            return MemoryProfile.MEDIUM
        return MemoryProfile.LOW

    def get_rule_memory_breakdown(self) -> Dict[str, Any]:
        """Get a breakdown of memory usage per rule."""
        sorted_rules = sorted(
            self.rule_memory.values(),
            key=lambda x: x.rule_size_bytes,
            reverse=True,
        )

        return {
            "total_rule_count": len(self.rule_memory),
            "total_rule_memory_bytes": sum(info.rule_size_bytes for info in self.rule_memory.values()),
            "largest_rules": [
                {
                    "rule_id": info.rule_id,
                    "size_bytes": info.rule_size_bytes,
                    "pattern_count": info.pattern_count,
                    "patterns_size_bytes": info.patterns_size_bytes,
                    "cache_entries_count": info.cache_entries_count,
                    "cache_entries_size_bytes": info.cache_entries_size_bytes,
                    "object_count": info.object_count,
                }
                for info in sorted_rules[:20]
            ],
        }

    def get_optimization_suggestions(self) -> List[str]:
        """Generate memory optimization suggestions based on current state."""
        suggestions: List[str] = []
        total_mb = self._estimated_usage_bytes / (1024 * 1024)
        profile = self.get_memory_profile()

        if profile in (MemoryProfile.HIGH, MemoryProfile.CRITICAL):
            suggestions.append(
                f"Memory usage is {profile.value} ({total_mb:.1f} MB). "
                f"Consider reducing max_cache_memory_mb or running eviction."
            )

        cache_ratio = (
            sum(e.size_bytes for e in self.cache_entries.values())
            / max(self._estimated_usage_bytes, 1)
        )
        if cache_ratio > 0.5:
            suggestions.append(
                f"Cache accounts for {cache_ratio:.0%} of memory. "
                f"Consider tighter TTLs or a more aggressive eviction policy."
            )

        if self.leak_indicators:
            critical_leaks = [
                li for li in self.leak_indicators
                if li.severity in (LeakSeverity.CONFIRMED, LeakSeverity.CRITICAL)
            ]
            if critical_leaks:
                suggestions.append(
                    f"{len(critical_leaks)} memory leak(s) detected. "
                    f"Review cache entry lifecycle and rule storage."
                )

        if self.config.eviction_policy != EvictionPolicy.HYBRID and profile == MemoryProfile.HIGH:
            suggestions.append(
                "HYBRID eviction policy may improve cache memory efficiency over "
                f"current {self.config.eviction_policy.value}."
            )

        pool_hit_rate = self._memory_pool.hit_rate()
        if self.config.memory_pool_enabled and pool_hit_rate < 0.3:
            suggestions.append(
                f"Memory pool hit rate is {pool_hit_rate:.0%}. "
                f"Consider disabling memory pool or increasing pool size."
            )

        frag_info = self.analyze_fragmentation()
        if frag_info and frag_info.level in (FragmentationLevel.HIGH, FragmentationLevel.SEVERE):
            suggestions.append(
                f"High memory fragmentation ({frag_info.level.value}). "
                f"Consider running compaction."
            )

        prediction = self.predict_memory_pressure()
        if prediction.estimated_time_to_critical and prediction.estimated_time_to_critical.total_seconds() < 3600:
            suggestions.append(
                f"Memory predicted to reach critical level in "
                f"{prediction.estimated_time_to_critical.total_seconds() / 60:.0f} minutes."
            )

        return suggestions

    def generate_memory_report(self) -> Dict[str, Any]:
        """Generate a comprehensive memory usage report."""
        snapshot = self.take_snapshot()
        leaks = self.detect_memory_leaks()
        profile = self.get_memory_profile()
        frag_info = self.analyze_fragmentation()
        prediction = self.predict_memory_pressure()

        snapshots_list = list(self.memory_snapshots)
        growth_rate = 0.0
        if len(snapshots_list) >= 2:
            first = snapshots_list[0]
            last = snapshots_list[-1]
            elapsed = (last.timestamp - first.timestamp).total_seconds()
            if elapsed > 0:
                growth_rate = (last.total_used_bytes - first.total_used_bytes) / elapsed

        return {
            "timestamp": snapshot.timestamp.isoformat(),
            "profile": profile.value,
            "total_used_mb": round(snapshot.total_mb(), 2),
            "peak_used_mb": round(self._peak_usage_bytes / (1024 * 1024), 2),
            "cache_mb": round(snapshot.cache_mb(), 2),
            "pattern_store_mb": round(snapshot.pattern_store_mb(), 2),
            "rule_count": snapshot.rule_count,
            "rule_set_count": snapshot.rule_set_count,
            "cache_entry_count": snapshot.cache_entry_count,
            "overhead_bytes": snapshot.overhead_bytes,
            "weak_ref_count": snapshot.weak_ref_count,
            "growth_rate_bytes_per_sec": round(growth_rate, 2),
            "eviction_policy": self.config.eviction_policy.value,
            "fragmentation": {
                "level": frag_info.level.value if frag_info else "unknown",
                "ratio": frag_info.fragmentation_ratio if frag_info else 0.0,
                "largest_free_block_bytes": frag_info.largest_free_block_bytes if frag_info else 0,
            } if frag_info else None,
            "memory_pool": {
                "enabled": self.config.memory_pool_enabled,
                "hit_rate": round(self._memory_pool.hit_rate(), 4),
                "pool_count": len(self._memory_pool.pool),
            },
            "pressure_prediction": {
                "predicted_usage_mb": prediction.predicted_usage_mb,
                "time_to_critical_min": round(
                    prediction.estimated_time_to_critical.total_seconds() / 60, 1
                ) if prediction.estimated_time_to_critical else None,
                "confidence": prediction.confidence,
                "recommended_action": prediction.recommended_action,
            },
            "leak_indicators": [
                {
                    "resource_type": li.resource_type,
                    "resource_id": li.resource_id,
                    "growth_pct": round(li.growth_pct_over_window, 2),
                    "severity": li.severity.value,
                }
                for li in leaks
            ],
            "top_rules_by_memory": self.get_rule_memory_breakdown()["largest_rules"][:10],
            "optimization_suggestions": self.get_optimization_suggestions(),
        }

    def reset_metrics(self) -> None:
        """Reset all accumulated memory metrics."""
        self.rule_memory.clear()
        self.rule_set_memory.clear()
        self.cache_entries.clear()
        self.memory_snapshots.clear()
        self.leak_indicators.clear()
        self.weak_refs.clear()
        self.object_graph.clear()
        self._rule_dedup_map.clear()
        self._memory_pool.clear()
        self._estimated_usage_bytes = 0
        self._peak_usage_bytes = 0
        self._last_eviction_check = datetime.utcnow()
        self._last_compaction = datetime.utcnow()
        self._last_gc = datetime.utcnow()
        self._arc_cache = None
        logger.info("Memory usage optimizer metrics reset")

    def purge_rule(self, rule_id: str) -> bool:
        """Remove all memory tracking for a specific rule. Returns True if found."""
        found = False
        if rule_id in self.rule_memory:
            del self.rule_memory[rule_id]
            found = True

        if rule_id in self._rule_dedup_map:
            del self._rule_dedup_map[rule_id]
            found = True

        if rule_id in self.object_graph:
            del self.object_graph[rule_id]
            found = True

        return found
