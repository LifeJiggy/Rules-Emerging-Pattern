"""
Correlation detection between rule firings and rule attributes.

Detects correlations between rule firings using co-occurrence analysis,
Pearson/Spearman correlation for numeric metrics, mutual information for
categorical attributes, cross-correlation with time lag, correlation clustering,
and causal inference hints based on temporal precedence.
"""

import logging
import math
import uuid
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from scipy.stats import pearsonr, spearmanr, entropy

from rules_emerging_pattern.models.rule import Rule, RuleType, RuleSeverity, RuleTier

logger = logging.getLogger(__name__)


class CorrelationMethod(str, Enum):
    """Methods used for correlation detection."""

    PEARSON = "pearson"
    SPEARMAN = "spearman"
    MUTUAL_INFORMATION = "mutual_information"
    CO_OCCURRENCE = "co_occurrence"
    CROSS_CORRELATION = "cross_correlation"
    JACCARD = "jaccard"


class CorrelationStrength(str, Enum):
    """Descriptive strength of a detected correlation."""

    VERY_STRONG = "very_strong"
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NEGLIGIBLE = "negligible"


class CorrelationDirection(str, Enum):
    """Direction of correlation between variables."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NONE = "none"


class CorrelationConfig:
    """Configuration for CorrelationDetector."""

    def __init__(
        self,
        min_data_points: int = 10,
        pearson_significance: float = 0.05,
        spearman_significance: float = 0.05,
        mutual_information_normalized: bool = True,
        co_occurrence_min_joint: int = 3,
        co_occurrence_min_expected: float = 0.5,
        cross_correlation_max_lag: int = 10,
        cross_correlation_min_score: float = 0.3,
        jaccard_threshold: float = 0.3,
        cluster_correlation_threshold: float = 0.6,
        min_cluster_size: int = 2,
        causal_min_temporal_precedence: float = 0.6,
        enable_pearson: bool = True,
        enable_spearman: bool = True,
        enable_mutual_information: bool = True,
        enable_co_occurrence: bool = True,
        enable_cross_correlation: bool = True,
        enable_clustering: bool = True,
        enable_causal_inference: bool = True,
    ) -> None:
        self.min_data_points = min_data_points
        self.pearson_significance = pearson_significance
        self.spearman_significance = spearman_significance
        self.mutual_information_normalized = mutual_information_normalized
        self.co_occurrence_min_joint = co_occurrence_min_joint
        self.co_occurrence_min_expected = co_occurrence_min_expected
        self.cross_correlation_max_lag = cross_correlation_max_lag
        self.cross_correlation_min_score = cross_correlation_min_score
        self.jaccard_threshold = jaccard_threshold
        self.cluster_correlation_threshold = cluster_correlation_threshold
        self.min_cluster_size = min_cluster_size
        self.causal_min_temporal_precedence = causal_min_temporal_precedence
        self.enable_pearson = enable_pearson
        self.enable_spearman = enable_spearman
        self.enable_mutual_information = enable_mutual_information
        self.enable_co_occurrence = enable_co_occurrence
        self.enable_cross_correlation = enable_cross_correlation
        self.enable_clustering = enable_clustering
        self.enable_causal_inference = enable_causal_inference

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class CorrelationResult:
    """Result of a correlation analysis between two entities."""

    def __init__(
        self,
        correlation_id: str,
        entity_a: str,
        entity_b: str,
        method: CorrelationMethod,
        coefficient: float,
        strength: CorrelationStrength,
        direction: CorrelationDirection,
        p_value: float,
        significant: bool,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.correlation_id = correlation_id
        self.entity_a = entity_a
        self.entity_b = entity_b
        self.method = method
        self.coefficient = coefficient
        self.strength = strength
        self.direction = direction
        self.p_value = p_value
        self.significant = significant
        self.description = description
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "correlation_id": self.correlation_id,
            "entity_a": self.entity_a,
            "entity_b": self.entity_b,
            "method": self.method.value,
            "coefficient": round(self.coefficient, 4),
            "strength": self.strength.value,
            "direction": self.direction.value,
            "p_value": round(self.p_value, 6),
            "significant": self.significant,
            "description": self.description,
            "metadata": self.metadata,
        }


class CorrelationCluster:
    """A cluster of correlated rules."""

    def __init__(
        self,
        cluster_id: str,
        rule_ids: List[str],
        average_correlation: float,
        primary_method: CorrelationMethod,
        dominant_direction: str,
        internal_edges: List[Dict[str, Any]],
        description: str,
    ) -> None:
        self.cluster_id = cluster_id
        self.rule_ids = rule_ids
        self.average_correlation = average_correlation
        self.primary_method = primary_method
        self.dominant_direction = dominant_direction
        self.internal_edges = internal_edges
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "cluster_id": self.cluster_id,
            "rule_ids": self.rule_ids,
            "average_correlation": round(self.average_correlation, 4),
            "primary_method": self.primary_method.value,
            "dominant_direction": self.dominant_direction,
            "internal_edge_count": len(self.internal_edges),
            "internal_edges": self.internal_edges[:10],
            "description": self.description,
        }


class CausalHint:
    """
    Causal inference hint based on temporal precedence.

    Suggests that entity_a may have a causal influence on entity_b
    when entity_a consistently precedes entity_b in time.
    """

    def __init__(
        self,
        hint_id: str,
        cause_entity: str,
        effect_entity: str,
        temporal_precedence_score: float,
        confidence: float,
        avg_lag: timedelta,
        evidence_count: int,
        description: str,
    ) -> None:
        self.hint_id = hint_id
        self.cause_entity = cause_entity
        self.effect_entity = effect_entity
        self.temporal_precedence_score = temporal_precedence_score
        self.confidence = confidence
        self.avg_lag = avg_lag
        self.evidence_count = evidence_count
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "hint_id": self.hint_id,
            "cause_entity": self.cause_entity,
            "effect_entity": self.effect_entity,
            "temporal_precedence_score": round(self.temporal_precedence_score, 4),
            "confidence": round(self.confidence, 4),
            "avg_lag_seconds": self.avg_lag.total_seconds(),
            "evidence_count": self.evidence_count,
            "description": self.description,
        }


class CorrelationDetector:
    """
    Detects correlations between rule firings and rule attributes.

    Capabilities:
    - Co-occurrence analysis between rule firing events
    - Pearson/Spearman correlation for numeric rule metrics
    - Mutual information for categorical rule attributes
    - Cross-correlation with time lag between rule firings
    - Correlation clustering (groups of correlated rules)
    - Causal inference hints (temporal precedence)
    - Config-driven thresholds and methods
    """

    _STRENGTH_BOUNDS = [
        (0.9, 1.0, CorrelationStrength.VERY_STRONG),
        (0.7, 0.9, CorrelationStrength.STRONG),
        (0.5, 0.7, CorrelationStrength.MODERATE),
        (0.3, 0.5, CorrelationStrength.WEAK),
        (0.0, 0.3, CorrelationStrength.NEGLIGIBLE),
    ]

    def __init__(self, config: Optional[CorrelationConfig] = None) -> None:
        self._config = config or CorrelationConfig()
        self._firing_log: Dict[str, List[datetime]] = defaultdict(list)
        self._numeric_metrics: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
        self._categorical_attributes: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        self._correlations: Dict[str, CorrelationResult] = {}
        self._clusters: Dict[str, CorrelationCluster] = {}
        self._causal_hints: Dict[str, CausalHint] = {}
        logger.info("CorrelationDetector initialized with config: %s", self._config.to_dict())

    # ------------------------------------------------------------------
    # Data Ingestion
    # ------------------------------------------------------------------

    def record_firing(self, rule_id: str, timestamp: Optional[datetime] = None) -> None:
        """Record a rule firing event."""
        self._firing_log[rule_id].append(timestamp or datetime.utcnow())

    def record_firings(self, rule_id: str, timestamps: List[datetime]) -> None:
        """Record multiple firing events at once."""
        self._firing_log[rule_id].extend(timestamps)

    def record_numeric_metric(
        self,
        rule_id: str,
        metric_name: str,
        value: float,
    ) -> None:
        """Record a numeric metric value for a rule."""
        self._numeric_metrics[rule_id][metric_name].append(value)

    def record_categorical_attribute(
        self,
        rule_id: str,
        attribute_name: str,
        value: str,
    ) -> None:
        """Record a categorical attribute value for a rule."""
        self._categorical_attributes[rule_id][attribute_name].append(value)

    # ------------------------------------------------------------------
    # Co-occurrence Analysis
    # ------------------------------------------------------------------

    def analyze_co_occurrence(
        self,
        time_window_seconds: int = 60,
        days: Optional[int] = None,
    ) -> List[CorrelationResult]:
        """
        Analyze co-occurrence of rule firings within a time window.

        Two rules co-occur if their firings happen within the specified
        time window of each other. Uses pointwise mutual information
        to measure the strength of co-occurrence.

        Args:
            time_window_seconds: Max seconds between firings to count as co-occurrence.
            days: Lookback window for firing records.

        Returns:
            List of CorrelationResult objects for co-occurrence pairs.
        """
        if not self._config.enable_co_occurrence:
            return []

        cutoff = datetime.utcnow() - timedelta(days=days or 30)
        filtered: Dict[str, List[datetime]] = {
            rid: sorted(ts for ts in timestamps if ts >= cutoff)
            for rid, timestamps in self._firing_log.items()
            if any(ts >= cutoff for ts in timestamps)
        }

        rule_ids = list(filtered.keys())
        if len(rule_ids) < 2:
            return []

        total_firings: Dict[str, int] = {
            rid: len(ts) for rid, ts in filtered.items()
        }
        total_all = sum(total_firings.values())

        co_occurrences: Dict[Tuple[str, str], int] = defaultdict(int)

        for i in range(len(rule_ids)):
            for j in range(i + 1, len(rule_ids)):
                a, b = rule_ids[i], rule_ids[j]
                timestamps_a = filtered[a]
                timestamps_b = filtered[b]

                count = 0
                idx_b = 0
                for ts_a in timestamps_a:
                    while idx_b < len(timestamps_b) and timestamps_b[idx_b] < ts_a - timedelta(seconds=time_window_seconds):
                        idx_b += 1
                    temp_b = idx_b
                    while temp_b < len(timestamps_b):
                        diff = abs((timestamps_b[temp_b] - ts_a).total_seconds())
                        if diff <= time_window_seconds:
                            count += 1
                            temp_b += 1
                        else:
                            break
                if count > 0:
                    co_occurrences[(a, b)] = count

        results: List[CorrelationResult] = []
        for (a, b), joint_count in co_occurrences.items():
            if joint_count < self._config.co_occurrence_min_joint:
                continue

            p_a = total_firings[a] / max(total_all, 1)
            p_b = total_firings[b] / max(total_all, 1)
            p_ab = joint_count / max(total_all, 1)

            expected = p_a * p_b * total_all
            if expected < self._config.co_occurrence_min_expected:
                continue

            if p_ab > 0 and p_a > 0 and p_b > 0:
                pmi = math.log2(p_ab / (p_a * p_b))
                normalized_pmi = pmi / -math.log2(p_ab) if p_ab < 1.0 else pmi
            else:
                normalized_pmi = 0.0

            coefficient = min(max(normalized_pmi, -1.0), 1.0)
            strength, direction = self._classify_correlation(coefficient)

            results.append(CorrelationResult(
                correlation_id=str(uuid.uuid4()),
                entity_a=a,
                entity_b=b,
                method=CorrelationMethod.CO_OCCURRENCE,
                coefficient=coefficient,
                strength=strength,
                direction=direction,
                p_value=0.0,
                significant=abs(coefficient) > 0.3,
                description=f"Co-occurrence between '{a}' and '{b}' (joint={joint_count}, window={time_window_seconds}s)",
                metadata={
                    "joint_occurrences": joint_count,
                    "expected_occurrences": round(expected, 2),
                    "total_firings_a": total_firings[a],
                    "total_firings_b": total_firings[b],
                    "time_window_seconds": time_window_seconds,
                },
            ))

        for result in results:
            self._correlations[result.correlation_id] = result

        logger.info("Found %d co-occurrence correlations", len(results))
        return results

    # ------------------------------------------------------------------
    # Pearson / Spearman Correlation for Numeric Metrics
    # ------------------------------------------------------------------

    def analyze_numeric_correlation(
        self,
        metric_name: str,
        method: Optional[CorrelationMethod] = None,
    ) -> List[CorrelationResult]:
        """
        Compute pairwise correlation coefficients for a numeric metric.

        Args:
            metric_name: Name of the numeric metric to correlate.
            method: PEARSON or SPEARMAN. Defaults to both if enabled.

        Returns:
            List of CorrelationResult objects.
        """
        methods: List[CorrelationMethod] = []
        if method is not None:
            methods = [method]
        else:
            if self._config.enable_pearson:
                methods.append(CorrelationMethod.PEARSON)
            if self._config.enable_spearman:
                methods.append(CorrelationMethod.SPEARMAN)

        if not methods:
            return []

        rules_with_metric = [
            rid for rid, metrics in self._numeric_metrics.items()
            if metric_name in metrics and len(metrics[metric_name]) >= self._config.min_data_points
        ]

        if len(rules_with_metric) < 2:
            return []

        results: List[CorrelationResult] = []
        for i in range(len(rules_with_metric)):
            for j in range(i + 1, len(rules_with_metric)):
                a, b = rules_with_metric[i], rules_with_metric[j]
                data_a = self._numeric_metrics[a][metric_name][-self._config.min_data_points:]
                data_b = self._numeric_metrics[b][metric_name][-self._config.min_data_points:]

                min_len = min(len(data_a), len(data_b))
                if min_len < self._config.min_data_points:
                    continue
                data_a = data_a[-min_len:]
                data_b = data_b[-min_len:]

                arr_a = np.array(data_a, dtype=float)
                arr_b = np.array(data_b, dtype=float)

                for meth in methods:
                    result = self._compute_numeric_correlation(a, b, arr_a, arr_b, meth, metric_name)
                    if result is not None:
                        results.append(result)

        for result in results:
            self._correlations[result.correlation_id] = result

        return results

    def _compute_numeric_correlation(
        self,
        a: str,
        b: str,
        arr_a: np.ndarray,
        arr_b: np.ndarray,
        method: CorrelationMethod,
        metric_name: str,
    ) -> Optional[CorrelationResult]:
        """Compute a single numeric correlation between two arrays."""
        try:
            if method == CorrelationMethod.PEARSON:
                coeff, p_val = pearsonr(arr_a, arr_b)
                sig_threshold = self._config.pearson_significance
            elif method == CorrelationMethod.SPEARMAN:
                coeff, p_val = spearmanr(arr_a, arr_b)
                sig_threshold = self._config.spearman_significance
            else:
                return None

            if math.isnan(coeff):
                return None

            strength, direction = self._classify_correlation(coeff)
            significant = p_val < sig_threshold

            return CorrelationResult(
                correlation_id=str(uuid.uuid4()),
                entity_a=a,
                entity_b=b,
                method=method,
                coefficient=coeff,
                strength=strength,
                direction=direction,
                p_value=p_val,
                significant=significant,
                description=f"{method.value} correlation for '{metric_name}' between '{a}' and '{b}'",
                metadata={"metric_name": metric_name, "data_points": len(arr_a)},
            )
        except Exception as exc:
            logger.debug("Failed to compute %s correlation: %s", method.value, exc)
            return None

    # ------------------------------------------------------------------
    # Mutual Information for Categorical Attributes
    # ------------------------------------------------------------------

    def analyze_mutual_information(
        self,
        attribute_name: str,
    ) -> List[CorrelationResult]:
        """
        Compute pairwise mutual information for a categorical attribute.

        Measures the dependency between two rules' categorical attribute
        distributions. Higher MI indicates stronger association.

        Args:
            attribute_name: Name of the categorical attribute.

        Returns:
            List of CorrelationResult objects.
        """
        if not self._config.enable_mutual_information:
            return []

        rules_with_attr = [
            rid for rid, attrs in self._categorical_attributes.items()
            if attribute_name in attrs and len(attrs[attribute_name]) >= self._config.min_data_points
        ]

        if len(rules_with_attr) < 2:
            return []

        results: List[CorrelationResult] = []
        for i in range(len(rules_with_attr)):
            for j in range(i + 1, len(rules_with_attr)):
                a, b = rules_with_attr[i], rules_with_attr[j]
                data_a = self._categorical_attributes[a][attribute_name]
                data_b = self._categorical_attributes[b][attribute_name]

                min_len = min(len(data_a), len(data_b))
                if min_len < self._config.min_data_points:
                    continue

                data_a = data_a[-min_len:]
                data_b = data_b[-min_len:]

                mi = self._compute_mutual_information(data_a, data_b)
                if mi < 0:
                    continue

                if self._config.mutual_information_normalized:
                    max_ent_a = entropy(list(Counter(data_a).values()), base=2) if len(set(data_a)) > 1 else 1.0
                    max_ent_b = entropy(list(Counter(data_b).values()), base=2) if len(set(data_b)) > 1 else 1.0
                    mi = mi / max(max_ent_a, max_ent_b, 0.01)

                strength, direction = self._classify_correlation(mi)
                significant = mi > 0.1

                results.append(CorrelationResult(
                    correlation_id=str(uuid.uuid4()),
                    entity_a=a,
                    entity_b=b,
                    method=CorrelationMethod.MUTUAL_INFORMATION,
                    coefficient=mi,
                    strength=strength,
                    direction=direction,
                    p_value=0.0,
                    significant=significant,
                    description=f"Mutual information for '{attribute_name}' between '{a}' and '{b}'",
                    metadata={"attribute_name": attribute_name, "data_points": min_len},
                ))

        for result in results:
            self._correlations[result.correlation_id] = result

        return results

    @staticmethod
    def _compute_mutual_information(
        values_a: List[str],
        values_b: List[str],
    ) -> float:
        """Compute mutual information between two categorical sequences."""
        pairs = list(zip(values_a, values_b))
        n = len(pairs)
        if n == 0:
            return -1.0

        joint_counts: Counter = Counter(pairs)
        margin_a: Counter = Counter(values_a)
        margin_b: Counter = Counter(values_b)

        mi = 0.0
        for (val_a, val_b), joint_count in joint_counts.items():
            p_ab = joint_count / n
            p_a = margin_a[val_a] / n
            p_b = margin_b[val_b] / n
            if p_ab > 0 and p_a > 0 and p_b > 0:
                mi += p_ab * math.log2(p_ab / (p_a * p_b))

        return mi

    # ------------------------------------------------------------------
    # Jaccard Similarity for Categorical Attributes
    # ------------------------------------------------------------------

    def analyze_jaccard_similarity(
        self,
        attribute_name: str,
    ) -> List[CorrelationResult]:
        """
        Compute Jaccard similarity between rules' categorical attribute value sets.

        Jaccard = |intersection| / |union| of unique attribute values.
        """
        rules_with_attr = [
            rid for rid, attrs in self._categorical_attributes.items()
            if attribute_name in attrs and len(attrs[attribute_name]) >= self._config.min_data_points
        ]

        if len(rules_with_attr) < 2:
            return []

        value_sets: Dict[str, Set[str]] = {
            rid: set(self._categorical_attributes[rid][attribute_name])
            for rid in rules_with_attr
        }

        results: List[CorrelationResult] = []
        for i in range(len(rules_with_attr)):
            for j in range(i + 1, len(rules_with_attr)):
                a, b = rules_with_attr[i], rules_with_attr[j]
                set_a = value_sets[a]
                set_b = value_sets[b]

                intersection = len(set_a & set_b)
                union = len(set_a | set_b)
                if union == 0:
                    continue

                jaccard = intersection / union
                if jaccard < self._config.jaccard_threshold:
                    continue

                strength, direction = self._classify_correlation(jaccard)

                results.append(CorrelationResult(
                    correlation_id=str(uuid.uuid4()),
                    entity_a=a,
                    entity_b=b,
                    method=CorrelationMethod.JACCARD,
                    coefficient=jaccard,
                    strength=strength,
                    direction=direction,
                    p_value=0.0,
                    significant=jaccard >= self._config.jaccard_threshold,
                    description=f"Jaccard similarity for '{attribute_name}' between '{a}' and '{b}'",
                    metadata={
                        "attribute_name": attribute_name,
                        "intersection_size": intersection,
                        "union_size": union,
                    },
                ))

        for result in results:
            self._correlations[result.correlation_id] = result

        return results

    # ------------------------------------------------------------------
    # Cross-Correlation with Time Lag
    # ------------------------------------------------------------------

    def analyze_cross_correlation(
        self,
        days: Optional[int] = None,
    ) -> List[CorrelationResult]:
        """
        Analyze cross-correlation between rule firing time series with time lag.

        Determines if one rule's firings tend to follow another's with
        a consistent time delay.

        Args:
            days: Lookback window for firing records.

        Returns:
            List of CorrelationResult objects with lag information.
        """
        if not self._config.enable_cross_correlation:
            return []

        cutoff = datetime.utcnow() - timedelta(days=days or 30)
        filtered: Dict[str, np.ndarray] = {}

        for rid, timestamps in self._firing_log.items():
            recent = sorted([ts for ts in timestamps if ts >= cutoff])
            if len(recent) < self._config.min_data_points:
                continue

            daily: Dict[str, int] = defaultdict(int)
            for ts in recent:
                daily[ts.strftime("%Y-%m-%d")] += 1

            sorted_days = sorted(daily.keys())
            values = np.array([float(daily[d]) for d in sorted_days], dtype=float)
            filtered[rid] = values

        rule_ids = list(filtered.keys())
        if len(rule_ids) < 2:
            return []

        results: List[CorrelationResult] = []
        max_lag = self._config.cross_correlation_max_lag
        min_score = self._config.cross_correlation_min_score

        for i in range(len(rule_ids)):
            for j in range(i + 1, len(rule_ids)):
                a, b = rule_ids[i], rule_ids[j]
                x = filtered[a]
                y = filtered[b]

                min_len = min(len(x), len(y))
                if min_len < self._config.min_data_points:
                    continue

                x = x[-min_len:]
                y = y[-min_len:]

                x_std = float(np.std(x)) or 1.0
                y_std = float(np.std(y)) or 1.0
                x_demean = x - np.mean(x)
                y_demean = y - np.mean(y)

                best_lag = 0
                best_corr = 0.0

                for lag in range(-max_lag, max_lag + 1):
                    if lag < 0:
                        corr = np.correlate(x_demean[:lag], y_demean[-lag:])
                    elif lag > 0:
                        corr = np.correlate(x_demean[lag:], y_demean[:-lag])
                    else:
                        corr = np.correlate(x_demean, y_demean)

                    if len(corr) > 0:
                        normalized_corr = float(corr[0]) / (x_std * y_std * min(min_len, len(y_demean)))
                        normalized_corr = max(-1.0, min(1.0, normalized_corr))
                        if abs(normalized_corr) > abs(best_corr):
                            best_corr = normalized_corr
                            best_lag = lag

                if abs(best_corr) >= min_score:
                    strength, direction = self._classify_correlation(best_corr)
                    results.append(CorrelationResult(
                        correlation_id=str(uuid.uuid4()),
                        entity_a=a,
                        entity_b=b,
                        method=CorrelationMethod.CROSS_CORRELATION,
                        coefficient=best_corr,
                        strength=strength,
                        direction=direction,
                        p_value=0.0,
                        significant=True,
                        description=(
                            f"Cross-correlation between '{a}' and '{b}' "
                            f"(lag={best_lag}d, corr={best_corr:.3f})"
                        ),
                        metadata={
                            "lag_days": best_lag,
                            "lag_direction": "a_leads" if best_lag > 0 else "b_leads" if best_lag < 0 else "simultaneous",
                            "data_points": min_len,
                        },
                    ))

        for result in results:
            self._correlations[result.correlation_id] = result

        return results

    # ------------------------------------------------------------------
    # Correlation Clustering
    # ------------------------------------------------------------------

    def cluster_correlations(
        self,
        method: Optional[CorrelationMethod] = None,
    ) -> List[CorrelationCluster]:
        """
        Group correlated rules into clusters based on correlation strength.

        Uses a graph-based approach: rules are nodes, correlations are edges
        above the cluster threshold. Connected components form clusters.

        Args:
            method: Optional method filter to cluster only specific types.

        Returns:
            List of CorrelationCluster objects.
        """
        if not self._config.enable_clustering:
            return []

        threshold = self._config.cluster_correlation_threshold

        edges: List[Dict[str, Any]] = []
        for corr in self._correlations.values():
            if method is not None and corr.method != method:
                continue
            if abs(corr.coefficient) >= threshold and corr.significant:
                edges.append({
                    "entity_a": corr.entity_a,
                    "entity_b": corr.entity_b,
                    "coefficient": corr.coefficient,
                    "method": corr.method,
                    "direction": corr.direction,
                })

        if not edges:
            return []

        adjacency: Dict[str, Set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge["entity_a"]].add(edge["entity_b"])
            adjacency[edge["entity_b"]].add(edge["entity_a"])

        visited: Set[str] = set()
        clusters_list: List[Set[str]] = []

        for node in adjacency:
            if node in visited:
                continue
            cluster = set()
            stack = [node]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                cluster.add(current)
                for neighbor in adjacency[current]:
                    if neighbor not in visited:
                        stack.append(neighbor)
            if len(cluster) >= self._config.min_cluster_size:
                clusters_list.append(cluster)

        results: List[CorrelationCluster] = []
        for idx, cluster_rules in enumerate(clusters_list):
            internal_edges = [
                e for e in edges
                if e["entity_a"] in cluster_rules and e["entity_b"] in cluster_rules
            ]

            avg_corr = float(np.mean([abs(e["coefficient"]) for e in internal_edges])) if internal_edges else 0.0
            methods_used = Counter(e["method"].value for e in internal_edges)
            primary_method = CorrelationMethod(methods_used.most_common(1)[0][0]) if methods_used else CorrelationMethod.PEARSON

            positive_count = sum(1 for e in internal_edges if e["direction"] == CorrelationDirection.POSITIVE.value)
            negative_count = sum(1 for e in internal_edges if e["direction"] == CorrelationDirection.NEGATIVE.value)
            if positive_count > negative_count:
                dom_dir = "positive"
            elif negative_count > positive_count:
                dom_dir = "negative"
            else:
                dom_dir = "mixed"

            cluster_obj = CorrelationCluster(
                cluster_id=f"corr_cluster_{idx:04d}",
                rule_ids=sorted(cluster_rules),
                average_correlation=avg_corr,
                primary_method=primary_method,
                dominant_direction=dom_dir,
                internal_edges=[
                    {
                        "entity_a": e["entity_a"],
                        "entity_b": e["entity_b"],
                        "coefficient": round(e["coefficient"], 4),
                        "method": e["method"].value,
                    }
                    for e in internal_edges[:20]
                ],
                description=f"Cluster of {len(cluster_rules)} correlated rules ({primary_method.value}, avg={avg_corr:.3f})",
            )
            results.append(cluster_obj)
            self._clusters[cluster_obj.cluster_id] = cluster_obj

        logger.info("Formed %d correlation clusters from %d edges", len(results), len(edges))
        return results

    # ------------------------------------------------------------------
    # Causal Inference Hints
    # ------------------------------------------------------------------

    def infer_causal_hints(
        self,
        time_window_seconds: int = 300,
        days: Optional[int] = None,
    ) -> List[CausalHint]:
        """
        Infer potential causal relationships based on temporal precedence.

        If rule A consistently fires before rule B within a time window,
        this suggests A may have a causal influence on B.

        Args:
            time_window_seconds: Max seconds between A and B firings.
            days: Lookback window.

        Returns:
            List of CausalHint objects with precedence scores.
        """
        if not self._config.enable_causal_inference:
            return []

        cutoff = datetime.utcnow() - timedelta(days=days or 30)
        filtered: Dict[str, List[datetime]] = {
            rid: sorted(ts for ts in timestamps if ts >= cutoff)
            for rid, timestamps in self._firing_log.items()
            if any(ts >= cutoff for ts in timestamps)
        }

        rule_ids = list(filtered.keys())
        if len(rule_ids) < 2:
            return []

        min_precedence = self._config.causal_min_temporal_precedence
        window = timedelta(seconds=time_window_seconds)
        hints: List[CausalHint] = []

        for i in range(len(rule_ids)):
            for j in range(len(rule_ids)):
                if i == j:
                    continue

                cause_id = rule_ids[i]
                effect_id = rule_ids[j]
                cause_times = filtered[cause_id]
                effect_times = filtered[effect_id]

                precedences = 0
                total_considered = 0
                lags: List[float] = []

                idx_effect = 0
                for ts_cause in cause_times:
                    while idx_effect < len(effect_times) and effect_times[idx_effect] < ts_cause:
                        idx_effect += 1

                    temp = idx_effect
                    while temp < len(effect_times):
                        diff = (effect_times[temp] - ts_cause).total_seconds()
                        if 0 <= diff <= time_window_seconds:
                            precedences += 1
                            lags.append(diff)
                            temp += 1
                        else:
                            break
                    total_considered += 1

                if total_considered == 0:
                    continue

                precedence_ratio = precedences / total_considered

                if precedence_ratio >= min_precedence and precedences >= 3:
                    avg_lag_seconds = float(np.mean(lags)) if lags else 0.0
                    confidence = min(precedence_ratio * (1.0 - 1.0 / max(precedences, 1)), 0.99)

                    hint = CausalHint(
                        hint_id=str(uuid.uuid4()),
                        cause_entity=cause_id,
                        effect_entity=effect_id,
                        temporal_precedence_score=precedence_ratio,
                        confidence=confidence,
                        avg_lag=timedelta(seconds=avg_lag_seconds),
                        evidence_count=precedences,
                        description=(
                            f"'{cause_id}' may influence '{effect_id}' "
                            f"(precedence={precedence_ratio:.2f}, avg_lag={avg_lag_seconds:.0f}s)"
                        ),
                    )
                    hints.append(hint)

        hints.sort(key=lambda h: h.confidence, reverse=True)
        for hint in hints:
            self._causal_hints[hint.hint_id] = hint

        logger.info("Inferred %d causal hints", len(hints))
        return hints

    # ------------------------------------------------------------------
    # Full Analysis Pipeline
    # ------------------------------------------------------------------

    def analyze_all(self) -> Dict[str, Any]:
        """
        Run all enabled correlation analyses.

        Returns:
            Dict with all results: co_occurrence, numeric, mutual_info,
            jaccard, cross_correlation, clusters, causal_hints.
        """
        results: Dict[str, Any] = {}

        co_occurrence = self.analyze_co_occurrence()
        results["co_occurrence"] = [r.to_dict() for r in co_occurrence]

        numeric_metric_names: Set[str] = set()
        for metrics in self._numeric_metrics.values():
            numeric_metric_names.update(metrics.keys())
        results["numeric_correlations"] = {}
        for metric in numeric_metric_names:
            corrs = self.analyze_numeric_correlation(metric)
            results["numeric_correlations"][metric] = [r.to_dict() for r in corrs]

        attr_names: Set[str] = set()
        for attrs in self._categorical_attributes.values():
            attr_names.update(attrs.keys())
        results["mutual_information"] = {}
        results["jaccard"] = {}
        for attr in attr_names:
            mi_results = self.analyze_mutual_information(attr)
            results["mutual_information"][attr] = [r.to_dict() for r in mi_results]
            jac_results = self.analyze_jaccard_similarity(attr)
            results["jaccard"][attr] = [r.to_dict() for r in jac_results]

        cross_corr = self.analyze_cross_correlation()
        results["cross_correlation"] = [r.to_dict() for r in cross_corr]

        clusters = self.cluster_correlations()
        results["clusters"] = [c.to_dict() for c in clusters]

        causal = self.infer_causal_hints()
        results["causal_hints"] = [h.to_dict() for h in causal]

        results["total_correlations"] = sum(
            len(results.get(k, [])) + sum(
                len(v) for v in results.get(k, {}).values()
            ) if isinstance(results.get(k), dict) else len(results.get(k, []))
            for k in ["co_occurrence", "numeric_correlations", "mutual_information", "jaccard", "cross_correlation"]
        )

        return results

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_correlations_for_rule(self, rule_id: str) -> List[CorrelationResult]:
        """Get all correlations involving a specific rule."""
        return [
            c for c in self._correlations.values()
            if c.entity_a == rule_id or c.entity_b == rule_id
        ]

    def get_significant_correlations(self, min_coefficient: float = 0.5) -> List[CorrelationResult]:
        """Get all significant correlations above a coefficient threshold."""
        return [
            c for c in self._correlations.values()
            if abs(c.coefficient) >= min_coefficient and c.significant
        ]

    def get_correlations_by_method(self, method: CorrelationMethod) -> List[CorrelationResult]:
        """Get correlations filtered by detection method."""
        return [c for c in self._correlations.values() if c.method == method]

    # ------------------------------------------------------------------
    # Statistics & Export
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about detected correlations."""
        by_method: Dict[str, int] = defaultdict(int)
        by_strength: Dict[str, int] = defaultdict(int)
        for corr in self._correlations.values():
            by_method[corr.method.value] += 1
            by_strength[corr.strength.value] += 1

        return {
            "total_correlations": len(self._correlations),
            "correlations_by_method": dict(by_method),
            "correlations_by_strength": dict(by_strength),
            "significant_count": sum(1 for c in self._correlations.values() if c.significant),
            "cluster_count": len(self._clusters),
            "causal_hint_count": len(self._causal_hints),
            "unique_rules_with_firings": len(self._firing_log),
            "unique_numeric_metrics": sum(len(m) for m in self._numeric_metrics.values()),
            "unique_categorical_attributes": sum(len(a) for a in self._categorical_attributes.values()),
            "config": self._config.to_dict(),
        }

    def export_data(self) -> Dict[str, Any]:
        """Export all correlation data for external consumption."""
        return {
            "config": self._config.to_dict(),
            "correlations": [c.to_dict() for c in self._correlations.values()],
            "clusters": [c.to_dict() for c in self._clusters.values()],
            "causal_hints": [h.to_dict() for h in self._causal_hints.values()],
            "stats": self.get_stats(),
        }

    def reset(self) -> None:
        """Reset all detector state."""
        self._firing_log.clear()
        self._numeric_metrics.clear()
        self._categorical_attributes.clear()
        self._correlations.clear()
        self._clusters.clear()
        self._causal_hints.clear()
        logger.info("CorrelationDetector reset to initial state")

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _classify_correlation(cls, coefficient: float) -> Tuple[CorrelationStrength, CorrelationDirection]:
        """
        Classify coefficient into strength and direction categories.
        """
        abs_coeff = abs(coefficient)
        if coefficient > 0:
            direction = CorrelationDirection.POSITIVE
        elif coefficient < 0:
            direction = CorrelationDirection.NEGATIVE
        else:
            direction = CorrelationDirection.NONE

        strength = CorrelationStrength.NEGLIGIBLE
        for lower, upper, s in cls._STRENGTH_BOUNDS:
            if lower <= abs_coeff <= upper:
                strength = s
                break

        return strength, direction
