"""Adaptive scheduler for rule adaptation events.

Provides cron-like and interval-based scheduling, time-window restrictions,
multi-rule batch coordination, event prioritization, and queue management.
"""

import heapq
import itertools
import json
import logging
import math
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType

logger = logging.getLogger(__name__)


class ScheduleType(str, Enum):
    """Types of scheduling mechanisms."""
    INTERVAL = "interval"
    CRON = "cron"
    ONCE = "once"
    IMMEDIATE = "immediate"
    RECURRING = "recurring"


class EventPriority(str, Enum):
    """Priority levels for scheduled events."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EventStatus(str, Enum):
    """Status of a scheduled event."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class DayOfWeek(int, Enum):
    """Days of week for schedule windows."""
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass(order=True)
class ScheduledEvent:
    """A scheduled adaptation event with priority ordering."""
    next_run: datetime
    priority: int = field(default=0)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schedule_type: ScheduleType = ScheduleType.ONCE
    rule_ids: List[str] = field(default_factory=list)
    action: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    interval_seconds: float = 0.0
    cron_expression: Optional[str] = None
    max_executions: int = 0
    execution_count: int = 0
    status: EventStatus = EventStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_run: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    callback: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdaptationWindow:
    """Time window during which adaptations are allowed."""
    window_id: str
    start_hour: int = 0
    end_hour: int = 23
    allowed_days: List[DayOfWeek] = field(default_factory=lambda: list(DayOfWeek))
    timezone_offset: int = 0
    description: str = ""

    def is_within_window(self, dt: Optional[datetime] = None) -> bool:
        """Check if a given datetime falls within this window.

        Args:
            dt: Datetime to check (defaults to UTC now).

        Returns:
            True if within the allowed window.
        """
        dt = dt or datetime.utcnow()
        local_hour = (dt.hour + self.timezone_offset) % 24

        if dt.weekday() not in [d.value for d in self.allowed_days]:
            return False

        if self.start_hour <= self.end_hour:
            return self.start_hour <= local_hour < self.end_hour

        return local_hour >= self.start_hour or local_hour < self.end_hour


@dataclass
class SchedulerStatistics:
    """Aggregated statistics for the adaptive scheduler."""
    total_events_scheduled: int = 0
    events_completed: int = 0
    events_failed: int = 0
    events_skipped: int = 0
    events_cancelled: int = 0
    pending_events: int = 0
    events_by_type: Dict[str, int] = field(default_factory=dict)
    events_by_priority: Dict[str, int] = field(default_factory=dict)
    unique_rules_scheduled: int = 0
    avg_queue_wait_ms: float = 0.0
    total_queue_wait_ms: float = 0.0
    total_wait_records: int = 0
    uptime_hours: float = 0.0
    last_event_time: Optional[datetime] = None
    active_windows: int = 0


