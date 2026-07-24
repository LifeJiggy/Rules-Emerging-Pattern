# API Data Flow

## HTTP Request Lifecycle

The following sequence diagram traces a complete HTTP request from the moment it reaches the server until the response is returned to the client. Every request passes through the middleware pipeline, authentication, rate limiting, and finally the handler.

```mermaid
sequenceDiagram
    participant Client
    participant LB as Load Balancer
    participant MW as APIMiddleware
    participant RL as RateLimiter
    participant Auth as APIAuth
    participant Handler as RestAPI/GraphQL
    participant Core as RuleEngine
    participant Log as AuditLog

    Client->>LB: HTTP POST /v1/evaluate
    Note over Client,LB: JSON body: {rule_id, context}
    LB->>MW: Forward request

    rect rgb(230, 242, 255)
        Note over MW,MW: Middleware Pipeline
        MW->>MW: parse_body()
        MW->>MW: validate_content_type()
        MW->>MW: check_cors()
        MW->>MW: inject_trace_id()
    end

    MW->>RL: check_rate_limit(api_key, 60, 60s)
    rect rgb(255, 235, 200)
        Note over RL,RL: Token Bucket Check
        RL->>RL: tokens = store.get(api_key)
        RL->>RL: if tokens < 1: return False
        RL->>RL: store.decrement(api_key)
        RL-->>MW: RateLimitResult(allowed=true, remaining=42, reset=45)
    end

    MW->>Auth: authenticate(request)
    rect rgb(200, 255, 200)
        Note over Auth,Auth: Authentication
        Auth->>Auth: extract_credentials(request)
        alt API Key Auth
            Auth->>Auth: validate_api_key(key)
        else JWT Auth
            Auth->>Auth: validate_jwt(token)
        else OAuth Auth
            Auth->>Auth: validate_oauth(token)
        end
        Auth-->>MW: AuthResult(authenticated=true, user=User, roles=[admin])
    end

    MW->>Handler: route_and_authorize(method, path, user)

    rect rgb(245, 245, 255)
        Note over Handler,Handler: Handler Execution
        Handler->>Handler: validate_request_body()
        Handler->>Handler: deserialize_params()

        alt REST Endpoint
            Handler->>Core: rule_service.evaluate(rule_id, context)
        else GraphQL Endpoint
            Handler->>Core: resolver.resolve_query(query, variables)
        end

        Core-->>Handler: EvaluationResult(result=True, violations=[], score=0.95)

        Handler->>Handler: format_response()
        Handler->>Handler: add_pagination_headers()
    end

    Handler-->>MW: Response(200, body, headers)
    MW->>MW: compress_response()
    MW->>MW: add_security_headers()
    MW->>MW: log_request(status, duration, user)

    MW->>Log: write_audit_log(trace_id, user, action, resource, status, duration_ms)
    MW-->>LB: HTTP 200 OK
    LB-->>Client: JSON Response

    Note over Client,Log: Total latency: ~45ms (p99 < 200ms)
```

## WebSocket Connection Lifecycle

