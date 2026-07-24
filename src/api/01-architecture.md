# API Architecture

## System Component Diagram

The API layer sits between external clients and the Core rule engine. All traffic flows through a load balancer, then through the middleware pipeline, authentication, and finally to the appropriate protocol handler.

```mermaid
graph TD
    subgraph "External"
        C1["Client HTTP"]
        C2["Client WS"]
        C3["Client GraphQL"]
    end

    subgraph "Edge"
        LB["Load Balancer<br/>HAProxy / Nginx"]
        CDN["CDN Cache<br/>CloudFront"]
        WAF["WAF<br/>ModSecurity"]
    end

    subgraph "Middleware Pipeline"
        M1["RequestParser<br/>body → JSON"]
        M2["CORSMiddleware<br/>origin → headers"]
        M3["RateLimiter<br/>token bucket"]
        M4["RequestLogger<br/>structured log"]
        M5["CompressionMiddleware<br/>gzip / brotli"]
    end

    subgraph "Authentication"
        A1["APIKeyAuth<br/>X-API-Key → User"]
        A2["JWTAuth<br/>Bearer → Claims"]
        A3["OAuthAuth<br/>OAuth2 → Identity"]
        A4["RoleResolver<br/>User → Permissions"]
    end

    subgraph "Protocol Handlers"
        H1["RestAPI<br/>HTTP Router"]
        H2["WebSocketHandler<br/>Channel Manager"]
        H3["GraphQLHandler<br/>Schema Executor"]
    end

    subgraph "Internal Services"
        S1["RuleEngine<br/>Core"]
        S2["Monitoring<br/>Prometheus"]
        S3["AuditLog<br/>ElasticSearch"]
        S4["Cache<br/>Redis"]
        S5["Queue<br/>RabbitMQ"]
    end

    C1 --> CDN --> WAF --> LB
    C2 --> WAF --> LB
    C3 --> CDN --> WAF --> LB
    LB --> M1
    M1 --> M2
    M2 --> M3
    M3 --> M4
    M4 --> M5

    M5 --> A1
    M5 --> A2
    M5 --> A3
    A1 --> A4
    A2 --> A4
    A3 --> A4

    A4 --> H1
    A4 --> H2
    A4 --> H3

    H1 --> S1
    H1 --> S2
    H1 --> S4
    H2 --> S1
    H2 --> S5
    H3 --> S1
    H3 --> S3

    H1 -.-> S3
    H2 -.-> S3
    H3 -.-> S3

    style C1 fill:#2196F3,stroke:#1565C0,color:#fff
    style C2 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style C3 fill:#FF9800,stroke:#E65100,color:#fff
    style LB fill:#9C27B0,stroke:#6A1B9A,color:#fff
    style H1 fill:#1976D2,stroke:#0D47A1,color:#fff
    style H2 fill:#388E3C,stroke:#1B5E20,color:#fff
    style H3 fill:#F57C00,stroke:#BF360C,color:#fff
```

## Class Diagram

