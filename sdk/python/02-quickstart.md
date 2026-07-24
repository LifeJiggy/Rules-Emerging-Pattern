# Quickstart Guide

## Installation

```bash
pip install rules-emerging-pattern-sdk
```

Or from source:

```bash
git clone https://github.com/your-org/rules-emerging-pattern-sdk.git
cd rules-emerging-pattern-sdk
pip install -e .
```

## Basic Usage

```python
from rep_sdk import Client

# Initialize the client
client = Client(
    base_url="https://api.example.com",
    api_key="your-api-key-here",
    timeout=30
)

# Validate content
result = client.validation.validate_content(
    content="Sample text to validate",
    rules=["rule-1", "rule-2"]
)

# Print results
print(f"Valid: {result.is_valid}")
for violation in result.violations:
    print(f"  - {violation.rule_id}: {violation.message}")
```

## Validation Sequence

```mermaid
sequenceDiagram
    participant User
    participant SDK as Python SDK
    participant API as API Server
    participant Engine as Rule Engine

    User->>SDK: Client(api_key, base_url)
    SDK->>API: POST /auth/verify
    API-->>SDK: 200 OK (token)
    SDK-->>User: Client ready

    User->>SDK: validate_content(content, rules)
    SDK->>API: POST /validate (content, rules)
    API->>Engine: evaluate(content, rules)
    Engine-->>API: ValidationResult
    API-->>SDK: 200 (result)
    SDK-->>User: ValidationResult

    User->>SDK: result.is_valid
    SDK-->>User: True / False
```

## Common Workflows

```mermaid
flowchart TD
    A[Start] --> B{What do you need?}
    
    B -->|Validate Content| C[Create ValidationClient]
    C --> D[Call validate_content]
    D --> E{Result valid?}
    E -->|Yes| F[Accept Content]
    E -->|No| G[Review Violations]
    G --> H[Fix Content]
    H --> D
    
    B -->|Manage Rules| I[Create RuleClient]
    I --> J[List Existing Rules]
    J --> K{Need new rule?}
    K -->|Yes| L[Create Rule]
    L --> J
    K -->|No| M[Update / Delete]
    
    B -->|Monitor System| N[Create MonitoringClient]
    N --> O[Subscribe to Alerts]
    O --> P[Receive Events]
    P --> Q[Take Action]
    Q --> P
```