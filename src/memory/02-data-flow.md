# Memory Module Data Flow

## Cache Lookup Flow

The RuleCache implements a standard cache lookup pattern: check cache → hit/miss → return or fallback to persistent storage.

```mermaid
sequenceDiagram
    participant Client
    participant RC as RuleCache
    participant Store as Persistent Store

    Client->>RC: get("rule_001")
    activate RC

    RC->>RC: hash lookup in entries
    alt Entry exists
        RC->>RC: check TTL expiration
        alt TTL valid
            RC->>RC: update LRU position
            RC->>RC: increment access_count
            RC-->>Client: cached value
        else TTL expired
            RC->>RC: remove expired entry
            RC->>Store: fetch from persistent store
            activate Store
            Store-->>RC: stored rule
            deactivate Store
            RC->>RC: cache with new TTL
            RC-->>Client: fresh value
        end
    else Entry not found
        RC->>Store: fetch from persistent store
        activate Store
        Store-->>RC: stored rule
        deactivate Store
        RC->>RC: cache with default TTL
        RC-->>Client: fresh value
    end

    deactivate RC
```

## Cache Miss → Fallback → Store Flow

When a cache miss occurs, the system falls back to the ResultStore, and then re-caches the result.

```mermaid
sequenceDiagram
    participant Client
    participant RC as RuleCache
    participant RS as ResultStore
    participant LTM as LongTermMemory

    Client->>RC: get("pattern:anomaly_001")
    activate RC
    RC-->>Client: None (miss)
    deactivate RC

    Client->>RS: retrieve("patterns", "anomaly_001")
    activate RS
    RS-->>Client: StoredResult
    deactivate RS

    Client->>RC: set("pattern:anomaly_001", value, ttl=3600)
    activate RC
    RC->>RC: check capacity
    alt Over capacity
        RC->>RC: evict LRU entry
    end
    RC->>RC: store with timestamp
    RC-->>Client: stored
    deactivate RC

    opt Persistence needed
        Client->>LTM: add_fact("anomaly_001", "is_pattern", ...)
        activate LTM
        LTM-->>Client: Fact
        deactivate LTM
    end
```

## Context Memory Data Flow

The ContextMemory tracks execution context across the system.

```mermaid
sequenceDiagram
    participant Module as Any Module
    participant CM as ContextMemory
    participant Log as Event Log

    Module->>CM: set("current_action", "analyze_patterns")
    activate CM
    CM->>CM: store in context_variables
    deactivate CM

    Module->>CM: push_event("session_run_001", event)
    activate CM
    CM->>Log: append to event_log["session_run_001"]
    deactivate CM

    Module->>CM: get("current_action")
    activate CM
    CM-->>Module: "analyze_patterns"
    deactivate CM

    Module->>CM: get_event_log("session_run_001")
    activate CM
    CM->>Log: retrieve by context_id
    Log-->>CM: List[ContextEvent]
    CM-->>Module: List[ContextEvent]
    deactivate CM
```

## PatternCache Score-Based Retrieval

The PatternCache maintains a score-ordered queue for efficient top-N retrieval.

```mermaid
sequenceDiagram
    participant Learning as Learning Module
    participant PC as PatternCache
    participant Queue as Score Queue

    Learning->>PC: set("pattern_001", data, score=0.85)
    activate PC
    PC->>PC: store in patterns dict
    PC->>Queue: push (-0.85, "pattern_001")
    deactivate PC

    Learning->>PC: set("pattern_002", data, score=0.92)
    activate PC
    PC->>Queue: push (-0.92, "pattern_002")
    deactivate PC

    Learning->>PC: get_top(5)
    activate PC
    PC->>Queue: peek top 5 (lowest neg = highest score)
    Queue-->>PC: [(-0.92, "p002"), (-0.85, "p001"), ...]
    PC->>PC: fetch full pattern objects
    PC-->>Learning: List[CachedPattern]
    deactivate PC
```

## SessionState Lifecycle

Sessions are created, used, and automatically cleaned up.

```mermaid
sequenceDiagram
    participant App as Application
    participant SS as SessionState
    participant Timer as Cleanup Timer

    App->>SS: create_session("sess_001")
    activate SS
    SS->>SS: store with current timestamp
    SS-->>App: Session object
    deactivate SS

    App->>SS: set_attribute("sess_001", "user", "admin")
    activate SS
    SS->>SS: store attribute
    deactivate SS

    App->>SS: get_attribute("sess_001", "user")
    activate SS
    SS-->>App: "admin"
    deactivate SS

    App->>SS: end_session("sess_001")
    activate SS
    SS->>SS: remove all session data
    SS-->>App: success
    deactivate SS

    Note over SS,Timer: Automatic cleanup
    Timer->>SS: cleanup_expired()
    activate SS
    SS->>SS: iterate sessions
    SS->>SS: remove sessions inactive > timeout
    SS-->>Timer: count removed
    deactivate SS
```

