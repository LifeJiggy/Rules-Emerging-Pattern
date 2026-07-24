"""
WebSocket handler for real-time event-based messaging including
validation results, alerts, and metrics streaming.
"""

import asyncio
import base64
import hashlib
import json
import logging
import time
import traceback
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import (
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)
from rules_emerging_pattern.models.validation import (
    ActionTaken,
    ValidationResult,
    Violation,
    ViolationType,
)
from rules_emerging_pattern.models.conflict import (
    ConflictSeverity,
    ConflictType,
    RuleConflict,
)

logger = logging.getLogger(__name__)


class WebSocketEventType(str, Enum):
    """Types of events that can be sent over WebSocket."""
    VALIDATION_RESULT = "validation_result"
    VALIDATION_STARTED = "validation_started"
    VALIDATION_COMPLETED = "validation_completed"
    ALERT_CREATED = "alert_created"
    ALERT_RESOLVED = "alert_resolved"
    RULE_CREATED = "rule_created"
    RULE_UPDATED = "rule_updated"
    RULE_DELETED = "rule_deleted"
    RULE_STATUS_CHANGED = "rule_status_changed"
    METRICS_UPDATE = "metrics_update"
    METRICS_THRESHOLD_BREACH = "metrics_threshold_breach"
    CONFLICT_DETECTED = "conflict_detected"
    CONFLICT_RESOLVED = "conflict_resolved"
    SYSTEM_HEALTH = "system_health"
    SYSTEM_ERROR = "system_error"
    CONNECTION_STATE = "connection_state"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    SUBSCRIPTION_CONFIRMED = "subscription_confirmed"
    UNSUBSCRIPTION_CONFIRMED = "unsubscription_confirmed"
    ERROR = "error"
    WELCOME = "welcome"
    RECONNECT = "reconnect"


class WebSocketCloseCode(int, Enum):
    """WebSocket close codes used by the handler."""
    NORMAL_CLOSURE = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    UNSUPPORTED_DATA = 1003
    INVALID_FRAME = 1007
    POLICY_VIOLATION = 1008
    MESSAGE_TOO_BIG = 1009
    INTERNAL_ERROR = 1011
    SERVICE_RESTART = 1012
    TRY_AGAIN_LATER = 1013
    BAD_GATEWAY = 1014
    TLS_HANDSHAKE_FAIL = 1015


class ConnectionState(str, Enum):
    """States for a WebSocket connection."""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    CLOSED = "closed"
    EXPIRED = "expired"


class SubscriptionFilterOperator(str, Enum):
    """Operators for subscription filters."""
    EQUALS = "eq"
    NOT_EQUALS = "neq"
    IN = "in"
    NOT_IN = "nin"
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    CONTAINS = "contains"
    REGEX = "regex"


@dataclass
class SubscriptionFilter:
    """Filter criteria for event subscriptions."""
    field: str
    operator: SubscriptionFilterOperator
    value: Any

    def matches(self, event_data: Dict[str, Any]) -> bool:
        actual = event_data.get(self.field)
        if self.operator == SubscriptionFilterOperator.EQUALS:
            return actual == self.value
        elif self.operator == SubscriptionFilterOperator.NOT_EQUALS:
            return actual != self.value
        elif self.operator == SubscriptionFilterOperator.IN:
            return actual in self.value if isinstance(self.value, list) else False
        elif self.operator == SubscriptionFilterOperator.NOT_IN:
            return actual not in self.value if isinstance(self.value, list) else True
        elif self.operator == SubscriptionFilterOperator.GREATER_THAN:
            if actual is None:
                return False
            try:
                return float(actual) > float(self.value)
            except (ValueError, TypeError):
                return False
        elif self.operator == SubscriptionFilterOperator.LESS_THAN:
            if actual is None:
                return False
            try:
                return float(actual) < float(self.value)
            except (ValueError, TypeError):
                return False
        elif self.operator == SubscriptionFilterOperator.CONTAINS:
            if actual is None:
                return False
            return str(self.value) in str(actual)
        elif self.operator == SubscriptionFilterOperator.REGEX:
            if actual is None:
                return False
            import re
            try:
                return bool(re.match(str(self.value), str(actual)))
            except re.error:
                return False
        return False


