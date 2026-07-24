# Storage Module — Data Flow

## 1. Read Flow

```mermaid
sequenceDiagram
    participant Client
    participant RS as RuleStorage
    participant IDX as RuleIndex
    participant CS as CacheStore
    participant FS as FileStore

    Client->>RS: read("my_rule", store_name="default")
    RS->>RS: acquire lock
    RS->>IDX: lookup("my_rule")
    IDX-->>RS: "/rules/my_rule.yaml"

    alt use_cache and cache hit
        RS->>CS: get("my_rule")
        CS-->>RS: cached data
        RS-->>Client: deserialized rule
    else cache miss or no cache
        RS->>FS: read("/rules/my_rule.yaml")
        FS->>FS: open file
        FS->>FS: detect format from magic bytes
        FS->>FS: deserialize (yaml/json/pickle)
        FS-->>RS: dict
        RS->>CS: set("my_rule", dict, ttl)
        RS-->>Client: dict
    end

    RS->>RS: release lock
```

### Read Strategy Decision Tree

```mermaid
flowchart TB
    START[read(name)] --> CHECK{Exists in index?}
    CHECK -->|no| ERROR[Raise FileNotFoundError]
    CHECK -->|yes| PATH[Get path from index]
    PATH --> CACHE{use_cache enabled?}
    CACHE -->|yes| HIT{Cache hit?}
    HIT -->|yes, fresh| RETURN_CACHE[Return cached value]
    HIT -->|miss/expired| READ_FS
    CACHE -->|no| READ_FS[FileStore.read]
    READ_FS --> DESER[Deserialize raw bytes]
    DESER --> CACHE_STORE[CacheStore.set]
    CACHE_STORE --> RETURN[Return parsed rule]
```

## 2. Write Flow

```mermaid
sequenceDiagram
    participant Client
    participant RS as RuleStorage
    participant IDX as RuleIndex
    participant CS as CacheStore
    participant FS as FileStore

    Client->>RS: write("my_rule", rule_data, fmt="yaml")
    RS->>RS: acquire lock
    RS->>RS: detect format (param > config > magic)
    RS->>FS: atomic_write("/rules/my_rule.yaml", serialized)
    FS->>FS: temp file → os.replace
    FS-->>RS: True
    RS->>IDX: add("my_rule", "/rules/my_rule.yaml", tags)
    RS->>CS: set("my_rule", rule_data, ttl)
    RS->>RS: update stats
    RS->>RS: release lock
    RS-->>Client: True
```

### Write Strategy Decision Tree

```mermaid
flowchart TB
    START[write(name, data)] --> EXISTS{Already exists?}
    EXISTS -->|yes| OVERWRITE{Overwrite allowed?}
    OVERWRITE -->|no| ERROR[Raise or skip]
    OVERWRITE -->|yes| PROCEED
    EXISTS -->|no| PROCEED

    PROCEED --> FMT{Format specified?}
    FMT -->|yes| USE_FMT[Use specified format]
    FMT -->|none| CONFIG_FMT[Use config.default_format]
    CONFIG_FMT -->|yaml| YAML
    CONFIG_FMT -->|json| JSON
    CONFIG_FMT -->|pickle| PICKLE

    USE_FMT --> YAML[yaml.dump]
    USE_FMT --> JSON[json.dumps]
    USE_FMT --> PICKLE[pickle.dumps]

    YAML --> WRITE[Write serialized bytes]
    JSON --> WRITE
    PICKLE --> WRITE

    WRITE --> ATOMIC{atomic_writes?}
    ATOMIC -->|yes| TMP[Write to .tmp file]
    TMP --> RENAME[os.replace → target]
    ATOMIC -->|no| DIRECT[Write directly to path]
    DIRECT --> DONE[Done]
    RENAME --> DONE
    DONE --> INDEX[Update RuleIndex]
    INDEX --> CACHE[Update CacheStore]
    CACHE --> RETURN[Return True]
```

## 3. Delete Flow

