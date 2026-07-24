"""Metrics collection system for recording and querying metric data points."""
import csv
import io
import json
import logging
import threading
import time
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DataPoint:
    """A single metric data point."""
    value: float
    timestamp: datetime
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class MetricDefinition:
    """Definition of a metric."""
    name: str
    description: str
    unit: str
    metric_type: str = "gauge"
    retention_days: int = 30
    max_data_points: int = 100000
    labels: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class AggregatedValue:
    """An aggregated metric value."""
    value: float
    aggregation: str
    count: int
    start_time: datetime
    end_time: datetime


class MetricsCollector:
    """Collects, stores, and queries metric data points with aggregation support."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the metrics collector.

        Args:
            config: Optional configuration dictionary
        """
        self._lock = threading.RLock()
        self._metrics: Dict[str, List[DataPoint]] = defaultdict(list)
        self._definitions: Dict[str, MetricDefinition] = {}
        self._prune_thread: Optional[threading.Thread] = None
        self._prune_running = False
        self._config = config or {}
        self._created_at = datetime.now()

        self.default_retention_days = self._config.get("default_retention_days", 30)
        self.default_max_points = self._config.get("default_max_data_points", 100000)
        self.prune_interval_minutes = self._config.get("prune_interval_minutes", 60)
        self.collector_name = self._config.get("collector_name", "default")

        if self._config.get("metric_definitions"):
            self._load_definitions_from_config(self._config["metric_definitions"])

        logger.info(f"MetricsCollector '{self.collector_name}' initialized")

    def _load_definitions_from_config(self, defs_config: List[Dict[str, Any]]) -> None:
        """Load metric definitions from configuration.

        Args:
            defs_config: List of metric definition dictionaries
        """
        for cfg in defs_config:
            try:
                definition = MetricDefinition(
                    name=cfg["name"],
                    description=cfg.get("description", ""),
                    unit=cfg.get("unit", "count"),
                    metric_type=cfg.get("metric_type", "gauge"),
                    retention_days=cfg.get("retention_days", self.default_retention_days),
                    max_data_points=cfg.get("max_data_points", self.default_max_points),
                    labels=cfg.get("labels", {}),
                    enabled=cfg.get("enabled", True),
                )
                self._definitions[definition.name] = definition
                logger.info(f"Loaded metric definition: {definition.name}")
            except Exception as e:
                logger.error(f"Failed to load metric definition: {e}")

    def define_metric(self, definition: MetricDefinition) -> None:
        """Register a metric definition.

        Args:
            definition: MetricDefinition to register
        """
        with self._lock:
            self._definitions[definition.name] = definition
        logger.info(f"Defined metric: {definition.name} ({definition.metric_type})")

    def get_definition(self, name: str) -> Optional[MetricDefinition]:
        """Get a metric's definition.

        Args:
            name: Metric name

        Returns:
            MetricDefinition or None
        """
        with self._lock:
            return self._definitions.get(name)

    def record_metric(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Record a metric data point.

        Args:
            name: Metric name
            value: Metric value
            labels: Optional label dictionary
            timestamp: Optional timestamp (defaults to now)
        """
        definition = self._definitions.get(name)
        if definition and not definition.enabled:
            logger.debug(f"Metric {name} is disabled, skipping")
            return

        ts = timestamp or datetime.now()
        point = DataPoint(
            value=value,
            timestamp=ts,
            labels=labels or {},
        )

        with self._lock:
            metric_list = self._metrics[name]
            metric_list.append(point)

            max_points = definition.max_data_points if definition else self.default_max_points
            if len(metric_list) > max_points:
                self._metrics[name] = metric_list[-max_points:]

        logger.debug(f"Recorded metric {name}: {value} at {ts.isoformat()}")

    def record_metrics_batch(
        self,
        metrics: List[Tuple[str, float, Optional[Dict[str, str]], Optional[datetime]]],
    ) -> int:
        """Record multiple metric data points efficiently.

        Args:
            metrics: List of (name, value, labels, timestamp) tuples

        Returns:
            Number of metrics recorded
        """
        count = 0
        for name, value, labels, timestamp in metrics:
            try:
                self.record_metric(name, value, labels, timestamp)
                count += 1
            except Exception as e:
                logger.error(f"Failed to record batch metric {name}: {e}")
        return count

    def get_metric(
        self,
        name: str,
        aggregation: str = "avg",
        window_seconds: Optional[int] = None,
        labels: Optional[Dict[str, str]] = None,
    ) -> Optional[AggregatedValue]:
        """Get an aggregated metric value.

        Args:
            name: Metric name
            aggregation: Aggregation function (sum, avg, min, max, count, p50, p95, p99)
            window_seconds: Optional time window in seconds
            labels: Optional label filter

        Returns:
            AggregatedValue or None if no data
        """
        with self._lock:
            if name not in self._metrics or not self._metrics[name]:
                return None

            points = self._metrics[name]

            if window_seconds is not None:
                cutoff = datetime.now() - timedelta(seconds=window_seconds)
                points = [p for p in points if p.timestamp >= cutoff]

            if labels:
                points = [
                    p for p in points
                    if all(p.labels.get(k) == v for k, v in labels.items())
                ]

            if not points:
                return None

            values = [p.value for p in points]
            start_time = points[0].timestamp
            end_time = points[-1].timestamp

            result = self._apply_aggregation(values, aggregation)

            return AggregatedValue(
                value=result,
                aggregation=aggregation,
                count=len(values),
                start_time=start_time,
                end_time=end_time,
            )

    def get_metric_history(
        self,
        name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        labels: Optional[Dict[str, str]] = None,
    ) -> List[DataPoint]:
        """Get raw metric data points within a time range.

        Args:
            name: Metric name
            start_time: Optional start time
            end_time: Optional end time
            labels: Optional label filter

        Returns:
            List of DataPoints
        """
        with self._lock:
            if name not in self._metrics:
                return []

            points = self._metrics[name]

            if start_time:
                points = [p for p in points if p.timestamp >= start_time]
            if end_time:
                points = [p for p in points if p.timestamp <= end_time]
            if labels:
                points = [
                    p for p in points
                    if all(p.labels.get(k) == v for k, v in labels.items())
                ]

            return points

    def _apply_aggregation(self, values: List[float], aggregation: str) -> float:
        """Apply an aggregation function to a list of values.

        Args:
            values: List of float values
            aggregation: Aggregation function name

        Returns:
            Aggregated result
        """
        n = len(values)
        if n == 0:
            return 0.0

        if aggregation == "sum":
            return sum(values)
        elif aggregation == "avg":
            return sum(values) / n
        elif aggregation == "min":
            return min(values)
        elif aggregation == "max":
            return max(values)
        elif aggregation == "count":
            return float(n)
        elif aggregation == "p50":
            sorted_vals = sorted(values)
            return sorted_vals[int(n * 0.5)]
        elif aggregation == "p95":
            sorted_vals = sorted(values)
            return sorted_vals[min(int(n * 0.95), n - 1)]
        elif aggregation == "p99":
            sorted_vals = sorted(values)
            return sorted_vals[min(int(n * 0.99), n - 1)]
        elif aggregation == "stddev":
            if n < 2:
                return 0.0
            mean = sum(values) / n
            variance = sum((v - mean) ** 2 for v in values) / n
            return math.sqrt(variance)
        elif aggregation == "variance":
            if n < 2:
                return 0.0
            mean = sum(values) / n
            return sum((v - mean) ** 2 for v in values) / n
        elif aggregation == "rate":
            if n < 2:
                return 0.0
            return (values[-1] - values[0]) / n
        elif aggregation == "median":
            sorted_vals = sorted(values)
            if n % 2 == 1:
                return sorted_vals[n // 2]
            return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0
        elif aggregation == "first":
            return values[0]
        elif aggregation == "last":
            return values[-1]
        elif aggregation == "delta":
            if n < 2:
                return 0.0
            return values[-1] - values[0]
        else:
            logger.warning(f"Unknown aggregation: {aggregation}, using avg")
            return sum(values) / n

    def get_multiple_metrics(
        self,
        names: List[str],
        aggregation: str = "avg",
        window_seconds: Optional[int] = None,
    ) -> Dict[str, Optional[AggregatedValue]]:
        """Get aggregated values for multiple metrics.

        Args:
            names: List of metric names
            aggregation: Aggregation function
            window_seconds: Optional time window

        Returns:
            Dictionary mapping metric names to AggregatedValues
        """
        results = {}
        for name in names:
            results[name] = self.get_metric(name, aggregation, window_seconds)
        return results

    def get_metric_names(self) -> List[str]:
        """Get list of all metric names with data.

        Returns:
            List of metric name strings
        """
        with self._lock:
            return list(self._metrics.keys())

    def get_defined_metric_names(self) -> List[str]:
        """Get list of all defined metric names.

        Returns:
            List of defined metric name strings
        """
        with self._lock:
            return list(self._definitions.keys())

    def data_point_count(self, name: Optional[str] = None) -> int:
        """Get the number of data points stored.

        Args:
            name: Optional specific metric name

        Returns:
            Number of data points
        """
        with self._lock:
            if name:
                return len(self._metrics.get(name, []))
            return sum(len(points) for points in self._metrics.values())

    def _prune_old_data(self) -> None:
        """Background thread: remove data points exceeding retention."""
        while self._prune_running:
            try:
                now = datetime.now()
                total_pruned = 0

                with self._lock:
                    names_to_check = list(self._metrics.keys())

                for name in names_to_check:
                    try:
                        definition = self._definitions.get(name)
                        retention_days = (
                            definition.retention_days if definition
                            else self.default_retention_days
                        )
                        max_points = (
                            definition.max_data_points if definition
                            else self.default_max_points
                        )

                        cutoff = now - timedelta(days=retention_days)

                        with self._lock:
                            if name not in self._metrics:
                                continue

                            points = self._metrics[name]
                            before = len(points)

                            points = [p for p in points if p.timestamp >= cutoff]

                            if len(points) > max_points:
                                points = points[-max_points:]

                            pruned = before - len(points)
                            if pruned > 0:
                                self._metrics[name] = points
                                total_pruned += pruned

                    except Exception as e:
                        logger.error(f"Error pruning metric {name}: {e}")

                if total_pruned > 0:
                    logger.info(f"Pruned {total_pruned} data points")

                time.sleep(self.prune_interval_minutes * 60)
            except Exception as e:
                logger.error(f"Prune loop error: {e}")
                time.sleep(300)

    def start_pruning(self) -> None:
        """Start background pruning thread."""
        if self._prune_thread and self._prune_thread.is_alive():
            logger.warning("Pruning already running")
            return
        self._prune_running = True
        self._prune_thread = threading.Thread(
            target=self._prune_old_data,
            daemon=True,
            name="metrics-collector-prune",
        )
        self._prune_thread.start()
        logger.info("Data pruning started")

    def stop_pruning(self) -> None:
        """Stop background pruning thread."""
        self._prune_running = False
        if self._prune_thread:
            self._prune_thread.join(timeout=10)
            logger.info("Data pruning stopped")

    def force_prune(self) -> int:
        """Force an immediate pruning of old data.

        Returns:
            Number of data points pruned
        """
        now = datetime.now()
        total_pruned = 0

        with self._lock:
            names = list(self._metrics.keys())

        for name in names:
            definition = self._definitions.get(name)
            retention_days = (
                definition.retention_days if definition else self.default_retention_days
            )
            max_points = (
                definition.max_data_points if definition else self.default_max_points
            )
            cutoff = now - timedelta(days=retention_days)

            with self._lock:
                if name not in self._metrics:
                    continue
                points = self._metrics[name]
                before = len(points)
                points = [p for p in points if p.timestamp >= cutoff]
                if len(points) > max_points:
                    points = points[-max_points:]
                self._metrics[name] = points
                total_pruned += before - len(points)

        if total_pruned > 0:
            logger.info(f"Forced prune removed {total_pruned} data points")
        return total_pruned

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text-based format.

        Returns:
            Prometheus-formatted string
        """
        lines: List[str] = []
        lines.append(f"# HELP metrics_collector_data_points Total data points stored")
        lines.append(f"# TYPE metrics_collector_data_points gauge")
        lines.append(f"metrics_collector_data_points {self.data_point_count()}")

        with self._lock:
            for name, points in self._metrics.items():
                definition = self._definitions.get(name)
                metric_type = definition.metric_type if definition else "gauge"
                description = definition.description if definition else name

                prom_name = name.replace(".", "_").replace("-", "_").replace(" ", "_")
                lines.append(f"# HELP {prom_name} {description}")
                lines.append(f"# TYPE {prom_name} {metric_type}")

                if not points:
                    continue

                if metric_type == "counter":
                    latest = points[-1]
                    label_str = self._format_prometheus_labels(latest.labels)
                    lines.append(f"{prom_name}{label_str} {latest.value}")

                elif metric_type == "gauge":
                    latest = points[-1]
                    label_str = self._format_prometheus_labels(latest.labels)
                    lines.append(f"{prom_name}{label_str} {latest.value}")

                elif metric_type == "histogram":
                    values = [p.value for p in points[-1000:]]
                    buckets = [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0]
                    for bucket in buckets:
                        count = sum(1 for v in values if v <= bucket)
                        bucket_str = f'{prom_name}_bucket{{le="{bucket}"}} {count}'
                        lines.append(bucket_str)
                    lines.append(f'{prom_name}_bucket{{le="+Inf"}} {len(values)}')
                    lines.append(f"{prom_name}_count {len(values)}")
                    lines.append(f"{prom_name}_sum {sum(values)}")

                elif metric_type == "summary":
                    values = sorted(p.value for p in points[-1000:])
                    n = len(values)
                    if n > 0:
                        p50 = values[int(n * 0.5)]
                        p90 = values[int(n * 0.9)]
                        p99 = values[int(n * 0.99)]
                        lines.append(f'{prom_name}{{quantile="0.5"}} {p50}')
                        lines.append(f'{prom_name}{{quantile="0.9"}} {p90}')
                        lines.append(f'{prom_name}{{quantile="0.99"}} {p99}')
                        lines.append(f"{prom_name}_count {n}")
                        lines.append(f"{prom_name}_sum {sum(values)}")

        return "\n".join(lines) + "\n"

    @staticmethod
    def _format_prometheus_labels(labels: Dict[str, str]) -> str:
        """Format labels for Prometheus output.

        Args:
            labels: Dictionary of label key-value pairs

        Returns:
            Formatted label string
        """
        if not labels:
            return ""
        parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(parts) + "}"

    def export_json(self, name: Optional[str] = None) -> str:
        """Export metrics as a JSON string.

        Args:
            name: Optional specific metric name

        Returns:
            JSON string
        """
        with self._lock:
            if name:
                if name not in self._metrics:
                    return "{}"
                metrics_data = {
                    name: [
                        {
                            "value": p.value,
                            "timestamp": p.timestamp.isoformat(),
                            "labels": p.labels,
                        }
                        for p in self._metrics[name]
                    ]
                }
            else:
                metrics_data = {}
                for metric_name, points in self._metrics.items():
                    metrics_data[metric_name] = [
                        {
                            "value": p.value,
                            "timestamp": p.timestamp.isoformat(),
                            "labels": p.labels,
                        }
                        for p in points
                    ]

            return json.dumps(metrics_data, indent=2)

    def export_to_file(self, filepath: str, fmt: str = "json") -> bool:
        """Export metrics to a file.

        Args:
            filepath: Output file path
            fmt: Format - "json" or "prometheus"

        Returns:
            True if successful, False otherwise
        """
        try:
            if fmt == "prometheus":
                content = self.export_prometheus()
            else:
                content = self.export_json()

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"Exported metrics to {filepath} ({fmt})")
            return True
        except Exception as e:
            logger.error(f"Failed to export metrics: {e}")
            return False

    def export_csv(self, name: str, filepath: str) -> bool:
        """Export a specific metric to a CSV file.

        Args:
            name: Metric name to export
            filepath: Output file path

        Returns:
            True if successful, False otherwise
        """
        try:
            with self._lock:
                if name not in self._metrics or not self._metrics[name]:
                    logger.warning(f"No data for metric {name}")
                    return False
                points = self._metrics[name]

            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                fieldnames = ["timestamp", "value", "labels"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for p in points:
                    writer.writerow({
                        "timestamp": p.timestamp.isoformat(),
                        "value": p.value,
                        "labels": json.dumps(p.labels),
                    })

            logger.info(f"Exported metric {name} to CSV: {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export CSV: {e}")
            return False

    def export_csv_string(self, name: str) -> Optional[str]:
        """Export a specific metric as a CSV string.

        Args:
            name: Metric name to export

        Returns:
            CSV string or None
        """
        try:
            with self._lock:
                if name not in self._metrics or not self._metrics[name]:
                    return None
                points = self._metrics[name]

            output = io.StringIO()
            fieldnames = ["timestamp", "value", "labels"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for p in points:
                writer.writerow({
                    "timestamp": p.timestamp.isoformat(),
                    "value": p.value,
                    "labels": json.dumps(p.labels),
                })
            return output.getvalue()
        except Exception as e:
            logger.error(f"Failed to export CSV string: {e}")
            return None

    def delete_metric(self, name: str) -> bool:
        """Delete a metric and all its data.

        Args:
            name: Metric name to delete

        Returns:
            True if deleted, False otherwise
        """
        with self._lock:
            if name in self._metrics:
                del self._metrics[name]
                self._definitions.pop(name, None)
                logger.info(f"Deleted metric: {name}")
                return True
            return False

    def clear_all(self) -> int:
        """Clear all metric data.

        Returns:
            Number of data points cleared
        """
        with self._lock:
            total = sum(len(points) for points in self._metrics.values())
            self._metrics.clear()
            logger.info(f"Cleared all metrics data ({total} points)")
            return total

    def get_statistics(self) -> Dict[str, Any]:
        """Get overall collector statistics.

        Returns:
            Dictionary with statistics
        """
        with self._lock:
            total_points = sum(len(points) for points in self._metrics.values())
            metric_counts = {name: len(points) for name, points in self._metrics.items()}

            return {
                "collector_name": self.collector_name,
                "total_metrics": len(self._metrics),
                "total_definitions": len(self._definitions),
                "total_data_points": total_points,
                "metrics": metric_counts,
                "pruning_running": self._prune_running,
                "default_retention_days": self.default_retention_days,
                "uptime_seconds": (datetime.now() - self._created_at).total_seconds(),
                "created_at": self._created_at.isoformat(),
            }

    def get_time_bounds(self, name: str) -> Optional[Tuple[datetime, datetime]]:
        """Get the earliest and latest timestamps for a metric.

        Args:
            name: Metric name

        Returns:
            (earliest, latest) tuple or None
        """
        with self._lock:
            if name not in self._metrics or not self._metrics[name]:
                return None
            points = self._metrics[name]
            return (points[0].timestamp, points[-1].timestamp)

    def has_metric(self, name: str) -> bool:
        """Check if a metric exists with data.

        Args:
            name: Metric name

        Returns:
            True if metric has data
        """
        with self._lock:
            return name in self._metrics and len(self._metrics[name]) > 0

    def get_dashboard_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics formatted for dashboard display.

        Returns:
            Dictionary of metric names to display data
        """
        dashboard = {}
        with self._lock:
            for name, points in self._metrics.items():
                if not points:
                    continue
                latest = points[-1]
                values = [p.value for p in points]
                dashboard[name] = {
                    "latest": latest.value,
                    "latest_timestamp": latest.timestamp.isoformat(),
                    "unit": self._definitions[name].unit if name in self._definitions else "count",
                    "count": len(values),
                    "min": min(values),
                    "max": max(values),
                    "avg": sum(values) / len(values),
                    "last_10_values": [p.value for p in points[-10:]],
                }
        return dashboard

    def get_config(self) -> Dict[str, Any]:
        """Get current collector configuration.

        Returns:
            Configuration dictionary
        """
        return {
            "collector_name": self.collector_name,
            "default_retention_days": self.default_retention_days,
            "default_max_data_points": self.default_max_points,
            "prune_interval_minutes": self.prune_interval_minutes,
            "total_definitions": len(self._definitions),
            "pruning_running": self._prune_running,
        }

    def aggregate_range(
        self,
        name: str,
        aggregation: str,
        interval_minutes: int,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[AggregatedValue]:
        """Aggregate a metric over regular time intervals.

        Args:
            name: Metric name
            aggregation: Aggregation function
            interval_minutes: Interval size in minutes
            start_time: Optional start time
            end_time: Optional end time

        Returns:
            List of AggregatedValues per interval
        """
        end = end_time or datetime.now()
        start = start_time or (end - timedelta(hours=1))
        interval = timedelta(minutes=interval_minutes)

        results = []
        current = start
        while current < end:
            interval_end = min(current + interval, end)
            points = self.get_metric_history(name, current, interval_end)
            if points:
                values = [p.value for p in points]
                agg_value = self._apply_aggregation(values, aggregation)
                results.append(AggregatedValue(
                    value=agg_value,
                    aggregation=aggregation,
                    count=len(values),
                    start_time=current,
                    end_time=interval_end,
                ))
            current = interval_end

        return results

    def top_metrics_by_count(self, n: int = 10) -> List[Tuple[str, int]]:
        """Get the top N metrics by data point count.

        Args:
            n: Number of metrics to return

        Returns:
            List of (metric_name, count) tuples
        """
        with self._lock:
            sorted_metrics = sorted(
                self._metrics.items(),
                key=lambda x: len(x[1]),
                reverse=True,
            )
            return [(name, len(points)) for name, points in sorted_metrics[:n]]
