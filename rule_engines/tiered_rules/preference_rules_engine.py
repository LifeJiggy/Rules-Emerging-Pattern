"""Preference rules engine - Tier 3 adaptive enforcement based on user preferences."""
import logging
import re
from typing import List, Dict, Any, Optional, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict
import math

logger = logging.getLogger(__name__)


class PreferenceAction(str, Enum):
    APPLY = "apply"
    SUGGEST = "suggest"
    IGNORE = "ignore"
    LEARN = "learn"


@dataclass
class PreferenceEvaluationResult:
    rule_id: str
    rule_name: str
    triggered: bool
    action: Optional[PreferenceAction]
    score: float
    matched_patterns: List[str]
    user_preference_score: float
    execution_time_ms: float
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PreferenceRulesEngine:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._compiled: Dict[str, re.Pattern] = {}
        self._user_preferences: Dict[str, Dict[str, float]] = defaultdict(dict)
        self._history: Dict[str, List[PreferenceEvaluationResult]] = defaultdict(list)
        self._max_history_per_user = self.config.get("max_history_per_user", 500)
        self._eval_count = 0
        self._apply_count = 0
        self._learning_mode = self.config.get("learning_mode", True)
        self._default_weight = self.config.get("default_weight", 0.5)
        self._preference_decay_rate = self.config.get("preference_decay_rate", 0.01)
        logger.info("PreferenceRulesEngine initialized (rules=%d, learning=%s)",
                     len(self._rules), self._learning_mode)

    def add_rule(self, rule_id: str, rule_data: Dict[str, Any]) -> None:
        rule_data["id"] = rule_id
        self._rules[rule_id] = rule_data
        patterns = rule_data.get("patterns", [])
        for p in patterns:
            if isinstance(p, str):
                try:
                    self._compiled[f"{rule_id}:{p}"] = re.compile(p, re.IGNORECASE)
                except re.error:
                    pass
        logger.info("Added preference rule %s", rule_id)

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id not in self._rules:
            return False
        del self._rules[rule_id]
        keys = [k for k in self._compiled if k.startswith(f"{rule_id}:")]
        for k in keys:
            del self._compiled[k]
        return True

    def set_user_preference(self, user_id: str, rule_id: str, score: float) -> None:
        self._user_preferences[user_id][rule_id] = max(-1.0, min(1.0, score))
        logger.info("Set preference: user=%s rule=%s score=%.2f", user_id, rule_id, score)

    def get_user_preferences(self, user_id: str) -> Dict[str, float]:
        return dict(self._user_preferences.get(user_id, {}))

    def evaluate(self, content: str, user_id: str,
                 context: Optional[Dict[str, Any]] = None) -> List[PreferenceEvaluationResult]:
        results: List[PreferenceEvaluationResult] = []
        ctx = context or {}
        user_prefs = self._user_preferences.get(user_id, {})

        if self._learning_mode and user_id not in self._user_preferences:
            pass

        for rule_id, rule in self._rules.items():
            patterns = rule.get("patterns", [])
            matched: List[str] = []
            for p in patterns:
                key = f"{rule_id}:{p}"
                compiled = self._compiled.get(key)
                if compiled and compiled.search(content):
                    matched.append(p)

            if not matched:
                continue

            pref_score = user_prefs.get(rule_id, self._default_weight)
            threshold = rule.get("threshold", 0.3)
            strength = rule.get("strength", 0.5) * (0.5 + pref_score * 0.5)

            if strength >= threshold:
                action = PreferenceAction.APPLY
                self._apply_count += 1
            elif self._learning_mode:
                action = PreferenceAction.SUGGEST
            else:
                action = PreferenceAction.IGNORE

            result = PreferenceEvaluationResult(
                rule_id=rule_id, rule_name=rule.get("name", rule_id),
                triggered=action != PreferenceAction.IGNORE,
                action=action, score=strength,
                matched_patterns=matched,
                user_preference_score=pref_score,
                execution_time_ms=0.0, context=ctx,
            )
            results.append(result)

        self._eval_count += 1
        user_history = self._history[user_id]
        user_history.extend(results)
        if len(user_history) > self._max_history_per_user:
            self._history[user_id] = user_history[-self._max_history_per_user:]

        return results

    def record_feedback(self, user_id: str, rule_id: str, positive: bool) -> None:
        prefs = self._user_preferences[user_id]
        current = prefs.get(rule_id, self._default_weight)
        delta = 0.1 if positive else -0.1
        new_score = max(-1.0, min(1.0, current + delta))
        prefs[rule_id] = new_score
        logger.info("Feedback: user=%s rule=%s positive=%s new_score=%.2f",
                     user_id, rule_id, positive, new_score)

    def update_preferences_from_history(self, user_id: str) -> int:
        history = self._history.get(user_id, [])
        if not history:
            return 0
        rule_applies: Dict[str, int] = defaultdict(int)
        rule_skips: Dict[str, int] = defaultdict(int)
        for r in history:
            if r.action == PreferenceAction.APPLY:
                rule_applies[r.rule_id] += 1
            elif r.action == PreferenceAction.IGNORE:
                rule_skips[r.rule_id] += 1
        updated = 0
        for rule_id in set(list(rule_applies.keys()) + list(rule_skips.keys())):
            applies = rule_applies.get(rule_id, 0)
            skips = rule_skips.get(rule_id, 0)
            total = applies + skips
            if total >= 5:
                ratio = applies / total
                self._user_preferences[user_id][rule_id] = round(ratio * 2 - 1, 4)
                updated += 1
        return updated

    def get_statistics(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            u_history = self._history.get(user_id, [])
            return {
                "user_id": user_id,
                "total_evaluations": len(u_history),
                "applies": sum(1 for r in u_history if r.action == PreferenceAction.APPLY),
                "suggestions": sum(1 for r in u_history if r.action == PreferenceAction.SUGGEST),
                "active_preferences": len(self._user_preferences.get(user_id, {})),
            }
        total_users = len(self._history)
        total_applies = sum(
            sum(1 for r in h if r.action == PreferenceAction.APPLY)
            for h in self._history.values()
        )
        return {
            "total_evaluations": self._eval_count,
            "total_applies": self._apply_count,
            "total_users": total_users,
            "active_rules": len(self._rules),
            "learning_mode": self._learning_mode,
            "total_preferences": sum(len(p) for p in self._user_preferences.values()),
        }
