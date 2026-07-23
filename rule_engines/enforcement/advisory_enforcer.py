"""Advisory enforcement handler - warnings with user override capability."""
import logging
import re
import time
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class AdvisoryAction(str, Enum):
    WARN = "warn"
    SUGGEST = "suggest"
    NOTIFY = "notify"
    LOG_ONLY = "log_only"


class AdvisorySeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class AdvisoryEnforcementResult:
    rule_id: str
    rule_name: str
    action: AdvisoryAction
    severity: AdvisorySeverity
    matched_keywords: List[str]
    suggestion: Optional[str]
    confidence: float
    execution_time_ms: float
    user_override_allowed: bool
    override_count: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AdvisoryEnforcer:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._advisory_rules: Dict[str, Dict[str, Any]] = {}
        self._compiled_patterns: Dict[str, re.Pattern] = {}
        self._user_overrides: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._enforcement_count = 0
        self._warning_count = 0
        self._override_count = 0
        self._history: List[AdvisoryEnforcementResult] = []
        self._max_history = self.config.get("max_history", 5000)
        self._max_overrides = self.config.get("max_overrides_per_user", 100)
        self._suppress_after_overrides = self.config.get("suppress_after_overrides", 5)
        logger.info("AdvisoryEnforcer initialized (rules=%d, max_overrides=%d)",
                     len(self._advisory_rules), self._max_overrides)

    def add_advisory_rule(self, rule_id: str, rule_data: Dict[str, Any]) -> None:
        self._advisory_rules[rule_id] = rule_data
        patterns = rule_data.get("patterns", [])
        for p in patterns:
            if isinstance(p, str):
                try:
                    self._compiled_patterns[f"{rule_id}:{p}"] = re.compile(p, re.IGNORECASE)
                except re.error as e:
                    logger.warning("Invalid pattern '%s': %s", p, e)
        logger.info("Added advisory rule %s", rule_id)

    def remove_advisory_rule(self, rule_id: str) -> bool:
        if rule_id not in self._advisory_rules:
            return False
        del self._advisory_rules[rule_id]
        keys = [k for k in self._compiled_patterns if k.startswith(f"{rule_id}:")]
        for k in keys:
            del self._compiled_patterns[k]
        return True

    def enforce(self, rule: Dict[str, Any], content: str,
                user_id: Optional[str] = None) -> Optional[AdvisoryEnforcementResult]:
        start = time.perf_counter()
        self._enforcement_count += 1
        rule_id = rule.get("id", "unknown")

        if user_id:
            override_count = self._user_overrides[user_id].get(rule_id, 0)
            if override_count >= self._suppress_after_overrides:
                logger.debug("Suppressing advisory rule %s for user %s (%d overrides)",
                             rule_id, user_id, override_count)
                return None
        else:
            override_count = 0

        patterns = rule.get("patterns", [])
        matched: List[str] = []

        for p in patterns:
            if isinstance(p, str):
                compiled = self._compiled_patterns.get(f"{rule_id}:{p}")
                if not compiled:
                    try:
                        compiled = re.compile(p, re.IGNORECASE)
                        self._compiled_patterns[f"{rule_id}:{p}"] = compiled
                    except re.error:
                        continue
                if compiled.search(content):
                    matched.append(p)

        if not matched:
            return None

        self._warning_count += 1
        severity = AdvisorySeverity(rule.get("severity", rule.get("severity", "medium")))
        action = AdvisoryAction(rule.get("action", "warn"))
        elapsed = (time.perf_counter() - start) * 1000

        result = AdvisoryEnforcementResult(
            rule_id=rule_id, rule_name=rule.get("name", rule_id),
            action=action, severity=severity,
            matched_keywords=matched,
            suggestion=rule.get("suggestion", rule.get("description")),
            confidence=rule.get("confidence", 0.8),
            execution_time_ms=round(elapsed, 3),
            user_override_allowed=rule.get("user_override", True),
            override_count=override_count,
        )

        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        logger.info("Advisory warning: rule=%s action=%s matched=%s", rule_id, action.value, matched)
        return result

    def record_override(self, user_id: str, rule_id: str) -> bool:
        if rule_id not in self._advisory_rules:
            return False
        if self._user_overrides[user_id][rule_id] >= self._max_overrides:
            logger.warning("User %s exceeded max overrides for rule %s", user_id, rule_id)
            return False
        self._user_overrides[user_id][rule_id] += 1
        self._override_count += 1
        logger.info("User %s overrode advisory rule %s (total=%d)",
                     user_id, rule_id, self._user_overrides[user_id][rule_id])
        return True

    def clear_overrides(self, user_id: Optional[str] = None) -> int:
        if user_id:
            count = len(self._user_overrides.get(user_id, {}))
            self._user_overrides[user_id].clear()
            return count
        total = sum(len(v) for v in self._user_overrides.values())
        self._user_overrides.clear()
        return total

    def get_overridden_rules(self, min_count: int = 3) -> List[Tuple[str, int]]:
        rule_counts: Dict[str, int] = defaultdict(int)
        for overrides in self._user_overrides.values():
            for rid, count in overrides.items():
                rule_counts[rid] += count
        return sorted(
            [(rid, count) for rid, count in rule_counts.items() if count >= min_count],
            key=lambda x: x[1], reverse=True
        )

    def get_statistics(self) -> Dict[str, Any]:
        if not self._history:
            return {
                "total_enforcements": self._enforcement_count,
                "warnings_issued": self._warning_count,
                "warning_rate": 0.0,
            }
        by_severity: Dict[str, int] = defaultdict(int)
        by_action: Dict[str, int] = defaultdict(int)
        for r in self._history:
            by_severity[r.severity.value] += 1
            by_action[r.action.value] += 1
        return {
            "total_enforcements": self._enforcement_count,
            "warnings_issued": self._warning_count,
            "warning_rate": self._warning_count / max(self._enforcement_count, 1),
            "total_overrides": self._override_count,
            "by_severity": dict(by_severity),
            "by_action": dict(by_action),
            "active_rules": len(self._advisory_rules),
            "users_with_overrides": len(self._user_overrides),
            "frequently_overridden": self.get_overridden_rules(),
        }

    def get_recent_warnings(self, limit: int = 50) -> List[AdvisoryEnforcementResult]:
        return list(reversed(self._history))[:limit]
