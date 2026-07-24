# Utility Module Architecture

## Overview

The Utility Module provides a service bus architecture where cross-cutting concerns are implemented as standalone services consumed by all other modules. The architecture separates infrastructure concerns (validation, caching, config, rate limiting, serialization) from business logic.

## Service Bus Architecture

```mermaid
flowchart TD
    subgraph Consumers["Consumer Modules"]
        A[Core Module]
        B[Learning Module]
        C[Memory Module]
        D[Monitoring]
    end

    subgraph Bus["Utility Service Bus"]
        direction LR
        V[Validators]
        S[Serializers]
        CM[CacheManager]
        CL[ConfigLoader]
        RL[RateLimiter]
    end

    subgraph Internal["Internal Components"]
        V1[Structure Validator]
        V2[Dependency Validator]
        V3[Temporal Validator]
        V4[Range Validator]
        V5[Schema Validator]
        S1[JSON Serializer]
        S2[JSONL Serializer]
        S3[Binary Serializer]
        CM1[TTL Manager]
        CM2[LRU Evictor]
        CL1[File Loader]
        CL2[Env Loader]
        CL3[Config Distributor]
        RL1[Token Bucket]
        RL2[Refill Engine]
    end

    A --> V
    A --> S
    A --> CM
    A --> CL
    A --> RL

    B --> V
    B --> S
    B --> CM
    B --> CL

    C --> V
    C --> S
    C --> CM
    C --> CL

    D --> V
    D --> CM
    D --> CL

    V --> V1
    V --> V2
    V --> V3
    V --> V4
    V --> V5
    S --> S1
    S --> S2
    S --> S3
    CM --> CM1
    CM --> CM2
    CL --> CL1
    CL --> CL2
    CL --> CL3
    RL --> RL1
    RL --> RL2
```

## Component Architecture

### UtilityValidators

Provides validation services for data integrity, structure, and constraints.

```python
class UtilityValidators:
    def __init__(self, config: ValidatorConfig = None):
        self.config = config or ValidatorConfig()

    def validate_structure(self, target: Any) -> ValidationResult:
        if isinstance(target, dict):
            missing = [f for f in self.config.required_fields if f not in target]
            if missing:
                return ValidationResult(False, 0.0, [f"Missing: {missing}"])
        return ValidationResult(True, 1.0, [])

    def validate_dependencies(self, target: Any) -> ValidationResult:
        deps = getattr(target, 'metadata', {}).get('depends_on', [])
        if deps:
            return ValidationResult(False, 0.5, [f"Unresolved deps: {deps}"])
        return ValidationResult(True, 1.0, [])

    def validate_temporal(self, target: Any) -> ValidationResult:
        valid_until = getattr(target, 'valid_until', None)
        if valid_until and valid_until < datetime.now(timezone.utc):
            return ValidationResult(False, 0.0, ["Expired"])
        return ValidationResult(True, 1.0, [])
```

### Serializers

Handles data serialization across multiple formats.

```python
class Serializers:
    @staticmethod
    def serialize_json(data: Any, pretty: bool = False) -> str:
        class DateTimeEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, datetime.datetime):
                    return obj.isoformat()
                if isinstance(obj, uuid.UUID):
                    return str(obj)
                if isinstance(obj, Decimal):
                    return float(obj)
                return super().default(obj)
        indent = 2 if pretty else None
        return json.dumps(data, cls=DateTimeEncoder, indent=indent)

    @staticmethod
    def serialize_binary(obj: Any) -> bytes:
        return pickle.dumps(obj)
```

### CacheManager

Provides centralized cache management across namespaces.

```python
class CacheManager:
    def __init__(self, config: CacheConfig = None):
        self.config = config or CacheConfig()
        self.namespaces: Dict[str, Dict[str, CacheEntry]] = {}

    def get(self, namespace: str, key: str) -> Any:
        ns = self.namespaces.get(namespace, {})
        entry = ns.get(key)
        if not entry:
            return None
        if self._is_expired(entry):
            del ns[key]
            return None
        entry.last_accessed = datetime.now(timezone.utc)
        entry.access_count += 1
        return entry.value
```

### ConfigLoader

Loads and distributes configuration from multiple sources.

```python
class ConfigLoader:
    def __init__(self, config: ConfigLoaderConfig = None):
        self.config = config or ConfigLoaderConfig()
        self.config_data: Dict[str, Any] = {}

    def load(self, filepath: str) -> Dict:
        if filepath.endswith('.yaml') or filepath.endswith('.yml'):
            with open(filepath, 'r') as f:
                self.config_data = yaml.safe_load(f)
        elif filepath.endswith('.json'):
            with open(filepath, 'r') as f:
                self.config_data = json.load(f)
        return self.config_data

    def load_from_env(self, prefix: str = "APP_") -> Dict:
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower().replace('__', '.')
                self._set_nested(config_key, value)
        return self.config_data
```

