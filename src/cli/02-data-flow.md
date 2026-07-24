# CLI Data Flow

## Command Execution Flow

The sequence diagram below traces a single CLI command from user input through parsing, handler execution, and output rendering. Every command follows this same lifecycle.

```mermaid
sequenceDiagram
    participant User
    participant CLI as CLIApplication
    participant Parser as ArgumentParser
    participant Config as ConfigManager
    participant Handler as CommandHandler
    participant API as APIClient
    participant Server as API Server
    participant Formatter as OutputFormatter

    User->>CLI: rules-cli evaluate r001 --context '{"age": 25}'
    Note over User,CLI: Raw argv: ["evaluate", "r001", "--context", '{"age": 25}']

    rect rgb(230, 242, 255)
        Note over CLI,Config: Initialization Phase
        CLI->>CLI: load_config(~/.rules/config.yaml)
        CLI->>Config: load(path)
        Config-->>CLI: Config(evaluate, ...)
        CLI->>CLI: setup_logging(level=INFO)
        CLI->>CLI: init_http_client(retry=3, timeout=30)
    end

    CLI->>Parser: parse_args(argv)
    Note over CLI,Parser: Uses click decorators or argparse

    rect rgb(255, 235, 200)
        Note over Parser,Parser: Argument Parsing
        Parser->>Parser: match subcommand "evaluate"
        Parser->>Parser: parse positional: r001 → rule_id
        Parser->>Parser: parse optional: --context → {"age": 25}
        Parser-->>CLI: Namespace(command="evaluate", rule_id="r001", context={"age": 25}, format="json")
    end

    CLI->>CLI: validate_args(args)
    Note over CLI,CLI: Check rule_id is not empty, context is valid JSON

    alt Invalid Arguments
        CLI-->>User: Error: Missing required argument 'rule_id'
        CLI-->>User: Usage: evaluate <rule_id> [--context <json>]
        CLI-->>User: exit code 2
    end

    CLI->>Handler: handle(args, config, api, formatter)

    rect rgb(200, 255, 200)
        Note over Handler,Handler: Handler Execution
        Handler->>Handler: build_payload(rule_id="r001", context={"age": 25})
        Handler->>Handler: select_format(args.format, config.output_format)
    end

    Handler->>API: post("/v1/evaluate", json={"rule_id": "r001", "context": {"age": 25}})

    rect rgb(245, 245, 255)
        Note over API,Server: HTTP Request
        API->>API: build_headers(Authorization: Bearer sk-xxx)
        API->>API: serialize_body(json)
        API->>Server: POST /v1/evaluate
        Note over API,Server: Headers: Content-Type, Authorization, User-Agent
        Server-->>API: 200 OK
        Note over API,Server: Body: {"passed": true, "score": 0.95, "rule_id": "r001"}
    end

    API-->>Handler: {"passed": true, "score": 0.95, "rule_id": "r001"}

    Handler->>Handler: process_response(data)

    alt API Error
        Handler-->>User: Error: <message>
        Handler-->>User: exit code 4
    end

    Handler->>Formatter: format(data, format_type="json")

    rect rgb(255, 255, 230)
        Note over Formatter,Formatter: Output Formatting
        Formatter->>Formatter: select_formatter("json")
        Formatter->>Formatter: json.dumps(data, indent=2)
        Formatter-->>Handler: formatted string
    end

    Handler-->>CLI: 0 (success code)

    CLI->>CLI: set_exit_code(0)
    CLI-->>User: formatted_output
    Note over CLI,User: {
    Note over CLI,User:   "passed": true,
    Note over CLI,User:   "score": 0.95,
    Note over CLI,User:   "rule_id": "r001"
    Note over CLI,User: }

    User->>CLI: echo $?
    CLI-->>User: 0
```

## Batch Processing Flow

The batch processor reads commands from a file, executes them with configurable concurrency, and writes results to an output file. Progress is reported in real-time.

