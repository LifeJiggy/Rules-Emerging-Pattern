# API Integration

## System Integration Overview

The API module integrates with Core (rule evaluation engine), Monitoring (metrics and observability), and Tools (debugging and diagnostics). Each integration follows an adapter pattern to maintain loose coupling.

```mermaid
graph TB
    subgraph "External Systems"
        SDK["External SDK<br/>Python/JS/Go"]
        Webhook["Webhook Callbacks"]
        CLI["CLI Tool"]
        UI["Web Dashboard"]
    end

    subgraph "API Layer"
        API["API Module"]
        MW["Middleware"]
        Auth["Authentication"]
        REST["REST API<br/>/v1/*"]
        WS["WebSocket<br/>/ws"]
        GQL["GraphQL<br/>/graphql"]
    end

    subgraph "Core Integration"
        RE["RuleEngine"]
        EV["Evaluator"]
        COMP["Compiler"]
        STORE["RuleStore"]
    end

    subgraph "Monitoring Integration"
        PROM["Prometheus<br/>Metrics"]
        GRAF["Grafana<br/>Dashboards"]
        ALERT["AlertManager"]
        LOGS["ElasticSearch<br/>Logs"]
        TRACE["Jaeger<br/>Traces"]
    end

    subgraph "Tools Integration"
        DEBUG["Debug Console"]
        PROF["Profiler"]
        PLAY["Playground<br/>Sandbox"]
        TEST["Test Runner"]
    end

    SDK -->|HTTP/HTTPS| REST
    SDK -->|WS| WS
    SDK -->|HTTP| GQL
    CLI -->|HTTP| API
    UI -->|HTTP| API
    Webhook -->|POST| REST

    REST --> RE
    WS --> RE
    GQL --> RE
    RE --> EV
    RE --> COMP
    RE --> STORE

    API -->|Metrics| PROM
    PROM --> GRAF
    PROM --> ALERT
    API -->|Logs| LOGS
    API -->|Traces| TRACE

    API --> DEBUG
    API --> PROF
    API --> PLAY
    API --> TEST

    style API fill:#1976D2,color:#fff
    style RE fill:#388E3C,color:#fff
    style PROM fill:#F57C00,color:#fff
    style DEBUG fill:#7B1FA2,color:#fff
```

## External SDK Integration Sequence

The following sequence diagram traces a call from an external SDK through the API to internal services and back. It shows how middleware, authentication, and handlers collaborate to produce a response.

```mermaid
sequenceDiagram
    participant SDK as External SDK
    participant LB as Load Balancer
    parserWorker as Middleware
    actor Auth as APIAuth
    participant Rest as RestAPI
    participant RuleSvc as RuleService
    participant Cache as Redis Cache
    participant DB as PostgreSQL
    participant Mon as Monitoring

    SDK->>LB: POST /v1/evaluate
    Note over SDK,LB: {"rule_id": "r001", "context": {"age": 25, "country": "US"}}

    LB->>parserWorker: Forward request

    rect rgb(230, 242, 255)
        Note over parserWorker,parserWorker: Middleware Pipeline
        parserWorker->>parserWorker: parse_body() → JSON
        parserWorker->>parserWorker: validate_content_type() → application/json
        parserWorker->>parserWorker: inject_trace_id() → req_trace_001
        parserWorker->>parserWorker: check_cors() → origin allowed
    end

    parserWorker->>Auth: authenticate(request)
    Note over parserWorker,Auth: Extract: Authorization: Bearer <jwt>

    rect rgb(200, 255, 200)
        Note over Auth,Auth: JWT Validation
        Auth->>Auth: decode_jwt(token)
        Auth->>Auth: verify_rs256_signature(jwks)
        Auth->>Auth: check_expiry(iat, exp)
        Auth->>Auth: extract_claims(sub=user_42, roles=[admin])
        Auth-->>parserWorker: AuthResult(authenticated=true, user=user_42)
    end

    parserWorker->>parserWorker: check_rate_limit(user_42, 60, 60s)
    Note over parserWorker,parserWorker: Remaining: 42, Reset: 45s

    parserWorker->>Rest: route("POST", "/v1/evaluate")
    Note over parserWorker,Rest: Authorize: user_42 has "evaluate" permission

    Rest->>RuleSvc: evaluate("r001", {"age": 25, "country": "US"})

    rect rgb(245, 245, 255)
        Note over RuleSvc,DB: Rule Evaluation
        RuleSvc->>Cache: check_rule_cache("r001")
        Cache-->>RuleSvc: miss
        RuleSvc->>DB: SELECT * FROM rules WHERE id = 'r001'
        DB-->>RuleSvc: {id: "r001", expression: "age >= 18", ...}
        RuleSvc->>RuleSvc: compile_expression("age >= 18")
        RuleSvc->>RuleSvc: evaluate_expression({"age": 25})
        RuleSvc->>RuleSvc: result = True
        RuleSvc->>Cache: set_rule_cache("r001", rule_data, ttl=300)
    end

    RuleSvc-->>Rest: EvaluationResult(passed=true, violations=[], score=0.95)

    Rest->>Rest: format_response()
    Note over Rest,Rest: {"data": {"passed": true, "score": 0.95, "rule_id": "r001"}}

    Rest-->>parserWorker: Response(200, body, headers)
    parserWorker->>parserWorker: compress_response(gzip)
    parserWorker->>parserWorker: add_security_headers(HSTS, CSP, X-Frame-Options)
    parserWorker-->>LB: HTTP 200 OK

    parsersWorker->>Mon: record_metrics()
    Note over parsersWorker,Mon: +1 request, 45ms latency, 200 status

    LB-->>SDK: 200 OK + JSON body

    Note over SDK,Mon: Total round-trip: 45ms
```

