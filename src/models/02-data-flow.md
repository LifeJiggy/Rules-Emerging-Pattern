# Model Data Flow

## Input to Rule Model Flow

The following flowchart illustrates how raw input data is processed through the Rule model, serialized, and eventually consumed by evaluation engines.

```mermaid
flowchart LR
    subgraph Input["Input Sources"]
        A1["YAML Rule File"]
        A2["JSON Rule File"]
        A3["API Request Body"]
        A4["Database Query"]
    end

    subgraph Parsing["Parsing Layer"]
        B1["yaml.safe_load()"]
        B2["json.loads()"]
        B3["Pydantic Model Validation"]
    end

    subgraph Model["Model Layer"]
        C1["Rule() constructor"]
        C2["Field validation"]
        C3["Default value application"]
        C4["Enum coercion"]
        C5["Rule model instance"]
    end

    subgraph Serialization["Serialization"]
        D1["rule.to_dict()"]
        D2["rule.to_json()"]
        D3["rule.to_yaml()"]
        D4["rule.json()"]
    end

    subgraph Deserialization["Deserialization"]
        E1["Rule.parse_obj(dict)"]
        E2["Rule.parse_raw(json_str)"]
        E3["RuleSchema().load(yaml_data)"]
    end

    subgraph Usage["Usage"]
        F1["Engine evaluates content"]
        F2["Violation detection"]
        F3["Result aggregation"]
        F4["Conflict detection"]
    end

    A1 --> B1
    A2 --> B2
    A3 --> B3
    A4 --> B3

    B1 --> C1
    B2 --> C1
    B3 --> C1

    C1 --> C2 --> C3 --> C4 --> C5

    C5 --> D1
    C5 --> D2
    C5 --> D3
    C5 --> D4

    D1 --> E1
    D2 --> E2
    D3 --> E3

    E1 --> F1
    E2 --> F2
    E3 --> F3
    E1 --> F4

    style Input fill:#e3f2fd
    style Parsing fill:#fff3e0
    style Model fill:#c8e6c9
    style Serialization fill:#f3e5f5
    style Deserialization fill:#e1f5fe
    style Usage fill:#ffcdd2
```

## Model Lifecycle Sequence

The following sequence diagram illustrates the complete lifecycle of a Rule model from creation through serialization, storage, retrieval, and usage.

```mermaid
sequenceDiagram
    participant Admin as Admin/API
    participant RuleM as Rule Model
    participant Validator as Pydantic Validator
    participant Store as Rule Store
    participant Cache as Rule Cache
    participant Engine as Rule Engine

    Admin->>RuleM: Rule(id, name, patterns, ...)
    RuleM->>Validator: validate fields
    Validator-->>RuleM: validation passed

    RuleM->>RuleM: apply defaults (status=ACTIVE, priority=100)
    RuleM-->>Admin: Rule instance created

    Admin->>RuleM: rule.to_dict()
    RuleM-->>Admin: Dict representation

    Admin->>Store: save(rule.to_dict())
    Store-->>Admin: rule_id stored

    Admin->>Cache: cache.set(rule.id, rule)
    Cache-->>Admin: cached

    Note over Engine,Store: Later... evaluation request arrives

    Engine->>Cache: get_applicable_rules(context)
    Cache-->>Engine: List[Rule] (cache hit)

    Engine->>RuleM: rule.is_applicable_to_context(context)
    RuleM-->>Engine: True/False

    Engine->>RuleM: rule.patterns[0].keywords
    RuleM-->>Engine: ["keyword1", "keyword2"]

    Engine->>RuleM: rule.patterns[0].match(content)
    RuleM-->>Engine: MatchResult

    Engine->>RuleM: create Violation from rule
    RuleM-->>Engine: Violation instance

    Engine->>Engine: aggregate into ValidationResult

    Admin->>RuleM: rule.updated_at = now()
    Admin->>RuleM: rule.status = RuleStatus.INACTIVE
    Admin->>Store: update(rule.to_dict())
    Admin->>Cache: invalidate(rule.id)

    Admin->>RuleM: rule.to_yaml()
    RuleM-->>Admin: YAML export
```

## Data Transformation Across Model Types

The following diagram shows how data is transformed as it flows from one model type to another during the evaluation lifecycle.

