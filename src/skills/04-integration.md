# Skills Module — Integration

## External Interfaces

The Skills module integrates with the broader system through well-defined interfaces. Each component exposes a public API that other modules consume.

## 1. Integration Overview

```mermaid
flowchart TB
    subgraph External
        CLI[CLI Interface]
        API[REST API]
        APP[Application Core]
        SCHED[Scheduler]
        WEB[Web Dashboard]
    end

    subgraph Skills Module
        LOAD[SkillLoader]
        REG[SkillRegistry]
        VAL[SkillValidator]
        EXEC[SkillExecutor]
    end

    subgraph Storage
        FILESTORE[FileStore]
        CACHE[CacheStore]
        BACKUP[BackupManager]
    end

    subgraph Monitoring
        LOG[Logger]
        METRICS[Metrics Collector]
        ALERT[Alert Manager]
    end

    CLI --> LOAD
    CLI --> REG
    CLI --> EXEC
    API --> REG
    API --> EXEC
    APP --> REG
    APP --> EXEC
    SCHED --> EXEC
    WEB --> REG
    WEB --> EXEC

    LOAD --> FILESTORE
    EXEC --> CACHE
    REG --> BACKUP
    EXEC --> LOG
    EXEC --> METRICS
    REG --> ALERT
```

## 2. Integration with CLI

The CLI module uses the Skills module to load, list, register, and execute skills from the command line.

```mermaid
sequenceDiagram
    participant User
    participant CLI as CLI Module
    participant SK as SkillLoader
    participant REG as SkillRegistry
    participant EXEC as SkillExecutor

    User->>CLI: skills load --dir ./skills
    CLI->>SK: load("./skills", SourceType.DIRECTORY)
    SK-->>CLI: [RuleSkill A, RuleSkill B]
    CLI->>User: "Loaded 2 skills"

    User->>CLI: skills list --category TRANSFORM
    CLI->>REG: query(category=SkillCategory.TRANSFORM)
    REG-->>CLI: [RuleSkill A]
    CLI->>User: formatted table of skills

    User->>CLI: skills run A --input text="hello"
    CLI->>REG: get("A")
    REG-->>CLI: RuleSkill A
    CLI->>EXEC: execute(RuleSkill A, {"text": "hello"})
    EXEC-->>CLI: ExecutionResult
    CLI->>User: formatted output
```

### CLI Command Mapping

| CLI Command | Module Method |
|---|---|
| `skills load <dir>` | `SkillLoader.load(dir, SourceType.DIRECTORY)` |
| `skills reload <name>` | `SkillLoader.reload(name)` |
| `skills list [--category] [--tags]` | `SkillRegistry.query(category, tags)` |
| `skills register <path>` | `SkillRegistry.register(skill)` |
| `skills unregister <name>` | `SkillRegistry.unregister(name)` |
| `skills activate <name>` | `SkillRegistry.activate(name)` |
| `skills deactivate <name>` | `SkillRegistry.deactivate(name)` |
| `skills validate <path>` | `SkillValidator.validate(skill)` |
| `skills run <name> [--input]` | `SkillExecutor.execute(skill, inputs)` |
| `skills batch <names> [--mode]` | `SkillExecutor.execute_batch(skills, mode)` |
| `skills stats` | `SkillExecutor.metrics()` |

## 3. Integration with REST API

The REST API module exposes Skills functionality over HTTP.

