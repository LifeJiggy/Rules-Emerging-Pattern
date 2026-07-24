"""Rate limiting middleware for the rules engine."""

import calendar
import json
import logging
import math
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


class RateLimitStrategy(Enum):
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"
    FIXED_WINDOW = "fixed_window"
    LEAKY_BUCKET = "leaky_bucket"
    GCRA = "gcra"


class RateLimitScope(Enum):
    GLOBAL = "global"
    PER_IP = "per_ip"
    PER_USER = "per_user"
    PER_ROUTE = "per_route"
    PER_IP_ROUTE = "per_ip_route"
    PER_USER_ROUTE = "per_user_route"


class RateLimitAction(Enum):
    DENY = "deny"
    DELAY = "delay"
    THROTTLE = "throttle"
    QUEUE = "queue"
    DEGRADE = "degrade"


@dataclass
class RateLimitRule:
    name: str
    strategy: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW
    scope: RateLimitScope = RateLimitScope.PER_IP
    max_requests: int = 100
    window_seconds: int = 60
    burst_size: int = 10
    refill_rate: float = 1.0
    action: RateLimitAction = RateLimitAction.DENY
    delay_ms: int = 100
    queue_size: int = 10
    queue_timeout: int = 30
    priority: int = 0
    enabled: bool = True
    routes: List[str] = field(default_factory=lambda: ["*"])
    methods: List[str] = field(default_factory=lambda: ["*"])
    group: str = "default"


@dataclass
class RateLimitConfig:
    enabled: bool = True
    default_max_requests: int = 100
    default_window_seconds: int = 60
    default_burst_size: int = 20
    default_refill_rate: float = 2.0
    default_strategy: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW
    default_action: RateLimitAction = RateLimitAction.DENY
    rules: List[RateLimitRule] = field(default_factory=list)
    global_max_requests: int = 10000
    global_window_seconds: int = 3600
    ip_max_requests: int = 200
    ip_window_seconds: int = 60
    user_max_requests: int = 500
    user_window_seconds: int = 60
    route_max_requests: int = 50
    route_window_seconds: int = 60
    enable_headers: bool = True
    header_limit: str = "X-RateLimit-Limit"
    header_remaining: str = "X-RateLimit-Remaining"
    header_reset: str = "X-RateLimit-Reset"
    header_retry_after: str = "Retry-After"
    retry_after_format: str = "seconds"
    enable_backoff: bool = True
    backoff_base: float = 2.0
    backoff_multiplier: float = 1.5
    max_backoff_seconds: int = 3600
    backoff_on_violation: bool = True
    backoff_violation_threshold: int = 5
    backoff_window: int = 300
    enable_statistics: bool = True
    statistics_window: int = 3600
    cleanup_interval: int = 300
    enable_whitelist: bool = True
    whitelist_ips: List[str] = field(default_factory=list)
    whitelist_users: List[str] = field(default_factory=list)
    whitelist_routes: List[str] = field(default_factory=list)
    enable_blacklist: bool = True
    blacklist_ips: List[str] = field(default_factory=list)
    blacklist_users: List[str] = field(default_factory=list)
    track_per_ip: bool = True
    track_per_user: bool = True
    track_per_route: bool = True
    track_per_ip_route: bool = True
    track_per_user_route: bool = True
    storage_backend: str = "memory"
    redis_url: str = ""
    redis_prefix: str = "ratelimit:"
    sync_on_mutate: bool = True


@dataclass
class SlidingWindowState:
    timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=10000))


@dataclass
class TokenBucketState:
    tokens: float = 0.0
    last_refill: float = 0.0


@dataclass
class LeakyBucketState:
    water: float = 0.0
    last_leak: float = 0.0


@dataclass
class GCRAState:
    tat: float = 0.0


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    limit: int
    reset_at: float
    retry_after: float = 0.0
    action: RateLimitAction = RateLimitAction.DENY
    rule_name: str = ""
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class RateLimitStats:
    total_requests: int = 0
    allowed_requests: int = 0
    denied_requests: int = 0
    delayed_requests: int = 0
    queued_requests: int = 0
    violations: int = 0
    current_active_rules: int = 0
    memory_usage_bytes: int = 0


