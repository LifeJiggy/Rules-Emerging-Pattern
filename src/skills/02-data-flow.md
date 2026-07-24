# Skills Module — Data Flow

## Overview

This document describes the data flow through the Skills module lifecycle. Data moves through four primary phases: Loading, Registration, Validation, and Execution. Each phase transforms the `RuleSkill` domain object through well-defined pipelines.

## 1. Full Lifecycle Flow

```mermaid
sequenceDiagram
    participant Client
    participant Loader as SkillLoader
    participant Registry as SkillRegistry
    participant Validator as SkillValidator
    participant Executor as SkillExecutor
    participant Handler as Skill Handler

    Client->>Loader: load("path/to/skills.yaml", SourceType.DIRECTORY)
    Loader->>Loader: parse YAML → dict
    Loader->>Loader: create RuleSkill objects
    Loader-->>Client: [RuleSkill, RuleSkill, ...]

    Client->>Registry: register(skill_a, namespace="data")
    Registry->>Registry: check conflict (name hash)
    Registry->>Registry: index by tags, categories, groups
    Registry-->>Client: True

    Client->>Validator: validate(skill_a, full=True)
    Validator->>Validator: run 10 validation categories
    Validator-->>Client: ValidationResult(issues=3, passed=True)

    Client->>Registry: activate(skill_a)
    Registry-->>Client: True

    Client->>Executor: execute(skill_a, {"text": "hello"})
    Executor->>Executor: check caching_policy
    Executor->>Executor: create ExecutionContext
    Executor->>Handler: execute(context)
    Handler-->>Executor: {"result": "HELLO"}
    Executor->>Executor: record metrics (time, status)
    Executor-->>Client: ExecutionResult(status=SUCCESS, output={"result": "HELLO"})
```

## 2. Skill Loader Data Flow

The loader processes multiple source types. The core flow is: discover → read → parse → validate → return.

```mermaid
flowchart TB
    subgraph Input
        SRC[Source Path or String]
        ST[SourceType: DIRECTORY | PACKAGE | STRING]
    end

    subgraph Discovery
        DISCOVER[Discover Sources]
        FILTER[Filter by pattern]
        READ[Read raw content]
    end

    subgraph Parsing
        DETECT{Format?}
        DETECT -->|.yaml/.yml| YAML[parse with yaml.safe_load]
        DETECT -->|.json| JSON[parse with json.loads]
        DETECT -->|.py| PY[importlib.import_module]
        DETECT -->|.md| MD[extract YAML frontmatter]
        DETECT -->|unknown| SKIP
    end

    subgraph Construction
        BUILD[Build RuleSkill dict]
        MAKE[from_dict → RuleSkill]
        HASH[Generate skill_id]
    end

    subgraph Output
        RETURN[List[RuleSkill]]
        CACHE[Update cache]
    end

    SRC --> DISCOVER
    ST --> DISCOVER
    DISCOVER --> FILTER
    FILTER --> READ
    READ --> DETECT
    YAML --> BUILD
    JSON --> BUILD
    PY --> BUILD
    MD --> BUILD
    BUILD --> MAKE
    MAKE --> HASH
    HASH --> RETURN
    HASH --> CACHE
```

### Source Type Details

```mermaid
flowchart LR
    subgraph DIRECTORY
        D1[scan dir]
        D2[match *.yaml, *.json, *.py, *.md]
        D3[recursive subdirs if config.recursive]
        D1 --> D2 --> D3
    end

    subgraph PACKAGE
        P1[importlib.resources.files]
        P2[list contents]
        P3[filter by extension]
        P1 --> P2 --> P3
    end

    subgraph STRING
        S1[Content string]
        S2[Detect format: yaml/json]
        S3[Parse in-memory]
        S1 --> S2 --> S3
    end
```

## 3. Skill Registry Data Flow

### Registration Flow

When a skill is registered, the following pipeline executes:

```mermaid
sequenceDiagram
    participant Caller
    participant R as SkillRegistry
    participant Indexes as Indexes dict
    participant Namespaces as _namespaces dict

    Caller->>R: register(skill, namespace="data")
    R->>R: validate skill object
    R->>R: check namespace exists, create if missing
    R->>R: check conflict (name + content_hash)
    alt Conflict exists
        R->>R: apply conflict_resolution strategy
        alt resolution = "error"
            R-->>Caller: raise RegistryConflictError
        else resolution = "skip"
            R-->>Caller: False
        else resolution = "replace"
            R->>R: unregister old skill
        else resolution = "merge"
            R->>R: merge attributes
        end
    end
    R->>R: store in _skills[name] = skill
    R->>R: store in _namespaces[namespace][name] = skill
    R->>R: index by tags (multi-map)
    R->>R: index by category (multi-map)
    R->>R: index by aliases (multi-map)
    R->>R: index by groups (multi-map)
    R->>R: emit RegistryEvent.SKILL_REGISTERED
    R-->>Caller: True
```

