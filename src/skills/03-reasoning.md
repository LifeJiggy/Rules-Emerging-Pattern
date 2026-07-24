# Skills Module — Reasoning

## Design Rationale

The Skills module is designed around a separation of concerns principle: loading, registration, validation, and execution are each handled by independent components. This document explains the reasoning behind key design decisions.

## 1. Why Separate Loader, Registry, Validator, and Executor?

```mermaid
flowchart LR
    subgraph Monolithic Approach
        M[One Class Does Everything]
        M --> P1[Hard to test]
        M --> P2[Single point of failure]
        M --> P3[Cannot swap implementations]
    end

    subgraph Modular Approach
        L[SkillLoader: source-aware]
        R[SkillRegistry: state-aware]
        V[SkillValidator: policy-aware]
        E[SkillExecutor: runtime-aware]
        L --> R --> V --> E
        L --> P4[Each component testable in isolation]
        L --> P5[Components can be versioned independently]
        L --> P6[Validation can be skipped in dev mode]
    end

    style Monolithic Approach fill:#f96
    style Modular Approach fill:#9f6
```

**Decision:** The modular approach was chosen because:

1. **Testability** — Each component can be mocked and tested independently.
2. **Flexibility** — The validator can be swapped for a stricter version, the loader can support new source types, and the executor can use different concurrency backends.
3. **Separation of concerns** — Loading knows about file formats, not execution. Validation knows about rules, not state.
4. **Future-proofing** — New execution modes or source types can be added without touching existing code.

## 2. Conflict Resolution Strategies

When a skill is registered that conflicts with an existing one (same name, different content hash), four strategies are available:

```mermaid
flowchart TB
    CONFLICT[Skill Name Conflict Detected] --> STRATEGY{Config: conflict_resolution}
    STRATEGY -->|error| ERR[raise RegistryConflictError]
    STRATEGY -->|skip| SKIP[return False, log warning]
    STRATEGY -->|replace| REPLACE[unregister old, register new]
    STRATEGY -->|merge| MERGE

    subgraph merge[Merge Strategy Details]
        M1[Keep old: name, status, created_at]
        M2[Override with new: handler, inputs, outputs]
        M3[Merge: tags, dependencies, triggers]
        M4[Highest wins: priority, version]
    end
```

**Decision rationale:**

- **error** — Default. Safe for production where conflicts should be investigated.
- **skip** — Useful in bulk-load scenarios where first registration wins.
- **replace** — Useful during development where the latest version should always be used.
- **merge** — Complex but useful when attributes are managed by different teams (e.g., handler changes by one team, metadata changes by another).

## 3. Execution Mode Selection

```mermaid
sequenceDiagram
    participant Client
    participant E as SkillExecutor

    Client->>E: execute_batch(skills, mode)
    E->>E: check mode parameter

    alt mode = SEQUENTIAL
        Note over E: Use when skills have implicit ordering<br/>or shared mutable state
        E->>E: for skill in skills: execute(skill)
    else mode = PARALLEL
        Note over E: Use when skills are independent<br/>and CPU/IO-bound
        E->>E: ThreadPoolExecutor(max_workers)
    else mode = PIPELINE
        Note over E: Use when each skill's output<br/>is the next skill's input
        E->>E: pipe output → next input
    else mode = FAN_OUT
        Note over E: Use when same base input<br/>must be processed by all skills
        E->>E: same inputs to each, collect all results
    else mode = FAN_IN
        Note over E: Use when multiple data sources<br/>need to be merged
        E->>E: run all, pass all outputs to aggregator
    else mode = CONDITIONAL
        Note over E: Use when skills have a _condition flag<br/>to determine whether they run
        E->>E: check _condition per skill
    end
```

**When to use each mode:**

| Mode | Best For | Example |
|---|---|---|
| SEQUENTIAL | Ordered processing | Preprocessing before ML inference |
| PARALLEL | Independent batch operations | Running multiple filters simultaneously |
| PIPELINE | Data transformation chains | Parse → Validate → Transform → Store |
| FAN_OUT | Broadcast processing | Sending same event to multiple handlers |
| FAN_IN | Aggregation | Merging data from multiple sources |
| CONDITIONAL | Decision-based execution | Run validation only if input is dirty |

## 4. Validation Severity Decision Tree

