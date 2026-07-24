# Storage Module

## Overview

The Storage module provides a layered data persistence architecture for rules, cache entries, backups, and schema migrations. It consists of five components:

- **RuleStorage** — High-level facade that coordinates reading/writing rules. Handles format detection, index maintenance, and delegates to `FileStore` for raw I/O.
- **FileStore** — Low-level file I/O with atomic writes, file locking, format serialization (YAML, JSON, Pickle), and streaming for large files.
- **CacheStore** — In-memory cache with TTL-based expiration, LRU/LFU/FIFO eviction policies, and optional disk persistence.
- **BackupManager** — Scheduled and ad-hoc backup creation with versioning, pruning, integrity checks, and catalog management.
- **MigrationManager** — Schema migration engine with forward/reverse migrations, dependency ordering, status tracking, and dry-run mode.

## Class Diagram

```mermaid
classDiagram
    class RuleStorage {
        +StorageConfig config
        +RuleIndex index
        +Dict stores
        +read(name) Rule
        +write(name, rule) bool
        +delete(name) bool
        +list_rules() List
        +exists(name) bool
        +search(pattern) List
        +count() int
        +stats() Dict
        +get_store(name) FileStore
        +close() void
        +__enter__()
        +__exit__()
    }

    class FileStore {
        +FileStoreConfig config
        +FileLock lock
        +read(path) Any
        +write(path, data) bool
        +delete(path) bool
        +exists(path) bool
        +list_files(pattern) List
        +atomic_write(path, data) bool
        +read_stream(path) Generator
        +write_stream(path, data) bool
        +read_binary(path) bytes
        +write_binary(path, data) bool
        +format_magic(data) FileFormat
    }

    class CacheStore {
        +CacheStoreConfig config
        +Dict cache
        +get(key) Any
        +set(key, value, ttl) void
        +delete(key) bool
        +clear() void
        +has(key) bool
        +size() int
        +keys() List
        +values() List
        +items() List
        +get_or_compute(key, factory, ttl) Any
        +evict(count) int
        +cleanup() int
        +snapshot() Dict
        +restore(data) void
    }

    class BackupManager {
        +BackupPolicy policy
        +List backups
        +Dict catalog
        +create_backup(source, type) BackupRecord
        +restore(backup_id, target) bool
        +list_backups() List
        +delete_backup(backup_id) bool
        +verify(backup_id) bool
        +prune() int
        +schedule_backup(interval) void
        +stop_scheduled() void
        +integrity_check() Dict
        +export_catalog(path) void
    }

    class MigrationManager {
        +List migrations
        +Dict migration_table
        +create(name, description) MigrationRecord
        +migrate(target_version) bool
        +rollback(target_version) bool
        +status() List
        +list_migrations() List
        +get_migration(migration_id) MigrationRecord
        +pending_migrations() List
        +executed_migrations() List
        +has_pending() bool
        +dry_run(target_version) List
        +resolve_conflicts(migrations) List
    }

    RuleStorage --> FileStore: delegates I/O
    RuleStorage --> CacheStore: caches reads
    RuleStorage --> BackupManager: triggers backups
    RuleStorage --> MigrationManager: manages schema
    BackupManager --> FileStore: writes backups
    MigrationManager --> FileStore: reads/writes schema
```

## Component Hierarchy

```mermaid
flowchart TB
    APP[Application] --> RS[RuleStorage]

    RS --> FS[FileStore]
    RS --> CS[CacheStore]
    RS --> BK[BackupManager]
    RS --> MG[MigrationManager]

    BK --> FS
    MG --> FS

    subgraph FileStore
        FSYSTEM[File System]
        FORMAT[YAML / JSON / Pickle]
        LOCK[File Locking]
    end

    subgraph CacheStore
        MEM[In-memory Dict]
        EVICT[Eviction Policy]
        DISK[Optional Persistence]
    end

    subgraph BackupManager
        SCHED[Scheduler]
        VERIFY[Integrity Checker]
        PRUNE[Pruner]
        CAT[Catalogue]
    end

    subgraph MigrationManager
        TABLE[Migration Table]
        ORDER[Dependency Sorter]
        STATUS[Status Tracker]
    end
```

## Store Delegation

`RuleStorage` can manage multiple `FileStore` instances, each associated with a named store. This enables multi-format, multi-path storage.

```mermaid
flowchart LR
    RS[RuleStorage] --> stores{_stores dict}
    stores -->|"default"| FS1[FileStore: ./rules]
    stores -->|"backup"| FS2[FileStore: ./backups]
    stores -->|"archive"| FS3[FileStore: ./archive]

    RS --> index{RuleIndex}
    index --> name["name → file path"]
    index --> tags["tag → [rule names]"]
    index --> created["created_at → sorted list"]
```

## API Reference

