"""MonitoringClient - specialized client for monitoring, metrics, and alerting operations.

Provides methods for querying system metrics, managing alerts, building dashboards,
health checking, and exporting metrics in Prometheus format.
"""

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from .client import Client
from .exceptions import APIError, ConfigurationError, SDKError
from .models import (
    AlertDefinition,
    AlertEvent,
    MetricsSnapshot,
    RuleSeverity,
)

logger = logging.getLogger(__name__)


class MonitoringClient:
    """Specialized client for monitoring, metrics, and alerting operations.

    Provides comprehensive monitoring capabilities including metric querying,
    alert management, dashboard data aggregation, health checks, and
    Prometheus-compatible metrics export.

    Args:
        client: Configured Client instance for API communication.
        default_window: Default time window in seconds for metric queries.
        alert_poll_interval: Polling interval in seconds for alert checks.
        max_metrics_history: Maximum number of metric snapshots to retain.
        enable_auto_refresh: Whether to enable automatic dashboard refresh.

    Example:
        client = Client(api_key="sk-...")
        mc = MonitoringClient(client)
        metrics = mc.get_metrics()
        alerts = mc.get_alerts(severity=RuleSeverity.CRITICAL)
    """

    def __init__(
        self,
        client: Client,
        default_window: int = 3600,
        alert_poll_interval: int = 60,
        max_metrics_history: int = 10000,
        enable_auto_refresh: bool = False,
    ):
        if not isinstance(client, Client):
            raise ConfigurationError("client must be an instance of Client")

        self._client = client
        self.default_window = default_window
        self.alert_poll_interval = alert_poll_interval
        self.max_metrics_history = max_metrics_history
        self.enable_auto_refresh = enable_auto_refresh

        self._metrics_history: deque = deque(maxlen=max_metrics_history)
        self._alert_cache: Dict[str, AlertEvent] = {}
        self._dashboard_cache: Optional[Dict[str, Any]] = None
        self._dashboard_cache_time: float = 0.0
        self._dashboard_cache_ttl: int = 30
        self._metric_names: Set[str] = set()
        self._alert_definitions: Dict[str, AlertDefinition] = {}
        self._monitoring_hooks: List[Callable] = []
        self._alert_handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._monitoring_count: int = 0
        self._alert_trigger_count: int = 0
        self._alert_resolve_count: int = 0

        logger.info(
            "MonitoringClient initialized (window=%ds, poll=%ds, auto_refresh=%s)",
            default_window,
            alert_poll_interval,
            enable_auto_refresh,
        )

    def get_metrics(self) -> Dict[str, Any]:
        self._monitoring_count += 1
        try:
            response = self._client.get_metrics()
            if isinstance(response, dict):
                snapshot = MetricsSnapshot(
                    snapshot_id=f"snap_{int(time.time())}",
                    metrics={k: float(v) for k, v in response.items() if isinstance(v, (int, float))},
                    labels={"source": "api", "timestamp": datetime.now(timezone.utc).isoformat()},
                    metadata={"raw_keys": list(response.keys())},
                )
                self._metrics_history.append(snapshot)
                self._metric_names.update(snapshot.metrics.keys())
            return response
        except APIError as e:
            logger.error("Failed to fetch metrics: %s", e)
            return {}

    def get_metric(
        self,
        name: str,
        aggregation: str = "latest",
        window: Optional[int] = None,
    ) -> float:
        effective_window = window or self.default_window
        snapshots = list(self._metrics_history)

        if not snapshots:
            current = self.get_metrics()
            if name in current:
                return float(current[name])
            return 0.0

        cutoff = time.time() - effective_window
        relevant = [
            s for s in snapshots
            if name in s.metrics
        ]

        if not relevant:
            current = self.get_metrics()
            if isinstance(current, dict) and name in current:
                return float(current[name])
            return 0.0

        values = [s.metrics[name] for s in relevant]

        if aggregation == "latest":
            return values[-1]
        elif aggregation == "avg":
            return sum(values) / max(len(values), 1)
        elif aggregation == "min":
            return min(values)
        elif aggregation == "max":
            return max(values)
        elif aggregation == "sum":
            return sum(values)
        elif aggregation == "count":
            return float(len(values))
        elif aggregation == "p50":
            sorted_vals = sorted(values)
            return sorted_vals[len(sorted_vals) // 2]
        elif aggregation == "p95":
            sorted_vals = sorted(values)
            idx = int(len(sorted_vals) * 0.95)
            return sorted_vals[min(idx, len(sorted_vals) - 1)]
        elif aggregation == "p99":
            sorted_vals = sorted(values)
            idx = int(len(sorted_vals) * 0.99)
            return sorted_vals[min(idx, len(sorted_vals) - 1)]
        else:
            return values[-1]

    def get_alerts(
        self,
        severity: Optional[RuleSeverity] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        include_resolved: bool = False,
    ) -> List[AlertEvent]:
        self._monitoring_count += 1
        try:
            alerts = self._client.get_alerts(
                severity=severity,
                status=status,
                source=source,
                limit=limit,
            )
            for alert in alerts:
                self._alert_cache[alert.event_id] = alert
            if not include_resolved:
                alerts = [a for a in alerts if a.is_active()]
            return alerts
        except APIError as e:
            logger.error("Failed to fetch alerts: %s", e)
            return list(self._alert_cache.values())[:limit]

    def get_alert(self, alert_id: str) -> Optional[AlertEvent]:
        cached = self._alert_cache.get(alert_id)
        if cached:
            if cached.is_active() or datetime.fromisoformat(cached.timestamp.replace("Z", "+00:00")) > datetime.now(timezone.utc) - timedelta(hours=1):
                return cached
        try:
            alerts = self._client.get_alerts(limit=100)
            for alert in alerts:
                self._alert_cache[alert.event_id] = alert
                if alert.event_id == alert_id:
                    return alert
        except APIError:
            pass
        return self._alert_cache.get(alert_id)

    def trigger_alert(
        self,
        name: str,
        severity: RuleSeverity,
        message: str,
        metric_value: float = 0.0,
        threshold: float = 0.0,
        source: str = "sdk",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AlertEvent:
        self._alert_trigger_count += 1
        try:
            alert = self._client.trigger_alert(
                name=name,
                severity=severity,
                message=message,
                metric_value=metric_value,
                threshold=threshold,
                source=source,
                metadata=metadata,
            )
            self._alert_cache[alert.event_id] = alert
            self._run_alert_handlers(alert)
            return alert
        except APIError as e:
            logger.error("Failed to trigger alert '%s': %s", name, e)
            return AlertEvent(
                event_id=f"error_{int(time.time())}",
                alert_name=name,
                severity=severity,
                message=f"Trigger failed: {e}",
                source=source,
                metadata={"error": str(e)} if metadata else {},
            )

    def resolve_alert(self, alert_id: str) -> bool:
        try:
            success = self._client.resolve_alert(alert_id)
            if success:
                self._alert_resolve_count += 1
                if alert_id in self._alert_cache:
                    cached = self._alert_cache[alert_id]
                    cached.status = "resolved"
                    cached.resolved_at = datetime.now(timezone.utc).isoformat()
                logger.info("Alert %s resolved", alert_id)
            return success
        except APIError as e:
            logger.error("Failed to resolve alert %s: %s", alert_id, e)
            return False

    def resolve_alerts_by_name(self, alert_name: str) -> int:
        resolved = 0
        active_alerts = [
            a for a in self._alert_cache.values()
            if a.alert_name == alert_name and a.is_active()
        ]
        for alert in active_alerts:
            if self.resolve_alert(alert.event_id):
                resolved += 1
        return resolved

    def get_dashboard(self, force_refresh: bool = False) -> Dict[str, Any]:
        self._monitoring_count += 1
        if not force_refresh and self._dashboard_cache:
            if time.time() - self._dashboard_cache_time < self._dashboard_cache_ttl:
                return self._dashboard_cache

        try:
            dashboard = self._client.get_dashboard()
            self._dashboard_cache = dashboard
            self._dashboard_cache_time = time.time()
            return dashboard
        except APIError as e:
            logger.error("Failed to fetch dashboard: %s", e)
            return self._build_local_dashboard()

    def get_health(self) -> Dict[str, Any]:
        try:
            health = self._client.health_check()
            return {
                "healthy": True,
                "status": "healthy",
                "data": health,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except APIError as e:
            return {
                "healthy": False,
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "healthy": False,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def export_prometheus(self) -> str:
        try:
            raw = self._client.export_metrics(format="prometheus")
            if isinstance(raw, str) and raw.startswith("{"):
                metrics = json.loads(raw)
                return self._format_prometheus(metrics)
            if isinstance(raw, str):
                return raw
            if isinstance(raw, dict):
                return self._format_prometheus(raw)
            return str(raw)
        except APIError:
            return self._format_prometheus(self.get_metrics())

    def _format_prometheus(self, metrics: Dict[str, Any]) -> str:
        lines: List[str] = []
        prefix = "rules_emerging_pattern"
        timestamp = int(time.time() * 1000)

        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                safe_key = key.replace(" ", "_").replace("-", "_").replace(".", "_")
                lines.append(f"# HELP {prefix}_{safe_key} {key}")
                lines.append(f"# TYPE {prefix}_{safe_key} gauge")
                lines.append(f"{prefix}_{safe_key} {value} {timestamp}")
            elif isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, (int, float)):
                        safe_key = f"{key}_{sub_key}".replace(" ", "_").replace("-", "_").replace(".", "_")
                        lines.append(f"# HELP {prefix}_{safe_key} {key} {sub_key}")
                        lines.append(f"# TYPE {prefix}_{safe_key} gauge")
                        lines.append(f"{prefix}_{safe_key} {sub_value} {timestamp}")

        return "\n".join(lines)

    def export_json(self) -> str:
        snapshot = MetricsSnapshot(
            snapshot_id=f"export_{int(time.time())}",
            metrics=self._aggregate_metrics_history(),
            labels={"export_type": "json", "timestamp": datetime.now(timezone.utc).isoformat()},
        )
        return json.dumps(snapshot.to_dict(), indent=2, default=str)

    def export_csv(self) -> str:
        snapshots = list(self._metrics_history)
        if not snapshots:
            return "timestamp,metric_name,metric_value\n"

        all_metric_names = sorted(set(
            name for s in snapshots for name in s.metrics.keys()
        ))
        lines = ["timestamp," + ",".join(all_metric_names)]
        for s in snapshots:
            row = [s.timestamp]
            for name in all_metric_names:
                row.append(str(s.metrics.get(name, "")))
            lines.append(",".join(row))
        return "\n".join(lines)

    def _aggregate_metrics_history(self) -> Dict[str, float]:
        aggregated: Dict[str, List[float]] = defaultdict(list)
        for snapshot in self._metrics_history:
            for name, value in snapshot.metrics.items():
                aggregated[name].append(value)

        result: Dict[str, float] = {}
        for name, values in aggregated.items():
            result[f"{name}_latest"] = values[-1]
            result[f"{name}_avg"] = sum(values) / max(len(values), 1)
            result[f"{name}_min"] = min(values)
            result[f"{name}_max"] = max(values)
        return result

    def _build_local_dashboard(self) -> Dict[str, Any]:
        snapshots = list(self._metrics_history)
        alerts = list(self._alert_cache.values())

        if snapshots:
            latest = snapshots[-1].metrics
        else:
            latest = {}

        active_alerts = [a for a in alerts if a.is_active()]
        by_severity: Dict[str, int] = defaultdict(int)
        for a in active_alerts:
            by_severity[a.severity.value] += 1

        return {
            "status": "cached",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": {
                "latest": latest,
                "history_count": len(snapshots),
                "metric_names": sorted(self._metric_names),
            },
            "alerts": {
                "total": len(alerts),
                "active": len(active_alerts),
                "by_severity": dict(by_severity),
                "recent": [a.to_dict() for a in alerts[-10:]],
            },
            "health": self.get_health(),
            "statistics": {
                "monitoring_queries": self._monitoring_count,
                "alerts_triggered": self._alert_trigger_count,
                "alerts_resolved": self._alert_resolve_count,
            },
        }

    def get_alert_definitions(self, force_refresh: bool = False) -> Dict[str, AlertDefinition]:
        if not force_refresh and self._alert_definitions:
            return dict(self._alert_definitions)
        try:
            response = self._client.get_alerts(limit=100)
            for alert in response:
                definition = AlertDefinition(
                    alert_id=alert.alert_id,
                    name=alert.alert_name,
                    severity=alert.severity,
                    metadata=alert.metadata,
                )
                self._alert_definitions[alert.alert_id] = definition
            return dict(self._alert_definitions)
        except APIError:
            return dict(self._alert_definitions)

    def register_alert_handler(
        self,
        alert_name: str,
        handler: Callable[[AlertEvent], None],
    ) -> None:
        self._alert_handlers[alert_name].append(handler)
        logger.debug(
            "Registered alert handler for '%s' (%d total)",
            alert_name,
            len(self._alert_handlers[alert_name]),
        )

    def unregister_alert_handler(
        self,
        alert_name: str,
        handler: Callable,
    ) -> bool:
        if alert_name in self._alert_handlers and handler in self._alert_handlers[alert_name]:
            self._alert_handlers[alert_name].remove(handler)
            return True
        return False

    def register_monitoring_hook(self, hook: Callable) -> None:
        self._monitoring_hooks.append(hook)

    def unregister_monitoring_hook(self, hook: Callable) -> bool:
        if hook in self._monitoring_hooks:
            self._monitoring_hooks.remove(hook)
            return True
        return False

    def _run_hooks(self, event: str, **kwargs: Any) -> None:
        for hook in self._monitoring_hooks:
            try:
                hook(event=event, **kwargs)
            except Exception as e:
                logger.warning("Monitoring hook failed for '%s': %s", event, e)

    def _run_alert_handlers(self, alert: AlertEvent) -> None:
        handlers = self._alert_handlers.get(alert.alert_name, [])
        for handler in handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.warning("Alert handler failed for '%s': %s", alert.alert_name, e)

    def get_metrics_trend(
        self,
        name: str,
        window: int = 3600,
        points: int = 10,
    ) -> List[Dict[str, Any]]:
        snapshots = list(self._metrics_history)
        if not snapshots:
            return []

        cutoff = time.time() - window
        relevant = [
            s for s in snapshots
            if name in s.metrics
        ]

        if not relevant:
            return []

        step = max(1, len(relevant) // points)
        trend: List[Dict[str, Any]] = []
        for i in range(0, len(relevant), step):
            batch = relevant[i:i + step]
            values = [s.metrics[name] for s in batch]
            trend.append({
                "timestamp": batch[-1].timestamp,
                "value": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "samples": len(values),
            })
        return trend

    def check_alert_conditions(self) -> List[AlertEvent]:
        triggered: List[AlertEvent] = []
        metrics = self.get_metrics()

        for def_id, definition in self._alert_definitions.items():
            if not definition.enabled:
                continue
            metric_value = metrics.get(definition.metric, 0.0)
            if isinstance(metric_value, dict):
                continue
            try:
                metric_value = float(metric_value)
            except (TypeError, ValueError):
                continue

            should_trigger = False
            if definition.condition == "gt" and metric_value > definition.threshold:
                should_trigger = True
            elif definition.condition == "lt" and metric_value < definition.threshold:
                should_trigger = True
            elif definition.condition == "eq" and metric_value == definition.threshold:
                should_trigger = True
            elif definition.condition == "gte" and metric_value >= definition.threshold:
                should_trigger = True
            elif definition.condition == "lte" and metric_value <= definition.threshold:
                should_trigger = True

            if should_trigger:
                alert = self.trigger_alert(
                    name=definition.name,
                    severity=definition.severity,
                    message=f"Alert condition '{definition.condition}' triggered: {definition.metric}={metric_value} (threshold={definition.threshold})",
                    metric_value=metric_value,
                    threshold=definition.threshold,
                    source="monitoring_client",
                    metadata={"definition_id": def_id},
                )
                triggered.append(alert)

        return triggered

    def acknowledge_alert(self, alert_id: str) -> bool:
        cached = self._alert_cache.get(alert_id)
        if cached:
            cached.status = "acknowledged"
            return True
        return False

    def get_alert_statistics(self) -> Dict[str, Any]:
        alerts = list(self._alert_cache.values())
        active = [a for a in alerts if a.is_active()]
        resolved = [a for a in alerts if a.is_resolved()]

        by_severity: Dict[str, int] = defaultdict(int)
        by_source: Dict[str, int] = defaultdict(int)
        by_name: Dict[str, int] = defaultdict(int)

        for a in alerts:
            by_severity[a.severity.value] += 1
            by_source[a.source] += 1
            by_name[a.alert_name] += 1

        return {
            "total_alerts": len(alerts),
            "active_alerts": len(active),
            "resolved_alerts": len(resolved),
            "by_severity": dict(by_severity),
            "by_source": dict(by_source),
            "by_name": dict(by_name),
            "most_frequent_alert": max(by_name, key=by_name.get) if by_name else None,
            "triggered_total": self._alert_trigger_count,
            "resolved_total": self._alert_resolve_count,
        }

    def get_metrics_history(
        self,
        metric_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[MetricsSnapshot]:
        snapshots = list(self._metrics_history)
        if metric_name:
            snapshots = [s for s in snapshots if metric_name in s.metrics]
        return snapshots[-limit:]

    def clear_metrics_history(self) -> None:
        self._metrics_history.clear()
        logger.info("Metrics history cleared")

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "monitoring_queries": self._monitoring_count,
            "alerts_triggered": self._alert_trigger_count,
            "alerts_resolved": self._alert_resolve_count,
            "metrics_history_size": len(self._metrics_history),
            "alert_cache_size": len(self._alert_cache),
            "alert_definitions": len(self._alert_definitions),
            "metric_names_tracked": len(self._metric_names),
            "monitoring_hooks": len(self._monitoring_hooks),
            "alert_handlers": sum(len(v) for v in self._alert_handlers.values()),
            "dashboard_cached": self._dashboard_cache is not None,
        }

    def close(self) -> None:
        self._metrics_history.clear()
        self._alert_cache.clear()
        self._alert_definitions.clear()
        self._monitoring_hooks.clear()
        self._alert_handlers.clear()
        logger.info("MonitoringClient closed")

    def __enter__(self) -> "MonitoringClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    async def async_get_metrics(self) -> Dict[str, Any]:
        self._monitoring_count += 1
        try:
            response = await self._client.async_get_metrics()
            if isinstance(response, dict):
                snapshot = MetricsSnapshot(
                    snapshot_id=f"snap_{int(time.time())}",
                    metrics={k: float(v) for k, v in response.items() if isinstance(v, (int, float))},
                    labels={"source": "api_async"},
                )
                self._metrics_history.append(snapshot)
                self._metric_names.update(snapshot.metrics.keys())
            return response
        except APIError as e:
            logger.error("Async metrics fetch failed: %s", e)
            return {}

    async def async_get_alerts(
        self,
        severity: Optional[RuleSeverity] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        include_resolved: bool = False,
    ) -> List[AlertEvent]:
        self._monitoring_count += 1
        try:
            alerts = await self._client.async_get_alerts(
                severity=severity,
                status=status,
                source=source,
                limit=limit,
            )
            for alert in alerts:
                self._alert_cache[alert.event_id] = alert
            if not include_resolved:
                alerts = [a for a in alerts if a.is_active()]
            return alerts
        except APIError as e:
            logger.error("Async alerts fetch failed: %s", e)
            return []

    async def async_trigger_alert(
        self,
        name: str,
        severity: RuleSeverity,
        message: str,
        metric_value: float = 0.0,
        threshold: float = 0.0,
        source: str = "sdk",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AlertEvent:
        self._alert_trigger_count += 1
        try:
            alert = await self._client.async_trigger_alert(
                name=name,
                severity=severity,
                message=message,
                metric_value=metric_value,
                threshold=threshold,
                source=source,
                metadata=metadata,
            )
            self._alert_cache[alert.event_id] = alert
            self._run_alert_handlers(alert)
            return alert
        except APIError as e:
            logger.error("Async alert trigger failed: %s", e)
            return AlertEvent(
                event_id=f"error_{int(time.time())}",
                alert_name=name,
                severity=severity,
                message=f"Trigger failed: {e}",
                source=source,
            )

    async def async_resolve_alert(self, alert_id: str) -> bool:
        try:
            success = await self._client.async_resolve_alert(alert_id)
            if success:
                self._alert_resolve_count += 1
                if alert_id in self._alert_cache:
                    self._alert_cache[alert_id].status = "resolved"
            return success
        except APIError as e:
            logger.error("Async alert resolve failed: %s", e)
            return False

    async def async_get_dashboard(self, force_refresh: bool = False) -> Dict[str, Any]:
        self._monitoring_count += 1
        if not force_refresh and self._dashboard_cache:
            if time.time() - self._dashboard_cache_time < self._dashboard_cache_ttl:
                return self._dashboard_cache
        try:
            dashboard = await self._client.async_get_dashboard()
            self._dashboard_cache = dashboard
            self._dashboard_cache_time = time.time()
            return dashboard
        except APIError as e:
            logger.error("Async dashboard fetch failed: %s", e)
            return self._build_local_dashboard()

    async def async_get_health(self) -> Dict[str, Any]:
        try:
            health = await self._client.async_health_check()
            return {
                "healthy": True,
                "status": "healthy",
                "data": health,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except APIError as e:
            return {
                "healthy": False,
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "healthy": False,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def async_check_alert_conditions(self) -> List[AlertEvent]:
        metrics = await self.async_get_metrics()
        triggered: List[AlertEvent] = []

        for def_id, definition in self._alert_definitions.items():
            if not definition.enabled:
                continue
            metric_value = metrics.get(definition.metric, 0.0)
            if isinstance(metric_value, dict):
                continue
            try:
                metric_value = float(metric_value)
            except (TypeError, ValueError):
                continue

            should_trigger = False
            if definition.condition == "gt" and metric_value > definition.threshold:
                should_trigger = True
            elif definition.condition == "lt" and metric_value < definition.threshold:
                should_trigger = True
            elif definition.condition == "eq" and metric_value == definition.threshold:
                should_trigger = True
            elif definition.condition == "gte" and metric_value >= definition.threshold:
                should_trigger = True
            elif definition.condition == "lte" and metric_value <= definition.threshold:
                should_trigger = True

            if should_trigger:
                alert = await self.async_trigger_alert(
                    name=definition.name,
                    severity=definition.severity,
                    message=f"Condition '{definition.condition}' triggered: {definition.metric}={metric_value}",
                    metric_value=metric_value,
                    threshold=definition.threshold,
                    source="monitoring_client",
                    metadata={"definition_id": def_id},
                )
                triggered.append(alert)

        return triggered

    async def async_get_metrics_history(
        self,
        metric_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[MetricsSnapshot]:
        snapshots = list(self._metrics_history)
        if not snapshots:
            await self.async_get_metrics()
            snapshots = list(self._metrics_history)
        if metric_name:
            snapshots = [s for s in snapshots if metric_name in s.metrics]
        return snapshots[-limit:]
