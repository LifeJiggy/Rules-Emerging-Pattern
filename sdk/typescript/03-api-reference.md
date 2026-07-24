# API Reference

## Model Types

```mermaid
classDiagram
    class Rule {
        +string id
        +string name
        +string description
        +RuleSeverity severity
        +RuleCategory category
        +RuleAction action
        +string[] patterns
        +Record~string,any~ metadata
        +boolean enabled
        +Date createdAt
        +Date updatedAt
    }

    class CreateRuleInput {
        +string name
        +string description
        +RuleSeverity severity
        +RuleCategory category
        +RuleAction action
        +string[] patterns
        +Record~string,any~ metadata
    }

    class UpdateRuleInput {
        +string name
        +string description
        +RuleSeverity severity
        +RuleCategory category
        +RuleAction action
        +string[] patterns
        +Record~string,any~ metadata
        +boolean enabled
    }

    class ValidationResult {
        +boolean passed
        +Violation[] violations
        +number score
        +number duration
        +ValidationMetadata metadata
    }

    class Violation {
        +string ruleId
        +string ruleName
        +string message
        +number line
        +number column
        +number offset
        +string snippet
        +RuleSeverity severity
        +string suggestion
        +Record~string,any~ context
    }

    class ValidationMetadata {
        +string version
        +number rulesEvaluated
        +number rulesMatched
        +Date timestamp
        +string requestId
    }

    class BatchInput {
        +string[] items
        +ValidationOptions options
    }

    class BatchResult {
        +ValidationResult[] results
        +number total
        +number passed
        +number failed
        +number duration
    }

    class ValidationOptions {
        +string[] ruleIds
        +RuleCategory[] categories
        +boolean streaming
        +number timeout
    }

    class EvaluationResult {
        +boolean matched
        +number confidence
        +string[] matches
        +number duration
    }

    class Metrics {
        +number totalValidations
        +number passed
        +number failed
        +number avgResponseTime
        +Record~string,number~ byCategory
        +Date period
    }

    class ClientConfig {
        +string apiKey
        +string baseUrl
        +number timeout
        +RetryConfig retry
        +string[] headers
        +boolean enableCache
    }

    class RetryConfig {
        +number maxRetries
        +number baseDelay
        +number maxDelay
        +boolean enabled
    }

    ValidationResult --> Violation : contains
    ValidationResult --> ValidationMetadata : contains
    BatchInput --> ValidationOptions : contains
    BatchResult --> ValidationResult : contains
    ClientConfig --> RetryConfig : contains
    Rule <-- CreateRuleInput : creates
    Rule <-- UpdateRuleInput : updates
```

## Validation Flow

```mermaid
sequenceDiagram
    participant App
    participant SDK as ValidationClient
    participant Cache as Rule Cache
    participant Transport as HTTP Transport
    participant API as REST API

    App->>SDK: validate(content, options?)
    SDK->>SDK: normalize options
    SDK->>Cache: getCachedRules(categories)
    alt Cache Miss
        Cache-->>SDK: null
        SDK->>Transport: GET /rules
        Transport->>API: request
        API-->>Transport: Rule[]
        Transport-->>SDK: Rule[]
        SDK->>Cache: set(category, rules)
    else Cache Hit
        Cache-->>SDK: Rule[]
    end
    SDK->>SDK: evaluateRules(content, rules)
    SDK->>SDK: buildViolations(matches)
    SDK->>SDK: computeScore(violations)
    SDK-->>App: ValidationResult
```

## Method Reference

| Method | Returns | Description |
|--------|---------|-------------|
| `validate(content, options?)` | `Promise<ValidationResult>` | Validate a single content string against active rules |
| `validateStream(content, callback)` | `Promise<void>` | Streaming validation with partial results via callback |
| `batchValidate(input)` | `Promise<BatchResult>` | Validate multiple content items in a single request |
| `getRules()` | `Promise<Rule[]>` | Get all active rules |
| `getRule(id)` | `Promise<Rule>` | Get a single rule by ID |
| `createRule(input)` | `Promise<Rule>` | Create a new validation rule |
| `updateRule(id, input)` | `Promise<Rule>` | Update an existing rule |
| `deleteRule(id)` | `Promise<void>` | Delete a rule by ID |
| `evaluateRule(ruleId, content)` | `Promise<EvaluationResult>` | Evaluate content against a specific rule |
| `getHistory(filters?)` | `Promise<ValidationHistory>` | Get validation history with optional filters |
| `trackEvent(name, data?)` | `void` | Track a custom monitoring event |
| `getMetrics(options?)` | `Promise<Metrics>` | Get aggregated validation metrics |
| `subscribe(channel, handler)` | `Subscription` | Subscribe to a real-time event channel |
| `unsubscribe(sub)` | `void` | Unsubscribe from a channel |

## Method Signatures

```typescript
class ValidationClient {
  validate(
    content: string,
    options?: ValidationOptions,
  ): Promise<ValidationResult>;

  validateStream(
    content: string,
    callback: (chunk: StreamChunk, done: boolean) => void,
  ): Promise<void>;

  batchValidate(input: BatchInput): Promise<BatchResult>;
}

class RuleClient {
  list(filters?: RuleFilters): Promise<Rule[]>;
  get(id: string): Promise<Rule>;
  create(input: CreateRuleInput): Promise<Rule>;
  update(id: string, input: UpdateRuleInput): Promise<Rule>;
  remove(id: string): Promise<void>;
  evaluate(ruleId: string, content: string): Promise<EvaluationResult>;
}

class MonitoringClient {
  trackEvent(name: string, data?: Record<string, any>): void;
  getMetrics(options?: MetricsOptions): Promise<Metrics>;
  subscribe(
    channel: string,
    handler: (event: MonitorEvent) => void,
  ): Subscription;
  unsubscribe(subscription: Subscription): void;
}
```

## Enums

```typescript
enum RuleSeverity {
  Info = 'info',
  Low = 'low',
  Medium = 'medium',
  High = 'high',
  Critical = 'critical',
}

enum RuleCategory {
  Security = 'security',
  Compliance = 'compliance',
  Style = 'style',
  Performance = 'performance',
  BestPractice = 'best_practice',
}

enum RuleAction {
  Allow = 'allow',
  Warn = 'warn',
  Block = 'block',
}
```
