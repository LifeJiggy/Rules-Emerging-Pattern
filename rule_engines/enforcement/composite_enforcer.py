"""Composite enforcer - orchestrates multiple enforcement strategies with fallback chaining."""
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from .strict_enforcer import StrictEnforcer, StrictEnforcementResult
from .advisory_enforcer import AdvisoryEnforcer, AdvisoryEnforcementResult
from .adaptive_enforcer import AdaptiveEnforcer, AdaptiveEnforcementResult
from .fallback_handler import FallbackHandler, FallbackEvent

logger = logging.getLogger(__name__)


class CompositeResultStatus(str, Enum):
    BLOCKED = "blocked"
    WARNED = "warned"
    PASSED = "passed"
    FALLBACK = "fallback"
    ERROR = "error"


@dataclass
class CompositeEnforcementResult:
    status: CompositeResultStatus
    rule_id: str
    rule_name: str
    tier: str
    enforcement_type: str
    strict_result: Optional[StrictEnforcementResult] = None
    advisory_result: Optional[AdvisoryEnforcementResult] = None
    adaptive_result: Optional[AdaptiveEnforcementResult] = None
    fallback_event: Optional[FallbackEvent] = None
    warnings: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CompositeEnforcer:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._strict = StrictEnforcer(self.config.get("strict_config"))
        self._advisory = AdvisoryEnforcer(self.config.get("advisory_config"))
        self._adaptive = AdaptiveEnforcer(self.config.get("adaptive_config"))
        self._fallback = FallbackHandler(self.config.get("fallback_config"))
        self._enforcement_order = self.config.get("enforcement_order", ["strict", "advisory", "adaptive"])
        self._history: List[CompositeEnforcementResult] = []
        self._max_history = self.config.get("max_history", 5000)
        self._enforcement_count = 0
        self._block_count = 0
        logger.info("CompositeEnforcer initialized (order=%s)", self._enforcement_order)

    def enforce(self, rule: Dict[str, Any], content: str,
                context: Optional[Dict[str, Any]] = None) -> CompositeEnforcementResult:
        start = time.perf_counter()
        self._enforcement_count += 1
        ctx = context or {}
        tier = rule.get("tier", "preference")
        rule_id = rule.get("id", "unknown")
        rule_name = rule.get("name", rule_id)
        warnings: List[str] = []

        strict_result: Optional[StrictEnforcementResult] = None
        advisory_result: Optional[AdvisoryEnforcementResult] = None
        adaptive_result: Optional[AdaptiveEnforcementResult] = None
        fallback_event: Optional[FallbackEvent] = None

        try:
            for etype in self._enforcement_order:
                if etype == "strict":
                    strict_result = self._strict.enforce(rule, content, ctx.get("bypass_token"))
                    if strict_result and strict_result.blocked:
                        self._block_count += 1
                        elapsed = (time.perf_counter() - start) * 1000
                        result = CompositeEnforcementResult(
                            status=CompositeResultStatus.BLOCKED,
                            rule_id=rule_id, rule_name=rule_name,
                            tier=tier, enforcement_type="strict",
                            strict_result=strict_result,
                            warnings=warnings,
                            execution_time_ms=round(elapsed, 3),
                        )
                        self._history.append(result)
                        return result

                elif etype == "advisory":
                    advisory_result = self._advisory.enforce(rule, content, ctx.get("user_id"))
                    if advisory_result:
                        warnings.append(f"Advisory: {rule_name} - {advisory_result.suggestion or ''}")

                elif etype == "adaptive":
                    adaptive_result = self._adaptive.enforce(rule, content, ctx)
                    if adaptive_result and adaptive_result.action.value in ("block", "warn"):
                        warnings.append(f"Adaptive: {rule_name} (confidence={adaptive_result.confidence:.2f})")

        except Exception as e:
            logger.error("Enforcement error for rule %s: %s", rule_id, e)
            fallback_event = self._fallback.handle_failure(rule, content, e)
            elapsed = (time.perf_counter() - start) * 1000
            result = CompositeEnforcementResult(
                status=CompositeResultStatus.FALLBACK,
                rule_id=rule_id, rule_name=rule_name,
                tier=tier, enforcement_type="fallback",
                fallback_event=fallback_event,
                warnings=warnings + [f"Fallback: {str(e)}"],
                execution_time_ms=round(elapsed, 3),
            )
            self._history.append(result)
            return result

        elapsed = (time.perf_counter() - start) * 1000
        result_status = CompositeResultStatus.WARNED if warnings else CompositeResultStatus.PASSED
        result = CompositeEnforcementResult(
            status=result_status,
            rule_id=rule_id, rule_name=rule_name,
            tier=tier, enforcement_type="composite",
            strict_result=strict_result,
            advisory_result=advisory_result,
            adaptive_result=adaptive_result,
            warnings=warnings,
            execution_time_ms=round(elapsed, 3),
        )
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        return result

    def enforce_batch(self, rules: List[Dict[str, Any]], content: str,
                      context: Optional[Dict[str, Any]] = None) -> Dict[str, CompositeEnforcementResult]:
        return {r.get("id", "unknown"): self.enforce(r, content, context) for r in rules}

    def get_strict_enforcer(self) -> StrictEnforcer:
        return self._strict

    def get_advisory_enforcer(self) -> AdvisoryEnforcer:
        return self._advisory

    def get_adaptive_enforcer(self) -> AdaptiveEnforcer:
        return self._adaptive

    def get_fallback_handler(self) -> FallbackHandler:
        return self._fallback

    def get_statistics(self) -> Dict[str, Any]:
        if not self._history:
            return {"total_enforcements": self._enforcement_count, "total_blocks": self._block_count}
        by_status: Dict[str, int] = {}
        for r in self._history:
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        return {
            "total_enforcements": self._enforcement_count,
            "total_blocks": self._block_count,
            "by_status": by_status,
            "strict": self._strict.get_statistics(),
            "advisory": self._advisory.get_statistics(),
            "adaptive": self._adaptive.get_statistics(),
            "fallback": self._fallback.get_statistics(),
        }
