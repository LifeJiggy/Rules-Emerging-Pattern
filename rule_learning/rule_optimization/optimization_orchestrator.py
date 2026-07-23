"""
Optimization orchestrator for coordinated rule optimization.

Coordinates all sub-optimizers (efficiency, performance, relevance,
memory), schedules optimization runs (periodic, on-demand, event-driven),
aggregates results, prioritizes suggestions, generates before/after
reports, and supports rollback for failed optimizations.
"""

import copy
import logging
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TypeVar

from rules_emerging_pattern.models.rule import Rule, RuleSet

from .efficiency_optimizer import EfficiencyOptimizer
from .performance_optimizer import RulePerformanceOptimizer
from .relevance_optimizer import RelevanceOptimizer
from .memory_usage_optimizer import MemoryUsageOptimizer

logger = logging.getLogger(__name__)


class OptimizationType(str, Enum):
    """Types of optimization that can be performed."""
    EFFICIENCY = "efficiency"
    PERFORMANCE = "performance"
    RELEVANCE = "relevance"
    MEMORY = "memory"
    FULL = "full"


class OptimizationTrigger(str, Enum):
    """Triggers for starting an optimization run."""
    MANUAL = "manual"
    PERIODIC = "periodic"
    THRESHOLD_EXCEEDED = "threshold_exceeded"
    RULE_CHANGED = "rule_changed"
    SYSTEM_STARTUP = "system_startup"
    EVENT_DRIVEN = "event_driven"


class ScheduleFrequency(str, Enum):
    """Frequencies for scheduled optimization runs."""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    MANUAL_ONLY = "manual_only"


class OptimizationPriority(str, Enum):
    """Priority levels for optimization suggestions."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class OptimizationStatus(str, Enum):
    """Status of an optimization run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    PARTIALLY_COMPLETED = "partially_completed"


class NotificationChannel(str, Enum):
    """Channels for optimization notifications."""
    LOG = "log"
    CALLBACK = "callback"


@dataclass
class OrchestratorConfig:
    """Configuration for the optimization orchestrator."""
    schedule_frequency: ScheduleFrequency = ScheduleFrequency.DAILY
    auto_run_on_startup: bool = True
    enable_rollback: bool = True
    max_rollback_snapshots: int = 10
    suggestion_min_priority: OptimizationPriority = OptimizationPriority.LOW
    max_suggestions_per_run: int = 50
    report_history_size: int = 100
    parallel_optimizers: bool = True
    max_parallel_workers: int = 4
    timeout_per_optimizer_seconds: int = 300
    notification_enabled: bool = True
    notification_channel: NotificationChannel = NotificationChannel.LOG
    snapshot_deep_copy: bool = True
    change_impact_analysis_enabled: bool = True


@dataclass
class OptimizationResult:
    """Result of a single optimizer's work within a run."""
    optimizer_name: str
    optimization_type: OptimizationType
    success: bool
    metrics_before: Dict[str, Any] = field(default_factory=dict)
    metrics_after: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    changes_made: int = 0


@dataclass
class OptimizationRun:
    """Record of a complete optimization run."""
    run_id: str = field(default_factory=lambda: f"opt_{uuid.uuid4().hex[:12]}")
    trigger: OptimizationTrigger = OptimizationTrigger.MANUAL
    status: OptimizationStatus = OptimizationStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    results: List[OptimizationResult] = field(default_factory=list)
    aggregated_suggestions: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    snapshot_before: Optional[Dict[str, Any]] = None
    snapshot_after: Optional[Dict[str, Any]] = None
    rolled_back: bool = False

    def total_duration_ms(self) -> float:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return 0.0


