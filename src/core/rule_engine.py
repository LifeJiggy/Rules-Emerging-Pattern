"""
Main rule engine with tiered architecture, caching, profiling, and full pipeline support.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import traceback
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import aiohttp
import yaml

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

from .engine_config import EngineConfig

logger = logging.getLogger(__name__)


class CacheEntry:
    """Cache entry with metadata for LRU tracking."""

    def __init__(self, key: str, result: ValidationResult, ttl: int = 300):
        self.key = key
        self.result = result
        self.created_at = time.time()
        self.ttl = ttl
        self.access_count = 0
        self.last_access = time.time()

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl

    def access(self) -> None:
        self.access_count += 1
        self.last_access = time.time()

    def age_seconds(self) -> float:
        return time.time() - self.created_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "ttl": self.ttl,
            "access_count": self.access_count,
            "last_access": datetime.fromtimestamp(self.last_access).isoformat(),
            "expired": self.is_expired(),
            "age_seconds": round(self.age_seconds(), 1),
        }


class ProfilingRecord:
    """Performance profiling record for a single evaluation."""

    def __init__(self, request_id: str):
        self.request_id = request_id
        self.stages: Dict[str, float] = {}
        self.total_time_ms: float = 0.0
        self.rules_evaluated: int = 0
        self.rules_triggered: int = 0
        self.tier_times: Dict[str, float] = {}
        self.cache_hit: bool = False
        self.cache_key: Optional[str] = None
        self.error: Optional[str] = None
        self.timestamp: float = time.time()
        self.content_size: int = 0
        self.tier_counts: Dict[str, int] = {}
        self.severity_counts: Dict[str, int] = {}
        self.request_details: Dict[str, Any] = {}

    def record_stage(self, name: str, duration_ms: float) -> None:
        self.stages[name] = duration_ms

    def record_tier(self, tier: str, duration_ms: float) -> None:
        self.tier_times[tier] = duration_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "total_time_ms": round(self.total_time_ms, 2),
            "stages": {k: round(v, 2) for k, v in self.stages.items()},
            "tier_times": {k: round(v, 2) for k, v in self.tier_times.items()},
            "rules_evaluated": self.rules_evaluated,
            "rules_triggered": self.rules_triggered,
            "cache_hit": self.cache_hit,
            "error": self.error,
            "timestamp": self.timestamp,
            "content_size": self.content_size,
            "tier_counts": self.tier_counts,
            "severity_counts": self.severity_counts,
        }


class RuleHotReloader:
    """Monitors rule definition files for changes and triggers reload."""

    def __init__(self, watch_paths: Optional[List[str]] = None):
        self.watch_paths = watch_paths or []
        self.file_hashes: Dict[str, str] = {}
        self.reload_callbacks: List[Callable] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_check_time: float = 0.0
        self._total_changes_detected: int = 0
        self._file_extensions: Set[str] = {".yaml", ".yml", ".json"}

    def add_watch_path(self, path: str) -> None:
        if path not in self.watch_paths:
            self.watch_paths.append(path)
            logger.info(f"Added watch path: {path}")

    def add_reload_callback(self, callback: Callable) -> None:
        self.reload_callbacks.append(callback)

    def set_file_extensions(self, extensions: List[str]) -> None:
        self._file_extensions = set(extensions)

    async def start(self, interval: float = 5.0) -> None:
        if self._running:
            logger.warning("Hot-reloader already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._watch_loop(interval))
        logger.info(f"Hot-reload watcher started with {interval}s interval")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Hot-reload watcher stopped")

    async def force_check(self) -> List[str]:
        changes = self._detect_changes()
        if changes:
            logger.info(f"Detected {len(changes)} changed rule files")
            for callback in self.reload_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(changes)
                    else:
                        callback(changes)
                except Exception as e:
                    logger.error(f"Reload callback failed: {e}")
        return changes

    async def _watch_loop(self, interval: float) -> None:
        while self._running:
            try:
                await asyncio.sleep(interval)
                changes = self._detect_changes()
                if changes:
                    self._total_changes_detected += len(changes)
                    logger.info(f"Detected {len(changes)} changed rule files")
                    for callback in self.reload_callbacks:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(changes)
                            else:
                                callback(changes)
                        except Exception as e:
                            logger.error(f"Reload callback failed: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watch loop error: {e}")

    def _detect_changes(self) -> List[str]:
        changes = []
        for watch_path in self.watch_paths:
            path = Path(watch_path)
            if not path.exists():
                continue
            if path.is_file():
                current_hash = self._hash_file(path)
                stored_hash = self.file_hashes.get(str(path))
                if stored_hash is not None and stored_hash != current_hash:
                    changes.append(str(path))
                self.file_hashes[str(path)] = current_hash
            elif path.is_dir():
                for ext in self._file_extensions:
                    for rule_file in path.glob(f"**/*{ext}"):
                        current_hash = self._hash_file(rule_file)
                        stored_hash = self.file_hashes.get(str(rule_file))
                        if stored_hash is not None and stored_hash != current_hash:
                            changes.append(str(rule_file))
                        self.file_hashes[str(rule_file)] = current_hash
        self._last_check_time = time.time()
        return changes

    def snapshot(self) -> None:
        for watch_path in self.watch_paths:
            path = Path(watch_path)
            if not path.exists():
                continue
            if path.is_file():
                self.file_hashes[str(path)] = self._hash_file(path)
            elif path.is_dir():
                for ext in self._file_extensions:
                    for rule_file in path.glob(f"**/*{ext}"):
                        self.file_hashes[str(rule_file)] = self._hash_file(rule_file)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "watch_paths": self.watch_paths,
            "tracked_files": len(self.file_hashes),
            "total_changes_detected": self._total_changes_detected,
            "last_check_time": datetime.fromtimestamp(self._last_check_time).isoformat() if self._last_check_time else None,
            "callbacks_registered": len(self.reload_callbacks),
        }

    @staticmethod
    def _hash_file(filepath: Path) -> str:
        try:
            return hashlib.sha256(filepath.read_bytes()).hexdigest()[:32]
        except Exception:
            return ""


class WebhookNotifier:
    """Sends webhook notifications for critical violations."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.webhook_urls: List[str] = self.config.get("urls", [])
        self.secret: Optional[str] = self.config.get("secret")
        self.timeout: int = self.config.get("timeout", 10)
        self.max_retries: int = self.config.get("max_retries", 3)
        self._session: Optional[aiohttp.ClientSession] = None
        self._notification_count: int = 0
        self._error_count: int = 0
        self._last_notification_time: Optional[float] = None
        self._rate_limit_window: float = 1.0
        self._last_send_time: float = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def notify_violation(self, violation: Violation, context: Optional[Dict[str, Any]] = None) -> None:
        if not self.webhook_urls:
            return
        now = time.time()
        if now - self._last_send_time < self._rate_limit_window:
            return
        self._last_send_time = now
        payload = self._build_payload(violation, context)
        for url in self.webhook_urls:
            await self._send_with_retry(url, payload)

    async def notify_batch(self, violations: List[Violation], context: Optional[Dict[str, Any]] = None) -> None:
        if not self.webhook_urls or not violations:
            return
        now = time.time()
        if now - self._last_send_time < self._rate_limit_window:
            return
        self._last_send_time = now
        payload = {
            "event": "batch_violations",
            "timestamp": datetime.utcnow().isoformat(),
            "violation_count": len(violations),
            "violations": [self._build_payload(v, context) for v in violations],
            "severity_summary": self._summarize_severities(violations),
        }
        for url in self.webhook_urls:
            await self._send_with_retry(url, payload)

    def _build_payload(self, violation: Violation, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "event": "rule_violation",
            "timestamp": datetime.utcnow().isoformat(),
            "rule_id": violation.rule_id,
            "rule_name": violation.rule_name,
            "rule_tier": violation.rule_tier.value if hasattr(violation.rule_tier, "value") else str(violation.rule_tier),
            "severity": violation.rule_severity.value if hasattr(violation.rule_severity, "value") else str(violation.rule_severity),
            "violation_type": violation.violation_type.value if hasattr(violation.violation_type, "value") else str(violation.violation_type),
            "action_taken": violation.action_taken.value if hasattr(violation.action_taken, "value") else str(violation.action_taken),
            "blocked": violation.blocked,
            "explanation": violation.explanation,
            "confidence": violation.confidence_score,
            "context": context or {},
        }

    async def _send_with_retry(self, url: str, payload: Dict[str, Any]) -> None:
        last_error = None
        for attempt in range(self.max_retries):
            try:
                session = await self._get_session()
                headers = {"Content-Type": "application/json"}
                if self.secret:
                    headers["X-Webhook-Secret"] = self.secret
                async with session.post(url, json=payload, headers=headers, timeout=self.timeout) as response:
                    if response.status >= 400:
                        logger.warning(f"Webhook {url} returned {response.status} (attempt {attempt + 1})")
                        last_error = f"HTTP {response.status}"
                    else:
                        self._notification_count += 1
                        logger.debug(f"Webhook notification sent to {url}")
                        return
            except asyncio.TimeoutError as e:
                last_error = f"Timeout: {e}"
                logger.warning(f"Webhook {url} timeout (attempt {attempt + 1})")
            except aiohttp.ClientError as e:
                last_error = f"ClientError: {e}"
                logger.warning(f"Webhook {url} client error (attempt {attempt + 1})")
            except Exception as e:
                last_error = str(e)
                logger.error(f"Webhook {url} error (attempt {attempt + 1}): {e}")
            if attempt < self.max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
        self._error_count += 1
        logger.error(f"Webhook {url} failed after {self.max_retries} attempts: {last_error}")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "notification_count": self._notification_count,
            "error_count": self._error_count,
            "webhook_urls": self.webhook_urls,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
        }

    @staticmethod
    def _summarize_severities(violations: List[Violation]) -> Dict[str, int]:
        summary: Dict[str, int] = {}
        for v in violations:
            sev = v.rule_severity.value if hasattr(v.rule_severity, "value") else str(v.rule_severity)
            summary[sev] = summary.get(sev, 0) + 1
        return summary

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class BatchProcessor:
    """Processes batches of evaluation requests with concurrency control."""

    def __init__(self, engine: "RuleEngine", max_concurrency: int = 10):
        self.engine = engine
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._total_batches: int = 0
        self._total_items: int = 0
        self._total_errors: int = 0
        self._avg_batch_time_ms: float = 0.0

    async def process(
        self,
        requests: List[RuleEvaluationRequest],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        return_exceptions: bool = False,
    ) -> List[ValidationResult]:
        if not requests:
            return []
        batch_start = time.time()
        total = len(requests)
        self._total_batches += 1
        self._total_items += total
        logger.info(f"BatchProcessor: processing {total} requests")

        async def process_one(index: int, request: RuleEvaluationRequest) -> Tuple[int, Optional[ValidationResult]]:
            async with self._semaphore:
                try:
                    result = await self.engine.evaluate(request)
                    return index, result
                except Exception as e:
                    self._total_errors += 1
                    logger.error(f"Batch item {index} failed: {e}")
                    if return_exceptions:
                        return index, None
                    return index, self.engine._create_error_result(request, str(e), time.time())

        tasks = [process_one(i, req) for i, req in enumerate(requests)]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        results: List[Optional[ValidationResult]] = [None] * total
        for item in completed:
            if isinstance(item, Exception):
                logger.error(f"Unexpected batch error: {item}")
                continue
            if isinstance(item, tuple) and len(item) == 2:
                index, result = item
                if index is not None and index < total:
                    results[index] = result

        for i in range(total):
            if results[i] is None:
                results[i] = self.engine._create_error_result(
                    requests[i], "Unexpected batch processing error", time.time()
                )

        if progress_callback:
            progress_callback(total, total)

        batch_duration = (time.time() - batch_start) * 1000
        if self._total_batches == 1:
            self._avg_batch_time_ms = batch_duration
        else:
            self._avg_batch_time_ms = (
                (self._avg_batch_time_ms * (self._total_batches - 1) + batch_duration) / self._total_batches
            )

        valid_list: List[ValidationResult] = []
        for r in results:
            if r is not None:
                valid_list.append(r)

        logger.info(f"BatchProcessor: {len(valid_list)}/{total} completed in {batch_duration:.0f}ms")
        return valid_list

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_batches": self._total_batches,
            "total_items": self._total_items,
            "total_errors": self._total_errors,
            "average_batch_time_ms": round(self._avg_batch_time_ms, 2),
            "max_concurrency": self.max_concurrency,
            "error_rate": round((self._total_errors / max(self._total_items, 1)) * 100, 2),
        }


