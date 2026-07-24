"""Health checking system for monitoring service health."""
import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthResult:
    """Result of a health check execution."""
    check_name: str
    status: HealthStatus
    timestamp: datetime
    response_time_ms: float
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    consecutive_failures: int = 0


@dataclass
class CheckDefinition:
    """Definition of a health check."""
    name: str
    description: str
    interval_seconds: int
    timeout_seconds: int = 30
    failure_threshold: int = 3
    degradation_threshold: int = 1
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckStatistics:
    """Statistics for a single health check."""
    check_name: str
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    last_run: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    avg_response_time_ms: float = 0.0
    min_response_time_ms: float = 0.0
    max_response_time_ms: float = 0.0
    consecutive_failures: int = 0
    uptime_percentage: float = 100.0


class HealthChecker:
    """Health checker for monitoring service health.

    Manages registered health checks, runs them periodically,
    tracks degradation, and provides health summaries.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the health checker.

        Args:
            config: Optional configuration dictionary
        """
        self._lock = threading.RLock()
        self._checks: Dict[str, Tuple[Callable, CheckDefinition]] = {}
        self._results: Dict[str, HealthResult] = {}
        self._history: Dict[str, List[HealthResult]] = defaultdict(list)
        self._statistics: Dict[str, CheckStatistics] = {}
        self._periodic_thread: Optional[threading.Thread] = None
        self._periodic_running = False
        self._check_threads: Dict[str, threading.Thread] = {}
        self._check_results_event = threading.Event()
        self._config = config or {}
        self._started_at = datetime.now()

        self.max_history_per_check = self._config.get("max_history_per_check", 1000)
        self.global_failure_threshold = self._config.get("global_failure_threshold", 5)
        self.global_degradation_threshold = self._config.get("global_degradation_threshold", 2)
        self.summary_refresh_interval = self._config.get("summary_refresh_seconds", 30)

        if self._config.get("check_definitions"):
            self._load_checks_from_config(self._config["check_definitions"])

        logger.info("HealthChecker initialized")

    def _load_checks_from_config(self, check_configs: List[Dict[str, Any]]) -> None:
        """Load health check definitions from configuration.

        Args:
            check_configs: List of check configuration dictionaries
        """
        for cfg in check_configs:
            try:
                check_fn = self._create_check_from_config(cfg)
                if check_fn:
                    definition = CheckDefinition(
                        name=cfg["name"],
                        description=cfg.get("description", ""),
                        interval_seconds=cfg["interval_seconds"],
                        timeout_seconds=cfg.get("timeout_seconds", 30),
                        failure_threshold=cfg.get("failure_threshold", 3),
                        degradation_threshold=cfg.get("degradation_threshold", 1),
                        enabled=cfg.get("enabled", True),
                        tags=cfg.get("tags", []),
                        metadata=cfg.get("metadata", {}),
                    )
                    self.register_check(cfg["name"], check_fn, definition)
                    logger.info(f"Loaded health check from config: {cfg['name']}")
            except Exception as e:
                logger.error(f"Failed to load check from config: {e}")

    def _create_check_from_config(self, cfg: Dict[str, Any]) -> Optional[Callable]:
        """Create a check function from configuration.

        Args:
            cfg: Check configuration

        Returns:
            Check function or None
        """
        check_type = cfg.get("type", "http")

        if check_type == "http":
            import urllib.request
            import urllib.error

            url = cfg.get("url", "")
            expected_status = cfg.get("expected_status", 200)
            timeout = cfg.get("timeout_seconds", 30)

            def http_check() -> HealthResult:
                start = time.time()
                try:
                    req = urllib.request.Request(url, method="GET")
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        elapsed = (time.time() - start) * 1000
                        status = resp.status
                        if status == expected_status:
                            return HealthResult(
                                check_name=cfg["name"],
                                status=HealthStatus.HEALTHY,
                                timestamp=datetime.now(),
                                response_time_ms=elapsed,
                                message=f"HTTP {status} OK",
                                details={"url": url, "status_code": status},
                            )
                        else:
                            return HealthResult(
                                check_name=cfg["name"],
                                status=HealthStatus.DEGRADED,
                                timestamp=datetime.now(),
                                response_time_ms=elapsed,
                                message=f"HTTP {status} (expected {expected_status})",
                                details={"url": url, "status_code": status, "expected": expected_status},
                            )
                except Exception as e:
                    elapsed = (time.time() - start) * 1000
                    return HealthResult(
                        check_name=cfg["name"],
                        status=HealthStatus.UNHEALTHY,
                        timestamp=datetime.now(),
                        response_time_ms=elapsed,
                        message=f"HTTP check failed: {e}",
                        details={"url": url, "error": str(e)},
                        error=str(e),
                    )

            return http_check

        elif check_type == "tcp":
            import socket

            host = cfg.get("host", "localhost")
            port = cfg.get("port", 80)
            timeout = cfg.get("timeout_seconds", 10)

            def tcp_check() -> HealthResult:
                start = time.time()
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    elapsed = (time.time() - start) * 1000
                    if result == 0:
                        return HealthResult(
                            check_name=cfg["name"],
                            status=HealthStatus.HEALTHY,
                            timestamp=datetime.now(),
                            response_time_ms=elapsed,
                            message=f"TCP connection to {host}:{port} successful",
                            details={"host": host, "port": port},
                        )
                    else:
                        return HealthResult(
                            check_name=cfg["name"],
                            status=HealthStatus.UNHEALTHY,
                            timestamp=datetime.now(),
                            response_time_ms=elapsed,
                            message=f"TCP connection to {host}:{port} failed (code {result})",
                            details={"host": host, "port": port, "error_code": result},
                            error=f"Connection error code: {result}",
                        )
                except Exception as e:
                    elapsed = (time.time() - start) * 1000
                    return HealthResult(
                        check_name=cfg["name"],
                        status=HealthStatus.UNHEALTHY,
                        timestamp=datetime.now(),
                        response_time_ms=elapsed,
                        message=f"TCP check failed: {e}",
                        details={"host": host, "port": port, "error": str(e)},
                        error=str(e),
                    )

            return tcp_check

        elif check_type == "ping":
            import subprocess
            import platform

            target = cfg.get("target", "localhost")
            count = cfg.get("count", 1)

            def ping_check() -> HealthResult:
                start = time.time()
                try:
                    param = "-n" if platform.system().lower() == "windows" else "-c"
                    cmd = ["ping", param, str(count), target]
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=30
                    )
                    elapsed = (time.time() - start) * 1000
                    if result.returncode == 0:
                        return HealthResult(
                            check_name=cfg["name"],
                            status=HealthStatus.HEALTHY,
                            timestamp=datetime.now(),
                            response_time_ms=elapsed,
                            message=f"Ping to {target} successful",
                            details={"target": target, "returncode": result.returncode},
                        )
                    else:
                        return HealthResult(
                            check_name=cfg["name"],
                            status=HealthStatus.UNHEALTHY,
                            timestamp=datetime.now(),
                            response_time_ms=elapsed,
                            message=f"Ping to {target} failed",
                            details={"target": target, "returncode": result.returncode},
                            error=result.stderr,
                        )
                except Exception as e:
                    elapsed = (time.time() - start) * 1000
                    return HealthResult(
                        check_name=cfg["name"],
                        status=HealthStatus.UNHEALTHY,
                        timestamp=datetime.now(),
                        response_time_ms=elapsed,
                        message=f"Ping check failed: {e}",
                        details={"target": target, "error": str(e)},
                        error=str(e),
                    )

            return ping_check

        else:
            logger.warning(f"Unknown check type: {check_type}")
            return None

    def register_check(
        self,
        name: str,
        check_fn: Callable[[], HealthResult],
        definition: Optional[CheckDefinition] = None,
    ) -> None:
        """Register a health check function.

        Args:
            name: Unique check name
            check_fn: Function that returns a HealthResult
            definition: Optional check definition (defaults will be used if None)
        """
        if definition is None:
            definition = CheckDefinition(
                name=name,
                description=f"Health check: {name}",
                interval_seconds=60,
            )

        with self._lock:
            self._checks[name] = (check_fn, definition)
            if name not in self._statistics:
                self._statistics[name] = CheckStatistics(check_name=name)

        logger.info(f"Registered health check: {name} (interval={definition.interval_seconds}s)")

    def unregister_check(self, name: str) -> bool:
        """Unregister a health check.

        Args:
            name: Name of the check to remove

        Returns:
            True if removed, False otherwise
        """
        with self._lock:
            if name in self._checks:
                del self._checks[name]
                self._results.pop(name, None)
                self._statistics.pop(name, None)
                logger.info(f"Unregistered health check: {name}")
                return True
            return False

    def get_check_definition(self, name: str) -> Optional[CheckDefinition]:
        """Get the definition of a registered check.

        Args:
            name: Check name

        Returns:
            CheckDefinition or None
        """
        with self._lock:
            _, definition = self._checks.get(name, (None, None))
            return definition

    def update_check_definition(self, name: str, updates: Dict[str, Any]) -> bool:
        """Update a check's definition.

        Args:
            name: Check name
            updates: Dictionary of fields to update

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if name not in self._checks:
                return False
            check_fn, definition = self._checks[name]
            for key, value in updates.items():
                if hasattr(definition, key):
                    setattr(definition, key, value)
            self._checks[name] = (check_fn, definition)
            logger.info(f"Updated check definition: {name}")
            return True

    def run_check(self, name: str) -> Optional[HealthResult]:
        """Run a specific health check by name.

        Args:
            name: Name of the check to run

        Returns:
            HealthResult or None if check not found
        """
        with self._lock:
            if name not in self._checks:
                logger.warning(f"Health check not found: {name}")
                return None
            check_fn, definition = self._checks[name]

        if not definition.enabled:
            logger.debug(f"Skipping disabled check: {name}")
            return None

        try:
            start_time = time.time()
            result = check_fn()
            elapsed_ms = (time.time() - start_time) * 1000
            result.response_time_ms = elapsed_ms
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000 if 'start_time' in locals() else 0
            result = HealthResult(
                check_name=name,
                status=HealthStatus.UNHEALTHY,
                timestamp=datetime.now(),
                response_time_ms=elapsed_ms,
                message=f"Check execution failed: {e}",
                error=str(e),
            )

        with self._lock:
            prev_result = self._results.get(name)
            if prev_result and prev_result.status != HealthStatus.HEALTHY:
                result.consecutive_failures = prev_result.consecutive_failures + 1
            elif result.status != HealthStatus.HEALTHY:
                result.consecutive_failures = 1

            self._results[name] = result
            self._history[name].append(result)
            self._update_statistics(name, result)

            if len(self._history[name]) > self.max_history_per_check:
                self._history[name] = self._history[name][-self.max_history_per_check:]

        self._check_results_event.set()
        return result

    def _update_statistics(self, name: str, result: HealthResult) -> None:
        """Update statistics for a check with the latest result.

        Args:
            name: Check name
            result: Latest health result
        """
        stats = self._statistics.get(name)
        if stats is None:
            stats = CheckStatistics(check_name=name)
            self._statistics[name] = stats

        stats.total_runs += 1
        stats.last_run = result.timestamp

        if result.status == HealthStatus.HEALTHY:
            stats.successful_runs += 1
            stats.last_success = result.timestamp
        else:
            stats.failed_runs += 1
            stats.last_failure = result.timestamp

        if stats.avg_response_time_ms == 0:
            stats.avg_response_time_ms = result.response_time_ms
            stats.min_response_time_ms = result.response_time_ms
            stats.max_response_time_ms = result.response_time_ms
        else:
            stats.avg_response_time_ms = (
                (stats.avg_response_time_ms * (stats.total_runs - 1) + result.response_time_ms)
                / stats.total_runs
            )
            stats.min_response_time_ms = min(stats.min_response_time_ms, result.response_time_ms)
            stats.max_response_time_ms = max(stats.max_response_time_ms, result.response_time_ms)

        stats.consecutive_failures = result.consecutive_failures

        if stats.total_runs > 0:
            stats.uptime_percentage = (stats.successful_runs / stats.total_runs) * 100.0

    def run_all_checks(self) -> Dict[str, HealthResult]:
        """Run all registered health checks.

        Returns:
            Dictionary mapping check names to HealthResults
        """
        with self._lock:
            check_names = list(self._checks.keys())

        results = {}
        for name in check_names:
            result = self.run_check(name)
            if result:
                results[name] = result

        return results

    def get_result(self, name: str) -> Optional[HealthResult]:
        """Get the latest result for a specific check.

        Args:
            name: Check name

        Returns:
            Latest HealthResult or None
        """
        with self._lock:
            return self._results.get(name)

    def get_all_results(self) -> Dict[str, HealthResult]:
        """Get the latest results for all checks.

        Returns:
            Dictionary mapping check names to HealthResults
        """
        with self._lock:
            return dict(self._results)

    def get_check_history(
        self,
        name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[HealthResult]:
        """Get historical results for a specific check.

        Args:
            name: Check name
            start_time: Optional start filter
            end_time: Optional end filter
            limit: Maximum number of results

        Returns:
            List of HealthResults
        """
        with self._lock:
            if name not in self._history:
                return []

            history = self._history[name]

            if start_time:
                history = [h for h in history if h.timestamp >= start_time]
            if end_time:
                history = [h for h in history if h.timestamp <= end_time]

            return history[-limit:]

    def get_health_summary(self) -> Dict[str, Any]:
        """Get a summary of overall system health.

        Returns:
            Dictionary with health summary
        """
        with self._lock:
            healthy_count = 0
            degraded_count = 0
            unhealthy_count = 0
            unknown_count = 0
            total_checks = len(self._checks)

            check_details = {}
            for name, result in self._results.items():
                status_key = result.status.value
                if result.status == HealthStatus.HEALTHY:
                    healthy_count += 1
                elif result.status == HealthStatus.DEGRADED:
                    degraded_count += 1
                elif result.status == HealthStatus.UNHEALTHY:
                    unhealthy_count += 1
                else:
                    unknown_count += 1

                check_details[name] = {
                    "status": result.status.value,
                    "message": result.message,
                    "response_time_ms": result.response_time_ms,
                    "last_checked": result.timestamp.isoformat(),
                    "consecutive_failures": result.consecutive_failures,
                }

            if unhealthy_count > 0:
                overall_status = HealthStatus.UNHEALTHY
            elif degraded_count > 0:
                overall_status = HealthStatus.DEGRADED
            elif healthy_count == total_checks and total_checks > 0:
                overall_status = HealthStatus.HEALTHY
            else:
                overall_status = HealthStatus.UNKNOWN

            unregistered_count = total_checks - len(self._results)
            if unregistered_count > 0:
                for name in self._checks:
                    if name not in check_details:
                        check_details[name] = {
                            "status": "not_run",
                            "message": "Check has not been run yet",
                            "response_time_ms": 0,
                            "last_checked": None,
                            "consecutive_failures": 0,
                        }

            stats_summary = {}
            for name, stats in self._statistics.items():
                stats_summary[name] = {
                    "total_runs": stats.total_runs,
                    "successful_runs": stats.successful_runs,
                    "failed_runs": stats.failed_runs,
                    "uptime_percentage": round(stats.uptime_percentage, 2),
                    "avg_response_time_ms": round(stats.avg_response_time_ms, 2),
                    "consecutive_failures": stats.consecutive_failures,
                }

            return {
                "overall_status": overall_status.value,
                "total_checks": total_checks,
                "healthy": healthy_count,
                "degraded": degraded_count,
                "unhealthy": unhealthy_count,
                "unknown": unknown_count,
                "uptime_percentage": self._calculate_global_uptime(),
                "checks": check_details,
                "statistics": stats_summary,
                "uptime_seconds": (datetime.now() - self._started_at).total_seconds(),
                "is_periodic_running": self._periodic_running,
                "summary_timestamp": datetime.now().isoformat(),
            }

    def _calculate_global_uptime(self) -> float:
        """Calculate global uptime percentage across all checks.

        Returns:
            Uptime percentage (0-100)
        """
        stats_list = list(self._statistics.values())
        if not stats_list:
            return 100.0

        total_runs = sum(s.total_runs for s in stats_list)
        total_success = sum(s.successful_runs for s in stats_list)

        if total_runs == 0:
            return 100.0

        return round((total_success / total_runs) * 100.0, 2)

    def detect_degradation(self, name: str) -> Optional[Dict[str, Any]]:
        """Detect degradation pattern for a specific check.

        Args:
            name: Check name

        Returns:
            Degradation info or None if no degradation
        """
        with self._lock:
            if name not in self._results:
                return None

            result = self._results[name]
            _, definition = self._checks.get(name, (None, None))
            if definition is None:
                return None

            degradation_info: Dict[str, Any] = {
                "check_name": name,
                "current_status": result.status.value,
                "consecutive_failures": result.consecutive_failures,
                "failure_threshold": definition.failure_threshold,
                "degradation_threshold": definition.degradation_threshold,
                "is_degraded": False,
                "pattern": "none",
            }

            if result.consecutive_failures >= definition.failure_threshold:
                degradation_info["is_degraded"] = True
                degradation_info["pattern"] = "consecutive_failures"
                degradation_info["message"] = (
                    f"Check {name} has {result.consecutive_failures} consecutive failures "
                    f"(threshold: {definition.failure_threshold})"
                )
            elif result.consecutive_failures >= definition.degradation_threshold:
                degradation_info["is_degraded"] = True
                degradation_info["pattern"] = "degradation"
                degradation_info["message"] = (
                    f"Check {name} is showing degradation with "
                    f"{result.consecutive_failures} consecutive failures"
                )

            history = self._history.get(name, [])
            if len(history) >= 10:
                recent = history[-10:]
                failure_rate = sum(1 for h in recent if h.status != HealthStatus.HEALTHY) / len(recent)
                if failure_rate > 0.5:
                    degradation_info["is_degraded"] = True
                    degradation_info["pattern"] = "high_failure_rate"
                    degradation_info["failure_rate"] = failure_rate
                    degradation_info["message"] = (
                        f"Check {name} has {failure_rate:.0%} failure rate in last 10 runs"
                    )

            if len(history) >= 5:
                response_times = [h.response_time_ms for h in history[-5:]]
                avg_rt = sum(response_times) / len(response_times)
                if avg_rt > 10000:
                    degradation_info["is_degraded"] = True
                    degradation_info["pattern"] = "slow_response"
                    degradation_info["avg_response_time_ms"] = avg_rt
                    degradation_info["message"] = (
                        f"Check {name} has high average response time: {avg_rt:.0f}ms"
                    )

            return degradation_info

    def detect_all_degradations(self) -> Dict[str, Dict[str, Any]]:
        """Detect degradation across all checks.

        Returns:
            Dictionary of check names to degradation info
        """
        with self._lock:
            check_names = list(self._checks.keys())

        degradations = {}
        for name in check_names:
            info = self.detect_degradation(name)
            if info and info.get("is_degraded"):
                degradations[name] = info

        return degradations

    def _periodic_loop(self) -> None:
        """Background thread: run all checks on their defined intervals."""
        logger.info("Periodic health checking started")
        while self._periodic_running:
            try:
                now = time.time()
                with self._lock:
                    check_schedule = []
                    for name, (_, definition) in self._checks.items():
                        if not definition.enabled:
                            continue
                        result = self._results.get(name)
                        if result is None:
                            check_schedule.append(name)
                        else:
                            last_run = result.timestamp.timestamp()
                            if (now - last_run) >= definition.interval_seconds:
                                check_schedule.append(name)

                for name in check_schedule:
                    if not self._periodic_running:
                        break
                    thread = threading.Thread(
                        target=self._run_check_safe,
                        args=(name,),
                        daemon=True,
                        name=f"check-{name}",
                    )
                    thread.start()

                self._check_results_event.wait(timeout=1.0)
                self._check_results_event.clear()

            except Exception as e:
                logger.error(f"Periodic check loop error: {e}")
                time.sleep(5)

        logger.info("Periodic health checking stopped")

    def _run_check_safe(self, name: str) -> None:
        """Run a check safely, catching any exceptions.

        Args:
            name: Check name
        """
        try:
            self.run_check(name)
        except Exception as e:
            logger.error(f"Safe check run failed for {name}: {e}")

    def start_periodic_checking(self) -> None:
        """Start the background periodic health check thread."""
        with self._lock:
            if self._periodic_thread and self._periodic_thread.is_alive():
                logger.warning("Periodic checking already running")
                return
            self._periodic_running = True
            self._periodic_thread = threading.Thread(
                target=self._periodic_loop,
                daemon=True,
                name="health-checker-periodic",
            )
            self._periodic_thread.start()
            logger.info("Periodic health checking started")

    def stop_periodic_checking(self) -> None:
        """Stop the background periodic health check thread."""
        self._periodic_running = False
        if self._periodic_thread:
            self._periodic_thread.join(timeout=15)
            logger.info("Periodic health checking stopped")

    def is_periodic_running(self) -> bool:
        """Check if periodic checking is active.

        Returns:
            True if periodic thread is running
        """
        return self._periodic_running and (self._periodic_thread is not None and self._periodic_thread.is_alive())

    def get_check_names(self) -> List[str]:
        """Get list of all registered check names.

        Returns:
            List of check name strings
        """
        with self._lock:
            return list(self._checks.keys())

    def get_enabled_check_names(self) -> List[str]:
        """Get list of enabled check names.

        Returns:
            List of enabled check name strings
        """
        with self._lock:
            return [
                name for name, (_, definition) in self._checks.items()
                if definition.enabled
            ]

    def get_statistics(self, name: str) -> Optional[CheckStatistics]:
        """Get statistics for a specific check.

        Args:
            name: Check name

        Returns:
            CheckStatistics or None
        """
        with self._lock:
            return self._statistics.get(name)

    def get_all_statistics(self) -> Dict[str, CheckStatistics]:
        """Get statistics for all checks.

        Returns:
            Dictionary of check names to CheckStatistics
        """
        with self._lock:
            return dict(self._statistics)

    def enable_check(self, name: str) -> bool:
        """Enable a specific health check.

        Args:
            name: Check name

        Returns:
            True if successful, False otherwise
        """
        return self.update_check_definition(name, {"enabled": True})

    def disable_check(self, name: str) -> bool:
        """Disable a specific health check.

        Args:
            name: Check name

        Returns:
            True if successful, False otherwise
        """
        return self.update_check_definition(name, {"enabled": False})

    def reset_statistics(self, name: Optional[str] = None) -> int:
        """Reset statistics for checks.

        Args:
            name: Optional specific check name

        Returns:
            Number of statistics reset
        """
        with self._lock:
            if name:
                if name in self._statistics:
                    self._statistics[name] = CheckStatistics(check_name=name)
                    self._history[name].clear()
                    return 1
                return 0
            else:
                count = len(self._statistics)
                self._statistics = {
                    cn: CheckStatistics(check_name=cn)
                    for cn in self._checks
                }
                self._history.clear()
                return count

    def export_results_json(self) -> str:
        """Export all health check results as a JSON string.

        Returns:
            JSON string with all results
        """
        summary = self.get_health_summary()
        return json.dumps(summary, indent=2, default=str)

    def export_results_to_file(self, filepath: str) -> bool:
        """Export health check results to a JSON file.

        Args:
            filepath: Path for the output file

        Returns:
            True if successful, False otherwise
        """
        try:
            data = self.export_results_json()
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(data)
            logger.info(f"Exported health results to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export health results: {e}")
            return False

    def get_checks_by_tag(self, tag: str) -> List[str]:
        """Get check names that have a specific tag.

        Args:
            tag: Tag to filter by

        Returns:
            List of matching check names
        """
        with self._lock:
            return [
                name for name, (_, definition) in self._checks.items()
                if tag in definition.tags
            ]

    def get_check_count(self) -> int:
        """Get total number of registered checks.

        Returns:
            Number of registered checks
        """
        with self._lock:
            return len(self._checks)

    def get_degraded_check_count(self) -> int:
        """Get count of currently degraded checks.

        Returns:
            Number of degraded checks
        """
        with self._lock:
            return sum(
                1 for r in self._results.values()
                if r.status in (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY)
            )

    def get_healthy_check_count(self) -> int:
        """Get count of currently healthy checks.

        Returns:
            Number of healthy checks
        """
        with self._lock:
            return sum(
                1 for r in self._results.values()
                if r.status == HealthStatus.HEALTHY
            )

    def wait_for_next_results(self, timeout: float = 30.0) -> bool:
        """Wait for the next batch of check results.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            True if results were produced, False on timeout
        """
        return self._check_results_event.wait(timeout=timeout)

    def get_unhealthy_checks(self) -> Dict[str, HealthResult]:
        """Get all currently unhealthy checks.

        Returns:
            Dictionary of unhealthy check results
        """
        with self._lock:
            return {
                name: result for name, result in self._results.items()
                if result.status == HealthStatus.UNHEALTHY
            }

    def get_config(self) -> Dict[str, Any]:
        """Get current health checker configuration.

        Returns:
            Configuration dictionary
        """
        return {
            "max_history_per_check": self.max_history_per_check,
            "global_failure_threshold": self.global_failure_threshold,
            "global_degradation_threshold": self.global_degradation_threshold,
            "summary_refresh_seconds": self.summary_refresh_interval,
            "total_checks": len(self._checks),
            "periodic_running": self._periodic_running,
            "uptime_seconds": (datetime.now() - self._started_at).total_seconds(),
        }
