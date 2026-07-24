# Middleware Module Data Flow

## 1. Full Request Processing Pipeline

End-to-end flow showing how all five middleware components process a single request.

```mermaid
sequenceDiagram
    participant C as Client
    participant V as ValidationMiddleware
    participant L as LoggingMiddleware
    participant A as AuthMiddleware
    participant R as RateLimitMiddleware
    participant AD as AuditMiddleware
    participant H as Rules Engine Handler

    C->>V: POST /api/rules/execute (payload + headers)

    activate V
    V->>V: normalize_request (uppercase method, title-case headers)
    V->>V: enrich request (request_id, timestamp, client_ip)
    V->>V: sanitize_headers (block proxy headers, strip X-Forwarded-For)
    V->>V: sanitize_value(body) → strip HTML, remove null bytes
    V->>V: validate content_type, method, size
    V-->>L: ValidatedRequest(sanitized, metadata)
    deactivate V

    activate L
    L->>L: mask_headers (redact Authorization, Cookie)
    L->>L: mask_body (redact password, token fields)
    L->>L: create LogEntry with correlation_id
    L->>L: log_request → JSON format → stdout/file
    L-->>A: forward with correlation_id header
    deactivate L

    activate A
    A->>A: extract Authorization header
    A->>A: token_handler.validate_token(bearer_token)
    A->>A: parse JWT payload → user_id, roles
    A->>A: role_manager.get_all_permissions(roles)
    A->>A: enrich request with _user context
    A-->>R: AuthResultData(GRANTED, UserContext)
    deactivate A

    activate R
    R->>R: build_key(rule, ip, user_id, route)
    R->>R: sliding_window.check(key) → current_count
    R->>R: allowed = current_count < max_requests
    R-->>AD: RateLimitResult(allowed=True)
    deactivate R

    activate AD
    AD->>AD: record_request(request)
    AD->>AD: _should_track("request_processed", "request") → True
    AD->>AD: storage.store(AuditRecord)
    AD-->>H: sanitized, authorized request
    deactivate AD

    activate H
    H->>H: Execute rule evaluation
    H-->>AD: response
    deactivate H

    activate AD
    AD->>AD: record_rule_evaluation(...)
    AD-->>L: response
    deactivate AD

    activate L
    L->>L: log_response(status, duration_ms)
    L-->>V: response
    deactivate L

    activate V
    V->>V: formatter.format_response(response)
    V-->>C: 200 OK (JSON body)
    deactivate V
```

## 2. Authentication Flow with Multiple Providers

The `AuthMiddleware` tries providers in order until one succeeds.

```mermaid
sequenceDiagram
    participant C as Client
    participant AM as AuthMiddleware
    participant TH as TokenHandler
    participant AKH as APIKeyHandler
    participant SH as SessionHandler
    participant RM as RoleManager
    participant CF as Cache / Failures

    C->>AM: authenticate(request)

    activate AM
    AM->>AM: is_public_route? → No
    AM->>CF: cache_auth_results? → check cache
    CF-->>AM: cache miss

    AM->>CF: _is_rate_limited(ip)?
    CF-->>AM: No

    Note over AM: Try provider 1: BEARER

    AM->>TH: validate_token("Bearer eyJ...")
    TH->>TH: split token → header, payload, signature
    TH->>TH: base64url_decode(header) → {"alg":"HS256"}
    TH->>TH: base64url_decode(payload) → {"sub":"u1","roles":["editor"]}
    TH->>TH: _sign(header.payload) with secret_key
    TH->>TH: hmac.compare_digest(signature, expected)
    TH->>TH: check exp, iss, aud
    TH-->>AM: valid=True, payload={"sub":"u1","roles":["editor"]}

    AM->>RM: get_all_permissions(["editor"])
    RM->>RM: inherit permissions from "editor" → includes ["read","write","export","import"]
    RM-->>AM: {"read","write","export","import"}

    AM->>AM: create UserContext(user_id="u1", roles=["editor"], permissions=...)

    AM->>CF: _record_failure? No (success)
    AM->>CF: cache result
    deactivate AM

    AM-->>C: AuthResultData(result=GRANTED, user=UserContext)

    Note over C,AM: If bearer fails, provider 2 (API_KEY) is tried next
    Note over C,AM: If all providers MISSING → 401 challenge
    Note over C,AM: If 5+ failures in 300s → RATE_LIMITED (429)
```

## 3. Rate Limit Decision Flow

The `RateLimitMiddleware` checks multiple rules and returns the first denied result.