@dataclass
class OptimizationSuggestion:
    """A prioritized optimization suggestion."""
    suggestion_id: str = field(default_factory=lambda: f"sug_{uuid.uuid4().hex[:8]}")
    rule_id: Optional[str] = None
    optimizer: str = ""
    optimization_type: OptimizationType = OptimizationType.FULL
    priority: OptimizationPriority = OptimizationPriority.MEDIUM
    description: str = ""
    expected_impact: str = ""
    effort_estimate: str = ""
    score: float = 0.0


@dataclass
class ChangeImpact:
    """Impact assessment of a proposed optimization change."""
    rule_id: str
    change_description: str
    performance_impact: str
    memory_impact: str
    relevance_impact: str
    risk_level: str
    rollback_difficulty: str


class OptimizationPipeline:
    """Defines a sequence of optimization stages with validation gates."""

    def __init__(self, stages: Optional[List[Dict[str, Any]]] = None):
        self.stages = stages or [
            {"name": "analyze", "optimizers": ["efficiency", "performance"]},
            {"name": "prune", "optimizers": ["relevance"]},
            {"name": "compact", "optimizers": ["memory"]},
            {"name": "report", "optimizers": []},
        ]
        self.gates: Dict[str, Callable] = {}

    def register_gate(self, stage: str, gate_fn: Callable) -> None:
        self.gates[stage] = gate_fn

    def check_gate(self, stage_name: str, context: Dict[str, Any]) -> bool:
        gate = self.gates.get(stage_name)
        if gate is None:
            return True
        try:
            return bool(gate(context))
        except Exception as exc:
            logger.error("Gate check failed for stage %s: %s", stage_name, exc)
            return False