```mermaid
sequenceDiagram
    participant Client
    participant API as REST API
    participant REG as SkillRegistry
    participant VAL as SkillValidator
    participant EXEC as SkillExecutor

    Client->>API: POST /skills/register {yaml_content}
    API->>API: parse YAML → RuleSkill
    API->>VAL: validate(skill)
    VAL-->>API: ValidationResult
    alt Validation fails
        API-->>Client: 422 Validation Error
    end
    API->>REG: register(skill)
    REG-->>API: True
    API-->>Client: 201 Created {skill_id, name}

    Client->>API: GET /skills?category=VALIDATE&status=ACTIVE
    API->>REG: query(category=SkillCategory.VALIDATE, status=...)
    REG-->>API: [RuleSkill ...]
    API-->>Client: 200 [{name, category, status}, ...]

    Client->>API: POST /skills/{name}/execute {inputs}
    API->>REG: get(name)
    REG-->>API: RuleSkill
    API->>EXEC: execute(skill, inputs)
    EXEC-->>API: ExecutionResult
    API-->>Client: 200 {status, output, execution_time}

    Client->>API: GET /skills/{name}/dependencies
    API->>REG: dependency_chain(name, direction="downstream")
    REG-->>API: [skill names]
    API-->>Client: 200 ["dep_a", "dep_b", ...]
```

### API Endpoint Mapping

| HTTP Method | Endpoint | Module Call |
|---|---|---|
| `POST` | `/skills/register` | `Registry.register()` |
| `DELETE` | `/skills/{name}` | `Registry.unregister()` |
| `GET` | `/skills` | `Registry.query()` |
| `GET` | `/skills/{name}` | `Registry.get()` |
| `POST` | `/skills/{name}/activate` | `Registry.activate()` |
| `POST` | `/skills/{name}/deactivate` | `Registry.deactivate()` |
| `POST` | `/skills/{name}/execute` | `Executor.execute()` |
| `POST` | `/skills/batch` | `Executor.execute_batch()` |
| `GET` | `/skills/{name}/dependencies` | `Registry.dependency_chain()` |
| `GET` | `/skills/snapshot` | `Registry.snapshot()` |
| `POST` | `/skills/restore` | `Registry.restore_snapshot()` |
| `GET` | `/skills/{name}/validate` | `Validator.validate()` |
| `GET` | `/skills/metrics` | `Executor.metrics()` |

## 4. Integration with Application Core

The application core module consumes skills as part of its main processing pipeline.

```mermaid
sequenceDiagram
    participant CORE as Application Core
    participant LOAD as SkillLoader
    participant REG as SkillRegistry
    participant EXEC as SkillExecutor

    Note over CORE: Startup
    CORE->>LOAD: load("./default_skills", "default")
    LOAD-->>CORE: [built-in skills]
    CORE->>REG: register(skills)
    CORE->>REG: activate(skills)

    Note over CORE: On new data
    CORE->>REG: query(category=SkillCategory.TRANSFORM, status=ACTIVE)
    REG-->>CORE: [transform_skills]
    CORE->>EXEC: execute_batch(transform_skills, mode=PIPELINE)
    EXEC-->>CORE: [transformed results]

    Note over CORE: On error
    CORE->>REG: query(category=SkillCategory.VALIDATE, tags=["error"])
    REG-->>CORE: [error_handler_skills]
    CORE->>EXEC: execute(error_skill, {"error": err})
    EXEC-->>CORE: resolved
```

### Core Integration Points

| Core Event | Skills Module Action |
|---|---|
| System startup | `SkillLoader.load()` + `SkillRegistry.register()` |
| Data ingestion | `SkillRegistry.query(TRANSFORM)` → `SkillExecutor.execute_batch(PIPELINE)` |
| Data validation | `SkillRegistry.query(VALIDATE)` → `SkillExecutor.execute_batch(SEQUENTIAL)` |
| Error handling | `SkillRegistry.query(CUSTOM, tags=["error"])` → `SkillExecutor.execute()` |
| Shutdown | `SkillExecutor.shutdown()` |
| Config change | `SkillLoader.reload()` |

## 5. Integration with Scheduler

The scheduler module triggers skill execution at configured intervals.

```mermaid
sequenceDiagram
    participant SCHED as Scheduler
    participant REG as SkillRegistry
    participant EXEC as SkillExecutor

    loop Every minute
        SCHED->>REG: query(triggers=[SkillTrigger.SCHEDULE])
        REG-->>SCHED: [scheduled skills]
        SCHED->>EXEC: execute_batch(scheduled, PARALLEL)
        EXEC-->>SCHED: results
    end
```

