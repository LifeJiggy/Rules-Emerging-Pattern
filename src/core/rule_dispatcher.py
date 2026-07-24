"""
Rule dispatcher that routes evaluation requests to appropriate engines.
"""

import asyncio
import heapq
import json
import logging
import random
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
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
    Suggestion,
    ValidationResult,
    Violation,
    ViolationType,
)
from rules_emerging_pattern.models.conflict import (
    ConflictResolution,
    ConflictType,
    ResolutionStrategy,
    RuleConflict,
)

from .engine_config import EngineConfig, ConfigEnvironment

logger = logging.getLogger(__name__)


class DispatchStrategy(str, Enum):
    """Strategies for dispatching requests to engines."""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    RANDOM = "random"
    PRIORITY = "priority"
    WEIGHTED = "weighted"
    FASTEST_RESPONSE = "fastest_response"


class DispatchPriority(int, Enum):
    """Priority levels for dispatch requests."""
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    BACKGROUND = 4


class EngineState(str, Enum):
    """State of an engine instance."""
    ACTIVE = "active"
    DEGRADED = "degraded"
    CIRCUIT_OPEN = "circuit_open"
    CIRCUIT_HALF_OPEN = "circuit_half_open"
    UNREACHABLE = "unreachable"
    DISABLED = "disabled"


