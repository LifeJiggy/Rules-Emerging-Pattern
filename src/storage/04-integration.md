# Storage Module — Integration

## 1. Integration Overview

```mermaid
flowchart TB
    subgraph External Consumers
        APP[Application Core]
        API[REST API]
        CLI[CLI Interface]
        SYNC[Sync Service]
    end

    subgraph Storage Module
        RS[RuleStorage]
        FS[FileStore]
        CS[CacheStore]
        BK[BackupManager]
        MG[MigrationManager]
    end

    subgraph External Infrastructure
        DISK[File System]
        NET[Network Drive / S3]
        DB[Database / State Store]
    end

    APP --> RS
    API --> RS
    CLI --> RS
    SYNC --> RS
    RS --> FS
    RS --> CS
    RS --> BK
    RS --> MG
    FS --> DISK
    FS -.->|optional| NET
    BK --> DISK
    MG --> DISK
```

## 2. Integration with Skills Module

The Skills module consumes the Storage module for persisting and retrieving skill definitions.

```mermaid
sequenceDiagram
    participant SK as Skills Module
    participant RS as RuleStorage
    participant FS as FileStore
    participant CS as CacheStore

    Note over SK,CS: Load Flow
    SK->>RS: list_rules()
    RS->>CS: get("rule_list")
    alt Cache miss
        RS->>FS: list_files()
        FS-->>RS: [paths]
        RS->>CS: set("rule_list", [paths])
    end
    RS-->>SK: [rule names]

    SK->>RS: read("transform_skill")
    RS->>FS: read("rules/transform_skill.yaml")
    FS-->>RS: dict
    RS-->>SK: RuleSkill dict

    Note over SK,CS: Save Flow
    SK->>RS: write("new_skill", skill_dict)
    RS->>FS: atomic_write("rules/new_skill.yaml", data)
    FS-->>RS: True
    RS-->>SK: True
```

### Integration Points

| Skills Module | Storage Module | Operation |
|---|---|---|
| `SkillLoader.load(dir)` | `RuleStorage.list_rules()` | Discover skill files |
| `SkillLoader.read()` | `RuleStorage.read()` | Load individual skill |
| `SkillLoader.reload()` | `RuleStorage.read(force=True)` | Skip cache, re-read from disk |
| `SkillLoader.hot_reload()` | `FileStore.stat()` | Check mtime for changes |
| `SkillRegistry.snapshot()` | `RuleStorage.write(snapshot)` | Persist registry state |
| `SkillRegistry.restore()` | `RuleStorage.read(snapshot)` | Load registry state |
| `SkillExecutor.cache` | `CacheStore.get/set` | Cache execution results |

## 3. Integration with Backup Service

```mermaid
sequenceDiagram
    participant SVC as Backup Service
    participant BK as BackupManager
    participant FS as FileStore
    participant CAT as Catalog

    Note over SVC,CAT: Scheduled Backup
    SVC->>BK: schedule_backup(interval=86400, source="/rules", type=DIFFERENTIAL)
    BK->>BK: start scheduler thread

    loop Every 24 hours
        BK->>FS: list_files("/rules/*")
        FS-->>BK: [files]
        BK->>FS: read(changed_files)
        FS-->>BK: content
        BK->>BK: compress + checksum
        BK->>FS: atomic_write("/backups/diff_*.zip")
        FS-->>BK: True
        BK->>CAT: update catalog entry
        BK->>BK: prune() if needed
    end

    Note over SVC,CAT: Ad-hoc Restore
    SVC->>BK: list_backups(source="/rules")
    BK-->>SVC: [BackupRecord, ...]
    SVC->>BK: restore("backup-uuid", target="/restore/rules")
    BK->>FS: read(backup_path)
    FS-->>BK: backup data
    BK->>BK: verify checksum
    BK->>FS: atomic_write(restore_path, data)
    FS-->>BK: True
    BK-->>SVC: True
```

### Backup Integration Configuration

```yaml
backup:
  directory: "/data/backups"
  sources:
    - path: "/data/rules"
      type: DIFFERENTIAL
      schedule: "0 2 * * *"    # daily at 2am
      retention:
        keep_full: 5
        keep_incremental: 20
        keep_differential: 10
        max_age_days: 90
    - path: "/data/config"
      type: FULL
      schedule: "0 3 * * 0"    # weekly on Sunday
      retention:
        keep_full: 10
        max_age_days: 365
```

## 4. Integration with Migration Pipeline

