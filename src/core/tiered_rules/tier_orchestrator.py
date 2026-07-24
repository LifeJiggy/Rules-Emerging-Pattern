"""Tier Orchestrator - coordinate evaluation across all three rule tiers."""
import asyncio
import logging
import time
from typing import List, Dict, Any, Optional, Set, Tuple, Callable
from datetime import datetime, timedelta
from enum import Enum

from rules_emerging_pattern.models.rule import RuleTier, RuleEvaluationRequest, RuleContext, RuleSeverity
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken
from rules_emerging_pattern.models.conflict import (
    RuleConflict, ConflictType, ConflictSeverity, ConflictResolution, ResolutionStrategy,
)
from rules_emerging_pattern.core.tiered_rules.safety_engine import SafetyRuleEngine
from rules_emerging_pattern.core.tiered_rules.operational_engine import OperationalRuleEngine
from rules_emerging_pattern.core.tiered_rules.preference_engine import PreferenceRuleEngine
from rules_emerging_pattern.core.tiered_rules.tier_metrics_collector import TierMetricsCollector

logger = logging.getLogger(__name__)


class EvaluationPhase(str, Enum):
    SAFETY_CHECK = "safety_check"
    OPERATIONAL_CHECK = "operational_check"
    PREFERENCE_CHECK = "preference_check"
    CONFLICT_RESOLUTION = "conflict_resolution"
    FINALIZATION = "finalization"


class TierStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class TierResult:
    def __init__(self, tier: RuleTier):
        self.tier = tier
        self.status: TierStatus = TierStatus.PENDING
        self.result: Optional[ValidationResult] = None
        self.processing_time_ms: float = 0.0
        self.error: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

    def start(self) -> None:
        self.status = TierStatus.RUNNING
        self.started_at = datetime.utcnow()

    def complete(self, result: ValidationResult) -> None:
        self.status = TierStatus.COMPLETED
        self.result = result
        self.completed_at = datetime.utcnow()
        if self.started_at:
            self.processing_time_ms = (
                self.completed_at - self.started_at
            ).total_seconds() * 1000

    def fail(self, error: str) -> None:
        self.status = TierStatus.FAILED
        self.error = error
        self.completed_at = datetime.utcnow()
        if self.started_at:
            self.processing_time_ms = (
                self.completed_at - self.started_at
            ).total_seconds() * 1000

    def skip(self, reason: str = "") -> None:
        self.status = TierStatus.SKIPPED
        self.completed_at = datetime.utcnow()

    def timeout(self) -> None:
        self.status = TierStatus.TIMED_OUT
        self.completed_at = datetime.utcnow()
        if self.started_at:
            self.processing_time_ms = (
                self.completed_at - self.started_at
            ).total_seconds() * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier.value,
            "status": self.status.value,
            "processing_time_ms": round(self.processing_time_ms, 2),
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ConflictDetector:
    def __init__(self):
        self.detection_count: int = 0

    def detect_conflicts(
        self, safety_result: Optional[ValidationResult],
        operational_result: Optional[ValidationResult],
        preference_result: Optional[ValidationResult],
    ) -> List[RuleConflict]:
        conflicts: List[RuleConflict] = []
        if not safety_result or not operational_result:
            return conflicts
        safety_violations = safety_result.violations
        operational_violations = operational_result.violations if operational_result else []
        preference_suggestions = preference_result.suggestions if preference_result else []
        for sv in safety_violations:
            if not sv.blocked:
                continue
            for ov in operational_violations:
                if sv.matched_content and ov.matched_content and \
                   sv.matched_content.lower() in ov.matched_content.lower():
                    conflicts.append(RuleConflict(
                        conflict_id=f"conflict_{self.detection_count}",
                        conflict_type=ConflictType.RULE_CONFLICT,
                        severity=ConflictSeverity.HIGH,
                        description=f"Safety rule '{sv.rule_name}' conflicts with operational rule '{ov.rule_name}'",
                        conflict_reason=(
                            f"Safety blocks '{sv.matched_content}' while operational "
                            f"warns about '{ov.matched_content}'"
                        ),
                        contradictory_elements=[sv.matched_content, ov.matched_content],
                        detection_method="cross_tier_analysis",
                        confidence=0.85,
                        resolution_strategy=ResolutionStrategy.PRIORITY_BASED,
                    ))
                    self.detection_count += 1
        for sv in safety_violations:
            for suggestion in preference_suggestions:
                if sv.matched_content and suggestion.original_text and \
                   sv.matched_content.lower() in suggestion.original_text.lower():
                    conflicts.append(RuleConflict(
                        conflict_id=f"conflict_{self.detection_count}",
                        conflict_type=ConflictType.SEMANTIC_CONFLICT,
                        severity=ConflictSeverity.MEDIUM,
                        description=f"Safety violation conflicts with preference '{suggestion.title}'",
                        conflict_reason=(
                            f"Safety blocks '{sv.matched_content}' but preference "
                            f"suggests '{suggestion.description}'"
                        ),
                        contradictory_elements=[sv.matched_content, suggestion.original_text or ""],
                        detection_method="cross_tier_semantic",
                        confidence=0.70,
                        resolution_strategy=ResolutionStrategy.PRIORITY_BASED,
                    ))
                    self.detection_count += 1
        return conflicts


