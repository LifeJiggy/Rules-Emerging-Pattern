"""Tier Metrics Collector - per-tier performance and violation metrics."""
import json
import logging
import time
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict, deque

from rules_emerging_pattern.models.rule import RuleTier, RuleEvaluationRequest, RuleSeverity
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ActionTaken

logger = logging.getLogger(__name__)


class MetricWindow(str, Enum):
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
    SIX_HOURS = "6h"
    TWENTY_FOUR_HOURS = "24h"


WINDOW_SECONDS = {
    MetricWindow.ONE_MINUTE: 60,
    MetricWindow.FIVE_MINUTES: 300,
    MetricWindow.FIFTEEN_MINUTES: 900,
    MetricWindow.ONE_HOUR: 3600,
    MetricWindow.SIX_HOURS: 21600,
    MetricWindow.TWENTY_FOUR_HOURS: 86400,
}


class MetricsExportFormat(str, Enum):
    JSON = "json"
    PROMETHEUS = "prometheus"


class TierMetrics:
    def __init__(self, tier: str):
        self.tier: str = tier
        self.evaluation_count: int = 0
        self.violation_count: int = 0
        self.block_count: int = 0
        self.warning_count: int = 0
        self.suggestion_count: int = 0
        self.critical_violation_count: int = 0
        self.total_processing_time_ms: float = 0.0
        self.min_processing_time_ms: float = 0.0
        self.max_processing_time_ms: float = 0.0
        self.total_score_sum: float = 0.0
        self.confidence_sum: float = 0.0
        self.timeout_count: int = 0
        self.error_count: int = 0
        self.severity_counts: Dict[str, int] = {}
        self.action_counts: Dict[str, int] = {}
        self.violation_type_counts: Dict[str, int] = {}
        self.last_evaluated_at: Optional[datetime] = None
        self.first_evaluated_at: Optional[datetime] = None
        self.peak_concurrent: int = 0
        self.current_concurrent: int = 0

    def record(
        self, result: ValidationResult, processing_time_ms: float,
        timed_out: bool = False, error: Optional[str] = None,
    ) -> None:
        self.evaluation_count += 1
        self.total_processing_time_ms += processing_time_ms
        if self.min_processing_time_ms == 0 or processing_time_ms < self.min_processing_time_ms:
            self.min_processing_time_ms = processing_time_ms
        if processing_time_ms > self.max_processing_time_ms:
            self.max_processing_time_ms = processing_time_ms
        self.total_score_sum += result.total_score
        self.confidence_sum += result.confidence
        now = datetime.utcnow()
        self.last_evaluated_at = now
        if self.first_evaluated_at is None:
            self.first_evaluated_at = now
        if timed_out:
            self.timeout_count += 1
        if error:
            self.error_count += 1
        for violation in result.violations:
            self.violation_count += 1
            sev = violation.rule_severity.value
            self.severity_counts[sev] = self.severity_counts.get(sev, 0) + 1
            act = violation.action_taken.value
            self.action_counts[act] = self.action_counts.get(act, 0) + 1
            vtype = violation.violation_type.value
            self.violation_type_counts[vtype] = self.violation_type_counts.get(vtype, 0) + 1
            if violation.blocked:
                self.block_count += 1
            if violation.action_taken == ActionTaken.WARNING:
                self.warning_count += 1
            if violation.is_critical():
                self.critical_violation_count += 1
        for _ in result.suggestions:
            self.suggestion_count += 1

    def get_average_processing_time(self) -> float:
        if self.evaluation_count == 0:
            return 0.0
        return round(self.total_processing_time_ms / self.evaluation_count, 2)

    def get_average_score(self) -> float:
        if self.evaluation_count == 0:
            return 1.0
        return round(self.total_score_sum / self.evaluation_count, 4)

    def get_average_confidence(self) -> float:
        if self.evaluation_count == 0:
            return 1.0
        return round(self.confidence_sum / self.evaluation_count, 4)

    def get_violation_rate(self) -> float:
        if self.evaluation_count == 0:
            return 0.0
        return round(self.violation_count / self.evaluation_count, 4)

    def get_block_rate(self) -> float:
        if self.evaluation_count == 0:
            return 0.0
        return round(self.block_count / self.evaluation_count, 4)

    def get_to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "evaluation_count": self.evaluation_count,
            "violation_count": self.violation_count,
            "block_count": self.block_count,
            "warning_count": self.warning_count,
            "suggestion_count": self.suggestion_count,
            "critical_violation_count": self.critical_violation_count,
            "total_processing_time_ms": round(self.total_processing_time_ms, 2),
            "avg_processing_time_ms": self.get_average_processing_time(),
            "min_processing_time_ms": round(self.min_processing_time_ms, 2),
            "max_processing_time_ms": round(self.max_processing_time_ms, 2),
            "avg_score": self.get_average_score(),
            "avg_confidence": self.get_average_confidence(),
            "violation_rate": self.get_violation_rate(),
            "block_rate": self.get_block_rate(),
            "timeout_count": self.timeout_count,
            "error_count": self.error_count,
            "severity_counts": dict(self.severity_counts),
            "action_counts": dict(self.action_counts),
            "violation_type_counts": dict(self.violation_type_counts),
            "peak_concurrent": self.peak_concurrent,
            "last_evaluated_at": self.last_evaluated_at.isoformat() if self.last_evaluated_at else None,
            "first_evaluated_at": self.first_evaluated_at.isoformat() if self.first_evaluated_at else None,
        }


