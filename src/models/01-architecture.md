# Model Architecture

## Rule Model Hierarchy

The Rule model is the central entity in the system, with supporting types for patterns, tiers, severity, status, and enforcement.

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
        +List[str] exceptions
        +EnforcementLevel enforcement_level
        +bool auto_block
        +bool user_override
        +bool override_justification_required
        +str version
        +datetime created_at
        +datetime updated_at
        +str created_by
        +List[str] tags
        +int priority
        +int timeout_ms
        +is_applicable_to_context(ctx) bool
        +to_dict() Dict
        +to_json() str
        +to_yaml() str
        +matches_content(content) bool
        +get_effective_severity(context) RuleSeverity
    }

    class RulePattern {
        +RuleType type
        +List[str] keywords
        +List[str] regex_patterns
        +str ml_model
        +float confidence_threshold
        +str action
        +compile_regex() Pattern
        +match(content) bool
        +to_dict() Dict
    }

    class RuleTier {
        <<enumeration>>
        SAFETY
        OPERATIONAL
        PREFERENCE
    }

    class RuleType {
        <<enumeration>>
        CONTENT_FILTERING
        PATTERN_MATCHING
        SEMANTIC_ANALYSIS
        STRUCTURAL_VALIDATION
        COMPLIANCE_CHECK
        QUALITY_ASSESSMENT
        CUSTOM
    }

    class RuleSeverity {
        <<enumeration>>
        LOW
        MEDIUM
        HIGH
        CRITICAL
    }

    class RuleStatus {
        <<enumeration>>
        ACTIVE
        INACTIVE
        DEPRECATED
        TESTING
    }

    class EnforcementLevel {
        <<enumeration>>
        STRICT
        ADVISORY
        ADAPTIVE
        FALLBACK
    }

    class RuleContext {
        +str user_id
        +str session_id
        +str content_type
        +str channel
        +str locale
        +List[str] user_roles
        +Dict metadata
        +get_effective_context() Dict
        +merge(other) RuleContext
        +to_dict() Dict
    }

    class RuleEvaluationRequest {
        +str content
        +RuleContext context
        +List[str] rule_ids
        +RuleTier tier
        +List[RuleType] rule_types
        +Dict options
        +Dict metadata
        +get_context() RuleContext
        +to_dict() Dict
    }

    class RuleSet {
        +str set_id
        +str name
        +str description
        +List[Rule] rules
        +List[str] tags
        +bool is_active
        +datetime created_at
        +datetime updated_at
        +add_rule(rule) void
        +remove_rule(rule_id) bool
        +get_rules_by_tier(tier) List[Rule]
        +get_rules_by_type(type) List[Rule]
        +get_rules_by_severity(severity) List[Rule]
        +get_active_rules() List[Rule]
        +to_dict() Dict
    }

    Rule *-- RulePattern : contains
    Rule --> RuleTier
    Rule --> RuleType
    Rule --> RuleSeverity
    Rule --> RuleStatus
    Rule --> EnforcementLevel
    RuleEvaluationRequest --> RuleContext
    RuleSet *-- Rule : contains
