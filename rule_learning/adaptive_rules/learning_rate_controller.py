"""Learning rate controller for adaptive rule learning.

Provides adaptive learning rate adjustment mechanisms including exponential
decay, step decay, and adaptive adjustment, convergence detection via
gradient-based and plateau-based methods, per-rule learning rates, rate
scheduling and annealing, and comprehensive statistics and reporting.
"""

import json
import logging
import math
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from rules_emerging_pattern.models.rule import Rule, RuleTier

logger = logging.getLogger(__name__)


class DecayStrategy(str, Enum):
    """Strategies for learning rate decay over time."""
    EXPONENTIAL = "exponential"
    STEP = "step"
    ADAPTIVE = "adaptive"
    COSINE = "cosine"
    INVERSE_TIME = "inverse_time"
    POLYNOMIAL = "polynomial"
    NONE = "none"


class ConvergenceMetric(str, Enum):
    """Metrics used for convergence detection."""
    GRADIENT_NORM = "gradient_norm"
    LOSS_PLATEAU = "loss_plateau"
    PARAMETER_CHANGE = "parameter_change"
    PERFORMANCE_STABILITY = "performance_stability"
    HYBRID = "hybrid"


class AnnealingSchedule(str, Enum):
    """Schedules for learning rate annealing."""
    MONOTONIC = "monotonic"
    CYCLICAL = "cyclical"
    WARM_RESTART = "warm_restart"
    ADAPTIVE = "adaptive"


class RateAdjustmentCause(str, Enum):
    """Causes for learning rate adjustments."""
    SCHEDULED_DECAY = "scheduled_decay"
    PLATEAU_DETECTED = "plateau_detected"
    GRADIENT_SPIKE = "gradient_spike"
    CONVERGENCE_APPROACHING = "convergence_approaching"
    DIVERGENCE_DETECTED = "divergence_detected"
    MANUAL_OVERRIDE = "manual_override"
    WARM_RESTART = "warm_restart"
    PERFORMANCE_DEGRADATION = "performance_degradation"