```mermaid
sequenceDiagram
    participant C as Client
    participant RL as RateLimitMiddleware
    participant SW as SlidingWindowCounter
    participant TB as TokenBucket
    participant BO as BackoffController
    participant Stats as RateLimitStats

    C->>RL: check_rate_limit(request)

    activate RL
    RL->>RL: _maybe_cleanup() → check elapsed time

    RL->>RL: Check whitelist (IP, user, route)
    Note over RL: 10.0.0.1 not in whitelist

    RL->>RL: Check blacklist (IP, user)
    Note over RL: 10.0.0.1 not in blacklist

    RL->>Stats: total_requests += 1

    Note over RL: Sort rules by priority descending
    RL->>RL: Process rule "global" (priority=0, scope=GLOBAL)
    RL->>RL: _build_key → "global"
    RL->>SW: check("global")
    SW->>SW: prune timestamps older than window
    SW->>SW: current_count = len(deque) = 5
    SW->>SW: allowed = 5 < 10000 → True
    SW->>SW: append(now) → count = 6
    SW-->>RL: allowed=True, remaining=9994

    RL->>RL: Process rule "per_ip" (priority=0, scope=PER_IP)
    RL->>RL: _build_key → "ip:10.0.0.1"
    RL->>TB: check("ip:10.0.0.1")
    TB->>TB: elapsed = now - last_refill
    TB->>TB: tokens = min(capacity, tokens + elapsed * refill_rate)
    TB->>TB: allowed = tokens >= 1.0
    TB->>TB: tokens -= 1.0
    TB-->>RL: allowed=True, remaining=149

    RL->>RL: All rules passed
    RL->>Stats: allowed_requests += 1
    deactivate RL

    RL-->>C: RateLimitResult(allowed=True, remaining=149, limit=200)

    Note over C,RL: If a rule denies → stats.denied_requests++, backoff recorded
```

## 4. Audit Record Creation and Storage Flow

The `AuditMiddleware` records events with multi-indexed storage.

```mermaid
sequenceDiagram
    participant App as Application
    participant AM as AuditMiddleware
    participant Store as AuditStorage
    participant Idx as Indexes
    participant Stats as AuditStats

    App->>AM: record_rule_evaluation(rule_name="age_check", actor_id="system", result="passed", duration_ms=3.2)

    activate AM
    AM->>AM: _should_track("rule_evaluated", "rule") → True
    AM->>AM: actor_id "system" in excluded_actors? → No

    AM->>AM: Generate record_id = uuid4()
    AM->>AM: Create AuditRecord with all fields
    Note over AM: record.timestamp = now ISO-8601
    Note over AM: record.severity = "INFO"
    Note over AM: record.event_type = "rule_evaluated"

    AM->>AM: _mask_sensitive(metadata) → no sensitive fields

    AM->>Store: store(AuditRecord)
    activate Store

    Store->>Store: Check max_records → 5000 < 100000
    Store->>Store: _records[record_id] = record
    Store->>Idx: _indexes["event_type"]["rule_evaluated"].append(record_id)
    Store->>Idx: _indexes["actor_id"]["system"].append(record_id)
    Store->>Idx: _indexes["resource_type"]["rule"].append(record_id)
    Store->>Idx: _indexes["severity"]["INFO"].append(record_id)
    Store->>Idx: _indexes["timestamp"]["2026-07-24"].append(record_id)
    deactivate Store

    AM->>Stats: total_records += 1
    AM->>Stats: records_by_type["rule_evaluated"] += 1
    AM->>Stats: records_by_actor["system"] += 1
    AM->>Stats: records_by_severity["INFO"] += 1
    AM->>Stats: records_by_resource["rule"] += 1

    deactivate AM

    App-->>AM: record_id = "uuid-string"

    Note over App,AM: Later...

    App->>AM: query(event_types=["rule_evaluated"], actor_ids=["system"], limit=10)

    activate AM
    AM->>Store: query(AuditFilter)
    activate Store
    Store->>Store: Filter: event_type in ["rule_evaluated"]
    Store->>Store: Filter: actor_id in ["system"]
    Store->>Store: Sort by timestamp desc
    Store-->>AM: [AuditRecord, ...]
    deactivate Store
    deactivate AM
```

## 5. Logging with Sensitive Data Masking

The `LoggingMiddleware` masks sensitive fields before writing log entries.