```mermaid
sequenceDiagram
    participant User
    participant Batch as BatchProcessor
    participant Reader as FileReader
    participant Exec as CommandExecutor
    participant Reporter as ProgressReporter
    participant API as APIClient
    participant Server as API Server
    participant Writer as FileWriter

    User->>Batch: batch --input evaluations.csv --output results.json --concurrency 5

    rect rgb(230, 242, 255)
        Note over Batch,Reader: Read Phase
        Batch->>Reader: read_input("evaluations.csv")
        Reader->>Reader: detect_format(csv)
        Reader->>Reader: parse_csv(header, rows)
        Reader-->>Batch: List[Command] (100 items)
        Note over Batch,Reader: Each item: {rule_id, context_json}
    end

    Batch->>Batch: validate_commands(commands)
    Batch->>Batch: configure_concurrency(5)
    Batch->>Batch: init_progress_bar(total=100)

    rect rgb(200, 255, 200)
        Note over Batch,API: Execution Phase
        par Concurrent Workers (5 at a time)
            Exec->>API: post("/v1/evaluate/batch", json={"items": [...20...]})
            API->>Server: POST /v1/evaluate/batch
            Server-->>API: 200 OK, {results: [...]}
            API-->>Exec: [result1, result2, ...]
            Exec->>Exec: parse_batch_response(data)

            Exec->>Reporter: report_progress(succeeded=20, failed=0)
            Reporter->>Reporter: update_progress_bar()
            Reporter-->>User: [#####-----] 20/100 (20%)
        end

        par Concurrent Workers (5 at a time)
            Exec->>API: post("/v1/evaluate/batch", json={"items": [...20...]})
            API->>Server: POST /v1/evaluate/batch
            Server-->>API: 200 OK
            API-->>Exec: [result1, result2, ...]
            Exec->>Reporter: report_progress(succeeded=40, failed=0)
            Reporter-->>User: [##########] 40/100 (40%)
        end

        par Concurrent Workers (5 at a time)
            Exec->>API: post("/v1/evaluate/batch", json={"items": [...20...]})
            API-->>Exec: NetworkError
            Exec->>Exec: apply_retry_policy(attempt=1)
            Exec->>API: post("/v1/evaluate/batch", ...)
            API-->>Exec: NetworkError
            Exec->>Exec: apply_retry_policy(attempt=2)
            Exec->>API: post("/v1/evaluate/batch", ...)
            API-->>Exec: 200 OK
            Exec->>Reporter: report_progress(succeeded=60, failed=0)
            Reporter-->>User: [##########] 60/100 (60%)
        end
    end

    rect rgb(255, 235, 200)
        Note over Batch,Writer: Write Phase
        Batch->>Batch: aggregate_results(all_results)
        Batch-->>Batch: BatchResult(total=100, succeeded=98, failed=2, duration=12.5s)

        alt Has Failures
            Batch->>Batch: summarize_failures(failures)
            Note over Batch,Batch: 2 items failed after 3 retries each
        end

        Batch->>Writer: write_output("results.json", batch_result)
        Writer->>Writer: serialize_json(pretty=True)
        Writer->>Writer: write_file(path)
        Writer-->>Batch: success
    end

    Batch-->>User: Batch complete: 98/100 succeeded, 2 failed
    Batch-->>User: Results written to results.json

    alt Has Failures
        Batch-->>User: exit code 5 (partial failure)
    else All Succeeded
        Batch-->>User: exit code 0
    end
```

## Config Command Flow

Configuration commands manage local settings through a load-modify-validate-save cycle. All mutations are transactional.