```mermaid
flowchart LR
    subgraph RuleModels["Rule Models"]
        R["Rule\n- id, name\n- tier, type\n- severity\n- patterns"]
        RC["RuleContext\n- user_id\n- session_id\n- metadata"]
        RER["RuleEvaluationRequest\n- content\n- context\n- options"]
    end

    subgraph ValidationModels["Validation Models"]
        V["Violation\n- rule_id\n- matched_content\n- confidence\n- action_taken"]
        VR["ValidationResult\n- valid flag\n- total_score\n- violations list\n- processing_time"]
        S["Suggestion\n- message\n- category\n- relevance"]
    end

    subgraph ConflictModels["Conflict Models"]
        RC2["RuleConflict\n- type\n- severity\n- involved rules\n- resolution"]
        CR["ConflictResolution\n- strategy\n- resolved_rule\n- timestamp"]
    end

    subgraph MonitoringModels["Monitoring Models"]
        AD["AlertDefinition\n- metric_name\n- threshold\n- severity"]
        MD["MetricData\n- name\n- value\n- labels\n- timestamp"]
    end

    subgraph AuditModels["Audit Models"]
        AE["AuditEvent\n- action\n- actor\n- resource\n- timestamp"]
        AT["AuditTrail\n- entity events\n- summary"]
    end

    RER -->|"evaluate()"| V
    V -->|"aggregate"| VR
    R -->|"get_applicable"| RER
    RC -->|"context"| RER

    R -->|"conflict detection"| RC2
    RC2 -->|"resolve"| CR

    VR -->|"metric recording"| MD
    VR -->|"alert evaluation"| AD

    VR -->|"audit logging"| AE
    RC2 -->|"audit logging"| AE
    R -->|"configuration audit"| AE

    AE -->|"trail building"| AT

    V -->|"to_summary()"| S

    style RuleModels fill:#e8f5e9
    style ValidationModels fill:#e3f2fd
    style ConflictModels fill:#fff3e0
    style MonitoringModels fill:#f3e5f5
    style AuditModels fill:#ffebee
```

## Serialization Formats Flow

```mermaid
flowchart TD
    A["Rule Model Instance"] --> B{"Export Format?"}

    B -->|"JSON"| C["json.dumps(rule.to_dict())"]
    B -->|"YAML"| D["yaml.dump(rule.to_dict())"]
    B -->|"Dict"| E["rule.to_dict()"]
    B -->|"Flat"| F["Flatten nested keys"]

    C --> G["HTTP Response"]
    C --> H["File Storage"]
    C --> I["Database Document"]

    D --> J["Rule Definition File"]
    D --> K["Configuration Export"]

    E --> L["In-Memory Processing"]
    E --> M["Cache Storage"]

    F --> N["Environment Variables"]
    F --> O["Simple Config Stores"]

    subgraph Import["Import Paths"]
        P["JSON File"] --> Q["json.loads()"]
        Q --> R["Rule.parse_obj()"]
        S["YAML File"] --> T["yaml.safe_load()"]
        T --> R
        U["API Request"] --> V["Rule.parse_raw()"]
        V --> R
    end
```

## Error Handling in Model Serialization

```mermaid
flowchart TD
    A["Input Data"] --> B["Pydantic Model Constructor"]
    B --> C{"Validation Error?"}
    C -->|No| D["Model Created Successfully"]
    D --> E["Normal Serialization Path"]

    C -->|Yes| F["ValidationError Raised"]
    F --> G{"Error Type?"}

    G -->|"Field type mismatch"| H["Coerce value if possible"]
    G -->|"Missing required field"| I["Apply default or raise"]
    G -->|"Constraint violation"| J["Raise ValueError"]
    G -->|"Enum value invalid"| K["Raise EnumError"]

    H --> L{"Coercion Successful?"}
    L -->|Yes| M["Use coerced value"]
    L -->|No| N["Raise TypeError"]

    I --> O{"Default Available?"}
    O -->|Yes| P["Apply Field(default=...)"]
    O -->|No| Q["Raise ValidationError"]

    J --> R["Error logged, rejected"]
    K --> R

    P --> D
    M --> D
```

## Model Versioning & Migration

```mermaid
flowchart LR
    subgraph V1["Version 1.0.0"]
        A["Rule\n- id\n- name\n- patterns (list)"]
    end

    subgraph V2["Version 1.1.0"]
        B["Rule\n- id\n- name\n- patterns (list)\n- conditions (dict)"]
    end

    subgraph V3["Version 2.0.0"]
        C["Rule\n- id\n- name\n- patterns (list)\n- conditions (dict)\n- exceptions (list)\n- tier (enum)"]
    end

    A -->|"migrate_v1_to_v1_1"| B
    B -->|"migrate_v1_1_to_v2"| C

    D["Rule stored as JSON in DB"] --> E{"Detect Version"}
    E -->|"version == 1.0.0"| F["Apply migration V1->V2"]
    F --> G["Apply migration V2->V3"]
    E -->|"version == 1.1.0"| G
    E -->|"version == 2.0.0"| H["No migration needed"]
    G --> H
    H --> I["Return current Rule model"]
```