### RateLimiter

Implements the token bucket algorithm for rate limiting.

```python
class RateLimiter:
    def __init__(self, config: RateLimiterConfig = None):
        self.config = config or RateLimiterConfig()
        self.buckets: Dict[str, TokenBucket] = {}

    def check(self, client_id: str) -> bool:
        bucket = self._get_bucket(client_id)
        self._refill(bucket)
        return bucket.tokens >= 1

    def consume(self, client_id: str, tokens: float = 1.0) -> bool:
        bucket = self._get_bucket(client_id)
        self._refill(bucket)
        if bucket.tokens >= tokens:
            bucket.tokens -= tokens
            return True
        return False
```

## Supporting System Architectures

### Verifier System Architecture

The Verifier implements a multi-stage verification pipeline.

```mermaid
flowchart LR
    subgraph Input["Input"]
        A[Target Rule / Pattern]
    end

    subgraph Stage1["Stage 1: Structure"]
        B[verify_structure]
        B1{Syntax valid?}
    end

    subgraph Stage2["Stage 2: Dependencies"]
        C[verify_dependencies]
        C1{All deps met?}
    end

    subgraph Stage3["Stage 3: Temporal"]
        D[verify_temporal]
        D1{Within valid window?}
    end

    subgraph Stage4["Stage 4: Confidence"]
        E[verify_confidence]
        E1{Confidence > threshold?}
    end

    subgraph Stage5["Stage 5: Knowledge"]
        F[verify_against_knowledge]
        G[verify_against_inferences]
    end

    subgraph Output["Output"]
        H{All checks passed?}
        I[VerificationResult]
    end

    A --> B
    B --> B1
    B1 --> C
    C --> C1
    C1 --> D
    D --> D1
    D1 --> E
    E --> E1
    E1 --> F
    F --> G
    G --> H
    H -->|yes| I
    H -->|no| I
```

### Refiner System Architecture

```mermaid
flowchart TD
    subgraph Input["Input"]
        A[Verification Results]
        B[Feedback Data]
        C[Rule / Pattern Store]
    end

    subgraph Analysis["Analysis"]
        D[Identify underperforming rules]
        E[Detect duplicate patterns]
        F[Find generalization opportunities]
        G[Find specialization opportunities]
    end

    subgraph Transform["Transformation Selection"]
        H{What refinement type?}
        I1[Generalize: broaden conditions]
        I2[Specialize: narrow conditions]
        I3[Merge: combine similar rules]
        I4[Split: separate concerns]
        I5[Tune: adjust threshold]
        I6[Template: extract parameterized form]
    end

    subgraph Validation["Validation"]
        J[Compute before/after metrics]
        K{Improvement > minimum?}
        L[Rollback: restore snapshot]
        M[Confirm: keep refinement]
    end

    A --> D
    B --> D
    C --> D
    C --> E
    C --> F
    C --> G
    D --> H
    E --> H
    F --> H
    G --> H
    H --> I1
    H --> I2
    H --> I3
    H --> I4
    H --> I5
    H --> I6
    I1 --> J
    I2 --> J
    I3 --> J
    I4 --> J
    I5 --> J
    I6 --> J
    J --> K
    K -->|yes| M
    K -->|no| L
    M --> N[Create RefinementRecord]
    L --> N
    N --> O[Log to history]
```

### Lifecycle Manager Architecture

```mermaid
stateDiagram-v2
    [*] --> Draft: create_rule()
    Draft --> PendingReview: submit_for_review()
    PendingReview --> Draft: request_changes()
    PendingReview --> Active: approve()
    Active --> Monitor: activate_monitoring()
    Monitor --> Active: monitoring_passed()
    Monitor --> Suspended: monitoring_failed()
    Suspended --> PendingReview: revised()
    Suspended --> Deprecated: deprecated()
    Active --> Updated: new_version_available()
    Updated --> Active: version_promoted()
    Active --> Archived: archive()
    Archived --> Active: restore()
    Archived --> Deprecated: aged_out()
    Deprecated --> Purged: purge()
    Purged --> [*]: removed
```

### Monitor Architecture

