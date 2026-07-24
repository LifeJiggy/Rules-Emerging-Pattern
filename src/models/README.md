# Data Models Module

## Overview

The Data Models module defines all core data structures used throughout the Rules-Emerging-Pattern system. It provides Pydantic-based models for rules, violations, conflicts, monitoring data, and audit trails. These models serve as the contract between the core engine, monitoring systems, and external APIs.

## Files

| File | Purpose |
|------|---------|
| `rule.py` | `Rule`, `RulePattern`, `RuleContext`, `RuleEvaluationRequest`, `RuleSet`, `RuleTier`, `RuleType`, `RuleSeverity`, `RuleStatus`, `EnforcementLevel` |
| `validation.py` | `ValidationResult`, `Violation`, `ViolationType`, `ActionTaken`, `Suggestion` |
| `conflict.py` | `RuleConflict`, `ConflictType`, `ResolutionStrategy`, `ConflictSeverity`, `ConflictResolution` |
| `monitoring.py` | `AlertDefinition`, `AlertSeverity`, `AlertStatus`, `MetricData`, `HealthStatus`, `TrendResult` |
| `audit.py` | `AuditEvent`, `AuditAction`, `AuditCategory`, `AuditSeverity`, `AuditTrail` |

## Class Hierarchy Diagram

```mermaid
classDiagram
    class Rule {
        +str id
        +str name
        +str description
        +RuleTier tier
        +RuleType rule_type
        +RuleSeverity severity
        +RuleStatus status
        +List[RulePattern] patterns
        +Dict conditions
        +EnforcementLevel enforcement_level
        +bool auto_block
        +bool user_override
        +int priority
        +is_applicable_to_context(ctx) bool
        +to_dict() Dict
    }

    class RulePattern {
        +RuleType type
        +List[str] keywords
        +List[str] regex_patterns
        +str ml_model
        +float confidence_threshold
        +str action
    }

    class RuleContext {
        +str user_id
        +str session_id
        +str content_type
        +Dict metadata
        +get_effective_context() Dict
    }

    class RuleEvaluationRequest {
        +str content
        +RuleContext context
        +List[str] rule_ids
        +RuleTier tier
        +List[RuleType] rule_types
        +Dict options
        +get_context() RuleContext
    }

    class Violation {
        +str rule_id
        +str rule_name
        +RuleTier rule_tier
        +RuleSeverity rule_severity
        +ViolationType violation_type
        +str matched_content
        +float confidence_score
        +ActionTaken action_taken
        +bool blocked
        +str explanation
        +is_critical() bool
        +requires_escalation() bool
        +get_violation_hash() str
        +to_summary() Dict
    }

    class ValidationResult {
        +bool valid
        +float total_score
        +float confidence
        +List[Violation] violations
        +List[Violation] critical_violations
        +List[Violation] warnings
        +List[Suggestion] suggestions
        +int processing_time_ms
        +str request_id
        +str content_hash
        +has_violations() bool
        +is_blocked() bool
        +get_summary() Dict
        +to_dict() Dict
    }

    class Suggestion {
        +str rule_id
        +str message
        +str category
        +float relevance_score
        +Dict metadata
    }

    class RuleConflict {
        +str conflict_id
        +ConflictType conflict_type
        +ConflictSeverity severity
        +Rule rule_1
        +Rule rule_2
        +str description
        +bool resolved
        +is_critical() bool
        +requires_immediate_resolution() bool
        +get_involved_tiers() List[str]
        +get_involved_rule_ids() List[str]
    }

    class ConflictResolution {
        +str resolution_id
        +ResolutionStrategy strategy
        +RuleConflict conflict
        +str resolution_detail
        +Rule resolved_rule
        +datetime resolved_at
    }

    class AlertDefinition {
        +str alert_id
        +str name
        +str metric_name
        +str comparison_operator
        +float threshold_value
        +AlertSeverity severity
        +int duration_seconds
        +int cooldown_minutes
        +evaluate_condition(value) bool
        +get_escalation_level(count) Dict
        +should_escalate(count) bool
    }

    class AuditEvent {
        +str event_id
        +str event_type
        +AuditCategory category
        +AuditAction action
        +AuditSeverity severity
        +str actor
        +str summary
        +str description
        +Dict details
        +datetime timestamp
    }

    Rule *-- RulePattern : contains
    Rule --> RuleTier
    Rule --> RuleType
    Rule --> RuleSeverity
    Rule --> RuleStatus
    Rule --> EnforcementLevel
    RuleEvaluationRequest --> RuleContext
    ValidationResult *-- Violation : contains
    ValidationResult *-- Suggestion : contains
    Violation --> RuleTier
    Violation --> RuleSeverity
    Violation --> ViolationType
    Violation --> ActionTaken
    RuleConflict --> Rule
    RuleConflict --> ConflictType
    RuleConflict --> ConflictSeverity
    ConflictResolution --> ResolutionStrategy
    ConflictResolution --> RuleConflict
```

## Usage Examples

```python
from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleSeverity, RuleType, EnforcementLevel

rule = Rule(
    id="rule_001",
    name="Block Profanity",
    description="Blocks content containing profane language",
    tier=RuleTier.SAFETY,
    rule_type=RuleType.CONTENT_FILTERING,
    severity=RuleSeverity.HIGH,
    enforcement_level=EnforcementLevel.STRICT,
    auto_block=True,
    patterns=[RulePattern(
        type=RuleType.CONTENT_FILTERING,
        keywords=["badword1", "badword2"],
        regex_patterns=[r"explicit\s+pattern"],
    )],
)

from rules_emerging_pattern.models.validation import Violation, ValidationResult, ViolationType, ActionTaken

violation = Violation(
    rule_id="rule_001",
    rule_name="Block Profanity",
    rule_tier=RuleTier.SAFETY,
    rule_severity=RuleSeverity.HIGH,
    violation_type=ViolationType.KEYWORD_MATCH,
    matched_content="badword1",
    confidence_score=0.95,
    action_taken=ActionTaken.BLOCK,
    blocked=True,
    explanation="Content contains prohibited keyword",
)

result = ValidationResult(
    valid=False,
    total_score=0.0,
    confidence=0.95,
    violations=[violation],
)
```

## Model Validation

All models use Pydantic `BaseModel` with built-in validation:

- `RulePattern` - Enforces `confidence_threshold` between 0.0 and 1.0
- `Rule` - Validates `priority` between 1 and 1000, `timeout_ms` between 1 and 10000
- `Violation` - Enforces `confidence_score` range
- `AlertDefinition` - Validates `duration_seconds` and `cooldown_minutes` ranges
- `AuditEvent` - Validates timestamp ordering