## Direct Core Integration

```mermaid
sequenceDiagram
    participant Handler as API Handler
    participant Core as RuleEngine
    participant FS as FileStore
    participant Mem as InMemoryCache

    Handler->>Core: compile_rule(rule_id, expression)

    Core->>Mem: check_cache(rule_id)
    alt Cache Miss
        Mem-->>Core: None
        Core->>FS: load_rule_source(rule_id)
        FS-->>Core: "age >= 18 AND country in ('US', 'CA')"
        Core->>Core: parse_ast(expression)
        Core->>Core: optimize_ast(ast)
        Core->>Core: generate_bytecode(ast)
        Core->>Mem: store_compiled(rule_id, bytecode)
    else Cache Hit
        Mem-->>Core: bytecode
    end

    Core-->>Handler: CompiledRule(bytecode, metadata)

    Handler->>Core: evaluate(compiled_rule, context)
    Core->>Core: execute_bytecode(context)
    Core->>Core: check_result(True/False)
    Core-->>Handler: EvaluationResult(passed=True, score=0.95)

    Handler->>Core: log_evaluation(rule_id, context, result)
    Core->>Core: record_metric(rule_id, latency_ms, result)
```

## Monitoring Integration

```mermaid
sequenceDiagram
    participant API as API Layer
    participant Prom as Prometheus
    participant Graf as Grafana
    participant Alert as AlertManager
    participant Slack as Slack Webhook

    API->>Prom: Counter: requests_total{method="POST", endpoint="/v1/evaluate", status="200"}
    API->>Prom: Histogram: request_duration_ms{bucket=[5, 10, 25, 50, 100, 250, 500, 1000]}
    API->>Prom: Gauge: active_connections{protocol="websocket"}
    API->>Prom: Counter: rate_limit_exceeded{user_id="user_42"}

    Prom->>Graf: Query: rate(request_duration_ms_sum[5m]) / rate(request_duration_ms_count[5m])
    Graf->>Graf: Render dashboard panel

    Prom->>Alert: Alert: request_error_rate > 5% for 5m
    Alert->>Alert: Evaluate silence rules
    Alert->>Slack: POST {"text": "High error rate on /v1/evaluate: 12% (threshold: 5%)"}
    Slack-->>Alert: 200 OK

    API->>Prom: Counter: evaluation_result{rule_id="r001", result="violation"}
    Prom->>Alert: Alert: rule_r001_violation_rate > 100/min
    Alert->>Slack: POST {"text": "Rule r001 violation rate spike: 150/min"}
```

## Debugging Tools Integration

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant Debug as DebugConsole
    participant API as API
    participant Core as RuleEngine
    participant Trace as Jaeger

    Dev->>Debug: Open debug console
    Debug->>Debug: List active endpoints

    Dev->>Debug: request POST /v1/evaluate {"rule_id": "r001", "context": {"age": 25}}
    Debug->>API: Forward request with debug=true flag
    API->>API: Add X-Debug: true header

    API->>Core: evaluate("r001", context)

    rect rgb(255, 245, 230)
        Note over Core,Core: Debug Mode
        Core->>Core: step_through_evaluation()
        Core->>Core: show_intermediate_values()
        Core-->>Debug: {steps: [
            {line: "age >= 18", input: {age: 25}, output: true},
            {line: "country in list", input: {country: "US"}, output: true}
        ]}
    end

    API-->>Debug: {result: true, debug: {steps: [...], timing_ms: {parse: 2, optimize: 1, execute: 0.5}}}

    Dev->>Dev: Analyze debug output

    Trace->>Trace: Record trace
    Note over Trace,Trace: Trace ID: trace_001, Span: evaluate_rule, Duration: 3.5ms

    Dev->>Trace: Query trace_001
    Trace-->>Dev: Full span tree