```mermaid
flowchart LR
    subgraph Sources["Data Sources"]
        A1[Pattern Engine]
        A2[Model Trainer]
        A3[Feedback Learner]
        A4[System Metrics]
    end

    subgraph Collection["Metric Collection"]
        B1[record_metric API]
        B2[Metric Buffer]
        B3[Metric Store]
    end

    subgraph Analysis["Analysis"]
        C1[Threshold Checker]
        C2[Trend Analyzer]
        C3[Anomaly Detector]
    end

    subgraph Alerting["Alerting"]
        D1[Alert Generator]
        D2[Alert Rules Engine]
        D3[Alert Store]
    end

    subgraph Output["Outputs"]
        E1[Dashboard]
        E2[Notifications]
        E3[Status API]
    end

    A1 --> B1
    A2 --> B1
    A3 --> B1
    A4 --> B1
    B1 --> B2
    B2 --> B3
    B3 --> C1
    B3 --> C2
    B3 --> C3
    C1 --> D1
    C2 --> D1
    C3 --> D1
    D2 --> D1
    D1 --> D3
    D3 --> E1
    D3 --> E2
    D3 --> E3
```

### Migration Architecture

```mermaid
flowchart TD
    subgraph Plan["Planning Phase"]
        A[Source Module] --> B[Detect current version]
        B --> C[Compare with target version]
        C --> D{Upgrade needed?}
        D -->|no| E[No action]
        D -->|yes| F[Select migration path]
        F --> G[Estimate impact & duration]
        G --> H[Create MigrationPlan]
    end

    subgraph Execute["Execution Phase"]
        H --> I{Requires downtime?}
        I -->|yes| J[Enter maintenance mode]
        I -->|no| K[Start online migration]
        J --> L[Backup current state]
        K --> L
        L --> M[Apply transformation rules]
        M --> N{Items to process?}
        N -->|yes| M
        N -->|no| O[Validate target state]
        O --> P{Validation passed?}
        P -->|yes| Q[Commit migration]
        P -->|no| R[Rollback]
        R --> L
    end

    subgraph Verify["Verification Phase"]
        Q --> S[Re-verify migrated items]
        S --> T[Update version metadata]
        T --> U[Log MigrationRecord]
    end
```

## Configuration Architecture

All utility components follow a consistent dataclass-based configuration pattern.

```python
@dataclass
class ValidatorConfig:
    required_fields: List[str] = field(default_factory=lambda: ["conditions", "actions"])
    enable_structure_check: bool = True
    enable_dependency_check: bool = True

@dataclass
class CacheConfig:
    max_capacity_per_namespace: int = 1000
    default_ttl_seconds: float = 300.0
    max_namespaces: int = 50
    enable_stats: bool = True

@dataclass
class ConfigLoaderConfig:
    config_dir: str = "./config"
    auto_reload: bool = False
    reload_interval_seconds: int = 60
    env_prefix: str = "APP_"

@dataclass
class RateLimiterConfig:
    default_capacity: float = 100.0
    default_refill_rate: float = 10.0
    refill_interval_seconds: float = 1.0
    max_buckets: int = 10000
```

## Class Relationships

```mermaid
classDiagram
    class UtilityValidators {
        +ValidatorConfig config
        +validate_structure(target) ValidationResult
        +validate_dependencies(target) ValidationResult
        +validate_temporal(target) ValidationResult
        +validate_range(target, min_val, max_val) ValidationResult
        +validate_schema(target, schema) ValidationResult
    }
    class Serializers {
        +serialize_json(data, pretty) str
        +deserialize_json(text) Any
        +serialize_jsonl(objects) str
        +deserialize_jsonl(text) List
        +serialize_binary(obj) bytes
        +deserialize_binary(data) Any
    }
    class CacheManager {
        +CacheConfig config
        +Dict~str, Dict~str, CacheEntry~~ namespaces
        +get(namespace, key) Any
        +set(namespace, key, value, ttl) void
        +invalidate(namespace, key) bool
        +clear_namespace(namespace) int
        +get_stats(namespace) Dict
    }
    class ConfigLoader {
        +ConfigLoaderConfig config
        +Dict~str, Any~ config_data
        +load(filepath) Dict
        +load_from_env(prefix) Dict
        +get(key, default) Any
        +validate(schema) List~str~
        +distribute() Dict~str, Dict~
    }
    class RateLimiter {
        +RateLimiterConfig config
        +Dict~str, TokenBucket~ buckets
        +check(client_id) bool
        +consume(client_id, tokens) bool
        +get_remaining(client_id) int
        +reset(client_id) void
        +get_stats() Dict
    }
    class TokenBucket {
        +str client_id
        +float capacity
        +float refill_rate
        +float tokens
        +datetime last_refill
    }
    class CacheEntry {
        +str key
        +Any value
        +float ttl
        +datetime created_at
        +datetime last_accessed
        +int access_count
    }
    class ValidationResult {
        +bool passed
        +float score
        +List~str~ errors
        +Dict details
    }

    UtilityValidators --> ValidationResult
    CacheManager --> CacheEntry
    RateLimiter --> TokenBucket
```