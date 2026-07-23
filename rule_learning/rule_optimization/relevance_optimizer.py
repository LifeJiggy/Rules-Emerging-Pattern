"""
Relevance optimizer for rule evaluation.

Provides relevance scoring for rules based on context matching, pruning
of low-relevance rules, context-driven relevance prediction, relevance
decay over time, user-specific relevance profiles, and a feedback loop
for continuous improvement.
"""

import logging
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from rules_emerging_pattern.models.rule import (
    Rule,
    RuleSet,
    RuleContext,
    RuleType,
    RuleTier,
    RuleStatus,
    RuleSeverity,
)

logger = logging.getLogger(__name__)


class RelevanceAction(str, Enum):
    """Actions that can be taken based on relevance scores."""
    KEEP_ACTIVE = "keep_active"
    DEPRECATE = "deprecate"
    ARCHIVE = "archive"
    DEACTIVATE = "deactivate"
    REVIEW = "review"
    PROMOTE = "promote"


class RelevanceTrend(str, Enum):
    """Trend direction for relevance over time."""
    INCREASING = "increasing"
    STABLE = "stable"
    DECREASING = "decreasing"
    VOLATILE = "volatile"
    INSUFFICIENT_DATA = "insufficient_data"


class DecayModel(str, Enum):
    """Decay models for relevance scoring."""
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    LOGARITHMIC = "logarithmic"
    STEP = "step"
    ADAPTIVE = "adaptive"


class ProfileClusterStrategy(str, Enum):
    """Strategies for clustering user profiles."""
    NONE = "none"
    SIMILARITY = "similarity"
    BEHAVIORAL = "behavioral"
    HYBRID = "hybrid"


@dataclass
class RelevanceConfig:
    """Configuration for relevance optimization."""
    relevance_threshold_keep: float = 0.5
    relevance_threshold_deprecate: float = 0.3
    relevance_threshold_archive: float = 0.1
    decay_rate_per_day: float = 0.05
    decay_model: DecayModel = DecayModel.EXPONENTIAL
    decay_acceleration_after_days: int = 30
    decay_linear_slope: float = 0.02
    decay_logarithmic_base: float = 2.0
    decay_step_threshold_days: int = 60
    decay_step_floor: float = 0.2
    feedback_weight: float = 0.3
    context_match_weight: float = 0.4
    usage_frequency_weight: float = 0.3
    semantic_similarity_weight: float = 0.15
    profile_similarity_weight: float = 0.2
    min_evaluations_for_scoring: int = 5
    profile_update_interval_seconds: int = 3600
    decay_check_interval_seconds: int = 86400
    max_profiles_cached: int = 1000
    feedback_positive_boost: float = 0.1
    feedback_negative_penalty: float = 0.2
    scoring_window_days: int = 30
    prediction_confidence_threshold: float = 0.6
    batch_relevance_enabled: bool = True
    max_batch_size: int = 500
    cross_validation_folds: int = 5
    profile_cluster_strategy: ProfileClusterStrategy = ProfileClusterStrategy.NONE
    profile_cluster_similarity_threshold: float = 0.8
    profile_merge_enabled: bool = True
    explanation_detail_level: int = 2
    heatmap_resolution_days: int = 7
    archive_after_days_unused: int = 90


@dataclass
class RelevanceScore:
    """Breakdown of a relevance score."""
    overall: float
    context_match: float
    usage_frequency: float
    decay_factor: float
    feedback_adjustment: float
    profile_similarity: float
    semantic_similarity: float
    cross_validated_score: Optional[float] = None
    confidence: float
    trend: RelevanceTrend
    suggested_action: RelevanceAction
    explanation: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "overall": round(self.overall, 4),
            "context_match": round(self.context_match, 4),
            "usage_frequency": round(self.usage_frequency, 4),
            "decay_factor": round(self.decay_factor, 4),
            "feedback_adjustment": round(self.feedback_adjustment, 4),
            "profile_similarity": round(self.profile_similarity, 4),
            "semantic_similarity": round(self.semantic_similarity, 4),
            "confidence": round(self.confidence, 4),
            "trend": self.trend.value,
            "suggested_action": self.suggested_action.value,
        }
        if self.cross_validated_score is not None:
            result["cross_validated_score"] = round(self.cross_validated_score, 4)
        if self.explanation:
            result["explanation"] = self.explanation
        return result


@dataclass
class UserRelevanceProfile:
    """Relevance profile for a specific user."""
    user_id: str
    preferred_rule_types: Dict[str, float] = field(default_factory=dict)
    preferred_tiers: Dict[str, float] = field(default_factory=dict)
    context_fingerprints: List[str] = field(default_factory=list)
    rule_affinity_scores: Dict[str, float] = field(default_factory=dict)
    domain_preferences: Dict[str, float] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    total_evaluations: int = 0
    positive_feedback_count: int = 0
    negative_feedback_count: int = 0
    cluster_id: Optional[str] = None


