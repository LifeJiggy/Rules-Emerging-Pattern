# Data Flow

## Primary Evaluation Sequence

The following sequence diagram illustrates the complete flow of a single evaluation request through the core engine components.

```mermaid
sequenceDiagram
    participant Client
    participant RE as RuleEngine
    participant RM as RuleManager
    participant RD as RuleDispatcher
    participant EP as EvaluationPipeline
    participant TE as TierEngine
    participant RA as ResultAggregator
    participant Cache as LRUCache

    Client->>RE: evaluate(request)
    RE->>RE: pre_evaluate_hooks(request)
    RE->>RE: _get_content_hash(content)

    RE->>Cache: _get_cached_result(hash, context)
    Cache-->>RE: cached result or None

    alt Cache Hit
        RE-->>Client: cached ValidationResult
    else Cache Miss
        RE->>RM: get_applicable_rules(request)
        RM-->>RE: List[Rule]

        alt Pre-Filter Enabled
            RE->>RE: _pre_filter_rules(rules, request)
        end

        RE->>RD: dispatch(request, priority)
        RD->>RD: _select_engine()
        RD->>TE: evaluate(request)
        TE-->>RD: tier_result
        RD-->>RE: ValidationResult

        RE->>EP: execute(request)
        EP->>EP: _execute_sequential(context, stages)
        EP-->>RE: PipelineContext

        alt Post-Process Enabled
            RE->>RE: _post_process_result(result, request)
            RE->>RE: _deduplicate_violations(result)
        end

        RE->>RE: post_process_hooks(result)

        RE->>Cache: _cache_result(hash, context, result)

        alt Critical Violations
            RE->>WN: notify_violation(violation)
        end

        RE->>RE: _async_update_statistics(result, start_time)
        RE-->>Client: ValidationResult
    end
```

## Error Handling Flow

The following flowchart describes the error handling paths within the evaluation pipeline, covering timeouts, engine failures, and pipeline stage errors.

```mermaid
flowchart TD
    A["Evaluation Request"] --> B{"Engine Available?"}
    B -->|No| C["Circuit Breaker Open?"]
    C -->|Yes - Open| D["Check Recovery Timeout"]
    D -->{"Recovery Elapsed?"}
    D -->|No| E["Return EngineUnavailableError"]
    D -->|Yes| F["Transition to Half-Open"]
    F --> G["Allow Probe Request"]
    G --> H{"Probe Succeeds?"}
    H -->|Yes| I["Close Circuit Breaker"]
    H -->|No| J["Reopen Circuit Breaker"]
    I --> K["Dispatch Request"]
    J --> E
    B -->|Yes| K
    K --> L{"Dispatch Timeout?"}
    L -->|Yes| M{"Retries Remaining?"}
    M -->|Yes| N["Increment Retry Count"]
    N --> O["Backoff Sleep"]
    O --> B
    M -->|No| P["Raise DispatchTimeoutError"]
    L -->|No| Q{"Stage Timeout?"}
    Q -->|Yes| R{"Stage Required?"}
    R -->|Yes| S["Raise StageExecutionError"]
    R -->|No| T{"Timeout Behavior?"}
    T -->|"skip"| U["Mark Stage Skipped"]
    T -->|"fail"| V["Abort Pipeline"]
    T -->|"retry"| W["Retry Stage"]
    W --> Q
    U --> X["Continue Next Stage"]
    V --> Y["Return Partial Result"]
    Q -->|No| Z{"Stage Failed?"}
    Z -->|Yes| AA{"Fail on Stage Error?"}
    AA -->|Yes| AB["Raise Pipeline Error"]
    AA -->|No| AC["Log Warning, Continue"]
    AC --> X
    Z -->|No| AD{"All Stages Complete?"}
    AD -->|No| X
    AD -->|Yes| AE["Aggregate Results"]
    AE --> AF["Return ValidationResult"]

    B --> AG{"Engine Health Check Failed?"}
    AG -->|Yes| AH["Mark Engine DEGRADED"]
    AH --> AI["Try Next Available Engine"]
    AI --> B
```

## Data Transformation Pipeline

The following diagram shows how data is transformed as it flows through each stage of the evaluation process.

