# Storage Module — Architecture

## Component Architecture

The Storage module follows a layered architecture. The `RuleStorage` facade sits at the top, delegating to `FileStore`, `CacheStore`, `BackupManager`, and `MigrationManager`. Each lower layer handles a specific concern.

```mermaid
flowchart TB
    subgraph Facade Layer
        RS[RuleStorage]
    end

    subgraph Service Layer
        BK[BackupManager]
        MG[MigrationManager]
    end

    subgraph Data Layer
        FS[FileStore]
        CS[CacheStore]
    end

    subgraph Infrastructure
        DISK[Disk / File System]
        MEM[In-Memory Dict]
    end

    RS --> FS
    RS --> CS
    RS --> BK
    RS --> MG
    BK --> FS
    MG --> FS
    FS --> DISK
    CS --> MEM
    CS -.->|optional| DISK
```

## RuleStorage Architecture

```mermaid
classDiagram
    class RuleStorage {
        -StorageConfig config
        -RuleIndex index
        -Dict~str, FileStore~ stores
        -CacheStore cache
        -BackupManager backup_mgr
        -MigrationManager migration_mgr
        -Dict stats_data
        -threading.Lock lock
        +read(name, store_name, force) Rule
        +write(name, rule, store_name, fmt) bool
        +delete(name, store_name) bool
        +list_rules(store_name, pattern) List
        +exists(name, store_name) bool
        +search(pattern, store_name) List
        +count() int
        +stats() Dict
        +get_store(name) FileStore
        +close()
        +__enter__()
        +__exit__()
    }

    class StorageConfig {
        +str base_path
        +str default_format
        +str encoding
        +bool atomic_writes
        +bool create_dirs
        +bool use_cache
        +int cache_ttl
        +bool enable_backup
        +bool enable_migration
    }

    class RuleIndex {
        +Dict~str, str~ name_to_path
        +Dict~str, List~str~~ tag_index
        +Dict~str, List~str~~ created_index
        +add(name, path, tags)
        +remove(name)
        +search(pattern) List
        +clear()
        +size() int
    }

    RuleStorage --> StorageConfig
    RuleStorage --> RuleIndex
    RuleStorage --> FileStore
    RuleStorage --> CacheStore
    RuleStorage --> BackupManager
    RuleStorage --> MigrationManager
```

## FileStore Architecture

```mermaid
classDiagram
    class FileStore {
        -FileStoreConfig config
        -FileLock lock
        -Dict stats
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

    class FileStoreConfig {
        +str base_path
        +str format
        +str encoding
        +bool atomic_writes
        +bool create_dirs
        +bool use_locking
        +float lock_timeout
    }

    class FileLock {
        +str path
        +str lock_path
        +float timeout
        +acquire()
        +release()
        +locked()
        +__enter__()
        +__exit__()
    }

    FileStore --> FileStoreConfig
    FileStore --> FileLock
    FileLock -->|.lock file| DISK[(File System)]
```

### FileLock Implementation

The `FileLock` uses a lock file on disk (`path.lock`). It:
1. Tries to create the `.lock` file exclusively (atomic `os.open` with `O_CREAT | O_EXCL`)
2. Retries until the lock is acquired or `timeout` expires
3. Cleans up the `.lock` file on `release()`

```mermaid
sequenceDiagram
    participant Client
    participant FS as FileStore
    participant LK as FileLock
    participant OS

    Client->>FS: write(path, data)
    FS->>LK: acquire()
    LK->>OS: open(.lock, O_CREAT|O_EXCL)
    alt Success
        OS-->>LK: fd
        LK-->>FS: acquired
    else FileExists
        loop until timeout
            LK->>LK: sleep 0.1
            LK->>OS: retry open
        end
        alt timeout reached
            LK-->>FS: raise LockError
        end
    end
    FS->>OS: write target file
    OS-->>FS: done
    FS->>LK: release()
    LK->>OS: remove .lock file
    FS-->>Client: True
```

## CacheStore Architecture

