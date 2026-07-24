# Model Integration

## Component Diagram

The following diagram shows how models are consumed by every module in the system.

```mermaid
flowchart TD
    subgraph Models["Models Module (src/models/)"]
        RuleM["Rule Model\nRule, RuleContext\nRuleTier, RuleType\nRuleSeverity, RuleStatus"]
        ValM["Validation Model\nValidationResult, Violation\nActionTaken, Suggestion\nViolationType"]
        ConfM["Conflict Model\nRuleConflict, ConflictType\nResolutionStrategy\nConflictSeverity"]
        MonM["Monitoring Model\nAlertDefinition, MetricData\nHealthStatus, TrendResult"]
        AuditM["Audit Model\nAuditEvent, AuditTrail\nAuditCategory, AuditAction"]
    end

    subgraph Core["Core Module (src/core/)"]
        RE["RuleEngine"]
        EP["EvaluationPipeline"]
        RA["ResultAggregator"]
        RD["RuleDispatcher"]
    end

    subgraph ModelsInternal["Model Consumers"]
        RM["RuleManager"]
        VL["ViolationLogger"]
        CD["ConflictDetector"]
        CR["ConflictResolver"]
    end

    subgraph Monitoring["Monitoring Module (src/monitoring/)"]
        MC["MetricsCollector"]
        AM["AlertManager"]
        HC["HealthChecker"]
        DASH["Dashboard"]
        EB["EventBus"]
    end

    subgraph API["API Layer"]
        REST["REST API"]
        GraphQL["GraphQL API"]
        GRPC["gRPC Service"]
    end

    subgraph Storage["Storage Layer"]
        DB["Database"]
        FS["File System"]
        Cache["Cache"]
    end

    RE -->|"evaluate() uses"| RuleM
    RE -->|"returns"| ValM
    RE -->|"detects"| ConfM

    RA -->|"aggregates"| ValM
    RA -->|"resolves"| ConfM

    RM -->|"manages"| RuleM
    VL -->|"logs"| ValM
    CD -->|"generates"| ConfM
    CR -->|"produces"| ConfM

    MC -->|"records"| MonM
    AM -->|"evaluates"| MonM
    HC -->|"publishes"| MonM
    DASH -->|"displays"| MonM
    EB -->|"transports"| MonM

    AuditM -->|"logs"| AuditM

    REST -->|"serializes"| RuleM
    REST -->|"serializes"| ValM
    REST -->|"serializes"| AuditM
    GraphQL -->|"resolves"| RuleM
    GraphQL -->|"resolves"| ValM
    GRPC -->|"protobuf"| RuleM

    DB -->|"stores"| RuleM
    DB -->|"stores"| AuditM
    FS -->|"persists"| RuleM
    Cache -->|"caches"| RuleM
    Cache -->|"caches"| ValM
```

## Integration Sequence: API to Model to Response

The following sequence diagram shows how models are used across the full request-response lifecycle.

```mermaid
sequenceDiagram
    participant Client
    participant API as API Gateway
    participant RuleM as Rule Model
    participant ValM as Validation Model
    participant ConfM as Conflict Model
    participant MonM as Monitoring Model
    participant AuditM as Audit Model
    participant Core as Core Engine
    participant DB as Database

    Client->>API: POST /evaluate {content, context}

    API->>RuleM: RuleEvaluationRequest(content, context)
    RuleM->>RuleM: validate fields

    API->>AuditM: AuditEvent(action=EVALUATE, actor=client_id)
    AuditM-->>API: event_id

    API->>Core: evaluate(request)

    Core->>RuleM: get_applicable_rules(context)
    RuleM-->>Core: List[Rule]

    Core->>ConfM: detect_conflicts(rules)
    ConfM-->>Core: List[RuleConflict]

    alt Conflicts Found
        Core->>ConfM: resolve(conflict, strategy)
        ConfM-->>Core: ConflictResolution
    end

    Core->>ValM: create Violation instances
    ValM-->>Core: Violation objects

    Core->>ValM: aggregate into ValidationResult
    ValM-->>Core: ValidationResult

    Core->>MonM: record MetricData(evaluation.count, duration)
    MonM-->>Core: metric recorded

    Core-->>API: ValidationResult

    API->>ValM: result.to_dict()
    ValM-->>API: Dict representation

    API->>AuditM: update AuditEvent with outcome
    AuditM->>DB: persist audit trail

    API-->>Client: JSON Response

    Client->>API: GET /rules
    API->>DB: query rules
    DB-->>API: List[Dict]

    API->>RuleM: Rule.parse_obj(data)
    RuleM-->>API: Rule instances

    API-->>Client: JSON({rules: [...]})

    Client->>API: POST /rules {rule definition}
    API->>RuleM: Rule(**data)
    RuleM->>RuleM: validate
    API->>AuditM: AuditEvent(action=CREATE, resource=rule)
    API->>DB: save rule
    API-->>Client: JSON({rule_id, status: "created"})
```