### Crontab Mapping

```yaml
# Schedule configuration in YAML
schedule:
  - skill: data_cleanup
    cron: "0 3 * * *"    # daily at 3am
  - skill: report_generate
    cron: "0 0 * * 1"     # weekly on Monday
  - skill: heartbeat
    cron: "* * * * *"     # every minute
```

## 6. Integration with FileStore

The `SkillLoader` reads skill definitions from the `FileStore`. The integration handles atomic reads, error recovery, and format detection.

```mermaid
sequenceDiagram
    participant LOAD as SkillLoader
    participant FS as FileStore
    participant OS as File System

    LOAD->>FS: read(directory)
    FS->>OS: os.listdir()
    OS-->>FS: [files]
    FS->>OS: open each file
    OS-->>FS: raw content
    FS-->>LOAD: [content strings]

    LOAD->>FS: stat(file)
    FS->>OS: os.stat()
    OS-->>FS: mtime, size
    FS-->>LOAD: StatResult
```

### File Extension Mapping

| Extension | Source Type | Parser |
|---|---|---|
| `.yaml`, `.yml` | `SourceType.DIRECTORY` | `yaml.safe_load()` |
| `.json` | `SourceType.DIRECTORY` | `json.loads()` |
| `.py` | `SourceType.PACKAGE` | `importlib.import_module()` |
| `.md` | `SourceType.DIRECTORY` | YAML frontmatter parser |

## 7. Integration with CacheStore

The `SkillExecutor` integrates with `CacheStore` to cache and retrieve execution results.

```mermaid
flowchart TB
    subgraph Cache Integration
        EXEC[SkillExecutor] --> CHECK{caching_policy?}
        CHECK -->|None| BYPASS[No cache - always execute]
        CHECK -->|TTL > 0| TTL_CHECK{Cache Has Key?}

        TTL_CHECK -->|yes| RETRIEVE[CacheStore.get(key)]
        RETRIEVE --> FRESH{Still Fresh?}
        FRESH -->|yes| RETURN[Return cached result]
        FRESH -->|no| EXECUTE[Execute and cache]
        TTL_CHECK -->|no| EXECUTE

        EXECUTE --> STORE[CacheStore.set(key, result, ttl)]
        STORE --> RETURN2[Return fresh result]
    end

    subgraph Cache Key
        K1["cache_key = f'{skill.skill_id}:{hash(inputs)}'"]
    end
```

## 8. Integration with BackupManager

The `SkillRegistry` integrates with `BackupManager` for periodic snapshots and disaster recovery.

```mermaid
sequenceDiagram
    participant REG as SkillRegistry
    participant BK as BackupManager
    participant FS as FileStore

    REG->>REG: snapshot()
    REG->>BK: create_backup(snapshot_data)
    BK->>FS: write serialized snapshot
    FS-->>BK: stored path
    BK-->>REG: BackupRecord

    Note over REG,BK: Restore flow
    BK->>FS: read snapshot file
    FS-->>BK: serialized data
    BK->>REG: restore_snapshot(data)
    REG-->>BK: True
```

## 9. Integration with Metrics System

The `SkillExecutor` exports metrics that the monitoring system collects.

```mermaid
flowchart LR
    EXEC[SkillExecutor] --> METRICS[In-memory Metrics]
    METRICS --> COLLECT[Collector polls every 60s]
    COLLECT --> PROM[Prometheus / Grafana]
    COLLECT --> LOG[Structured Logs]
    COLLECT --> DASH[Web Dashboard]

    subgraph Metrics Exported
        M1["total_executions (counter)"]
        M2["successful_executions (counter)"]
        M3["failed_executions (counter)"]
        M4["execution_time_seconds (histogram)"]
        M5["errors_by_type (counter)"]
        M6["success_rate (gauge)"]
        M7["slowest_executions (info)"]
    end

    METRICS --> M1
    METRICS --> M2
    METRICS --> M3
    METRICS --> M4
    METRICS --> M5
    METRICS --> M6
    METRICS --> M7
```