class OrchestrationStats:
    def __init__(self):
        self.total_evaluations: int = 0
        self.early_terminations: int = 0
        self.safety_bypasses: int = 0
        self.timeouts: int = 0
        self.errors: Dict[str, int] = {}
        self.conflicts_detected: int = 0
        self.conflicts_resolved: int = 0
        self.total_processing_time_ms: int = 0
        self.tier_processing_times: Dict[str, List[float]] = {
            "safety": [],
            "operational": [],
            "preference": [],
        }
        self.evaluation_phases: Dict[str, int] = {
            phase.value: 0 for phase in EvaluationPhase
        }
        self.last_evaluation_time: Optional[datetime] = None

    def record_evaluation(
        self, processing_ms: float, early_terminated: bool = False,
        safety_bypassed: bool = False, timed_out: bool = False,
        error: Optional[str] = None,
    ) -> None:
        self.total_evaluations += 1
        self.total_processing_time_ms += processing_ms
        self.last_evaluation_time = datetime.utcnow()
        if early_terminated:
            self.early_terminations += 1
        if safety_bypassed:
            self.safety_bypasses += 1
        if timed_out:
            self.timeouts += 1
        if error:
            self.errors[error] = self.errors.get(error, 0) + 1

    def record_phase(self, phase: EvaluationPhase) -> None:
        self.evaluation_phases[phase.value] = \
            self.evaluation_phases.get(phase.value, 0) + 1

    def record_tier_time(self, tier: str, time_ms: float) -> None:
        if tier in self.tier_processing_times:
            self.tier_processing_times[tier].append(time_ms)

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "early_terminations": self.early_terminations,
            "early_termination_rate": round(
                self.early_terminations / max(self.total_evaluations, 1), 4
            ),
            "safety_bypasses": self.safety_bypasses,
            "timeouts": self.timeouts,
            "errors": dict(self.errors),
            "conflicts_detected": self.conflicts_detected,
            "conflicts_resolved": self.conflicts_resolved,
            "avg_processing_time_ms": round(
                self.total_processing_time_ms / max(self.total_evaluations, 1), 2
            ),
            "total_processing_time_ms": round(self.total_processing_time_ms, 2),
            "tier_avg_times_ms": {
                tier: round(sum(times) / max(len(times), 1), 2)
                for tier, times in self.tier_processing_times.items()
            },
            "phase_counts": dict(self.evaluation_phases),
            "last_evaluation": (
                self.last_evaluation_time.isoformat()
                if self.last_evaluation_time else None
            ),
        }


