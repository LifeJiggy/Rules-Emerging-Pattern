# Utility Module Data Flow

## Config Load → Validate → Distribute Flow

The configuration loading pipeline processes configuration from multiple sources, validates it, and distributes it to all modules.

```mermaid
flowchart LR
    subgraph Sources["Config Sources"]
        A[YAML File]
        B[JSON File]
        C[Environment Variables]
        D[Default Values]
    end

    subgraph Load["Config Loader"]
        E[ConfigLoader.load()]
        F[Merge Configs]
    end

    subgraph Validate["Validation"]
        G[Validate Structure]
        H[Validate Values]
        I{Valid?}
    end

    subgraph Distribute["Distribution"]
        J[Extract Module Configs]
        K[Core Config]
        L[Learning Config]
        M[Memory Config]
        N[Utils Config]
    end

    A --> E
    B --> E
    C --> E
    D --> F
    E --> F
    F --> G
    G --> H
    H --> I
    I -->|yes| J
    I -->|no| O[Log Errors]
    J --> K
    J --> L
    J --> M
    J --> N
```

### Config Load Sequence

```mermaid
sequenceDiagram
    participant App as Application
    participant CL as ConfigLoader
    participant File as File System
    participant Env as Environment
    participant Modules as Consumer Modules

    App->>CL: load("config.yaml")
    activate CL
    CL->>File: read file
    File-->>CL: raw config dict
    CL->>CL: parse YAML/JSON

    CL->>CL: load_from_env("APP_")
    CL->>Env: read environment variables
    Env-->>CL: env config dict

    CL->>CL: merge with defaults
    CL->>CL: validate against schema
    alt Validation fails
        CL-->>App: List[str] errors
    else Validation passes
        CL->>CL: store merged config
        CL-->>App: merged config dict
    end
    deactivate CL

    App->>CL: distribute()
    activate CL
    CL->>CL: extract module-specific sections
    CL->>Modules: core_config
    CL->>Modules: learning_config
    CL->>Modules: memory_config
    CL->>Modules: utils_config
    deactivate CL
```

## Cache Data Flow

### Cache Get/Set/Invalidate

```mermaid
sequenceDiagram
    participant Client
    participant CM as CacheManager
    participant Namespace as Namespace Store

    Client->>CM: set("patterns", "pattern_001", data, ttl=3600)
    activate CM
    CM->>Namespace: check namespace exists
    alt Namespace missing
        CM->>CM: create "patterns" namespace
    end
    CM->>Namespace: store CacheEntry with TTL
    CM-->>Client: stored
    deactivate CM

    Client->>CM: get("patterns", "pattern_001")
    activate CM
    CM->>Namespace: lookup entry
    alt Entry found & TTL valid
        CM->>CM: update access stats
        CM-->>Client: cached value
    else Entry expired
        CM->>Namespace: remove expired entry
        CM-->>Client: None
    else Entry not found
        CM-->>Client: None
    end
    deactivate CM

    Client->>CM: invalidate("patterns", "pattern_001")
    activate CM
    CM->>Namespace: delete entry
    CM-->>Client: success
    deactivate CM
```

## Rate Limiter Data Flow

### Token Bucket Algorithm

```mermaid
flowchart TD
    A[Request: client_id] --> B[Get or create bucket]
    B --> C[Compute elapsed time]
    C --> D[Refill: tokens += elapsed * refill_rate]
    D --> E{Tokens > capacity?}
    E -->|yes| F[Cap at capacity]
    E -->|no| G[Keep current tokens]
    F --> H{Tokens >= cost?}
    G --> H
    H -->|yes| I[Consume: tokens -= cost]
    I --> J[Allow request]
    H -->|no| K[Deny request]
    J --> L[Update last_refill]
    K --> L
```

### Rate Limiter Sequence

```mermaid
sequenceDiagram
    participant Client
    participant RL as RateLimiter
    participant Bucket as TokenBucket

    Client->>RL: check("client_001")
    activate RL
    RL->>Bucket: get or create bucket
    activate Bucket

    RL->>Bucket: compute refill amount
    RL->>Bucket: tokens += delta * refill_rate

    alt tokens >= 1
        Bucket-->>RL: True
        RL-->>Client: allowed
    else tokens < 1
        Bucket-->>RL: False
        RL-->>Client: rate limited
    end
    deactivate Bucket
    deactivate RL

    Client->>RL: consume("client_001", 1)
    activate RL
    RL->>Bucket: refill first
    RL->>Bucket: tokens -= 1
    Bucket-->>RL: consumed
    RL-->>Client: success
    deactivate RL

    Client->>RL: get_remaining("client_001")
    activate RL
    RL->>Bucket: get current tokens
    Bucket-->>RL: float tokens
    RL-->>Client: remaining count
    deactivate RL
```

