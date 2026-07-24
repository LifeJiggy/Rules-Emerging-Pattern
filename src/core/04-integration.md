# Integration with Other Modules

## Component Diagram

The following diagram shows how the Core Rule Engine module integrates with Models, Monitoring, and external systems.

```mermaid
flowchart TD
    subgraph Core["Core Module"]
        RE["RuleEngine"]
        EC["EngineConfig"]
        RD["RuleDispatcher"]
        EP["EvaluationPipeline"]
        RA["ResultAggregator"]
        WN["WebhookNotifier"]
    end

    subgraph Models["Models Module (src/models/)"]
        Rule_model["Rule Model\nRule, RuleContext, RuleTier\nRulePattern, RuleType"]
        Validation_model["Validation Model\nValidationResult, Violation\nActionTaken, Suggestion"]
        Conflict_model["Conflict Model\nRuleConflict, ConflictType\nResolutionStrategy"]
        Monitoring_model["Monitoring Model\nAlertDefinition, MetricData\nHealthStatus, TrendResult"]
        Audit_model["Audit Model\nAuditEvent, AuditTrail\nAuditAction, AuditCategory"]
    end

    subgraph Monitoring["Monitoring Module (src/monitoring/)"]
        MC["MetricsCollector"]
        EB["EventBus"]
        AM["AlertManager"]
        DASH["MonitoringDashboard"]
        HC["HealthChecker"]
    end

    subgraph Learning["Learning Module (hypothetical)"]
        Trainer["Model Trainer"]
        Feedback["Feedback Collector"]
        Adaptive["Adaptive Rule Updater"]
    end

    subgraph External["External Systems"]
        Prom["Prometheus"]
        Webhook_Endpoint["Webhook Endpoints"]
        Logging["Logging System"]
        FileSystem["File System (YAML/JSON)"]
    end

    RE -->|"uses"| Rule_model
    RE -->|"uses"| Validation_model
    RE -->|"uses"| Conflict_model
    RE --> RA
    RE --> RD
    RE --> EP
    RE --> WN
    RE --> EC

    EC -->|"loads from"| FileSystem

    RD -->|"dispatches to"| EP
    EP -->|"feeds into"| RA

    RE -->|"emits metrics to"| MC
    RE -->|"publishes events"| EB
    RA -->|"emits aggregation metrics"| MC
    RD -->|"emits dispatch metrics"| MC
    EP -->|"emits pipeline metrics"| MC

    MC -->|"feeds"| AM
    MC -->|"powers"| DASH
    EB -->|"triggers"| AM
    EB -->|"updates"| DASH
    HC -->|"probes"| RE
    HC -->|"probes"| RD
    HC -->|"probes"| EP
    HC -->|"probes"| RA

    MC -->|"exports to"| Prom
    RE -->|"export_statistics_prometheus()"| Prom
    WN -->|"HTTP POST to"| Webhook_Endpoint

    Learning -->|"provides feedback"| RE
    Trainer -->|"generates rules"| Rule_model
    Adaptive -->|"adjusts config"| EC

    AM -->|"notifications"| Logging
    DASH -->|"renders"| Logging
```

## Cross-Module Integration Sequence

The following sequence diagram shows how the core module integrates with models and monitoring during a complete evaluation lifecycle.

```mermaid
sequenceDiagram
    participant API as API Layer
    participant RE as RuleEngine
    participant RuleM as Rule Model
    participant ValM as Validation Model
    participant ConfM as Conflict Model
    participant MC as MetricsCollector
    participant EB as EventBus
    participant AM as AlertManager
    participant DASH as Dashboard
    participant HC as HealthChecker

    API->>RE: evaluate(request)

    RE->>RuleM: get_applicable_rules(context)
    RuleM-->>RE: List[Rule]

    RE->>ConfM: detect_conflicts(rules)
    ConfM-->>RE: List[RuleConflict]

    alt Conflicts Detected
        RE->>ConfM: resolve_conflicts(conflicts)
        ConfM-->>RE: ResolutionStrategy
    end

    RE->>RE: _evaluate_by_tiers(request, rules)

    RE->>ValM: create Violation(rule_id, type, confidence)
    RE->>ValM: create ValidationResult(violations, score)

    RE->>MC: record_data_point("evaluation.count", 1)
    RE->>MC: record_data_point("evaluation.duration_ms", elapsed)

    RE->>EB: publish("evaluation.completed", {request_id, result})
    EB->>AM: evaluate_alert_conditions(event)

    alt Condition Met
        AM->>AM: create_or_update_alert()
        AM->>AM: check_escalation()
        AM-->>DASH: push_alert_update()
    end

    RE->>DASH: refresh_metric("evaluation.rate")

    HC->>RE: health_check()
    HC-->>RE: HealthResult

    RE-->>API: ValidationResult

    API->>ValM: serialize result to JSON
    ValM-->>API: JSON Response
```

