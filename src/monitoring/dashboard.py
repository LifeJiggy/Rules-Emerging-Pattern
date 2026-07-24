"""Monitoring dashboard for system metrics."""
import copy
import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Metric:
    """Represents a system metric."""
    name: str
    value: float
    unit: str
    timestamp: datetime
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class DashboardWidget:
    """Represents a dashboard widget."""
    widget_id: str
    widget_type: str
    title: str
    metric_names: List[str]
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ThresholdRule:
    """Threshold rule for metric alerts."""
    rule_id: str
    metric_name: str
    operator: str
    value: float
    severity: str
    message: str
    enabled: bool = True
    cooldown_seconds: int = 300


@dataclass
class TrendResult:
    """Result of a metric trend analysis."""
    metric_name: str
    current_value: float
    historical_avg: float
    change_percent: float
    trend_direction: str
    is_anomalous: bool
    confidence: float


@dataclass
class DashboardTemplate:
    """Template for creating dashboards."""
    template_id: str
    name: str
    description: str
    widgets: List[Dict[str, Any]] = field(default_factory=list)
    refresh_interval: int = 30
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DashboardSnapshot:
    """Snapshot of dashboard state."""
    snapshot_id: str
    timestamp: datetime
    dashboard_data: Dict[str, Any]
    description: str = ""


