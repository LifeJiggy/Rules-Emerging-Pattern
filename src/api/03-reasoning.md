# API Logic & Decision Making

## Request Processing Flowchart

Every incoming request follows a deterministic path through validation, authentication, rate limiting, routing, response formatting, and audit logging. The flowchart below captures branching decisions at each stage.

```mermaid
flowchart TD
    Start(["Request Arrives"]) --> ParseBody["Parse Request Body"]
    ParseBody --> ContentType{"Content-Type<br/>Supported?"}

    ContentType -->|No| Reject415["415 Unsupported Media Type"]
    ContentType -->|Yes| ValidateSchema["Validate Against Schema"]

    ValidateSchema --> SchemaValid{"Schema<br/>Valid?"}
    SchemaValid -->|No| Reject422["422 Validation Error<br/>+ Field Errors"]
    SchemaValid -->|Yes| ExtractAuth["Extract Auth Headers"]

    ExtractAuth --> HasAuth{"Has API Key,<br/>JWT, or OAuth?"}

    HasAuth -->|No| IsPublic{"Is Public<br/>Endpoint?"}
    IsPublic -->|Yes| CheckRateLimit["Check Rate Limit"]
    IsPublic -->|No| Reject401["401 Unauthorized<br/>+ WWW-Authenticate"]

    HasAuth -->|Yes| AuthStrategy{"Which Auth<br/>Strategy?"}

    AuthStrategy -->|API Key| ValidateKey["Validate API Key<br/>against Key Store"]
    AuthStrategy -->|JWT| ValidateJWT["Validate JWT<br/>Signature + Expiry"]
    AuthStrategy -->|OAuth| ValidateOAuth["Validate OAuth Token<br/>against Provider"]

    ValidateKey --> KeyValid{"Key Valid<br/>+ Not Expired?"}
    ValidateJWT --> JWTValid{"Signature OK<br/>+ Not Expired?"}
    ValidateOAuth --> OAuthValid{"Token Valid?"}

    KeyValid -->|No| Reject401
    JWTValid -->|No| Reject401
    OAuthValid -->|No| Reject401

    KeyValid -->|Yes| ResolveRoles["Resolve User Roles"]
    JWTValid -->|Yes| ResolveRoles
    OAuthValid -->|Yes| ResolveRoles

    CheckRateLimit --> RateOk{"Rate Limit<br/>Exceeded?"}
    ResolveRoles --> CheckRateLimit2{"Rate Limit<br/>Exceeded?"}

    RateOk -->|Yes| Reject429["429 Too Many Requests<br/>+ Retry-After Header"]
    CheckRateLimit2 -->|Yes| Reject429

    RateOk -->|No| RouteRequest["Route to Handler"]
    CheckRateLimit2 -->|No| RouteRequest

    RouteRequest --> AuthorizeAction{"User Authorized<br/>for this Action?"}

    AuthorizeAction -->|No| Reject403["403 Forbidden"]
    AuthorizeAction -->|Yes| ExecuteHandler["Execute Handler"]

    ExecuteHandler --> HandlerResult{"Handler<br/>Succeeded?"}

    HandlerResult -->|No| HandlerError{"Error Type?"}
    HandlerError -->|NotFound| Reject404["404 Not Found"]
    HandlerError -->|Conflict| Reject409["409 Conflict"]
    HandlerError -->|Internal| Reject500["500 Internal Server Error"]
    HandlerError -->|Timeout| Reject504["504 Gateway Timeout"]

    HandlerResult -->|Yes| FormatResponse["Format Response<br/>+ Add Headers"]

    FormatResponse --> Envelope{"Use Standard<br/>Envelope?"}

    Envelope -->|Yes| WrapEnvelope["Wrap in {data, meta, errors}"]
    Envelope -->|No| RawResponse["Return Raw Response"]

    WrapEnvelope --> AuditLog["Write Audit Log"]
    RawResponse --> AuditLog

    AuditLog --> Compress{"Compress<br/>Response?"}
    Compress -->|Yes| Gzip["Apply gzip/brotli"]
    Compress -->|No| Return["Return Response"]

    Gzip --> Return

    style Start fill:#1565C0,color:#fff
    style Reject401 fill:#C62828,color:#fff
    style Reject403 fill:#C62828,color:#fff
    style Reject422 fill:#E65100,color:#fff
    style Reject429 fill:#E65100,color:#fff
    style Reject500 fill:#B71C1C,color:#fff
    style Return fill:#2E7D32,color:#fff
```

## WebSocket Reconnection Strategy

When a WebSocket connection drops, the client-side handler follows a decision tree to determine the reconnection approach based on the close code, the number of previous attempts, and the current network state.