```mermaid
classDiagram
    class BaseAPI {
        +str version
        +APIMiddleware middleware
        +APIAuth auth
        +Config config
        +start() void
        +stop() void
        +health_check() HealthStatus
    }

    class RestAPI {
        +Dict~str, Route~ routes
        +int max_body_size
        +handle_get(request) Response
        +handle_post(request) Response
        +handle_put(request) Response
        +handle_delete(request) Response
        +handle_patch(request) Response
        +register_route(path, method, handler) void
        +register_blueprint(prefix, routes) void
        +add_error_handler(status_code, handler) void
        -router Router
        -serializer Serializer
        -validator RequestValidator
        -pagination PaginationHandler
    }

    class WebSocketHandler {
        +int max_connections
        +int heartbeat_interval
        +str ping_message
        +on_connect(connection) void
        +on_message(connection, message) void
        +on_disconnect(connection) void
        +on_error(connection, error) void
        +broadcast(channel, message) void
        +send_to_user(user_id, message) void
        +get_channel_members(channel) List~Connection~
        +close_connection(connection_id) void
        -connection_manager ConnectionManager
        -heartbeat_monitor HeartbeatMonitor
        -channel_registry ChannelRegistry
        -message_queue AsyncQueue
        -reconnect_policy ReconnectPolicy
    }

    class GraphQLHandler {
        +GraphQLSchema schema
        +int max_depth
        +int max_complexity
        +bool enable_introspection
        +execute_query(query, variables, context) ExecutionResult
        +execute_mutation(query, variables, context) ExecutionResult
        +subscribe(subscription, variables, context) AsyncIterator
        +get_type(type_name) GraphQLType
        +register_directive(directive) void
        +register_middleware(middleware) void
        -schema_builder SchemaBuilder
        -resolver_map ResolverMap
        -validator QueryValidator
        -complexity_analyzer ComplexityAnalyzer
        -data_loader DataLoader
    }

    class APIMiddleware {
        +List~Middleware~ pipeline
        +Dict~str, object~ context
        +process_request(request) Response
        +process_response(request, response) Response
        +process_exception(request, exception) Response
        +add_middleware(middleware) void
        +remove_middleware(name) void
        +insert_middleware(index, middleware) void
        +clear_middleware() void
        -rate_limiter RateLimiter
        -logger RequestLogger
        -cors_handler CORSHandler
        -compressor Compressor
    }

    class APIAuth {
        +Dict~str, AuthStrategy~ strategies
        +int token_ttl
        +int refresh_ttl
        +authenticate(request) AuthResult
        +authorize(user, resource, action) bool
        +validate_api_key(key) User
        +validate_jwt(token) User
        +validate_oauth(token) User
        +validate_basic(username, password) User
        +refresh_token(token) TokenPair
        +revoke_token(token) void
        +get_user_permissions(user) List~str~
        -key_store KeyStore
        -jwt_manager JWTManager
        -oauth_provider OAuthProvider
        -token_blacklist TokenBlacklist
    }

    class Connection {
        +str id
        +str user_id
        +str status
        +int connected_at
        +List~str~ subscribed_channels
        +Dict metadata
        +send(data) void
        +close(code, reason) void
        +ping() void
    }

    class Route {
        +str path
        +str method
        +Callable handler
        +List~str~ required_roles
        +int rate_limit
        +bool require_auth
        +Dict metadata
    }

    class ExecutionResult {
        +Dict data
        +List~GraphQLError~ errors
        +bool success
        +int query_complexity
        +float execution_time_ms
    }

    BaseAPI <|-- RestAPI
    BaseAPI <|-- WebSocketHandler
    BaseAPI <|-- GraphQLHandler
    BaseAPI --> APIMiddleware
    BaseAPI --> APIAuth
    RestAPI --> Route : manages
    WebSocketHandler --> Connection : manages
    GraphQLHandler --> ExecutionResult : returns
    RestAPI --> RateLimiter : uses
    WebSocketHandler --> RateLimiter : uses
    GraphQLHandler --> RateLimiter : uses
    RestAPI --> RequestLogger : uses
    WebSocketHandler --> RequestLogger : uses
    GraphQLHandler --> RequestLogger : uses
```

## Authentication Flow