## Shared Model Usage Patterns

```mermaid
flowchart TD
    subgraph Pattern1["Pattern 1: Request-Response"]
        A["RuleEvaluationRequest"] --> B["RuleEngine.evaluate()"]
        B --> C["ValidationResult"]
        C --> D["Client receives result"]
    end

    subgraph Pattern2["Pattern 2: Batch Processing"]
        E["List[RuleEvaluationRequest]"] --> F["RuleEngine.evaluate_batch()"]
        F --> G["List[ValidationResult]"]
        G --> H["ResultAggregator.aggregate()"]
        H --> I["AggregatedResult"]
    end

    subgraph Pattern3["Pattern 3: Conflict-Aware"]
        J["List[Rule]"] --> K["ConflictDetector.detect()"]
        K --> L["List[RuleConflict]"]
        L --> M["ConflictResolver.resolve()"]
        M --> N["ConflictResolution"]
        N --> O["Adjusted Rule list"]
    end

    subgraph Pattern4["Pattern 4: Monitoring Pipeline"]
        P["ValidationResult"] --> Q["MetricsCollector.record()"]
        P --> R["AlertManager.evaluate()"]
        Q --> S["Dashboard.refresh()"]
        R --> T["Alert notification"]
    end

    subgraph Pattern5["Pattern 5: Audit Trail"]
        U["Any system action"] --> V["AuditEvent(action, actor, resource)"]
        V --> W["AuditTrail.append(event)"]
        W --> X["AuditTrail stored in DB"]
        X --> Y["Compliance queries"]
        X --> Z["Forensic analysis"]
    end
```

## Model Serialization Integration

```mermaid
sequenceDiagram
    participant Svc as Service
    participant Model as Pydantic Model
    participant Ser as Serializer
    participant Wire as Wire Format
    participant Consumer

    Svc->>Model: Rule(id="r1", name="test", patterns=[...])
    Model->>Model: __init__ with validation

    Note over Svc,Consumer: Serialization to dict
    Svc->>Model: rule.to_dict()
    Model-->>Svc: Dict[str, Any]

    Note over Svc,Consumer: Serialization to JSON
    Svc->>Model: rule.json()
    Model-->>Svc: str (JSON)

    Note over Svc,Consumer: Serialization to YAML
    Svc->>Model: yaml.dump(rule.to_dict())
    Model-->>Svc: str (YAML)

    Note over Svc,Consumer: Deserialization
    Consumer->>Model: Rule.parse_obj(data_dict)
    Model->>Model: field validation
    Model-->>Consumer: Rule instance

    Consumer->>Model: Rule.parse_raw(json_str)
    Model->>Model: JSON parsing + validation
    Model-->>Consumer: Rule instance

    Note over Svc,Consumer: Schema migration
    Svc->>Model: version field read
    Model-->>Svc: "2.0.0"
    Svc->>Svc: apply migrations if needed
    Svc->>Model: Rule(**migrated_data)
    Model-->>Svc: Current version Rule
```

## Cross-Module Audit Integration

```mermaid
flowchart LR
    subgraph Sources["Audit Event Sources"]
        S1["Rule CRUD"]
        S2["Evaluation Results"]
        S3["Config Changes"]
        S4["Alert Triggers"]
        S5["User Overrides"]
    end

    subgraph Bus["Event Bus (src/monitoring/event_bus.py)"]
        EB["Event Bus\npublish/subscribe\npattern"]
    end

    subgraph AuditSys["Audit System"]
        AE["AuditEvent model"]
        AT["AuditTrail model"]
        Store["Persistent Storage"]
    end

    subgraph Consumers["Audit Consumers"]
        C1["Compliance Reporter"]
        C2["Security Analyst"]
        C3["System Auditor"]
        C4["Forensic Investigator"]
    end

    S1 -->|"publish audit event"| EB
    S2 -->|"publish audit event"| EB
    S3 -->|"publish audit event"| EB
    S4 -->|"publish audit event"| EB
    S5 -->|"publish audit event"| EB

    EB -->|"route to audit"| AE
    AE -->|"append to"| AT
    AT -->|"store"| Store

    Store -->|"query"| C1
    Store -->|"query"| C2
    Store -->|"query"| C3
    Store -->|"query"| C4
```
