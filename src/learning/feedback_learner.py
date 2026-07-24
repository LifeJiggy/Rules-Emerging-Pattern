"""Feedback learning module for adaptive model improvement."""
import copy
import json
import logging
import math
import random
import statistics
import time
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple, Set, Callable, Iterator

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RulePattern

logger = logging.getLogger(__name__)


class FeedbackSource(Enum):
    USER_EXPLICIT = "user_explicit"
    USER_IMPLICIT = "user_implicit"
    SYSTEM_AUTOMATED = "system_automated"
    SYSTEM_VALIDATION = "system_validation"
    CROSS_VALIDATION = "cross_validation"
    CROWD_SOURCED = "crowd_sourced"
    HISTORICAL = "historical"
    SIMULATED = "simulated"


class FeedbackType(Enum):
    CORRECTION = "correction"
    CONFIRMATION = "confirmation"
    REJECTION = "rejection"
    SCORE = "score"
    RANKING = "ranking"
    SUGGESTION = "suggestion"
    FLAG = "flag"
    RATING = "rating"


class FeedbackOutcome(Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class LearningPhase(Enum):
    EXPLORATION = "exploration"
    EXPLOITATION = "exploitation"
    BALANCED = "balanced"
    COOLDOWN = "cooldown"


class ReinforcementStrategy(Enum):
    Q_LEARNING = "q_learning"
    BANDIT = "bandit"
    THOMPSON = "thompson"
    GREEDY = "greedy"


@dataclass
class FeedbackConfig:
    learning_rate: float = 0.1
    discount_factor: float = 0.9
    exploration_rate: float = 0.2
    exploration_decay: float = 0.995
    min_exploration_rate: float = 0.01
    user_explicit_weight: float = 1.0
    user_implicit_weight: float = 0.5
    system_automated_weight: float = 0.3
    system_validation_weight: float = 0.7
    cross_validation_weight: float = 0.8
    crowd_sourced_weight: float = 0.4
    historical_weight: float = 0.2
    simulated_weight: float = 0.1
    recency_decay_hours: float = 72.0
    max_feedback_history: int = 10000
    min_feedback_for_adjustment: int = 5
    feedback_aggregation_window: int = 50
    enable_auto_adjustment: bool = True
    adjustment_cooldown_minutes: int = 10
    reinforcement_strategy: str = "q_learning"
    num_bandit_arms: int = 5
    learning_phase: str = "balanced"
    target_improvement_rate: float = 0.05
    max_episodes: int = 10000
    episode_length: int = 100
    progress_tracking_window: int = 20
    enable_history_pruning: bool = True
    history_pruning_interval: int = 1000
    store_full_metadata: bool = True


@dataclass
class FeedbackEntry:
    feedback_id: str
    source: FeedbackSource
    feedback_type: FeedbackType
    target_id: str
    value: float
    weight: float = 1.0
    outcome: FeedbackOutcome = FeedbackOutcome.NEUTRAL
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    episode: int = 0
    processed: bool = False
    effective_weight: float = 1.0

    def get_effective_weight(self) -> float:
        return self.weight * self.confidence


@dataclass
class FeedbackAggregate:
    target_id: str
    feedback_type: FeedbackType
    total_count: int
    positive_count: int
    negative_count: int
    neutral_count: int
    mean_value: float
    weighted_mean: float
    std_value: float
    net_score: float
    confidence: float
    source_breakdown: Dict[str, int]
    last_updated: datetime = field(default_factory=datetime.now)
    trend_direction: str = "stable"
    agreement_ratio: float = 0.0

    def to_summary(self) -> Dict:
        return {
            'target_id': self.target_id,
            'feedback_type': self.feedback_type.value,
            'total': self.total_count,
            'positive': self.positive_count,
            'negative': self.negative_count,
            'neutral': self.neutral_count,
            'mean': round(self.mean_value, 4),
            'weighted_mean': round(self.weighted_mean, 4),
            'net_score': round(self.net_score, 4),
            'confidence': round(self.confidence, 4),
            'agreement': round(self.agreement_ratio, 4),
            'trend': self.trend_direction,
        }


@dataclass
class LearningProgress:
    episode: int
    phase: LearningPhase
    total_feedback: int
    positive_rate: float
    negative_rate: float
    average_score: float
    improvement_rate: float
    exploration_rate: float
    q_values: Dict[str, float]
    timestamp: datetime = field(default_factory=datetime.now)
    metrics: Dict[str, float] = field(default_factory=dict)
    active_actions: int = 0
    convergence_score: float = 0.0
    reward_total: float = 0.0

    def to_summary(self) -> Dict:
        return {
            'episode': self.episode,
            'phase': self.phase.value,
            'total_feedback': self.total_feedback,
            'positive_rate': round(self.positive_rate, 4),
            'negative_rate': round(self.negative_rate, 4),
            'avg_score': round(self.average_score, 4),
            'improvement': round(self.improvement_rate, 4),
            'exploration': round(self.exploration_rate, 4),
            'convergence': round(self.convergence_score, 4),
            'reward': round(self.reward_total, 4),
        }


class FeedbackLearner:
    def __init__(self, config: Optional[FeedbackConfig] = None):
        self.config = config or FeedbackConfig()
        self.feedback_history: List[FeedbackEntry] = []
        self.feedback_aggregates: Dict[str, FeedbackAggregate] = {}
        self.target_adjustments: Dict[str, float] = {}
        self.target_confidence: Dict[str, float] = {}
        self.learning_progress: List[LearningProgress] = []
        self.q_table: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.action_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.action_rewards: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.episode_count: int = 0
        self.total_feedback_count: int = 0
        self.last_adjustment_time: Optional[datetime] = None
        self.convergence_history: List[float] = []
        self.current_phase: LearningPhase = LearningPhase(self.config.learning_phase)
        self._source_weights: Dict[FeedbackSource, float] = {}
        self._initialize_source_weights()
        self._action_space: List[str] = [
            'increase_threshold', 'decrease_threshold',
            'increase_weight', 'decrease_weight',
            'add_feature', 'remove_feature',
            'boost_positive', 'suppress_negative',
            'reset_model', 'maintain',
        ]
        logger.info(f"FeedbackLearner initialized (phase={self.current_phase.value})")

    def _initialize_source_weights(self) -> None:
        self._source_weights = {
            FeedbackSource.USER_EXPLICIT: self.config.user_explicit_weight,
            FeedbackSource.USER_IMPLICIT: self.config.user_implicit_weight,
            FeedbackSource.SYSTEM_AUTOMATED: self.config.system_automated_weight,
            FeedbackSource.SYSTEM_VALIDATION: self.config.system_validation_weight,
            FeedbackSource.CROSS_VALIDATION: self.config.cross_validation_weight,
            FeedbackSource.CROWD_SOURCED: self.config.crowd_sourced_weight,
            FeedbackSource.HISTORICAL: self.config.historical_weight,
            FeedbackSource.SIMULATED: self.config.simulated_weight,
        }

    def record_feedback(self, target_id: str, value: float,
                        source: FeedbackSource = FeedbackSource.SYSTEM_AUTOMATED,
                        feedback_type: FeedbackType = FeedbackType.CORRECTION,
                        confidence: float = 1.0, weight: Optional[float] = None,
                        user_id: Optional[str] = None,
                        context: Optional[Dict] = None,
                        metadata: Optional[Dict] = None) -> FeedbackEntry:
        source_weight = self._source_weights.get(source, 0.5)
        if weight is None:
            weight = source_weight
        if value > 0.5:
            outcome = FeedbackOutcome.POSITIVE
        elif value < -0.5:
            outcome = FeedbackOutcome.NEGATIVE
        else:
            outcome = FeedbackOutcome.NEUTRAL
        effective_weight = weight * confidence
        entry = FeedbackEntry(
            feedback_id=f"fb_{uuid.uuid4().hex[:12]}",
            source=source,
            feedback_type=feedback_type,
            target_id=target_id,
            value=value,
            weight=weight,
            outcome=outcome,
            confidence=confidence,
            context=context or {},
            metadata=metadata or {},
            user_id=user_id,
            episode=self.episode_count,
            effective_weight=effective_weight,
        )
        self.feedback_history.append(entry)
        self.total_feedback_count += 1
        self._update_aggregates(entry)
        self._update_target_adjustments(entry)
        if self.config.enable_history_pruning and self.total_feedback_count % self.config.history_pruning_interval == 0:
            self._prune_history()
        if self.config.enable_auto_adjustment:
            self._check_adjustment_needed()
        return entry

    def record_batch_feedback(self, feedback_list: List[Tuple[str, float, FeedbackSource, FeedbackType]],
                               confidence: float = 1.0) -> List[FeedbackEntry]:
        entries = []
        for item in feedback_list:
            target_id = item[0]
            value = item[1]
            source = item[2] if len(item) > 2 else FeedbackSource.SYSTEM_AUTOMATED
            fb_type = item[3] if len(item) > 3 else FeedbackType.CORRECTION
            entry = self.record_feedback(target_id, value, source, fb_type, confidence)
            entries.append(entry)
        return entries

    def record_user_feedback(self, target_id: str, rating: float,
                              explicit: bool = True,
                              user_id: Optional[str] = None) -> FeedbackEntry:
        source = FeedbackSource.USER_EXPLICIT if explicit else FeedbackSource.USER_IMPLICIT
        fb_type = FeedbackType.RATING
        normalized_rating = max(-1.0, min(1.0, rating))
        confidence = 1.0 if explicit else 0.6
        return self.record_feedback(
            target_id, normalized_rating, source, fb_type,
            confidence=confidence, user_id=user_id
        )

    def record_correction(self, target_id: str, was_correct: bool,
                           expected_value: Optional[Any] = None) -> FeedbackEntry:
        value = -0.8 if not was_correct else 0.8
        return self.record_feedback(
            target_id, value, FeedbackSource.SYSTEM_VALIDATION,
            FeedbackType.CORRECTION, confidence=0.9,
            context={'was_correct': was_correct, 'expected': str(expected_value)}
        )

    def _update_aggregates(self, entry: FeedbackEntry) -> None:
        key = f"{entry.target_id}_{entry.feedback_type.value}"
        if key not in self.feedback_aggregates:
            self.feedback_aggregates[key] = FeedbackAggregate(
                target_id=entry.target_id,
                feedback_type=entry.feedback_type,
                total_count=0, positive_count=0,
                negative_count=0, neutral_count=0,
                mean_value=0.0, weighted_mean=0.0,
                std_value=0.0, net_score=0.0,
                confidence=0.0, source_breakdown={}
            )
        agg = self.feedback_aggregates[key]
        agg.total_count += 1
        source_key = entry.source.value
        agg.source_breakdown[source_key] = agg.source_breakdown.get(source_key, 0) + 1
        if entry.outcome == FeedbackOutcome.POSITIVE:
            agg.positive_count += 1
        elif entry.outcome == FeedbackOutcome.NEGATIVE:
            agg.negative_count += 1
        else:
            agg.neutral_count += 1
        window = self.feedback_history[-self.config.feedback_aggregation_window:]
        recent_for_target = [fb for fb in window if fb.target_id == entry.target_id
                             and fb.feedback_type == entry.feedback_type]
        if recent_for_target:
            values = [fb.value for fb in recent_for_target]
            weights = [fb.get_effective_weight() for fb in recent_for_target]
            total_weight = sum(weights) or 1.0
            agg.mean_value = statistics.mean(values)
            agg.weighted_mean = sum(v * w for v, w in zip(values, weights)) / total_weight
            try:
                agg.std_value = statistics.stdev(values) if len(values) > 1 else 0.0
            except statistics.StatisticsError:
                agg.std_value = 0.0
        positive_entries = sum(1 for fb in self.feedback_history[-100:]
                                if fb.target_id == entry.target_id and fb.outcome == FeedbackOutcome.POSITIVE)
        negative_entries = sum(1 for fb in self.feedback_history[-100:]
                                if fb.target_id == entry.target_id and fb.outcome == FeedbackOutcome.NEGATIVE)
        total_recent = positive_entries + negative_entries
        if total_recent > 0:
            agg.net_score = (positive_entries - negative_entries) / total_recent
            agg.agreement_ratio = max(positive_entries, negative_entries) / total_recent if total_recent > 0 else 0.0
        agg.confidence = min(1.0, agg.total_count / 20.0)
        feedback_for_target = [fb for fb in self.feedback_history[-50:]
                                if fb.target_id == entry.target_id]
        if len(feedback_for_target) >= 5:
            recent_outcomes = [fb.outcome for fb in feedback_for_target[-10:]]
            pos_ratio = recent_outcomes.count(FeedbackOutcome.POSITIVE) / len(recent_outcomes)
            if pos_ratio > 0.7:
                agg.trend_direction = "improving"
            elif pos_ratio < 0.3:
                agg.trend_direction = "declining"
            else:
                agg.trend_direction = "stable"
        agg.last_updated = datetime.now()

    def _update_target_adjustments(self, entry: FeedbackEntry) -> None:
        target_id = entry.target_id
        current = self.target_adjustments.get(target_id, 0.0)
        current_conf = self.target_confidence.get(target_id, 0.0)
        learning = self.config.learning_rate * entry.effective_weight
        adjustment = learning * entry.value * (1.0 - abs(current))
        self.target_adjustments[target_id] = max(-1.0, min(1.0, current + adjustment))
        conf_change = entry.confidence * entry.effective_weight * 0.1
        self.target_confidence[target_id] = max(0.0, min(1.0, current_conf + conf_change))
        if self.target_confidence[target_id] > 0.95:
            self.target_adjustments[target_id] = current + adjustment * 0.1

    def _check_adjustment_needed(self) -> None:
        if self.last_adjustment_time is not None:
            elapsed = (datetime.now() - self.last_adjustment_time).total_seconds()
            if elapsed < self.config.adjustment_cooldown_minutes * 60:
                return
        recent = self.feedback_history[-self.config.min_feedback_for_adjustment:]
        if len(recent) < self.config.min_feedback_for_adjustment:
            return
        negative_ratio = sum(1 for fb in recent if fb.outcome == FeedbackOutcome.NEGATIVE) / len(recent)
        if negative_ratio > 0.4:
            self._perform_adjustment(recent)

    def _perform_adjustment(self, recent_feedback: List[FeedbackEntry]) -> None:
        self.last_adjustment_time = datetime.now()
        targets = set(fb.target_id for fb in recent_feedback)
        action = self._select_action(targets)
        logger.info(f"Performing adjustment: {action} for {len(targets)} targets")
        for target_id in targets:
            agg_key = f"{target_id}_correction"
            if agg_key in self.feedback_aggregates:
                agg = self.feedback_aggregates[agg_key]
                if action == 'increase_threshold':
                    self.target_adjustments[target_id] = min(
                        1.0, self.target_adjustments.get(target_id, 0.0) + 0.05
                    )
                elif action == 'decrease_threshold':
                    self.target_adjustments[target_id] = max(
                        -1.0, self.target_adjustments.get(target_id, 0.0) - 0.05
                    )
                elif action == 'boost_positive':
                    self.target_adjustments[target_id] = min(
                        1.0, self.target_adjustments.get(target_id, 0.0) + 0.1
                    )
                elif action == 'suppress_negative':
                    self.target_adjustments[target_id] = max(
                        -1.0, self.target_adjustments.get(target_id, 0.0) - 0.1
                    )
                elif action == 'reset_model':
                    self.target_adjustments[target_id] = 0.0
                    self.target_confidence[target_id] = 0.0
        reward = self._compute_adjustment_reward(recent_feedback)
        self._update_q_table(action, reward, list(targets))

    def _select_action(self, targets: Set[str]) -> str:
        phase = self.current_phase
        if phase == LearningPhase.EXPLORATION:
            return random.choice(self._action_space)
        elif phase == LearningPhase.EXPLOITATION:
            return self._best_action(targets)
        elif phase == LearningPhase.BALANCED:
            if random.random() < self.config.exploration_rate:
                return random.choice(self._action_space)
            return self._best_action(targets)
        return self._action_space[0]

    def _best_action(self, targets: Set[str]) -> str:
        if not targets:
            return 'maintain'
        state_key = self._get_state_key(targets)
        state_actions = self.q_table[state_key]
        if not state_actions:
            return 'maintain'
        return max(state_actions, key=state_actions.get)

    def _get_state_key(self, targets: Set[str]) -> str:
        sorted_targets = sorted(targets)
        return f"state_{hash(tuple(sorted_targets)) % 1000}"

    def _compute_adjustment_reward(self, recent_feedback: List[FeedbackEntry]) -> float:
        if not recent_feedback:
            return 0.0
        before = self.feedback_history[-len(recent_feedback) - 10:-len(recent_feedback)] or []
        after = recent_feedback
        if not before:
            return 0.0
        before_neg = sum(1 for fb in before if fb.outcome == FeedbackOutcome.NEGATIVE) / max(len(before), 1)
        after_neg = sum(1 for fb in after if fb.outcome == FeedbackOutcome.NEGATIVE) / max(len(after), 1)
        improvement = before_neg - after_neg
        return improvement * 2.0 - 0.5

    def _update_q_table(self, action: str, reward: float, targets: List[str]) -> None:
        for target_id in targets:
            state_key = self._get_state_key({target_id})
            current_q = self.q_table[state_key].get(action, 0.0)
            max_future_q = max(self.q_table[state_key].values()) if self.q_table[state_key] else 0.0
            new_q = current_q + self.config.learning_rate * (
                reward + self.config.discount_factor * max_future_q - current_q
            )
            self.q_table[state_key][action] = new_q
            self.action_counts[state_key][action] = self.action_counts[state_key].get(action, 0) + 1
            self.action_rewards[state_key][action] += reward

    def run_episode(self, feedback_batch: List[Tuple[str, float, FeedbackSource, FeedbackType]]) -> LearningProgress:
        self.episode_count += 1
        entries = self.record_batch_feedback(feedback_batch)
        if self.episode_count % self.config.episode_length == 0:
            self._decay_exploration()
            self._update_phase()
        self._compute_learning_progress(entries)
        progress_entries = [p for p in self.learning_progress if p.episode == self.episode_count]
        return progress_entries[-1] if progress_entries else self._compute_learning_progress(entries)

    def _decay_exploration(self) -> None:
        self.config.exploration_rate = max(
            self.config.min_exploration_rate,
            self.config.exploration_rate * self.config.exploration_decay
        )

    def _update_phase(self) -> None:
        if not self.learning_progress:
            return
        recent = self.learning_progress[-self.config.progress_tracking_window:]
        if len(recent) < 5:
            return
        improvements = [p.improvement_rate for p in recent if p.improvement_rate is not None]
        if not improvements:
            return
        avg_improvement = statistics.mean(improvements)
        if avg_improvement > self.config.target_improvement_rate * 1.5:
            self.current_phase = LearningPhase.EXPLOITATION
        elif avg_improvement < self.config.target_improvement_rate * 0.5:
            self.current_phase = LearningPhase.EXPLORATION
        else:
            self.current_phase = LearningPhase.BALANCED
        self.config.learning_phase = self.current_phase.value

    def _compute_learning_progress(self, recent_entries: List[FeedbackEntry]) -> LearningProgress:
        window = self.feedback_history[-self.config.progress_tracking_window:]
        if not window:
            window = recent_entries
        total = len(window)
        positive = sum(1 for fb in window if fb.outcome == FeedbackOutcome.POSITIVE)
        negative = sum(1 for fb in window if fb.outcome == FeedbackOutcome.NEGATIVE)
        scores = [fb.value for fb in window] if window else [0.0]
        avg_score = statistics.mean(scores) if scores else 0.0
        if len(self.learning_progress) >= 2:
            prev = self.learning_progress[-1]
            improvement = avg_score - prev.average_score if prev.average_score != 0 else avg_score
        else:
            improvement = 0.0
        state_summary = {}
        for state_key, actions in self.q_table.items():
            if actions:
                best_action = max(actions, key=actions.get)
                state_summary[state_key] = {
                    'best_action': best_action,
                    'best_q': actions[best_action],
                    'total_actions': len(actions),
                }
        convergence_score = 0.0
        if len(self.convergence_history) >= 5:
            recent_conv = self.convergence_history[-5:]
            if len(set(round(c, 4) for c in recent_conv)) <= 2:
                convergence_score = 1.0
            else:
                try:
                    convergence_score = 1.0 - min(1.0, statistics.stdev(recent_conv))
                except statistics.StatisticsError:
                    convergence_score = 0.0
        reward_total = sum(
            sum(rewards.values()) for rewards in self.action_rewards.values()
        )
        progress = LearningProgress(
            episode=self.episode_count,
            phase=self.current_phase,
            total_feedback=self.total_feedback_count,
            positive_rate=positive / max(total, 1),
            negative_rate=negative / max(total, 1),
            average_score=avg_score,
            improvement_rate=improvement,
            exploration_rate=self.config.exploration_rate,
            q_values={k: max(v.values()) if v else 0.0 for k, v in self.q_table.items()},
            active_actions=len(self._action_space),
            convergence_score=convergence_score,
            reward_total=reward_total,
            metrics={
                'positive_count': positive,
                'negative_count': negative,
                'total_in_window': total,
            }
        )
        self.learning_progress.append(progress)
        self.convergence_history.append(avg_score)
        return progress

    def get_adjustment(self, target_id: str) -> float:
        return self.target_adjustments.get(target_id, 0.0)

    def get_confidence(self, target_id: str) -> float:
        return self.target_confidence.get(target_id, 0.0)

    def get_aggregate(self, target_id: str,
                      feedback_type: FeedbackType = FeedbackType.CORRECTION) -> Optional[FeedbackAggregate]:
        key = f"{target_id}_{feedback_type.value}"
        return self.feedback_aggregates.get(key)

    def get_all_aggregates(self) -> List[FeedbackAggregate]:
        return list(self.feedback_aggregates.values())

    def get_feedback_for_target(self, target_id: str,
                                 limit: int = 100) -> List[FeedbackEntry]:
        return [fb for fb in self.feedback_history if fb.target_id == target_id][-limit:]

    def get_recent_feedback(self, limit: int = 50) -> List[FeedbackEntry]:
        return self.feedback_history[-limit:]

    def get_positive_rate(self, target_id: Optional[str] = None,
                          feedback_type: FeedbackType = FeedbackType.CORRECTION) -> float:
        window = self.feedback_history[-self.config.feedback_aggregation_window:]
        if target_id:
            window = [fb for fb in window if fb.target_id == target_id]
        window = [fb for fb in window if fb.feedback_type == feedback_type]
        if not window:
            return 0.5
        positive = sum(1 for fb in window if fb.outcome == FeedbackOutcome.POSITIVE)
        return positive / len(window)

    def get_learning_curve(self) -> List[Dict]:
        return [p.to_summary() for p in self.learning_progress]

    def simulate_feedback_batch(self, target_ids: List[str],
                                 positive_ratio: float = 0.7,
                                 batch_size: int = 50) -> List[FeedbackEntry]:
        entries = []
        for target_id in target_ids:
            for _ in range(batch_size // len(target_ids)):
                value = random.uniform(0.3, 1.0) if random.random() < positive_ratio else random.uniform(-1.0, -0.3)
                entry = self.record_feedback(
                    target_id, value, FeedbackSource.SIMULATED, FeedbackType.RATING,
                    confidence=0.5
                )
                entries.append(entry)
        return entries

    def get_q_values(self, target_id: str) -> Dict[str, float]:
        state_key = self._get_state_key({target_id})
        return dict(self.q_table[state_key])

    def get_best_action(self, target_id: str) -> Optional[str]:
        q_values = self.get_q_values(target_id)
        if not q_values:
            return None
        return max(q_values, key=q_values.get)

    def _prune_history(self) -> None:
        if len(self.feedback_history) <= self.config.max_feedback_history:
            return
        cutoff = len(self.feedback_history) - self.config.max_feedback_history
        pruned = self.feedback_history[cutoff:]
        removed = len(self.feedback_history) - len(pruned)
        self.feedback_history = pruned
        logger.debug(f"Pruned {removed} old feedback entries")

    def get_statistics(self) -> Dict:
        source_counts = Counter(fb.source.value for fb in self.feedback_history)
        outcome_counts = Counter(fb.outcome.value for fb in self.feedback_history)
        type_counts = Counter(fb.feedback_type.value for fb in self.feedback_history)
        target_count = len(set(fb.target_id for fb in self.feedback_history))
        adjustments_count = len(self.target_adjustments)
        phase_episodes = Counter(p.phase.value for p in self.learning_progress)
        if self.feedback_history:
            first_fb = min(fb.timestamp for fb in self.feedback_history)
            last_fb = max(fb.timestamp for fb in self.feedback_history)
            duration = (last_fb - first_fb).total_seconds()
        else:
            duration = 0.0
        return {
            'total_feedback': self.total_feedback_count,
            'history_size': len(self.feedback_history),
            'unique_targets': target_count,
            'episodes': self.episode_count,
            'current_phase': self.current_phase.value,
            'exploration_rate': round(self.config.exploration_rate, 4),
            'learning_rate': self.config.learning_rate,
            'discount_factor': self.config.discount_factor,
            'adjustments_made': adjustments_count,
            'q_table_size': sum(len(actions) for actions in self.q_table.values()),
            'convergence_score': round(self.learning_progress[-1].convergence_score, 4) if self.learning_progress else 0.0,
            'source_breakdown': dict(source_counts),
            'outcome_breakdown': dict(outcome_counts),
            'feedback_type_breakdown': dict(type_counts),
            'phase_breakdown': dict(phase_episodes),
            'time_span_seconds': duration,
            'aggregates_count': len(self.feedback_aggregates),
            'config': {
                'user_explicit_weight': self.config.user_explicit_weight,
                'user_implicit_weight': self.config.user_implicit_weight,
                'reinforcement_strategy': self.config.reinforcement_strategy,
                'max_history': self.config.max_feedback_history,
                'auto_adjustment': self.config.enable_auto_adjustment,
            }
        }

    def export_feedback(self, target_id: Optional[str] = None) -> Dict:
        feedback_list = self.feedback_history
        if target_id:
            feedback_list = [fb for fb in feedback_list if fb.target_id == target_id]
        return {
            'export_version': '1.0',
            'exported_at': datetime.now().isoformat(),
            'config': asdict(self.config),
            'feedback_count': len(feedback_list),
            'feedback': [
                {
                    'feedback_id': fb.feedback_id,
                    'source': fb.source.value,
                    'feedback_type': fb.feedback_type.value,
                    'target_id': fb.target_id,
                    'value': fb.value,
                    'weight': fb.weight,
                    'outcome': fb.outcome.value,
                    'timestamp': fb.timestamp.isoformat(),
                    'confidence': fb.confidence,
                    'effective_weight': fb.effective_weight,
                    'episode': fb.episode,
                }
                for fb in feedback_list[-1000:]
            ],
            'aggregates': {
                k: agg.to_summary() for k, agg in self.feedback_aggregates.items()
            },
            'adjustments': dict(self.target_adjustments),
            'confidences': dict(self.target_confidence),
            'learning_progress': [p.to_summary() for p in self.learning_progress[-100:]],
            'statistics': self.get_statistics(),
        }

    def import_feedback(self, data: Dict) -> int:
        count = 0
        if 'feedback' in data:
            for fb_data in data['feedback']:
                fb_data['source'] = FeedbackSource(fb_data['source'])
                fb_data['feedback_type'] = FeedbackType(fb_data['feedback_type'])
                fb_data['outcome'] = FeedbackOutcome(fb_data['outcome'])
                if 'timestamp' in fb_data:
                    fb_data['timestamp'] = datetime.fromisoformat(fb_data['timestamp'])
                entry = FeedbackEntry(**{k: v for k, v in fb_data.items()
                                          if k in FeedbackEntry.__dataclass_fields__})
                self.feedback_history.append(entry)
                self.total_feedback_count += 1
                count += 1
        if 'aggregates' in data:
            for key, agg_data in data['aggregates'].items():
                agg_data['feedback_type'] = FeedbackType(agg_data['feedback_type'])
                self.feedback_aggregates[key] = FeedbackAggregate(**agg_data)
        if 'adjustments' in data:
            self.target_adjustments.update(data['adjustments'])
        if 'confidences' in data:
            self.target_confidence.update(data['confidences'])
        self._prune_history()
        logger.info(f"Imported {count} feedback entries")
        return count

    def reset(self) -> None:
        self.feedback_history.clear()
        self.feedback_aggregates.clear()
        self.target_adjustments.clear()
        self.target_confidence.clear()
        self.learning_progress.clear()
        self.q_table.clear()
        self.action_counts.clear()
        self.action_rewards.clear()
        self.episode_count = 0
        self.total_feedback_count = 0
        self.last_adjustment_time = None
        self.convergence_history.clear()
        self.current_phase = LearningPhase(self.config.learning_phase)
        logger.info("FeedbackLearner reset")

    def reset_target(self, target_id: str) -> None:
        self.target_adjustments.pop(target_id, None)
        self.target_confidence.pop(target_id, None)
        keys_to_delete = [k for k in self.feedback_aggregates if k.startswith(target_id)]
        for k in keys_to_delete:
            del self.feedback_aggregates[k]
        self.feedback_history = [fb for fb in self.feedback_history if fb.target_id != target_id]
        logger.info(f"Reset feedback data for target: {target_id}")
