"""Track resolution lifecycle, outcomes, and effectiveness metrics."""
import logging
import uuid
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class ResolutionMethod(str, Enum):
    PRIORITY_BASED = "priority_based"
    CONTEXT_AWARE = "context_aware"
    USER_PREFERENCE = "user_preference"
    FALLBACK = "fallback"
    MANUAL = "manual"
    COMPOSITE = "composite"


class ResolutionOutcome(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    ESCALATED = "escalated"
    ROLLED_BACK = "rolled_back"


@dataclass
class TrackedResolution:
    resolution_id: str
    conflict_id: str
    method: ResolutionMethod
    outcome: ResolutionOutcome
    winning_rule_id: str
    losing_rule_id: str
    duration_ms: float
    context: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    applied_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_at: Optional[datetime] = None
    rollback_at: Optional[datetime] = None
    effectiveness_score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ResolutionTracker:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._resolutions: Dict[str, TrackedResolution] = {}
        self._max_tracked = self.config.get("max_tracked", 5000)
        self._success_threshold_ms = self.config.get("success_threshold_ms", 100.0)
        logger.info("ResolutionTracker initialized (max_tracked=%d)", self._max_tracked)

    def track(self, resolution_data: Dict[str, Any]) -> TrackedResolution:
        if len(self._resolutions) >= self._max_tracked:
            oldest = min(self._resolutions.keys(),
                        key=lambda k: self._resolutions[k].applied_at)
            del self._resolutions[oldest]
            logger.debug("Evicted oldest resolution %s", oldest[:8])

        tracked = TrackedResolution(
            resolution_id=resolution_data.get("id") or str(uuid.uuid4()),
            conflict_id=resolution_data.get("conflict_id", "unknown"),
            method=ResolutionMethod(resolution_data.get("method", ResolutionMethod.PRIORITY_BASED.value)),
            outcome=ResolutionOutcome(resolution_data.get("outcome", ResolutionOutcome.SUCCESS.value)),
            winning_rule_id=resolution_data.get("winning_rule_id", "unknown"),
            losing_rule_id=resolution_data.get("losing_rule_id", "unknown"),
            duration_ms=float(resolution_data.get("duration_ms", 0)),
            context=resolution_data.get("context", {}),
            reason=resolution_data.get("reason", ""),
            metadata=resolution_data.get("metadata", {}),
        )

        self._resolutions[tracked.resolution_id] = tracked
        logger.info("Tracked resolution %s: method=%s outcome=%s duration=%.1fms",
                     tracked.resolution_id[:8], tracked.method.value,
                     tracked.outcome.value, tracked.duration_ms)
        return tracked

    def confirm(self, resolution_id: str) -> bool:
        tracked = self._resolutions.get(resolution_id)
        if not tracked:
            return False
        tracked.confirmed_at = datetime.now(timezone.utc)
        logger.info("Confirmed resolution %s", resolution_id[:8])
        return True

    def rollback(self, resolution_id: str) -> bool:
        tracked = self._resolutions.get(resolution_id)
        if not tracked:
            return False
        tracked.outcome = ResolutionOutcome.ROLLED_BACK
        tracked.rollback_at = datetime.now(timezone.utc)
        logger.info("Rolled back resolution %s", resolution_id[:8])
        return True

    def get(self, resolution_id: str) -> Optional[TrackedResolution]:
        return self._resolutions.get(resolution_id)

    def get_by_conflict(self, conflict_id: str) -> List[TrackedResolution]:
        return [
            r for r in self._resolutions.values()
            if r.conflict_id == conflict_id
        ]

    def query(
        self,
        method: Optional[ResolutionMethod] = None,
        outcome: Optional[ResolutionOutcome] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100
    ) -> List[TrackedResolution]:
        results = list(self._resolutions.values())

        if method:
            results = [r for r in results if r.method == method]
        if outcome:
            results = [r for r in results if r.outcome == outcome]
        if since:
            results = [r for r in results if r.applied_at >= since]
        if until:
            results = [r for r in results if r.applied_at <= until]

        results.sort(key=lambda r: r.applied_at, reverse=True)
        return results[:limit]

    def get_effectiveness_by_method(self) -> Dict[str, Dict[str, float]]:
        by_method: Dict[str, List[TrackedResolution]] = defaultdict(list)
        for r in self._resolutions.values():
            by_method[r.method.value].append(r)

        result: Dict[str, Dict[str, float]] = {}
        for method, items in by_method.items():
            total = len(items)
            successes = sum(1 for r in items if r.outcome == ResolutionOutcome.SUCCESS)
            avg_duration = sum(r.duration_ms for r in items) / total if total > 0 else 0.0
            result[method] = {
                "total": total,
                "success_rate": successes / total if total > 0 else 0.0,
                "avg_duration_ms": avg_duration,
                "rollback_rate": sum(1 for r in items if r.outcome == ResolutionOutcome.ROLLED_BACK) / total if total > 0 else 0.0
            }

        return result

    def get_statistics(self) -> Dict[str, Any]:
        total = len(self._resolutions)
        if total == 0:
            return {"total": 0, "message": "No resolutions tracked"}

        outcomes: Dict[str, int] = defaultdict(int)
        methods: Dict[str, int] = defaultdict(int)
        total_duration = 0.0

        for r in self._resolutions.values():
            outcomes[r.outcome.value] += 1
            methods[r.method.value] += 1
            total_duration += r.duration_ms

        return {
            "total_resolutions": total,
            "by_outcome": dict(outcomes),
            "by_method": dict(methods),
            "avg_duration_ms": total_duration / total,
            "overall_success_rate": outcomes.get(ResolutionOutcome.SUCCESS.value, 0) / total,
            "method_effectiveness": self.get_effectiveness_by_method()
        }

    def clear(self) -> int:
        count = len(self._resolutions)
        self._resolutions.clear()
        return count