@dataclass
class Subscription:
    """Client subscription to specific event types."""
    subscription_id: str
    client_id: str
    event_types: Set[WebSocketEventType]
    filters: List[SubscriptionFilter] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    max_events: Optional[int] = None
    event_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def matches_event(self, event_type: WebSocketEventType, event_data: Dict[str, Any]) -> bool:
        if event_type not in self.event_types:
            return False
        if self.max_events and self.event_count >= self.max_events:
            return False
        for filter_ in self.filters:
            if not filter_.matches(event_data):
                return False
        return True

    def record_delivery(self) -> None:
        self.event_count += 1

    def is_exhausted(self) -> bool:
        return self.max_events is not None and self.event_count >= self.max_events


@dataclass
class ClientConnection:
    """Represents a connected WebSocket client."""
    client_id: str
    connection_state: ConnectionState = ConnectionState.CONNECTED
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    subscriptions: Dict[str, Subscription] = field(default_factory=dict)
    user_id: Optional[str] = None
    user_roles: List[str] = field(default_factory=list)
    reconnect_count: int = 0
    max_reconnects: int = 5
    reconnect_token: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    pending_events: deque = field(default_factory=lambda: deque(maxlen=1000))
    message_count: int = 0
    total_bytes_sent: int = 0

    @property
    def is_connected(self) -> bool:
        return self.connection_state == ConnectionState.CONNECTED

    @property
    def uptime_seconds(self) -> float:
        return (datetime.utcnow() - self.connected_at).total_seconds()

    def add_subscription(self, subscription: Subscription) -> None:
        self.subscriptions[subscription.subscription_id] = subscription

    def remove_subscription(self, subscription_id: str) -> Optional[Subscription]:
        return self.subscriptions.pop(subscription_id, None)

    def get_subscriptions_for_event(self, event_type: WebSocketEventType,
                                    event_data: Dict[str, Any]) -> List[Subscription]:
        matching = []
        for sub in self.subscriptions.values():
            if sub.matches_event(event_type, event_data):
                matching.append(sub)
        return matching

    def record_heartbeat(self) -> None:
        self.last_heartbeat = datetime.utcnow()
        self.last_activity = datetime.utcnow()

    def record_message(self, size_bytes: int) -> None:
        self.message_count += 1
        self.total_bytes_sent += size_bytes
        self.last_activity = datetime.utcnow()

    def check_heartbeat_timeout(self, timeout_seconds: int = 30) -> bool:
        elapsed = (datetime.utcnow() - self.last_heartbeat).total_seconds()
        return elapsed > timeout_seconds

    def generate_reconnect_token(self) -> str:
        raw = f"{self.client_id}:{uuid.uuid4().hex}:{int(time.time())}"
        self.reconnect_token = hashlib.sha256(raw.encode()).hexdigest()[:32]
        return self.reconnect_token

    def validate_reconnect_token(self, token: str) -> bool:
        return self.reconnect_token == token

    def can_reconnect(self) -> bool:
        return self.reconnect_count < self.max_reconnects


