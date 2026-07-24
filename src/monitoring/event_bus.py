"""Event bus system for publishing and subscribing to events."""
import json
import logging
import queue
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class DeliveryGuarantee(Enum):
    """Delivery guarantee levels."""
    AT_MOST_ONCE = "at_most_once"
    AT_LEAST_ONCE = "at_least_once"
    EXACTLY_ONCE = "exactly_once"


class EventPriority(Enum):
    """Event processing priority levels."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Event:
    """Represents an event in the event bus."""
    event_id: str
    event_type: str
    data: Dict[str, Any]
    timestamp: datetime
    source: str = "unknown"
    priority: EventPriority = EventPriority.NORMAL
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    delivery_guarantee: DeliveryGuarantee = DeliveryGuarantee.AT_LEAST_ONCE


@dataclass
class EventFilter:
    """Filter for event subscriptions."""
    event_types: Optional[List[str]] = None
    sources: Optional[List[str]] = None
    min_priority: Optional[EventPriority] = None
    data_filters: Optional[Dict[str, Any]] = None


@dataclass
class Subscriber:
    """Represents a subscriber to events."""
    subscriber_id: str
    handler: Callable[[Event], None]
    event_types: List[str]
    filter: Optional[EventFilter] = None
    name: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class DeliveryRecord:
    """Record of an event delivery attempt."""
    event_id: str
    subscriber_id: str
    status: str
    timestamp: datetime
    error: Optional[str] = None
    attempt: int = 1


@dataclass
class SubscriberStatistics:
    """Statistics for a subscriber."""
    subscriber_id: str
    total_events_received: int = 0
    successful_deliveries: int = 0
    failed_deliveries: int = 0
    last_event_received: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    avg_processing_time_ms: float = 0.0
    total_processing_time_ms: float = 0.0


class EventBus:
    """Event bus for publishing and subscribing to events with async processing.

    Supports event filtering, history with retention, replay,
    delivery guarantees, and subscriber statistics.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the event bus.

        Args:
            config: Optional configuration dictionary
        """
        self._lock = threading.RLock()
        self._subscribers: Dict[str, Subscriber] = {}
        self._event_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._history: List[Event] = []
        self._delivery_records: List[DeliveryRecord] = []
        self._subscriber_stats: Dict[str, SubscriberStatistics] = {}
        self._event_counter = 0

        self._pool_threads: List[threading.Thread] = []
        self._pool_running = False
        self._replay_in_progress = False

        self._config = config or {}
        self._started_at = datetime.now()

        self.max_history_size = self._config.get("max_history_size", 10000)
        self.max_delivery_records = self._config.get("max_delivery_records", 50000)
        self.retention_hours = self._config.get("retention_hours", 24)
        self.thread_pool_size = self._config.get("thread_pool_size", 4)
        self.max_retries = self._config.get("max_retries", 3)
        self.retry_delay_seconds = self._config.get("retry_delay_seconds", 5)
        self.default_delivery_guarantee = DeliveryGuarantee(
            self._config.get("default_delivery_guarantee", "at_least_once")
        )

        if self._config.get("subscribers"):
            self._load_subscribers_from_config(self._config["subscribers"])

        logger.info("EventBus initialized")

    def _load_subscribers_from_config(self, subscribers_config: List[Dict[str, Any]]) -> None:
        """Load subscribers from configuration.

        Args:
            subscribers_config: List of subscriber configuration dictionaries
        """
        for cfg in subscribers_config:
            try:
                handler = self._create_handler_from_config(cfg)
                if handler:
                    filter_cfg = cfg.get("filter")
                    event_filter = None
                    if filter_cfg:
                        min_priority = None
                        if "min_priority" in filter_cfg:
                            min_priority = EventPriority[filter_cfg["min_priority"].upper()]
                        event_filter = EventFilter(
                            event_types=filter_cfg.get("event_types"),
                            sources=filter_cfg.get("sources"),
                            min_priority=min_priority,
                            data_filters=filter_cfg.get("data_filters"),
                        )
                    self.subscribe(
                        cfg["event_types"],
                        handler,
                        subscriber_id=cfg.get("subscriber_id"),
                        name=cfg.get("name", ""),
                        event_filter=event_filter,
                    )
                    logger.info(f"Loaded subscriber from config: {cfg.get('name', cfg.get('subscriber_id', 'unknown'))}")
            except Exception as e:
                logger.error(f"Failed to load subscriber from config: {e}")

    def _create_handler_from_config(self, cfg: Dict[str, Any]) -> Optional[Callable]:
        """Create a handler function from configuration.

        Args:
            cfg: Subscriber configuration

        Returns:
            Handler function or None
        """
        handler_type = cfg.get("handler_type", "log")

        if handler_type == "log":

            def log_handler(event: Event) -> None:
                logger.info(f"[EventBus] {event.event_type}: {json.dumps(event.data, default=str)[:200]}")

            return log_handler

        elif handler_type == "webhook":
            webhook_url = cfg.get("webhook_url", "")
            timeout = cfg.get("timeout_seconds", 30)

            def webhook_handler(event: Event) -> None:
                import urllib.request
                import urllib.error
                payload = json.dumps({
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "data": event.data,
                    "timestamp": event.timestamp.isoformat(),
                    "source": event.source,
                }).encode("utf-8")
                req = urllib.request.Request(
                    webhook_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status not in (200, 201, 202, 204):
                        logger.warning(f"Webhook returned {resp.status} for event {event.event_id}")

            return webhook_handler

        elif handler_type == "callback":
            logger.warning("Callback handler type requires a registered callback function, using log fallback")

            def callback_fallback(event: Event) -> None:
                logger.info(f"[EventBus-Callback] {event.event_type}: {json.dumps(event.data, default=str)[:200]}")

            return callback_fallback

        else:
            logger.warning(f"Unknown handler type: {handler_type}, using log")
            return lambda event: logger.info(f"[EventBus] {event.event_type}: {json.dumps(event.data, default=str)[:200]}")

    def publish(
        self,
        event_type: str,
        data: Dict[str, Any],
        source: str = "unknown",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
        delivery_guarantee: Optional[DeliveryGuarantee] = None,
    ) -> str:
        """Publish an event to the bus.

        Args:
            event_type: Type of the event
            data: Event data payload
            source: Source of the event
            priority: Event priority
            metadata: Optional metadata
            delivery_guarantee: Override default delivery guarantee

        Returns:
            The event ID
        """
        with self._lock:
            self._event_counter += 1
            event_id = f"EVT_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._event_counter}_{uuid.uuid4().hex[:8]}"

        event = Event(
            event_id=event_id,
            event_type=event_type,
            data=data,
            timestamp=datetime.now(),
            source=source,
            priority=priority,
            metadata=metadata or {},
            delivery_guarantee=delivery_guarantee or self.default_delivery_guarantee,
        )

        with self._lock:
            self._history.append(event)
            self._prune_history()

        self._event_queue.put((-priority.value, event))
        logger.debug(f"Published event: {event_id} ({event_type})")
        return event_id

    def subscribe(
        self,
        event_types: List[str],
        handler: Callable[[Event], None],
        subscriber_id: Optional[str] = None,
        name: str = "",
        event_filter: Optional[EventFilter] = None,
    ) -> str:
        """Subscribe a handler to one or more event types.

        Args:
            event_types: List of event types to subscribe to
            handler: Callable that accepts an Event
            subscriber_id: Optional subscriber ID (auto-generated if None)
            name: Optional human-readable name
            event_filter: Optional event filter

        Returns:
            The subscriber ID
        """
        sid = subscriber_id or f"sub_{uuid.uuid4().hex[:12]}"

        subscriber = Subscriber(
            subscriber_id=sid,
            handler=handler,
            event_types=event_types,
            filter=event_filter,
            name=name or sid,
        )

        with self._lock:
            self._subscribers[sid] = subscriber
            if sid not in self._subscriber_stats:
                self._subscriber_stats[sid] = SubscriberStatistics(subscriber_id=sid)

        logger.info(f"Subscribed {sid} to {event_types}")
        return sid

    def unsubscribe(self, event_types: List[str], handler: Callable) -> bool:
        """Unsubscribe a handler from specific event types.

        Args:
            event_types: Event types to unsubscribe from
            handler: The handler to remove

        Returns:
            True if unsubscribed, False otherwise
        """
        with self._lock:
            to_remove = []
            for sid, subscriber in self._subscribers.items():
                if subscriber.handler is handler:
                    remaining = [et for et in subscriber.event_types if et not in event_types]
                    if remaining:
                        subscriber.event_types = remaining
                    else:
                        to_remove.append(sid)

            for sid in to_remove:
                del self._subscribers[sid]
                self._subscriber_stats.pop(sid, None)

            if to_remove:
                logger.info(f"Unsubscribed handler from {event_types}")
                return True
            return False

    def unsubscribe_by_id(self, subscriber_id: str) -> bool:
        """Unsubscribe a subscriber by ID.

        Args:
            subscriber_id: ID of the subscriber to remove

        Returns:
            True if removed, False otherwise
        """
        with self._lock:
            if subscriber_id in self._subscribers:
                del self._subscribers[subscriber_id]
                self._subscriber_stats.pop(subscriber_id, None)
                logger.info(f"Unsubscribed: {subscriber_id}")
                return True
            return False

    def get_subscriber(self, subscriber_id: str) -> Optional[Subscriber]:
        """Get a subscriber by ID.

        Args:
            subscriber_id: Subscriber ID

        Returns:
            Subscriber or None
        """
        with self._lock:
            return self._subscribers.get(subscriber_id)

    def get_subscribers(self) -> Dict[str, Subscriber]:
        """Get all subscribers.

        Returns:
            Dictionary of subscriber IDs to Subscribers
        """
        with self._lock:
            return dict(self._subscribers)

    def _match_subscriber(self, subscriber: Subscriber, event: Event) -> bool:
        """Check if an event matches a subscriber's filter.

        Args:
            subscriber: The subscriber to check
            event: The event to match

        Returns:
            True if the event matches
        """
        if event.event_type not in subscriber.event_types:
            return False

        if subscriber.filter:
            f = subscriber.filter
            if f.event_types and event.event_type not in f.event_types:
                return False
            if f.sources and event.source not in f.sources:
                return False
            if f.min_priority and event.priority.value < f.min_priority.value:
                return False
            if f.data_filters:
                for key, value in f.data_filters.items():
                    if key not in event.data or event.data[key] != value:
                        return False

        return True

    def _process_events(self, worker_id: int) -> None:
        """Background worker: process events from the queue.

        Args:
            worker_id: Worker thread identifier
        """
        logger.info(f"EventBus worker {worker_id} started")
        while self._pool_running:
            try:
                try:
                    _, event = self._event_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                with self._lock:
                    matching_subscribers = [
                        sub for sub in self._subscribers.values()
                        if self._match_subscriber(sub, event)
                    ]

                for subscriber in matching_subscribers:
                    if not self._pool_running:
                        break
                    self._deliver_with_retry(subscriber, event, worker_id)

                self._event_queue.task_done()

            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                time.sleep(0.1)

        logger.info(f"EventBus worker {worker_id} stopped")

    def _deliver_with_retry(self, subscriber: Subscriber, event: Event, worker_id: int) -> None:
        """Deliver an event to a subscriber with retry logic.

        Args:
            subscriber: The subscriber to deliver to
            event: The event to deliver
            worker_id: Worker thread ID
        """
        max_attempts = 1
        if event.delivery_guarantee == DeliveryGuarantee.AT_LEAST_ONCE:
            max_attempts = self.max_retries
        elif event.delivery_guarantee == DeliveryGuarantee.EXACTLY_ONCE:
            max_attempts = self.max_retries + 2

        for attempt in range(1, max_attempts + 1):
            start_time = time.time()
            try:
                subscriber.handler(event)
                elapsed_ms = (time.time() - start_time) * 1000

                self._record_delivery(event.event_id, subscriber.subscriber_id, "success", attempt)
                self._update_subscriber_stats(subscriber.subscriber_id, True, elapsed_ms)

                if attempt > 1:
                    logger.info(f"Event {event.event_id} delivered to {subscriber.subscriber_id} after {attempt} attempts")
                return

            except Exception as e:
                elapsed_ms = (time.time() - start_time) * 1000
                self._record_delivery(event.event_id, subscriber.subscriber_id, "failed", attempt, str(e))
                self._update_subscriber_stats(subscriber.subscriber_id, False, elapsed_ms)

                if attempt < max_attempts:
                    delay = self.retry_delay_seconds * (2 ** (attempt - 1))
                    logger.warning(
                        f"Delivery failed for event {event.event_id} to {subscriber.subscriber_id}"
                        f" (attempt {attempt}/{max_attempts}): {e}. Retrying in {delay}s"
                    )
                    time.sleep(delay)
                    event.retry_count = attempt
                else:
                    logger.error(
                        f"Event {event.event_id} permanently failed delivery to "
                        f"{subscriber.subscriber_id} after {max_attempts} attempts: {e}"
                    )

    def _record_delivery(
        self,
        event_id: str,
        subscriber_id: str,
        status: str,
        attempt: int,
        error: Optional[str] = None,
    ) -> None:
        """Record a delivery attempt.

        Args:
            event_id: Event ID
            subscriber_id: Subscriber ID
            status: Delivery status
            attempt: Attempt number
            error: Optional error message
        """
        record = DeliveryRecord(
            event_id=event_id,
            subscriber_id=subscriber_id,
            status=status,
            timestamp=datetime.now(),
            error=error,
            attempt=attempt,
        )
        with self._lock:
            self._delivery_records.append(record)
            if len(self._delivery_records) > self.max_delivery_records:
                self._delivery_records = self._delivery_records[-self.max_delivery_records:]

    def _update_subscriber_stats(self, subscriber_id: str, success: bool, elapsed_ms: float) -> None:
        """Update subscriber statistics.

        Args:
            subscriber_id: Subscriber ID
            success: Whether delivery was successful
            elapsed_ms: Processing time in milliseconds
        """
        with self._lock:
            stats = self._subscriber_stats.get(subscriber_id)
            if stats is None:
                return

            stats.total_events_received += 1
            stats.last_event_received = datetime.now()

            if success:
                stats.successful_deliveries += 1
                stats.last_success = datetime.now()
            else:
                stats.failed_deliveries += 1
                stats.last_failure = datetime.now()

            stats.total_processing_time_ms += elapsed_ms
            if stats.total_events_received > 0:
                stats.avg_processing_time_ms = (
                    stats.total_processing_time_ms / stats.total_events_received
                )

    def start(self) -> None:
        """Start the event bus processing pool."""
        with self._lock:
            if self._pool_running:
                logger.warning("EventBus already running")
                return

            self._pool_running = True
            self._pool_threads = []

            for i in range(self.thread_pool_size):
                thread = threading.Thread(
                    target=self._process_events,
                    args=(i,),
                    daemon=True,
                    name=f"eventbus-worker-{i}",
                )
                thread.start()
                self._pool_threads.append(thread)

            logger.info(f"EventBus started with {self.thread_pool_size} workers")

    def stop(self, wait_for_queue: bool = True) -> None:
        """Stop the event bus processing pool.

        Args:
            wait_for_queue: Wait for all queued events to be processed
        """
        if wait_for_queue:
            self._event_queue.join()

        self._pool_running = False

        for thread in self._pool_threads:
            thread.join(timeout=5)

        self._pool_threads.clear()
        logger.info("EventBus stopped")

    def get_event_history(
        self,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Event]:
        """Get event history with optional filters.

        Args:
            event_type: Filter by event type
            source: Filter by source
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum number of results

        Returns:
            List of matching events
        """
        with self._lock:
            events = list(self._history)

            if event_type:
                events = [e for e in events if e.event_type == event_type]
            if source:
                events = [e for e in events if e.source == source]
            if start_time:
                events = [e for e in events if e.timestamp >= start_time]
            if end_time:
                events = [e for e in events if e.timestamp <= end_time]

            return sorted(events, key=lambda e: e.timestamp, reverse=True)[:limit]

    def get_events_by_type(self, event_type: str, limit: int = 100) -> List[Event]:
        """Get recent events of a specific type.

        Args:
            event_type: Event type to filter by
            limit: Maximum number of results

        Returns:
            List of matching events
        """
        return self.get_event_history(event_type=event_type, limit=limit)

    def replay(
        self,
        event_ids: Optional[List[str]] = None,
        event_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """Replay events from history.

        Args:
            event_ids: Optional list of specific event IDs to replay
            event_type: Optional event type filter
            start_time: Optional start time filter
            end_time: Optional end time filter

        Returns:
            Number of events replayed
        """
        with self._lock:
            events_to_replay = list(self._history)

            if event_ids:
                events_to_replay = [e for e in events_to_replay if e.event_id in event_ids]
            if event_type:
                events_to_replay = [e for e in events_to_replay if e.event_type == event_type]
            if start_time:
                events_to_replay = [e for e in events_to_replay if e.timestamp >= start_time]
            if end_time:
                events_to_replay = [e for e in events_to_replay if e.timestamp <= end_time]

        count = 0
        self._replay_in_progress = True
        try:
            for event in events_to_replay:
                if not self._pool_running:
                    break
                self._event_queue.put((-EventPriority.HIGH.value, event))
                count += 1

            logger.info(f"Queued {count} events for replay")
        finally:
            self._replay_in_progress = False

        return count

    def get_delivery_records(
        self,
        event_id: Optional[str] = None,
        subscriber_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[DeliveryRecord]:
        """Get delivery attempt records.

        Args:
            event_id: Optional event ID filter
            subscriber_id: Optional subscriber ID filter
            status: Optional status filter
            limit: Maximum results

        Returns:
            List of DeliveryRecords
        """
        with self._lock:
            records = list(self._delivery_records)

            if event_id:
                records = [r for r in records if r.event_id == event_id]
            if subscriber_id:
                records = [r for r in records if r.subscriber_id == subscriber_id]
            if status:
                records = [r for r in records if r.status == status]

            return records[-limit:]

    def get_subscriber_statistics(self, subscriber_id: str) -> Optional[SubscriberStatistics]:
        """Get statistics for a specific subscriber.

        Args:
            subscriber_id: Subscriber ID

        Returns:
            SubscriberStatistics or None
        """
        with self._lock:
            return self._subscriber_stats.get(subscriber_id)

    def get_all_subscriber_statistics(self) -> Dict[str, SubscriberStatistics]:
        """Get statistics for all subscribers.

        Returns:
            Dictionary of subscriber IDs to SubscriberStatistics
        """
        with self._lock:
            return dict(self._subscriber_stats)

    def get_bus_statistics(self) -> Dict[str, Any]:
        """Get overall event bus statistics.

        Returns:
            Dictionary with bus statistics
        """
        with self._lock:
            event_type_counts: Dict[str, int] = defaultdict(int)
            source_counts: Dict[str, int] = defaultdict(int)
            total_events = len(self._history)

            for event in self._history:
                event_type_counts[event.event_type] += 1
                source_counts[event.source] += 1

            success_count = sum(
                1 for r in self._delivery_records if r.status == "success"
            )
            failed_count = sum(
                1 for r in self._delivery_records if r.status == "failed"
            )

            queue_size = self._event_queue.qsize()

            return {
                "total_events_published": total_events,
                "total_subscribers": len(self._subscribers),
                "queue_size": queue_size,
                "events_by_type": dict(event_type_counts),
                "events_by_source": dict(source_counts),
                "delivery_records": len(self._delivery_records),
                "successful_deliveries": success_count,
                "failed_deliveries": failed_count,
                "delivery_success_rate": (
                    (success_count / (success_count + failed_count) * 100)
                    if (success_count + failed_count) > 0 else 100.0
                ),
                "workers": self.thread_pool_size,
                "workers_alive": sum(1 for t in self._pool_threads if t.is_alive()),
                "pool_running": self._pool_running,
                "max_history_size": self.max_history_size,
                "max_retries": self.max_retries,
                "uptime_seconds": (datetime.now() - self._started_at).total_seconds(),
                "replay_in_progress": self._replay_in_progress,
            }

    def _prune_history(self) -> None:
        """Prune event history based on retention settings."""
        if len(self._history) <= self.max_history_size:
            return

        cutoff = datetime.now() - timedelta(hours=self.retention_hours)
        self._history = [
            e for e in self._history
            if e.timestamp >= cutoff
        ][-self.max_history_size:]

        record_cutoff = datetime.now() - timedelta(hours=self.retention_hours)
        self._delivery_records = [
            r for r in self._delivery_records
            if r.timestamp >= record_cutoff
        ][-self.max_delivery_records:]

    def clear_history(self) -> int:
        """Clear all event history.

        Returns:
            Number of events cleared
        """
        with self._lock:
            count = len(self._history)
            self._history.clear()
            self._delivery_records.clear()
            logger.info(f"Cleared {count} events from history")
            return count

    def clear_delivery_records(self) -> int:
        """Clear all delivery records.

        Returns:
            Number of records cleared
        """
        with self._lock:
            count = len(self._delivery_records)
            self._delivery_records.clear()
            logger.info(f"Cleared {count} delivery records")
            return count

    def get_event_by_id(self, event_id: str) -> Optional[Event]:
        """Get an event by its ID.

        Args:
            event_id: The event ID to find

        Returns:
            Event or None
        """
        with self._lock:
            for event in self._history:
                if event.event_id == event_id:
                    return event
            return None

    def wait_for_empty_queue(self, timeout: float = 30.0) -> bool:
        """Wait for the event queue to be empty.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            True if queue emptied, False on timeout
        """
        try:
            self._event_queue.join()
            return True
        except Exception:
            return False

    def get_queue_size(self) -> int:
        """Get the current event queue size.

        Returns:
            Number of events waiting in the queue
        """
        return self._event_queue.qsize()

    def has_subscriber(self, subscriber_id: str) -> bool:
        """Check if a subscriber exists.

        Args:
            subscriber_id: Subscriber ID

        Returns:
            True if subscriber exists
        """
        with self._lock:
            return subscriber_id in self._subscribers

    def get_subscribers_for_event(self, event_type: str) -> List[Subscriber]:
        """Get all subscribers that would receive an event type.

        Args:
            event_type: Event type to check

        Returns:
            List of matching subscribers
        """
        with self._lock:
            return [
                sub for sub in self._subscribers.values()
                if event_type in sub.event_types
            ]

    def get_event_type_count(self) -> int:
        """Get the number of unique event types seen.

        Returns:
            Count of unique event types
        """
        with self._lock:
            return len(set(e.event_type for e in self._history))

    def export_history_json(self, filepath: str) -> bool:
        """Export event history to a JSON file.

        Args:
            filepath: Output file path

        Returns:
            True if successful, False otherwise
        """
        try:
            with self._lock:
                data = [
                    {
                        "event_id": e.event_id,
                        "event_type": e.event_type,
                        "data": e.data,
                        "timestamp": e.timestamp.isoformat(),
                        "source": e.source,
                        "priority": e.priority.name,
                        "metadata": e.metadata,
                        "retry_count": e.retry_count,
                        "delivery_guarantee": e.delivery_guarantee.value,
                    }
                    for e in self._history
                ]

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)

            logger.info(f"Exported {len(data)} events to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export event history: {e}")
            return False

    def get_config(self) -> Dict[str, Any]:
        """Get current event bus configuration.

        Returns:
            Configuration dictionary
        """
        return {
            "max_history_size": self.max_history_size,
            "max_delivery_records": self.max_delivery_records,
            "retention_hours": self.retention_hours,
            "thread_pool_size": self.thread_pool_size,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "default_delivery_guarantee": self.default_delivery_guarantee.value,
            "pool_running": self._pool_running,
            "queue_size": self._event_queue.qsize(),
            "total_subscribers": len(self._subscribers),
        }