```mermaid
sequenceDiagram
    participant APP as Application
    participant MG as MigrationManager
    participant FS as FileStore
    participant RS as RuleStorage

    Note over APP,RS: Startup Migration Check
    APP->>MG: has_pending()
    MG->>FS: list_files("/migrations/*.py")
    FS-->>MG: [migration files]
    MG->>FS: read("_migration_table.json")
    FS-->>MG: executed migrations
    MG-->>APP: True (has pending)

    APP->>MG: dry_run(target_version="2.0")
    MG-->>APP: [migration_1, migration_2, ...]

    APP->>MG: migrate(target_version="2.0")
    loop for each migration
        MG->>MG: execute fn()
        MG->>FS: atomic_write("_migration_table.json", updated)
        FS-->>MG: True
    end
    MG-->>APP: True

    Note over APP,RS: Post-migration, storage schema may have changed
    APP->>RS: read("existing_rule")
    RS->>FS: read("rules/existing_rule.yaml")
    FS-->>RS: old format data
    RS->>RS: apply schema conversion
    RS-->>APP: migrated rule data
```

### Migration Script Template

```python
# migrations/001_add_version_field.py
def upgrade():
    # Load all rules, add "version": "1.0" if missing
    for rule_name in storage.list_rules():
        rule = storage.read(rule_name)
        if "version" not in rule:
            rule["version"] = "1.0"
        storage.write(rule_name, rule)

def downgrade():
    # Remove "version" field from all rules
    for rule_name in storage.list_rules():
        rule = storage.read(rule_name)
        rule.pop("version", None)
        storage.write(rule_name, rule)
```

## 5. Integration with REST API

```mermaid
sequenceDiagram
    participant Client
    participant API as REST API
    participant RS as RuleStorage
    participant FS as FileStore

    Client->>API: GET /rules
    API->>RS: list_rules()
    RS-->>API: [rule names]
    API-->>Client: 200 ["rule_a", "rule_b"]

    Client->>API: GET /rules/rule_a
    API->>RS: read("rule_a")
    RS->>FS: read("rules/rule_a.yaml")
    FS-->>RS: dict
    RS-->>API: rule_data
    API-->>Client: 200 {name: "rule_a", ...}

    Client->>API: PUT /rules/rule_a
    API->>RS: write("rule_a", body)
    RS->>FS: atomic_write("rules/rule_a.yaml", body)
    FS-->>RS: True
    RS-->>API: True
    API-->>Client: 200 Updated

    Client->>API: POST /search?q=transform
    API->>RS: search("transform")
    RS-->>API: matching rules
    API-->>Client: 200 [...]

    Client->>API: GET /stats
    API->>RS: stats()
    RS-->>API: stats dict
    API-->>Client: 200 {total_rules: 42, ...}
```

### API Endpoint Mapping

| HTTP Method | Endpoint | Module Call |
|---|---|---|
| `GET` | `/rules` | `RuleStorage.list_rules()` |
| `GET` | `/rules/{name}` | `RuleStorage.read(name)` |
| `PUT` | `/rules/{name}` | `RuleStorage.write(name, data)` |
| `DELETE` | `/rules/{name}` | `RuleStorage.delete(name)` |
| `GET` | `/rules/{name}/exists` | `RuleStorage.exists(name)` |
| `POST` | `/search` | `RuleStorage.search(pattern)` |
| `GET` | `/stats` | `RuleStorage.stats()` |
| `POST` | `/backup` | `BackupManager.create_backup()` |
| `GET` | `/backups` | `BackupManager.list_backups()` |
| `POST` | `/backups/{id}/restore` | `BackupManager.restore(id)` |
| `POST` | `/migrate` | `MigrationManager.migrate()` |
| `GET` | `/migrations` | `MigrationManager.status()` |
| `POST` | `/migrations/dry-run` | `MigrationManager.dry_run()` |

## 6. Integration with CLI

```mermaid
sequenceDiagram
    participant User
    participant CLI as CLI
    participant RS as RuleStorage
    participant BK as BackupManager
    participant MG as MigrationManager

    User->>CLI: rules list
    CLI->>RS: list_rules()
    RS-->>CLI: ["rule_a", "rule_b"]
    CLI->>User: formatted table

    User->>CLI: rules show rule_a
    CLI->>RS: read("rule_a")
    RS-->>CLI: dict
    CLI->>User: formatted YAML/JSON

    User->>CLI: rules write rule_a --format json
    CLI->>RS: write("rule_a", data, fmt="json")
    RS-->>CLI: True
    CLI->>User: "rule_a written"

    User->>CLI: backup create --source /rules --full
    CLI->>BK: create_backup(source="/rules", type=FULL)
    BK-->>CLI: BackupRecord
    CLI->>User: "Backup created: backup-uuid"

    User->>CLI: backup list
    CLI->>BK: list_backups()
    BK-->>CLI: [BackupRecord, ...]
    CLI->>User: formatted table

    User->>CLI: migrate status
    CLI->>MG: status()
    MG-->>CLI: [migration statuses]
    CLI->>User: formatted table

    User->>CLI: migrate run --target 2.0
    CLI->>MG: migrate("2.0")
    MG-->>CLI: True
    CLI->>User: "Migration to 2.0 complete"
```