### Query Flow

```mermaid
flowchart TB
    Q[query()] --> FILTERS{Apply Filters}
    FILTERS --> CAT{category?}
    FILTERS --> TAG{tags?}
    FILTERS --> STS{status?}
    FILTERS --> NS{namespace?}
    FILTERS --> ALIAS{alias?}
    FILTERS --> GRP{group?}
    FILTERS --> ACT{is_active?}

    CAT -->|yes| by_cat[filter by SkillCategory]
    TAG -->|yes| by_tag[filter intersection of tags]
    STS -->|yes| by_sts[filter by SkillStatus]
    NS -->|yes| by_ns[filter by namespace prefix]
    ALIAS -->|yes| by_alias[filter by alias match]
    GRP -->|yes| by_grp[filter by group match]
    ACT -->|yes| by_act[filter is_active=True]

    by_cat --> COMBINE[combine with AND logic]
    by_tag --> COMBINE
    by_sts --> COMBINE
    by_ns --> COMBINE
    by_alias --> COMBINE
    by_grp --> COMBINE
    by_act --> COMBINE

    COMBINE --> SORT{sort_by?}
    SORT -->|name| sort_name[sort by name]
    SORT -->|priority| sort_pri[sort by priority desc]
    SORT -->|version| sort_ver[sort by version]
    SORT -->|none| no_sort[keep order]
    sort_name --> LIMIT{limit?}
    sort_pri --> LIMIT
    sort_ver --> LIMIT
    no_sort --> LIMIT
    LIMIT -->|n| truncated[first n results]
    LIMIT -->|None| all[all matches]
    truncated --> RETURN[List[RuleSkill]]
    all --> RETURN
```

### Snapshot/Restore Flow

```mermaid
sequenceDiagram
    participant Caller
    participant R as SkillRegistry

    Caller->>R: snapshot()
    R->>R: serialize all _skills to dict
    R->>R: serialize namespaces structure
    R->>R: wrap in RegistrySnapshot
    R-->>Caller: RegistrySnapshot
    Note over R: snapshot.skills = {name: skill.to_dict()}
    Note over R: snapshot.namespaces = {ns: [names]}

    Caller->>R: restore_snapshot(snapshot)
    R->>R: clear current state
    R->>R: for each name, dict in snapshot.skills
    R->>R: RuleSkill.from_dict(dict)
    R->>R: register rebuilt skill
    R->>R: restore namespace structure
    R-->>Caller: True
```

## 4. Skill Validation Data Flow

```mermaid
sequenceDiagram
    participant Caller
    participant V as SkillValidator

    Caller->>V: validate(skill, full=True)
    V->>V: check _schema (has required fields: name, handler, etc.)
    V->>V: check _naming (name regex: ^[a-zA-Z][a-zA-Z0-9_]*$)
    V->>V: check _signature (handler is callable, accepts context)
    V->>V: check _inputs (valid type_hints, defaults match types)
    V->>V: check _dependencies (referenced skills exist)
    alt full=True
        V->>V: check _compatibility (version vs registry)
        V->>V: check _security (AST analysis of handler code)
        V->>V: check _performance (config thresholds)
        V->>V: check _documentation (description populated)
        V->>V: check _best_practices (naming, structure)
    end
    V->>V: aggregate all ValidationIssue
    V->>V: compute passed (no ERROR issues)
    V->>V: cache result if config.cache_results
    V-->>Caller: ValidationResult(issues=List, passed=bool)
```

### Validation Issue Severity Levels

```mermaid
flowchart LR
    E[ERROR] -->|blocking| FAIL[Skill Fails]
    W[WARNING] -->|advisory| PASS[Skill Passes]
    I[INFO] -->|informational| PASS2[Skill Passes]

    style E fill:#f96
    style W fill:#ff9
    style I fill:#9f6
```

### Security Validation Flow

```mermaid
flowchart TB
    SEC[Security Check] --> AST[ast.parse handler source]
    AST --> NODE{Node type}
    NODE -->|Call| CALL[Check function call]
    NODE -->|Import| IMP[Check imported module]
    NODE -->|Attribute| ATTR[Check attribute access]
    CALL --> eval{is eval/exec?}
    eval -->|yes| WARN1[Warning: dangerous eval]
    IMP --> os{is os module?}
    os -->|yes| WARN2[Warning: os operations]
    IMP --> sub{is subprocess?}
    sub -->|yes| WARN3[Warning: subprocess]
    ATTR --> wire{is __import__?}
    wire -->|yes| WARN4[Warning: dynamic import]
```

## 5. Skill Execution Data Flow

### Single Skill Execution

