"""
Error classification engine for exception handling.

Classifies errors by type, severity, and pattern with deduplication,
grouping, remediation suggestions, config-driven classification rules,
and trend analysis.
"""

import logging
import uuid
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class ErrorType(str, Enum):
    """High-level error categories."""
    VALIDATION = "validation"
    SYSTEM = "system"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    PERFORMANCE = "performance"
    DATA_QUALITY = "data_quality"
    BUSINESS_LOGIC = "business_logic"
    INTEGRATION = "integration"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class ClassificationMethod(str, Enum):
    """Method used for classification."""
    RULE_BASED = "rule_based"
    PATTERN_MATCH = "pattern_match"
    SEVERITY_BASED = "severity_based"
    SEMANTIC = "semantic"
    STATISTICAL = "statistical"
    MANUAL = "manual"


class ErrorGroupStatus(str, Enum):
    """Status of an error group."""
    ACTIVE = "active"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    WONTFIX = "wontfix"


@dataclass
class ClassificationRule:
    """Config-driven classification rule definition."""
    rule_id: str
    name: str
    error_type: ErrorType
    conditions: Dict[str, Any] = field(default_factory=dict)
    priority: int = 100
    enabled: bool = True
    description: str = ""

    def matches_violation(self, violation: Violation) -> bool:
        type_match = True
        if "violation_types" in self.conditions:
            allowed = self.conditions["violation_types"]
            type_match = violation.violation_type.value in allowed
        severity_match = True
        if "severities" in self.conditions:
            allowed_sevs = self.conditions["severities"]
            severity_match = violation.rule_severity.value in allowed_sevs
        tier_match = True
        if "tiers" in self.conditions:
            allowed_tiers = self.conditions["tiers"]
            tier_match = violation.rule_tier.value in allowed_tiers
        content_match = True
        if "content_patterns" in self.conditions:
            patterns = self.conditions["content_patterns"]
            content = (violation.matched_content or "") + (violation.explanation or "")
            content_match = any(
                re.search(p, content, re.IGNORECASE) for p in patterns
            )
        return type_match and severity_match and tier_match and content_match

    def matches_context(self, context: Dict[str, Any]) -> bool:
        if not self.conditions.get("context_conditions"):
            return True
        for key, expected in self.conditions["context_conditions"].items():
            actual = context.get(key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif isinstance(expected, dict):
                if "min" in expected and (actual is None or actual < expected["min"]):
                    return False
                if "max" in expected and (actual is None or actual > expected["max"]):
                    return False
            elif actual != expected:
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "error_type": self.error_type.value,
        }


@dataclass
class ClassificationResult:
    """Result of a single error classification."""
    classification_id: str
    source_id: str
    error_type: ErrorType
    severity: RuleSeverity
    method: ClassificationMethod
    rule_id: Optional[str] = None
    confidence: float = 1.0
    patterns_matched: List[str] = field(default_factory=list)
    group_id: Optional[str] = None
    is_duplicate: bool = False
    original_classification_id: Optional[str] = None
    remediation_suggestions: List[str] = field(default_factory=list)
    classified_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "error_type": self.error_type.value,
            "severity": self.severity.value,
            "method": self.method.value,
            "classified_at": self.classified_at.isoformat(),
        }


@dataclass
class ErrorGroup:
    """Group of related errors for deduplication and trending."""
    group_id: str
    error_type: ErrorType
    severity: RuleSeverity
    status: ErrorGroupStatus = ErrorGroupStatus.ACTIVE
    signature: str = ""
    title: str = ""
    description: str = ""
    classification_ids: List[str] = field(default_factory=list)
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    occurrence_count: int = 0
    unique_sources: Set[str] = field(default_factory=set)
    tags: List[str] = field(default_factory=list)
    assigned_to: Optional[str] = None
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "error_type": self.error_type.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "unique_sources": list(self.unique_sources),
            "occurrence_count": self.occurrence_count,
        }


@dataclass
class ErrorClassifierConfig:
    """Configuration for the ErrorClassifier."""
    config_id: str = "default_error_classifier"
    classification_rules: List[ClassificationRule] = field(default_factory=list)
    dedup_window_minutes: int = 60
    max_group_size: int = 10000
    auto_group: bool = True
    enable_statistics: bool = True
    max_history_size: int = 100000
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_rule(self, rule: ClassificationRule) -> None:
        self.classification_rules.append(rule)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_id": self.config_id,
            "classification_rules": [r.to_dict() for r in self.classification_rules],
            "dedup_window_minutes": self.dedup_window_minutes,
            "max_group_size": self.max_group_size,
            "auto_group": self.auto_group,
            "enable_statistics": self.enable_statistics,
            "max_history_size": self.max_history_size,
            "version": self.version,
            "metadata": self.metadata,
        }


