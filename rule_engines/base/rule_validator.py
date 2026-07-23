"""Rule validator - validates rule definitions, configurations, and cross-rule consistency."""
import logging
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationCategory(str, Enum):
    SYNTAX = "syntax"
    SEMANTIC = "semantic"
    CONSISTENCY = "consistency"
    SECURITY = "security"
    PERFORMANCE = "performance"
    COMPLIANCE = "compliance"


@dataclass
class ValidationIssue:
    category: ValidationCategory
    severity: ValidationSeverity
    message: str
    rule_id: Optional[str]
    field: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class ValidationReport:
    valid: bool
    issues: List[ValidationIssue]
    errors_count: int
    warnings_count: int
    info_count: int
    rules_validated: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RuleValidator:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._strict_mode = self.config.get("strict_mode", True)
        self._reports: List[ValidationReport] = []
        logger.info("RuleValidator initialized (strict_mode=%s)", self._strict_mode)

    def validate_rule(self, rule: Dict[str, Any]) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        rule_id = rule.get("id", "unknown")

        issues.extend(self._validate_required_fields(rule, rule_id))
        issues.extend(self._validate_tier(rule, rule_id))
        issues.extend(self._validate_enforcement(rule, rule_id))
        issues.extend(self._validate_patterns(rule, rule_id))
        issues.extend(self._validate_priority(rule, rule_id))
        issues.extend(self._validate_severity(rule, rule_id))
        issues.extend(self._validate_timeout(rule, rule_id))
        issues.extend(self._validate_conditions(rule, rule_id))
        issues.extend(self._validate_tags(rule, rule_id))

        return issues

    def validate_rules(self, rules: Dict[str, Dict[str, Any]]) -> ValidationReport:
        all_issues: List[ValidationIssue] = []
        for rid, rule_data in rules.items():
            issues = self.validate_rule(rule_data)
            all_issues.extend(issues)
        all_issues.extend(self._validate_cross_rule(rules))
        errors = [i for i in all_issues if i.severity == ValidationSeverity.ERROR]
        warnings = [i for i in all_issues if i.severity == ValidationSeverity.WARNING]
        infos = [i for i in all_issues if i.severity == ValidationSeverity.INFO]
        report = ValidationReport(
            valid=len(errors) == 0,
            issues=all_issues,
            errors_count=len(errors),
            warnings_count=len(warnings),
            info_count=len(infos),
            rules_validated=len(rules),
        )
        self._reports.append(report)
        logger.info("Validation: %s (errors=%d, warnings=%d, rules=%d)",
                     "PASS" if report.valid else "FAIL",
                     errors, warnings, len(rules))
        return report

    def _validate_required_fields(self, rule: Dict[str, Any], rid: str) -> List[ValidationIssue]:
        issues = []
        required = ["id", "name"]
        if self._strict_mode:
            required.extend(["description", "patterns"])
        for field in required:
            if field not in rule or not rule.get(field):
                issues.append(ValidationIssue(
                    category=ValidationCategory.SYNTAX,
                    severity=ValidationSeverity.ERROR,
                    message=f"Missing required field: '{field}'",
                    rule_id=rid, field=field,
                    suggestion=f"Add '{field}' to rule definition",
                ))
        return issues

    def _validate_tier(self, rule: Dict[str, Any], rid: str) -> List[ValidationIssue]:
        issues = []
        tier = rule.get("tier", "preference")
        valid_tiers = {"safety", "operational", "preference"}
        if tier not in valid_tiers:
            issues.append(ValidationIssue(
                category=ValidationCategory.SYNTAX,
                severity=ValidationSeverity.ERROR,
                message=f"Invalid tier: '{tier}'. Must be one of: {valid_tiers}",
                rule_id=rid, field="tier",
            ))
        return issues

    def _validate_enforcement(self, rule: Dict[str, Any], rid: str) -> List[ValidationIssue]:
        issues = []
        tier = rule.get("tier", "preference")
        enforcement = rule.get("enforcement", "advisory")
        valid = {"strict", "advisory", "adaptive"}
        if enforcement not in valid:
            issues.append(ValidationIssue(
                category=ValidationCategory.SYNTAX,
                severity=ValidationSeverity.ERROR,
                message=f"Invalid enforcement: '{enforcement}'",
                rule_id=rid, field="enforcement",
            ))
        if tier == "safety" and enforcement != "strict":
            issues.append(ValidationIssue(
                category=ValidationCategory.COMPLIANCE,
                severity=ValidationSeverity.ERROR,
                message=f"Safety rules must use 'strict' enforcement, got '{enforcement}'",
                rule_id=rid, field="enforcement",
                suggestion="Change enforcement to 'strict'",
            ))
        if tier == "safety" and rule.get("user_override", False):
            issues.append(ValidationIssue(
                category=ValidationCategory.SECURITY,
                severity=ValidationSeverity.ERROR,
                message="Safety rules must not allow user override",
                rule_id=rid, field="user_override",
                suggestion="Set user_override to false",
            ))
        return issues

    def _validate_patterns(self, rule: Dict[str, Any], rid: str) -> List[ValidationIssue]:
        issues = []
        patterns = rule.get("patterns", [])
        if not patterns and self._strict_mode:
            issues.append(ValidationIssue(
                category=ValidationCategory.SEMANTIC,
                severity=ValidationSeverity.WARNING,
                message="Rule has no patterns defined",
                rule_id=rid, field="patterns",
                suggestion="Add at least one pattern for rule to be effective",
            ))
        for p in patterns:
            if isinstance(p, str):
                try:
                    re.compile(p)
                except re.error as e:
                    issues.append(ValidationIssue(
                        category=ValidationCategory.SYNTAX,
                        severity=ValidationSeverity.ERROR,
                        message=f"Invalid regex pattern: {e}",
                        rule_id=rid, field="patterns",
                    ))
        return issues

    def _validate_priority(self, rule: Dict[str, Any], rid: str) -> List[ValidationIssue]:
        issues = []
        priority = rule.get("priority", 100)
        if not isinstance(priority, int) or priority < 1 or priority > 1000:
            issues.append(ValidationIssue(
                category=ValidationCategory.SYNTAX,
                severity=ValidationSeverity.ERROR,
                message=f"Priority must be integer 1-1000, got {priority}",
                rule_id=rid, field="priority",
            ))
        return issues

    def _validate_severity(self, rule: Dict[str, Any], rid: str) -> List[ValidationIssue]:
        issues = []
        severity = rule.get("severity", "medium")
        valid = {"critical", "high", "medium", "low", "info"}
        if severity not in valid:
            issues.append(ValidationIssue(
                category=ValidationCategory.SYNTAX,
                severity=ValidationSeverity.ERROR,
                message=f"Invalid severity: '{severity}'",
                rule_id=rid, field="severity",
            ))
        tier = rule.get("tier", "preference")
        if tier == "safety" and severity not in ("critical", "high"):
            issues.append(ValidationIssue(
                category=ValidationCategory.COMPLIANCE,
                severity=ValidationSeverity.WARNING,
                message=f"Safety rule should have at least 'high' severity, got '{severity}'",
                rule_id=rid, field="severity",
            ))
        return issues

    def _validate_timeout(self, rule: Dict[str, Any], rid: str) -> List[ValidationIssue]:
        issues = []
        timeout = rule.get("timeout_ms", 1000)
        if not isinstance(timeout, (int, float)) or timeout < 1 or timeout > 30000:
            issues.append(ValidationIssue(
                category=ValidationCategory.PERFORMANCE,
                severity=ValidationSeverity.ERROR,
                message=f"Timeout must be 1-30000ms, got {timeout}",
                rule_id=rid, field="timeout_ms",
            ))
        return issues

    def _validate_conditions(self, rule: Dict[str, Any], rid: str) -> List[ValidationIssue]:
        issues = []
        conditions = rule.get("conditions", {})
        if conditions and not isinstance(conditions, dict):
            issues.append(ValidationIssue(
                category=ValidationCategory.SYNTAX,
                severity=ValidationSeverity.ERROR,
                message="Conditions must be a dictionary",
                rule_id=rid, field="conditions",
            ))
        return issues

    def _validate_tags(self, rule: Dict[str, Any], rid: str) -> List[ValidationIssue]:
        issues = []
        tags = rule.get("tags", [])
        if not isinstance(tags, list):
            issues.append(ValidationIssue(
                category=ValidationCategory.SYNTAX,
                severity=ValidationSeverity.ERROR,
                message="Tags must be a list",
                rule_id=rid, field="tags",
            ))
        return issues

    def _validate_cross_rule(self, rules: Dict[str, Dict[str, Any]]) -> List[ValidationIssue]:
        issues = []
        ids: Set[str] = set()
        names: Set[str] = set()
        for rid, rule in rules.items():
            if rid in ids:
                issues.append(ValidationIssue(
                    category=ValidationCategory.CONSISTENCY,
                    severity=ValidationSeverity.ERROR,
                    message=f"Duplicate rule ID: {rid}",
                    rule_id=rid,
                    suggestion="Ensure each rule has a unique ID",
                ))
            ids.add(rid)
            name = rule.get("name", "")
            if name and name in names:
                issues.append(ValidationIssue(
                    category=ValidationCategory.CONSISTENCY,
                    severity=ValidationSeverity.WARNING,
                    message=f"Duplicate rule name: '{name}'",
                    rule_id=rid,
                    suggestion="Consider using unique rule names",
                ))
            names.add(name)
        return issues

    def get_last_report(self) -> Optional[ValidationReport]:
        return self._reports[-1] if self._reports else None

    def get_statistics(self) -> Dict[str, Any]:
        if not self._reports:
            return {"total_validations": 0}
        return {
            "total_validations": len(self._reports),
            "pass_rate": sum(1 for r in self._reports if r.valid) / len(self._reports),
            "last_valid": self._reports[-1].valid if self._reports else False,
        }