```mermaid
sequenceDiagram
    participant Caller
    participant E as SkillExecutor
    participant Ctx as ExecutionContext
    participant Handler as RuleSkill.handler

    Caller->>E: execute(skill, inputs)
    E->>E: validate skill.can_execute()
    E->>E: check cache (if enabled)
    alt Cache hit
        E-->>Caller: cached ExecutionResult
    end
    E->>E: create ExecutionContext
    E->>Ctx: __enter__ → start timing
    E->>E: prepare inputs (merge with defaults)
    E->>E: apply middleware chain (pre)
    E->>Handler: execute(context)
    Handler-->>E: output dict
    E->>E: apply middleware chain (post)
    E->>Ctx: __exit__ → record timing
    E->>E: compute status (SUCCESS/FAILURE)
    E->>E: update metrics
    E->>E: cache result (if enabled)
    E-->>Caller: ExecutionResult(status=SUCCESS, output=..., time=..., execution_id=...)
```

### Batch Execution Modes

#### Sequential Mode

```mermaid
sequenceDiagram
    participant E as SkillExecutor
    participant S1 as Skill A
    participant S2 as Skill B
    participant S3 as Skill C

    E->>S1: execute(context)
    S1-->>E: result A
    E->>S2: execute(context)
    S2-->>E: result B
    E->>S3: execute(context)
    S3-->>E: result C
    E->>E: collect all results
    E-->>Client: List[ExecutionResult]
```

#### Parallel Mode

```mermaid
sequenceDiagram
    participant E as SkillExecutor
    participant Pool as ThreadPoolExecutor
    participant S1 as Skill A
    participant S2 as Skill B
    participant S3 as Skill C

    E->>Pool: submit(skills, max_workers=4)
    par A execution
        Pool->>S1: execute()
        S1-->>Pool: result A
    and B execution
        Pool->>S2: execute()
        S2-->>Pool: result B
    and C execution
        Pool->>S3: execute()
        S3-->>Pool: result C
    end
    Pool->>Pool: concurrent.futures.as_completed()
    Pool-->>E: List[ExecutionResult] (unordered)
```

#### Pipeline Mode

In pipeline mode, the output of each skill is passed as input to the next skill in the chain.

```mermaid
sequenceDiagram
    participant E as SkillExecutor
    participant S1 as Skill: Parse
    participant S2 as Skill: Validate
    participant S3 as Skill: Transform
    participant S4 as Skill: Store

    E->>S1: execute({raw: "data"})
    S1-->>E: {parsed: {...}}
    E->>S2: execute({parsed: {...}})
    S2-->>E: {validated: {...}}
    E->>S3: execute({validated: {...}})
    S3-->>E: {transformed: {...}}
    E->>S4: execute({transformed: {...}})
    S4-->>E: {stored: True}
    E-->>Client: List[ExecutionResult]
```

#### Fan-Out Mode

```mermaid
flowchart TB
    INPUT[Base Input] --> S1[Skill A]
    INPUT --> S2[Skill B]
    INPUT --> S3[Skill C]
    S1 --> COLLECT{Collect All Results}
    S2 --> COLLECT
    S3 --> COLLECT
    COLLECT --> OUTPUT[List[ExecutionResult]]
```

#### Fan-In Mode

```mermaid
flowchart TB
    INPUT1[Data Source 1] --> S1[Skill A: analyze]
    INPUT2[Data Source 2] --> S2[Skill B: analyze]
    INPUT3[Data Source 3] --> S3[Skill C: analyze]
    S1 --> AGG[Skill: Aggregator]
    S2 --> AGG
    S3 --> AGG
    AGG --> RESULT[Merged Result]
```

#### Conditional Mode

```mermaid
flowchart TB
    SKILL[Skill with _condition flag] --> CHECK{_condition True?}
    CHECK -->|yes| EXEC[Execute Handler]
    CHECK -->|no| SKIP[Skip, record as SKIPPED]
    EXEC --> RESULT[ExecutionResult.SUCCESS]
    SKIP --> SKIP_RESULT[ExecutionResult.SKIPPED]
```

## 6. Event Flow

The registry emits events during key lifecycle transitions. Listeners registered via `on()` receive event notifications.

```mermaid
flowchart LR
    REG[SkillRegistry] --> EMIT{Event}
    EMIT -->|SKILL_REGISTERED| LR1[Listener: Log Registration]
    EMIT -->|SKILL_UNREGISTERED| LR2[Listener: Cleanup Dependencies]
    EMIT -->|SKILL_ACTIVATED| LR3[Listener: Notify Executor]
    EMIT -->|SKILL_DEACTIVATED| LR4[Listener: Remove from Active Pool]
    EMIT -->|SKILL_UPDATED| LR5[Listener: Invalidate Cache]
    EMIT -->|ERROR| LR6[Listener: Alert Admin]
```

