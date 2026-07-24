"""Trend analysis module for detecting emerging patterns."""
import logging
import json
import math
import statistics
import uuid
from typing import Dict, List, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from enum import Enum
from itertools import combinations

logger = logging.getLogger(__name__)


class ForecastMethod(Enum):
    LINEAR = "linear"
    MOVING_AVERAGE = "moving_average"
    EXPONENTIAL_SMOOTHING = "exponential_smoothing"
    ARIMA_LIKE = "arima_like"
    ENSEMBLE = "ensemble"


class TrendDirection(Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    CYCLICAL = "cyclical"
    VOLATILE = "volatile"


@dataclass
class TrendConfig:
    window_size: int = 24
    anomaly_threshold: float = 2.0
    min_data_points: int = 5
    forecast_periods: int = 5
    seasonal_period: int = 7
    smoothing_alpha: float = 0.3
    change_point_sensitivity: float = 0.6
    correlation_min_overlap: int = 5
    enable_seasonal_decomposition: bool = True
    enable_change_point_detection: bool = True
    enable_correlation_analysis: bool = True
    max_data_points_per_metric: int = 10000
    default_forecast_method: str = "linear"
    confidence_decay_days: int = 30


@dataclass
class DataPoint:
    value: float
    timestamp: datetime
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_anomaly: bool = False


@dataclass
class Trend:
    trend_id: str
    metric_name: str
    direction: str
    strength: float
    start_time: datetime
    end_time: datetime
    data_points: List[float]
    direction_enum: TrendDirection = TrendDirection.STABLE
    confidence_score: float = 0.0
    slope: float = 0.0
    intercept: float = 0.0
    r_squared: float = 0.0
    volatility: float = 0.0
    seasonal_strength: float = 0.0
    forecast_values: List[float] = field(default_factory=list)
    forecast_confidence: float = 0.0
    change_points: List[datetime] = field(default_factory=list)


@dataclass
class Anomaly:
    timestamp: datetime
    value: float
    z_score: float
    expected_value: float
    expected_range: Tuple[float, float]
    metric_name: str
    severity: str = "medium"
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SeasonalComponent:
    period: int
    strength: float
    seasonal_factors: List[float]
    residual_std: float
    trend_component: List[float]
    seasonal_component: List[float]
    residual_component: List[float]


@dataclass
class MetricCorrelation:
    metric_1: str
    metric_2: str
    pearson_r: float
    spearman_r: float
    overlap_count: int
    direction: str
    significance: float


class TrendAnalyzer:
    def __init__(self, config: Optional[TrendConfig] = None):
        self.config = config or TrendConfig()
        self.time_series_data: Dict[str, List[DataPoint]] = defaultdict(list)
        self.detected_trends: Dict[str, Trend] = {}
        self.detected_anomalies: Dict[str, List[Anomaly]] = defaultdict(list)
        self.seasonal_components: Dict[str, SeasonalComponent] = {}
        self.metric_correlations: Dict[str, Dict[str, MetricCorrelation]] = defaultdict(dict)
        self.analysis_count = 0
        self.change_points: Dict[str, List[datetime]] = defaultdict(list)
        self.forecast_accuracy: Dict[str, List[float]] = defaultdict(list)
        self._alerts: Dict[str, Dict] = {}
        self._custom_metrics: Dict[str, Dict] = {}
        logger.info(f"TrendAnalyzer initialized (window_size={self.config.window_size})")

    def add_data_point(self, metric_name: str, value: float, timestamp: Optional[datetime] = None,
                       weight: float = 1.0, metadata: Optional[Dict] = None) -> None:
        if timestamp is None:
            timestamp = datetime.now()
        point = DataPoint(
            value=value,
            timestamp=timestamp,
            weight=weight,
            metadata=metadata or {}
        )
        self.time_series_data[metric_name].append(point)
        cutoff = timestamp - timedelta(hours=self.config.window_size)
        self.time_series_data[metric_name] = [
            d for d in self.time_series_data[metric_name]
            if d['timestamp'] > cutoff
        ] if False else self.time_series_data[metric_name]
        data = self.time_series_data[metric_name]
        cutoff_dt = timestamp - timedelta(hours=self.config.window_size)
        filtered = [d for d in data if d.timestamp > cutoff_dt]
        filtered.sort(key=lambda d: d.timestamp)
        if len(filtered) > self.config.max_data_points_per_metric:
            filtered = filtered[-self.config.max_data_points_per_metric:]
        self.time_series_data[metric_name] = filtered
        logger.debug(f"Added data point for {metric_name}: {value}")

    def add_data_points_batch(self, metric_name: str, values: List[float],
                               timestamps: Optional[List[datetime]] = None) -> int:
        if timestamps is None:
            timestamps = [datetime.now() for _ in values]
        count = 0
        for value, ts in zip(values, timestamps):
            self.add_data_point(metric_name, value, ts)
            count += 1
        logger.info(f"Added batch of {count} data points for {metric_name}")
        return count

    def analyze_trends(self, metric_name: Optional[str] = None) -> List[Trend]:
        trends = []
        metrics_to_analyze = [metric_name] if metric_name else list(self.time_series_data.keys())
        for metric in metrics_to_analyze:
            if not metric or metric not in self.time_series_data:
                continue
            data = self.time_series_data[metric]
            if len(data) < self.config.min_data_points:
                continue
            values = [d.value for d in data]
            timestamps = [d.timestamp for d in data]
            trend_direction = self._calculate_trend_direction(values)
            trend_strength = self._calculate_trend_strength(values)
            slope, intercept = self._linear_regression(values)
            r_squared = self._calculate_r_squared(values, slope, intercept)
            volatility = self._calculate_volatility(values)
            seasonal_strength = 0.0
            if self.config.enable_seasonal_decomposition and len(values) >= self.config.seasonal_period * 2:
                seasonal = self._decompose_seasonal(values)
                seasonal_strength = seasonal.strength
                self.seasonal_components[metric] = seasonal
            forecast_values = self.forecast(metric, self.config.forecast_periods)
            forecast_conf = self._calculate_forecast_confidence(values, forecast_values)
            direction_enum = self._classify_trend_direction(values, trend_direction, volatility, seasonal_strength)
            change_pts = []
            if self.config.enable_change_point_detection and len(values) >= 10:
                change_pts = self._detect_change_points(values, timestamps)
                if change_pts:
                    self.change_points[metric].extend(change_pts)
            if self.config.enable_seasonal_decomposition and self.config.enable_change_point_detection:
                pass
            confidence_score = self._calculate_trend_confidence(trend_strength, r_squared, volatility,
                                                                  seasonal_strength, len(data))
            trend = Trend(
                trend_id=f"{metric}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.analysis_count}",
                metric_name=metric,
                direction=trend_direction,
                strength=trend_strength,
                start_time=min(timestamps),
                end_time=max(timestamps),
                data_points=values[-50:],
                direction_enum=direction_enum,
                confidence_score=confidence_score,
                slope=slope,
                intercept=intercept,
                r_squared=r_squared,
                volatility=volatility,
                seasonal_strength=seasonal_strength,
                forecast_values=forecast_values,
                forecast_confidence=forecast_conf,
                change_points=change_pts
            )
            trends.append(trend)
            self.detected_trends[trend.trend_id] = trend
        self.analysis_count += 1
        if self.config.enable_correlation_analysis and len(self.time_series_data) >= 2:
            self._analyze_metric_correlations()
        logger.info(f"Analysis #{self.analysis_count}: Found {len(trends)} trends across {len(metrics_to_analyze)} metrics")
        return trends

    def _calculate_trend_direction(self, values: List[float]) -> str:
        if len(values) < 2:
            return "stable"
        first_half = values[:len(values)//2]
        second_half = values[len(values)//2:]
        first_avg = statistics.mean(first_half) if first_half else 0
        second_avg = statistics.mean(second_half) if second_half else 0
        diff = second_avg - first_avg
        threshold = abs(first_avg) * 0.05 if first_avg != 0 else 0.1
        if diff > threshold:
            return "increasing"
        elif diff < -threshold:
            return "decreasing"
        else:
            return "stable"

    def _calculate_trend_strength(self, values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        try:
            std_dev = statistics.stdev(values)
            mean_val = statistics.mean(values)
            if mean_val == 0:
                return 0.0
            coefficient_of_variation = std_dev / abs(mean_val)
            strength = min(1.0, max(0.0, 1.0 - coefficient_of_variation))
            return strength
        except statistics.StatisticsError:
            return 0.0

    def _linear_regression(self, values: List[float]) -> Tuple[float, float]:
        n = len(values)
        if n < 2:
            return 0.0, sum(values) / n if n > 0 else 0.0
        x = list(range(n))
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(values)
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, values))
        denominator = sum((xi - mean_x) ** 2 for xi in x)
        slope = numerator / denominator if denominator != 0 else 0.0
        intercept = mean_y - slope * mean_x
        return slope, intercept

    def _calculate_r_squared(self, values: List[float], slope: float, intercept: float) -> float:
        n = len(values)
        if n < 2:
            return 0.0
        mean_y = statistics.mean(values)
        x = list(range(n))
        ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, values))
        ss_tot = sum((yi - mean_y) ** 2 for yi in values)
        if ss_tot == 0:
            return 0.0
        return 1.0 - (ss_res / ss_tot)

    def _calculate_volatility(self, values: List[float]) -> float:
        if len(values) < 3:
            return 0.0
        try:
            returns = [abs(values[i] - values[i-1]) / max(abs(values[i-1]), 0.001) for i in range(1, len(values))]
            return statistics.stdev(returns) if len(returns) > 1 else 0.0
        except (statistics.StatisticsError, ZeroDivisionError):
            return 0.0

    def _classify_trend_direction(self, values: List[float], direction: str,
                                    volatility: float, seasonal_strength: float) -> TrendDirection:
        if seasonal_strength > 0.5:
            return TrendDirection.CYCLICAL
        if volatility > 0.5:
            return TrendDirection.VOLATILE
        if direction == "increasing":
            return TrendDirection.INCREASING
        elif direction == "decreasing":
            return TrendDirection.DECREASING
        return TrendDirection.STABLE

    def _calculate_trend_confidence(self, strength: float, r_squared: float,
                                      volatility: float, seasonal_strength: float,
                                      data_points: int) -> float:
        score = strength * 0.3 + r_squared * 0.3 + (1.0 - volatility) * 0.2
        data_point_factor = min(1.0, data_points / 50)
        score += data_point_factor * 0.1
        if seasonal_strength > 0.7:
            score -= 0.1
        return max(0.0, min(1.0, score))

    def _calculate_forecast_confidence(self, values: List[float], forecast: List[float]) -> float:
        if len(values) < 5 or not forecast:
            return 0.0
        try:
            recent_values = values[-min(5, len(values)):]
            recent_mean = statistics.mean(recent_values)
            recent_std = statistics.stdev(recent_values) if len(recent_values) > 1 else 0
            if recent_std == 0:
                return 0.8
            forecast_mean = statistics.mean(forecast)
            deviation = abs(forecast_mean - recent_mean) / recent_std
            confidence = max(0.0, 1.0 - deviation * 0.2)
            return min(1.0, confidence)
        except statistics.StatisticsError:
            return 0.5

    def detect_anomalies(self, metric_name: str, threshold: Optional[float] = None,
                         use_mad: bool = False) -> List[Anomaly]:
        if threshold is None:
            threshold = self.config.anomaly_threshold
        if metric_name not in self.time_series_data:
            return []
        data = self.time_series_data[metric_name]
        if len(data) < 5:
            return []
        values = [d.value for d in data]
        if use_mad:
            median = statistics.median(values)
            mad = statistics.median([abs(v - median) for v in values])
            mad_normalizer = 1.4826
            anomalies = []
            for point in data:
                if mad > 0:
                    modified_z = 0.6745 * (point.value - median) / (mad * mad_normalizer) if mad > 0 else 0
                    if abs(modified_z) > threshold:
                        anomalies.append(Anomaly(
                            timestamp=point.timestamp,
                            value=point.value,
                            z_score=abs(modified_z),
                            expected_value=median,
                            expected_range=(median - threshold * mad * mad_normalizer,
                                            median + threshold * mad * mad_normalizer),
                            metric_name=metric_name,
                            severity=self._classify_anomaly_severity(abs(modified_z), threshold),
                            context={'method': 'modified_z_score', 'mad': mad, 'median': median}
                        ))
        else:
            mean = statistics.mean(values)
            std_dev = statistics.stdev(values)
            anomalies = []
            for point in data:
                z_score = abs(point.value - mean) / std_dev if std_dev > 0 else 0
                if z_score > threshold:
                    anomalies.append(Anomaly(
                        timestamp=point.timestamp,
                        value=point.value,
                        z_score=z_score,
                        expected_value=mean,
                        expected_range=(mean - threshold * std_dev, mean + threshold * std_dev),
                        metric_name=metric_name,
                        severity=self._classify_anomaly_severity(z_score, threshold),
                        context={'method': 'z_score', 'mean': mean, 'std_dev': std_dev}
                    ))
        for anomaly in anomalies:
            self.detected_anomalies[metric_name].append(anomaly)
            for dp in data:
                if dp.timestamp == anomaly.timestamp:
                    dp.is_anomaly = True
        logger.info(f"Detected {len(anomalies)} anomalies in {metric_name}")
        return anomalies

    def _classify_anomaly_severity(self, z_score: float, threshold: float) -> str:
        ratio = z_score / threshold
        if ratio >= 3.0:
            return "critical"
        elif ratio >= 2.0:
            return "high"
        elif ratio >= 1.5:
            return "medium"
        return "low"

    def forecast(self, metric_name: str, periods: Optional[int] = None,
                 method: Optional[ForecastMethod] = None) -> List[float]:
        if periods is None:
            periods = self.config.forecast_periods
        if method is None:
            method = ForecastMethod(self.config.default_forecast_method)
        if metric_name not in self.time_series_data:
            return []
        data = self.time_series_data[metric_name]
        if len(data) < 3:
            return []
        values = [d.value for d in data]
        if method == ForecastMethod.LINEAR:
            return self._forecast_linear(values, periods)
        elif method == ForecastMethod.MOVING_AVERAGE:
            return self._forecast_moving_average(values, periods)
        elif method == ForecastMethod.EXPONENTIAL_SMOOTHING:
            return self._forecast_exponential_smoothing(values, periods)
        elif method == ForecastMethod.ARIMA_LIKE:
            return self._forecast_arima_like(values, periods)
        elif method == ForecastMethod.ENSEMBLE:
            return self._forecast_ensemble(values, periods)
        return self._forecast_linear(values, periods)

    def _forecast_linear(self, values: List[float], periods: int) -> List[float]:
        if len(values) < 2:
            return [statistics.mean(values)] * periods if values else [0.0] * periods
        slope, intercept = self._linear_regression(values)
        return [slope * (len(values) + i) + intercept for i in range(periods)]

    def _forecast_moving_average(self, values: List[float], periods: int,
                                   window: Optional[int] = None) -> List[float]:
        if window is None:
            window = min(5, len(values) // 2) if len(values) >= 4 else max(1, len(values))
        recent = values[-window:] if len(values) >= window else values
        ma = statistics.mean(recent)
        return [ma] * periods

    def _forecast_exponential_smoothing(self, values: List[float], periods: int,
                                          alpha: Optional[float] = None) -> List[float]:
        if alpha is None:
            alpha = self.config.smoothing_alpha
        if not values:
            return [0.0] * periods
        smoothed = values[0]
        for v in values[1:]:
            smoothed = alpha * v + (1 - alpha) * smoothed
        return [smoothed] * periods

    def _forecast_arima_like(self, values: List[float], periods: int) -> List[float]:
        if len(values) < 6:
            return self._forecast_moving_average(values, periods, max(1, len(values)//2))
        diff_1 = [values[i] - values[i-1] for i in range(1, len(values))]
        if not diff_1:
            return [values[-1]] * periods
        ma_term = statistics.mean(diff_1[-3:]) if len(diff_1) >= 3 else statistics.mean(diff_1)
        ar_term = diff_1[-1] if diff_1 else 0
        forecast_diff = 0.6 * ar_term + 0.4 * ma_term
        forecast = [values[-1] + forecast_diff]
        for i in range(1, periods):
            forecast.append(forecast[-1] + forecast_diff * 0.9)
        return forecast

    def _forecast_ensemble(self, values: List[float], periods: int) -> List[float]:
        linear = self._forecast_linear(values, periods)
        ma = self._forecast_moving_average(values, periods)
        es = self._forecast_exponential_smoothing(values, periods)
        arima = self._forecast_arima_like(values, periods)
        ensemble = []
        for i in range(periods):
            vals = [linear[i] if i < len(linear) else 0,
                    ma[i] if i < len(ma) else 0,
                    es[i] if i < len(es) else 0,
                    arima[i] if i < len(arima) else 0]
            ensemble.append(statistics.mean(vals))
        return ensemble

    def _decompose_seasonal(self, values: List[float], period: Optional[int] = None) -> SeasonalComponent:
        if period is None:
            period = self.config.seasonal_period
        n = len(values)
        if n < period * 2:
            return SeasonalComponent(
                period=period, strength=0.0, seasonal_factors=[],
                residual_std=0.0, trend_component=values,
                seasonal_component=[0.0] * n, residual_component=[0.0] * n
            )
        trend_ma = []
        half = period // 2
        for i in range(n):
            start = max(0, i - half)
            end = min(n, i + half + 1)
            trend_ma.append(statistics.mean(values[start:end]))
        if len(trend_ma) != n:
            while len(trend_ma) < n:
                trend_ma.append(trend_ma[-1] if trend_ma else 0)
        detrended = [values[i] - trend_ma[i] for i in range(n)]
        seasonal_factors = []
        for i in range(period):
            indices = list(range(i, n, period))
            if indices:
                avg = statistics.mean([detrended[j] for j in indices])
                seasonal_factors.append(avg)
            else:
                seasonal_factors.append(0.0)
        factor_mean = statistics.mean(seasonal_factors)
        seasonal_factors = [f - factor_mean for f in seasonal_factors]
        seasonal_comp = [seasonal_factors[i % period] for i in range(n)]
        residual_comp = [detrended[i] - seasonal_comp[i] for i in range(n)]
        try:
            residual_std = statistics.stdev(residual_comp)
        except statistics.StatisticsError:
            residual_std = 0.0
        seasonal_var = statistics.variance(seasonal_comp) if len(seasonal_comp) > 1 else 0
        total_var = statistics.variance(values) if len(values) > 1 else 0
        strength = min(1.0, seasonal_var / total_var) if total_var > 0 else 0.0
        return SeasonalComponent(
            period=period, strength=strength, seasonal_factors=seasonal_factors,
            residual_std=residual_std, trend_component=trend_ma,
            seasonal_component=seasonal_comp, residual_component=residual_comp
        )

    def _detect_change_points(self, values: List[float], timestamps: List[datetime]) -> List[datetime]:
        if len(values) < 10:
            return []
        change_points = []
        min_segment = max(3, len(values) // 10)
        sensitivity = self.config.change_point_sensitivity
        cumulative_means = []
        cum_sum = 0.0
        for i, v in enumerate(values):
            cum_sum += v
            cumulative_means.append(cum_sum / (i + 1))
        for i in range(min_segment, len(values) - min_segment):
            left_mean = statistics.mean(values[i - min_segment:i])
            right_mean = statistics.mean(values[i:i + min_segment])
            diff = abs(right_mean - left_mean)
            overall_std = statistics.stdev(values) if len(values) > 1 else 0
            if overall_std > 0:
                normalized_diff = diff / overall_std
                if normalized_diff > sensitivity:
                    change_points.append(timestamps[i])
        self.change_points[None] = change_points
        merged = []
        if change_points:
            merged = [change_points[0]]
            for cp in change_points[1:]:
                if (cp - merged[-1]).total_seconds() > 3600:
                    merged.append(cp)
        return merged

    def _analyze_metric_correlations(self) -> None:
        metrics = list(self.time_series_data.keys())
        if len(metrics) < 2:
            return
        for m1, m2 in combinations(metrics, 2):
            if m2 in self.metric_correlations and m1 in self.metric_correlations[m2]:
                continue
            points1 = self.time_series_data[m1]
            points2 = self.time_series_data[m2]
            paired = self._pair_time_series(points1, points2)
            if len(paired) < self.config.correlation_min_overlap:
                continue
            vals1, vals2 = zip(*paired)
            p_r = self._pearson_correlation(list(vals1), list(vals2))
            s_r = self._spearman_correlation(list(vals1), list(vals2))
            p_val = self._correlation_significance(p_r, len(vals1))
            direction = "positive" if p_r > 0 else "negative"
            corr = MetricCorrelation(
                metric_1=m1, metric_2=m2,
                pearson_r=p_r, spearman_r=s_r,
                overlap_count=len(paired),
                direction=direction,
                significance=p_val
            )
            self.metric_correlations[m1][m2] = corr
            self.metric_correlations[m2][m1] = corr

    def _pair_time_series(self, points1: List[DataPoint], points2: List[DataPoint],
                            max_delta_seconds: int = 3600) -> List[Tuple[float, float]]:
        paired = []
        for p1 in points1:
            closest = min(points2, key=lambda p: abs((p.timestamp - p1.timestamp).total_seconds()))
            delta = abs((closest.timestamp - p1.timestamp).total_seconds())
            if delta <= max_delta_seconds:
                paired.append((p1.value, closest.value))
        return paired

    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        n = len(x)
        if n < 3:
            return 0.0
        try:
            mean_x = statistics.mean(x)
            mean_y = statistics.mean(y)
            std_x = statistics.stdev(x)
            std_y = statistics.stdev(y)
            if std_x == 0 or std_y == 0:
                return 0.0
            cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / (n - 1)
            return max(-1.0, min(1.0, cov / (std_x * std_y)))
        except statistics.StatisticsError:
            return 0.0

    def _spearman_correlation(self, x: List[float], y: List[float]) -> float:
        from scipy.stats import spearmanr
        try:
            r, _ = spearmanr(x, y)
            return r if not math.isnan(r) else 0.0
        except ImportError:
            return self._pearson_correlation(x, y)

    def _correlation_significance(self, r: float, n: int) -> float:
        if n < 3 or abs(r) >= 1.0:
            return 1.0
        try:
            t_stat = r * math.sqrt((n - 2) / (1 - r * r))
            from scipy.stats import t as t_dist
            p_value = 2 * (1 - t_dist.cdf(abs(t_stat), df=n - 2))
            return p_value
        except ImportError:
            return 1.0 / (1 + abs(r) * n)

    def get_trend_summary(self) -> Dict:
        direction_counts = Counter(t.direction for t in self.detected_trends.values())
        strength_buckets = {
            'strong': len([t for t in self.detected_trends.values() if t.strength > 0.8]),
            'moderate': len([t for t in self.detected_trends.values() if 0.5 < t.strength <= 0.8]),
            'weak': len([t for t in self.detected_trends.values() if t.strength <= 0.5])
        }
        return {
            'total_trends': len(self.detected_trends),
            'direction_summary': dict(direction_counts),
            'strength_summary': strength_buckets,
            'metrics_analyzed': len(self.time_series_data),
            'analysis_count': self.analysis_count,
            'high_strength_trends': len([t for t in self.detected_trends.values() if t.strength > 0.8]),
            'high_confidence_trends': len([t for t in self.detected_trends.values() if t.confidence_score > 0.8]),
            'total_anomalies': sum(len(a) for a in self.detected_anomalies.values()),
            'total_change_points': sum(len(cp) for cp in self.change_points.values()),
            'total_correlations': sum(len(c) for c in self.metric_correlations.values()) // 2,
            'seasonal_metrics': len(self.seasonal_components)
        }

    def get_detailed_trend_report(self, metric_name: Optional[str] = None) -> Dict:
        summary = self.get_trend_summary()
        trend_details = []
        for tid, trend in self.detected_trends.items():
            if metric_name and trend.metric_name != metric_name:
                continue
            trend_details.append({
                'trend_id': tid,
                'metric': trend.metric_name,
                'direction': trend.direction,
                'direction_enum': trend.direction_enum.value,
                'strength': trend.strength,
                'confidence': trend.confidence_score,
                'slope': trend.slope,
                'r_squared': trend.r_squared,
                'volatility': trend.volatility,
                'seasonal_strength': trend.seasonal_strength,
                'data_points': len(trend.data_points),
                'forecast': trend.forecast_values,
                'forecast_confidence': trend.forecast_confidence,
                'change_points': len(trend.change_points),
                'period': f"{trend.start_time.isoformat()} to {trend.end_time.isoformat()}"
            })
        anomaly_counts = {m: len(a) for m, a in self.detected_anomalies.items()}
        return {
            'summary': summary,
            'trends': trend_details,
            'anomaly_counts': anomaly_counts,
            'correlations': [
                {'metric_1': c.metric_1, 'metric_2': c.metric_2,
                 'pearson_r': c.pearson_r, 'spearman_r': c.spearman_r,
                 'direction': c.direction, 'significance': c.significance}
                for corrs in self.metric_correlations.values()
                for c in corrs.values()
                if c.metric_1 < c.metric_2
            ][:50]
        }

    def get_correlated_metrics(self, metric_name: str, min_r: float = 0.5) -> List[MetricCorrelation]:
        if metric_name not in self.metric_correlations:
            return []
        return sorted(
            [c for c in self.metric_correlations[metric_name].values() if abs(c.pearson_r) >= min_r],
            key=lambda c: abs(c.pearson_r),
            reverse=True
        )

    def export_trend_data(self, metric_name: Optional[str] = None) -> Dict:
        data = {
            'export_version': '1.0',
            'exported_at': datetime.now().isoformat(),
            'config': asdict(self.config),
            'trends': {},
            'anomalies': {},
            'seasonal': {}
        }
        for tid, trend in self.detected_trends.items():
            if metric_name and trend.metric_name != metric_name:
                continue
            data['trends'][tid] = {
                'metric_name': trend.metric_name,
                'direction': trend.direction,
                'strength': trend.strength,
                'confidence_score': trend.confidence_score,
                'slope': trend.slope,
                'r_squared': trend.r_squared,
                'seasonal_strength': trend.seasonal_strength,
                'forecast_values': trend.forecast_values,
                'data_points': trend.data_points[:100] if len(trend.data_points) > 100 else trend.data_points
            }
        for m, anoms in self.detected_anomalies.items():
            if metric_name and m != metric_name:
                continue
            data['anomalies'][m] = [
                {'timestamp': a.timestamp.isoformat(), 'value': a.value,
                 'z_score': a.z_score, 'severity': a.severity}
                for a in anoms[-100:]
            ]
        for m, seasonal in self.seasonal_components.items():
            if metric_name and m != metric_name:
                continue
            data['seasonal'][m] = {
                'period': seasonal.period,
                'strength': seasonal.strength,
                'seasonal_factors': seasonal.seasonal_factors[:20]
            }
        return data

    def reset_metric(self, metric_name: str) -> None:
        if metric_name in self.time_series_data:
            del self.time_series_data[metric_name]
        trends_to_delete = [tid for tid, t in self.detected_trends.items() if t.metric_name == metric_name]
        for tid in trends_to_delete:
            del self.detected_trends[tid]
        if metric_name in self.detected_anomalies:
            del self.detected_anomalies[metric_name]
        if metric_name in self.seasonal_components:
            del self.seasonal_components[metric_name]
        if metric_name in self.metric_correlations:
            del self.metric_correlations[metric_name]
        for other_metric in list(self.metric_correlations.keys()):
            if metric_name in self.metric_correlations[other_metric]:
                del self.metric_correlations[other_metric][metric_name]
        logger.info(f"Reset all data for metric: {metric_name}")

    def reset_all(self) -> None:
        self.time_series_data.clear()
        self.detected_trends.clear()
        self.detected_anomalies.clear()
        self.seasonal_components.clear()
        self.metric_correlations.clear()
        self.change_points.clear()
        self.forecast_accuracy.clear()
        self._alerts.clear()
        self._custom_metrics.clear()
        self.analysis_count = 0
        logger.info("TrendAnalyzer fully reset")

    def get_statistics(self) -> Dict:
        return self.get_trend_summary()

    def forecast_multi_horizon(self, metric_name: str,
                                horizons: Optional[List[int]] = None) -> Dict:
        if horizons is None:
            horizons = [1, 3, 5, 10, 20]
        if metric_name not in self.time_series_data:
            return {'metric': metric_name, 'error': 'metric_not_found'}
        data = self.time_series_data[metric_name]
        if len(data) < 3:
            return {'metric': metric_name, 'error': 'insufficient_data'}
        values = [d.value for d in data]
        results = {}
        for periods in horizons:
            if periods > len(values) * 2:
                continue
            linear_fc = self._forecast_linear(values, periods)
            ma_fc = self._forecast_moving_average(values, periods)
            es_fc = self._forecast_exponential_smoothing(values, periods)
            ensemble = self._forecast_ensemble(values, periods)
            last_value = values[-1]
            results[str(periods)] = {
                'periods': periods,
                'linear': [round(v, 4) for v in linear_fc],
                'moving_average': [round(v, 4) for v in ma_fc],
                'exponential_smoothing': [round(v, 4) for v in es_fc],
                'ensemble': [round(v, 4) for v in ensemble],
                'last_actual': round(last_value, 4),
                'linear_change': round((linear_fc[-1] - last_value) / max(abs(last_value), 0.001), 4),
                'ensemble_change': round((ensemble[-1] - last_value) / max(abs(last_value), 0.001), 4),
                'direction': 'up' if ensemble[-1] > last_value else ('down' if ensemble[-1] < last_value else 'flat'),
            }
        current_trend = self.detected_trends.get(
            f"{metric_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.analysis_count}"
        )
        return {
            'metric': metric_name,
            'data_points': len(values),
            'forecasts': results,
            'volatility': round(self._calculate_volatility(values), 4),
            'current_direction': current_trend.direction if current_trend else 'unknown',
            'generated_at': datetime.now().isoformat(),
        }

    def track_forecast_accuracy(self, metric_name: str, actual_value: float,
                                 forecast_horizon: int = 1) -> Dict:
        if metric_name not in self.time_series_data:
            return {'error': 'metric_not_found'}
        data = self.time_series_data[metric_name]
        if len(data) < 3:
            return {'error': 'insufficient_data'}
        values = [d.value for d in data]
        forecast_values = self.forecast(metric_name, forecast_horizon)
        if not forecast_values:
            return {'error': 'forecast_failed'}
        predicted = forecast_values[0]
        error = actual_value - predicted
        abs_error = abs(error)
        pct_error = abs_error / max(abs(actual_value), 0.001) * 100
        record = {
            'timestamp': datetime.now().isoformat(),
            'metric': metric_name,
            'actual': actual_value,
            'predicted': round(predicted, 4),
            'error': round(error, 4),
            'abs_error': round(abs_error, 4),
            'pct_error': round(pct_error, 2),
            'horizon': forecast_horizon,
            'data_points': len(values),
        }
        self.forecast_accuracy[metric_name].append(abs_error)
        logger.info(f"Forecast accuracy for {metric_name}: error={abs_error:.4f} ({pct_error:.1f}%)")
        return record

    def get_forecast_accuracy_summary(self, metric_name: Optional[str] = None) -> Dict:
        if metric_name:
            errors = self.forecast_accuracy.get(metric_name, [])
        else:
            errors = [e for errs in self.forecast_accuracy.values() for e in errs]
        if not errors:
            return {'error': 'no_accuracy_data', 'count': 0}
        mae = statistics.mean(errors)
        mse = statistics.mean(e ** 2 for e in errors)
        rmse = math.sqrt(mse)
        return {
            'metric': metric_name or 'all_metrics',
            'count': len(errors),
            'mae': round(mae, 4),
            'mse': round(mse, 4),
            'rmse': round(rmse, 4),
            'max_error': round(max(errors), 4),
            'min_error': round(min(errors), 4),
            'std_error': round(statistics.stdev(errors), 4) if len(errors) > 1 else 0.0,
            'recent_errors': [round(e, 4) for e in errors[-10:]],
        }

    def smooth_data(self, metric_name: str, method: str = "moving_average",
                     window: Optional[int] = None) -> List[float]:
        if metric_name not in self.time_series_data:
            return []
        data = self.time_series_data[metric_name]
        if len(data) < 3:
            return [d.value for d in data]
        values = [d.value for d in data]
        if window is None:
            window = max(3, len(values) // 10)
        if method == "moving_average":
            smoothed = []
            for i in range(len(values)):
                start = max(0, i - window // 2)
                end = min(len(values), i + window // 2 + 1)
                smoothed.append(statistics.mean(values[start:end]))
            return smoothed
        elif method == "median_filter":
            smoothed = []
            for i in range(len(values)):
                start = max(0, i - window // 2)
                end = min(len(values), i + window // 2 + 1)
                smoothed.append(statistics.median(values[start:end]))
            return smoothed
        elif method == "exponential":
            alpha = 2.0 / (window + 1)
            smoothed = [values[0]]
            for v in values[1:]:
                smoothed.append(alpha * v + (1 - alpha) * smoothed[-1])
            return smoothed
        elif method == "loess":
            return self._smooth_loess(values, window)
        return values

    def _smooth_loess(self, values: List[float], window: int) -> List[float]:
        n = len(values)
        smoothed = list(values)
        if n < 3:
            return smoothed
        for i in range(n):
            start = max(0, i - window // 2)
            end = min(n, i + window // 2 + 1)
            segment = values[start:end]
            weights = []
            for j in range(start, end):
                dist = abs(j - i) / max(window // 2, 1)
                weight = (1 - dist ** 3) ** 3 if dist < 1 else 0
                weights.append(weight)
            total_w = sum(weights)
            if total_w > 0:
                smoothed[i] = sum(v * w for v, w in zip(segment, weights)) / total_w
        return smoothed

    def detect_outliers(self, metric_name: str, method: str = "iqr",
                         threshold: float = 1.5) -> List[Dict]:
        if metric_name not in self.time_series_data:
            return []
        data = self.time_series_data[metric_name]
        if len(data) < 5:
            return []
        values = [d.value for d in data]
        outliers = []
        if method == "iqr":
            sorted_vals = sorted(values)
            q1 = sorted_vals[len(sorted_vals) // 4]
            q3 = sorted_vals[3 * len(sorted_vals) // 4]
            iqr = q3 - q1
            lower = q1 - threshold * iqr
            upper = q3 + threshold * iqr
            for point in data:
                if point.value < lower or point.value > upper:
                    outliers.append({
                        'timestamp': point.timestamp.isoformat(),
                        'value': point.value,
                        'lower_bound': lower,
                        'upper_bound': upper,
                        'method': 'iqr',
                        'severity': 'high' if abs(point.value - q2) > 2 * iqr else 'medium',
                    })
        elif method == "z_score":
            mean = statistics.mean(values)
            std = statistics.stdev(values) if len(values) > 1 else 0
            for point in data:
                z = abs(point.value - mean) / std if std > 0 else 0
                if z > threshold:
                    outliers.append({
                        'timestamp': point.timestamp.isoformat(),
                        'value': point.value,
                        'z_score': z,
                        'mean': mean,
                        'std': std,
                        'method': 'z_score',
                        'severity': 'critical' if z > 3 else 'high' if z > 2.5 else 'medium',
                    })
        if 'q2' not in dir():
            pass
        return outliers

    def correct_outliers(self, metric_name: str, method: str = "clip",
                          threshold: float = 1.5) -> int:
        if metric_name not in self.time_series_data:
            return 0
        data = self.time_series_data[metric_name]
        if len(data) < 5:
            return 0
        values = [d.value for d in data]
        sorted_vals = sorted(values)
        q1 = sorted_vals[len(sorted_vals) // 4]
        q3 = sorted_vals[3 * len(sorted_vals) // 4]
        iqr = q3 - q1
        lower = q1 - threshold * iqr
        upper = q3 + threshold * iqr
        corrected = 0
        for i, point in enumerate(data):
            if point.value < lower or point.value > upper:
                if method == "clip":
                    data[i].value = max(lower, min(upper, point.value))
                elif method == "median":
                    data[i].value = statistics.median(values)
                elif method == "mean":
                    data[i].value = statistics.mean(values)
                corrected += 1
        self.time_series_data[metric_name] = data
        if corrected > 0:
            logger.info(f"Corrected {corrected} outliers in {metric_name} using {method}")
        return corrected

    def setup_alert(self, metric_name: str, condition: str = "above",
                     threshold: float = 0.0, cooldown_minutes: int = 60) -> Dict:
        alert_id = f"alert_{metric_name}_{uuid.uuid4().hex[:6]}"
        alert = {
            'alert_id': alert_id,
            'metric': metric_name,
            'condition': condition,
            'threshold': threshold,
            'cooldown_minutes': cooldown_minutes,
            'created_at': datetime.now().isoformat(),
            'last_triggered': None,
            'trigger_count': 0,
            'active': True,
        }
        self._alerts[alert_id] = alert
        logger.info(f"Created alert {alert_id}: {metric_name} {condition} {threshold}")
        return alert

    def remove_alert(self, alert_id: str) -> bool:
        if alert_id in self._alerts:
            del self._alerts[alert_id]
            logger.info(f"Removed alert {alert_id}")
            return True
        return False

    def check_alerts(self, metric_name: Optional[str] = None) -> List[Dict]:
        triggered = []
        now = datetime.now()
        for alert_id, alert in list(self._alerts.items()):
            if not alert['active']:
                continue
            if metric_name and alert['metric'] != metric_name:
                continue
            mn = alert['metric']
            if mn not in self.time_series_data:
                continue
            values = [d.value for d in self.time_series_data[mn]]
            if not values:
                continue
            current = values[-1]
            should_trigger = False
            if alert['condition'] == 'above' and current > alert['threshold']:
                should_trigger = True
            elif alert['condition'] == 'below' and current < alert['threshold']:
                should_trigger = True
            elif alert['condition'] == 'change_pct':
                if len(values) >= 2:
                    pct = (values[-1] - values[-2]) / max(abs(values[-2]), 0.001) * 100
                    should_trigger = abs(pct) > alert['threshold']
            elif alert['condition'] == 'anomaly':
                anoms = self.detect_anomalies(mn, threshold=2.0)
                should_trigger = len(anoms) > 0
            if should_trigger:
                if alert['last_triggered']:
                    elapsed = (now - datetime.fromisoformat(alert['last_triggered'])).total_seconds()
                    if elapsed < alert['cooldown_minutes'] * 60:
                        continue
                alert['last_triggered'] = now.isoformat()
                alert['trigger_count'] += 1
                triggered.append({
                    'alert_id': alert_id,
                    'metric': mn,
                    'condition': alert['condition'],
                    'current_value': current,
                    'threshold': alert['threshold'],
                    'triggered_at': now.isoformat(),
                    'trigger_count': alert['trigger_count'],
                })
        return triggered

    def get_active_alerts(self) -> List[Dict]:
        return [a for a in self._alerts.values() if a['active']]

    def optimize_window(self, metric_name: str) -> Dict:
        if metric_name not in self.time_series_data:
            return {'error': 'metric_not_found'}
        data = self.time_series_data[metric_name]
        if len(data) < 10:
            return {'error': 'insufficient_data', 'data_points': len(data)}
        values = [d.value for d in data]
        results = {}
        for window in [5, 10, 20, 50, 100]:
            if window > len(values):
                continue
            window_data = values[-window:]
            try:
                mean = statistics.mean(window_data)
                std = statistics.stdev(window_data) if len(window_data) > 1 else 0
                cv = std / max(abs(mean), 0.001)
                slope, _ = self._linear_regression(window_data)
                results[window] = {
                    'mean': round(mean, 4),
                    'std': round(std, 4),
                    'cv': round(cv, 4),
                    'slope': round(slope, 6),
                    'data_points': len(window_data),
                }
            except (statistics.StatisticsError, ZeroDivisionError):
                continue
        if not results:
            return {'error': 'all_windows_failed'}
        best_window = min(results, key=lambda w: results[w]['cv'])
        return {
            'metric': metric_name,
            'total_points': len(values),
            'window_analysis': results,
            'recommended_window': best_window,
            'recommended_reason': 'lowest_coefficient_of_variation',
        }

    def get_metric_health(self, metric_name: str) -> Dict:
        if metric_name not in self.time_series_data:
            return {'metric': metric_name, 'health': 'unknown', 'error': 'metric_not_found'}
        data = self.time_series_data[metric_name]
        if len(data) < 5:
            return {'metric': metric_name, 'health': 'insufficient'}
        values = [d.value for d in data]
        try:
            mean = statistics.mean(values)
            std = statistics.stdev(values) if len(values) > 1 else 0
            cv = std / max(abs(mean), 0.001) if mean != 0 else std
        except (statistics.StatisticsError, ZeroDivisionError):
            cv = 1.0
        missing_ratio = sum(1 for d in data if d.weight < 0.1) / max(len(data), 1)
        anomaly_ratio = sum(1 for d in data if d.is_anomaly) / max(len(data), 1)
        trend = self._calculate_trend_direction(values)
        stability = max(0.0, 1.0 - cv)
        completeness = 1.0 - missing_ratio
        cleanliness = 1.0 - anomaly_ratio
        overall = (stability * 0.4 + completeness * 0.3 + cleanliness * 0.3)
        if overall > 0.8:
            health = "good"
        elif overall > 0.5:
            health = "fair"
        else:
            health = "poor"
        return {
            'metric': metric_name,
            'health': health,
            'score': round(overall, 4),
            'stability': round(stability, 4),
            'completeness': round(completeness, 4),
            'cleanliness': round(cleanliness, 4),
            'cv': round(cv, 4),
            'anomaly_ratio': round(anomaly_ratio, 4),
            'missing_ratio': round(missing_ratio, 4),
            'direction': trend,
            'data_points': len(data),
        }

    def bucket_metrics(self, bucket_function: Optional[Callable] = None) -> Dict:
        buckets = defaultdict(list)
        if bucket_function:
            for metric in self.time_series_data:
                bucket = bucket_function(metric)
                buckets[bucket].append(metric)
        else:
            for metric in self.time_series_data:
                parts = metric.split('_')
                bucket = parts[0] if parts else 'other'
                buckets[bucket].append(metric)
        bucket_stats = {}
        for bucket, metrics in buckets.items():
            all_values = []
            for m in metrics:
                all_values.extend(d.value for d in self.time_series_data.get(m, []))
            if all_values:
                bucket_stats[bucket] = {
                    'metrics': len(metrics),
                    'data_points': len(all_values),
                    'mean': round(statistics.mean(all_values), 4),
                    'std': round(statistics.stdev(all_values), 4) if len(all_values) > 1 else 0.0,
                    'min': round(min(all_values), 4),
                    'max': round(max(all_values), 4),
                    'recent_value': round(all_values[-1], 4) if all_values else None,
                }
            else:
                bucket_stats[bucket] = {'metrics': len(metrics), 'data_points': 0}
        return {
            'total_buckets': len(bucket_stats),
            'total_metrics': len(self.time_series_data),
            'buckets': bucket_stats,
        }

    def detect_trend_shifts(self, metric_name: str, window: int = 5) -> List[Dict]:
        if metric_name not in self.time_series_data:
            return []
        data = self.time_series_data[metric_name]
        if len(data) < window * 3:
            return []
        values = [d.value for d in data]
        timestamps = [d.timestamp for d in data]
        shifts = []
        for i in range(window, len(values) - window):
            left = values[i - window:i]
            right = values[i:i + window]
            left_mean = statistics.mean(left)
            right_mean = statistics.mean(right)
            left_std = statistics.stdev(left) if len(left) > 1 else 0
            if left_std > 0:
                effect_size = abs(right_mean - left_mean) / left_std
                if effect_size > 1.5:
                    shifts.append({
                        'index': i,
                        'timestamp': timestamps[i].isoformat(),
                        'left_mean': round(left_mean, 4),
                        'right_mean': round(right_mean, 4),
                        'effect_size': round(effect_size, 4),
                        'direction': 'up' if right_mean > left_mean else 'down',
                        'magnitude': round(abs(right_mean - left_mean), 4),
                    })
        return shifts

    def get_comprehensive_report(self, metric_name: Optional[str] = None,
                                  include_raw: bool = False) -> Dict:
        report = {
            'generated_at': datetime.now().isoformat(),
            'summary': self.get_trend_summary(),
            'forecast_accuracy': self.get_forecast_accuracy_summary(metric_name),
        }
        if metric_name and metric_name in self.time_series_data:
            report['metric_health'] = self.get_metric_health(metric_name)
            report['optimal_window'] = self.optimize_window(metric_name)
            report['trend_shifts'] = self.detect_trend_shifts(metric_name)
            report['multi_horizon_forecast'] = self.forecast_multi_horizon(metric_name)
            data = self.time_series_data[metric_name]
            report['data_quality'] = {
                'total_points': len(data),
                'zero_values': sum(1 for d in data if d.value == 0),
                'negative_values': sum(1 for d in data if d.value < 0),
                'anomaly_count': sum(1 for d in data if d.is_anomaly),
                'date_range': f"{data[0].timestamp.isoformat() if data else 'N/A'} to {data[-1].timestamp.isoformat() if data else 'N/A'}",
            }
        if include_raw:
            report['alerts'] = list(self._alerts.values())
            report['change_points'] = {
                m: [cp.isoformat() for cp in cps]
                for m, cps in self.change_points.items()
            }
        return report