```mermaid
flowchart TD
    Start(["WebSocket Closed"]) --> GetCode["Get Close Code"]

    GetCode --> CodeCheck{"Close Code?"}

    CodeCheck -->|1000 Normal| NoReconnect["No Reconnect<br/>Intentional close"]
    CodeCheck -->|1001 Going Away| NoReconnect
    CodeCheck -->|1002 Protocol Error| RetryCheck1{"Retry Count<br/>< 3?"}
    CodeCheck -->|1003 Unsupported| NoReconnect
    CodeCheck -->|1005 No Status| RetryCheck5{"Retry Count<br/>< 5?"}
    CodeCheck -->|1006 Abnormal| RetryCheck5
    CodeCheck -->|1007 Invalid Frame| RetryCheck1
    CodeCheck -->|1008 Policy Violation| NoReconnect
    CodeCheck -->|1009 Too Large| Resize["Resize Message Buffer"]
    CodeCheck -->|1010 Missing Extension| RetryCheck1
    CodeCheck -->|1011 Internal Error| RetryCheck5
    CodeCheck -->|1012 Service Restart| RetryCheck10{"Retry Count<br/>< 10?"}
    CodeCheck -->|1013 Try Again Later| RetryCheck10
    CodeCheck -->|4000-4999 App| RetryCheck3{"Retry Count<br/>< 3?"}

    Resize --> ReconnectImmediate["Reconnect Immediately<br/>with larger buffer"]

    RetryCheck1 -->|Yes| ReconnectImmediate
    RetryCheck1 -->|No| GiveUp["Give Up<br/>Report Error"]

    RetryCheck5 -->|Yes| Backoff["Exponential Backoff<br/>delay = min(2^n * 1s, 60s)"]
    RetryCheck5 -->|No| GiveUp

    RetryCheck10 -->|Yes| Backoff
    RetryCheck10 -->|No| GiveUp

    RetryCheck3 -->|Yes| Backoff
    RetryCheck3 -->|No| GiveUp

    Backoff --> WaitDelay["Wait delay seconds"]
    WaitDelay --> HealthCheck{"Network<br/>Reachable?"}

    HealthCheck -->|No| WaitLonger["Wait +5s, check again"]
    WaitLonger --> HealthCheck

    HealthCheck -->|Yes| AuthRefresh["Check Token Expiry"]

    AuthRefresh --> TokenExpired{"Token<br/>Expired?"}

    TokenExpired -->|Yes| RefreshToken["Attempt Token Refresh"]
    RefreshToken --> RefreshOk{"Refresh<br/>Successful?"}
    RefreshOk -->|Yes| Connect["Reconnect with new token"]
    RefreshOk -->|No| GiveUp

    TokenExpired -->|No| Connect

    Connect --> Subscribe["Resubscribe to Channels"]
    Subscribe --> RestoreState["Restore Local State"]
    RestoreState --> Done(["Connected"])

    style Start fill:#E65100,color:#fff
    style Done fill:#2E7D32,color:#fff
    style NoReconnect fill:#757575,color:#fff
    style GiveUp fill:#C62828,color:#fff
```

## API Version Resolution Logic

The API supports multiple concurrent versions. When a request arrives, the system determines which version to use based on URL prefix, custom headers, or content negotiation.

```mermaid
flowchart TD
    Start(["Request Received"]) --> CheckURL{"URL Contains<br/>Version Prefix?"}

    CheckURL -->|Yes| ExtractURL["Extract version from URL<br/>e.g., /v2/rules → v2"]
    CheckURL -->|No| CheckHeader{"Has Accept-Version<br/>or X-API-Version?"}

    CheckHeader -->|Yes| ParseHeader["Parse Version Header<br/>e.g., Accept-Version: 2026-07"]
    CheckHeader -->|No| CheckContentNeg{"Content Negotiation<br/>Accept: application/vnd.api+json; version=2"}

    CheckContentNeg -->|Yes| ParseAccept["Parse media type<br/>parameter version"]
    CheckContentNeg -->|No| DefaultVersion["Use Default Version<br/>config.api.default_version"]

    ExtractURL --> ValidateURL{"Version<br/>Exists?"}
    ParseHeader --> ValidateHeader{"Version<br/>Exists?"}
    ParseAccept --> ValidateAccept{"Version<br/>Exists?"}
    DefaultVersion --> UseDefault["Route to<br/>Default Version Handler"]

    ValidateURL -->|Yes| CheckDeprecated{"Version<br/>Deprecated?"}
    ValidateURL -->|No| Fallback["404 Version Not Found"]
    ValidateHeader -->|Yes| CheckDeprecated
    ValidateHeader -->|No| Fallback
    ValidateAccept -->|Yes| CheckDeprecated
    ValidateAccept -->|No| Fallback

    CheckDeprecated -->|Yes| AddWarning["Add Warning Header<br/>Warning: 299 api/v1 \"Deprecated, sunset 2027-01\""]
    CheckDeprecated -->|No| NoWarning["No Warning Needed"]

    AddWarning --> LoadSchema["Load Version Schema"]
    NoWarning --> LoadSchema

    LoadSchema --> CheckCompat{"Backward Compat<br/>Override?"}

    CheckCompat -->|Yes| PatchSchema["Apply Compatibility<br/>Shims"]
    CheckCompat -->|No| UseSchema["Use Standard Schema"]

    PatchSchema --> RouteHandler["Route to Version Handler"]
    UseSchema --> RouteHandler

    RouteHandler --> Execute["Execute Request"]

    Fallback --> Respond404["Respond 404"]

    style Start fill:#1565C0,color:#fff
    style Execute fill:#2E7D32,color:#fff
    style Respond404 fill:#C62828,color:#fff
```