```

## Conflict Model Hierarchy

```mermaid
classDiagram
    class RuleConflict {
        +str conflict_id
        +ConflictType conflict_type
        +ConflictSeverity severity
        +Rule rule_1
        +Rule rule_2
        +List[Rule] additional_rules
        +str description
        +str conflict_reason
        +List[str] contradictory_elements
        +List[str] context_triggers
        +datetime detected_at
        +str detection_method
        +float confidence
        +ResolutionStrategy resolution_strategy
        +bool resolved
        +str resolution_applied
        +str resolution_outcome
        +is_critical() bool
        +requires_immediate_resolution() bool
        +get_involved_tiers() List[str]
        +get_involved_rule_ids() List[str]
        +get_involved_severities() List[str]
        +has_rule(rule_id) bool
        +to_dict() Dict
        +to_summary() Dict
    }

    class ConflictType {
        <<enumeration>>
        RULE_CONFLICT
        PRIORITY_CONFLICT
        SEMANTIC_CONFLICT
        CONTEXT_CONFLICT
        LOGICAL_CONTRADICTION
        MUTUAL_EXCLUSIVITY
    }

    class ResolutionStrategy {
        <<enumeration>>
        PRIORITY_BASED
        CONTEXT_AWARE
        USER_PREFERENCE
        FALLBACK
        HYBRID
        HUMAN_REVIEW
    }

    class ConflictSeverity {
        <<enumeration>>
        LOW
        MEDIUM
        HIGH
        CRITICAL
    }

    class ConflictResolution {
        +str resolution_id
        +ResolutionStrategy strategy
        +str conflict_id
        +RuleConflict conflict
        +str resolution_detail
        +Rule resolved_rule
        +List[Rule] suppressed_rules
        +datetime resolved_at
        +str resolved_by
        +str notes
        +bool automatic
        +to_dict() Dict
        +to_summary() Dict
    }

    class ConflictDetector {
        +detect_conflicts(rules) List[RuleConflict]
        +detect_semantic_conflicts(rules) List[RuleConflict]
        +detect_priority_conflicts(rules) List[RuleConflict]
        +detect_logical_contradictions(rules) List[RuleConflict]
        +detect_mutual_exclusivity(rules) List[RuleConflict]
        +detect_context_conflicts(rules, context) List[RuleConflict]
    }

    class ConflictResolver {
        +resolve(conflict, strategy) ConflictResolution
        +resolve_priority_based(conflict) ConflictResolution
        +resolve_context_aware(conflict, context) ConflictResolution
        +resolve_user_preference(conflict, preference) ConflictResolution
        +resolve_hybrid(conflict) ConflictResolution
        +resolve_fallback(conflict) ConflictResolution
    }

    RuleConflict --> ConflictType
    RuleConflict --> ConflictSeverity
    RuleConflict --> ResolutionStrategy
    RuleConflict --> Rule
    ConflictResolution --> ResolutionStrategy
    ConflictResolution --> RuleConflict
    ConflictDetector --> RuleConflict : generates
    ConflictResolver --> ConflictResolution : produces
```

## Validation Model Hierarchy

```mermaid
classDiagram
    class ValidationResult {
        +bool valid
        +float total_score
        +float confidence
        +int total_rules_evaluated
        +int rules_triggered
        +int rules_violated
        +List[Violation] violations
        +List[Violation] critical_violations
        +List[Violation] warnings
        +List[Suggestion] suggestions
        +Dict rules_by_tier
        +int processing_time_ms
        +str request_id
        +str content_hash
        +datetime evaluated_at
        +has_violations() bool
        +has_critical_violations() bool
        +is_blocked() bool
        +get_violations_by_tier() Dict
        +get_violations_by_severity() Dict
        +get_summary() Dict
        +to_dict() Dict
        +to_prometheus() Dict
    }

    class Violation {
        +str rule_id
        +str rule_name
        +RuleTier rule_tier
        +RuleSeverity rule_severity
        +ViolationType violation_type
        +str matched_content
        +List[str] matched_patterns
        +float confidence_score
        +Dict position_info
        +ActionTaken action_taken
        +bool blocked
        +bool user_override_allowed
        +str override_justification
        +str explanation
        +List[str] suggestions
        +str educational_content
        +datetime detected_at
        +str detection_method
        +Dict context
        +is_critical() bool
        +requires_escalation() bool
        +get_violation_hash() str
        +to_summary() Dict
        +was_blocked() bool
        +was_overridden() bool
    }

    class ViolationType {
        <<enumeration>>
        KEYWORD_MATCH
        REGEX_MATCH
        SEMANTIC_VIOLATION
        STRUCTURAL_VIOLATION
        COMPLIANCE_VIOLATION
        QUALITY_VIOLATION
        CUSTOM_VIOLATION
    }

    class ActionTaken {
        <<enumeration>>
        NONE
        WARNING
        SUGGESTION
        BLOCK
        REDACT
        QUARANTINE
        ESCALATE
    }

    class Suggestion {
        +str rule_id
        +str rule_name
        +str message
        +str category
        +float relevance_score
        +int priority
        +Dict metadata
        +to_dict() Dict
        +to_summary() Dict
    }

    ValidationResult *-- Violation : contains
    ValidationResult *-- Suggestion : contains
    Violation --> RuleTier
    Violation --> RuleSeverity
    Violation --> ViolationType
    Violation --> ActionTaken