class MessageSerializer:
    """Serializes and deserializes WebSocket messages."""

    @staticmethod
    def serialize(event_type: WebSocketEventType, data: Any,
                  message_id: Optional[str] = None,
                  correlation_id: Optional[str] = None) -> str:
        msg_id = message_id or str(uuid.uuid4())
        message = {
            "type": "message",
            "event_type": event_type.value,
            "message_id": msg_id,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data,
        }
        if correlation_id:
            message["correlation_id"] = correlation_id
        return json.dumps(message, default=str)

    @staticmethod
    def serialize_batch(events: List[Tuple[WebSocketEventType, Any]]) -> str:
        messages = []
        for event_type, data in events:
            messages.append({
                "type": "message",
                "event_type": event_type.value,
                "message_id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat(),
                "data": data,
            })
        return json.dumps({"type": "batch", "messages": messages, "count": len(messages)}, default=str)

    @staticmethod
    def serialize_heartbeat(nonce: Optional[str] = None) -> str:
        return json.dumps({
            "type": "heartbeat",
            "nonce": nonce or str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat()
        })

    @staticmethod
    def serialize_heartbeat_ack(nonce: str) -> str:
        return json.dumps({
            "type": "heartbeat_ack",
            "nonce": nonce,
            "timestamp": datetime.utcnow().isoformat()
        })

    @staticmethod
    def serialize_welcome(client_id: str, reconnect_token: Optional[str] = None) -> str:
        data = {
            "type": "welcome",
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat(),
            "protocol_version": "1.0",
        }
        if reconnect_token:
            data["reconnect_token"] = reconnect_token
        return json.dumps(data)

    @staticmethod
    def serialize_error(code: str, message: str, correlation_id: Optional[str] = None) -> str:
        msg = {
            "type": "error",
            "code": code,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if correlation_id:
            msg["correlation_id"] = correlation_id
        return json.dumps(msg)

    @staticmethod
    def deserialize(message: str) -> Dict[str, Any]:
        try:
            return json.loads(message)
        except json.JSONDecodeError as e:
            return {
                "type": "parse_error",
                "error": f"Invalid JSON: {str(e)}",
                "raw": message[:500]
            }

    @staticmethod
    def extract_event_type(message: Dict[str, Any]) -> Optional[WebSocketEventType]:
        event_str = message.get("event_type") or message.get("type")
        if not event_str:
            return None
        try:
            return WebSocketEventType(event_str)
        except ValueError:
            return None


class ConnectionPool:
    """Manages WebSocket client connections."""

    def __init__(self, max_connections: int = 10000, heartbeat_timeout: int = 30) -> None:
        self._connections: Dict[str, ClientConnection] = {}
        self._max_connections = max_connections
        self._heartbeat_timeout = heartbeat_timeout
        self._user_to_connections: Dict[str, Set[str]] = defaultdict(set)
        self._connection_lock = asyncio.Lock()

    @property
    def total_connections(self) -> int:
        return len(self._connections)

    @property
    def active_connections(self) -> int:
        return sum(1 for c in self._connections.values() if c.is_connected)

    async def add_connection(self, connection: ClientConnection) -> bool:
        async with self._connection_lock:
            if len(self._connections) >= self._max_connections:
                logger.warning(f"Connection pool full: {self._max_connections}")
                return False
            self._connections[connection.client_id] = connection
            if connection.user_id:
                self._user_to_connections[connection.user_id].add(connection.client_id)
            logger.info(f"Connection added: {connection.client_id}")
            return True

    async def remove_connection(self, client_id: str) -> Optional[ClientConnection]:
        async with self._connection_lock:
            connection = self._connections.pop(client_id, None)
            if connection and connection.user_id:
                user_set = self._user_to_connections.get(connection.user_id)
                if user_set:
                    user_set.discard(client_id)
                    if not user_set:
                        del self._user_to_connections[connection.user_id]
            return connection

    def get_connection(self, client_id: str) -> Optional[ClientConnection]:
        return self._connections.get(client_id)

    def get_connections_by_user(self, user_id: str) -> List[ClientConnection]:
        client_ids = self._user_to_connections.get(user_id, set())
        return [self._connections[cid] for cid in client_ids if cid in self._connections]

    def get_all_connections(self) -> List[ClientConnection]:
        return list(self._connections.values())

    def get_connections_by_state(self, state: ConnectionState) -> List[ClientConnection]:
        return [c for c in self._connections.values() if c.connection_state == state]

    async def broadcast(self, event_type: WebSocketEventType, data: Any,
                        exclude_client_id: Optional[str] = None) -> int:
        sent_count = 0
        message = MessageSerializer.serialize(event_type, data)
        message_bytes = len(message.encode("utf-8"))
        for client_id, connection in list(self._connections.items()):
            if exclude_client_id and client_id == exclude_client_id:
                continue
            if connection.is_connected:
                connection.record_message(message_bytes)
                sent_count += 1
        logger.debug(f"Broadcast {event_type.value} to {sent_count} clients")
        return sent_count

    async def send_to_user(self, user_id: str, event_type: WebSocketEventType, data: Any) -> int:
        sent_count = 0
        message = MessageSerializer.serialize(event_type, data)
        message_bytes = len(message.encode("utf-8"))
        for connection in self.get_connections_by_user(user_id):
            if connection.is_connected:
                connection.record_message(message_bytes)
                sent_count += 1
        return sent_count

    async def send_to_connections(self, client_ids: List[str], event_type: WebSocketEventType, data: Any) -> int:
        sent_count = 0
        message = MessageSerializer.serialize(event_type, data)
        message_bytes = len(message.encode("utf-8"))
        for client_id in client_ids:
            connection = self._connections.get(client_id)
            if connection and connection.is_connected:
                connection.record_message(message_bytes)
                sent_count += 1
        return sent_count

    def has_connection(self, client_id: str) -> bool:
        return client_id in self._connections

    def get_connection_count_by_state(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for conn in self._connections.values():
            counts[conn.connection_state.value] += 1
        return dict(counts)

    def get_oldest_connection(self) -> Optional[ClientConnection]:
        if not self._connections:
            return None
        return min(self._connections.values(), key=lambda c: c.connected_at)

    def get_statistics(self) -> Dict[str, Any]:
        total = self.total_connections
        active = self.active_connections
        total_messages = sum(c.message_count for c in self._connections.values())
        total_bytes = sum(c.total_bytes_sent for c in self._connections.values())
        return {
            "total_connections": total,
            "active_connections": active,
            "disconnected_connections": total - active,
            "total_messages_sent": total_messages,
            "total_bytes_sent": total_bytes,
            "unique_users": len(self._user_to_connections),
            "heartbeat_timeout_seconds": self._heartbeat_timeout,
        }

    async def cleanup_stale_connections(self) -> int:
        removed = 0
        stale_ids = [
            cid for cid, conn in self._connections.items()
            if conn.check_heartbeat_timeout(self._heartbeat_timeout)
        ]
        for cid in stale_ids:
            conn = await self.remove_connection(cid)
            if conn:
                removed += 1
                logger.info(f"Removed stale connection: {cid}")
        return removed

    async def check_and_reconnect(self, client_id: str, token: str) -> Optional[ClientConnection]:
        connection = self._connections.get(client_id)
        if not connection:
            return None
        if not connection.validate_reconnect_token(token):
            return None
        if not connection.can_reconnect():
            return None
        connection.connection_state = ConnectionState.CONNECTED
        connection.reconnect_count += 1
        connection.last_heartbeat = datetime.utcnow()
        logger.info(f"Client reconnected: {client_id} (attempt {connection.reconnect_count})")
        return connection


class EventBus:
    """Internal event bus for dispatching WebSocket events."""

    def __init__(self) -> None:
        self._listeners: Dict[WebSocketEventType, List[Callable]] = defaultdict(list)
        self._global_listeners: List[Callable] = []
        self._event_history: deque = deque(maxlen=10000)
        self._rate_limits: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

    def subscribe(self, event_type: WebSocketEventType, listener: Callable) -> None:
        self._listeners[event_type].append(listener)

    def unsubscribe(self, event_type: WebSocketEventType, listener: Callable) -> bool:
        if listener in self._listeners[event_type]:
            self._listeners[event_type].remove(listener)
            return True
        return False

    def add_global_listener(self, listener: Callable) -> None:
        self._global_listeners.append(listener)

    def remove_global_listener(self, listener: Callable) -> bool:
        if listener in self._global_listeners:
            self._global_listeners.remove(listener)
            return True
        return False

    async def emit(self, event_type: WebSocketEventType, data: Any,
                   source: Optional[str] = None) -> int:
        event = {
            "event_type": event_type.value,
            "data": data,
            "source": source or "system",
            "timestamp": datetime.utcnow().isoformat(),
            "event_id": str(uuid.uuid4()),
        }
        self._event_history.append(event)
        tasks = []
        for listener in self._listeners.get(event_type, []):
            tasks.append(listener(event_type, data))
        for listener in self._global_listeners:
            tasks.append(listener(event_type, data))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        error_count = sum(1 for r in results if isinstance(r, Exception))
        if error_count:
            logger.error(f"{error_count} listener(s) failed for event {event_type.value}")
        return len(tasks) - error_count

    async def emit_batch(self, events: List[Tuple[WebSocketEventType, Any]],
                         source: Optional[str] = None) -> int:
        total = 0
        for event_type, data in events:
            count = await self.emit(event_type, data, source)
            total += count
        return total

    def get_event_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self._event_history)[-limit:]

    def get_event_count_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for event in self._event_history:
            counts[event["event_type"]] += 1
        return dict(counts)

    def clear_history(self) -> None:
        self._event_history.clear()

    def check_rate_limit(self, key: str, max_per_second: int = 10) -> bool:
        now = time.time()
        window = self._rate_limits[key]
        window.append(now)
        cutoff = now - 1.0
        recent = [t for t in window if t > cutoff]
        return len(recent) <= max_per_second


class WebSocketHandler:
    """
    WebSocket handler for real-time client communication.

    Manages WebSocket connections, event subscriptions, heartbeat/ping-pong,
    reconnection support, and message serialization. Supports event types
    for validation results, alerts, metrics, rule changes, and conflicts.
    """

    def __init__(self, connection_pool: Optional[ConnectionPool] = None,
                 heartbeat_interval: int = 15,
                 heartbeat_timeout: int = 30) -> None:
        self._connection_pool = connection_pool or ConnectionPool(
            max_connections=10000,
            heartbeat_timeout=heartbeat_timeout
        )
        self._event_bus = EventBus()
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    @property
    def connection_pool(self) -> ConnectionPool:
        return self._connection_pool

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    async def start(self) -> None:
        if self._running:
            logger.warning("WebSocketHandler already running")
            return
        self._running = True
        self._shutdown_event.clear()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("WebSocketHandler started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._shutdown_event.set()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        await self._disconnect_all_clients(WebSocketCloseCode.SERVICE_RESTART, "Server shutting down")
        logger.info("WebSocketHandler stopped")

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await self._send_heartbeats()
                await asyncio.sleep(self._heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
                await asyncio.sleep(5)

    async def _cleanup_loop(self) -> None:
        while self._running:
            try:
                removed = await self._connection_pool.cleanup_stale_connections()
                if removed:
                    logger.info(f"Cleaned up {removed} stale connections")
                await asyncio.sleep(self._heartbeat_timeout)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
                await asyncio.sleep(10)

    async def _send_heartbeats(self) -> None:
        message = MessageSerializer.serialize_heartbeat()
        message_bytes = len(message.encode("utf-8"))
        for connection in self._connection_pool.get_all_connections():
            if connection.is_connected:
                if connection.check_heartbeat_timeout(self._heartbeat_timeout):
                    connection.connection_state = ConnectionState.DISCONNECTED
                    logger.warning(f"Connection heartbeat timeout: {connection.client_id}")
                else:
                    connection.record_message(message_bytes)

    async def _disconnect_all_clients(self, code: WebSocketCloseCode, reason: str) -> None:
        for connection in self._connection_pool.get_all_connections():
            connection.connection_state = ConnectionState.CLOSED

    async def handle_connect(self, client_id: Optional[str] = None,
                             user_id: Optional[str] = None,
                             user_roles: Optional[List[str]] = None,
                             metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        connection = ClientConnection(
            client_id=client_id or str(uuid.uuid4()),
            user_id=user_id,
            user_roles=user_roles or [],
            metadata=metadata or {},
        )
        if client_id and self._connection_pool.has_connection(client_id):
            await self._connection_pool.remove_connection(client_id)
        success = await self._connection_pool.add_connection(connection)
        if not success:
            return {"success": False, "error": "Connection pool full"}
        reconnect_token = connection.generate_reconnect_token()
        welcome = MessageSerializer.serialize_welcome(connection.client_id, reconnect_token)
        await self._event_bus.emit(WebSocketEventType.CONNECTION_STATE, {
            "client_id": connection.client_id,
            "state": ConnectionState.CONNECTED.value,
            "user_id": user_id,
        })
        logger.info(f"Client connected: {connection.client_id}")
        return {
            "success": True,
            "client_id": connection.client_id,
            "reconnect_token": reconnect_token,
            "welcome_message": welcome,
        }

    async def handle_disconnect(self, client_id: str,
                                code: WebSocketCloseCode = WebSocketCloseCode.NORMAL_CLOSURE,
                                reason: str = "Client disconnected") -> bool:
        connection = await self._connection_pool.remove_connection(client_id)
        if connection:
            await self._event_bus.emit(WebSocketEventType.CONNECTION_STATE, {
                "client_id": client_id,
                "state": ConnectionState.DISCONNECTED.value,
                "reason": reason,
                "code": code.value,
            })
            logger.info(f"Client disconnected: {client_id} ({reason})")
            return True
        return False

    async def handle_reconnect(self, client_id: str, token: str,
                               metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        connection = await self._connection_pool.check_and_reconnect(client_id, token)
        if not connection:
            return {
                "success": False,
                "error": "Reconnection failed: invalid client_id or token"
            }
        if metadata:
            connection.metadata.update(metadata)
        new_token = connection.generate_reconnect_token()
        await self._event_bus.emit(WebSocketEventType.RECONNECT, {
            "client_id": client_id,
            "reconnect_count": connection.reconnect_count,
            "metadata": metadata,
        })
        logger.info(f"Client reconnected: {client_id}")
        return {
            "success": True,
            "client_id": client_id,
            "reconnect_token": new_token,
            "reconnect_count": connection.reconnect_count,
        }

    async def handle_message(self, client_id: str, raw_message: str) -> Optional[Dict[str, Any]]:
        connection = self._connection_pool.get_connection(client_id)
        if not connection:
            return {"type": "error", "code": "NOT_CONNECTED", "message": "Client not connected"}
        parsed = MessageSerializer.deserialize(raw_message)
        msg_type = parsed.get("type", "")
        if msg_type == "heartbeat_ack":
            connection.record_heartbeat()
            return None
        elif msg_type == "heartbeat":
            nonce = parsed.get("nonce")
            return {"type": "heartbeat_ack", "nonce": nonce}
        elif msg_type == "subscribe":
            return await self._handle_subscribe(connection, parsed)
        elif msg_type == "unsubscribe":
            return await self._handle_unsubscribe(connection, parsed)
        elif msg_type == "publish":
            return await self._handle_publish(connection, parsed)
        elif msg_type == "ping":
            return {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
        elif msg_type == "reconnect":
            return await self.handle_reconnect(
                parsed.get("client_id", client_id),
                parsed.get("token", ""),
                parsed.get("metadata")
            )
        else:
            event_type = MessageSerializer.extract_event_type(parsed)
            if event_type:
                await self._event_bus.emit(event_type, parsed.get("data", {}), source=client_id)
                return {"type": "ack", "event_type": event_type.value, "message_id": parsed.get("message_id")}
            return {"type": "error", "code": "UNKNOWN_TYPE", "message": f"Unknown message type: {msg_type}"}

    async def _handle_subscribe(self, connection: ClientConnection,
                                message: Dict[str, Any]) -> Dict[str, Any]:
        event_types_raw = message.get("event_types", [])
        if not event_types_raw:
            return {"type": "error", "code": "INVALID_REQUEST", "message": "event_types required"}
        event_types: Set[WebSocketEventType] = set()
        for et in event_types_raw:
            try:
                event_types.add(WebSocketEventType(et))
            except ValueError:
                return {"type": "error", "code": "INVALID_EVENT_TYPE", "message": f"Unknown event type: {et}"}
        filters_raw = message.get("filters", [])
        filters = []
        for f in filters_raw:
            try:
                filter_ = SubscriptionFilter(
                    field=f["field"],
                    operator=SubscriptionFilterOperator(f.get("operator", "eq")),
                    value=f["value"],
                )
                filters.append(filter_)
            except (KeyError, ValueError) as e:
                return {"type": "error", "code": "INVALID_FILTER", "message": str(e)}
        subscription = Subscription(
            subscription_id=message.get("subscription_id", str(uuid.uuid4())),
            client_id=connection.client_id,
            event_types=event_types,
            filters=filters,
            max_events=message.get("max_events"),
            metadata=message.get("metadata", {}),
        )
        connection.add_subscription(subscription)
        logger.info(f"Client {connection.client_id} subscribed to {[e.value for e in event_types]}")
        return {
            "type": "subscription_confirmed",
            "subscription_id": subscription.subscription_id,
            "event_types": [e.value for e in event_types],
            "filter_count": len(filters),
        }

    async def _handle_unsubscribe(self, connection: ClientConnection,
                                  message: Dict[str, Any]) -> Dict[str, Any]:
        subscription_id = message.get("subscription_id")
        if not subscription_id:
            return {"type": "error", "code": "INVALID_REQUEST", "message": "subscription_id required"}
        removed = connection.remove_subscription(subscription_id)
        if removed:
            return {"type": "unsubscription_confirmed", "subscription_id": subscription_id}
        return {"type": "error", "code": "NOT_FOUND", "message": f"Subscription not found: {subscription_id}"}

    async def _handle_publish(self, connection: ClientConnection,
                              message: Dict[str, Any]) -> Dict[str, Any]:
        event_type_raw = message.get("event_type")
        data = message.get("data", {})
        if not event_type_raw:
            return {"type": "error", "code": "INVALID_REQUEST", "message": "event_type required"}
        try:
            event_type = WebSocketEventType(event_type_raw)
        except ValueError:
            return {"type": "error", "code": "INVALID_EVENT_TYPE", "message": f"Unknown event type: {event_type_raw}"}
        await self._event_bus.emit(event_type, data, source=connection.client_id)
        return {
            "type": "publish_ack",
            "event_type": event_type_raw,
            "message_id": message.get("message_id"),
        }

    async def send_event(self, client_id: str, event_type: WebSocketEventType, data: Any) -> bool:
        connection = self._connection_pool.get_connection(client_id)
        if not connection or not connection.is_connected:
            return False
        message = MessageSerializer.serialize(event_type, data)
        connection.record_message(len(message.encode("utf-8")))
        return True

    async def broadcast_event(self, event_type: WebSocketEventType, data: Any) -> int:
        return await self._connection_pool.broadcast(event_type, data)

    async def emit_validation_result(self, result: ValidationResult) -> int:
        data = result.get_summary()
        await self._event_bus.emit(WebSocketEventType.VALIDATION_RESULT, data)
        return await self._connection_pool.broadcast(WebSocketEventType.VALIDATION_RESULT, data)

    async def emit_alert(self, alert_data: Dict[str, Any]) -> int:
        await self._event_bus.emit(WebSocketEventType.ALERT_CREATED, alert_data)
        return await self._connection_pool.broadcast(WebSocketEventType.ALERT_CREATED, alert_data)

    async def emit_rule_change(self, event_type: WebSocketEventType, rule: Rule) -> int:
        data = rule.to_dict()
        await self._event_bus.emit(event_type, data)
        return await self._connection_pool.broadcast(event_type, data)

    async def emit_metrics_update(self, metrics_data: Dict[str, Any]) -> int:
        await self._event_bus.emit(WebSocketEventType.METRICS_UPDATE, metrics_data)
        return await self._connection_pool.broadcast(WebSocketEventType.METRICS_UPDATE, metrics_data)

    async def emit_system_error(self, error_data: Dict[str, Any]) -> int:
        await self._event_bus.emit(WebSocketEventType.SYSTEM_ERROR, error_data)
        return await self._connection_pool.broadcast(WebSocketEventType.SYSTEM_ERROR, error_data)

    async def emit_conflict_detected(self, conflict: RuleConflict) -> int:
        data = conflict.to_dict()
        await self._event_bus.emit(WebSocketEventType.CONFLICT_DETECTED, data)
        return await self._connection_pool.broadcast(WebSocketEventType.CONFLICT_DETECTED, data)

    async def emit_connection_event(self, event_type: WebSocketEventType,
                                    data: Dict[str, Any]) -> int:
        return await self._connection_pool.broadcast(event_type, data)

    def get_client_info(self, client_id: str) -> Optional[Dict[str, Any]]:
        connection = self._connection_pool.get_connection(client_id)
        if not connection:
            return None
        return {
            "client_id": connection.client_id,
            "state": connection.connection_state.value,
            "connected_at": connection.connected_at.isoformat(),
            "last_heartbeat": connection.last_heartbeat.isoformat(),
            "last_activity": connection.last_activity.isoformat(),
            "user_id": connection.user_id,
            "user_roles": connection.user_roles,
            "reconnect_count": connection.reconnect_count,
            "subscription_count": len(connection.subscriptions),
            "message_count": connection.message_count,
            "total_bytes_sent": connection.total_bytes_sent,
            "uptime_seconds": connection.uptime_seconds,
        }

    def get_statistics(self) -> Dict[str, Any]:
        pool_stats = self._connection_pool.get_statistics()
        event_stats = self._event_bus.get_event_count_by_type()
        return {
            "connections": pool_stats,
            "events": event_stats,
            "heartbeat_interval": self._heartbeat_interval,
            "heartbeat_timeout": self._heartbeat_timeout,
            "running": self._running,
        }

    def get_subscriptions_summary(self) -> List[Dict[str, Any]]:
        summary = []
        for connection in self._connection_pool.get_all_connections():
            for sub in connection.subscriptions.values():
                summary.append({
                    "subscription_id": sub.subscription_id,
                    "client_id": sub.client_id,
                    "event_types": [e.value for e in sub.event_types],
                    "filter_count": len(sub.filters),
                    "event_count": sub.event_count,
                    "created_at": sub.created_at.isoformat(),
                    "is_exhausted": sub.is_exhausted(),
                })
        return summary

    async def send_pending_events(self, client_id: str) -> int:
        connection = self._connection_pool.get_connection(client_id)
        if not connection or not connection.is_connected:
            return 0
        sent = 0
        while connection.pending_events:
            event = connection.pending_events.popleft()
            success = await self.send_event(client_id, event["type"], event["data"])
            if success:
                sent += 1
        return sent