## Serializer Data Flow

```mermaid
flowchart LR
    subgraph Input["Serialization Input"]
        A[Python Objects]
        B[Numpy Arrays]
        C[Datetime Objects]
        D[UUID Objects]
        E[Decimal Values]
    end

    subgraph Formats["Output Formats"]
        F[JSON: serialize_json]
        G[JSON Lines: serialize_jsonl]
        H[Binary: serialize_binary]
    end

    subgraph Deserialize["Deserialization"]
        I[JSON → Python]
        J[Binary → Python]
    end

    A --> F
    B --> F
    C --> F
    D --> F
    E --> F
    A --> G
    B --> G
    A --> H
    F --> I
    G --> I
    H --> J
```

## Verifier Pipeline

```mermaid
sequenceDiagram
    participant Caller
    participant V as Verifier
    participant Struct as Structure Check
    participant Dep as Dependency Check
    participant Temp as Temporal Check
    participant Conf as Confidence Check
    participant LTM as LongTermMemory
    participant IM as InferenceMemory

    Caller->>V: verify(target, target_type)
    activate V
    V->>V: create VerificationResult

    par Stage 1-4
        V->>Struct: verify_structure(target)
        activate Struct
        Struct-->>V: CheckResult
        deactivate Struct

        V->>Dep: verify_dependencies(target)
        activate Dep
        Dep-->>V: CheckResult
        deactivate Dep

        V->>Temp: verify_temporal_consistency(target)
        activate Temp
        Temp-->>V: CheckResult
        deactivate Temp

        V->>Conf: verify_confidence(target)
        activate Conf
        Conf-->>V: CheckResult
        deactivate Conf
    end

    par Stage 5: Cross-reference
        V->>LTM: verify_against_knowledge(target)
        activate LTM
        LTM-->>V: CheckResult
        deactivate LTM
        V->>IM: verify_against_inferences(target)
        activate IM
        IM-->>V: CheckResult
        deactivate IM
    end

    V->>V: compute weighted overall_score
    V->>V: determine passed / failed
    V-->>Caller: VerificationResult
    deactivate V
```

## Refinement Pipeline

```mermaid
sequenceDiagram
    participant Analyzer as Analysis Engine
    participant R as Refiner
    participant Store as Rule Store
    participant Verifier as Verifier

    Analyzer->>R: identify candidates for refinement
    activate R
    R->>R: evaluate transformation options

    par Generate Suggestions
        R->>R: generalize(rule)
        R->>R: specialize(rule)
        R->>R: merge([rule_a, rule_b])
        R->>R: split(rule)
        R->>R: tune_threshold(rule)
        R->>R: extract_template(rule)
    end

    R->>R: score suggestions by expected benefit
    R-->>Analyzer: RefinementSuggestion list
    deactivate R

    Analyzer->>R: apply_refinement(suggestion)
    activate R
    R->>R: snapshot current state
    R->>R: apply transformation
    R->>Verifier: re-verify refined rule
    activate Verifier
    Verifier-->>R: VerificationResult
    deactivate Verifier

    R->>R: compute improvement_score
    alt improvement_score > min_improvement
        R->>Store: update rule
        R-->>Analyzer: RefinementRecord (applied=true)
    else
        R->>R: rollback
        R-->>Analyzer: RefinementRecord (applied=false)
    end
    deactivate R
```

## Migration Flow

```mermaid
sequenceDiagram
    participant Admin as Administrator
    participant MM as MigrationManager
    participant Source as Source Module
    participant Target as Target Module
    participant Validator as Post-Migration Validator

    Admin->>MM: plan_migration(source_module, target_version)
    activate MM
    MM->>Source: get current version
    Source-->>MM: version X
    MM->>MM: lookup registered migrations
    MM->>MM: compose step sequence
    MM-->>Admin: MigrationPlan
    deactivate MM

    Admin->>MM: run_migration(migration_id)
    activate MM
    MM->>Source: begin batch read
    Source-->>MM: batch of items
    loop each batch
        MM->>MM: apply transformation rules
        MM->>Target: write transformed items
        Target-->>MM: success/failure
    end
    MM->>Validator: validate migrated data
    activate Validator
    Validator->>Target: sample and verify
    Target-->>Validator: verified
    Validator-->>MM: validation report
    deactivate Validator

    alt Validation passes
        MM->>MM: create MigrationRecord (success)
        MM-->>Admin: MigrationRecord with summary
    else Validation fails
        MM->>Source: rollback changes
        MM-->>Admin: MigrationRecord with errors
    end
    deactivate MM
```