class SlidingWindowCounter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._states: Dict[str, SlidingWindowState] = defaultdict(SlidingWindowState)
        self._lock = Lock()

    def check(self, key: str) -> RateLimitResult:
        now = time.time()
        with self._lock:
            state = self._states[key]
            cutoff = now - self.window_seconds
            while state.timestamps and state.timestamps[0] < cutoff:
                state.timestamps.popleft()
            current_count = len(state.timestamps)
            allowed = current_count < self.max_requests
            if allowed:
                state.timestamps.append(now)
            remaining = max(0, self.max_requests - current_count - (0 if allowed else 1))
            reset_at = cutoff + self.window_seconds
            retry_after = 0.0
            if not allowed and state.timestamps:
                retry_after = max(0.0, state.timestamps[0] + self.window_seconds - now)
            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                limit=self.max_requests,
                reset_at=reset_at,
                retry_after=retry_after,
            )

    def get_count(self, key: str) -> int:
        now = time.time()
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return 0
            cutoff = now - self.window_seconds
            while state.timestamps and state.timestamps[0] < cutoff:
                state.timestamps.popleft()
            return len(state.timestamps)

    def reset(self, key: str) -> bool:
        with self._lock:
            if key in self._states:
                del self._states[key]
                return True
            return False

    def cleanup(self, max_age: float = 300.0) -> int:
        now = time.time()
        cutoff = now - max_age
        count = 0
        with self._lock:
            for key in list(self._states.keys()):
                state = self._states[key]
                if state.timestamps and state.timestamps[-1] < cutoff:
                    del self._states[key]
                    count += 1
        return count

    def size(self) -> int:
        with self._lock:
            return len(self._states)


class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float, refill_interval: float = 1.0):
        self.capacity = float(capacity)
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval
        self._states: Dict[str, TokenBucketState] = defaultdict(TokenBucketState)
        self._lock = Lock()

    def check(self, key: str, tokens: float = 1.0) -> RateLimitResult:
        now = time.time()
        with self._lock:
            state = self._states[key]
            if state.last_refill == 0:
                state.tokens = self.capacity
                state.last_refill = now
            elapsed = now - state.last_refill
            refill = elapsed * self.refill_rate
            state.tokens = min(self.capacity, state.tokens + refill)
            state.last_refill = now
            allowed = state.tokens >= tokens
            if allowed:
                state.tokens -= tokens
            remaining = max(0, int(state.tokens))
            tokens_needed = tokens - state.tokens if not allowed else 0
            retry_after = tokens_needed / self.refill_rate if tokens_needed > 0 else 0
            reset_at = now + (self.capacity - state.tokens) / self.refill_rate
            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                limit=int(self.capacity),
                reset_at=reset_at,
                retry_after=retry_after,
            )

    def get_tokens(self, key: str) -> float:
        now = time.time()
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return self.capacity
            elapsed = now - state.last_refill
            return min(self.capacity, state.tokens + elapsed * self.refill_rate)

    def reset(self, key: str) -> bool:
        with self._lock:
            if key in self._states:
                del self._states[key]
                return True
            return False

    def cleanup(self, max_age: float = 300.0) -> int:
        now = time.time()
        cutoff = now - max_age
        count = 0
        with self._lock:
            for key in list(self._states.keys()):
                state = self._states[key]
                if state.last_refill > 0 and state.last_refill < cutoff:
                    del self._states[key]
                    count += 1
        return count

    def size(self) -> int:
        with self._lock:
            return len(self._states)


