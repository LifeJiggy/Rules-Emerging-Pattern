"""Operational compliance testing - validate rule operations against SLAs and policies."""
import logging
import time
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class OperationalPolicy(str, Enum):
    MAX_LATENCY = "max_latency"
    MIN_THROUGHPUT = "min_throughput"
    ERROR_RATE = "error_rate"
    AVAILABILITY = "availability"
    RESOURCE_USAGE = "resource_usage"
    CACHE_EFFECTIVENESS = "cache_effectiveness"


class OperationalStatus(str, Enum):
    COMPLIANT = "compliant"
    WARNING = "warning"
    VIOLATED = "violated"
    CRITICAL = "critical"


@dataclass
class OperationalCheck:
    policy: OperationalPolicy
    status: OperationalStatus
    actual_value: float
    threshold_value: float
    description: str
    suggestion: Optional[str] = None


@dataclass
class OperationalComplianceResult:
    compliant: bool
    checks: List[OperationalCheck]
    score: float
    summary: Dict[str, Any]
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class OperationalCompliance:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._thresholds: Dict[str, Dict[str, float]] = {
            OperationalPolicy.MAX_LATENCY.value: {
                "warning": self.config.get("latency_warning_ms", 200.0),
                "critical": self.config.get("latency_critical_ms", 1000.0),
            },
            OperationalPolicy.MIN_THROUGHPUT.value: {
                "warning": self.config.get("throughput_warning", 50.0),
                "critical": self.config.get("throughput_critical", 10.0),
            },
            OperationalPolicy.ERROR_RATE.value: {
                "warning": self.config.get("error_rate_warning", 0.01),
                "critical": self.config.get("error_rate_critical", 0.05),
            },
            OperationalPolicy.AVAILABILITY.value: {
                "warning": self.config.get("availability_warning", 99.0),
                "critical": self.config.get("availability_critical", 95.0),
            },
        }
        self._history: List[OperationalComplianceResult] = []
        logger.info("OperationalCompliance initialized (config=%s)", self.config)

    def validate(self, operation: Dict[str, Any]) -> OperationalComplianceResult:
        checks: List[OperationalCheck] = []

        latency_check = self._check_latency(operation)
        if latency_check:
            checks.append(latency_check)

        throughput_check = self._check_throughput(operation)
        if throughput_check:
            checks.append(throughput_check)

        error_check = self._check_error_rate(operation)
        if error_check:
            checks.append(error_check)

        availability_check = self._check_availability(operation)
        if availability_check:
            checks.append(availability_check)

        resource_check = self._check_resource_usage(operation)
        if resource_check:
            checks.append(resource_check)

        cache_check = self._check_cache_effectiveness(operation)
        if cache_check:
            checks.append(cache_check)

        score = self._compute_score(checks)
        compliant = score >= 0.7

        summary = {
            "compliant": compliant,
            "score": score,
            "total_checks": len(checks),
            "passed": sum(1 for c in checks if c.status == OperationalStatus.COMPLIANT),
            "warnings": sum(1 for c in checks if c.status == OperationalStatus.WARNING),
            "violations": sum(1 for c in checks if c.status in (OperationalStatus.VIOLATED, OperationalStatus.CRITICAL)),
            "by_policy": {c.policy.value: c.status.value for c in checks},
        }

        result = OperationalComplianceResult(
            compliant=compliant,
            checks=checks,
            score=score,
            summary=summary,
        )
        self._history.append(result)

        logger.info(
            "Operational compliance: %s (score=%.2f, checks=%d, violations=%d)",
            "PASS" if compliant else "FAIL", score, len(checks),
            summary["violations"]
        )
        return result

    def validate_many(self, operations: List[Dict[str, Any]]) -> List[OperationalComplianceResult]:
        return [self.validate(op) for op in operations]

    def get_statistics(self) -> Dict[str, Any]:
        if not self._history:
            return {"total_validations": 0, "compliant_rate": 0.0}

        total = len(self._history)
        compliant = sum(1 for r in self._history if r.compliant)
        policy_status: Dict[str, List[OperationalStatus]] = defaultdict(list)

        for result in self._history:
            for check in result.checks:
                policy_status[check.policy.value].append(check.status)

        return {
            "total_validations": total,
            "compliant_rate": compliant / total,
            "avg_score": sum(r.score for r in self._history) / total,
            "policy_health": {
                policy: {
                    "compliant": sum(1 for s in statuses if s == OperationalStatus.COMPLIANT),
                    "violated": sum(1 for s in statuses if s in (OperationalStatus.VIOLATED, OperationalStatus.CRITICAL)),
                    "total": len(statuses),
                }
                for policy, statuses in policy_status.items()
            },
        }

    def _check_latency(self, op: Dict[str, Any]) -> Optional[OperationalCheck]:
        latency = op.get("latency_ms")
        if latency is None:
            return None

        thresholds = self._thresholds[OperationalPolicy.MAX_LATENCY.value]
        status = self._threshold_status(latency, thresholds, higher_is_worse=True)

        return OperationalCheck(
            policy=OperationalPolicy.MAX_LATENCY,
            status=status,
            actual_value=latency,
            threshold_value=thresholds["critical"],
            description=f"Operation latency: {latency:.1f}ms",
            suggestion="Optimize rule evaluation or enable caching" if status != OperationalStatus.COMPLIANT else None,
        )

    def _check_throughput(self, op: Dict[str, Any]) -> Optional[OperationalCheck]:
        throughput = op.get("throughput_per_sec")
        if throughput is None:
            return None

        thresholds = self._thresholds[OperationalPolicy.MIN_THROUGHPUT.value]
        status = self._threshold_status(throughput, thresholds, higher_is_worse=False)

        return OperationalCheck(
            policy=OperationalPolicy.MIN_THROUGHPUT,
            status=status,
            actual_value=throughput,
            threshold_value=thresholds["critical"],
            description=f"Operation throughput: {throughput:.1f}/s",
            suggestion="Scale horizontally or optimize rule processing" if status != OperationalStatus.COMPLIANT else None,
        )

    def _check_error_rate(self, op: Dict[str, Any]) -> Optional[OperationalCheck]:
        error_rate = op.get("error_rate")
        if error_rate is None:
            return None

        thresholds = self._thresholds[OperationalPolicy.ERROR_RATE.value]
        status = self._threshold_status(error_rate, thresholds, higher_is_worse=True)

        return OperationalCheck(
            policy=OperationalPolicy.ERROR_RATE,
            status=status,
            actual_value=error_rate,
            threshold_value=thresholds["critical"],
            description=f"Error rate: {error_rate:.4f}",
            suggestion="Review error logs and fix recurring failures" if status != OperationalStatus.COMPLIANT else None,
        )

    def _check_availability(self, op: Dict[str, Any]) -> Optional[OperationalCheck]:
        availability = op.get("availability_pct")
        if availability is None:
            return None

        thresholds = self._thresholds[OperationalPolicy.AVAILABILITY.value]
        status = self._threshold_status(availability, thresholds, higher_is_worse=False)

        return OperationalCheck(
            policy=OperationalPolicy.AVAILABILITY,
            status=status,
            actual_value=availability,
            threshold_value=thresholds["critical"],
            description=f"System availability: {availability:.1f}%",
            suggestion="Implement redundancy and failover mechanisms" if status != OperationalStatus.COMPLIANT else None,
        )

    def _check_resource_usage(self, op: Dict[str, Any]) -> Optional[OperationalCheck]:
        cpu = op.get("cpu_pct")
        memory = op.get("memory_mb")
        if cpu is None and memory is None:
            return None

        cpu_ok = cpu is None or cpu < 80
        mem_ok = memory is None or memory < 512

        if cpu_ok and mem_ok:
            return None

        return OperationalCheck(
            policy=OperationalPolicy.RESOURCE_USAGE,
            status=OperationalStatus.WARNING,
            actual_value=cpu or 0,
            threshold_value=80,
            description=f"Resource usage: CPU={cpu}%, Memory={memory}MB",
            suggestion="Scale up or optimize resource allocation",
        )

    def _check_cache_effectiveness(self, op: Dict[str, Any]) -> Optional[OperationalCheck]:
        cache_rate = op.get("cache_hit_rate")
        if cache_rate is None:
            return None

        if cache_rate < 0.5:
            return OperationalCheck(
                policy=OperationalPolicy.CACHE_EFFECTIVENESS,
                status=OperationalStatus.WARNING,
                actual_value=cache_rate,
                threshold_value=0.5,
                description=f"Cache hit rate: {cache_rate:.1%}",
                suggestion="Review caching strategy and rule access patterns",
            )
        return None

    def _compute_score(self, checks: List[OperationalCheck]) -> float:
        if not checks:
            return 1.0

        status_scores = {
            OperationalStatus.COMPLIANT: 1.0,
            OperationalStatus.WARNING: 0.6,
            OperationalStatus.VIOLATED: 0.3,
            OperationalStatus.CRITICAL: 0.0,
        }

        return sum(status_scores.get(c.status, 0.5) for c in checks) / len(checks)

    def _threshold_status(
        self,
        value: float,
        thresholds: Dict[str, float],
        higher_is_worse: bool
    ) -> OperationalStatus:
        if higher_is_worse:
            if value >= thresholds["critical"]:
                return OperationalStatus.CRITICAL
            if value >= thresholds["warning"]:
                return OperationalStatus.VIOLATED
        else:
            if value <= thresholds["critical"]:
                return OperationalStatus.CRITICAL
            if value <= thresholds["warning"]:
                return OperationalStatus.VIOLATED
        return OperationalStatus.COMPLIANT
