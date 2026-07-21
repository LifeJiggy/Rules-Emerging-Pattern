"""User preference-based conflict resolution with decay, history, and ranking."""
import logging
import math
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class UserPreference:
    rule_id: str
    preference_score: float
    reason: Optional[str] = None
    source: str = "manual"
    weight: float = 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    decay_rate: float = 0.01


@dataclass
class PreferenceResolution:
    winning_rule_id: str
    losing_rule_id: str
    strategy: str
    reason: str
    score_winner: float = 0.0
    score_loser: float = 0.0
    preference_source: str = "manual"
    resolved_at: datetime = field(default_factory=datetime.utcnow)


class UserPreferenceResolver:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.user_preferences: Dict[str, Dict[str, List[UserPreference]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._default_score = self.config.get("default_score", 0.0)
        self._max_preferences_per_user = self.config.get("max_preferences_per_user", 100)
        self._decay_enabled = self.config.get("decay_enabled", True)
        self._decay_rate = self.config.get("decay_rate", 0.01)
        self._preference_ttl_days = self.config.get("preference_ttl_days", 365)
        logger.info("UserPreferenceResolver initialized (decay=%s, ttl=%dd)",
                     self._decay_enabled, self._preference_ttl_days)

    def set_user_preference(
        self,
        user_id: str,
        rule_id: str,
        score: float,
        reason: Optional[str] = None,
        source: str = "manual",
        weight: float = 1.0
    ) -> UserPreference:
        score = max(-1.0, min(1.0, score))
        weight = max(0.1, min(10.0, weight))

        if len(self.user_preferences[user_id]) >= self._max_preferences_per_user:
            oldest_rule = min(
                self.user_preferences[user_id].keys(),
                key=lambda r: max(p.updated_at for p in self.user_preferences[user_id][r])
            )
            del self.user_preferences[user_id][oldest_rule]
            logger.debug("Evicted oldest preference for user %s (rule %s)", user_id, oldest_rule)

        pref = UserPreference(
            rule_id=rule_id,
            preference_score=score,
            reason=reason,
            source=source,
            weight=weight,
            decay_rate=self._decay_rate,
        )
        self.user_preferences[user_id][rule_id].append(pref)
        logger.info("Set preference for user %s: rule=%s score=%.2f weight=%.1f source=%s",
                     user_id, rule_id, score, weight, source)
        return pref

    def remove_user_preference(self, user_id: str, rule_id: str) -> bool:
        if rule_id in self.user_preferences[user_id]:
            del self.user_preferences[user_id][rule_id]
            logger.info("Removed preference: user=%s rule=%s", user_id, rule_id)
            return True
        return False

    def get_user_preferences(
        self,
        user_id: str,
        decay: bool = True
    ) -> List[UserPreference]:
        prefs: List[UserPreference] = []
        now = datetime.now(timezone.utc)

        for rule_prefs in self.user_preferences.get(user_id, {}).values():
            latest = max(rule_prefs, key=lambda p: p.updated_at)
            if decay:
                days_elapsed = (now - latest.updated_at).days
                if days_elapsed > self._preference_ttl_days:
                    continue
                effective_score = self._apply_decay(latest.preference_score, days_elapsed)
                latest.preference_score = effective_score
            prefs.append(latest)

        prefs.sort(key=lambda p: p.preference_score, reverse=True)
        return prefs

    def resolve(
        self,
        user_id: str,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[PreferenceResolution]:
        prefs = self.get_user_preferences(user_id)
        rid1 = rule_1.get("id", "unknown")
        rid2 = rule_2.get("id", "unknown")

        score_1 = self._default_score
        score_2 = self._default_score
        source_1 = "default"
        source_2 = "default"

        for pref in prefs:
            if pref.rule_id == rid1:
                score_1 = pref.preference_score * pref.weight
                source_1 = pref.source
            elif pref.rule_id == rid2:
                score_2 = pref.preference_score * pref.weight
                source_2 = pref.source

        if score_1 == self._default_score and score_2 == self._default_score:
            return None

        if score_1 > score_2:
            return PreferenceResolution(
                winning_rule_id=rid1,
                losing_rule_id=rid2,
                strategy="user_preference",
                reason=f"User prefers rule {rid1} (score={score_1:.2f} vs {score_2:.2f})",
                score_winner=score_1,
                score_loser=score_2,
                preference_source=source_1,
            )
        else:
            return PreferenceResolution(
                winning_rule_id=rid2,
                losing_rule_id=rid1,
                strategy="user_preference",
                reason=f"User prefers rule {rid2} (score={score_2:.2f} vs {score_1:.2f})",
                score_winner=score_2,
                score_loser=score_1,
                preference_source=source_2,
            )

    def resolve_with_fallback(
        self,
        user_id: str,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any],
        fallback_resolver: Any,
        fallback_context: Optional[Dict[str, Any]] = None
    ) -> PreferenceResolution:
        result = self.resolve(user_id, rule_1, rule_2)
        if result is not None:
            return result

        if fallback_resolver and hasattr(fallback_resolver, "resolve"):
            fb = fallback_resolver.resolve(rule_1, rule_2) if fallback_context is None \
                else fallback_resolver.resolve(rule_1, rule_2, fallback_context)  # type: ignore

            if hasattr(fb, "winning_rule_id"):
                return PreferenceResolution(
                    winning_rule_id=fb.winning_rule_id,
                    losing_rule_id=fb.losing_rule_id,
                    strategy=f"user_preference_fallback",
                    reason=f"No user preference found, used fallback: {fb.reason}",
                    score_winner=getattr(fb, "score_winner", 0),
                    score_loser=getattr(fb, "score_loser", 0),
                    preference_source="fallback",
                )

        return PreferenceResolution(
            winning_rule_id=rule_1.get("id", "unknown"),
            losing_rule_id=rule_2.get("id", "unknown"),
            strategy="user_preference_fallback",
            reason="No preferences found and no fallback available, defaulting to rule_1",
            preference_source="default",
        )

    def _apply_decay(self, score: float, days_elapsed: int) -> float:
        if not self._decay_enabled or days_elapsed <= 0:
            return score
        decay_factor = math.exp(-self._decay_rate * days_elapsed)
        return score * decay_factor

    def get_statistics(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            prefs = self.get_user_preferences(user_id, decay=False)
            return {
                "user_id": user_id,
                "total_preferences": len(prefs),
                "avg_score": sum(p.preference_score for p in prefs) / len(prefs) if prefs else 0.0,
                "sources": dict(Counter(p.source for p in prefs)),
            }

        total_prefs = sum(
            len(prefs) for user_rules in self.user_preferences.values()
            for prefs in user_rules.values()
        )
        return {
            "total_users": len(self.user_preferences),
            "total_preferences": total_prefs,
            "avg_per_user": total_prefs / max(len(self.user_preferences), 1),
        }
