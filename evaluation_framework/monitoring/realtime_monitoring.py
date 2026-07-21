"""Real-time monitoring of rule execution with streaming metrics and live dashboards."""
import logging
import time
import threading
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict, deque
import statistics

logger = logging.getLogger(__name__)


@dataclass
class ExecutionEvent:
    execution_id: str
    rule_id: str
    rule_name: str
    tier: str
    duration_ms: float
    result: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LiveMetricsSnapshot:
    active_rules: int
    evaluations_last_minute: int
    avg_latency_ms: float
    p95_latency_ms: float
    error_rate: float
    cache_hit_rate: float
    throughput_per_sec: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RealtimeMonitoring:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._event_buffer: deque = deque(maxlen=self.config.get("buffer_size", 10000))
        self._metrics_snapshot: Optional[LiveMetricsSnapshot] = None
        self._monitored_rules: Dict[str, Dict[str, Any]] = {}
        self._listeners: List[Callable[[ExecutionEvent], None]] = []
        self._window_seconds = self.config.get("window_seconds", 60)
        self._lock = threading.RLock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._event_count = 0
        self._error_count = 0
        logger.info("RealtimeMonitoring initialized (buffer=%d, window=%ds)",
                     self._event_buffer.maxlen, self._window_seconds)

    def monitor(self, rule_execution: Dict[str, Any]) -> ExecutionEvent:
        event = ExecutionEvent(
            execution_id=rule_execution.get("execution_id", rule_execution.get("id", "unknown")),
            rule_id=rule_execution.get("rule_id", "unknown"),
            rule_name=rule_execution.get("rule_name", rule_execution.get("name", "unknown")),
            tier=rule_execution.get("tier", "unknown"),
            duration_ms=float(rule_execution.get("duration_ms", 0)),
            result=rule_execution.get("result", "unknown"),
            context=rule_execution.get("context", {}),
        )

        with self._lock:
            self._event_buffer.append(event)
            self._event_count += 1
            if event.result == "error":
                self._error_count += 1

            if event.rule_id not in self._monitored_rules:
                self._monitored_rules[event.rule_id] = {
                    "rule_id": event.rule_id,
                    "rule_name": event.rule_name,
                    "tier": event.tier,
                    "total_evaluations": 0,
                    "total_errors": 0,
                    "avg_latency_ms": 0.0,
                }

            stats = self._monitored_rules[event.rule_id]
            stats["total_evaluations"] += 1
            if event.result == "error":
                stats["total_errors"] += 1
            stats["avg_latency_ms"] = (
                (stats["avg_latency_ms"] * (stats["total_evaluations"] - 1) + event.duration_ms)
                / stats["total_evaluations"]
            )

        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                logger.error("Listener error: %s", e)

        return event

    def monitor_many(self, executions: List[Dict[str, Any]]) -> List[ExecutionEvent]:
        return [self.monitor(ex) for ex in executions]

    def register_listener(self, listener: Callable[[ExecutionEvent], None]) -> None:
        self._listeners.append(listener)
        logger.debug("Registered listener (%d total)", len(self._listeners))

    def start_auto_snapshot(self, interval_seconds: float = 5.0) -> None:
        if self._running:
            logger.warning("Auto-snapshot already running")
            return

        self._running = True

        def _snapshot_loop() -> None:
            while self._running:
                self._compute_snapshot()
                time.sleep(interval_seconds)

        self._monitor_thread = threading.Thread(target=_snapshot_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Auto-snapshot started (interval=%.1fs)", interval_seconds)

    def stop_auto_snapshot(self) -> None:
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("Auto-snapshot stopped")

    def get_live_metrics(self) -> LiveMetricsSnapshot:
        return self._compute_snapshot()

    def get_rule_stats(self, rule_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if rule_id:
                stats = self._monitored_rules.get(rule_id)
                return dict(stats) if stats else {}

            total_evals = sum(s["total_evaluations"] for s in self._monitored_rules.values())
            total_errors = sum(s["total_errors"] for s in self._monitored_rules.values())

            return {
                "total_rules_monitored": len(self._monitored_rules),
                "total_evaluations": total_evals,
                "total_errors": total_errors,
                "overall_error_rate": total_errors / max(total_evals, 1),
                "by_tier": dict(Counter(
                    s["tier"] for s in self._monitored_rules.values()
                )),
            }

    def _compute_snapshot(self) -> LiveMetricsSnapshot:
        with self._lock:
            cutoff = datetime.now(timezone.utc).timestamp() - self._window_seconds
            recent = [
                e for e in self._event_buffer
                if e.timestamp.timestamp() >= cutoff
            ]

            if not recent:
                self._metrics_snapshot = LiveMetricsSnapshot(
                    active_rules=len(self._monitored_rules),
                    evaluations_last_minute=0,
                    avg_latency_ms=0.0,
                    p95_latency_ms=0.0,
                    error_rate=0.0,
                    cache_hit_rate=0.0,
                    throughput_per_sec=0.0,
                )
            else:
                durations = [e.duration_ms for e in recent]
                errors = sum(1 for e in recent if e.result == "error")
                sorted_durs = sorted(durations)
                cache_hits = sum(1 for e in recent if e.result == "cache_hit")

                self._metrics_snapshot = LiveMetricsSnapshot(
                    active_rules=len(self._monitored_rules),
                    evaluations_last_minute=len(recent),
                    avg_latency_ms=round(statistics.mean(durations), 3),
                    p95_latency_ms=round(sorted_durs[int(len(sorted_durs) * 0.95)], 3),
                    error_rate=errors / max(len(recent), 1),
                    cache_hit_rate=cache_hits / max(len(recent), 1),
                    throughput_per_sec=round(len(recent) / self._window_seconds, 1),
                )

        return self._metrics_snapshot


from collections import Counter
