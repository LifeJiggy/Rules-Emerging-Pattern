"""
Profiler tool for rule evaluation timing, memory usage, cache efficiency analysis,
bottleneck identification, and cross-run comparison.
"""

import gc
import json
import logging
import math
import os
import statistics
import time
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

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
from rules_emerging_pattern.models.validation import ValidationResult

logger = logging.getLogger(__name__)


class ProfilingTarget(str, Enum):
    """What to profile during a session."""
    EVALUATION_TIME = "evaluation_time"
    MEMORY_USAGE = "memory_usage"
    CACHE_EFFICIENCY = "cache_efficiency"
    ALL = "all"


class ProfilingDepth(str, Enum):
    """Depth of profiling detail."""
    LIGHT = "light"
    NORMAL = "normal"
    DEEP = "deep"
    EXTREME = "extreme"


class ReportFormat(str, Enum):
    """Output format for profiling reports."""
    JSON = "json"
    YAML = "yaml"
    TEXT = "text"
    MARKDOWN = "markdown"


@dataclass
class ProfilerConfig:
    """Configuration for the profiler."""
    profiling_target: ProfilingTarget = ProfilingTarget.ALL
    depth: ProfilingDepth = ProfilingDepth.NORMAL
    sample_size: int = 1000
    warmup_iterations: int = 10
    track_memory_delta: bool = True
    track_object_counts: bool = False
    cache_simulation: bool = True
    cache_ttl_seconds: int = 300
    cutoff_percentile: float = 95.0
    detect_bottlenecks: bool = True
    bottleneck_threshold_ms: float = 50.0
    compare_with_previous: bool = True
    history_dir: Optional[str] = None
    max_history_runs: int = 20
    report_format: ReportFormat = ReportFormat.JSON
    auto_export: bool = False
    export_dir: Optional[str] = None
    detailed_per_rule: bool = True
    include_traceback: bool = False
    parallel_profiling: bool = False
    max_workers: int = 4
    timer_precision: int = 6


@dataclass
class RuleTimingStats:
    """Timing statistics for a single rule."""
    rule_id: str
    rule_name: str
    tier: str
    rule_type: str
    count: int
    total_time_ms: float
    avg_time_ms: float
    min_time_ms: float
    max_time_ms: float
    median_time_ms: float
    p50_time_ms: float
    p95_time_ms: float
    p99_time_ms: float
    std_dev_ms: float
    timeout_ms: int
    timeout_hits: int
    slowest_input: Optional[str] = None


@dataclass
class MemoryStats:
    """Memory usage statistics."""
    timestamp: str
    rss_bytes: int
    vms_bytes: int
    gc_objects: int
    gc_generations: List[int]
    objects_by_type: Dict[str, int] = field(default_factory=dict)
    description: str = ""


@dataclass
class CacheEfficiencyStats:
    """Cache efficiency statistics."""
    total_requests: int
    hits: int
    misses: int
    hit_rate: float
    avg_ttl_remaining: float
    entries_by_rule: Dict[str, Dict[str, int]]
    stale_entries: int
    memory_estimate_bytes: int
    eviction_count: int
    avg_lookup_time_ms: float


@dataclass
class BottleneckInfo:
    """Information about a identified bottleneck."""
    rule_id: str
    rule_name: str
    metric: str
    value: float
    threshold: float
    severity: str
    suggestion: str
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProfilingRun:
    """Data from a single profiling run."""
    run_id: str
    started_at: datetime
    finished_at: datetime
    config_snapshot: Dict[str, Any]
    environment: Dict[str, Any]
    rule_timing: Dict[str, RuleTimingStats]
    memory_stats: List[MemoryStats]
    cache_efficiency: Optional[CacheEfficiencyStats]
    bottlenecks: List[BottleneckInfo]
    summary: Dict[str, Any]
    previous_run_id: Optional[str] = None
    comparison: Optional[Dict[str, Any]] = None