@dataclass
class FeedbackEntry:
    """A single relevance feedback entry."""
    rule_id: str
    user_id: str
    context_id: str
    was_relevant: bool
    timestamp: datetime = field(default_factory=datetime.utcnow)
    user_rating: Optional[float] = None
    context_snapshot: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


@dataclass
class RelevanceHeatmapCell:
    """A cell in the relevance heatmap."""
    rule_id: str
    time_bucket: str
    average_score: float
    evaluation_count: int
    trend: str


class RelevanceOptimizer:
    """Optimize rule relevance through scoring, pruning, and profiling.

    Scores rules based on context match, usage frequency, decay over time,
    and user-specific profiles. Prunes low-relevance rules through
    deactivation, deprecation, or archiving. Maintains user-specific
    relevance profiles and incorporates feedback for continuous
    improvement of relevance predictions. Supports semantic similarity
    scoring, batch relevance updates, cross-validation, and explanation
    generation.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = RelevanceConfig(**(config or {}))
        self.relevance_scores: Dict[str, RelevanceScore] = {}
        self.user_profiles: Dict[str, UserRelevanceProfile] = {}
        self.feedback_log: List[FeedbackEntry] = []
        self.rule_usage_counts: Dict[str, int] = defaultdict(int)
        self.context_match_cache: Dict[str, float] = {}
        self.semantic_similarity_cache: Dict[str, float] = {}
        self.pruning_history: Dict[str, Dict[str, Any]] = {}
        self.decay_tracker: Dict[str, datetime] = {}
        self.relevance_history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=200)
        )
        self.cross_validation_scores: Dict[str, List[float]] = defaultdict(list)
        self.heatmap_cache: Dict[str, List[RelevanceHeatmapCell]] = {}
        self.profile_clusters: Dict[str, List[str]] = defaultdict(list)
        self._last_profile_update: datetime = datetime.utcnow()
        self._last_decay_check: datetime = datetime.utcnow()
        self._last_cluster_check: datetime = datetime.utcnow()

    def score_relevance(
        self,
        rule: Rule,
        context: Optional[RuleContext] = None,
        user_id: Optional[str] = None,
        generate_explanation: bool = False,
    ) -> RelevanceScore:
        """Compute a comprehensive relevance score for a rule.

        Combines context matching, usage frequency, decay, profile
        similarity, semantic similarity, and feedback into a single
        relevance score. Optionally generates an explanation of the
        contributing factors.
        """
        context_score = self._score_context_match(rule, context)
        usage_score = self._score_usage_frequency(rule)
        decay_factor = self._compute_decay_factor(rule)
        profile_score = self._score_profile_similarity(rule, user_id)
        semantic_score = self._score_semantic_similarity(rule, context)
        feedback_adj = self._compute_feedback_adjustment(rule.id, user_id)

        confidence = self._estimate_confidence(rule.id)
        trend = self._determine_trend(rule.id)

        semantic_weight = self.config.semantic_similarity_weight if semantic_score > 0 else 0.0
        total_weight = (
            self.config.context_match_weight
            + self.config.usage_frequency_weight
            + self.config.profile_similarity_weight
            + semantic_weight
        )

        if total_weight > 0:
            normalized = (
                context_score * self.config.context_match_weight
                + usage_score * self.config.usage_frequency_weight
                + profile_score * self.config.profile_similarity_weight
                + semantic_score * semantic_weight
            ) / total_weight
        else:
            normalized = 0.5

        overall = normalized * decay_factor + feedback_adj
        overall = max(0.0, min(1.0, overall))
        suggested_action = self._suggest_action(overall)

        cross_val = self._cross_validate_relevance(rule.id) if self.config.batch_relevance_enabled else None

        explanation = None
        if generate_explanation:
            explanation = self._generate_explanation(
                rule, context_score, usage_score, decay_factor,
                profile_score, semantic_score, feedback_adj, overall,
            )

        score = RelevanceScore(
            overall=overall,
            context_match=context_score,
            usage_frequency=usage_score,
            decay_factor=decay_factor,
            feedback_adjustment=feedback_adj,
            profile_similarity=profile_score,
            semantic_similarity=semantic_score,
            cross_validated_score=cross_val,
            confidence=confidence,
            trend=trend,
            suggested_action=suggested_action,
            explanation=explanation,
        )

        self.relevance_scores[rule.id] = score
        self.relevance_history[rule.id].append({
            "timestamp": datetime.utcnow().isoformat(),
            "score": overall,
            "action": suggested_action.value,
        })

        return score

    def _score_context_match(
        self,
        rule: Rule,
        context: Optional[RuleContext],
    ) -> float:
        """Score how well a rule matches the given context (0.0 to 1.0)."""
        if context is None:
            return 0.5

        cache_key = f"{rule.id}:{context.user_id}:{context.domain}:{context.user_role}"
        if cache_key in self.context_match_cache:
            return self.context_match_cache[cache_key]

        match_score = 0.0
        total_checks = 0.0

        if context.domain:
            total_checks += 1.0
            rule_domains = [tag for tag in rule.tags if tag.startswith("domain:")]
            if rule_domains:
                if any(tag.split(":", 1)[1].lower() == context.domain.lower() for tag in rule_domains):
                    match_score += 1.0
            else:
                match_score += 0.5

        if context.user_role:
            total_checks += 1.0
            rule_roles = [tag for tag in rule.tags if tag.startswith("role:")]
            if rule_roles:
                if any(tag.split(":", 1)[1] == context.user_role for tag in rule_roles):
                    match_score += 1.0
            else:
                match_score += 0.5

        if context.content_type:
            total_checks += 1.0
            rule_types = [tag for tag in rule.tags if tag.startswith("content_type:")]
            if rule_types:
                if any(tag.split(":", 1)[1] == context.content_type for tag in rule_types):
                    match_score += 1.0
            else:
                match_score += 0.5

        if context.organization:
            total_checks += 1.0
            org_tags = [tag for tag in rule.tags if tag.startswith("org:")]
            if org_tags:
                if any(tag.split(":", 1)[1].lower() == context.organization.lower() for tag in org_tags):
                    match_score += 1.0
            else:
                match_score += 0.5

        if total_checks == 0:
            self.context_match_cache[cache_key] = 0.5
            return 0.5

        result = match_score / total_checks
        if len(self.context_match_cache) < 10000:
            self.context_match_cache[cache_key] = result
        return result

    def _score_semantic_similarity(
        self,
        rule: Rule,
        context: Optional[RuleContext],
    ) -> float:
        """Score semantic similarity between rule tags and context (0.0 to 1.0)."""
        if context is None:
            return 0.0

        cache_key = f"sem:{rule.id}:{context.user_id}:{context.domain}"
        if cache_key in self.semantic_similarity_cache:
            return self.semantic_similarity_cache[cache_key]

        score = 0.0
        matches = 0

        for tag in rule.tags:
            tag_lower = tag.lower()
            if context.domain and context.domain.lower() in tag_lower:
                score += 0.3
                matches += 1
            if context.content_type and context.content_type.lower() in tag_lower:
                score += 0.3
                matches += 1
            if context.organization and context.organization.lower() in tag_lower:
                score += 0.2
                matches += 1
            if context.user_role and context.user_role.lower() in tag_lower:
                score += 0.2
                matches += 1

        if matches == 0:
            self.semantic_similarity_cache[cache_key] = 0.0
            return 0.0

        result = min(1.0, score / matches)
        if len(self.semantic_similarity_cache) < 5000:
            self.semantic_similarity_cache[cache_key] = result
        return result

    def _score_usage_frequency(self, rule: Rule) -> float:
        """Score based on how frequently a rule has been used recently."""
        count = self.rule_usage_counts.get(rule.id, 0)
        if count == 0:
            return 0.0

        max_count = max(self.rule_usage_counts.values()) if self.rule_usage_counts else 1
        return min(1.0, count / max(max_count, 1))

    def _compute_decay_factor(self, rule: Rule) -> float:
        """Compute a decay factor based on time since last use.

        Supports multiple decay models: exponential, linear, logarithmic,
        step, and adaptive.
        """
        last_used = self.decay_tracker.get(rule.id)
        if last_used is None:
            return 1.0

        days_since = (datetime.utcnow() - last_used).total_seconds() / 86400.0
        if days_since <= 0:
            return 1.0

        model = self.config.decay_model

        if model == DecayModel.LINEAR:
            decay = max(0.0, 1.0 - self.config.decay_linear_slope * days_since)
        elif model == DecayModel.LOGARITHMIC:
            decay = max(0.0, 1.0 - math.log(1 + days_since, self.config.decay_logarithmic_base) * 0.1)
        elif model == DecayModel.STEP:
            if days_since > self.config.decay_step_threshold_days:
                decay = self.config.decay_step_floor
            else:
                decay = 1.0 - (days_since / self.config.decay_step_threshold_days) * (1 - self.config.decay_step_floor)
        elif model == DecayModel.ADAPTIVE:
            base_decay = math.exp(-self.config.decay_rate_per_day * days_since)
            usage_freq = self.rule_usage_counts.get(rule.id, 0) / max(days_since, 1)
            acceleration = max(0.5, 1.0 - usage_freq * 0.1)
            decay = math.exp(-self.config.decay_rate_per_day * days_since * acceleration)
        else:
            decay = math.exp(-self.config.decay_rate_per_day * days_since)
            if days_since > self.config.decay_acceleration_after_days:
                extra_days = days_since - self.config.decay_acceleration_after_days
                decay *= math.exp(-self.config.decay_rate_per_day * 2 * extra_days)

        return max(0.01, decay)

    def _score_profile_similarity(
        self,
        rule: Rule,
        user_id: Optional[str],
    ) -> float:
        """Score how well a rule matches a user's relevance profile."""
        if user_id is None or user_id not in self.user_profiles:
            return 0.5

        profile = self.user_profiles[user_id]
        score = 0.0
        total_weights = 0.0

        type_key = rule.rule_type.value
        if type_key in profile.preferred_rule_types:
            score += profile.preferred_rule_types[type_key] * 0.35
            total_weights += 0.35

        tier_key = rule.tier.value
        if tier_key in profile.preferred_tiers:
            score += profile.preferred_tiers[tier_key] * 0.25
            total_weights += 0.25

        aff_score = profile.rule_affinity_scores.get(rule.id, 0.5)
        score += aff_score * 0.25
        total_weights += 0.25

        if rule.patterns:
            domain_tags = [tag for tag in rule.tags if tag.startswith("domain:")]
            for tag in domain_tags:
                domain = tag.split(":", 1)[1].lower()
                if domain in profile.domain_preferences:
                    score += profile.domain_preferences[domain] * 0.15
                    total_weights += 0.15
                    break

        if total_weights == 0:
            return 0.5

        return score / total_weights

    def _compute_feedback_adjustment(
        self,
        rule_id: str,
        user_id: Optional[str],
    ) -> float:
        """Compute relevance adjustment based on user feedback."""
        relevant_feedback = [
            entry for entry in self.feedback_log
            if entry.rule_id == rule_id
            and (user_id is None or entry.user_id == user_id)
        ]

        if not relevant_feedback:
            return 0.0

        recent = relevant_feedback[-50:]
        positive = sum(1 for e in recent if e.was_relevant)
        negative = sum(1 for e in recent if not e.was_relevant)
        total = positive + negative

        if total == 0:
            return 0.0

        recency_weighted = 0.0
        weight_sum = 0.0
        now = datetime.utcnow()
        for entry in recent:
            hours_ago = (now - entry.timestamp).total_seconds() / 3600
            weight = math.exp(-hours_ago / 72)
            recency_weighted += (1.0 if entry.was_relevant else -1.0) * weight
            weight_sum += weight

        if weight_sum > 0:
            net = recency_weighted / weight_sum
        else:
            net = (positive - negative) / total

        return net * self.config.feedback_weight

    def _estimate_confidence(self, rule_id: str) -> float:
        """Estimate confidence in the relevance score (0.0 to 1.0)."""
        total = self.rule_usage_counts.get(rule_id, 0)
        if total < self.config.min_evaluations_for_scoring:
            return total / self.config.min_evaluations_for_scoring

        return min(1.0, 0.5 + (total / (total + 100)) * 0.5)

    def _determine_trend(self, rule_id: str) -> RelevanceTrend:
        """Determine the relevance trend direction for a rule."""
        scores = [
            entry for entry in self.feedback_log
            if entry.rule_id == rule_id
        ]

        if len(scores) < 5:
            return RelevanceTrend.INSUFFICIENT_DATA

        recent = scores[-10:]
        positive_ratio = sum(1 for e in recent if e.was_relevant) / len(recent)

        early = scores[:5]
        early_ratio = sum(1 for e in early if e.was_relevant) / len(early)
        late_ratio = sum(1 for e in scores[-5:] if e.was_relevant) / len(scores[-5:])

        difference = late_ratio - early_ratio

        if positive_ratio > 0.8:
            return RelevanceTrend.INCREASING if difference > 0 else RelevanceTrend.STABLE
        if positive_ratio < 0.3:
            return RelevanceTrend.DECREASING if difference < 0 else RelevanceTrend.STABLE

        if abs(difference) < 0.1:
            return RelevanceTrend.STABLE
        if difference > 0:
            return RelevanceTrend.INCREASING

        return RelevanceTrend.DECREASING

    def _suggest_action(self, score: float) -> RelevanceAction:
        """Determine the suggested action based on relevance score."""
        if score >= self.config.relevance_threshold_keep:
            if score >= 0.8:
                return RelevanceAction.PROMOTE
            return RelevanceAction.KEEP_ACTIVE
        if score >= self.config.relevance_threshold_deprecate:
            return RelevanceAction.REVIEW
        if score >= self.config.relevance_threshold_archive:
            return RelevanceAction.DEPRECATE
        return RelevanceAction.ARCHIVE

    def _generate_explanation(
        self,
        rule: Rule,
        context_score: float,
        usage_score: float,
        decay_factor: float,
        profile_score: float,
        semantic_score: float,
        feedback_adj: float,
        overall: float,
    ) -> Dict[str, Any]:
        """Generate a human-readable explanation of the relevance score."""
        factors: List[Dict[str, Any]] = []

        factors.append({
            "factor": "context_match",
            "value": round(context_score, 4),
            "weight": self.config.context_match_weight,
            "contribution": round(context_score * self.config.context_match_weight, 4),
        })
        factors.append({
            "factor": "usage_frequency",
            "value": round(usage_score, 4),
            "weight": self.config.usage_frequency_weight,
            "contribution": round(usage_score * self.config.usage_frequency_weight, 4),
        })
        factors.append({
            "factor": "profile_similarity",
            "value": round(profile_score, 4),
            "weight": self.config.profile_similarity_weight,
            "contribution": round(profile_score * self.config.profile_similarity_weight, 4),
        })
        if semantic_score > 0:
            factors.append({
                "factor": "semantic_similarity",
                "value": round(semantic_score, 4),
                "weight": self.config.semantic_similarity_weight,
                "contribution": round(semantic_score * self.config.semantic_similarity_weight, 4),
            })

        factors.sort(key=lambda f: f["contribution"], reverse=True)

        dominant_factor = factors[0]["factor"] if factors else "unknown"
        if decay_factor < 0.5:
            dominant_penalty = "decay"

        return {
            "overall_score": round(overall, 4),
            "decay_factor": round(decay_factor, 4),
            "feedback_adjustment": round(feedback_adj, 4),
            "dominant_factor": dominant_factor,
            "factors": factors,
        }

    def _cross_validate_relevance(self, rule_id: str) -> Optional[float]:
        """Cross-validate relevance score using historical feedback."""
        entries = [
            e for e in self.feedback_log if e.rule_id == rule_id
        ]
        if len(entries) < self.config.cross_validation_folds * 2:
            return None

        scores = []
        fold_size = len(entries) // self.config.cross_validation_folds

        for fold in range(self.config.cross_validation_folds):
            start = fold * fold_size
            end = start + fold_size
            test_set = entries[start:end]
            train_set = entries[:start] + entries[end:]

            if not train_set or not test_set:
                continue

            positive = sum(1 for e in train_set if e.was_relevant)
            accuracy = sum(1 for e in test_set if e.was_relevant == (positive > len(train_set) / 2))
            scores.append(accuracy / max(len(test_set), 1))

        if not scores:
            return None

        avg_score = sum(scores) / len(scores)
        self.cross_validation_scores[rule_id].append(avg_score)
        return round(avg_score, 4)

    def prune_low_relevance_rules(
        self,
        rules: List[Rule],
        context: Optional[RuleContext] = None,
    ) -> Tuple[List[Rule], List[Dict[str, Any]]]:
        """Identify and suggest actions for low-relevance rules.

        Returns (actionable_rules, pruning_decisions).
        """
        pruning_decisions: List[Dict[str, Any]] = []

        for rule in rules:
            score = self.score_relevance(rule, context)
            action = score.suggested_action

            if action in (RelevanceAction.DEPRECATE, RelevanceAction.ARCHIVE, RelevanceAction.DEACTIVATE):
                decision = {
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "current_status": rule.status.value,
                    "relevance_score": score.overall,
                    "suggested_action": action.value,
                    "confidence": score.confidence,
                    "trend": score.trend.value,
                    "reason": f"Relevance score {score.overall:.2f} below threshold for {action.value}",
                    "timestamp": datetime.utcnow().isoformat(),
                    "explanation": score.explanation,
                }
                pruning_decisions.append(decision)
                self.pruning_history[rule.id] = decision

        actionable = [
            rule for rule in rules
            if self.relevance_scores.get(rule.id, None) is not None
            and self.relevance_scores[rule.id].suggested_action
            in (RelevanceAction.DEPRECATE, RelevanceAction.ARCHIVE, RelevanceAction.DEACTIVATE)
        ]

        logger.info(
            "Pruning analysis: %d/%d rules flagged for action",
            len(pruning_decisions), len(rules),
        )

        return actionable, pruning_decisions

    def batch_score_relevance(
        self,
        rules: List[Rule],
        context: Optional[RuleContext] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, RelevanceScore]:
        """Score relevance for a batch of rules efficiently."""
        scores: Dict[str, RelevanceScore] = {}
        batch = rules[:self.config.max_batch_size]

        for rule in batch:
            score = self.score_relevance(rule, context, user_id)
            scores[rule.id] = score

        return scores

    def record_usage(self, rule: Rule, user_id: Optional[str] = None) -> None:
        """Record that a rule was used, updating usage and decay data."""
        self.rule_usage_counts[rule.id] += 1
        self.decay_tracker[rule.id] = datetime.utcnow()

        if user_id and user_id in self.user_profiles:
            profile = self.user_profiles[user_id]
            profile.total_evaluations += 1
            profile.rule_affinity_scores[rule.id] = (
                profile.rule_affinity_scores.get(rule.id, 0.5) * 0.9 + 0.1
            )
            type_key = rule.rule_type.value
            profile.preferred_rule_types[type_key] = (
                profile.preferred_rule_types.get(type_key, 0.5) * 0.95 + 0.05
            )
            tier_key = rule.tier.value
            profile.preferred_tiers[tier_key] = (
                profile.preferred_tiers.get(tier_key, 0.5) * 0.95 + 0.05
            )

            domain_tags = [tag for tag in rule.tags if tag.startswith("domain:")]
            for tag in domain_tags:
                domain = tag.split(":", 1)[1].lower()
                profile.domain_preferences[domain] = (
                    profile.domain_preferences.get(domain, 0.5) * 0.95 + 0.05
                )

    def record_feedback(
        self,
        rule_id: str,
        user_id: str,
        context_id: str,
        was_relevant: bool,
        user_rating: Optional[float] = None,
        context: Optional[RuleContext] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Record user feedback on rule relevance."""
        context_snapshot = context.get_effective_context() if context else None

        entry = FeedbackEntry(
            rule_id=rule_id,
            user_id=user_id,
            context_id=context_id,
            was_relevant=was_relevant,
            user_rating=user_rating,
            context_snapshot=context_snapshot,
            notes=notes,
        )
        self.feedback_log.append(entry)

        if user_id in self.user_profiles:
            profile = self.user_profiles[user_id]
            if was_relevant:
                profile.positive_feedback_count += 1
                profile.rule_affinity_scores[rule_id] = min(
                    1.0,
                    profile.rule_affinity_scores.get(rule_id, 0.5)
                    + self.config.feedback_positive_boost,
                )
            else:
                profile.negative_feedback_count += 1
                profile.rule_affinity_scores[rule_id] = max(
                    0.0,
                    profile.rule_affinity_scores.get(rule_id, 0.5)
                    - self.config.feedback_negative_penalty,
                )

        logger.debug(
            "Feedback recorded: rule=%s user=%s relevant=%s rating=%s",
            rule_id, user_id, was_relevant, user_rating,
        )

    def get_or_create_profile(self, user_id: str) -> UserRelevanceProfile:
        """Get or create a relevance profile for a user."""
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = UserRelevanceProfile(user_id=user_id)
            logger.debug("Created relevance profile for user %s", user_id)

            if len(self.user_profiles) > self.config.max_profiles_cached:
                self._evict_oldest_profile()

        return self.user_profiles[user_id]

    def _evict_oldest_profile(self) -> None:
        """Evict the oldest user profile when cache limit is exceeded."""
        oldest_user = min(
            self.user_profiles.keys(),
            key=lambda uid: self.user_profiles[uid].last_updated,
        )
        del self.user_profiles[oldest_user]
        logger.debug("Evicted oldest profile for user %s", oldest_user)

    def _merge_similar_profiles(self) -> int:
        """Merge similar user profiles to reduce memory usage. Returns merges performed."""
        if not self.config.profile_merge_enabled:
            return 0

        users = list(self.user_profiles.keys())
        merges = 0

        for i in range(len(users)):
            for j in range(i + 1, len(users)):
                if users[j] not in self.user_profiles:
                    continue
                similarity = self._compute_profile_similarity(
                    self.user_profiles[users[i]],
                    self.user_profiles[users[j]],
                )
                if similarity >= self.config.profile_cluster_similarity_threshold:
                    target = self.user_profiles[users[i]]
                    source = self.user_profiles[users[j]]

                    for key, val in source.preferred_rule_types.items():
                        target.preferred_rule_types[key] = (target.preferred_rule_types.get(key, 0.5) + val) / 2
                    for key, val in source.preferred_tiers.items():
                        target.preferred_tiers[key] = (target.preferred_tiers.get(key, 0.5) + val) / 2
                    for key, val in source.rule_affinity_scores.items():
                        target.rule_affinity_scores[key] = (target.rule_affinity_scores.get(key, 0.5) + val) / 2

                    target.total_evaluations += source.total_evaluations
                    target.positive_feedback_count += source.positive_feedback_count
                    target.negative_feedback_count += source.negative_feedback_count
                    target.last_updated = datetime.utcnow()

                    del self.user_profiles[users[j]]
                    merges += 1

        if merges > 0:
            logger.info("Merged %d similar user profiles", merges)
        return merges

    def _compute_profile_similarity(
        self,
        profile_a: UserRelevanceProfile,
        profile_b: UserRelevanceProfile,
    ) -> float:
        """Compute similarity between two user profiles (0.0 to 1.0)."""
        type_keys = set(profile_a.preferred_rule_types.keys()) | set(profile_b.preferred_rule_types.keys())
        if not type_keys:
            return 0.0

        type_sim = sum(
            abs(profile_a.preferred_rule_types.get(k, 0.0) - profile_b.preferred_rule_types.get(k, 0.0))
            for k in type_keys
        ) / len(type_keys)

        return 1.0 - min(1.0, type_sim)

    def predict_relevance(
        self,
        rule: Rule,
        context: Optional[RuleContext],
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Predict future relevance of a rule based on trends and profiles."""
        current_score = self.score_relevance(rule, context, user_id)
        trend = current_score.trend

        if trend == RelevanceTrend.INSUFFICIENT_DATA:
            prediction = current_score.overall
            confidence = 0.3
        elif trend == RelevanceTrend.INCREASING:
            prediction = min(1.0, current_score.overall * 1.1)
            confidence = current_score.confidence * 0.8
        elif trend == RelevanceTrend.DECREASING:
            prediction = max(0.0, current_score.overall * 0.9)
            confidence = current_score.confidence * 0.9
        else:
            prediction = current_score.overall
            confidence = current_score.confidence

        return {
            "rule_id": rule.id,
            "current_score": current_score.overall,
            "predicted_score": round(prediction, 4),
            "confidence": round(confidence, 4),
            "trend": trend.value,
            "days_until_below_threshold": self._estimate_days_until_threshold(
                rule, current_score.overall, trend,
            ),
            "suggested_action": current_score.suggested_action.value,
        }

    def _estimate_days_until_threshold(
        self,
        rule: Rule,
        current_score: float,
        trend: RelevanceTrend,
    ) -> Optional[float]:
        """Estimate days until relevance drops below deprecation threshold."""
        if trend != RelevanceTrend.DECREASING or current_score <= 0:
            return None

        threshold = self.config.relevance_threshold_deprecate
        if current_score <= threshold:
            return 0.0

        daily_decay = self.config.decay_rate_per_day
        if daily_decay <= 0:
            return None

        return math.log(threshold / current_score) / (-daily_decay)

    def apply_decay_to_all(self) -> List[Dict[str, Any]]:
        """Apply relevance decay to all tracked rules. Returns decay events."""
        now = datetime.utcnow()
        if (now - self._last_decay_check).total_seconds() < self.config.decay_check_interval_seconds:
            return []

        self._last_decay_check = now
        decay_events: List[Dict[str, Any]] = []

        for rule_id, last_used in list(self.decay_tracker.items()):
            days_since = (now - last_used).total_seconds() / 86400.0
            if days_since > 0:
                decay_amount = 1.0 - self._compute_decay_factor(
                    Rule(id=rule_id, name="", description="", tier=RuleTier.PREFERENCE,
                         rule_type=RuleType.CUSTOM, severity=RuleSeverity.MEDIUM,
                         enforcement_level="advisory")
                )

                event = {
                    "rule_id": rule_id,
                    "days_since_last_use": round(days_since, 1),
                    "decay_amount": round(decay_amount, 4),
                    "timestamp": now.isoformat(),
                }
                decay_events.append(event)

        return decay_events

    def build_relevance_heatmap(
        self,
        rule_ids: Optional[List[str]] = None,
        days: int = 30,
    ) -> Dict[str, List[RelevanceHeatmapCell]]:
        """Build a relevance heatmap showing score changes over time."""
        bucket_size = timedelta(days=self.config.heatmap_resolution_days)
        heatmap: Dict[str, List[RelevanceHeatmapCell]] = {}

        target_ids = rule_ids or list(self.relevance_scores.keys())
        now = datetime.utcnow()

        for rule_id in target_ids:
            history = list(self.relevance_history.get(rule_id, []))
            if not history:
                continue

            cells: List[RelevanceHeatmapCell] = []
            bucket_start = now - timedelta(days=days)

            while bucket_start < now:
                bucket_end = bucket_start + bucket_size
                bucket_entries = [
                    h for h in history
                    if bucket_start.isoformat() <= h["timestamp"] < bucket_end.isoformat()
                ]

                if bucket_entries:
                    avg = sum(e["score"] for e in bucket_entries) / len(bucket_entries)
                else:
                    avg = 0.0

                cell = RelevanceHeatmapCell(
                    rule_id=rule_id,
                    time_bucket=bucket_start.strftime("%Y-%m-%d"),
                    average_score=round(avg, 4),
                    evaluation_count=len(bucket_entries),
                    trend="stable",
                )
                cells.append(cell)
                bucket_start = bucket_end

            heatmap[rule_id] = cells

        self.heatmap_cache = heatmap
        return heatmap

    def generate_relevance_report(self) -> Dict[str, Any]:
        """Generate a comprehensive relevance report."""
        scores = list(self.relevance_scores.values())
        avg_score = sum(s.overall for s in scores) / len(scores) if scores else 0.0

        action_counts: Dict[str, int] = {action.value: 0 for action in RelevanceAction}
        for s in scores:
            action_counts[s.suggested_action.value] += 1

        trend_counts: Dict[str, int] = {trend.value: 0 for trend in RelevanceTrend}
        for s in scores:
            trend_counts[s.trend.value] += 1

        low_confidence = sum(1 for s in scores if s.confidence < 0.5)
        high_relevance = sum(1 for s in scores if s.overall >= 0.8)
        low_relevance = sum(1 for s in scores if s.overall < self.config.relevance_threshold_deprecate)

        total_feedback = len(self.feedback_log)
        positive_feedback = sum(1 for e in self.feedback_log if e.was_relevant)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_rules_scored": len(self.relevance_scores),
            "average_relevance": round(avg_score, 4),
            "relevance_distribution": action_counts,
            "trend_distribution": trend_counts,
            "high_relevance_rules": high_relevance,
            "low_relevance_rules": low_relevance,
            "low_confidence_scores": low_confidence,
            "total_feedback_entries": total_feedback,
            "positive_feedback_rate": round(
                positive_feedback / total_feedback, 4
            ) if total_feedback > 0 else 0.0,
            "total_user_profiles": len(self.user_profiles),
            "total_pruning_decisions": len(self.pruning_history),
            "decay_model": self.config.decay_model.value,
            "recommended_actions": self._summarize_recommended_actions(),
        }

    def _summarize_recommended_actions(self) -> List[Dict[str, Any]]:
        """Summarize recommended actions based on relevance scoring."""
        actions: List[Dict[str, Any]] = []

        to_archive = [
            (rid, sc) for rid, sc in self.relevance_scores.items()
            if sc.suggested_action == RelevanceAction.ARCHIVE
        ]
        if to_archive:
            actions.append({
                "action": RelevanceAction.ARCHIVE.value,
                "count": len(to_archive),
                "rules": [rid for rid, _ in sorted(to_archive, key=lambda x: x[1].overall)[:10]],
            })

        to_deprecate = [
            (rid, sc) for rid, sc in self.relevance_scores.items()
            if sc.suggested_action == RelevanceAction.DEPRECATE
        ]
        if to_deprecate:
            actions.append({
                "action": RelevanceAction.DEPRECATE.value,
                "count": len(to_deprecate),
                "rules": [rid for rid, _ in sorted(to_deprecate, key=lambda x: x[1].overall)[:10]],
            })

        to_promote = [
            (rid, sc) for rid, sc in self.relevance_scores.items()
            if sc.suggested_action == RelevanceAction.PROMOTE
        ]
        if to_promote:
            actions.append({
                "action": RelevanceAction.PROMOTE.value,
                "count": len(to_promote),
                "rules": [rid for rid, _ in sorted(to_promote, key=lambda x: x[1].overall, reverse=True)[:10]],
            })

        return actions

    def reset_metrics(self) -> None:
        """Reset all accumulated relevance metrics."""
        self.relevance_scores.clear()
        self.user_profiles.clear()
        self.feedback_log.clear()
        self.rule_usage_counts.clear()
        self.context_match_cache.clear()
        self.semantic_similarity_cache.clear()
        self.pruning_history.clear()
        self.decay_tracker.clear()
        self.relevance_history.clear()
        self.cross_validation_scores.clear()
        self.heatmap_cache.clear()
        self.profile_clusters.clear()
        self._last_profile_update = datetime.utcnow()
        self._last_decay_check = datetime.utcnow()
        self._last_cluster_check = datetime.utcnow()
        logger.info("Relevance optimizer metrics reset")

    def purge_rule(self, rule_id: str) -> bool:
        """Remove all tracking data for a specific rule. Returns True if found."""
        found = False

        if rule_id in self.relevance_scores:
            del self.relevance_scores[rule_id]
            found = True

        if rule_id in self.rule_usage_counts:
            del self.rule_usage_counts[rule_id]
            found = True

        if rule_id in self.decay_tracker:
            del self.decay_tracker[rule_id]
            found = True

        if rule_id in self.pruning_history:
            del self.pruning_history[rule_id]
            found = True

        if rule_id in self.relevance_history:
            del self.relevance_history[rule_id]
            found = True

        if rule_id in self.cross_validation_scores:
            del self.cross_validation_scores[rule_id]
            found = True

        if rule_id in self.heatmap_cache:
            del self.heatmap_cache[rule_id]
            found = True

        for profile in self.user_profiles.values():
            if rule_id in profile.rule_affinity_scores:
                del profile.rule_affinity_scores[rule_id]
                found = True

        return found
