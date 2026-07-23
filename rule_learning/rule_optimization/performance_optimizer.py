"""
Performance optimizer for rule evaluation.

Comprehensive performance metrics tracking with cache optimization
strategies, index optimization, execution plan optimization, performance
degradation detection, trend analysis, and anomaly detection.
"""

import logging
import math
import statistics
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from rules_emerging_pattern.models.rule import Rule, RuleSet, RulePattern, RuleType, RuleTier

logger = logging.getLogger(__name__)


class CacheStrategy(str, Enum):
    """Cache eviction and management strategies."""
    LRU = "lru"
    LFU = "lfu"
    TTL = "ttl"
    HYBRID = "hybrid"
    ADAPTIVE = "adaptive"
    TWO_Q = "two_q"
    SLRU = "slru"


class ExecutionStrategy(str, Enum):
    """Execution plan strategies."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    PRIORITY = "priority"
    ADAPTIVE = "adaptive"
    HYBRID = "hybrid"


class DegradationLevel(str, Enum):
    """Levels of performance degradation."""
    NONE = "none"
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


class IndexType(str, Enum):
    """Types of pattern indexes supported."""
    KEYWORD = "keyword"
    REGEX = "regex"
    TYPE = "type"
    NGRAM = "ngram"
    BLOOM = "bloom"


@dataclass
class PerformanceConfig:
    """Configuration for performance optimization."""
    slow_rule_threshold_ms: float = 100.0
    cache_enabled: bool = True
    cache_strategy: CacheStrategy = CacheStrategy.HYBRID
    cache_max_size: int = 5000
    cache_default_ttl_seconds: int = 300
    cache_min_ttl_seconds: int = 30
    cache_max_ttl_seconds: int = 3600
    cache_cleanup_interval_seconds: int = 60
    adaptive_ttl_enabled: bool = True
    adaptive_ttl_min: int = 30
    adaptive_ttl_max: int = 3600
    degradation_window_minutes: int = 30
    degradation_threshold_pct: float = 20.0
    trend_window_size: int = 50
    anomaly_std_dev_threshold: float = 3.0
    parallel_execution_threshold: int = 10
    min_pattern_index_size: int = 5
    index_refresh_interval_seconds: int = 300
    max_suggestions_per_rule: int = 5
    metrics_retention_days: int = 7
    benchmark_comparison_enabled: bool = True
    prediction_model_enabled: bool = True
    prediction_window_size: int = 20
    resource_contention_threshold: float = 0.8
    two_q_fifo_ratio: float = 0.25
    slru_segment_ratio: float = 0.2


@dataclass
class CacheEntry:
    """An entry in the evaluation cache."""
    key: str
    value: Any
    size_bytes: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_access: datetime = field(default_factory=datetime.utcnow)
    access_count: int = 1
    ttl_seconds: int = 300
    access_history: deque = field(default_factory=lambda: deque(maxlen=100))

    def is_expired(self) -> bool:
        return (datetime.utcnow() - self.created_at).total_seconds() > self.ttl_seconds

    def touch(self) -> None:
        self.last_access = datetime.utcnow()
        self.access_count += 1
        self.access_history.append(datetime.utcnow())

    def get_access_frequency(self, window_seconds: int = 300) -> float:
        """Get access frequency within a recent time window."""
        cutoff = datetime.utcnow() - timedelta(seconds=window_seconds)
        recent = [t for t in self.access_history if t > cutoff]
        return len(recent) / max(window_seconds, 1)


@dataclass
class PatternIndex:
    """Index for efficient pattern matching."""
    keyword_index: Dict[str, List[str]] = field(default_factory=dict)
    regex_index: Dict[str, List[str]] = field(default_factory=dict)
    type_index: Dict[str, List[str]] = field(default_factory=dict)
    ngram_index: Dict[str, List[str]] = field(default_factory=dict)
    bloom_filter: Optional[Any] = None
    last_refreshed: Optional[datetime] = None
    total_patterns: int = 0
    indexed_rules: int = 0
    build_time_ms: float = 0.0


@dataclass
class ExecutionPlan:
    """Optimized execution plan for rule evaluation."""
    rule_order: List[str] = field(default_factory=list)
    strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL
    estimated_time_ms: float = 0.0
    parallel_groups: List[List[str]] = field(default_factory=list)
    cache_plan: Dict[str, str] = field(default_factory=dict)
    estimated_cache_hits: int = 0
    estimated_cache_misses: int = 0
    adaptive_threshold: float = 0.0


@dataclass
class PerformanceSample:
    """A single performance data sample."""
    rule_id: str
    execution_time_ms: float
    timestamp: datetime
    cached: bool
    content_size: int
    pattern_count: int


@dataclass
class PredictionResult:
    """Predicted performance metrics for a rule."""
    rule_id: str
    predicted_time_ms: float
    confidence: float
    trend_direction: str
    estimated_optimal_cache_ttl: int
    recommendation: Optional[str] = None


@dataclass
class BenchmarkComparison:
    """Comparison of rule performance against baseline benchmarks."""
    rule_id: str
    current_avg_ms: float
    benchmark_avg_ms: float
    ratio: float
    percentile_rank: float
    assessment: str


class AdaptiveTTL:
    """Adaptive TTL calculator based on access patterns."""

    def __init__(self, min_ttl: int = 30, max_ttl: int = 3600):
        self.min_ttl = min_ttl
        self.max_ttl = max_ttl
        self.access_log: Dict[str, deque] = defaultdict(lambda: deque(maxlen=50))

    def record_access(self, key: str) -> None:
        self.access_log[key].append(datetime.utcnow())

    def compute_ttl(self, key: str, default_ttl: int = 300) -> int:
        history = list(self.access_log.get(key, []))
        if len(history) < 3:
            return default_ttl

        now = datetime.utcnow()
        recent = [t for t in history if (now - t).total_seconds() < 600]
        interval = (
            (recent[-1] - recent[0]).total_seconds() / max(len(recent) - 1, 1)
            if len(recent) > 1 else float("inf")
        )

        if interval < 10:
            ttl = self.max_ttl
        elif interval < 60:
            ttl = int(self.max_ttl * 0.75)
        elif interval < 300:
            ttl = default_ttl
        elif interval < 900:
            ttl = int(default_ttl * 0.5)
        else:
            ttl = self.min_ttl

        return max(self.min_ttl, min(ttl, self.max_ttl))


class TwoQCache:
    """2Q cache implementation for improved hit rates."""

    def __init__(self, max_size: int, fifo_ratio: float = 0.25):
        self.max_size = max_size
        self.fifo_max = int(max_size * fifo_ratio)
        self._fifo: Dict[str, CacheEntry] = {}
        self._lru: Dict[str, CacheEntry] = {}
        self._fifo_order: deque = deque(maxlen=self.fifo_max)

    def get(self, key: str) -> Optional[CacheEntry]:
        if key in self._lru:
            entry = self._lru[key]
            entry.touch()
            return entry
        if key in self._fifo:
            entry = self._fifo.pop(key)
            self._lru[key] = entry
            entry.touch()
            return entry
        return None

    def put(self, key: str, entry: CacheEntry) -> None:
        if key in self._lru:
            self._lru[key] = entry
            return
        if key in self._fifo:
            self._fifo[key] = entry
            return

        if len(self._fifo) >= self.fifo_max:
            evict_key = self._fifo_order[0]
            entry_to_evict = self._fifo.pop(evict_key, None)
            if entry_to_evict:
                self._lru[evict_key] = entry_to_evict

        self._fifo[key] = entry
        self._fifo_order.append(key)

    def evict(self, count: int = 1) -> int:
        evicted = 0
        for key in list(self._lru.keys()):
            if evicted >= count:
                break
            del self._lru[key]
            evicted += 1
        if evicted < count:
            for key in list(self._fifo.keys()):
                if evicted >= count:
                    break
                del self._fifo[key]
                evicted += 1
        return evicted

    def __len__(self) -> int:
        return len(self._fifo) + len(self._lru)

    def clean_expired(self) -> int:
        now = datetime.utcnow()
        expired = 0
        for key, entry in list(self._fifo.items()):
            if entry.is_expired():
                del self._fifo[key]
                expired += 1
        for key, entry in list(self._lru.items()):
            if entry.is_expired():
                del self._lru[key]
                expired += 1
        return expired


class RulePerformanceOptimizer:
    """Optimize rule performance with comprehensive metrics and strategies.

    Tracks detailed performance metrics per rule, manages evaluation caches
    with configurable strategies (LRU, LFU, TTL, HYBRID, 2Q, SLRU), builds
    pattern indexes for fast matching, generates execution plans for optimal
    evaluation order, detects performance degradation and anomalies, and
    produces optimization suggestions with prediction models.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = PerformanceConfig(**(config or {}))
        self.performance_data: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "total_evaluations": 0,
            "total_time_ms": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "slow_evaluations": 0,
            "max_time_ms": 0.0,
            "min_time_ms": float("inf"),
            "last_evaluation_time": None,
            "total_content_size": 0,
            "total_pattern_count": 0,
        })
        self.samples: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.config.trend_window_size)
        )
        self.degradation_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.anomaly_log: List[Dict[str, Any]] = []
        self.cache: Dict[str, CacheEntry] = {}
        self.two_q_cache: Optional[TwoQCache] = None
        self.slru_segments: List[Dict[str, CacheEntry]] = [{}, {}]
        self.cache_access_log: List[str] = []
        self.pattern_index: PatternIndex = PatternIndex()
        self.execution_plans: Dict[str, ExecutionPlan] = {}
        self.optimization_suggestions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.adaptive_ttl: AdaptiveTTL = AdaptiveTTL(
            min_ttl=self.config.adaptive_ttl_min,
            max_ttl=self.config.adaptive_ttl_max,
        )
        self.benchmarks: Dict[str, List[float]] = defaultdict(list)
        self.prediction_cache: Dict[str, PredictionResult] = {}
        self._last_cache_cleanup: datetime = datetime.utcnow()
        self._last_index_refresh: Optional[datetime] = None

        if self.config.cache_strategy == CacheStrategy.TWO_Q:
            self.two_q_cache = TwoQCache(
                max_size=self.config.cache_max_size,
                fifo_ratio=self.config.two_q_fifo_ratio,
            )

    def record_evaluation(
        self,
        rule_id: str,
        execution_time_ms: float,
        cached: bool = False,
        content_size: int = 0,
        pattern_count: int = 0,
    ) -> None:
        """Record performance data for a rule evaluation."""
        data = self.performance_data[rule_id]
        data["total_evaluations"] += 1
        data["total_time_ms"] += execution_time_ms
        data["max_time_ms"] = max(data["max_time_ms"], execution_time_ms)
        data["min_time_ms"] = min(data["min_time_ms"], execution_time_ms)
        data["last_evaluation_time"] = datetime.utcnow()
        data["total_content_size"] += content_size
        data["total_pattern_count"] += pattern_count

        if cached:
            data["cache_hits"] += 1
        else:
            data["cache_misses"] += 1

        if execution_time_ms > self.config.slow_rule_threshold_ms:
            data["slow_evaluations"] += 1

        sample = PerformanceSample(
            rule_id=rule_id,
            execution_time_ms=execution_time_ms,
            timestamp=datetime.utcnow(),
            cached=cached,
            content_size=content_size,
            pattern_count=pattern_count,
        )
        self.samples[rule_id].append(sample)

        if self.config.benchmark_comparison_enabled:
            self.benchmarks[rule_id].append(execution_time_ms)

        self._check_anomaly(rule_id, execution_time_ms)
        self._check_degradation(rule_id)

    def get_average_execution_time(self, rule_id: str) -> float:
        """Get average execution time for a rule in milliseconds."""
        data = self.performance_data.get(rule_id, {})
        total = data.get("total_evaluations", 0)
        if total == 0:
            return 0.0
        return data.get("total_time_ms", 0) / total

    def get_cache_hit_rate(self, rule_id: Optional[str] = None) -> float:
        """Get cache hit rate for a specific rule or overall."""
        if rule_id:
            data = self.performance_data.get(rule_id, {})
            hits = data.get("cache_hits", 0)
            misses = data.get("cache_misses", 0)
        else:
            hits = sum(d["cache_hits"] for d in self.performance_data.values())
            misses = sum(d["cache_misses"] for d in self.performance_data.values())

        total = hits + misses
        if total == 0:
            return 0.0
        return hits / total

    def get_slow_rules(self, threshold_ms: Optional[float] = None) -> List[Tuple[str, float]]:
        """Get rules with average execution time above threshold, sorted slowest first."""
        threshold = threshold_ms or self.config.slow_rule_threshold_ms
        slow_rules: List[Tuple[str, float]] = []
        for rule_id, data in self.performance_data.items():
            avg_time = self.get_average_execution_time(rule_id)
            if avg_time > threshold:
                slow_rules.append((rule_id, avg_time))
        return sorted(slow_rules, key=lambda x: x[1], reverse=True)

    def cache_put(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store a value in the performance cache with configured strategy."""
        if not self.config.cache_enabled:
            return

        ttl = ttl_seconds or self.config.cache_default_ttl_seconds

        if self.config.adaptive_ttl_enabled:
            ttl = self.adaptive_ttl.compute_ttl(key, ttl)

        ttl = max(self.config.cache_min_ttl_seconds, min(ttl, self.config.cache_max_ttl_seconds))

        if self.config.cache_strategy == CacheStrategy.TWO_Q and self.two_q_cache:
            size = sys.getsizeof(value)
            entry = CacheEntry(key=key, value=value, size_bytes=size, ttl_seconds=ttl)
            self.two_q_cache.put(key, entry)
            return

        self._enforce_cache_size()

        if key in self.cache:
            entry = self.cache[key]
            entry.value = value
            entry.ttl_seconds = ttl
            entry.touch()
        else:
            size = sys.getsizeof(value)
            self.cache[key] = CacheEntry(
                key=key,
                value=value,
                size_bytes=size,
                ttl_seconds=ttl,
            )

    def cache_get(self, key: str) -> Optional[Any]:
        """Retrieve a value from the cache, updating access metadata."""
        if not self.config.cache_enabled:
            return None

        if self.config.cache_strategy == CacheStrategy.TWO_Q and self.two_q_cache:
            entry = self.two_q_cache.get(key)
            if entry:
                self.cache_access_log.append(key)
                return entry.value
            return None

        if self.config.cache_strategy == CacheStrategy.SLRU:
            return self._slru_get(key)

        entry = self.cache.get(key)
        if entry is None:
            return None

        if entry.is_expired():
            del self.cache[key]
            return None

        entry.touch()
        self.cache_access_log.append(key)
        self.adaptive_ttl.record_access(key)
        return entry.value

    def cache_evict(self, key: str) -> bool:
        """Evict a specific key from cache. Returns True if evicted."""
        if self.config.cache_strategy == CacheStrategy.TWO_Q and self.two_q_cache:
            return False

        if key in self.cache:
            del self.cache[key]
            return True
        return False

    def _slru_get(self, key: str) -> Optional[Any]:
        """SLRU cache get with probation/protected segments."""
        for segment_idx, segment in enumerate(self.slru_segments):
            entry = segment.get(key)
            if entry:
                entry.touch()
                if segment_idx == 0:
                    del segment[key]
                    self.slru_segments[1][key] = entry
                    if len(self.slru_segments[1]) > self.config.cache_max_size * (1 - self.config.slru_segment_ratio):
                        evict_key = min(
                            self.slru_segments[1].keys(),
                            key=lambda k: self.slru_segments[1][k].access_count,
                        )
                        self.slru_segments[0][evict_key] = self.slru_segments[1].pop(evict_key)
                self.cache_access_log.append(key)
                return entry.value
        return None

    def _enforce_cache_size(self) -> None:
        """Evict entries when cache exceeds max size using configured strategy."""
        if self.config.cache_strategy in (CacheStrategy.TWO_Q, CacheStrategy.SLRU):
            return

        if len(self.cache) < self.config.cache_max_size:
            return

        strategy = self.config.cache_strategy
        now = datetime.utcnow()

        if strategy == CacheStrategy.LRU:
            sorted_entries = sorted(
                self.cache.items(),
                key=lambda x: x[1].last_access,
            )
        elif strategy == CacheStrategy.LFU:
            sorted_entries = sorted(
                self.cache.items(),
                key=lambda x: x[1].access_count,
            )
        elif strategy == CacheStrategy.TTL:
            sorted_entries = sorted(
                self.cache.items(),
                key=lambda x: x[1].created_at,
            )
        elif strategy == CacheStrategy.ADAPTIVE:
            sorted_entries = sorted(
                self.cache.items(),
                key=lambda x: (
                    x[1].is_expired(),
                    x[1].get_access_frequency(600) / max(
                        (now - x[1].last_access).total_seconds(), 1
                    ),
                ),
            )
        else:
            sorted_entries = sorted(
                self.cache.items(),
                key=lambda x: (
                    x[1].is_expired(),
                    x[1].access_count / max(
                        (now - x[1].last_access).total_seconds(), 1
                    ),
                ),
            )

        evict_count = max(1, len(sorted_entries) // 5)
        for key, _ in sorted_entries[:evict_count]:
            del self.cache[key]

        logger.debug(
            "Cache eviction: removed %d entries using %s strategy (size: %d)",
            evict_count, strategy.value, len(self.cache),
        )

    def _cleanup_expired_cache(self) -> int:
        """Remove all expired cache entries. Returns count removed."""
        if self.config.cache_strategy == CacheStrategy.TWO_Q and self.two_q_cache:
            return self.two_q_cache.clean_expired()

        expired = [key for key, entry in self.cache.items() if entry.is_expired()]
        for key in expired:
            del self.cache[key]
        if expired:
            logger.debug("Cache cleanup: removed %d expired entries", len(expired))
        return len(expired)

    def optimize_cache(self) -> Dict[str, Any]:
        """Run cache optimization and return statistics."""
        original_size = len(self.cache)
        expired = self._cleanup_expired_cache()

        remaining = len(self.cache)
        total_size = sum(e.size_bytes for e in self.cache.values())
        avg_ttl = (
            statistics.mean([e.ttl_seconds for e in self.cache.values()])
            if self.cache else 0.0
        )

        strategy_name = self.config.cache_strategy.value
        suggestions: List[str] = []

        if self.get_cache_hit_rate() < 0.5:
            suggestions.append("Consider switching to HYBRID cache strategy for better hit rate")
        if expired > original_size * 0.3:
            suggestions.append("High expiration rate - consider shorter TTL or adaptive TTL")
        if avg_ttl < 60:
            suggestions.append("Average TTL is very low - consider increasing default TTL")
        if total_size > 10 * 1024 * 1024:
            suggestions.append("Cache memory usage exceeds 10MB - consider reducing max size")

        if self.config.cache_strategy != CacheStrategy.ADAPTIVE and self.get_cache_hit_rate() < 0.4:
            suggestions.append("ADAPTIVE cache strategy may improve hit rate by adjusting TTL per entry")

        logger.info(
            "Cache optimization: %d -> %d entries (%d expired), %.1f KB, avg TTL %.0fs",
            original_size, remaining, expired, total_size / 1024, avg_ttl,
        )

        return {
            "original_size": original_size,
            "remaining": remaining,
            "expired_removed": expired,
            "total_size_bytes": total_size,
            "total_size_kb": round(total_size / 1024, 2),
            "average_ttl_seconds": round(avg_ttl, 1),
            "strategy": strategy_name,
            "cache_hit_rate": round(self.get_cache_hit_rate(), 4),
            "suggestions": suggestions,
        }

    def build_pattern_index(self, rules: List[Rule]) -> PatternIndex:
        """Build an optimized index for pattern matching across rules."""
        start = time.perf_counter()
        index = PatternIndex()
        keyword_index: Dict[str, Set[str]] = defaultdict(set)
        rule_count = 0
        pattern_count = 0

        for rule in rules:
            rule_count += 1
            index.type_index.setdefault(rule.rule_type.value, []).append(rule.id)

            for pattern in rule.patterns:
                pattern_count += 1
                for kw in pattern.keywords:
                    keyword_index[kw.lower()].add(rule.id)
                for rgx in pattern.regex_patterns:
                    index.regex_index.setdefault(rgx, []).append(rule.id)

        index.keyword_index = {k: list(v) for k, v in keyword_index.items()}
        index.total_patterns = pattern_count
        index.indexed_rules = rule_count
        index.last_refreshed = datetime.utcnow()
        index.build_time_ms = (time.perf_counter() - start) * 1000

        self.pattern_index = index
        self._last_index_refresh = datetime.utcnow()

        logger.info(
            "Pattern index built: %d rules, %d patterns, %d keywords, %d regex patterns in %.1fms",
            rule_count, pattern_count, len(keyword_index), len(index.regex_index),
            index.build_time_ms,
        )

        return index

    def build_ngram_index(self, rules: List[Rule], ngram_size: int = 3) -> None:
        """Build an n-gram based index for fast content filtering."""
        ngram_index: Dict[str, Set[str]] = defaultdict(set)

        for rule in rules:
            for pattern in rule.patterns:
                for kw in pattern.keywords:
                    kw_lower = kw.lower()
                    for i in range(len(kw_lower) - ngram_size + 1):
                        ngram = kw_lower[i:i + ngram_size]
                        ngram_index[ngram].add(rule.id)

        self.pattern_index.ngram_index = {k: list(v) for k, v in ngram_index.items()}
        logger.info("N-gram index built: %d unique n-grams", len(ngram_index))

    def find_candidate_rules(
        self,
        content: str,
        rule_type: Optional[RuleType] = None,
        use_ngram: bool = False,
    ) -> List[str]:
        """Use pattern index to find candidate rule IDs for content."""
        if not self.pattern_index.last_refreshed:
            return []

        content_lower = content.lower()
        candidate_ids: Set[str] = set()

        words = set(content_lower.split())
        for word in words:
            matched_ids = self.pattern_index.keyword_index.get(word, [])
            candidate_ids.update(matched_ids)

        if use_ngram and self.pattern_index.ngram_index:
            for i in range(len(content_lower) - 3 + 1):
                ngram = content_lower[i:i + 3]
                matched_ids = self.pattern_index.ngram_index.get(ngram, [])
                candidate_ids.update(matched_ids)

        if rule_type and rule_type.value in self.pattern_index.type_index:
            type_ids = set(self.pattern_index.type_index[rule_type.value])
            candidate_ids &= type_ids

        return list(candidate_ids)

    def create_execution_plan(
        self,
        rules: List[Rule],
        content: str,
        parallel: bool = True,
    ) -> ExecutionPlan:
        """Create an optimized execution plan for rule evaluation."""
        plan = ExecutionPlan()

        if len(rules) < self.config.parallel_execution_threshold or not parallel:
            plan.strategy = ExecutionStrategy.PRIORITY
            plan.rule_order = [
                r.id for r in sorted(
                    rules, key=lambda r: (r.priority, r.severity.value), reverse=True
                )
            ]
            plan.estimated_time_ms = sum(
                self.get_average_execution_time(r.id) or 5.0
                for r in rules
            )
            self.execution_plans["current"] = plan
            return plan

        if len(rules) > self.config.parallel_execution_threshold * 3:
            plan.strategy = ExecutionStrategy.HYBRID
        else:
            plan.strategy = ExecutionStrategy.PARALLEL

        rules_sorted = sorted(
            rules, key=lambda r: (r.priority, r.severity.value), reverse=True
        )

        groups: List[List[str]] = []
        current_group: List[str] = []
        current_group_time = 0.0

        for rule in rules_sorted:
            avg_time = self.get_average_execution_time(rule.id) or 5.0
            if current_group_time + avg_time > self.config.slow_rule_threshold_ms and current_group:
                groups.append(current_group)
                current_group = [rule.id]
                current_group_time = avg_time
            else:
                current_group.append(rule.id)
                current_group_time += avg_time

        if current_group:
            groups.append(current_group)

        plan.parallel_groups = groups
        plan.rule_order = [rid for group in groups for rid in group]
        plan.estimated_time_ms = (
            max(
                sum(self.get_average_execution_time(rid) or 5.0 for rid in group)
                for group in groups
            )
            if groups else 0.0
        )

        hit_rate = self.get_cache_hit_rate()
        plan.estimated_cache_hits = int(len(rules) * hit_rate)
        plan.estimated_cache_misses = len(rules) - plan.estimated_cache_hits

        self.execution_plans["current"] = plan
        logger.debug(
            "Execution plan: %d rules in %d groups, strategy=%s, estimated %.1fms",
            len(rules), len(groups), plan.strategy.value, plan.estimated_time_ms,
        )

        return plan

    def get_execution_plan(self, plan_id: str = "current") -> Optional[ExecutionPlan]:
        """Retrieve a cached execution plan."""
        return self.execution_plans.get(plan_id)

    def _check_anomaly(self, rule_id: str, execution_time_ms: float) -> None:
        """Detect anomalous execution times for a rule."""
        samples = list(self.samples.get(rule_id, []))
        if len(samples) < 10:
            return

        recent_times = [s.execution_time_ms for s in samples[-20:]]
        mean = statistics.mean(recent_times)
        stdev = statistics.stdev(recent_times) if len(recent_times) > 1 else 0.0

        if stdev > 0 and abs(execution_time_ms - mean) / stdev > self.config.anomaly_std_dev_threshold:
            anomaly = {
                "rule_id": rule_id,
                "execution_time_ms": execution_time_ms,
                "expected_mean_ms": round(mean, 2),
                "expected_std_ms": round(stdev, 2),
                "deviation_std": round(abs(execution_time_ms - mean) / stdev, 2),
                "timestamp": datetime.utcnow().isoformat(),
            }
            self.anomaly_log.append(anomaly)
            logger.warning(
                "Performance anomaly detected for rule %s: %.1fms (mean=%.1fms, std=%.1fms)",
                rule_id, execution_time_ms, mean, stdev,
            )

    def _check_degradation(self, rule_id: str) -> None:
        """Check for gradual performance degradation over time."""
        samples = list(self.samples.get(rule_id, []))
        if len(samples) < self.config.trend_window_size:
            return

        half = len(samples) // 2
        first_half = [s.execution_time_ms for s in samples[:half]]
        second_half = [s.execution_time_ms for s in samples[half:]]

        first_mean = statistics.mean(first_half)
        second_mean = statistics.mean(second_half)

        if first_mean > 0:
            change_pct = ((second_mean - first_mean) / first_mean) * 100
            if change_pct > self.config.degradation_threshold_pct:
                level = self._classify_degradation(change_pct)
                record = {
                    "rule_id": rule_id,
                    "previous_avg_ms": round(first_mean, 2),
                    "current_avg_ms": round(second_mean, 2),
                    "change_pct": round(change_pct, 2),
                    "level": level.value,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                self.degradation_history[rule_id].append(record)
                logger.info(
                    "Performance degradation detected for rule %s: %.1f%% increase (level=%s)",
                    rule_id, change_pct, level.value,
                )

    def _classify_degradation(self, change_pct: float) -> DegradationLevel:
        """Classify the severity of performance degradation."""
        if change_pct < 10:
            return DegradationLevel.NONE
        if change_pct < 25:
            return DegradationLevel.MILD
        if change_pct < 50:
            return DegradationLevel.MODERATE
        if change_pct < 100:
            return DegradationLevel.SEVERE
        return DegradationLevel.CRITICAL

    def get_trend(self, rule_id: str) -> Dict[str, Any]:
        """Get performance trend data for a rule."""
        samples = list(self.samples.get(rule_id, []))
        if len(samples) < 2:
            return {"trend": "insufficient_data", "direction": "unknown"}

        times = [s.execution_time_ms for s in samples]
        mean = statistics.mean(times)
        stdev = statistics.stdev(times) if len(times) > 1 else 0.0
        recent = times[-10:] if len(times) >= 10 else times
        recent_mean = statistics.mean(recent)

        if len(times) >= 10:
            early_mean = statistics.mean(times[:5])
            direction = "improving" if recent_mean < early_mean else "degrading"
        else:
            direction = "stable"

        return {
            "rule_id": rule_id,
            "sample_count": len(samples),
            "mean_ms": round(mean, 2),
            "std_ms": round(stdev, 2),
            "min_ms": round(min(times), 2),
            "max_ms": round(max(times), 2),
            "recent_mean_ms": round(recent_mean, 2),
            "direction": direction,
            "degradation_events": len(self.degradation_history.get(rule_id, [])),
            "anomaly_events": sum(
                1 for a in self.anomaly_log if a["rule_id"] == rule_id
            ),
        }

    def predict_performance(self, rule_id: str) -> PredictionResult:
        """Predict future performance for a rule using historical data."""
        if rule_id in self.prediction_cache:
            return self.prediction_cache[rule_id]

        samples = list(self.samples.get(rule_id, []))
        if len(samples) < self.config.prediction_window_size:
            result = PredictionResult(
                rule_id=rule_id,
                predicted_time_ms=self.get_average_execution_time(rule_id),
                confidence=0.3,
                trend_direction="unknown",
                estimated_optimal_cache_ttl=self.config.cache_default_ttl_seconds,
                recommendation="Insufficient data for prediction",
            )
            self.prediction_cache[rule_id] = result
            return result

        recent = [s.execution_time_ms for s in samples[-self.config.prediction_window_size:]]
        recent_mean = statistics.mean(recent)
        recent_stdev = statistics.stdev(recent) if len(recent) > 1 else 0.0

        earlier = [s.execution_time_ms for s in samples[:-self.config.prediction_window_size]]
        earlier_mean = statistics.mean(earlier) if earlier else recent_mean

        trend = "improving" if recent_mean < earlier_mean else "degrading"
        confidence = min(0.9, 0.5 + (len(samples) / 500) * 0.4)

        access_frequency = self._estimate_access_frequency(rule_id)
        if access_frequency > 0.1:
            optimal_ttl = int(self.config.cache_max_ttl_seconds * min(1.0, access_frequency * 10))
        else:
            optimal_ttl = self.config.cache_default_ttl_seconds

        recommendation = None
        if trend == "degrading" and recent_mean > earlier_mean * 1.2:
            recommendation = "Performance degrading. Consider pattern optimization."
        elif recent_stdev > recent_mean * 0.5:
            recommendation = "High variance detected. Consider caching more aggressively."

        result = PredictionResult(
            rule_id=rule_id,
            predicted_time_ms=round(recent_mean, 2),
            confidence=round(confidence, 4),
            trend_direction=trend,
            estimated_optimal_cache_ttl=optimal_ttl,
            recommendation=recommendation,
        )

        self.prediction_cache[rule_id] = result
        return result

    def _estimate_access_frequency(self, rule_id: str) -> float:
        """Estimate the access frequency for a rule (accesses per second)."""
        samples = list(self.samples.get(rule_id, []))
        if len(samples) < 2:
            return 0.0

        span = (samples[-1].timestamp - samples[0].timestamp).total_seconds()
        if span <= 0:
            return 0.0

        return len(samples) / span

    def compare_benchmark(self, rule_id: str) -> Optional[BenchmarkComparison]:
        """Compare a rule's performance against its own benchmark history."""
        times = self.benchmarks.get(rule_id, [])
        if len(times) < 10:
            return None

        current_avg = statistics.mean(times[-5:])
        benchmark_avg = statistics.mean(times[:-5])
        ratio = current_avg / max(benchmark_avg, 0.001)

        sorted_times = sorted(times)
        rank = sum(1 for t in sorted_times if t < current_avg)
        percentile = rank / len(sorted_times) * 100

        if ratio < 0.8:
            assessment = "significantly_improved"
        elif ratio < 0.95:
            assessment = "slightly_improved"
        elif ratio < 1.05:
            assessment = "stable"
        elif ratio < 1.2:
            assessment = "slightly_degraded"
        else:
            assessment = "significantly_degraded"

        return BenchmarkComparison(
            rule_id=rule_id,
            current_avg_ms=round(current_avg, 2),
            benchmark_avg_ms=round(benchmark_avg, 2),
            ratio=round(ratio, 4),
            percentile_rank=round(percentile, 1),
            assessment=assessment,
        )

    def get_hot_cache_keys(self, top_n: int = 20) -> List[Dict[str, Any]]:
        """Get the most frequently accessed cache keys for analysis."""
        access_counts: Dict[str, int] = defaultdict(int)
        for key in self.cache_access_log[-5000:]:
            access_counts[key] += 1

        sorted_keys = sorted(access_counts.items(), key=lambda x: x[1], reverse=True)
        return [
            {"key": key, "access_count": count}
            for key, count in sorted_keys[:top_n]
        ]

    def suggest_optimizations(self, rule_id: str) -> List[str]:
        """Suggest performance optimizations for a specific rule."""
        suggestions: List[str] = []
        data = self.performance_data.get(rule_id, {})

        total = data.get("cache_hits", 0) + data.get("cache_misses", 0)
        if total > 0:
            hit_rate = data.get("cache_hits", 0) / total
            if hit_rate < 0.5:
                suggestions.append(
                    f"Cache hit rate is {hit_rate:.0%}. Consider increasing cache TTL "
                    f"(current: {self.config.cache_default_ttl_seconds}s)."
                )
            if hit_rate < 0.2:
                suggestions.append("Cache hit rate is critically low. Review caching strategy.")

        avg_time = self.get_average_execution_time(rule_id)
        threshold = self.config.slow_rule_threshold_ms
        if avg_time > threshold:
            severity = "slightly" if avg_time < threshold * 2 else "significantly"
            suggestions.append(
                f"Rule {severity} slow ({avg_time:.1f}ms vs {threshold:.0f}ms threshold). "
                f"Consider pattern simplification or index optimization."
            )

        trend = self.get_trend(rule_id)
        if trend.get("direction") == "degrading":
            suggestions.append(
                f"Performance degrading (recent avg: {trend['recent_mean_ms']}ms). "
                f"Review recent rule changes or pattern complexity."
            )

        if rule_id in self.degradation_history:
            latest = self.degradation_history[rule_id][-1]
            if latest["level"] in ("severe", "critical"):
                suggestions.append(
                    f"Critical degradation: {latest['change_pct']:.0f}% performance loss detected. "
                    f"Immediate optimization recommended."
                )

        prediction = self.predict_performance(rule_id)
        if prediction.recommendation:
            suggestions.append(f"[Prediction] {prediction.recommendation}")

        benchmark = self.compare_benchmark(rule_id)
        if benchmark and benchmark.assessment in ("slightly_degraded", "significantly_degraded"):
            suggestions.append(
                f"Benchmark comparison shows {benchmark.assessment} "
                f"(ratio: {benchmark.ratio:.2f}x vs baseline)."
            )

        return suggestions[:self.config.max_suggestions_per_rule]

    def generate_performance_report(self) -> Dict[str, Any]:
        """Generate a comprehensive performance report."""
        self._cleanup_expired_cache()

        all_rules = list(self.performance_data.keys())
        total_eval = sum(d["total_evaluations"] for d in self.performance_data.values())
        total_time = sum(d["total_time_ms"] for d in self.performance_data.values())
        slow_rules = self.get_slow_rules()

        avg_times = [self.get_average_execution_time(rid) for rid in all_rules]
        overall_avg = statistics.mean(avg_times) if avg_times else 0.0

        degradation_summary: Dict[str, int] = {level.value: 0 for level in DegradationLevel}
        for records in self.degradation_history.values():
            for record in records:
                level = record.get("level", DegradationLevel.NONE.value)
                if level in degradation_summary:
                    degradation_summary[level] += 1

        predicted_times: List[Dict[str, Any]] = []
        if self.config.prediction_model_enabled:
            for rule_id in all_rules[:20]:
                pred = self.predict_performance(rule_id)
                predicted_times.append({
                    "rule_id": rule_id,
                    "predicted_ms": pred.predicted_time_ms,
                    "confidence": pred.confidence,
                    "trend": pred.trend_direction,
                })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_rules_tracked": len(all_rules),
            "total_evaluations": total_eval,
            "total_time_ms": round(total_time, 2),
            "overall_average_ms": round(overall_avg, 2),
            "cache_hit_rate": round(self.get_cache_hit_rate(), 4),
            "cache_size": len(self.cache),
            "cache_strategy": self.config.cache_strategy.value,
            "pattern_index_built": self.pattern_index.last_refreshed is not None,
            "pattern_index_rules": self.pattern_index.indexed_rules,
            "pattern_index_build_time_ms": self.pattern_index.build_time_ms,
            "execution_plans_cached": len(self.execution_plans),
            "slow_rule_count": len(slow_rules),
            "slow_rules": [
                {"rule_id": rid, "avg_time_ms": round(t, 2)}
                for rid, t in slow_rules[:20]
            ],
            "degradation_summary": degradation_summary,
            "total_degradation_events": sum(len(v) for v in self.degradation_history.values()),
            "total_anomalies": len(self.anomaly_log),
            "recent_anomalies": sorted(
                self.anomaly_log[-10:],
                key=lambda x: x["timestamp"],
                reverse=True,
            ),
            "predictions": predicted_times,
        }

    def reset_metrics(self) -> None:
        """Reset all accumulated performance metrics."""
        self.performance_data.clear()
        self.samples.clear()
        self.degradation_history.clear()
        self.anomaly_log.clear()
        self.cache.clear()
        self.two_q_cache = None
        self.slru_segments = [{}, {}]
        self.cache_access_log.clear()
        self.pattern_index = PatternIndex()
        self.execution_plans.clear()
        self.optimization_suggestions.clear()
        self.benchmarks.clear()
        self.prediction_cache.clear()
        self._last_cache_cleanup = datetime.utcnow()
        self._last_index_refresh = None
        logger.info("Performance optimizer metrics reset")

    def purge_rule(self, rule_id: str) -> bool:
        """Remove all tracking data for a specific rule. Returns True if found."""
        found = False

        if rule_id in self.performance_data:
            del self.performance_data[rule_id]
            found = True

        if rule_id in self.samples:
            del self.samples[rule_id]
            found = True

        if rule_id in self.degradation_history:
            del self.degradation_history[rule_id]
            found = True

        if rule_id in self.benchmarks:
            del self.benchmarks[rule_id]
            found = True

        if rule_id in self.prediction_cache:
            del self.prediction_cache[rule_id]
            found = True

        return found
