"""Health checker for rule engine - monitors system health, component status, and readiness."""
import logging
import time
import threading
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ComponentType(str, Enum):
    RULE_ENGINE = "rule_engine"
    ENFORCER = "enforcer"
    MONITOR = "monitor"
    PERSISTENCE = "persistence"
    CACHE = "cache"
    API = "api"


@dataclass
class ComponentHealth:
    component_id: str
    component_type: ComponentType
    status: HealthStatus
    latency_ms: float
    last_check: datetime
    error_count: int
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    overall: HealthStatus
    components: List[ComponentHealth]
    healthy_count: int
    degraded_count: int
    unhealthy_count: int
    avg_latency_ms: float
    uptime_seconds: float
    last_comprehensive_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HealthChecker:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._checks: Dict[str, Callable[[], ComponentHealth]] = {}
        self._components: Dict[str, ComponentHealth] = {}
        self._error_threshold = self.config.get("error_threshold", 5)
        self._latency_threshold_ms = self.config.get("latency_threshold_ms", 1000.0)
        self._check_interval_seconds = self.config.get("check_interval_seconds", 60)
        self._start_time = time.time()
        self._check_count = 0
        self._failure_history: Dict[str, List[datetime]] = defaultdict(list)
        self._listeners: List[Callable[[HealthReport], None]] = []
        self._auto_check_active = False
        self._auto_check_thread: Optional[threading.Thread] = None
        logger.info("HealthChecker initialized (interval=%ds, latency_threshold=%.0fms)",
                     self._check_interval_seconds, self._latency_threshold_ms)

    def register_check(self, component_id: str, component_type: ComponentType,
                       check_fn: Callable[[], ComponentHealth]) -> None:
        self._checks[component_id] = check_fn
        logger.info("Registered health check: %s (%s)", component_id, component_type.value)

    def run_check(self, component_id: str) -> Optional[ComponentHealth]:
        if component_id not in self._checks:
            return None
        try:
            start = time.perf_counter()
            result = self._checks[component_id]()
            elapsed = (time.perf_counter() - start) * 1000
            self._components[component_id] = result
            self._check_count += 1
            if result.status in (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY):
                self._failure_history[component_id].append(datetime.now(timezone.utc))
            return result
        except Exception as e:
            error_health = ComponentHealth(
                component_id=component_id,
                component_type=ComponentType.RULE_ENGINE,
                status=HealthStatus.UNHEALTHY,
                latency_ms=0, last_check=datetime.now(timezone.utc),
                error_count=1, message=f"Check failed: {e}",
            )
            self._components[component_id] = error_health
            return error_health

    def run_all_checks(self) -> HealthReport:
        components: List[ComponentHealth] = []
        for cid in self._checks:
            result = self.run_check(cid)
            if result:
                components.append(result)

        healthy = sum(1 for c in components if c.status == HealthStatus.HEALTHY)
        degraded = sum(1 for c in components if c.status == HealthStatus.DEGRADED)
        unhealthy = sum(1 for c in components if c.status == HealthStatus.UNHEALTHY)
        avg_latency = sum(c.latency_ms for c in components) / max(len(components), 1)

        if unhealthy > 0:
            overall = HealthStatus.UNHEALTHY
        elif degraded > 0:
            overall = HealthStatus.DEGRADED
        elif healthy == len(components):
            overall = HealthStatus.HEALTHY
        else:
            overall = HealthStatus.UNKNOWN

        report = HealthReport(
            overall=overall,
            components=components,
            healthy_count=healthy,
            degraded_count=degraded,
            unhealthy_count=unhealthy,
            avg_latency_ms=round(avg_latency, 2),
            uptime_seconds=round(time.time() - self._start_time, 1),
        )

        for listener in self._listeners:
            try:
                listener(report)
            except Exception as e:
                logger.error("Health listener error: %s", e)

        logger.info("Health check: %s (healthy=%d, degraded=%d, unhealthy=%d, avg_latency=%.1fms)",
                     overall.value, healthy, degraded, unhealthy, avg_latency)
        return report

    def start_auto_checking(self) -> None:
        if self._auto_check_active:
            logger.warning("Auto-checking already active")
            return
        self._auto_check_active = True
        def _loop():
            while self._auto_check_active:
                self.run_all_checks()
                time.sleep(self._check_interval_seconds)
        self._auto_check_thread = threading.Thread(target=_loop, daemon=True)
        self._auto_check_thread.start()
        logger.info("Auto health checking started (interval=%ds)", self._check_interval_seconds)

    def stop_auto_checking(self) -> None:
        self._auto_check_active = False
        if self._auto_check_thread:
            self._auto_check_thread.join(timeout=10)
        logger.info("Auto health checking stopped")

    def register_listener(self, listener: Callable[[HealthReport], None]) -> None:
        self._listeners.append(listener)

    def get_component_health(self, component_id: str) -> Optional[ComponentHealth]:
        return self._components.get(component_id)

    def get_latest_report(self) -> Optional[HealthReport]:
        if not self._components:
            return None
        return self.run_all_checks()

    def is_healthy(self) -> bool:
        report = self.get_latest_report()
        return report.overall == HealthStatus.HEALTHY if report else False

    def get_failing_components(self) -> List[str]:
        return [
            cid for cid, failures in self._failure_history.items()
            if len(failures) >= self._error_threshold
        ]

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "total_checks": self._check_count,
            "registered_checks": len(self._checks),
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "overall_status": self.run_all_checks().overall.value if self._checks else "unknown",
            "failing_components": self.get_failing_components(),
            "auto_checking": self._auto_check_active,
        }