```mermaid
sequenceDiagram
    participant Client
    participant RS as RuleStorage
    participant IDX as RuleIndex
    participant CS as CacheStore
    participant FS as FileStore

    Client->>RS: delete("my_rule")
    RS->>RS: acquire lock
    RS->>IDX: lookup("my_rule")
    IDX-->>RS: "/rules/my_rule.yaml"
    RS->>FS: delete("/rules/my_rule.yaml")
    FS->>FS: os.remove()
    FS-->>RS: True
    RS->>IDX: remove("my_rule")
    RS->>CS: delete("my_rule")
    RS->>RS: release lock
    RS-->>Client: True
```

## 4. Search Flow

```mermaid
flowchart TB
    START[search(pattern)] --> INDEX[Get all names from index]
    INDEX --> FILTER[For each name: re.search(pattern, name)]
    FILTER --> MATCHES[Collect matching names]
    MATCHES --> RESOLVE[For each match: get path from index]
    RESOLVE --> READ[For each path: FileStore.read]
    READ --> DESER[Deserialize]
    DESER --> COLLECT[Collect into list]
    COLLECT --> RETURN[List[dict]]

    note right of INDEX: Uses re.search, not fnmatch<br/>Pattern "trans.*" matches "transform_rule"
```

## 5. Cache Flow

### Get-or-Compute

```mermaid
sequenceDiagram
    participant Client
    participant CS as CacheStore

    Client->>CS: get_or_compute("key", factory_fn, ttl=60)
    CS->>CS: check internal dict for "key"
    alt Hit (exists and not expired)
        CS->>CS: touch entry (update last_access, access_count)
        CS-->>Client: value
    else Miss
        CS->>Client: call factory_fn()  # Note: Client provides factory
        Client-->>CS: computed_value
        alt size >= max_size
            CS->>CS: evict(1) per policy
        end
        CS->>CS: create CacheEntry(value, ttl)
        CS->>CS: store in dict
        CS-->>Client: computed_value
    end
```

### Eviction Flow

```mermaid
flowchart TB
    TRIGGER{Eviction trigger}
    TRIGGER -->|set() when size >= max_size| EVICT[evict(count)]
    TRIGGER -->|explicit evict(n)| EVICT
    TRIGGER -->|cleanup()| CLEANUP[Remove expired entries only]

    EVICT --> POLICY{Eviction Policy}
    POLICY -->|LRU| LRU[Sort by last_access ascending]
    POLICY -->|LFU| LFU[Sort by access_count ascending]
    POLICY -->|FIFO| FIFO[Sort by created_at ascending]

    LRU --> REMOVE[Remove first N entries]
    LFU --> REMOVE
    FIFO --> REMOVE
    REMOVE --> UPDATE[Update size]
    UPDATE --> DONE[Return number evicted]
```

### Cleanup Flow

```mermaid
sequenceDiagram
    participant Client
    participant CS as CacheStore

    Client->>CS: cleanup()
    CS->>CS: iterate all entries
    loop for each entry
        CS->>CS: check entry.is_expired()
        alt expired
            CS->>CS: delete entry
            CS->>CS: decrement current_size
        end
    end
    CS-->>Client: number_cleaned
```

## 6. Backup Flow

### Create Backup

```mermaid
sequenceDiagram
    participant Client
    participant BK as BackupManager
    participant FS as FileStore

    Client->>BK: create_backup(source="/rules", type=FULL)
    BK->>BK: generate backup_id (uuid)
    BK->>BK: determine backup path

    alt FULL
        BK->>FS: list_files("*")
        FS-->>BK: [file paths]
        loop for each file
            BK->>FS: read(path)
            FS-->>BK: file content
        end
    else INCREMENTAL
        BK->>BK: find last backup timestamp
        BK->>FS: list_files("*")
        FS-->>BK: [file paths]
        loop for each file
            BK->>FS: read(path)
            FS-->>BK: file content
            BK->>BK: compare mtime vs last backup
            alt changed or new
                BK->>BK: include in backup
            end
        end
    else DIFFERENTIAL
        BK->>BK: find last FULL backup timestamp
        BK->>FS: list_files("*")
        loop for each file
            BK->>FS: read + check mtime vs last FULL
            alt changed
                BK->>BK: include
            end
        end
    end

    BK->>BK: serialize backup data
    BK->>BK: compute checksum
    BK->>FS: atomic_write(backup_path, data)
    FS-->>BK: True
    BK->>BK: create BackupRecord
    BK->>BK: update catalog
    BK->>BK: if verify_on_create: verify(backup_id)
    BK-->>Client: BackupRecord
```