@dataclass
class LearningRateRecord:
    """Record of a single learning rate adjustment."""
    record_id: str
    rule_id: str
    learning_rate_before: float
    learning_rate_after: float
    cause: RateAdjustmentCause
    decay_strategy: DecayStrategy
    gradient_value: Optional[float] = None
    loss_value: Optional[float] = None
    performance_metric: Optional[float] = None
    epoch: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleLearningState:
    """Per-rule learning state tracking."""
    rule_id: str
    learning_rate: float = 0.01
    base_learning_rate: float = 0.01
    min_learning_rate: float = 1e-6
    max_learning_rate: float = 1.0
    decay_strategy: DecayStrategy = DecayStrategy.EXPONENTIAL
    decay_rate: float = 0.96
    step_size: int = 100
    current_epoch: int = 0
    total_adjustments: int = 0
    last_adjustment_time: Optional[datetime] = None
    loss_history: deque = field(default_factory=lambda: deque(maxlen=500))
    gradient_history: deque = field(default_factory=lambda: deque(maxlen=200))
    parameter_change_history: deque = field(default_factory=lambda: deque(maxlen=200))
    performance_history: deque = field(default_factory=lambda: deque(maxlen=200))
    plateau_count: int = 0
    divergence_count: int = 0
    convergence_epoch: Optional[int] = None
    warm_restart_count: int = 0
    is_frozen: bool = False
    frozen_at: Optional[datetime] = None
    tier: Optional[RuleTier] = None

    def compute_current_rate(self) -> float:
        """Compute the current learning rate based on decay strategy."""
        if self.is_frozen:
            return self.learning_rate
        strategy = self.decay_strategy
        base = self.base_learning_rate
        epoch = self.current_epoch
        if strategy == DecayStrategy.EXPONENTIAL:
            return base * (self.decay_rate ** epoch)
        if strategy == DecayStrategy.STEP:
            factor = self.decay_rate ** (epoch // self.step_size)
            return base * factor
        if strategy == DecayStrategy.INVERSE_TIME:
            return base / (1.0 + self.decay_rate * epoch)
        if strategy == DecayStrategy.COSINE:
            factor = 0.5 * (1.0 + math.cos(math.pi * epoch / max(self.step_size, 1)))
            return self.min_learning_rate + (base - self.min_learning_rate) * factor
        if strategy == DecayStrategy.POLYNOMIAL:
            factor = (1.0 - epoch / max(self.step_size, 1)) ** self.decay_rate
            return base * max(factor, self.min_learning_rate / base)
        return self.learning_rate

    def apply_rate(self, new_rate: float) -> None:
        """Apply a new learning rate with bounds checking."""
        clamped = max(self.min_learning_rate, min(self.max_learning_rate, new_rate))
        self.learning_rate = clamped
        self.last_adjustment_time = datetime.utcnow()
        self.total_adjustments += 1

    def record_loss(self, loss: float) -> None:
        """Record a loss value for plateau/gradient detection."""
        self.loss_history.append(loss)

    def record_gradient(self, gradient: float) -> None:
        """Record a gradient norm value."""
        self.gradient_history.append(gradient)

    def record_parameter_change(self, change: float) -> None:
        """Record parameter change magnitude."""
        self.parameter_change_history.append(change)

    def record_performance(self, metric: float) -> None:
        """Record a performance metric value."""
        self.performance_history.append(metric)

    def loss_plateau_detected(self, window: int = 20, tolerance: float = 1e-4) -> bool:
        """Detect if loss has plateaued over a recent window."""
        if len(self.loss_history) < window:
            return False
        recent = list(self.loss_history)[-window:]
        return max(recent) - min(recent) < tolerance

    def divergence_detected(self, threshold: float = 10.0) -> bool:
        """Detect if training is diverging based on loss trend."""
        if len(self.loss_history) < 10:
            return False
        recent = list(self.loss_history)[-10:]
        if recent[-1] > recent[0] * threshold:
            return True
        half = len(recent) // 2
        first_half_avg = sum(recent[:half]) / max(half, 1)
        second_half_avg = sum(recent[half:]) / max(len(recent) - half, 1)
        return second_half_avg > first_half_avg * threshold

    def gradient_spike_detected(self, std_multiplier: float = 3.0) -> bool:
        """Detect if the latest gradient is a spike."""
        if len(self.gradient_history) < 5:
            return False
        grads = list(self.gradient_history)
        mean = sum(grads) / len(grads)
        variance = sum((g - mean) ** 2 for g in grads) / len(grads)
        std = math.sqrt(variance)
        if std == 0.0:
            return False
        latest = grads[-1]
        return abs(latest - mean) / std > std_multiplier

    def convergence_score(self) -> float:
        """Compute a convergence score between 0.0 (not converged) and 1.0 (converged)."""
        scores: List[float] = []
        if len(self.loss_history) >= 50:
            early_loss = sum(list(self.loss_history)[:10]) / 10.0
            recent_loss = sum(list(self.loss_history)[-10:]) / 10.0
            if early_loss > 0:
                reduction = (early_loss - recent_loss) / early_loss
                scores.append(min(1.0, max(0.0, reduction)))
        if len(self.parameter_change_history) >= 20:
            recent_changes = list(self.parameter_change_history)[-20:]
            avg_change = sum(recent_changes) / len(recent_changes)
            scores.append(max(0.0, 1.0 - avg_change / max(avg_change * 2, 1e-8)))
        if len(self.performance_history) >= 20:
            recent_perf = list(self.performance_history)[-20:]
            perf_stability = 1.0 - (max(recent_perf) - min(recent_perf)) / max(abs(sum(recent_perf) / len(recent_perf)), 1e-8)
            scores.append(max(0.0, min(1.0, perf_stability)))
        if not scores:
            return 0.0
        return sum(scores) / len(scores)


@dataclass
class LearningRateStatistics:
    """Aggregated statistics for the learning rate controller."""
    total_rules_tracked: int = 0
    active_rules: int = 0
    frozen_rules: int = 0
    converged_rules: int = 0
    total_adjustments: int = 0
    average_learning_rate: float = 0.0
    median_learning_rate: float = 0.0
    min_learning_rate: float = 1.0
    max_learning_rate: float = 0.0
    adjustments_by_cause: Dict[str, int] = field(default_factory=dict)
    adjustments_by_strategy: Dict[str, int] = field(default_factory=dict)
    plateau_events: int = 0
    divergence_events: int = 0
    warm_restarts: int = 0
    average_convergence_score: float = 0.0
    last_adjustment_time: Optional[datetime] = None
    uptime_hours: float = 0.0


class ConvergenceDetector:
    """Detects convergence of learning processes using multiple strategies."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._metric = ConvergenceMetric(self.config.get("metric", "hybrid"))
        self._plateau_window = self.config.get("plateau_window", 20)
        self._plateau_tolerance = self.config.get("plateau_tolerance", 1e-4)
        self._convergence_threshold = self.config.get("convergence_threshold", 0.9)
        self._stability_window = self.config.get("stability_window", 50)
        logger.info(
            "ConvergenceDetector initialized (metric=%s, threshold=%.2f)",
            self._metric.value, self._convergence_threshold,
        )

    def check_convergence(self, state: RuleLearningState) -> Tuple[bool, float]:
        """Check if a rule's learning process has converged.

        Args:
            state: The learning state to evaluate.

        Returns:
            Tuple of (is_converged, convergence_score).
        """
        metric = self._metric
        if metric == ConvergenceMetric.GRADIENT_NORM:
            return self._check_gradient_norm(state)
        if metric == ConvergenceMetric.LOSS_PLATEAU:
            return self._check_loss_plateau(state)
        if metric == ConvergenceMetric.PARAMETER_CHANGE:
            return self._check_parameter_change(state)
        if metric == ConvergenceMetric.PERFORMANCE_STABILITY:
            return self._check_performance_stability(state)
        return self._check_hybrid(state)

    def _check_gradient_norm(self, state: RuleLearningState) -> Tuple[bool, float]:
        """Check convergence based on gradient norm approaching zero."""
        if len(state.gradient_history) < 10:
            return False, 0.0
        recent = list(state.gradient_history)[-10:]
        avg_norm = sum(abs(g) for g in recent) / len(recent)
        score = 1.0 - min(1.0, avg_norm / max(self._plateau_tolerance * 100, 1e-8))
        converged = avg_norm < self._plateau_tolerance
        return converged, max(0.0, score)

    def _check_loss_plateau(self, state: RuleLearningState) -> Tuple[bool, float]:
        """Check convergence based on loss plateau."""
        if len(state.loss_history) < self._plateau_window:
            return False, 0.0
        recent = list(state.loss_history)[-self._plateau_window:]
        loss_range = max(recent) - min(recent)
        avg_loss = sum(recent) / len(recent)
        score = 1.0 - min(1.0, loss_range / max(avg_loss, 1e-8))
        converged = loss_range < self._plateau_tolerance
        return converged, max(0.0, score)

    def _check_parameter_change(self, state: RuleLearningState) -> Tuple[bool, float]:
        """Check convergence based on parameter change magnitude."""
        if len(state.parameter_change_history) < 10:
            return False, 0.0
        recent = list(state.parameter_change_history)[-10:]
        avg_change = sum(recent) / len(recent)
        score = 1.0 - min(1.0, avg_change / max(self._plateau_tolerance * 10, 1e-8))
        converged = avg_change < self._plateau_tolerance
        return converged, max(0.0, score)

    def _check_performance_stability(self, state: RuleLearningState) -> Tuple[bool, float]:
        """Check convergence based on performance metric stability."""
        if len(state.performance_history) < self._stability_window:
            return False, 0.0
        recent = list(state.performance_history)[-self._stability_window:]
        half = len(recent) // 2
        first_half = recent[:half]
        second_half = recent[half:]
        first_mean = sum(first_half) / len(first_half)
        second_mean = sum(second_half) / len(second_half)
        change_ratio = abs(second_mean - first_mean) / max(abs(first_mean), 1e-8)
        score = 1.0 - min(1.0, change_ratio)
        converged = change_ratio < 0.01
        return converged, max(0.0, score)

    def _check_hybrid(self, state: RuleLearningState) -> Tuple[bool, float]:
        """Check convergence using a hybrid of all metrics."""
        scores: List[float] = []
        converged_count = 0
        for method in [
            self._check_gradient_norm,
            self._check_loss_plateau,
            self._check_parameter_change,
            self._check_performance_stability,
        ]:
            try:
                c, s = method(state)
                scores.append(s)
                if c:
                    converged_count += 1
            except Exception:
                continue
        if not scores:
            return False, 0.0
        avg_score = sum(scores) / len(scores)
        converged = converged_count >= max(1, len(scores) // 2) or avg_score >= self._convergence_threshold
        return converged, min(1.0, avg_score)


class LearningRateScheduler:
    """Manages learning rate scheduling and annealing."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._annealing_schedule = AnnealingSchedule(self.config.get("annealing", "monotonic"))
        self._cycle_length = self.config.get("cycle_length", 500)
        self._cycle_mult = self.config.get("cycle_mult", 1.5)
        self._min_lr_mult = self.config.get("min_lr_mult", 0.01)
        self._warm_start_lr = self.config.get("warm_start_lr", 0.001)
        logger.info("LearningRateScheduler initialized (annealing=%s)", self._annealing_schedule.value)

    def compute_rate(
        self,
        state: RuleLearningState,
        epoch: int,
        convergence_score: float,
    ) -> float:
        """Compute the next learning rate based on the annealing schedule.

        Args:
            state: Current learning state for the rule.
            epoch: Current training epoch.
            convergence_score: Current convergence score (0-1).

        Returns:
            The computed learning rate.
        """
        schedule = self._annealing_schedule
        base = state.base_learning_rate
        min_rate = state.min_learning_rate
        if schedule == AnnealingSchedule.MONOTONIC:
            return self._monotonic(base, epoch, convergence_score)
        if schedule == AnnealingSchedule.CYCLICAL:
            return self._cyclical(base, epoch, min_rate)
        if schedule == AnnealingSchedule.WARM_RESTART:
            return self._warm_restart(base, epoch, min_rate)
        if schedule == AnnealingSchedule.ADAPTIVE:
            return self._adaptive(base, epoch, convergence_score, state)
        return base

    def _monotonic(self, base: float, epoch: int, convergence_score: float) -> float:
        """Monotonic annealing that reduces rate as convergence approaches."""
        factor = 1.0 - convergence_score * 0.9
        return base * max(factor, self._min_lr_mult)

    def _cyclical(self, base: float, epoch: int, min_rate: float) -> float:
        """Cyclical annealing with cosine-shaped cycles."""
        cycle_pos = (epoch % self._cycle_length) / max(self._cycle_length, 1)
        cosine = 0.5 * (1.0 + math.cos(math.pi * cycle_pos))
        return min_rate + (base - min_rate) * cosine

    def _warm_restart(self, base: float, epoch: int, min_rate: float) -> float:
        """Warm restarts with increasing cycle lengths (SGDR)."""
        cycle = 0
        cycle_start = 0
        while epoch >= cycle_start + self._cycle_length * (self._cycle_mult ** cycle):
            cycle_start += int(self._cycle_length * (self._cycle_mult ** cycle))
            cycle += 1
        cycle_pos = (epoch - cycle_start) / max(self._cycle_length * (self._cycle_mult ** cycle), 1)
        cosine = 0.5 * (1.0 + math.cos(math.pi * cycle_pos))
        return min_rate + (base - min_rate) * cosine

    def _adaptive(self, base: float, epoch: int, convergence_score: float, state: RuleLearningState) -> float:
        """Adaptive annealing that responds to convergence and divergence signals."""
        if state.divergence_detected():
            reduced = base * (1.0 - convergence_score * 0.5)
            return max(reduced, state.min_learning_rate)
        if state.loss_plateau_detected():
            reduced = base * 0.5
            return max(reduced, state.min_learning_rate)
        return base * max(1.0 - convergence_score * 0.5, self._min_lr_mult)

    def get_warm_start_rate(self, state: RuleLearningState) -> float:
        """Get the rate to use after a warm restart."""
        return self._warm_start_lr


class LearningRateController:
    """Controller for managing learning rates across rules.

    Provides adaptive learning rate adjustment with multiple decay strategies,
    convergence detection, per-rule learning states, rate scheduling and
    annealing, and comprehensive statistics and reporting.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._states: Dict[str, RuleLearningState] = {}
        self._adjustment_history: deque = deque(
            maxlen=self.config.get("max_history", 5000)
        )
        self._convergence_detector = ConvergenceDetector(self.config.get("convergence", {}))
        self._rate_scheduler = LearningRateScheduler(self.config.get("scheduler", {}))
        self._default_lr = self.config.get("default_learning_rate", 0.01)
        self._default_decay = DecayStrategy(self.config.get("default_decay", "exponential"))
        self._default_decay_rate = self.config.get("default_decay_rate", 0.96)
        self._default_min_lr = self.config.get("default_min_learning_rate", 1e-6)
        self._default_max_lr = self.config.get("default_max_learning_rate", 1.0)
        self._auto_adjust = self.config.get("auto_adjust", True)
        self._adjust_interval = self.config.get("adjust_interval", 50)
        self._start_time: datetime = datetime.utcnow()

        logger.info(
            "LearningRateController initialized (default_lr=%.6f, decay=%s, auto_adjust=%s)",
            self._default_lr, self._default_decay.value, self._auto_adjust,
        )

    def initialize_rule(
        self,
        rule_id: str,
        learning_rate: Optional[float] = None,
        decay_strategy: Optional[DecayStrategy] = None,
        decay_rate: Optional[float] = None,
        min_lr: Optional[float] = None,
        max_lr: Optional[float] = None,
        tier: Optional[RuleTier] = None,
    ) -> RuleLearningState:
        """Initialize or re-initialize learning state for a rule.

        Args:
            rule_id: Identifier for the rule.
            learning_rate: Initial learning rate.
            decay_strategy: Decay strategy to use.
            decay_rate: Rate of decay per epoch/step.
            min_lr: Minimum allowed learning rate.
            max_lr: Maximum allowed learning rate.
            tier: Rule tier (safety rules may get different defaults).

        Returns:
            The initialized RuleLearningState.
        """
        lr = learning_rate or self._default_lr
        if tier == RuleTier.SAFETY:
            lr = min(lr, self.config.get("safety_max_lr", 0.001))

        state = RuleLearningState(
            rule_id=rule_id,
            learning_rate=lr,
            base_learning_rate=lr,
            min_learning_rate=min_lr or self._default_min_lr,
            max_learning_rate=max_lr or self._default_max_lr,
            decay_strategy=decay_strategy or self._default_decay,
            decay_rate=decay_rate or self._default_decay_rate,
            tier=tier,
        )

        self._states[rule_id] = state
        logger.info(
            "Initialized rule %s: lr=%.6f, decay=%s, decay_rate=%.4f",
            rule_id, lr, state.decay_strategy.value, state.decay_rate,
        )
        return state

    def initialize_rules(
        self,
        rules: List[Rule],
        default_lr: Optional[float] = None,
    ) -> Dict[str, RuleLearningState]:
        """Initialize learning states for multiple rules.

        Args:
            rules: List of rules to initialize.
            default_lr: Optional default learning rate override.

        Returns:
            Dict of rule_id -> RuleLearningState.
        """
        states: Dict[str, RuleLearningState] = {}
        for rule in rules:
            lr = default_lr or self.config.get(f"lr_{rule.rule_type.value}", self._default_lr)
            state = self.initialize_rule(
                rule_id=rule.id,
                learning_rate=lr,
                tier=rule.tier,
            )
            states[rule.id] = state
        logger.info("Initialized %d rules", len(states))
        return states

    def get_learning_rate(self, rule_id: str) -> Optional[float]:
        """Get the current learning rate for a rule.

        Args:
            rule_id: The rule identifier.

        Returns:
            Current learning rate, or None if rule not tracked.
        """
        state = self._states.get(rule_id)
        if state is None:
            return None
        return state.learning_rate

    def get_learning_rates(self) -> Dict[str, float]:
        """Get current learning rates for all tracked rules.

        Returns:
            Dict of rule_id -> learning_rate.
        """
        return {rid: s.learning_rate for rid, s in self._states.items()}

    def set_learning_rate(
        self,
        rule_id: str,
        rate: float,
        cause: RateAdjustmentCause = RateAdjustmentCause.MANUAL_OVERRIDE,
    ) -> bool:
        """Manually set the learning rate for a rule.

        Args:
            rule_id: The rule identifier.
            rate: New learning rate value.
            cause: Reason for the adjustment.

        Returns:
            True if the rate was updated.
        """
        state = self._states.get(rule_id)
        if state is None:
            logger.warning("Rule %s not tracked, cannot set rate", rule_id)
            return False

        old_rate = state.learning_rate
        state.apply_rate(rate)

        self._record_adjustment(
            rule_id=rule_id,
            old_rate=old_rate,
            new_rate=rate,
            cause=cause,
        )

        logger.info(
            "Manually set rate for rule %s: %.6f -> %.6f (%s)",
            rule_id, old_rate, rate, cause.value,
        )
        return True

    def record_loss(self, rule_id: str, loss: float) -> None:
        """Record a loss value for a rule's learning process.

        Args:
            rule_id: The rule identifier.
            loss: The loss value to record.
        """
        state = self._states.get(rule_id)
        if state is None:
            return
        state.record_loss(loss)

    def record_gradient(self, rule_id: str, gradient: float) -> None:
        """Record a gradient norm value for a rule.

        Args:
            rule_id: The rule identifier.
            gradient: The gradient norm value.
        """
        state = self._states.get(rule_id)
        if state is None:
            return
        state.record_gradient(gradient)

    def record_parameter_change(self, rule_id: str, change: float) -> None:
        """Record a parameter change magnitude.

        Args:
            rule_id: The rule identifier.
            change: The magnitude of parameter change.
        """
        state = self._states.get(rule_id)
        if state is None:
            return
        state.record_parameter_change(change)

    def record_performance(self, rule_id: str, metric: float) -> None:
        """Record a performance metric value.

        Args:
            rule_id: The rule identifier.
            metric: The performance metric (higher is better).
        """
        state = self._states.get(rule_id)
        if state is None:
            return
        state.record_performance(metric)
        self._maybe_adjust_rule(rule_id)

    def step(self, rule_ids: Optional[List[str]] = None) -> Dict[str, float]:
        """Advance one epoch for specified rules (or all active rules).

        Computes and applies updated learning rates based on decay
        strategies, convergence status, and divergence signals.

        Args:
            rule_ids: Rules to step. If None, steps all tracked rules.

        Returns:
            Dict of rule_id -> new_learning_rate for rules that changed.
        """
        targets = rule_ids or list(self._states.keys())
        changes: Dict[str, float] = {}

        for rid in targets:
            state = self._states.get(rid)
            if state is None or state.is_frozen:
                continue

            state.current_epoch += 1
            old_rate = state.learning_rate

            is_converged, conv_score = self._convergence_detector.check_convergence(state)
            if is_converged and state.convergence_epoch is None:
                state.convergence_epoch = state.current_epoch
                logger.info(
                    "Rule %s converged at epoch %d (score=%.4f)",
                    rid, state.current_epoch, conv_score,
                )

            computed_rate = self._rate_scheduler.compute_rate(
                state, state.current_epoch, conv_score,
            )

            cause = RateAdjustmentCause.SCHEDULED_DECAY
            if state.divergence_detected():
                computed_rate *= 0.5
                state.divergence_count += 1
                cause = RateAdjustmentCause.DIVERGENCE_DETECTED
                logger.warning("Divergence detected for rule %s, reducing rate", rid)
            elif state.loss_plateau_detected():
                state.plateau_count += 1
                cause = RateAdjustmentCause.PLATEAU_DETECTED
            elif state.gradient_spike_detected():
                computed_rate *= 0.7
                cause = RateAdjustmentCause.GRADIENT_SPIKE

            state.apply_rate(computed_rate)
            new_rate = state.learning_rate

            if abs(new_rate - old_rate) > 1e-10:
                self._record_adjustment(
                    rule_id=rid,
                    old_rate=old_rate,
                    new_rate=new_rate,
                    cause=cause,
                    gradient=state.gradient_history[-1] if state.gradient_history else None,
                    loss=state.loss_history[-1] if state.loss_history else None,
                    epoch=state.current_epoch,
                )
                changes[rid] = new_rate

        if changes:
            logger.debug("Stepped %d rules, %d rates changed", len(targets), len(changes))

        return changes

    def warm_restart(self, rule_ids: Optional[List[str]] = None) -> Dict[str, float]:
        """Perform a warm restart of learning rates for specified rules.

        Resets the learning rate to the warm-start value and clears
        convergence state, allowing the learning process to escape
        local minima.

        Args:
            rule_ids: Rules to restart. None restarts all tracked rules.

        Returns:
            Dict of rule_id -> new_learning_rate.
        """
        targets = rule_ids or list(self._states.keys())
        results: Dict[str, float] = {}

        for rid in targets:
            state = self._states.get(rid)
            if state is None:
                continue

            old_rate = state.learning_rate
            warm_rate = self._rate_scheduler.get_warm_start_rate(state)
            state.apply_rate(warm_rate)
            state.convergence_epoch = None
            state.warm_restart_count += 1
            state.current_epoch = 0

            self._record_adjustment(
                rule_id=rid,
                old_rate=old_rate,
                new_rate=warm_rate,
                cause=RateAdjustmentCause.WARM_RESTART,
                epoch=0,
            )

            results[rid] = warm_rate
            logger.info(
                "Warm restart for rule %s: %.6f -> %.6f (restart #%d)",
                rid, old_rate, warm_rate, state.warm_restart_count,
            )

        return results

    def freeze_rule(self, rule_id: str) -> bool:
        """Freeze a rule's learning rate, preventing further adjustments.

        Args:
            rule_id: The rule to freeze.

        Returns:
            True if the rule was frozen.
        """
        state = self._states.get(rule_id)
        if state is None:
            return False
        state.is_frozen = True
        state.frozen_at = datetime.utcnow()
        logger.info("Frozen learning rate for rule %s (rate=%.6f)", rule_id, state.learning_rate)
        return True

    def unfreeze_rule(self, rule_id: str) -> bool:
        """Unfreeze a previously frozen rule's learning rate.

        Args:
            rule_id: The rule to unfreeze.

        Returns:
            True if the rule was unfrozen.
        """
        state = self._states.get(rule_id)
        if state is None:
            return False
        state.is_frozen = False
        state.frozen_at = None
        logger.info("Unfrozen learning rate for rule %s", rule_id)
        return True

    def get_state(self, rule_id: str) -> Optional[RuleLearningState]:
        """Get the full learning state for a rule.

        Args:
            rule_id: The rule identifier.

        Returns:
            The RuleLearningState, or None if not tracked.
        """
        return self._states.get(rule_id)

    def get_all_states(self) -> Dict[str, RuleLearningState]:
        """Get learning states for all tracked rules.

        Returns:
            Dict of rule_id -> RuleLearningState.
        """
        return dict(self._states)

    def get_convergence_status(self, rule_id: str) -> Dict[str, Any]:
        """Get convergence status for a specific rule.

        Args:
            rule_id: The rule identifier.

        Returns:
            Dict with convergence information.
        """
        state = self._states.get(rule_id)
        if state is None:
            return {"rule_id": rule_id, "tracked": False}

        is_converged, score = self._convergence_detector.check_convergence(state)

        return {
            "rule_id": rule_id,
            "tracked": True,
            "is_converged": is_converged,
            "convergence_score": round(score, 4),
            "convergence_epoch": state.convergence_epoch,
            "current_epoch": state.current_epoch,
            "is_frozen": state.is_frozen,
            "plateau_count": state.plateau_count,
            "divergence_count": state.divergence_count,
            "learning_rate": state.learning_rate,
            "loss_samples": len(state.loss_history),
            "gradient_samples": len(state.gradient_history),
        }

    def get_convergence_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Get convergence status for all tracked rules.

        Returns:
            Dict of rule_id -> convergence status dict.
        """
        return {rid: self.get_convergence_status(rid) for rid in self._states}

    def get_adjustment_history(
        self,
        rule_id: Optional[str] = None,
        cause: Optional[RateAdjustmentCause] = None,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[LearningRateRecord]:
        """Query adjustment history with filters.

        Args:
            rule_id: Filter by rule ID.
            cause: Filter by adjustment cause.
            since: Only records after this datetime.
            limit: Max results.
            offset: Records to skip.

        Returns:
            Filtered list of LearningRateRecord.
        """
        records = list(self._adjustment_history)

        if rule_id:
            records = [r for r in records if r.rule_id == rule_id]
        if cause:
            records = [r for r in records if r.cause == cause]
        if since:
            records = [r for r in records if r.timestamp >= since]

        records.sort(key=lambda r: r.timestamp, reverse=True)
        records = records[offset:]
        if limit:
            records = records[:limit]

        return records

    def export_adjustments(
        self,
        format: str = "json",
        rule_id: Optional[str] = None,
    ) -> str:
        """Export adjustment history as JSON string.

        Args:
            format: Output format ("json" only currently).
            rule_id: Optional rule filter.

        Returns:
            Formatted string of adjustment history.
        """
        records = self.get_adjustment_history(rule_id=rule_id)

        data = [
            {
                "record_id": r.record_id,
                "rule_id": r.rule_id,
                "learning_rate_before": r.learning_rate_before,
                "learning_rate_after": r.learning_rate_after,
                "cause": r.cause.value,
                "decay_strategy": r.decay_strategy.value,
                "gradient_value": r.gradient_value,
                "loss_value": r.loss_value,
                "performance_metric": r.performance_metric,
                "epoch": r.epoch,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in records
        ]
        return json.dumps(data, indent=2, default=str)

    def export_state(self) -> Dict[str, Any]:
        """Export the current controller state as a serializable dictionary.

        Returns:
            Dict with all states and configuration.
        """
        return {
            "controller_version": "1.0.0",
            "default_learning_rate": self._default_lr,
            "default_decay": self._default_decay.value,
            "default_decay_rate": self._default_decay_rate,
            "states": {
                rid: {
                    "rule_id": s.rule_id,
                    "learning_rate": s.learning_rate,
                    "base_learning_rate": s.base_learning_rate,
                    "min_learning_rate": s.min_learning_rate,
                    "max_learning_rate": s.max_learning_rate,
                    "decay_strategy": s.decay_strategy.value,
                    "decay_rate": s.decay_rate,
                    "step_size": s.step_size,
                    "current_epoch": s.current_epoch,
                    "total_adjustments": s.total_adjustments,
                    "plateau_count": s.plateau_count,
                    "divergence_count": s.divergence_count,
                    "convergence_epoch": s.convergence_epoch,
                    "warm_restart_count": s.warm_restart_count,
                    "is_frozen": s.is_frozen,
                    "tier": s.tier.value if s.tier else None,
                }
                for rid, s in self._states.items()
            },
            "exported_at": datetime.utcnow().isoformat(),
        }

    def import_state(self, data: Dict[str, Any]) -> int:
        """Import previously exported controller state.

        Args:
            data: Dictionary from export_state().

        Returns:
            Number of states imported.
        """
        count = 0
        try:
            states_data = data.get("states", {})
            for rid, sdata in states_data.items():
                try:
                    decay_strategy = DecayStrategy(sdata.get("decay_strategy", "exponential"))
                except ValueError:
                    decay_strategy = DecayStrategy.EXPONENTIAL
                tier_raw = sdata.get("tier")
                tier = RuleTier(tier_raw) if tier_raw else None

                state = RuleLearningState(
                    rule_id=sdata.get("rule_id", rid),
                    learning_rate=sdata.get("learning_rate", self._default_lr),
                    base_learning_rate=sdata.get("base_learning_rate", self._default_lr),
                    min_learning_rate=sdata.get("min_learning_rate", self._default_min_lr),
                    max_learning_rate=sdata.get("max_learning_rate", self._default_max_lr),
                    decay_strategy=decay_strategy,
                    decay_rate=sdata.get("decay_rate", self._default_decay_rate),
                    step_size=sdata.get("step_size", 100),
                    current_epoch=sdata.get("current_epoch", 0),
                    total_adjustments=sdata.get("total_adjustments", 0),
                    plateau_count=sdata.get("plateau_count", 0),
                    divergence_count=sdata.get("divergence_count", 0),
                    convergence_epoch=sdata.get("convergence_epoch"),
                    warm_restart_count=sdata.get("warm_restart_count", 0),
                    is_frozen=sdata.get("is_frozen", False),
                    tier=tier,
                )
                self._states[rid] = state
                count += 1

            logger.info("Imported %d learning states", count)
            return count

        except Exception as exc:
            logger.error("Failed to import states: %s", exc, exc_info=True)
            return count

    def is_converged(self, rule_id: str, threshold: Optional[float] = None) -> bool:
        """Quick check if a rule's learning process has converged.

        Args:
            rule_id: The rule identifier.
            threshold: Override convergence threshold.

        Returns:
            True if converged.
        """
        state = self._states.get(rule_id)
        if state is None:
            return False
        is_c, _ = self._convergence_detector.check_convergence(state)
        return is_c

    def are_all_converged(self) -> bool:
        """Check if all tracked rules have converged.

        Returns:
            True if all tracked rules are converged.
        """
        if not self._states:
            return False
        return all(self.is_converged(rid) for rid in self._states)

    def reset_rule(self, rule_id: str) -> bool:
        """Reset a rule's learning state to initial conditions.

        Args:
            rule_id: The rule to reset.

        Returns:
            True if the rule was reset.
        """
        state = self._states.get(rule_id)
        if state is None:
            return False
        state.learning_rate = state.base_learning_rate
        state.current_epoch = 0
        state.total_adjustments = 0
        state.last_adjustment_time = None
        state.loss_history.clear()
        state.gradient_history.clear()
        state.parameter_change_history.clear()
        state.performance_history.clear()
        state.plateau_count = 0
        state.divergence_count = 0
        state.convergence_epoch = None
        state.warm_restart_count = 0
        state.is_frozen = False
        state.frozen_at = None
        logger.info("Reset learning state for rule %s", rule_id)
        return True

    def reset_all(self) -> int:
        """Reset all learning states to initial conditions.

        Returns:
            Number of states reset.
        """
        count = 0
        for rid in list(self._states.keys()):
            if self.reset_rule(rid):
                count += 1
        logger.info("Reset %d learning states", count)
        return count

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule from tracking entirely.

        Args:
            rule_id: The rule to remove.

        Returns:
            True if the rule was removed.
        """
        if rule_id in self._states:
            del self._states[rule_id]
            logger.info("Removed rule %s from learning rate tracking", rule_id)
            return True
        return False

    def get_statistics(self) -> LearningRateStatistics:
        """Get aggregated statistics about the learning rate controller.

        Returns:
            LearningRateStatistics with comprehensive metrics.
        """
        all_rates = [s.learning_rate for s in self._states.values()]
        if not all_rates:
            return LearningRateStatistics()

        by_cause: Dict[str, int] = defaultdict(int)
        by_strategy: Dict[str, int] = defaultdict(int)
        for record in self._adjustment_history:
            by_cause[record.cause.value] += 1
            by_strategy[record.decay_strategy.value] += 1

        sorted_rates = sorted(all_rates)
        n = len(sorted_rates)
        median_rate = sorted_rates[n // 2] if n % 2 else (sorted_rates[n // 2 - 1] + sorted_rates[n // 2]) / 2.0

        converged = sum(1 for s in self._states.values() if s.convergence_epoch is not None)
        frozen = sum(1 for s in self._states.values() if s.is_frozen)
        total_plateau = sum(s.plateau_count for s in self._states.values())
        total_divergence = sum(s.divergence_count for s in self._states.values())
        total_restarts = sum(s.warm_restart_count for s in self._states.values())

        conv_scores = []
        for state in self._states.values():
            _, score = self._convergence_detector.check_convergence(state)
            conv_scores.append(score)
        avg_conv = sum(conv_scores) / len(conv_scores) if conv_scores else 0.0

        uptime = (datetime.utcnow() - self._start_time).total_seconds() / 3600.0

        last_time = None
        if self._adjustment_history:
            last_time = self._adjustment_history[-1].timestamp

        return LearningRateStatistics(
            total_rules_tracked=len(self._states),
            active_rules=len(self._states) - frozen,
            frozen_rules=frozen,
            converged_rules=converged,
            total_adjustments=len(self._adjustment_history),
            average_learning_rate=sum(all_rates) / len(all_rates),
            median_learning_rate=median_rate,
            min_learning_rate=min(all_rates),
            max_learning_rate=max(all_rates),
            adjustments_by_cause=dict(by_cause),
            adjustments_by_strategy=dict(by_strategy),
            plateau_events=total_plateau,
            divergence_events=total_divergence,
            warm_restarts=total_restarts,
            average_convergence_score=round(avg_conv, 4),
            last_adjustment_time=last_time,
            uptime_hours=round(uptime, 2),
        )

    def get_rule_summary(self, rule_id: str) -> Dict[str, Any]:
        """Get a detailed summary for a specific rule.

        Args:
            rule_id: The rule identifier.

        Returns:
            Dict with comprehensive rule learning information.
        """
        state = self._states.get(rule_id)
        if state is None:
            return {"rule_id": rule_id, "tracked": False}

        is_converged, conv_score = self._convergence_detector.check_convergence(state)
        recent_adjustments = self.get_adjustment_history(rule_id=rule_id, limit=10)

        total_loss = len(state.loss_history)
        recent_loss = list(state.loss_history)[-10:] if total_loss >= 10 else list(state.loss_history)
        loss_trend = sum(recent_loss) / len(recent_loss) if recent_loss else 0.0

        return {
            "rule_id": rule_id,
            "tracked": True,
            "learning_rate": state.learning_rate,
            "base_learning_rate": state.base_learning_rate,
            "min_learning_rate": state.min_learning_rate,
            "max_learning_rate": state.max_learning_rate,
            "decay_strategy": state.decay_strategy.value,
            "decay_rate": state.decay_rate,
            "current_epoch": state.current_epoch,
            "total_adjustments": state.total_adjustments,
            "is_frozen": state.is_frozen,
            "is_converged": is_converged,
            "convergence_score": round(conv_score, 4),
            "convergence_epoch": state.convergence_epoch,
            "plateau_count": state.plateau_count,
            "divergence_count": state.divergence_count,
            "warm_restart_count": state.warm_restart_count,
            "tier": state.tier.value if state.tier else None,
            "loss_samples": total_loss,
            "recent_loss_trend": round(loss_trend, 6),
            "gradient_samples": len(state.gradient_history),
            "parameter_change_samples": len(state.parameter_change_history),
            "performance_samples": len(state.performance_history),
            "last_adjustment_time": state.last_adjustment_time.isoformat() if state.last_adjustment_time else None,
            "recent_adjustments": [
                {
                    "epoch": r.epoch,
                    "rate_before": r.learning_rate_before,
                    "rate_after": r.learning_rate_after,
                    "cause": r.cause.value,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in recent_adjustments
            ],
        }

    def generate_report(self) -> Dict[str, Any]:
        """Generate a comprehensive report on the learning rate controller.

        Returns:
            Dict with full report data including statistics, per-rule
            summaries, and configuration.
        """
        stats = self.get_statistics()

        converged_rules: List[Dict[str, Any]] = []
        active_rules: List[Dict[str, Any]] = []
        frozen_rules: List[Dict[str, Any]] = []

        for rid, state in self._states.items():
            _, conv_score = self._convergence_detector.check_convergence(state)
            entry = {
                "rule_id": rid,
                "learning_rate": state.learning_rate,
                "epoch": state.current_epoch,
                "convergence_score": round(conv_score, 4),
            }
            if state.is_frozen:
                frozen_rules.append(entry)
            elif state.convergence_epoch is not None:
                converged_rules.append(entry)
            else:
                active_rules.append(entry)

        return {
            "report_time": datetime.utcnow().isoformat(),
            "uptime_hours": stats.uptime_hours,
            "statistics": {
                "total_rules_tracked": stats.total_rules_tracked,
                "active_rules": stats.active_rules,
                "converged_rules": stats.converged_rules,
                "frozen_rules": stats.frozen_rules,
                "total_adjustments": stats.total_adjustments,
                "average_learning_rate": round(stats.average_learning_rate, 6),
                "median_learning_rate": round(stats.median_learning_rate, 6),
                "learning_rate_range": [round(stats.min_learning_rate, 6), round(stats.max_learning_rate, 6)],
                "plateau_events": stats.plateau_events,
                "divergence_events": stats.divergence_events,
                "warm_restarts": stats.warm_restarts,
                "average_convergence_score": stats.average_convergence_score,
                "adjustments_by_cause": stats.adjustments_by_cause,
                "adjustments_by_strategy": stats.adjustments_by_strategy,
            },
            "converged_rules": converged_rules[:50],
            "active_rules": active_rules[:50],
            "frozen_rules": frozen_rules[:50],
            "configuration": {
                "default_learning_rate": self._default_lr,
                "default_decay": self._default_decay.value,
                "default_decay_rate": self._default_decay_rate,
                "default_min_learning_rate": self._default_min_lr,
                "default_max_learning_rate": self._default_max_lr,
                "auto_adjust": self._auto_adjust,
                "adjust_interval": self._adjust_interval,
                "convergence_metric": self._convergence_detector._metric.value,
                "annealing_schedule": self._rate_scheduler._annealing_schedule.value,
            },
        }

    def _maybe_adjust_rule(self, rule_id: str) -> None:
        """Automatically adjust learning rate based on performance, if enabled.

        Args:
            rule_id: The rule to potentially adjust.
        """
        if not self._auto_adjust:
            return

        state = self._states.get(rule_id)
        if state is None or state.is_frozen:
            return

        if state.current_epoch % self._adjust_interval == 0 and state.current_epoch > 0:
            self.step([rule_id])

    def _record_adjustment(
        self,
        rule_id: str,
        old_rate: float,
        new_rate: float,
        cause: RateAdjustmentCause,
        gradient: Optional[float] = None,
        loss: Optional[float] = None,
        epoch: int = 0,
    ) -> LearningRateRecord:
        """Record a learning rate adjustment in the history.

        Args:
            rule_id: The rule that was adjusted.
            old_rate: Previous learning rate.
            new_rate: New learning rate.
            cause: Reason for adjustment.
            gradient: Optional gradient value at adjustment time.
            loss: Optional loss value at adjustment time.
            epoch: Current epoch at adjustment time.

        Returns:
            The created LearningRateRecord.
        """
        state = self._states.get(rule_id)

        record = LearningRateRecord(
            record_id=str(uuid.uuid4()),
            rule_id=rule_id,
            learning_rate_before=old_rate,
            learning_rate_after=new_rate,
            cause=cause,
            decay_strategy=state.decay_strategy if state else self._default_decay,
            gradient_value=gradient,
            loss_value=loss,
            epoch=epoch,
        )

        self._adjustment_history.append(record)
        return record
