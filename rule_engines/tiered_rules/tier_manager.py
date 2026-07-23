"""Tier manager - orchestrates multi-tier rule evaluation with priority ordering."""
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import IntEnum
from datetime import datetime, timezone

from .safety_rules_engine import SafetyRulesEngine, SafetyEvaluationResult
from .operational_rules_engine import OperationalRulesEngine, OperationalEvaluationResult
from .preference_rules_engine import PreferenceRulesEngine, PreferenceEvaluationResult

logger = logging.getLogger(__name__)


class TierPriority(IntEnum):
    SAFETY = 1
    OPERATIONAL = 2
    PREFERENCE = 3


@dataclass
class TierConfig:
    safety_enabled: bool = True
    operational_enabled: bool = True
    preference_enabled: bool = True
    fail_safe: bool = True
    block_on_any_safety: bool = True
    max_warnings_per_request: int = 10
    preference_user_id: Optional[str] = None


@dataclass
class TieredEvaluationResult:
    passed: bool
    blocked: bool
    safety_results: List[SafetyEvaluationResult]
    operational_results: List[OperationalEvaluationResult]
    preference_results: List[PreferenceEvaluationResult]
    applied_tiers: List[str]
    warnings: List[str]
    execution_time_ms: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TierManager:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._safety_engine = SafetyRulesEngine(self.config.get("safety_config"))
        self._operational_engine = OperationalRulesEngine(self.config.get("operational_config"))
        self._preference_engine = PreferenceRulesEngine(self.config.get("preference_config"))
        self._tier_config = TierConfig(**{
            k: v for k, v in self.config.get("tier_config", {}).items()
            if k in TierConfig.__dataclass_fields__
        })
        self._eval_count = 0
        self._block_count = 0
        logger.info("TierManager initialized (safety=%s, operational=%s, preference=%s)",
                     self._tier_config.safety_enabled,
                     self._tier_config.operational_enabled,
                     self._tier_config.preference_enabled)

    def evaluate(self, content: str, context: Optional[Dict[str, Any]] = None) -> TieredEvaluationResult:
        ctx = context or {}
        user_id = ctx.get("user_id") or self._tier_config.preference_user_id
        import time
        start = time.perf_counter()
        applied: List[str] = []
        warnings: List[str] = []

        safety_results: List[SafetyEvaluationResult] = []
        if self._tier_config.safety_enabled:
            safety_results = self._safety_engine.evaluate(content, ctx)
            applied.append("safety")
            blocks = [r for r in safety_results if r.action and r.action.value == "block"]
            if blocks:
                self._block_count += 1
                if self._tier_config.block_on_any_safety:
                    elapsed = (time.perf_counter() - start) * 1000
                    self._eval_count += 1
                    return TieredEvaluationResult(
                        passed=False, blocked=True,
                        safety_results=safety_results,
                        operational_results=[],
                        preference_results=[],
                        applied_tiers=applied,
                        warnings=[f"Blocked by safety rule: {b.rule_name}" for b in blocks],
                        execution_time_ms=round(elapsed, 3),
                    )

        operational_results: List[OperationalEvaluationResult] = []
        if self._tier_config.operational_enabled:
            operational_results = self._operational_engine.evaluate(content, user_id, ctx)
            applied.append("operational")
            for r in operational_results:
                if r.action and r.action.value == "warn":
                    warnings.append(f"Warning: {r.rule_name} - {r.suggestion or ''}")

        preference_results: List[PreferenceEvaluationResult] = []
        if self._tier_config.preference_enabled and user_id:
            preference_results = self._preference_engine.evaluate(content, user_id, ctx)
            applied.append("preference")

        while len(warnings) > self._tier_config.max_warnings_per_request:
            warnings.pop()

        elapsed = (time.perf_counter() - start) * 1000
        self._eval_count += 1
        return TieredEvaluationResult(
            passed=len(blocks := [r for r in safety_results if r.action and r.action.value == "block"]) == 0,
            blocked=len([r for r in safety_results if r.action and r.action.value == "block"]) > 0,
            safety_results=safety_results,
            operational_results=operational_results,
            preference_results=preference_results,
            applied_tiers=applied,
            warnings=warnings,
            execution_time_ms=round(elapsed, 3),
        )

    def evaluate_batch(self, contents: List[str], context: Optional[Dict[str, Any]] = None) -> Dict[str, TieredEvaluationResult]:
        return {f"item_{i}": self.evaluate(c, context) for i, c in enumerate(contents)}

    def get_safety_engine(self) -> SafetyRulesEngine:
        return self._safety_engine

    def get_operational_engine(self) -> OperationalRulesEngine:
        return self._operational_engine

    def get_preference_engine(self) -> PreferenceRulesEngine:
        return self._preference_engine

    def update_config(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if hasattr(self._tier_config, k):
                setattr(self._tier_config, k, v)
                logger.info("Updated tier config: %s = %s", k, v)

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "total_evaluations": self._eval_count,
            "total_blocks": self._block_count,
            "block_rate": self._block_count / max(self._eval_count, 1),
            "tier_config": {
                "safety_enabled": self._tier_config.safety_enabled,
                "operational_enabled": self._tier_config.operational_enabled,
                "preference_enabled": self._tier_config.preference_enabled,
                "fail_safe": self._tier_config.fail_safe,
            },
            "safety": self._safety_engine.get_statistics(),
            "operational": self._operational_engine.get_statistics(),
            "preference": self._preference_engine.get_statistics(),
        }