class TierOrchestrator:
    """Coordinate evaluation across all 3 tiers: safety, operational, preference."""

    def __init__(
        self,
        safety_engine: Optional[SafetyRuleEngine] = None,
        operational_engine: Optional[OperationalRuleEngine] = None,
        preference_engine: Optional[PreferenceRuleEngine] = None,
        metrics_collector: Optional[TierMetricsCollector] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.safety_engine = safety_engine or SafetyRuleEngine()
        self.operational_engine = operational_engine or OperationalRuleEngine()
        self.preference_engine = preference_engine or PreferenceRuleEngine()
        self.metrics_collector = metrics_collector or TierMetricsCollector()
        self.config = config or {}
        self.stats = OrchestrationStats()
        self.conflict_detector = ConflictDetector()
        self._tier_timeouts: Dict[RuleTier, float] = {
            RuleTier.SAFETY: self.config.get("safety_timeout_ms", 5000) / 1000.0,
            RuleTier.OPERATIONAL: self.config.get("operational_timeout_ms", 3000) / 1000.0,
            RuleTier.PREFERENCE: self.config.get("preference_timeout_ms", 2000) / 1000.0,
        }
        self._evaluation_order: List[RuleTier] = [
            RuleTier.SAFETY,
            RuleTier.OPERATIONAL,
            RuleTier.PREFERENCE,
        ]
        self._early_termination_enabled: bool = self.config.get(
            "early_termination_enabled", True
        )
        self._conflict_resolution_enabled: bool = self.config.get(
            "conflict_resolution_enabled", True
        )
        self._parallel_tiers: bool = self.config.get("parallel_tiers", False)
        logger.info(
            "TierOrchestrator initialized: order=%s early_termination=%s parallel=%s",
            [t.value for t in self._evaluation_order],
            self._early_termination_enabled,
            self._parallel_tiers,
        )

    async def evaluate(self, request: RuleEvaluationRequest) -> ValidationResult:
        start_time = time.time()
        overall_start = datetime.utcnow()
        request_id = f"orchestrated_{self.stats.total_evaluations}"

        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
            request_id=request_id,
            content_hash=str(hash(request.content))[:16],
        )

        tier_results: Dict[RuleTier, TierResult] = {
            tier: TierResult(tier) for tier in self._evaluation_order
        }

        try:
            self.stats.record_phase(EvaluationPhase.SAFETY_CHECK)
            if not self._parallel_tiers:
                for tier in self._evaluation_order:
                    tier_result = tier_results[tier]
                    tier_result.start()
                    try:
                        tier_eval_result = await self._evaluate_tier_with_timeout(
                            tier, request, tier_result
                        )
                        tier_result.complete(tier_eval_result)
                        self._merge_tier_result(result, tier_eval_result)
                        self.stats.record_tier_time(
                            tier.value, tier_result.processing_time_ms
                        )
                        if self._should_early_terminate(tier, result):
                            self.stats.record_evaluation(
                                processing_ms=(time.time() - start_time) * 1000,
                                early_terminated=True,
                            )
                            for remaining in self._evaluation_order[
                                self._evaluation_order.index(tier) + 1:
                            ]:
                                tier_results[remaining].skip(
                                    "Skipped due to early termination"
                                )
                            break
                    except asyncio.TimeoutError:
                        tier_result.timeout()
                        self.stats.timeouts += 1
                        logger.warning(
                            "Tier %s timed out after %sms",
                            tier.value, self._tier_timeouts.get(tier, 5) * 1000,
                        )
                    except Exception as e:
                        tier_result.fail(str(e))
                        self.stats.record_evaluation(
                            processing_ms=(time.time() - start_time) * 1000,
                            error=str(e),
                        )
                        logger.error(
                            "Tier %s evaluation failed: %s", tier.value, e
                        )
            else:
                all_results = await self._evaluate_tiers_parallel(request, tier_results)
                for tier, tier_result in all_results.items():
                    if tier_result.status == TierStatus.COMPLETED and tier_result.result:
                        self._merge_tier_result(result, tier_result.result)
                        self.stats.record_tier_time(
                            tier.value, tier_result.processing_time_ms
                        )

            self.stats.record_phase(EvaluationPhase.CONFLICT_RESOLUTION)
            if self._conflict_resolution_enabled:
                conflicts = self.conflict_detector.detect_conflicts(
                    tier_results[RuleTier.SAFETY].result if tier_results[RuleTier.SAFETY].status == TierStatus.COMPLETED else None,
                    tier_results[RuleTier.OPERATIONAL].result if tier_results[RuleTier.OPERATIONAL].status == TierStatus.COMPLETED else None,
                    tier_results[RuleTier.PREFERENCE].result if tier_results[RuleTier.PREFERENCE].status == TierStatus.COMPLETED else None,
                )
                self.stats.conflicts_detected += len(conflicts)
                if conflicts:
                    resolved = self._resolve_conflicts(result, conflicts)
                    self.stats.conflicts_resolved += resolved

            self.stats.record_phase(EvaluationPhase.FINALIZATION)
            processing_ms = int((datetime.utcnow() - overall_start).total_seconds() * 1000)
            result.processing_time_ms = processing_ms
            result.evaluated_at = datetime.utcnow()
            result.total_rules_evaluated = sum(
                1 for tr in tier_results.values()
                if tr.status == TierStatus.COMPLETED
            )
            result.rules_triggered = len(result.violations)
            result.rules_violated = len([
                v for v in result.violations
                if v.action_taken not in (ActionTaken.NONE, ActionTaken.SUGGESTION)
            ])

            self.stats.record_evaluation(
                processing_ms=processing_ms,
                timed_out=any(
                    tr.status == TierStatus.TIMED_OUT for tr in tier_results.values()
                ),
            )

            tier_detail = {
                tier.value: tr.to_dict()
                for tier, tr in tier_results.items()
            }
            result.processing_details = {
                "tier_results": tier_detail,
                "early_terminated": any(
                    tr.status == TierStatus.SKIPPED for tr in tier_results.values()
                ),
                "conflicts_detected": self.stats.conflicts_detected,
            }

            self.metrics_collector.record_evaluation(
                tier_results=tier_results,
                result=result,
                config=self.config,
            )

        except Exception as e:
            logger.error("Orchestrated evaluation failed: %s", e)
            self.stats.record_evaluation(
                processing_ms=(time.time() - start_time) * 1000,
                error=str(e),
            )
            result.valid = False
            result.processing_time_ms = int(
                (time.time() - start_time) * 1000
            )

        return result

    async def evaluate_batch(
        self, requests: List[RuleEvaluationRequest]
    ) -> List[ValidationResult]:
        if not requests:
            return []
        semaphore = asyncio.Semaphore(
            self.config.get("batch_concurrency", 10)
        )
        async def evaluate_one(req: RuleEvaluationRequest) -> ValidationResult:
            async with semaphore:
                return await self.evaluate(req)
        results = await asyncio.gather(
            *[evaluate_one(req) for req in requests],
            return_exceptions=True,
        )
        processed = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error("Batch evaluation failed for request %d: %s", i, res)
                processed.append(ValidationResult(
                    valid=False,
                    total_score=0.0,
                    confidence=0.0,
                    request_id=f"batch_failed_{i}",
                    violations=[
                        Violation(
                            rule_id="orchestrator_error",
                            rule_name="Orchestrator Error",
                            rule_tier=RuleTier.SAFETY,
                            rule_severity=RuleSeverity.CRITICAL,
                            violation_type=ViolationType.CUSTOM_VIOLATION,
                            confidence_score=1.0,
                            action_taken=ActionTaken.BLOCK,
                            blocked=True,
                            user_override_allowed=False,
                            explanation=f"Orchestrated batch evaluation failed: {res}",
                            context={},
                        )
                    ],
                ))
            else:
                processed.append(res)
        return processed

    async def _evaluate_tier_with_timeout(
        self, tier: RuleTier, request: RuleEvaluationRequest,
        tier_result: TierResult,
    ) -> ValidationResult:
        timeout_seconds = self._tier_timeouts.get(tier, 5.0)
        engine = self._get_engine(tier)
        if not engine:
            raise ValueError(f"No engine registered for tier: {tier}")
        tier_request = RuleEvaluationRequest(
            content=request.content,
            context=request.context,
            rule_ids=request.rule_ids,
            tier=tier,
            rule_types=request.rule_types,
            options=request.options,
            timeout_ms=int(timeout_seconds * 1000),
        )
        try:
            coro = engine.evaluate(tier_request)
            result = await asyncio.wait_for(coro, timeout=timeout_seconds)
            return result
        except asyncio.TimeoutError:
            tier_result.timeout()
            raise
        except Exception as e:
            tier_result.fail(str(e))
            raise

    async def _evaluate_tiers_parallel(
        self, request: RuleEvaluationRequest,
        tier_results: Dict[RuleTier, TierResult],
    ) -> Dict[RuleTier, TierResult]:
        async def eval_tier(tier: RuleTier) -> Tuple[RuleTier, TierResult]:
            tr = tier_results[tier]
            tr.start()
            try:
                safe_request = RuleEvaluationRequest(
                    content=request.content,
                    context=request.context,
                    rule_ids=request.rule_ids,
                    tier=tier,
                    rule_types=request.rule_types,
                    options=request.options,
                    timeout_ms=int(self._tier_timeouts.get(tier, 5.0) * 1000),
                )
                engine = self._get_engine(tier)
                if engine:
                    tier_result = await engine.evaluate(safe_request)
                    tr.complete(tier_result)
                else:
                    tr.skip(f"No engine for tier {tier.value}")
            except asyncio.TimeoutError:
                tr.timeout()
            except Exception as e:
                tr.fail(str(e))
            return tier, tr

        tasks = [eval_tier(tier) for tier in self._evaluation_order]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        results: Dict[RuleTier, TierResult] = {}
        for item in completed:
            if isinstance(item, Exception):
                logger.error("Parallel tier evaluation error: %s", item)
            elif isinstance(item, tuple):
                tier, tr = item
                results[tier] = tr
        return results

    def _should_early_terminate(
        self, current_tier: RuleTier, result: ValidationResult
    ) -> bool:
        if not self._early_termination_enabled:
            return False
        if current_tier == RuleTier.SAFETY and result.is_blocked():
            return True
        if current_tier == RuleTier.SAFETY and result.has_critical_violations():
            return True
        return False

    def _merge_tier_result(
        self, main: ValidationResult, tier_result: ValidationResult
    ) -> None:
        main.violations.extend(tier_result.violations)
        main.critical_violations.extend(tier_result.critical_violations)
        main.warnings.extend(tier_result.warnings)
        main.suggestions.extend(tier_result.suggestions)
        if not tier_result.valid:
            main.valid = False
        main.total_score = min(main.total_score, tier_result.total_score)
        main.confidence = (main.confidence + tier_result.confidence) / 2.0

    def _resolve_conflicts(
        self, result: ValidationResult, conflicts: List[RuleConflict]
    ) -> int:
        resolved_count = 0
        for conflict in conflicts:
            try:
                if conflict.resolution_strategy == ResolutionStrategy.PRIORITY_BASED:
                    safety_rules = {
                        v.rule_id for v in result.violations
                        if v.rule_tier == RuleTier.SAFETY
                    }
                    for violation in result.violations[:]:
                        if violation.rule_tier == RuleTier.OPERATIONAL:
                            if violation.matched_content and any(
                                c.rule_1.id in safety_rules or c.rule_2.id in safety_rules
                                for c in [conflict]
                            ):
                                if violation.blocked:
                                    result.violations.remove(violation)
                                    if violation in result.warnings:
                                        result.warnings.remove(violation)
                                    resolved_count += 1
                                    logger.info(
                                        "Conflict resolved: operational violation '%s' overridden by safety",
                                        violation.rule_name,
                                    )
                elif conflict.resolution_strategy == ResolutionStrategy.CONTEXT_AWARE:
                    if conflict.severity in (ConflictSeverity.CRITICAL, ConflictSeverity.HIGH):
                        logger.info(
                            "Conflict %s escalated for human review", conflict.conflict_id
                        )
                    else:
                        resolved_count += 1
                else:
                    for violation in result.violations[:]:
                        if violation.rule_tier == RuleTier.PREFERENCE:
                            result.violations.remove(violation)
                            resolved_count += 1
            except Exception as e:
                logger.error("Failed to resolve conflict %s: %s", conflict.conflict_id, e)
        return resolved_count

    def _get_engine(self, tier: RuleTier) -> Any:
        mapping = {
            RuleTier.SAFETY: self.safety_engine,
            RuleTier.OPERATIONAL: self.operational_engine,
            RuleTier.PREFERENCE: self.preference_engine,
        }
        return mapping.get(tier)

    def get_tier_timeout(self, tier: RuleTier) -> float:
        return self._tier_timeouts.get(tier, 5.0)

    def set_tier_timeout(self, tier: RuleTier, timeout_ms: int) -> None:
        self._tier_timeouts[tier] = timeout_ms / 1000.0
        logger.info(
            "Tier %s timeout set to %dms", tier.value, timeout_ms
        )

    def get_evaluation_order(self) -> List[str]:
        return [t.value for t in self._evaluation_order]

    def set_evaluation_order(self, order: List[RuleTier]) -> None:
        if set(order) != {RuleTier.SAFETY, RuleTier.OPERATIONAL, RuleTier.PREFERENCE}:
            raise ValueError("Evaluation order must include all three tiers exactly once")
        self._evaluation_order = order
        logger.info(
            "Evaluation order set to: %s", [t.value for t in order]
        )

    def enable_early_termination(self) -> None:
        self._early_termination_enabled = True
        logger.info("Early termination enabled")

    def disable_early_termination(self) -> None:
        self._early_termination_enabled = False
        logger.info("Early termination disabled")

    def enable_conflict_resolution(self) -> None:
        self._conflict_resolution_enabled = True
        logger.info("Conflict resolution enabled")

    def disable_conflict_resolution(self) -> None:
        self._conflict_resolution_enabled = False
        logger.info("Conflict resolution disabled")

    def enable_parallel_tiers(self) -> None:
        self._parallel_tiers = True
        logger.info("Parallel tier evaluation enabled")

    def disable_parallel_tiers(self) -> None:
        self._parallel_tiers = False
        logger.info("Parallel tier evaluation disabled")

    def update_config(self, config: Dict[str, Any]) -> None:
        self.config.update(config)
        if "safety_timeout_ms" in config:
            self._tier_timeouts[RuleTier.SAFETY] = config["safety_timeout_ms"] / 1000.0
        if "operational_timeout_ms" in config:
            self._tier_timeouts[RuleTier.OPERATIONAL] = config["operational_timeout_ms"] / 1000.0
        if "preference_timeout_ms" in config:
            self._tier_timeouts[RuleTier.PREFERENCE] = config["preference_timeout_ms"] / 1000.0
        if "early_termination_enabled" in config:
            self._early_termination_enabled = config["early_termination_enabled"]
        if "conflict_resolution_enabled" in config:
            self._conflict_resolution_enabled = config["conflict_resolution_enabled"]
        if "parallel_tiers" in config:
            self._parallel_tiers = config["parallel_tiers"]
        logger.info("TierOrchestrator configuration updated")

    def get_statistics(self) -> Dict[str, Any]:
        return self.stats.get_summary()

    def get_tier_results_summary(self) -> Dict[str, Any]:
        return {
            "safety": {
                "active_categories": self.safety_engine.get_active_categories(),
                "stats": self.safety_engine.get_statistics(),
            },
            "operational": {
                "active_categories": self.operational_engine.get_active_categories(),
                "stats": self.operational_engine.get_statistics(),
            },
            "preference": {
                "active_categories": self.preference_engine.get_active_categories(),
                "stats": self.preference_engine.get_statistics(),
            },
        }

    def get_metrics_collector(self) -> TierMetricsCollector:
        return self.metrics_collector

    def get_conflict_statistics(self) -> Dict[str, int]:
        return {
            "detected": self.stats.conflicts_detected,
            "resolved": self.stats.conflicts_resolved,
            "unresolved": self.stats.conflicts_detected - self.stats.conflicts_resolved,
        }

    def get_early_termination_rate(self) -> float:
        if self.stats.total_evaluations == 0:
            return 0.0
        return round(
            self.stats.early_terminations / self.stats.total_evaluations, 4
        )

    def get_timeout_rate(self) -> float:
        if self.stats.total_evaluations == 0:
            return 0.0
        return round(
            self.stats.timeouts / self.stats.total_evaluations, 4
        )

    def replace_safety_engine(self, engine: SafetyRuleEngine) -> None:
        self.safety_engine = engine
        logger.info("SafetyRuleEngine replaced")

    def replace_operational_engine(self, engine: OperationalRuleEngine) -> None:
        self.operational_engine = engine
        logger.info("OperationalRuleEngine replaced")

    def replace_preference_engine(self, engine: PreferenceRuleEngine) -> None:
        self.preference_engine = engine
        logger.info("PreferenceRuleEngine replaced")

    def replace_metrics_collector(self, collector: TierMetricsCollector) -> None:
        self.metrics_collector = collector
        logger.info("TierMetricsCollector replaced")

    def reset_statistics(self) -> None:
        self.stats = OrchestrationStats()
        self.safety_engine.reset_statistics()
        self.operational_engine.reset_statistics()
        self.preference_engine.reset_statistics()
        self.metrics_collector.reset_statistics()
        logger.info("All tier statistics reset")

    def get_throughput(self, window_minutes: int = 5) -> float:
        summary = self.metrics_collector.get_statistics()
        evaluations = summary.get("total_evaluations", 0)
        if evaluations == 0:
            return 0.0
        return round(evaluations / max(window_minutes, 1), 2)

    def get_error_rate(self) -> float:
        if self.stats.total_evaluations == 0:
            return 0.0
        total_errors = sum(self.stats.errors.values())
        return round(total_errors / self.stats.total_evaluations, 4)

    def is_safety_bypass_active(self) -> bool:
        return self.config.get("allow_safety_bypass", False)

    def set_safety_bypass(self, enabled: bool) -> None:
        self.config["allow_safety_bypass"] = enabled
        logger.info("Safety bypass %s", "enabled" if enabled else "disabled")