class CircuitBreakerState(str, Enum):
    """State of a circuit breaker."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class DispatchError(Exception):
    """Raised when dispatch fails."""
    pass


class EngineUnavailableError(DispatchError):
    """Raised when no engine is available."""
    pass


class DispatchTimeoutError(DispatchError):
    """Raised when dispatch times out."""
    pass


class QueueFullError(DispatchError):
    """Raised when the dispatch queue is full."""
    pass


@dataclass
class DispatchRequest:
    """A request queued for dispatch."""

    request: RuleEvaluationRequest
    priority: int = DispatchPriority.MEDIUM.value
    created_at: float = field(default_factory=time.time)
    timeout_ms: int = 5000
    retry_count: int = 0
    max_retries: int = 3
    request_id: str = ""
    callback: Optional[Callable[[ValidationResult], None]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.request_id:
            self.request_id = f"disp_{int(time.time() * 1000)}_{random.randint(0, 9999)}"

    def is_expired(self) -> bool:
        elapsed_ms = (time.time() - self.created_at) * 1000
        return elapsed_ms > self.timeout_ms

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def time_remaining_ms(self) -> float:
        elapsed_ms = (time.time() - self.created_at) * 1000
        return max(0.0, self.timeout_ms - elapsed_ms)

    def __lt__(self, other: "DispatchRequest") -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


@dataclass
class DispatchResult:
    """Result of a dispatch operation."""

    success: bool
    request_id: str
    engine_id: str
    result: Optional[ValidationResult] = None
    error: Optional[str] = None
    dispatch_time_ms: float = 0.0
    queue_wait_ms: float = 0.0
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "request_id": self.request_id,
            "engine_id": self.engine_id,
            "error": self.error,
            "dispatch_time_ms": round(self.dispatch_time_ms, 2),
            "queue_wait_ms": round(self.queue_wait_ms, 2),
            "retry_count": self.retry_count,
        }


class CircuitBreaker:
    """Circuit breaker for failing engine instances."""

    def __init__(
        self,
        threshold: int = 5,
        recovery_timeout_ms: int = 30000,
        half_open_max_requests: int = 3,
    ):
        self.threshold = threshold
        self.recovery_timeout_ms = recovery_timeout_ms
        self.half_open_max_requests = half_open_max_requests
        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_time: float = 0.0
        self._last_open_time: float = 0.0
        self._half_open_requests: int = 0
        self._lock = asyncio.Lock()
        self._failure_history: List[Dict[str, Any]] = []
        self._state_change_callbacks: List[Callable] = []

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    def add_state_change_callback(self, callback: Callable) -> None:
        self._state_change_callbacks.append(callback)

    async def record_success(self) -> None:
        async with self._lock:
            self._success_count += 1
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._half_open_requests -= 1
                if self._success_count >= self.half_open_max_requests:
                    self._set_state(CircuitBreakerState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitBreakerState.CLOSED:
                self._failure_count = max(0, self._failure_count - 1)

    async def record_failure(self, error: str = "") -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            self._failure_history.append({
                "timestamp": time.time(),
                "error": error,
                "failure_count": self._failure_count,
                "state": self._state.value,
            })
            if len(self._failure_history) > 100:
                self._failure_history = self._failure_history[-100:]
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._set_state(CircuitBreakerState.OPEN)
                self._last_open_time = time.time()
                self._half_open_requests = 0
            elif self._state == CircuitBreakerState.CLOSED and self._failure_count >= self.threshold:
                self._set_state(CircuitBreakerState.OPEN)
                self._last_open_time = time.time()

    async def allow_request(self) -> bool:
        async with self._lock:
            if self._state == CircuitBreakerState.CLOSED:
                return True
            if self._state == CircuitBreakerState.OPEN:
                recovery_elapsed_ms = (time.time() - self._last_open_time) * 1000
                if recovery_elapsed_ms >= self.recovery_timeout_ms:
                    self._set_state(CircuitBreakerState.HALF_OPEN)
                    self._half_open_requests = 0
                    return True
                return False
            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_requests < self.half_open_max_requests:
                    self._half_open_requests += 1
                    return True
                return False
            return False

    def _set_state(self, new_state: CircuitBreakerState) -> None:
        old_state = self._state
        self._state = new_state
        logger.info(f"CircuitBreaker: {old_state.value} -> {new_state.value}")
        for callback in self._state_change_callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                logger.error(f"State change callback error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "threshold": self.threshold,
            "recovery_timeout_ms": self.recovery_timeout_ms,
            "half_open_max_requests": self.half_open_max_requests,
            "last_failure_time": datetime.fromtimestamp(self._last_failure_time).isoformat() if self._last_failure_time else None,
            "last_open_time": datetime.fromtimestamp(self._last_open_time).isoformat() if self._last_open_time else None,
            "recent_failures": self._failure_history[-10:],
        }

    def reset(self) -> None:
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._last_open_time = 0.0
        self._half_open_requests = 0
        logger.info("CircuitBreaker reset to CLOSED")


class EngineInstance:
    """Wrapper for an engine instance with health tracking."""

    def __init__(
        self,
        engine_id: str,
        engine: Any,
        weight: float = 1.0,
        max_concurrent: int = 10,
        tags: Optional[Dict[str, str]] = None,
    ):
        self.engine_id = engine_id
        self.engine = engine
        self.weight = weight
        self.max_concurrent = max_concurrent
        self.tags = tags or {}
        self.state: EngineState = EngineState.ACTIVE
        self.circuit_breaker = CircuitBreaker()
        self._current_load: int = 0
        self._total_dispatched: int = 0
        self._total_errors: int = 0
        self._total_time_ms: float = 0.0
        self._average_time_ms: float = 0.0
        self._response_times: List[float] = []
        self._last_health_check: float = 0.0
        self._last_health_status: bool = True
        self._lock = asyncio.Lock()
        self._health_check_fn: Optional[Callable[[], bool]] = None

    @property
    def load(self) -> float:
        return self._current_load / self.max_concurrent if self.max_concurrent > 0 else 1.0

    def set_health_check(self, fn: Callable[[], bool]) -> None:
        self._health_check_fn = fn

    async def can_accept(self) -> bool:
        if self.state in (EngineState.DISABLED, EngineState.UNREACHABLE):
            return False
        if self._current_load >= self.max_concurrent:
            return False
        return await self.circuit_breaker.allow_request()

    async def dispatch(self, request: RuleEvaluationRequest, timeout_ms: int = 5000) -> ValidationResult:
        async with self._lock:
            self._current_load += 1
            self._total_dispatched += 1
        start_time = time.time()
        try:
            if hasattr(self.engine, "evaluate") and asyncio.iscoroutinefunction(self.engine.evaluate):
                result = await asyncio.wait_for(
                    self.engine.evaluate(request),
                    timeout=timeout_ms / 1000.0,
                )
            elif hasattr(self.engine, "evaluate"):
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self.engine.evaluate, request
                )
            else:
                raise DispatchError(f"Engine {self.engine_id} has no evaluate method")
            elapsed_ms = (time.time() - start_time) * 1000
            self._total_time_ms += elapsed_ms
            self._response_times.append(elapsed_ms)
            if len(self._response_times) > 100:
                self._response_times = self._response_times[-100:]
            self._average_time_ms = self._total_time_ms / self._total_dispatched
            await self.circuit_breaker.record_success()
            return result
        except asyncio.TimeoutError:
            elapsed_ms = (time.time() - start_time) * 1000
            self._total_errors += 1
            await self.circuit_breaker.record_failure("timeout")
            raise DispatchTimeoutError(f"Engine {self.engine_id} timed out after {elapsed_ms:.0f}ms")
        except Exception as e:
            self._total_errors += 1
            await self.circuit_breaker.record_failure(str(e))
            raise DispatchError(f"Engine {self.engine_id} failed: {e}")
        finally:
            async with self._lock:
                self._current_load = max(0, self._current_load - 1)

    async def health_check(self) -> bool:
        now = time.time()
        if now - self._last_health_check < 5.0:
            return self._last_health_status
        self._last_health_check = now
        try:
            if self._health_check_fn:
                status = self._health_check_fn()
            elif hasattr(self.engine, "health_check"):
                if asyncio.iscoroutinefunction(self.engine.health_check):
                    status = await self.engine.health_check()
                else:
                    status = self.engine.health_check()
            else:
                status = True
            self._last_health_status = bool(status)
            if isinstance(status, dict):
                self._last_health_status = status.get("status") == "healthy"
        except Exception as e:
            logger.warning(f"Health check failed for engine {self.engine_id}: {e}")
            self._last_health_status = False
        return self._last_health_status

    def get_stats(self) -> Dict[str, Any]:
        avg_ms = round(self._average_time_ms, 2)
        p50 = 0.0
        p95 = 0.0
        p99 = 0.0
        if self._response_times:
            sorted_times = sorted(self._response_times)
            length = len(sorted_times)
            p50 = sorted_times[length // 2]
            p95 = sorted_times[int(length * 0.95)]
            p99 = sorted_times[int(length * 0.99)]
        return {
            "engine_id": self.engine_id,
            "state": self.state.value,
            "weight": self.weight,
            "current_load": self._current_load,
            "max_concurrent": self.max_concurrent,
            "load_ratio": round(self.load, 3),
            "total_dispatched": self._total_dispatched,
            "total_errors": self._total_errors,
            "error_rate": round((self._total_errors / max(self._total_dispatched, 1)) * 100, 2),
            "average_time_ms": avg_ms,
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "circuit_breaker": self.circuit_breaker.get_stats(),
            "tags": self.tags,
            "last_health_status": self._last_health_status,
        }


@dataclass
class DispatchMetrics:
    """Metrics for dispatch operations."""

    total_dispatched: int = 0
    successful_dispatches: int = 0
    failed_dispatches: int = 0
    timed_out_dispatches: int = 0
    queued_requests: int = 0
    dropped_requests: int = 0
    retried_requests: int = 0
    average_dispatch_time_ms: float = 0.0
    average_queue_wait_ms: float = 0.0
    total_dispatch_time_ms: float = 0.0
    busiest_engine: str = ""
    start_time: float = field(default_factory=time.time)

    def record_success(self, dispatch_time_ms: float, queue_wait_ms: float = 0.0) -> None:
        self.total_dispatched += 1
        self.successful_dispatches += 1
        self.total_dispatch_time_ms += dispatch_time_ms
        if self.total_dispatched > 0:
            self.average_dispatch_time_ms = self.total_dispatch_time_ms / self.total_dispatched
        if queue_wait_ms > 0:
            self.average_queue_wait_ms = (
                (self.average_queue_wait_ms * (self.total_dispatched - 1) + queue_wait_ms)
                / self.total_dispatched
            )

    def record_failure(self) -> None:
        self.total_dispatched += 1
        self.failed_dispatches += 1

    def record_timeout(self) -> None:
        self.total_dispatched += 1
        self.timed_out_dispatches += 1

    def record_retry(self) -> None:
        self.retried_requests += 1

    def to_dict(self) -> Dict[str, Any]:
        uptime = time.time() - self.start_time
        return {
            "total_dispatched": self.total_dispatched,
            "successful_dispatches": self.successful_dispatches,
            "failed_dispatches": self.failed_dispatches,
            "timed_out_dispatches": self.timed_out_dispatches,
            "queued_requests": self.queued_requests,
            "dropped_requests": self.dropped_requests,
            "retried_requests": self.retried_requests,
            "average_dispatch_time_ms": round(self.average_dispatch_time_ms, 2),
            "average_queue_wait_ms": round(self.average_queue_wait_ms, 2),
            "success_rate": round(
                (self.successful_dispatches / max(self.total_dispatched, 1)) * 100, 2
            ),
            "uptime_seconds": round(uptime, 1),
            "dispatches_per_second": round(self.total_dispatched / max(uptime, 1), 2),
        }


class PriorityQueue:
    """Priority queue for dispatch requests."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._heap: List[Tuple[int, float, int, DispatchRequest]] = []
        self._counter: int = 0
        self._lock = asyncio.Lock()
        self._dropped_count: int = 0

    async def push(self, request: DispatchRequest) -> bool:
        async with self._lock:
            if len(self._heap) >= self.max_size:
                self._dropped_count += 1
                return False
            self._counter += 1
            heapq.heappush(self._heap, (
                request.priority,
                request.created_at,
                self._counter,
                request,
            ))
            return True

    async def pop(self) -> Optional[DispatchRequest]:
        async with self._lock:
            while self._heap:
                priority, created_at, counter, request = heapq.heappop(self._heap)
                if request.is_expired():
                    self._dropped_count += 1
                    continue
                return request
            return None

    async def peek(self) -> Optional[DispatchRequest]:
        async with self._lock:
            while self._heap:
                priority, created_at, counter, request = self._heap[0]
                if request.is_expired():
                    heapq.heappop(self._heap)
                    self._dropped_count += 1
                    continue
                return request
            return None

    async def size(self) -> int:
        async with self._lock:
            return len(self._heap)

    async def remove_expired(self) -> int:
        removed = 0
        async with self._lock:
            valid_items = []
            for item in self._heap:
                if not item[3].is_expired():
                    valid_items.append(item)
                else:
                    removed += 1
            self._heap = valid_items
            heapq.heapify(self._heap)
            self._dropped_count += removed
        return removed

    def get_stats(self) -> Dict[str, Any]:
        return {
            "current_size": len(self._heap),
            "max_size": self.max_size,
            "dropped_count": self._dropped_count,
            "usage_percent": round((len(self._heap) / max(self.max_size, 1)) * 100, 2),
        }


