# Python SDK Architecture

## Class Hierarchy

```mermaid
classDiagram
    class Client {
        +str base_url
        +str api_key
        +int timeout
        +__init__(base_url, api_key, timeout)
        +request(method, path, data)
    }
    class RuleClient {
        +list_rules() List[Rule]
        +get_rule(id) Rule
        +create_rule(rule) Rule
        +update_rule(id, rule) Rule
        +delete_rule(id) bool
    }
    class ValidationClient {
        +validate_content(content) ValidationResult
        +validate_batch(items) List[ValidationResult]
        +get_status(id) ValidationStatus
    }
    class MonitoringClient {
        +get_alerts(filters) List[Alert]
        +get_metrics(duration) Metrics
        +subscribe_events(callback) Subscription
    }
    class Models {
        +Rule
        +ValidationResult
        +Violation
        +Alert
        +Metrics
    }
    Client <|-- RuleClient
    Client <|-- ValidationClient
    Client <|-- MonitoringClient
    Client *-- Models
```

## SDK Initialization Flow

```mermaid
flowchart TD
    A[Import SDK] --> B[Create Client Config]
    B --> C{Config Valid?}
    C -->|Yes| D[Initialize Client]
    C -->|No| E[Raise ConfigError]
    D --> F[Authenticate with API Key]
    F --> G{Auth Success?}
    G -->|Yes| H[Ready State]
    G -->|No| I[Raise AuthError]
    H --> J[Select Sub-Client]
    J --> K[RuleClient]
    J --> L[ValidationClient]
    J --> M[MonitoringClient]
    K --> N[Ready for Rule Operations]
    L --> O[Ready for Validation]
    M --> P[Ready for Monitoring]
```

## SDK to Core System Connection

```mermaid
componentDiagram
    component SDK_Python {
        component RuleClient
        component ValidationClient
        component MonitoringClient
    }
    component API_Gateway {
        component Auth_Middleware
        component Rate_Limiter
    }
    component Core_Engine {
        component Rule_Evaluator
        component Content_Validator
        component Alert_Manager
    }
    component Data_Layer {
        component Rule_Store
        component Result_Store
        component Metrics_Store
    }
    SDK_Python --> API_Gateway : HTTPS/REST
    API_Gateway --> Core_Engine : Internal RPC
    Core_Engine --> Data_Layer : Read/Write
```

## Component Descriptions

| Component | Responsibility |
|---|---|
| **Client** | Base class handling HTTP transport, auth, and request lifecycle |
| **RuleClient** | CRUD operations for rules — create, read, update, delete, list |
| **ValidationClient** | Content validation against rules, batch processing, status polling |
| **MonitoringClient** | Alert subscriptions, metric collection, real-time event streaming |
| **Models** | Type definitions for all domain objects (Rule, Violation, Result, etc.) |
| **API Gateway** | Entry point for all SDK requests — auth checks, rate limiting |
| **Core Engine** | Server-side rule evaluation, validation logic, alert dispatch |
| **Data Layer** | Persistent storage for rules, validation results, and telemetry |