class CronParser:
    """Simple cron expression parser supporting basic patterns.

    Supports: minute, hour, day-of-week fields.
    Patterns: *, */N, N-M, N,M,O comma lists.
    """

    def __init__(self, expression: str) -> None:
        self.expression = expression
        self._fields = self._parse(expression)

    def _parse(self, expression: str) -> Dict[str, Set[int]]:
        """Parse a cron expression into field sets."""
        parts = expression.strip().split()
        if len(parts) < 3:
            raise ValueError(
                f"Cron expression must have at least 3 fields (minute hour day-of-week), got: {expression}"
            )

        minute_str = parts[0]
        hour_str = parts[1]
        dow_str = parts[2]

        return {
            "minute": self._expand_field(minute_str, 0, 59),
            "hour": self._expand_field(hour_str, 0, 23),
            "day_of_week": self._expand_field(dow_str, 0, 6),
        }

    def _expand_field(self, field: str, min_val: int, max_val: int) -> Set[int]:
        """Expand a cron field into a set of matching values."""
        result: Set[int] = set()

        for part in field.split(","):
            part = part.strip()
            if not part:
                continue

            if part == "*":
                return set(range(min_val, max_val + 1))

            if "/" in part:
                base, step_str = part.split("/", 1)
                step = int(step_str)
                if base == "*":
                    result.update(range(min_val, max_val + 1, step))
                else:
                    start = int(base)
                    result.update(range(start, max_val + 1, step))
                continue

            if "-" in part:
                low_str, high_str = part.split("-", 1)
                result.update(range(int(low_str), int(high_str) + 1))
                continue

            result.add(int(part))

        return result

    def matches(self, dt: datetime) -> bool:
        """Check if a datetime matches the cron expression."""
        return (
            dt.minute in self._fields["minute"]
            and dt.hour in self._fields["hour"]
            and dt.weekday() in self._fields["day_of_week"]
        )

    def next_match(self, from_dt: Optional[datetime] = None) -> Optional[datetime]:
        """Find the next datetime matching the cron expression.

        Args:
            from_dt: Starting point (defaults to now).

        Returns:
            Next matching datetime, or None if not found within 7 days.
        """
        from_dt = from_dt or datetime.utcnow()
        check = from_dt.replace(second=0, microsecond=0)

        for _ in range(7 * 24 * 60):
            if self.matches(check) and check > from_dt:
                return check
            check += timedelta(minutes=1)

        return None