```

## Plugin / Extension API

The API module exposes a plugin system that allows external extensions to hook into the request lifecycle:

```mermaid
graph TB
    subgraph "Plugin Hooks"
        PRE["pre_request hook"]
        AUTH["auth_hook"]
        ROUTE["route_hook"]
        POST["post_request hook"]
        ERROR["error_hook"]
    end

    subgraph "Lifecycle"
        START["Request Start"]
        PARSE["Parse Body"]
        AUTH_CHECK["Auth Check"]
        ROUTING["Routing"]
        EXEC["Execution"]
        FORMAT["Format Response"]
        LOG["Log"]
        DONE["Response Sent"]
    end

    subgraph "Example Plugins"
        P1["AuditPlugin<br/>logs all requests"]
        P2["CachePlugin<br/>response caching"]
        P3["TransformPlugin<br/>body transformation"]
        P4["AnalyticsPlugin<br/>event tracking"]
    end

    START --> PRE
    PRE --> PARSE
    PARSE --> AUTH
    AUTH --> AUTH_CHECK
    AUTH_CHECK --> ROUTE
    ROUTE --> ROUTING
    ROUTING --> EXEC
    EXEC --> POST
    POST --> FORMAT
    FORMAT --> ERROR
    ERROR --> LOG
    LOG --> DONE

    PRE -.-> P1
    PRE -.-> P2
    AUTH -.-> P3
    POST -.-> P1
    POST -.-> P4
    ERROR -.-> P1

    style START fill:#1565C0,color:#fff
    style DONE fill:#2E7D32,color:#fff
    style PRE fill:#F57F17,color:#fff
    style POST fill:#F57F17,color:#fff
```

## Integration Configuration

```python
INTEGRATION_CONFIG = {
    "core": {
        "host": "localhost",
        "port": 50051,
        "protocol": "grpc",
        "timeout_ms": 5000,
        "retry_policy": {"max_retries": 3, "backoff_ms": [100, 500, 1000]}
    },
    "monitoring": {
        "metrics_port": 9090,
        "push_interval_s": 15,
        "exporters": ["prometheus", "datadog"],
        "labels": {"service": "api", "version": "v2", "env": "production"}
    },
    "tools": {
        "debug_console": {"enabled": True, "allowed_roles": ["admin", "developer"]},
        "profiling": {"enabled": True, "sample_rate": 0.1},
        "playground": {"enabled": True, "sandbox": True, "max_execution_ms": 5000}
    },
    "cache": {
        "backend": "redis",
        "host": "redis-cluster.example.com",
        "port": 6379,
        "default_ttl_s": 300,
        "max_memory_mb": 512
    }
}
```

## Health Check Dependencies

```mermaid
graph TD
    Health["/v1/health"] --> CheckCore["Check Core<br/>gRPC ping"]
    Health --> CheckDB["Check Database<br/>SELECT 1"]
    Health --> CheckCache["Check Cache<br/>Redis PING"]
    Health --> CheckQueue["Check Queue<br/>RabbitMQ status"]

    CheckCore --> Up1{"Core<br/>Up?"}
    CheckDB --> Up2{"DB<br/>Up?"}
    CheckCache --> Up3{"Cache<br/>Up?"}
    CheckQueue --> Up4{"Queue<br/>Up?"}

    Up1 -->|No| Degraded["Degraded<br/>status=degraded"]
    Up2 -->|No| Critical["Critical<br/>status=critical"]
    Up3 -->|No| Degraded
    Up4 -->|No| Degraded

    Up1 -->|Yes| AllUp{"All Dependencies<br/>Healthy?"}
    Up2 -->|Yes| AllUp
    Up3 -->|Yes| AllUp
    Up4 -->|Yes| AllUp

    AllUp -->|Yes| Healthy["Healthy<br/>status=healthy"]

    style Health fill:#1565C0,color:#fff
    style Healthy fill:#2E7D32,color:#fff
    style Degraded fill:#F57F17,color:#fff
    style Critical fill:#C62828,color:#fff
```