class PrecisionTimer:
    """High-precision timer for profiling."""

    def __init__(self, precision: int = 6):
        self._precision = precision
        self._start_times: Dict[str, float] = {}
        self._accumulated: Dict[str, float] = defaultdict(float)
        self._counts: Dict[str, int] = defaultdict(int)
        self._laps: Dict[str, List[float]] = defaultdict(list)

    def start(self, timer_id: str) -> None:
        self._start_times[timer_id] = time.perf_counter()

    def stop(self, timer_id: str) -> float:
        start = self._start_times.pop(timer_id, None)
        if start is None:
            return 0.0
        elapsed = time.perf_counter() - start
        self._accumulated[timer_id] += elapsed
        self._counts[timer_id] += 1
        self._laps[timer_id].append(elapsed)
        return round(elapsed, self._precision)

    def lap(self, timer_id: str) -> float:
        start = self._start_times.get(timer_id)
        if start is None:
            return 0.0
        elapsed = time.perf_counter() - start
        self._laps[timer_id].append(elapsed)
        self._start_times[timer_id] = time.perf_counter()
        return round(elapsed, self._precision)

    def reset(self, timer_id: Optional[str] = None) -> None:
        if timer_id:
            self._start_times.pop(timer_id, None)
            self._accumulated.pop(timer_id, None)
            self._counts.pop(timer_id, None)
            self._laps.pop(timer_id, None)
        else:
            self._start_times.clear()
            self._accumulated.clear()
            self._counts.clear()
            self._laps.clear()

    def get_stats(self, timer_id: str) -> Dict[str, Any]:
        laps = self._laps.get(timer_id, [])
        if not laps:
            return {"count": 0, "total": 0.0, "avg": 0.0}
        total = sum(laps)
        count = len(laps)
        return {
            "count": count,
            "total": round(total, self._precision),
            "avg": round(total / count, self._precision),
            "min": round(min(laps), self._precision),
            "max": round(max(laps), self._precision),
            "median": round(statistics.median(laps), self._precision) if len(laps) > 1 else round(laps[0], self._precision),
            "p95": round(self._percentile(laps, 95), self._precision),
            "p99": round(self._percentile(laps, 99), self._precision),
        }

    def _percentile(self, data: List[float], percentile: float) -> float:
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = math.ceil(len(sorted_data) * percentile / 100) - 1
        return sorted_data[max(0, min(index, len(sorted_data) - 1))]

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        return {tid: self.get_stats(tid) for tid in self._laps}


class MemoryProfiler:
    """Profiles memory usage during rule evaluation."""

    def __init__(self, config: ProfilerConfig):
        self.config = config
        self._snapshots: List[MemoryStats] = []
        self.logger = logging.getLogger(f"{__name__}.MemoryProfiler")

    def take_snapshot(self, description: str = "") -> MemoryStats:
        gc.collect()
        rss = 0
        vms = 0
        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            rss = mem_info.rss
            vms = mem_info.vms
        except ImportError:
            pass
        gc_objects = len(gc.get_objects())
        gen_counts = [len(gc.get_objects(i)) for i in range(3)]
        obj_types = {}
        if self.config.depth in (ProfilingDepth.DEEP, ProfilingDepth.EXTREME):
            for obj in gc.get_objects():
                type_name = type(obj).__name__
                obj_types[type_name] = obj_types.get(type_name, 0) + 1
        stats = MemoryStats(
            timestamp=datetime.utcnow().isoformat(),
            rss_bytes=rss,
            vms_bytes=vms,
            gc_objects=gc_objects,
            gc_generations=gen_counts,
            objects_by_type=obj_types,
            description=description,
        )
        self._snapshots.append(stats)
        return stats

    def get_delta(self, idx_a: int = 0, idx_b: int = -1) -> Dict[str, Any]:
        if len(self._snapshots) < 2:
            return {}
        a = self._snapshots[idx_a]
        b = self._snapshots[idx_b]
        return {
            "rss_delta_bytes": b.rss_bytes - a.rss_bytes,
            "rss_delta_mb": (b.rss_bytes - a.rss_bytes) / (1024 * 1024),
            "vms_delta_bytes": b.vms_bytes - a.vms_bytes,
            "vms_delta_mb": (b.vms_bytes - a.vms_bytes) / (1024 * 1024),
            "gc_objects_delta": b.gc_objects - a.gc_objects,
            "from": a.description,
            "to": b.description,
            "time_delta_seconds": (
                datetime.fromisoformat(b.timestamp) - datetime.fromisoformat(a.timestamp)
            ).total_seconds(),
        }

    def get_summary(self) -> Dict[str, Any]:
        if not self._snapshots:
            return {"error": "no snapshots"}
        first = self._snapshots[0]
        last = self._snapshots[-1]
        peak_rss = max(s.rss_bytes for s in self._snapshots)
        avg_gc = statistics.mean(s.gc_objects for s in self._snapshots) if len(self._snapshots) > 1 else self._snapshots[0].gc_objects
        return {
            "snapshots_taken": len(self._snapshots),
            "start_rss_mb": first.rss_bytes / (1024 * 1024),
            "end_rss_mb": last.rss_bytes / (1024 * 1024),
            "delta_rss_mb": (last.rss_bytes - first.rss_bytes) / (1024 * 1024),
            "peak_rss_mb": peak_rss / (1024 * 1024),
            "avg_gc_objects": avg_gc,
            "start_gc_objects": first.gc_objects,
            "end_gc_objects": last.gc_objects,
            "generations": last.gc_generations,
        }

    def get_snapshots(self) -> List[MemoryStats]:
        return list(self._snapshots)


