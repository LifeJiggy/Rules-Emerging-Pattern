# API Reference

## Model Classes

```mermaid
classDiagram
    class Rule {
        +str id
        +str name
        +str description
        +str pattern
        +str severity
        +bool enabled
        +dict metadata
        +to_dict() dict
        +from_dict(data) Rule
    }
    class ValidationResult {
        +str id
        +bool is_valid
        +str content_hash
        +datetime timestamp
        +List~Violation~ violations
        +float score
        +to_dict() dict
    }
    class Violation {
        +str rule_id
        +str rule_name
        +str severity
        +str message
        +int line
        +int column
        +str snippet
        +to_dict() dict
    }
    class Alert {
        +str id
        +str type
        +str severity
        +str message
        +dict data
        +datetime timestamp
        +bool acknowledged
    }
    class Metrics {
        +int total_validations
        +int total_violations
        +float avg_score
        +dict~str,int~ rule_hits
        +dict~str,float~ latency_p99
    }
    ValidationResult *-- Violation
```

## Validation Flow

```mermaid
sequenceDiagram
    participant App as Application
    participant SDK as ValidationClient
    participant Cache
    participant API
    participant Engine as Rule Engine

    App->>SDK: validate_content(text, rules)
    SDK->>SDK: Hash content
    SDK->>Cache: Check cache (content_hash)
    alt Cache Hit
        Cache-->>SDK: Cached result
        SDK-->>App: ValidationResult (cached)
    else Cache Miss
        SDK->>API: POST /v1/validate
        API->>Engine: Evaluate rules
        Engine-->>API: Violations + Score
        API-->>SDK: ValidationResult
        SDK->>Cache: Store result
        SDK-->>App: ValidationResult
    end
```

## Method Reference

| Method | Description | Return Type |
|---|---|---|
| `Client.__init__` | Initialize SDK client with config | `None` |
| `RuleClient.list_rules` | List all rules with optional filters | `List[Rule]` |
| `RuleClient.get_rule` | Get a single rule by ID | `Rule` |
| `RuleClient.create_rule` | Create a new rule | `Rule` |
| `RuleClient.update_rule` | Update an existing rule | `Rule` |
| `RuleClient.delete_rule` | Delete a rule by ID | `bool` |
| `ValidationClient.validate_content` | Validate a single content string | `ValidationResult` |
| `ValidationClient.validate_batch` | Validate multiple items | `List[ValidationResult]` |
| `ValidationClient.get_status` | Get validation status by ID | `ValidationStatus` |
| `MonitoringClient.get_alerts` | Retrieve alerts with filters | `List[Alert]` |
| `MonitoringClient.get_metrics` | Get system metrics for a duration | `Metrics` |
| `MonitoringClient.subscribe_events` | Subscribe to real-time events | `Subscription` |

## Method Signatures

```python
class Client:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 30,
        retry_count: int = 3,
        retry_delay: float = 1.0
    ) -> None: ...

class RuleClient:
    def list_rules(
        self,
        page: int = 1,
        page_size: int = 20,
        severity: Optional[str] = None,
        enabled: Optional[bool] = None
    ) -> List[Rule]: ...

    def create_rule(
        self,
        name: str,
        pattern: str,
        severity: str = "medium",
        description: str = "",
        enabled: bool = True,
        metadata: Optional[dict] = None
    ) -> Rule: ...

class ValidationClient:
    def validate_content(
        self,
        content: str,
        rules: Optional[List[str]] = None,
        async_mode: bool = False
    ) -> ValidationResult: ...

    def validate_batch(
        self,
        items: List[dict],
        concurrency: int = 5
    ) -> List[ValidationResult]: ...

class MonitoringClient:
    def subscribe_events(
        self,
        event_types: List[str],
        callback: Callable[[Alert], None],
        polling_interval: float = 1.0
    ) -> Subscription: ...
```