class TimeWindowMetrics:
    def __init__(self, window: MetricWindow):
        self.window = window
        self.max_age_seconds = WINDOW_SECONDS[window]
        self.events: deque = deque()
        self.violation_events: deque = deque()
        self.processing_times: deque = deque()

    def record_event(self, event_type: str, processing_time_ms: float, has_violation: bool) -> None:
        now = time.time()
        self.events.append((now, event_type))
        self.processing_times.append((now, processing_time_ms))
        if has_violation:
            self.violation_events.append((now, event_type))
        self._expire(now)

    def _expire(self, now: float) -> None:
        cutoff = now - self.max_age_seconds
        while self.events and self.events[0][0] < cutoff:
            self.events.popleft()
        while self.processing_times and self.processing_times[0][0] < cutoff:
            self.processing_times.popleft()
        while self.violation_events and self.violation_events[0][0] < cutoff:
            self.violation_events.popleft()

    def get_event_count(self) -> int:
        self._expire(time.time())
        return len(self.events)

    def get_violation_count(self) -> int:
        self._expire(time.time())
        return len(self.violation_events)

    def get_average_processing_time(self) -> float:
        self._expire(time.time())
        if not self.processing_times:
            return 0.0
        total = sum(pt for _, pt in self.processing_times)
        return round(total / len(self.processing_times), 2)

    def get_throughput_per_second(self) -> float:
        self._expire(time.time())
        return round(len(self.events) / max(self.max_age_seconds, 1), 4)

    def get_violation_rate_window(self) -> float:
        total = self.get_event_count()
        if total == 0:
            return 0.0
        return round(self.get_violation_count() / total, 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window": self.window.value,
            "window_seconds": self.max_age_seconds,
            "event_count": self.get_event_count(),
            "violation_count": self.get_violation_count(),
            "avg_processing_time_ms": self.get_average_processing_time(),
            "throughput_per_second": self.get_throughput_per_second(),
            "violation_rate": self.get_violation_rate_window(),
        }


