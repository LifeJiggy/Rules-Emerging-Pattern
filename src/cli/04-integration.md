# CLI Integration

## System Integration Diagram

The CLI module integrates with the API (HTTP calls for data operations), Core (direct import for local evaluations), and Tools (debugging and diagnostics). Each integration path uses a different communication pattern.

```mermaid
graph TB
    subgraph "CLI Module"
        CLI["CLI Application"]
        SHELL["InteractiveShell"]
        BATCH["BatchProcessor"]
        CONFIG["ConfigCommands"]
        FORMAT["OutputFormatter"]
    end

    subgraph "API Integration"
        APC["APIClient<br/>HTTP/HTTPS"]
        REST["REST API<br/>/v1/*"]
        WS["WebSocket<br/>Event Stream"]
        GQL["GraphQL"]
    end

    subgraph "Core Integration"
        CE["RuleEngine<br/>Direct Import"]
        EVAL["Evaluator"]
        COMP["Compiler<br/>AST → Bytecode"]
        STORE["RuleStore<br/>In-Memory"]
    end

    subgraph "Tools Integration"
        DBG["DebugConsole"]
        PROF["Profiler<br/>cProfile / py-spy"]
        LOGS["Log Analyzer"]
        DIFF["Diff Tool<br/>Config Compare"]
    end

    subgraph "External Systems"
        FILE["File System<br/>Input / Output"]
        ENV["Environment<br/>Variables"]
        TTY["Terminal<br/>stdout / stderr"]
    end

    CLI --> APC
    CLI --> CE
    CLI --> DBG
    SHELL --> APC
    SHELL --> CE
    SHELL --> DBG
    BATCH --> APC
    BATCH --> FILE
    CONFIG --> FILE
    CONFIG --> ENV
    FORMAT --> TTY

    APC --> REST
    APC --> WS
    APC --> GQL

    CE --> EVAL
    CE --> COMP
    CE --> STORE

    REST -->|Remote| CE
    WS -->|Stream| CE
    GQL -->|Query| CE

    DBG --> PROF
    DBG --> LOGS
    DBG --> DIFF

    style CLI fill:#1565C0,color:#fff
    style APC fill:#1976D2,color:#fff
    style CE fill:#388E3C,color:#fff
    style DBG fill:#7B1FA2,color:#fff
    style FILE fill:#F57F17,color:#fff
    style TTY fill:#4CAF50,color:#fff
```

## CLI-to-API Integration Sequence

The most common integration path is the CLI making HTTP calls to the API server. The sequence below shows a complete command lifecycle including request building, retry logic, response parsing, and output formatting.

```mermaid
sequenceDiagram
    participant User
    participant CLI as CLIApplication
    participant Cmd as EvaluateCommand
    participant API as APIClient
    participant LB as Load Balancer
    participant Server as API Server
    participant Format as OutputFormatter

    User->>CLI: rules-cli evaluate r001 -c '{"age":25}' -f json

    rect rgb(230, 242, 255)
        Note over CLI,Cmd: Initialization
        CLI->>CLI: parse_args()
        CLI->>CLI: load_config()
        CLI->>CLI: init_api_client()
    end

    CLI->>Cmd: handle(args, config, api, formatter)

    rect rgb(255, 235, 200)
        Note over Cmd,API: Build Request
        Cmd->>Cmd: build_url("/v1/evaluate")
        Cmd->>Cmd: build_payload(rule_id="r001", context={"age": 25})
        Cmd->>Cmd: select_format("json", config.output_format)
    end

    Cmd->>API: post("/v1/evaluate", json=payload)

    rect rgb(200, 255, 200)
        Note over API,API: Request Execution
        API->>API: build_headers()
        Note over API,API: Authorization: Bearer sk-xxx
        Note over API,API: Content-Type: application/json
        Note over API,API: User-Agent: rules-cli/1.0
        Note over API,API: X-Request-Id: req-abc123

        API->>LB: POST /v1/evaluate
        Note over API,LB: SSL/TLS handshake
        LB->>Server: POST /v1/evaluate
        Server-->>LB: 200 OK
        Note over Server,LB: {"passed": true, "score": 0.95}
        LB-->>API: 200 OK
    end

    API-->>Cmd: {"passed": true, "score": 0.95}

    alt Error Response
        Note over API,Cmd: Connection Error
        API->>API: should_retry(ConnectionError)
        API->>API: apply_backoff(attempt=1, delay=500ms)
        API->>LB: POST /v1/evaluate
        LB-->>API: 200 OK
        API-->>Cmd: {"passed": true, "score": 0.95}
    end

    rect rgb(245, 245, 255)
        Note over Cmd,Format: Process Response
        Cmd->>Cmd: parse_response(data)
        Cmd->>Cmd: check_for_warnings(headers)
        Cmd->>Cmd: extract_metadata(data)
    end

    Cmd->>Format: format(data, "json")

    rect rgb(255, 255, 230)
        Note over Format,Format: Format Output
        Format->>Format: json.dumps({"passed": true, "score": 0.95}, indent=2)
        alt Color Enabled
            Format->>Format: pygments.highlight(json_str, JsonLexer, TerminalFormatter)
        end
        Format-->>Cmd: formatted string
    end

    Cmd-->>CLI: 0

    CLI-->>User: {
    CLI-->>User:   "passed": true,
    CLI-->>User:   "score": 0.95
    CLI-->>User: }
    Note over CLI,User: Colored JSON output with syntax highlighting
```

