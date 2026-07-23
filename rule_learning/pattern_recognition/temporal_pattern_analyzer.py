"""
Temporal pattern analysis for rule firings.

Provides time-series analysis, seasonal pattern detection, trend detection
(linear, exponential, polynomial), periodicity detection via FFT/autocorrelation,
change point detection, and forecasting (moving average, exponential smoothing).
"""

import logging
import math
import uuid
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from rules_emerging_pattern.models.rule import Rule

logger = logging.getLogger(__name__)


class TrendModel(str, Enum):
    """Mathematical model types for trend fitting."""

    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    POLYNOMIAL = "polynomial"
    LOGARITHMIC = "logarithmic"
    POWER = "power"


class SeasonalPeriod(str, Enum):
    """Detected seasonal periods in time-series data."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    NO_SEASONALITY = "no_seasonality"


class ChangePointType(str, Enum):
    """Types of detected change points."""

    MEAN_SHIFT = "mean_shift"
    VARIANCE_SHIFT = "variance_shift"
    TREND_CHANGE = "trend_change"
    SEASONALITY_CHANGE = "seasonality_change"


class TemporalConfig:
    """Configuration for TemporalPatternAnalyzer."""

    def __init__(
        self,
        history_window_days: int = 365,
        min_data_points: int = 10,
        seasonal_min_periods: int = 2,
        fft_significance_threshold: float = 0.3,
        autocorrelation_lag_max: int = 100,
        change_point_min_distance: int = 7,
        change_point_threshold: float = 2.0,
        forecast_horizon: int = 30,
        moving_average_window: int = 7,
        exponential_smoothing_alpha: float = 0.3,
        polynomial_degree: int = 2,
        enable_fft_periodicity: bool = True,
        enable_change_point_detection: bool = True,
        enable_forecasting: bool = True,
    ) -> None:
        self.history_window_days = history_window_days
        self.min_data_points = min_data_points
        self.seasonal_min_periods = seasonal_min_periods
        self.fft_significance_threshold = fft_significance_threshold
        self.autocorrelation_lag_max = autocorrelation_lag_max
        self.change_point_min_distance = change_point_min_distance
        self.change_point_threshold = change_point_threshold
        self.forecast_horizon = forecast_horizon
        self.moving_average_window = moving_average_window
        self.exponential_smoothing_alpha = exponential_smoothing_alpha
        self.polynomial_degree = polynomial_degree
        self.enable_fft_periodicity = enable_fft_periodicity
        self.enable_change_point_detection = enable_change_point_detection
        self.enable_forecasting = enable_forecasting

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class TimeSeriesData:
    """Container for time-series data used in analysis."""

    def __init__(
        self,
        timestamps: List[datetime],
        values: List[float],
        label: str = "",
    ) -> None:
        if len(timestamps) != len(values):
            raise ValueError("timestamps and values must have the same length")
        self.timestamps = timestamps
        self.values = values
        self.label = label

    def __len__(self) -> int:
        return len(self.timestamps)

    def sort(self) -> None:
        """Sort data by timestamp in ascending order."""
        paired = sorted(zip(self.timestamps, self.values), key=lambda x: x[0])
        self.timestamps = [p[0] for p in paired]
        self.values = [p[1] for p in paired]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary (limited to first 1000 points)."""
        max_points = 1000
        return {
            "label": self.label,
            "point_count": len(self.timestamps),
            "timestamps": [t.isoformat() for t in self.timestamps[:max_points]],
            "values": self.values[:max_points],
            "date_range": {
                "start": self.timestamps[0].isoformat() if self.timestamps else None,
                "end": self.timestamps[-1].isoformat() if self.timestamps else None,
            },
        }


class TrendResult:
    """Result of trend detection and fitting."""

    def __init__(
        self,
        model: TrendModel,
        coefficients: List[float],
        r_squared: float,
        mse: float,
        direction: str,
        description: str,
    ) -> None:
        self.model = model
        self.coefficients = coefficients
        self.r_squared = r_squared
        self.mse = mse
        self.direction = direction
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "model": self.model.value,
            "coefficients": [round(c, 6) for c in self.coefficients],
            "r_squared": round(self.r_squared, 4),
            "mse": round(self.mse, 4),
            "direction": self.direction,
            "description": self.description,
        }


