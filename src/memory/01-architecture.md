# Memory Module Architecture

## Overview

The Memory Module implements a four-tier memory hierarchy inspired by cognitive architecture. The system provides specialized memory types for procedural, inference, long-term, short-term, metacognitive, and remembrance functions, along with operational caches and state management.

## Memory Architecture

```mermaid
flowchart TD
    subgraph System["System Boundary"]
        subgraph L1["L1: RuleCache"]
            RC[Fast rule lookup<br/>TTL-based expiration<br/>LRU eviction]
        end

        subgraph L2["L2: PatternCache"]
            PC[Pattern storage<br/>Score-based ranking<br/>TTL: 1 hour]
        end

        subgraph L3["L3: Context & Session"]
            CM[ContextMemory<br/>Execution context]
            SS[SessionState<br/>Session management]
        end

        subgraph L4["L4: Cognitive Memory"]
            STM[ShortTermMemory]
            LTM[LongTermMemory]
            PAM[ProceduralActionMemory]
            IM[InferenceMemory]
            MM[MetaCognitiveMemory]
            REM[RemembranceMemory]
        end

        subgraph Storage["Persistence"]
            RS[ResultStore<br/>Namespaced storage]
        end
    end

    RC --> PC
    PC --> STM
    PC --> LTM
    CM --> IM
    SS --> STM
    STM --> LTM
    LTM --> PAM
    LTM --> IM
    LTM --> REM
    PAM --> MM
    IM --> MM
    REM --> MM
    STM --> RS
    LTM --> RS
```

## Component Architecture

### RuleCache

The RuleCache provides fast-access caching for active rules. It uses LRU eviction with configurable TTL for each entry.

```python
class RuleCache:
    def __init__(self, config: CacheConfig = None):
        self.config = config or CacheConfig()
        self.entries: Dict[str, CacheEntry] = {}
        self.lru_list: List[str] = []
        self.hits = 0
        self.misses = 0
```

### ContextMemory

The ContextMemory tracks execution context across the system, storing variables and event logs per context ID.

```python
class ContextMemory:
    def __init__(self, config: ContextConfig = None):
        self.config = config or ContextConfig()
        self.context_variables: Dict[str, Any] = {}
        self.event_log: Dict[str, List[ContextEvent]] = {}
```

### PatternCache

The PatternCache stores discovered patterns with score-based ranking, enabling quick retrieval of top patterns.

```python
class PatternCache:
    def __init__(self, config: CacheConfig = None):
        self.config = config or CacheConfig()
        self.patterns: Dict[str, CachedPattern] = {}
        self.score_queue: List[Tuple[float, str]] = []
```

### ResultStore

The ResultStore provides namespaced persistent storage for computation results with versioning and metadata.

```python
class ResultStore:
    def __init__(self, config: StoreConfig = None):
        self.config = config or StoreConfig()
        self.store: Dict[str, Dict[str, StoredResult]] = {}
```

### SessionState

The SessionState manages ephemeral session data with automatic cleanup of expired sessions.

```python
class SessionState:
    def __init__(self, config: SessionConfig = None):
        self.config = config or SessionConfig()
        self.sessions: Dict[str, Session] = {}
```

## Cognitive Memory Architecture

### Procedural-Action Memory (PAM)

PAM stores learned procedures, rules, and action sequences — the "how-to" memory.