## Rate Limiting Decision Logic

```mermaid
flowchart TD
    Start(["Rate Limit Check"]) --> IdentifyKey["Identify Key<br/>(user_id + endpoint + IP)"]

    IdentifyKey --> LookupBucket["Lookup Token Bucket"]
    LookupBucket --> BucketExists{"Bucket<br/>Exists?"}

    BucketExists -->|No| CreateBucket["Create Bucket<br/>tokens = max_burst"]
    BucketExists -->|Yes| RefillBucket["Refill Tokens<br/>tokens += rate * elapsed<br/>cap at max_burst"]

    CreateBucket --> Allow["Allow Request<br/>tokens -= 1"]
    RefillBucket --> HasTokens{"tokens >= 1?"}

    HasTokens -->|Yes| Allow
    HasTokens -->|No| CalculateWait{"Wait Time<br/>Acceptable?"}

    CalculateWait -->|Yes| QueueRequest["Queue for<br/>wait_ms seconds"]
    CalculateWait -->|No| Deny["Deny Request<br/>Retry-After: wait_ms"]

    Allow --> UpdateStore["Update Store<br/>remaining = tokens"]
    Deny --> UpdateStore
    QueueRequest --> UpdateStore

    UpdateStore --> Return["Return Result"]

    style Start fill:#E65100,color:#fff
    style Allow fill:#2E7D32,color:#fff
    style Deny fill:#C62828,color:#fff
    style Return fill:#1565C0,color:#fff
```

## Caching Strategy

```mermaid
flowchart TD
    Start(["Cache Check"]) --> CacheKey["Build Cache Key<br/>method:path:params:user_id"]

    CacheKey --> Lookup["Check Redis Cache"]

    Lookup --> Hit{"Cache HIT?"}

    Hit -->|Yes| CheckFresh{"Still Fresh<br/>(TTL > 0)?"}
    CheckFresh -->|Yes| Stale{"Stale-While-Revalidate<br/>Window?"}
    Stale -->|Yes| ServeStale["Serve Cached Data"]
    ServeStale --> AsyncRefresh["Async Refresh in Background"]
    Stale -->|No| ServeStale2["Serve Stale<br/>+ Set New TTL"]
    CheckFresh -->|No| Stale

    AsyncRefresh --> Fetch["Fetch from Origin"]
    Stale --> Fetch["Fetch from Origin"]
    ServeStale2 --> Fetch
    Hit -->|No| Fetch

    Fetch --> Store["Store in Redis<br/>TTL = cache_config.ttl"]
    Store --> Return["Return Fresh Data"]

    style Start fill:#1565C0,color:#fff
    style Return fill:#2E7D32,color:#fff
    style ServeStale fill:#F57F17,color:#fff
```

## Content Negotiation

When a client sends an HTTP request, the API determines the response format through a multi-step negotiation process:

1. **Parse Accept header**: Extract weighted media types (`application/json; q=0.9`, `text/html; q=0.5`)
2. **Filter supported types**: Remove types the API cannot produce
3. **Weight comparison**: Select the type with the highest quality factor
4. **Fallback chain**: If no match, try `application/json`; if JSON fails, use `text/plain`

The negotiated format affects serialization (JSON, XML, YAML, MsgPack), compression (none, gzip, brotli), and schema validation (strict vs lenient mode for requested version).

## Timeout Handling

| Stage | Timeout | Action on Timeout |
|---|---|---|
| Request parsing | 5s | 400 Bad Request |
| Authentication | 3s | 503, circuit breaker |
| Rate limit check | 1s | Bypass, log warning |
| Handler execution | 30s | 504, kill goroutine/coroutine |
| Response serialization | 5s | 500, log error |
| Audit log write | 2s | Async fire-and-forget |

Configurable via the `API_TIMEOUTS` environment variable as a JSON map of stage-to-seconds pairs. Separate read and write timeouts for database-accessing handlers.