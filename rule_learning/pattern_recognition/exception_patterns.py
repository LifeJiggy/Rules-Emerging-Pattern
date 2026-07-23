"""
Exception pattern analysis for rule evaluation.

Tracks, categorizes, and analyzes exception patterns raised during rule
evaluation. Provides frequency analysis, clustering, severity classification,
prediction, and correlation with rule changes.
"""

import logging
import uuid
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from pydantic import BaseModel, Field

from rules_emerging_pattern.models.rule import Rule, RuleSeverity
from rules_emerging_pattern.models.conflict import ConflictSeverity

logger = logging.getLogger(__name__)


class ExceptionCategory(str, Enum):
    """Categories of exceptions raised during rule evaluation."""

    EVALUATION_ERROR = "evaluation_error"
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    PATTERN_MISMATCH = "pattern_mismatch"
    CONTEXT_ERROR = "context_error"
    DEPENDENCY_ERROR = "dependency_error"
    CONFIGURATION_ERROR = "configuration_error"
    PERMISSION_DENIED = "permission_denied"
    DATA_INTEGRITY = "data_integrity"
    UNKNOWN = "unknown"


class ExceptionSeverity(str, Enum):
    """Severity levels for exception events."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExceptionRecord:
    """
    A single exception occurrence record with full context.
    """

    def __init__(
        self,
        record_id: str,
        rule_id: str,
        exception_type: str,
        exception_message: str,
        category: ExceptionCategory,
        severity: ExceptionSeverity,
        context: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
        stack_trace: Optional[str] = None,
        resolved: bool = False,
    ) -> None:
        self.record_id = record_id
        self.rule_id = rule_id
        self.exception_type = exception_type
        self.exception_message = exception_message
        self.category = category
        self.severity = severity
        self.context = context or {}
        self.timestamp = timestamp or datetime.utcnow()
        self.stack_trace = stack_trace
        self.resolved = resolved

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "record_id": self.record_id,
            "rule_id": self.rule_id,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "category": self.category.value,
            "severity": self.severity.value,
            "context": self.context,
            "timestamp": self.timestamp.isoformat(),
            "stack_trace": self.stack_trace[-500:] if self.stack_trace else None,
            "resolved": self.resolved,
        }


class ExceptionCluster:
    """A cluster of related exception records."""

    def __init__(
        self,
        cluster_id: str,
        category: ExceptionCategory,
        exception_types: List[str],
        affected_rules: List[str],
        record_count: int,
        average_severity_score: float,
        first_occurrence: datetime,
        last_occurrence: datetime,
        common_context: Dict[str, Any],
    ) -> None:
        self.cluster_id = cluster_id
        self.category = category
        self.exception_types = exception_types
        self.affected_rules = affected_rules
        self.record_count = record_count
        self.average_severity_score = average_severity_score
        self.first_occurrence = first_occurrence
        self.last_occurrence = last_occurrence
        self.common_context = common_context

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "cluster_id": self.cluster_id,
            "category": self.category.value,
            "exception_types": self.exception_types[:5],
            "affected_rules": self.affected_rules,
            "record_count": self.record_count,
            "average_severity_score": self.average_severity_score,
            "first_occurrence": self.first_occurrence.isoformat(),
            "last_occurrence": self.last_occurrence.isoformat(),
            "common_context": self.common_context,
        }


class ExceptionPrediction:
    """
    Predicted future exception event with probability and expected impact.
    """

    def __init__(
        self,
        prediction_id: str,
        rule_id: str,
        predicted_category: ExceptionCategory,
        probability: float,
        expected_severity: ExceptionSeverity,
        time_horizon_hours: int,
        confidence: float,
        contributing_factors: List[str],
    ) -> None:
        self.prediction_id = prediction_id
        self.rule_id = rule_id
        self.predicted_category = predicted_category
        self.probability = probability
        self.expected_severity = expected_severity
        self.time_horizon_hours = time_horizon_hours
        self.confidence = confidence
        self.contributing_factors = contributing_factors

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "prediction_id": self.prediction_id,
            "rule_id": self.rule_id,
            "predicted_category": self.predicted_category.value,
            "probability": self.probability,
            "expected_severity": self.expected_severity.value,
            "time_horizon_hours": self.time_horizon_hours,
            "confidence": self.confidence,
            "contributing_factors": self.contributing_factors,
        }


class ExceptionPatternAnalyzerConfig:
    """Configuration for ExceptionPatternAnalyzer."""

    def __init__(
        self,
        min_records_for_cluster: int = 3,
        min_records_for_prediction: int = 10,
        history_window_days: int = 90,
        cluster_time_window_hours: int = 24,
        severity_threshold_critical: float = 0.8,
        severity_threshold_high: float = 0.6,
        severity_threshold_medium: float = 0.4,
        prediction_min_probability: float = 0.3,
        trend_data_points_required: int = 5,
        max_exception_types_per_cluster: int = 10,
        enable_prediction: bool = True,
        enable_clustering: bool = True,
        anomaly_std_dev_threshold: float = 2.0,
    ) -> None:
        self.min_records_for_cluster = min_records_for_cluster
        self.min_records_for_prediction = min_records_for_prediction
        self.history_window_days = history_window_days
        self.cluster_time_window_hours = cluster_time_window_hours
        self.severity_threshold_critical = severity_threshold_critical
        self.severity_threshold_high = severity_threshold_high
        self.severity_threshold_medium = severity_threshold_medium
        self.prediction_min_probability = prediction_min_probability
        self.trend_data_points_required = trend_data_points_required
        self.max_exception_types_per_cluster = max_exception_types_per_cluster
        self.enable_prediction = enable_prediction
        self.enable_clustering = enable_clustering
        self.anomaly_std_dev_threshold = anomaly_std_dev_threshold

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class ExceptionPatternAnalyzer:
    """
    Analyzes exception patterns raised during rule evaluation.

    Capabilities:
    - Exception frequency analysis (per-rule, per-type, per-context)
    - Exception clustering (temporal and contextual grouping)
    - Exception severity classification
    - Exception prediction based on historical data
    - Exception correlation with rule changes
    - Anomaly detection in exception patterns
    - Configurable thresholds and analysis windows
    """

    _SEVERITY_SCORE_MAP = {
        ExceptionSeverity.LOW: 1,
        ExceptionSeverity.MEDIUM: 2,
        ExceptionSeverity.HIGH: 3,
        ExceptionSeverity.CRITICAL: 4,
    }

    def __init__(self, config: Optional[ExceptionPatternAnalyzerConfig] = None) -> None:
        self._config = config or ExceptionPatternAnalyzerConfig()
        self._records: Dict[str, ExceptionRecord] = {}
        self._clusters: Dict[str, ExceptionCluster] = {}
        self._predictions: Dict[str, ExceptionPrediction] = {}
        self._rule_change_log: Dict[str, List[datetime]] = defaultdict(list)
        self._rule_cache: Dict[str, Rule] = {}
        logger.info("ExceptionPatternAnalyzer initialized with config: %s", self._config.to_dict())

    # ------------------------------------------------------------------
    # Registration & Data Ingestion
    # ------------------------------------------------------------------

    def register_rule(self, rule: Rule) -> None:
        """Register a rule for exception analysis."""
        self._rule_cache[rule.id] = rule
        logger.debug("Registered rule: %s", rule.id)

    def record_exception(self, record: ExceptionRecord) -> None:
        """Record a single exception event."""
        self._records[record.record_id] = record
        logger.debug("Recorded exception %s for rule %s: %s", record.record_id, record.rule_id, record.exception_type)

    def record_exceptions(self, records: Sequence[ExceptionRecord]) -> None:
        """Record multiple exception events."""
        for record in records:
            self.record_exception(record)

    def log_rule_change(self, rule_id: str, timestamp: Optional[datetime] = None) -> None:
        """Log a rule change event for correlation analysis."""
        self._rule_change_log[rule_id].append(timestamp or datetime.utcnow())

    # ------------------------------------------------------------------
    # Frequency Analysis
    # ------------------------------------------------------------------

    def analyze_frequency(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Compute exception frequency statistics across all dimensions.

        Returns:
            Dict with per-rule, per-type, and per-category frequency breakdowns.
        """
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        relevant = [r for r in self._records.values() if r.timestamp >= cutoff]

        per_rule: Dict[str, int] = defaultdict(int)
        per_type: Dict[str, int] = defaultdict(int)
        per_category: Dict[str, int] = defaultdict(int)
        per_severity: Dict[str, int] = defaultdict(int)
        per_day: Dict[str, int] = defaultdict(int)

        for record in relevant:
            per_rule[record.rule_id] += 1
            per_type[record.exception_type] += 1
            per_category[record.category.value] += 1
            per_severity[record.severity.value] += 1
            day_key = record.timestamp.strftime("%Y-%m-%d")
            per_day[day_key] += 1

        total = len(relevant)
        return {
            "analyzed_period_days": window,
            "total_exceptions": total,
            "unique_affected_rules": len(per_rule),
            "unique_exception_types": len(per_type),
            "per_rule": dict(per_rule),
            "per_type": dict(per_type),
            "per_category": dict(per_category),
            "per_severity": dict(per_severity),
            "per_day": dict(per_day),
            "average_per_day": round(total / max(window, 1), 2),
            "top_affected_rules": sorted(per_rule.items(), key=lambda x: x[1], reverse=True)[:10],
            "top_exception_types": sorted(per_type.items(), key=lambda x: x[1], reverse=True)[:10],
        }

    def get_rule_exception_frequency(self, rule_id: str, days: Optional[int] = None) -> Dict[str, Any]:
        """Get exception frequency statistics for a specific rule."""
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        relevant = [
            r for r in self._records.values()
            if r.rule_id == rule_id and r.timestamp >= cutoff
        ]

        per_type: Dict[str, int] = defaultdict(int)
        per_severity: Dict[str, int] = defaultdict(int)
        per_category: Dict[str, int] = defaultdict(int)

        for record in relevant:
            per_type[record.exception_type] += 1
            per_severity[record.severity.value] += 1
            per_category[record.category.value] += 1

        return {
            "rule_id": rule_id,
            "total_exceptions": len(relevant),
            "frequency_per_day": round(len(relevant) / max(window, 1), 2),
            "per_type": dict(per_type),
            "per_severity": dict(per_severity),
            "per_category": dict(per_category),
            "most_common_type": max(per_type, key=per_type.get) if per_type else None,
            "severity_trend": self._compute_severity_trend(relevant),
        }

    # ------------------------------------------------------------------
    # Contextual Analysis
    # ------------------------------------------------------------------

    def analyze_contextual_patterns(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Analyze exception patterns grouped by evaluation context.

        Returns:
            Dict with context-based frequency analysis and correlations.
        """
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        relevant = [r for r in self._records.values() if r.timestamp >= cutoff]

        context_domain: Dict[str, int] = defaultdict(int)
        context_role: Dict[str, int] = defaultdict(int)
        context_content_type: Dict[str, int] = defaultdict(int)

        for record in relevant:
            ctx = record.context
            domain = ctx.get("domain", "unknown")
            role = ctx.get("user_role", "unknown")
            content_type = ctx.get("content_type", "unknown")
            context_domain[domain] += 1
            context_role[role] += 1
            context_content_type[content_type] += 1

        return {
            "period_days": window,
            "total_context_aware_records": len(relevant),
            "by_domain": dict(context_domain),
            "by_user_role": dict(context_role),
            "by_content_type": dict(context_content_type),
            "domain_with_most_exceptions": max(context_domain, key=context_domain.get) if context_domain else None,
        }

    # ------------------------------------------------------------------
    # Anomaly Detection
    # ------------------------------------------------------------------

    def detect_anomalies(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Detect anomalous exception patterns using statistical deviation.

        Identifies days, rules, or exception types with abnormally high
        counts compared to their historical baseline.
        """
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        relevant = [r for r in self._records.values() if r.timestamp >= cutoff]

        daily_counts: Dict[str, int] = defaultdict(int)
        rule_counts: Dict[str, int] = defaultdict(int)
        type_counts: Dict[str, int] = defaultdict(int)

        for record in relevant:
            day_key = record.timestamp.strftime("%Y-%m-%d")
            daily_counts[day_key] += 1
            rule_counts[record.rule_id] += 1
            type_counts[record.exception_type] += 1

        anomalies: Dict[str, Any] = {"daily": [], "per_rule": [], "per_type": []}

        daily_values = list(daily_counts.values())
        if len(daily_values) >= 5:
            mean = float(np.mean(daily_values))
            std = float(np.std(daily_values)) or 1.0
            threshold = mean + self._config.anomaly_std_dev_threshold * std
            for day, count in sorted(daily_counts.items()):
                if count > threshold:
                    anomalies["daily"].append({
                        "day": day,
                        "count": count,
                        "expected": round(mean, 2),
                        "deviation": round((count - mean) / std, 2),
                    })

        rule_values = list(rule_counts.values())
        if len(rule_values) >= 3:
            mean = float(np.mean(rule_values))
            std = float(np.std(rule_values)) or 1.0
            threshold = mean + self._config.anomaly_std_dev_threshold * std
            for rule_id, count in sorted(rule_counts.items(), key=lambda x: x[1], reverse=True):
                if count > threshold:
                    anomalies["per_rule"].append({
                        "rule_id": rule_id,
                        "count": count,
                        "expected": round(mean, 2),
                        "deviation": round((count - mean) / std, 2),
                    })

        return anomalies

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def find_clusters(self) -> List[ExceptionCluster]:
        """
        Identify clusters of related exception records based on temporal
        proximity and shared characteristics.

        Clusters are formed from records occurring within a configurable
        time window that share similar exception types or rule IDs.
        """
        if not self._config.enable_clustering:
            return []

        sorted_records = sorted(self._records.values(), key=lambda r: r.timestamp)
        window = timedelta(hours=self._config.cluster_time_window_hours)

        clusters: List[List[ExceptionRecord]] = []
        used: Set[str] = set()

        for i, record in enumerate(sorted_records):
            if record.record_id in used:
                continue
            cluster = [record]
            used.add(record.record_id)
            for j in range(i + 1, len(sorted_records)):
                other = sorted_records[j]
                if other.record_id in used:
                    continue
                time_diff = abs((other.timestamp - record.timestamp).total_seconds())
                if time_diff > window.total_seconds():
                    break
                if (
                    other.rule_id == record.rule_id
                    or other.category == record.category
                    or other.exception_type == record.exception_type
                ):
                    cluster.append(other)
                    used.add(other.record_id)
            if len(cluster) >= self._config.min_records_for_cluster:
                clusters.append(cluster)

        result: List[ExceptionCluster] = []
        for idx, cluster in enumerate(clusters):
            categories = Counter(r.category for r in cluster)
            dominant_category = categories.most_common(1)[0][0]

            exception_types = list(set(r.exception_type for r in cluster))
            affected_rules = list(set(r.rule_id for r in cluster))
            severity_scores = [self._SEVERITY_SCORE_MAP.get(r.severity, 1) for r in cluster]
            avg_severity = float(np.mean(severity_scores)) if severity_scores else 1.0

            timestamps = [r.timestamp for r in cluster]
            first_ts = min(timestamps)
            last_ts = max(timestamps)

            common_ctx_keys = {"domain", "user_role", "content_type", "organization"}
            common_ctx: Dict[str, Any] = {}
            for key in common_ctx_keys:
                values = [r.context.get(key) for r in cluster if key in r.context]
                if values:
                    common_ctx[key] = Counter(values).most_common(1)[0][0]

            cluster_obj = ExceptionCluster(
                cluster_id=f"ec_{idx:04d}",
                category=dominant_category,
                exception_types=exception_types[:self._config.max_exception_types_per_cluster],
                affected_rules=affected_rules,
                record_count=len(cluster),
                average_severity_score=round(avg_severity, 2),
                first_occurrence=first_ts,
                last_occurrence=last_ts,
                common_context=common_ctx,
            )
            result.append(cluster_obj)
            self._clusters[cluster_obj.cluster_id] = cluster_obj

        logger.info("Found %d exception clusters from %d records", len(result), len(sorted_records))
        return result

    # ------------------------------------------------------------------
    # Severity Classification
    # ------------------------------------------------------------------

    def classify_severity(self, record: ExceptionRecord) -> ExceptionSeverity:
        """
        Classify the severity of an exception record based on its
        category, frequency of similar exceptions, and context.
        """
        base_score = self._SEVERITY_SCORE_MAP.get(record.severity, 1)

        frequency_boost = 0.0
        recent_cutoff = datetime.utcnow() - timedelta(hours=24)
        similar_count = sum(
            1 for r in self._records.values()
            if r.rule_id == record.rule_id
            and r.category == record.category
            and r.timestamp >= recent_cutoff
        )
        if similar_count > 10:
            frequency_boost = 1.0
        elif similar_count > 5:
            frequency_boost = 0.5

        adjusted_score = min(base_score + frequency_boost, 4.0)

        if adjusted_score >= self._config.severity_threshold_critical * 4:
            return ExceptionSeverity.CRITICAL
        if adjusted_score >= self._config.severity_threshold_high * 4:
            return ExceptionSeverity.HIGH
        if adjusted_score >= self._config.severity_threshold_medium * 4:
            return ExceptionSeverity.MEDIUM
        return ExceptionSeverity.LOW

    def get_severity_distribution(self, days: Optional[int] = None) -> Dict[str, int]:
        """Get the distribution of exception severities over a time window."""
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        distribution: Dict[str, int] = defaultdict(int)
        for record in self._records.values():
            if record.timestamp >= cutoff:
                distribution[record.severity.value] += 1
        return dict(distribution)

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict_exceptions(self) -> List[ExceptionPrediction]:
        """
        Predict future exception events based on historical patterns.

        Uses frequency analysis and trend detection across rules and
        exception types to generate probabilistic predictions.
        """
        if not self._config.enable_prediction:
            return []

        cutoff = datetime.utcnow() - timedelta(days=self._config.history_window_days)
        relevant = [r for r in self._records.values() if r.timestamp >= cutoff]
        recent_cutoff = datetime.utcnow() - timedelta(days=7)

        if len(relevant) < self._config.min_records_for_prediction:
            logger.debug("Insufficient data for prediction: %d records", len(relevant))
            return []

        rule_counts: Dict[str, int] = defaultdict(int)
        rule_recent_counts: Dict[str, int] = defaultdict(int)
        rule_category: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for record in relevant:
            rule_counts[record.rule_id] += 1
            rule_category[record.rule_id][record.category.value] += 1
            if record.timestamp >= recent_cutoff:
                rule_recent_counts[record.rule_id] += 1

        predictions: List[ExceptionPrediction] = []
        for rule_id, total_count in rule_counts.items():
            if total_count < self._config.min_records_for_prediction:
                continue

            recent_count = rule_recent_counts.get(rule_id, 0)
            trend_ratio = recent_count / max(total_count / max(self._config.history_window_days, 1), 0.01)

            if trend_ratio < 0.5:
                continue

            dominant_category_str = max(rule_category[rule_id], key=rule_category[rule_id].get)
            dominant_category = ExceptionCategory(dominant_category_str)

            probability = min(trend_ratio * 0.3, 0.95)
            confidence = min(total_count / 50, 0.99)

            if probability >= self._config.prediction_min_probability:
                pred = ExceptionPrediction(
                    prediction_id=str(uuid.uuid4()),
                    rule_id=rule_id,
                    predicted_category=dominant_category,
                    probability=round(probability, 3),
                    expected_severity=self._predict_severity(rule_id, dominant_category),
                    time_horizon_hours=24,
                    confidence=round(confidence, 3),
                    contributing_factors=[
                        f"total_historical:{total_count}",
                        f"recent_trend:{recent_count}",
                        f"dominant_category:{dominant_category_str}",
                    ],
                )
                predictions.append(pred)
                self._predictions[pred.prediction_id] = pred

        predictions.sort(key=lambda p: p.probability, reverse=True)
        logger.info("Generated %d exception predictions", len(predictions))
        return predictions

    def _predict_severity(self, rule_id: str, category: ExceptionCategory) -> ExceptionSeverity:
        """Predict the expected severity of future exceptions for a rule."""
        relevant = [
            r for r in self._records.values()
            if r.rule_id == rule_id and r.category == category
        ]
        if not relevant:
            return ExceptionSeverity.MEDIUM

        scores = [self._SEVERITY_SCORE_MAP.get(r.severity, 1) for r in relevant]
        avg_score = float(np.mean(scores))
        if avg_score >= 3.5:
            return ExceptionSeverity.CRITICAL
        if avg_score >= 2.5:
            return ExceptionSeverity.HIGH
        if avg_score >= 1.5:
            return ExceptionSeverity.MEDIUM
        return ExceptionSeverity.LOW

    # ------------------------------------------------------------------
    # Correlation with Rule Changes
    # ------------------------------------------------------------------

    def correlate_with_rule_changes(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Analyze correlation between rule changes and exception occurrences.

        Returns:
            Dict mapping rule IDs to correlation statistics between
            change events and subsequent exception spikes.
        """
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        change_window = timedelta(hours=48)

        correlations: Dict[str, Any] = {}
        for rule_id, change_timestamps in self._rule_change_log.items():
            recent_changes = [ts for ts in change_timestamps if ts >= cutoff]
            if not recent_changes:
                continue

            rule_exceptions = [
                r for r in self._records.values()
                if r.rule_id == rule_id and r.timestamp >= cutoff
            ]

            exceptions_after_change = 0
            exceptions_before_change = 0
            total_nearby = 0

            for change_ts in recent_changes:
                before = change_ts - change_window
                after = change_ts + change_window
                for exc in rule_exceptions:
                    if before <= exc.timestamp <= after:
                        total_nearby += 1
                        if exc.timestamp >= change_ts:
                            exceptions_after_change += 1
                        else:
                            exceptions_before_change += 1

            if total_nearby > 0 and recent_changes:
                after_ratio = exceptions_after_change / max(total_nearby, 1)
                correlations[rule_id] = {
                    "rule_id": rule_id,
                    "total_changes": len(recent_changes),
                    "total_exceptions_near_changes": total_nearby,
                    "exceptions_after_change": exceptions_after_change,
                    "exceptions_before_change": exceptions_before_change,
                    "post_change_exception_ratio": round(after_ratio, 3),
                    "likely_caused_by_change": after_ratio > 0.7 and total_nearby >= 3,
                }

        return correlations

    # ------------------------------------------------------------------
    # Trends
    # ------------------------------------------------------------------

    def analyze_trends(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Analyze exception trends over time for all dimensions.

        Returns:
            Dict with trend data per exception category, per rule,
            and overall direction assessments.
        """
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        relevant = sorted(
            [r for r in self._records.values() if r.timestamp >= cutoff],
            key=lambda x: x.timestamp,
        )

        if len(relevant) < self._config.trend_data_points_required:
            return {"has_sufficient_data": False}

        by_week: Dict[str, int] = defaultdict(int)
        by_category_weekly: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for record in relevant:
            week_key = record.timestamp.strftime("%Y-W%W")
            by_week[week_key] += 1
            by_category_weekly[record.category.value][week_key] += 1

        weeks = sorted(by_week.keys())
        overall_trend = self._compute_time_series_trend([by_week[w] for w in weeks])

        category_trends: Dict[str, str] = {}
        for cat, weekly_data in by_category_weekly.items():
            cat_weeks = sorted(weekly_data.keys())
            if len(cat_weeks) >= 3:
                cat_values = [weekly_data[w] for w in cat_weeks]
                category_trends[cat] = self._compute_time_series_trend(cat_values)

        return {
            "has_sufficient_data": True,
            "period_days": window,
            "total_records_analyzed": len(relevant),
            "weekly_counts": dict(by_week),
            "overall_trend": overall_trend,
            "category_trends": category_trends,
            "top_increasing_categories": [
                cat for cat, trend in category_trends.items()
                if trend == "increasing"
            ][:5],
            "top_decreasing_categories": [
                cat for cat, trend in category_trends.items()
                if trend == "decreasing"
            ][:5],
        }

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_records_by_rule(self, rule_id: str) -> List[ExceptionRecord]:
        """Get all exception records for a specific rule."""
        return [r for r in self._records.values() if r.rule_id == rule_id]

    def get_records_by_category(self, category: ExceptionCategory) -> List[ExceptionRecord]:
        """Get all exception records of a specific category."""
        return [r for r in self._records.values() if r.category == category]

    def get_records_by_severity(self, severity: ExceptionSeverity) -> List[ExceptionRecord]:
        """Get all exception records of a specific severity level."""
        return [r for r in self._records.values() if r.severity == severity]

    def get_unresolved_records(self) -> List[ExceptionRecord]:
        """Get all unresolved exception records."""
        return [r for r in self._records.values() if not r.resolved]

    def get_most_exception_prone_rules(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """Get rules with the highest exception counts."""
        counts: Dict[str, int] = defaultdict(int)
        for record in self._records.values():
            counts[record.rule_id] += 1
        sorted_rules = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [
            {"rule_id": rule_id, "exception_count": count}
            for rule_id, count in sorted_rules[:top_n]
        ]

    def get_rule_stability_score(self, rule_id: str) -> float:
        """
        Compute a stability score (0-1) for a rule based on its
        exception history. Higher scores indicate more stable rules.
        """
        records = self.get_records_by_rule(rule_id)
        if not records:
            return 1.0

        total = len(records)
        severity_scores = [self._SEVERITY_SCORE_MAP.get(r.severity, 1) for r in records]
        avg_severity = float(np.mean(severity_scores)) if severity_scores else 1.0
        max_severity = max(severity_scores) if severity_scores else 1.0

        stability = 1.0 - (avg_severity / 5.0) * 0.6 - (min(total, 100) / 100) * 0.4
        return round(max(0.0, min(1.0, stability)), 4)

    # ------------------------------------------------------------------
    # Statistics & Export
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about recorded exceptions."""
        by_category: Dict[str, int] = defaultdict(int)
        by_severity: Dict[str, int] = defaultdict(int)
        for record in self._records.values():
            by_category[record.category.value] += 1
            by_severity[record.severity.value] += 1
        return {
            "total_records": len(self._records),
            "records_by_category": dict(by_category),
            "records_by_severity": dict(by_severity),
            "cluster_count": len(self._clusters),
            "prediction_count": len(self._predictions),
            "unresolved_count": len(self.get_unresolved_records()),
            "registered_rules": len(self._rule_cache),
            "most_exception_prone_rules": self.get_most_exception_prone_rules(5),
            "rule_change_log_entries": sum(len(v) for v in self._rule_change_log.values()),
            "config": self._config.to_dict(),
        }

    def export_data(self, max_records: int = 1000) -> Dict[str, Any]:
        """Export all exception data for external consumption."""
        sorted_records = sorted(self._records.values(), key=lambda r: r.timestamp, reverse=True)
        return {
            "config": self._config.to_dict(),
            "records": [r.to_dict() for r in sorted_records[:max_records]],
            "clusters": [c.to_dict() for c in self._clusters.values()],
            "predictions": [p.to_dict() for p in self._predictions.values()],
            "stats": self.get_stats(),
        }

    def reset(self) -> None:
        """Reset all analyzer state."""
        self._records.clear()
        self._clusters.clear()
        self._predictions.clear()
        self._rule_change_log.clear()
        self._rule_cache.clear()
        logger.info("ExceptionPatternAnalyzer reset to initial state")

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_severity_trend(records: List[ExceptionRecord]) -> str:
        """Compute the trend direction of exception severity over time."""
        if len(records) < 4:
            return "stable"
        sorted_records = sorted(records, key=lambda r: r.timestamp)
        mid = len(sorted_records) // 2
        first_avg = np.mean([
            1 if r.severity == ExceptionSeverity.LOW
            else 2 if r.severity == ExceptionSeverity.MEDIUM
            else 3 if r.severity == ExceptionSeverity.HIGH
            else 4
            for r in sorted_records[:mid]
        ]) if mid > 0 else 0
        second_avg = np.mean([
            1 if r.severity == ExceptionSeverity.LOW
            else 2 if r.severity == ExceptionSeverity.MEDIUM
            else 3 if r.severity == ExceptionSeverity.HIGH
            else 4
            for r in sorted_records[mid:]
        ]) if len(sorted_records) > mid else 0
        if second_avg > first_avg + 0.5:
            return "worsening"
        if second_avg < first_avg - 0.5:
            return "improving"
        return "stable"

    @staticmethod
    def _compute_time_series_trend(values: List[int]) -> str:
        """Determine if a time series is increasing, decreasing, or stable."""
        if len(values) < 2:
            return "stable"
        first_half = values[:len(values) // 2]
        second_half = values[len(values) // 2:]
        avg_first = float(np.mean(first_half)) if first_half else 0
        avg_second = float(np.mean(second_half)) if second_half else 0
        if avg_second > avg_first * 1.2:
            return "increasing"
        if avg_second < avg_first * 0.8:
            return "decreasing"
        return "stable"
