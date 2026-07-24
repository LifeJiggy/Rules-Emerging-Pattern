# Advanced Usage

## Batch Evaluation Pipeline

```mermaid
flowchart LR
    A[Content Batch] --> B[Split into Chunks]
    B --> C[Chunk 1]
    B --> D[Chunk 2]
    B --> E[Chunk N]
    
    C --> F[Worker 1]
    D --> G[Worker 2]
    E --> H[Worker N]
    
    F --> I{Aggregate Results}
    G --> I
    H --> I
    
    I --> J[All Valid?]
    J -->|Yes| K[Accept Batch]
    J -->|No| L[Collect Violations]
    L --> M[Group by Rule]
    M --> N[Generate Report]
    
    subgraph Worker_Pool[Thread Pool]
        F
        G
        H
    end
    
    subgraph Aggregation[Aggregation Layer]
        I
        J
        L
        M
        N
    end
```

## Monitoring & Alerting Flow

```mermaid
sequenceDiagram
    participant App
    participant SDK as MonitoringClient
    participant WS as WebSocket Server
    participant Engine as Rule Engine
    participant Alert as Alert Service
    participant Notify as Notifier

    App->>SDK: subscribe_events(["violation", "error"])
    SDK->>WS: WSS /events (auth token)
    WS-->>SDK: Connected (subscription ID)

    Engine->>Alert: Critical violation detected
    Alert->>WS: Push event (type: violation)
    WS-->>SDK: {"type": "violation", "data": {...}}
    SDK->>App: callback(alert)

    App->>SDK: get_metrics("1h")
    SDK->>WS: Request metrics snapshot
    WS-->>SDK: Metrics{total, violations, latency}
    SDK-->>App: Metrics object

    App->>App: Check threshold exceeded
    App->>Notify: Send notification (email/pager)

    App->>SDK: unsubscribe(subscription_id)
    SDK->>WS: Close connection
    WS-->>SDK: Closed
```

## Full Type System

```mermaid
classDiagram
    class ClientConfig {
        +str base_url
        +str api_key
        +int timeout
        +int retry_count
        +float retry_delay
        +float max_retry_delay
        +LogConfig log_config
    }
    class Subscription {
        +str id
        +List~str~ event_types
        +bool active
        +cancel() None
    }
    class PaginatedResponse~T~ {
        +List~T~ items
        +int total
        +int page
        +int page_size
        +bool has_next
    }
    class ValidationStatus {
        +str id
        +str state
        +float progress
        +Optional~ValidationResult~ result
    }
    class LogConfig {
        +str level
        +str format
        +Optional~str~ output_file
    }
    class BatchConfig {
        +int concurrency
        +bool stop_on_first_error
        +Optional~int~ max_chunk_size
    }

    Client --> ClientConfig
    ValidationClient --> BatchConfig
    MonitoringClient --> Subscription
    ValidationClient --> ValidationStatus
    PaginatedResponse --> Rule
    PaginatedResponse --> ValidationResult
```

## Async Usage

```python
from rep_sdk import AsyncClient

async_client = AsyncClient(
    base_url="https://api.example.com",
    api_key="sk-..."
)

# Concurrent validations
import asyncio

async def validate_many(contents):
    tasks = [
        async_client.validation.validate_content(text)
        for text in contents
    ]
    results = await asyncio.gather(*tasks)
    return results

# Run with event loop
results = asyncio.run(validate_many(["text1", "text2", "text3"]))

# Async batch with streaming
async for result in async_client.validation.validate_stream(
    content_stream,
    concurrency=10
):
    print(f"Result: {result.is_valid}")
```

## Custom Configuration

```python
from rep_sdk import Client
from rep_sdk.config import BatchConfig, LogConfig, CacheConfig
import logging

# Full custom configuration
client = Client(
    base_url="https://api.example.com",
    api_key="sk-...",
    timeout=60,
    retry_count=5,
    retry_delay=0.5,
    max_retry_delay=60.0,
    log_config=LogConfig(
        level="DEBUG",
        format="json",
        output_file="/var/log/rep_sdk.log"
    ),
    cache_config=CacheConfig(
        enabled=True,
        ttl=300,
        max_size=1000
    ),
    batch_config=BatchConfig(
        concurrency=20,
        stop_on_first_error=False,
        max_chunk_size=50000
    )
)
```

## Performance Optimization Tips

| Technique | Impact | Complexity |
|---|---|---|
| **Connection pooling** — reuse HTTP sessions | High | Low |
| **Content caching** — avoid re-validation of identical content | High | Low |
| **Batch operations** — validate in bulk instead of single items | High | Medium |
| **Async I/O** — use `AsyncClient` for concurrent workloads | Medium | Medium |
| **Chunked processing** — split large batches into optimal chunks | Medium | Low |
| **Result pagination** — use page_size to control payload size | Low | Low |
| **Local fallback** — run simple rules locally to reduce API calls | Medium | High |

```python
# Optimized: Reuse client and HTTP session
client = Client(base_url="...", api_key="...")

# Optimized: Batch instead of loop
# BAD
for text in thousand_texts:
    client.validation.validate_content(text)

# GOOD
results = client.validation.validate_batch(
    [{"content": t} for t in thousand_texts],
    concurrency=20
)

# Optimized: Cache identical content
cache = {}
def validate_with_cache(text):
    h = hash(text)
    if h not in cache:
        cache[h] = client.validation.validate_content(text)
    return cache[h]
```