```mermaid
sequenceDiagram
    participant Client
    participant LB as Load Balancer
    participant MW as Middleware
    participant Auth as APIAuth
    participant Handler as Protocol Handler
    participant DB as User Store

    rect rgb(200, 230, 255)
        Note over Client,DB: API Key Flow
        Client->>LB: GET /v1/rules (X-API-Key: sk-xxx)
        LB->>MW: Forward request
        MW->>Auth: authenticate(request)
        Auth->>Auth: Extract X-API-Key header
        Auth->>DB: Lookup key in keystore
        DB-->>Auth: {user_id, permissions, expires_at}
        alt Valid Key
            Auth-->>MW: AuthResult(authenticated=true, user=User)
            MW->>Handler: process_request(request)
            Handler-->>Client: 200 OK + data
        else Expired Key
            Auth-->>MW: AuthResult(authenticated=false, error="Key expired")
            MW-->>Client: 401 Unauthorized + error
        else Invalid Key
            Auth-->>MW: AuthResult(authenticated=false, error="Invalid key")
            MW-->>Client: 401 Unauthorized + error
        end
    end

    rect rgb(255, 235, 200)
        Note over Client,DB: JWT Flow
        Client->>LB: POST /auth/login (username, password)
        LB->>MW: Forward request
        MW->>Auth: authenticate(request)
        Auth->>DB: Verify credentials
        DB-->>Auth: credentials valid
        Auth->>Auth: Generate access_token (15m) + refresh_token (7d)
        Auth-->>MW: AuthResult(authenticated=true, token_pair=...)
        MW-->>Client: 200 OK + {access_token, refresh_token}
        Client->>LB: GET /v1/rules (Authorization: Bearer <access_token>)
        LB->>MW: Forward request
        MW->>Auth: validate_jwt(token)
        Auth->>Auth: Verify signature + expiry
        alt Valid Token
            Auth-->>MW: {user, roles}
            MW->>Handler: process_request(request)
            Handler-->>Client: 200 OK
        else Expired
            Auth-->>MW: TokenExpired
            MW-->>Client: 401 + error code "TOKEN_EXPIRED"
        end
    end

    rect rgb(230, 255, 230)
        Note over Client,DB: OAuth 2.0 Flow
        Client->>Auth: GET /auth/oauth/authorize?client_id=xxx&redirect_uri=yyy
        Auth->>Client: 302 redirect to OAuth provider
        Client->>OAuthP: Login + consent
        OAuthP-->>Client: Auth code (redirect to callback)
        Client->>Auth: POST /auth/oauth/token (code, client_secret)
        Auth->>OAuthP: Exchange code for token
        OAuthP-->>Auth: {access_token, id_token}
        Auth->>Auth: Validate id_token (JWKS)
        Auth->>DB: Create local session
        Auth-->>Client: {local_token, expires_at}
    end
```

## Deployment Topology

```mermaid
graph LR
    subgraph "Region US-East"
        LB1["ALB"]
        API1["API Instance 1"]
        API2["API Instance 2"]
        API3["API Instance 3"]
        R1["Redis Cache"]
        DB1["PostgreSQL"]
        LB1 --> API1
        LB1 --> API2
        LB1 --> API3
        API1 --> R1
        API1 --> DB1
        API2 --> R1
        API2 --> DB1
        API3 --> R1
        API3 --> DB1
    end

    subgraph "Region EU-West"
        LB2["ALB"]
        API4["API Instance 1"]
        API5["API Instance 2"]
        R2["Redis Cache"]
        DB2["PostgreSQL Replica"]
        LB2 --> API4
        LB2 --> API5
        API4 --> R2
        API4 --> DB2
        API5 --> R2
        API5 --> DB2
    end

    DNS["Route53<br/>Geo Routing"]
    DNS --> LB1
    DNS --> LB2

    DB1 <--> DB2["Async Replication"]
    R1 <--> R2["Active-Passive"]
```

## Middleware Pipeline Order

| Position | Middleware | Purpose | Skip Condition |
|---|---|---|---|
| 1 | RequestIDInjector | Adds unique trace ID to every request | None |
| 2 | CORSMiddleware | Validates origin, sets CORS headers | OPTIONS requests short-circuit |
| 3 | BodyParser | Parses JSON, form, multipart bodies | GET/HEAD/DELETE without body |
| 4 | RateLimiter | Token bucket rate limiting | Internal service calls |
| 5 | Authenticator | Routes to APIAuth strategy | Public endpoints only |
| 6 | RequestLogger | Structured logging with timing | Health check endpoints |
| 7 | Compressor | gzip/brotli response compression | Small responses (< 1KB) |
| 8 | ResponseFormatter | Standardizes response envelope | Stream/SSE responses |

## Error Handling Strategy

All errors follow a consistent envelope format:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request body validation failed",
    "details": [
      {"field": "age", "reason": "must be positive integer", "value": -5}
    ],
    "trace_id": "req-abc123",
    "timestamp": "2026-07-24T12:00:00Z"
  }
}
```

Errors propagate through the middleware in reverse order — innermost handler wraps the exception, outermost formats the response. Unhandled exceptions are caught by a global `ExceptionMiddleware` that logs the full stack trace and returns a sanitized 500 response.

## Security Considerations

- All traffic must use TLS 1.3 with HSTS preload
- API keys are stored as bcrypt hashes, never in plaintext
- JWT tokens use RS256 with a rotating signing key pair
- Rate limiting is applied per-user and per-IP simultaneously
- SQL injection prevention via parameterized queries in all resolvers
- GraphQL depth limiting prevents recursive query bombs
- WebSocket origins are validated against an allowlist