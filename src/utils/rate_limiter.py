"""Production-grade rate limiter with token bucket, sliding window, per-user/per-IP/per-route, backoff, violation tracking, and config-driven limits."""

import time
import math
import threading
import logging
import hashlib
import json
import re
from typing import Any, Callable, Optional, Union, List, Dict, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict, OrderedDict
from enum import Enum, auto
from pathlib import Path

logger = logging.getLogger(__name__)


class RateLimitAlgorithm(Enum):
    TOKEN_BUCKET = auto()
    SLIDING_WINDOW = auto()
    FIXED_WINDOW = auto()
    LEAKY_BUCKET = auto()


class BackoffStrategy(Enum):
    NONE = auto()
    LINEAR = auto()
    EXPONENTIAL = auto()
    JITTER = auto()
    DECORRELATED_JITTER = auto()


class RateLimitScope(Enum):
    GLOBAL = auto()
    USER = auto()
    IP = auto()
    ROUTE = auto()
    USER_IP = auto()
    USER_ROUTE = auto()
    IP_ROUTE = auto()
    CUSTOM = auto()


@dataclass
class RateLimitRule:
    max_requests: int
    window_seconds: float
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW
    scope: RateLimitScope = RateLimitScope.GLOBAL
    burst_size: Optional[int] = None
    backoff: BackoffStrategy = BackoffStrategy.NONE
    backoff_multiplier: float = 2.0
    backoff_base_delay: float = 1.0
    backoff_max_delay: float = 3600.0
    max_penalty_requests: int = 10
    penalty_window_seconds: float = 600.0
    violation_threshold: int = 5
    violation_window: float = 300.0
    auto_ban_after: int = 10
    auto_ban_duration: float = 86400.0
    name: str = "default"

    def effective_burst(self) -> int:
        return self.burst_size if self.burst_size is not None else self.max_requests


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_time: float
    limit: int
    retry_after: float = 0.0
    violated: bool = False
    banned: bool = False
    ban_remaining: float = 0.0

    def to_headers(self) -> Dict[str, str]:
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(int(self.reset_time)),
        }
        if self.retry_after > 0:
            headers["Retry-After"] = str(int(math.ceil(self.retry_after)))
        if self.banned:
            headers["X-RateLimit-Banned"] = "true"
        return headers

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "remaining": self.remaining,
            "reset_time": self.reset_time,
            "limit": self.limit,
            "retry_after": self.retry_after,
            "violated": self.violated,
            "banned": self.banned,
            "ban_remaining": self.ban_remaining,
        }


@dataclass
class RateLimiterConfig:
    default_max_requests: int = 100
    default_window_seconds: float = 60.0
    default_algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW
    default_scope: RateLimitScope = RateLimitScope.IP
    global_max_requests: int = 10000
    global_window_seconds: float = 60.0
    cleanup_interval: float = 60.0
    enable_stats: bool = True
    track_violations: bool = True
    auto_ban_enabled: bool = False
    key_prefix_separator: str = ":"
    clock_skew_tolerance: float = 2.0
    max_tracked_keys: int = 100000
    violation_tracking_window: float = 3600.0


class ViolationTracker:
    def __init__(self, config: RateLimiterConfig):
        self.config = config
        self._violations: Dict[str, List[float]] = defaultdict(list)
        self._bans: Dict[str, float] = {}
        self._lock = threading.RLock()

    def record_violation(self, key: str) -> int:
        now = time.time()
        with self._lock:
            self._violations[key].append(now)
            self._prune(key, now)
            return len(self._violations[key])

    def get_violation_count(self, key: str) -> int:
        now = time.time()
        with self._lock:
            self._prune(key, now)
            return len(self._violations[key])

    def check_banned(self, key: str) -> Tuple[bool, float]:
        now = time.time()
        with self._lock:
            if key in self._bans:
                ban_until = self._bans[key]
                if now < ban_until:
                    return True, ban_until - now
                del self._bans[key]
            return False, 0.0

    def ban(self, key: str, duration: float):
        with self._lock:
            self._bans[key] = time.time() + duration

    def unban(self, key: str):
        with self._lock:
            self._bans.pop(key, None)

    def clear(self):
        with self._lock:
            self._violations.clear()
            self._bans.clear()

    def _prune(self, key: str, now: float):
        window = self.config.violation_tracking_window
        self._violations[key] = [t for t in self._violations[key] if now - t < window]
        if not self._violations[key]:
            del self._violations[key]

    def get_banned_keys(self) -> List[str]:
        now = time.time()
        with self._lock:
            return [k for k, v in self._bans.items() if v > now]