## Direct Core Integration

For local development and testing, the CLI can bypass the API and import Core modules directly. This path is faster and works offline.

```mermaid
sequenceDiagram
    participant User
    participant CLI as CLIApplication
    participant Cmd as EvaluateCommand
    participant Core as RuleEngine
    participant Comp as Compiler
    participant Eval as Evaluator
    participant Format as OutputFormatter

    User->>CLI: rules-cli evaluate r001 -c '{"age":25}' --local

    CLI->>Cmd: handle(args, config, api, formatter)

    Note over Cmd,Cmd: --local flag detected, bypass API

    Cmd->>Core: evaluate_local(rule_id="r001", context={"age": 25})

    Core->>Comp: load_rule("r001")
    Note over Comp,Comp: Reads from local rules/ directory

    Comp->>Comp: read_rule_file("rules/r001.yaml")
    Comp->>Comp: parse_expression("age >= 18")
    Comp->>Comp: compile_to_bytecode()
    Comp-->>Core: CompiledRule(bytecode, metadata)

    Core->>Eval: execute_bytecode(bytecode, context)
    Eval->>Eval: push context {"age": 25}
    Eval->>Eval: load variable "age" → 25
    Eval->>Eval: load constant 18
    Eval->>Eval: compare >= → True
    Eval-->>Core: EvaluationResult(passed=true, score=0.94)

    Core-->>Cmd: {"passed": true, "score": 0.94, "mode": "local"}

    Cmd->>Format: format(result, "json")
    Format-->>Cmd: formatted json

    Cmd-->>CLI: 0

    CLI-->>User: {"passed": true, "score": 0.94, "mode": "local"}
```

## Batch Integration with API

```mermaid
sequenceDiagram
    participant User
    participant BATCH as BatchProcessor
    participant READ as FileReader
    participant EXEC as CommandExecutor
    participant API as APIClient
    participant SERVER as API Server
    participant WRITE as FileWriter
    participant FORMAT as OutputFormatter

    User->>BATCH: batch --input evaluations.csv --output results.json

    BATCH->>READ: read_input("evaluations.csv")
    READ->>READ: detect_format() → csv
    READ->>READ: parse_csv()
    READ-->>BATCH: 100 commands

    BATCH->>BATCH: validate_commands()
    BATCH->>BATCH: configure_concurrency(5)
    BATCH->>BATCH: init_progress(total=100)

    loop Process Chunks (20 items each)
        BATCH->>EXEC: execute_chunk(items[0:20])

        par Worker 1
            EXEC->>API: post("/v1/evaluate/batch", json={items: [...]})
            API->>SERVER: POST /v1/evaluate/batch
            SERVER-->>API: 200, {results: [{...}, ...]}
            API-->>EXEC: parsed results
            EXEC->>BATCH: report_progress(succeeded=20)
            BATCH->>BATCH: update_progress_bar()
        and Worker 2
            EXEC->>API: post("/v1/evaluate/batch", json={items: [...]})
            API-->>EXEC: ConnectionError
            EXEC->>EXEC: retry(attempt=1, backoff=500ms)
            EXEC->>API: post("/v1/evaluate/batch", json={items: [...]})
            API-->>EXEC: ConnectionError
            EXEC->>EXEC: retry(attempt=2, backoff=1000ms)
            EXEC->>API: post("/v1/evaluate/batch", json={items: [...]})
            API-->>EXEC: 200 OK
            EXEC->>BATCH: report_progress(succeeded=20)
        end
    end

    BATCH->>BATCH: aggregate_results()
    Note over BATCH,BATCH: Total: 100, Succeeded: 98, Failed: 2, Duration: 8.3s

    BATCH->>FORMAT: format(batch_result, "json")
    FORMAT-->>BATCH: formatted json

    BATCH->>WRITE: write_output("results.json", formatted)
    WRITE->>WRITE: write_file(path)
    WRITE-->>BATCH: success

    alt Has Failures
        BATCH-->>User: Batch complete: 98/100 succeeded, 2 failed
        BATCH-->>User: Results written to results.json
        BATCH-->>User: exit code 5
    else All Succeeded
        BATCH-->>User: Batch complete: 100/100 succeeded
        BATCH-->>User: Results written to results.json
        BATCH-->>User: exit code 0
    end
```

