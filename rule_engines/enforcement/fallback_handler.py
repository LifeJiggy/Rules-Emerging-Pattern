"""Fallback handler for rule enforcement failures with graceful degradation."""
import logging
import time
import traceback
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class FallbackAction(str, Enum):
    ABORT = "abort"
    CONTINUE = "continue"
    RETRY = "retry"
    BYPASS = "bypass"
    ESCALATE = "escalate"
    LOG_ONLY = "log_only"


class FallbackReason(str, Enum):
    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    DEPENDENCY_FAILURE = "dependency_failure"
    CONFIG_ERROR = "config_error"
    RULE_ERROR = "rule_error"


@dataclass
class FallbackEvent:
    rule_id: str
    action: FallbackAction
    reason: FallbackReason
    error_message: str
    retry_count: int
    execution_time_ms: float
    escalation_level: Optional[str] = None
    stack_trace: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FallbackHandler:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._action_chain: List[FallbackAction] = [
            FallbackAction(a) for a in self.config.get("action_chain", [
                "retry", "log_only", "bypass", "escalate", "abort"
            ])
        ]
        self._default_action = FallbackAction(self.config.get("default_action", "abort"))
        self._max_retries = self.config.get("max_retries", 3)
        self._retry_delay_ms = self.config.get("retry_delay_ms", 100)
        self._escalation_path = self.config.get("escalation_path", "admin_notification")
        self._fallback_count = 0
        self._escalation_count = 0
        self._history: List[FallbackEvent] = []
        self._max_history = self.config.get("max_history", 5000)
        self._hooks: List[Callable[[FallbackEvent], None]] = []
        self._last_fallback: Dict[str, float] = {}
        logger.info("FallbackHandler initialized (chain=%s, max_retries=%d)",
                     [a.value for a in self._action_chain], self._max_retries)

    def handle_failure(self, rule: Dict[str, Any], content: str,
                       error: Optional[Exception] = None,
                       error_message: Optional[str] = None) -> FallbackEvent:
        rule_id = rule.get("id", "unknown")
        tier = rule.get("tier", "preference")
        msg = error_message or str(error) if error else "Unknown error"
        tb = traceback.format_exc() if error else None
        start = time.perf_counter()
        self._fallback_count += 1

        for attempt, action in enumerate(self._action_chain):
            if action == FallbackAction.RETRY:
                if attempt >= self._max_retries:
                    continue
                delay = self._retry_delay_ms * (attempt + 1)
                time.sleep(delay / 1000)
                logger.info("Fallback retry %d/%d for rule %s", attempt + 1, self._max_retries, rule_id)
                continue

            elif action == FallbackAction.LOG_ONLY:
                logger.warning("Fallback[log_only] for rule %s (tier=%s): %s", rule_id, tier, msg)
                reason = self._classify_error(error, msg)
                return self._record(rule_id, action, reason, msg, attempt, tb)

            elif action == FallbackAction.BYPASS:
                if tier == "safety":
                    logger.warning("Cannot bypass safety rule %s, trying next action", rule_id)
                    continue
                reason = FallbackReason.RULE_ERROR
                return self._record(rule_id, action, reason, f"Bypassed: {msg}", attempt, tb)

            elif action == FallbackAction.ESCALATE:
                self._escalation_count += 1
                reason = self._classify_error(error, msg)
                event = self._record(rule_id, action, reason, f"Escalated: {msg}", attempt, tb,
                                     escalation_level=self._escalation_path)
                for hook in self._hooks:
                    try:
                        hook(event)
                    except Exception as e:
                        logger.error("Escalation hook error: %s", e)
                return event

            elif action == FallbackAction.ABORT:
                reason = FallbackReason.EXCEPTION
                return self._record(rule_id, action, reason, f"Aborted: {msg}", attempt, tb)

        return self._record(rule_id, self._default_action, FallbackReason.CONFIG_ERROR,
                            f"Default fallback: {msg}", len(self._action_chain), tb)

    def register_hook(self, hook: Callable[[FallbackEvent], None]) -> None:
        self._hooks.append(hook)
        logger.debug("Registered fallback hook (%d total)", len(self._hooks))

    def get_recent_fallbacks(self, limit: int = 50) -> List[FallbackEvent]:
        return list(reversed(self._history))[:limit]

    def get_fallbacks_by_rule(self, rule_id: str) -> List[FallbackEvent]:
        return [e for e in self._history if e.rule_id == rule_id]

    def get_statistics(self) -> Dict[str, Any]:
        if not self._history:
            return {
                "total_fallbacks": self._fallback_count,
                "total_escalations": self._escalation_count,
            }
        by_action: Dict[str, int] = defaultdict(int)
        by_reason: Dict[str, int] = defaultdict(int)
        for e in self._history:
            by_action[e.action.value] += 1
            by_reason[e.reason.value] += 1
        return {
            "total_fallbacks": self._fallback_count,
            "total_escalations": self._escalation_count,
            "by_action": dict(by_action),
            "by_reason": dict(by_reason),
            "most_common_action": max(by_action, key=by_action.get) if by_action else None,
            "most_common_reason": max(by_reason, key=by_reason.get) if by_reason else None,
        }

    def _record(self, rule_id: str, action: FallbackAction, reason: FallbackReason,
                error_message: str, retry_count: int, stack_trace: Optional[str] = None,
                escalation_level: Optional[str] = None) -> FallbackEvent:
        event = FallbackEvent(
            rule_id=rule_id, action=action, reason=reason,
            error_message=error_message[:500],
            retry_count=retry_count,
            execution_time_ms=0.0,
            escalation_level=escalation_level,
            stack_trace=stack_trace,
        )
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        return event

    def _classify_error(self, error: Optional[Exception], message: str) -> FallbackReason:
        if error:
            err_type = type(error).__name__
            if "Time" in err_type or "timeout" in message.lower():
                return FallbackReason.TIMEOUT
            if "Resource" in err_type or "Memory" in err_type:
                return FallbackReason.RESOURCE_EXHAUSTED
        return FallbackReason.EXCEPTION