class PeriodicityResult:
    """Result of periodicity detection."""

    def __init__(
        self,
        has_periodicity: bool,
        dominant_period_days: Optional[float],
        seasonal_period: SeasonalPeriod,
        fft_peaks: List[Dict[str, float]],
        autocorrelation_peaks: List[Dict[str, float]],
        confidence: float,
    ) -> None:
        self.has_periodicity = has_periodicity
        self.dominant_period_days = dominant_period_days
        self.seasonal_period = seasonal_period
        self.fft_peaks = fft_peaks
        self.autocorrelation_peaks = autocorrelation_peaks
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "has_periodicity": self.has_periodicity,
            "dominant_period_days": self.dominant_period_days,
            "seasonal_period": self.seasonal_period.value,
            "fft_peaks": self.fft_peaks[:5],
            "autocorrelation_peaks": self.autocorrelation_peaks[:5],
            "confidence": round(self.confidence, 4),
        }


class ChangePoint:
    """A detected change point in the time series."""

    def __init__(
        self,
        index: int,
        timestamp: datetime,
        change_type: ChangePointType,
        magnitude: float,
        confidence: float,
        before_stats: Dict[str, float],
        after_stats: Dict[str, float],
    ) -> None:
        self.index = index
        self.timestamp = timestamp
        self.change_type = change_type
        self.magnitude = magnitude
        self.confidence = confidence
        self.before_stats = before_stats
        self.after_stats = after_stats

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "index": self.index,
            "timestamp": self.timestamp.isoformat(),
            "change_type": self.change_type.value,
            "magnitude": round(self.magnitude, 4),
            "confidence": round(self.confidence, 4),
            "before_stats": {k: round(v, 4) for k, v in self.before_stats.items()},
            "after_stats": {k: round(v, 4) for k, v in self.after_stats.items()},
        }


class ForecastResult:
    """Result of time-series forecasting."""

    def __init__(
        self,
        method: str,
        forecast_values: List[float],
        confidence_intervals: List[Dict[str, float]],
        mse: float,
        horizon: int,
    ) -> None:
        self.method = method
        self.forecast_values = forecast_values
        self.confidence_intervals = confidence_intervals
        self.mse = mse
        self.horizon = horizon

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "method": self.method,
            "horizon": self.horizon,
            "forecast_values": [round(v, 4) for v in self.forecast_values],
            "confidence_intervals": [
                {
                    "lower": round(ci.get("lower", 0), 4),
                    "upper": round(ci.get("upper", 0), 4),
                }
                for ci in self.confidence_intervals
            ],
            "mse": round(self.mse, 4),
        }


