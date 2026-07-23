"""
Temporary rule handler for time-bound, session-scoped, and one-time rules.

Manages rules with automatic expiry based on TTL, time windows, or events.
Supports session-scoped rules tied to user sessions and one-time rules
that self-delete after their first trigger.
"""

import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict, OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from weakref import WeakSet

import yaml

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)

logger = logging.getLogger(__name__)


class TemporaryRuleError(Exception):
    """Base exception for temporary rule operations."""


class TemporaryRuleExpiredError(TemporaryRuleError):
    """Exception raised when an operation targets an expired temporary rule."""


class TemporaryRuleLimitError(TemporaryRuleError):
    """Exception raised when temporary rule limits are exceeded."""


class ExpiryMode(str, Enum):
    """Modes for temporary rule expiry."""

    TTL = "ttl"
    TIME_WINDOW = "time_window"
    EVENT_DRIVEN = "event_driven"
    SESSION_BOUND = "session_bound"
    ONE_TIME = "one_time"
    COUNT_BASED = "count_based"
    CONDITIONAL = "conditional"


class CleanupStrategy(str, Enum):
    """Strategies for cleanup of expired temporary rules."""

    IMMEDIATE = "immediate"
    DEFERRED = "deferred"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


@dataclass
class TemporaryRule:
    """A rule with temporary validity constraints."""

    rule: Rule
    expiry_mode: ExpiryMode = ExpiryMode.TTL
    ttl_seconds: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    max_trigger_count: Optional[int] = None
    current_trigger_count: int = 0
    trigger_condition: Optional[Callable[[], bool]] = None
    on_expire_callback: Optional[Callable[["TemporaryRule"], None]] = None
    on_trigger_callback: Optional[Callable[["TemporaryRule"], None]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_expired: bool = False
    temp_rule_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tags: List[str] = field(default_factory=list)

    def is_valid(self) -> bool:
        """Check if this temporary rule is still valid."""
        if self.is_expired:
            return False

        if self.expiry_mode == ExpiryMode.TTL:
            if self.ttl_seconds is not None:
                elapsed = (datetime.utcnow() - self.created_at).total_seconds()
                if elapsed >= self.ttl_seconds:
                    return False

        elif self.expiry_mode == ExpiryMode.TIME_WINDOW:
            now = datetime.utcnow()
            if self.window_start and now < self.window_start:
                return False
            if self.window_end and now > self.window_end:
                return False

        elif self.expiry_mode == ExpiryMode.SESSION_BOUND:
            if not self.session_id:
                return False

        elif self.expiry_mode == ExpiryMode.ONE_TIME:
            if self.current_trigger_count >= 1:
                return False

        elif self.expiry_mode == ExpiryMode.COUNT_BASED:
            if self.max_trigger_count is not None:
                if self.current_trigger_count >= self.max_trigger_count:
                    return False

        elif self.expiry_mode == ExpiryMode.CONDITIONAL:
            if self.trigger_condition is not None:
                try:
                    if not self.trigger_condition():
                        return False
                except Exception:
                    return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if key == "rule":
                result[key] = value.dict()
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, Enum):
                result[key] = value.value
            elif callable(value):
                result[key] = repr(value)
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporaryRule":
        """Create from dictionary."""
        if "rule" in data and isinstance(data["rule"], dict):
            rule_data = data.pop("rule")
            data["rule"] = Rule(**rule_data)
        for key in ("created_at", "expires_at", "window_start", "window_end"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = datetime.fromisoformat(data[key])
                except (ValueError, TypeError):
                    data[key] = None if "expires" in key else datetime.utcnow()
        if "expiry_mode" in data and isinstance(data["expiry_mode"], str):
            try:
                data["expiry_mode"] = ExpiryMode(data["expiry_mode"])
            except ValueError:
                data["expiry_mode"] = ExpiryMode.TTL
        data.pop("trigger_condition", None)
        data.pop("on_expire_callback", None)
        data.pop("on_trigger_callback", None)
        return cls(**data)


@dataclass
class TemporaryRuleStats:
    """Statistics for temporary rule tracking."""

    total_created: int = 0
    total_expired: int = 0
    total_triggered: int = 0
    active_count: int = 0
    session_count: int = 0
    one_time_count: int = 0
    ttl_count: int = 0
    time_window_count: int = 0
    cleanup_count: int = 0
    average_ttl_seconds: float = 0.0
    by_tier: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_type: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_created": self.total_created,
            "total_expired": self.total_expired,
            "total_triggered": self.total_triggered,
            "active_count": self.active_count,
            "session_count": self.session_count,
            "one_time_count": self.one_time_count,
            "ttl_count": self.ttl_count,
            "time_window_count": self.time_window_count,
            "cleanup_count": self.cleanup_count,
            "average_ttl_seconds": self.average_ttl_seconds,
            "by_tier": dict(self.by_tier),
            "by_type": dict(self.by_type),
        }