```mermaid
sequenceDiagram
    participant User
    participant Config as ConfigCommands
    participant Store as ConfigStore
    participant Profile as ProfileManager
    participant Validator as ConfigValidator

    User->>Config: config set api_key "sk-new-key"

    rect rgb(230, 242, 255)
        Note over Config,Store: Load Current Config
        Config->>Store: load(active_profile)
        Store->>Store: read_file(~/.rules/config.yaml)
        Store-->>Config: Config(profiles={default: {api_key: "sk-old-key", ...}}, active_profile="production")
    end

    Config->>Config: resolve_active_config()
    Config-->>Config: current_profile = "production"

    rect rgb(255, 235, 200)
        Note over Config,Validator: Modify + Validate
        Config->>Config: set_nested(profile.production.api_key, "sk-new-key")
        Config-->>Config: modified_config

        Config->>Validator: validate_key(modified_config)
        Validator->>Validator: check_api_key_length("sk-new-key")
        Validator->>Validator: check_api_key_format("sk-new-key")
        alt Invalid
            Validator-->>Config: ValidationError("API key must start with sk-")
            Config-->>User: Error: API key must start with sk-
            Config-->>User: Config not saved
        end
    end

    rect rgb(200, 255, 200)
        Note over Config,Store: Save Phase
        Config->>Config: create_backup(~/.rules/config.yaml.bak)

        alt Backup Failed
            Config-->>User: Warning: Could not create backup
        end

        Config->>Store: save(modified_config, ~/.rules/config.yaml)
        Store->>Store: atomic_write(temp_path, new_content)
        Store->>Store: rename(temp_path, config_path)
        Store-->>Config: success
    end

    Config-->>User: api_key set to "sk-new-key" (profile: production)
    Config-->>User: Config saved to ~/.rules/config.yaml

    User->>Config: config get api_key
    Config->>Store: load()
    Store-->>Config: Config
    Config->>Config: get("api_key")
    Config-->>User: sk-new-key

    User->>Config: config profile switch default
    Config->>Profile: switch("default")
    Profile->>Profile: validate_profile_exists("default")
    Profile->>Profile: set_active_profile("default")
    Profile->>Profile: persist_active_profile()
    Profile-->>Config: profile switched
    Config-->>User: Switched to profile "default"

    User->>Config: config export ./backup.yaml
    Config->>Store: export("./backup.yaml")
    Store->>Store: serialize_config()
    Store->>Store: write_file("./backup.yaml")
    Store-->>Config: success
    Config-->>User: Config exported to ./backup.yaml

    User->>Config: config import ./backup.yaml
    Config->>Validator: validate_import("./backup.yaml")
    Validator->>Validator: parse_yaml(file)
    Validator->>Validator: validate_schema(parsed)
    Validator-->>Config: valid
    Config->>Config: merge_import(parsed, current)
    Config->>Store: save(merged)
    Store-->>Config: success
    Config-->>User: Config imported and merged
```

## Data Transformation Pipeline

```mermaid
flowchart LR
    subgraph "Input Sources"
        I1["CLI Arguments"]
        I2["Config File<br/>~/.rules/config.yaml"]
        I3["Batch File<br/>CSV/JSON/YAML"]
        I4["Environment Variables<br/>RULES_*"]
        I5["Interactive Shell<br/>User Input"]
    end

    subgraph "Parse Layer"
        P1["argparse/click<br/>parse_args()"]
        P2["yaml.safe_load()"]
        P3["csv.DictReader()"]
        P4["os.environ.get()"]
        P5["prompt_toolkit<br/>session.prompt()"]
    end

    subgraph "Transform Layer"
        T1["merge_configs()"]
        T2["normalize_context()"]
        T3["resolve_profile()"]
        T4["validate_format()"]
    end

    subgraph "Execute Layer"
        E1["CommandHandler.handle()"]
        E2["BatchProcessor.process()"]
        E3["InteractiveShell.execute()"]
    end

    subgraph "Serialize Layer"
        S1["OutputFormatter.format_json()"]
        S2["OutputFormatter.format_yaml()"]
        S3["OutputFormatter.format_table()"]
        S4["OutputFormatter.format_csv()"]
    end

    subgraph "Output Sinks"
        O1["stdout"]
        O2["File<br/>batch results"]
        O3["stderr<br/>errors/warnings"]
    end

    I1 --> P1
    I2 --> P2
    I3 --> P3
    I4 --> P4
    I5 --> P5

    P1 --> T1
    P2 --> T1
    P3 --> T2
    P4 --> T1
    P5 --> T4

    T1 --> T3
    T3 --> E1
    T2 --> E2
    T4 --> E3

    E1 --> S1
    E1 --> S2
    E1 --> S3
    E2 --> S4
    E3 --> S1

    S1 --> O1
    S2 --> O1
    S3 --> O1
    S4 --> O2
    S1 --> O3
    S2 --> O3
    S3 --> O3

    style I1 fill:#2196F3,color:#fff
    style I2 fill:#4CAF50,color:#fff
    style I3 fill:#FF9800,color:#fff
    style O1 fill:#1565C0,color:#fff
    style O2 fill:#1565C0,color:#fff
```