### Restore Backup

```mermaid
sequenceDiagram
    participant Client
    participant BK as BackupManager
    participant FS as FileStore

    Client->>BK: restore("backup-uuid", target="/restore/rules")
    BK->>BK: find BackupRecord by backup_id
    alt Not found
        BK-->>Client: raise BackupError
    end
    BK->>FS: read(backup_record.path)
    FS-->>BK: serialized backup data
    BK->>BK: verify checksum
    BK->>BK: deserialize backup content

    alt target provided
        BK->>FS: write to target directory
    else no target
        BK->>BK: restore to original paths
    end

    loop for each file in backup
        BK->>FS: atomic_write(target_path, file_content)
        FS-->>BK: True
    end

    BK->>BK: update BackupRecord status = RESTORED
    BK-->>Client: True
```

### Prune Flow

```mermaid
flowchart TB
    PRUNE[prune()] --> GROUP[Group backups by source]
    GROUP --> FILTER[For each source: apply retention policy]

    FILTER --> FULL_KEEP[Keep n most recent FULL]
    FULL_KEEP --> INC_KEEP[Keep m most recent INCREMENTAL]
    INC_KEEP --> DIFF_KEEP[Keep p most recent DIFFERENTIAL]
    DIFF_KEEP --> AGE[Remove backups older than max_age_days]
    AGE --> DELETE[Delete remaining backups]
    DELETE --> UPDATE_CAT[Update catalog]
    UPDATE_CAT --> RETURN[Return count deleted]
```

## 7. Migration Flow

### Run Migrations

```mermaid
sequenceDiagram
    participant Client
    participant MG as MigrationManager
    participant FS as FileStore

    Note over MG: Startup loads migration table from disk
    Client->>MG: migrate(target_version="2.0")
    MG->>MG: load migration table (executed migrations)
    MG->>MG: list all available migrations
    MG->>MG: sort by version, resolve dependencies
    MG->>MG: compute pending = available - executed
    MG->>MG: filter pending <= target_version
    MG->>MG: topologically sort pending

    loop for each pending migration
        MG->>MG: check dependencies satisfied
        MG->>FS: run migration.fn()
        FS-->>MG: success
        MG->>MG: update migration_table status = EXECUTED
        MG->>MG: persist migration table
    end

    alt all succeeded
        MG-->>Client: True
    else any failed
        MG->>MG: mark failed in migration_table
        MG-->>Client: False
    end
```

### Rollback Flow

```mermaid
sequenceDiagram
    participant Client
    participant MG as MigrationManager

    Client->>MG: rollback(target_version="1.0")
    MG->>MG: list executed migrations >= target_version
    MG->>MG: reverse sort by version (descending)
    MG->>MG: check all have reverse_fn defined

    loop for each migration to rollback
        alt reverse_fn exists
            MG->>MG: run reverse_fn()
            MG->>MG: update status = REVERTED
        else no reverse_fn
            MG-->>Client: raise IrreversibleMigrationError
        end
    end
    MG-->>Client: True
```

### Dry Run

```mermaid
sequenceDiagram
    participant Client
    participant MG as MigrationManager

    Client->>MG: dry_run(target_version="2.0")
    MG->>MG: compute pending migrations
    MG->>MG: build execution plan (order, deps)
    MG->>MG: for each, check reverse_fn exists
    MG-->>Client: [migration_1: will_execute, migration_2: will_execute, ...]
    Note over MG: No actual migration fn is called
```

## 8. RuleStorage Stats Flow