## Alert Flow

```mermaid
sequenceDiagram
    participant Source as Metric Source
    participant M as Monitor
    participant Checker as Threshold Checker
    participant AlertGen as Alert Generator
    participant Store as Alert Store

    Source->>M: record_metric(name, value, labels)
    activate M
    M->>M: store MetricSample
    M->>Checker: check thresholds for metric
    deactivate M

    activate Checker
    loop for each alert rule matching metric
        Checker->>Checker: evaluate condition(value, threshold)
        alt Condition triggered
            Checker->>AlertGen: generate alert
            activate AlertGen
            AlertGen->>AlertGen: create Alert object
            AlertGen->>AlertGen: check cooldown period
            alt Cooldown expired
                AlertGen->>Store: persist alert
                AlertGen-->>Checker: alert_id
            else Within cooldown
                AlertGen-->>Checker: suppressed
            end
            deactivate AlertGen
        end
    end
    deactivate Checker
```

## Lifecycle State Transitions

```mermaid
sequenceDiagram
    participant Creator as Rule Creator
    participant LM as LifecycleManager
    participant Verifier as Verifier
    participant Store as Rule Store

    Creator->>LM: create_rule(rule_data)
    activate LM
    LM->>LM: set state = Draft
    LM-->>Creator: rule_id + Draft status
    deactivate LM

    Creator->>LM: submit_for_review(rule_id)
    activate LM
    LM->>LM: validate transition Draft→PendingReview
    LM->>Verifier: verify(rule)
    activate Verifier
    Verifier-->>LM: VerificationResult
    deactivate Verifier
    alt Verification passed
        LM->>LM: set state = PendingReview
    else Verification failed
        LM->>LM: remain in Draft
    end
    LM-->>Creator: current state
    deactivate LM

    Creator->>LM: approve(rule_id)
    activate LM
    LM->>LM: validate transition PendingReview→Active
    LM->>LM: set state = Active
    LM->>Store: persist rule
    deactivate LM

    Creator->>LM: archive(rule_id)
    activate LM
    LM->>LM: validate transition Active→Archived
    LM->>LM: set state = Archived
    LM->>LM: log archive timestamp
    LM-->>Creator: archived
    deactivate LM
```

## Normalization Method Flow

```mermaid
flowchart TD
    subgraph Input["Input Values"]
        V[Raw Feature Values]
    end

    subgraph Methods["Normalization Methods"]
        M1[Min-Max: (x - min) / (max - min)]
        M2[Z-Score: (x - mean) / std]
        M3[Robust: (x - median) / IQR]
        M4[Log: log(1 + x)]
        M5[Unit Length: x / ||x||]
    end

    subgraph Output["Output"]
        N[Normalized Values]
    end

    V --> M1
    V --> M2
    V --> M3
    V --> M4
    V --> M5
    M1 --> N
    M2 --> N
    M3 --> N
    M4 --> N
    M5 --> N
```

## Metric Computation Flow

```mermaid
flowchart TD
    subgraph Input["Evaluator Input"]
        Y[Actual Labels]
        P[Predicted Labels]
    end

    subgraph Confusion["Confusion Matrix"]
        C1[TP: true positive]
        C2[TN: true negative]
        C3[FP: false positive]
        C4[FN: false negative]
    end

    subgraph Metrics["Computed Metrics"]
        M1[Accuracy: TP+TN / Total]
        M2[Precision: TP / TP+FP]
        M3[Recall: TP / TP+FN]
        M4[F1: 2*P*R / P+R]
        M5[Specificity: TN / TN+FP]
        M6[MCC: Matthews Correlation]
        M7[Log Loss]
    end

    Y --> C1
    Y --> C2
    Y --> C3
    Y --> C4
    P --> C1
    P --> C2
    P --> C3
    P --> C4
    C1 --> M1
    C2 --> M1
    C3 --> M1
    C4 --> M1
    C1 --> M2
    C3 --> M2
    C1 --> M3
    C4 --> M3
    M2 --> M4
    M3 --> M4
    C1 --> M5
    C4 --> M5
    C2 --> M5
    C3 --> M5
    C1 --> M6
    C2 --> M6
    C3 --> M6
    C4 --> M6
    Y --> M7
    P --> M7
```