class TemporalPatternAnalyzer:
    """
    Analyzes temporal patterns in rule firing time-series data.

    Capabilities:
    - Time-series aggregation from rule firing records
    - Seasonal pattern detection (hourly, daily, weekly, monthly cycles)
    - Trend detection (linear, exponential, polynomial, logarithmic, power)
    - Periodicity detection using FFT and autocorrelation
    - Change point detection (mean shift, variance shift, trend change)
    - Forecasting (simple moving average, exponential smoothing)
    - Visualization-ready statistics for external charting
    """

    _DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def __init__(self, config: Optional[TemporalConfig] = None) -> None:
        self._config = config or TemporalConfig()
        self._rule_series: Dict[str, TimeSeriesData] = {}
        self._trend_results: Dict[str, TrendResult] = {}
        self._periodicity_results: Dict[str, PeriodicityResult] = {}
        self._change_points: Dict[str, List[ChangePoint]] = {}
        self._forecasts: Dict[str, ForecastResult] = {}
        logger.info("TemporalPatternAnalyzer initialized with config: %s", self._config.to_dict())

    # ------------------------------------------------------------------
    # Data Ingestion
    # ------------------------------------------------------------------

    def ingest_firings(
        self,
        rule_id: str,
        timestamps: List[datetime],
        values: Optional[List[float]] = None,
    ) -> None:
        """
        Ingest rule firing data as a time series.

        Args:
            rule_id: ID of the rule.
            timestamps: List of firing timestamps (or time buckets).
            values: Optional numeric values (e.g., counts, scores).
                    Defaults to 1.0 for each timestamp.
        """
        vals = values if values is not None else [1.0] * len(timestamps)
        series = TimeSeriesData(timestamps, vals, label=rule_id)
        series.sort()
        self._rule_series[rule_id] = series
        logger.debug("Ingested %d data points for rule %s", len(series), rule_id)

    def ingest_from_records(
        self,
        rule_id: str,
        records: List[Dict[str, Any]],
        timestamp_key: str = "timestamp",
        value_key: Optional[str] = None,
    ) -> None:
        """
        Ingest rule firing data from a list of record dictionaries.

        Args:
            rule_id: ID of the rule.
            records: List of record dicts containing timestamps.
            timestamp_key: Dict key for timestamp values.
            value_key: Optional dict key for numeric values.
        """
        timestamps: List[datetime] = []
        values: List[float] = []
        for record in records:
            ts = record.get(timestamp_key)
            if ts is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            timestamps.append(ts)
            if value_key:
                v = record.get(value_key, 1.0)
                values.append(float(v) if v is not None else 1.0)
            else:
                values.append(1.0)
        self.ingest_firings(rule_id, timestamps, values)

    def ingest_daily_counts(
        self,
        rule_id: str,
        daily_counts: Dict[str, int],
    ) -> None:
        """
        Ingest pre-aggregated daily count data.

        Args:
            rule_id: ID of the rule.
            daily_counts: Dict mapping date strings (YYYY-MM-DD) to counts.
        """
        timestamps: List[datetime] = []
        values: List[float] = []
        for date_str, count in sorted(daily_counts.items()):
            timestamps.append(datetime.fromisoformat(date_str))
            values.append(float(count))
        self.ingest_firings(rule_id, timestamps, values)

    def aggregate_firings_by_day(
        self,
        rule_id: str,
        timestamps: List[datetime],
    ) -> TimeSeriesData:
        """
        Aggregate raw firing timestamps into daily counts.

        Returns:
            TimeSeriesData with daily aggregate values.
        """
        daily: Dict[str, int] = defaultdict(int)
        for ts in timestamps:
            daily[ts.strftime("%Y-%m-%d")] += 1
        return self._from_daily_dict(rule_id, dict(daily))

    def aggregate_firings_by_hour(
        self,
        rule_id: str,
        timestamps: List[datetime],
    ) -> TimeSeriesData:
        """
        Aggregate raw firing timestamps into hourly counts.
        """
        hourly: Dict[str, int] = defaultdict(int)
        for ts in timestamps:
            hourly[ts.strftime("%Y-%m-%dT%H:00:00")] += 1
        sorted_keys = sorted(hourly.keys())
        return TimeSeriesData(
            timestamps=[datetime.fromisoformat(k) for k in sorted_keys],
            values=[float(hourly[k]) for k in sorted_keys],
            label=rule_id,
        )

    def _from_daily_dict(self, rule_id: str, daily: Dict[str, int]) -> TimeSeriesData:
        sorted_days = sorted(daily.keys())
        return TimeSeriesData(
            timestamps=[datetime.fromisoformat(d) for d in sorted_days],
            values=[float(daily[d]) for d in sorted_days],
            label=rule_id,
        )

    def get_series(self, rule_id: str) -> Optional[TimeSeriesData]:
        """Get the time-series data for a rule."""
        return self._rule_series.get(rule_id)

    # ------------------------------------------------------------------
    # Trend Detection
    # ------------------------------------------------------------------

    def detect_trend(
        self,
        rule_id: str,
        models: Optional[List[TrendModel]] = None,
    ) -> TrendResult:
        """
        Detect and fit trend models to rule firing data.

        Tries each specified model and returns the best fit based on
        R-squared. Models: linear, exponential, polynomial, logarithmic, power.

        Args:
            rule_id: ID of the rule.
            models: List of TrendModel values to try (defaults to all).

        Returns:
            TrendResult with the best-fitting model.
        """
        series = self._rule_series.get(rule_id)
        if series is None or len(series) < self._config.min_data_points:
            return TrendResult(
                model=TrendModel.LINEAR,
                coefficients=[0.0, 0.0],
                r_squared=0.0,
                mse=0.0,
                direction="unknown",
                description="Insufficient data for trend detection",
            )

        values = np.array(series.values, dtype=float)
        x = np.arange(len(values), dtype=float)

        if models is None:
            models = list(TrendModel)

        best_result: Optional[TrendResult] = None
        best_r2 = -float("inf")

        for model in models:
            result = self._fit_trend_model(x, values, model)
            if result is not None and result.r_squared > best_r2:
                best_r2 = result.r_squared
                best_result = result

        if best_result is None:
            best_result = TrendResult(
                model=TrendModel.LINEAR,
                coefficients=[0.0, float(np.mean(values))],
                r_squared=0.0,
                mse=float(np.var(values)),
                direction="stable",
                description="Could not fit any trend model",
            )

        self._trend_results[rule_id] = best_result
        return best_result

    def _fit_trend_model(
        self,
        x: np.ndarray,
        y: np.ndarray,
        model: TrendModel,
    ) -> Optional[TrendResult]:
        """Fit a specific trend model and return TrendResult."""
        n = len(x)
        try:
            if model == TrendModel.LINEAR:
                coeffs = np.polyfit(x, y, 1)
                y_pred = np.polyval(coeffs, x)

            elif model == TrendModel.EXPONENTIAL:
                if np.any(y <= 0):
                    return None
                log_y = np.log(y)
                coeffs = np.polyfit(x, log_y, 1)
                y_pred = np.exp(np.polyval(coeffs, x))

            elif model == TrendModel.POLYNOMIAL:
                degree = min(self._config.polynomial_degree, n - 2)
                if degree < 1:
                    return None
                coeffs = np.polyfit(x, y, degree)
                y_pred = np.polyval(coeffs, x)

            elif model == TrendModel.LOGARITHMIC:
                if np.any(x <= 0):
                    x_pos = x + 1
                else:
                    x_pos = x
                log_x = np.log(x_pos)
                coeffs = np.polyfit(log_x, y, 1)
                y_pred = np.polyval(coeffs, log_x)

            elif model == TrendModel.POWER:
                if np.any(y <= 0) or np.any(x <= 0):
                    return None
                log_x = np.log(x + 1)
                log_y = np.log(y)
                coeffs = np.polyfit(log_x, log_y, 1)
                y_pred = np.exp(np.polyval(coeffs, log_x))

            else:
                return None

            ss_res = float(np.sum((y - y_pred) ** 2))
            ss_tot = float(np.sum((y - np.mean(y)) ** 2))
            r_squared = 1.0 - (ss_res / max(ss_tot, 1e-10))
            mse = ss_res / max(n, 1)

            slope = coeffs[0] if len(coeffs) >= 1 else 0
            if slope > 0.01:
                direction = "increasing"
            elif slope < -0.01:
                direction = "decreasing"
            else:
                direction = "stable"

            return TrendResult(
                model=model,
                coefficients=[float(c) for c in coeffs],
                r_squared=max(0.0, r_squared),
                mse=mse,
                direction=direction,
                description=f"{model.value} trend ({direction}, R²={r_squared:.3f})",
            )

        except Exception as exc:
            logger.debug("Failed to fit %s trend: %s", model.value, exc)
            return None

    def detect_all_trends(self) -> Dict[str, TrendResult]:
        """Detect trends for all ingested rule series."""
        for rule_id in self._rule_series:
            self.detect_trend(rule_id)
        return dict(self._trend_results)

    # ------------------------------------------------------------------
    # Periodicity Detection
    # ------------------------------------------------------------------

    def detect_periodicity(self, rule_id: str) -> PeriodicityResult:
        """
        Detect periodic patterns in rule firing data using FFT and autocorrelation.

        Returns:
            PeriodicityResult with detected periods and confidence.
        """
        series = self._rule_series.get(rule_id)
        if series is None or len(series) < self._config.min_data_points:
            return PeriodicityResult(
                has_periodicity=False,
                dominant_period_days=None,
                seasonal_period=SeasonalPeriod.NO_SEASONALITY,
                fft_peaks=[],
                autocorrelation_peaks=[],
                confidence=0.0,
            )

        values = np.array(series.values, dtype=float)
        n = len(values)

        fft_peaks: List[Dict[str, float]] = []
        autocorr_peaks: List[Dict[str, float]] = []

        if self._config.enable_fft_periodicity and n >= 4:
            fft = np.fft.rfft(values - np.mean(values))
            freqs = np.fft.rfftfreq(n)
            power = np.abs(fft) ** 2

            peak_indices = np.argsort(power)[-10:][::-1]
            for idx in peak_indices:
                if freqs[idx] > 0:
                    period_days = int(1.0 / freqs[idx])
                    significance = float(power[idx] / max(np.sum(power), 1e-10))
                    if significance >= self._config.fft_significance_threshold:
                        fft_peaks.append({
                            "period_days": period_days,
                            "frequency": float(freqs[idx]),
                            "significance": round(significance, 4),
                        })

        if n >= self._config.autocorrelation_lag_max:
            max_lag = min(self._config.autocorrelation_lag_max, n // 2)
        else:
            max_lag = max(1, n // 2)

        if max_lag >= 2:
            mean_val = np.mean(values)
            std_val = np.std(values) or 1.0
            auto_corr: List[float] = []
            for lag in range(1, max_lag + 1):
                if n - lag <= 0:
                    break
                cov = np.mean((values[:-lag] - mean_val) * (values[lag:] - mean_val))
                auto_corr.append(float(cov / (std_val ** 2)))

            if auto_corr:
                auto_arr = np.array(auto_corr)
                peak_lags = np.argsort(auto_arr)[-5:][::-1]
                for lag_idx in peak_lags:
                    if auto_arr[lag_idx] > 0.3:
                        autocorr_peaks.append({
                            "lag_days": int(lag_idx + 1),
                            "correlation": round(float(auto_arr[lag_idx]), 4),
                        })

        has_periodicity = len(fft_peaks) > 0 or len(autocorr_peaks) > 0

        dominant_period = None
        seasonal_period = SeasonalPeriod.NO_SEASONALITY

        if fft_peaks:
            dominant_period = float(fft_peaks[0]["period_days"])
            seasonal_period = self._classify_period(dominant_period)
        elif autocorr_peaks:
            dominant_period = float(autocorr_peaks[0]["lag_days"])
            seasonal_period = self._classify_period(dominant_period)

        confidence = 0.0
        if has_periodicity:
            if fft_peaks:
                confidence = fft_peaks[0]["significance"]
            elif autocorr_peaks:
                confidence = autocorr_peaks[0]["correlation"]
            confidence = min(confidence * 2, 1.0)

        result = PeriodicityResult(
            has_periodicity=has_periodicity,
            dominant_period_days=dominant_period,
            seasonal_period=seasonal_period,
            fft_peaks=fft_peaks[:5],
            autocorrelation_peaks=autocorr_peaks[:5],
            confidence=round(confidence, 4),
        )
        self._periodicity_results[rule_id] = result
        return result

    @staticmethod
    def _classify_period(period_days: float) -> SeasonalPeriod:
        """Classify a numerical period into a SeasonalPeriod enum."""
        if period_days < 0.5:
            return SeasonalPeriod.HOURLY
        if period_days < 2:
            return SeasonalPeriod.DAILY
        if period_days < 10:
            return SeasonalPeriod.WEEKLY
        if period_days < 45:
            return SeasonalPeriod.MONTHLY
        if period_days < 180:
            return SeasonalPeriod.QUARTERLY
        return SeasonalPeriod.YEARLY

    def detect_all_periodicities(self) -> Dict[str, PeriodicityResult]:
        """Detect periodicity for all ingested rule series."""
        for rule_id in self._rule_series:
            self.detect_periodicity(rule_id)
        return dict(self._periodicity_results)

    # ------------------------------------------------------------------
    # Seasonal Pattern Detection
    # ------------------------------------------------------------------

    def detect_seasonal_patterns(self, rule_id: str) -> Dict[str, Any]:
        """
        Detect detailed seasonal patterns across multiple time scales.

        Returns:
            Dict with hourly, daily, weekly, and monthly seasonal profiles.
        """
        series = self._rule_series.get(rule_id)
        if series is None or len(series) < self._config.min_data_points:
            return {"has_sufficient_data": False}

        hourly: Dict[int, float] = defaultdict(float)
        hourly_count: Dict[int, int] = defaultdict(int)
        daily: Dict[str, float] = defaultdict(float)
        daily_count: Dict[str, int] = defaultdict(int)
        weekly: Dict[int, float] = defaultdict(float)
        weekly_count: Dict[int, int] = defaultdict(int)
        monthly: Dict[int, float] = defaultdict(float)
        monthly_count: Dict[int, int] = defaultdict(int)

        for ts, val in zip(series.timestamps, series.values):
            hourly[ts.hour] += val
            hourly_count[ts.hour] += 1
            day_name = ts.strftime("%A")
            daily[day_name] += val
            daily_count[day_name] += 1
            weekly[ts.weekday()] += val
            weekly_count[ts.weekday()] += 1
            monthly[ts.month] += val
            monthly_count[ts.month] += 1

        return {
            "has_sufficient_data": True,
            "hourly_profile": {
                str(h): round(hourly[h] / max(hourly_count[h], 1), 4)
                for h in sorted(hourly.keys())
            },
            "daily_profile": {
                d: round(daily[d] / max(daily_count[d], 1), 4)
                for d in self._DAY_NAMES if d in daily
            },
            "weekly_profile": {
                str(w): round(weekly[w] / max(weekly_count[w], 1), 4)
                for w in sorted(weekly.keys())
            },
            "monthly_profile": {
                str(m): round(monthly[m] / max(monthly_count[m], 1), 4)
                for m in sorted(monthly.keys())
            },
            "peak_hour": max(hourly, key=lambda h: hourly[h] / max(hourly_count[h], 1)) if hourly else None,
            "peak_day": max(daily, key=lambda d: daily[d] / max(daily_count[d], 1)) if daily else None,
            "peak_month": max(monthly, key=lambda m: monthly[m] / max(monthly_count[m], 1)) if monthly else None,
        }

    # ------------------------------------------------------------------
    # Change Point Detection
    # ------------------------------------------------------------------

    def detect_change_points(self, rule_id: str) -> List[ChangePoint]:
        """
        Detect change points in rule firing time series.

        Uses sliding window statistics to identify points where the
        mean, variance, or trend behavior changes significantly.

        Returns:
            List of ChangePoint objects sorted by index.
        """
        if not self._config.enable_change_point_detection:
            return []

        series = self._rule_series.get(rule_id)
        if series is None or len(series) < self._config.min_data_points * 2:
            return []

        values = np.array(series.values, dtype=float)
        n = len(values)
        min_dist = self._config.change_point_min_distance
        threshold = self._config.change_point_threshold
        window = max(min_dist, 5)

        change_points: List[ChangePoint] = []

        for i in range(window, n - window):
            before = values[i - window:i]
            after = values[i:i + window]

            before_mean = float(np.mean(before))
            after_mean = float(np.mean(after))
            before_std = float(np.std(before)) or 1.0

            mean_diff = abs(after_mean - before_mean)
            z_score = mean_diff / (before_std / math.sqrt(window))

            if z_score > threshold:
                change_type = ChangePointType.MEAN_SHIFT
                magnitude = (after_mean - before_mean) / max(before_mean, 0.01)

                cp = ChangePoint(
                    index=i,
                    timestamp=series.timestamps[i],
                    change_type=change_type,
                    magnitude=magnitude,
                    confidence=min(z_score / 5.0, 1.0),
                    before_stats={"mean": before_mean, "std": before_std, "count": window},
                    after_stats={"mean": after_mean, "std": float(np.std(after)), "count": window},
                )
                change_points.append(cp)

        merged = self._merge_change_points(change_points, min_dist)
        merged.sort(key=lambda cp: cp.index)

        self._change_points[rule_id] = merged
        logger.info("Detected %d change points for rule %s", len(merged), rule_id)
        return merged

    @staticmethod
    def _merge_change_points(
        points: List[ChangePoint],
        min_distance: int,
    ) -> List[ChangePoint]:
        """Merge nearby change points, keeping the one with highest confidence."""
        if not points:
            return []

        points.sort(key=lambda cp: cp.index)
        merged: List[ChangePoint] = [points[0]]

        for cp in points[1:]:
            if cp.index - merged[-1].index < min_distance:
                if cp.confidence > merged[-1].confidence:
                    merged[-1] = cp
            else:
                merged.append(cp)

        return merged

    def detect_all_change_points(self) -> Dict[str, List[ChangePoint]]:
        """Detect change points for all ingested rule series."""
        for rule_id in self._rule_series:
            self.detect_change_points(rule_id)
        return dict(self._change_points)

    # ------------------------------------------------------------------
    # Forecasting
    # ------------------------------------------------------------------

    def forecast(
        self,
        rule_id: str,
        horizon: Optional[int] = None,
        method: str = "auto",
    ) -> ForecastResult:
        """
        Generate future forecasts for rule firing time series.

        Args:
            rule_id: ID of the rule.
            horizon: Number of time steps to forecast (defaults to config value).
            method: 'moving_average', 'exponential_smoothing', or 'auto'.

        Returns:
            ForecastResult with forecast values and confidence intervals.
        """
        if not self._config.enable_forecasting:
            return ForecastResult(
                method="disabled",
                forecast_values=[],
                confidence_intervals=[],
                mse=0.0,
                horizon=horizon or self._config.forecast_horizon,
            )

        series = self._rule_series.get(rule_id)
        if series is None or len(series) < self._config.min_data_points:
            return ForecastResult(
                method=method,
                forecast_values=[],
                confidence_intervals=[],
                mse=0.0,
                horizon=horizon or self._config.forecast_horizon,
            )

        horizon = horizon or self._config.forecast_horizon
        values = np.array(series.values, dtype=float)
        n = len(values)

        if method == "auto":
            if n >= 30:
                method = "exponential_smoothing"
            else:
                method = "moving_average"

        if method == "moving_average":
            result = self._moving_average_forecast(values, horizon)
        elif method == "exponential_smoothing":
            result = self._exponential_smoothing_forecast(values, horizon)
        else:
            result = ForecastResult(
                method="unknown",
                forecast_values=[],
                confidence_intervals=[],
                mse=0.0,
                horizon=horizon,
            )

        self._forecasts[rule_id] = result
        return result

    def _moving_average_forecast(
        self,
        values: np.ndarray,
        horizon: int,
    ) -> ForecastResult:
        """Forecast using simple moving average."""
        window = min(self._config.moving_average_window, len(values))
        if window < 1:
            window = 1

        ma_values = np.convolve(values, np.ones(window) / window, mode="valid")
        last_ma = float(ma_values[-1]) if len(ma_values) > 0 else float(values[-1])

        residuals = values[window - 1:] - ma_values[:len(values) - window + 1] if len(values) > window else np.array([0.0])
        residual_std = float(np.std(residuals)) if len(residuals) > 1 else float(np.std(values)) * 0.5

        forecast_values = [last_ma] * horizon
        confidence_intervals = [
            {
                "lower": last_ma - 1.96 * residual_std,
                "upper": last_ma + 1.96 * residual_std,
            }
            for _ in range(horizon)
        ]

        mse = float(np.mean(residuals ** 2)) if len(residuals) > 0 else 0.0

        return ForecastResult(
            method=f"moving_average_w{window}",
            forecast_values=forecast_values,
            confidence_intervals=confidence_intervals,
            mse=mse,
            horizon=horizon,
        )

    def _exponential_smoothing_forecast(
        self,
        values: np.ndarray,
        horizon: int,
    ) -> ForecastResult:
        """Forecast using simple exponential smoothing."""
        alpha = self._config.exponential_smoothing_alpha
        n = len(values)

        smoothed = np.zeros(n)
        smoothed[0] = values[0]
        for t in range(1, n):
            smoothed[t] = alpha * values[t] + (1 - alpha) * smoothed[t - 1]

        last_smoothed = float(smoothed[-1])
        residuals = values - smoothed
        residual_std = float(np.std(residuals)) if n > 1 else float(np.std(values)) * 0.5

        forecast_values = [last_smoothed] * horizon
        confidence_intervals = [
            {
                "lower": last_smoothed - 1.96 * residual_std,
                "upper": last_smoothed + 1.96 * residual_std,
            }
            for _ in range(horizon)
        ]

        mse = float(np.mean(residuals ** 2))

        return ForecastResult(
            method=f"exponential_smoothing_a{alpha}",
            forecast_values=forecast_values,
            confidence_intervals=confidence_intervals,
            mse=mse,
            horizon=horizon,
        )

    def forecast_all(self, horizon: Optional[int] = None) -> Dict[str, ForecastResult]:
        """Generate forecasts for all ingested rule series."""
        for rule_id in self._rule_series:
            self.forecast(rule_id, horizon)
        return dict(self._forecasts)

    # ------------------------------------------------------------------
    # Comprehensive Analysis
    # ------------------------------------------------------------------

    def analyze_rule(self, rule_id: str) -> Dict[str, Any]:
        """
        Run full temporal analysis pipeline for a single rule.

        Combines trend detection, periodicity, seasonal patterns,
        change points, and forecasting into a single result dict.

        Returns:
            Dict with all temporal analysis results for the rule.
        """
        trend = self.detect_trend(rule_id)
        periodicity = self.detect_periodicity(rule_id)
        seasonal = self.detect_seasonal_patterns(rule_id)
        changes = self.detect_change_points(rule_id)
        forecast_res = self.forecast(rule_id)

        return {
            "rule_id": rule_id,
            "data_points": len(self._rule_series.get(rule_id, [])),
            "trend": trend.to_dict(),
            "periodicity": periodicity.to_dict(),
            "seasonal_patterns": seasonal,
            "change_points": [cp.to_dict() for cp in changes],
            "forecast": forecast_res.to_dict(),
        }

    # ------------------------------------------------------------------
    # Statistics & Export
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about temporal analysis results."""
        return {
            "rules_analyzed": len(self._rule_series),
            "total_data_points": sum(len(s) for s in self._rule_series.values()),
            "trends_detected": len(self._trend_results),
            "periodicities_detected": sum(
                1 for r in self._periodicity_results.values() if r.has_periodicity
            ),
            "change_points_detected": sum(len(cps) for cps in self._change_points.values()),
            "forecasts_generated": len(self._forecasts),
            "config": self._config.to_dict(),
        }

    def export_viz_data(self, rule_id: str) -> Dict[str, Any]:
        """
        Export visualization-ready data for external charting.

        Returns data structured for plotting: trend lines, seasonal
        profiles, forecast projections, and change point markers.
        """
        series = self._rule_series.get(rule_id)
        if series is None:
            return {"rule_id": rule_id, "error": "No data available"}

        trend = self._trend_results.get(rule_id)
        periodicity = self._periodicity_results.get(rule_id)
        changes = self._change_points.get(rule_id, [])
        forecast_res = self._forecasts.get(rule_id)

        timestamps_iso = [t.isoformat() for t in series.timestamps]

        viz_data: Dict[str, Any] = {
            "rule_id": rule_id,
            "original_series": {
                "timestamps": timestamps_iso,
                "values": series.values,
            },
            "change_point_markers": [
                {"timestamp": cp.timestamp.isoformat(), "type": cp.change_type.value}
                for cp in changes
            ],
        }

        if trend is not None and trend.r_squared > 0:
            x = np.arange(len(series.values))
            if trend.model == TrendModel.LINEAR:
                trend_values = np.polyval(trend.coefficients, x).tolist()
            elif trend.model == TrendModel.EXPONENTIAL:
                trend_values = np.exp(np.polyval(trend.coefficients, x)).tolist()
            elif trend.model == TrendModel.POLYNOMIAL:
                trend_values = np.polyval(trend.coefficients, x).tolist()
            else:
                trend_values = []
            viz_data["trend_line"] = {
                "timestamps": timestamps_iso,
                "values": [round(v, 4) for v in trend_values],
                "model": trend.model.value,
                "r_squared": trend.r_squared,
            }

        if forecast_res is not None and forecast_res.forecast_values:
            last_ts = series.timestamps[-1]
            forecast_timestamps = [
                (last_ts + timedelta(days=i + 1)).isoformat()
                for i in range(forecast_res.horizon)
            ]
            viz_data["forecast"] = {
                "timestamps": forecast_timestamps,
                "values": [round(v, 4) for v in forecast_res.forecast_values],
                "confidence_intervals": forecast_res.confidence_intervals,
                "method": forecast_res.method,
            }

        if periodicity is not None:
            viz_data["periodicity"] = {
                "has_periodicity": periodicity.has_periodicity,
                "dominant_period_days": periodicity.dominant_period_days,
                "seasonal_period": periodicity.seasonal_period.value,
            }

        return viz_data

    def export_data(self) -> Dict[str, Any]:
        """Export all temporal analysis data for external consumption."""
        return {
            "config": self._config.to_dict(),
            "stats": self.get_stats(),
            "trends": {rid: r.to_dict() for rid, r in self._trend_results.items()},
            "periodicities": {rid: r.to_dict() for rid, r in self._periodicity_results.items()},
            "change_points": {
                rid: [cp.to_dict() for cp in cps]
                for rid, cps in self._change_points.items()
            },
            "forecasts": {rid: f.to_dict() for rid, f in self._forecasts.items()},
        }

    def reset(self) -> None:
        """Reset all analyzer state."""
        self._rule_series.clear()
        self._trend_results.clear()
        self._periodicity_results.clear()
        self._change_points.clear()
        self._forecasts.clear()
        logger.info("TemporalPatternAnalyzer reset to initial state")