## API Surface Diagram

```mermaid
flowchart LR
    subgraph PublicAPI["Public API Surface"]
        IN["evaluate(request) -> ValidationResult"]
        IB["evaluate_batch(requests) -> List[ValidationResult]"]
        IT["evaluate_tiered(request) -> ValidationResult"]
        STAT["get_statistics() -> Dict"]
        CACHE["clear_cache() -> void"]
        EXPORT["export_statistics_json(path) -> Dict"]
        PROM["export_statistics_prometheus() -> str"]
        START["start() -> void"]
    end

    subgraph InternalAPI["Internal API Surface"]
        GF["_get_applicable_rules(request) -> List[Rule]"]
        PF["_pre_filter_rules(rules, request) -> List[Rule]"]
        PP["_post_process_result(result, request) -> ValidationResult"]
        EB["_evaluate_by_tiers(request, rules) -> ValidationResult"]
        ES["_evaluate_single_rule(rule, content, context) -> Violation"]
        MERGE["_merge_tier_result(main, tier) -> void"]
        STATS["_update_statistics(result, start_time) -> void"]
    end

    subgraph HookAPI["Hook System"]
        PRE["add_pre_evaluate_hook(hook) -> void"]
        POST["add_post_process_hook(hook) -> void"]
    end

    PublicAPI --> InternalAPI
    PublicAPI --> HookAPI
```

## Integration Configuration

The `EngineConfig` provides a unified configuration interface shared across all modules:

```python
# Core module uses these config sections:
engine_config.get("engine.max_workers", 10)
engine_config.get("dispatcher.strategy", "round_robin")
engine_config.get("pipeline.timeout_per_stage_ms", 3000)
engine_config.get("aggregator.strategy", "weighted")
engine_config.get("monitoring.prometheus_enabled", False)

# Models module uses:
engine_config.get("cache.backend", "memory")
engine_config.get("logging.level", "INFO")

# Monitoring module uses:
engine_config.get("monitoring.export_interval", 300)
engine_config.get("monitoring.prometheus_port", 8000)
```

## Webhook Integration Flow

```mermaid
sequenceDiagram
    participant RE as RuleEngine
    participant WN as WebhookNotifier
    participant Target as External Webhook Target

    RE->>RE: evaluate(request)
    RE->>RE: detect critical violations

    alt Critical Violations Detected
        RE->>WN: notify_batch(violations, context)
        WN->>WN: _build_payload(violation)

        loop For each webhook URL
            WN->>WN: _rate_limit check

            loop For each retry (max_retries)
                WN->>Target: HTTP POST (json payload)
                alt Success (status < 400)
                    Target-->>WN: 200 OK
                    WN->>WN: increment notification_count
                else Failure
                    Target-->>WN: error response
                    WN->>WN: log warning, sleep(backoff)
                end
            end

            alt All Retries Exhausted
                WN->>WN: increment error_count
                WN->>WN: log error
            end
        end
    end
```

## Prometheus Export Integration

The core module exports metrics in Prometheus text format, which is consumed by the monitoring module and external Prometheus servers:

```
# HELP rule_engine_total_evaluations Total number of evaluations
# TYPE rule_engine_total_evaluations counter
rule_engine_total_evaluations 1234
# HELP rule_engine_average_time_ms Average processing time
# TYPE rule_engine_average_time_ms gauge
rule_engine_average_time_ms 45.2
# HELP rule_engine_cache_hits Cache hit count
# TYPE rule_engine_cache_hits counter
rule_engine_cache_hits 567
```
