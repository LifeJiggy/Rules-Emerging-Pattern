"""Strict enforcement handler - automatic blocking with no user override for safety rules."""
import logging
import re
import time
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class StrictAction(str, Enum):
    BLOCK = "block"
    BLOCK_AND_LOG = "block_and_log"
    BLOCK_AND_ESCALATE = "block_and_escalate"


class StrictSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"


@dataclass
class StrictEnforcementResult:
    rule_id: str
    rule_name: str
    action: StrictAction
    severity: StrictSeverity
    blocked: bool
    matched_keywords: List[str]
    confidence: float
    execution_time_ms: float
    escalation_path: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StrictEnforcer:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._blocklist: Dict[str, Dict[str, Any]] = {}
        self._compiled_patterns: Dict[str, re.Pattern] = {}
        self._bypass_tokens: Set[str] = set()
        self._enforcement_count = 0
        self._block_count = 0
        self._history: List[StrictEnforcementResult] = []
        self._max_history = self.config.get("max_history", 10000)
        self._min_confidence = self.config.get("min_confidence", 0.8)
        self._auto_escalate = self.config.get("auto_escalate", True)
        self._escalation_path = self.config.get("escalation_path", "admin_review")
        logger.info("StrictEnforcer initialized (blocklist=%d, min_confidence=%.2f)",
                     len(self._blocklist), self._min_confidence)

    def add_blocklist_rule(self, rule_id: str, rule_data: Dict[str, Any]) -> None:
        self._blocklist[rule_id] = rule_data
        patterns = rule_data.get("patterns", [])
        for p in patterns:
            if isinstance(p, str):
                try:
                    self._compiled_patterns[f"{rule_id}:{p}"] = re.compile(p, re.IGNORECASE | re.MULTILINE)
                except re.error as e:
                    logger.warning("Invalid pattern '%s': %s", p, e)
        logger.info("Added blocklist rule %s (%d patterns)", rule_id, len(patterns))

    def remove_blocklist_rule(self, rule_id: str) -> bool:
        if rule_id not in self._blocklist:
            return False
        del self._blocklist[rule_id]
        keys = [k for k in self._compiled_patterns if k.startswith(f"{rule_id}:")]
        for k in keys:
            del self._compiled_patterns[k]
        return True

    def add_bypass_token(self, token: str) -> None:
        self._bypass_tokens.add(token)
        logger.debug("Added bypass token")

    def remove_bypass_token(self, token: str) -> None:
        self._bypass_tokens.discard(token)

    def enforce(self, rule: Dict[str, Any], content: str,
                bypass_token: Optional[str] = None) -> Optional[StrictEnforcementResult]:
        if bypass_token and bypass_token in self._bypass_tokens:
            return None

        start = time.perf_counter()
        self._enforcement_count += 1
        patterns = rule.get("patterns", [])
        rule_id = rule.get("id", "unknown")
        matched: List[str] = []

        for p in patterns:
            if isinstance(p, str):
                compiled = self._compiled_patterns.get(f"{rule_id}:{p}")
                if not compiled:
                    try:
                        compiled = re.compile(p, re.IGNORECASE | re.MULTILINE)
                        self._compiled_patterns[f"{rule_id}:{p}"] = compiled
                    except re.error:
                        continue
                if compiled.search(content):
                    matched.append(p)

        if not matched:
            elapsed = (time.perf_counter() - start) * 1000
            return StrictEnforcementResult(
                rule_id=rule_id, rule_name=rule.get("name", rule_id),
                action=StrictAction.BLOCK, severity=StrictSeverity.HIGH,
                blocked=False, matched_keywords=[],
                confidence=0.0, execution_time_ms=round(elapsed, 3),
            )

        confidence = rule.get("confidence", 0.9)
        if confidence < self._min_confidence:
            elapsed = (time.perf_counter() - start) * 1000
            return StrictEnforcementResult(
                rule_id=rule_id, rule_name=rule.get("name", rule_id),
                action=StrictAction.BLOCK, severity=StrictSeverity.HIGH,
                blocked=False, matched_keywords=matched,
                confidence=confidence, execution_time_ms=round(elapsed, 3),
            )

        self._block_count += 1
        severity = rule.get("severity", "critical")
        action = StrictAction.BLOCK_AND_ESCALATE if (
            self._auto_escalate and severity == "critical"
        ) else StrictAction.BLOCK_AND_LOG

        if matched and severity == "critical":
            action = StrictAction.BLOCK_AND_ESCALATE
        elif matched:
            action = StrictAction.BLOCK

        elapsed = (time.perf_counter() - start) * 1000
        result = StrictEnforcementResult(
            rule_id=rule_id, rule_name=rule.get("name", rule_id),
            action=action, severity=StrictSeverity(severity) if severity in [s.value for s in StrictSeverity] else StrictSeverity.HIGH,
            blocked=True, matched_keywords=matched,
            confidence=confidence, execution_time_ms=round(elapsed, 3),
            escalation_path=self._escalation_path if action == StrictAction.BLOCK_AND_ESCALATE else None,
        )

        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        logger.warning("Strict block: rule=%s matched=%s action=%s", rule_id, matched, action.value)
        return result

    def enforce_batch(self, rules: List[Dict[str, Any]], contents: List[str]) -> Dict[str, List[StrictEnforcementResult]]:
        results: Dict[str, List[StrictEnforcementResult]] = defaultdict(list)
        for rule in rules:
            for content in contents:
                r = self.enforce(rule, content)
                if r:
                    results[rule.get("id", "unknown")].append(r)
        return dict(results)

    def get_statistics(self) -> Dict[str, Any]:
        if not self._history:
            return {
                "total_enforcements": self._enforcement_count,
                "blocks_applied": self._block_count,
                "block_rate": 0.0,
            }
        by_severity: Dict[str, int] = defaultdict(int)
        by_action: Dict[str, int] = defaultdict(int)
        for r in self._history:
            by_severity[r.severity.value] += 1
            by_action[r.action.value] += 1
        return {
            "total_enforcements": self._enforcement_count,
            "blocks_applied": self._block_count,
            "block_rate": self._block_count / max(self._enforcement_count, 1),
            "by_severity": dict(by_severity),
            "by_action": dict(by_action),
            "active_blocklist_rules": len(self._blocklist),
            "bypass_tokens_active": len(self._bypass_tokens),
        }

    def get_blocked_items(self, limit: int = 50) -> List[StrictEnforcementResult]:
        return [r for r in reversed(self._history) if r.blocked][:limit]
