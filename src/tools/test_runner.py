"""
Test runner for rule evaluation - test case definition, automated execution,
result comparison, coverage analysis, and report generation.
"""

import csv
import json
import logging
import math
import os
import time
import traceback
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)
from rules_emerging_pattern.models.validation import ValidationResult, Violation

logger = logging.getLogger(__name__)


class TestStatus(str, Enum):
    """Status of a test case execution."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class ComparisonMethod(str, Enum):
    """Method for comparing actual vs expected results."""
    EXACT_MATCH = "exact_match"
    SUBSET_MATCH = "subset_match"
    SCORE_THRESHOLD = "score_threshold"
    CUSTOM = "custom"


class CoverageMetric(str, Enum):
    """Types of coverage metrics to track."""
    RULE_COVERAGE = "rule_coverage"
    PATTERN_COVERAGE = "pattern_coverage"
    CONDITION_COVERAGE = "condition_coverage"
    INPUT_VARIETY = "input_variety"
    TIER_COVERAGE = "tier_coverage"
    TYPE_COVERAGE = "type_coverage"


@dataclass
class TestConfig:
    """Configuration for the test runner."""
    comparison_method: ComparisonMethod = ComparisonMethod.EXACT_MATCH
    score_threshold: float = 0.8
    timeout_per_test: int = 5000
    max_retries: int = 0
    stop_on_first_failure: bool = False
    parallel_execution: bool = False
    max_workers: int = 4
    capture_performance: bool = True
    capture_context: bool = True
    coverage_enabled: bool = True
    coverage_metrics: List[CoverageMetric] = field(default_factory=lambda: list(CoverageMetric))
    report_format: str = "json"
    export_results: bool = False
    export_dir: Optional[str] = None
    export_on_failure_only: bool = False
    test_data_dir: Optional[str] = None
    suite_definitions: Dict[str, str] = field(default_factory=dict)
    before_test_hook: Optional[Callable] = None
    after_test_hook: Optional[Callable] = None
    fail_on_unmatched_rules: bool = False
    strict_mode: bool = False


@dataclass
class TestInput:
    """Input data for a test case."""
    content: str
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


@dataclass
class ExpectedOutput:
    """Expected output for a test case."""
    matched_rule_ids: List[str] = field(default_factory=list)
    matched_rule_names: List[str] = field(default_factory=list)
    action: Optional[str] = None
    violations: List[str] = field(default_factory=list)
    match_count: Optional[int] = None
    score: Optional[float] = None
    custom_checks: Optional[Dict[str, Any]] = None


@dataclass
class TestCase:
    """A single test case definition."""
    id: str
    name: str
    description: str
    input: TestInput
    expected: ExpectedOutput
    tags: List[str] = field(default_factory=list)
    priority: int = 0
    timeout_ms: Optional[int] = None
    enabled: bool = True
    category: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TestResult:
    """Result of a single test execution."""
    test_case: TestCase
    status: TestStatus
    actual_output: Dict[str, Any]
    duration_ms: float
    errors: List[str] = field(default_factory=list)
    mismatches: List[str] = field(default_factory=list)
    matched_rule_ids: List[str] = field(default_factory=list)
    matched_rule_names: List[str] = field(default_factory=list)
    score: float = 0.0
    retry_count: int = 0
    executed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CoverageReport:
    """Coverage analysis report."""
    total_rules: int
    covered_rules: int
    uncovered_rules: List[str]
    coverage_pct: float
    per_tier_coverage: Dict[str, float]
    per_type_coverage: Dict[str, float]
    uncovered_patterns: List[str]
    uncovered_conditions: List[str]
    input_variety_score: float
    recommendations: List[str]


@dataclass
class TestSuite:
    """A named collection of test cases."""
    name: str
    description: str
    test_cases: List[TestCase]
    config_overrides: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TestRunReport:
    """Complete test run report."""
    run_id: str
    suite_name: str
    started_at: datetime
    finished_at: datetime
    total_tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    results: List[TestResult]
    coverage: Optional[CoverageReport]
    summary: Dict[str, Any]
    duration_seconds: float
    config_used: Dict[str, Any]
    recommendations: List[str]


class ResultComparator:
    """Compares actual test results against expected outputs."""

    def __init__(self, config: TestConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.ResultComparator")

    def compare(self, test_case: TestCase, actual_output: Dict[str, Any]) -> TestResult:
        mismatches = []
        score = 1.0
        matched_rule_ids = actual_output.get("matched_rule_ids", [])
        matched_rule_names = actual_output.get("matched_rule_names", [])
        expected = test_case.expected
        if self.config.comparison_method == ComparisonMethod.EXACT_MATCH:
            score, mismatches = self._exact_compare(test_case, actual_output)
        elif self.config.comparison_method == ComparisonMethod.SUBSET_MATCH:
            score, mismatches = self._subset_compare(test_case, actual_output)
        elif self.config.comparison_method == ComparisonMethod.SCORE_THRESHOLD:
            score, mismatches = self._score_compare(test_case, actual_output)
        elif self.config.comparison_method == ComparisonMethod.CUSTOM:
            score, mismatches = self._custom_compare(test_case, actual_output)
        passed = len(mismatches) == 0 and score >= self.config.score_threshold
        return TestResult(
            test_case=test_case,
            status=TestStatus.PASSED if passed else TestStatus.FAILED,
            actual_output=actual_output,
            duration_ms=actual_output.get("duration_ms", 0),
            mismatches=mismatches,
            matched_rule_ids=matched_rule_ids,
            matched_rule_names=matched_rule_names,
            score=score,
            executed_at=datetime.utcnow(),
        )

    def _exact_compare(self, test_case: TestCase, actual: Dict) -> Tuple[float, List[str]]:
        mismatches = []
        expected = test_case.expected
        actual_ids = set(actual.get("matched_rule_ids", []))
        expected_ids = set(expected.matched_rule_ids)
        if actual_ids != expected_ids:
            missing = expected_ids - actual_ids
            extra = actual_ids - expected_ids
            if missing:
                mismatches.append(f"Missing expected rule matches: {missing}")
            if extra:
                mismatches.append(f"Unexpected rule matches: {extra}")
        if expected.match_count is not None:
            actual_count = len(actual.get("matched_rule_ids", []))
            if actual_count != expected.match_count:
                mismatches.append(f"Match count: expected {expected.match_count}, got {actual_count}")
        if expected.action:
            actual_action = actual.get("action_taken")
            if actual_action != expected.action:
                mismatches.append(f"Action: expected '{expected.action}', got '{actual_action}'")
        if expected.violations:
            actual_violations = set(actual.get("violations", []))
            for v in expected.violations:
                if v not in actual_violations:
                    mismatches.append(f"Missing expected violation: {v}")
        score = max(0.0, 1.0 - len(mismatches) * 0.25)
        return score, mismatches

    def _subset_compare(self, test_case: TestCase, actual: Dict) -> Tuple[float, List[str]]:
        mismatches = []
        expected = test_case.expected
        actual_ids = set(actual.get("matched_rule_ids", []))
        expected_ids = set(expected.matched_rule_ids)
        if not expected_ids.issubset(actual_ids):
            missing = expected_ids - actual_ids
            mismatches.append(f"Expected rules not matched: {missing}")
        covered = len(expected_ids & actual_ids)
        total = len(expected_ids) if expected_ids else 1
        score = covered / total
        return score, mismatches

    def _score_compare(self, test_case: TestCase, actual: Dict) -> Tuple[float, List[str]]:
        mismatches = []
        expected = test_case.expected
        actual_score = actual.get("score", 0.0)
        expected_score = expected.score or self.config.score_threshold
        if actual_score < expected_score:
            mismatches.append(f"Score {actual_score:.2f} below threshold {expected_score:.2f}")
        return actual_score, mismatches

    def _custom_compare(self, test_case: TestCase, actual: Dict) -> Tuple[float, List[str]]:
        mismatches = []
        expected = test_case.expected
        if expected.custom_checks:
            for key, expected_val in expected.custom_checks.items():
                actual_val = actual.get(key)
                if actual_val != expected_val:
                    mismatches.append(f"Custom check '{key}': expected {expected_val}, got {actual_val}")
        return 1.0 if not mismatches else 0.5, mismatches


class CoverageAnalyzer:
    """Analyzes test coverage of rules."""

    def __init__(self, config: TestConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.CoverageAnalyzer")

    def analyze_coverage(self, rules: List[Rule], results: List[TestResult]) -> CoverageReport:
        if not self.config.coverage_enabled:
            return CoverageReport(
                total_rules=len(rules), covered_rules=0, uncovered_rules=[],
                coverage_pct=0.0, per_tier_coverage={}, per_type_coverage={},
                uncovered_patterns=[], uncovered_conditions=[],
                input_variety_score=0.0, recommendations=[],
            )
        covered_rule_ids = set()
        for result in results:
            if result.status == TestStatus.PASSED:
                covered_rule_ids.update(result.matched_rule_ids)
        all_rule_ids = {r.id for r in rules}
        uncovered_ids = all_rule_ids - covered_rule_ids
        uncovered_rules = [r for r in rules if r.id in uncovered_ids]
        coverage_pct = len(covered_rule_ids) / len(all_rule_ids) * 100 if all_rule_ids else 0
        per_tier = self._per_tier_coverage(rules, covered_rule_ids)
        per_type = self._per_type_coverage(rules, covered_rule_ids)
        uncovered_patterns = self._find_uncovered_patterns(rules, covered_rule_ids)
        uncovered_conditions = self._find_uncovered_conditions(rules, covered_rule_ids)
        input_variety = self._input_variety_score(results)
        recommendations = self._generate_coverage_recommendations(
            uncovered_rules, coverage_pct, per_tier,
        )
        return CoverageReport(
            total_rules=len(rules),
            covered_rules=len(covered_rule_ids),
            uncovered_rules=[r.name for r in uncovered_rules],
            coverage_pct=round(coverage_pct, 2),
            per_tier_coverage=per_tier,
            per_type_coverage=per_type,
            uncovered_patterns=uncovered_patterns,
            uncovered_conditions=uncovered_conditions,
            input_variety_score=input_variety,
            recommendations=recommendations,
        )

    def _per_tier_coverage(self, rules: List[Rule], covered_ids: Set[str]) -> Dict[str, float]:
        coverage = {}
        for tier in RuleTier:
            tier_rules = [r for r in rules if r.tier == tier]
            if not tier_rules:
                continue
            covered = sum(1 for r in tier_rules if r.id in covered_ids)
            coverage[tier.value] = round(covered / len(tier_rules) * 100, 2)
        return coverage

    def _per_type_coverage(self, rules: List[Rule], covered_ids: Set[str]) -> Dict[str, float]:
        coverage = {}
        for rtype in RuleType:
            type_rules = [r for r in rules if r.rule_type == rtype]
            if not type_rules:
                continue
            covered = sum(1 for r in type_rules if r.id in covered_ids)
            coverage[rtype.value] = round(covered / len(type_rules) * 100, 2)
        return coverage

    def _find_uncovered_patterns(self, rules: List[Rule], covered_ids: Set[str]) -> List[str]:
        uncovered = []
        for rule in rules:
            if rule.id not in covered_ids:
                for pattern in rule.patterns:
                    for kw in pattern.keywords:
                        uncovered.append(f"{rule.name}:keyword={kw}")
                    for regex in pattern.regex_patterns:
                        uncovered.append(f"{rule.name}:regex={regex[:50]}")
        return uncovered[:100]

    def _find_uncovered_conditions(self, rules: List[Rule], covered_ids: Set[str]) -> List[str]:
        uncovered = []
        for rule in rules:
            if rule.id not in covered_ids:
                for key, value in rule.conditions.items():
                    uncovered.append(f"{rule.name}:condition={key}={value}")
        return uncovered[:100]

    def _input_variety_score(self, results: List[TestResult]) -> float:
        if not results:
            return 0.0
        unique_inputs = set()
        for r in results:
            content = r.test_case.input.content[:100]
            unique_inputs.add(content)
        variety = len(unique_inputs) / len(results)
        return round(min(1.0, variety * 2), 4)

    def _generate_coverage_recommendations(self, uncovered_rules: List[Rule], coverage_pct: float, per_tier: Dict[str, float]) -> List[str]:
        recs = []
        if coverage_pct < 50:
            recs.append(f"Critical: only {coverage_pct:.1f}% rule coverage. Add tests for {len(uncovered_rules)} uncovered rules.")
        elif coverage_pct < 80:
            recs.append(f"Coverage is {coverage_pct:.1f}%. Aim for at least 80%. {len(uncovered_rules)} rules uncovered.")
        elif coverage_pct < 95:
            recs.append(f"Good coverage ({coverage_pct:.1f}%). Add edge case tests for remaining rules.")
        else:
            recs.append(f"Excellent coverage ({coverage_pct:.1f}%). Maintain with regression tests.")
        for tier, pct in sorted(per_tier.items()):
            if pct < 60:
                recs.append(f"Low coverage in {tier} tier ({pct:.1f}%). Prioritize tests for this tier.")
        if len(uncovered_rules) > 0:
            sample_names = [r.name for r in uncovered_rules[:5]]
            recs.append(f"Uncovered rules (sample): {', '.join(sample_names)}")
        return recs


class TestSuiteLoader:
    """Loads test suites from files."""

    def __init__(self, config: TestConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.TestSuiteLoader")

    def load_from_file(self, filepath: str) -> TestSuite:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Test suite file not found: {filepath}")
        content = path.read_text(encoding="utf-8")
        if filepath.endswith(".yaml") or filepath.endswith(".yml"):
            data = yaml.safe_load(content)
        elif filepath.endswith(".json"):
            data = json.loads(content)
        elif filepath.endswith(".csv"):
            return self._load_csv(path)
        else:
            raise ValueError(f"Unsupported file format: {filepath}")
        return self._parse_suite(data, path.stem)

    def _load_csv(self, path: Path) -> TestSuite:
        test_cases = []
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                test_case = TestCase(
                    id=row.get("id", f"TC-{uuid.uuid4().hex[:8]}"),
                    name=row.get("name", "Unnamed"),
                    description=row.get("description", ""),
                    input=TestInput(
                        content=row.get("input_content", ""),
                        context=json.loads(row.get("context", "{}")),
                    ),
                    expected=ExpectedOutput(
                        matched_rule_ids=json.loads(row.get("expected_rule_ids", "[]")),
                        action=row.get("expected_action"),
                    ),
                    tags=[t.strip() for t in row.get("tags", "").split(",") if t.strip()],
                )
                test_cases.append(test_case)
        return TestSuite(
            name=path.stem,
            description=f"Loaded from {path.name}",
            test_cases=test_cases,
        )

    def _parse_suite(self, data: Dict, default_name: str) -> TestSuite:
        suite_name = data.get("name", default_name)
        suite_desc = data.get("description", "")
        suite_tags = data.get("tags", [])
        test_cases = []
        for tc_data in data.get("test_cases", []):
            test_case = TestCase(
                id=tc_data.get("id", f"TC-{uuid.uuid4().hex[:8]}"),
                name=tc_data.get("name", "Unnamed"),
                description=tc_data.get("description", ""),
                input=TestInput(
                    content=tc_data.get("input", {}).get("content", ""),
                    context=tc_data.get("input", {}).get("context", {}),
                    metadata=tc_data.get("input", {}).get("metadata", {}),
                    tags=tc_data.get("input", {}).get("tags", []),
                ),
                expected=ExpectedOutput(
                    matched_rule_ids=tc_data.get("expected", {}).get("matched_rule_ids", []),
                    matched_rule_names=tc_data.get("expected", {}).get("matched_rule_names", []),
                    action=tc_data.get("expected", {}).get("action"),
                    violations=tc_data.get("expected", {}).get("violations", []),
                    match_count=tc_data.get("expected", {}).get("match_count"),
                    score=tc_data.get("expected", {}).get("score"),
                ),
                tags=tc_data.get("tags", []),
                priority=tc_data.get("priority", 0),
                enabled=tc_data.get("enabled", True),
                category=tc_data.get("category"),
            )
            test_cases.append(test_case)
        return TestSuite(
            name=suite_name,
            description=suite_desc,
            test_cases=test_cases,
            tags=suite_tags,
        )

    def load_suite(self, suite_name: str) -> Optional[TestSuite]:
        if suite_name in self.config.suite_definitions:
            filepath = self.config.suite_definitions[suite_name]
            return self.load_from_file(filepath)
        if self.config.test_data_dir:
            for ext in (".json", ".yaml", ".yml", ".csv"):
                path = Path(self.config.test_data_dir) / f"{suite_name}{ext}"
                if path.exists():
                    return self.load_from_file(str(path))
        self.logger.warning("Test suite '%s' not found", suite_name)
        return None

    def discover_suites(self, dirpath: Optional[str] = None) -> List[str]:
        search_dir = dirpath or self.config.test_data_dir
        if not search_dir:
            return []
        path = Path(search_dir)
        if not path.exists():
            return []
        suites = []
        for ext in ("*.json", "*.yaml", "*.yml", "*.csv"):
            for f in path.glob(ext):
                if f.is_file():
                    suites.append(f.stem)
        return sorted(suites)


class TestRunner:
    """
    Test runner for rule evaluation.

    Defines and runs test cases against rules, compares results,
    analyzes coverage, and generates detailed test reports.
    """

    def __init__(self, config: Optional[TestConfig] = None):
        self.config = config or TestConfig()
        self._comparator = ResultComparator(self.config)
        self._coverage_analyzer = CoverageAnalyzer(self.config)
        self._suite_loader = TestSuiteLoader(self.config)
        self._evaluation_fn: Optional[Callable] = None
        self._results_history: List[TestRunReport] = []
        self.logger = logging.getLogger(f"{__name__}.TestRunner")

    def update_config(self, config_updates: Dict[str, Any]) -> None:
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self._comparator = ResultComparator(self.config)
        self._coverage_analyzer = CoverageAnalyzer(self.config)
        self._suite_loader = TestSuiteLoader(self.config)
        self.logger.info("Test runner config updated with %d changes", len(config_updates))

    def set_evaluation_fn(self, fn: Callable) -> None:
        self._evaluation_fn = fn

    def run_test_case(self, test_case: TestCase) -> TestResult:
        if not test_case.enabled:
            return TestResult(
                test_case=test_case,
                status=TestStatus.SKIPPED,
                actual_output={},
                duration_ms=0,
            )
        timeout_ms = test_case.timeout_ms or self.config.timeout_per_test
        start_time = time.time()
        errors = []
        actual_output = {}
        current_status = TestStatus.RUNNING
        if self.config.before_test_hook:
            try:
                self.config.before_test_hook(test_case)
            except Exception as e:
                self.logger.warning("Before-test hook failed: %s", e)
        for attempt in range(self.config.max_retries + 1):
            try:
                if self._evaluation_fn:
                    result = self._evaluation_fn(
                        test_case.input.content,
                        context=test_case.input.context,
                    )
                    if isinstance(result, dict):
                        actual_output = result
                    elif isinstance(result, ValidationResult):
                        actual_output = {
                            "matched_rule_ids": [r.id for r in result.matched_rules] if hasattr(result, "matched_rules") else [],
                            "matched_rule_names": [r.name for r in result.matched_rules] if hasattr(result, "matched_rules") else [],
                            "action_taken": result.action.value if hasattr(result, "action") else None,
                            "violations": [str(v) for v in result.violations] if hasattr(result, "violations") else [],
                            "score": result.confidence if hasattr(result, "confidence") else 1.0,
                            "duration_ms": (time.time() - start_time) * 1000,
                        }
                    else:
                        actual_output = {"raw_result": str(result)}
                else:
                    actual_output = self._simulate_evaluation(test_case)
            except Exception as e:
                errors.append(f"Attempt {attempt + 1}: {type(e).__name__}: {e}")
                if self.config.max_retries == 0 or attempt == self.config.max_retries:
                    if self.config.stack_trace_on_error:
                        errors.append(traceback.format_exc())
                    current_status = TestStatus.ERROR
                    actual_output = {"error": str(e)}
                    break
                time.sleep(0.1 * (attempt + 1))
                continue
            break
        elapsed_ms = (time.time() - start_time) * 1000
        if elapsed_ms > timeout_ms and current_status != TestStatus.ERROR:
            current_status = TestStatus.TIMEOUT
        if current_status == TestStatus.ERROR:
            result = TestResult(
                test_case=test_case,
                status=TestStatus.ERROR,
                actual_output=actual_output,
                duration_ms=elapsed_ms,
                errors=errors,
                executed_at=datetime.utcnow(),
            )
        elif current_status == TestStatus.TIMEOUT:
            result = TestResult(
                test_case=test_case,
                status=TestStatus.TIMEOUT,
                actual_output=actual_output,
                duration_ms=elapsed_ms,
                errors=["Test timed out"],
                executed_at=datetime.utcnow(),
            )
        else:
            result = self._comparator.compare(test_case, actual_output)
            result.duration_ms = elapsed_ms
            result.errors = errors
        if self.config.after_test_hook:
            try:
                self.config.after_test_hook(test_case, result)
            except Exception as e:
                self.logger.warning("After-test hook failed: %s", e)
        return result

    def _simulate_evaluation(self, test_case: TestCase) -> Dict[str, Any]:
        return {
            "matched_rule_ids": [],
            "matched_rule_names": [],
            "action_taken": None,
            "violations": [],
            "score": 0.0,
            "duration_ms": 1.0,
        }

    def run_test_suite(
        self,
        suite: TestSuite,
        rules: Optional[List[Rule]] = None,
    ) -> TestRunReport:
        run_id = f"TESTRUN-{uuid.uuid4().hex[:12]}"
        started_at = datetime.utcnow()
        self.logger.info(
            "Starting test suite '%s' (%d tests)",
            suite.name,
            len(suite.test_cases),
        )
        config_updates = suite.config_overrides
        if config_updates:
            original_config = {k: getattr(self.config, k) for k in config_updates if hasattr(self.config, k)}
            self.update_config(config_updates)
        results = []
        for test_case in suite.test_cases:
            if self.config.stop_on_first_failure and any(
                r.status in (TestStatus.FAILED, TestStatus.ERROR) for r in results
            ):
                result = TestResult(
                    test_case=test_case,
                    status=TestStatus.SKIPPED,
                    actual_output={},
                    duration_ms=0,
                )
                results.append(result)
                continue
            result = self.run_test_case(test_case)
            results.append(result)
        if config_updates:
            self.update_config(original_config)
        finished_at = datetime.utcnow()
        passed = sum(1 for r in results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in results if r.status == TestStatus.FAILED)
        errors = sum(1 for r in results if r.status == TestStatus.ERROR)
        skipped = sum(1 for r in results if r.status == TestStatus.SKIPPED)
        timeout = sum(1 for r in results if r.status == TestStatus.TIMEOUT)
        total_duration = (finished_at - started_at).total_seconds()
        coverage = None
        if self.config.coverage_enabled and rules:
            coverage = self._coverage_analyzer.analyze_coverage(rules, results)
        summary = {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "timeout": timeout,
            "pass_rate": round(passed / len(results) * 100, 2) if results else 0,
            "avg_duration_ms": statistics.mean([r.duration_ms for r in results]) if results else 0,
            "total_duration_ms": total_duration * 1000,
        }
        recommendations = self._generate_recommendations(summary, coverage)
        report = TestRunReport(
            run_id=run_id,
            suite_name=suite.name,
            started_at=started_at,
            finished_at=finished_at,
            total_tests=len(results),
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            results=results,
            coverage=coverage,
            summary=summary,
            duration_seconds=total_duration,
            config_used=self._config_to_dict(),
            recommendations=recommendations,
        )
        self._results_history.append(report)
        self.logger.info(
            "Test suite '%s' complete: %d/%d passed (%.1f%%)",
            suite.name, passed, len(results),
            summary["pass_rate"],
        )
        if self.config.export_results:
            self._export_report(report)
        return report

    def run_tests(
        self,
        test_cases: List[TestCase],
        rules: Optional[List[Rule]] = None,
        suite_name: str = "adhoc",
    ) -> TestRunReport:
        suite = TestSuite(
            name=suite_name,
            description="Ad-hoc test run",
            test_cases=test_cases,
        )
        return self.run_test_suite(suite, rules)

    def load_and_run_suite(
        self,
        suite_name: str,
        rules: Optional[List[Rule]] = None,
    ) -> Optional[TestRunReport]:
        suite = self._suite_loader.load_suite(suite_name)
        if not suite:
            self.logger.error("Suite '%s' not found", suite_name)
            return None
        return self.run_test_suite(suite, rules)

    def create_test_case(
        self,
        name: str,
        content: str,
        expected_rule_ids: Optional[List[str]] = None,
        context: Optional[Dict] = None,
        expected_action: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> TestCase:
        return TestCase(
            id=f"TC-{uuid.uuid4().hex[:8]}",
            name=name,
            description=f"Test case: {name}",
            input=TestInput(
                content=content,
                context=context or {},
                tags=tags or [],
            ),
            expected=ExpectedOutput(
                matched_rule_ids=expected_rule_ids or [],
                action=expected_action,
            ),
            tags=tags or [],
        )

    def analyze_coverage(self, rules: List[Rule], results: List[TestResult]) -> CoverageReport:
        return self._coverage_analyzer.analyze_coverage(rules, results)

    def get_results_by_status(self, report: TestRunReport, status: TestStatus) -> List[TestResult]:
        return [r for r in report.results if r.status == status]

    def get_failures(self, report: TestRunReport) -> List[TestResult]:
        return self.get_results_by_status(report, TestStatus.FAILED)

    def get_summary_text(self, report: TestRunReport) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append(f"TEST REPORT: {report.suite_name}")
        lines.append("=" * 60)
        lines.append(f"  Run ID: {report.run_id}")
        lines.append(f"  Duration: {report.duration_seconds:.2f}s")
        lines.append(f"  Total: {report.total_tests}")
        lines.append(f"  Passed: {report.passed}")
        lines.append(f"  Failed: {report.failed}")
        lines.append(f"  Errors: {report.errors}")
        lines.append(f"  Skipped: {report.skipped}")
        lines.append(f"  Pass Rate: {report.summary.get('pass_rate', 0):.1f}%")
        lines.append("")
        failures = self.get_failures(report)
        if failures:
            lines.append("--- FAILURES ---")
            for f in failures:
                lines.append(f"  [{f.status.value}] {f.test_case.name} ({f.test_case.id})")
                for m in f.mismatches[:5]:
                    lines.append(f"    - {m}")
                lines.append("")
        if report.coverage:
            lines.append("--- COVERAGE ---")
            lines.append(f"  Coverage: {report.coverage.coverage_pct:.1f}%")
            lines.append(f"  Covered: {report.coverage.covered_rules}/{report.coverage.total_rules}")
            if report.coverage.uncovered_rules:
                for name in report.coverage.uncovered_rules[:5]:
                    lines.append(f"    Uncovered: {name}")
        lines.append("")
        lines.append("--- Recommendations ---")
        for rec in report.recommendations:
            lines.append(f"  - {rec}")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def _generate_recommendations(self, summary: Dict, coverage: Optional[CoverageReport]) -> List[str]:
        recs = []
        if summary["pass_rate"] < 100:
            recs.append(f"Fix {summary['failed'] + summary['errors']} failing test(s) before deployment.")
        if summary["pass_rate"] < 80:
            recs.append("Critical: test pass rate below 80%. Investigate regressions.")
        if coverage:
            recs.extend(coverage.recommendations[:3])
        if summary["avg_duration_ms"] > 100:
            recs.append(f"Average test duration is {summary['avg_duration_ms']:.1f}ms. Consider optimizing slow evaluations.")
        if not recs:
            recs.append("All tests passing. No issues detected.")
        return recs

    def get_failed_test_details(self, report: TestRunReport) -> List[Dict[str, Any]]:
        details = []
        for result in self.get_failures(report):
            details.append({
                "test_id": result.test_case.id,
                "test_name": result.test_case.name,
                "status": result.status.value,
                "score": result.score,
                "duration_ms": result.duration_ms,
                "mismatches": result.mismatches,
                "errors": result.errors,
                "expected_rule_ids": result.test_case.expected.matched_rule_ids,
                "actual_rule_ids": result.matched_rule_ids,
                "expected_action": result.test_case.expected.action,
                "actual_action": result.actual_output.get("action_taken"),
            })
        return details

    def export_report(self, report: TestRunReport, filepath: Optional[str] = None) -> str:
        return self._export_report(report, filepath)

    def _export_report(self, report: TestRunReport, filepath: Optional[str] = None) -> str:
        data = {
            "run_id": report.run_id,
            "suite_name": report.suite_name,
            "started_at": report.started_at.isoformat(),
            "finished_at": report.finished_at.isoformat(),
            "duration_seconds": report.duration_seconds,
            "summary": report.summary,
            "recommendations": report.recommendations,
            "results": [
                {
                    "test_id": r.test_case.id,
                    "test_name": r.test_case.name,
                    "status": r.status.value,
                    "duration_ms": r.duration_ms,
                    "score": r.score,
                    "mismatches": r.mismatches,
                    "errors": r.errors,
                    "matched_rule_ids": r.matched_rule_ids,
                }
                for r in report.results
            ],
        }
        if report.coverage:
            data["coverage"] = {
                "total_rules": report.coverage.total_rules,
                "covered_rules": report.coverage.covered_rules,
                "coverage_pct": report.coverage.coverage_pct,
                "per_tier": report.coverage.per_tier_coverage,
                "per_type": report.coverage.per_type_coverage,
            }
        json_str = json.dumps(data, indent=2, default=str)
        if filepath:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json_str, encoding="utf-8")
            self.logger.info("Report exported to %s", filepath)
            return str(path)
        if self.config.export_dir:
            path = Path(self.config.export_dir) / f"testrun_{report.run_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json_str, encoding="utf-8")
            self.logger.info("Report exported to %s", path)
            return str(path)
        return json_str

    def discover_suites(self, dirpath: Optional[str] = None) -> List[str]:
        return self._suite_loader.discover_suites(dirpath)

    def load_suite(self, filepath: str) -> TestSuite:
        return self._suite_loader.load_from_file(filepath)

    def _config_to_dict(self) -> Dict[str, Any]:
        return {
            "comparison_method": self.config.comparison_method.value,
            "score_threshold": self.config.score_threshold,
            "timeout_per_test": self.config.timeout_per_test,
            "max_retries": self.config.max_retries,
            "stop_on_first_failure": self.config.stop_on_first_failure,
            "coverage_enabled": self.config.coverage_enabled,
            "strict_mode": self.config.strict_mode,
        }

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "comparison_method": {
                "type": "string",
                "enum": [e.value for e in ComparisonMethod],
                "default": "exact_match",
            },
            "score_threshold": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.8,
            },
            "timeout_per_test": {
                "type": "integer",
                "minimum": 100,
                "maximum": 60000,
                "default": 5000,
            },
            "max_retries": {"type": "integer", "minimum": 0, "default": 0},
            "stop_on_first_failure": {"type": "boolean", "default": False},
            "coverage_enabled": {"type": "boolean", "default": True},
            "strict_mode": {"type": "boolean", "default": False},
        }