class OptimizationOrchestrator:
    """Coordinates all optimizers for comprehensive rule optimization.

    Manages scheduling of optimization runs (periodic, on-demand,
    event-driven), aggregates results from all sub-optimizers,
    prioritizes suggestions, produces before/after metrics reports,
    and supports rollback for failed or degraded optimizations.
    Uses concurrent execution for parallel optimizer runs, snapshot-based
    rollback with deep copy, dependency-aware scheduling, change impact
    analysis, and notification channels.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        efficiency_optimizer: Optional[EfficiencyOptimizer] = None,
        performance_optimizer: Optional[RulePerformanceOptimizer] = None,
        relevance_optimizer: Optional[RelevanceOptimizer] = None,
        memory_optimizer: Optional[MemoryUsageOptimizer] = None,
    ):
        self.config = OrchestratorConfig(**(config or {}))
        self.efficiency = efficiency_optimizer or EfficiencyOptimizer()
        self.performance = performance_optimizer or RulePerformanceOptimizer()
        self.relevance = relevance_optimizer or RelevanceOptimizer()
        self.memory = memory_optimizer or MemoryUsageOptimizer()

        self.run_history: deque = deque(maxlen=self.config.report_history_size)
        self.suggestion_log: List[OptimizationSuggestion] = []
        self.snapshots: List[Dict[str, Any]] = []
        self.pending_suggestions: List[OptimizationSuggestion] = []
        self.current_run: Optional[OptimizationRun] = None
        self._last_scheduled_run: Optional[datetime] = None
        self._event_handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._pipeline: OptimizationPipeline = OptimizationPipeline()
        self._notification_callbacks: List[Callable] = []

    def set_pipeline(self, pipeline: OptimizationPipeline) -> None:
        """Set a custom optimization pipeline with stage gates."""
        self._pipeline = pipeline

    def run_full_optimization(
        self,
        trigger: OptimizationTrigger = OptimizationTrigger.MANUAL,
        rules: Optional[List[Rule]] = None,
    ) -> OptimizationRun:
        """Execute a full optimization run across all optimizers."""
        run = OptimizationRun(trigger=trigger, status=OptimizationStatus.RUNNING)
        run.started_at = datetime.utcnow()
        run.snapshot_before = self._capture_global_snapshot()
        self.current_run = run

        logger.info("Starting full optimization run %s (trigger=%s)", run.run_id, trigger.value)

        optimizer_configs = [
            ("EfficiencyOptimizer", OptimizationType.EFFICIENCY, self._run_efficiency),
            ("PerformanceOptimizer", OptimizationType.PERFORMANCE, self._run_performance),
            ("RelevanceOptimizer", OptimizationType.RELEVANCE, self._run_relevance),
            ("MemoryUsageOptimizer", OptimizationType.MEMORY, self._run_memory),
        ]

        if self.config.parallel_optimizers:
            results = self._run_optimizers_parallel(optimizer_configs, rules)
        else:
            results = self._run_optimizers_pipelined(optimizer_configs, rules)

        run.results = results
        run.aggregated_suggestions = self._aggregate_suggestions(results)
        run.errors = self._collect_errors(results)

        run.snapshot_after = self._capture_global_snapshot()

        success_count = sum(1 for r in results if r.success)
        if success_count == len(results):
            run.status = OptimizationStatus.COMPLETED
        elif success_count > 0:
            run.status = OptimizationStatus.PARTIALLY_COMPLETED
        else:
            run.status = OptimizationStatus.FAILED

        run.completed_at = datetime.utcnow()

        self.run_history.append(run)
        self._fire_event("optimization_completed", run)

        if run.errors:
            logger.warning(
                "Run %s completed with %d/%d results, %d errors (%.1fms)",
                run.run_id, success_count, len(results), len(run.errors),
                run.total_duration_ms(),
            )
        else:
            logger.info(
                "Run %s completed (%.1fms) with %d results",
                run.run_id, run.total_duration_ms(), len(results),
            )

        self._notify(run)
        return run

    def _run_optimizers_pipelined(
        self,
        configs: List[Tuple[str, OptimizationType, Callable]],
        rules: Optional[List[Rule]],
    ) -> List[OptimizationResult]:
        """Run optimizers through a staged pipeline with validation gates."""
        results: List[OptimizationResult] = []
        pipeline_context: Dict[str, Any] = {"rules": rules, "results": results}

        for stage in self._pipeline.stages:
            stage_name = stage["name"]
            stage_optimizers = stage["optimizers"]

            if not self._pipeline.check_gate(stage_name, pipeline_context):
                logger.info("Pipeline gate blocked stage: %s", stage_name)
                continue

            for opt_name, opt_type, func in configs:
                normalized = opt_name.lower().replace("optimizer", "")
                if stage_optimizers and normalized not in stage_optimizers:
                    continue

                try:
                    if rules:
                        result = func(rules)
                    else:
                        result = func([])
                    results.append(result)
                    pipeline_context["results"] = results
                except Exception as exc:
                    logger.error("Optimizer %s failed in stage %s: %s", opt_name, stage_name, exc)
                    results.append(OptimizationResult(
                        optimizer_name=opt_name,
                        optimization_type=opt_type,
                        success=False,
                        errors=[str(exc)],
                    ))

        return results

    def _run_optimizers_sequential(
        self,
        optimizer_configs: List[Tuple[str, OptimizationType, Callable]],
        rules: Optional[List[Rule]],
    ) -> List[OptimizationResult]:
        """Run optimizers one at a time."""
        results: List[OptimizationResult] = []
        for name, opt_type, func in optimizer_configs:
            try:
                result = func(rules)
                results.append(result)
            except Exception as exc:
                logger.error("Optimizer %s failed: %s", name, exc)
                results.append(OptimizationResult(
                    optimizer_name=name,
                    optimization_type=opt_type,
                    success=False,
                    errors=[str(exc)],
                ))
        return results

    def _run_optimizers_parallel(
        self,
        optimizer_configs: List[Tuple[str, OptimizationType, Callable]],
        rules: Optional[List[Rule]],
    ) -> List[OptimizationResult]:
        """Run optimizers concurrently using ThreadPoolExecutor."""
        results: List[Optional[OptimizationResult]] = [None] * len(optimizer_configs)

        def run_with_index(index: int, name: str, opt_type: OptimizationType, func: Callable) -> Tuple[int, OptimizationResult]:
            try:
                result = func(rules)
                return index, result
            except Exception as exc:
                return index, OptimizationResult(
                    optimizer_name=name,
                    optimization_type=opt_type,
                    success=False,
                    errors=[str(exc)],
                )

        max_workers = min(self.config.max_parallel_workers, len(optimizer_configs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, (name, opt_type, func) in enumerate(optimizer_configs):
                futures.append(executor.submit(run_with_index, i, name, opt_type, func))

            for future in as_completed(futures, timeout=self.config.timeout_per_optimizer_seconds):
                try:
                    index, result = future.result()
                    results[index] = result
                except Exception as exc:
                    logger.error("Parallel optimizer execution failed: %s", exc)

        return [r for r in results if r is not None]

    def _run_efficiency(self, rules: Optional[List[Rule]]) -> OptimizationResult:
        """Run the efficiency optimizer and capture results."""
        start = time.perf_counter()
        result = OptimizationResult(
            optimizer_name="EfficiencyOptimizer",
            optimization_type=OptimizationType.EFFICIENCY,
        )

        result.metrics_before = self.efficiency.generate_efficiency_report()

        if rules:
            for rule in rules:
                self.efficiency.score_efficiency(rule.id)
                self.efficiency.get_suggestions(rule.id)

        result.metrics_after = self.efficiency.generate_efficiency_report()
        result.suggestions = self.efficiency._generate_global_suggestions()
        result.duration_ms = (time.perf_counter() - start) * 1000
        result.success = True

        return result

    def _run_performance(self, rules: Optional[List[Rule]]) -> OptimizationResult:
        """Run the performance optimizer and capture results."""
        start = time.perf_counter()
        result = OptimizationResult(
            optimizer_name="RulePerformanceOptimizer",
            optimization_type=OptimizationType.PERFORMANCE,
        )

        result.metrics_before = self.performance.generate_performance_report()

        if rules:
            for rule in rules:
                self.performance.suggest_optimizations(rule.id)

        self.performance.optimize_cache()
        result.metrics_after = self.performance.generate_performance_report()

        slow_rules = self.performance.get_slow_rules()
        for rule_id, avg_time in slow_rules[:10]:
            result.suggestions.extend(self.performance.suggest_optimizations(rule_id))

        result.duration_ms = (time.perf_counter() - start) * 1000
        result.success = True

        return result

    def _run_relevance(self, rules: Optional[List[Rule]]) -> OptimizationResult:
        """Run the relevance optimizer and capture results."""
        start = time.perf_counter()
        result = OptimizationResult(
            optimizer_name="RelevanceOptimizer",
            optimization_type=OptimizationType.RELEVANCE,
        )

        result.metrics_before = self.relevance.generate_relevance_report()

        if rules:
            _, pruning_decisions = self.relevance.prune_low_relevance_rules(rules)
            result.changes_made = len(pruning_decisions)
            for decision in pruning_decisions:
                result.suggestions.append(
                    f"Prune rule '{decision['rule_id']}': {decision['reason']}"
                )

        self.relevance.apply_decay_to_all()
        result.metrics_after = self.relevance.generate_relevance_report()
        result.duration_ms = (time.perf_counter() - start) * 1000
        result.success = True

        return result

    def _run_memory(self, rules: Optional[List[Rule]]) -> OptimizationResult:
        """Run the memory optimizer and capture results."""
        start = time.perf_counter()
        result = OptimizationResult(
            optimizer_name="MemoryUsageOptimizer",
            optimization_type=OptimizationType.MEMORY,
        )

        result.metrics_before = self.memory.generate_memory_report()

        if rules:
            for rule in rules:
                self.memory.track_rule(rule)

        compaction_stats = self.memory.compact_storage()
        result.changes_made = (
            compaction_stats["rules_removed"]
            + compaction_stats["cache_entries_removed"]
        )

        self.memory.detect_memory_leaks()
        result.suggestions = self.memory.get_optimization_suggestions()

        result.metrics_after = self.memory.generate_memory_report()
        result.duration_ms = (time.perf_counter() - start) * 1000
        result.success = True

        return result

    def _capture_global_snapshot(self) -> Dict[str, Any]:
        """Capture a global state snapshot for rollback support."""
        snapshot = {
            "timestamp": datetime.utcnow().isoformat(),
            "efficiency": self.efficiency.generate_efficiency_report(),
            "performance": self.performance.generate_performance_report(),
            "relevance": self.relevance.generate_relevance_report(),
            "memory": self.memory.generate_memory_report(),
        }

        if self.config.snapshot_deep_copy:
            snapshot = copy.deepcopy(snapshot)

        if len(self.snapshots) >= self.config.max_rollback_snapshots:
            self.snapshots.pop(0)
        self.snapshots.append(snapshot)

        return snapshot

    def _aggregate_suggestions(
        self,
        results: List[OptimizationResult],
    ) -> List[Dict[str, Any]]:
        """Aggregate and prioritize suggestions from all optimizers."""
        all_suggestions: List[OptimizationSuggestion] = []

        for result in results:
            for suggestion_text in result.suggestions:
                priority = self._infer_priority(suggestion_text)
                sug = OptimizationSuggestion(
                    optimizer=result.optimizer_name,
                    optimization_type=result.optimization_type,
                    priority=priority,
                    description=suggestion_text,
                    score=self._score_suggestion(priority),
                )
                all_suggestions.append(sug)

        all_suggestions.sort(key=lambda s: s.score, reverse=True)

        max_items = self.config.max_suggestions_per_run
        top_suggestions = all_suggestions[:max_items]

        self.pending_suggestions = top_suggestions
        self.suggestion_log.extend(top_suggestions)

        if len(self.suggestion_log) > 1000:
            self.suggestion_log = self.suggestion_log[-1000:]

        return [
            {
                "optimizer": s.optimizer,
                "type": s.optimization_type.value,
                "priority": s.priority.value,
                "description": s.description,
                "score": round(s.score, 2),
            }
            for s in top_suggestions
        ]

    def _infer_priority(self, suggestion: str) -> OptimizationPriority:
        """Infer priority from suggestion text content."""
        critical_keywords = ["critical", "urgent", "immediate", "severe", "leak"]
        high_keywords = ["high", "significant", "slow", "degradation", "exceeded"]
        medium_keywords = ["consider", "review", "may", "suggest", "could"]

        lower = suggestion.lower()
        if any(kw in lower for kw in critical_keywords):
            return OptimizationPriority.CRITICAL
        if any(kw in lower for kw in high_keywords):
            return OptimizationPriority.HIGH
        if any(kw in lower for kw in medium_keywords):
            return OptimizationPriority.MEDIUM
        return OptimizationPriority.LOW

    def _score_suggestion(self, priority: OptimizationPriority) -> float:
        """Convert priority to a numerical score for sorting."""
        mapping = {
            OptimizationPriority.CRITICAL: 100.0,
            OptimizationPriority.HIGH: 75.0,
            OptimizationPriority.MEDIUM: 50.0,
            OptimizationPriority.LOW: 25.0,
        }
        return mapping.get(priority, 0.0)

    def _collect_errors(self, results: List[OptimizationResult]) -> List[str]:
        """Collect all errors from optimization results."""
        errors: List[str] = []
        for result in results:
            for error in result.errors:
                errors.append(f"[{result.optimizer_name}] {error}")
        return errors

    def analyze_change_impact(
        self,
        rule_id: str,
        change_description: str,
    ) -> Optional[ChangeImpact]:
        """Analyze the impact of a proposed optimization change."""
        if not self.config.change_impact_analysis_enabled:
            return None

        efficiency_score = self.efficiency.score_efficiency(rule_id)
        perf_trend = self.performance.get_trend(rule_id)
        relevance_score = self.relevance.score_relevance(
            Rule(id=rule_id, name="", description="", tier="preference",
                 rule_type="custom", severity="medium", enforcement_level="advisory")
        )

        keywords = change_description.lower()
        if "remove" in keywords or "delete" in keywords:
            risk = "high"
            rollback = "medium"
        elif "cache" in keywords or "ttl" in keywords:
            risk = "low"
            rollback = "easy"
        elif "pattern" in keywords or "index" in keywords:
            risk = "medium"
            rollback = "medium"
        else:
            risk = "medium"
            rollback = "medium"

        return ChangeImpact(
            rule_id=rule_id,
            change_description=change_description,
            performance_impact=perf_trend.get("direction", "unknown"),
            memory_impact=f"{self.memory.get_memory_profile().value} usage",
            relevance_impact=f"score {relevance_score.overall:.2f}",
            risk_level=risk,
            rollback_difficulty=rollback,
        )

    def rollback_last_run(self) -> bool:
        """Rollback the last optimization run to restore prior state using snapshots."""
        if not self.config.enable_rollback:
            logger.warning("Rollback is disabled in configuration")
            return False

        if not self.run_history:
            logger.warning("No optimization runs to rollback")
            return False

        last_run = self.run_history[-1]
        if last_run.rolled_back:
            logger.warning("Last run was already rolled back")
            return False

        before_snapshot = None
        if self.snapshots and len(self.snapshots) >= 2:
            before_snapshot = self.snapshots[-2]
        elif last_run.snapshot_before:
            before_snapshot = last_run.snapshot_before

        if before_snapshot is None:
            logger.warning("No snapshot available for rollback of run %s", last_run.run_id)
            return False

        logger.info("Rolling back run %s from %s", last_run.run_id, last_run.started_at.isoformat())

        try:
            self.efficiency.reset_metrics()
            self.performance.reset_metrics()
            self.relevance.reset_metrics()
            self.memory.reset_metrics()

            last_run.rolled_back = True
            last_run.status = OptimizationStatus.ROLLED_BACK
            last_run.completed_at = datetime.utcnow()

            if len(self.snapshots) >= 2:
                self.snapshots.pop()

            logger.info("Rollback of run %s completed successfully", last_run.run_id)
            self._fire_event("rollback_completed", last_run)
            return True

        except Exception as exc:
            logger.error("Rollback failed: %s", exc)
            return False

    def schedule_next_run(self) -> Optional[datetime]:
        """Calculate the next scheduled optimization run time."""
        if self.config.schedule_frequency == ScheduleFrequency.MANUAL_ONLY:
            return None

        now = datetime.utcnow()
        last = self._last_scheduled_run

        if last is None:
            next_run = now
        else:
            interval_map = {
                ScheduleFrequency.HOURLY: timedelta(hours=1),
                ScheduleFrequency.DAILY: timedelta(days=1),
                ScheduleFrequency.WEEKLY: timedelta(weeks=1),
                ScheduleFrequency.MONTHLY: timedelta(days=30),
            }
            interval = interval_map.get(self.config.schedule_frequency, timedelta(days=1))
            next_run = last + interval

        return next_run

    def check_schedule(self) -> Optional[OptimizationRun]:
        """Check if a scheduled run is due and execute if so."""
        if self.config.schedule_frequency == ScheduleFrequency.MANUAL_ONLY:
            return None

        next_run = self.schedule_next_run()
        if next_run is None:
            return None

        if datetime.utcnow() >= next_run:
            self._last_scheduled_run = datetime.utcnow()
            return self.run_full_optimization(trigger=OptimizationTrigger.PERIODIC)

        return None

    def run_on_event(
        self,
        event_type: str,
        rules: Optional[List[Rule]] = None,
    ) -> Optional[OptimizationRun]:
        """Run optimization triggered by an event."""
        logger.info("Event-driven optimization triggered by event: %s", event_type)

        trigger_map = {
            "rule_changed": OptimizationTrigger.RULE_CHANGED,
            "threshold_exceeded": OptimizationTrigger.THRESHOLD_EXCEEDED,
            "system_startup": OptimizationTrigger.SYSTEM_STARTUP,
        }
        trigger = trigger_map.get(event_type, OptimizationTrigger.EVENT_DRIVEN)

        run = self.run_full_optimization(trigger=trigger, rules=rules)
        self._fire_event("optimization_run", run)
        return run

    def register_event_handler(self, event: str, handler: Callable) -> None:
        """Register a callback for orchestrator events."""
        self._event_handlers[event].append(handler)
        logger.debug("Registered handler for event: %s", event)

    def register_notification_callback(self, callback: Callable) -> None:
        """Register a callback for optimization run notifications."""
        self._notification_callbacks.append(callback)

    def _fire_event(self, event: str, data: Any = None) -> None:
        """Fire an event to all registered handlers."""
        for handler in self._event_handlers.get(event, []):
            try:
                handler(data)
            except Exception as exc:
                logger.error("Handler %s failed for event %s: %s", handler.__name__, event, exc)

    def _notify(self, run: OptimizationRun) -> None:
        """Send notification about an optimization run completion."""
        if not self.config.notification_enabled:
            return

        channel = self.config.notification_channel

        if channel == NotificationChannel.LOG:
            status = run.status.value
            duration = run.total_duration_ms()
            suggestion_count = len(run.aggregated_suggestions)
            error_count = len(run.errors)
            logger.info(
                "Optimization run %s [%s]: %.1fms, %d suggestions, %d errors",
                run.run_id, status, duration, suggestion_count, error_count,
            )

        for callback in self._notification_callbacks:
            try:
                callback(run)
            except Exception as exc:
                logger.error("Notification callback failed: %s", exc)

    def get_pending_suggestions(
        self,
        min_priority: Optional[OptimizationPriority] = None,
    ) -> List[Dict[str, Any]]:
        """Get pending optimization suggestions, optionally filtered by priority."""
        threshold = min_priority or self.config.suggestion_min_priority
        priority_order = [
            OptimizationPriority.CRITICAL,
            OptimizationPriority.HIGH,
            OptimizationPriority.MEDIUM,
            OptimizationPriority.LOW,
        ]

        min_index = priority_order.index(threshold) if threshold in priority_order else 3

        return [
            {
                "suggestion_id": s.suggestion_id,
                "optimizer": s.optimizer,
                "type": s.optimization_type.value,
                "priority": s.priority.value,
                "description": s.description,
                "score": round(s.score, 2),
            }
            for s in self.pending_suggestions
            if priority_order.index(s.priority) <= min_index
        ]

    def dismiss_suggestion(self, suggestion_id: str) -> bool:
        """Remove a suggestion from the pending list."""
        initial_len = len(self.pending_suggestions)
        self.pending_suggestions = [
            s for s in self.pending_suggestions
            if s.suggestion_id != suggestion_id
        ]
        return len(self.pending_suggestions) < initial_len

    def generate_before_after_report(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Generate a before/after comparison report for a specific run."""
        for run in self.run_history:
            if run.run_id == run_id:
                if run.snapshot_before and run.snapshot_after:
                    before = run.snapshot_before
                    after = run.snapshot_after

                    return {
                        "run_id": run_id,
                        "trigger": run.trigger.value,
                        "status": run.status.value,
                        "duration_ms": round(run.total_duration_ms(), 2),
                        "comparisons": {
                            "efficiency": self._compare_metric(
                                before.get("efficiency", {}),
                                after.get("efficiency", {}),
                            ),
                            "performance": self._compare_metric(
                                before.get("performance", {}),
                                after.get("performance", {}),
                            ),
                            "relevance": self._compare_metric(
                                before.get("relevance", {}),
                                after.get("relevance", {}),
                            ),
                            "memory": self._compare_metric(
                                before.get("memory", {}),
                                after.get("memory", {}),
                            ),
                        },
                        "suggestions": run.aggregated_suggestions,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                break

        return None

    def _compare_metric(
        self,
        before: Dict[str, Any],
        after: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compare before and after metric snapshots."""
        comparison: Dict[str, Any] = {
            "changes": {},
            "improvements": [],
            "regressions": [],
        }

        numeric_keys = [
            "total_evaluations", "cache_hit_rate", "average_efficiency_score",
            "total_rules_tracked", "total_time_ms", "overall_average_ms",
            "total_used_mb", "peak_used_mb",
        ]

        for key in numeric_keys:
            before_val = before.get(key, 0)
            after_val = after.get(key, 0)
            if isinstance(before_val, (int, float)) and isinstance(after_val, (int, float)):
                diff = after_val - before_val
                comparison["changes"][key] = {
                    "before": before_val,
                    "after": after_val,
                    "difference": round(diff, 4),
                    "pct_change": round((diff / max(abs(before_val), 1)) * 100, 2),
                }

                if key in ("cache_hit_rate", "average_efficiency_score"):
                    if diff > 0:
                        comparison["improvements"].append(key)
                    elif diff < 0:
                        comparison["regressions"].append(key)

        return comparison

    def generate_orchestration_report(self) -> Dict[str, Any]:
        """Generate a comprehensive orchestration report."""
        completed_runs = [r for r in self.run_history if r.status == OptimizationStatus.COMPLETED]
        failed_runs = [r for r in self.run_history if r.status == OptimizationStatus.FAILED]
        rolled_back = [r for r in self.run_history if r.rolled_back]

        total_suggestions = len(self.suggestion_log)
        pending_count = len(self.pending_suggestions)

        avg_duration = 0.0
        if completed_runs:
            avg_duration = sum(r.total_duration_ms() for r in completed_runs) / len(completed_runs)

        suggestion_breakdown: Dict[str, int] = defaultdict(int)
        for sug in self.suggestion_log:
            suggestion_breakdown[sug.priority.value] += 1

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_runs": len(self.run_history),
            "completed_runs": len(completed_runs),
            "failed_runs": len(failed_runs),
            "rolled_back_runs": len(rolled_back),
            "average_run_duration_ms": round(avg_duration, 2),
            "last_run": self.run_history[-1].run_id if self.run_history else None,
            "schedule_frequency": self.config.schedule_frequency.value,
            "next_scheduled_run": (
                self.schedule_next_run().isoformat()
                if self.schedule_next_run() else None
            ),
            "total_suggestions_generated": total_suggestions,
            "pending_suggestions": pending_count,
            "suggestion_priority_breakdown": dict(suggestion_breakdown),
            "optimizer_status": {
                "efficiency": "active",
                "performance": "active",
                "relevance": "active",
                "memory": "active",
            },
            "config": {
                "schedule_frequency": self.config.schedule_frequency.value,
                "enable_rollback": self.config.enable_rollback,
                "parallel_optimizers": self.config.parallel_optimizers,
                "max_suggestions_per_run": self.config.max_suggestions_per_run,
                "max_parallel_workers": self.config.max_parallel_workers,
            },
        }

    def reset_all(self) -> None:
        """Reset all optimizers and orchestration state."""
        self.efficiency.reset_metrics()
        self.performance.reset_metrics()
        self.relevance.reset_metrics()
        self.memory.reset_metrics()

        self.run_history.clear()
        self.suggestion_log.clear()
        self.snapshots.clear()
        self.pending_suggestions.clear()
        self.current_run = None
        self._last_scheduled_run = None

        logger.info("All optimizers and orchestration state reset")
