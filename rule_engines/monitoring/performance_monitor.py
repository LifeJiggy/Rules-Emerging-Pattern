"""Performance monitoring for rule engine with real-time metrics, alerts, and dashboards."""
import logging
import time
import statistics
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


@dataclass
class RuleMetrics:
    rule_id: str
    rule_name: str
    tier: str
    count: int
    total_time_ms: float
    min_time_ms: float
    max_time_ms: float
    avg_time_ms: float
    p50_time_ms: float
    p95_time_ms: float
    p99_time_ms: float
    errors: int
    error_rate: float
    cache_hits: int
    cache_misses: int


@dataclass
class PerformanceSnapshot:
    avg_latency_ms: float
    p95_latency_ms: float
    throughput_per_sec: float
    error_rate: float
    cache_hit_rate: float
    active_rules: int
    total_evaluations: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PerformanceMonitor:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._metrics: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "count": 0, "total_time": 0.0, "min_time": float("inf"),
            "max_time": 0.0, "errors": 0, "cache_hits": 0, "cache_misses": 0,
            "durations": deque(maxlen=1000),
        })
        self._start_times: Dict[str, float] = {}
        self._history: deque = deque(maxlen=self.config.get("history_size", 10000))
        self._snapshots: deque = deque(maxlen=self.config.get("snapshots_size", 1000))
        self._thresholds: Dict[str, float] = {
            "latency_ms": self.config.get("latency_threshold_ms", 500.0),
            "error_rate": self.config.get("error_rate_threshold", 0.05),
            "cache_hit_rate": self.config.get("cache_hit_threshold", 0.5),
        }
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._total_ops = 0
        self._total_errors = 0
        self._monitoring_active = False
        self._slow_ops: Dict[str, float] = {}
        logger.info("PerformanceMonitor initialized (thresholds=%s)", self._thresholds)

    def start_timer(self, operation_id: str) -> None:
        self._start_times[operation_id] = time.perf_counter()

    def end_timer(self, operation_id: str, rule_id: Optional[str] = None,
                  success: bool = True, cached: bool = False) -> float:
        if operation_id not in self._start_times:
            return 0.0
        elapsed = (time.perf_counter() - self._start_times[operation_id]) * 1000
        del self._start_times[operation_id]

        self._total_ops += 1
        if not success:
            self._total_errors += 1

        if rule_id:
            m = self._metrics[rule_id]
            m["count"] += 1
            m["total_time"] += elapsed
            m["min_time"] = min(m["min_time"], elapsed)
            m["max_time"] = max(m["max_time"], elapsed)
            m["durations"].append(elapsed)
            if not success:
                m["errors"] += 1
            if cached:
                m["cache_hits"] += 1
            else:
                m["cache_misses"] += 1

            if elapsed > self._thresholds["latency_ms"]:
                self._slow_ops[rule_id] = elapsed

        self._history.append({
            "operation_id": operation_id, "rule_id": rule_id,
            "elapsed_ms": elapsed, "success": success, "cached": cached,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return elapsed

    def record(self, rule_id: str, elapsed_ms: float, success: bool = True,
               cached: bool = False) -> None:
        self._total_ops += 1
        if not success:
            self._total_errors += 1
        m = self._metrics[rule_id]
        m["count"] += 1
        m["total_time"] += elapsed_ms
        m["min_time"] = min(m["min_time"], elapsed_ms)
        m["max_time"] = max(m["max_time"], elapsed_ms)
        m["durations"].append(elapsed_ms)
        if not success:
            m["errors"] += 1
        if cached:
            m["cache_hits"] += 1
        else:
            m["cache_misses"] += 1

    def collect_snapshot(self) -> PerformanceSnapshot:
        all_durations = []
        total_rules = 0
        for mid, m in self._metrics.items():
            total_rules += 1
            all_durations.extend(list(m["durations"]))

        if not all_durations:
            snapshot = PerformanceSnapshot(
                avg_latency_ms=0, p95_latency_ms=0,
                throughput_per_sec=0, error_rate=0,
                cache_hit_rate=0, active_rules=total_rules,
                total_evaluations=self._total_ops,
            )
        else:
            sorted_d = sorted(all_durations)
            cache_hits = sum(m["cache_hits"] for m in self._metrics.values())
            cache_misses = sum(m["cache_misses"] for m in self._metrics.values())
            total_cache = cache_hits + cache_misses
            window_seconds = 60
            recent = [h for h in list(self._history)[-100:] if
                      (datetime.now(timezone.utc) - datetime.fromisoformat(h["timestamp"])).total_seconds() < window_seconds]

            snapshot = PerformanceSnapshot(
                avg_latency_ms=round(statistics.mean(all_durations), 3),
                p95_latency_ms=round(sorted_d[int(len(sorted_d) * 0.95)], 3),
                throughput_per_sec=round(len(recent) / window_seconds, 1),
                error_rate=self._total_errors / max(self._total_ops, 1),
                cache_hit_rate=cache_hits / max(total_cache, 1),
                active_rules=total_rules,
                total_evaluations=self._total_ops,
            )
        self._snapshots.append(snapshot)

        for listener in self._listeners:
            try:
                listener(snapshot.__dict__)
            except Exception as e:
                logger.error("Snapshot listener error: %s", e)
        return snapshot

    def get_metrics(self, rule_id: Optional[str] = None) -> Dict[str, Any]:
        if rule_id:
            m = self._metrics.get(rule_id)
            if not m:
                return {}
            return self._build_rule_metrics(rule_id, "", "", m).__dict__
        return {
            rid: self._build_rule_metrics(rid, "", "", m).__dict__
            for rid, m in self._metrics.items()
        }

    def get_slow_operations(self, threshold_ms: float = 100.0) -> Dict[str, float]:
        slow: Dict[str, float] = {}
        metrics = self.get_metrics()
        for rid, m in metrics.items():
            avg_time = m.get("avg_time_ms", 0)
            if avg_time > threshold_ms:
                slow[rid] = avg_time
        return slow

    def get_snapshots(self, n: int = 10) -> List[PerformanceSnapshot]:
        return list(self._snapshots)[-n:]

    def register_listener(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        self._listeners.append(listener)

    def get_statistics(self) -> Dict[str, Any]:
        snapshots = list(self._snapshots)
        if snapshots:
            latest = snapshots[-1]
            recent_snapshot = {
                "avg_latency_ms": latest.avg_latency_ms,
                "p95_latency_ms": latest.p95_latency_ms,
                "throughput": latest.throughput_per_sec,
                "error_rate": latest.error_rate,
                "cache_hit_rate": latest.cache_hit_rate,
            }
        else:
            recent_snapshot = {}
        return {
            "total_operations": self._total_ops,
            "total_errors": self._total_errors,
            "active_rules": sum(1 for m in self._metrics.values() if m["count"] > 0),
            "slow_operations": len(self._slow_ops),
            "recent_snapshot": recent_snapshot,
            "listeners": len(self._listeners),
        }

    def _build_rule_metrics(self, rule_id: str, rule_name: str, tier: str,
                            m: Dict[str, Any]) -> RuleMetrics:
        durations = list(m["durations"])
        count = m["count"]
        avg = m["total_time"] / count if count > 0 else 0
        sorted_d = sorted(durations)
        return RuleMetrics(
            rule_id=rule_id, rule_name=rule_name, tier=tier,
            count=count, total_time_ms=round(m["total_time"], 3),
            min_time_ms=round(m["min_time"], 3) if m["min_time"] != float("inf") else 0,
            max_time_ms=round(m["max_time"], 3),
            avg_time_ms=round(avg, 3),
            p50_time_ms=round(sorted_d[len(sorted_d) // 2], 3) if sorted_d else 0,
            p95_time_ms=round(sorted_d[int(len(sorted_d) * 0.95)], 3) if sorted_d else 0,
            p99_time_ms=round(sorted_d[int(len(sorted_d) * 0.99)], 3) if sorted_d else 0,
            errors=m["errors"],
            error_rate=m["errors"] / max(count, 1),
            cache_hits=m["cache_hits"],
            cache_misses=m["cache_misses"],
        )
