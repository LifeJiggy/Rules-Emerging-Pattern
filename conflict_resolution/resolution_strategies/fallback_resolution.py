"""Fallback conflict resolution with configurable action chain and escalation."""
import logging
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class FallbackAction(str, Enum):
    ABORT = "abort"
    BLOCK = "block"
    LOG_ONLY = "log_only"
    ESCALATE = "escalate"
    DEFER = "defer"
    DEFAULT_WINNER = "default_winner"
    COMPOSITE = "composite"
    MANUAL_REVIEW = "manual_review"


class EscalationLevel(str, Enum):
    SILENT = "silent"
    NOTIFY = "notify"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class FallbackResolution:
    conflict_id: str
    action: FallbackAction
    reason: str
    strategy: str = "fallback"
    escalation_level: EscalationLevel = EscalationLevel.SILENT
    suggestions: List[str] = field(default_factory=list)
    resolved_at: datetime = field(default_factory=datetime.utcnow)


class FallbackResolver:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._action_chain: List[FallbackAction] = [
            FallbackAction(a) for a in self.config.get(
                "action_chain",
                ["log_only", "default_winner", "escalate", "abort"]
            )
        ]
        self._default_action = FallbackAction(self.config.get("default_action", "abort"))
        self._escalation_level = EscalationLevel(
            self.config.get("escalation_level", "warning")
        )
        self._escalation_hooks: List[Callable[[FallbackResolution], None]] = []
        self._default_winner_rule = self.config.get("default_winner_rule", "safety")
        logger.info("FallbackResolver initialized (chain=%s, default=%s)",
                     [a.value for a in self._action_chain], self._default_action.value)

    def resolve(self, conflict: Dict[str, Any]) -> FallbackResolution:
        conflict_id = conflict.get("id") or conflict.get("conflict_id", "unknown")
        severity = conflict.get("severity", "medium")

        for action in self._action_chain:
            result = self._try_action(action, conflict_id, severity, conflict)
            if result is not None:
                return result

        return self._apply_default(conflict_id, severity, conflict)

    def resolve_with_context(
        self,
        conflict: Dict[str, Any],
        context: Dict[str, Any]
    ) -> FallbackResolution:
        context_strategy = context.get("fallback_strategy")
        if context_strategy:
            try:
                action = FallbackAction(context_strategy)
                return self._build_resolution(
                    conflict_id=conflict.get("id", "unknown"),
                    action=action,
                    reason=f"Context-directed fallback: {context_strategy}",
                    conflict=conflict,
                )
            except ValueError:
                pass

        return self.resolve(conflict)

    def register_escalation_hook(
        self,
        hook: Callable[[FallbackResolution], None]
    ) -> None:
        self._escalation_hooks.append(hook)
        logger.debug("Registered escalation hook (%d total)", len(self._escalation_hooks))

    def _try_action(
        self,
        action: FallbackAction,
        conflict_id: str,
        severity: str,
        conflict: Dict[str, Any]
    ) -> Optional[FallbackResolution]:
        if action == FallbackAction.LOG_ONLY:
            logger.warning("Fallback[log_only] for conflict %s (severity=%s)",
                           conflict_id, severity)
            return self._build_resolution(conflict_id, action, "Logged without action", conflict)

        if action == FallbackAction.DEFAULT_WINNER:
            return self._build_resolution(
                conflict_id, action,
                f"Defaulting to {self._default_winner_rule} rule",
                conflict, suggestions=[f"Apply {self._default_winner_rule} rule"]
            )

        if action == FallbackAction.ESCALATE:
            level = self._escalation_level
            if severity == "critical":
                level = EscalationLevel.EMERGENCY
            elif severity == "high":
                level = EscalationLevel.CRITICAL

            resolution = self._build_resolution(
                conflict_id, action,
                f"Escalated at level {level.value}",
                conflict, escalation_level=level
            )

            for hook in self._escalation_hooks:
                try:
                    hook(resolution)
                except Exception as e:
                    logger.error("Escalation hook failed: %s", e)

            return resolution

        if action == FallbackAction.ABORT:
            return self._build_resolution(
                conflict_id, action,
                "Aborted due to unresolvable conflict",
                conflict
            )

        if action == FallbackAction.BLOCK:
            return self._build_resolution(
                conflict_id, action,
                "Blocked content due to unresolvable conflict",
                conflict
            )

        if action == FallbackAction.DEFER:
            return self._build_resolution(
                conflict_id, action,
                "Deferred conflict resolution to next cycle",
                conflict
            )

        return None

    def _apply_default(
        self,
        conflict_id: str,
        severity: str,
        conflict: Dict[str, Any]
    ) -> FallbackResolution:
        logger.warning("Fallback chain exhausted, applying default %s to %s",
                       self._default_action.value, conflict_id)
        return self._build_resolution(
            conflict_id, self._default_action,
            f"Default fallback action applied",
            conflict
        )

    def _build_resolution(
        self,
        conflict_id: str,
        action: FallbackAction,
        reason: str,
        conflict: Dict[str, Any],
        escalation_level: Optional[EscalationLevel] = None,
        suggestions: Optional[List[str]] = None,
    ) -> FallbackResolution:
        return FallbackResolution(
            conflict_id=conflict_id,
            action=action,
            reason=reason,
            strategy="fallback",
            escalation_level=escalation_level or self._escalation_level,
            suggestions=suggestions or [],
        )
