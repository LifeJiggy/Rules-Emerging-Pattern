"""Adaptive enforcement handler - context-aware with dynamic threshold adjustment."""
import logging
import re
import time
import math
from typing import List, Dict, Any, Optional, Set, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


class AdaptiveAction(str, Enum):
    BLOCK = "block"
    WARN = "warn"
    SUGGEST = "suggest"
    LOG = "log"
    DEFER = "defer"


class AdaptiveSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class AdaptiveEnforcementResult:
    rule_id: str
    rule_name: str
    action: AdaptiveAction
    severity: AdaptiveSeverity
    matched_patterns: List[str]
    dynamic_threshold: float
    confidence: float
    execution_time_ms: float
    context_score: float
    user_role: Optional[str]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AdaptiveEnforcer:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._compiled: Dict[str, re.Pattern] = {}
        self._history: List[AdaptiveEnforcementResult] = []
        self._max_history = self.config.get("max_history", 5000)
        self._enforcement_count = 0
        self._base_threshold = self.config.get("base_threshold", 0.6)
        self._min_threshold = self.config.get("min_threshold", 0.3)
        self._max_threshold = self.config.get("max_threshold", 0.95)
        self._learning_rate = self.config.get("learning_rate", 0.05)
        self._context_weights: Dict[str, float] = {
            "user_role": self.config.get("weight_role", 0.3),
            "domain": self.config.get("weight_domain", 0.2),
            "history": self.config.get("weight_history", 0.3),
            "content_type": self.config.get("weight_content_type", 0.2),
        }
        self._role_multipliers: Dict[str, float] = {
            "admin": self.config.get("admin_multiplier", 0.3),
            "moderator": self.config.get("moderator_multiplier", 0.6),
            "user": self.config.get("user_multiplier", 0.9),
            "anonymous": self.config.get("anonymous_multiplier", 1.0),
        }
        logger.info("AdaptiveEnforcer initialized (base_threshold=%.2f, roles=%d)",
                     self._base_threshold, len(self._role_multipliers))

    def add_adaptive_rule(self, rule_id: str, rule_data: Dict[str, Any]) -> None:
        self._rules[rule_id] = rule_data
        patterns = rule_data.get("patterns", [])
        for p in patterns:
            if isinstance(p, str):
                try:
                    self._compiled[f"{rule_id}:{p}"] = re.compile(p, re.IGNORECASE)
                except re.error:
                    pass
        logger.info("Added adaptive rule %s", rule_id)

    def remove_adaptive_rule(self, rule_id: str) -> bool:
        if rule_id not in self._rules:
            return False
        del self._rules[rule_id]
        keys = [k for k in self._compiled if k.startswith(f"{rule_id}:")]
        for k in keys:
            del self._compiled[k]
        return True

    def enforce(self, rule: Dict[str, Any], content: str,
                context: Optional[Dict[str, Any]] = None) -> Optional[AdaptiveEnforcementResult]:
        start = time.perf_counter()
        self._enforcement_count += 1
        ctx = context or {}
        rule_id = rule.get("id", "unknown")
        rule_name = rule.get("name", rule_id)

        thresholds = rule.get("thresholds", {})
        user_role = ctx.get("user_role", "anonymous")
        domain = ctx.get("domain", "general")
        content_type = ctx.get("content_type", "text")

        role_mult = self._role_multipliers.get(user_role, 1.0)
        domain_mult = thresholds.get(domain, 1.0)
        history_mult = self._compute_history_multiplier(rule_id)

        threshold = self._base_threshold * role_mult * domain_mult * history_mult
        threshold = max(self._min_threshold, min(self._max_threshold, threshold))

        patterns = rule.get("patterns", [])
        matched: List[str] = []
        for p in patterns:
            if isinstance(p, str):
                compiled = self._compiled.get(f"{rule_id}:{p}")
                if not compiled:
                    try:
                        compiled = re.compile(p, re.IGNORECASE)
                        self._compiled[f"{rule_id}:{p}"] = compiled
                    except re.error:
                        continue
                if compiled.search(content):
                    matched.append(p)

        if not matched:
            return None

        confidence = rule.get("confidence", 0.8)
        effective_confidence = confidence * role_mult
        context_score = self._compute_context_score(ctx)

        if effective_confidence >= threshold:
            if effective_confidence >= 0.9:
                action = AdaptiveAction.BLOCK
            elif effective_confidence >= 0.7:
                action = AdaptiveAction.WARN
            else:
                action = AdaptiveAction.SUGGEST
        else:
            action = AdaptiveAction.LOG

        severity_str = rule.get("severity", "medium")
        severity = AdaptiveSeverity(severity_str) if severity_str in [s.value for s in AdaptiveSeverity] else AdaptiveSeverity.MEDIUM

        elapsed = (time.perf_counter() - start) * 1000
        result = AdaptiveEnforcementResult(
            rule_id=rule_id, rule_name=rule_name,
            action=action, severity=severity,
            matched_patterns=matched,
            dynamic_threshold=round(threshold, 4),
            confidence=round(effective_confidence, 4),
            execution_time_ms=round(elapsed, 3),
            context_score=round(context_score, 4),
            user_role=user_role,
        )

        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        logger.debug("Adaptive enforce: rule=%s action=%s threshold=%.3f confidence=%.3f role=%s",
                     rule_id, action.value, threshold, effective_confidence, user_role)
        return result

    def record_feedback(self, rule_id: str, action: AdaptiveAction, positive: bool) -> None:
        if rule_id not in self._rules:
            return
        adjustment = self._learning_rate * (1.0 if positive else -1.0)
        rule = self._rules[rule_id]
        current = rule.get("confidence", 0.8)
        rule["confidence"] = max(0.1, min(1.0, current + adjustment))
        logger.info("Adaptive feedback: rule=%s positive=%s confidence=%.3f -> %.3f",
                     rule_id, positive, current, rule["confidence"])

    def enforce_contextual(self, rule: Dict[str, Any], content: str,
                           context: Dict[str, Any]) -> List[AdaptiveEnforcementResult]:
        results = []
        roles = context.get("roles", [context.get("user_role", "user")])
        for role in roles:
            ctx_copy = dict(context, user_role=role)
            result = self.enforce(rule, content, ctx_copy)
            if result:
                results.append(result)
        return results

    def get_statistics(self) -> Dict[str, Any]:
        if not self._history:
            return {"total_enforcements": self._enforcement_count}
        by_action: Dict[str, int] = defaultdict(int)
        by_role: Dict[str, int] = defaultdict(int)
        for r in self._history:
            by_action[r.action.value] += 1
            if r.user_role:
                by_role[r.user_role] += 1
        return {
            "total_enforcements": self._enforcement_count,
            "by_action": dict(by_action),
            "by_role": dict(by_role),
            "avg_threshold": sum(r.dynamic_threshold for r in self._history) / len(self._history),
            "active_rules": len(self._rules),
            "base_threshold": self._base_threshold,
        }

    def _compute_history_multiplier(self, rule_id: str) -> float:
        recent = [r for r in self._history[-100:] if r.rule_id == rule_id]
        if not recent:
            return 1.0
        false_positives = sum(1 for r in recent if r.action == AdaptiveAction.LOG)
        rate = false_positives / max(len(recent), 1)
        return max(0.5, 1.0 - rate * 0.1)

    def _compute_context_score(self, context: Dict[str, Any]) -> float:
        score = 0.5
        if context.get("user_role") == "admin":
            score += self._context_weights["user_role"]
        if "safety" in context.get("domain", ""):
            score += self._context_weights["domain"] * 0.5
        return min(1.0, score)