```mermaid
sequenceDiagram
    participant Client
    participant LB as Load Balancer
    participant WS as WebSocketHandler
    participant CM as ConnectionManager
    participant HB as HeartbeatMonitor
    participant CR as ChannelRegistry
    participant Core as RuleEngine
    participant Queue as MessageQueue

    Client->>LB: GET /ws (Upgrade: websocket)
    LB->>WS: Upgrade connection
    WS->>WS: validate_origin()
    WS->>WS: authenticate_websocket(headers)
    alt Auth Failed
        WS-->>Client: 403 Forbidden
    end

    rect rgb(230, 242, 255)
        Note over Client,Queue: Connection Establishment
        WS->>CM: register_connection(client_info)
        CM-->>WS: connection_id = "conn-abc123"
        WS-->>Client: 101 Switching Protocols
        WS->>Client: WelcomeMessage(connection_id, server_time, heartbeat_interval=30)
        Client-->>WS: AckMessage(connection_id)
    end

    rect rgb(255, 255, 230)
        Note over Client,Queue: Heartbeat Loop
        loop Every 30 seconds
            WS->>Client: Ping(frame)
            alt Within 10s
                Client-->>WS: Pong(frame)
                WS->>HB: record_heartbeat(conn_id, latency_ms)
            else Timeout
                WS->>HB: mark_missed(conn_id)
                HB-->>WS: MissedCount = 3
                alt Exceeded max misses (3)
                    WS->>CM: deregister_connection(conn_id)
                    WS-->>Client: Close(1000, "heartbeat timeout")
                end
            end
        end
    end

    rect rgb(245, 245, 255)
        Note over Client,Queue: Message Handling
        Client->>WS: TextMessage({"action": "subscribe", "channel": "rule:r001"})
        WS->>WS: validate_message_format()
        WS->>WS: check_rate_limit(message_type, 100/min)
        WS->>CR: subscribe(conn_id, "rule:r001")
        CR-->>WS: SubscriptionResult(success=true)
        WS-->>Client: AckMessage("subscribed to rule:r001")

        Client->>WS: TextMessage({"action": "evaluate", "rule_id": "r001", "context": {...}})
        WS->>Core: evaluate("r001", context)
        Core-->>WS: EvaluationResult(...)
        WS-->>Client: TextMessage({"event": "evaluation_result", "data": {...}})
    end

    rect rgb(255, 230, 230)
        Note over Client,Queue: Event Broadcasting
        Core->>WS: PushEvent(channel="rule:r001", event={"status": "violation", ...})
        WS->>CR: get_subscribers("rule:r001")
        CR-->>WS: [conn-abc123, conn-def456, ...]
        WS->>Queue: enqueue_broadcast([conn-abc123, ...], event)
        Queue-->>Client: TextMessage({"event": "rule_updated", "data": {...}})
        Queue-->>Client: TextMessage({"event": "rule_updated", "data": {...}})
    end

    rect rgb(255, 230, 255)
        Note over Client,Queue: Disconnection
        Client-->>WS: CloseFrame(code=1000, reason="client shutdown")
        WS->>CR: unsubscribe_all(conn_id)
        WS->>CM: deregister_connection(conn_id)
        WS->>HB: stop_heartbeat(conn_id)
        WS-->>Client: CloseFrame(code=1000, reason="ok")
    end
```

## GraphQL Query Resolution

```mermaid
sequenceDiagram
    participant Client
    participant GH as GraphQLHandler
    participant Parser as QueryParser
    participant Validator as QueryValidator
    participant CA as ComplexityAnalyzer
    participant DL as DataLoader
    participant Resolver as ResolverMap
    participant DB as Database
    participant Cache as Redis

    Client->>GH: POST /graphql
    Note over Client,GH: {"query": "query GetRules {...}", "variables": {"limit": 10}}

    GH->>GH: parse_request_body()
    GH->>GH: extract_operation_name("GetRules")
    GH->>Parser: parse(query)

    rect rgb(230, 242, 255)
        Note over Parser,Parser: Parse Phase
        Parser->>Parser: lex_query()
        Parser->>Parser: build_ast()
        Parser-->>GH: Document(AST)
    end

    GH->>Validator: validate(document, schema)

    rect rgb(255, 235, 200)
        Note over Validator,Validator: Validation Phase
        Validator->>Validator: validate_syntax()
        Validator->>Validator: validate_types()
        Validator->>Validator: validate_fields_exist()
        Validator->>Validator: validate_arguments()
        Validator->>Validator: validate_directives()
        Validator-->>GH: ValidationResult(errors=[], valid=true)
    end

    GH->>CA: analyze_complexity(document, variables)

    rect rgb(200, 255, 200)
        Note over CA,CA: Complexity Check
        CA->>CA: walk_ast.assign_costs()
        CA->>CA: compute_total(75)
        CA->>CA: if total > max_complexity(1000)
        alt Under Limit
            CA-->>GH: ComplexityResult(total=75, allowed=true)
        else Exceeded Limit
            CA-->>GH: ComplexityResult(total=1500, allowed=false)
            GH-->>Client: 400 {"errors": [{"message": "Query too complex"}]}
        end
    end

    rect rgb(245, 245, 255)
        Note over GH,Resolver: Execution Phase
        GH->>GH: create_execution_context(user, loaders)

        alt Query Operation
            GH->>Resolver: resolve_field("Query", "rules", {limit: 10})
        else Mutation Operation
            GH->>Resolver: resolve_field("Mutation", "createRule", {input: {...}})
        end

        Resolver->>DL: dataloader.load("rules", {limit: 10})

        rect rgb(255, 245, 230)
            Note over DL,Cache: DataLoader Batching
            DL->>Cache: check_cache("rules:limit=10:page=1")
            alt Cache Hit
                Cache-->>DL: cached_data
            else Cache Miss
                Cache-->>DL: None
                DL->>DB: SELECT * FROM rules LIMIT 10
                DB-->>DL: [{id: 1, name: "Rule1", ...}, ...]
                DL->>Cache: set("rules:limit=10:page=1", data, ttl=60)
            end
            DL-->>Resolver: [{id: 1, name: "Rule1", ...}]
        end

        Resolver-->>GH: ExecutionResult(data={rules: [...]}, errors=[])
    end

    GH->>GH: serialize_result()
    GH-->>Client: 200 {"data": {"rules": [...]}}
```

