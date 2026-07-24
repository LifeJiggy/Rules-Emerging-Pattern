"""ValidationClient - specialized client for content validation operations.

Provides methods for rule-based validation, batch validation, compliance checking,
safety checking, format validation, quality assessment, hallucination detection,
and citation validation with result formatting and aggregation.
"""

import asyncio
import json
import logging
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from .client import Client
from .exceptions import (
    APIError,
    ConfigurationError,
    SDKError,
    ValidationError,
)
from .models import (
    BatchValidationRequest,
    BatchValidationResult,
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleSeverity,
    RuleTier,
    ValidationResult,
    Violation,
    ViolationType,
)

logger = logging.getLogger(__name__)


class ValidationClient:
    """Specialized client for content validation operations.

    Provides comprehensive validation capabilities including rule-based validation,
    compliance checks, safety evaluation, format verification, quality assessment,
    hallucination detection, and citation validation with configurable result
    aggregation and formatting.

    Args:
        client: Configured Client instance for API communication.
        default_content_type: Default content type for validation.
        max_batch_size: Maximum number of items in a batch validation.
        strict_mode: Whether to use strict enforcement by default.
        aggregation_mode: How to aggregate batch results (any, all, weighted).
        result_ttl: Cache TTL for validation results in seconds.

    Example:
        client = Client(api_key="sk-...")
        vc = ValidationClient(client)
        result = vc.validate_content("Some content")
    """

    def __init__(
        self,
        client: Client,
        default_content_type: str = "text",
        max_batch_size: int = 100,
        strict_mode: bool = False,
        aggregation_mode: str = "any",
        result_ttl: int = 60,
    ):
        if not isinstance(client, Client):
            raise ConfigurationError("client must be an instance of Client")

        self._client = client
        self.default_content_type = default_content_type
        self.max_batch_size = max_batch_size
        self.strict_mode = strict_mode
        self.aggregation_mode = aggregation_mode
        self.result_ttl = result_ttl

        self._validation_count: int = 0
        self._pass_count: int = 0
        self._fail_count: int = 0
        self._block_count: int = 0
        self._total_time_ms: float = 0.0
        self._violation_stats: Counter = Counter()
        self._custom_rules: Dict[str, Rule] = {}
        self._validation_hooks: List[Callable] = []
        self._preprocessors: List[Callable] = []
        self._result_formatters: Dict[str, Callable] = {}
        self._aggregation_strategies: Dict[str, Callable] = {}

        self._register_default_formatters()
        self._register_aggregation_strategies()
        logger.info(
            "ValidationClient initialized (content_type=%s, strict=%s, aggregation=%s)",
            default_content_type,
            strict_mode,
            aggregation_mode,
        )

    def _register_default_formatters(self) -> None:
        self._result_formatters["summary"] = self._format_summary
        self._result_formatters["detailed"] = self._format_detailed
        self._result_formatters["json"] = self._format_json
        self._result_formatters["minimal"] = self._format_minimal
        self._result_formatters["score_only"] = self._format_score_only

    def _register_aggregation_strategies(self) -> None:
        self._aggregation_strategies["any"] = self._aggregate_any
        self._aggregation_strategies["all"] = self._aggregate_all
        self._aggregation_strategies["weighted"] = self._aggregate_weighted
        self._aggregation_strategies["severity_based"] = self._aggregate_severity

    def _format_summary(self, result: ValidationResult) -> Dict[str, Any]:
        return {
            "passed": result.passed,
            "blocked": result.blocked,
            "score": round(result.score, 4),
            "violations": len(result.violations),
            "errors": result.error_count(),
            "warnings": result.warning_count(),
            "processing_time_ms": round(result.processing_time_ms, 2),
            "applied_rules": result.applied_rules,
            "tier": result.tier,
        }

    def _format_detailed(self, result: ValidationResult) -> Dict[str, Any]:
        return {
            "passed": result.passed,
            "blocked": result.blocked,
            "score": round(result.score, 4),
            "violations": [
                {
                    "rule": v.rule_name,
                    "type": v.violation_type.value,
                    "severity": v.severity.value,
                    "message": v.message,
                    "field": v.field,
                    "line": v.line,
                    "column": v.column,
                    "suggestion": v.suggestion,
                }
                for v in result.violations
            ],
            "suggestions": [s.message for s in result.suggestions],
            "warnings": result.warnings,
            "applied_rules": result.applied_rules,
            "tier": result.tier,
            "request_id": result.request_id,
            "processing_time_ms": round(result.processing_time_ms, 2),
            "timestamp": result.timestamp,
        }

    def _format_json(self, result: ValidationResult) -> str:
        return json.dumps(result.to_dict(), indent=2, default=str)

    def _format_minimal(self, result: ValidationResult) -> Dict[str, Any]:
        return {
            "passed": result.passed,
            "blocked": result.blocked,
            "violation_count": len(result.violations),
        }

    def _format_score_only(self, result: ValidationResult) -> float:
        return result.score

    def _aggregate_any(self, results: List[ValidationResult]) -> ValidationResult:
        if not results:
            return ValidationResult(passed=True)
        any_blocked = any(r.blocked for r in results)
        any_failed = any(not r.passed for r in results)
        all_violations: List[Violation] = []
        all_suggestions = []
        all_warnings: List[str] = []
        total_time = sum(r.processing_time_ms for r in results)
        max_score = max(r.score for r in results)

        for r in results:
            all_violations.extend(r.violations)
            all_suggestions.extend(r.suggestions)
            all_warnings.extend(r.warnings)

        return ValidationResult(
            passed=not any_failed,
            blocked=any_blocked,
            violations=all_violations,
            suggestions=all_suggestions,
            warnings=all_warnings,
            score=max_score,
            processing_time_ms=total_time,
            applied_rules=sum(r.applied_rules for r in results),
        )

    def _aggregate_all(self, results: List[ValidationResult]) -> ValidationResult:
        if not results:
            return ValidationResult(passed=True)
        all_blocked = all(r.blocked for r in results)
        all_passed = all(r.passed for r in results)
        all_violations: List[Violation] = []
        all_suggestions = []
        all_warnings: List[str] = []
        total_time = sum(r.processing_time_ms for r in results)
        scores = [r.score for r in results]

        for r in results:
            all_violations.extend(r.violations)
            all_suggestions.extend(r.suggestions)
            all_warnings.extend(r.warnings)

        return ValidationResult(
            passed=all_passed,
            blocked=all_blocked,
            violations=all_violations,
            suggestions=all_suggestions,
            warnings=all_warnings,
            score=min(scores) if scores else 1.0,
            processing_time_ms=total_time,
            applied_rules=sum(r.applied_rules for r in results),
        )

    def _aggregate_weighted(self, results: List[ValidationResult]) -> ValidationResult:
        if not results:
            return ValidationResult(passed=True)
        total_weight = sum(r.applied_rules or 1 for r in results)
        weighted_score = sum(r.score * (r.applied_rules or 1) for r in results) / max(total_weight, 1)
        any_blocked = any(r.blocked for r in results)
        all_violations: List[Violation] = []
        all_suggestions = []
        all_warnings: List[str] = []
        total_time = sum(r.processing_time_ms for r in results)

        for r in results:
            all_violations.extend(r.violations)
            all_suggestions.extend(r.suggestions)
            all_warnings.extend(r.warnings)

        return ValidationResult(
            passed=weighted_score >= 0.7,
            blocked=any_blocked,
            violations=all_violations,
            suggestions=all_suggestions,
            warnings=all_warnings,
            score=weighted_score,
            processing_time_ms=total_time,
            applied_rules=sum(r.applied_rules for r in results),
        )

    def _aggregate_severity(self, results: List[ValidationResult]) -> ValidationResult:
        if not results:
            return ValidationResult(passed=True)
        all_violations: List[Violation] = []
        all_suggestions = []
        all_warnings: List[str] = []
        total_time = sum(r.processing_time_ms for r in results)

        for r in results:
            all_violations.extend(r.violations)
            all_suggestions.extend(r.suggestions)
            all_warnings.extend(r.warnings)

        has_critical = any(v.severity == RuleSeverity.CRITICAL for v in all_violations)
        has_high = any(v.severity == RuleSeverity.HIGH for v in all_violations)
        has_blocker = any(r.blocked for r in results)

        return ValidationResult(
            passed=not has_critical and not has_blocker,
            blocked=has_blocker or has_critical,
            violations=all_violations,
            suggestions=all_suggestions,
            warnings=all_warnings,
            score=0.0 if has_critical else (0.5 if has_high else 1.0),
            processing_time_ms=total_time,
            applied_rules=sum(r.applied_rules for r in results),
        )

    def _get_aggregation_mode(self, mode: Optional[str]) -> str:
        return mode or self.aggregation_mode

    def validate_content(
        self,
        content: str,
        rules: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        self._validation_count += 1

        processed_content = self._apply_preprocessors(content)
        try:
            result = self._client.validate(
                content=processed_content,
                tier=tier,
                rule_ids=rules,
                context=context,
            )
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._total_time_ms += elapsed_ms
            self._fail_count += 1
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(
                        rule_id="validation_error",
                        rule_name="ValidationError",
                        violation_type=ViolationType.CUSTOM,
                        severity=RuleSeverity.HIGH,
                        message=str(e),
                    )
                ],
                processing_time_ms=elapsed_ms,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        result.processing_time_ms = elapsed_ms
        self._total_time_ms += elapsed_ms

        if result.passed:
            self._pass_count += 1
        else:
            self._fail_count += 1
        if result.blocked:
            self._block_count += 1
        for v in result.violations:
            self._violation_stats[v.violation_type.value] += 1

        self._run_hooks("after_validate", result=result)
        return result

    def validate_batch(
        self,
        contents: List[str],
        rules: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
        parallel: bool = False,
        max_workers: int = 4,
        aggregation: Optional[str] = None,
    ) -> BatchValidationResult:
        start = time.perf_counter()
        batch_result = BatchValidationResult()

        if not contents:
            return batch_result

        if len(contents) > self.max_batch_size:
            logger.warning(
                "Batch size %d exceeds max %d, truncating",
                len(contents),
                self.max_batch_size,
            )
            contents = contents[:self.max_batch_size]

        if parallel:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self.validate_content, c, rules, context, tier
                    ): i
                    for i, c in enumerate(contents)
                }
                ordered: List[Optional[ValidationResult]] = [None] * len(contents)
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        ordered[idx] = future.result()
                    except Exception as e:
                        logger.error("Batch item %d failed: %s", idx, e)
                        ordered[idx] = ValidationResult(
                            passed=False,
                            violations=[
                                Violation(
                                    rule_id="batch_error",
                                    rule_name="BatchError",
                                    violation_type=ViolationType.CUSTOM,
                                    severity=RuleSeverity.HIGH,
                                    message=str(e),
                                )
                            ],
                        )
                for r in ordered:
                    if r:
                        batch_result.add_result(r)
        else:
            for i, content in enumerate(contents):
                try:
                    result = self.validate_content(content, rules, context, tier)
                    batch_result.add_result(result)
                except Exception as e:
                    logger.error("Batch item %d failed: %s", i, e)
                    batch_result.add_result(
                        ValidationResult(
                            passed=False,
                            violations=[
                                Violation(
                                    rule_id="batch_error",
                                    rule_name="BatchError",
                                    violation_type=ViolationType.CUSTOM,
                                    severity=RuleSeverity.HIGH,
                                    message=str(e),
                                )
                            ],
                        )
                    )

        batch_result.total_time_ms = (time.perf_counter() - start) * 1000
        return batch_result

    def check_compliance(
        self,
        content: str,
        regulations: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        strict: Optional[bool] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        effective_strict = strict if strict is not None else self.strict_mode

        try:
            result = self._client.check_compliance(content, regulations, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._total_time_ms += elapsed_ms
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(
                        rule_id="compliance_error",
                        rule_name="ComplianceError",
                        violation_type=ViolationType.COMPLIANCE,
                        severity=RuleSeverity.CRITICAL if effective_strict else RuleSeverity.HIGH,
                        message=str(e),
                    )
                ],
                processing_time_ms=elapsed_ms,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        result.processing_time_ms = elapsed_ms
        self._total_time_ms += elapsed_ms
        return result

    def check_safety(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
        strict: Optional[bool] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        effective_strict = strict if strict is not None else self.strict_mode

        try:
            result = self._client.check_safety(content, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                blocked=effective_strict,
                violations=[
                    Violation(
                        rule_id="safety_error",
                        rule_name="SafetyError",
                        violation_type=ViolationType.CONTENT_SAFETY,
                        severity=RuleSeverity.CRITICAL if effective_strict else RuleSeverity.HIGH,
                        message=str(e),
                    )
                ],
                processing_time_ms=elapsed_ms,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        result.processing_time_ms = elapsed_ms
        return result

    def check_format(
        self,
        content: str,
        format_type: str = "text",
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        try:
            result = self._client.check_format(content, format_type, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(
                        rule_id="format_error",
                        rule_name="FormatError",
                        violation_type=ViolationType.FORMAT_ERROR,
                        severity=RuleSeverity.MEDIUM,
                        message=str(e),
                    )
                ],
                processing_time_ms=elapsed_ms,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        result.processing_time_ms = elapsed_ms
        return result

    def check_quality(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        try:
            result = self._client.check_quality(content, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(
                        rule_id="quality_error",
                        rule_name="QualityError",
                        violation_type=ViolationType.QUALITY,
                        severity=RuleSeverity.MEDIUM,
                        message=str(e),
                    )
                ],
                processing_time_ms=elapsed_ms,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        result.processing_time_ms = elapsed_ms
        return result

    def detect_hallucinations(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        try:
            result = self._client.detect_hallucinations(content, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(
                        rule_id="hallucination_error",
                        rule_name="HallucinationError",
                        violation_type=ViolationType.HALLUCINATION,
                        severity=RuleSeverity.MEDIUM,
                        message=str(e),
                    )
                ],
                processing_time_ms=elapsed_ms,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        result.processing_time_ms = elapsed_ms
        return result

    def validate_citations(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        try:
            result = self._client.validate_citations(content, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(
                        rule_id="citation_error",
                        rule_name="CitationError",
                        violation_type=ViolationType.CITATION,
                        severity=RuleSeverity.MEDIUM,
                        message=str(e),
                    )
                ],
                processing_time_ms=elapsed_ms,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        result.processing_time_ms = elapsed_ms
        return result

    def full_validation(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
        regulations: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        start = time.perf_counter()
        results: Dict[str, ValidationResult] = {}

        results["content"] = self.validate_content(content, context=context)
        results["safety"] = self.check_safety(content, context=context)
        results["quality"] = self.check_quality(content, context=context)
        results["hallucination"] = self.detect_hallucinations(content, context=context)
        results["citations"] = self.validate_citations(content, context=context)
        if regulations:
            results["compliance"] = self.check_compliance(content, regulations, context=context)

        all_passed = all(r.passed for r in results.values())
        any_blocked = any(r.blocked for r in results.values())
        all_violations: List[Violation] = []
        total_rules = 0
        for r in results.values():
            all_violations.extend(r.violations)
            total_rules += r.applied_rules

        overall_score = (
            sum(r.score for r in results.values()) / max(len(results), 1)
        )

        total_time_ms = (time.perf_counter() - start) * 1000
        return {
            "passed": all_passed,
            "blocked": any_blocked,
            "overall_score": round(overall_score, 4),
            "results": {k: v.to_dict() for k, v in results.items()},
            "violations": [v.to_dict() for v in all_violations],
            "total_violations": len(all_violations),
            "total_rules_applied": total_rules,
            "processing_time_ms": round(total_time_ms, 2),
        }

    def validate_with_ruleset(
        self,
        content: str,
        rule_set_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        try:
            rule_set = self._client.get_rule_set(rule_set_id)
        except SDKError:
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(
                        rule_id="rule_set_error",
                        rule_name="RuleSetError",
                        violation_type=ViolationType.CUSTOM,
                        severity=RuleSeverity.HIGH,
                        message=f"Rule set '{rule_set_id}' not found",
                    )
                ],
            )
        rule_ids = [r.rule_id for r in rule_set.rules]
        return self.validate_content(content, rules=rule_ids, context=context)

    def format_result(
        self,
        result: ValidationResult,
        format_type: str = "summary",
    ) -> Any:
        formatter = self._result_formatters.get(format_type)
        if not formatter:
            logger.warning("Unknown format type '%s', using summary", format_type)
            formatter = self._format_summary
        return formatter(result)

    def aggregate_results(
        self,
        results: List[ValidationResult],
        mode: Optional[str] = None,
    ) -> ValidationResult:
        effective_mode = self._get_aggregation_mode(mode)
        strategy = self._aggregation_strategies.get(effective_mode)
        if not strategy:
            logger.warning("Unknown aggregation mode '%s', using 'any'", effective_mode)
            strategy = self._aggregate_any
        return strategy(results)

    def classify_violations(
        self,
        violations: List[Violation],
    ) -> Dict[str, List[Violation]]:
        classified: Dict[str, List[Violation]] = defaultdict(list)
        for v in violations:
            classified[v.violation_type.value].append(v)
        return dict(classified)

    def get_violation_summary(self, violations: List[Violation]) -> Dict[str, Any]:
        counts: Dict[str, int] = defaultdict(int)
        severity_counts: Dict[str, int] = defaultdict(int)
        rule_counts: Dict[str, int] = defaultdict(int)

        for v in violations:
            counts[v.violation_type.value] += 1
            severity_counts[v.severity.value] += 1
            rule_counts[v.rule_name] += 1

        return {
            "total_violations": len(violations),
            "by_type": dict(counts),
            "by_severity": dict(severity_counts),
            "by_rule": dict(rule_counts),
            "most_common_type": max(counts, key=counts.get) if counts else None,
            "most_common_rule": max(rule_counts, key=rule_counts.get) if rule_counts else None,
        }

    def register_preprocessor(self, preprocessor: Callable[[str], str]) -> None:
        self._preprocessors.append(preprocessor)
        logger.debug("Registered preprocessor (%d total)", len(self._preprocessors))

    def unregister_preprocessor(self, preprocessor: Callable) -> bool:
        if preprocessor in self._preprocessors:
            self._preprocessors.remove(preprocessor)
            return True
        return False

    def register_validation_hook(self, hook: Callable) -> None:
        self._validation_hooks.append(hook)

    def unregister_validation_hook(self, hook: Callable) -> bool:
        if hook in self._validation_hooks:
            self._validation_hooks.remove(hook)
            return True
        return False

    def register_result_formatter(self, name: str, formatter: Callable) -> None:
        self._result_formatters[name] = formatter

    def register_aggregation_strategy(self, name: str, strategy: Callable) -> None:
        self._aggregation_strategies[name] = strategy

    def _run_hooks(self, phase: str, **kwargs: Any) -> None:
        for hook in self._validation_hooks:
            try:
                hook(phase=phase, **kwargs)
            except Exception as e:
                logger.warning("Validation hook failed at '%s': %s", phase, e)

    def _apply_preprocessors(self, content: str) -> str:
        for preprocessor in self._preprocessors:
            try:
                content = preprocessor(content)
            except Exception as e:
                logger.warning("Preprocessor failed: %s", e)
        return content

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "total_validations": self._validation_count,
            "passed": self._pass_count,
            "failed": self._fail_count,
            "blocked": self._block_count,
            "pass_rate": self._pass_count / max(self._validation_count, 1),
            "total_time_ms": round(self._total_time_ms, 2),
            "avg_time_ms": round(self._total_time_ms / max(self._validation_count, 1), 2),
            "violation_breakdown": dict(self._violation_stats.most_common()),
            "preprocessors": len(self._preprocessors),
            "hooks": len(self._validation_hooks),
        }

    def close(self) -> None:
        self._validation_hooks.clear()
        self._preprocessors.clear()
        self._custom_rules.clear()
        logger.info("ValidationClient closed")

    def __enter__(self) -> "ValidationClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    async def async_validate_content(
        self,
        content: str,
        rules: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        self._validation_count += 1
        processed_content = self._apply_preprocessors(content)

        try:
            result = await self._client.async_validate(
                content=processed_content,
                tier=tier,
                rule_ids=rules,
                context=context,
            )
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._total_time_ms += elapsed_ms
            self._fail_count += 1
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(
                        rule_id="validation_error",
                        rule_name="ValidationError",
                        violation_type=ViolationType.CUSTOM,
                        severity=RuleSeverity.HIGH,
                        message=str(e),
                    )
                ],
                processing_time_ms=elapsed_ms,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        result.processing_time_ms = elapsed_ms
        self._total_time_ms += elapsed_ms
        if result.passed:
            self._pass_count += 1
        else:
            self._fail_count += 1
        return result

    async def async_validate_batch(
        self,
        contents: List[str],
        rules: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
    ) -> BatchValidationResult:
        start = time.perf_counter()
        tasks = []
        for content in contents:
            tasks.append(
                self.async_validate_content(content, rules, context, tier)
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        batch_result = BatchValidationResult()
        for r in results:
            if isinstance(r, Exception):
                batch_result.add_result(
                    ValidationResult(
                        passed=False,
                        violations=[
                            Violation(
                                rule_id="batch_error",
                                rule_name="BatchError",
                                violation_type=ViolationType.CUSTOM,
                                severity=RuleSeverity.HIGH,
                                message=str(r),
                            )
                        ],
                    )
                )
                batch_result.errors.append(str(r))
            else:
                batch_result.add_result(r)
        batch_result.total_time_ms = (time.perf_counter() - start) * 1000
        return batch_result

    async def async_check_compliance(
        self,
        content: str,
        regulations: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        try:
            result = await self._client.async_check_compliance(content, regulations, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                violations=[Violation(rule_id="compliance_error", rule_name="ComplianceError",
                                     violation_type=ViolationType.COMPLIANCE,
                                     severity=RuleSeverity.HIGH, message=str(e))],
                processing_time_ms=elapsed_ms,
            )
        result.processing_time_ms = (time.perf_counter() - start) * 1000
        return result

    async def async_check_safety(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        try:
            result = await self._client.async_check_safety(content, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                violations=[Violation(rule_id="safety_error", rule_name="SafetyError",
                                     violation_type=ViolationType.CONTENT_SAFETY,
                                     severity=RuleSeverity.CRITICAL, message=str(e))],
                processing_time_ms=elapsed_ms,
            )
        result.processing_time_ms = (time.perf_counter() - start) * 1000
        return result

    async def async_check_format(
        self,
        content: str,
        format_type: str = "text",
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        try:
            result = await self._client.async_check_format(content, format_type, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                violations=[Violation(rule_id="format_error", rule_name="FormatError",
                                     violation_type=ViolationType.FORMAT_ERROR,
                                     severity=RuleSeverity.MEDIUM, message=str(e))],
                processing_time_ms=elapsed_ms,
            )
        result.processing_time_ms = (time.perf_counter() - start) * 1000
        return result

    async def async_check_quality(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        try:
            result = await self._client.async_check_quality(content, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                violations=[Violation(rule_id="quality_error", rule_name="QualityError",
                                     violation_type=ViolationType.QUALITY,
                                     severity=RuleSeverity.MEDIUM, message=str(e))],
                processing_time_ms=elapsed_ms,
            )
        result.processing_time_ms = (time.perf_counter() - start) * 1000
        return result

    async def async_detect_hallucinations(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        try:
            result = await self._client.async_detect_hallucinations(content, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                violations=[Violation(rule_id="hallucination_error", rule_name="HallucinationError",
                                     violation_type=ViolationType.HALLUCINATION,
                                     severity=RuleSeverity.MEDIUM, message=str(e))],
                processing_time_ms=elapsed_ms,
            )
        result.processing_time_ms = (time.perf_counter() - start) * 1000
        return result

    async def async_validate_citations(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        start = time.perf_counter()
        try:
            result = await self._client.async_validate_citations(content, context)
        except SDKError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ValidationResult(
                passed=False,
                violations=[Violation(rule_id="citation_error", rule_name="CitationError",
                                     violation_type=ViolationType.CITATION,
                                     severity=RuleSeverity.MEDIUM, message=str(e))],
                processing_time_ms=elapsed_ms,
            )
        result.processing_time_ms = (time.perf_counter() - start) * 1000
        return result

    async def async_full_validation(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
        regulations: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        start = time.perf_counter()
        tasks = {
            "content": self.async_validate_content(content, context=context),
            "safety": self.async_check_safety(content, context=context),
            "quality": self.async_check_quality(content, context=context),
            "hallucination": self.async_detect_hallucinations(content, context=context),
            "citations": self.async_validate_citations(content, context=context),
        }
        if regulations:
            tasks["compliance"] = self.async_check_compliance(content, regulations, context=context)

        results = {}
        for name, coro in tasks.items():
            results[name] = await coro

        all_passed = all(r.passed for r in results.values())
        any_blocked = any(r.blocked for r in results.values())
        all_violations: List[Violation] = []
        for r in results.values():
            all_violations.extend(r.violations)

        overall_score = sum(r.score for r in results.values()) / max(len(results), 1)
        total_time_ms = (time.perf_counter() - start) * 1000

        return {
            "passed": all_passed,
            "blocked": any_blocked,
            "overall_score": round(overall_score, 4),
            "results": {k: v.to_dict() for k, v in results.items()},
            "violations": [v.to_dict() for v in all_violations],
            "total_violations": len(all_violations),
            "processing_time_ms": round(total_time_ms, 2),
        }