## 7. Integration with Cache Invalidation

```mermaid
sequenceDiagram
    participant APP as Application
    participant RS as RuleStorage
    participant CS as CacheStore

    Note over APP,CS: Cache consistency protocol
    APP->>RS: write("rule_a", new_data)
    RS->>RS: update FileStore
    RS->>CS: delete("rule_a")
    Note over CS: Explicit invalidation<br/>ensures next read<br/>hits FileStore

    APP->>RS: read("rule_a")
    RS->>CS: get("rule_a") → None (invalidated)
    RS->>RS: read from FileStore
    RS->>CS: set("rule_a", fresh_data)
    RS-->>APP: fresh_data
```

## 8. Integration with Monitoring

```mermaid
flowchart LR
    subgraph Storage Metrics
        RS[RuleStorage.stats()] --> M1[total_rules]
        RS --> M2[rules_per_format]
        RS --> M3[index_size]
        RS --> M4[cache_size]
        BK[BackupManager] --> M5[last_backup_time]
        BK --> M6[backup_count]
        BK --> M7[integrity_status]
        CS[CacheStore] --> M8[hit_rate]
        CS --> M9[eviction_count]
        CS --> M10[expired_count]
    end

    subgraph Monitoring Consumers
        PROM[Prometheus]
        GRAF[Grafana Dashboard]
        LOG[Structured Logs]
        ALERT[Alert Manager]
    end

    M1 --> PROM
    M2 --> PROM
    M5 --> ALERT
    M7 --> ALERT
    M8 --> GRAF
    M9 --> GRAF
    M10 --> GRAF
```

## 9. Integration Patterns

### Pattern 1: Read-Through Cache

```mermaid
sequenceDiagram
    participant App
    participant RS as RuleStorage
    participant CS as CacheStore
    participant FS as FileStore

    App->>RS: read("rule")
    RS->>CS: get("rule")
    alt Miss
        RS->>FS: read("rule.yaml")
        FS-->>RS: data
        RS->>CS: set("rule", data, ttl=300)
        RS-->>App: data
    end
    RS-->>App: data
```

### Pattern 2: Write-Through Cache

```mermaid
sequenceDiagram
    participant App
    participant RS as RuleStorage
    participant FS as FileStore
    participant CS as CacheStore

    App->>RS: write("rule", data)
    RS->>FS: atomic_write("rule.yaml", data)
    FS-->>RS: True
    RS->>CS: set("rule", data, ttl=300)  # update cache
    RS-->>App: True
```

### Pattern 3: Write-Behind Cache (Async Persist)

```mermaid
sequenceDiagram
    participant App
    participant RS as RuleStorage
    participant CS as CacheStore
    participant FS as FileStore
    participant BK as Background Worker

    App->>RS: write("rule", data)
    RS->>CS: set("rule", data)  # immediate confirm
    RS-->>App: True
    Note over RS: Background: persist to disk
    RS->>BK: queue("rule.yaml", data)
    BK->>FS: atomic_write("rule.yaml", data)
    FS-->>BK: True
    BK->>RS: confirm persisted
```

### Pattern 4: Versioned Migration

```mermaid
sequenceDiagram
    participant App
    participant MG as MigrationManager
    participant RS as RuleStorage

    Note over App: App starts with version 1.0
    App->>MG: has_pending()
    MG-->>App: True
    App->>MG: migrate(target="2.0")
    MG->>MG: run migration_1 → 2.0
    MG-->>App: True
    Note over App: Schema now at 2.0
    App->>RS: read("old_rule")
    RS->>RS: detect schema 1.0 → auto-convert
    RS-->>App: schema 2.0 data
```

## 10. Configuration Integration

```yaml
# Main application config
storage:
  base_path: "/data/rules"
  default_format: "yaml"
  atomic_writes: true
  create_dirs: true
  cache:
    enabled: true
    max_size: 10000
    ttl: 300
    eviction_policy: "LRU"
  backup:
    enabled: true
    directory: "/data/backups"
    retention:
      keep_full: 5
      keep_incremental: 20
    schedule_interval: 3600
  migration:
    directory: "/data/migrations"
    auto_create: true
```

The Storage module reads this configuration on initialization. Each component (`FileStore`, `CacheStore`, `BackupManager`, `MigrationManager`) receives its relevant subset.
