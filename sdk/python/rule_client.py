"""RuleEngineClient - specialized client for rule evaluation operations.

Provides batch evaluation, tier-specific evaluation, caching of rule definitions,
request batching, timeout handling, and error recovery.
"""

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from .client import Client
from .exceptions import (
    APIError,
    ConfigurationError,
    RuleNotFoundError,
    SDKError,
    TimeoutError,
    ValidationError,
)
from .models import (
    BatchValidationRequest,
    BatchValidationResult,
    EnforcementLevel,
    ResolutionStrategy,
    Rule,
    RuleConflict,
    RuleContext,
    RuleEvaluationRequest,
    RuleSet,
    RuleSeverity,
    RuleTier,
    RuleType,
    ValidationResult,
    Violation,
)

logger = logging.getLogger(__name__)


class RuleEngineClient:
    """Specialized client for rule evaluation with caching, batching, and error recovery.

    Provides high-level evaluation methods with built-in caching of rule definitions,
    configurable request batching, per-request timeout control, and automatic
    error recovery strategies.

    Args:
        client: Configured Client instance for API communication.
        cache_enabled: Whether to cache rule definitions locally.
        cache_ttl: Cache TTL in seconds for rule definitions.
        cache_max_size: Maximum number of cached rule definitions.
        default_tier: Default rule tier to evaluate against.
        batch_size: Default batch size for evaluation requests.
        max_retries: Maximum retries for evaluation operations.
        timeout: Default timeout in seconds for evaluation operations.

    Example:
        client = Client(api_key="sk-...")
        engine = RuleEngineClient(client)
        result = engine.evaluate("Some content")
    """

    def __init__(
        self,
        client: Client,
        cache_enabled: bool = True,
        cache_ttl: int = 300,
        cache_max_size: int = 1000,
        default_tier: Optional[RuleTier] = None,
        batch_size: int = 50,
        max_retries: int = 2,
        timeout: int = 30,
    ):
        if not isinstance(client, Client):
            raise ConfigurationError("client must be an instance of Client")

        self._client = client
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        self.cache_max_size = cache_max_size
        self.default_tier = default_tier
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.timeout = timeout

        self._rule_cache: OrderedDict = OrderedDict()
        self._rule_set_cache: OrderedDict = OrderedDict()
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._evaluation_count: int = 0
        self._error_count: int = 0
        self._total_eval_time_ms: float = 0.0
        self._lock = threading.RLock()
        self._evaluation_hooks: List[Callable] = []
        self._recovery_strategies: Dict[str, Callable] = {}
        self._result_transformers: List[Callable] = []

        self._register_default_recovery_strategies()
        logger.info(
            "RuleEngineClient initialized (cache=%s, ttl=%d, batch_size=%d, default_tier=%s)",
            cache_enabled,
            cache_ttl,
            batch_size,
            default_tier.value if default_tier else "none",
        )

    def _register_default_recovery_strategies(self) -> None:
        self._recovery_strategies["retry"] = self._recovery_retry
        self._recovery_strategies["fallback_tier"] = self._recovery_fallback_tier
        self._recovery_strategies["skip_and_log"] = self._recovery_skip

    def _cache_key(self, identifier: str, **params: Any) -> str:
        raw = f"{identifier}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_from_cache(self, cache: OrderedDict, key: str) -> Optional[Any]:
        if not self.cache_enabled:
            return None
        with self._lock:
            if key in cache:
                entry, timestamp = cache[key]
                if time.time() - timestamp < self.cache_ttl:
                    cache.move_to_end(key)
                    self._cache_hits += 1
                    return entry
                del cache[key]
            self._cache_misses += 1
            return None

    def _set_in_cache(self, cache: OrderedDict, key: str, value: Any) -> None:
        if not self.cache_enabled:
            return
        with self._lock:
            cache[key] = (value, time.time())
            if len(cache) > self.cache_max_size:
                cache.popitem(last=False)

    def _invalidate_cache(self, rule_id: Optional[str] = None) -> None:
        with self._lock:
            if rule_id:
                keys_to_remove = [
                    k for k in self._rule_cache if k.startswith(rule_id)
                ]
                for k in keys_to_remove:
                    del self._rule_cache[k]
            else:
                self._rule_cache.clear()
                self._rule_set_cache.clear()
            logger.debug("Cache invalidated (rule=%s)", rule_id or "all")

    def _resolve_tier(self, tier: Optional[RuleTier]) -> RuleTier:
        return tier or self.default_tier or RuleTier.SAFETY

    def _build_context(
        self,
        context: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not context and not options:
            return None
        result: Dict[str, Any] = {}
        if context:
            result.update(context)
        if options:
            result["options"] = options
        return result

    def _measure_time(self) -> float:
        return time.perf_counter()

    def _record_evaluation(self, elapsed_ms: float, success: bool) -> None:
        self._evaluation_count += 1
        self._total_eval_time_ms += elapsed_ms
        if not success:
            self._error_count += 1

    def _run_hooks(self, phase: str, **kwargs: Any) -> None:
        for hook in self._evaluation_hooks:
            try:
                hook(phase=phase, **kwargs)
            except Exception as e:
                logger.warning("Evaluation hook failed at phase '%s': %s", phase, e)

    def _recovery_retry(self, content: str, context: Optional[Dict] = None,
                        options: Optional[Dict] = None) -> Optional[ValidationResult]:
        for attempt in range(self.max_retries):
            try:
                logger.info("Recovery retry %d/%d", attempt + 1, self.max_retries)
                return self._client.evaluate_rules(content, context=context)
            except (APIError, TimeoutError) as e:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(1.0 * (2 ** attempt))
        return None

    def _recovery_fallback_tier(self, content: str, context: Optional[Dict] = None,
                                options: Optional[Dict] = None) -> Optional[ValidationResult]:
        fallback_tiers = [RuleTier.OPERATIONAL, RuleTier.PREFERENCE]
        for tier in fallback_tiers:
            try:
                logger.info("Recovery fallback to tier: %s", tier.value)
                return self._client.evaluate_rules(content, context=context)
            except SDKError:
                continue
        return None

    def _recovery_skip(self, content: str, context: Optional[Dict] = None,
                       options: Optional[Dict] = None) -> Optional[ValidationResult]:
        logger.warning("Recovery skip for content: %s...", content[:50])
        return ValidationResult(
            passed=True,
            warnings=["Evaluation skipped due to error recovery"],
            metadata={"recovery": "skipped"},
        )

    def _apply_result_transformers(self, result: ValidationResult) -> ValidationResult:
        for transformer in self._result_transformers:
            try:
                result = transformer(result)
            except Exception as e:
                logger.warning("Result transformer failed: %s", e)
        return result

    def evaluate(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
        recovery: Optional[str] = None,
    ) -> ValidationResult:
        start = self._measure_time()
        self._run_hooks("before_evaluate", content=content, context=context, options=options)

        ctx = self._build_context(context, options)
        effective_tier = self._resolve_tier(tier)

        try:
            result = self._client.evaluate_rules(
                content=content,
                context=ctx,
                tier=effective_tier,
            )
            success = True
        except (APIError, TimeoutError) as e:
            self._record_evaluation((self._measure_time() - start) * 1000, False)
            recovery_strategy = recovery or "retry"
            handler = self._recovery_strategies.get(recovery_strategy)
            if handler:
                recovered = handler(content, ctx, options)
                if recovered:
                    self._run_hooks("after_recovery", result=recovered, strategy=recovery_strategy)
                    elapsed_ms = (self._measure_time() - start) * 1000
                    self._record_evaluation(elapsed_ms, True)
                    recovered.metadata["recovery_strategy"] = recovery_strategy
                    recovered.processing_time_ms = elapsed_ms
                    return self._apply_result_transformers(recovered)
            elapsed_ms = (self._measure_time() - start) * 1000
            result = ValidationResult(
                passed=False,
                warnings=[f"Evaluation failed: {e}"],
                processing_time_ms=elapsed_ms,
                metadata={"error": str(e), "recovery": recovery_strategy},
            )
            self._record_evaluation(elapsed_ms, False)
            return self._apply_result_transformers(result)

        elapsed_ms = (self._measure_time() - start) * 1000
        result.processing_time_ms = elapsed_ms
        self._record_evaluation(elapsed_ms, success)
        self._run_hooks("after_evaluate", result=result)
        return self._apply_result_transformers(result)

    def evaluate_batch(
        self,
        contents: List[str],
        options: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
        parallel: bool = False,
        max_workers: int = 4,
    ) -> BatchValidationResult:
        start = self._measure_time()
        batch_result = BatchValidationResult()
        effective_tier = self._resolve_tier(tier)

        if not contents:
            return batch_result

        self._run_hooks("before_batch_evaluate", count=len(contents), parallel=parallel)

        if parallel:
            chunks = self._chunk_list(contents, self.batch_size)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for chunk in chunks:
                    future = executor.submit(
                        self._evaluate_chunk, chunk, options, effective_tier
                    )
                    futures.append(future)
                for future in as_completed(futures):
                    try:
                        chunk_result = future.result()
                        for r in chunk_result:
                            batch_result.add_result(r)
                    except Exception as e:
                        logger.error("Batch parallel evaluation chunk failed: %s", e)
                        batch_result.errors.append(str(e))
        else:
            for i, content in enumerate(contents):
                try:
                    result = self.evaluate(content, context=options, tier=effective_tier)
                    batch_result.add_result(result)
                except SDKError as e:
                    logger.error("Batch item %d failed: %s", i, e)
                    batch_result.errors.append(f"Item {i}: {e}")
                    batch_result.add_result(
                        ValidationResult(
                            passed=False,
                            warnings=[f"Evaluation failed: {e}"],
                        )
                    )

        batch_result.total_time_ms = (self._measure_time() - start) * 1000
        self._run_hooks("after_batch_evaluate", result=batch_result)
        return batch_result

    def evaluate_by_tier(
        self,
        content: str,
        tier: RuleTier,
        options: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        if not isinstance(tier, RuleTier):
            try:
                tier = RuleTier.from_str(str(tier))
            except ValueError:
                raise ConfigurationError(f"Invalid tier: {tier}")

        logger.debug("Evaluating by tier: %s", tier.value)
        return self.evaluate(content, context=options, tier=tier)

    def evaluate_with_rules(
        self,
        content: str,
        rule_ids: List[str],
        context: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = self._measure_time()

        ctx = self._build_context(context, options)
        try:
            result = self._client.evaluate_rules(
                content=content,
                context=ctx,
                rule_ids=rule_ids,
            )
        except SDKError as e:
            elapsed_ms = (self._measure_time() - start) * 1000
            result = ValidationResult(
                passed=False,
                warnings=[f"Evaluation failed: {e}"],
                processing_time_ms=elapsed_ms,
                metadata={"error": str(e)},
            )
            result.processing_time_ms = elapsed_ms
            return result

        elapsed_ms = (self._measure_time() - start) * 1000
        result.processing_time_ms = elapsed_ms
        return result

    def evaluate_by_content_type(
        self,
        content: str,
        content_type: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        ctx = dict(context or {})
        ctx["content_type"] = content_type
        return self.evaluate(content, context=ctx)

    def get_applicable_rules(
        self,
        context: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
        force_refresh: bool = False,
    ) -> List[Rule]:
        ctx = context or {}
        effective_tier = self._resolve_tier(tier)
        cache_key = self._cache_key("applicable_rules", tier=effective_tier.value, **ctx)

        if not force_refresh:
            cached = self._get_from_cache(self._rule_cache, cache_key)
            if cached is not None:
                return cached

        try:
            rules = self._client.get_rules(tier=effective_tier)
            applicable = [r for r in rules if r.is_applicable(ctx)]
            self._set_in_cache(self._rule_cache, cache_key, applicable)
            return applicable
        except APIError as e:
            logger.error("Failed to fetch applicable rules: %s", e)
            return []

    def get_rules_by_tier(self, tier: RuleTier, force_refresh: bool = False) -> List[Rule]:
        cache_key = self._cache_key("rules_by_tier", tier=tier.value)
        if not force_refresh:
            cached = self._get_from_cache(self._rule_cache, cache_key)
            if cached is not None:
                return cached
        try:
            rules = self._client.get_rules(tier=tier)
            self._set_in_cache(self._rule_cache, cache_key, rules)
            return rules
        except APIError as e:
            logger.error("Failed to fetch rules for tier %s: %s", tier.value, e)
            return []

    def get_rule_details(self, rule_id: str, force_refresh: bool = False) -> Optional[Rule]:
        cache_key = self._cache_key("rule_detail", rule_id=rule_id)
        if not force_refresh:
            cached = self._get_from_cache(self._rule_cache, cache_key)
            if cached is not None:
                return cached
        try:
            rule = self._client.get_rule(rule_id)
            self._set_in_cache(self._rule_cache, cache_key, rule)
            return rule
        except RuleNotFoundError:
            return None
        except APIError as e:
            logger.error("Failed to fetch rule %s: %s", rule_id, e)
            return None

    def get_rule_set(self, rule_set_id: str, force_refresh: bool = False) -> Optional[RuleSet]:
        cache_key = self._cache_key("rule_set", rule_set_id=rule_set_id)
        if not force_refresh:
            cached = self._get_from_cache(self._rule_set_cache, cache_key)
            if cached is not None:
                return cached
        try:
            rule_set = self._client.get_rule_set(rule_set_id)
            self._set_in_cache(self._rule_set_cache, cache_key, rule_set)
            return rule_set
        except APIError as e:
            logger.error("Failed to fetch rule set %s: %s", rule_set_id, e)
            return None

    def evaluate_with_timeout(
        self,
        content: str,
        timeout: int = 10,
        context: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
    ) -> ValidationResult:
        if timeout <= 0:
            raise ConfigurationError("timeout must be > 0")

        original_timeout = self._client.timeout
        self._client.timeout = timeout
        try:
            return self.evaluate(content, context=context, tier=tier)
        except TimeoutError:
            return ValidationResult(
                passed=False,
                blocked=True,
                warnings=[f"Evaluation timed out after {timeout}s"],
                processing_time_ms=timeout * 1000,
                metadata={"timeout": True, "timeout_seconds": timeout},
            )
        finally:
            self._client.timeout = original_timeout

    def evaluate_stream(
        self,
        contents: List[str],
        tier: Optional[RuleTier] = None,
        callback: Optional[Callable[[ValidationResult], None]] = None,
    ) -> BatchValidationResult:
        batch_result = BatchValidationResult()
        for i, content in enumerate(contents):
            try:
                result = self.evaluate(content, tier=tier)
                batch_result.add_result(result)
                if callback:
                    try:
                        callback(result)
                    except Exception as e:
                        logger.warning("Stream callback failed at item %d: %s", i, e)
            except SDKError as e:
                logger.error("Stream evaluation item %d failed: %s", i, e)
                err_result = ValidationResult(
                    passed=False,
                    warnings=[f"Item {i} failed: {e}"],
                )
                batch_result.add_result(err_result)
                if callback:
                    try:
                        callback(err_result)
                    except Exception as ex:
                        logger.warning("Stream callback error: %s", ex)
        return batch_result

    def register_evaluation_hook(self, hook: Callable) -> None:
        self._evaluation_hooks.append(hook)
        logger.debug("Registered evaluation hook (%d total)", len(self._evaluation_hooks))

    def unregister_evaluation_hook(self, hook: Callable) -> bool:
        if hook in self._evaluation_hooks:
            self._evaluation_hooks.remove(hook)
            logger.debug("Unregistered evaluation hook")
            return True
        return False

    def register_result_transformer(self, transformer: Callable) -> None:
        self._result_transformers.append(transformer)
        logger.debug("Registered result transformer (%d total)", len(self._result_transformers))

    def register_recovery_strategy(self, name: str, strategy: Callable) -> None:
        self._recovery_strategies[name] = strategy
        logger.debug("Registered recovery strategy: %s", name)

    def clear_cache(self) -> None:
        with self._lock:
            self._rule_cache.clear()
            self._rule_set_cache.clear()
            self._cache_hits = 0
            self._cache_misses = 0
        logger.info("Rule engine cache cleared")

    def preload_rules(self, tiers: Optional[List[RuleTier]] = None) -> int:
        tiers_to_load = tiers or list(RuleTier)
        total = 0
        for tier in tiers_to_load:
            try:
                rules = self._client.get_rules(tier=tier)
                cache_key = self._cache_key("rules_by_tier", tier=tier.value)
                self._set_in_cache(self._rule_cache, cache_key, rules)
                total += len(rules)
                logger.debug("Preloaded %d rules for tier %s", len(rules), tier.value)
            except APIError as e:
                logger.warning("Failed to preload rules for tier %s: %s", tier.value, e)
        logger.info("Preloaded %d rules total", total)
        return total

    def _evaluate_chunk(
        self,
        contents: List[str],
        options: Optional[Dict[str, Any]],
        tier: RuleTier,
    ) -> List[ValidationResult]:
        results: List[ValidationResult] = []
        for content in contents:
            try:
                result = self.evaluate(content, context=options, tier=tier)
                results.append(result)
            except SDKError as e:
                logger.warning("Chunk evaluation failed: %s", e)
                results.append(
                    ValidationResult(
                        passed=False,
                        warnings=[f"Chunk evaluation failed: {e}"],
                    )
                )
        return results

    def _chunk_list(self, items: List[Any], chunk_size: int) -> List[List[Any]]:
        return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

    def compute_rule_coverage(
        self,
        content: str,
        tier: Optional[RuleTier] = None,
    ) -> Dict[str, Any]:
        effective_tier = self._resolve_tier(tier)
        rules = self.get_applicable_rules(tier=effective_tier)
        result = self.evaluate(content, tier=effective_tier)
        triggered_rule_ids = {v.rule_id for v in result.violations}
        untriggered = [r for r in rules if r.rule_id not in triggered_rule_ids]
        return {
            "total_rules": len(rules),
            "triggered_rules": len(triggered_rule_ids),
            "untriggered_rules": len(untriggered),
            "coverage_ratio": len(triggered_rule_ids) / max(len(rules), 1),
            "triggered_rule_ids": list(triggered_rule_ids),
            "untriggered_rule_ids": [r.rule_id for r in untriggered],
            "tier": effective_tier.value,
        }

    def evaluate_with_context(
        self,
        content: str,
        context: RuleContext,
        tier: Optional[RuleTier] = None,
    ) -> ValidationResult:
        ctx_dict = context.to_dict() if isinstance(context, RuleContext) else context
        return self.evaluate(content, context=ctx_dict, tier=tier)

    def evaluate_with_options(
        self,
        content: str,
        options: Dict[str, Any],
        tier: Optional[RuleTier] = None,
    ) -> ValidationResult:
        return self.evaluate(content, options=options, tier=tier)

    def get_statistics(self) -> Dict[str, Any]:
        avg_time = self._total_eval_time_ms / max(self._evaluation_count, 1)
        return {
            "evaluation_count": self._evaluation_count,
            "error_count": self._error_count,
            "error_rate": self._error_count / max(self._evaluation_count, 1),
            "total_eval_time_ms": round(self._total_eval_time_ms, 2),
            "avg_eval_time_ms": round(avg_time, 2),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": self._cache_hits / max(self._cache_hits + self._cache_misses, 1),
            "cache_size": len(self._rule_cache),
            "hooks_registered": len(self._evaluation_hooks),
            "recovery_strategies": list(self._recovery_strategies.keys()),
            "default_tier": self.default_tier.value if self.default_tier else None,
            "batch_size": self.batch_size,
            "timeout": self.timeout,
        }

    def check_rule_consistency(
        self,
        rule_ids: List[str],
    ) -> Dict[str, Any]:
        rules: List[Rule] = []
        for rid in rule_ids:
            rule = self.get_rule_details(rid)
            if rule:
                rules.append(rule)
        conflicts: List[RuleConflict] = []
        for i, r1 in enumerate(rules):
            for r2 in rules[i + 1:]:
                if r1.tier == r2.tier and r1.priority == r2.priority:
                    if r1.severity != r2.severity:
                        conflicts.append(
                            RuleConflict(
                                conflict_id=f"{r1.rule_id}-{r2.rule_id}",
                                rule_ids=[r1.rule_id, r2.rule_id],
                                description=f"Severity mismatch: {r1.severity.value} vs {r2.severity.value}",
                            )
                        )
        return {
            "checked_rules": len(rules),
            "conflicts_found": len(conflicts),
            "conflicts": [c.to_dict() for c in conflicts],
        }

    def close(self) -> None:
        self.clear_cache()
        self._evaluation_hooks.clear()
        self._result_transformers.clear()
        logger.info("RuleEngineClient closed")

    def __enter__(self) -> "RuleEngineClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    async def async_evaluate(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
    ) -> ValidationResult:
        start = self._measure_time()
        ctx = self._build_context(context, options)
        effective_tier = self._resolve_tier(tier)

        try:
            result = await self._client.async_evaluate_rules(
                content=content,
                context=ctx,
                tier=effective_tier,
            )
            elapsed_ms = (self._measure_time() - start) * 1000
            result.processing_time_ms = elapsed_ms
            self._record_evaluation(elapsed_ms, True)
            return result
        except SDKError as e:
            elapsed_ms = (self._measure_time() - start) * 1000
            self._record_evaluation(elapsed_ms, False)
            return ValidationResult(
                passed=False,
                warnings=[f"Async evaluation failed: {e}"],
                processing_time_ms=elapsed_ms,
                metadata={"error": str(e)},
            )

    async def async_evaluate_batch(
        self,
        contents: List[str],
        options: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
    ) -> BatchValidationResult:
        start = self._measure_time()
        effective_tier = self._resolve_tier(tier)
        tasks = []
        for content in contents:
            tasks.append(self.async_evaluate(content, context=options, tier=effective_tier))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        batch_result = BatchValidationResult()
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error("Async batch item %d failed: %s", i, r)
                batch_result.add_result(
                    ValidationResult(
                        passed=False,
                        warnings=[f"Item {i} failed: {r}"],
                    )
                )
                batch_result.errors.append(f"Item {i}: {r}")
            else:
                batch_result.add_result(r)
        batch_result.total_time_ms = (self._measure_time() - start) * 1000
        return batch_result

    async def async_evaluate_by_tier(
        self,
        content: str,
        tier: RuleTier,
        options: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        return await self.async_evaluate(content, context=options, tier=tier)

    async def async_get_applicable_rules(
        self,
        context: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
        force_refresh: bool = False,
    ) -> List[Rule]:
        ctx = context or {}
        effective_tier = self._resolve_tier(tier)
        cache_key = self._cache_key("applicable_rules", tier=effective_tier.value, **ctx)

        if not force_refresh:
            cached = self._get_from_cache(self._rule_cache, cache_key)
            if cached is not None:
                return cached

        try:
            rules = await self._client.async_get_rules(tier=effective_tier)
            applicable = [r for r in rules if r.is_applicable(ctx)]
            self._set_in_cache(self._rule_cache, cache_key, applicable)
            return applicable
        except APIError as e:
            logger.error("Failed to fetch applicable rules: %s", e)
            return []

    async def async_get_rule_details(
        self,
        rule_id: str,
        force_refresh: bool = False,
    ) -> Optional[Rule]:
        cache_key = self._cache_key("rule_detail", rule_id=rule_id)
        if not force_refresh:
            cached = self._get_from_cache(self._rule_cache, cache_key)
            if cached is not None:
                return cached
        try:
            rule = await self._client.async_get_rule(rule_id)
            self._set_in_cache(self._rule_cache, cache_key, rule)
            return rule
        except RuleNotFoundError:
            return None
        except APIError as e:
            logger.error("Failed to fetch rule %s: %s", rule_id, e)
            return None

    async def async_preload_rules(self, tiers: Optional[List[RuleTier]] = None) -> int:
        tiers_to_load = tiers or list(RuleTier)
        total = 0
        for tier in tiers_to_load:
            try:
                rules = await self._client.async_get_rules(tier=tier)
                cache_key = self._cache_key("rules_by_tier", tier=tier.value)
                self._set_in_cache(self._rule_cache, cache_key, rules)
                total += len(rules)
            except APIError as e:
                logger.warning("Failed to preload rules for tier %s: %s", tier.value, e)
        logger.info("Async preloaded %d rules", total)
        return total