class ErrorClassifier:
    """Error classification engine with pattern matching, grouping, and trend analysis."""

    def __init__(self, config: Optional[ErrorClassifierConfig] = None) -> None:
        self.logger = logger
        self.config = config or self._default_config()
        self._classifications: Dict[str, ClassificationResult] = {}
        self._groups: Dict[str, ErrorGroup] = {}
        self._signature_index: Dict[str, List[str]] = {}
        self._daily_stats: Dict[str, Dict[str, int]] = {}
        self._hourly_stats: Dict[str, Dict[str, int]] = {}
        self._type_counts: Dict[str, int] = {}
        self._severity_counts: Dict[str, int] = {}
        self._recent_classifications: List[str] = []
        self._handlers: Dict[str, List[Callable]] = {
            "on_classify": [],
            "on_group": [],
            "on_dedup": [],
        }
        self._init_default_rules()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _default_config(self) -> ErrorClassifierConfig:
        config = ErrorClassifierConfig(config_id="default")
        return config

    def _init_default_rules(self) -> None:
        default_rules = [
            ClassificationRule(
                rule_id="classify_validation",
                name="Validation Error Classification",
                error_type=ErrorType.VALIDATION,
                conditions={
                    "violation_types": [
                        ViolationType.KEYWORD_MATCH.value,
                        ViolationType.REGEX_MATCH.value,
                        ViolationType.STRUCTURAL_VIOLATION.value,
                        ViolationType.QUALITY_VIOLATION.value,
                        ViolationType.CUSTOM_VIOLATION.value,
                    ],
                },
                priority=10,
                description="Classify rule validation errors",
            ),
            ClassificationRule(
                rule_id="classify_security",
                name="Security Error Classification",
                error_type=ErrorType.SECURITY,
                conditions={
                    "content_patterns": [
                        r"sql.injection", r"xss", r"cross.site.scripting",
                        r"rce", r"remote.code.execution", r"auth.bypass",
                        r"privilege.escalation", r"path.traversal",
                        r"injection", r"ssrf", r"csrf",
                    ],
                },
                priority=20,
                description="Classify security-related errors",
            ),
            ClassificationRule(
                rule_id="classify_compliance",
                name="Compliance Error Classification",
                error_type=ErrorType.COMPLIANCE,
                conditions={
                    "content_patterns": [
                        r"gdpr", r"hipaa", r"pci", r"sox", r"ccpa",
                        r"compliance", r"regulatory", r"audit",
                    ],
                },
                priority=30,
                description="Classify compliance-related errors",
            ),
            ClassificationRule(
                rule_id="classify_system",
                name="System Error Classification",
                error_type=ErrorType.SYSTEM,
                conditions={
                    "violation_types": [ViolationType.SEMANTIC_VIOLATION.value],
                    "content_patterns": [
                        r"timeout", r"exception", r"error", r"crash",
                        r"unavailable", r"overflow", r"memory",
                        r"connection", r"disconnect",
                    ],
                },
                priority=40,
                description="Classify system-level errors",
            ),
            ClassificationRule(
                rule_id="classify_performance",
                name="Performance Error Classification",
                error_type=ErrorType.PERFORMANCE,
                conditions={
                    "content_patterns": [
                        r"performance", r"latency", r"throughput",
                        r"slow", r"degradation", r"bottleneck",
                        r"timeout", r"exceeded.*limit",
                    ],
                },
                priority=50,
                description="Classify performance-related errors",
            ),
            ClassificationRule(
                rule_id="classify_data_quality",
                name="Data Quality Error Classification",
                error_type=ErrorType.DATA_QUALITY,
                conditions={
                    "content_patterns": [
                        r"data.quality", r"integrity", r"corruption",
                        r"duplicate", r"inconsistent", r"malformed",
                        r"missing.*field", r"invalid.*format",
                    ],
                },
                priority=60,
                description="Classify data quality errors",
            ),
            ClassificationRule(
                rule_id="classify_business_logic",
                name="Business Logic Error Classification",
                error_type=ErrorType.BUSINESS_LOGIC,
                conditions={
                    "content_patterns": [
                        r"business.logic", r"workflow", r"state",
                        r"transition", r"precondition", r"postcondition",
                        r"invariant",
                    ],
                },
                priority=70,
                description="Classify business logic errors",
            ),
            ClassificationRule(
                rule_id="classify_integration",
                name="Integration Error Classification",
                error_type=ErrorType.INTEGRATION,
                conditions={
                    "content_patterns": [
                        r"integration", r"api.*error", r"service.*unavailable",
                        r"downstream", r"upstream", r"external.*service",
                        r"provider", r"webhook.*fail",
                    ],
                },
                priority=80,
                description="Classify integration-related errors",
            ),
        ]
        for rule in default_rules:
            self.config.add_rule(rule)

    def load_config(self, config: ErrorClassifierConfig) -> None:
        self.config = config

    def add_classification_rule(self, rule: ClassificationRule) -> None:
        self.config.add_rule(rule)

    def remove_classification_rule(self, rule_id: str) -> bool:
        initial = len(self.config.classification_rules)
        self.config.classification_rules = [
            r for r in self.config.classification_rules if r.rule_id != rule_id
        ]
        return len(self.config.classification_rules) < initial

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    def on_classify(self, handler: Callable) -> None:
        self._handlers["on_classify"].append(handler)

    def on_group(self, handler: Callable) -> None:
        self._handlers["on_group"].append(handler)

    def on_dedup(self, handler: Callable) -> None:
        self._handlers["on_dedup"].append(handler)

    def _fire_event(self, event: str, **kwargs: Any) -> None:
        for handler in self._handlers.get(event, []):
            try:
                handler(**kwargs)
            except Exception as exc:
                self.logger.error("Event handler %s failed: %s", event, exc)

    # ------------------------------------------------------------------
    # Core Classification
    # ------------------------------------------------------------------

    def classify(
        self,
        violation: Violation,
        context: Optional[Dict[str, Any]] = None,
    ) -> ClassificationResult:
        context = context or {}
        error_type = self._determine_error_type(violation, context)
        method = ClassificationMethod.RULE_BASED if context.get("rule_match") else ClassificationMethod.PATTERN_MATCH
        matched_rule = self._find_matching_rule(violation, context)
        if matched_rule:
            error_type = matched_rule.error_type
            method = ClassificationMethod.RULE_BASED

        severity = self._classify_severity(violation, error_type)
        patterns = self._extract_patterns(violation)
        suggestions = self._suggest_remediation(error_type, severity, patterns)

        classification_id = self._generate_classification_id(violation)
        group_id = None
        is_duplicate = False
        original_id = None

        if self.config.auto_group:
            signature = self._compute_signature(violation, error_type)
            group_result = self._resolve_group(signature, error_type, severity, classification_id, violation)
            group_id = group_result["group_id"]
            is_duplicate = group_result["is_duplicate"]
            original_id = group_result.get("original_classification_id")

        result = ClassificationResult(
            classification_id=classification_id,
            source_id=violation.rule_id,
            error_type=error_type,
            severity=severity,
            method=method,
            rule_id=matched_rule.rule_id if matched_rule else None,
            confidence=self._compute_confidence(violation, matched_rule),
            patterns_matched=patterns,
            group_id=group_id,
            is_duplicate=is_duplicate,
            original_classification_id=original_id,
            remediation_suggestions=suggestions,
            metadata={
                "violation_type": violation.violation_type.value,
                "rule_tier": violation.rule_tier.value,
                "action_taken": violation.action_taken.value,
                "context": context,
            },
        )
        self._classifications[classification_id] = result
        self._update_statistics(result)
        self._recent_classifications.append(classification_id)
        self._trim_history()

        if is_duplicate:
            self._fire_event("on_dedup", result=result, original_id=original_id)
        self._fire_event("on_classify", result=result, violation=violation)
        self.logger.debug(
            "Classified violation %s as %s/%s (dup=%s)",
            classification_id, error_type.value, severity.value, is_duplicate,
        )
        return result

    def classify_batch(
        self,
        violations: List[Violation],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[ClassificationResult]:
        return [self.classify(v, context) for v in violations]

    def classify_result(
        self,
        result: ValidationResult,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[ClassificationResult]:
        all_violations = result.violations + result.warnings
        return self.classify_batch(all_violations, context)

    # ------------------------------------------------------------------
    # Error Type Determination
    # ------------------------------------------------------------------

    def _determine_error_type(self, violation: Violation, context: Dict[str, Any]) -> ErrorType:
        matched_rule = self._find_matching_rule(violation, context)
        if matched_rule:
            return matched_rule.error_type
        if violation.rule_tier == RuleTier.SAFETY:
            return ErrorType.SECURITY
        if violation.violation_type in (
            ViolationType.COMPLIANCE_VIOLATION,
        ):
            return ErrorType.COMPLIANCE
        if violation.violation_type in (
            ViolationType.KEYWORD_MATCH,
            ViolationType.REGEX_MATCH,
            ViolationType.STRUCTURAL_VIOLATION,
        ):
            return ErrorType.VALIDATION
        if violation.violation_type == ViolationType.SEMANTIC_VIOLATION:
            return ErrorType.BUSINESS_LOGIC
        return ErrorType.UNKNOWN

    def _find_matching_rule(
        self,
        violation: Violation,
        context: Dict[str, Any],
    ) -> Optional[ClassificationRule]:
        for rule in sorted(self.config.classification_rules, key=lambda r: r.priority):
            if not rule.enabled:
                continue
            if rule.matches_violation(violation) and rule.matches_context(context):
                return rule
        return None

    # ------------------------------------------------------------------
    # Severity Classification
    # ------------------------------------------------------------------

    def _classify_severity(self, violation: Violation, error_type: ErrorType) -> RuleSeverity:
        if error_type == ErrorType.SECURITY:
            return self._classify_security_severity(violation)
        if error_type == ErrorType.COMPLIANCE:
            return self._classify_compliance_severity(violation)
        if error_type == ErrorType.SYSTEM:
            return self._classify_system_severity(violation)
        if error_type == ErrorType.PERFORMANCE:
            return self._classify_performance_severity(violation)
        return violation.rule_severity

    def _classify_security_severity(self, violation: Violation) -> RuleSeverity:
        critical_patterns = [
            r"rce", r"remote.code.execution", r"sql.injection",
            r"auth.bypass", r"privilege.escalation",
        ]
        high_patterns = [
            r"xss", r"ssrf", r"path.traversal", r"csrf",
            r"idor", r"insecure.direct.object.reference",
        ]
        content = (violation.matched_content or "") + (violation.explanation or "")
        if any(re.search(p, content, re.IGNORECASE) for p in critical_patterns):
            return RuleSeverity.CRITICAL
        if any(re.search(p, content, re.IGNORECASE) for p in high_patterns):
            return RuleSeverity.HIGH
        if violation.rule_severity == RuleSeverity.CRITICAL:
            return RuleSeverity.CRITICAL
        return violation.rule_severity

    def _classify_compliance_severity(self, violation: Violation) -> RuleSeverity:
        critical_regulations = [
            r"gdpr.*breach", r"pci.*violation", r"hipaa.*breach",
            r"sox.*violation", r"data.*breach",
        ]
        content = (violation.matched_content or "") + (violation.explanation or "")
        if any(re.search(p, content, re.IGNORECASE) for p in critical_regulations):
            return RuleSeverity.CRITICAL
        if violation.rule_severity in (RuleSeverity.CRITICAL, RuleSeverity.HIGH):
            return RuleSeverity.HIGH
        return RuleSeverity.MEDIUM

    def _classify_system_severity(self, violation: Violation) -> RuleSeverity:
        critical_patterns = [
            r"crash", r"data.loss", r"corruption", r"unavailable",
            r"outage", r"overflow",
        ]
        content = (violation.matched_content or "") + (violation.explanation or "")
        if any(re.search(p, content, re.IGNORECASE) for p in critical_patterns):
            return RuleSeverity.CRITICAL
        return RuleSeverity.HIGH

    def _classify_performance_severity(self, violation: Violation) -> RuleSeverity:
        critical_patterns = [
            r"outage", r"complete.*degradation", r"downtime",
        ]
        content = (violation.matched_content or "") + (violation.explanation or "")
        if any(re.search(p, content, re.IGNORECASE) for p in critical_patterns):
            return RuleSeverity.CRITICAL
        return RuleSeverity.MEDIUM

    def classify_error_type(
        self,
        error_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ErrorType:
        context = context or {}
        for rule in sorted(self.config.classification_rules, key=lambda r: r.priority):
            if not rule.enabled:
                continue
            if "content_patterns" in rule.conditions:
                patterns = rule.conditions["content_patterns"]
                if any(re.search(p, error_message, re.IGNORECASE) for p in patterns):
                    return rule.error_type
        return ErrorType.UNKNOWN

    def classify_severity(
        self,
        error_message: str,
        error_type: Optional[ErrorType] = None,
    ) -> RuleSeverity:
        critical_patterns = [
            r"critical", r"emergency", r"data.breach", r"rce",
            r"remote.code", r"crash", r"outage", r"data.loss",
        ]
        high_patterns = [
            r"high", r"severe", r"major", r"exploit", r"vulnerability",
            r"breach", r"unauthorized",
        ]
        if any(re.search(p, error_message, re.IGNORECASE) for p in critical_patterns):
            return RuleSeverity.CRITICAL
        if any(re.search(p, error_message, re.IGNORECASE) for p in high_patterns):
            return RuleSeverity.HIGH
        if error_type in (ErrorType.SECURITY, ErrorType.COMPLIANCE):
            return RuleSeverity.HIGH
        if error_type == ErrorType.SYSTEM:
            return RuleSeverity.MEDIUM
        return RuleSeverity.LOW

    # ------------------------------------------------------------------
    # Pattern Extraction
    # ------------------------------------------------------------------

    def _extract_patterns(self, violation: Violation) -> List[str]:
        patterns: List[str] = []
        content = (violation.matched_content or "") + " " + (violation.explanation or "")
        pattern_map: Dict[str, str] = {
            r"sql\s+(injection|inject)": "sql_injection",
            r"cross.?site.?script": "xss",
            r"remote.?code.?execution": "rce",
            r"auth(orization|entication).?bypass": "auth_bypass",
            r"privilege.?escalation": "privilege_escalation",
            r"path.?traversal": "path_traversal",
            r"server.?side.?request.?forgery": "ssrf",
            r"cross.?site.?request.?forgery": "csrf",
            r"(general|personal).?data.?protection.?regulation": "gdpr",
            r"health.?insurance.?portability": "hipaa",
            r"payment.?card.?industry": "pci",
            r"sarbanes.?oxley": "sox",
            r"california.?consumer.?privacy": "ccpa",
            r"insecure.?direct.?object.?reference": "idor",
            r"buffer.?overflow": "buffer_overflow",
            r"format.?string": "format_string",
            r"race.?condition": "race_condition",
            r"timing.?attack": "timing_attack",
            r"clickjack": "clickjacking",
        }
        for regex, pattern_name in pattern_map.items():
            if re.search(regex, content, re.IGNORECASE):
                patterns.append(pattern_name)
        if violation.violation_type.value not in patterns:
            patterns.append(violation.violation_type.value)
        return patterns

    # ------------------------------------------------------------------
    # Grouping & Deduplication
    # ------------------------------------------------------------------

    def _compute_signature(self, violation: Violation, error_type: ErrorType) -> str:
        raw = json.dumps({
            "error_type": error_type.value,
            "violation_type": violation.violation_type.value,
            "rule_id": violation.rule_id,
            "severity": violation.rule_severity.value,
            "normalized_content": self._normalize_content(violation.matched_content or ""),
        }, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    @staticmethod
    def _normalize_content(content: str) -> str:
        normalized = content.lower().strip()
        normalized = re.sub(r'\d+', '<NUM>', normalized)
        normalized = re.sub(r'[\'"`]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized[:200]

    def _resolve_group(
        self,
        signature: str,
        error_type: ErrorType,
        severity: RuleSeverity,
        classification_id: str,
        violation: Violation,
    ) -> Dict[str, Any]:
        if signature in self._signature_index:
            existing_ids = self._signature_index[signature]
            for gid in existing_ids:
                group = self._groups.get(gid)
                if group:
                    group.last_seen = datetime.utcnow()
                    group.occurrence_count += 1
                    if classification_id not in group.classification_ids:
                        group.classification_ids.append(classification_id)
                    if violation.rule_id:
                        group.unique_sources.add(violation.rule_id)
                    return {
                        "group_id": gid,
                        "is_duplicate": True,
                        "original_classification_id": group.classification_ids[0],
                    }
        group_id = f"grp_{uuid.uuid4().hex[:12]}"
        title = f"{error_type.value}/{severity.value}: {violation.rule_name}"
        group = ErrorGroup(
            group_id=group_id,
            error_type=error_type,
            severity=severity,
            signature=signature,
            title=title,
            description=violation.explanation or violation.matched_content or "",
            classification_ids=[classification_id],
            occurrence_count=1,
            unique_sources={violation.rule_id} if violation.rule_id else set(),
        )
        self._groups[group_id] = group
        self._signature_index.setdefault(signature, []).append(group_id)
        self._fire_event("on_group", group=group, classification_id=classification_id)
        return {
            "group_id": group_id,
            "is_duplicate": False,
            "original_classification_id": None,
        }

    def find_group(self, group_id: str) -> Optional[ErrorGroup]:
        return self._groups.get(group_id)

    def find_groups_by_type(self, error_type: ErrorType) -> List[ErrorGroup]:
        return [g for g in self._groups.values() if g.error_type == error_type]

    def find_groups_by_status(self, status: ErrorGroupStatus) -> List[ErrorGroup]:
        return [g for g in self._groups.values() if g.status == status]

    def find_groups_by_severity(self, severity: RuleSeverity) -> List[ErrorGroup]:
        return [g for g in self._groups.values() if g.severity == severity]

    def update_group_status(self, group_id: str, status: ErrorGroupStatus, notes: Optional[str] = None) -> bool:
        group = self._groups.get(group_id)
        if not group:
            return False
        group.status = status
        if notes:
            group.notes = notes
        return True

    def assign_group(self, group_id: str, assignee: str) -> bool:
        group = self._groups.get(group_id)
        if not group:
            return False
        group.assigned_to = assignee
        return True

    def merge_groups(self, target_group_id: str, source_group_id: str) -> bool:
        target = self._groups.get(target_group_id)
        source = self._groups.get(source_group_id)
        if not target or not source:
            return False
        target.classification_ids.extend(source.classification_ids)
        target.occurrence_count += source.occurrence_count
        target.unique_sources.update(source.unique_sources)
        target.last_seen = max(target.last_seen, source.last_seen)
        del self._groups[source_group_id]
        for sig, gids in self._signature_index.items():
            if source_group_id in gids:
                gids.remove(source_group_id)
                if target_group_id not in gids:
                    gids.append(target_group_id)
        return True

    # ------------------------------------------------------------------
    # Confidence Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_confidence(violation: Violation, matched_rule: Optional[ClassificationRule]) -> float:
        base = violation.confidence_score
        if matched_rule:
            base = min(1.0, base + 0.1)
        if violation.rule_tier == RuleTier.SAFETY:
            base = min(1.0, base + 0.05)
        return round(base, 4)

    # ------------------------------------------------------------------
    # Remediation Suggestions
    # ------------------------------------------------------------------

    def _suggest_remediation(
        self,
        error_type: ErrorType,
        severity: RuleSeverity,
        patterns: List[str],
    ) -> List[str]:
        suggestions: List[str] = []
        if error_type == ErrorType.VALIDATION:
            suggestions.append("Review input validation rules for appropriate constraints")
            suggestions.append("Consider adding more specific validation patterns")
            suggestions.append("Check if validation threshold needs adjustment")
        elif error_type == ErrorType.SECURITY:
            suggestions.append("Immediately review and patch the identified security vulnerability")
            suggestions.append("Conduct security impact assessment for affected systems")
            suggestions.append("Update WAF rules if applicable")
            suggestions.append("Review access control and authentication mechanisms")
            if "sql_injection" in patterns:
                suggestions.append("Switch to parameterized queries or prepared statements")
                suggestions.append("Implement input sanitization for all user-supplied data")
            if "xss" in patterns:
                suggestions.append("Implement Content Security Policy (CSP) headers")
                suggestions.append("Apply output encoding for all user-supplied content")
        elif error_type == ErrorType.COMPLIANCE:
            regulations = [p for p in patterns if p in ("gdpr", "hipaa", "pci", "sox", "ccpa")]
            if regulations:
                suggestions.append(f"Review {', '.join(regulations).upper()} compliance requirements")
            suggestions.append("Consult legal/compliance team for regulatory impact")
            suggestions.append("Audit data handling and storage practices")
        elif error_type == ErrorType.SYSTEM:
            suggestions.append("Check system logs for additional error context")
            suggestions.append("Verify system resource availability (memory, disk, CPU)")
            suggestions.append("Review recent deployments or configuration changes")
            suggestions.append("Consider restarting affected service or component")
        elif error_type == ErrorType.PERFORMANCE:
            suggestions.append("Investigate recent changes in traffic patterns")
            suggestions.append("Review database query performance and indexing")
            suggestions.append("Check for resource contention or memory leaks")
            suggestions.append("Consider scaling resources or optimizing code paths")
        elif error_type == ErrorType.DATA_QUALITY:
            suggestions.append("Validate data source integrity and freshness")
            suggestions.append("Check ETL pipelines for data transformation errors")
            suggestions.append("Review data validation rules and constraints")
        elif error_type == ErrorType.BUSINESS_LOGIC:
            suggestions.append("Review business logic workflow and state transitions")
            suggestions.append("Verify preconditions and postconditions are enforced")
            suggestions.append("Check for edge cases in business rule implementation")
        elif error_type == ErrorType.INTEGRATION:
            suggestions.append("Check connectivity and authentication with external services")
            suggestions.append("Review API contract and expected response formats")
            suggestions.append("Implement circuit breaker pattern for external calls")
        elif error_type == ErrorType.CONFIGURATION:
            suggestions.append("Review configuration file syntax and values")
            suggestions.append("Check environment-specific configuration overrides")
            suggestions.append("Validate configuration against schema")
        if severity in (RuleSeverity.CRITICAL, RuleSeverity.HIGH):
            suggestions.append("ESCALATE: This issue requires immediate attention")
        suggestions.append("Document the error conditions and remediation steps")
        return suggestions

    def get_remediation_suggestions(
        self,
        error_type: ErrorType,
        severity: RuleSeverity,
        patterns: Optional[List[str]] = None,
    ) -> List[str]:
        return self._suggest_remediation(error_type, severity, patterns or [])

    def get_remediation_for_classification(self, classification_id: str) -> List[str]:
        result = self._classifications.get(classification_id)
        if not result:
            return []
        return result.remediation_suggestions

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def _update_statistics(self, result: ClassificationResult) -> None:
        if not self.config.enable_statistics:
            return
        type_key = result.error_type.value
        self._type_counts[type_key] = self._type_counts.get(type_key, 0) + 1
        sev_key = result.severity.value
        self._severity_counts[sev_key] = self._severity_counts.get(sev_key, 0) + 1
        date_key = result.classified_at.strftime("%Y-%m-%d")
        hour_key = result.classified_at.strftime("%Y-%m-%d-%H")
        if date_key not in self._daily_stats:
            self._daily_stats[date_key] = {}
        self._daily_stats[date_key][type_key] = self._daily_stats[date_key].get(type_key, 0) + 1
        if hour_key not in self._hourly_stats:
            self._hourly_stats[hour_key] = {}
        self._hourly_stats[hour_key][type_key] = self._hourly_stats[hour_key].get(type_key, 0) + 1

    def _trim_history(self) -> None:
        if len(self._classifications) > self.config.max_history_size:
            excess = len(self._classifications) - self.config.max_history_size
            for cid in self._recent_classifications[:excess]:
                self._classifications.pop(cid, None)
            self._recent_classifications = self._recent_classifications[excess:]

    def get_statistics(self) -> Dict[str, Any]:
        total = len(self._classifications)
        by_type = dict(self._type_counts)
        by_severity = dict(self._severity_counts)
        group_count = len(self._groups)
        dup_count = sum(1 for c in self._classifications.values() if c.is_duplicate)
        return {
            "total_classifications": total,
            "unique_classifications": total - dup_count,
            "duplicates_suppressed": dup_count,
            "duplicate_rate": round(dup_count / total * 100, 2) if total else 0.0,
            "by_error_type": by_type,
            "by_severity": by_severity,
            "active_groups": group_count,
            "groups_by_type": {t: len(self.find_groups_by_type(ErrorType(t))) for t in by_type},
            "groups_by_status": {s.value: len(self.find_groups_by_status(s)) for s in ErrorGroupStatus},
        }

    def get_type_statistics(self, error_type: ErrorType) -> Dict[str, Any]:
        type_classifications = [
            c for c in self._classifications.values() if c.error_type == error_type
        ]
        total = len(type_classifications)
        if total == 0:
            return {"error_type": error_type.value, "total": 0}
        severity_dist = {}
        for c in type_classifications:
            sev = c.severity.value
            severity_dist[sev] = severity_dist.get(sev, 0) + 1
        groups = self.find_groups_by_type(error_type)
        return {
            "error_type": error_type.value,
            "total_classifications": total,
            "unique_groups": len(groups),
            "severity_distribution": severity_dist,
            "avg_confidence": round(
                sum(c.confidence for c in type_classifications) / total, 4
            ),
            "most_common_patterns": self._get_common_patterns(type_classifications, 5),
            "remediation_rate": round(
                sum(1 for c in type_classifications if c.remediation_suggestions) / total * 100, 2
            ),
        }

    def get_trend_data(self, days: int = 30) -> Dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        recent = [c for c in self._classifications.values() if c.classified_at >= cutoff]
        daily: Dict[str, Dict[str, int]] = {}
        for c in recent:
            date_key = c.classified_at.strftime("%Y-%m-%d")
            if date_key not in daily:
                daily[date_key] = {}
            daily[date_key][c.error_type.value] = daily[date_key].get(c.error_type.value, 0) + 1
        weekly: Dict[str, int] = {}
        for date_key, counts in daily.items():
            week_key = datetime.strptime(date_key, "%Y-%m-%d").strftime("%Y-W%W")
            weekly[week_key] = weekly.get(week_key, 0) + sum(counts.values())
        return {
            "period_days": days,
            "total_in_period": len(recent),
            "daily_breakdown": daily,
            "weekly_totals": weekly,
            "avg_daily": round(len(recent) / days, 2) if days else 0.0,
            "trend_direction": self._compute_trend(daily),
        }

    def get_hourly_heatmap(self, days: int = 7) -> Dict[str, Dict[str, int]]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        heatmap: Dict[str, Dict[str, int]] = {}
        for c in self._classifications.values():
            if c.classified_at < cutoff:
                continue
            hour_key = c.classified_at.strftime("%Y-%m-%d-%H")
            if hour_key not in heatmap:
                heatmap[hour_key] = {}
            heatmap[hour_key][c.error_type.value] = heatmap[hour_key].get(c.error_type.value, 0) + 1
        return heatmap

    @staticmethod
    def _compute_trend(daily: Dict[str, Dict[str, int]]) -> str:
        if len(daily) < 2:
            return "insufficient_data"
        sorted_dates = sorted(daily.keys())
        mid = len(sorted_dates) // 2
        first_half = sum(sum(c.values()) for d in sorted_dates[:mid] for c in [daily[d]])
        second_half = sum(sum(c.values()) for d in sorted_dates[mid:] for c in [daily[d]])
        if second_half > first_half * 1.2:
            return "increasing"
        elif second_half < first_half * 0.8:
            return "decreasing"
        return "stable"

    @staticmethod
    def _get_common_patterns(classifications: List[ClassificationResult], top_n: int = 5) -> List[Dict[str, Any]]:
        pattern_counts: Dict[str, int] = {}
        for c in classifications:
            for p in c.patterns_matched:
                pattern_counts[p] = pattern_counts.get(p, 0) + 1
        sorted_patterns = sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)
        return [
            {"pattern": p, "count": count}
            for p, count in sorted_patterns[:top_n]
        ]

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_classification(self, classification_id: str) -> Optional[ClassificationResult]:
        return self._classifications.get(classification_id)

    def find_classifications_by_type(self, error_type: ErrorType, limit: int = 100) -> List[ClassificationResult]:
        results = [c for c in self._classifications.values() if c.error_type == error_type]
        results.sort(key=lambda c: c.classified_at, reverse=True)
        return results[:limit]

    def find_classifications_by_severity(self, severity: RuleSeverity, limit: int = 100) -> List[ClassificationResult]:
        results = [c for c in self._classifications.values() if c.severity == severity]
        results.sort(key=lambda c: c.classified_at, reverse=True)
        return results[:limit]

    def find_classifications_by_source(self, source_id: str, limit: int = 100) -> List[ClassificationResult]:
        results = [c for c in self._classifications.values() if c.source_id == source_id]
        results.sort(key=lambda c: c.classified_at, reverse=True)
        return results[:limit]

    def find_duplicates(self, classification_id: str) -> List[ClassificationResult]:
        result = self._classifications.get(classification_id)
        if not result or not result.group_id:
            return []
        group = self._groups.get(result.group_id)
        if not group:
            return []
        return [
            self._classifications[cid] for cid in group.classification_ids
            if cid in self._classifications and cid != classification_id
        ]

    def search_classifications(
        self,
        query: Optional[str] = None,
        error_type: Optional[ErrorType] = None,
        severity: Optional[RuleSeverity] = None,
        source_id: Optional[str] = None,
        group_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[ClassificationResult]:
        results = list(self._classifications.values())
        if query:
            q = query.lower()
            results = [
                c for c in results
                if q in c.source_id.lower() or any(q in p for p in c.patterns_matched)
            ]
        if error_type:
            results = [c for c in results if c.error_type == error_type]
        if severity:
            results = [c for c in results if c.severity == severity]
        if source_id:
            results = [c for c in results if c.source_id == source_id]
        if group_id:
            results = [c for c in results if c.group_id == group_id]
        if start_time:
            results = [c for c in results if c.classified_at >= start_time]
        if end_time:
            results = [c for c in results if c.classified_at <= end_time]
        results.sort(key=lambda c: c.classified_at, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_classification_id(violation: Violation) -> str:
        raw = f"{violation.rule_id}:{violation.violation_type.value}:{datetime.utcnow().isoformat()}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"cls_{h}"

    def reset_statistics(self) -> None:
        self._type_counts.clear()
        self._severity_counts.clear()
        self._daily_stats.clear()
        self._hourly_stats.clear()

    def clear(self) -> None:
        self._classifications.clear()
        self._groups.clear()
        self._signature_index.clear()
        self._daily_stats.clear()
        self._hourly_stats.clear()
        self._type_counts.clear()
        self._severity_counts.clear()
        self._recent_classifications.clear()

    def __len__(self) -> int:
        return len(self._classifications)

    def __contains__(self, classification_id: str) -> bool:
        return classification_id in self._classifications