## Error Handling Flow

```mermaid
flowchart TD
    Start(["Error Occurred"]) --> Classify{"Error Category?"}

    Classify -->|User Error| UserErr["Bad Input / Missing Args"]
    Classify -->|Auth Error| AuthErr["Auth Failed<br/>401 / 403"]
    Classify -->|API Error| APIErr["Server Error<br/>500 / 502 / 503"]
    Classify -->|Network Error| NetErr["Connection Failed<br/>DNS / Timeout"]
    Classify -->|Config Error| CfgErr["Config Corrupt<br/>Parse Failure"]
    Classify -->|Runtime Error| RunErr["Unexpected Exception"]

    UserErr --> ShowUsage["Show Usage Message"]
    ShowUsage --> ExitCode2["Exit Code 2"]

    AuthErr --> CheckConfig{"API Key<br/>Configured?"}
    CheckConfig -->|No| PromptLogin["Prompt: run 'config set api_key'"]
    CheckConfig -->|Yes| CheckExpired{"Key<br/>Expired?"}
    CheckExpired -->|Yes| SuggestRefresh["Suggest refreshing API key"]
    CheckExpired -->|No| SuggestPermissions["Check API key permissions"]
    PromptLogin --> ExitCode3["Exit Code 3"]
    SuggestRefresh --> ExitCode3
    SuggestPermissions --> ExitCode3

    APIErr --> Retry{"Retries<br/>Remaining?"}
    Retry -->|Yes| Backoff["Wait + Backoff"]
    Backoff --> RetryRequest["Retry Request"]
    RetryRequest --> Classify
    Retry -->|No| ShowServerError["Show Error Details"]
    ShowServerError --> ExitCode4["Exit Code 4"]

    NetErr --> Retry2{"Retries<br/>Remaining?"}
    Retry2 -->|Yes| Backoff2["Wait + Backoff"]
    Backoff2 --> RetryRequest2["Retry Request"]
    RetryRequest2 --> Classify
    Retry2 -->|No| CheckConnectivity{"Check Internet<br/>Connectivity?"}
    CheckConnectivity -->|Fail| ShowNetworkMsg["Network unreachable"]
    CheckConnectivity -->|Pass| ShowEndpointMsg["Endpoint unreachable<br/>check RULES_ENDPOINT"]
    ShowNetworkMsg --> ExitCode6["Exit Code 6"]
    ShowEndpointMsg --> ExitCode6

    CfgErr --> BackupExists{"Backup File<br/>Exists?"}
    BackupExists -->|Yes| RestoreBackup["Restore from backup"]
    BackupExists -->|No| ResetDefaults["Reset to defaults"]
    RestoreBackup --> ExitCode7["Exit Code 7"]
    ResetDefaults --> ExitCode7

    RunErr --> LogStack["Log Full Stack Trace"]
    LogStack --> ShowGeneric["Show Generic Error"]
    ShowGeneric --> ExitCode1["Exit Code 1"]

    style Start fill:#C62828,color:#fff
    style ShowUsage fill:#F57F17,color:#fff
    style ShowServerError fill:#C62828,color:#fff
    style ShowNetworkMsg fill:#C62828,color:#fff
    style ShowGeneric fill:#C62828,color:#fff
```