class AdaptiveScheduler:
    """Scheduler for rule adaptation events.

    Supports interval-based and cron-like scheduling, time-window
    restrictions, multi-rule batch coordination, event prioritization
    with a priority queue, and comprehensive statistics.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._event_queue: List[ScheduledEvent] = []
        self._events: Dict[str, ScheduledEvent] = {}
        self._adaptation_windows: List[AdaptationWindow] = []
        self._completed_events: deque = deque(
            maxlen=self.config.get("max_completed_history", 1000)
        )
        self._lock = Lock()
        self._event_counter: itertools.count = itertools.count()
        self._start_time: datetime = datetime.utcnow()
        self._default_window = AdaptationWindow(
            window_id="default",
            start_hour=self.config.get("default_start_hour", 0),
            end_hour=self.config.get("default_end_hour", 23),
            allowed_days=list(DayOfWeek),
            description="Default adaptation window",
        )

        logger.info(
            "AdaptiveScheduler initialized (max_completed=%d)",
            self.config.get("max_completed_history", 1000),
        )

    def schedule_interval(
        self,
        rule_ids: List[str],
        action: str,
        interval_seconds: float,
        priority: EventPriority = EventPriority.MEDIUM,
        params: Optional[Dict[str, Any]] = None,
        max_executions: int = 0,
        tags: Optional[List[str]] = None,
        start_delay: float = 0.0,
    ) -> str:
        """Schedule a recurring interval-based adaptation.

        Args:
            rule_ids: Rules to adapt.
            action: Action to perform (e.g., "adapt_threshold", "adapt_patterns").
            interval_seconds: Interval between executions.
            priority: Event priority level.
            params: Additional parameters for the action.
            max_executions: Max times to run (0 = unlimited).
            tags: Optional tags for filtering.
            start_delay: Delay before first execution (seconds).

        Returns:
            The event ID.
        """
        first_run = datetime.utcnow() + timedelta(seconds=start_delay)

        event = ScheduledEvent(
            next_run=first_run,
            priority=self._priority_to_int(priority),
            schedule_type=ScheduleType.INTERVAL,
            rule_ids=rule_ids,
            action=action,
            params=params or {},
            interval_seconds=interval_seconds,
            max_executions=max_executions,
            tags=tags or [],
        )

        self._add_event(event)
        logger.info(
            "Scheduled interval event %s: every %.1fs for %d rules (priority=%s)",
            event.event_id, interval_seconds, len(rule_ids), priority.value,
        )

        return event.event_id

    def schedule_cron(
        self,
        rule_ids: List[str],
        action: str,
        cron_expression: str,
        priority: EventPriority = EventPriority.MEDIUM,
        params: Optional[Dict[str, Any]] = None,
        max_executions: int = 0,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Schedule a cron-based adaptation event.

        Args:
            rule_ids: Rules to adapt.
            action: Action to perform.
            cron_expression: Cron pattern (minute hour day-of-week).
            priority: Event priority level.
            params: Additional parameters.
            max_executions: Max runs (0 = unlimited).
            tags: Optional tags.

        Returns:
            The event ID.
        """
        parser = CronParser(cron_expression)
        next_run = parser.next_match()

        if next_run is None:
            logger.warning(
                "Cron expression %s has no future match within 7 days",
                cron_expression,
            )
            next_run = datetime.utcnow() + timedelta(days=7)

        event = ScheduledEvent(
            next_run=next_run,
            priority=self._priority_to_int(priority),
            schedule_type=ScheduleType.CRON,
            rule_ids=rule_ids,
            action=action,
            params=params or {},
            cron_expression=cron_expression,
            max_executions=max_executions,
            tags=tags or [],
        )

        self._add_event(event)
        logger.info(
            "Scheduled cron event %s: '%s' next=%s (priority=%s)",
            event.event_id, cron_expression,
            next_run.isoformat(), priority.value,
        )

        return event.event_id

    def schedule_once(
        self,
        rule_ids: List[str],
        action: str,
        run_at: Optional[datetime] = None,
        delay_seconds: float = 0.0,
        priority: EventPriority = EventPriority.MEDIUM,
        params: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Schedule a one-time adaptation event.

        Args:
            rule_ids: Rules to adapt.
            action: Action to perform.
            run_at: Specific datetime to run (alternative to delay_seconds).
            delay_seconds: Delay from now (alternative to run_at).
            priority: Event priority.
            params: Additional parameters.
            tags: Optional tags.

        Returns:
            The event ID.
        """
        if run_at:
            first_run = run_at
        else:
            first_run = datetime.utcnow() + timedelta(seconds=delay_seconds)

        event = ScheduledEvent(
            next_run=first_run,
            priority=self._priority_to_int(priority),
            schedule_type=ScheduleType.ONCE,
            rule_ids=rule_ids,
            action=action,
            params=params or {},
            max_executions=1,
            tags=tags or [],
        )

        self._add_event(event)
        logger.info(
            "Scheduled one-time event %s: at %s (priority=%s)",
            event.event_id, first_run.isoformat(), priority.value,
        )

        return event.event_id

    def schedule_immediate(
        self,
        rule_ids: List[str],
        action: str,
        priority: EventPriority = EventPriority.HIGH,
        params: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Schedule an immediate (high-priority) adaptation event.

        Args:
            rule_ids: Rules to adapt.
            action: Action to perform.
            priority: Event priority (defaults to HIGH).
            params: Additional parameters.
            tags: Optional tags.

        Returns:
            The event ID.
        """
        return self.schedule_once(
            rule_ids=rule_ids,
            action=action,
            delay_seconds=0.0,
            priority=priority,
            params=params,
            tags=tags,
        )

    def add_adaptation_window(self, window: AdaptationWindow) -> str:
        """Add a time window restriction for adaptations.

        Args:
            window: The AdaptationWindow to add.

        Returns:
            The window ID.
        """
        self._adaptation_windows.append(window)
        logger.info(
            "Added adaptation window %s: %02d:00-%02d:00, %d days",
            window.window_id, window.start_hour, window.end_hour,
            len(window.allowed_days),
        )
        return window.window_id

    def remove_adaptation_window(self, window_id: str) -> bool:
        """Remove an adaptation window by ID."""
        before = len(self._adaptation_windows)
        self._adaptation_windows = [
            w for w in self._adaptation_windows if w.window_id != window_id
        ]
        removed = before - len(self._adaptation_windows) > 0
        if removed:
            logger.info("Removed adaptation window %s", window_id)
        return removed

    def is_within_window(self, dt: Optional[datetime] = None) -> bool:
        """Check if a given time falls within any adaptation window.

        If no windows are configured, uses a default 24/7 window.

        Args:
            dt: Datetime to check (defaults to now).

        Returns:
            True if within at least one adaptation window.
        """
        dt = dt or datetime.utcnow()

        if not self._adaptation_windows:
            return self._default_window.is_within_window(dt)

        return any(w.is_within_window(dt) for w in self._adaptation_windows)

    def get_due_events(self, limit: int = 50) -> List[ScheduledEvent]:
        """Get all events that are due for execution.

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of due ScheduledEvent instances.
        """
        now = datetime.utcnow()
        due: List[ScheduledEvent] = []

        with self._lock:
            while self._event_queue and len(due) < limit:
                if self._event_queue[0].next_run > now:
                    break
                event = heapq.heappop(self._event_queue)
                if event.status == EventStatus.PENDING:
                    due.append(event)

        for event in due:
            event.last_run = now
            event.status = EventStatus.RUNNING
            event.execution_count += 1

        if due:
            logger.debug("Retrieved %d due events", len(due))

        return due

    def complete_event(
        self,
        event_id: str,
        success: bool = True,
        reschedule: bool = True,
    ) -> None:
        """Mark an event as completed and optionally reschedule.

        Args:
            event_id: The event to complete.
            success: Whether the execution succeeded.
            reschedule: Whether to reschedule recurring events.
        """
        event = self._events.get(event_id)
        if event is None:
            logger.warning("Event %s not found for completion", event_id)
            return

        event.status = EventStatus.COMPLETED if success else EventStatus.FAILED

        if success and reschedule and event.schedule_type in (
            ScheduleType.INTERVAL, ScheduleType.RECURRING,
        ):
            if event.max_executions == 0 or event.execution_count < event.max_executions:
                event.next_run = datetime.utcnow() + timedelta(seconds=event.interval_seconds)
                event.status = EventStatus.PENDING
                self._add_event(event, check_exists=False)
                logger.debug("Rescheduled event %s: next at %s", event_id, event.next_run.isoformat())
            else:
                logger.info("Event %s reached max_executions (%d)", event_id, event.max_executions)

        if event.schedule_type == ScheduleType.CRON and success and reschedule:
            parser = CronParser(event.cron_expression)
            next_run = parser.next_match()
            if next_run and (
                event.max_executions == 0 or event.execution_count < event.max_executions
            ):
                event.next_run = next_run
                event.status = EventStatus.PENDING
                self._add_event(event, check_exists=False)
            else:
                logger.info("Cron event %s has no further runs", event_id)

        if event.status in (EventStatus.COMPLETED, EventStatus.FAILED):
            self._completed_events.append(event)

    def cancel_event(self, event_id: str) -> bool:
        """Cancel a pending event.

        Args:
            event_id: The event to cancel.

        Returns:
            True if the event was cancelled.
        """
        event = self._events.get(event_id)
        if event is None:
            return False

        event.status = EventStatus.CANCELLED
        self._completed_events.append(event)

        with self._lock:
            self._event_queue = [
                e for e in self._event_queue if e.event_id != event_id
            ]
            heapq.heapify(self._event_queue)

        logger.info("Cancelled event %s", event_id)
        return True

    def get_event(self, event_id: str) -> Optional[ScheduledEvent]:
        """Get a scheduled event by ID."""
        return self._events.get(event_id)

    def get_events(
        self,
        rule_id: Optional[str] = None,
        status: Optional[EventStatus] = None,
        schedule_type: Optional[ScheduleType] = None,
        priority: Optional[EventPriority] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[ScheduledEvent]:
        """Query events with filters.

        Args:
            rule_id: Filter by rule involved.
            status: Filter by status.
            schedule_type: Filter by schedule type.
            priority: Filter by priority.
            limit: Max results.
            offset: Skip count.

        Returns:
            Filtered list of events.
        """
        events = list(self._events.values()) + list(self._completed_events)

        if rule_id:
            events = [e for e in events if rule_id in e.rule_ids]
        if status:
            events = [e for e in events if e.status == status]
        if schedule_type:
            events = [e for e in events if e.schedule_type == schedule_type]
        if priority:
            events = [e for e in events if e.priority == self._priority_to_int(priority)]

        events.sort(key=lambda e: e.created_at, reverse=True)
        events = events[offset:]
        if limit:
            events = events[:limit]

        return events

    def get_next_event(self, rule_id: Optional[str] = None) -> Optional[ScheduledEvent]:
        """Get the next pending event, optionally for a specific rule."""
        pending = [e for e in self._events.values() if e.status == EventStatus.PENDING]
        if rule_id:
            pending = [e for e in pending if rule_id in e.rule_ids]
        if not pending:
            return None
        return min(pending, key=lambda e: e.next_run)

    def reschedule_event(
        self,
        event_id: str,
        new_interval: Optional[float] = None,
        new_cron: Optional[str] = None,
    ) -> bool:
        """Reschedule an existing event with new timing.

        Args:
            event_id: The event to reschedule.
            new_interval: New interval in seconds (for interval events).
            new_cron: New cron expression (for cron events).

        Returns:
            True if rescheduled.
        """
        event = self._events.get(event_id)
        if event is None:
            logger.warning("Event %s not found for reschedule", event_id)
            return False

        if new_interval is not None and event.schedule_type == ScheduleType.INTERVAL:
            event.interval_seconds = new_interval
            event.next_run = datetime.utcnow() + timedelta(seconds=new_interval)
            logger.info("Rescheduled event %s: new interval=%.1fs", event_id, new_interval)

        if new_cron is not None and event.schedule_type == ScheduleType.CRON:
            parser = CronParser(new_cron)
            next_run = parser.next_match()
            if next_run:
                event.cron_expression = new_cron
                event.next_run = next_run
                logger.info("Rescheduled event %s: new cron='%s' next=%s", event_id, new_cron, next_run.isoformat())
            else:
                logger.warning("New cron expression %s has no future match", new_cron)
                return False

        return True

    def get_statistics(self) -> SchedulerStatistics:
        """Get aggregated scheduler statistics."""
        all_events = list(self._events.values())
        completed = [e for e in all_events if e.status == EventStatus.COMPLETED]
        failed = [e for e in all_events if e.status == EventStatus.FAILED]
        skipped = [e for e in all_events if e.status == EventStatus.SKIPPED]
        cancelled = [e for e in all_events if e.status == EventStatus.CANCELLED]
        pending = [e for e in all_events if e.status == EventStatus.PENDING]

        by_type: Dict[str, int] = defaultdict(int)
        by_priority: Dict[str, int] = defaultdict(int)
        unique_rules: Set[str] = set()

        for e in all_events:
            by_type[e.schedule_type.value] += 1
            by_priority[self._int_to_priority(e.priority).value] += 1
            unique_rules.update(e.rule_ids)

        uptime = (datetime.utcnow() - self._start_time).total_seconds() / 3600.0

        total_wait_ms = sum(
            ((e.last_run - e.created_at).total_seconds() * 1000.0)
            for e in all_events if e.last_run
        )
        total_wait_records = sum(1 for e in all_events if e.last_run)
        avg_wait = total_wait_ms / max(total_wait_records, 1)

        return SchedulerStatistics(
            total_events_scheduled=len(all_events),
            events_completed=len(completed),
            events_failed=len(failed),
            events_skipped=len(skipped),
            events_cancelled=len(cancelled),
            pending_events=len(pending),
            events_by_type=dict(by_type),
            events_by_priority=dict(by_priority),
            unique_rules_scheduled=len(unique_rules),
            avg_queue_wait_ms=round(avg_wait, 2),
            total_queue_wait_ms=round(self._total_queue_wait_ms, 2),
            total_wait_records=self._total_wait_records,
            uptime_hours=round(uptime, 2),
            last_event_time=completed[-1].last_run if completed else None,
            active_windows=len(self._adaptation_windows),
        )

    def get_schedule_summary(self) -> Dict[str, Any]:
        """Get a human-readable summary of the current schedule."""
        pending = [e for e in self._events.values() if e.status == EventStatus.PENDING]
        now = datetime.utcnow()

        next_event = min(pending, key=lambda e: e.next_run) if pending else None

        upcoming: List[Dict[str, Any]] = []
        for event in sorted(pending, key=lambda e: e.next_run)[:10]:
            upcoming.append({
                "event_id": event.event_id,
                "action": event.action,
                "rule_count": len(event.rule_ids),
                "schedule_type": event.schedule_type.value,
                "next_run": event.next_run.isoformat(),
                "in_seconds": (event.next_run - now).total_seconds(),
                "priority": self._int_to_priority(event.priority).value,
            })

        return {
            "total_events": len(self._events),
            "pending_events": len(pending),
            "next_event": {
                "event_id": next_event.event_id,
                "action": next_event.action,
                "next_run": next_event.next_run.isoformat(),
                "in_seconds": round((next_event.next_run - now).total_seconds(), 1),
            } if next_event else None,
            "within_window": self.is_within_window(),
            "active_windows": len(self._adaptation_windows),
            "upcoming": upcoming,
        }

    def clear_completed(self, max_age_hours: float = 24.0) -> int:
        """Clear completed events older than a threshold.

        Args:
            max_age_hours: Max age in hours for completed events.

        Returns:
            Number of events cleared.
        """
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        before = len(self._completed_events)
        self._completed_events = deque(
            (e for e in self._completed_events if e.last_run and e.last_run >= cutoff),
            maxlen=self._completed_events.maxlen,
        )
        cleared = before - len(self._completed_events)

        events_to_remove = [
            eid for eid, e in self._events.items()
            if e.status in (EventStatus.COMPLETED, EventStatus.FAILED, EventStatus.CANCELLED)
            and e.last_run and e.last_run < cutoff
        ]
        for eid in events_to_remove:
            del self._events[eid]
        cleared += len(events_to_remove)

        logger.info("Cleared %d completed events", cleared)
        return cleared

    def _add_event(self, event: ScheduledEvent, check_exists: bool = True) -> None:
        """Add an event to the queue and event registry.

        Args:
            event: The event to add.
            check_exists: If True, skip if event_id already exists.
        """
        if check_exists and event.event_id in self._events:
            return

        self._events[event.event_id] = event

        with self._lock:
            heapq.heappush(self._event_queue, event)

    def _priority_to_int(self, priority: EventPriority) -> int:
        """Convert EventPriority enum to integer (lower = higher priority)."""
        mapping = {
            EventPriority.CRITICAL: 0,
            EventPriority.HIGH: 1,
            EventPriority.MEDIUM: 2,
            EventPriority.LOW: 3,
        }
        return mapping.get(priority, 2)

    def _int_to_priority(self, value: int) -> EventPriority:
        """Convert integer priority back to EventPriority enum."""
        mapping = {
            0: EventPriority.CRITICAL,
            1: EventPriority.HIGH,
            2: EventPriority.MEDIUM,
            3: EventPriority.LOW,
        }
        return mapping.get(value, EventPriority.MEDIUM)

    @property
    def _total_queue_wait_ms(self) -> float:
        return sum(
            ((e.last_run - e.created_at).total_seconds() * 1000.0)
            for e in self._events.values()
            if e.last_run
        )

    @property
    def _total_wait_records(self) -> int:
        return sum(1 for e in self._events.values() if e.last_run)


# Backward-compatible alias
AdaptiveScheduler = AdaptiveScheduler