```mermaid
flowchart TB
    ISSUE[Validation Issue Found] --> CAT{Category}
    CAT --> SCHEMA[Schema]
    CAT --> SEC[Security]
    CAT --> COMPAT[Compatibility]
    CAT --> INPUT[Input/Output]
    CAT --> NAMING[Naming]
    CAT --> DEP[Dependency]
    CAT --> PERF[Performance]
    CAT --> DOC[Documentation]
    CAT --> BP[Best Practice]

    SCHEMA --> S_E{Missing required?}
    S_E -->|yes| ERROR[Severity: ERROR]
    S_E -->|no| WARN[Severity: WARNING]

    SEC --> SEC_E{Dangerous pattern?}
    SEC_E -->|eval/exec| ERROR
    SEC_E -->|dangerous module| WARN
    SEC_E -->|subprocess/os| WARN
    SEC_E -->|dynamic import| WARN

    COMPAT --> C_E{Version mismatch?}
    C_E -->|incompatible| ERROR
    C_E -->|minor mismatch| WARN

    INPUT --> I_E{Type mismatch?}
    I_E -->|required input missing| ERROR
    I_E -->|type_hint invalid| WARN
    I_E -->|validator fails| WARN

    NAMING --> N_E{Invalid name?}
    N_E -->|empty| ERROR
    N_E -->|invalid chars| WARN
    N_E -->|reserved word| WARN

    DEP --> D_E{Required dep missing?}
    D_E -->|required| ERROR
    D_E -->|optional| WARN

    PERF --> P_E{Config issue?}
    P_E -->|timeout too low| WARN
    P_E -->|retry infinite loop| WARN

    DOC --> Missing{Description empty?}
    Missing -->|yes| INFO[Severity: INFO]

    BP --> Style{Naming convention?}
    Style -->|no hints| INFO
```

**Why ERROR blocks execution:** A skill with ERROR-level issues cannot be safely executed. For example, missing a required handler means there is no code to run. Dangerous patterns like `eval()` could lead to remote code execution.

**Why WARNING does not block:** WARNING-level issues suggest problems but do not prevent execution. For example, using `subprocess` is a valid pattern in some contexts but should be flagged for review.

**Why INFO is advisory:** INFO-level issues (like missing documentation) are quality concerns, not safety concerns.

## 5. Retry Policy Design

```mermaid
flowchart TB
    EXEC[Execute Handler] --> OK{Success?}
    OK -->|yes| DONE[Done - Return Result]
    OK -->|no| RETRY{retry_policy set?}
    RETRY -->|no| FAIL[Return Failure]
    RETRY -->|yes| ATTEMPT[attempt = 1]

    subgraph Retry Loop
        ATTEMPT --> MAX{attempt <= max_retries?}
        MAX -->|no| FAIL
        MAX -->|yes| WAIT[Wait delay seconds]
        WAIT --> EXEC2[Retry Handler]
        EXEC2 --> OK2{Success?}
        OK2 -->|yes| DONE
        OK2 -->|no| NEXT[attempt += 1]
        NEXT --> BACKOFF[delay *= backoff]
        BACKOFF --> CAP{delay > max_delay?}
        CAP -->|yes| CLAMP[delay = max_delay]
        CLAMP --> MAX
        CAP -->|no| MAX
    end
```

**Why exponential backoff:** Fixed-interval retries can cause thundering herd problems when multiple skills fail simultaneously. Exponential backoff spreads retry attempts and reduces load on downstream dependencies.

**Why max_delay cap:** Without a cap, backoff can grow unreasonably large (e.g., 1s × 2^10 = 1024s ≈ 17 minutes).

**Default values rationale:**
- `max_retries: 3` — Most transient failures resolve within 3 attempts
- `delay: 1.0` — Initial 1-second pause is reasonable for most systems
- `backoff: 2.0` — Doubling is the standard exponential backoff multiplier
- `max_delay: 60.0` — Beyond 60 seconds, the skill likely has a fundamental issue

## 6. Middleware Chain Design

```mermaid
flowchart TB
    subgraph Why Middleware?
        WHY1[Cross-cutting concerns\nseparated from handler logic]
        WHY2[Reusable: logging, metrics,\nauth, rate limiting]
        WHY3[Composable: add/remove\nwithout changing handler]
        WHY4[Testable: each middleware\ncan be unit-tested]
    end

    subgraph Ordering
        DECORATE[Decorator Pattern]
        DECORATE --> FIRST[First registered = outer wrapper]
        DECORATE --> LAST[Last registered = inner wrapper]
    end

    subgraph Execution
        PRE[Pre-handler: input validation, logging, auth]
        HANDLER[Skill Handler]
        POST[Post-handler: output formatting, caching, metrics]
        PRE --> HANDLER --> POST
    end
```

**Decision:** Middleware follows the onion/decorator pattern because:

1. It matches the natural request-response lifecycle — set up before handler, tear down after.
2. Middleware can wrap the handler, catching exceptions and adding fallback behavior.
3. The order of middleware registration matters predictably: first registered middleware executes first in the pre-phase and last in the post-phase.

## 7. Caching Strategy

```mermaid
flowchart TB
    CACHE_CONFIG{caching_policy?}

    CACHE_CONFIG -->|None| NO[No Caching]
    CACHE_CONFIG -->|dict| TTL{TTL defined?}
    TTL -->|yes| EXPIRE[Expire results after TTL seconds]
    TTL -->|no| FOREVER[Cache permanently until evicted]

    NO --> EXEC[Always Execute]
    EXPIRE --> CHECK{Result cached?}
    FOREVER --> CHECK

    CHECK -->|hit, valid| RETURN[Return cached]
    CHECK -->|miss or expired| EXECUTE[Execute, Cache, Return]

    EXECUTE --> STORE{Store result}
    STORE --> MEM[In-memory dict\nkeyed by execution_id]
```

**Why in-memory cache:** The cache is per-executor-instance. A distributed cache (Redis, Memcached) would add deployment complexity and is better suited for higher-level orchestration layers.

**Why per-skill TTL:** Different skills have different staleness tolerances. A "get current time" skill can cache indefinitely, while a "get stock price" skill needs seconds-level TTL.

## 8. Namespace Design

```mermaid
flowchart TB
    subgraph Why Namespaces?
        REASON1[Isolation: data.transform\nvs app.transform are different]
        REASON2[Organization: mirror\nproject directory structure]
        REASON3[Permissions: role admin\ncan manage app namespace only]
        REASON4[Versioning: v1.parse\nvs v2.parse can coexist]
    end

    subgraph Dot Notation
        NS1["data.transform.parse"]
        NS2["data.transform.validate"]
        NS3["data.store"]
        NS4["app.user.login"]
        NS5["app.user.register"]
    end

    subgraph Implementation
        REG[SkillRegistry]
        REG --> DICT{_namespaces dict}
        DICT --> N1["data.transform" → List[Skill]]
        DICT --> N2["data" → List[Skill]]
        DICT --> N3["app.user" → List[Skill]]
        DICT --> N4[default namespace]
    end
```

**Decision rationale:**

Dot-separated namespaces were chosen over nested objects because:
1. **Flat lookup** — `_namespaces[dot_string]` is O(1) dict access
2. **Prefix matching** — `query(namespace="data")` returns all skills under `data.*` by iterating keys and matching prefix
3. **Serialization** — Easy to serialize as a flat dictionary

## 9. Content Hash for Conflict Detection

```mermaid
sequenceDiagram
    participant Loader as SkillLoader
    participant Registry as SkillRegistry

    Loader->>Registry: register(skill)
    Registry->>Registry: compute incoming_hash = hash(skill.to_dict())
    Registry->>Registry: lookup existing = _skills.get(skill.name)
    alt No existing
        Registry->>Registry: store skill with incoming_hash
    else Existing
        Registry->>Registry: compare incoming_hash vs stored_hash
        alt Hashes match
            Registry->>Registry: skip - identical skill
        else Hashes differ
            Registry->>Registry: apply conflict_resolution strategy
        end
    end
```

**Why content hash instead of version comparison:**