## ResultStore Namespaced Storage

Results are stored and retrieved by namespace and key.

```mermaid
sequenceDiagram
    participant Module as Module
    participant RS as ResultStore

    Module->>RS: store("models", "v1", {"acc": 0.94}, {"version": "1.0"})
    activate RS
    RS->>RS: check namespace exists
    alt Namespace missing
        RS->>RS: create "models" namespace
    end
    RS->>RS: store result with timestamp
    RS-->>Module: StoredResult
    deactivate RS

    Module->>RS: retrieve("models", "v1")
    activate RS
    RS->>RS: lookup by namespace + key
    RS-->>Module: StoredResult
    deactivate RS

    Module->>RS: query("models", {"version": "1.0"})
    activate RS
    RS->>RS: filter stored results
    RS-->>Module: List[StoredResult]
    deactivate RS
```

## Cognitive Memory Data Flows

### STM Store & Eviction

```mermaid
sequenceDiagram
    participant Client
    participant STM as ShortTermMemory
    participant Decay as Priority Decay Engine

    Client->>STM: store(key, value, type, priority, ttl)
    activate STM
    STM->>STM: evict_expired()
    STM->>STM: create STMEntry
    STM->>STM: add to priority_queue if priority > 0

    alt entries > max_capacity
        STM->>STM: evict_low_priority()
        STM->>STM: or evict LRU
    end

    STM-->>Client: STMEntry
    deactivate STM

    Client->>STM: retrieve(key)
    activate STM
    STM->>STM: find by key
    STM->>STM: check TTL
    alt Expired
        STM-->>Client: None
    else Valid
        STM->>STM: refresh last_accessed
        STM->>STM: increment access_count
        STM-->>Client: value
    end
    deactivate STM
```

### LTM Fact Query Flow

```mermaid
sequenceDiagram
    participant Client
    participant LTM as LongTermMemory
    participant Index as Fact Index
    participant EntityStore as Entity Store

    Client->>LTM: query_facts(subject="server-01", predicate="hosts")
    activate LTM
    LTM->>Index: lookup by subject + predicate
    activate Index
    Index-->>LTM: fact_id list
    deactivate Index
    LTM->>LTM: filter by active status & validity window
    LTM-->>Client: List[Fact]
    deactivate LTM

    Client->>LTM: get_entity_by_name("api-gateway")
    activate LTM
    LTM->>EntityStore: search by name + aliases
    activate EntityStore
    EntityStore-->>LTM: matching entity
    deactivate EntityStore
    LTM-->>Client: Entity
    deactivate LTM

    Client->>LTM: get_related_entities("E002", "depends_on")
    activate LTM
    LTM->>EntityStore: filter relationships by type
    activate EntityStore
    EntityStore-->>LTM: target entity IDs
    deactivate EntityStore
    LTM->>EntityStore: fetch each entity
    EntityStore-->>LTM: List[Entity]
    deactivate EntityStore
    LTM-->>Client: List[Entity]
    deactivate LTM
```

### PAM Procedure Execution Flow

```mermaid
sequenceDiagram
    participant Caller
    participant PAM as ProceduralActionMemory
    participant Executor as Procedure Executor
    participant StepEngine as Step Engine
    participant RL as Rule Lookup

    Caller->>PAM: execute_procedure(procedure_id, context)
    activate PAM
    PAM->>PAM: Lookup procedure
    PAM->>PAM: Fetch procedure steps
    PAM->>Executor: begin execution
    activate Executor

    loop for each step in order
        Executor->>StepEngine: execute step
        activate StepEngine
        StepEngine->>RL: get_rule(step.rule_id)
        activate RL
        RL-->>StepEngine: Rule object
        deactivate RL
        StepEngine->>StepEngine: evaluate preconditions
        alt Preconditions met
            StepEngine->>StepEngine: execute rule actions
            StepEngine->>StepEngine: verify postconditions
            StepEngine-->>Executor: success result
        else Preconditions not met
            alt step is optional
                StepEngine-->>Executor: skip
            else step is required
                StepEngine-->>Executor: failure
                Executor-->>PAM: procedure failed at step N
                PAM-->>Caller: partial result with error
            end
        end
        deactivate StepEngine
    end
    Executor-->>PAM: aggregated result
    deactivate Executor
    PAM-->>Caller: success result
    deactivate PAM
```