## Request Batching Flow

```mermaid
graph TD
    Start["Client Request"] --> CheckType{"Is Batch?"}

    CheckType -->|Single| SinglePath["Parse Single Request"]
    CheckType -->|Batch| BatchPath["Parse Batch Array"]

    BatchPath --> ValidateBatch["Validate each item in batch"]
    ValidateBatch --> ProcessBatch["Process items sequentially<br/>or in parallel (configurable)"]

    subgraph "Per-Item Processing"
        ProcessBatch --> Item1["Item 1"]
        ProcessBatch --> Item2["Item 2"]
        ProcessBatch --> ItemN["Item N"]
    end

    Item1 --> Auth1["Auth Check"]
    Item2 --> Auth2["Auth Check"]
    ItemN --> AuthN["Auth Check"]

    Auth1 --> Exec1["Execute"]
    Auth2 --> Exec2["Execute"]
    AuthN --> ExecN["Execute"]

    Exec1 --> Collect["Collect Results"]
    Exec2 --> Collect
    ExecN --> Collect

    Collect --> BuildResponse["Build Response Array"]
    SinglePath --> ProcessSingle["Process Single Item"]
    ProcessSingle --> SingleAuth["Auth Check"]
    SingleAuth --> SingleExec["Execute"]
    SingleExec --> SingleResponse["Build Single Response"]

    BuildResponse --> Return["Return to Client"]
    SingleResponse --> Return

    style Start fill:#1565C0,color:#fff
    style Return fill:#2E7D32,color:#fff
    style CheckType fill:#F57F17,color:#fff
```

## Error Propagation

```mermaid
flowchart LR
    subgraph "Error Sources"
        E1["Validation Error<br/>422"]
        E2["Auth Error<br/>401/403"]
        E3["Rate Limit<br/>429"]
        E4["Not Found<br/>404"]
        E5["Server Error<br/>500"]
        E6["Timeout<br/>504"]
    end

    subgraph "Middleware Handling"
        M1["RequestParser"]
        M2["Authenticator"]
        M3["RateLimiter"]
        M4["Router"]
        M5["Handler"]
        M6["ExceptionWrapper"]
    end

    subgraph "Response"
        R1["Error Envelope"]
        R2["Retry-After Header"]
        R3["Trace ID"]
        R4["Log Entry"]
    end

    E1 --> M1 --> R1
    E2 --> M2 --> R1
    E3 --> M3 --> R1
    E3 --> M3 --> R2
    E4 --> M4 --> R1
    E5 --> M5 --> M6 --> R1
    E6 --> M5 --> M6 --> R1
    M1 --> R3
    M2 --> R3
    M3 --> R3
    M5 --> R3
    M6 --> R4
```