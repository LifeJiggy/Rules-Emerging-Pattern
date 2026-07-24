# Advanced Usage

## Batch Evaluation Pipeline

```mermaid
flowchart LR
    subgraph Input [Batch Input]
        A1[Content 1]
        A2[Content 2]
        A3[Content N]
    end

    subgraph Pipeline [Batch Pipeline]
        B[BatchProcessor]
        C[Parallel Executor]
        D[Aggregator]
    end

    subgraph Processing [Per-Item]
        E1[Validate 1]
        E2[Validate 2]
        EN[Validate N]
    end

    subgraph Output [Batch Result]
        F1[Result 1]
        F2[Result 2]
        FN[Result N]
        G[Summary: passed/failed/total/duration]
    end

    A1 --> B
    A2 --> B
    A3 --> B
    B --> C
    C --> E1
    C --> E2
    C --> EN
    E1 --> D
    E2 --> D
    EN --> D
    D --> F1
    D --> F2
    D --> FN
    D --> G
```

## Monitoring & Alerting Flow

```mermaid
sequenceDiagram
    participant App
    participant SDK as MonitoringClient
    participant Buffer as Event Buffer
    participant Service as Monitoring Service
    participant Alert as Alert Manager
    participant Webhook as Webhook Endpoint

    App->>SDK: trackEvent('validation.failed', data)
    SDK->>Buffer: buffer event
    Buffer->>Buffer: batch (every 5s or 100 events)
    Buffer->>Service: POST /events (batched)
    Service->>Service: aggregate metrics

    App->>SDK: getMetrics({ period: '24h' })
    SDK->>Service: GET /metrics
    Service-->>SDK: Metrics
    SDK-->>App: { totalValidations, avgResponseTime, ... }

    Service->>Alert: check thresholds
    Alert->>Alert: failure rate > 5%?
    Alert->>Webhook: POST alert payload
    Webhook-->>Alert: 200 OK
    Alert-->>Service: alert dispatched
```

## Full Type System

```mermaid
classDiagram
    class ClientConfig {
        +string apiKey
        +string baseUrl
        +number timeout
        +RetryConfig retry
        +Record~string,string~ headers
        +boolean enableCache
        +string environment
    }

    class RetryConfig {
        +boolean enabled
        +number maxRetries
        +number baseDelay
        +number maxDelay
    }

    class ValidationOptions {
        +string[] ruleIds
        +RuleCategory[] categories
        +boolean streaming
        +number timeout
        +Record~string,any~ context
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
        +string[] categoriesChecked
    }

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
        +string[] failedItems
    }

    class StreamChunk {
        +number index
        +boolean isFinal
        +Violation[] violations
        +number score
        +number progress
    }

    class Metrics {
        +number totalValidations
        +number passed
        +number failed
        +number avgResponseTime
        +number p95ResponseTime
        +number p99ResponseTime
        +Record~string,number~ byCategory
        +Record~string,number~ bySeverity
        +Date period
    }

    class Subscription {
        +string id
        +string channel
        +void unsubscribe()
    }

    class EvaluationResult {
        +boolean matched
        +number confidence
        +string[] matches
        +number duration
        +string ruleId
    }

    ClientConfig --> RetryConfig
    ValidationResult --> Violation
    ValidationResult --> ValidationMetadata
    BatchInput --> ValidationOptions
    BatchResult --> ValidationResult
    BatchResult --> StreamChunk
    ValidationOptions --> RuleCategory
    Rule --> RuleSeverity
    Rule --> RuleCategory
    Rule --> RuleAction
    Violation --> RuleSeverity
```

## Async/Await Patterns

```typescript
import { Client } from '@rules-emerging/sdk';

const client = new Client({ apiKey: process.env.API_KEY! });

// Parallel validation
async function validateAll(contents: string[]) {
  const results = await Promise.allSettled(
    contents.map((c) => client.validate(c)),
  );
  return results.map((r, i) => ({
    index: i,
    status: r.status,
    result: r.status === 'fulfilled' ? r.value : null,
    error: r.status === 'rejected' ? r.reason : null,
  }));
}

// Streaming with progress
async function streamValidate(content: string) {
  const violations: Violation[] = [];
  await client.validateStream(content, (chunk, done) => {
    violations.push(...chunk.violations);
    console.log(`Progress: ${chunk.progress}%`);
    if (done) {
      console.log(`Total violations: ${violations.length}`);
    }
  });
}

// Batch with concurrency control
async function batchWithConcurrency(
  items: string[],
  concurrency = 5,
) {
  const results: ValidationResult[] = [];
  for (let i = 0; i < items.length; i += concurrency) {
    const batch = items.slice(i, i + concurrency);
    const batchResults = await Promise.all(
      batch.map((item) => client.validate(item)),
    );
    results.push(...batchResults);
  }
  return results;
}
```

## Custom Configuration

```typescript
import { Client } from '@rules-emerging/sdk';

const client = new Client({
  apiKey: process.env.API_KEY!,
  baseUrl: 'https://api.rules-emerging.dev/v2',
  timeout: 30_000,
  enableCache: true,
  retry: {
    enabled: true,
    maxRetries: 5,
    baseDelay: 500,
    maxDelay: 10_000,
  },
  headers: {
    'X-Custom-Header': 'custom-value',
    'X-Trace-Id': crypto.randomUUID(),
  },
  environment: 'production',
});

// Custom rule scope
const result = await client.validate(content, {
  ruleIds: ['rule-security-001', 'rule-compliance-002'],
  categories: [RuleCategory.Security, RuleCategory.Compliance],
  context: { userId: 'usr_123', source: 'onboarding' },
});
```

## Performance Optimization

| Technique | Description |
|-----------|-------------|
| **Reuse Client** | Create one `Client` instance and reuse it across requests. Avoid per-request instantiation. |
| **Enable Cache** | Rule cache avoids re-fetching rules on every validation. Cache TTL is 5 minutes by default. |
| **Batch Requests** | Use `batchValidate` instead of multiple `validate` calls to reduce HTTP overhead. |
| **Streaming** | For large content, use `validateStream` to get partial results while processing continues. |
| **Concurrency Control** | Limit concurrent validation calls to avoid overwhelming the API (5-10 concurrent max). |
| **Connection Keep-Alive** | SDK uses HTTP keep-alive by default. Ensure your Node.js version supports it. |
| **Tree-Shaking** | For browser builds, import only the modules you need to reduce bundle size. |

```typescript
// Tree-shakeable imports (browser)
import { ValidationClient } from '@rules-emerging/sdk/validation';
import type { ValidationResult } from '@rules-emerging/sdk/types';

// Pre-warm cache
const client = new Client({ apiKey: process.env.API_KEY! });
await client.getRules(); // pre-warm

// Measure performance
console.time('validation');
const result = await client.validate(largeContent);
console.timeEnd('validation');
```