class FixedWindowCounter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._counts: Dict[str, Tuple[int, int]] = {}
        self._lock = Lock()

    def check(self, key: str) -> RateLimitResult:
        now = time.time()
        window_start = int(now // self.window_seconds) * self.window_seconds
        with self._lock:
            count, start = self._counts.get(key, (0, window_start))
            if start != window_start:
                count = 0
                start = window_start
            allowed = count < self.max_requests
            if allowed:
                count += 1
            self._counts[key] = (count, start)
            remaining = max(0, self.max_requests - count)
            reset_at = start + self.window_seconds
            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                limit=self.max_requests,
                reset_at=reset_at,
                retry_after=max(0.0, reset_at - now),
            )

    def get_count(self, key: str) -> int:
        now = time.time()
        window_start = int(now // self.window_seconds) * self.window_seconds
        with self._lock:
            count, start = self._counts.get(key, (0, window_start))
            if start != window_start:
                return 0
            return count

    def reset(self, key: str) -> bool:
        with self._lock:
            if key in self._counts:
                del self._counts[key]
                return True
            return False


class LeakyBucket:
    def __init__(self, capacity: int, leak_rate: float):
        self.capacity = float(capacity)
        self.leak_rate = leak_rate
        self._states: Dict[str, LeakyBucketState] = defaultdict(LeakyBucketState)
        self._lock = Lock()

    def check(self, key: str, tokens: float = 1.0) -> RateLimitResult:
        now = time.time()
        with self._lock:
            state = self._states[key]
            elapsed = now - state.last_leak
            leaked = elapsed * self.leak_rate
            state.water = max(0.0, state.water - leaked)
            state.last_leak = now
            allowed = state.water + tokens <= self.capacity
            if allowed:
                state.water += tokens
            remaining = max(0, int(self.capacity - state.water))
            retry_after = (state.water + tokens - self.capacity) / self.leak_rate if not allowed else 0
            reset_at = now + (self.capacity - state.water) / self.leak_rate
            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                limit=int(self.capacity),
                reset_at=reset_at,
                retry_after=retry_after,
            )

    def get_water(self, key: str) -> float:
        now = time.time()
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return 0.0
            elapsed = now - state.last_leak
            return max(0.0, state.water - elapsed * self.leak_rate)

    def reset(self, key: str) -> bool:
        with self._lock:
            if key in self._states:
                del self._states[key]
                return True
            return False

    def cleanup(self, max_age: float = 300.0) -> int:
        now = time.time()
        cutoff = now - max_age
        count = 0
        with self._lock:
            for key in list(self._states.keys()):
                state = self._states[key]
                if state.last_leak > 0 and state.last_leak < cutoff:
                    del self._states[key]
                    count += 1
        return count


class GCRACounter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.tau = window_seconds / max_requests
        self.t_max = window_seconds
        self._states: Dict[str, GCRAState] = defaultdict(GCRAState)
        self._lock = Lock()

    def check(self, key: str) -> RateLimitResult:
        now = time.time()
        with self._lock:
            state = self._states[key]
            if state.tat == 0:
                state.tat = now
            new_tat = max(state.tat, now) + self.tau
            allowed = new_tat <= now + self.t_max
            delay = new_tat - now
            if allowed:
                state.tat = new_tat
            remaining = max(0, int((now + self.t_max - state.tat) / self.tau)) if allowed else 0
            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                limit=self._get_limit(),
                reset_at=state.tat if allowed else now + delay,
                retry_after=delay if not allowed else 0,
            )

    def _get_limit(self) -> int:
        return int(self.t_max / self.tau) if self.tau > 0 else 0

    def reset(self, key: str) -> bool:
        with self._lock:
            if key in self._states:
                del self._states[key]
                return True
            return False

    def cleanup(self, max_age: float = 300.0) -> int:
        now = time.time()
        cutoff = now - max_age
        count = 0
        with self._lock:
            for key in list(self._states.keys()):
                state = self._states[key]
                if state.tat > 0 and state.tat < cutoff:
                    del self._states[key]
                    count += 1
        return count