```mermaid
classDiagram
    class ProceduralActionMemory {
        +PAMConfig config
        +Dict~str, Rule~ rules
        +Dict~str, RuleTemplate~ rule_templates
        +Dict~str, Procedure~ procedures
        +Dict~str, List~ProcedureStep~~ procedure_steps
        +Dict~str, List~RuleVersion~~ rule_versions
        +List~ExecutionRecord~ execution_log
        +add_rule(name, desc, type, conds, actions, postconds) Rule
        +add_template(name, desc, params, cond_template, action_template) RuleTemplate
        +create_procedure(name, desc, trigger_type, conditions) Procedure
        +add_step(procedure_id, rule_id, order, params) ProcedureStep
        +get_rule(rule_id) Rule
        +get_applicable_rules(context) List~Rule~
        +execute_rule(rule_id, context) Dict
        +execute_procedure(procedure_id, context) Dict
        +update_confidence(rule_id, success) float
        +archive_rule(rule_id) bool
    }
    class Rule {
        +str rule_id
        +str name
        +str description
        +str rule_type
        +Dict conditions
        +Dict actions
        +Dict postconditions
        +float confidence
        +int occurrence_count
        +datetime last_used_at
        +float version
        +bool is_active
    }
    class Procedure {
        +str procedure_id
        +str name
        +str description
        +str trigger_type
        +Dict trigger_conditions
        +int step_count
        +float confidence
        +bool is_active
    }
    ProceduralActionMemory --> Rule : manages
    ProceduralActionMemory --> Procedure : manages
    Procedure --> ProcedureStep : contains
    ProcedureStep --> Rule : references
```

### Inference Memory (IM)

IM stores inference results — conclusions, predictions, and relationships derived from raw data with evidence chain tracking.

```mermaid
classDiagram
    class InferenceMemory {
        +IMConfig config
        +Dict~str, Inference~ inferences
        +Dict~str, List~Evidence~~ evidence_chains
        +Dict~str, InferenceMetadata~ inference_metadata
        +store_inference(conclusion, type, evidence_list, confidence) Inference
        +add_evidence(inference_id, source, type, value, weight, supports) Evidence
        +get_inference(inference_id) Inference
        +get_inferences_by_type(type) List~Inference~
        +get_active_inferences() List~Inference~
        +get_evidence_chain(inference_id) List~Evidence~
        +propagate_confidence(inference_id) float
        +invalidate_inference(inference_id) bool
        +merge_inferences(inference_ids) Inference
        +find_contradictions() List~Tuple~str, str~~
    }
    class Inference {
        +str inference_id
        +str conclusion
        +str inference_type
        +float confidence
        +datetime created_at
        +datetime valid_until
        +str status
        +Dict metadata
        +List~str~ tags
    }
    class Evidence {
        +str evidence_id
        +str inference_id
        +str source
        +str evidence_type
        +Any value
        +float weight
        +float confidence
        +datetime observed_at
        +Dict context
        +bool supports
    }
    InferenceMemory --> Inference : manages
    InferenceMemory --> Evidence : stores
    Inference --> Evidence : supported by
```

### Long-Term Memory (LTM)

LTM provides durable persistent storage for declarative knowledge — facts, entities, and relationships.

```mermaid
classDiagram
    class LongTermMemory {
        +LTMConfig config
        +Dict~str, Fact~ facts
        +Dict~str, Entity~ entities
        +Dict~str, Relationship~ relationships
        +Dict~str, List~str~~ entity_relationships
        +Dict~str, SemanticSchema~ schemas
        +add_fact(subject, predicate, object, confidence, source) Fact
        +add_entity(name, type, attributes) Entity
        +add_relationship(source_id, target_id, type, properties) Relationship
        +add_schema(name, type, definition) SemanticSchema
        +query_facts(subject, predicate, object) List~Fact~
        +get_entity(entity_id) Entity
        +get_entity_by_name(name) Entity
        +get_related_entities(entity_id, relationship_type) List~Entity~
        +get_entity_relationships(entity_id) List~Relationship~
        +update_fact_confidence(fact_id, confidence) float
        +invalidate_fact(fact_id) bool
        +export_knowledge_graph() Dict
    }
    class Fact {
        +str fact_id
        +str subject
        +str predicate
        +str object
        +float confidence
        +datetime valid_from
        +datetime valid_until
        +str source
        +Dict metadata
        +List~str~ tags
    }
    class Entity {
        +str entity_id
        +str name
        +str entity_type
        +Dict attributes
        +datetime last_updated
        +List~str~ aliases
        +Dict metadata
    }
    class Relationship {
        +str relationship_id
        +str source_entity_id
        +str target_entity_id
        +str relationship_type
        +Dict properties
        +float confidence
        +datetime valid_until
    }
    LongTermMemory --> Fact : stores
    LongTermMemory --> Entity : manages
    LongTermMemory --> Relationship : manages
    Entity --> Relationship : participates
```