class RuleEngine:
    """Main rule engine with tiered architecture and comprehensive evaluation."""

    def __init__(self, rule_manager=None, config: Optional[Dict[str, Any]] = None):
        self.rule_manager = rule_manager
        self.engine_config = EngineConfig(config or {})

        self.evaluation_stats: Dict[str, Any] = {
            "total_evaluations": 0,
            "successful_evaluations": 0,
            "failed_evaluations": 0,
            "average_time_ms": 0.0,
            "violations_detected": 0,
            "blocks_applied": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_processing_time_ms": 0,
            "warnings_issued": 0,
            "suggestions_generated": 0,
            "evaluations_by_tier": {},
            "evaluations_by_severity": {},
            "peak_time_ms": 0.0,
            "min_time_ms": float("inf"),
            "evaluations_by_rule_type": {},
            "start_time": time.time(),
        }

        self.executor = ThreadPoolExecutor(
            max_workers=self.engine_config.get_int("engine.max_workers", 10)
        )
        self.evaluation_cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.cache_max_size = self.engine_config.get_int("engine.cache_size", 1000)
        self.cache_ttl = self.engine_config.get_int("engine.cache_ttl", 300)

        self.tier_engines: Dict[str, Any] = {}
        self._initialize_tier_engines()

        self.profiling_records: List[ProfilingRecord] = []
        self.profiling_enabled = self.engine_config.get_bool("engine.profiling_enabled", True)
        self.profiling_max_records = self.engine_config.get_int("engine.profiling_max_records", 10000)

        self.batch_processor = BatchProcessor(
            self,
            max_concurrency=self.engine_config.get_int("engine.batch_concurrency", 10),
        )

        self.hot_reloader: Optional[RuleHotReloader] = None
        if self.engine_config.get_bool("engine.hot_reload_enabled", False):
            self.hot_reloader = RuleHotReloader(
                self.engine_config.get_list("engine.hot_reload_paths", [])
            )
            self.hot_reloader.add_reload_callback(self._on_rules_changed)

        self.webhook_notifier: Optional[WebhookNotifier] = None
        if self.engine_config.get_bool("engine.webhook_enabled", False):
            self.webhook_notifier = WebhookNotifier({
                "urls": self.engine_config.get_list("engine.webhook_urls", []),
                "secret": self.engine_config.get("engine.webhook_secret"),
                "timeout": self.engine_config.get_int("engine.webhook_timeout", 10),
                "max_retries": self.engine_config.get_int("engine.webhook_max_retries", 3),
            })

        self._shutdown_event = asyncio.Event()
        self._stats_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()
        self._hot_reload_started = False

        self._post_process_hooks: List[Callable] = []
        self._pre_evaluate_hooks: List[Callable] = []
        self._evaluation_counters: Dict[str, int] = {}

        logger.info(
            f"RuleEngine initialized: max_workers={self.engine_config.get_int('engine.max_workers', 10)}, "
            f"cache_size={self.cache_max_size}, profiling={self.profiling_enabled}"
        )

    def _initialize_tier_engines(self) -> None:
        try:
            from .tiered_rules.safety_engine import SafetyRuleEngine
            from .tiered_rules.operational_engine import OperationalRuleEngine
            from .tiered_rules.preference_engine import PreferenceRuleEngine

            self.tier_engines[RuleTier.SAFETY] = SafetyRuleEngine()
            self.tier_engines[RuleTier.OPERATIONAL] = OperationalRuleEngine()
            self.tier_engines[RuleTier.PREFERENCE] = PreferenceRuleEngine()
            logger.info("Tier-specific engines initialized successfully")
        except ImportError as e:
            logger.warning(f"Could not initialize tier engines: {e}")
        except Exception as e:
            logger.error(f"Tier engine initialization failed: {e}")

    def add_pre_evaluate_hook(self, hook: Callable[[RuleEvaluationRequest], RuleEvaluationRequest]) -> None:
        self._pre_evaluate_hooks.append(hook)

    def add_post_process_hook(self, hook: Callable[[ValidationResult], ValidationResult]) -> None:
        self._post_process_hooks.append(hook)

    async def start(self) -> None:
        if self.hot_reloader and not self._hot_reload_started:
            await self.hot_reloader.start(
                interval=self.engine_config.get_float("engine.hot_reload_interval", 5.0)
            )
            self._hot_reload_started = True
            logger.info("Hot-reload service started")
        logger.info("RuleEngine background services started")

    async def evaluate(self, request: RuleEvaluationRequest) -> ValidationResult:
        start_time = time.time()
        profile: Optional[ProfilingRecord] = None

        for hook in self._pre_evaluate_hooks:
            try:
                request = hook(request)
            except Exception as e:
                logger.error(f"Pre-evaluate hook failed: {e}")

        if self.profiling_enabled:
            profile = ProfilingRecord(self._generate_request_id())
            profile.content_size = len(request.content)

        try:
            content_hash = self._get_content_hash(request.content)
            cached_result = await self._get_cached_result_async(content_hash, request.context)
            if cached_result:
                async with self._stats_lock:
                    self.evaluation_stats["cache_hits"] += 1
                if profile:
                    profile.cache_hit = True
                logger.debug(f"Cache hit for content hash: {content_hash}")
                return cached_result

            async with self._stats_lock:
                self.evaluation_stats["cache_misses"] += 1

            applicable_rules = self._get_applicable_rules(request)
            if not applicable_rules:
                result = self._create_empty_result(request, start_time)
                if profile:
                    profile.total_time_ms = (time.time() - start_time) * 1000
                    profile.rules_evaluated = 0
                return result

            pre_filter_enabled = self.engine_config.get_bool("engine.enable_pre_filter", True)
            if pre_filter_enabled:
                pre_filter_start = time.time()
                applicable_rules = self._pre_filter_rules(applicable_rules, request)
                if profile:
                    profile.record_stage("pre_filter", (time.time() - pre_filter_start) * 1000)

            evaluate_start = time.time()
            result = await self._evaluate_by_tiers(request, applicable_rules)
            if profile:
                profile.record_stage("evaluate", (time.time() - evaluate_start) * 1000)

            post_process_enabled = self.engine_config.get_bool("engine.enable_post_process", True)
            if post_process_enabled:
                post_process_start = time.time()
                result = self._post_process_result(result, request)
                if profile:
                    profile.record_stage("post_process", (time.time() - post_process_start) * 1000)

            for hook in self._post_process_hooks:
                try:
                    result = hook(result)
                except Exception as e:
                    logger.error(f"Post-process hook failed: {e}")

            await self._async_update_statistics(result, start_time)
            await self._cache_result_async(content_hash, request.context, result)

            if result.critical_violations and self.webhook_notifier:
                notify_critical_only = self.engine_config.get_bool("engine.webhook_notify_critical_only", True)
                if notify_critical_only:
                    asyncio.ensure_future(self.webhook_notifier.notify_batch(result.critical_violations))
                else:
                    asyncio.ensure_future(self.webhook_notifier.notify_batch(result.violations))

            if profile:
                profile.total_time_ms = (time.time() - start_time) * 1000
                profile.rules_evaluated = result.total_rules_evaluated
                profile.rules_triggered = result.rules_triggered
                if applicable_rules:
                    for rule in applicable_rules:
                        tier_str = rule.tier.value if hasattr(rule.tier, "value") else str(rule.tier)
                        profile.tier_counts[tier_str] = profile.tier_counts.get(tier_str, 0) + 1
                for v in result.violations:
                    sev = v.rule_severity.value if hasattr(v.rule_severity, "value") else str(v.rule_severity)
                    profile.severity_counts[sev] = profile.severity_counts.get(sev, 0) + 1
                self._record_profile(profile)

            return result

        except Exception as e:
            logger.error(f"Rule evaluation failed: {e}\n{traceback.format_exc()}")
            async with self._stats_lock:
                self.evaluation_stats["failed_evaluations"] += 1
            if profile:
                profile.error = str(e)
                profile.total_time_ms = (time.time() - start_time) * 1000
                self._record_profile(profile)
            return self._create_error_result(request, str(e), start_time)

    async def evaluate_batch(
        self,
        requests: List[RuleEvaluationRequest],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[ValidationResult]:
        return await self.batch_processor.process(requests, progress_callback=progress_callback)

    async def evaluate_batch_with_progress(
        self,
        requests: List[RuleEvaluationRequest],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[ValidationResult]:
        return await self.batch_processor.process(requests, progress_callback=progress_callback)

    async def evaluate_tiered(self, request: RuleEvaluationRequest) -> ValidationResult:
        start_time = time.time()
        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
            request_id=self._generate_request_id(),
            content_hash=self._get_content_hash(request.content),
        )
        for tier in [RuleTier.SAFETY, RuleTier.OPERATIONAL, RuleTier.PREFERENCE]:
            if request.tier and request.tier != tier:
                continue
            tier_engine = self.tier_engines.get(tier)
            if not tier_engine:
                continue
            try:
                tier_start = time.time()
                tier_result = await tier_engine.evaluate(request)
                tier_duration = (time.time() - tier_start) * 1000
                self._merge_tier_result(result, tier_result)
                if tier == RuleTier.SAFETY and result.is_blocked():
                    logger.info("Early termination due to safety violation")
                    break
            except Exception as e:
                logger.error(f"Tier {tier} evaluation failed: {e}")
        result.processing_time_ms = int((time.time() - start_time) * 1000)
        result.evaluated_at = datetime.utcnow()
        return result

    def _get_applicable_rules(self, request: RuleEvaluationRequest) -> List[Rule]:
        if not self.rule_manager:
            return []
        if request.rule_ids:
            rules = []
            for rule_id in request.rule_ids:
                rule = self.rule_manager.get_rule(rule_id)
                if rule and rule.status.value == "active":
                    rules.append(rule)
            return rules
        if request.tier:
            return self.rule_manager.get_rules_by_tier(request.tier)
        if request.rule_types:
            rules = []
            for rule_type in request.rule_types:
                rules.extend(self.rule_manager.get_rules_by_type(rule_type))
            return rules
        context = request.get_context()
        return self.rule_manager.get_applicable_rules(context)

    def _pre_filter_rules(self, rules: List[Rule], request: RuleEvaluationRequest) -> List[Rule]:
        if not rules:
            return rules
        filtered = []
        context = request.get_context().get_effective_context() if request.context else {}
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        min_severity = request.options.get("min_severity")
        for rule in rules:
            if rule.status != RuleStatus.ACTIVE:
                continue
            if min_severity:
                rule_sev = rule.severity.value if hasattr(rule.severity, "value") else str(rule.severity)
                if severity_order.get(rule_sev, 0) < severity_order.get(min_severity, 0):
                    continue
            if not rule.is_applicable_to_context(context):
                continue
            filtered.append(rule)
        return filtered

    def _post_process_result(self, result: ValidationResult, request: RuleEvaluationRequest) -> ValidationResult:
        result.total_rules_evaluated = max(result.total_rules_evaluated, len(result.violations))
        result.rules_triggered = len(result.violations)
        result.rules_violated = len([v for v in result.violations if v.action_taken != ActionTaken.NONE])
        if result.violations:
            has_block = any(v.blocked for v in result.violations)
            result.valid = not has_block
        self._deduplicate_violations(result)
        if result.warnings:
            seen = set()
            unique_warnings = []
            for w in result.warnings:
                key = (w.rule_id, w.violation_type.value if hasattr(w.violation_type, "value") else str(w.violation_type))
                if key not in seen:
                    seen.add(key)
                    unique_warnings.append(w)
            result.warnings = unique_warnings
        return result

    @staticmethod
    def _deduplicate_violations(result: ValidationResult) -> None:
        if not result.violations:
            return
        seen = set()
        unique_violations = []
        unique_critical = []
        for v in result.violations:
            key = (
                v.rule_id,
                v.matched_content,
                v.violation_type.value if hasattr(v.violation_type, "value") else str(v.violation_type),
            )
            if key not in seen:
                seen.add(key)
                unique_violations.append(v)
                if v.is_critical():
                    unique_critical.append(v)
        result.violations = unique_violations
        result.critical_violations = unique_critical

    async def _evaluate_by_tiers(self, request: RuleEvaluationRequest, rules: List[Rule]) -> ValidationResult:
        start_time = time.time()
        rules_by_tier: Dict[RuleTier, List[Rule]] = {}
        for rule in rules:
            tier = rule.tier
            if tier not in rules_by_tier:
                rules_by_tier[tier] = []
            rules_by_tier[tier].append(rule)
        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
            request_id=self._generate_request_id(),
            content_hash=self._get_content_hash(request.content),
        )
        tier_order = [RuleTier.SAFETY, RuleTier.OPERATIONAL, RuleTier.PREFERENCE]
        for tier in tier_order:
            if tier not in rules_by_tier:
                continue
            tier_rules = rules_by_tier[tier]
            tier_engine = self.tier_engines.get(tier)
            tier_start = time.time()
            if tier_engine:
                tier_request = RuleEvaluationRequest(
                    content=request.content,
                    context=request.context,
                    rule_ids=[rule.id for rule in tier_rules],
                    options=request.options,
                )
                try:
                    tier_result = await tier_engine.evaluate(tier_request)
                    self._merge_tier_result(result, tier_result)
                    if tier == RuleTier.SAFETY and result.is_blocked():
                        logger.info("Early termination due to safety violation")
                        break
                except Exception as e:
                    logger.error(f"Tier {tier} engine failed: {e}")
                    await self._evaluate_rules_directly(result, tier_rules, request)
            else:
                await self._evaluate_rules_directly(result, tier_rules, request)
            tier_duration = (time.time() - tier_start) * 1000
            if self.profiling_enabled:
                profile_tier_name = tier.value if hasattr(tier, "value") else str(tier)
        result.processing_time_ms = int((time.time() - start_time) * 1000)
        result.evaluated_at = datetime.utcnow()
        result.total_rules_evaluated = len(rules)
        result.rules_triggered = len(result.violations)
        result.rules_violated = len([v for v in result.violations if v.action_taken != ActionTaken.NONE])
        return result

    async def _evaluate_rules_directly(
        self, result: ValidationResult, rules: List[Rule], request: RuleEvaluationRequest
    ) -> None:
        for rule in rules:
            try:
                violation = await self._evaluate_single_rule(rule, request.content, request.context)
                if violation:
                    result.violations.append(violation)
                    if violation.is_critical():
                        result.critical_violations.append(violation)
                    if violation.action_taken == ActionTaken.WARNING:
                        result.warnings.append(violation)
                    if violation.blocked:
                        result.valid = False
            except Exception as e:
                logger.error(f"Rule {rule.id} evaluation failed: {e}")

    async def _evaluate_single_rule(
        self, rule: Rule, content: str, context: Optional[RuleContext]
    ) -> Optional[Violation]:
        if context and not rule.is_applicable_to_context(context.get_effective_context()):
            return None
        for pattern in rule.patterns:
            if pattern.keywords:
                content_lower = content.lower()
                for keyword in pattern.keywords:
                    if keyword.lower() in content_lower:
                        return Violation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            rule_tier=rule.tier,
                            rule_severity=rule.severity,
                            violation_type=ViolationType.KEYWORD_MATCH,
                            matched_content=keyword,
                            matched_patterns=[keyword],
                            confidence_score=0.8,
                            action_taken=self._get_action_for_rule(rule),
                            blocked=rule.auto_block,
                            user_override_allowed=rule.user_override,
                            explanation=f"Content contains prohibited keyword: {keyword}",
                            context=context.get_effective_context() if context else {},
                        )
            if pattern.regex_patterns:
                for regex_str in pattern.regex_patterns:
                    try:
                        if re.search(regex_str, content, re.IGNORECASE):
                            return Violation(
                                rule_id=rule.id,
                                rule_name=rule.name,
                                rule_tier=rule.tier,
                                rule_severity=rule.severity,
                                violation_type=ViolationType.REGEX_MATCH,
                                matched_content=regex_str,
                                matched_patterns=[regex_str],
                                confidence_score=0.9,
                                action_taken=self._get_action_for_rule(rule),
                                blocked=rule.auto_block,
                                user_override_allowed=rule.user_override,
                                explanation=f"Content matches prohibited pattern: {regex_str}",
                                context=context.get_effective_context() if context else {},
                            )
                    except re.error as e:
                        logger.warning(f"Invalid regex pattern '{regex_str}' in rule {rule.id}: {e}")
        return None

    def _get_action_for_rule(self, rule: Rule) -> ActionTaken:
        level = rule.enforcement_level.value if hasattr(rule.enforcement_level, "value") else str(rule.enforcement_level)
        if level == "strict":
            return ActionTaken.BLOCK
        elif level == "advisory":
            return ActionTaken.WARNING
        elif level == "adaptive":
            return ActionTaken.SUGGESTION
        else:
            return ActionTaken.NONE

    def _merge_tier_result(self, main_result: ValidationResult, tier_result: ValidationResult) -> None:
        main_result.violations.extend(tier_result.violations)
        main_result.critical_violations.extend(tier_result.critical_violations)
        main_result.warnings.extend(tier_result.warnings)
        main_result.suggestions.extend(tier_result.suggestions)
        if not tier_result.valid:
            main_result.valid = False
        main_result.total_score = min(main_result.total_score, tier_result.total_score)
        main_result.confidence = (main_result.confidence + tier_result.confidence) / 2

    def _get_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    async def _get_cached_result_async(
        self, content_hash: str, context: Optional[RuleContext]
    ) -> Optional[ValidationResult]:
        cache_key = f"{content_hash}:{hash(str(context)) if context else 'no_context'}"
        async with self._cache_lock:
            if cache_key in self.evaluation_cache:
                entry = self.evaluation_cache[cache_key]
                if not entry.is_expired():
                    entry.access()
                    self.evaluation_cache.move_to_end(cache_key)
                    return entry.result
                else:
                    del self.evaluation_cache[cache_key]
        return None

    async def _cache_result_async(
        self, content_hash: str, context: Optional[RuleContext], result: ValidationResult
    ) -> None:
        cache_key = f"{content_hash}:{hash(str(context)) if context else 'no_context'}"
        async with self._cache_lock:
            if len(self.evaluation_cache) >= self.cache_max_size:
                lru_key, _ = next(iter(self.evaluation_cache.items()))
                del self.evaluation_cache[lru_key]
                logger.debug(f"LRU eviction: removed cache entry {lru_key}")
            self.evaluation_cache[cache_key] = CacheEntry(
                key=cache_key, result=result, ttl=self.cache_ttl,
            )
            self.evaluation_cache.move_to_end(cache_key)

    def _get_cached_result(self, content_hash: str, context: Optional[RuleContext]) -> Optional[ValidationResult]:
        cache_key = f"{content_hash}:{hash(str(context)) if context else 'no_context'}"
        if cache_key in self.evaluation_cache:
            entry = self.evaluation_cache[cache_key]
            if not entry.is_expired():
                entry.access()
                self.evaluation_cache.move_to_end(cache_key)
                return entry.result
            else:
                del self.evaluation_cache[cache_key]
        return None

    def _cache_result(self, content_hash: str, context: Optional[RuleContext], result: ValidationResult) -> None:
        cache_key = f"{content_hash}:{hash(str(context)) if context else 'no_context'}"
        if len(self.evaluation_cache) >= self.cache_max_size:
            lru_key, _ = next(iter(self.evaluation_cache.items()))
            del self.evaluation_cache[lru_key]
        self.evaluation_cache[cache_key] = CacheEntry(
            key=cache_key, result=result, ttl=self.cache_ttl,
        )
        self.evaluation_cache.move_to_end(cache_key)

    def _create_empty_result(self, request: RuleEvaluationRequest, start_time: float) -> ValidationResult:
        return ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
            processing_time_ms=int((time.time() - start_time) * 1000),
            request_id=self._generate_request_id(),
            content_hash=self._get_content_hash(request.content),
            evaluated_at=datetime.utcnow(),
        )

    def _create_error_result(self, request: RuleEvaluationRequest, error: str, start_time: float) -> ValidationResult:
        return ValidationResult(
            valid=False,
            total_score=0.0,
            confidence=0.0,
            processing_time_ms=int((time.time() - start_time) * 1000),
            request_id=self._generate_request_id(),
            content_hash=self._get_content_hash(request.content),
            evaluated_at=datetime.utcnow(),
            violations=[
                Violation(
                    rule_id="system_error",
                    rule_name="System Error",
                    rule_tier=RuleTier.SAFETY,
                    rule_severity=RuleSeverity.CRITICAL,
                    violation_type=ViolationType.CUSTOM_VIOLATION,
                    confidence_score=1.0,
                    action_taken=ActionTaken.BLOCK,
                    blocked=True,
                    user_override_allowed=False,
                    explanation=f"Evaluation failed: {error}",
                    context={},
                )
            ],
        )

    def _generate_request_id(self) -> str:
        return f"req_{int(time.time() * 1000)}_{hash(time.time()) % 10000}"

    def _update_statistics(self, result: ValidationResult, start_time: float) -> None:
        self.evaluation_stats["total_evaluations"] += 1
        if result.valid:
            self.evaluation_stats["successful_evaluations"] += 1
        else:
            self.evaluation_stats["failed_evaluations"] += 1
        processing_time = (time.time() - start_time) * 1000
        total_evals = self.evaluation_stats["total_evaluations"]
        current_avg = self.evaluation_stats["average_time_ms"]
        self.evaluation_stats["average_time_ms"] = (
            (current_avg * (total_evals - 1) + processing_time) / total_evals
        )
        self.evaluation_stats["total_processing_time_ms"] += processing_time
        self.evaluation_stats["peak_time_ms"] = max(self.evaluation_stats["peak_time_ms"], processing_time)
        self.evaluation_stats["min_time_ms"] = min(self.evaluation_stats["min_time_ms"], processing_time)
        if result.has_violations():
            self.evaluation_stats["violations_detected"] += len(result.violations)
        if result.is_blocked():
            self.evaluation_stats["blocks_applied"] += 1
        self.evaluation_stats["warnings_issued"] += len(result.warnings)
        self.evaluation_stats["suggestions_generated"] += len(result.suggestions)

    async def _async_update_statistics(self, result: ValidationResult, start_time: float) -> None:
        async with self._stats_lock:
            self._update_statistics(result, start_time)

    def get_statistics(self) -> Dict[str, Any]:
        stats = self.evaluation_stats.copy()
        stats["cache_size"] = len(self.evaluation_cache)
        stats["cache_max_size"] = self.cache_max_size
        stats["profiling_records_count"] = len(self.profiling_records)
        stats["hot_reload_enabled"] = self.hot_reloader is not None
        stats["webhook_enabled"] = self.webhook_notifier is not None
        stats["tier_engines_loaded"] = len(self.tier_engines)
        stats["uptime_seconds"] = round(time.time() - self.evaluation_stats.get("start_time", time.time()), 1)
        if self.hot_reloader:
            stats["hot_reloader_stats"] = self.hot_reloader.get_stats()
        if self.webhook_notifier:
            stats["webhook_stats"] = self.webhook_notifier.get_stats()
        stats["batch_processor_stats"] = self.batch_processor.get_stats()
        return stats

    def export_statistics_json(self, filepath: Optional[str] = None) -> Dict[str, Any]:
        stats = self.get_statistics()
        if filepath:
            with open(filepath, "w") as f:
                json.dump(stats, f, indent=2, default=str)
            logger.info(f"Statistics exported to {filepath}")
        return stats

    def export_statistics_prometheus(self) -> str:
        stats = self.get_statistics()
        lines = [
            "# HELP rule_engine_total_evaluations Total number of evaluations",
            "# TYPE rule_engine_total_evaluations counter",
            f"rule_engine_total_evaluations {stats['total_evaluations']}",
            "# HELP rule_engine_successful_evaluations Successful evaluations",
            "# TYPE rule_engine_successful_evaluations counter",
            f"rule_engine_successful_evaluations {stats['successful_evaluations']}",
            "# HELP rule_engine_failed_evaluations Failed evaluations",
            "# TYPE rule_engine_failed_evaluations counter",
            f"rule_engine_failed_evaluations {stats['failed_evaluations']}",
            "# HELP rule_engine_average_time_ms Average processing time",
            "# TYPE rule_engine_average_time_ms gauge",
            f"rule_engine_average_time_ms {stats['average_time_ms']}",
            "# HELP rule_engine_violations_detected Total violations detected",
            "# TYPE rule_engine_violations_detected counter",
            f"rule_engine_violations_detected {stats['violations_detected']}",
            "# HELP rule_engine_blocks_applied Total blocks applied",
            "# TYPE rule_engine_blocks_applied counter",
            f"rule_engine_blocks_applied {stats['blocks_applied']}",
            "# HELP rule_engine_cache_hits Cache hit count",
            "# TYPE rule_engine_cache_hits counter",
            f"rule_engine_cache_hits {stats.get('cache_hits', 0)}",
            "# HELP rule_engine_cache_misses Cache miss count",
            "# TYPE rule_engine_cache_misses counter",
            f"rule_engine_cache_misses {stats.get('cache_misses', 0)}",
            "# HELP rule_engine_cache_size Current cache size",
            "# TYPE rule_engine_cache_size gauge",
            f"rule_engine_cache_size {stats['cache_size']}",
            "# HELP rule_engine_peak_time_ms Peak processing time",
            "# TYPE rule_engine_peak_time_ms gauge",
            f"rule_engine_peak_time_ms {stats.get('peak_time_ms', 0)}",
            "# HELP rule_engine_warnings_issued Total warnings issued",
            "# TYPE rule_engine_warnings_issued counter",
            f"rule_engine_warnings_issued {stats.get('warnings_issued', 0)}",
            "# HELP rule_engine_suggestions_generated Total suggestions generated",
            "# TYPE rule_engine_suggestions_generated counter",
            f"rule_engine_suggestions_generated {stats.get('suggestions_generated', 0)}",
            "# HELP rule_engine_uptime_seconds Engine uptime",
            "# TYPE rule_engine_uptime_seconds gauge",
            f"rule_engine_uptime_seconds {stats.get('uptime_seconds', 0)}",
            "",
        ]
        return "\n".join(lines)

    def export_statistics_all(self, directory: str) -> Dict[str, str]:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        json_path = path / "statistics.json"
        prom_path = path / "statistics.prom"
        json_result = self.export_statistics_json(str(json_path))
        prom_result = self.export_statistics_prometheus()
        with open(prom_path, "w") as f:
            f.write(prom_result)
        logger.info(f"Statistics exported to {directory}")
        return {"json": str(json_path), "prometheus": str(prom_path)}

    def clear_cache(self) -> None:
        self.evaluation_cache.clear()
        logger.info("Evaluation cache cleared")

    def clear_cache_by_pattern(self, pattern: str) -> int:
        removed = 0
        keys_to_remove = [k for k in self.evaluation_cache if pattern in k]
        for key in keys_to_remove:
            del self.evaluation_cache[key]
            removed += 1
        if removed:
            logger.info(f"Removed {removed} cache entries matching pattern '{pattern}'")
        return removed

    def get_cache_info(self) -> Dict[str, Any]:
        total_accesses = self.evaluation_stats.get("cache_hits", 0) + self.evaluation_stats.get("cache_misses", 0)
        hit_rate = 0.0
        if total_accesses > 0:
            hit_rate = (self.evaluation_stats.get("cache_hits", 0) / total_accesses) * 100
        return {
            "size": len(self.evaluation_cache),
            "max_size": self.cache_max_size,
            "ttl_seconds": self.cache_ttl,
            "hits": self.evaluation_stats.get("cache_hits", 0),
            "misses": self.evaluation_stats.get("cache_misses", 0),
            "hit_rate_percent": round(hit_rate, 2),
            "entries": [
                {
                    "key": entry.key,
                    "age_seconds": round(time.time() - entry.created_at, 1),
                    "access_count": entry.access_count,
                }
                for entry in self.evaluation_cache.values()
            ][:50],
        }

    def get_profiling_data(self, limit: int = 100) -> List[Dict[str, Any]]:
        records = self.profiling_records[-limit:]
        return [r.to_dict() for r in records]

    def get_profiling_summary(self) -> Dict[str, Any]:
        if not self.profiling_records:
            return {"message": "No profiling records available", "enabled": self.profiling_enabled}
        total_times = [r.total_time_ms for r in self.profiling_records]
        cache_hits = sum(1 for r in self.profiling_records if r.cache_hit)
        errors = sum(1 for r in self.profiling_records if r.error)
        stage_totals: Dict[str, List[float]] = {}
        for record in self.profiling_records:
            for stage, duration in record.stages.items():
                if stage not in stage_totals:
                    stage_totals[stage] = []
                stage_totals[stage].append(duration)
        tier_totals: Dict[str, List[float]] = {}
        for record in self.profiling_records:
            for tier, duration in record.tier_times.items():
                if tier not in tier_totals:
                    tier_totals[tier] = []
                tier_totals[tier].append(duration)
        sorted_times = sorted(total_times)
        return {
            "total_records": len(self.profiling_records),
            "cache_hit_rate_percent": round((cache_hits / len(self.profiling_records)) * 100, 2) if self.profiling_records else 0,
            "error_rate_percent": round((errors / len(self.profiling_records)) * 100, 2) if self.profiling_records else 0,
            "average_total_time_ms": round(sum(total_times) / len(total_times), 2) if total_times else 0,
            "min_total_time_ms": round(min(total_times), 2) if total_times else 0,
            "max_total_time_ms": round(max(total_times), 2) if total_times else 0,
            "p50_total_time_ms": round(sorted_times[len(sorted_times) // 2], 2) if sorted_times else 0,
            "p95_total_time_ms": round(sorted_times[int(len(sorted_times) * 0.95)], 2) if sorted_times else 0,
            "p99_total_time_ms": round(sorted_times[int(len(sorted_times) * 0.99)], 2) if sorted_times else 0,
            "stages": {
                stage: {
                    "average_ms": round(sum(times) / len(times), 2),
                    "total_ms": round(sum(times), 2),
                    "count": len(times),
                }
                for stage, times in stage_totals.items()
            },
            "tiers": {
                tier: {
                    "average_ms": round(sum(times) / len(times), 2),
                    "total_ms": round(sum(times), 2),
                    "count": len(times),
                }
                for tier, times in tier_totals.items()
            },
        }

    def _record_profile(self, record: ProfilingRecord) -> None:
        self.profiling_records.append(record)
        if len(self.profiling_records) > self.profiling_max_records:
            self.profiling_records = self.profiling_records[-self.profiling_max_records:]

    async def reload_rules(self, filepath: Optional[str] = None) -> bool:
        if not self.rule_manager:
            logger.warning("No rule manager available for reload")
            return False
        try:
            if filepath:
                self.rule_manager.load_rules_from_file(filepath)
                logger.info(f"Rules reloaded from {filepath}")
            else:
                self.rule_manager.refresh_rules()
                logger.info("Rules refreshed from rule manager")
            self.clear_cache()
            return True
        except Exception as e:
            logger.error(f"Rule reload failed: {e}")
            return False

    async def _on_rules_changed(self, changed_files: List[str]) -> None:
        logger.info(f"Rule files changed: {changed_files}")
        await self.reload_rules()
        if self.hot_reloader:
            self.hot_reloader.snapshot()
        logger.info("Rules hot-reloaded after file changes")

    def get_tier_engine_status(self) -> Dict[str, Any]:
        status = {}
        for tier, engine in self.tier_engines.items():
            tier_name = tier.value if hasattr(tier, "value") else str(tier)
            try:
                if hasattr(engine, "get_statistics"):
                    status[tier_name] = {
                        "available": True,
                        "type": type(engine).__name__,
                        "statistics": engine.get_statistics(),
                    }
                else:
                    status[tier_name] = {
                        "available": True,
                        "type": type(engine).__name__,
                    }
            except Exception as e:
                status[tier_name] = {
                    "available": False,
                    "error": str(e),
                }
        return status

    async def shutdown(self) -> None:
        logger.info("Shutting down RuleEngine...")
        self._shutdown_event.set()
        if self.hot_reloader:
            await self.hot_reloader.stop()
        if self.webhook_notifier:
            await self.webhook_notifier.close()
        self.executor.shutdown(wait=True)
        self.evaluation_cache.clear()
        self.profiling_records.clear()
        for tier, engine in self.tier_engines.items():
            try:
                if hasattr(engine, "shutdown"):
                    if asyncio.iscoroutinefunction(engine.shutdown):
                        await engine.shutdown()
                    else:
                        engine.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down tier engine {tier}: {e}")
        logger.info("RuleEngine shutdown complete")

    async def health_check(self) -> Dict[str, Any]:
        status = "healthy"
        issues = []
        details: Dict[str, Any] = {}
        try:
            cache_size = len(self.evaluation_cache)
            details["cache_size"] = cache_size
            details["cache_max"] = self.cache_max_size
            if cache_size > self.cache_max_size * 0.9:
                issues.append("Cache near capacity")
        except Exception as e:
            issues.append(f"Cache check failed: {e}")
        try:
            tier_count = len(self.tier_engines)
            details["tier_engines"] = tier_count
            if tier_count == 0:
                issues.append("No tier engines loaded")
        except Exception as e:
            issues.append(f"Tier engine check failed: {e}")
        try:
            stats = self.evaluation_stats
            details["total_evaluations"] = stats["total_evaluations"]
            details["failed_evaluations"] = stats["failed_evaluations"]
            failure_rate = 0
            if stats["total_evaluations"] > 0:
                failure_rate = (stats["failed_evaluations"] / stats["total_evaluations"]) * 100
            details["failure_rate_percent"] = round(failure_rate, 2)
            if failure_rate > 50:
                issues.append(f"High failure rate: {failure_rate:.1f}%")
        except Exception as e:
            issues.append(f"Stats check failed: {e}")
        details["hot_reload"] = self.hot_reloader is not None
        details["webhook"] = self.webhook_notifier is not None
        details["batch_processor"] = self.batch_processor.get_stats()
        details["profiling_enabled"] = self.profiling_enabled
        details["profiling_records"] = len(self.profiling_records)
        if issues:
            status = "degraded"
        return {
            "status": status,
            "engine": "RuleEngine",
            "issues": issues,
            "details": details,
            "timestamp": datetime.utcnow().isoformat(),
        }