class TokenBucket:
    def __init__(self, max_tokens: int, refill_rate: float, burst_size: Optional[int] = None):
        self.max_tokens = float(max_tokens)
        self.refill_rate = refill_rate
        self.burst = float(burst_size) if burst_size else self.max_tokens
        self.tokens = self.max_tokens
        self.last_refill = time.time()

    def refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, count: int = 1) -> bool:
        self.refill()
        if self.tokens >= count:
            self.tokens -= count
            return True
        return False

    def get_remaining(self) -> float:
        self.refill()
        return self.tokens

    def get_reset_time(self) -> float:
        return self.last_refill + (self.max_tokens / self.refill_rate) if self.refill_rate > 0 else float("inf")

    def needs_reset(self) -> bool:
        return self.get_remaining() >= self.max_tokens


class SlidingWindow:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: List[float] = []

    def prune(self, now: float):
        cutoff = now - self.window_seconds
        self.timestamps = [t for t in self.timestamps if t > cutoff]

    def consume(self, count: int = 1, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.time()
        self.prune(now)
        if len(self.timestamps) + count <= self.max_requests:
            for _ in range(count):
                self.timestamps.append(now)
            return True
        return False

    def remaining(self, now: Optional[float] = None) -> int:
        if now is None:
            now = time.time()
        self.prune(now)
        return max(0, self.max_requests - len(self.timestamps))

    def reset_time(self, now: Optional[float] = None) -> float:
        if now is None:
            now = time.time()
        self.prune(now)
        if not self.timestamps:
            return now
        return self.timestamps[0] + self.window_seconds


class FixedWindow:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.count: int = 0
        self.window_start: float = time.time()

    def _check_window(self, now: float):
        if now - self.window_start >= self.window_seconds:
            self.count = 0
            self.window_start = now

    def consume(self, count: int = 1, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.time()
        self._check_window(now)
        if self.count + count <= self.max_requests:
            self.count += count
            return True
        return False

    def remaining(self, now: Optional[float] = None) -> int:
        if now is None:
            now = time.time()
        self._check_window(now)
        return max(0, self.max_requests - self.count)

    def reset_time(self, now: Optional[float] = None) -> float:
        if now is None:
            now = time.time()
        return self.window_start + self.window_seconds


class LeakyBucket:
    def __init__(self, max_capacity: int, leak_rate: float):
        self.max_capacity = max_capacity
        self.leak_rate = leak_rate
        self.water: float = 0.0
        self.last_leak = time.time()

    def _leak(self, now: float):
        elapsed = now - self.last_leak
        leaked = elapsed * self.leak_rate
        self.water = max(0.0, self.water - leaked)
        self.last_leak = now

    def consume(self, count: int = 1, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.time()
        self._leak(now)
        if self.water + count <= self.max_capacity:
            self.water += count
            return True
        return False

    def remaining(self, now: Optional[float] = None) -> int:
        if now is None:
            now = time.time()
        self._leak(now)
        return max(0, int(self.max_capacity - self.water))

    def reset_time(self, now: Optional[float] = None) -> float:
        if now is None:
            now = time.time()
        return now + (self.water / self.leak_rate) if self.leak_rate > 0 else float("inf")


class RateLimiter:
    """Production-grade rate limiter with multiple algorithms, scopes, backoff, and violation tracking."""

    def __init__(self, config: Optional[RateLimiterConfig] = None):
        self.config = config or RateLimiterConfig()
        self._token_buckets: Dict[str, TokenBucket] = {}
        self._sliding_windows: Dict[str, SlidingWindow] = {}
        self._fixed_windows: Dict[str, FixedWindow] = {}
        self._leaky_buckets: Dict[str, LeakyBucket] = {}
        self._rules: Dict[str, RateLimitRule] = {}
        self._global_rule = RateLimitRule(
            max_requests=self.config.global_max_requests,
            window_seconds=self.config.global_window_seconds,
            scope=RateLimitScope.GLOBAL,
            name="global"
        )
        self._lock = threading.RLock()
        self._violation_tracker = ViolationTracker(self.config)
        self._stats_lock = threading.RLock()
        self._total_checks: int = 0
        self._total_allowed: int = 0
        self._total_denied: int = 0
        self._cleanup_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()

        if self.config.cleanup_interval > 0:
            self._start_cleanup()

    def add_rule(self, rule: RateLimitRule) -> "RateLimiter":
        with self._lock:
            self._rules[rule.name] = rule
        return self

    def remove_rule(self, name: str) -> bool:
        with self._lock:
            return self._rules.pop(name, None) is not None

    def get_rule(self, name: str) -> Optional[RateLimitRule]:
        return self._rules.get(name)

    def list_rules(self) -> List[str]:
        return list(self._rules.keys())

    def check(self, key: str, count: int = 1, scope: Optional[RateLimitScope] = None,
              rule_name: Optional[str] = None) -> RateLimitResult:
        with self._stats_lock:
            self._total_checks += 1
        banned, ban_remaining = self._violation_tracker.check_banned(key)
        if banned:
            with self._stats_lock:
                self._total_denied += 1
            return RateLimitResult(
                allowed=False, remaining=0, reset_time=time.time() + ban_remaining,
                limit=0, retry_after=ban_remaining, banned=True, ban_remaining=ban_remaining
            )
        rule = self._resolve_rule(key, scope, rule_name)
        window_key = self._window_key(key, rule)
        result = self._check_window(window_key, rule, count)
        if result.violated:
            violation_count = self._violation_tracker.record_violation(key)
            if self.config.auto_ban_enabled and violation_count >= rule.auto_ban_after:
                self._violation_tracker.ban(key, rule.auto_ban_duration)
                result.banned = True
                result.ban_remaining = rule.auto_ban_duration
        if result.allowed:
            with self._stats_lock:
                self._total_allowed += 1
        else:
            with self._stats_lock:
                self._total_denied += 1
        return result

    def consume(self, key: str, count: int = 1, scope: Optional[RateLimitScope] = None,
                rule_name: Optional[str] = None) -> bool:
        return self.check(key, count, scope, rule_name).allowed

    def get_remaining(self, key: str, scope: Optional[RateLimitScope] = None,
                      rule_name: Optional[str] = None) -> int:
        rule = self._resolve_rule(key, scope, rule_name)
        window_key = self._window_key(key, rule)
        with self._lock:
            if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                bucket = self._token_buckets.get(window_key)
                if bucket:
                    return int(bucket.get_remaining())
                return rule.max_requests
            elif rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
                window = self._sliding_windows.get(window_key)
                if window:
                    return window.remaining()
                return rule.max_requests
            elif rule.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
                window = self._fixed_windows.get(window_key)
                if window:
                    return window.remaining()
                return rule.max_requests
            elif rule.algorithm == RateLimitAlgorithm.LEAKY_BUCKET:
                bucket = self._leaky_buckets.get(window_key)
                if bucket:
                    return bucket.remaining()
                return rule.effective_burst()
        return rule.max_requests

    def get_reset_time(self, key: str, scope: Optional[RateLimitScope] = None,
                       rule_name: Optional[str] = None) -> float:
        rule = self._resolve_rule(key, scope, rule_name)
        window_key = self._window_key(key, rule)
        with self._lock:
            if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                bucket = self._token_buckets.get(window_key)
                return bucket.get_reset_time() if bucket else time.time()
            elif rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
                window = self._sliding_windows.get(window_key)
                return window.reset_time() if window else time.time()
            elif rule.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
                window = self._fixed_windows.get(window_key)
                return window.reset_time() if window else time.time()
            elif rule.algorithm == RateLimitAlgorithm.LEAKY_BUCKET:
                bucket = self._leaky_buckets.get(window_key)
                return bucket.reset_time() if bucket else time.time()
        return time.time()

    def check_key(self, key: str) -> RateLimitResult:
        return self.check(key)

    def _resolve_rule(self, key: str, scope: Optional[RateLimitScope],
                      rule_name: Optional[str]) -> RateLimitRule:
        if rule_name and rule_name in self._rules:
            return self._rules[rule_name]
        if scope:
            for rule in self._rules.values():
                if rule.scope == scope:
                    return rule
        if self._rules:
            return next(iter(self._rules.values()))
        return self._global_rule

    def _window_key(self, key: str, rule: RateLimitRule) -> str:
        return f"{rule.name}:{key}"

    def _check_window(self, window_key: str, rule: RateLimitRule, count: int) -> RateLimitResult:
        now = time.time()
        with self._lock:
            if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                if window_key not in self._token_buckets:
                    refill_rate = rule.max_requests / rule.window_seconds if rule.window_seconds > 0 else float("inf")
                    self._token_buckets[window_key] = TokenBucket(
                        max_tokens=rule.max_requests,
                        refill_rate=refill_rate,
                        burst_size=rule.effective_burst()
                    )
                bucket = self._token_buckets[window_key]
                allowed = bucket.consume(count)
                remaining = int(bucket.get_remaining())
                reset_time = bucket.get_reset_time()
            elif rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
                if window_key not in self._sliding_windows:
                    self._sliding_windows[window_key] = SlidingWindow(rule.max_requests, rule.window_seconds)
                window = self._sliding_windows[window_key]
                allowed = window.consume(count, now)
                remaining = window.remaining(now)
                reset_time = window.reset_time(now)
            elif rule.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
                if window_key not in self._fixed_windows:
                    self._fixed_windows[window_key] = FixedWindow(rule.max_requests, rule.window_seconds)
                window = self._fixed_windows[window_key]
                allowed = window.consume(count, now)
                remaining = window.remaining(now)
                reset_time = window.reset_time(now)
            elif rule.algorithm == RateLimitAlgorithm.LEAKY_BUCKET:
                if window_key not in self._leaky_buckets:
                    leak_rate = rule.max_requests / rule.window_seconds if rule.window_seconds > 0 else float("inf")
                    self._leaky_buckets[window_key] = LeakyBucket(rule.effective_burst(), leak_rate)
                bucket = self._leaky_buckets[window_key]
                allowed = bucket.consume(count, now)
                remaining = bucket.remaining(now)
                reset_time = bucket.reset_time(now)
            else:
                allowed = True
                remaining = rule.max_requests
                reset_time = now + rule.window_seconds
            limit = rule.max_requests
            retry_after = 0.0
            violated = False
            if not allowed:
                retry_after = max(0.0, reset_time - now)
                backoff_delay = self._compute_backoff(window_key, rule)
                if backoff_delay > 0:
                    retry_after = max(retry_after, backoff_delay)
                violated = True
            return RateLimitResult(
                allowed=allowed, remaining=max(0, remaining),
                reset_time=reset_time, limit=limit,
                retry_after=retry_after, violated=violated
            )

    def _compute_backoff(self, key: str, rule: RateLimitRule) -> float:
        if rule.backoff == BackoffStrategy.NONE:
            return 0.0
        violation_count = self._violation_tracker.get_violation_count(key)
        if violation_count == 0:
            return 0.0
        if rule.backoff == BackoffStrategy.LINEAR:
            return min(rule.backoff_base_delay * violation_count, rule.backoff_max_delay)
        if rule.backoff == BackoffStrategy.EXPONENTIAL:
            return min(rule.backoff_base_delay * (rule.backoff_multiplier ** (violation_count - 1)), rule.backoff_max_delay)
        if rule.backoff == BackoffStrategy.JITTER:
            base = min(rule.backoff_base_delay * (rule.backoff_multiplier ** (violation_count - 1)), rule.backoff_max_delay)
            return base * (0.5 + 0.5 * (hash(key) % 100) / 100.0)
        if rule.backoff == BackoffStrategy.DECORRELATED_JITTER:
            import random
            base = min(rule.backoff_base_delay * (rule.backoff_multiplier ** (violation_count - 1)), rule.backoff_max_delay)
            return min(rule.backoff_max_delay, random.uniform(rule.backoff_base_delay, base * 3))
        return 0.0

    def reset_key(self, key: str, scope: Optional[RateLimitScope] = None,
                  rule_name: Optional[str] = None):
        rule = self._resolve_rule(key, scope, rule_name)
        window_key = self._window_key(key, rule)
        with self._lock:
            self._token_buckets.pop(window_key, None)
            self._sliding_windows.pop(window_key, None)
            self._fixed_windows.pop(window_key, None)
            self._leaky_buckets.pop(window_key, None)
        self._violation_tracker.unban(key)

    def reset_all(self):
        with self._lock:
            self._token_buckets.clear()
            self._sliding_windows.clear()
            self._fixed_windows.clear()
            self._leaky_buckets.clear()
        self._violation_tracker.clear()

    def get_stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            total = self._total_checks
            allowed = self._total_allowed
            denied = self._total_denied
        with self._lock:
            bucket_count = len(self._token_buckets) + len(self._sliding_windows) + len(self._fixed_windows) + len(self._leaky_buckets)
        return {
            "total_checks": total,
            "total_allowed": allowed,
            "total_denied": denied,
            "allow_rate": (allowed / total * 100) if total > 0 else 0.0,
            "deny_rate": (denied / total * 100) if total > 0 else 0.0,
            "active_windows": bucket_count,
            "rules": len(self._rules),
            "violation_tracker": {
                "banned_keys": len(self._violation_tracker.get_banned_keys()),
            }
        }

    def make_limit_headers(self, key: str, scope: Optional[RateLimitScope] = None,
                           rule_name: Optional[str] = None) -> Dict[str, str]:
        result = self.check(key, count=0, scope=scope, rule_name=rule_name)
        return result.to_headers()

    def _build_scope_key(self, user_id: Optional[str] = None, ip: Optional[str] = None,
                         route: Optional[str] = None, scope: RateLimitScope = RateLimitScope.GLOBAL) -> str:
        if scope == RateLimitScope.GLOBAL:
            return "global"
        if scope == RateLimitScope.USER:
            return f"user:{user_id}" if user_id else "global"
        if scope == RateLimitScope.IP:
            return f"ip:{ip}" if ip else "global"
        if scope == RateLimitScope.ROUTE:
            return f"route:{route}" if route else "global"
        if scope == RateLimitScope.USER_IP:
            return f"user_ip:{user_id}:{ip}" if user_id and ip else "global"
        if scope == RateLimitScope.USER_ROUTE:
            return f"user_route:{user_id}:{route}" if user_id and route else "global"
        if scope == RateLimitScope.IP_ROUTE:
            return f"ip_route:{ip}:{route}" if ip and route else "global"
        return "global"

    def check_user(self, user_id: str, count: int = 1) -> RateLimitResult:
        key = self._build_scope_key(user_id=user_id, scope=RateLimitScope.USER)
        return self.check(key, count, scope=RateLimitScope.USER)

    def check_ip(self, ip: str, count: int = 1) -> RateLimitResult:
        key = self._build_scope_key(ip=ip, scope=RateLimitScope.IP)
        return self.check(key, count, scope=RateLimitScope.IP)

    def check_route(self, route: str, count: int = 1) -> RateLimitResult:
        key = self._build_scope_key(route=route, scope=RateLimitScope.ROUTE)
        return self.check(key, count, scope=RateLimitScope.ROUTE)

    def check_user_ip(self, user_id: str, ip: str, count: int = 1) -> RateLimitResult:
        key = self._build_scope_key(user_id=user_id, ip=ip, scope=RateLimitScope.USER_IP)
        return self.check(key, count, scope=RateLimitScope.USER_IP)

    def check_user_route(self, user_id: str, route: str, count: int = 1) -> RateLimitResult:
        key = self._build_scope_key(user_id=user_id, route=route, scope=RateLimitScope.USER_ROUTE)
        return self.check(key, count, scope=RateLimitScope.USER_ROUTE)

    def check_ip_route(self, ip: str, route: str, count: int = 1) -> RateLimitResult:
        key = self._build_scope_key(ip=ip, route=route, scope=RateLimitScope.IP_ROUTE)
        return self.check(key, count, scope=RateLimitScope.IP_ROUTE)

    def get_ban_status(self, key: str) -> Tuple[bool, float]:
        return self._violation_tracker.check_banned(key)

    def ban_key(self, key: str, duration: float = 86400.0):
        self._violation_tracker.ban(key, duration)

    def unban_key(self, key: str):
        self._violation_tracker.unban(key)

    def get_banned_keys(self) -> List[str]:
        return self._violation_tracker.get_banned_keys()

    def get_violations(self, key: str) -> int:
        return self._violation_tracker.get_violation_count(key)

    def middleware_check(self, key: str, scope: RateLimitScope = RateLimitScope.IP,
                         rule_name: Optional[str] = None) -> RateLimitResult:
        return self.check(key, 1, scope, rule_name)

    def wsgi_middleware(self, environ, start_response, app):
        ip = environ.get("REMOTE_ADDR", "unknown")
        path = environ.get("PATH_INFO", "/")
        result = self.check_ip_route(ip, path)
        if not result.allowed:
            status = "429 Too Many Requests"
            headers = [("Content-Type", "text/plain")]
            headers.extend(result.to_headers().items())
            start_response(status, headers)
            return [b"Rate limit exceeded"]
        return app(environ, start_response)

    def asgi_middleware(self, scope, receive, send, app):
        import asyncio

        async def asgi_app(scope, receive, send):
            client = scope.get("client", ("unknown", 0))
            ip = client[0]
            path = scope.get("path", "/")
            result = self.check_ip_route(ip, path)
            if not result.allowed:
                await send({
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"text/plain"),
                    ]
                })
                await send({
                    "type": "http.response.body",
                    "body": b"Rate limit exceeded",
                })
                return
            await app(scope, receive, send)
        return asgi_app

    def _start_cleanup(self):
        self._shutdown_event.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="rate-limiter-cleanup",
            daemon=True
        )
        self._cleanup_thread.start()

    def _cleanup_loop(self):
        while not self._shutdown_event.is_set():
            self._shutdown_event.wait(self.config.cleanup_interval)
            if self._shutdown_event.is_set():
                break
            try:
                self._run_cleanup()
            except Exception as e:
                logger.error("Rate limiter cleanup error: %s", e)

    def _run_cleanup(self):
        now = time.time()
        with self._lock:
            cutoff = self.config.max_tracked_keys
            for store in (self._token_buckets, self._sliding_windows,
                          self._fixed_windows, self._leaky_buckets):
                if len(store) > cutoff:
                    excess = sorted(store.items(), key=lambda x: getattr(x[1], 'last_refill', getattr(x[1], 'window_start', 0)))
                    for key, _ in excess[:len(store) - cutoff]:
                        del store[key]

    def set_config(self, config: RateLimiterConfig):
        old_interval = self.config.cleanup_interval
        self.config = config
        if config.cleanup_interval != old_interval:
            self._start_cleanup()

    def update_config(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                logger.warning("Unknown config key: %s", key)

    def export_rules(self) -> List[Dict[str, Any]]:
        rules = []
        for name, rule in self._rules.items():
            rules.append({
                "name": name,
                "max_requests": rule.max_requests,
                "window_seconds": rule.window_seconds,
                "algorithm": rule.algorithm.name,
                "scope": rule.scope.name,
                "burst_size": rule.burst_size,
                "backoff": rule.backoff.name,
            })
        rules.append({
            "name": "global",
            "max_requests": self._global_rule.max_requests,
            "window_seconds": self._global_rule.window_seconds,
            "algorithm": self._global_rule.algorithm.name,
            "scope": self._global_rule.scope.name,
        })
        return rules

    def import_rules(self, rules: List[Dict[str, Any]]):
        for rule_dict in rules:
            rule = RateLimitRule(
                max_requests=rule_dict.get("max_requests", 100),
                window_seconds=rule_dict.get("window_seconds", 60),
                algorithm=RateLimitAlgorithm[rule_dict.get("algorithm", "SLIDING_WINDOW").upper()],
                scope=RateLimitScope[rule_dict.get("scope", "GLOBAL").upper()],
                burst_size=rule_dict.get("burst_size"),
                backoff=BackoffStrategy[rule_dict.get("backoff", "NONE").upper()],
                name=rule_dict.get("name", f"rule_{len(self._rules)}"),
            )
            self.add_rule(rule)

    def close(self):
        self._shutdown_event.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)
        logger.info("Rate limiter shut down")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
