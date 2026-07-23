"""
Conflict pattern detection and analysis for rule evaluation.

Detects conflict patterns between rules including direct overlap, transitive,
circular, semantic, and temporal conflicts. Provides clustering, metrics,
and historical trend analysis.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Callable, Sequence

import numpy as np

from rules_emerging_pattern.models.rule import Rule, RuleTier
from rules_emerging_pattern.models.conflict import ConflictSeverity

logger = logging.getLogger(__name__)


class PatternConflictCategory(str, Enum):
    """Categories of conflict patterns detected between rules."""

    KEYWORD_OVERLAP = "keyword_overlap"
    REGEX_OVERLAP = "regex_overlap"
    SEMANTIC_CONFLICT = "semantic_conflict"
    TEMPORAL_CONFLICT = "temporal_conflict"
    TRANSITIVE_CONFLICT = "transitive_conflict"
    CIRCULAR_CONFLICT = "circular_conflict"
    HIERARCHICAL_CONFLICT = "hierarchical_conflict"


class ConflictMatch:
    """A detected conflict match between two or more rules."""

    def __init__(
        self,
        conflict_id: str,
        rule_a: str,
        rule_b: str,
        category: PatternConflictCategory,
        overlap_score: float,
        severity: ConflictSeverity,
        description: str,
        overlapping_elements: List[str],
        detected_at: Optional[datetime] = None,
        resolved: bool = False,
    ) -> None:
        self.conflict_id = conflict_id
        self.rule_a = rule_a
        self.rule_b = rule_b
        self.category = category
        self.overlap_score = overlap_score
        self.severity = severity
        self.description = description
        self.overlapping_elements = overlapping_elements
        self.detected_at = detected_at or datetime.utcnow()
        self.resolved = resolved

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "conflict_id": self.conflict_id,
            "rule_a": self.rule_a,
            "rule_b": self.rule_b,
            "category": self.category.value,
            "overlap_score": self.overlap_score,
            "severity": self.severity.value,
            "description": self.description,
            "overlapping_elements": self.overlapping_elements,
            "detected_at": self.detected_at.isoformat(),
            "resolved": self.resolved,
        }


class ConflictCluster:
    """Group of related conflicts sharing common rules or root causes."""

    def __init__(
        self,
        cluster_id: str,
        conflict_ids: List[str],
        root_cause: str,
        affected_rules: List[str],
        average_overlap_score: float,
        total_conflicts: int,
        detected_at: Optional[datetime] = None,
    ) -> None:
        self.cluster_id = cluster_id
        self.conflict_ids = conflict_ids
        self.root_cause = root_cause
        self.affected_rules = affected_rules
        self.average_overlap_score = average_overlap_score
        self.total_conflicts = total_conflicts
        self.detected_at = detected_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "cluster_id": self.cluster_id,
            "conflict_ids": self.conflict_ids,
            "root_cause": self.root_cause,
            "affected_rules": self.affected_rules,
            "average_overlap_score": self.average_overlap_score,
            "total_conflicts": self.total_conflicts,
            "detected_at": self.detected_at.isoformat(),
        }


class ConflictTrend:
    """Historical trend analysis for a specific conflict pattern."""

    def __init__(
        self,
        trend_id: str,
        pattern_name: str,
        time_period: str,
        conflict_count: int,
        trend_direction: str,
        severity_distribution: Dict[str, int],
        repeat_offenders: List[Dict[str, Any]],
    ) -> None:
        self.trend_id = trend_id
        self.pattern_name = pattern_name
        self.time_period = time_period
        self.conflict_count = conflict_count
        self.trend_direction = trend_direction
        self.severity_distribution = severity_distribution
        self.repeat_offenders = repeat_offenders

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "trend_id": self.trend_id,
            "pattern_name": self.pattern_name,
            "time_period": self.time_period,
            "conflict_count": self.conflict_count,
            "trend_direction": self.trend_direction,
            "severity_distribution": self.severity_distribution,
            "repeat_offenders": self.repeat_offenders,
        }


class ConflictPatternDetectorConfig:
    """Configuration for ConflictPatternDetector."""

    def __init__(
        self,
        min_overlap_threshold: float = 0.3,
        max_conflict_age_hours: int = 168,
        cluster_similarity_threshold: float = 0.6,
        enable_transitive_detection: bool = True,
        enable_circular_detection: bool = True,
        enable_semantic_detection: bool = True,
        history_window_days: int = 90,
        min_trend_data_points: int = 5,
        max_rules_per_cluster: int = 50,
        keyword_weight: float = 0.4,
        regex_weight: float = 0.3,
        semantic_weight: float = 0.2,
        temporal_weight: float = 0.1,
        enable_hierarchical_detection: bool = True,
        max_conflicts_per_pair: int = 1,
    ) -> None:
        self.min_overlap_threshold = min_overlap_threshold
        self.max_conflict_age_hours = max_conflict_age_hours
        self.cluster_similarity_threshold = cluster_similarity_threshold
        self.enable_transitive_detection = enable_transitive_detection
        self.enable_circular_detection = enable_circular_detection
        self.enable_semantic_detection = enable_semantic_detection
        self.history_window_days = history_window_days
        self.min_trend_data_points = min_trend_data_points
        self.max_rules_per_cluster = max_rules_per_cluster
        self.keyword_weight = keyword_weight
        self.regex_weight = regex_weight
        self.semantic_weight = semantic_weight
        self.temporal_weight = temporal_weight
        self.enable_hierarchical_detection = enable_hierarchical_detection
        self.max_conflicts_per_pair = max_conflicts_per_pair

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class ConflictPatternDetector:
    """
    Detects and analyzes conflict patterns between rules.

    Capabilities:
    - Direct overlap detection (keyword, regex, semantic, temporal)
    - Transitive conflict detection (A->B->C implies A may conflict with C)
    - Circular conflict detection (cycles of 3+ rules)
    - Hierarchical conflict detection (tier-based priority conflicts)
    - Conflict clustering (grouping related conflicts)
    - Historical trend analysis and repeat offender identification
    - Configurable thresholds and weights
    """

    _SEVERITY_ORDER = {
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4,
    }

    _TIER_MULTIPLIERS = {
        RuleTier.SAFETY: 1.5,
        RuleTier.OPERATIONAL: 1.2,
        RuleTier.PREFERENCE: 1.0,
    }

    _CATEGORY_PRIORITY = [
        PatternConflictCategory.CIRCULAR_CONFLICT,
        PatternConflictCategory.TRANSITIVE_CONFLICT,
        PatternConflictCategory.HIERARCHICAL_CONFLICT,
        PatternConflictCategory.SEMANTIC_CONFLICT,
        PatternConflictCategory.TEMPORAL_CONFLICT,
        PatternConflictCategory.REGEX_OVERLAP,
        PatternConflictCategory.KEYWORD_OVERLAP,
    ]

    _STOP_WORDS = frozenset({
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "in", "on", "at", "of", "to", "for", "and", "or", "not", "no",
        "it", "its", "this", "that", "with", "from", "by", "as", "but",
    })

    def __init__(self, config: Optional[ConflictPatternDetectorConfig] = None) -> None:
        self._config = config or ConflictPatternDetectorConfig()
        self._conflicts: Dict[str, ConflictMatch] = {}
        self._clusters: Dict[str, ConflictCluster] = {}
        self._history: List[ConflictMatch] = []
        self._rule_cache: Dict[str, Rule] = {}
        logger.info("ConflictPatternDetector initialized with config: %s", self._config.to_dict())

    # ------------------------------------------------------------------
    # Registration & Data Ingestion
    # ------------------------------------------------------------------

    def register_rule(self, rule: Rule) -> None:
        """Register a single rule for conflict detection."""
        self._rule_cache[rule.id] = rule
        logger.debug("Registered rule: %s", rule.id)

    def register_rules(self, rules: Sequence[Rule]) -> None:
        """Register multiple rules at once."""
        for rule in rules:
            self.register_rule(rule)

    def unregister_rule(self, rule_id: str) -> bool:
        """Remove a rule from the cache."""
        if rule_id in self._rule_cache:
            del self._rule_cache[rule_id]
            logger.debug("Unregistered rule: %s", rule_id)
            return True
        return False

    def ingest_conflict(self, conflict: ConflictMatch) -> None:
        """Ingest a known conflict for analysis and history tracking."""
        self._conflicts[conflict.conflict_id] = conflict
        self._history.append(conflict)

    def ingest_conflicts(self, conflicts: Sequence[ConflictMatch]) -> None:
        """Ingest multiple conflicts at once."""
        for conflict in conflicts:
            self.ingest_conflict(conflict)

    # ------------------------------------------------------------------
    # Core Detection Pipeline
    # ------------------------------------------------------------------

    def detect_all_patterns(self) -> Dict[str, List[ConflictMatch]]:
        """
        Run all enabled detection methods and return categorized results.

        Returns:
            Dict mapping category names to lists of detected ConflictMatch.
        """
        results: Dict[str, List[ConflictMatch]] = defaultdict(list)

        keyword_overlaps = self._detect_keyword_overlap_conflicts()
        results["keyword_overlap"].extend(keyword_overlaps)

        regex_overlaps = self._detect_regex_overlap_conflicts()
        results["regex_overlap"].extend(regex_overlaps)

        temporal = self._detect_temporal_conflicts()
        results["temporal_conflict"].extend(temporal)

        if self._config.enable_semantic_detection:
            semantic = self._detect_semantic_conflicts()
            results["semantic_conflict"].extend(semantic)

        if self._config.enable_transitive_detection:
            transitive = self._detect_transitive_conflicts()
            results["transitive_conflict"].extend(transitive)

        if self._config.enable_circular_detection:
            circular = self._detect_circular_conflicts()
            results["circular_conflict"].extend(circular)

        if self._config.enable_hierarchical_detection:
            hierarchical = self._detect_hierarchical_conflicts()
            results["hierarchical_conflict"].extend(hierarchical)

        all_conflicts = [c for cat_list in results.values() for c in cat_list]
        for conflict in all_conflicts:
            self._conflicts[conflict.conflict_id] = conflict
            self._history.append(conflict)

        if all_conflicts:
            logger.info("Detected %d total conflicts across %d categories", len(all_conflicts), len(results))

        return dict(results)

    def detect_direct_overlap(self, rule_a: Rule, rule_b: Rule) -> Optional[ConflictMatch]:
        """
        Detect direct overlap between two rules considering all pattern types.

        Returns:
            ConflictMatch if overlap found above threshold, else None.
        """
        overlapping_elements: List[str] = []
        total_score = 0.0
        categories_used: List[PatternConflictCategory] = []

        keywords_a = self._get_keywords(rule_a)
        keywords_b = self._get_keywords(rule_b)
        common_keywords = set(keywords_a) & set(keywords_b)
        if common_keywords:
            union_size = max(len(set(keywords_a) | set(keywords_b)), 1)
            keyword_score = len(common_keywords) / union_size
            total_score += keyword_score * self._config.keyword_weight
            overlapping_elements.extend(f"keyword:{kw}" for kw in common_keywords)
            categories_used.append(PatternConflictCategory.KEYWORD_OVERLAP)

        regexes_a = self._get_regexes(rule_a)
        regexes_b = self._get_regexes(rule_b)
        common_regexes = set(regexes_a) & set(regexes_b)
        if common_regexes:
            union_size = max(len(set(regexes_a) | set(regexes_b)), 1)
            regex_score = len(common_regexes) / union_size
            total_score += regex_score * self._config.regex_weight
            overlapping_elements.extend(f"regex:{rg}" for rg in common_regexes)
            categories_used.append(PatternConflictCategory.REGEX_OVERLAP)

        if not overlapping_elements:
            return None

        dominant_category = self._select_dominant_category(categories_used)
        severity = self._compute_severity(total_score, rule_a, rule_b)

        return ConflictMatch(
            conflict_id=str(uuid.uuid4()),
            rule_a=rule_a.id,
            rule_b=rule_b.id,
            category=dominant_category,
            overlap_score=round(total_score, 4),
            severity=severity,
            description=self._build_conflict_description(rule_a, rule_b, overlapping_elements, total_score),
            overlapping_elements=overlapping_elements,
            detected_at=datetime.utcnow(),
        )

    # ------------------------------------------------------------------
    # Keyword Overlap Detection
    # ------------------------------------------------------------------

    def _detect_keyword_overlap_conflicts(self) -> List[ConflictMatch]:
        """Detect conflicts based on keyword overlap between rule patterns."""
        return self._detect_overlap_by_extractor(
            PatternConflictCategory.KEYWORD_OVERLAP,
            self._get_keywords,
            self._config.keyword_weight,
        )

    # ------------------------------------------------------------------
    # Regex Overlap Detection
    # ------------------------------------------------------------------

    def _detect_regex_overlap_conflicts(self) -> List[ConflictMatch]:
        """Detect conflicts based on shared regex patterns."""
        return self._detect_overlap_by_extractor(
            PatternConflictCategory.REGEX_OVERLAP,
            self._get_regexes,
            self._config.regex_weight,
        )

    # ------------------------------------------------------------------
    # Semantic Conflict Detection
    # ------------------------------------------------------------------

    def _detect_semantic_conflicts(self) -> List[ConflictMatch]:
        """Detect semantic conflicts using description text similarity."""
        conflicts: List[ConflictMatch] = []
        rule_ids = list(self._rule_cache.keys())

        for i in range(len(rule_ids)):
            for j in range(i + 1, len(rule_ids)):
                rule_a = self._rule_cache[rule_ids[i]]
                rule_b = self._rule_cache[rule_ids[j]]

                tokens_a = {w for w in rule_a.description.lower().split() if w not in self._STOP_WORDS}
                tokens_b = {w for w in rule_b.description.lower().split() if w not in self._STOP_WORDS}

                common_tokens = tokens_a & tokens_b
                if len(common_tokens) >= 2:
                    union_size = max(len(tokens_a | tokens_b), 1)
                    semantic_score = len(common_tokens) / union_size * self._config.semantic_weight
                    effective_threshold = self._config.min_overlap_threshold * self._config.semantic_weight

                    if semantic_score >= effective_threshold:
                        conflicts.append(ConflictMatch(
                            conflict_id=str(uuid.uuid4()),
                            rule_a=rule_a.id,
                            rule_b=rule_b.id,
                            category=PatternConflictCategory.SEMANTIC_CONFLICT,
                            overlap_score=round(semantic_score, 4),
                            severity=self._compute_severity(semantic_score, rule_a, rule_b),
                            description=(
                                f"Semantic overlap between '{rule_a.name}' and '{rule_b.name}'"
                            ),
                            overlapping_elements=[f"term:{t}" for t in sorted(common_tokens)],
                            detected_at=datetime.utcnow(),
                        ))

        return conflicts

    # ------------------------------------------------------------------
    # Temporal Conflict Detection
    # ------------------------------------------------------------------

    def _detect_temporal_conflicts(self) -> List[ConflictMatch]:
        """
        Detect temporal conflicts where rules exhibit time-based
        conflicting behavior such as competing priorities or timeouts.
        """
        conflicts: List[ConflictMatch] = []
        rule_ids = list(self._rule_cache.keys())

        for i in range(len(rule_ids)):
            for j in range(i + 1, len(rule_ids)):
                rule_a = self._rule_cache[rule_ids[i]]
                rule_b = self._rule_cache[rule_ids[j]]

                if (
                    rule_a.tier != rule_b.tier
                    and rule_a.priority == rule_b.priority
                    and abs(rule_a.timeout_ms - rule_b.timeout_ms) < 100
                ):
                    temporal_score = self._config.temporal_weight * 0.8
                    conflicts.append(ConflictMatch(
                        conflict_id=str(uuid.uuid4()),
                        rule_a=rule_a.id,
                        rule_b=rule_b.id,
                        category=PatternConflictCategory.TEMPORAL_CONFLICT,
                        overlap_score=round(temporal_score, 4),
                        severity=ConflictSeverity.LOW,
                        description=(
                            f"Temporal conflict between '{rule_a.name}' and "
                            f"'{rule_b.name}' due to competing priorities"
                        ),
                        overlapping_elements=[
                            f"priority:{rule_a.priority}",
                            f"timeout:{rule_a.timeout_ms}ms",
                            f"tier:{rule_a.tier.value}",
                        ],
                        detected_at=datetime.utcnow(),
                    ))

        return conflicts

    # ------------------------------------------------------------------
    # Hierarchical Conflict Detection
    # ------------------------------------------------------------------

    def _detect_hierarchical_conflicts(self) -> List[ConflictMatch]:
        """
        Detect hierarchical conflicts where rules from different tiers
        have overlapping patterns but contradictory enforcement levels.
        """
        conflicts: List[ConflictMatch] = []
        rule_ids = list(self._rule_cache.keys())

        for i in range(len(rule_ids)):
            for j in range(i + 1, len(rule_ids)):
                rule_a = self._rule_cache[rule_ids[i]]
                rule_b = self._rule_cache[rule_ids[j]]

                if rule_a.tier == rule_b.tier:
                    continue

                keywords_a = set(self._get_keywords(rule_a))
                keywords_b = set(self._get_keywords(rule_b))
                common_words = keywords_a & keywords_b
                if not common_words:
                    continue

                if rule_a.enforcement_level.value != rule_b.enforcement_level.value:
                    union_size = max(len(keywords_a | keywords_b), 1)
                    overlap_ratio = len(common_words) / union_size
                    if overlap_ratio >= self._config.min_overlap_threshold:
                        hierarchical_score = overlap_ratio * 0.9
                        conflicts.append(ConflictMatch(
                            conflict_id=str(uuid.uuid4()),
                            rule_a=rule_a.id,
                            rule_b=rule_b.id,
                            category=PatternConflictCategory.HIERARCHICAL_CONFLICT,
                            overlap_score=round(hierarchical_score, 4),
                            severity=self._compute_severity(hierarchical_score, rule_a, rule_b),
                            description=(
                                f"Hierarchical conflict between '{rule_a.name}' "
                                f"(tier={rule_a.tier.value}) and '{rule_b.name}' "
                                f"(tier={rule_b.tier.value})"
                            ),
                            overlapping_elements=[f"keyword:{w}" for w in sorted(common_words)],
                            detected_at=datetime.utcnow(),
                        ))

        return conflicts

    # ------------------------------------------------------------------
    # Transitive Conflict Detection
    # ------------------------------------------------------------------

    def _detect_transitive_conflicts(self) -> List[ConflictMatch]:
        """
        Detect transitive conflicts using a conflict graph approach.

        If A conflicts with B and B conflicts with C, check whether
        A indirectly conflicts with C (transitive closure).
        """
        if len(self._rule_cache) < 3:
            return []

        rule_ids = list(self._rule_cache.keys())
        n = len(rule_ids)
        conflict_matrix: List[List[float]] = [[0.0] * n for _ in range(n)]

        for i in range(n):
            for j in range(i + 1, n):
                conflict = self._check_pair_conflict(rule_ids[i], rule_ids[j])
                if conflict is not None:
                    conflict_matrix[i][j] = conflict.overlap_score
                    conflict_matrix[j][i] = conflict.overlap_score

        transitive_conflicts: List[ConflictMatch] = []
        threshold = self._config.min_overlap_threshold

        for k in range(n):
            for i in range(n):
                for j in range(n):
                    if i != j and conflict_matrix[i][k] > 0 and conflict_matrix[k][j] > 0:
                        transitive_score = min(conflict_matrix[i][k], conflict_matrix[k][j])
                        if conflict_matrix[i][j] == 0 and transitive_score >= threshold:
                            direct = self._check_pair_conflict(rule_ids[i], rule_ids[j])
                            if direct is None or direct.overlap_score < transitive_score * 0.5:
                                adjusted_score = round(transitive_score * 0.8, 4)
                                transitive_conflicts.append(ConflictMatch(
                                    conflict_id=str(uuid.uuid4()),
                                    rule_a=rule_ids[i],
                                    rule_b=rule_ids[j],
                                    category=PatternConflictCategory.TRANSITIVE_CONFLICT,
                                    overlap_score=adjusted_score,
                                    severity=ConflictSeverity.MEDIUM,
                                    description=(
                                        f"Transitive conflict between {rule_ids[i]} and "
                                        f"{rule_ids[j]} via intermediate rules"
                                    ),
                                    overlapping_elements=[
                                        f"transitive_path:{rule_ids[i]}->{rule_ids[k]}->{rule_ids[j]}",
                                    ],
                                    detected_at=datetime.utcnow(),
                                ))
                                conflict_matrix[i][j] = adjusted_score
                                conflict_matrix[j][i] = adjusted_score

        return transitive_conflicts

    # ------------------------------------------------------------------
    # Circular Conflict Detection
    # ------------------------------------------------------------------

    def _detect_circular_conflicts(self) -> List[ConflictMatch]:
        """
        Detect circular conflict patterns where three or more rules
        form a conflict cycle (A->B, B->C, C->A).
        """
        if len(self._rule_cache) < 3:
            return []

        rule_ids = list(self._rule_cache.keys())
        pairs: Dict[Tuple[str, str], float] = {}

        for i in range(len(rule_ids)):
            for j in range(i + 1, len(rule_ids)):
                conflict = self._check_pair_conflict(rule_ids[i], rule_ids[j])
                if conflict is not None and conflict.overlap_score >= self._config.min_overlap_threshold:
                    pairs[(rule_ids[i], rule_ids[j])] = conflict.overlap_score

        circular_conflicts: List[ConflictMatch] = []
        visited_cycles: Set[Tuple[str, ...]] = set()

        for a, b in pairs:
            for c, d in pairs:
                if b == c and a < d:
                    pair_ad = (a, d) if a < d else (d, a)
                    if pair_ad in pairs:
                        cycle_key = tuple(sorted([a, b, d]))
                        if cycle_key in visited_cycles:
                            continue
                        visited_cycles.add(cycle_key)
                        cycle_score = (pairs[(a, b)] + pairs[(b, d)] + pairs[pair_ad]) / 3
                        circular_conflicts.append(ConflictMatch(
                            conflict_id=str(uuid.uuid4()),
                            rule_a=a,
                            rule_b=d,
                            category=PatternConflictCategory.CIRCULAR_CONFLICT,
                            overlap_score=round(cycle_score, 4),
                            severity=ConflictSeverity.HIGH,
                            description=(
                                f"Circular conflict detected among rules: {a}, {b}, {d}"
                            ),
                            overlapping_elements=[f"cycle:{a}->{b}->{d}->{a}"],
                            detected_at=datetime.utcnow(),
                        ))

        return circular_conflicts

    # ------------------------------------------------------------------
    # Generic Overlap Detection Helper
    # ------------------------------------------------------------------

    def _detect_overlap_by_extractor(
        self,
        category: PatternConflictCategory,
        extractor: Callable[[Rule], List[str]],
        weight: float,
    ) -> List[ConflictMatch]:
        """
        Generic pairwise overlap detection using a provided extractor function.

        Args:
            category: Conflict category to assign to matches.
            extractor: Function that extracts pattern strings from a Rule.
            weight: Weight multiplier for this overlap type.

        Returns:
            List of detected ConflictMatch objects.
        """
        conflicts: List[ConflictMatch] = []
        rule_ids = list(self._rule_cache.keys())
        effective_threshold = self._config.min_overlap_threshold * weight

        for i in range(len(rule_ids)):
            for j in range(i + 1, len(rule_ids)):
                rule_a = self._rule_cache[rule_ids[i]]
                rule_b = self._rule_cache[rule_ids[j]]
                patterns_a = set(extractor(rule_a))
                patterns_b = set(extractor(rule_b))
                common = patterns_a & patterns_b

                if not common:
                    continue

                union_size = max(len(patterns_a | patterns_b), 1)
                score = len(common) / union_size * weight

                if score >= effective_threshold:
                    conflicts.append(ConflictMatch(
                        conflict_id=str(uuid.uuid4()),
                        rule_a=rule_a.id,
                        rule_b=rule_b.id,
                        category=category,
                        overlap_score=round(score, 4),
                        severity=self._compute_severity(score, rule_a, rule_b),
                        description=(
                            f"{category.value.replace('_', ' ').title()} "
                            f"between '{rule_a.name}' and '{rule_b.name}'"
                        ),
                        overlapping_elements=sorted(common),
                        detected_at=datetime.utcnow(),
                    ))

        return conflicts

    # ------------------------------------------------------------------
    # Metrics & Scoring
    # ------------------------------------------------------------------

    def compute_overlap_score(self, rule_a: Rule, rule_b: Rule) -> float:
        """Compute a composite overlap score between two rules."""
        score = 0.0

        keywords_a = set(self._get_keywords(rule_a))
        keywords_b = set(self._get_keywords(rule_b))
        if keywords_a and keywords_b:
            jaccard = len(keywords_a & keywords_b) / len(keywords_a | keywords_b)
            score += jaccard * self._config.keyword_weight

        regexes_a = set(self._get_regexes(rule_a))
        regexes_b = set(self._get_regexes(rule_b))
        if regexes_a and regexes_b:
            jaccard = len(regexes_a & regexes_b) / len(regexes_a | regexes_b)
            score += jaccard * self._config.regex_weight

        return round(min(score, 1.0), 4)

    def compute_conflict_impact(self, conflict: ConflictMatch) -> float:
        """
        Compute impact score of a conflict based on overlap score,
        rule severities, and rule tiers.
        """
        impact = conflict.overlap_score
        rule_a = self._rule_cache.get(conflict.rule_a)
        rule_b = self._rule_cache.get(conflict.rule_b)
        if rule_a:
            impact *= self._TIER_MULTIPLIERS.get(rule_a.tier, 1.0)
        if rule_b:
            impact *= self._TIER_MULTIPLIERS.get(rule_b.tier, 1.0)
        return round(min(impact, 1.0), 4)

    def compute_pairwise_conflict_matrix(self) -> Dict[str, Dict[str, float]]:
        """
        Compute a full pairwise conflict score matrix for all registered rules.

        Returns:
            Nested dict: {rule_id: {other_rule_id: overlap_score}}.
        """
        matrix: Dict[str, Dict[str, float]] = {}
        rule_ids = list(self._rule_cache.keys())
        for rid in rule_ids:
            matrix[rid] = {}
        for i in range(len(rule_ids)):
            for j in range(i + 1, len(rule_ids)):
                a, b = rule_ids[i], rule_ids[j]
                r_a, r_b = self._rule_cache[a], self._rule_cache[b]
                score = self.compute_overlap_score(r_a, r_b)
                matrix[a][b] = score
                matrix[b][a] = score
        return matrix

    # ------------------------------------------------------------------
    # Conflict Clustering
    # ------------------------------------------------------------------

    def cluster_conflicts(self) -> List[ConflictCluster]:
        """
        Group related conflicts into clusters based on shared rules.

        Two conflicts are clustered together if they share at least one
        common rule.
        """
        if not self._conflicts:
            return []

        conflict_list = list(self._conflicts.values())
        clusters: List[List[ConflictMatch]] = []
        assigned: Set[str] = set()

        for conflict in conflict_list:
            if conflict.conflict_id in assigned:
                continue
            cluster = [conflict]
            assigned.add(conflict.conflict_id)
            shared_rules = {conflict.rule_a, conflict.rule_b}

            for other in conflict_list:
                if other.conflict_id in assigned:
                    continue
                other_rules = {other.rule_a, other.rule_b}
                if shared_rules & other_rules:
                    cluster.append(other)
                    assigned.add(other.conflict_id)
                    shared_rules |= other_rules
                    if len(shared_rules) > self._config.max_rules_per_cluster:
                        break

            clusters.append(cluster)

        result: List[ConflictCluster] = []
        for idx, cluster in enumerate(clusters):
            affected = list({c.rule_a for c in cluster} | {c.rule_b for c in cluster})
            scores = [c.overlap_score for c in cluster]
            avg_score = float(np.mean(scores)) if scores else 0.0
            root_cause = self._identify_root_cause(cluster)

            cluster_obj = ConflictCluster(
                cluster_id=f"cc_{idx:04d}",
                conflict_ids=[c.conflict_id for c in cluster],
                root_cause=root_cause,
                affected_rules=affected,
                average_overlap_score=round(avg_score, 4),
                total_conflicts=len(cluster),
                detected_at=datetime.utcnow(),
            )
            result.append(cluster_obj)
            self._clusters[cluster_obj.cluster_id] = cluster_obj

        logger.info("Formed %d conflict clusters from %d conflicts", len(result), len(conflict_list))
        return result

    @staticmethod
    def _identify_root_cause(cluster: List[ConflictMatch]) -> str:
        """Identify the most frequent conflict category in a cluster as root cause."""
        categories: Dict[str, int] = defaultdict(int)
        for c in cluster:
            categories[c.category.value] += 1
        if not categories:
            return "unknown"
        return max(categories, key=categories.get)

    # ------------------------------------------------------------------
    # Historical Analysis
    # ------------------------------------------------------------------

    def analyze_history(self, days: Optional[int] = None) -> List[ConflictTrend]:
        """
        Analyze historical conflict data for trends and repeat offenders.

        Args:
            days: Lookback window (defaults to config.history_window_days).

        Returns:
            List of ConflictTrend objects, one per conflict category.
        """
        window = days if days is not None else self._config.history_window_days
        cutoff = datetime.utcnow() - timedelta(days=window)
        relevant = [c for c in self._history if c.detected_at >= cutoff]

        if not relevant:
            return []

        by_category: Dict[str, List[ConflictMatch]] = defaultdict(list)
        for conflict in relevant:
            by_category[conflict.category.value].append(conflict)

        trends: List[ConflictTrend] = []
        for category_name, conflicts in by_category.items():
            if len(conflicts) < self._config.min_trend_data_points:
                continue

            severity_dist: Dict[str, int] = defaultdict(int)
            for c in conflicts:
                severity_dist[c.severity.value] += 1

            direction = self._detect_trend_direction(conflicts)

            offender_counts: Dict[str, int] = defaultdict(int)
            for c in conflicts:
                offender_counts[c.rule_a] += 1
                offender_counts[c.rule_b] += 1

            repeat_offenders = [
                {"rule_id": rule, "count": count, "category": category_name}
                for rule, count in sorted(offender_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            ]

            trends.append(ConflictTrend(
                trend_id=f"trend_{category_name}",
                pattern_name=f"{category_name}_trend",
                time_period=f"{window}d",
                conflict_count=len(conflicts),
                trend_direction=direction,
                severity_distribution=dict(severity_dist),
                repeat_offenders=repeat_offenders,
            ))

        return trends

    @staticmethod
    def _detect_trend_direction(conflicts: List[ConflictMatch]) -> str:
        """Detect whether conflict frequency is increasing, decreasing, or stable."""
        if len(conflicts) < 4:
            return "stable"

        mid = len(conflicts) // 2
        first_half_count = len(conflicts[:mid])
        second_half_count = len(conflicts[mid:])

        avg_first = first_half_count / max(mid, 1)
        avg_second = second_half_count / max(len(conflicts) - mid, 1)

        if avg_second > avg_first * 1.2:
            return "increasing"
        if avg_second < avg_first * 0.8:
            return "decreasing"
        return "stable"

    def get_repeat_offenders(self, min_offenses: int = 3) -> List[Dict[str, Any]]:
        """Identify rules that frequently appear in conflicts."""
        counts: Dict[str, int] = defaultdict(int)
        for conflict in self._history:
            counts[conflict.rule_a] += 1
            counts[conflict.rule_b] += 1
        return [
            {"rule_id": rule, "offense_count": count}
            for rule, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)
            if count >= min_offenses
        ]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_conflicts_by_rule(self, rule_id: str) -> List[ConflictMatch]:
        """Get all conflicts involving a specific rule."""
        return [
            c for c in self._conflicts.values()
            if c.rule_a == rule_id or c.rule_b == rule_id
        ]

    def get_unresolved_conflicts(self) -> List[ConflictMatch]:
        """Get all unresolved conflicts."""
        return [c for c in self._conflicts.values() if not c.resolved]

    def get_conflicts_by_severity(self, severity: ConflictSeverity) -> List[ConflictMatch]:
        """Get conflicts filtered by severity level."""
        return [c for c in self._conflicts.values() if c.severity == severity]

    def get_conflicts_by_category(self, category: PatternConflictCategory) -> List[ConflictMatch]:
        """Get conflicts filtered by pattern category."""
        return [c for c in self._conflicts.values() if c.category == category]

    def get_high_impact_conflicts(self, threshold: float = 0.7) -> List[Dict[str, Any]]:
        """
        Get conflicts with impact score above threshold, sorted descending.
        """
        high_impact: List[Dict[str, Any]] = []
        for conflict in self._conflicts.values():
            impact = self.compute_conflict_impact(conflict)
            if impact >= threshold:
                high_impact.append({
                    "conflict_id": conflict.conflict_id,
                    "rule_a": conflict.rule_a,
                    "rule_b": conflict.rule_b,
                    "category": conflict.category.value,
                    "overlap_score": conflict.overlap_score,
                    "impact": impact,
                    "severity": conflict.severity.value,
                })
        return sorted(high_impact, key=lambda x: x["impact"], reverse=True)

    # ------------------------------------------------------------------
    # Statistics & Export
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about detected conflicts."""
        by_category: Dict[str, int] = defaultdict(int)
        by_severity: Dict[str, int] = defaultdict(int)
        for c in self._conflicts.values():
            by_category[c.category.value] += 1
            by_severity[c.severity.value] += 1
        return {
            "total_conflicts": len(self._conflicts),
            "conflicts_by_category": dict(by_category),
            "conflicts_by_severity": dict(by_severity),
            "unresolved_count": len(self.get_unresolved_conflicts()),
            "cluster_count": len(self._clusters),
            "total_history_entries": len(self._history),
            "registered_rules": len(self._rule_cache),
            "repeat_offender_count": len(self.get_repeat_offenders()),
            "pairwise_conflict_count": len(self.compute_pairwise_conflict_matrix()) if self._rule_cache else 0,
            "config": self._config.to_dict(),
        }

    def export_data(self, max_history: int = 1000) -> Dict[str, Any]:
        """Export all conflict data for external consumption."""
        return {
            "config": self._config.to_dict(),
            "conflicts": [c.to_dict() for c in self._conflicts.values()],
            "clusters": [c.to_dict() for c in self._clusters.values()],
            "history": [c.to_dict() for c in self._history[-max_history:]],
            "stats": self.get_stats(),
        }

    def reset(self) -> None:
        """Reset all detector state."""
        self._conflicts.clear()
        self._clusters.clear()
        self._history.clear()
        self._rule_cache.clear()
        logger.info("ConflictPatternDetector reset to initial state")

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _check_pair_conflict(self, rule_id_a: str, rule_id_b: str) -> Optional[ConflictMatch]:
        """Check if two registered rules have a direct conflict."""
        rule_a = self._rule_cache.get(rule_id_a)
        rule_b = self._rule_cache.get(rule_id_b)
        if rule_a is None or rule_b is None:
            return None
        return self.detect_direct_overlap(rule_a, rule_b)

    @staticmethod
    def _get_keywords(rule: Rule) -> List[str]:
        """Extract unique keywords from all patterns in a rule."""
        keywords: Set[str] = set()
        for pattern in rule.patterns:
            keywords.update(pattern.keywords)
        return sorted(keywords)

    @staticmethod
    def _get_regexes(rule: Rule) -> List[str]:
        """Extract unique regex patterns from all patterns in a rule."""
        regexes: Set[str] = set()
        for pattern in rule.patterns:
            regexes.update(pattern.regex_patterns)
        return sorted(regexes)

    def _compute_severity(self, score: float, rule_a: Rule, rule_b: Rule) -> ConflictSeverity:
        """
        Compute conflict severity from overlap score and participating rule severities.
        """
        max_rule_severity = max(
            self._SEVERITY_ORDER.get(rule_a.severity.value, 2),
            self._SEVERITY_ORDER.get(rule_b.severity.value, 2),
        )
        if score >= 0.8 or max_rule_severity >= 4:
            return ConflictSeverity.CRITICAL
        if score >= 0.6 or max_rule_severity >= 3:
            return ConflictSeverity.HIGH
        if score >= 0.4:
            return ConflictSeverity.MEDIUM
        return ConflictSeverity.LOW

    @staticmethod
    def _build_conflict_description(
        rule_a: Rule, rule_b: Rule, elements: List[str], score: float,
    ) -> str:
        """Build a human-readable description of a conflict."""
        overlap_types = set(e.split(":")[0] for e in elements)
        return (
            f"Conflict between '{rule_a.name}' ({rule_a.id}) and "
            f"'{rule_b.name}' ({rule_b.id}). "
            f"Overlap types: {', '.join(sorted(overlap_types))}. "
            f"Overlap score: {score:.2f}"
        )

    @staticmethod
    def _select_dominant_category(categories: List[PatternConflictCategory]) -> PatternConflictCategory:
        """Select the dominant category based on a priority ordering."""
        for cat in ConflictPatternDetector._CATEGORY_PRIORITY:
            if cat in categories:
                return cat
        return PatternConflictCategory.KEYWORD_OVERLAP