class MonitoringDashboard:
    """Dashboard for monitoring system health and metrics."""

    def __init__(self, dashboard_id: str = "main", config: Optional[Dict[str, Any]] = None):
        """Initialize the monitoring dashboard.

        Args:
            dashboard_id: Unique identifier for the dashboard
            config: Optional configuration dictionary
        """
        self.dashboard_id = dashboard_id
        self.metrics: Dict[str, List[Metric]] = defaultdict(list)
        self.widgets: Dict[str, DashboardWidget] = {}
        self.refresh_interval = 30
        self.last_refresh = datetime.now()
        self.alerts_enabled = True
        self._lock = threading.RLock()

        self.threshold_rules: Dict[str, ThresholdRule] = {}
        self.dashboard_templates: Dict[str, DashboardTemplate] = {}
        self.snapshots: List[DashboardSnapshot] = []
        self._polling_callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._polling_threads: Dict[str, threading.Thread] = {}
        self._polling_running: Dict[str, bool] = {}
        self._config = config or {}
        self.historical_baselines: Dict[str, List[float]] = defaultdict(list)

        if self._config.get("widgets"):
            self._load_widgets_from_config(self._config["widgets"])
        if self._config.get("thresholds"):
            self._load_thresholds_from_config(self._config["thresholds"])

        logger.info(f"MonitoringDashboard '{dashboard_id}' initialized")

    def _load_widgets_from_config(self, widgets_config: List[Dict[str, Any]]) -> None:
        """Load widgets from configuration.

        Args:
            widgets_config: List of widget configuration dictionaries
        """
        for w_cfg in widgets_config:
            try:
                widget = DashboardWidget(
                    widget_id=w_cfg.get("widget_id", f"w_{len(self.widgets)}"),
                    widget_type=w_cfg["widget_type"],
                    title=w_cfg["title"],
                    metric_names=w_cfg.get("metric_names", []),
                    config=w_cfg.get("config", {}),
                )
                self.widgets[widget.widget_id] = widget
                logger.info(f"Loaded widget from config: {widget.title}")
            except Exception as e:
                logger.error(f"Failed to load widget from config: {e}")

    def _load_thresholds_from_config(self, thresholds_config: List[Dict[str, Any]]) -> None:
        """Load threshold rules from configuration.

        Args:
            thresholds_config: List of threshold configuration dictionaries
        """
        for t_cfg in thresholds_config:
            try:
                rule = ThresholdRule(
                    rule_id=t_cfg.get("rule_id", f"th_{len(self.threshold_rules)}"),
                    metric_name=t_cfg["metric_name"],
                    operator=t_cfg["operator"],
                    value=float(t_cfg["value"]),
                    severity=t_cfg.get("severity", "warning"),
                    message=t_cfg.get("message", ""),
                    enabled=t_cfg.get("enabled", True),
                    cooldown_seconds=t_cfg.get("cooldown_seconds", 300),
                )
                self.threshold_rules[rule.rule_id] = rule
                logger.info(f"Loaded threshold rule: {rule.metric_name} {rule.operator} {rule.value}")
            except Exception as e:
                logger.error(f"Failed to load threshold rule: {e}")

    def record_metric(
        self,
        name: str,
        value: float,
        unit: str = "count",
        labels: Optional[Dict[str, str]] = None,
    ) -> Metric:
        """Record a metric value.

        Args:
            name: Metric name
            value: Metric value
            unit: Unit of measurement
            labels: Optional labels/tags

        Returns:
            The recorded metric
        """
        metric = Metric(
            name=name,
            value=value,
            unit=unit,
            timestamp=datetime.now(),
            labels=labels or {},
        )

        with self._lock:
            self.metrics[name].append(metric)
            self.historical_baselines[name].append(value)

            if len(self.metrics[name]) > 10000:
                self.metrics[name] = self.metrics[name][-10000:]
            if len(self.historical_baselines[name]) > 50000:
                self.historical_baselines[name] = self.historical_baselines[name][-50000:]

        logger.debug(f"Recorded metric {name}: {value} {unit}")
        return metric

    def add_widget(self, widget: DashboardWidget) -> None:
        """Add a widget to the dashboard.

        Args:
            widget: DashboardWidget to add
        """
        with self._lock:
            self.widgets[widget.widget_id] = widget
        logger.info(f"Added widget: {widget.title} ({widget.widget_id})")

    def remove_widget(self, widget_id: str) -> bool:
        """Remove a widget from the dashboard.

        Args:
            widget_id: ID of the widget to remove

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            if widget_id in self.widgets:
                del self.widgets[widget_id]
                logger.info(f"Removed widget: {widget_id}")
                return True
            return False

    def update_widget(self, widget_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing widget.

        Args:
            widget_id: ID of the widget to update
            updates: Dictionary of fields to update

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if widget_id not in self.widgets:
                return False
            widget = self.widgets[widget_id]
            for key, value in updates.items():
                if hasattr(widget, key):
                    setattr(widget, key, value)
            logger.info(f"Updated widget: {widget_id}")
            return True

    def add_threshold_rule(self, rule: ThresholdRule) -> None:
        """Add a threshold alert rule.

        Args:
            rule: The threshold rule to add
        """
        with self._lock:
            self.threshold_rules[rule.rule_id] = rule
        logger.info(f"Added threshold rule: {rule.metric_name} {rule.operator} {rule.value}")

    def remove_threshold_rule(self, rule_id: str) -> bool:
        """Remove a threshold rule.

        Args:
            rule_id: ID of the rule to remove

        Returns:
            True if removed, False otherwise
        """
        with self._lock:
            if rule_id in self.threshold_rules:
                del self.threshold_rules[rule_id]
                return True
            return False

    def get_current_metrics(self) -> Dict[str, Metric]:
        """Get current (latest) value for all metrics.

        Returns:
            Dictionary of metric names to latest Metric
        """
        current = {}
        with self._lock:
            for name, metric_list in self.metrics.items():
                if metric_list:
                    current[name] = metric_list[-1]
        return current

    def get_metric_history(
        self,
        metric_name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Metric]:
        """Get historical data for a metric.

        Args:
            metric_name: Name of the metric
            start_time: Optional start time filter
            end_time: Optional end time filter

        Returns:
            List of matching metrics
        """
        with self._lock:
            if metric_name not in self.metrics:
                return []

            metrics = self.metrics[metric_name]

            if start_time:
                metrics = [m for m in metrics if m.timestamp >= start_time]
            if end_time:
                metrics = [m for m in metrics if m.timestamp <= end_time]

            return metrics

    def get_widget_data(self, widget_id: str) -> Optional[Dict[str, Any]]:
        """Get the current data for a specific widget.

        Args:
            widget_id: ID of the widget

        Returns:
            Widget data dictionary or None
        """
        with self._lock:
            if widget_id not in self.widgets:
                return None
            widget = self.widgets[widget_id]
            data: Dict[str, Any] = {
                "widget_id": widget.widget_id,
                "widget_type": widget.widget_type,
                "title": widget.title,
                "metric_names": widget.metric_names,
                "config": widget.config,
                "metrics": {},
            }
            for metric_name in widget.metric_names:
                if metric_name in self.metrics and self.metrics[metric_name]:
                    latest = self.metrics[metric_name][-1]
                    data["metrics"][metric_name] = {
                        "value": latest.value,
                        "unit": latest.unit,
                        "timestamp": latest.timestamp.isoformat(),
                        "labels": latest.labels,
                    }
                    aggregates = self.calculate_aggregates(metric_name)
                    data["metrics"][f"{metric_name}_aggregates"] = aggregates
            return data

    def start_metric_stream(
        self,
        metric_name: str,
        callback: Callable[[Metric], None],
        interval_seconds: float = 1.0,
    ) -> None:
        """Start a real-time metric streaming callback.

        Args:
            metric_name: Name of metric to stream
            callback: Function called with new Metric values
            interval_seconds: Polling interval
        """
        stream_id = f"{metric_name}_{id(callback)}"
        with self._lock:
            self._polling_callbacks[metric_name].append(callback)

        if metric_name not in self._polling_threads or not self._polling_threads[metric_name].is_alive():
            self._polling_running[metric_name] = True
            thread = threading.Thread(
                target=self._poll_metric_loop,
                args=(metric_name, interval_seconds),
                daemon=True,
                name=f"metric-stream-{metric_name}",
            )
            self._polling_threads[metric_name] = thread
            thread.start()
            logger.info(f"Started metric stream: {metric_name} ({interval_seconds}s)")

    def stop_metric_stream(self, metric_name: str, callback: Optional[Callable] = None) -> None:
        """Stop a metric streaming callback.

        Args:
            metric_name: Name of metric
            callback: Optional specific callback to remove
        """
        with self._lock:
            if callback:
                self._polling_callbacks[metric_name] = [
                    cb for cb in self._polling_callbacks[metric_name] if cb is not callback
                ]
            else:
                self._polling_callbacks[metric_name].clear()

            if not self._polling_callbacks[metric_name]:
                self._polling_running[metric_name] = False

        logger.info(f"Stopped metric stream: {metric_name}")

    def _poll_metric_loop(self, metric_name: str, interval_seconds: float) -> None:
        """Background thread for polling a metric.

        Args:
            metric_name: The metric to poll
            interval_seconds: Polling interval
        """
        last_value: Optional[float] = None
        while self._polling_running.get(metric_name, False):
            try:
                with self._lock:
                    if metric_name in self.metrics and self.metrics[metric_name]:
                        latest = self.metrics[metric_name][-1]
                        if last_value is None or latest.value != last_value:
                            callbacks = list(self._polling_callbacks.get(metric_name, []))
                        else:
                            callbacks = []
                        last_value = latest.value
                    else:
                        callbacks = []

                for callback in callbacks:
                    try:
                        callback(latest)
                    except Exception as e:
                        logger.error(f"Stream callback error for {metric_name}: {e}")

                time.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Metric poll loop error: {e}")
                time.sleep(interval_seconds * 2)

    def check_thresholds(self, metric_name: str) -> List[Dict[str, Any]]:
        """Check threshold rules for a metric.

        Args:
            metric_name: Name of the metric to check

        Returns:
            List of triggered threshold alerts
        """
        with self._lock:
            if metric_name not in self.metrics or not self.metrics[metric_name]:
                return []
            latest = self.metrics[metric_name][-1].value

            triggered = []
            for rule in self.threshold_rules.values():
                if not rule.enabled or rule.metric_name != metric_name:
                    continue

                is_triggered = False
                if rule.operator == "gt":
                    is_triggered = latest > rule.value
                elif rule.operator == "gte":
                    is_triggered = latest >= rule.value
                elif rule.operator == "lt":
                    is_triggered = latest < rule.value
                elif rule.operator == "lte":
                    is_triggered = latest <= rule.value
                elif rule.operator == "eq":
                    is_triggered = latest == rule.value
                elif rule.operator == "ne":
                    is_triggered = latest != rule.value

                if is_triggered:
                    triggered.append({
                        "rule_id": rule.rule_id,
                        "metric_name": rule.metric_name,
                        "operator": rule.operator,
                        "threshold": rule.value,
                        "current_value": latest,
                        "severity": rule.severity,
                        "message": rule.message.format(
                            metric=rule.metric_name,
                            value=latest,
                            threshold=rule.value,
                        ) if "{" in rule.message else rule.message,
                    })

            return triggered

    def check_all_thresholds(self) -> Dict[str, List[Dict[str, Any]]]:
        """Check all threshold rules against all metrics.

        Returns:
            Dictionary mapping metric names to triggered alerts
        """
        with self._lock:
            metric_names = list(self.metrics.keys())

        results = {}
        for name in metric_names:
            triggered = self.check_thresholds(name)
            if triggered:
                results[name] = triggered
        return results

    def analyze_trend(self, metric_name: str, window_minutes: int = 60) -> Optional[TrendResult]:
        """Analyze trend for a metric compared to historical baseline.

        Args:
            metric_name: Name of the metric
            window_minutes: Recent window for current trend

        Returns:
            TrendResult or None if insufficient data
        """
        with self._lock:
            if metric_name not in self.metrics or not self.metrics[metric_name]:
                return None

            metrics = self.metrics[metric_name]
            if len(metrics) < 10:
                return None

            now = datetime.now()
            recent_cutoff = now - timedelta(minutes=window_minutes)
            recent_values = [
                m.value for m in metrics if m.timestamp >= recent_cutoff
            ]
            historical_values = [
                m.value for m in metrics if m.timestamp < recent_cutoff
            ]

            if not recent_values:
                return None

            current_value = recent_values[-1]
            recent_avg = sum(recent_values) / len(recent_values)

            if not historical_values:
                historical_avg = recent_avg
            else:
                historical_avg = sum(historical_values) / len(historical_values)

            if historical_avg == 0:
                change_percent = 0.0
            else:
                change_percent = ((recent_avg - historical_avg) / abs(historical_avg)) * 100

            if change_percent > 10:
                direction = "increasing"
            elif change_percent < -10:
                direction = "decreasing"
            else:
                direction = "stable"

            variance = sum((v - historical_avg) ** 2 for v in historical_values) / len(historical_values) if historical_values else 0
            std_dev = variance ** 0.5
            is_anomalous = std_dev > 0 and abs(current_value - historical_avg) > 3 * std_dev

            confidence = min(100.0, len(recent_values) / window_minutes * 100)

            return TrendResult(
                metric_name=metric_name,
                current_value=current_value,
                historical_avg=historical_avg,
                change_percent=change_percent,
                trend_direction=direction,
                is_anomalous=is_anomalous,
                confidence=confidence,
            )

    def analyze_all_trends(self, window_minutes: int = 60) -> Dict[str, TrendResult]:
        """Analyze trends for all metrics.

        Args:
            window_minutes: Recent window for current trend

        Returns:
            Dictionary mapping metric names to TrendResults
        """
        with self._lock:
            metric_names = list(self.metrics.keys())

        results = {}
        for name in metric_names:
            trend = self.analyze_trend(name, window_minutes)
            if trend:
                results[name] = trend
        return results

    def create_template(
        self,
        template_id: str,
        name: str,
        description: str,
        widgets: Optional[List[Dict[str, Any]]] = None,
        refresh_interval: int = 30,
        config: Optional[Dict[str, Any]] = None,
    ) -> DashboardTemplate:
        """Create a dashboard template.

        Args:
            template_id: Unique identifier
            name: Template name
            description: Template description
            widgets: List of widget configurations
            refresh_interval: Default refresh interval
            config: Additional configuration

        Returns:
            The created template
        """
        template = DashboardTemplate(
            template_id=template_id,
            name=name,
            description=description,
            widgets=widgets or [],
            refresh_interval=refresh_interval,
            config=config or {},
        )
        with self._lock:
            self.dashboard_templates[template_id] = template
        logger.info(f"Created dashboard template: {name}")
        return template

    def apply_template(self, template_id: str, override_id: Optional[str] = None) -> bool:
        """Apply a dashboard template to create widgets.

        Args:
            template_id: ID of the template to apply
            override_id: Optional override dashboard ID

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if template_id not in self.dashboard_templates:
                logger.warning(f"Template not found: {template_id}")
                return False

            template = self.dashboard_templates[template_id]
            for w_cfg in template.widgets:
                widget = DashboardWidget(
                    widget_id=w_cfg.get("widget_id", f"w_{len(self.widgets)}_{int(time.time())}"),
                    widget_type=w_cfg["widget_type"],
                    title=w_cfg["title"],
                    metric_names=w_cfg.get("metric_names", []),
                    config=w_cfg.get("config", {}),
                )
                self.widgets[widget.widget_id] = widget

            if override_id:
                self.dashboard_id = override_id
            self.refresh_interval = template.refresh_interval

            logger.info(f"Applied template: {template.name}")
            return True

    def take_snapshot(self, description: str = "") -> DashboardSnapshot:
        """Take a snapshot of the current dashboard state.

        Args:
            description: Optional description for the snapshot

        Returns:
            The created snapshot
        """
        snapshot_id = f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.snapshots)}"
        data = self.export_dashboard_data()

        snapshot = DashboardSnapshot(
            snapshot_id=snapshot_id,
            timestamp=datetime.now(),
            dashboard_data=data,
            description=description,
        )
        with self._lock:
            self.snapshots.append(snapshot)
            if len(self.snapshots) > 100:
                self.snapshots = self.snapshots[-100:]

        logger.info(f"Took dashboard snapshot: {snapshot_id}")
        return snapshot

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Restore dashboard state from a snapshot.

        Args:
            snapshot_id: ID of the snapshot to restore

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            snapshot = None
            for s in self.snapshots:
                if s.snapshot_id == snapshot_id:
                    snapshot = s
                    break

            if not snapshot:
                logger.warning(f"Snapshot not found: {snapshot_id}")
                return False

            data = snapshot.dashboard_data
            self.metrics.clear()
            self.widgets.clear()

            for name, metric_list in data.get("metrics", {}).items():
                for m_data in metric_list:
                    metric = Metric(
                        name=name,
                        value=m_data["value"],
                        unit=m_data.get("unit", "count"),
                        timestamp=datetime.fromisoformat(m_data["timestamp"]),
                        labels=m_data.get("labels", {}),
                    )
                    self.metrics[name].append(metric)

            for widget_id, w_data in data.get("widgets", {}).items():
                widget = DashboardWidget(
                    widget_id=widget_id,
                    widget_type=w_data["widget_type"],
                    title=w_data["title"],
                    metric_names=w_data["metric_names"],
                    config=w_data.get("config", {}),
                )
                self.widgets[widget_id] = widget

            logger.info(f"Restored snapshot: {snapshot_id}")
            return True

    def get_snapshots(self) -> List[DashboardSnapshot]:
        """Get all dashboard snapshots.

        Returns:
            List of snapshots
        """
        with self._lock:
            return list(self.snapshots)

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a dashboard snapshot.

        Args:
            snapshot_id: ID of the snapshot to delete

        Returns:
            True if deleted, False otherwise
        """
        with self._lock:
            for i, s in enumerate(self.snapshots):
                if s.snapshot_id == snapshot_id:
                    del self.snapshots[i]
                    return True
            return False

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get a summary of the current dashboard state.

        Returns:
            Dictionary with dashboard summary
        """
        with self._lock:
            summary: Dict[str, Any] = {
                'dashboard_id': self.dashboard_id,
                'total_metrics': len(self.metrics),
                'total_widgets': len(self.widgets),
                'last_refresh': self.last_refresh.isoformat(),
                'refresh_interval': self.refresh_interval,
                'current_values': {},
                'system_health': 'healthy',
            }

            for name, metric_list in self.metrics.items():
                if metric_list:
                    latest = metric_list[-1]
                    summary['current_values'][name] = {
                        'value': latest.value,
                        'unit': latest.unit,
                        'timestamp': latest.timestamp.isoformat(),
                    }

            stale_threshold = timedelta(minutes=5)
            stale_metrics = []

            for name, metric_list in self.metrics.items():
                if metric_list:
                    latest = metric_list[-1]
                    if datetime.now() - latest.timestamp > stale_threshold:
                        stale_metrics.append(name)

            if stale_metrics:
                summary['system_health'] = 'degraded'
                summary['stale_metrics'] = stale_metrics

            threshold_triggers = self.check_all_thresholds()
            if threshold_triggers:
                summary['threshold_triggers'] = threshold_triggers
                summary['system_health'] = 'degraded'

            summary['total_metric_data_points'] = sum(
                len(v) for v in self.metrics.values()
            )
            summary['threshold_rules'] = len(self.threshold_rules)
            summary['templates'] = len(self.dashboard_templates)
            summary['snapshots'] = len(self.snapshots)

            return summary

    def calculate_aggregates(self, metric_name: str) -> Dict[str, float]:
        """Calculate aggregate statistics for a metric.

        Args:
            metric_name: Name of the metric

        Returns:
            Dictionary with aggregate statistics
        """
        with self._lock:
            if metric_name not in self.metrics or not self.metrics[metric_name]:
                return {}

            values = [m.value for m in self.metrics[metric_name]]
            sorted_vals = sorted(values)
            n = len(values)

            p50 = sorted_vals[int(n * 0.5)] if n > 0 else 0
            p95 = sorted_vals[int(n * 0.95)] if n > 0 else 0
            p99 = sorted_vals[int(n * 0.99)] if n > 0 else 0

            return {
                'count': n,
                'sum': sum(values),
                'avg': sum(values) / n,
                'min': min(values),
                'max': max(values),
                'latest': values[-1],
                'p50': p50,
                'p95': p95,
                'p99': p99,
                'range': max(values) - min(values),
            }

    def get_metric_statistics(
        self,
        metric_name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get detailed statistics for a metric over a time range.

        Args:
            metric_name: Name of the metric
            start_time: Optional start time
            end_time: Optional end time

        Returns:
            Dictionary with detailed statistics
        """
        history = self.get_metric_history(metric_name, start_time, end_time)
        if not history:
            return {}

        values = [m.value for m in history]
        timestamps = [m.timestamp for m in history]
        sorted_vals = sorted(values)
        n = len(values)

        if n == 0:
            return {}

        p50 = sorted_vals[int(n * 0.5)]
        p95 = sorted_vals[int(n * 0.95)]
        p99 = sorted_vals[int(n * 0.99)]

        variance = sum((v - (sum(values) / n)) ** 2 for v in values) / n
        std_dev = variance ** 0.5

        return {
            'metric': metric_name,
            'count': n,
            'sum': sum(values),
            'avg': sum(values) / n,
            'min': min(values),
            'max': max(values),
            'p50': p50,
            'p95': p95,
            'p99': p99,
            'std_dev': std_dev,
            'variance': variance,
            'latest': values[-1],
            'latest_timestamp': timestamps[-1].isoformat(),
            'earliest_timestamp': timestamps[0].isoformat(),
            'timespan_seconds': (timestamps[-1] - timestamps[0]).total_seconds(),
        }

    def correlate_metrics(self, metric_a: str, metric_b: str) -> Optional[Dict[str, float]]:
        """Calculate correlation between two metrics.

        Args:
            metric_a: First metric name
            metric_b: Second metric name

        Returns:
            Correlation statistics or None if insufficient data
        """
        with self._lock:
            if metric_a not in self.metrics or metric_b not in self.metrics:
                return None

            a_values = self.metrics[metric_a]
            b_values = self.metrics[metric_b]

            min_len = min(len(a_values), len(b_values))
            if min_len < 5:
                return None

            pairs = list(zip(
                [m.value for m in a_values[-min_len:]],
                [m.value for m in b_values[-min_len:]],
            ))

            n = len(pairs)
            sum_x = sum(p[0] for p in pairs)
            sum_y = sum(p[1] for p in pairs)
            sum_xy = sum(p[0] * p[1] for p in pairs)
            sum_x2 = sum(p[0] ** 2 for p in pairs)
            sum_y2 = sum(p[1] ** 2 for p in pairs)

            numerator = n * sum_xy - sum_x * sum_y
            denominator = ((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2)) ** 0.5

            if denominator == 0:
                return None

            correlation = numerator / denominator

            return {
                'metric_a': metric_a,
                'metric_b': metric_b,
                'correlation': correlation,
                'strength': 'strong' if abs(correlation) > 0.7 else 'moderate' if abs(correlation) > 0.4 else 'weak',
                'direction': 'positive' if correlation > 0 else 'negative',
                'data_points': n,
            }

    def export_dashboard_data(self) -> Dict[str, Any]:
        """Export all dashboard data for external use.

        Returns:
            Dictionary with all dashboard data
        """
        with self._lock:
            export_data: Dict[str, Any] = {
                'dashboard_id': self.dashboard_id,
                'exported_at': datetime.now().isoformat(),
                'metrics': {},
                'widgets': {},
            }

            for name, metric_list in self.metrics.items():
                export_data['metrics'][name] = [
                    {
                        'value': m.value,
                        'unit': m.unit,
                        'timestamp': m.timestamp.isoformat(),
                        'labels': m.labels,
                    }
                    for m in metric_list
                ]

            for widget_id, widget in self.widgets.items():
                export_data['widgets'][widget_id] = {
                    'widget_type': widget.widget_type,
                    'title': widget.title,
                    'metric_names': widget.metric_names,
                    'config': widget.config,
                }

            return export_data

    def export_to_json(self, filepath: str) -> bool:
        """Export dashboard data to a JSON file.

        Args:
            filepath: Path for the output file

        Returns:
            True if successful, False otherwise
        """
        try:
            data = self.export_dashboard_data()
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            logger.info(f"Exported dashboard data to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export dashboard: {e}")
            return False

    def import_from_json(self, filepath: str) -> bool:
        """Import dashboard data from a JSON file.

        Args:
            filepath: Path to the input file

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            with self._lock:
                self.metrics.clear()
                self.widgets.clear()

                for name, metric_list in data.get("metrics", {}).items():
                    for m_data in metric_list:
                        metric = Metric(
                            name=name,
                            value=m_data["value"],
                            unit=m_data.get("unit", "count"),
                            timestamp=datetime.fromisoformat(m_data["timestamp"]),
                            labels=m_data.get("labels", {}),
                        )
                        self.metrics[name].append(metric)

                for widget_id, w_data in data.get("widgets", {}).items():
                    widget = DashboardWidget(
                        widget_id=widget_id,
                        widget_type=w_data["widget_type"],
                        title=w_data["title"],
                        metric_names=w_data["metric_names"],
                        config=w_data.get("config", {}),
                    )
                    self.widgets[widget_id] = widget

            logger.info(f"Imported dashboard data from {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to import dashboard: {e}")
            return False

    def clear_metrics(self, metric_name: Optional[str] = None) -> int:
        """Clear metric data.

        Args:
            metric_name: Optional specific metric to clear

        Returns:
            Number of data points cleared
        """
        with self._lock:
            if metric_name:
                if metric_name in self.metrics:
                    count = len(self.metrics[metric_name])
                    del self.metrics[metric_name]
                    return count
                return 0
            else:
                count = sum(len(v) for v in self.metrics.values())
                self.metrics.clear()
                return count

    def get_supported_widget_types(self) -> List[str]:
        """Get list of supported widget types.

        Returns:
            List of widget type strings
        """
        return [
            "chart",
            "gauge",
            "table",
            "stat",
            "heatmap",
            "list",
            "markdown",
            "alert_list",
            "top_n",
            "time_series",
        ]

    def get_config(self) -> Dict[str, Any]:
        """Get current dashboard configuration.

        Returns:
            Configuration dictionary
        """
        return {
            "dashboard_id": self.dashboard_id,
            "refresh_interval": self.refresh_interval,
            "alerts_enabled": self.alerts_enabled,
            "widget_count": len(self.widgets),
            "metric_count": len(self.metrics),
            "threshold_rules": len(self.threshold_rules),
            "templates": len(self.dashboard_templates),
            "snapshots": len(self.snapshots),
            "active_streams": len(self._polling_threads),
        }