class CacheProfiler:
    """Profiles cache efficiency for rule evaluation."""

    def __init__(self, config: ProfilerConfig):
        self.config = config
        self._requests: int = 0
        self._hits: int = 0
        self._misses: int = 0
        self._entries_by_rule: Dict[str, Dict[str, int]] = defaultdict(lambda: {"hits": 0, "misses": 0})
        self._lookup_times: List[float] = []
        self._stale_entries: int = 0
        self._evictions: int = 0
        self.logger = logging.getLogger(f"{__name__}.CacheProfiler")

    def record_lookup(self, rule_id: str, hit: bool, lookup_time_ms: float, ttl_remaining: Optional[float] = None) -> None:
        self._requests += 1
        self._lookup_times.append(lookup_time_ms)
        entry = self._entries_by_rule[rule_id]
        if hit:
            self._hits += 1
            entry["hits"] += 1
        else:
            self._misses += 1
            entry["misses"] += 1

    def record_eviction(self) -> None:
        self._evictions += 1

    def record_stale(self) -> None:
        self._stale_entries += 1

    def reset(self) -> None:
        self._requests = 0
        self._hits = 0
        self._misses = 0
        self._entries_by_rule.clear()
        self._lookup_times.clear()
        self._stale_entries = 0
        self._evictions = 0

    def get_stats(self) -> CacheEfficiencyStats:
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        avg_lookup = statistics.mean(self._lookup_times) if self._lookup_times else 0.0
        return CacheEfficiencyStats(
            total_requests=self._requests,
            hits=self._hits,
            misses=self._misses,
            hit_rate=hit_rate,
            avg_ttl_remaining=0.0,
            entries_by_rule=dict(self._entries_by_rule),
            stale_entries=self._stale_entries,
            memory_estimate_bytes=self._requests * 512,
            eviction_count=self._evictions,
            avg_lookup_time_ms=avg_lookup,
        )

    def get_rule_rankings(self) -> List[Dict[str, Any]]:
        rankings = []
        for rule_id, stats in self._entries_by_rule.items():
            total = stats["hits"] + stats["misses"]
            hit_rate = stats["hits"] / total if total > 0 else 0.0
            rankings.append({
                "rule_id": rule_id,
                "hits": stats["hits"],
                "misses": stats["misses"],
                "hit_rate": hit_rate,
                "total": total,
            })
        rankings.sort(key=lambda x: x["hit_rate"])
        return rankings