## 10. Integration Patterns

### Pattern 1: Load and Forget

```mermaid
sequenceDiagram
    participant Client
    participant REG as SkillRegistry
    participant EXEC as SkillExecutor

    Client->>REG: get("cleanup_skill")
    REG-->>Client: RuleSkill
    Client->>EXEC: execute(skill, inputs)
    EXEC-->>Client: ExecutionResult
    Client->>Client: cache result locally
```

### Pattern 2: Pipeline Orchestrator

```mermaid
flowchart TB
    PIPELINE[Pipeline Orchestrator]
    PIPELINE --> Q{Query Registry}
    Q --> S1[Load Skill: raw_data_loader]
    Q --> S2[Load Skill: data_cleaner]
    Q --> S3[Load Skill: data_analyzer]
    Q --> S4[Load Skill: report_generator]

    PIPELINE --> EXEC{Execute Pipeline}
    EXEC -->|mode=PIPELINE| EXEC
    S1 -->|output| S2 -->|output| S3 -->|output| S4

    PIPELINE --> VALIDATE{Validate Output}
    S4 --> VALIDATE
    VALIDATE --> REPORT[Return Final Report]
```

### Pattern 3: Error Handler Chain

```mermaid
flowchart TB
    TRY[Execute Primary Skill] --> SUCCESS{Success?}
    SUCCESS -->|yes| DONE[Done]
    SUCCESS -->|no| ERROR_MATCH{Match Error Type}

    ERROR_MATCH -->|ValidationError| VALIDATE_H[Run: validate_fix_skill]
    ERROR_MATCH -->|TimeoutError| RETRY_H[Run: retry_with_backoff_skill]
    ERROR_MATCH -->|DataError| CORRECT_H[Run: data_correction_skill]
    ERROR_MATCH -->|Fallback| FALLBACK_H[Run: fallback_handler_skill]

    VALIDATE_H --> REASSESS{Reassess}
    RETRY_H --> REASSESS
    CORRECT_H --> REASSESS
    FALLBACK_H --> DONE2[Done with fallback]

    REASSESS -->|fixed| RETRY_PRIMARY[Retry Primary]
    RETRY_PRIMARY --> SUCCESS
    REASSESS -->|unfixable| DONE2
```

## 11. Integration Configuration

When integrating the Skills module, the following configuration must be provided:

```yaml
skills:
  loader:
    format: "auto"
    recursive: true
    validate: true
    hot_reload: false
    hot_reload_interval: 5
    cache_loaded: true
    resolve_dependencies: true

  registry:
    allow_overwrite: false
    auto_activate: true
    check_circular_deps: true
    conflict_resolution: "error"
    validate_on_register: true

  executor:
    max_workers: 4
    default_timeout: 30.0
    retry_on_failure: false
    track_metrics: true
    cache_results: false

  validator:
    max_issues_per_skill: 20
    fail_on_error: true
    fail_on_warning: false
    check_security: true
```

### Integration with External Systems

```mermaid
flowchart TB
    subgraph Skills Module
        LOAD[SkillLoader]
        REG[SkillRegistry]
        VAL[SkillValidator]
        EXEC[SkillExecutor]
    end

    subgraph System Integration
        CONFIG[System Config]
        EVENTS[Event Bus]
        STORE[Data Store]
        AUTH[Auth Provider]
    end

    LOAD -->|reads| CONFIG
    REG -->|emits| EVENTS
    EXEC -->|reads/writes| STORE
    EXEC -->|checks| AUTH
    EVENTS -->|notifies| STORE
    AUTH -->|validates| EXEC
```

The Skills module does not require a specific event bus, auth provider, or data store. Each integration adapter implements a thin wrapper that maps the module's interfaces to the system's infrastructure.