class MetricsConfig:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.enabled_windows: List[MetricWindow] = [
            MetricWindow(w) for w in config.get(
                "enabled_windows",
                ["1m", "5m", "15m", "1h", "24h"],
            )
        ]
        self.max_history_events: int = config.get("max_history_events", 100000)
        self.export_format: MetricsExportFormat = MetricsExportFormat(
            config.get("export_format", "json")
        )
        self.prometheus_prefix: str = config.get("prometheus_prefix", "tiered_rules")
        self.collect_severity_breakdown: bool = config.get(
            "collect_severity_breakdown", True
        )
        self.collect_action_breakdown: bool = config.get(
            "collect_action_breakdown", True
        )
        self.collect_violation_type_breakdown: bool = config.get(
            "collect_violation_type_breakdown", True
        )
        self.historical_retention_days: int = config.get(
            "historical_retention_days", 30
        )
        self.auto_prune: bool = config.get("auto_prune", True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled_windows": [w.value for w in self.enabled_windows],
            "max_history_events": self.max_history_events,
            "export_format": self.export_format.value,
            "prometheus_prefix": self.prometheus_prefix,
            "collect_severity_breakdown": self.collect_severity_breakdown,
            "collect_action_breakdown": self.collect_action_breakdown,
            "collect_violation_type_breakdown": self.collect_violation_type_breakdown,
            "historical_retention_days": self.historical_retention_days,
            "auto_prune": self.auto_prune,
        }