| Class | Method | Description |
|---|---|---|
| `RuleStorage` | `read(name)` | Read rule by name from default store |
| `RuleStorage` | `write(name, rule)` | Write rule, auto-serialize, update index |
| `RuleStorage` | `search(pattern)` | Pattern match rule names (RE search) |
| `RuleStorage` | `stats()` | Total rules, per-format counts, index size |
| `FileStore` | `atomic_write(path, data)` | Write with temp file + rename |
| `FileStore` | `read_stream(path)` | Lazy line-by-line generator |
| `FileStore` | `format_magic(data)` | Detect format from magic bytes |
| `CacheStore` | `get_or_compute(key, fn, ttl)` | Get or call factory to populate |
| `CacheStore` | `evict(count)` | Evict N entries per policy (LRU/LFU/FIFO) |
| `BackupManager` | `create_backup(source, type)` | Create full/incremental/differential backup |
| `BackupManager` | `prune()` | Remove old backups per retention policy |
| `MigrationManager` | `migrate(target_version)` | Run pending migrations in order |
| `MigrationManager` | `rollback(target_version)` | Reverse applied migrations |
| `MigrationManager` | `dry_run(target_version)` | Preview migrations without executing |

## Data Flow

```mermaid
sequenceDiagram
    participant App
    participant RS as RuleStorage
    participant FS as FileStore
    participant CS as CacheStore
    participant BK as BackupManager

    App->>RS: write("my_rule", rule_data)
    RS->>RS: validate rule_data
    RS->>RS: format detection
    RS->>FS: atomic_write(path, serialized)
    FS-->>RS: success
    RS->>RS: update RuleIndex
    RS->>CS: set(cache_key, rule_data)
    RS-->>App: True

    App->>RS: read("my_rule")
    RS->>CS: get(cache_key)
    alt Cache hit
        CS-->>RS: cached_data
        RS-->>App: rule_data
    else Cache miss
        RS->>FS: read(path)
        FS-->>RS: raw data
        RS->>RS: deserialize
        RS->>CS: set(cache_key, rule_data)
        RS-->>App: rule_data
    end

    App->>BK: create_backup("my_rule", FULL)
    BK->>FS: read(rule_path)
    FS-->>BK: serialized_rule
    BK->>BK: compress + timestamp
    BK->>FS: atomic_write(backup_path, data)
    FS-->>BK: success
    BK->>BK: update catalog
    BK-->>App: BackupRecord
```

## Storage Formats

| Format | Extension | Serialization | Magic Bytes |
|---|---|---|---|
| YAML | `.yaml`, `.yml` | `yaml.dump/load` | `%YAML` or `---` |
| JSON | `.json` | `json.dumps/loads` | `{` or `[` |
| Pickle | `.pkl`, `.pickle` | `pickle.dump/load` | Python pickle protocol |

## Error Handling

All storage classes define their own exception types that extend `StorageError`:

```mermaid
flowchart TB
    StorageError --> FileStoreError
    StorageError --> CacheError
    StorageError --> BackupError
    StorageError --> MigrationError

    FileStoreError --> FileNotFoundError
    FileStoreError --> PermissionError
    FileStoreError --> FormatError
    FileStoreError --> LockError
    FileStoreError --> AtomicWriteError

    CacheError --> KeyNotFoundError
    CacheError --> EvictionError
    CacheError --> SerializationError

    BackupError --> VerificationError
    BackupError --> PruneError
    BackupError --> CatalogError

    MigrationError --> VersionMismatchError
    MigrationError --> CircularDependencyError
    MigrationError --> IrreversibleMigrationError
```

## Performance Characteristics

| Operation | Time Complexity | Notes |
|---|---|---|
| `FileStore.read()` | O(s) | s = file size |
| `FileStore.atomic_write()` | O(s) | Write to tmp + rename |
| `FileStore.read_stream()` | O(1) per yield | Memory-efficient for large files |
| `CacheStore.get()` | O(1) | Dict lookup |
| `CacheStore.set()` | O(1) average | May trigger O(n) eviction |
| `CacheStore.evict(LRU)` | O(n log n) | Sort by access time |
| `CacheStore.evict(LFU)` | O(n log n) | Sort by access count |
| `CacheStore.cleanup()` | O(n) | Remove expired entries |
| `BackupManager.create_backup()` | O(s) | s = source size |
| `BackupManager.prune()` | O(n log n) | Sort by version/age |
| `MigrationManager.migrate()` | O(m × n) | m = migrations, n = dependencies |
| `RuleStorage.search()` | O(k) | k = number of rules (regex scan) |

## Configuration

```yaml
storage:
  default_format: "yaml"
  encoding: "utf-8"
  atomic_writes: true
  create_dirs: true

cache:
  backend: "memory"
  max_size: 1000
  eviction_policy: "LRU"
  default_ttl: 300
  persist_path: null

backup:
  directory: "./backups"
  retention:
    keep_full: 5
    keep_incremental: 20
    max_age_days: 90
  schedule_interval: 3600
  compression: true
  verify_on_create: true

migration:
  table_name: "_migrations"
  directory: "./migrations"
  auto_create: true
  dry_run: false
```
