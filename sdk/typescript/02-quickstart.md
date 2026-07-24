# Quickstart Guide

## Installation

```bash
npm install @rules-emerging/sdk
```

For Yarn or pnpm:

```bash
yarn add @rules-emerging/sdk
pnpm add @rules-emerging/sdk
```

## Basic Usage

### Validate Content

```mermaid
sequenceDiagram
    participant App as Your App
    participant SDK as SDK Client
    participant API as REST API
    participant Engine as Rule Engine

    App->>SDK: new Client({ apiKey })
    SDK->>API: GET /rules (cache-warm)
    API-->>SDK: Rule[]
    App->>SDK: client.validate(content)
    SDK->>API: POST /validate { content }
    API->>Engine: evaluate rules
    Engine-->>API: Violation[]
    API-->>SDK: ValidationResult
    SDK-->>App: { passed, violations, score }
    Note over App: Check result.passed
    alt Violations Found
        App->>App: Handle violations
    else No Violations
        App->>App: Proceed with content
    end
```

### Minimal Example

```typescript
import { Client } from '@rules-emerging/sdk';

const client = new Client({
  apiKey: 'your-api-key-here',
});

async function checkContent() {
  const result = await client.validate('Some content to validate');
  console.log(result);
}
```

### Full Workflow

```mermaid
flowchart LR
    A[Install SDK] --> B[Import Client]
    B --> C[Initialize with Config]
    C --> D[Ready]
    D --> E{Validation Type}
    E -->|Single| F[client.validate()]
    E -->|Batch| G[client.batchValidate()]
    E -->|Stream| H[client.validateStream()]
    F --> I{Passed?}
    G --> I
    H --> I
    I -->|Yes| J[Content Approved]
    I -->|No| K[Review Violations]
    K --> L[Fix Content]
    L --> F
```

### Common Workflows

```mermaid
flowchart TD
    subgraph Workflow1 [Simple Validation]
        A1[client.validate] --> B1{result.passed}
        B1 -->|true| C1[Accept]
        B1 -->|false| D1[Reject with violations]
    end

    subgraph Workflow2 [Batch Processing]
        A2[client.batchValidate] --> B2[Check each result]
        B2 --> C2[Report per-item status]
    end

    subgraph Workflow3 [Streaming]
        A3[client.validateStream] --> B3[Receive chunks]
        B3 --> C3[Aggregate partial results]
        C3 --> D3[Final result]
    end
```

### Error Handling

```typescript
import { Client, SdkError } from '@rules-emerging/sdk';

const client = new Client({ apiKey: 'sk-...' });

try {
  const result = await client.validate('Hello world');
  if (result.passed) {
    console.log('Content passed validation');
  } else {
    console.error('Violations:', result.violations);
  }
} catch (err) {
  if (err instanceof SdkError) {
    console.error('SDK error:', err.message);
  } else {
    console.error('Unexpected error:', err);
  }
}
```

### TypeScript Types

```typescript
import type {
  ClientConfig,
  ValidationResult,
  Violation,
  Rule,
} from '@rules-emerging/sdk';

const config: ClientConfig = {
  apiKey: process.env.API_KEY!,
  baseUrl: 'https://api.rules-emerging.dev',
  timeout: 10_000,
};
```

### Next Steps

- See [API Reference](./03-api-reference.md) for all available methods.
- See [Integration Guide](./04-integration-guide.md) for production setup.
- See [Advanced Usage](./05-advanced-usage.md) for batch and streaming patterns.