## Debugging Tools Integration

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant CLI as CLIApplication
    participant Cmd as EvaluateCommand
    participant API as APIClient
    participant Server as API Server
    participant Debug as DebugConsole

    Dev->>CLI: rules-cli evaluate r001 -c '{"age":25}' --debug

    CLI->>Cmd: handle(args, config, api, formatter)

    Note over Cmd,Cmd: --debug flag enabled

    Cmd->>API: post("/v1/evaluate", json=payload, debug=True)

    API->>Server: POST /v1/evaluate
    Note over API,Server: Headers: X-Debug: true

    Server-->>API: 200 OK
    Note over Server,API: Body includes debug_info section

    API-->>Cmd: {"passed": true, "score": 0.95, "debug_info": {...}}

    Cmd->>Cmd: check_debug_flag()
    Note over Cmd,Cmd: debug_info present

    Cmd->>Debug: render_debug_output(debug_info)

    Debug->>Debug: format_timing(timing_ms)
    Note over Debug,Debug: ast_parse: 2ms
    Note over Debug,Debug: optimize: 1ms
    Note over Debug,Debug: execute: 0.5ms
    Note over Debug,Debug: total: 3.5ms

    Debug->>Debug: format_steps(steps)
    Note over Debug,Debug: Step 1: load age → 25
    Note over Debug,Debug: Step 2: load threshold → 18
    Note over Debug,Debug: Step 3: compare 25 >= 18 → True

    Debug->>Debug: format_rule_source(rule)
    Note over Debug,Debug: Rule: age >= 18
    Note over Debug,Debug: Priority: HIGH
    Note over Debug,Debug: Status: active

    Debug-->>Cmd: DebugOutput(timing, steps, source)

    Cmd->>Cmd: build_output(result, debug_output)

    CLI-->>Dev: ## Result
    CLI-->>Dev: {"passed": true, "score": 0.95}
    CLI-->>Dev:
    CLI-->>Dev: ## Debug Info
    CLI-->>Dev: Timing:
    CLI-->>Dev:   ast_parse: 2ms
    CLI-->>Dev:   optimize: 1ms
    CLI-->>Dev:   execute: 0.5ms
    CLI-->>Dev:   total: 3.5ms
    CLI-->>Dev:
    CLI-->>Dev: Evaluation Steps:
    CLI-->>Dev:   1. context: {age: 25}
    CLI-->>Dev:   2. load age → 25
    CLI-->>Dev:   3. load threshold → 18
    CLI-->>Dev:   4. 25 >= 18 → True
    CLI-->>Dev:   5. result: passed (score: 0.95)
```

## Configuration Integration Points

```mermaid
graph TB
    subgraph "Config Sources"
        S1["Default Config<br/>hardcoded defaults"]
        S2["Config File<br/>~/.rules/config.yaml"]
        S3["Profile Config<br/>~/.rules/profiles/"]
        S4["Environment Vars<br/>RULES_*"]
        S5["CLI Flags<br/>--format, --endpoint"]
    end

    subgraph "Merge Priority<br/>(highest wins)"
        M1["1. CLI Flags"]
        M2["2. Environment Vars"]
        M3["3. Active Profile"]
        M4["4. Config File"]
        M5["5. Defaults"]
    end

    subgraph "Consumers"
        C1["APIClient<br/>base_url, api_key, timeout"]
        C2["OutputFormatter<br/>format, color, width"]
        C3["BatchProcessor<br/>concurrency, continue_on_error"]
        C4["InteractiveShell<br/>history_size, prompt"]
        C5["ConfigCommands<br/>config_path, profile"]
    end

    S1 --> M5
    S2 --> M4
    S3 --> M3
    S4 --> M2
    S5 --> M1

    M5 --> Merge["Config Merge"]
    M4 --> Merge
    M3 --> Merge
    M2 --> Merge
    M1 --> Merge

    Merge --> C1
    Merge --> C2
    Merge --> C3
    Merge --> C4
    Merge --> C5

    style S1 fill:#BDBDBD,color:#000
    style S2 fill:#4CAF50,color:#fff
    style S3 fill:#2196F3,color:#fff