Versions can be misleading — the same version number may refer to different content after a rebase or fix. Content hashing (using Python's `hashlib.sha256` over the serialized dict) guarantees deterministic conflict detection.

## 10. Event System Design

```mermaid
flowchart LR
    subgraph Producer
        REG[SkillRegistry]
    end

    subgraph Events
        E1[SKILL_REGISTERED]
        E2[SKILL_UNREGISTERED]
        E3[SKILL_ACTIVATED]
        E4[SKILL_DEACTIVATED]
        E5[SKILL_UPDATED]
        E6[BEFORE_EXECUTION]
        E7[AFTER_EXECUTION]
        E8[ERROR]
    end

    subgraph Consumers
        C1[Logger: log all events]
        C2[Metrics Collector: track counts]
        C3[Cache Invalidator: on UPDATE]
        C4[Dependency Resolver: on UNREGISTER]
        C5[Alert Manager: on ERROR]
    end

    REG --> E1
    REG --> E2
    REG --> E3
    REG --> E4
    REG --> E5
    REG --> E6
    REG --> E7
    REG --> E8

    E1 --> C1
    E2 --> C1
    E2 --> C4
    E3 --> C2
    E4 --> C2
    E5 --> C3
    E6 --> C2
    E7 --> C2
    E8 --> C5
```

**Decision:** The event system uses a simple publish-subscribe pattern rather than a message queue because:
1. All consumers run in-process — no serialization or network overhead required
2. Events are non-blocking — listeners run in a separate thread or are scheduled for later execution
3. Complexity is minimized — no broker, no topic hierarchy, no partitioning

## 11. Thread Safety Design

```mermaid
flowchart TB
    subgraph SkillRegistry
        LOCK[threading.Lock]
        SKILLS[_skills dict]
        NS[_namespaces dict]
        QUERY{Query}
        WRITE{Write}
        QUERY -->|read lock| LOCK
        WRITE -->|write lock| LOCK
        LOCK --> DATA[(Protected Data)]
    end

    subgraph SkillExecutor
        POOL[ThreadPoolExecutor]
        WORKER1[Worker 1: Skill A]
        WORKER2[Worker 2: Skill B]
        WORKER3[Worker 3: Skill C]
        POOL --> WORKER1
        POOL --> WORKER2
        POOL --> WORKER3
    end

    subgraph SkillLoader
        SEQ[Sequential - No locks needed]
    end

    subgraph SkillValidator
        STATELESS[Stateless - No locks needed]
    end
```

**Why a single lock on the registry:** The registry is read-heavy (many more query() calls than register() calls). Python's `threading.Lock` is sufficient because:
- Dict operations are fast (O(1))
- The lock is held only during the actual mutation, not during validation
- `threading.RLock` would add overhead without benefit since the registry methods are not recursive

**Why ThreadPoolExecutor for parallel execution:** Python's `concurrent.futures.ThreadPoolExecutor` is the standard library for thread-based parallelism. The GIL makes CPU-bound tasks slower in threads, but skill execution is typically I/O-bound (API calls, database queries, file reads), so threading is appropriate.

## 12. Skill Versioning Strategy

```mermaid
flowchart LR
    V[SkillVersion] --> SEMVER[Semantic Versioning: major.minor.patch]
    SEMVER --> COMPAT{compat(other, strategy)}
    COMPAT -->|strict| major_eq["major == other.major"]
    COMPAT -->|minor| major_gte["major >= other.major AND minor >= other.minor"]
    COMPAT -->|flexible| major_ge["major >= other.major"]
    COMPAT -->|any| always["always True"]

    subgraph Version Bump Rules
        MAJOR[breaking changes → increment major]
        MINOR[new features, backward compat → increment minor]
        PATCH[bug fixes → increment patch]
    end
```

**Why semantic versioning:** Semantic versioning gives consumers clear signals about compatibility. A skill with `major=2` is expected to break consumers of `major=1`. The `compat()` method encodes four strategies that skills can declare in their dependencies.

## 13. Config Validation on Startup

```mermaid
flowchart TB
    STARTUP[SkillExecutor.__init__] --> CHECK{Validate config}
    CHECK --> MAX_W[max_workers must be >= 1]
    CHECK --> TIMEOUT[default_timeout must be > 0]
    CHECK --> RETRY[max_retries must be >= 0]
    CHECK --> DELAY[delay must be >= 0]
    CHECK --> BACKOFF[backoff must be >= 1.0]
    CHECK --> MAX_D[max_delay must be > 0]

    MAX_W -->|fails| CLAMP1[clamp to max(1, max_workers)]
    TIMEOUT -->|fails| CLAMP2[clamp to default 30.0]
    RETRY -->|fails| CLAMP3[clamp to 0]
    DELAY -->|fails| CLAMP4[clamp to 0.1]
    BACKOFF -->|fails| CLAMP5[clamp to 1.0]
    MAX_D -->|fails| CLAMP6[clamp to max_delay + 1.0]
```

**Why clamp instead of raise:** Configuration errors should not crash the system. Clamping to sensible defaults is more resilient. The original values are kept in the raw config; warnings are logged for audit purposes.

## 14. Hot-Reload Tradeoffs

```mermaid
flowchart LR
    subgraph Benefits
        B1[No restart needed\nfor skill changes]
        B2[Fast iteration\nduring development]
        B3[Auto-rollback\non validation failure]
    end

    subgraph Costs
        C1[Polling overhead\nevery N seconds]
        C2[Mutable state\nif skills hold references]
        C3[No atomic swap\nbrief window with stale state]
    end

    subgraph Best Practices
        BP1[Use in dev only;\navoid in prod]
        BP2[Stateless skills only]
        BP3[Versioned configs;\nold version kept]
    end
```

**Decision:** Hot-reload is optional and disabled by default. It is intended for development environments where rapid iteration is valuable and the risks of mutable state are acceptable.