class BackoffController:
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._violations: Dict[str, List[float]] = defaultdict(list)
        self._lock = Lock()

    def record_violation(self, key: str) -> None:
        now = time.time()
        with self._lock:
            self._violations[key].append(now)
            cutoff = now - self.config.backoff_window
            self._violations[key] = [v for v in self._violations[key] if v > cutoff]

    def get_backoff(self, key: str) -> float:
        if not self.config.enable_backoff:
            return 0.0
        now = time.time()
        with self._lock:
            violations = self._violations.get(key, [])
            cutoff = now - self.config.backoff_window
            violations = [v for v in violations if v > cutoff]
            self._violations[key] = violations
            if len(violations) < self.config.backoff_violation_threshold:
                return 0.0
            violation_count = len(violations)
            backoff = self.config.backoff_base * (
                self.config.backoff_multiplier ** (violation_count - self.config.backoff_violation_threshold + 1)
            )
            return min(backoff, float(self.config.max_backoff_seconds))

    def is_backing_off(self, key: str) -> bool:
        backoff = self.get_backoff(key)
        if backoff <= 0:
            return False
        now = time.time()
        with self._lock:
            violations = self._violations.get(key, [])
            if not violations:
                return False
            return (now - violations[-1]) < backoff

    def reset(self, key: str) -> None:
        with self._lock:
            self._violations.pop(key, None)

    def cleanup(self) -> None:
        now = time.time()
        cutoff = now - self.config.backoff_window
        with self._lock:
            for key in list(self._violations.keys()):
                self._violations[key] = [v for v in self._violations[key] if v > cutoff]
                if not self._violations[key]:
                    del self._violations[key]