```mermaid
classDiagram
    class CacheStore {
        -CacheStoreConfig config
        -Dict~str, CacheEntry~ cache
        -Heap eviction_heap
        -int current_size
        +get(key) Any
        +set(key, value, ttl) void
        +delete(key) bool
        +clear()
        +has(key) bool
        +size() int
        +keys() List
        +values() List
        +items() List
        +get_or_compute(key, factory, ttl) Any
        +evict(count) int
        +cleanup() int
        +snapshot() Dict
        +restore(data)
    }

    class CacheStoreConfig {
        +str backend
        +int max_size
        +str eviction_policy
        +int default_ttl
        +Optional~str~ persist_path
        +bool persist
    }

    class CacheEntry {
        +Any value
        +float created_at
        +float expires_at
        +int access_count
        +float last_access
        +is_expired() bool
        +touch()
    }

    CacheStore --> CacheStoreConfig
    CacheStore --> CacheEntry
```

### Eviction Policy State Machine

```mermaid
stateDiagram-v2
    [*] --> IDLE
    IDLE --> CHECKING: set() when size >= max_size
    CHECKING --> LRU_EVICT: policy = LRU
    CHECKING --> LFU_EVICT: policy = LFU
    CHECKING --> FIFO_EVICT: policy = FIFO
    LRU_EVICT --> IDLE: remove oldest last_access
    LFU_EVICT --> IDLE: remove lowest access_count
    FIFO_EVICT --> IDLE: remove oldest created_at
    CHECKING --> IDLE: evict() called directly
    IDLE --> CLEANUP: cleanup() triggered
    CLEANUP --> IDLE: remove expired entries
    IDLE --> SNAPSHOT: snapshot() called
    SNAPSHOT --> IDLE: return copy of cache
```

## BackupManager Architecture

```mermaid
classDiagram
    class BackupManager {
        -BackupPolicy policy
        -List~BackupRecord~ backups
        -Dict catalog
        -Optional~threading.Thread~ scheduler_thread
        -bool running
        +create_backup(source, type, metadata) BackupRecord
        +restore(backup_id, target) bool
        +list_backups(filters) List
        +delete_backup(backup_id) bool
        +verify(backup_id) bool
        +prune() int
        +schedule_backup(interval, source, type)
        +stop_scheduled()
        +integrity_check() Dict
        +export_catalog(path) void
    }

    class BackupPolicy {
        +str directory
        +BackupSchedule schedule
        +int keep_full
        +int keep_incremental
        +int keep_differential
        +int max_age_days
        +bool compression
        +bool verify_on_create
        +int max_backup_size
    }

    class BackupRecord {
        +str backup_id
        +str source
        +BackupType type
        +BackupStatus status
        +float created_at
        +float size
        +str path
        +str checksum
        +Dict metadata
        +to_dict()
    }

    class BackupSchedule {
        +str cron_expression
        +BackupType backup_type
        +Dict config
    }

    BackupManager --> BackupPolicy
    BackupManager --> BackupRecord
    BackupManager --> BackupSchedule
```

## MigrationManager Architecture

```mermaid
classDiagram
    class MigrationManager {
        -List~Migration~ migrations
        -Dict~str, MigrationStatus~ migration_table
        -MigrationConfig config
        +create(name, description, fn, reverse_fn) MigrationRecord
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

    class Migration {
        +str migration_id
        +str name
        +str description
        +MigrationType type
        +MigrationStatus status
        +int version
        +List~str~ dependencies
        +callable fn
        +callable reverse_fn
        +float created_at
        +float executed_at
        +Dict metadata
    }

    class MigrationRecord {
        +str migration_id
        +str name
        +str description
        +MigrationType type
        +int version
        +List dependencies
        +float created_at
        +float executed_at
        +Dict metadata
        +to_dict()
    }

    class MigrationConfig {
        +str table_name
        +str directory
        +bool auto_create
        +bool dry_run
        +int max_batch_size
        +bool check_circular_deps
    }

    MigrationManager --> Migration
    MigrationManager --> MigrationRecord
    MigrationManager --> MigrationConfig
```

## Storage Format Detection

The `FileStore.format_magic()` method detects the file format from content prefix:

