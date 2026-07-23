"""Operational rules engine - Tier 2 advisory enforcement with user override."""
import logging
import re
import time
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class OperationalAction(str, Enum):
    WARN = "warn"
    SUGGEST = "suggest"
    LOG = "log"
    DEFER = "defer"


class OperationalSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class OperationalEvaluationResult:
    rule_id: str
    rule_name: str
    triggered: bool
    action: Optional[OperationalAction]
    severity: OperationalSeverity
    matched_patterns: List[str]
    suggestion: Optional[str]
    confidence: float
    execution_time_ms: float
    user_override_allowed: bool = True
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class OperationalRulesEngine:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._compiled: Dict[str, re.Pattern] = {}
        self._history: List[OperationalEvaluationResult] = []
        self._max_history = self.config.get("max_history", 5000)
        self._eval_count = 0
        self._warn_count = 0
        self._override_count = 0
        self._user_overrides: Dict[str, Set[str]] = defaultdict(set)
        self._override_threshold = self.config.get("override_threshold", 5)
        logger.info("OperationalRulesEngine initialized (rules=%d)", len(self._rules))

    def add_rule(self, rule_id: str, rule_data: Dict[str, Any]) -> None:
        rule_data["id"] = rule_id
        self._rules[rule_id] = rule_data
        patterns = rule_data.get("patterns", [])
        for p in patterns:
            if isinstance(p, str):
                try:
                    self._compiled[f"{rule_id}:{p}"] = re.compile(p, re.IGNORECASE | re.MULTILINE)
                except re.error as e:
                    logger.warning("Invalid pattern '%s' for rule %s: %s", p, rule_id, e)
        logger.info("Added operational rule %s (%d patterns)", rule_id, len(patterns))

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id not in self._rules:
            return False
        del self._rules[rule_id]
        keys = [k for k in self._compiled if k.startswith(f"{rule_id}:")]
        for k in keys:
            del self._compiled[k]
        return True

    def evaluate(self, content: str, user_id: Optional[str] = None,
                 context: Optional[Dict[str, Any]] = None) -> List[OperationalEvaluationResult]:
        results: List[OperationalEvaluationResult] = []
        ctx = context or {}
        start = time.perf_counter()

        for rule_id, rule in self._rules.items():
            if user_id and rule_id in self._user_overrides.get(user_id, set()):
                continue

            patterns = rule.get("patterns", [])
            only_if = rule.get("condition", {})
            if only_if:
                if not self._check_condition(only_if, content, ctx):
                    continue

            matched: List[str] = []
            for p in patterns:
                key = f"{rule_id}:{p}"
                compiled = self._compiled.get(key)
                if compiled and compiled.search(content):
                    matched.append(p)

            if not matched:
                continue

            action_str = rule.get("action", "warn")
            action = OperationalAction(action_str) if action_str in [a.value for a in OperationalAction] else OperationalAction.WARN
            severity = OperationalSeverity(rule.get("severity", "medium"))
            elapsed = (time.perf_counter() - start) * 1000

            result = OperationalEvaluationResult(
                rule_id=rule_id, rule_name=rule.get("name", rule_id),
                triggered=True, action=action, severity=severity,
                matched_patterns=matched,
                suggestion=rule.get("suggestion", rule.get("description")),
                confidence=rule.get("confidence", 0.8),
                execution_time_ms=round(elapsed, 3),
                user_override_allowed=rule.get("user_override", True),
                context=ctx,
            )
            results.append(result)
            self._warn_count += 1 if action == OperationalAction.WARN else 0

        self._eval_count += 1
        for r in results:
            self._history.append(r)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return results

    def record_override(self, user_id: str, rule_id: str) -> None:
        if rule_id in self._rules:
            self._user_overrides[user_id].add(rule_id)
            self._override_count += 1
            logger.info("User %s overrode rule %s", user_id, rule_id)

    def clear_overrides(self, user_id: Optional[str] = None) -> int:
        if user_id:
            count = len(self._user_overrides.get(user_id, set()))
            self._user_overrides[user_id].clear()
            return count
        total = sum(len(v) for v in self._user_overrides.values())
        self._user_overrides.clear()
        return total

    def get_frequently_overridden(self, min_override_count: int = 3) -> List[str]:
        rule_counts: Dict[str, int] = defaultdict(int)
        for overrides in self._user_overrides.values():
            for rid in overrides:
                rule_counts[rid] += 1
        return [rid for rid, count in rule_counts.items() if count >= min_override_count]

    def evaluate_batch(self, contents: List[str], context: Optional[Dict[str, Any]] = None) -> Dict[str, List[OperationalEvaluationResult]]:
        return {f"doc_{i}": self.evaluate(c, context=context) for i, c in enumerate(contents)}

    def get_statistics(self) -> Dict[str, Any]:
        if not self._history:
            return {"total_evaluations": self._eval_count, "total_warnings": self._warn_count}
        by_severity: Dict[str, int] = defaultdict(int)
        by_action: Dict[str, int] = defaultdict(int)
        for r in self._history:
            by_severity[r.severity.value] += 1
            by_action[r.action.value if r.action else "none"] += 1
        return {
            "total_evaluations": self._eval_count,
            "total_warnings": self._warn_count,
            "total_overrides": self._override_count,
            "freq_overridden": self.get_frequently_overridden(),
            "by_severity": dict(by_severity),
            "by_action": dict(by_action),
            "active_rules": len(self._rules),
        }

    def _check_condition(self, condition: Dict[str, Any], content: str, context: Dict[str, Any]) -> bool:
        content_type = condition.get("content_type", "")
        domain = condition.get("domain", "")
        min_length = condition.get("min_length", 0)
        if content_type and content_type not in context.get("content_type", ""):
            return False
        if domain and domain not in context.get("domain", ""):
            return False
        if min_length and len(content) < min_length:
            return False
        return True
