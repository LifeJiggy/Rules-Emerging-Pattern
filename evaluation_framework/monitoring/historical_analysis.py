"""Historical trend analysis, anomaly detection, and forecasting for rule system metrics."""
import logging
import math
import statistics
from typing import List, Dict, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


@dataclass
class MetricDataPoint:
    timestamp: datetime
    metric_name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class TrendResult:
    metric_name: str
    direction: str
    slope: float
    percent_change: float
    is_significant: bool
    data_points: int


@dataclass
class AnomalyResult:
    metric_name: str
    current_value: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    is_anomaly: bool
    severity: str


@dataclass
class ForecastResult:
    metric_name: str
    next_value: float
    confidence_upper: float
    confidence_lower: float
    seasonality_period: Optional[int]


@dataclass
class HistoricalAnalysisReport:
    timeframe: str
    total_metrics: int
    trends: List[TrendResult]
    anomalies: List[AnomalyResult]
    forecasts: List[ForecastResult]
    summary: Dict[str, Any]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HistoricalAnalysis:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._data: Dict[str, List[MetricDataPoint]] = defaultdict(list)
        self._max_points_per_metric = self.config.get("max_points_per_metric", 100000)
        self._anomaly_z_threshold = self.config.get("anomaly_z_threshold", 2.5)
        self._trend_significance_pct = self.config.get("trend_significance_pct", 5.0)
        self._reports: List[HistoricalAnalysisReport] = []
        logger.info("HistoricalAnalysis initialized (z_threshold=%.2f, trend_significance=%.1f%%)",
                     self._anomaly_z_threshold, self._trend_significance_pct)

    def record(self, metric_name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        point = MetricDataPoint(
            timestamp=datetime.now(timezone.utc),
            metric_name=metric_name,
            value=value,
            labels=labels or {},
        )

        points = self._data[metric_name]
        points.append(point)

        if len(points) > self._max_points_per_metric:
            points.pop(0)

    def record_many(self, data_points: List[Dict[str, Any]]) -> None:
        for dp in data_points:
            self.record(
                metric_name=dp["metric_name"],
                value=dp["value"],
                labels=dp.get("labels"),
            )

    def record_batch(self, metrics: Dict[str, float]) -> None:
        for name, value in metrics.items():
            self.record(name, value)

    def analyze_history(
        self,
        timeframe: str = "30d",
        metrics: Optional[List[str]] = None
    ) -> HistoricalAnalysisReport:
        cutoff = self._parse_timeframe(timeframe)
        target_metrics = metrics or list(self._data.keys())

        trends: List[TrendResult] = []
        anomalies: List[AnomalyResult] = []
        forecasts: List[ForecastResult] = []

        for metric_name in target_metrics:
            points = [p for p in self._data.get(metric_name, [])
                     if p.timestamp >= cutoff]
            if len(points) < 3:
                continue

            trend = self._analyze_trend(points, metric_name)
            if trend:
                trends.append(trend)

            anomaly = self._detect_anomaly(points, metric_name)
            if anomaly:
                anomalies.append(anomaly)

            forecast = self._forecast(points, metric_name)
            if forecast:
                forecasts.append(forecast)

        summary = self._build_summary(trends, anomalies, forecasts)

        report = HistoricalAnalysisReport(
            timeframe=timeframe,
            total_metrics=len(target_metrics),
            trends=trends,
            anomalies=anomalies,
            forecasts=forecasts,
            summary=summary,
        )

        self._reports.append(report)
        logger.info(
            "Historical analysis complete: %d metrics, %d trends, %d anomalies, %d forecasts",
            len(target_metrics), len(trends), len(anomalies), len(forecasts)
        )
        return report

    def get_latest_report(self) -> Optional[HistoricalAnalysisReport]:
        return self._reports[-1] if self._reports else None

    def query_metric(
        self,
        metric_name: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[MetricDataPoint]:
        points = self._data.get(metric_name, [])
        if since:
            points = [p for p in points if p.timestamp >= since]
        if until:
            points = [p for p in points if p.timestamp <= until]
        return points[-limit:]

    def get_summary_statistics(self, metric_name: str) -> Dict[str, float]:
        points = self._data.get(metric_name, [])
        if not points:
            return {}

        values = [p.value for p in points]
        sorted_vals = sorted(values)
        n = len(values)

        return {
            "count": n,
            "min": min(values),
            "max": max(values),
            "mean": statistics.mean(values),
            "median": sorted_vals[n // 2],
            "stdev": statistics.stdev(values) if n > 1 else 0.0,
            "p95": sorted_vals[int(n * 0.95)],
            "p99": sorted_vals[int(n * 0.99)],
            "sum": sum(values),
            "latest": values[-1],
        }

    def _analyze_trend(
        self,
        points: List[MetricDataPoint],
        metric_name: str
    ) -> Optional[TrendResult]:
        if len(points) < 5:
            return None

        values = [p.value for p in points]
        indices = list(range(len(values)))

        n = len(indices)
        sum_x = sum(indices)
        sum_y = sum(values)
        sum_xy = sum(x * y for x, y in zip(indices, values))
        sum_xx = sum(x * x for x in indices)

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x * sum_x) if (n * sum_xx - sum_x * sum_x) != 0 else 0

        mean_y = sum_y / n
        percent_change = (slope * n / abs(mean_y)) * 100 if abs(mean_y) > 1e-10 else 0

        direction = "up" if slope > 0 else ("down" if slope < 0 else "stable")
        is_significant = abs(percent_change) >= self._trend_significance_pct

        return TrendResult(
            metric_name=metric_name,
            direction=direction,
            slope=round(slope, 4),
            percent_change=round(percent_change, 2),
            is_significant=is_significant,
            data_points=len(points),
        )

    def _detect_anomaly(
        self,
        points: List[MetricDataPoint],
        metric_name: str
    ) -> Optional[AnomalyResult]:
        if len(points) < 10:
            return None

        values = [p.value for p in points]
        current = values[-1]
        baseline = values[:-1]

        mean = statistics.mean(baseline)
        stdev = statistics.stdev(baseline) if len(baseline) > 1 else 0.0

        if stdev < 1e-10:
            return None

        z_score = abs((current - mean) / stdev)
        is_anomaly = z_score >= self._anomaly_z_threshold

        severity = "critical" if z_score >= 4.0 else (
            "high" if z_score >= 3.0 else (
                "medium" if z_score >= self._anomaly_z_threshold else "low"
            )
        )

        return AnomalyResult(
            metric_name=metric_name,
            current_value=current,
            baseline_mean=round(mean, 4),
            baseline_std=round(stdev, 4),
            z_score=round(z_score, 2),
            is_anomaly=is_anomaly,
            severity=severity if is_anomaly else "none",
        )

    def _forecast(
        self,
        points: List[MetricDataPoint],
        metric_name: str
    ) -> Optional[ForecastResult]:
        if len(points) < 10:
            return None

        values = [p.value for p in points]
        n = len(values)

        recent = values[-min(7, n):]
        next_val = sum(recent) / len(recent)

        residuals = [abs(v - next_val) for v in recent]
        mae = sum(residuals) / len(residuals)

        seasonality = self._detect_seasonality(values)

        return ForecastResult(
            metric_name=metric_name,
            next_value=round(next_val, 4),
            confidence_upper=round(next_val + 2 * mae, 4),
            confidence_lower=round(max(0, next_val - 2 * mae), 4),
            seasonality_period=seasonality,
        )

    def _detect_seasonality(self, values: List[float]) -> Optional[int]:
        if len(values) < 20:
            return None

        for period in [7, 24, 12, 30]:
            if len(values) >= period * 2:
                segments = [values[i:i + period] for i in range(0, len(values), period)][:5]
                if len(segments) >= 2:
                    correlations = []
                    for i in range(len(segments) - 1):
                        if len(segments[i]) == len(segments[i + 1]):
                            try:
                                corr = statistics.correlation(segments[i], segments[i + 1])
                                correlations.append(corr)
                            except Exception:
                                pass
                    if correlations and statistics.mean(correlations) > 0.7:
                        return period
        return None

    def _build_summary(
        self,
        trends: List[TrendResult],
        anomalies: List[AnomalyResult],
        forecasts: List[ForecastResult]
    ) -> Dict[str, Any]:
        significant_trends = [t for t in trends if t.is_significant]
        real_anomalies = [a for a in anomalies if a.is_anomaly]

        return {
            "total_significant_trends": len(significant_trends),
            "trending_up": len([t for t in significant_trends if t.direction == "up"]),
            "trending_down": len([t for t in significant_trends if t.direction == "down"]),
            "total_anomalies": len(real_anomalies),
            "critical_anomalies": len([a for a in real_anomalies if a.severity == "critical"]),
            "forecasts_available": len(forecasts),
        }

    def _parse_timeframe(self, timeframe: str) -> datetime:
        now = datetime.now(timezone.utc)

        unit = timeframe[-1]
        value = int(timeframe[:-1])

        if unit == "h":
            return now - timedelta(hours=value)
        elif unit == "d":
            return now - timedelta(days=value)
        elif unit == "w":
            return now - timedelta(weeks=value)
        elif unit == "m":
            return now - timedelta(days=value * 30)
        else:
            return now - timedelta(days=30)
