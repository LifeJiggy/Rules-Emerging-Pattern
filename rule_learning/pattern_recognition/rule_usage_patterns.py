"""
Pattern recognition for rule usage analysis.

Analyzes usage frequency, context correlations, time-based patterns, trends,
anomalies, and generates usage-based rule recommendations. Supports batch
analysis across rule sets with config-driven parameters.
"""

import logging
import math
import uuid
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RuleSet

logger = logging.getLogger(__name__)


class UsageTrendDirection(str, Enum):
    """Direction of usage trend over time."""

    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    VOLATILE = "volatile"


class UsageAnomalyType(str, Enum):
    """Types of anomalies detected in usage patterns."""

    SPIKE = "spike"
    DROP = "drop"
    SEASONAL_SHIFT = "seasonal_shift"
    NEW_PATTERN = "new_pattern"
    CESSATION = "cessation"


class RuleUsageConfig:
    """Configuration for RuleUsagePatternAnalyzer."""

    def __init__(
        self,
        history_window_days: int = 90,
        min_usage_records: int = 5,
        trend_data_points_required: int = 7,
        anomaly_std_threshold: float = 2.5,
        recommendation_min_confidence: float = 0.3,
        peak_hour_count: int = 3,
        seasonal_period_days: int = 7,
        enable_anomaly_detection: bool = True,
        enable_recommendations: bool = True,
        enable_batch_analysis: bool = True,
        context_correlation_min_occurrences: int = 3,
        export_max_records_per_rule: int = 1000,
    ) -> None:
        self.history_window_days = history_window_days
        self.min_usage_records = min_usage_records
        self.trend_data_points_required = trend_data_points_required
        self.anomaly_std_threshold = anomaly_std_threshold
        self.recommendation_min_confidence = recommendation_min_confidence
        self.peak_hour_count = peak_hour_count
        self.seasonal_period_days = seasonal_period_days
        self.enable_anomaly_detection = enable_anomaly_detection
        self.enable_recommendations = enable_recommendations
        self.enable_batch_analysis = enable_batch_analysis
        self.context_correlation_min_occurrences = context_correlation_min_occurrences
        self.export_max_records_per_rule = export_max_records_per_rule

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class ContextCorrelation:
    """Correlation between a context attribute and rule usage."""

    def __init__(
        self,
        context_key: str,
        context_value: str,
        rule_id: str,
        occurrence_count: int,
        total_occurrences: int,
        confidence: float,
    ) -> None:
        self.context_key = context_key
        self.context_value = context_value
        self.rule_id = rule_id
        self.occurrence_count = occurrence_count
        self.total_occurrences = total_occurrences
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "context_key": self.context_key,
            "context_value": self.context_value,
            "rule_id": self.rule_id,
            "occurrence_count": self.occurrence_count,
            "total_occurrences": self.total_occurrences,
            "confidence": round(self.confidence, 4),
        }


class TimeBasedPattern:
    """Time-based usage pattern for a rule."""

    def __init__(
        self,
        rule_id: str,
        hourly_distribution: Dict[int, int],
        daily_distribution: Dict[str, int],
        weekly_distribution: Dict[int, int],
        peak_hours: List[int],
        peak_days: List[str],
        seasonal_profile: str,
    ) -> None:
        self.rule_id = rule_id
        self.hourly_distribution = hourly_distribution
        self.daily_distribution = daily_distribution
        self.weekly_distribution = weekly_distribution
        self.peak_hours = peak_hours
        self.peak_days = peak_days
        self.seasonal_profile = seasonal_profile

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "rule_id": self.rule_id,
            "hourly_distribution": {str(k): v for k, v in self.hourly_distribution.items()},
            "daily_distribution": self.daily_distribution,
            "weekly_distribution": {str(k): v for k, v in self.weekly_distribution.items()},
            "peak_hours": self.peak_hours,
            "peak_days": self.peak_days,
            "seasonal_profile": self.seasonal_profile,
        }