class TierMetricsCollector:
    """Per-tier performance metrics collection and export."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = MetricsConfig(config or {})
        self._tier_metrics: Dict[str, TierMetrics] = {}
        self._window_metrics: Dict[str, Dict[str, TimeWindowMetrics]] = {}
        self._historical_records: List[Dict[str, Any]] = []
        self._evaluation_history: deque = deque(maxlen=self.config.max_history_events)
        self._concurrent_evaluations: int = 0
        self._peak_concurrent: int = 0
        self._total_evaluations: int = 0
        self._total_violations: int = 0
        self._total_blocks: int = 0
        self._total_warnings: int = 0
        self._total_suggestions: int = 0
        self._total_processing_time_ms: float = 0.0
        self._started_at: datetime = datetime.utcnow()
        self._last_pruned_at: Optional[datetime] = None
        self._initialize_windows()
        for tier in ["safety", "operational", "preference"]:
            self._tier_metrics[tier] = TierMetrics(tier)
        logger.info(
            "TierMetricsCollector initialized: windows=%s, max_history=%d",
            [w.value for w in self.config.enabled_windows],
            self.config.max_history_events,
        )

    def _initialize_windows(self) -> None:
        for tier in ["safety", "operational", "preference", "overall"]:
            self._window_metrics[tier] = {}
            for window in self.config.enabled_windows:
                self._window_metrics[tier][window.value] = TimeWindowMetrics(window)

    def record_evaluation(
        self,
        tier_results: Dict[Any, Any],
        result: ValidationResult,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._concurrent_evaluations += 1
        if self._concurrent_evaluations > self._peak_concurrent:
            self._peak_concurrent = self._concurrent_evaluations
        start_time = time.time()
        try:
            tier_dict = {}
            for tier_enum, tier_result in tier_results.items():
                tier_name = tier_enum.value if hasattr(tier_enum, 'value') else str(tier_enum)
                tier_dict[tier_name] = tier_result
            overall_processing_ms = result.processing_time_ms
            self._total_evaluations += 1
            self._total_violations += len(result.violations)
            self._total_blocks += sum(1 for v in result.violations if v.blocked)
            self._total_warnings += len(result.warnings)
            self._total_suggestions += len(result.suggestions)
            self._total_processing_time_ms += overall_processing_ms
            for tier_name, tier_result in tier_dict.items():
                if hasattr(tier_result, 'result') and tier_result.result:
                    tier_metrics = self._tier_metrics.get(tier_name)
                    if tier_metrics:
                        tier_processing = getattr(tier_result, 'processing_time_ms', overall_processing_ms)
                        timed_out = getattr(tier_result, 'status', None) and \
                            hasattr(tier_result.status, 'value') and \
                            tier_result.status.value == "timed_out"
                        tier_metrics.record(
                            result=tier_result.result,
                            processing_time_ms=tier_processing,
                            timed_out=timed_out,
                        )
                        for window_key, wm in self._window_metrics.get(tier_name, {}).items():
                            wm.record_event(
                                event_type="evaluation",
                                processing_time_ms=tier_processing,
                                has_violation=len(result.violations) > 0,
                            )
            overall_window = self._window_metrics.get("overall", {})
            for wm in overall_window.values():
                wm.record_event(
                    event_type="evaluation",
                    processing_time_ms=overall_processing_ms,
                    has_violation=len(result.violations) > 0,
                )
            record = {
                "timestamp": datetime.utcnow().isoformat(),
                "processing_time_ms": overall_processing_ms,
                "valid": result.valid,
                "violation_count": len(result.violations),
                "suggestion_count": len(result.suggestions),
                "blocked": result.is_blocked(),
                "tier_details": {
                    tn: tr.to_dict() if hasattr(tr, 'to_dict') else {}
                    for tn, tr in tier_dict.items()
                },
            }
            self._evaluation_history.append(record)
            if self.config.auto_prune:
                self._prune_history()
        finally:
            self._concurrent_evaluations -= 1

    def _prune_history(self) -> None:
        now = datetime.utcnow()
        if self._last_pruned_at and (now - self._last_pruned_at).total_seconds() < 300:
            return
        self._last_pruned_at = now
        cutoff = now - timedelta(days=self.config.historical_retention_days)
        before = len(self._evaluation_history)
        self._evaluation_history = deque(
            (r for r in self._evaluation_history
             if datetime.fromisoformat(r["timestamp"]) > cutoff),
            maxlen=self.config.max_history_events,
        )
        pruned = before - len(self._evaluation_history)
        if pruned > 0:
            logger.debug("Pruned %d historical records", pruned)

    def get_tier_metrics(self, tier_name: str) -> Optional[Dict[str, Any]]:
        tm = self._tier_metrics.get(tier_name)
        return tm.get_to_dict() if tm else None

    def get_all_tier_metrics(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: tm.get_to_dict()
            for name, tm in self._tier_metrics.items()
        }

    def get_window_metrics(
        self, tier_name: Optional[str] = None, window: Optional[MetricWindow] = None
    ) -> Dict[str, Any]:
        if tier_name and window:
            wm = self._window_metrics.get(tier_name, {}).get(window.value)
            return wm.to_dict() if wm else {}
        if tier_name:
            return {
                wkey: wm.to_dict()
                for wkey, wm in self._window_metrics.get(tier_name, {}).items()
            }
        result = {}
        for tname, windows in self._window_metrics.items():
            result[tname] = {
                wkey: wm.to_dict() for wkey, wm in windows.items()
            }
        return result

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "total_evaluations": self._total_evaluations,
            "total_violations": self._total_violations,
            "total_blocks": self._total_blocks,
            "total_warnings": self._total_warnings,
            "total_suggestions": self._total_suggestions,
            "total_processing_time_ms": round(self._total_processing_time_ms, 2),
            "avg_processing_time_ms": round(
                self._total_processing_time_ms / max(self._total_evaluations, 1), 2
            ),
            "violation_rate": round(
                self._total_violations / max(self._total_evaluations, 1), 4
            ),
            "block_rate": round(
                self._total_blocks / max(self._total_evaluations, 1), 4
            ),
            "warning_rate": round(
                self._total_warnings / max(self._total_evaluations, 1), 4
            ),
            "suggestion_rate": round(
                self._total_suggestions / max(self._total_evaluations, 1), 4
            ),
            "peak_concurrent": self._peak_concurrent,
            "current_concurrent": self._concurrent_evaluations,
            "started_at": self._started_at.isoformat(),
            "uptime_seconds": round(
                (datetime.utcnow() - self._started_at).total_seconds(), 2
            ),
            "history_size": len(self._evaluation_history),
            "tier_metrics": self.get_all_tier_metrics(),
            "window_metrics": self.get_window_metrics(),
            "config": self.config.to_dict(),
        }

    def export_metrics(
        self, format: MetricsExportFormat = MetricsExportFormat.JSON
    ) -> str:
        if format == MetricsExportFormat.PROMETHEUS:
            return self._export_prometheus()
        return self._export_json()

    def _export_json(self) -> str:
        data = {
            "generated_at": datetime.utcnow().isoformat(),
            "collector_uptime_seconds": round(
                (datetime.utcnow() - self._started_at).total_seconds(), 2
            ),
            "summary": {
                "total_evaluations": self._total_evaluations,
                "total_violations": self._total_violations,
                "total_blocks": self._total_blocks,
                "total_warnings": self._total_warnings,
                "total_suggestions": self._total_suggestions,
                "avg_processing_time_ms": round(
                    self._total_processing_time_ms / max(self._total_evaluations, 1), 2
                ),
            },
            "tier_metrics": self.get_all_tier_metrics(),
            "window_metrics": self.get_window_metrics(),
            "config": self.config.to_dict(),
        }
        return json.dumps(data, indent=2, default=str)

    def _export_prometheus(self) -> str:
        prefix = self.config.prometheus_prefix
        lines: List[str] = []
        lines.append(f"# HELP {prefix}_total_evaluations Total number of evaluations")
        lines.append(f"# TYPE {prefix}_total_evaluations counter")
        lines.append(f"{prefix}_total_evaluations {self._total_evaluations}")
        lines.append(f"# HELP {prefix}_total_violations Total number of violations detected")
        lines.append(f"# TYPE {prefix}_total_violations counter")
        lines.append(f"{prefix}_total_violations {self._total_violations}")
        lines.append(f"# HELP {prefix}_total_blocks Total number of blocks applied")
        lines.append(f"# TYPE {prefix}_total_blocks counter")
        lines.append(f"{prefix}_total_blocks {self._total_blocks}")
        lines.append(f"# HELP {prefix}_total_warnings Total number of warnings issued")
        lines.append(f"# TYPE {prefix}_total_warnings counter")
        lines.append(f"{prefix}_total_warnings {self._total_warnings}")
        lines.append(f"# HELP {prefix}_total_suggestions Total number of suggestions made")
        lines.append(f"# TYPE {prefix}_total_suggestions counter")
        lines.append(f"{prefix}_total_suggestions {self._total_suggestions}")
        lines.append(f"# HELP {prefix}_processing_time_ms Total processing time in milliseconds")
        lines.append(f"# TYPE {prefix}_processing_time_ms counter")
        lines.append(f"{prefix}_processing_time_ms {self._total_processing_time_ms}")
        lines.append(f"# HELP {prefix}_avg_processing_time_ms Average processing time per evaluation")
        lines.append(f"# TYPE {prefix}_avg_processing_time_ms gauge")
        lines.append(f"{prefix}_avg_processing_time_ms {round(self._total_processing_time_ms / max(self._total_evaluations, 1), 2)}")
        lines.append(f"# HELP {prefix}_peak_concurrent Peak concurrent evaluations")
        lines.append(f"# TYPE {prefix}_peak_concurrent gauge")
        lines.append(f"{prefix}_peak_concurrent {self._peak_concurrent}")
        lines.append(f"# HELP {prefix}_current_concurrent Current concurrent evaluations")
        lines.append(f"# TYPE {prefix}_current_concurrent gauge")
        lines.append(f"{prefix}_current_concurrent {self._concurrent_evaluations}")
        lines.append(f"# HELP {prefix}_uptime_seconds Collector uptime in seconds")
        lines.append(f"# TYPE {prefix}_uptime_seconds counter")
        uptime = round((datetime.utcnow() - self._started_at).total_seconds(), 2)
        lines.append(f"{prefix}_uptime_seconds {uptime}")
        for tier_name, tm in self._tier_metrics.items():
            line_prefix = f"{prefix}_tier_{tier_name}"
            lines.append(f"# HELP {line_prefix}_evaluations Evaluations for tier {tier_name}")
            lines.append(f"# TYPE {line_prefix}_evaluations counter")
            lines.append(f"{line_prefix}_evaluations {tm.evaluation_count}")
            lines.append(f"# HELP {line_prefix}_violations Violations for tier {tier_name}")
            lines.append(f"# TYPE {line_prefix}_violations counter")
            lines.append(f"{line_prefix}_violations {tm.violation_count}")
            lines.append(f"# HELP {line_prefix}_blocks Blocks for tier {tier_name}")
            lines.append(f"# TYPE {line_prefix}_blocks counter")
            lines.append(f"{line_prefix}_blocks {tm.block_count}")
            lines.append(f"# HELP {line_prefix}_avg_processing_ms Average processing time for tier {tier_name}")
            lines.append(f"# TYPE {line_prefix}_avg_processing_ms gauge")
            lines.append(f"{line_prefix}_avg_processing_ms {tm.get_average_processing_time()}")
        for tname, windows in self._window_metrics.items():
            for wkey, wm in windows.items():
                wprefix = f"{prefix}_window_{tname}_{wkey.replace(' ', '_')}"
                lines.append(f"# HELP {wprefix}_events Events in window")
                lines.append(f"# TYPE {wprefix}_events gauge")
                lines.append(f"{wprefix}_events {wm.get_event_count()}")
                lines.append(f"# HELP {wprefix}_violations Violations in window")
                lines.append(f"# TYPE {wprefix}_violations gauge")
                lines.append(f"{wprefix}_violations {wm.get_violation_count()}")
                lines.append(f"# HELP {wprefix}_avg_processing_ms Average processing time in window")
                lines.append(f"# TYPE {wprefix}_avg_processing_ms gauge")
                lines.append(f"{wprefix}_avg_processing_ms {wm.get_average_processing_time()}")
        return "\n".join(lines)

    def get_evaluation_history(
        self, limit: int = 100, offset: int = 0,
        min_violations: Optional[int] = None,
        only_blocked: bool = False,
    ) -> List[Dict[str, Any]]:
        records = list(self._evaluation_history)
        if min_violations is not None:
            records = [r for r in records if r["violation_count"] >= min_violations]
        if only_blocked:
            records = [r for r in records if r.get("blocked", False)]
        records = records[offset:offset + limit]
        return records

    def get_violation_trend(
        self, window: MetricWindow = MetricWindow.ONE_HOUR
    ) -> Dict[str, Any]:
        overall = self._window_metrics.get("overall", {})
        wm = overall.get(window.value)
        if not wm:
            return {"window": window.value, "error": "Window not enabled"}
        return wm.to_dict()

    def get_tier_comparison(self) -> Dict[str, Any]:
        tiers = self.get_all_tier_metrics()
        comparison = {}
        for tier_name, metrics in tiers.items():
            comparison[tier_name] = {
                "evaluation_count": metrics["evaluation_count"],
                "violation_rate": metrics["violation_rate"],
                "block_rate": metrics["block_rate"],
                "avg_processing_time_ms": metrics["avg_processing_time_ms"],
                "primary_action": max(
                    metrics.get("action_counts", {}).items(),
                    key=lambda x: x[1],
                    default=("none", 0),
                )[0],
            }
        return comparison

    def get_health_status(self) -> Dict[str, Any]:
        metrics = self.get_statistics()
        status: Dict[str, Any] = {"healthy": True, "issues": []}
        error_rate = metrics.get("total_violations", 0) / max(metrics.get("total_evaluations", 1), 1)
        if error_rate > 0.5:
            status["healthy"] = False
            status["issues"].append(
                f"High violation rate: {round(error_rate * 100, 1)}%"
            )
        timeout_total = sum(
            tm.get_to_dict().get("timeout_count", 0)
            for tm in self._tier_metrics.values()
        )
        if timeout_total > 10:
            status["healthy"] = False
            status["issues"].append(f"High timeout count: {timeout_total}")
        avg_time = metrics.get("avg_processing_time_ms", 0)
        if avg_time > 5000:
            status["healthy"] = False
            status["issues"].append(
                f"High average processing time: {avg_time}ms"
            )
        status["violation_rate"] = round(error_rate, 4)
        status["timeout_count"] = timeout_total
        status["avg_processing_time_ms"] = avg_time
        return status

    def get_performance_summary(self) -> Dict[str, Any]:
        return {
            "total_evaluations": self._total_evaluations,
            "evaluations_per_second": round(
                self._total_evaluations / max(
                    (datetime.utcnow() - self._started_at).total_seconds(), 1
                ), 4
            ),
            "avg_processing_time_ms": round(
                self._total_processing_time_ms / max(self._total_evaluations, 1), 2
            ),
            "p50_processing_time_ms": self._percentile_processing_time(50),
            "p95_processing_time_ms": self._percentile_processing_time(95),
            "p99_processing_time_ms": self._percentile_processing_time(99),
            "peak_concurrent": self._peak_concurrent,
            "current_concurrent": self._concurrent_evaluations,
        }

    def _percentile_processing_time(self, percentile: int) -> float:
        times = [
            r["processing_time_ms"]
            for r in self._evaluation_history
        ]
        if not times:
            return 0.0
        times.sort()
        idx = max(0, int(len(times) * percentile / 100) - 1)
        return round(times[idx], 2)

    def reset_statistics(self) -> None:
        self._tier_metrics = {}
        self._window_metrics = {}
        self._evaluation_history.clear()
        self._historical_records.clear()
        self._total_evaluations = 0
        self._total_violations = 0
        self._total_blocks = 0
        self._total_warnings = 0
        self._total_suggestions = 0
        self._total_processing_time_ms = 0.0
        self._concurrent_evaluations = 0
        self._peak_concurrent = 0
        self._started_at = datetime.utcnow()
        self._last_pruned_at = None
        for tier in ["safety", "operational", "preference"]:
            self._tier_metrics[tier] = TierMetrics(tier)
        self._initialize_windows()
        logger.info("TierMetricsCollector statistics reset")

    def update_config(self, config: Dict[str, Any]) -> None:
        self.config = MetricsConfig({**self.config.to_dict(), **config})
        if "enabled_windows" in config:
            self._initialize_windows()
        logger.info("TierMetricsCollector configuration updated")

    def get_config(self) -> Dict[str, Any]:
        return self.config.to_dict()

    def get_history_size(self) -> int:
        return len(self._evaluation_history)

    def get_uptime_seconds(self) -> float:
        return round((datetime.utcnow() - self._started_at).total_seconds(), 2)

    def get_daily_summary(self) -> Dict[str, Any]:
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_records = [
            r for r in self._evaluation_history
            if datetime.fromisoformat(r["timestamp"]) >= today_start
        ]
        yesterday_start = today_start - timedelta(days=1)
        yesterday_records = [
            r for r in self._evaluation_history
            if today_start > datetime.fromisoformat(r["timestamp"]) >= yesterday_start
        ]
        def aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
            if not records:
                return {"evaluations": 0, "violations": 0, "blocks": 0, "avg_time_ms": 0.0}
            ev = len(records)
            vl = sum(r["violation_count"] for r in records)
            bl = sum(1 for r in records if r.get("blocked", False))
            at = sum(r["processing_time_ms"] for r in records) / ev
            return {"evaluations": ev, "violations": vl, "blocks": bl, "avg_time_ms": round(at, 2)}
        return {
            "today": aggregate(today_records),
            "yesterday": aggregate(yesterday_records),
        }

    def get_top_violation_categories(self, limit: int = 10) -> List[Dict[str, Any]]:
        category_counts: Dict[str, int] = {}
        for record in self._evaluation_history:
            tier_details = record.get("tier_details", {})
            for tier_name, detail in tier_details.items():
                category_counts[tier_name] = category_counts.get(tier_name, 0) + 1
        sorted_cats = sorted(
            category_counts.items(), key=lambda x: x[1], reverse=True
        )[:limit]
        return [
            {"category": cat, "count": count}
            for cat, count in sorted_cats
        ]