```mermaid
flowchart LR
    subgraph Input["Input Layer"]
        A["Raw Content (str)"] --> B["RuleEvaluationRequest"]
        B --> C["Content Hash (sha256)"]
    end

    subgraph PreProcessing["Pre-Processing"]
        C --> D["Rule Selection"]
        D --> E["Rule List"]
        E --> F["Pre-Filtering"]
        F --> G["Filtered Rule List"]
    end

    subgraph Evaluation["Evaluation Layer"]
        G --> H["Tiered Evaluation"]
        H --> I["Safety Check"]
        I --> J["Operational Check"]
        J --> K["Preference Check"]
        K --> L["Violation List"]
    end

    subgraph PostProcessing["Post-Processing"]
        L --> M["Deduplication"]
        M --> N["Deduplicated Violations"]
        N --> O["Post-Process Hooks"]
        O --> P["Processed Violations"]
    end

    subgraph Aggregation["Aggregation Layer"]
        P --> Q["Weighted Scoring"]
        Q --> R["Confidence Calculation"]
        R --> S["Score + Confidence"]
        S --> T["AggregatedResult"]
    end

    subgraph Output["Output Layer"]
        T --> U["Cache Storage"]
        T --> V["Statistics Update"]
        T --> W["JSON Response"]
        T --> X["Prometheus Export"]
        T --> Y["Webhook Notification"]
    end

    subgraph Serialization["Serialization"]
        W --> Z["to_dict()"]
        Z --> AA["JSON Serialization"]
        Y --> AB["_build_payload()"]
        AB --> AC["HTTP POST"]
    end

    style A fill:#e1f5fe
    style W fill:#c8e6c9
    style X fill:#c8e6c9
    style Y fill:#c8e6c9
    style AA fill:#fff3e0
    style AC fill:#fff3e0
```

## Batch Processing Flow

```mermaid
sequenceDiagram
    participant Client
    participant RE as RuleEngine
    participant BP as BatchProcessor
    participant Sem as Semaphore
    participant Engine as TierEngine

    Client->>RE: evaluate_batch(requests)
    RE->>BP: process(requests, callback)

    BP->>BP: Create process_one tasks

    par Parallel Processing (max_concurrency)
        BP->>Sem: acquire()
        BP->>Engine: evaluate(request[0])
        Engine-->>BP: result[0]
        BP->>Sem: release()

        BP->>Sem: acquire()
        BP->>Engine: evaluate(request[1])
        Engine-->>BP: result[1]
        BP->>Sem: release()

        BP->>Sem: acquire()
        BP->>Engine: evaluate(request[N])
        Engine-->>BP: result[N]
        BP->>Sem: release()
    end

    BP->>BP: gather completed results
    BP->>BP: fill gaps with error results
    BP-->>RE: List[ValidationResult]
    RE-->>Client: List[ValidationResult]
```

## Cache Lifecycle

```mermaid
flowchart LR
    A["Content Hash + Context"] --> B{"In Cache?"}
    B -->|Yes| C{"TTL Expired?"}
    C -->|No| D["Return Cached Result"]
    C -->|Yes| E["Evict Entry"]
    B -->|No| F["Evaluate Rules"]
    F --> G["Store in Cache"]
    G --> D
    E --> F

    subgraph Eviction["Eviction Policy"]
        H["Cache Full?"] -->|Yes| I["LRU Eviction"]
        I --> J["Remove Oldest Accessed Entry"]
        H -->|No| K["Add New Entry"]
        J --> K
    end

    G --> H
    K --> D
```

## Dispatch Strategy Selection

```mermaid
flowchart TD
    A["Dispatch Request"] --> B{"Strategy?"}
    B -->|"round_robin"| C["RR Index + 1 mod N"]
    B -->|"least_loaded"| D["min(load) over engines"]
    B -->|"random"| E["random.choice(available)"]
    B -->|"priority"| F["First available engine"]
    B -->|"weighted"| G["Weighted random selection"]
    B -->|"fastest_response"| H["min(average_time_ms)"]
    C --> I["Dispatch to Selected Engine"]
    D --> I
    E --> I
    F --> I
    G --> I
    H --> I
    I --> J{"Success?"}
    J -->|Yes| K["Record Metrics"]
    J -->|No| L{"Retries Left?"}
    L -->|Yes| M["Backoff + Retry"]
    M --> B
    L -->|No| N["Raise EngineUnavailableError"]
```