```mermaid
sequenceDiagram
    participant App as Application
    participant LM as LoggingMiddleware
    participant Masker as SensitiveDataMasker
    participant Sampler as LogSampler
    participant Formatter as StructuredLogFormatter
    participant File as Log File

    App->>LM: log_request({"method":"POST","headers":{"Authorization":"Bearer eyJ...","Content-Type":"application/json"},"body":{"password":"secret123","email":"user@test.com"}})

    activate LM
    LM->>Sampler: should_log("core", 1.0)
    Sampler-->>LM: True

    LM->>Masker: mask_headers({"Authorization":"Bearer eyJ...","Content-Type":"application/json"})
    Masker->>Masker: sensitive=["authorization","cookie","set-cookie","x-api-key"]
    Masker->>Masker: key="authorization" in sensitive → redact
    Masker-->>LM: {"Authorization":"***","Content-Type":"application/json"}

    LM->>Masker: mask_body({"password":"secret123","email":"user@test.com"})
    Masker->>Masker: key="password" → "password" in global_mask_fields → mask_value
    Masker->>Masker: mask_value("secret123") → "se***23"
    Masker->>Masker: key="email" → "email" in global_mask_fields → mask_value
    Masker->>Masker: mask_value("user@test.com") → "us***om"
    Masker-->>LM: {"password":"se***23","email":"us***om"}

    LM->>Masker: mask_body truncation? body < 4096 bytes → no truncation

    LM->>Formatter: format_entry(LogEntry)
    Formatter->>Formatter: Build structured dict with timestamp, level, component, event_type, message
    Formatter-->>LM: structured dict

    LM->>LM: get_component_logger("core") → logger.core
    LM->>File: logger.info("Request: POST /api/login", extra={"extra_fields": structured})
    File-->>LM: written
    deactivate LM

    LM-->>App: correlation_id = "uuid"
```

## 6. Validation and Sanitization Flow

The `ValidationMiddleware` transforms a raw request into a sanitized, enriched `ValidatedRequest`.

```mermaid
sequenceDiagram
    participant C as Client
    participant VM as ValidationMiddleware
    participant Enricher as RequestEnricher
    participant Sanitizer as ContentSanitizer
    participant HS as HTMLSanitizer
    participant WN as WhitespaceNormalizer
    participant Coercer as TypeCoercer

    C->>VM: validate_request({"method":"POST","route":"/api/data","headers":{"Content-Type":"application/json"},"body":{"name":"<b>John</b>","age":"25","comment":"<script>alert(1)</script>"}})

    activate VM
    VM->>Enricher: enrich(request)
    Enricher->>Enricher: Generate request_id = uuid4()
    Enricher->>Enricher: Extract client_ip from X-Forwarded-For
    Enricher->>Enricher: Add _metadata block
    Enricher-->>VM: enriched request

    VM->>Sanitizer: sanitize_headers(headers)
    Sanitizer->>Sanitizer: Check blocked_headers list
    Sanitizer-->>VM: sanitized headers

    VM->>Sanitizer: sanitize_value(body)
    Sanitizer->>Sanitizer: sanitize_string("<b>John</b>")

    Sanitizer->>HS: strip_html_tags("<b>John</b>")
    HS->>HS: re.sub(r"<[^>]*>", "", text) → "John"
    HS-->>Sanitizer: "John"

    Sanitizer->>HS: remove_script_tags("John")
    HS->>HS: No script patterns → unchanged
    HS-->>Sanitizer: "John"

    Sanitizer->>HS: sanitize_attribute("John") → unchanged
    Sanitizer->>HS: sanitize_url("John") → unchanged
    Sanitizer->>HS: html.escape("John") → "John"

    Sanitizer->>WN: normalize("John") → "John"
    Sanitizer-->>VM: "John"

    Sanitizer->>Sanitizer: sanitize_string("<script>alert(1)</script>")
    Sanitizer->>HS: strip_html_tags → ""
    Sanitizer->>HS: remove_script_tags → ""
    Sanitizer-->>VM: "" (empty string)

    Sanitizer->>Sanitizer: sanitize_value("25") → str unchanged (no type coercion)
    Sanitizer-->>VM: "25" as string

    VM->>Coercer: coerce("25", "int")? Only if coerce_types enabled → no
    Coercer-->>VM: "25" kept as string

    VM->>VM: Check validation rules for route /api/data
    VM->>VM: Check body size < max_request_size
    VM->>VM: Check method in allowed_methods
    VM->>VM: Check Content-Type in allowed_content_types

    deactivate VM

    VM-->>C: ValidatedRequest(valid=True, sanitized={body:{name:"John",age:"25",comment:""}, warnings:["age should be int"]})
```