```mermaid
flowchart TB
    DATA[Content bytes] --> MAGIC{First bytes}
    MAGIC -->|b'%YAML' or b'---'| YAML[FileFormat.YAML]
    MAGIC -->|b'{' or b'['| JSON[FileFormat.JSON]
    MAGIC -->|b'\\x80' pickle protocol| PICKLE[FileFormat.PICKLE]
    MAGIC -->|otherwise| UNKNOWN[FileFormat.UNKNOWN]

    YAML --> DECODE{Decode}
    JSON --> DECODE
    PICKLE --> DECODE
    DECODE --> RETURN[Return FileFormat]
```

## Lock-Free Atomic Writes

```mermaid
sequenceDiagram
    participant Client
    participant FS as FileStore
    participant TMP as temp file
    participant TARGET as target file

    Client->>FS: atomic_write("/path/file.yaml", data)
    FS->>FS: detect format from data
    FS->>FS: serialize data (yaml.dump / json.dumps / pickle.dumps)
    FS->>TMP: write to /path/.file.yaml.tmp
    TMP-->>FS: written
    FS->>FS: os.replace(tmp_path, target_path)
    FS->>TARGET: atomic rename
    FS-->>Client: True

    Note over FS: os.replace() is atomic on same filesystem<br/>If crash during write: .tmp file is cleaned<br/>on next startup
    Note over TARGET: If crash during rename:<br/>target is either old or new — never partial
```

## Index Data Structure

The `RuleIndex` maps rule names to file paths and maintains secondary indexes:

```mermaid
flowchart TB
    INDEX[RuleIndex]
    INDEX --> N2P["name_to_path: dict\n'my_rule' → '/rules/my_rule.yaml'"]
    INDEX --> TAG["tag_index: dict of lists\n'transform' → ['a', 'b']"]
    INDEX --> CREATED["created_index: dict of lists\n'2025-01-01' → ['a']"]

    N2P --> LOOKUP[O(1) name lookup]
    TAG --> TAG_LOOKUP[O(1) tag lookup, returns list]
    CREATED --> DATE_LOOKUP[O(1) date filter]
```

## Backup Types

```mermaid
flowchart TB
    BT[BackupType]
    BT --> FULL[FULL: complete copy of all data]
    BT --> INCREMENTAL[INCREMENTAL: changes since last backup]
    BT --> DIFFERENTIAL[DIFFERENTIAL: changes since last FULL]

    FULL --> SIZE["Largest, fastest to restore"]
    INCREMENTAL --> SIZE2["Smallest, slowest to restore"]
    DIFFERENTIAL --> SIZE3["Medium, medium to restore"]

    subgraph Restore Order
        FULL_R[Restore Full] --> INC_R[Apply all incrementals in order]
        FULL_R2[Restore Full] --> DIFF_R[Apply most recent differential]
    end
```

## Migration Types

```mermaid
flowchart LR
    MT[MigrationType]
    MT --> SCHEMA[SCHEMA: structural changes]
    MT --> DATA[DATA: data transformation]
    MT --> INDEX[INDEX: index rebuild]
    MT --> CONFIG[CONFIG: configuration change]
    MT --> CUSTOM[CUSTOM: user-defined]

    SCHEMA --> DIR[forward/reverse direction]
    DATA --> DIR
    INDEX --> DIR
    CONFIG --> DIR
    CUSTOM --> DIR
```

## Thread Safety

```mermaid
flowchart TB
    subgraph Thread-Safe
        RS[RuleStorage: threading.Lock]
        FS[FileStore: FileLock per file]
        CS[CacheStore: threading.Lock]
    end

    subgraph Not Thread-Safe
        BK[BackupManager: sequential operations]
        MG[MigrationManager: sequential migrations]
    end

    T1[Thread 1] --> RS
    T2[Thread 2] --> RS
    RS --> FS
    RS --> CS
    RS --> BK
    RS --> MG

    note for FS: FileLock prevents concurrent writes to same file
    note for CS: CacheStore lock protects internal dict during eviction
```

The `RuleStorage` uses a single `threading.Lock` to protect all public methods. This ensures that read/write/delete operations on the index are serialized. The `FileStore` relies on the filesystem-level `FileLock` for multi-process safety. The `CacheStore` uses a lock to protect its internal dict and eviction heap during concurrent access.