### Short-Term Memory (STM)

STM provides ephemeral session-scoped storage for transient data with TTL-based eviction.

```mermaid
classDiagram
    class ShortTermMemory {
        +STMConfig config
        +Dict~str, STMEntry~ entries
        +List~STMEvent~ event_log
        +Dict~str, Any~ session_context
        +List~Tuple~str, int~~ priority_queue
        +store(key, value, type, priority, ttl) STMEntry
        +retrieve(key) Any
        +get_entry(entry_id) STMEntry
        +remove(key) bool
        +clear() void
        +get_all() List~STMEntry~
        +get_by_type(type) List~STMEntry~
        +get_priority_items(min_priority) List~STMEntry~
        +record_event(event_type, data, source) STMEvent
        +get_recent_events(count) List~STMEvent~
        +update_session(key, value) void
        +get_session(key) Any
        +evict_expired() int
        +evict_low_priority() int
    }
    class STMEntry {
        +str entry_id
        +str key
        +Any value
        +str entry_type
        +int priority
        +float ttl_seconds
        +datetime last_accessed_at
        +int access_count
    }
    class STMEvent {
        +str event_id
        +str event_type
        +Any data
        +datetime occurred_at
        +str source
        +Dict context
    }
    ShortTermMemory --> STMEntry : manages
    ShortTermMemory --> STMEvent : logs
```

### Metacognitive Memory (MM)

MM provides self-awareness and introspection — performance metrics, confidence calibration, and strategy tracking.

```mermaid
classDiagram
    class MetaCognitiveMemory {
        +MMConfig config
        +Dict~str, List~PerformanceRecord~~ performance_metrics
        +List~ConfidenceRecord~ confidence_history
        +Dict~str, StrategyMetrics~ strategy_effectiveness
        +List~LearningMilestone~ learning_progress
        +List~SelfAssessment~ self_assessments
        +record_performance(task_type, task_id, accuracy, latency, confidence, success) PerformanceRecord
        +record_confidence(target_id, target_type, predicted, actual) ConfidenceRecord
        +update_strategy_metrics(strategy_id, success) StrategyMetrics
        +record_milestone(milestone_type, description, metric_value) LearningMilestone
        +assess_self(aspect, score, rationale) SelfAssessment
        +get_performance_summary(task_type) Dict
        +get_best_strategy(task_type) str
        +get_calibration_curve() List~Tuple~
        +get_learning_trajectory() List~LearningMilestone~
        +detect_performance_degradation(task_type) bool
        +suggest_improvement() List~str~
    }
    class PerformanceRecord {
        +str record_id
        +str task_type
        +str task_id
        +float accuracy
        +float latency_ms
        +float confidence
        +datetime timestamp
        +Dict context
        +bool success
    }
    class ConfidenceRecord {
        +str record_id
        +str target_id
        +str target_type
        +float predicted_confidence
        +float actual_accuracy
        +float calibration_error
        +datetime timestamp
    }
    MetaCognitiveMemory --> PerformanceRecord : tracks
    MetaCognitiveMemory --> ConfidenceRecord : calibrates
    MetaCognitiveMemory --> StrategyMetrics : evaluates
```

### Remembrance Memory (REM)

REM provides recollection and association — episodic experience records with contextual embeddings.