```

## Monitoring Model Hierarchy

```mermaid
classDiagram
    class AlertDefinition {
        +str alert_id
        +str name
        +str description
        +str alert_type
        +AlertSeverity severity
        +str metric_name
        +str metric_source
        +str comparison_operator
        +float threshold_value
        +int duration_seconds
        +int evaluation_window_minutes
        +int cooldown_minutes
        +int max_alerts_per_hour
        +List[str] notification_channels
        +List[Dict] escalation_levels
        +int auto_resolve_minutes
        +bool is_active
        +datetime created_at
        +datetime updated_at
        +evaluate_condition(value) bool
        +get_escalation_level(count) Dict
        +should_escalate(count) bool
        +activate() void
        +deactivate() void
        +to_dict() Dict
    }

    class AlertSeverity {
        <<enumeration>>
        INFO
        WARNING
        ERROR
        CRITICAL
    }

    class AlertStatus {
        <<enumeration>>
        TRIGGERED
        ACKNOWLEDGED
        RESOLVED
        DISMISSED
        ESCALATED
    }

    class MetricData {
        +str metric_id
        +str name
        +float value
        +str unit
        +str metric_type
        +Dict labels
        +datetime timestamp
        +str source
        +to_dict() Dict
    }

    class HealthStatus {
        <<enumeration>>
        HEALTHY
        DEGRADED
        UNHEALTHY
        UNKNOWN
    }

    class TrendResult {
        +str metric_name
        +float current_value
        +float historical_avg
        +float change_percent
        +str trend_direction
        +bool is_anomalous
        +float confidence
        +to_dict() Dict
    }

    AlertDefinition --> AlertSeverity
```

## Audit Model Hierarchy

```mermaid
classDiagram
    class AuditEvent {
        +str event_id
        +str event_type
        +AuditCategory category
        +AuditAction action
        +AuditSeverity severity
        +str actor
        +str actor_type
        +str actor_id
        +str resource_type
        +str resource_id
        +str resource_name
        +str summary
        +str description
        +Dict details
        +Any previous_value
        +Any new_value
        +List[Dict] changes
        +str outcome
        +str reason
        +str error_message
        +datetime timestamp
        +str ip_address
        +str user_agent
        +str session_id
        +str correlation_id
        +str source
        +str environment
        +str host
        +str service
        +to_dict() Dict
        +to_summary() Dict
    }

    class AuditAction {
        <<enumeration>>
        CREATE
        READ
        UPDATE
        DELETE
        ACTIVATE
        DEACTIVATE
        EVALUATE
        RESOLVE
        ESCALATE
        OVERRIDE
        EXPORT
        IMPORT
        CONFIGURE
        VALIDATE
        APPROVE
        REJECT
        SYSTEM
    }

    class AuditCategory {
        <<enumeration>>
        RULE
        CONFLICT
        VIOLATION
        VALIDATION
        CONFIGURATION
        SYSTEM
        SECURITY
        COMPLIANCE
        USER
    }

    class AuditSeverity {
        <<enumeration>>
        DEBUG
        INFO
        WARNING
        ERROR
        CRITICAL
    }

    class AuditTrail {
        +str trail_id
        +str entity_type
        +str entity_id
        +List[AuditEvent] events
        +datetime created_at
        +datetime updated_at
        +add_event(event) void
        +get_events_by_action(action) List[AuditEvent]
        +get_events_by_actor(actor) List[AuditEvent]
        +get_events_by_timerange(start, end) List[AuditEvent]
        +get_summary() Dict
        +to_dict() Dict
    }

    AuditEvent --> AuditCategory
    AuditEvent --> AuditAction
    AuditEvent --> AuditSeverity
    AuditTrail *-- AuditEvent : contains
```
