"""Data models for the Rules-Emerging-Pattern SDK.

Mirrors the project's internal models for rule tiers, patterns, evaluations,
violations, conflicts, monitoring, and auditing.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class RuleTier(str, Enum):
    SAFETY = "safety"
    OPERATIONAL = "operational"
    PREFERENCE = "preference"
    COMPLIANCE = "compliance"
    CUSTOM = "custom"

    @classmethod
    def from_str(cls, value: str) -> "RuleTier":
        normalized = value.lower().strip()
        for tier in cls:
            if tier.value == normalized:
                return tier
        raise ValueError(f"Unknown RuleTier: {value}")

    @classmethod
    def values(cls) -> List[str]:
        return [t.value for t in cls]

    @classmethod
    def priority(cls, tier: "RuleTier") -> int:
        priorities = {
            cls.SAFETY: 1,
            cls.OPERATIONAL: 2,
            cls.COMPLIANCE: 3,
            cls.PREFERENCE: 4,
            cls.CUSTOM: 5,
        }
        return priorities.get(tier, 99)

    def is_critical(self) -> bool:
        return self in (self.SAFETY, self.COMPLIANCE)


class RuleType(str, Enum):
    PATTERN = "pattern"
    KEYWORD = "keyword"
    REGEX = "regex"
    SEMANTIC = "semantic"
    COMPOSITE = "composite"
    CONDITIONAL = "conditional"
    TEMPLATE = "template"
    CUSTOM = "custom"

    @classmethod
    def from_str(cls, value: str) -> "RuleType":
        normalized = value.lower().strip()
        for rt in cls:
            if rt.value == normalized:
                return rt
        raise ValueError(f"Unknown RuleType: {value}")


class RuleSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @classmethod
    def from_str(cls, value: str) -> "RuleSeverity":
        normalized = value.lower().strip()
        for rs in cls:
            if rs.value == normalized:
                return rs
        raise ValueError(f"Unknown RuleSeverity: {value}")

    @classmethod
    def numeric_value(cls, severity: "RuleSeverity") -> int:
        values = {
            cls.CRITICAL: 5,
            cls.HIGH: 4,
            cls.MEDIUM: 3,
            cls.LOW: 2,
            cls.INFO: 1,
        }
        return values.get(severity, 0)

    def __ge__(self, other: "RuleSeverity") -> bool:
        return self.numeric_value(self) >= self.numeric_value(other)

    def __le__(self, other: "RuleSeverity") -> bool:
        return self.numeric_value(self) <= self.numeric_value(other)


class RuleStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    DRAFT = "draft"
    DISABLED = "disabled"
    ARCHIVED = "archived"

    @classmethod
    def from_str(cls, value: str) -> "RuleStatus":
        normalized = value.lower().strip()
        for rs in cls:
            if rs.value == normalized:
                return rs
        raise ValueError(f"Unknown RuleStatus: {value}")

    def is_active(self) -> bool:
        return self == RuleStatus.ACTIVE


class EnforcementLevel(str, Enum):
    STRICT = "strict"
    ADVISORY = "advisory"
    ADAPTIVE = "adaptive"
    MONITOR = "monitor"
    DISABLED = "disabled"

    @classmethod
    def from_str(cls, value: str) -> "EnforcementLevel":
        normalized = value.lower().strip()
        for el in cls:
            if el.value == normalized:
                return el
        raise ValueError(f"Unknown EnforcementLevel: {value}")

    def blocks_content(self) -> bool:
        return self == EnforcementLevel.STRICT


class ViolationType(str, Enum):
    CONTENT_SAFETY = "content_safety"
    FORMAT_ERROR = "format_error"
    COMPLIANCE = "compliance"
    QUALITY = "quality"
    HALLUCINATION = "hallucination"
    CITATION = "citations"
    STYLE = "style"
    PATTERN_MATCH = "pattern_match"
    CUSTOM = "custom"
    BUSINESS_RULE = "business_rule"
    SECURITY = "security"

    @classmethod
    def from_str(cls, value: str) -> "ViolationType":
        normalized = value.lower().strip()
        for vt in cls:
            if vt.value == normalized:
                return vt
        return ViolationType.CUSTOM


class ActionTaken(str, Enum):
    BLOCKED = "blocked"
    WARNED = "warned"
    FLAGGED = "flagged"
    ALLOWED = "allowed"
    ESCALATED = "escalated"
    MODIFIED = "modified"
    LOGGED = "logged"

    @classmethod
    def from_str(cls, value: str) -> "ActionTaken":
        normalized = value.lower().strip()
        for at in cls:
            if at.value == normalized:
                return at
        return ActionTaken.LOGGED

    def is_blocking(self) -> bool:
        return self == ActionTaken.BLOCKED


class ConflictType(str, Enum):
    OVERLAPPING_PATTERNS = "overlapping_patterns"
    CONTRADICTORY_ACTIONS = "contradictory_actions"
    DUPLICATE_RULES = "duplicate_rules"
    HIERARCHY_CONFLICT = "hierarchy_conflict"
    CONDITION_OVERLAP = "condition_overlap"
    PRIORITY_CONFLICT = "priority_conflict"

    @classmethod
    def from_str(cls, value: str) -> "ConflictType":
        normalized = value.lower().strip()
        for ct in cls:
            if ct.value == normalized:
                return ct
        raise ValueError(f"Unknown ConflictType: {value}")


class ResolutionStrategy(str, Enum):
    HIGHEST_PRIORITY = "highest_priority"
    MOST_RESTRICTIVE = "most_restrictive"
    LEAST_RESTRICTIVE = "least_restrictive"
    SPECIFIC_FIRST = "specific_first"
    MANUAL = "manual"
    TIME_BASED = "time_based"
    CUSTOM = "custom"

    @classmethod
    def from_str(cls, value: str) -> "ResolutionStrategy":
        normalized = value.lower().strip()
        for rs in cls:
            if rs.value == normalized:
                return rs
        return ResolutionStrategy.HIGHEST_PRIORITY


@dataclass
class RulePattern:
    pattern_id: str = ""
    pattern_type: RuleType = RuleType.PATTERN
    value: str = ""
    description: str = ""
    case_sensitive: bool = False
    whole_word: bool = False
    flags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def compile(self) -> Any:
        import re
        flags = 0
        if not self.case_sensitive:
            flags |= re.IGNORECASE
        if self.whole_word:
            wrapped = rf"\b{self.value}\b"
        else:
            wrapped = self.value
        try:
            return re.compile(wrapped, flags)
        except re.error as e:
            logger.warning("Failed to compile pattern '%s': %s", self.pattern_id, e)
            return None

    def match(self, text: str) -> bool:
        compiled = self.compile()
        if compiled:
            return bool(compiled.search(text))
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type.value,
            "value": self.value,
            "description": self.description,
            "case_sensitive": self.case_sensitive,
            "whole_word": self.whole_word,
            "flags": self.flags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RulePattern":
        return cls(
            pattern_id=data.get("pattern_id", ""),
            pattern_type=RuleType.from_str(data.get("pattern_type", "pattern")),
            value=data.get("value", ""),
            description=data.get("description", ""),
            case_sensitive=data.get("case_sensitive", False),
            whole_word=data.get("whole_word", False),
            flags=data.get("flags", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Rule:
    rule_id: str = ""
    name: str = ""
    description: str = ""
    tier: RuleTier = RuleTier.CUSTOM
    rule_type: RuleType = RuleType.PATTERN
    severity: RuleSeverity = RuleSeverity.MEDIUM
    status: RuleStatus = RuleStatus.ACTIVE
    enforcement: EnforcementLevel = EnforcementLevel.ADVISORY
    patterns: List[RulePattern] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)
    actions: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    priority: int = 0

    def is_active(self) -> bool:
        return self.status == RuleStatus.ACTIVE

    def is_applicable(self, context: Optional[Dict[str, Any]] = None) -> bool:
        if not self.is_active():
            return False
        if not context:
            return True
        conditions = self.conditions
        if not conditions:
            return True
        for key, expected in conditions.items():
            actual = context.get(key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "tier": self.tier.value,
            "rule_type": self.rule_type.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "enforcement": self.enforcement.value,
            "patterns": [p.to_dict() for p in self.patterns],
            "conditions": self.conditions,
            "actions": self.actions,
            "tags": self.tags,
            "metadata": self.metadata,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Rule":
        patterns_data = data.get("patterns", [])
        patterns = []
        for p in patterns_data:
            if isinstance(p, dict):
                patterns.append(RulePattern.from_dict(p))
        return cls(
            rule_id=data.get("rule_id", data.get("id", "")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            tier=RuleTier.from_str(data.get("tier", "custom")),
            rule_type=RuleType.from_str(data.get("rule_type", "pattern")),
            severity=RuleSeverity.from_str(data.get("severity", "medium")),
            status=RuleStatus.from_str(data.get("status", "active")),
            enforcement=EnforcementLevel.from_str(data.get("enforcement", "advisory")),
            patterns=patterns,
            conditions=data.get("conditions", {}),
            actions=data.get("actions", {}),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            version=data.get("version", "1.0.0"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            created_by=data.get("created_by"),
            priority=data.get("priority", 0),
        )

    def merge(self, updates: Dict[str, Any]) -> "Rule":
        merged_data = self.to_dict()
        for key, value in updates.items():
            if key == "patterns" and isinstance(value, list):
                merged_data["patterns"] = [
                    p.to_dict() if isinstance(p, RulePattern) else p for p in value
                ]
            else:
                merged_data[key] = value
        return Rule.from_dict(merged_data)


@dataclass
class RuleSet:
    rule_set_id: str = ""
    name: str = ""
    description: str = ""
    rules: List[Rule] = field(default_factory=list)
    tier: RuleTier = RuleTier.CUSTOM
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        for i, r in enumerate(self.rules):
            if r.rule_id == rule_id:
                self.rules.pop(i)
                return True
        return False

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        for r in self.rules:
            if r.rule_id == rule_id:
                return r
        return None

    def active_rules(self) -> List[Rule]:
        return [r for r in self.rules if r.is_active()]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_set_id": self.rule_set_id,
            "name": self.name,
            "description": self.description,
            "rules": [r.to_dict() for r in self.rules],
            "tier": self.tier.value,
            "tags": self.tags,
            "metadata": self.metadata,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleSet":
        rules_data = data.get("rules", [])
        rules = [Rule.from_dict(r) if isinstance(r, dict) else r for r in rules_data]
        return cls(
            rule_set_id=data.get("rule_set_id", data.get("id", "")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            rules=rules,
            tier=RuleTier.from_str(data.get("tier", "custom")),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            version=data.get("version", "1.0.0"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def __len__(self) -> int:
        return len(self.rules)

    def __iter__(self):
        return iter(self.rules)


@dataclass
class RuleContext:
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    channel: Optional[str] = None
    locale: Optional[str] = None
    user_role: Optional[str] = None
    content_type: Optional[str] = None
    environment: str = "production"
    additional: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "channel": self.channel,
            "locale": self.locale,
            "user_role": self.user_role,
            "content_type": self.content_type,
            "environment": self.environment,
            "additional": self.additional,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleContext":
        return cls(
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            request_id=data.get("request_id"),
            channel=data.get("channel"),
            locale=data.get("locale"),
            user_role=data.get("user_role"),
            content_type=data.get("content_type"),
            environment=data.get("environment", "production"),
            additional=data.get("additional", {}),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class RuleEvaluationRequest:
    content: str
    context: Optional[RuleContext] = None
    tier: Optional[RuleTier] = None
    rule_ids: Optional[List[str]] = None
    options: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "context": self.context.to_dict() if self.context else None,
            "tier": self.tier.value if self.tier else None,
            "rule_ids": self.rule_ids,
            "options": self.options,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleEvaluationRequest":
        ctx_data = data.get("context")
        ctx = RuleContext.from_dict(ctx_data) if ctx_data and isinstance(ctx_data, dict) else None
        tier_str = data.get("tier")
        return cls(
            content=data.get("content", ""),
            context=ctx,
            tier=RuleTier.from_str(tier_str) if tier_str else None,
            rule_ids=data.get("rule_ids"),
            options=data.get("options", {}),
        )


@dataclass
class Violation:
    rule_id: str = ""
    rule_name: str = ""
    violation_type: ViolationType = ViolationType.CUSTOM
    severity: RuleSeverity = RuleSeverity.MEDIUM
    message: str = ""
    field: str = "content"
    position_start: Optional[int] = None
    position_end: Optional[int] = None
    line: Optional[int] = None
    column: Optional[int] = None
    code: Optional[str] = None
    suggestion: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "violation_type": self.violation_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "field": self.field,
            "position_start": self.position_start,
            "position_end": self.position_end,
            "line": self.line,
            "column": self.column,
            "code": self.code,
            "suggestion": self.suggestion,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Violation":
        return cls(
            rule_id=data.get("rule_id", ""),
            rule_name=data.get("rule_name", ""),
            violation_type=ViolationType.from_str(data.get("violation_type", "custom")),
            severity=RuleSeverity.from_str(data.get("severity", "medium")),
            message=data.get("message", ""),
            field=data.get("field", "content"),
            position_start=data.get("position_start"),
            position_end=data.get("position_end"),
            line=data.get("line"),
            column=data.get("column"),
            code=data.get("code"),
            suggestion=data.get("suggestion"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Suggestion:
    message: str = ""
    fix: Optional[str] = None
    replacement: Optional[str] = None
    severity: RuleSeverity = RuleSeverity.INFO
    rule_id: Optional[str] = None
    category: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "fix": self.fix,
            "replacement": self.replacement,
            "severity": self.severity.value,
            "rule_id": self.rule_id,
            "category": self.category,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Suggestion":
        return cls(
            message=data.get("message", ""),
            fix=data.get("fix"),
            replacement=data.get("replacement"),
            severity=RuleSeverity.from_str(data.get("severity", "info")),
            rule_id=data.get("rule_id"),
            category=data.get("category"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ValidationResult:
    passed: bool = True
    blocked: bool = False
    violations: List[Violation] = field(default_factory=list)
    suggestions: List[Suggestion] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    score: float = 1.0
    processing_time_ms: float = 0.0
    applied_rules: int = 0
    tier: Optional[str] = None
    request_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def has_violations(self) -> bool:
        return len(self.violations) > 0

    def has_blockers(self) -> bool:
        return self.blocked or any(v.severity == RuleSeverity.CRITICAL for v in self.violations)

    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity in (RuleSeverity.CRITICAL, RuleSeverity.HIGH))

    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == RuleSeverity.WARNING)

    def info_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == RuleSeverity.INFO)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "blocked": self.blocked,
            "violations": [v.to_dict() for v in self.violations],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "warnings": self.warnings,
            "score": round(self.score, 4),
            "processing_time_ms": round(self.processing_time_ms, 3),
            "applied_rules": self.applied_rules,
            "tier": self.tier,
            "request_id": self.request_id,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationResult":
        violations = [Violation.from_dict(v) for v in data.get("violations", [])]
        suggestions = [Suggestion.from_dict(s) for s in data.get("suggestions", [])]
        return cls(
            passed=data.get("passed", True),
            blocked=data.get("blocked", False),
            violations=violations,
            suggestions=suggestions,
            warnings=data.get("warnings", []),
            score=data.get("score", 1.0),
            processing_time_ms=data.get("processing_time_ms", 0.0),
            applied_rules=data.get("applied_rules", 0),
            tier=data.get("tier"),
            request_id=data.get("request_id"),
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class RuleConflict:
    conflict_id: str = ""
    conflict_type: ConflictType = ConflictType.OVERLAPPING_PATTERNS
    rule_ids: List[str] = field(default_factory=list)
    description: str = ""
    severity: RuleSeverity = RuleSeverity.MEDIUM
    resolution: Optional[ResolutionStrategy] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "conflict_type": self.conflict_type.value,
            "rule_ids": self.rule_ids,
            "description": self.description,
            "severity": self.severity.value,
            "resolution": self.resolution.value if self.resolution else None,
            "metadata": self.metadata,
            "detected_at": self.detected_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleConflict":
        res_str = data.get("resolution")
        return cls(
            conflict_id=data.get("conflict_id", ""),
            conflict_type=ConflictType.from_str(data.get("conflict_type", "overlapping_patterns")),
            rule_ids=data.get("rule_ids", []),
            description=data.get("description", ""),
            severity=RuleSeverity.from_str(data.get("severity", "medium")),
            resolution=ResolutionStrategy.from_str(res_str) if res_str else None,
            metadata=data.get("metadata", {}),
            detected_at=data.get("detected_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class ConflictResolution:
    resolution_id: str = ""
    conflicts: List[RuleConflict] = field(default_factory=list)
    strategy: ResolutionStrategy = ResolutionStrategy.HIGHEST_PRIORITY
    resolved: bool = False
    resolution_details: Dict[str, Any] = field(default_factory=dict)
    resolved_at: Optional[str] = None
    applied_rules: List[str] = field(default_factory=list)
    suppressed_rules: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolution_id": self.resolution_id,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "strategy": self.strategy.value,
            "resolved": self.resolved,
            "resolution_details": self.resolution_details,
            "resolved_at": self.resolved_at,
            "applied_rules": self.applied_rules,
            "suppressed_rules": self.suppressed_rules,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConflictResolution":
        conflicts = [RuleConflict.from_dict(c) for c in data.get("conflicts", [])]
        return cls(
            resolution_id=data.get("resolution_id", ""),
            conflicts=conflicts,
            strategy=ResolutionStrategy.from_str(data.get("strategy", "highest_priority")),
            resolved=data.get("resolved", False),
            resolution_details=data.get("resolution_details", {}),
            resolved_at=data.get("resolved_at"),
            applied_rules=data.get("applied_rules", []),
            suppressed_rules=data.get("suppressed_rules", []),
        )


@dataclass
class BatchValidationRequest:
    contents: List[str] = field(default_factory=list)
    context: Optional[RuleContext] = None
    tier: Optional[RuleTier] = None
    rule_ids: Optional[List[str]] = None
    options: Dict[str, Any] = field(default_factory=dict)
    parallel: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contents": self.contents,
            "context": self.context.to_dict() if self.context else None,
            "tier": self.tier.value if self.tier else None,
            "rule_ids": self.rule_ids,
            "options": self.options,
            "parallel": self.parallel,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BatchValidationRequest":
        ctx_data = data.get("context")
        ctx = RuleContext.from_dict(ctx_data) if ctx_data and isinstance(ctx_data, dict) else None
        tier_str = data.get("tier")
        return cls(
            contents=data.get("contents", []),
            context=ctx,
            tier=RuleTier.from_str(tier_str) if tier_str else None,
            rule_ids=data.get("rule_ids"),
            options=data.get("options", {}),
            parallel=data.get("parallel", False),
        )


@dataclass
class BatchValidationResult:
    results: List[ValidationResult] = field(default_factory=list)
    total_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    total_time_ms: float = 0.0
    errors: List[str] = field(default_factory=list)

    def add_result(self, result: ValidationResult) -> None:
        self.results.append(result)
        self.total_count += 1
        if result.passed:
            self.passed_count += 1
        else:
            self.failed_count += 1
        if result.blocked:
            self.blocked_count += 1

    def pass_rate(self) -> float:
        return self.passed_count / max(self.total_count, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "total_count": self.total_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "blocked_count": self.blocked_count,
            "total_time_ms": round(self.total_time_ms, 3),
            "pass_rate": round(self.pass_rate(), 4),
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BatchValidationResult":
        results = [ValidationResult.from_dict(r) for r in data.get("results", [])]
        return cls(
            results=results,
            total_count=data.get("total_count", len(results)),
            passed_count=data.get("passed_count", sum(1 for r in results if r.passed)),
            failed_count=data.get("failed_count", sum(1 for r in results if not r.passed)),
            blocked_count=data.get("blocked_count", sum(1 for r in results if r.blocked)),
            total_time_ms=data.get("total_time_ms", 0.0),
            errors=data.get("errors", []),
        )


@dataclass
class AlertDefinition:
    alert_id: str = ""
    name: str = ""
    description: str = ""
    metric: str = ""
    condition: str = "gt"
    threshold: float = 0.0
    severity: RuleSeverity = RuleSeverity.MEDIUM
    enabled: bool = True
    cooldown_seconds: int = 300
    channels: List[str] = field(default_factory=lambda: ["console"])
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "name": self.name,
            "description": self.description,
            "metric": self.metric,
            "condition": self.condition,
            "threshold": self.threshold,
            "severity": self.severity.value,
            "enabled": self.enabled,
            "cooldown_seconds": self.cooldown_seconds,
            "channels": self.channels,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlertDefinition":
        return cls(
            alert_id=data.get("alert_id", data.get("id", "")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            metric=data.get("metric", ""),
            condition=data.get("condition", "gt"),
            threshold=float(data.get("threshold", 0.0)),
            severity=RuleSeverity.from_str(data.get("severity", "medium")),
            enabled=data.get("enabled", True),
            cooldown_seconds=data.get("cooldown_seconds", 300),
            channels=data.get("channels", ["console"]),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at"),
        )


@dataclass
class AlertEvent:
    event_id: str = ""
    alert_name: str = ""
    alert_id: str = ""
    severity: RuleSeverity = RuleSeverity.MEDIUM
    message: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0
    status: str = "triggered"
    source: str = "system"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "alert_name": self.alert_name,
            "alert_id": self.alert_id,
            "severity": self.severity.value,
            "message": self.message,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "status": self.status,
            "source": self.source,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlertEvent":
        return cls(
            event_id=data.get("event_id", ""),
            alert_name=data.get("alert_name", ""),
            alert_id=data.get("alert_id", ""),
            severity=RuleSeverity.from_str(data.get("severity", "medium")),
            message=data.get("message", ""),
            metric_value=float(data.get("metric_value", 0.0)),
            threshold=float(data.get("threshold", 0.0)),
            status=data.get("status", "triggered"),
            source=data.get("source", "system"),
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            resolved_at=data.get("resolved_at"),
        )

    def is_active(self) -> bool:
        return self.status in ("triggered", "acknowledged")

    def is_resolved(self) -> bool:
        return self.status == "resolved"


@dataclass
class MetricsSnapshot:
    snapshot_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metrics: Dict[str, float] = field(default_factory=dict)
    labels: Dict[str, str] = field(default_factory=dict)
    source: str = "sdk"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "metrics": self.metrics,
            "labels": self.labels,
            "source": self.source,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetricsSnapshot":
        return cls(
            snapshot_id=data.get("snapshot_id", ""),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            metrics={k: float(v) for k, v in data.get("metrics", {}).items()},
            labels=data.get("labels", {}),
            source=data.get("source", "sdk"),
            metadata=data.get("metadata", {}),
        )

    def get_metric(self, name: str, default: float = 0.0) -> float:
        return self.metrics.get(name, default)

    def __getitem__(self, key: str) -> float:
        return self.metrics[key]

    def __contains__(self, key: str) -> bool:
        return key in self.metrics


@dataclass
class AuditEvent:
    event_id: str = ""
    event_type: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = ""
    user_id: Optional[str] = None
    rule_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    severity: str = "info"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "source": self.source,
            "user_id": self.user_id,
            "rule_id": self.rule_id,
            "details": self.details,
            "severity": self.severity,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEvent":
        return cls(
            event_id=data.get("event_id", ""),
            event_type=data.get("event_type", ""),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            source=data.get("source", ""),
            user_id=data.get("user_id"),
            rule_id=data.get("rule_id"),
            details=data.get("details", {}),
            severity=data.get("severity", "info"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AuditTrail:
    entries: List[AuditEvent] = field(default_factory=list)
    total_count: int = 0
    queried_count: int = 0
    query_params: Dict[str, Any] = field(default_factory=dict)

    def add_entry(self, entry: AuditEvent) -> None:
        self.entries.append(entry)
        self.total_count += 1
        self.queried_count += 1

    def filter(self, event_type: Optional[str] = None, user_id: Optional[str] = None,
               rule_id: Optional[str] = None, severity: Optional[str] = None) -> List[AuditEvent]:
        results = list(self.entries)
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if rule_id:
            results = [e for e in results if e.rule_id == rule_id]
        if severity:
            results = [e for e in results if e.severity == severity]
        return results

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "total_count": self.total_count,
            "queried_count": self.queried_count,
            "query_params": self.query_params,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditTrail":
        entries = [AuditEvent.from_dict(e) for e in data.get("entries", [])]
        return cls(
            entries=entries,
            total_count=data.get("total_count", len(entries)),
            queried_count=data.get("queried_count", len(entries)),
            query_params=data.get("query_params", {}),
        )

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)


def json_serialize(obj: Any) -> str:
    if hasattr(obj, "to_dict"):
        return json.dumps(obj.to_dict(), default=str, indent=2)
    if isinstance(obj, dict):
        return json.dumps(obj, default=str, indent=2)
    return json.dumps({"value": str(obj)}, default=str)


def json_deserialize(data: str, target_class: Any) -> Any:
    parsed = json.loads(data)
    if hasattr(target_class, "from_dict"):
        return target_class.from_dict(parsed)
    return parsed