## 7. Metrics Collection Flow

```mermaid
sequenceDiagram
    participant Caller
    participant E as SkillExecutor

    loop per execute()
        E->>E: record start_time
        E->>E: execute handler
        E->>E: record end_time
        E->>E: compute elapsed = end_time - start_time
        E->>E: update total_time += elapsed
        E->>E: append to execution_times
        E->>E: increment counter (success/fail)
        E->>E: update top_slowest heap
    end

    Caller->>E: success_rate(timeframe=3600)
    E->>E: filter execution_times within timeframe
    E->>E: compute success_rate = successes / total
    E-->>Caller: float

    Caller->>E: top_slowest(n=5)
    E->>E: sort reversed execution_times
    E->>E: take first n
    E-->>Caller: List[Dict{skill_name, elapsed, timestamp}]
```

## 8. Error Handling Flow

```mermaid
sequenceDiagram
    participant E as SkillExecutor
    participant Handler as RuleSkill.handler

    E->>Handler: execute(context)
    Handler-->>E: raises Exception

    E->>E: determine error_strategy

    alt error_strategy = STOP_IMMEDIATELY
        E->>E: record error metrics
        E-->>Caller: ExecutionResult(status=FAILURE, error=...)
    else error_strategy = CONTINUE
        E->>E: log error, proceed
        E-->>Caller: ExecutionResult(status=FAILURE, error=..., continued=True)
    else error_strategy = RETRY
        loop max_retries times
            E->>Handler: execute(context)
            Handler-->>E: raises Exception
            E->>E: wait delay * backoff^attempt
        end
        E-->>Caller: ExecutionResult(status=FAILURE, error=..., retries=n)
    else error_strategy = FALLBACK
        E->>Handler: invoke fallback handler
        Handler-->>E: fallback result
        E-->>Caller: ExecutionResult(status=SUCCESS, output=fallback, fallback=True)
    else error_strategy = IGNORE
        E->>E: log warning silently
        E-->>Caller: ExecutionResult(status=SKIPPED, ignored=True)
    end
```

## 9. Hot-Reload Data Flow

```mermaid
flowchart TB
    START[Start Hot-Reload] --> THREAD[Spawn Watcher Thread]
    THREAD --> LOOP{Infinite Loop}
    LOOP --> SLEEP[Sleep interval seconds]
    SLEEP --> SCAN[Scan source paths]
    SCAN --> CMP{Compare mtimes vs cache}
    CMP -->|no changes| LOOP
    CMP -->|changes detected| RELOAD[reload() for each changed file]
    RELOAD --> PARSE[Parse new content]
    PARSE --> VALIDATE[Validate new skill]
    VALIDATE -->|passes| SWAP[Replace in registry]
    VALIDATE -->|fails| LOG[Log error, keep old]
    SWAP --> EMIT[Emit SKILL_UPDATED event]
    EMIT --> LOOP
    LOG --> LOOP
```

## 10. Dependency Resolution Flow

When `resolve_dependencies` is enabled, the loader resolves each skill's dependency list against already-loaded skills.

```mermaid
flowchart TB
    SKILL[Loaded Skill] --> DEPS{[dependencies] empty?}
    DEPS -->|yes| READY[Skill is ready]
    DEPS -->|no| RESOLVE{For each dep}
    RESOLVE --> FIND{Find in loaded_skills}
    FIND -->|found| CHECK{Check compat}
    CHECK -->|compatible| SAT[Dep satisfied]
    CHECK -->|incompatible| FAIL[Load failure]
    FIND -->|not found, optional| WARN[Log warning]
    FIND -->|not found, required| FAIL2[Load failure]
    SAT --> ALL{All deps resolved?}
    WARN --> ALL
    ALL -->|yes| READY
    ALL -->|no| LOAD_DEP[Load dependency first]
    LOAD_DEP --> RESOLVE
```

## 11. Thread Safety Model

```mermaid
flowchart LR
    subgraph Thread-Safe Zones
        REG[SkillRegistry: threading.Lock on _skills]
        EXEC[SkillExecutor: ThreadPoolExecutor]
        CACHE[CacheStore: threading.Lock]
    end

    subgraph Non-Thread-Safe
        LOAD[SkillLoader: sequential only]
        VAL[SkillValidator: per-call stateless]
    end

    T1[Thread 1] --> REG
    T2[Thread 2] --> REG
    T3[Thread 3] --> EXEC
    T4[Thread 4] --> EXEC
```

The `SkillRegistry` uses `threading.Lock` to protect its `_skills` and `_namespaces` dictionaries during registration, unregistration, and query operations. The `SkillExecutor` uses `concurrent.futures.ThreadPoolExecutor` for parallel execution modes. `SkillLoader` and `SkillValidator` are designed for single-threaded use, though the validator is stateless and could be called from multiple threads safely.
