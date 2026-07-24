# TypeScript SDK Architecture

## Class Hierarchy

```mermaid
classDiagram
    class Client {
        +string apiKey
        +string baseUrl
        +number timeout
        +constructor(config: ClientConfig)
        +validate(content: string): Promise~ValidationResult~
        +batchValidate(items: string[]): Promise~ValidationResult[]~
        +getRules(): Promise~Rule[]~
        +monitor(key: string): MonitoringClient
        +disconnect(): void
    }

    class RuleClient {
        +list(): Promise~Rule[]~
        +get(id: string): Promise~Rule~
        +create(rule: CreateRuleInput): Promise~Rule~
        +update(id: string, rule: UpdateRuleInput): Promise~Rule~
        +delete(id: string): Promise~void~
        +evaluate(ruleId: string, content: string): Promise~EvaluationResult~
    }

    class ValidationClient {
        +validate(content: string, options?: ValidationOptions): Promise~ValidationResult~
        +validateStream(content: string, callback: StreamCallback): Promise~void~
        +batchValidate(items: BatchInput): Promise~BatchResult~
        +getHistory(filters?: HistoryFilters): Promise~ValidationHistory~
    }

    class MonitoringClient {
        +trackEvent(name: string, data?: any): void
        +getMetrics(options?: MetricsOptions): Promise~Metrics~
        +subscribe(channel: string, handler: EventHandler): Subscription
        +unsubscribe(subscription: Subscription): void
    }

    class Models {
        <<namespace>>
    }

    class Rule {
        +string id
        +string name
        +string description
        +RuleSeverity severity
        +RuleCategory category
        +RuleAction action
        +string[] patterns
        +boolean enabled
        +Date createdAt
        +Date updatedAt
    }

    class ValidationResult {
        +bool passed
        +Violation[] violations
        +number score
        +number duration
        +ValidationMetadata metadata
    }

    class Violation {
        +string ruleId
        +string message
        +number line
        +number column
        +RuleSeverity severity
        +string suggestion
    }

    Client --> RuleClient : creates
    Client --> ValidationClient : creates
    Client --> MonitoringClient : creates
    Client --> Models : uses
    ValidationResult --> Violation : contains
    RuleClient --> Rule : returns
    ValidationClient --> ValidationResult : returns
```

## SDK Initialization Flow

```mermaid
flowchart TD
    A[Import SDK] --> B[Create ClientConfig]
    B --> C[Instantiate Client]
    C --> D{Valid Config?}
    D -->|No| E[Throw ConfigError]
    D -->|Yes| F[Initialize HTTP Transport]
    F --> G[Initialize Auth Handler]
    G --> H[Initialize Sub-Clients]
    H --> I[RuleClient]
    H --> J[ValidationClient]
    H --> K[MonitoringClient]
    I --> L[SDK Ready]
    J --> L
    K --> L
    L --> M[Emit 'ready' Event]
```

## System Components

```mermaid
C4Component
    title SDK Component Diagram - Core System Connection

    Component(sdk, "TypeScript SDK", "Package", "Client, RuleClient, ValidationClient, MonitoringClient")
    Component(http, "HTTP Transport", "Module", "Axios-based REST client with retry logic")
    Component(auth, "Auth Handler", "Module", "API key & JWT token management")
    Component(cache, "Cache Layer", "Module", "In-memory rule cache for performance")

    System_Ext(api, "REST API Server", "Core backend API endpoints")
    System_Ext(engine, "Rule Engine", "Pattern matching & validation engine")
    System_Ext(mon, "Monitoring Service", "Telemetry & alerting pipeline")

    Rel(sdk, api, "REST calls", "HTTPS/JSON")
    Rel(api, engine, "validation requests", "gRPC")
    Rel(sdk, mon, "metrics & events", "HTTPS")
    Rel(http, api, "HTTP requests")
    Rel(auth, api, "authenticated sessions")
    Rel(cache, sdk, "fast rule lookups")
```

## Component Descriptions

| Component | Description |
|-----------|-------------|
| **Client** | Main entry point. Accepts config, initializes sub-clients, manages lifecycle. |
| **RuleClient** | CRUD operations for validation rules. Supports listing, fetching, creating, updating, and deleting rules. |
| **ValidationClient** | Core validation logic. Supports single, batch, and streaming validation with configurable options. |
| **MonitoringClient** | Telemetry and event tracking. Subscribes to real-time channels and aggregates metrics. |
| **Models** | TypeScript types and interfaces for Rule, ValidationResult, Violation, and all supporting types. |
| **HTTP Transport** | Axios-based transport with retry, timeout, and error normalization. |
| **Auth Handler** | Manages API key header injection and optional JWT token refresh. |
| **Cache Layer** | In-memory LRU cache for rule definitions to reduce API calls. |