```mermaid
sequenceDiagram
    participant Client
    participant RS as RuleStorage
    participant IDX as RuleIndex
    participant FS as FileStore

    Client->>RS: stats()
    RS->>IDX: size()
    IDX-->>RS: total_rules
    RS->>RS: iterate stores
    loop for each store
        RS->>FS: list_files()
        FS-->>RS: [files]
        RS->>RS: count per format
        RS->>RS: compute total size
    end
    RS-->>Client: {total_rules: 42, stores: {default: {yaml: 30, json: 12}}, index_size: 42, cache_size: 18}
```

## 9. Full Lifecycle: Rule Write with Backup

```mermaid
sequenceDiagram
    participant App
    participant RS as RuleStorage
    participant FS as FileStore
    participant CS as CacheStore
    participant IDX as RuleIndex
    participant BK as BackupManager

    App->>RS: write("new_rule", {...})
    RS->>FS: atomic_write("rules/new_rule.yaml", data)
    FS-->>RS: True
    RS->>IDX: add("new_rule", path, tags)
    RS->>CS: set("new_rule", data, ttl=300)
    RS-->>App: True

    Note over RS: Time passes...

    App->>BK: create_backup(source="rules", type=DIFFERENTIAL)
    BK->>FS: list_files("rules/*")
    FS-->>BK: [files with mtimes]
    BK->>BK: filter by mtime > last_full
    BK->>FS: read("rules/new_rule.yaml")
    FS-->>BK: content
    BK->>BK: compress, checksum
    BK->>FS: atomic_write("backups/diff_20250101.zip")
    FS-->>BK: True
    BK->>BK: update catalog
    BK-->>App: BackupRecord(id="diff_...", type=DIFFERENTIAL)

    Note over RS: On restore...

    App->>BK: restore("full_20250101", target="./restore")
    BK->>FS: read("backups/full_20250101.zip")
    FS-->>BK: content
    BK->>BK: verify checksum
    BK->>FS: atomic_write("restore/new_rule.yaml", data)
    FS-->>BK: True
    BK-->>App: True
```

## 10. Pipeline: Migrate After Write

```mermaid
flowchart TB
    WRITE[write() detects schema version mismatch] --> MIGRATE[call migration_manager.migrate()]
    MIGRATE --> LOAD_MIG[load migration files]
    LOAD_MIG --> SORT[sort by version]
    SORT --> EXEC[execute pending]
    EXEC --> MARK[mark as EXECUTED]
    MARK --> WRITE_RETRY[retry write with new schema]
    WRITE_RETRY --> SUCCESS[write succeeds]
```

## 11. Error Recovery Flows

### Atomic Write Failure Recovery

```mermaid
flowchart TB
    WRITE[atomic_write start] --> TMP[Write to .tmp file]
    TMP --> CRASH{System crash?}
    CRASH -->|during tmp write| RECOVER[On restart: clean stale .tmp files]
    RECOVER --> RETRY[Next write proceeds normally]
    CRASH -->|during os.replace| PARTIAL[Target file is intact \n(old version preserved)]
    PARTIAL --> RETRY2[Next write retries]
    TMP -->|success| RENAME[os.replace]
    RENAME -->|success| DONE[Done]
```

### Cache Corruption Recovery

```mermaid
sequenceDiagram
    participant Client
    participant CS as CacheStore

    CS->>CS: get("key")
    alt entry data corrupt
        CS->>CS: catch deserialization error
        CS->>CS: delete corrupted entry
        CS-->>Client: None (cache miss)
    else entry expired
        CS->>CS: delete expired entry
        CS-->>Client: None (cache miss)
    end
```

### Backup Verification Failure

```mermaid
sequenceDiagram
    participant Client
    participant BK as BackupManager
    participant FS as FileStore

    Client->>BK: verify("backup-uuid")
    BK->>FS: read(backup_record.path)
    FS-->>BK: serialized data
    BK->>BK: compute checksum of data
    BK->>BK: compare with stored checksum
    alt Match
        BK-->>Client: True
    else Mismatch
        BK->>BK: update status = CORRUPTED
        BK-->>Client: False
    end
```