class BottleneckDetector:
    """Identifies performance bottlenecks in rule evaluation."""

    def __init__(self, config: ProfilerConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.BottleneckDetector")

    def detect_bottlenecks(self, timings: Dict[str, RuleTimingStats]) -> List[BottleneckInfo]:
        bottlenecks = []
        if not timings:
            return bottlenecks
        all_avg = statistics.mean(s.avg_time_ms for s in timings.values()) if len(timings) > 0 else 0
        all_max = max(s.max_time_ms for s in timings.values()) if timings else 0
        for rule_id, stats in timings.items():
            if stats.avg_time_ms > self.config.bottleneck_threshold_ms:
                severity = self._classify_severity(stats.avg_time_ms, all_avg)
                suggestion = self._generate_suggestion(stats)
                bottlenecks.append(BottleneckInfo(
                    rule_id=rule_id,
                    rule_name=stats.rule_name,
                    metric="avg_time_ms",
                    value=stats.avg_time_ms,
                    threshold=self.config.bottleneck_threshold_ms,
                    severity=severity,
                    suggestion=suggestion,
                    context={
                        "total_time_ms": stats.total_time_ms,
                        "max_time_ms": stats.max_time_ms,
                        "p95_time_ms": stats.p95_time_ms,
                        "count": stats.count,
                        "timeout_ms": stats.timeout_ms,
                        "timeout_hits": stats.timeout_hits,
                    },
                ))
            if stats.timeout_hits > 0:
                bottlenecks.append(BottleneckInfo(
                    rule_id=rule_id,
                    rule_name=stats.rule_name,
                    metric="timeout_hits",
                    value=stats.timeout_hits,
                    threshold=0,
                    severity="critical",
                    suggestion=f"Rule has {stats.timeout_hits} timeout(s). Increase timeout_ms or optimize patterns.",
                    context={"timeout_ms": stats.timeout_ms, "timeout_hits": stats.timeout_hits},
                ))
            if stats.max_time_ms > stats.timeout_ms * 0.9:
                bottlenecks.append(BottleneckInfo(
                    rule_id=rule_id,
                    rule_name=stats.rule_name,
                    metric="approaching_timeout",
                    value=stats.max_time_ms,
                    threshold=stats.timeout_ms * 0.9,
                    severity="warning",
                    suggestion=f"Max time {stats.max_time_ms:.1f}ms is approaching {stats.timeout_ms}ms timeout.",
                    context={"max_time_ms": stats.max_time_ms, "timeout_ms": stats.timeout_ms},
                ))
            if stats.std_dev_ms > stats.avg_time_ms * 0.5 and stats.count > 5:
                bottlenecks.append(BottleneckInfo(
                    rule_id=rule_id,
                    rule_name=stats.rule_name,
                    metric="high_variance",
                    value=stats.std_dev_ms,
                    threshold=stats.avg_time_ms * 0.5,
                    severity="info",
                    suggestion=f"High timing variance (std={stats.std_dev_ms:.1f}ms). Check for input-dependent performance.",
                    context={"avg_time_ms": stats.avg_time_ms, "std_dev_ms": stats.std_dev_ms},
                ))
        return bottlenecks

    def _classify_severity(self, value: float, baseline: float) -> str:
        ratio = value / max(baseline, 0.001)
        if value > 500 or ratio > 10:
            return "critical"
        if value > 200 or ratio > 5:
            return "high"
        if value > 100 or ratio > 3:
            return "medium"
        return "low"

    def _generate_suggestion(self, stats: RuleTimingStats) -> str:
        if stats.avg_time_ms > 500:
            return (
                f"Rule '{stats.rule_name}' is very slow (avg {stats.avg_time_ms:.1f}ms). "
                f"Review regex patterns, reduce keyword count, or simplify conditions."
            )
        if stats.avg_time_ms > 200:
            return (
                f"Rule '{stats.rule_name}' is slow (avg {stats.avg_time_ms:.1f}ms). "
                f"Consider optimizing patterns or increasing cache TTL."
            )
        if stats.max_time_ms > stats.timeout_ms * 0.8:
            return (
                f"Rule '{stats.rule_name}' occasionally spikes to {stats.max_time_ms:.1f}ms. "
                f"Investigate input patterns causing slow evaluations."
            )
        return (
            f"Rule '{stats.rule_name}' has moderate timing ({stats.avg_time_ms:.1f}ms avg). "
            f"Monitor for regression."
        )


class RunComparator:
    """Compares profiling data across different runs."""

    def __init__(self, config: ProfilerConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.RunComparator")

    def compare(self, current: ProfilingRun, previous: ProfilingRun) -> Dict[str, Any]:
        comparison = {
            "previous_run_id": previous.run_id,
            "current_run_id": current.run_id,
            "time_between_runs": (current.started_at - previous.started_at).total_seconds(),
            "summary_changes": {},
            "rule_changes": [],
            "bottleneck_changes": [],
            "cache_changes": {},
        }
        for key in current.summary:
            if key in previous.summary:
                curr_val = current.summary[key]
                prev_val = previous.summary[key]
                if isinstance(curr_val, (int, float)) and isinstance(prev_val, (int, float)):
                    delta = curr_val - prev_val
                    pct_change = ((curr_val - prev_val) / prev_val * 100) if prev_val != 0 else 0
                    comparison["summary_changes"][key] = {
                        "previous": prev_val,
                        "current": curr_val,
                        "delta": delta,
                        "percent_change": round(pct_change, 2),
                    }
        for rule_id, curr_stats in current.rule_timing.items():
            prev_stats = previous.rule_timing.get(rule_id)
            if prev_stats:
                avg_delta = curr_stats.avg_time_ms - prev_stats.avg_time_ms
                pct_change = (avg_delta / prev_stats.avg_time_ms * 100) if prev_stats.avg_time_ms > 0 else 0
                if abs(pct_change) > 5:
                    comparison["rule_changes"].append({
                        "rule_id": rule_id,
                        "rule_name": curr_stats.rule_name,
                        "previous_avg_ms": prev_stats.avg_time_ms,
                        "current_avg_ms": curr_stats.avg_time_ms,
                        "delta_ms": round(avg_delta, 4),
                        "percent_change": round(pct_change, 2),
                        "regression": avg_delta > 0,
                    })
        curr_bottleneck_ids = {b.rule_id for b in current.bottlenecks}
        prev_bottleneck_ids = {b.rule_id for b in previous.bottlenecks}
        new_bottlenecks = curr_bottleneck_ids - prev_bottleneck_ids
        resolved_bottlenecks = prev_bottleneck_ids - curr_bottleneck_ids
        comparison["bottleneck_changes"] = {
            "new": list(new_bottlenecks),
            "resolved": list(resolved_bottlenecks),
            "persistent": list(curr_bottleneck_ids & prev_bottleneck_ids),
        }
        if current.cache_efficiency and previous.cache_efficiency:
            curr_hit = current.cache_efficiency.hit_rate
            prev_hit = previous.cache_efficiency.hit_rate
            comparison["cache_changes"] = {
                "previous_hit_rate": prev_hit,
                "current_hit_rate": curr_hit,
                "delta": curr_hit - prev_hit,
                "improvement": curr_hit > prev_hit,
            }
        return comparison


class Profiler:
    """
    Performance profiler for rule evaluation.

    Profiles evaluation time, memory usage, cache efficiency, identifies bottlenecks,
    and compares results across multiple profiling runs.
    """

    def __init__(self, config: Optional[ProfilerConfig] = None):
        self.config = config or ProfilerConfig()
        self._timer = PrecisionTimer(self.config.timer_precision)
        self._memory_profiler = MemoryProfiler(self.config)
        self._cache_profiler = CacheProfiler(self.config)
        self._bottleneck_detector = BottleneckDetector(self.config)
        self._run_comparator = RunComparator(self.config)
        self._history: List[ProfilingRun] = []
        self._current_run: Optional[ProfilingRun] = None
        self._rule_timings: Dict[str, RuleTimingStats] = {}
        self._raw_timings: Dict[str, List[float]] = defaultdict(list)
        self._raw_inputs: Dict[str, List[str]] = defaultdict(list)
        self._run_count: int = 0
        self.logger = logging.getLogger(f"{__name__}.Profiler")

    def update_config(self, config_updates: Dict[str, Any]) -> None:
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self._timer = PrecisionTimer(self.config.timer_precision)
        self._bottleneck_detector = BottleneckDetector(self.config)
        self._run_comparator = RunComparator(self.config)
        self.logger.info("Profiler config updated with %d changes", len(config_updates))

    def start_run(self, label: Optional[str] = None) -> str:
        run_id = f"PROFILE-{uuid.uuid4().hex[:12]}"
        self._current_run = ProfilingRun(
            run_id=run_id,
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            config_snapshot=self._config_to_dict(),
            environment=self._capture_environment(),
            rule_timing={},
            memory_stats=[],
            cache_efficiency=None,
            bottlenecks=[],
            summary={},
        )
        self._rule_timings.clear()
        self._raw_timings.clear()
        self._raw_inputs.clear()
        self._timer.reset()
        self._cache_profiler.reset()
        if self.config.profiling_target in (ProfilingTarget.MEMORY_USAGE, ProfilingTarget.ALL):
            self._memory_profiler.take_snapshot(f"run_start_{label or run_id}")
        self.logger.info("Profiling run started: %s", run_id)
        return run_id

    def profile_rule_evaluation(
        self,
        rule: Rule,
        input_data: Union[str, Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        input_text = input_data if isinstance(input_data, str) else json.dumps(input_data)
        self._timer.start(f"rule_{rule.id}")
        if self.config.profiling_target in (ProfilingTarget.MEMORY_USAGE, ProfilingTarget.ALL):
            mem_before = self._memory_profiler.take_snapshot(f"before_{rule.id}")
        timeout_hit = False
        try:
            if context:
                _ = context.get("dummy", None)
            pattern_match_time = self._simulate_pattern_matching(rule, input_text)
            condition_time = self._simulate_condition_checking(rule, context or {})
            total_time = pattern_match_time + condition_time
            if total_time > rule.timeout_ms / 1000.0:
                timeout_hit = True
        except Exception as e:
            self.logger.warning("Error profiling rule %s: %s", rule.id, e)
            total_time = 0.0
        elapsed = self._timer.stop(f"rule_{rule.id}")
        self._raw_timings[rule.id].append(elapsed * 1000)
        self._raw_inputs[rule.id].append(input_text[:100])
        result = {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "duration_ms": elapsed * 1000,
            "timeout_hit": timeout_hit,
            "input_preview": input_text[:100],
        }
        if self.config.profiling_target in (ProfilingTarget.MEMORY_USAGE, ProfilingTarget.ALL):
            mem_after = self._memory_profiler.take_snapshot(f"after_{rule.id}")
            result["memory_delta_mb"] = (mem_after.rss_bytes - mem_before.rss_bytes) / (1024 * 1024)
        return result

    def profile_rule_batch(
        self,
        rules: List[Rule],
        inputs: List[Union[str, Dict[str, Any]]],
        contexts: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        results = []
        warmup_done = False
        for i, input_data in enumerate(inputs):
            if i < self.config.warmup_iterations and not warmup_done:
                for rule in rules[:3]:
                    self._simulate_pattern_matching(rule, str(input_data))
                if i == self.config.warmup_iterations - 1:
                    warmup_done = True
                    self._timer.reset()
                continue
            context = contexts[i] if contexts and i < len(contexts) else None
            for rule in rules:
                result = self.profile_rule_evaluation(rule, input_data, context)
                results.append(result)
                if self.config.sample_size and len(self._raw_timings.get(rule.id, [])) >= self.config.sample_size:
                    continue
            if all(len(self._raw_timings.get(r.id, [])) >= self.config.sample_size for r in rules):
                break
        return results

    def _simulate_pattern_matching(self, rule: Rule, input_text: str) -> float:
        import re
        start = time.perf_counter()
        for pattern in rule.patterns:
            for kw in pattern.keywords:
                _ = kw.lower() in input_text.lower()
            for regex_str in pattern.regex_patterns:
                try:
                    re.search(regex_str, input_text, re.IGNORECASE)
                except re.error:
                    pass
        return time.perf_counter() - start

    def _simulate_condition_checking(self, rule: Rule, context: Dict) -> float:
        start = time.perf_counter()
        for key, value in rule.conditions.items():
            _ = context.get(key) == value
        return time.perf_counter() - start

    def end_run(self) -> ProfilingRun:
        if not self._current_run:
            raise RuntimeError("No active profiling run")
        self._current_run.finished_at = datetime.utcnow()
        self._build_rule_timings()
        self._current_run.rule_timing = dict(self._rule_timings)
        if self.config.profiling_target in (ProfilingTarget.MEMORY_USAGE, ProfilingTarget.ALL):
            self._memory_profiler.take_snapshot("run_end")
            self._current_run.memory_stats = self._memory_profiler.get_snapshots()
        if self.config.profiling_target in (ProfilingTarget.CACHE_EFFICIENCY, ProfilingTarget.ALL):
            self._current_run.cache_efficiency = self._cache_profiler.get_stats()
        if self.config.detect_bottlenecks:
            self._current_run.bottlenecks = self._bottleneck_detector.detect_bottlenecks(self._rule_timings)
        self._current_run.summary = self._build_summary()
        if self.config.compare_with_previous and self._history:
            previous = self._history[-1]
            self._current_run.comparison = self._run_comparator.compare(self._current_run, previous)
            if previous.run_id:
                self._current_run.previous_run_id = previous.run_id
        self._history.append(self._current_run)
        if len(self._history) > self.config.max_history_runs:
            self._history = self._history[-self.config.max_history_runs:]
        self._run_count += 1
        if self.config.auto_export:
            self._export_run(self._current_run)
        self.logger.info(
            "Profiling run ended: %d rules, %.2f total time, %d bottlenecks",
            len(self._current_run.rule_timing),
            self._current_run.summary.get("total_evaluation_time_ms", 0),
            len(self._current_run.bottlenecks),
        )
        return self._current_run

    def _build_rule_timings(self) -> None:
        for rule_id, times in self._raw_timings.items():
            if not times:
                continue
            sorted_times = sorted(times)
            avg_ms = statistics.mean(times)
            self._rule_timings[rule_id] = RuleTimingStats(
                rule_id=rule_id,
                rule_name=rule_id,
                tier="unknown",
                rule_type="unknown",
                count=len(times),
                total_time_ms=sum(times),
                avg_time_ms=avg_ms,
                min_time_ms=min(times),
                max_time_ms=max(times),
                median_time_ms=statistics.median(times) if len(times) > 1 else times[0],
                p50_time_ms=self._percentile(times, 50),
                p95_time_ms=self._percentile(times, 95),
                p99_time_ms=self._percentile(times, 99),
                std_dev_ms=statistics.stdev(times) if len(times) > 1 else 0.0,
                timeout_ms=1000,
                timeout_hits=sum(1 for t in times if t > 1000),
            )

    def _percentile(self, data: List[float], p: float) -> float:
        if not data:
            return 0.0
        sorted_data = sorted(data)
        idx = max(0, min(len(sorted_data) - 1, int(len(sorted_data) * p / 100)))
        return sorted_data[idx]

    def _build_summary(self) -> Dict[str, Any]:
        total_time = sum(s.total_time_ms for s in self._rule_timings.values())
        total_rules = len(self._rule_timings)
        total_calls = sum(s.count for s in self._rule_timings.values())
        if total_calls > 0:
            overall_avg = total_time / total_calls
        else:
            overall_avg = 0.0
        timeout_total = sum(s.timeout_hits for s in self._rule_timings.values())
        slowest_rule = max(self._rule_timings.values(), key=lambda s: s.avg_time_ms) if self._rule_timings else None
        return {
            "run_id": self._current_run.run_id if self._current_run else "unknown",
            "total_rules_profiled": total_rules,
            "total_evaluations": total_calls,
            "total_evaluation_time_ms": round(total_time, 4),
            "overall_avg_time_ms": round(overall_avg, 4),
            "total_timeouts": timeout_total,
            "total_bottlenecks": len(self._current_run.bottlenecks) if self._current_run else 0,
            "slowest_rule_name": slowest_rule.rule_name if slowest_rule else None,
            "slowest_rule_avg_ms": round(slowest_rule.avg_time_ms, 4) if slowest_rule else 0,
            "profiling_target": self.config.profiling_target.value,
            "profiling_depth": self.config.depth.value,
        }

    def _capture_environment(self) -> Dict[str, Any]:
        env = {
            "python_version": __import__("sys").version,
            "platform": __import__("sys").platform,
            "timestamp": datetime.utcnow().isoformat(),
        }
        try:
            env["cpu_count"] = os.cpu_count()
        except Exception:
            pass
        try:
            import psutil
            env["memory_total_mb"] = psutil.virtual_memory().total / (1024 * 1024)
            env["memory_available_mb"] = psutil.virtual_memory().available / (1024 * 1024)
        except ImportError:
            pass
        return env

    def record_cache_lookup(self, rule_id: str, hit: bool, lookup_time_ms: float) -> None:
        self._cache_profiler.record_lookup(rule_id, hit, lookup_time_ms)

    def record_cache_eviction(self) -> None:
        self._cache_profiler.record_eviction()

    def get_rule_timing(self, rule_id: str) -> Optional[RuleTimingStats]:
        return self._rule_timings.get(rule_id)

    def get_bottlenecks(self, run: Optional[ProfilingRun] = None) -> List[BottleneckInfo]:
        target = run or self._current_run
        if not target:
            return []
        return list(target.bottlenecks)

    def get_cache_stats(self, run: Optional[ProfilingRun] = None) -> Optional[CacheEfficiencyStats]:
        target = run or self._current_run
        if not target:
            return None
        return target.cache_efficiency

    def get_memory_summary(self, run: Optional[ProfilingRun] = None) -> Dict[str, Any]:
        target = run or self._current_run
        if not target or not target.memory_stats:
            return {}
        memory_profiler = MemoryProfiler(self.config)
        memory_profiler._snapshots = target.memory_stats
        return memory_profiler.get_summary()

    def get_history(self) -> List[ProfilingRun]:
        return list(self._history)

    def get_latest_run(self) -> Optional[ProfilingRun]:
        return self._history[-1] if self._history else None

    def compare_runs(self, run_a_id: str, run_b_id: str) -> Optional[Dict[str, Any]]:
        run_a = next((r for r in self._history if r.run_id == run_a_id), None)
        run_b = next((r for r in self._history if r.run_id == run_b_id), None)
        if not run_a or not run_b:
            self.logger.warning("Cannot compare runs: one or both run IDs not found")
            return None
        return self._run_comparator.compare(run_b, run_a)

    def generate_report(self, run: Optional[ProfilingRun] = None, format: Optional[ReportFormat] = None) -> str:
        target = run or self._current_run
        if not target:
            return "No profiling data available"
        fmt = format or self.config.report_format
        if fmt == ReportFormat.JSON:
            return self._generate_json_report(target)
        elif fmt == ReportFormat.YAML:
            return self._generate_yaml_report(target)
        elif fmt == ReportFormat.TEXT:
            return self._generate_text_report(target)
        elif fmt == ReportFormat.MARKDOWN:
            return self._generate_markdown_report(target)
        return self._generate_json_report(target)

    def _generate_json_report(self, run: ProfilingRun) -> str:
        data = {
            "run_id": run.run_id,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat(),
            "duration_seconds": (run.finished_at - run.started_at).total_seconds(),
            "config": run.config_snapshot,
            "environment": run.environment,
            "summary": run.summary,
            "rule_timing": {
                rid: {
                    "rule_name": s.rule_name,
                    "count": s.count,
                    "total_time_ms": round(s.total_time_ms, 4),
                    "avg_time_ms": round(s.avg_time_ms, 4),
                    "min_time_ms": round(s.min_time_ms, 4),
                    "max_time_ms": round(s.max_time_ms, 4),
                    "p95_time_ms": round(s.p95_time_ms, 4),
                    "p99_time_ms": round(s.p99_time_ms, 4),
                    "std_dev_ms": round(s.std_dev_ms, 4),
                    "timeout_hits": s.timeout_hits,
                }
                for rid, s in run.rule_timing.items()
            },
            "bottlenecks": [
                {
                    "rule_id": b.rule_id,
                    "rule_name": b.rule_name,
                    "metric": b.metric,
                    "value": b.value,
                    "threshold": b.threshold,
                    "severity": b.severity,
                    "suggestion": b.suggestion,
                }
                for b in run.bottlenecks
            ],
        }
        if run.comparison:
            data["comparison"] = run.comparison
        return json.dumps(data, indent=2, default=str)

    def _generate_yaml_report(self, run: ProfilingRun) -> str:
        data = {
            "run_id": run.run_id,
            "started_at": run.started_at.isoformat(),
            "duration_seconds": (run.finished_at - run.started_at).total_seconds(),
            "summary": run.summary,
            "bottlenecks_count": len(run.bottlenecks),
            "rules_profiled": len(run.rule_timing),
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    def _generate_text_report(self, run: ProfilingRun) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append(f"PROFILING REPORT: {run.run_id}")
        lines.append("=" * 60)
        duration = (run.finished_at - run.started_at).total_seconds()
        lines.append(f"  Duration: {duration:.2f}s")
        lines.append(f"  Rules profiled: {run.summary.get('total_rules_profiled', 0)}")
        lines.append(f"  Total evaluations: {run.summary.get('total_evaluations', 0)}")
        lines.append(f"  Total time: {run.summary.get('total_evaluation_time_ms', 0):.2f}ms")
        lines.append(f"  Overall avg: {run.summary.get('overall_avg_time_ms', 0):.4f}ms")
        lines.append(f"  Timeouts: {run.summary.get('total_timeouts', 0)}")
        lines.append("")
        if run.rule_timing:
            lines.append("--- Rule Timings (top 10 by avg time) ---")
            sorted_rules = sorted(run.rule_timing.values(), key=lambda s: s.avg_time_ms, reverse=True)[:10]
            lines.append(f"  {'Rule':<30} {'Avg(ms)':<10} {'Max(ms)':<10} {'P95(ms)':<10} {'Count':<8}")
            lines.append(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")
            for s in sorted_rules:
                lines.append(f"  {s.rule_name:<30} {s.avg_time_ms:<10.4f} {s.max_time_ms:<10.4f} {s.p95_time_ms:<10.4f} {s.count:<8}")
        if run.bottlenecks:
            lines.append("")
            lines.append("--- Bottlenecks ---")
            for b in run.bottlenecks:
                lines.append(f"  [{b.severity.upper()}] {b.rule_name}: {b.metric}={b.value:.2f} (threshold={b.threshold})")
                lines.append(f"    {b.suggestion}")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def _generate_markdown_report(self, run: ProfilingRun) -> str:
        lines = []
        lines.append(f"# Profiling Report: {run.run_id}")
        lines.append("")
        lines.append(f"**Started:** {run.started_at.isoformat()}")
        lines.append(f"**Finished:** {run.finished_at.isoformat()}")
        duration = (run.finished_at - run.started_at).total_seconds()
        lines.append(f"**Duration:** {duration:.2f}s")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Rules Profiled | {run.summary.get('total_rules_profiled', 0)} |")
        lines.append(f"| Total Evaluations | {run.summary.get('total_evaluations', 0)} |")
        lines.append(f"| Total Time | {run.summary.get('total_evaluation_time_ms', 0):.2f}ms |")
        lines.append(f"| Overall Avg | {run.summary.get('overall_avg_time_ms', 0):.4f}ms |")
        lines.append(f"| Timeouts | {run.summary.get('total_timeouts', 0)} |")
        lines.append("")
        if run.bottlenecks:
            lines.append("## Bottlenecks")
            lines.append("")
            for b in run.bottlenecks:
                lines.append(f"- **[{b.severity.upper()}] {b.rule_name}**: {b.suggestion}")
        lines.append("")
        return "\n".join(lines)

    def export_report(self, run: Optional[ProfilingRun] = None, filepath: Optional[str] = None) -> str:
        target = run or self._current_run
        if not target:
            raise RuntimeError("No profiling data to export")
        return self._export_run(target, filepath)

    def _export_run(self, run: ProfilingRun, filepath: Optional[str] = None) -> str:
        report = self._generate_json_report(run)
        if filepath:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report, encoding="utf-8")
            self.logger.info("Report exported to %s", filepath)
            return str(path)
        if self.config.export_dir:
            path = Path(self.config.export_dir) / f"profile_{run.run_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report, encoding="utf-8")
            self.logger.info("Report exported to %s", path)
            return str(path)
        return report

    def load_history(self, dirpath: str) -> int:
        path = Path(dirpath)
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"History directory not found: {dirpath}")
        loaded = 0
        for filepath in sorted(path.glob("profile_*.json")):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                run = self._deserialize_run(data)
                self._history.append(run)
                loaded += 1
            except Exception as e:
                self.logger.warning("Failed to load %s: %s", filepath, e)
        self.logger.info("Loaded %d profiling runs from %s", loaded, dirpath)
        return loaded

    def _deserialize_run(self, data: Dict) -> ProfilingRun:
        rule_timing = {}
        for rid, stats_data in data.get("rule_timing", {}).items():
            rule_timing[rid] = RuleTimingStats(
                rule_id=rid,
                rule_name=stats_data.get("rule_name", rid),
                tier=stats_data.get("tier", "unknown"),
                rule_type=stats_data.get("rule_type", "unknown"),
                count=stats_data.get("count", 0),
                total_time_ms=stats_data.get("total_time_ms", 0),
                avg_time_ms=stats_data.get("avg_time_ms", 0),
                min_time_ms=stats_data.get("min_time_ms", 0),
                max_time_ms=stats_data.get("max_time_ms", 0),
                median_time_ms=stats_data.get("median_time_ms", 0),
                p50_time_ms=stats_data.get("p50_time_ms", 0),
                p95_time_ms=stats_data.get("p95_time_ms", 0),
                p99_time_ms=stats_data.get("p99_time_ms", 0),
                std_dev_ms=stats_data.get("std_dev_ms", 0),
                timeout_ms=stats_data.get("timeout_ms", 1000),
                timeout_hits=stats_data.get("timeout_hits", 0),
            )
        bottlenecks = [
            BottleneckInfo(**b) for b in data.get("bottlenecks", [])
        ]
        return ProfilingRun(
            run_id=data["run_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            finished_at=datetime.fromisoformat(data["finished_at"]),
            config_snapshot=data.get("config", {}),
            environment=data.get("environment", {}),
            rule_timing=rule_timing,
            memory_stats=[],
            cache_efficiency=None,
            bottlenecks=bottlenecks,
            summary=data.get("summary", {}),
            previous_run_id=data.get("previous_run_id"),
            comparison=data.get("comparison"),
        )

    def _config_to_dict(self) -> Dict[str, Any]:
        return {
            "profiling_target": self.config.profiling_target.value,
            "depth": self.config.depth.value,
            "sample_size": self.config.sample_size,
            "warmup_iterations": self.config.warmup_iterations,
            "track_memory_delta": self.config.track_memory_delta,
            "detect_bottlenecks": self.config.detect_bottlenecks,
            "bottleneck_threshold_ms": self.config.bottleneck_threshold_ms,
            "compare_with_previous": self.config.compare_with_previous,
        }

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "profiling_target": {
                "type": "string",
                "enum": [e.value for e in ProfilingTarget],
                "default": "all",
            },
            "depth": {
                "type": "string",
                "enum": [e.value for e in ProfilingDepth],
                "default": "normal",
            },
            "sample_size": {
                "type": "integer",
                "minimum": 10,
                "maximum": 100000,
                "default": 1000,
            },
            "bottleneck_threshold_ms": {
                "type": "number",
                "minimum": 1,
                "default": 50.0,
            },
            "detect_bottlenecks": {"type": "boolean", "default": True},
            "compare_with_previous": {"type": "boolean", "default": True},
            "cache_simulation": {"type": "boolean", "default": True},
            "auto_export": {"type": "boolean", "default": False},
        }