class RateLimitMiddleware:
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self._sliding_windows: Dict[str, SlidingWindowCounter] = {}
        self._token_buckets: Dict[str, TokenBucket] = {}
        self._fixed_windows: Dict[str, FixedWindowCounter] = {}
        self._leaky_buckets: Dict[str, LeakyBucket] = {}
        self._gcras: Dict[str, GCRACounter] = {}
        self._backoff = BackoffController(self.config)
        self._stats = RateLimitStats()
        self._queues: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._lock = Lock()
        self._last_cleanup = time.time()
        self._init_default_rules()
        logger.info(
            "RateLimitMiddleware initialized with %d rules",
            len(self.config.rules),
        )

    def _init_default_rules(self) -> None:
        if not self.config.rules:
            self.config.rules = [
                RateLimitRule(
                    name="global",
                    scope=RateLimitScope.GLOBAL,
                    max_requests=self.config.global_max_requests,
                    window_seconds=self.config.global_window_seconds,
                    strategy=RateLimitStrategy.SLIDING_WINDOW,
                ),
                RateLimitRule(
                    name="per_ip",
                    scope=RateLimitScope.PER_IP,
                    max_requests=self.config.ip_max_requests,
                    window_seconds=self.config.ip_window_seconds,
                    strategy=RateLimitStrategy.TOKEN_BUCKET,
                    burst_size=self.config.default_burst_size,
                    refill_rate=self.config.default_refill_rate,
                ),
                RateLimitRule(
                    name="per_user",
                    scope=RateLimitScope.PER_USER,
                    max_requests=self.config.user_max_requests,
                    window_seconds=self.config.user_window_seconds,
                    strategy=RateLimitStrategy.TOKEN_BUCKET,
                ),
                RateLimitRule(
                    name="per_route",
                    scope=RateLimitScope.PER_ROUTE,
                    max_requests=self.config.route_max_requests,
                    window_seconds=self.config.route_window_seconds,
                    strategy=RateLimitStrategy.SLIDING_WINDOW,
                ),
            ]

    def add_rule(self, rule: RateLimitRule) -> None:
        self.config.rules.append(rule)
        self._get_counter(rule)

    def remove_rule(self, name: str) -> bool:
        before = len(self.config.rules)
        self.config.rules = [r for r in self.config.rules if r.name != name]
        removed = len(self.config.rules) < before
        if removed:
            self._sliding_windows.pop(name, None)
            self._token_buckets.pop(name, None)
            self._fixed_windows.pop(name, None)
            self._leaky_buckets.pop(name, None)
            self._gcras.pop(name, None)
        return removed

    def check_rate_limit(self, request: Dict[str, Any]) -> RateLimitResult:
        if not self.config.enabled:
            return RateLimitResult(allowed=True, remaining=999999, limit=999999, reset_at=time.time() + 3600)

        self._maybe_cleanup()

        method = request.get("method", "GET").upper()
        route = request.get("route", "")
        ip = request.get("headers", {}).get("X-Forwarded-For", request.get("headers", {}).get("X-Real-IP", "unknown"))
        user_id = request.get("user_id") or request.get("_metadata", {}).get("user_id")

        if self.config.enable_whitelist:
            if ip in self.config.whitelist_ips:
                return RateLimitResult(allowed=True, remaining=999999, limit=999999, reset_at=time.time() + 3600)
            if user_id and user_id in self.config.whitelist_users:
                return RateLimitResult(allowed=True, remaining=999999, limit=999999, reset_at=time.time() + 3600)
            for wl_route in self.config.whitelist_routes:
                if route.startswith(wl_route):
                    return RateLimitResult(allowed=True, remaining=999999, limit=999999, reset_at=time.time() + 3600)

        if self.config.enable_blacklist:
            if ip in self.config.blacklist_ips:
                return RateLimitResult(
                    allowed=False, remaining=0, limit=0, reset_at=0,
                    action=RateLimitAction.DENY, retry_after=86400,
                )
            if user_id and user_id in self.config.blacklist_users:
                return RateLimitResult(
                    allowed=False, remaining=0, limit=0, reset_at=0,
                    action=RateLimitAction.DENY, retry_after=86400,
                )

        with self._lock:
            self._stats.total_requests += 1

        sorted_rules = sorted(self.config.rules, key=lambda r: r.priority, reverse=True)

        for rule in sorted_rules:
            if not rule.enabled:
                continue
            if rule.methods != ["*"] and method not in rule.methods:
                continue
            if rule.routes != ["*"] and not any(
                route.startswith(r) if r.endswith("*") else route == r
                for r in rule.routes
            ):
                continue

            key = self._build_key(rule, ip, user_id, route)
            if self.config.enable_backoff and self._backoff.is_backing_off(key):
                backoff = self._backoff.get_backoff(key)
                with self._lock:
                    self._stats.denied_requests += 1
                    self._stats.violations += 1
                return RateLimitResult(
                    allowed=False, remaining=0, limit=rule.max_requests,
                    reset_at=time.time() + backoff, retry_after=backoff,
                    action=rule.action, rule_name=rule.name,
                )

            result = self._check_rule(rule, key)
            if not result.allowed:
                if self.config.backoff_on_violation:
                    self._backoff.record_violation(key)
                with self._lock:
                    self._stats.denied_requests += 1
                    self._stats.violations += 1
                result.action = rule.action
                result.rule_name = rule.name
                if self.config.enable_headers:
                    result.headers = self._build_headers(result, rule)
                return result

        with self._lock:
            self._stats.allowed_requests += 1

        return RateLimitResult(
            allowed=True, remaining=999999, limit=999999,
            reset_at=time.time() + 3600,
            action=RateLimitAction.DENY,
        )

    def _build_key(self, rule: RateLimitRule, ip: str, user_id: Optional[str], route: str) -> str:
        if rule.scope == RateLimitScope.GLOBAL:
            return "global"
        elif rule.scope == RateLimitScope.PER_IP:
            return f"ip:{ip}"
        elif rule.scope == RateLimitScope.PER_USER:
            return f"user:{user_id or 'anonymous'}"
        elif rule.scope == RateLimitScope.PER_ROUTE:
            return f"route:{route}"
        elif rule.scope == RateLimitScope.PER_IP_ROUTE:
            return f"ip_route:{ip}:{route}"
        elif rule.scope == RateLimitScope.PER_USER_ROUTE:
            return f"user_route:{user_id or 'anonymous'}:{route}"
        return f"{rule.scope.value}:{ip}:{route}"

    def _check_rule(self, rule: RateLimitRule, key: str) -> RateLimitResult:
        counter = self._get_counter(rule)
        if counter is None:
            return RateLimitResult(allowed=True, remaining=999999, limit=999999, reset_at=time.time() + 3600)

        if isinstance(counter, (SlidingWindowCounter, FixedWindowCounter)):
            return counter.check(key)
        elif isinstance(counter, TokenBucket):
            return counter.check(key, 1.0)
        elif isinstance(counter, LeakyBucket):
            return counter.check(key, 1.0)
        elif isinstance(counter, GCRACounter):
            return counter.check(key)
        return RateLimitResult(allowed=True, remaining=999999, limit=999999, reset_at=time.time() + 3600)

    def _get_counter(self, rule: RateLimitRule) -> Any:
        name = rule.name
        if rule.strategy == RateLimitStrategy.SLIDING_WINDOW:
            if name not in self._sliding_windows:
                self._sliding_windows[name] = SlidingWindowCounter(rule.max_requests, rule.window_seconds)
            return self._sliding_windows[name]
        elif rule.strategy == RateLimitStrategy.TOKEN_BUCKET:
            if name not in self._token_buckets:
                self._token_buckets[name] = TokenBucket(rule.burst_size or rule.max_requests, rule.refill_rate)
            return self._token_buckets[name]
        elif rule.strategy == RateLimitStrategy.FIXED_WINDOW:
            if name not in self._fixed_windows:
                self._fixed_windows[name] = FixedWindowCounter(rule.max_requests, rule.window_seconds)
            return self._fixed_windows[name]
        elif rule.strategy == RateLimitStrategy.LEAKY_BUCKET:
            if name not in self._leaky_buckets:
                self._leaky_buckets[name] = LeakyBucket(rule.burst_size or rule.max_requests, rule.refill_rate)
            return self._leaky_buckets[name]
        elif rule.strategy == RateLimitStrategy.GCRA:
            if name not in self._gcras:
                self._gcras[name] = GCRACounter(rule.max_requests, rule.window_seconds)
            return self._gcras[name]
        return None

    def _build_headers(self, result: RateLimitResult, rule: RateLimitRule) -> Dict[str, str]:
        headers = {}
        if self.config.enable_headers:
            headers[self.config.header_limit] = str(result.limit)
            headers[self.config.header_remaining] = str(result.remaining)
            headers[self.config.header_reset] = str(int(result.reset_at))
            if not result.allowed and result.retry_after > 0:
                if self.config.retry_after_format == "seconds":
                    headers[self.config.header_retry_after] = str(int(math.ceil(result.retry_after)))
                else:
                    headers[self.config.header_retry_after] = datetime.fromtimestamp(
                        time.time() + result.retry_after, tz=timezone.utc
                    ).isoformat()
        return headers

    def _maybe_cleanup(self) -> None:
        now = time.time()
        if now - self._last_cleanup > self.config.cleanup_interval:
            for sw in self._sliding_windows.values():
                sw.cleanup(self.config.statistics_window)
            for tb in self._token_buckets.values():
                tb.cleanup(self.config.statistics_window)
            for lb in self._leaky_buckets.values():
                lb.cleanup(self.config.statistics_window)
            for gc in self._gcras.values():
                gc.cleanup(self.config.statistics_window)
            self._backoff.cleanup()
            self._last_cleanup = now

    def can_proceed(self, request: Dict[str, Any]) -> Tuple[bool, Dict[str, str]]:
        result = self.check_rate_limit(request)
        return result.allowed, result.headers

    def get_remaining(self, request: Dict[str, Any]) -> int:
        result = self.check_rate_limit(request)
        return result.remaining

    def get_retry_after(self, request: Dict[str, Any]) -> float:
        result = self.check_rate_limit(request)
        return result.retry_after

    def reset_key(self, key: str) -> bool:
        any_reset = False
        for sw in self._sliding_windows.values():
            if sw.reset(key):
                any_reset = True
        for tb in self._token_buckets.values():
            if tb.reset(key):
                any_reset = True
        for fw in self._fixed_windows.values():
            if fw.reset(key):
                any_reset = True
        for lb in self._leaky_buckets.values():
            if lb.reset(key):
                any_reset = True
        for gc in self._gcras.values():
            if gc.reset(key):
                any_reset = True
        self._backoff.reset(key)
        return any_reset

    def reset_all(self) -> int:
        count = 0
        for sw in self._sliding_windows.values():
            count += sw.size()
        for tb in self._token_buckets.values():
            count += tb.size()
        self._sliding_windows.clear()
        self._token_buckets.clear()
        self._fixed_windows.clear()
        self._leaky_buckets.clear()
        self._gcras.clear()
        return count

    def add_to_whitelist(self, ip: Optional[str] = None, user: Optional[str] = None, route: Optional[str] = None) -> None:
        if ip:
            self.config.whitelist_ips.append(ip)
        if user:
            self.config.whitelist_users.append(user)
        if route:
            self.config.whitelist_routes.append(route)

    def remove_from_whitelist(self, ip: Optional[str] = None, user: Optional[str] = None, route: Optional[str] = None) -> bool:
        found = False
        if ip and ip in self.config.whitelist_ips:
            self.config.whitelist_ips.remove(ip)
            found = True
        if user and user in self.config.whitelist_users:
            self.config.whitelist_users.remove(user)
            found = True
        if route and route in self.config.whitelist_routes:
            self.config.whitelist_routes.remove(route)
            found = True
        return found

    def add_to_blacklist(self, ip: Optional[str] = None, user: Optional[str] = None) -> None:
        if ip:
            self.config.blacklist_ips.append(ip)
        if user:
            self.config.blacklist_users.append(user)

    def remove_from_blacklist(self, ip: Optional[str] = None, user: Optional[str] = None) -> bool:
        found = False
        if ip and ip in self.config.blacklist_ips:
            self.config.blacklist_ips.remove(ip)
            found = True
        if user and user in self.config.blacklist_users:
            self.config.blacklist_users.remove(user)
            found = True
        return found

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_requests": self._stats.total_requests,
            "allowed_requests": self._stats.allowed_requests,
            "denied_requests": self._stats.denied_requests,
            "delayed_requests": self._stats.delayed_requests,
            "queued_requests": self._stats.queued_requests,
            "violations": self._stats.violations,
            "rules_count": len(self.config.rules),
            "sliding_windows": len(self._sliding_windows),
            "token_buckets": len(self._token_buckets),
            "fixed_windows": len(self._fixed_windows),
            "leaky_buckets": len(self._leaky_buckets),
            "gcra_counters": len(self._gcras),
            "whitelist_ips": len(self.config.whitelist_ips),
            "whitelist_users": len(self.config.whitelist_users),
            "whitelist_routes": len(self.config.whitelist_routes),
            "blacklist_ips": len(self.config.blacklist_ips),
            "blacklist_users": len(self.config.blacklist_users),
            "backoff_enabled": self.config.enable_backoff,
            "headers_enabled": self.config.enable_headers,
            "strategy": self.config.default_strategy.value,
        }

    def get_rule_stats(self, rule_name: str) -> Optional[Dict[str, Any]]:
        for rule in self.config.rules:
            if rule.name == rule_name:
                counter = self._get_counter(rule)
                size = 0
                if hasattr(counter, "size"):
                    size = counter.size()
                return {
                    "name": rule.name,
                    "strategy": rule.strategy.value,
                    "scope": rule.scope.value,
                    "max_requests": rule.max_requests,
                    "window_seconds": rule.window_seconds,
                    "burst_size": rule.burst_size,
                    "enabled": rule.enabled,
                    "active_keys": size,
                }
        return None

    def update_rule(self, name: str, **kwargs: Any) -> bool:
        for rule in self.config.rules:
            if rule.name == name:
                for key, value in kwargs.items():
                    if hasattr(rule, key):
                        setattr(rule, key, value)
                return True
        return False

    def update_config(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    def reset_config(self) -> None:
        self.config = RateLimitConfig()
        self._sliding_windows.clear()
        self._token_buckets.clear()
        self._fixed_windows.clear()
        self._leaky_buckets.clear()
        self._gcras.clear()
        self._stats = RateLimitStats()
        self._init_default_rules()

    def get_backoff_status(self, ip: str) -> Dict[str, Any]:
        backoff = self._backoff.get_backoff(ip)
        return {
            "ip": ip,
            "backoff_seconds": backoff,
            "is_backing_off": backoff > 0,
        }

    def reset_ip_backoff(self, ip: str) -> None:
        self._backoff.reset(ip)

    def check_rate_limit_batch(self, requests: List[Dict[str, Any]]) -> List[RateLimitResult]:
        return [self.check_rate_limit(req) for req in requests]

    def estimated_limit_for(self, scope: RateLimitScope, identifier: str) -> int:
        for rule in self.config.rules:
            if rule.scope == scope:
                return rule.max_requests
        return self.config.default_max_requests

    def __repr__(self) -> str:
        return (
            f"RateLimitMiddleware(rules={len(self.config.rules)}, "
            f"allowed={self._stats.allowed_requests}, "
            f"denied={self._stats.denied_requests})"
        )