class RuleDispatcher:
    """Dispatches rule evaluation requests to appropriate engines with load balancing."""

    def __init__(
        self,
        config: Optional[EngineConfig] = None,
        engines: Optional[Dict[str, Any]] = None,
    ):
        self.config = config or EngineConfig()
        self._engine_instances: Dict[str, EngineInstance] = {}
        self._queue = PriorityQueue(max_size=self.config.get_int("dispatcher.queue_size", 1000))
        self._strategy = DispatchStrategy(
            self.config.get("dispatcher.strategy", "round_robin")
        )
        self._metrics = DispatchMetrics()
        self._rr_index: int = 0
        self._running = False
        self._dispatch_tasks: Set[asyncio.Task] = set()
        self._health_check_task: Optional[asyncio.Task] = None
        self._pre_dispatch_hooks: List[Callable] = []
        self._post_dispatch_hooks: List[Callable] = []
        self._lock = asyncio.Lock()
        self._dispatch_history: deque = deque(maxlen=1000)

        if engines:
            for engine_id, engine in engines.items():
                self.register_engine(engine_id, engine)

        logger.info(
            f"RuleDispatcher initialized with strategy={self._strategy.value}, "
            f"engines={len(self._engine_instances)}"
        )

    def register_engine(
        self,
        engine_id: str,
        engine: Any,
        weight: float = 1.0,
        max_concurrent: int = 10,
        tags: Optional[Dict[str, str]] = None,
    ) -> EngineInstance:
        if engine_id in self._engine_instances:
            logger.warning(f"Engine {engine_id} already registered, overwriting")
        instance = EngineInstance(engine_id, engine, weight, max_concurrent, tags)
        self._engine_instances[engine_id] = instance
        logger.info(f"Engine {engine_id} registered (weight={weight}, max_concurrent={max_concurrent})")
        return instance

    def unregister_engine(self, engine_id: str) -> bool:
        if engine_id in self._engine_instances:
            del self._engine_instances[engine_id]
            logger.info(f"Engine {engine_id} unregistered")
            return True
        return False

    def set_engine_state(self, engine_id: str, state: EngineState) -> bool:
        instance = self._engine_instances.get(engine_id)
        if instance:
            instance.state = state
            logger.info(f"Engine {engine_id} state set to {state.value}")
            return True
        return False

    def set_strategy(self, strategy: DispatchStrategy) -> None:
        self._strategy = strategy
        logger.info(f"Dispatch strategy set to {strategy.value}")

    def add_pre_dispatch_hook(self, hook: Callable[[RuleEvaluationRequest], RuleEvaluationRequest]) -> None:
        self._pre_dispatch_hooks.append(hook)

    def add_post_dispatch_hook(self, hook: Callable[[ValidationResult], ValidationResult]) -> None:
        self._post_dispatch_hooks.append(hook)

    async def dispatch(
        self,
        request: RuleEvaluationRequest,
        priority: int = DispatchPriority.MEDIUM.value,
        timeout_ms: Optional[int] = None,
    ) -> ValidationResult:
        dispatch_request = DispatchRequest(
            request=request,
            priority=priority,
            timeout_ms=timeout_ms or self.config.get_int("dispatcher.queue_timeout_ms", 5000),
        )
        return await self._dispatch_internal(dispatch_request)

    async def dispatch_async(
        self,
        request: RuleEvaluationRequest,
        priority: int = DispatchPriority.MEDIUM.value,
        callback: Optional[Callable[[ValidationResult], None]] = None,
    ) -> str:
        dispatch_request = DispatchRequest(
            request=request,
            priority=priority,
            callback=callback,
        )
        queued = await self._queue.push(dispatch_request)
        if not queued:
            raise QueueFullError("Dispatch queue is full")
        self._metrics.queued_requests += 1
        return dispatch_request.request_id

    async def dispatch_batch(
        self,
        requests: List[RuleEvaluationRequest],
        priority: int = DispatchPriority.MEDIUM.value,
    ) -> List[ValidationResult]:
        results: List[ValidationResult] = []
        for req in requests:
            try:
                result = await self.dispatch(req, priority=priority)
                results.append(result)
            except Exception as e:
                logger.error(f"Batch dispatch failed: {e}")
                results.append(ValidationResult(
                    valid=False,
                    total_score=0.0,
                    confidence=0.0,
                ))
        return results

    async def dispatch_to_engine(
        self,
        engine_id: str,
        request: RuleEvaluationRequest,
        timeout_ms: Optional[int] = None,
    ) -> ValidationResult:
        instance = self._engine_instances.get(engine_id)
        if not instance:
            raise EngineUnavailableError(f"Engine {engine_id} not found")
        if instance.state == EngineState.DISABLED:
            raise EngineUnavailableError(f"Engine {engine_id} is disabled")
        return await instance.dispatch(
            request,
            timeout_ms=timeout_ms or self.config.get_int("dispatcher.queue_timeout_ms", 5000),
        )

    async def _dispatch_internal(self, dispatch_request: DispatchRequest) -> ValidationResult:
        for hook in self._pre_dispatch_hooks:
            try:
                dispatch_request.request = hook(dispatch_request.request)
            except Exception as e:
                logger.error(f"Pre-dispatch hook failed: {e}")

        last_error: Optional[str] = None
        start_time = time.time()

        while dispatch_request.can_retry():
            if dispatch_request.is_expired():
                self._metrics.record_timeout()
                raise DispatchTimeoutError(f"Dispatch timed out after {dispatch_request.timeout_ms}ms")

            engine_instance = await self._select_engine()
            if not engine_instance:
                await asyncio.sleep(0.1)
                last_error = "No available engines"
                continue

            try:
                result = await engine_instance.dispatch(
                    dispatch_request.request,
                    timeout_ms=int(dispatch_request.time_remaining_ms()),
                )
                elapsed_ms = (time.time() - start_time) * 1000
                self._metrics.record_success(elapsed_ms)
                for hook in self._post_dispatch_hooks:
                    try:
                        result = hook(result)
                    except Exception as e:
                        logger.error(f"Post-dispatch hook failed: {e}")
                self._dispatch_history.append({
                    "request_id": dispatch_request.request_id,
                    "engine_id": engine_instance.engine_id,
                    "success": True,
                    "time_ms": elapsed_ms,
                    "timestamp": time.time(),
                })
                return result

            except (DispatchTimeoutError, DispatchError) as e:
                last_error = str(e)
                dispatch_request.retry_count += 1
                self._metrics.record_retry()
                logger.warning(f"Dispatch retry {dispatch_request.retry_count}: {e}")
                await asyncio.sleep(0.1 * dispatch_request.retry_count)

        elapsed_ms = (time.time() - start_time) * 1000
        self._metrics.record_failure()
        self._dispatch_history.append({
            "request_id": dispatch_request.request_id,
            "engine_id": "none",
            "success": False,
            "error": last_error,
            "time_ms": elapsed_ms,
            "timestamp": time.time(),
        })
        raise EngineUnavailableError(f"All engines failed: {last_error}")

    async def _select_engine(self) -> Optional[EngineInstance]:
        available = []
        for instance in self._engine_instances.values():
            if await instance.can_accept():
                available.append(instance)
        if not available:
            return None

        if self._strategy == DispatchStrategy.ROUND_ROBIN:
            async with self._lock:
                idx = self._rr_index % len(available)
                self._rr_index += 1
                return available[idx]

        elif self._strategy == DispatchStrategy.LEAST_LOADED:
            return min(available, key=lambda e: e.load)

        elif self._strategy == DispatchStrategy.RANDOM:
            return random.choice(available)

        elif self._strategy == DispatchStrategy.PRIORITY:
            return available[0]

        elif self._strategy == DispatchStrategy.WEIGHTED:
            total_weight = sum(e.weight for e in available)
            r = random.uniform(0, total_weight)
            cumulative = 0.0
            for e in available:
                cumulative += e.weight
                if r <= cumulative:
                    return e
            return available[-1]

        elif self._strategy == DispatchStrategy.FASTEST_RESPONSE:
            return min(available, key=lambda e: e._average_time_ms if e._average_time_ms > 0 else float("inf"))

        return available[0]

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        self._dispatch_tasks.add(asyncio.create_task(self._queue_processor()))
        logger.info("RuleDispatcher started")

    async def stop(self) -> None:
        self._running = False
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        for task in self._dispatch_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._dispatch_tasks.clear()
        logger.info("RuleDispatcher stopped")

    async def _queue_processor(self) -> None:
        while self._running:
            try:
                request = await self._queue.pop()
                if request:
                    try:
                        result = await self._dispatch_internal(request)
                        if request.callback:
                            try:
                                request.callback(result)
                            except Exception as e:
                                logger.error(f"Dispatch callback failed: {e}")
                    except Exception as e:
                        logger.error(f"Queue dispatch failed: {e}")
                        if request.callback:
                            try:
                                request.callback(ValidationResult(
                                    valid=False,
                                    total_score=0.0,
                                    confidence=0.0,
                                ))
                            except Exception:
                                pass
                else:
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue processor error: {e}")
                await asyncio.sleep(0.5)

    async def _health_check_loop(self) -> None:
        interval = self.config.get_int("dispatcher.health_check_interval", 30)
        while self._running:
            try:
                await asyncio.sleep(interval)
                for instance in self._engine_instances.values():
                    healthy = await instance.health_check()
                    if not healthy and instance.state == EngineState.ACTIVE:
                        instance.state = EngineState.DEGRADED
                        logger.warning(f"Engine {instance.engine_id} marked as DEGRADED")
                    elif healthy and instance.state == EngineState.DEGRADED:
                        instance.state = EngineState.ACTIVE
                        logger.info(f"Engine {instance.engine_id} restored to ACTIVE")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")

    async def cancel_request(self, request_id: str) -> bool:
        return False

    def get_engine_stats(self, engine_id: Optional[str] = None) -> Dict[str, Any]:
        if engine_id:
            instance = self._engine_instances.get(engine_id)
            if instance:
                return instance.get_stats()
            return {"error": f"Engine {engine_id} not found"}
        return {
            eid: inst.get_stats()
            for eid, inst in self._engine_instances.items()
        }

    def get_metrics(self) -> Dict[str, Any]:
        metrics = self._metrics.to_dict()
        metrics["queue"] = self._queue.get_stats()
        metrics["strategy"] = self._strategy.value
        metrics["engine_count"] = len(self._engine_instances)
        metrics["running"] = self._running
        return metrics

    def get_dispatch_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        history = list(self._dispatch_history)
        return history[-limit:]

    def get_engine_by_id(self, engine_id: str) -> Optional[EngineInstance]:
        return self._engine_instances.get(engine_id)

    def get_engines_by_tag(self, key: str, value: str) -> List[EngineInstance]:
        return [
            inst for inst in self._engine_instances.values()
            if inst.tags.get(key) == value
        ]

    def get_engines_by_state(self, state: EngineState) -> List[EngineInstance]:
        return [
            inst for inst in self._engine_instances.values()
            if inst.state == state
        ]

    async def reset_circuit_breaker(self, engine_id: str) -> bool:
        instance = self._engine_instances.get(engine_id)
        if instance:
            instance.circuit_breaker.reset()
            return True
        return False

    async def health_check(self) -> Dict[str, Any]:
        status = "healthy"
        issues = []
        details: Dict[str, Any] = {}
        healthy_count = 0
        degraded_count = 0
        for eid, inst in self._engine_instances.items():
            healthy = await inst.health_check()
            if healthy:
                healthy_count += 1
            else:
                degraded_count += 1
            details[eid] = {
                "state": inst.state.value,
                "load": inst.load,
                "healthy": healthy,
            }
        if degraded_count > 0:
            status = "degraded"
            issues.append(f"{degraded_count} engine(s) unhealthy")
        if not self._engine_instances:
            status = "degraded"
            issues.append("No engines registered")
        queue_size = await self._queue.size()
        if queue_size > self._queue.max_size * 0.9:
            issues.append(f"Queue near capacity ({queue_size}/{self._queue.max_size})")
        return {
            "status": status,
            "dispatcher": "RuleDispatcher",
            "issues": issues,
            "details": details,
            "engine_count": len(self._engine_instances),
            "healthy_count": healthy_count,
            "degraded_count": degraded_count,
            "queue_size": queue_size,
            "metrics": self._metrics.to_dict(),
            "strategy": self._strategy.value,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def to_prometheus(self) -> str:
        metrics = self._metrics
        lines = [
            "# HELP rule_dispatcher_total_dispatched Total dispatch count",
            "# TYPE rule_dispatcher_total_dispatched counter",
            f"rule_dispatcher_total_dispatched {metrics.total_dispatched}",
            "# HELP rule_dispatcher_successful_dispatches Successful dispatches",
            "# TYPE rule_dispatcher_successful_dispatches counter",
            f"rule_dispatcher_successful_dispatches {metrics.successful_dispatches}",
            "# HELP rule_dispatcher_failed_dispatches Failed dispatches",
            "# TYPE rule_dispatcher_failed_dispatches counter",
            f"rule_dispatcher_failed_dispatches {metrics.failed_dispatches}",
            "# HELP rule_dispatcher_timed_out_dispatches Timed out dispatches",
            "# TYPE rule_dispatcher_timed_out_dispatches counter",
            f"rule_dispatcher_timed_out_dispatches {metrics.timed_out_dispatches}",
            "# HELP rule_dispatcher_queued_requests Currently queued",
            "# TYPE rule_dispatcher_queued_requests gauge",
            f"rule_dispatcher_queued_requests {metrics.queued_requests}",
            "# HELP rule_dispatcher_retried_requests Retried dispatches",
            "# TYPE rule_dispatcher_retried_requests counter",
            f"rule_dispatcher_retried_requests {metrics.retried_requests}",
            "# HELP rule_dispatcher_average_dispatch_time_ms Average dispatch time",
            "# TYPE rule_dispatcher_average_dispatch_time_ms gauge",
            f"rule_dispatcher_average_dispatch_time_ms {metrics.average_dispatch_time_ms}",
        ]
        for eid, inst in self._engine_instances.items():
            stats = inst.get_stats()
            lines.extend([
                f'rule_dispatcher_engine_state{{engine_id="{eid}"}} {1 if stats["state"] == "active" else 0}',
                f'rule_dispatcher_engine_load{{engine_id="{eid}"}} {stats["load_ratio"]}',
                f'rule_dispatcher_engine_errors{{engine_id="{eid}"}} {stats["total_errors"]}',
            ])
        return "\n".join(lines)