### IM Evidence Flow

```mermaid
sequenceDiagram
    participant Source as Evidence Source
    participant IM as InferenceMemory
    participant Engine as Inference Engine
    participant Propagator as Confidence Propagator

    Source->>IM: add_evidence(inference_id, source, value, weight, supports)
    activate IM
    IM->>IM: store evidence in evidence_chains
    IM->>Engine: trigger confidence re-evaluation
    deactivate IM

    activate Engine
    Engine->>IM: get evidence chain for inference
    IM-->>Engine: List[Evidence]
    Engine->>Propagator: propagate_confidence(inference_id)
    activate Propagator
    Propagator->>Propagator: calculate weighted average
    Propagator->>Propagator: apply propagation factor
    Propagator->>Propagator: adjust for supporting vs contradicting
    Propagator-->>Engine: new confidence value
    Engine->>IM: update inference confidence
    alt new confidence > threshold
        Engine->>IM: set status = Active
    else
        Engine->>IM: set status = Pending
    end
    deactivate Propagator
    deactivate Engine
```

### REM Recall Pipeline

```mermaid
sequenceDiagram
    participant Source as Experience Source
    participant REM as RemembranceMemory
    participant Encoder as Context Encoder
    participant Index as Similarity Index
    participant AnalogyEngine as Analogy Engine

    Source->>REM: store_experience(type, context, actions, outcome)
    activate REM
    REM->>Encoder: generate context embedding
    activate Encoder
    Encoder-->>REM: np.ndarray embedding
    deactivate Encoder
    REM->>REM: compute salience score
    REM->>REM: store Experience + embedding
    REM-->>Source: Experience
    deactivate REM

    Source->>REM: recall(query_context, limit=5)
    activate REM
    REM->>Encoder: encode query context
    activate Encoder
    Encoder-->>REM: query_vector
    deactivate Encoder
    REM->>Index: cosine similarity search
    activate Index
    Index-->>REM: top_k experience_ids + scores
    deactivate Index
    REM->>REM: fetch full Experience objects
    REM->>AnalogyEngine: find analogies for top results
    activate AnalogyEngine
    AnalogyEngine-->>REM: List[AnalogyMapping]
    deactivate AnalogyEngine
    REM-->>Source: List[Experience] + List[AnalogyMapping]
    deactivate REM
```

### MM Performance Monitoring Flow

```mermaid
sequenceDiagram
    participant Task as Task Executor
    participant MM as MetaCognitiveMemory
    participant Analyzer as Performance Analyzer
    participant Advisor as Improvement Advisor

    Task->>MM: record_performance(task_type, task_id, accuracy, latency, confidence, success)
    activate MM
    MM->>MM: store PerformanceRecord
    MM->>Analyzer: trigger analysis
    deactivate MM

    activate Analyzer
    Analyzer->>MM: get_performance_summary(task_type)
    MM-->>Analyzer: aggregated stats
    Analyzer->>Analyzer: compute rolling average
    Analyzer->>Analyzer: compare to historical baseline
    Analyzer->>Analyzer: detect trend

    alt Degradation detected
        Analyzer->>Advisor: request improvement suggestions
        activate Advisor
        Advisor->>MM: get_best_strategy(task_type)
        MM-->>Advisor: strategy_id
        Advisor->>Advisor: formulate recommendation
        Advisor-->>Analyzer: List[str] suggestions
        deactivate Advisor
        Analyzer-->>MM: degradation alert with suggestions
    else Stable or Improving
        Analyzer-->>MM: status ok
    end
    deactivate Analyzer
```

## Cross-Memory Migration Flow

Data can be promoted between memory tiers (STM → LTM → PAM).

```mermaid
flowchart LR
    subgraph STM["Short-Term Memory"]
        A[Ephemeral entries<br/>with TTL]
    end

    subgraph Promotion["Promotion Pipeline"]
        B[Frequency filter: access_count > threshold]
        C[Importance filter: priority > threshold]
        D[Confidence filter: confidence > threshold]
        E[Entity extraction: extract entities from entries]
        F[Relationship inference: infer from co-occurrence]
    end

    subgraph LTM["Long-Term Memory"]
        G[Persistent facts]
        H[Entities with attributes]
        I[Relationships]
    end

    subgraph PAM["Procedural-Action Memory"]
        J[Rules extracted from frequent patterns]
        K[Procedures from action sequences]
    end

    A --> B
    B --> C
    C --> D
    D --> E
    D --> F
    E --> G
    E --> H
    F --> I
    D --> J
    D --> K
```