```mermaid
classDiagram
    class RemembranceMemory {
        +REMConfig config
        +Dict~str, Experience~ experiences
        +Dict~str, np.ndarray~ context_embeddings
        +List~AnalogyMapping~ analogies
        +Dict~str, Lesson~ lessons
        +Dict~str, RecollectionTrigger~ recollection_triggers
        +store_experience(situation_type, context, actions, outcome) Experience
        +recall(context, limit) List~Experience~
        +recall_by_similarity(context_vector, limit) List~Experience~
        +create_analogy(source_id, target_domain, source_features, target_features) AnalogyMapping
        +extract_lesson(experience_id) Lesson
        +add_trigger(name, conditions, experience_id, threshold) RecollectionTrigger
        +get_experience(experience_id) Experience
        +get_analogies_for_context(context) List~AnalogyMapping~
        +get_applicable_lessons(situation_type) List~Lesson~
        +compute_salience(experience) float
        +consolidate() int
    }
    class Experience {
        +str experience_id
        +str situation_type
        +Dict context
        +Dict actions_taken
        +Dict outcome
        +float salience_score
        +float retention_priority
        +datetime occurred_at
        +int recall_count
        +List~str~ tags
    }
    class AnalogyMapping {
        +str analogy_id
        +str source_experience_id
        +str target_domain
        +Dict source_features
        +Dict target_features
        +float similarity_score
        +float transfer_effectiveness
    }
    class Lesson {
        +str lesson_id
        +str lesson_text
        +str domain
        +List~str~ applicable_situations
        +float confidence
        +int times_applied
    }
    RemembranceMemory --> Experience : stores
    RemembranceMemory --> AnalogyMapping : manages
    RemembranceMemory --> Lesson : derives
    Experience --> AnalogyMapping : source
```

## Data Model Relationships

```mermaid
erDiagram
    Rule {
        string rule_id PK
        string name
        float confidence
        bool is_active
    }
    RuleTemplate {
        string template_id PK
        string name
        list parameters
    }
    Procedure {
        string procedure_id PK
        string name
        int step_count
    }
    ProcedureStep {
        string step_id PK
        string procedure_id FK
        string rule_id FK
        int step_order
    }
    RuleVersion {
        string version_id PK
        string rule_id FK
        int version_number
    }
    ExecutionRecord {
        string execution_id PK
        string rule_id FK
        bool success
    }
    Inference {
        string inference_id PK
        string conclusion
        float confidence
    }
    Evidence {
        string evidence_id PK
        string inference_id FK
        float weight
        bool supports
    }
    InferenceDependency {
        string dependency_id PK
        string inference_id FK
        string depends_on_inference_id FK
    }
    Fact {
        string fact_id PK
        string subject
        string predicate
        string object
    }
    Entity {
        string entity_id PK
        string name
        string entity_type
    }
    Relationship {
        string relationship_id PK
        string source_entity_id FK
        string target_entity_id FK
        string relationship_type
    }
    Experience {
        string experience_id PK
        string situation_type
        float salience_score
    }
    AnalogyMapping {
        string analogy_id PK
        string source_experience_id FK
        string target_domain
        float similarity_score
    }
    STMEntry {
        string entry_id PK
        string key
        int priority
        float ttl_seconds
    }
    PerformanceRecord {
        string record_id PK
        string task_type
        float accuracy
    }
    ConfidenceRecord {
        string record_id PK
        string target_id
        float calibration_error
    }

    Rule ||--o{ RuleVersion : has
    Procedure ||--o{ ProcedureStep : contains
    ProcedureStep }o--|| Rule : references
    Rule ||--o{ ExecutionRecord : logs
    Inference ||--o{ Evidence : supported_by
    Inference ||--o{ InferenceDependency : depends_on
    Entity ||--o{ Relationship : source
    Entity ||--o{ Relationship : target
    Fact ||--o{ Fact : versions
    Experience ||--o{ AnalogyMapping : source
    Experience ||--o{ RecollectionTrigger : triggers
```

## Configuration Architecture

```python
@dataclass
class CacheConfig:
    max_capacity: int = 1000
    default_ttl_seconds: float = 300.0
    enable_lru_eviction: bool = True
    eviction_batch_size: int = 50

@dataclass
class ContextConfig:
    max_contexts: int = 100
    max_events_per_context: int = 1000
    enable_event_logging: bool = True

@dataclass
class StoreConfig:
    max_namespaces: int = 50
    max_results_per_namespace: int = 10000
    enable_versioning: bool = True

@dataclass
class SessionConfig:
    session_timeout_minutes: int = 30
    max_sessions: int = 1000
    cleanup_interval_seconds: int = 300
```