class TemporaryRuleHandler:
    """
    Manages temporary, time-bound, session-scoped, and one-time rules.

    Supports multiple expiry modes, automatic cleanup, event callbacks,
    and comprehensive statistics tracking.
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._storage_path = storage_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "temp_rules"
        )
        self._config = self._default_config()
        if config:
            self._config.update(config)
        self._temp_rules: Dict[str, TemporaryRule] = {}
        self._session_rules: Dict[str, Dict[str, TemporaryRule]] = defaultdict(dict)
        self._one_time_rules: Dict[str, TemporaryRule] = {}
        self._stats = TemporaryRuleStats()
        self._lock = threading.RLock()
        self._cleanup_timer: Optional[threading.Timer] = None
        self._global_expiry_callback: Optional[Callable[[TemporaryRule], None]] = None
        self._global_trigger_callback: Optional[Callable[[TemporaryRule], None]] = None

        self._load_persistent_rules()

        if self._config["auto_cleanup_enabled"]:
            self._start_cleanup_scheduler()

        logger.info(
            "TemporaryRuleHandler initialized with %d active rules",
            len(self._temp_rules),
        )

    def _default_config(self) -> Dict[str, Any]:
        """Default configuration."""
        return {
            "max_temporary_rules": 5000,
            "max_session_rules_per_session": 200,
            "default_ttl_seconds": 3600,
            "min_ttl_seconds": 1,
            "max_ttl_seconds": 2592000,
            "auto_cleanup_enabled": True,
            "cleanup_interval_seconds": 300,
            "cleanup_strategy": "scheduled",
            "persist_temporary_rules": True,
            "max_one_time_rules": 1000,
            "enable_event_callbacks": True,
            "track_statistics": True,
            "log_expiry_events": True,
            "cleanup_batch_size": 100,
            "max_tag_count": 20,
        }

    def create_temporary_rule(
        self,
        rule: Rule,
        expiry_mode: Union[str, ExpiryMode] = "ttl",
        ttl_seconds: Optional[int] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        max_trigger_count: Optional[int] = None,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TemporaryRule:
        """Create a new temporary rule with the specified expiry constraints."""
        expiry = ExpiryMode(expiry_mode) if isinstance(expiry_mode, str) else expiry_mode

        if ttl_seconds is None:
            ttl_seconds = self._config["default_ttl_seconds"]
        ttl_seconds = max(self._config["min_ttl_seconds"], min(
            ttl_seconds, self._config["max_ttl_seconds"]
        ))

        expires_at: Optional[datetime] = None
        if expiry == ExpiryMode.TTL:
            expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        elif expiry == ExpiryMode.TIME_WINDOW:
            expires_at = window_end

        with self._lock:
            if len(self._temp_rules) >= self._config["max_temporary_rules"]:
                raise TemporaryRuleLimitError(
                    f"Maximum temporary rules reached ({self._config['max_temporary_rules']})"
                )

            temp_rule = TemporaryRule(
                rule=rule,
                expiry_mode=expiry,
                ttl_seconds=ttl_seconds,
                expires_at=expires_at,
                window_start=window_start,
                window_end=window_end,
                session_id=session_id,
                user_id=user_id,
                max_trigger_count=max_trigger_count,
                tags=tags or [],
                metadata=metadata or {},
            )

            self._temp_rules[temp_rule.temp_rule_id] = temp_rule

            if expiry == ExpiryMode.SESSION_BOUND and session_id:
                if len(self._session_rules[session_id]) >= self._config["max_session_rules_per_session"]:
                    del self._temp_rules[temp_rule.temp_rule_id]
                    raise TemporaryRuleLimitError(
                        f"Maximum session rules for session {session_id}"
                    )
                self._session_rules[session_id][temp_rule.temp_rule_id] = temp_rule

            if expiry == ExpiryMode.ONE_TIME:
                if len(self._one_time_rules) >= self._config["max_one_time_rules"]:
                    del self._temp_rules[temp_rule.temp_rule_id]
                    raise TemporaryRuleLimitError(
                        f"Maximum one-time rules reached ({self._config['max_one_time_rules']})"
                    )
                self._one_time_rules[temp_rule.temp_rule_id] = temp_rule

            if self._config["track_statistics"]:
                self._stats.total_created += 1
                self._stats.active_count = len(self._temp_rules)
                self._stats.by_tier[rule.tier.value] += 1
                self._stats.by_type[rule.rule_type.value] += 1
                if expiry == ExpiryMode.SESSION_BOUND:
                    self._stats.session_count += 1
                elif expiry == ExpiryMode.ONE_TIME:
                    self._stats.one_time_count += 1
                elif expiry == ExpiryMode.TTL:
                    self._stats.ttl_count += 1
                elif expiry == ExpiryMode.TIME_WINDOW:
                    self._stats.time_window_count += 1
                total_ttl = self._stats.average_ttl_seconds * (self._stats.total_created - 1)
                self._stats.average_ttl_seconds = (
                    (total_ttl + ttl_seconds) / self._stats.total_created
                )

            if self._config["persist_temporary_rules"]:
                self._save_temp_rule(temp_rule)

            logger.debug(
                "Created temporary rule '%s' (mode=%s, ttl=%s, session=%s)",
                rule.name, expiry.value, ttl_seconds, session_id,
            )
            return deepcopy(temp_rule)

    def get_temporary_rule(self, temp_rule_id: str) -> Optional[TemporaryRule]:
        """Get a temporary rule by its ID."""
        with self._lock:
            temp_rule = self._temp_rules.get(temp_rule_id)
            if temp_rule and not temp_rule.is_valid():
                self._expire_rule(temp_rule)
                return None
            return deepcopy(temp_rule) if temp_rule else None

    def get_temporary_rules(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        expiry_mode: Optional[ExpiryMode] = None,
        include_expired: bool = False,
    ) -> List[TemporaryRule]:
        """Get temporary rules matching the specified filters."""
        with self._lock:
            results: List[TemporaryRule] = []
            for temp_rule in self._temp_rules.values():
                if not include_expired and not temp_rule.is_valid():
                    continue
                if user_id and temp_rule.user_id != user_id:
                    continue
                if session_id and temp_rule.session_id != session_id:
                    continue
                if expiry_mode and temp_rule.expiry_mode != expiry_mode:
                    continue
                results.append(deepcopy(temp_rule))
            results.sort(key=lambda r: r.created_at, reverse=True)
            return results

    def get_session_rules(self, session_id: str) -> Dict[str, TemporaryRule]:
        """Get all temporary rules for a specific session."""
        with self._lock:
            rules = self._session_rules.get(session_id, {})
            valid = {}
            for rid, temp_rule in rules.items():
                if temp_rule.is_valid():
                    valid[rid] = deepcopy(temp_rule)
                else:
                    self._expire_rule(temp_rule)
            return valid

    def trigger_temporary_rule(self, temp_rule_id: str) -> bool:
        """Record a trigger event for a temporary rule (e.g., for one-time/count-based rules)."""
        with self._lock:
            temp_rule = self._temp_rules.get(temp_rule_id)
            if not temp_rule:
                return False
            if not temp_rule.is_valid():
                self._expire_rule(temp_rule)
                return False

            temp_rule.current_trigger_count += 1

            if self._config["track_statistics"]:
                self._stats.total_triggered += 1

            if temp_rule.on_trigger_callback and self._config["enable_event_callbacks"]:
                try:
                    temp_rule.on_trigger_callback(temp_rule)
                except Exception as exc:
                    logger.error("Trigger callback failed for %s: %s", temp_rule_id, exc)

            if self._global_trigger_callback and self._config["enable_event_callbacks"]:
                try:
                    self._global_trigger_callback(temp_rule)
                except Exception as exc:
                    logger.error("Global trigger callback failed: %s", exc)

            if not temp_rule.is_valid():
                self._expire_rule(temp_rule)

            if self._config["persist_temporary_rules"]:
                self._save_temp_rule(temp_rule)

            return True

    def extend_ttl(self, temp_rule_id: str, additional_seconds: int) -> bool:
        """Extend the TTL of a temporary rule."""
        with self._lock:
            temp_rule = self._temp_rules.get(temp_rule_id)
            if not temp_rule:
                return False
            if temp_rule.is_expired:
                return False

            if temp_rule.expiry_mode == ExpiryMode.TTL:
                new_ttl = temp_rule.ttl_seconds + additional_seconds
                if new_ttl > self._config["max_ttl_seconds"]:
                    new_ttl = self._config["max_ttl_seconds"]
                temp_rule.ttl_seconds = new_ttl
                temp_rule.expires_at = datetime.utcnow() + timedelta(seconds=new_ttl)

            elif temp_rule.expiry_mode == ExpiryMode.TIME_WINDOW:
                if temp_rule.window_end:
                    temp_rule.window_end += timedelta(seconds=additional_seconds)
                temp_rule.expires_at = temp_rule.window_end

            else:
                return False

            logger.debug("Extended TTL for rule %s by %d seconds", temp_rule_id, additional_seconds)
            return True

    def revoke_temporary_rule(self, temp_rule_id: str) -> bool:
        """Manually revoke a temporary rule before its natural expiry."""
        with self._lock:
            temp_rule = self._temp_rules.get(temp_rule_id)
            if not temp_rule:
                return False
            self._expire_rule(temp_rule)
            logger.info("Revoked temporary rule %s", temp_rule_id)
            return True

    def revoke_session_rules(self, session_id: str) -> int:
        """Revoke all temporary rules for a session."""
        with self._lock:
            session_rules = self._session_rules.get(session_id, {})
            count = len(session_rules)
            for temp_rule in list(session_rules.values()):
                self._expire_rule(temp_rule)
            logger.info("Revoked %d session rules for session %s", count, session_id)
            return count

    def register_on_expire_callback(
        self,
        temp_rule_id: str,
        callback: Callable[["TemporaryRule"], None],
    ) -> bool:
        """Register a callback to be invoked when a temporary rule expires."""
        with self._lock:
            temp_rule = self._temp_rules.get(temp_rule_id)
            if not temp_rule:
                return False
            temp_rule.on_expire_callback = callback
            return True

    def register_global_expiry_callback(
        self,
        callback: Callable[["TemporaryRule"], None],
    ) -> None:
        """Register a global callback invoked when any temporary rule expires."""
        self._global_expiry_callback = callback

    def register_global_trigger_callback(
        self,
        callback: Callable[["TemporaryRule"], None],
    ) -> None:
        """Register a global callback invoked when any temporary rule is triggered."""
        self._global_trigger_callback = callback

    def cleanup_expired_rules(self, batch_size: Optional[int] = None) -> int:
        """Remove all expired temporary rules."""
        with self._lock:
            batch = batch_size or self._config["cleanup_batch_size"]
            expired_ids: List[str] = []
            for tid, temp_rule in list(self._temp_rules.items()):
                if not temp_rule.is_valid():
                    expired_ids.append(tid)
                    if len(expired_ids) >= batch:
                        break

            count = len(expired_ids)
            for tid in expired_ids:
                temp_rule = self._temp_rules.get(tid)
                if temp_rule:
                    self._expire_rule(temp_rule)

            if self._config["track_statistics"]:
                self._stats.cleanup_count += count

            if count > 0:
                logger.info("Cleaned up %d expired temporary rules", count)
            return count

    def get_statistics(self) -> Dict[str, Any]:
        """Get temporary rule statistics."""
        with self._lock:
            stats = deepcopy(self._stats)
            stats.active_count = len(self._temp_rules)
            return stats.to_dict()

    def get_rules_by_tags(self, tags: List[str]) -> List[TemporaryRule]:
        """Get temporary rules that have any of the specified tags."""
        with self._lock:
            tag_set = set(tags)
            results = []
            for temp_rule in self._temp_rules.values():
                if not temp_rule.is_valid():
                    continue
                if tag_set & set(temp_rule.tags):
                    results.append(deepcopy(temp_rule))
            return results

    def create_session_scoped_rule(
        self,
        rule: Rule,
        session_id: str,
        user_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> TemporaryRule:
        """Convenience method to create a session-scoped temporary rule."""
        return self.create_temporary_rule(
            rule=rule,
            expiry_mode=ExpiryMode.SESSION_BOUND,
            ttl_seconds=ttl_seconds,
            session_id=session_id,
            user_id=user_id,
        )

    def create_one_time_rule(
        self,
        rule: Rule,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> TemporaryRule:
        """Convenience method to create a one-time rule."""
        return self.create_temporary_rule(
            rule=rule,
            expiry_mode=ExpiryMode.ONE_TIME,
            ttl_seconds=ttl_seconds,
            user_id=user_id,
            session_id=session_id,
            max_trigger_count=1,
        )

    def create_count_based_rule(
        self,
        rule: Rule,
        max_triggers: int,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> TemporaryRule:
        """Convenience method to create a count-based rule."""
        return self.create_temporary_rule(
            rule=rule,
            expiry_mode=ExpiryMode.COUNT_BASED,
            ttl_seconds=ttl_seconds,
            user_id=user_id,
            session_id=session_id,
            max_trigger_count=max_triggers,
        )

    def create_time_window_rule(
        self,
        rule: Rule,
        window_start: datetime,
        window_end: datetime,
        user_id: Optional[str] = None,
    ) -> TemporaryRule:
        """Convenience method to create a time-window rule."""
        return self.create_temporary_rule(
            rule=rule,
            expiry_mode=ExpiryMode.TIME_WINDOW,
            window_start=window_start,
            window_end=window_end,
            user_id=user_id,
        )

    def clear_all_rules(self) -> int:
        """Remove all temporary rules (for emergency/reset scenarios)."""
        with self._lock:
            count = len(self._temp_rules)
            for temp_rule in list(self._temp_rules.values()):
                self._expire_rule(temp_rule)
            logger.warning("Cleared all %d temporary rules", count)
            return count

    def shutdown(self) -> None:
        """Shutdown the handler and perform cleanup."""
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
        self.cleanup_expired_rules()
        logger.info("TemporaryRuleHandler shut down")

    def _expire_rule(self, temp_rule: TemporaryRule) -> None:
        """Mark a rule as expired and clean up references."""
        if temp_rule.is_expired:
            return
        temp_rule.is_expired = True

        tid = temp_rule.temp_rule_id
        self._temp_rules.pop(tid, None)

        if temp_rule.session_id:
            session_rules = self._session_rules.get(temp_rule.session_id, {})
            session_rules.pop(tid, None)

        self._one_time_rules.pop(tid, None)

        if self._config["log_expiry_events"]:
            logger.info(
                "Temporary rule '%s' expired (mode=%s, triggers=%d)",
                temp_rule.rule.name, temp_rule.expiry_mode.value,
                temp_rule.current_trigger_count,
            )

        if temp_rule.on_expire_callback and self._config["enable_event_callbacks"]:
            try:
                temp_rule.on_expire_callback(temp_rule)
            except Exception as exc:
                logger.error("Expiry callback failed for %s: %s", tid, exc)

        if self._global_expiry_callback and self._config["enable_event_callbacks"]:
            try:
                self._global_expiry_callback(temp_rule)
            except Exception as exc:
                logger.error("Global expiry callback failed: %s", exc)

        if self._config["track_statistics"]:
            self._stats.total_expired += 1
            self._stats.active_count = len(self._temp_rules)

        if self._config["persist_temporary_rules"]:
            self._delete_temp_rule_file(tid)

    def _start_cleanup_scheduler(self) -> None:
        """Start the periodic cleanup scheduler."""
        interval = self._config["cleanup_interval_seconds"]

        def cleanup_worker() -> None:
            try:
                self.cleanup_expired_rules()
            except Exception as exc:
                logger.error("Scheduled cleanup failed: %s", exc)
            finally:
                with self._lock:
                    if self._config["auto_cleanup_enabled"]:
                        self._cleanup_timer = threading.Timer(interval, cleanup_worker)
                        self._cleanup_timer.daemon = True
                        self._cleanup_timer.start()

        self._cleanup_timer = threading.Timer(interval, cleanup_worker)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()
        logger.debug("Cleanup scheduler started (interval=%ds)", interval)

    def _load_persistent_rules(self) -> None:
        """Load persisted temporary rules from storage."""
        storage_path = Path(self._storage_path)
        if not storage_path.exists():
            storage_path.mkdir(parents=True, exist_ok=True)
            return
        for file_path in storage_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                temp_rule = TemporaryRule.from_dict(data)
                if temp_rule.is_valid():
                    self._temp_rules[temp_rule.temp_rule_id] = temp_rule
                    if temp_rule.session_id:
                        self._session_rules[temp_rule.session_id][temp_rule.temp_rule_id] = temp_rule
                    if temp_rule.expiry_mode == ExpiryMode.ONE_TIME:
                        self._one_time_rules[temp_rule.temp_rule_id] = temp_rule
                    if self._config["track_statistics"]:
                        self._stats.total_created += 1
                else:
                    self._delete_temp_rule_file(file_path.stem)
            except Exception as exc:
                logger.error("Failed to load temp rule from %s: %s", file_path, exc)

    def _save_temp_rule(self, temp_rule: TemporaryRule) -> None:
        """Save a temporary rule to storage."""
        storage_path = Path(self._storage_path)
        storage_path.mkdir(parents=True, exist_ok=True)
        file_path = storage_path / f"{temp_rule.temp_rule_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(temp_rule.to_dict(), f, indent=2, default=str)

    def _delete_temp_rule_file(self, temp_rule_id: str) -> None:
        """Delete a temporary rule file from storage."""
        file_path = Path(self._storage_path) / f"{temp_rule_id}.json"
        if file_path.exists():
            file_path.unlink()