class UsageRecommendation:
    """Recommendation based on usage pattern analysis."""

    def __init__(
        self,
        recommendation_id: str,
        rule_id: str,
        recommendation_type: str,
        description: str,
        confidence: float,
        reasoning: List[str],
        suggested_action: str,
    ) -> None:
        self.recommendation_id = recommendation_id
        self.rule_id = rule_id
        self.recommendation_type = recommendation_type
        self.description = description
        self.confidence = confidence
        self.reasoning = reasoning
        self.suggested_action = suggested_action

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "recommendation_id": self.recommendation_id,
            "rule_id": self.rule_id,
            "recommendation_type": self.recommendation_type,
            "description": self.description,
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
            "suggested_action": self.suggested_action,
        }


class RuleUsagePatternAnalyzer:
    """
    Analyze patterns in rule usage across dimensions.

    Capabilities:
    - Usage frequency analysis (per-rule, per-context, per-time-period)
    - Context correlation (which contexts trigger which rules)
    - Time-based patterns (hourly, daily, weekly, seasonal)
    - Usage trend detection (increasing, decreasing, stable, volatile)
    - Anomaly detection in usage patterns (spikes, drops, shifts)
    - Usage-based rule recommendations
    - Batch analysis across rule sets
    - Config-driven parameters
    - Full statistics and export
    """

    _CONTEXT_KEYS = frozenset({
        "domain", "user_role", "content_type", "language",
        "organization", "project", "business_process",
    })

    def __init__(self, config: Optional[RuleUsageConfig] = None) -> None:
        self._config = config or RuleUsageConfig()
        self._usage_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._recommendations: Dict[str, UsageRecommendation] = {}
        self._rule_cache: Dict[str, Rule] = {}
        self._pattern_cache: Dict[str, Any] = {}
        self._time_based_patterns: Dict[str, TimeBasedPattern] = {}
        self._context_correlations: Dict[str, List[ContextCorrelation]] = {}
        logger.info("RuleUsagePatternAnalyzer initialized with config: %s", self._config.to_dict())

    # ------------------------------------------------------------------
    # Registration & Data Ingestion
    # ------------------------------------------------------------------

    def register_rule(self, rule: Rule) -> None:
        """Register a rule for usage analysis."""
        self._rule_cache[rule.id] = rule
        logger.debug("Registered rule: %s", rule.id)

    def register_rules(self, rules: Sequence[Rule]) -> None:
        """Register multiple rules at once."""
        for rule in rules:
            self.register_rule(rule)

    def record_usage(
        self,
        rule_id: str,
        context: Dict[str, Any],
        result: Dict[str, Any],
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Record a rule usage event.

        Args:
            rule_id: ID of the rule used.
            context: Evaluation context dictionary.
            result: Result dictionary with keys like triggered, blocked, score.
            timestamp: Event timestamp (defaults to now).
        """
        usage_record: Dict[str, Any] = {
            "timestamp": timestamp or datetime.utcnow(),
            "rule_id": rule_id,
            "context": context,
            "triggered": result.get("triggered", False),
            "blocked": result.get("blocked", False),
            "score": result.get("score", 0.0),
            "processing_time_ms": result.get("processing_time_ms", 0),
        }
        self._usage_history[rule_id].append(usage_record)

    def record_usage_batch(
        self,
        records: Sequence[Dict[str, Any]],
    ) -> None:
        """Record multiple usage events at once."""
        for record in records:
            rule_id = record.get("rule_id", "unknown")
            context = record.get("context", {})
            result = {
                "triggered": record.get("triggered", False),
                "blocked": record.get("blocked", False),
                "score": record.get("score", 0.0),
                "processing_time_ms": record.get("processing_time_ms", 0),
            }
            timestamp = record.get("timestamp")
            self.record_usage(rule_id, context, result, timestamp)

    # ------------------------------------------------------------------
    # Usage Frequency Analysis
    # ------------------------------------------------------------------

    def analyze_frequency(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Analyze usage frequency across all registered rules.

        Returns:
            Dict with per-rule frequency stats, overall metrics,
            and top/bottom rule lists.
        """
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)

        per_rule_total: Dict[str, int] = defaultdict(int)
        per_rule_triggered: Dict[str, int] = defaultdict(int)
        per_rule_blocked: Dict[str, int] = defaultdict(int)

        for rule_id, history in self._usage_history.items():
            for usage in history:
                if usage["timestamp"] >= cutoff:
                    per_rule_total[rule_id] += 1
                    if usage.get("triggered"):
                        per_rule_triggered[rule_id] += 1
                    if usage.get("blocked"):
                        per_rule_blocked[rule_id] += 1

        if not per_rule_total:
            return {"total_usage": 0, "active_rules": 0, "per_rule": {}}

        total_usage = sum(per_rule_total.values())
        active_rules = len(per_rule_total)

        per_rule_stats: Dict[str, Dict[str, Any]] = {}
        for rule_id in set(
            list(per_rule_total.keys())
            + list(per_rule_triggered.keys())
            + list(per_rule_blocked.keys())
        ):
            total = per_rule_total.get(rule_id, 0)
            triggered = per_rule_triggered.get(rule_id, 0)
            blocked = per_rule_blocked.get(rule_id, 0)
            per_rule_stats[rule_id] = {
                "total_uses": total,
                "frequency_per_day": round(total / max(window, 1), 4),
                "triggered_count": triggered,
                "trigger_rate": round(triggered / max(total, 1), 4),
                "blocked_count": blocked,
                "block_rate": round(blocked / max(total, 1), 4),
            }

        sorted_by_freq = sorted(per_rule_stats.items(), key=lambda x: x[1]["frequency_per_day"], reverse=True)
        return {
            "analyzed_period_days": window,
            "total_usage": total_usage,
            "active_rules": active_rules,
            "average_usage_per_rule": round(total_usage / max(active_rules, 1), 2),
            "per_rule": per_rule_stats,
            "top_10_most_used": [{"rule_id": r, **s} for r, s in sorted_by_freq[:10]],
            "bottom_10_least_used": [{"rule_id": r, **s} for r, s in sorted_by_freq[-10:]],
            "most_triggered": max(per_rule_triggered.items(), key=lambda x: x[1]) if per_rule_triggered else None,
        }

    def get_rule_usage(self, rule_id: str, days: Optional[int] = None) -> Dict[str, Any]:
        """Get detailed usage statistics for a specific rule."""
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        history = [
            u for u in self._usage_history.get(rule_id, [])
            if u["timestamp"] >= cutoff
        ]

        if not history:
            return {
                "rule_id": rule_id,
                "total_uses": 0,
                "frequency_per_day": 0.0,
                "trigger_rate": 0.0,
                "block_rate": 0.0,
                "average_score": 0.0,
                "average_processing_time_ms": 0.0,
            }

        total = len(history)
        triggered = sum(1 for u in history if u.get("triggered"))
        blocked = sum(1 for u in history if u.get("blocked"))
        scores = [u.get("score", 0.0) for u in history]
        proctimes = [u.get("processing_time_ms", 0) for u in history]

        return {
            "rule_id": rule_id,
            "total_uses": total,
            "frequency_per_day": round(total / max(window, 1), 4),
            "triggered_count": triggered,
            "trigger_rate": round(triggered / max(total, 1), 4),
            "blocked_count": blocked,
            "block_rate": round(blocked / max(total, 1), 4),
            "average_score": round(float(np.mean(scores)), 4) if scores else 0.0,
            "average_processing_time_ms": round(float(np.mean(proctimes)), 2) if proctimes else 0.0,
            "median_score": round(float(np.median(scores)), 4) if scores else 0.0,
        }

    # ------------------------------------------------------------------
    # Context Correlation
    # ------------------------------------------------------------------

    def analyze_context_correlation(self, days: Optional[int] = None) -> Dict[str, List[ContextCorrelation]]:
        """
        Analyze which contexts are correlated with which rule usages.

        Returns:
            Dict mapping rule IDs to lists of ContextCorrelation objects.
        """
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)

        context_occurrences: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )

        for rule_id, history in self._usage_history.items():
            for usage in history:
                if usage["timestamp"] < cutoff:
                    continue
                ctx = usage.get("context", {})
                for key in self._CONTEXT_KEYS:
                    value = ctx.get(key)
                    if value is not None:
                        context_occurrences[rule_id][key][str(value)] += 1

        results: Dict[str, List[ContextCorrelation]] = {}
        for rule_id, key_values in context_occurrences.items():
            total_uses = len([
                u for u in self._usage_history.get(rule_id, [])
                if u["timestamp"] >= cutoff
            ])
            correlations: List[ContextCorrelation] = []
            for key, value_counts in key_values.items():
                for value, count in value_counts.items():
                    if count >= self._config.context_correlation_min_occurrences:
                        confidence = count / max(total_uses, 1)
                        correlations.append(ContextCorrelation(
                            context_key=key,
                            context_value=value,
                            rule_id=rule_id,
                            occurrence_count=count,
                            total_occurrences=total_uses,
                            confidence=confidence,
                        ))
            if correlations:
                correlations.sort(key=lambda c: c.confidence, reverse=True)
                results[rule_id] = correlations

        self._context_correlations = results
        return results

    def get_context_triggers(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Given a context, predict which rules are likely to trigger.

        Returns:
            List of {rule_id, probability} sorted by likelihood.
        """
        scores: Dict[str, float] = defaultdict(float)
        for rule_id, correlations in self._context_correlations.items():
            match_score = 0.0
            total_matches = 0
            for corr in correlations:
                ctx_value = context.get(corr.context_key)
                if ctx_value is not None and str(ctx_value) == corr.context_value:
                    match_score += corr.confidence
                    total_matches += 1
            if total_matches > 0:
                scores[rule_id] = match_score / total_matches

        return [
            {"rule_id": rule_id, "probability": round(score, 4)}
            for rule_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True)
        ]

    # ------------------------------------------------------------------
    # Time-Based Patterns
    # ------------------------------------------------------------------

    def analyze_time_patterns(self, rule_id: str, days: Optional[int] = None) -> TimeBasedPattern:
        """
        Analyze time-based usage patterns for a specific rule.

        Returns a TimeBasedPattern with hourly, daily, weekly distributions
        and identified peak times.
        """
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        history = [
            u for u in self._usage_history.get(rule_id, [])
            if u["timestamp"] >= cutoff
        ]

        hourly: Dict[int, int] = defaultdict(int)
        daily: Dict[str, int] = defaultdict(int)
        weekly: Dict[int, int] = defaultdict(int)

        for usage in history:
            ts = usage["timestamp"]
            hourly[ts.hour] += 1
            daily[ts.strftime("%A")] += 1
            weekly[ts.weekday()] += 1

        peak_hours = sorted(hourly, key=hourly.get, reverse=True)[:self._config.peak_hour_count]
        peak_days = sorted(daily, key=daily.get, reverse=True)[:3]

        seasonal_profile = self._classify_seasonal_profile(hourly, daily)

        pattern = TimeBasedPattern(
            rule_id=rule_id,
            hourly_distribution=dict(hourly),
            daily_distribution=dict(daily),
            weekly_distribution=dict(weekly),
            peak_hours=peak_hours,
            peak_days=peak_days,
            seasonal_profile=seasonal_profile,
        )
        self._time_based_patterns[rule_id] = pattern
        return pattern

    def analyze_all_time_patterns(self, days: Optional[int] = None) -> Dict[str, TimeBasedPattern]:
        """Analyze time-based patterns for all registered rules."""
        for rule_id in list(self._usage_history.keys()):
            self.analyze_time_patterns(rule_id, days)
        return dict(self._time_based_patterns)

    @staticmethod
    def _classify_seasonal_profile(
        hourly: Dict[int, int],
        daily: Dict[str, int],
    ) -> str:
        """Classify the seasonal profile of usage patterns."""
        work_hours = sum(hourly.get(h, 0) for h in range(8, 18))
        off_hours = sum(hourly.get(h, 0) for h in list(range(0, 8)) + list(range(18, 24)))
        total = work_hours + off_hours
        if total == 0:
            return "unknown"

        work_ratio = work_hours / total
        if work_ratio > 0.8:
            return "business_hours"
        if work_ratio < 0.2:
            return "after_hours"
        if 0.4 <= work_ratio <= 0.6:
            return "balanced"

        weekend = sum(daily.get(d, 0) for d in ["Saturday", "Sunday"])
        weekday = sum(daily.get(d, 0) for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        total_days = weekend + weekday
        if total_days > 0:
            weekend_ratio = weekend / total_days
            if weekend_ratio > 0.6:
                return "weekend_heavy"
            if weekend_ratio > 0.3:
                return "mixed_weekend"

        return "business_hours"

    # ------------------------------------------------------------------
    # Trend Detection
    # ------------------------------------------------------------------

    def detect_trend(self, rule_id: str, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Detect usage trend direction for a specific rule.

        Returns:
            Dict with trend direction, velocity, and confidence.
        """
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        history = sorted(
            [u for u in self._usage_history.get(rule_id, []) if u["timestamp"] >= cutoff],
            key=lambda x: x["timestamp"],
        )

        if len(history) < self._config.trend_data_points_required:
            return {"trend": UsageTrendDirection.STABLE.value, "velocity": 0.0, "confidence": 0.0}

        daily_counts: Dict[str, int] = defaultdict(int)
        for usage in history:
            day_key = usage["timestamp"].strftime("%Y-%m-%d")
            daily_counts[day_key] += 1

        sorted_days = sorted(daily_counts.keys())
        values = [daily_counts[d] for d in sorted_days]

        if len(values) < 3:
            return {"trend": UsageTrendDirection.STABLE.value, "velocity": 0.0, "confidence": 0.0}

        x = np.arange(len(values))
        y = np.array(values, dtype=float)
        if np.std(y) == 0:
            return {"trend": UsageTrendDirection.STABLE.value, "velocity": 0.0, "confidence": 1.0}

        coeffs = np.polyfit(x, y, 1)
        slope = coeffs[0]

        mean_y = float(np.mean(y))
        velocity = slope / max(mean_y, 0.01)

        residuals = y - (coeffs[0] * x + coeffs[1])
        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((y - mean_y) ** 2)
        r_squared = 1.0 - (ss_res / max(ss_tot, 0.001))

        if abs(velocity) < 0.05:
            direction = UsageTrendDirection.STABLE
        elif velocity > 0:
            direction = UsageTrendDirection.INCREASING
        else:
            direction = UsageTrendDirection.DECREASING

        volatility = float(np.std(values)) / max(mean_y, 0.01)
        if volatility > 1.5:
            direction = UsageTrendDirection.VOLATILE

        return {
            "trend": direction.value,
            "velocity": round(velocity, 4),
            "slope": round(float(slope), 4),
            "r_squared": round(float(r_squared), 4),
            "mean_daily_usage": round(mean_y, 2),
            "volatility": round(volatility, 4),
            "confidence": round(min(r_squared * 2, 1.0), 4),
        }

    def detect_all_trends(self, days: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
        """Detect usage trends for all registered rules."""
        return {
            rule_id: self.detect_trend(rule_id, days)
            for rule_id in self._usage_history
        }

    # ------------------------------------------------------------------
    # Anomaly Detection
    # ------------------------------------------------------------------

    def detect_anomalies(self, rule_id: str, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Detect anomalous usage patterns for a specific rule.

        Returns:
            Dict with detected anomalies, their types, and severity.
        """
        if not self._config.enable_anomaly_detection:
            return {"anomalies": [], "has_anomalies": False}

        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        history = [
            u for u in self._usage_history.get(rule_id, []) if u["timestamp"] >= cutoff
        ]

        if len(history) < self._config.trend_data_points_required:
            return {"anomalies": [], "has_anomalies": False}

        daily_counts: Dict[str, int] = defaultdict(int)
        for usage in history:
            daily_counts[usage["timestamp"].strftime("%Y-%m-%d")] += 1

        sorted_days = sorted(daily_counts.keys())
        values = np.array([daily_counts[d] for d in sorted_days], dtype=float)

        if len(values) < 5:
            return {"anomalies": [], "has_anomalies": False}

        mean = float(np.mean(values))
        std = float(np.std(values)) or 1.0
        threshold = self._config.anomaly_std_threshold * std

        detected: List[Dict[str, Any]] = []
        for i, day in enumerate(sorted_days):
            deviation = values[i] - mean
            if abs(deviation) > threshold:
                anomaly_type = UsageAnomalyType.SPIKE if deviation > 0 else UsageAnomalyType.DROP
                detected.append({
                    "date": day,
                    "type": anomaly_type.value,
                    "actual_count": int(values[i]),
                    "expected_count": round(mean, 2),
                    "deviation": round(deviation, 2),
                    "severity": round(abs(deviation) / max(std, 0.01), 2),
                })

        return {
            "rule_id": rule_id,
            "anomalies": detected,
            "has_anomalies": len(detected) > 0,
            "baseline_mean": round(mean, 2),
            "baseline_std": round(std, 2),
            "threshold": round(threshold, 2),
        }

    def detect_all_anomalies(self, days: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
        """Detect usage anomalies for all registered rules."""
        return {
            rule_id: self.detect_anomalies(rule_id, days)
            for rule_id in self._usage_history
        }

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def generate_recommendations(self, days: Optional[int] = None) -> List[UsageRecommendation]:
        """
        Generate usage-based rule recommendations.

        Recommendations include:
        - Rules that may need optimization (high usage, high processing time)
        - Rules that may be candidates for deactivation (very low usage)
        - Rules that may benefit from caching (steady high usage)
        - Context-specific rule suggestions
        """
        if not self._config.enable_recommendations:
            return []

        recommendations: List[UsageRecommendation] = []

        for rule_id, history in self._usage_history.items():
            usage_stats = self.get_rule_usage(rule_id, days)
            total = usage_stats["total_uses"]

            if total < self._config.min_usage_records:
                continue

            avg_time = usage_stats.get("average_processing_time_ms", 0)
            freq = usage_stats.get("frequency_per_day", 0)
            trigger_rate = usage_stats.get("trigger_rate", 0)

            if avg_time > 500 and freq > 10:
                rec = UsageRecommendation(
                    recommendation_id=str(uuid.uuid4()),
                    rule_id=rule_id,
                    recommendation_type="optimization",
                    description=f"Rule {rule_id} has high processing time ({avg_time:.0f}ms) with high usage ({freq:.1f}/day)",
                    confidence=min(avg_time / 1000, 0.95),
                    reasoning=[
                        f"Average processing time: {avg_time:.0f}ms",
                        f"Usage frequency: {freq:.2f}/day",
                        "High-usage + high-latency rules are optimization candidates",
                    ],
                    suggested_action="Review rule patterns for efficiency, consider caching or simplifying regex",
                )
                recommendations.append(rec)

            if freq < 0.1 and total >= self._config.min_usage_records:
                rec = UsageRecommendation(
                    recommendation_id=str(uuid.uuid4()),
                    rule_id=rule_id,
                    recommendation_type="deactivation_candidate",
                    description=f"Rule {rule_id} has very low usage ({freq:.4f}/day)",
                    confidence=min(1.0 - freq, 0.8),
                    reasoning=[
                        f"Usage frequency: {freq:.4f}/day",
                        f"Total uses in window: {total}",
                        "Low-usage rules may be candidates for deactivation or review",
                    ],
                    suggested_action="Review if rule is still needed, consider deactivating or merging",
                )
                recommendations.append(rec)

            if trigger_rate > 0.9 and freq > 20:
                rec = UsageRecommendation(
                    recommendation_id=str(uuid.uuid4()),
                    rule_id=rule_id,
                    recommendation_type="caching",
                    description=f"Rule {rule_id} has high trigger rate ({trigger_rate:.0%}) with steady usage",
                    confidence=min(trigger_rate, 0.9),
                    reasoning=[
                        f"Trigger rate: {trigger_rate:.0%}",
                        f"Usage frequency: {freq:.2f}/day",
                        "Consistently triggered rules benefit from result caching",
                    ],
                    suggested_action="Consider enabling or extending cache TTL for this rule",
                )
                recommendations.append(rec)

            trend_data = self.detect_trend(rule_id, days)
            if trend_data.get("trend") == UsageTrendDirection.INCREASING.value and trend_data.get("velocity", 0) > 0.5:
                rec = UsageRecommendation(
                    recommendation_id=str(uuid.uuid4()),
                    rule_id=rule_id,
                    recommendation_type="scaling",
                    description=f"Rule {rule_id} usage is rapidly increasing (velocity={trend_data['velocity']:.2f})",
                    confidence=min(abs(trend_data["velocity"]), 0.95),
                    reasoning=[
                        f"Trend velocity: {trend_data['velocity']:.2f}",
                        f"R-squared: {trend_data['r_squared']:.2f}",
                        "Rapidly increasing usage may require scaling attention",
                    ],
                    suggested_action="Monitor rule performance, consider pre-allocation of resources",
                )
                recommendations.append(rec)

        recommendations.sort(key=lambda r: r.confidence, reverse=True)
        for rec in recommendations:
            self._recommendations[rec.recommendation_id] = rec

        logger.info("Generated %d usage recommendations", len(recommendations))
        return recommendations

    # ------------------------------------------------------------------
    # Batch Analysis
    # ------------------------------------------------------------------

    def analyze_rule_set(self, rule_set: RuleSet, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Perform batch analysis across all rules in a RuleSet.

        Returns:
            Dict with aggregate metrics, per-rule breakdown, and insights.
        """
        for rule in rule_set.rules:
            self.register_rule(rule)

        frequency = self.analyze_frequency(days)
        trends = self.detect_all_trends(days)
        patterns = self.analyze_all_time_patterns(days)
        anomalies = self.detect_all_anomalies(days)
        recommendations = self.generate_recommendations(days)

        active_rule_count = len([
            r for r in rule_set.rules if r.status.value == "active"
        ])
        usage_rule_count = len(frequency.get("per_rule", {}))

        return {
            "rule_set_id": rule_set.id,
            "rule_set_name": rule_set.name,
            "analyzed_period_days": days or self._config.history_window_days,
            "total_rules": len(rule_set.rules),
            "active_rules": active_rule_count,
            "rules_with_usage": usage_rule_count,
            "usage_coverage": round(usage_rule_count / max(active_rule_count, 1), 4),
            "frequency": frequency,
            "trends": trends,
            "time_patterns": {
                rid: p.to_dict() for rid, p in patterns.items()
            },
            "anomalies": {
                rid: a for rid, a in anomalies.items() if a.get("has_anomalies")
            },
            "recommendations": [r.to_dict() for r in recommendations],
            "insights": self._generate_insights(frequency, trends, patterns),
        }

    @staticmethod
    def _generate_insights(
        frequency: Dict[str, Any],
        trends: Dict[str, Dict[str, Any]],
        patterns: Dict[str, TimeBasedPattern],
    ) -> List[str]:
        """Generate human-readable insights from analysis results."""
        insights: List[str] = []
        per_rule = frequency.get("per_rule", {})
        if per_rule:
            most_used = max(per_rule.items(), key=lambda x: x[1]["total_uses"])
            insights.append(f"Most used rule: {most_used[0]} ({most_used[1]['total_uses']} uses)")

        increasing = [
            rid for rid, t in trends.items()
            if t.get("trend") == UsageTrendDirection.INCREASING.value
        ]
        if increasing:
            insights.append(f"Rules with increasing usage trend: {', '.join(increasing[:5])}")

        decreasing = [
            rid for rid, t in trends.items()
            if t.get("trend") == UsageTrendDirection.DECREASING.value
        ]
        if decreasing:
            insights.append(f"Rules with decreasing usage trend: {', '.join(decreasing[:5])}")

        return insights

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_underutilized_rules(self, threshold: float = 1.0, days: Optional[int] = None) -> List[str]:
        """Get rules with usage frequency below threshold (uses per day)."""
        window = days if days is not None else self._config.history_window_days
        underutilized: List[str] = []
        for rule_id, history in self._usage_history.items():
            cutoff = datetime.utcnow() - timedelta(days=window)
            recent = [u for u in history if u["timestamp"] >= cutoff]
            freq = len(recent) / max(window, 1)
            if freq < threshold:
                underutilized.append(rule_id)
        return underutilized

    def get_overutilized_rules(self, threshold: float = 100.0, days: Optional[int] = None) -> List[str]:
        """Get rules with usage frequency above threshold (uses per day)."""
        window = days if days is not None else self._config.history_window_days
        overutilized: List[str] = []
        for rule_id, history in self._usage_history.items():
            cutoff = datetime.utcnow() - timedelta(days=window)
            recent = [u for u in history if u["timestamp"] >= cutoff]
            freq = len(recent) / max(window, 1)
            if freq > threshold:
                overutilized.append(rule_id)
        return overutilized

    def get_inactive_rules(self, days: Optional[int] = None) -> List[str]:
        """Get rules with no usage in the specified window."""
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        return [
            rule_id for rule_id, history in self._usage_history.items()
            if not any(u["timestamp"] >= cutoff for u in history)
        ]

    def get_peak_usage_times(self, rule_id: str, top_n: int = 3) -> List[str]:
        """Get peak usage hours for a rule."""
        pattern = self._time_based_patterns.get(rule_id)
        if pattern is None:
            pattern = self.analyze_time_patterns(rule_id)
        return [f"{h}:00" for h in pattern.peak_hours[:top_n]]

    # ------------------------------------------------------------------
    # Statistics & Export
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about usage patterns."""
        total_records = sum(len(h) for h in self._usage_history.values())
        unique_rules = len(self._usage_history)
        pattern_count = len(self._time_based_patterns)
        recommendation_count = len(self._recommendations)

        return {
            "total_usage_records": total_records,
            "unique_rules_tracked": unique_rules,
            "average_records_per_rule": round(total_records / max(unique_rules, 1), 2),
            "time_patterns_computed": pattern_count,
            "recommendations_generated": recommendation_count,
            "context_correlations_computed": sum(len(v) for v in self._context_correlations.values()),
            "registered_rules": len(self._rule_cache),
            "config": self._config.to_dict(),
        }

    def export_data(self) -> Dict[str, Any]:
        """Export all usage data for external consumption."""
        max_records = self._config.export_max_records_per_rule
        return {
            "config": self._config.to_dict(),
            "usage_history": {
                rule_id: history[-max_records:]
                for rule_id, history in self._usage_history.items()
            },
            "time_patterns": {
                rid: p.to_dict() for rid, p in self._time_based_patterns.items()
            },
            "context_correlations": {
                rid: [c.to_dict() for c in corrs]
                for rid, corrs in self._context_correlations.items()
            },
            "recommendations": [r.to_dict() for r in self._recommendations.values()],
            "stats": self.get_stats(),
        }

    def reset(self) -> None:
        """Reset all analyzer state."""
        self._usage_history.clear()
        self._recommendations.clear()
        self._rule_cache.clear()
        self._pattern_cache.clear()
        self._time_based_patterns.clear()
        self._context_correlations.clear()
        logger.info("RuleUsagePatternAnalyzer reset to initial state")
