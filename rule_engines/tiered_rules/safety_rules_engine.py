"""Safety rules engine - Tier 1 enforcement with non-negotiable blocking."""
import logging
import re
import time
from typing import List, Dict, Any, Optional, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class SafetyAction(str, Enum):
    BLOCK = "block"
    FLAG = "flag"
    ESCALATE = "escalate"
    LOG = "log"


class SafetySeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class SafetyEvaluationResult:
    rule_id: str
    rule_name: str
    triggered: bool
    action: Optional[SafetyAction]
    severity: SafetySeverity
    matched_patterns: List[str]
    confidence: float
    execution_time_ms: float
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SafetyRulesEngine:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._compiled_patterns: Dict[str, re.Pattern] = {}
        self._blocklist: Set[str] = set()
        self._history: List[SafetyEvaluationResult] = []
        self._max_history = self.config.get("max_history", 10000)
        self._eval_count = 0
        self._block_count = 0
        self._critical_patterns = self.config.get("critical_patterns", [
            r"(?i)child\s*(abuse|exploit|pornography)",
            r"(?i)instructions?\s+(for|to)\s+(create|make|build)\s+(weapon|bomb|explosive|poison)",
            r"(?i)hate\s+speech\s+targeting",
        ])
        self._high_patterns = self.config.get("high_patterns", [
            r"(?i)how\s+to\s+(harm|hurt|kill|injure)\s+(someone|people|person)",
            r"(?i)personal\s+(data|information|details)\s+(of|for)\s+(other|another)",
        ])
        self._compile_patterns()
        logger.info("SafetyRulesEngine initialized (rules=%d, critical=%d, high=%d)",
                     len(self._rules), len(self._critical_patterns), len(self._high_patterns))

    def add_rule(self, rule_id: str, rule_data: Dict[str, Any]) -> None:
        rule_data["id"] = rule_id
        self._rules[rule_id] = rule_data
        patterns = rule_data.get("patterns", [])
        for p in patterns:
            if isinstance(p, str):
                try:
                    self._compiled_patterns[f"{rule_id}:{p}"] = re.compile(p, re.IGNORECASE)
                except re.error as e:
                    logger.warning("Invalid pattern '%s' for rule %s: %s", p, rule_id, e)
        if rule_data.get("auto_block", True):
            self._blocklist.add(rule_id)
        logger.info("Added safety rule %s", rule_id)

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._blocklist.discard(rule_id)
            keys = [k for k in self._compiled_patterns if k.startswith(f"{rule_id}:")]
            for k in keys:
                del self._compiled_patterns[k]
            return True
        return False

    def evaluate(self, content: str, context: Optional[Dict[str, Any]] = None) -> List[SafetyEvaluationResult]:
        results: List[SafetyEvaluationResult] = []
        ctx = context or {}

        for pattern in self._critical_patterns:
            match = re.search(pattern, content)
            if match:
                results.append(self._build_result(
                    rule_id="critical_safety", rule_name="Critical Safety Rule",
                    triggered=True, action=SafetyAction.BLOCK,
                    severity=SafetySeverity.CRITICAL,
                    matched=[match.group()], confidence=0.99,
                    ctx=ctx
                ))
                self._block_count += 1

        for pattern in self._high_patterns:
            match = re.search(pattern, content)
            if match:
                results.append(self._build_result(
                    rule_id="high_safety", rule_name="High Safety Rule",
                    triggered=True, action=SafetyAction.BLOCK,
                    severity=SafetySeverity.HIGH,
                    matched=[match.group()], confidence=0.95,
                    ctx=ctx
                ))
                self._block_count += 1

        for rule_id, rule in self._rules.items():
            patterns = rule.get("patterns", [])
            matched: List[str] = []
            for p in patterns:
                key = f"{rule_id}:{p}"
                compiled = self._compiled_patterns.get(key)
                if compiled and compiled.search(content):
                    matched.append(p)

            if matched:
                action = SafetyAction.BLOCK if rule_id in self._blocklist else (
                    SafetyAction.ESCALATE if rule.get("escalate", True) else SafetyAction.FLAG
                )
                severity = SafetySeverity(rule.get("severity", "high"))
                results.append(self._build_result(
                    rule_id=rule_id, rule_name=rule.get("name", rule_id),
                    triggered=True, action=action, severity=severity,
                    matched=matched, confidence=rule.get("confidence", 0.9),
                    ctx=ctx
                ))
                if action == SafetyAction.BLOCK:
                    self._block_count += 1

        self._eval_count += 1
        for r in results:
            self._history.append(r)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return results

    def evaluate_batch(self, contents: List[str], context: Optional[Dict[str, Any]] = None) -> Dict[str, List[SafetyEvaluationResult]]:
        return {f"content_{i}": self.evaluate(c, context) for i, c in enumerate(contents)}

    def is_blocked(self, content: str) -> bool:
        return any(r.action == SafetyAction.BLOCK for r in self.evaluate(content))

    def get_statistics(self) -> Dict[str, Any]:
        if not self._history:
            return {"total_evaluations": self._eval_count, "total_blocks": self._block_count}
        blocked = sum(1 for r in self._history if r.action == SafetyAction.BLOCK)
        by_severity: Dict[str, int] = defaultdict(int)
        for r in self._history:
            by_severity[r.severity.value] += 1
        return {
            "total_evaluations": self._eval_count,
            "total_blocks": self._block_count,
            "block_rate": self._block_count / max(self._eval_count, 1),
            "by_severity": dict(by_severity),
            "active_rules": len(self._rules),
            "compiled_patterns": len(self._compiled_patterns),
        }

    def get_recent_blocks(self, limit: int = 20) -> List[SafetyEvaluationResult]:
        return [r for r in reversed(self._history) if r.action == SafetyAction.BLOCK][:limit]

    def _build_result(self, rule_id: str, rule_name: str, triggered: bool,
                      action: SafetyAction, severity: SafetySeverity,
                      matched: List[str], confidence: float,
                      ctx: Dict[str, Any]) -> SafetyEvaluationResult:
        return SafetyEvaluationResult(
            rule_id=rule_id, rule_name=rule_name, triggered=triggered,
            action=action, severity=severity, matched_patterns=matched,
            confidence=min(confidence, 1.0), execution_time_ms=0.0,
            context=ctx,
        )

    def _compile_patterns(self) -> None:
        for rule_id, rule in self._rules.items():
            patterns = rule.get("patterns", [])
            for p in patterns:
                if isinstance(p, str):
                    try:
                        self._compiled_patterns[f"{rule_id}:{p}"] = re.compile(p, re.IGNORECASE)
                    except re.error:
                        pass
