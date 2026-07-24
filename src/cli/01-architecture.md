# CLI Architecture

## Command Flow

All CLI commands follow a consistent path from user input to displayed output. The flowchart below shows the complete lifecycle of a command: parsing, dispatch, execution, and display.

```mermaid
flowchart TD
    Start(["User Invokes CLI"]) --> EntryPoint["Entry Point<br/>cli.py → main()"]

    EntryPoint --> ParseConfig["Load Config<br/>~/.rules/config.yaml"]
    ParseConfig --> SetupLogging["Setup Logging<br/>level from config"]
    SetupLogging --> ParseArgs["Parse Arguments<br/>argparse / click"]

    ParseArgs --> HasSubcommand{"Has Valid<br/>Subcommand?"}

    HasSubcommand -->|No| ShowHelp["Show Help Text<br/>+ Command List"]
    HasSubcommand -->|Yes| ValidateArgs["Validate Arguments"]
    ValidateArgs --> ArgsValid{"Arguments<br/>Valid?"}

    ArgsValid -->|No| ShowError["Show Error<br/>+ Usage Hint"]
    ArgsValid -->|Yes| ResolveProfile{"Active Profile<br/>Set?"}

    ResolveProfile -->|Yes| LoadProfile["Load Profile Config"]
    ResolveProfile -->|No| UseDefault["Use Default Config"]
    LoadProfile --> SetupAuth["Setup Auth<br/>from Config"]
    UseDefault --> SetupAuth

    SetupAuth --> SetupClient["Setup HTTP Client<br/>+ Retry Policy"]
    SetupClient --> Dispatch["Dispatch to<br/>Command Handler"]

    Dispatch --> HandlerType{"Handler Type?"}

    HandlerType -->|List| ListHandler["List Rules Handler"]
    HandlerType -->|Get| GetHandler["Get Rule Handler"]
    HandlerType -->|Create| CreateHandler["Create Rule Handler"]
    HandlerType -->|Update| UpdateHandler["Update Rule Handler"]
    HandlerType -->|Delete| DeleteHandler["Delete Rule Handler"]
    HandlerType -->|Evaluate| EvalHandler["Evaluate Rule Handler"]
    HandlerType -->|Batch| BatchHandler["Batch Handler"]
    HandlerType -->|Shell| ShellHandler["Launch Interactive Shell"]
    HandlerType -->|Config| ConfigHandler["Config Handler"]
    HandlerType -->|Metrics| MetricsHandler["Metrics Handler"]
    HandlerType -->|Health| HealthHandler["Health Handler"]

    ListHandler --> CallAPI["Call API<br/>GET /v1/rules"]
    GetHandler --> CallAPI2["Call API<br/>GET /v1/rules/:id"]
    CreateHandler --> CallAPI3["Call API<br/>POST /v1/rules"]
    UpdateHandler --> CallAPI4["Call API<br/>PUT /v1/rules/:id"]
    DeleteHandler --> CallAPI5["Call API<br/>DELETE /v1/rules/:id"]
    EvalHandler --> CallAPI6["Call API<br/>POST /v1/evaluate"]
    BatchHandler --> CallAPI7["Call API<br/>POST /v1/evaluate/batch"]

    CallAPI --> APIResponse{"API Returns<br/>Success?"}
    CallAPI2 --> APIResponse
    CallAPI3 --> APIResponse
    CallAPI4 --> APIResponse
    CallAPI5 --> APIResponse
    CallAPI6 --> APIResponse
    CallAPI7 --> APIResponse

    APIResponse -->|No| HandleError["Handle Error<br/>Map Status Code"]
    APIResponse -->|Yes| FormatOutput["Format Output"]

    HandleError --> ErrorType{"Error Type?"}
    ErrorType -->|401/403| AuthError["Auth Error<br/>→ Suggest re-auth"]
    ErrorType -->|404| NotFoundError["Not Found<br/>→ Show message"]
    ErrorType -->|422| ValidationError["Validation Error<br/>→ Show details"]
    ErrorType -->|429| RateLimitError["Rate Limited<br/>→ Show Retry-After"]
    ErrorType -->|500/503| ServerError["Server Error<br/>→ Show generic error"]
    ErrorType -->|Timeout| TimeoutError["Timeout<br/>→ Suggest retry"]
    ErrorType -->|Network| NetworkError["Network Error<br/>→ Check connection"]

    AuthError --> DisplayError["Display Error<br/>to stderr"]
    NotFoundError --> DisplayError
    ValidationError --> DisplayError
    RateLimitError --> DisplayError
    ServerError --> DisplayError
    TimeoutError --> DisplayError
    NetworkError --> DisplayError

    DisplayError --> SetExitCode["Set Exit Code<br/>non-zero"]
    SetExitCode --> Exit(["Exit"])

    FormatOutput --> SelectFormat{"Output Format<br/>from --format / config"}

    SelectFormat -->|table| BuildTable["Build Table<br/>via rich.Table"]
    SelectFormat -->|json| BuildJson["Serialize to JSON<br/>json.dumps(indent=2)"]
    SelectFormat -->|yaml| BuildYaml["Serialize to YAML<br/>yaml.dump"]
    SelectFormat -->|plain| BuildPlain["Build Key=Value<br/>lines"]
    SelectFormat -->|tree| BuildTree["Build Tree<br/>indented hierarchy"]
    SelectFormat -->|csv| BuildCSV["Build CSV<br/>with header row"]

    BuildTable --> ApplyColor["Apply Color<br/>if --color / config"]
    BuildJson --> ApplyColor
    BuildYaml --> ApplyColor
    BuildPlain --> ApplyColor
    BuildTree --> ApplyColor
    BuildCSV --> ApplyColor

    ApplyColor --> PrintOutput["Print to stdout"]
    PrintOutput --> SetExitCode0["Set Exit Code 0"]
    SetExitCode0 --> Exit

    ShowHelp --> ExitCode0["Exit Code 0"]
    ExitCode0 --> Exit
    ShowError --> ExitCode2["Exit Code 2"]
    ExitCode2 --> Exit

    style Start fill:#1565C0,color:#fff
    style Exit fill:#2E7D32,color:#fff
    style ShowHelp fill:#F57F17,color:#fff
    style DisplayError fill:#C62828,color:#fff
```

## Class Diagram

```mermaid
classDiagram
    class CLIApplication {
        -str name
        -str version
        -ArgumentParser parser
        -Dict~str, CommandHandler~ handlers
        -ConfigManager config
        -OutputFormatter formatter
        -APIClient api_client
        +__init__(name, version) void
        +run(argv) int
        +register_command(name, handler, aliases) void
        +get_help() str
        -build_parser() ArgumentParser
        -parse_arguments(argv) Namespace
        -dispatch(args) int
        -handle_unexpected_error(error) int
    }

    class CommandHandler {
        <<abstract>>
        +str name
        +List~str~ aliases
        +str description
        +handle(args, config, api, formatter) int
        +configure_parser(subparser) void
    }

    class ListCommand {
        +handle(args, config, api, formatter) int
        +configure_parser(subparser) void
        -build_filter(args) Dict
        -build_pagination(args) Dict
        -render_table(rules, formatter) str
    }

    class EvaluateCommand {
        +handle(args, config, api, formatter) int
        +configure_parser(subparser) void
        -validate_context(context) bool
        -render_result(result, format) str
        -calculate_score(data) float
    }

    class BatchCommand {
        +handle(args, config, api, formatter) int
        +configure_parser(subparser) void
        -read_input(path) List~Dict~
        -execute_batch(items) BatchResult
        -render_batch_result(result, format) str
        -handle_partial_failure(result) int
    }

    class InteractiveShell {
        -str prompt
        -bool multiline_mode
        -HistoryManager history
        -Completer completer
        -ExecutionContext context
        -Dict~str, str~ aliases
        +start() void
        +stop() void
        +execute(line) str
        +autocomplete(text, state) str
        +get_history() List~str~
        +clear_history() void
        +load_rc_file(path) void
        -build_completer() Completer
        -handle_multiline() str
        -process_input(line) void
    }

    class OutputFormatter {
        -bool pretty_print
        -bool color_enabled
        -int max_width
        -JSONEncoder json_encoder
        -TableBuilder table_builder
        -Colorizer colorizer
        +format(data, format_type) str
        +format_json(data) str
        +format_yaml(data) str
        +format_table(data, columns) str
        +format_plain(data) str
        +format_tree(data, key) str
        +format_csv(data) str
        +set_pretty_print(enabled) void
        +set_color(enabled) void
        +set_max_width(width) void
        -detect_color_support() bool
        -truncate(text, max_len) str
    }

    class ConfigManager {
        -ConfigStore store
        -ProfileManager profiles
        -ConfigValidator validator
        -str active_profile
        +load(path) Config
        +save(config, path) void
        +get(key, default) object
        +set(key, value) void
        +unset(key) void
        +list_profiles() List~str~
        +switch_profile(name) void
        +create_profile(name, config) void
        +delete_profile(name) void
        +validate(config) ValidationResult
        +export(path) void
        +import(path) void
        +get_all() Dict
        +reset_to_defaults() void
    }

    class APIClient {
        -str base_url
        -str api_key
        -int timeout
        -bool verify_ssl
        -Session session
        -RetryPolicy retry_policy
        +get(path, params) Response
        +post(path, json) Response
        +put(path, json) Response
        +delete(path) Response
        +health_check() HealthStatus
        +set_auth(token) void
        +close() void
        -build_headers() Dict
        -handle_response(response) Dict
        -should_retry(exception, attempt) bool
    }

    CLIApplication --> CommandHandler : dispatches to
    CLIApplication --> OutputFormatter : formats with
    CLIApplication --> ConfigManager : reads config from
    CLIApplication --> APIClient : calls API via
    CommandHandler <|-- ListCommand
    CommandHandler <|-- EvaluateCommand
    CommandHandler <|-- BatchCommand
    CommandHandler --> OutputFormatter : uses
    CommandHandler --> APIClient : uses
    CommandHandler --> ConfigManager : reads
    CLIApplication --> InteractiveShell : launches
```

## Interactive Shell State Machine

```mermaid
stateDiagram-v2
    [*] --> Idle : start shell
    Idle --> ReadingInput : user types text
    ReadingInput --> CheckingPrefix : enter pressed
    CheckingPrefix --> MultilineMode : line ends with \
    CheckingPrefix --> SingleLineMode : line does not end with \
    MultilineMode --> ReadingInput : continue reading
    SingleLineMode --> ParsingCommand : parse line
    ParsingCommand --> Validating : command recognized
    ParsingCommand --> ShowHelp : "help" or "?"
    ParsingCommand --> UnknownCommand : command not recognized
    UnknownCommand --> Idle : show error, return to prompt
    Validating --> Executing : arguments valid
    Validating --> ValidationError : arguments invalid
    ValidationError --> Idle : show error, return to prompt
    Executing --> Formatting : execution complete
    Executing --> ExecutionError : execution failed
    ExecutionError --> Idle : show error, return to prompt
    Formatting --> Displaying : format prepared
    Displaying --> Idle : output displayed
    ShowHelp --> Idle : help text displayed

    Idle --> Completion : tab pressed
    Completion --> Idle : cycle suggestions
    Idle --> HistorySearch : up/down arrows
    HistorySearch --> Idle : select from history

    Idle --> Exiting : "exit", "quit", or Ctrl+D
    Exiting --> [*] : clean shutdown

    note right of Idle : Prompt: "rules> "
    note right of MultilineMode : Prompt becomes "... "
    note right of Completion : Autocomplete commands,<br/>rule IDs, file paths
```

## Plugin Architecture

```mermaid
graph TB
    subgraph "Core CLI"
        MAIN["CLIApplication"]
        PARSER["ArgumentParser"]
        DISPATCH["Dispatcher"]
    end

    subgraph "Plugin System"
        REG["PluginRegistry"]
        LOADER["PluginLoader"]
        HOOKS["HookManager"]
    end

    subgraph "Built-in Commands"
        C1["ListCommand"]
        C2["EvalCommand"]
        C3["BatchCommand"]
        C4["ConfigCommand"]
        C5["ShellCommand"]
    end

    subgraph "Third-party Plugins"
        P1["ExportPlugin"]
        P2["NotifyPlugin"]
        P3["AuditPlugin"]
    end

    MAIN --> DISPATCH
    DISPATCH --> REG
    REG --> C1
    REG --> C2
    REG --> C3
    REG --> C4
    REG --> C5
    REG --> LOADER
    LOADER --> P1
    LOADER --> P2
    LOADER --> P3
    HOOKS --> C1
    HOOKS --> C2
    HOOKS --> P1
    HOOKS --> P2

    style MAIN fill:#1565C0,color:#fff
    style C1 fill:#1976D2,color:#fff
    style C2 fill:#1976D2,color:#fff
    style P1 fill:#7B1FA2,color:#fff
    style P2 fill:#7B1FA2,color:#fff
```

## Directory Structure

```
src/cli/
├── __init__.py
├── cli.py                  # CLIApplication entry point
├── output_formatter.py     # OutputFormatter class
├── interactive_shell.py    # InteractiveShell class
├── config_commands.py      # ConfigCommands class
├── batch_processor.py      # BatchProcessor class
├── commands/
│   ├── __init__.py
│   ├── base.py             # CommandHandler base class
│   ├── list.py
│   ├── get.py
│   ├── create.py
│   ├── update.py
│   ├── delete.py
│   ├── evaluate.py
│   ├── batch.py
│   ├── config.py
│   └── shell.py
├── utils/
│   ├── __init__.py
│   ├── api_client.py       # APIClient HTTP wrapper
│   ├── config_manager.py   # ConfigManager
│   ├── colorizer.py        # Terminal color support
│   └── table_builder.py    # ASCII table construction
└── plugins/
    └── __init__.py          # Plugin discovery hooks
```

## Configuration Schema

```yaml
# ~/.rules/config.yaml
version: "2.0"
profiles:
  default:
    api_endpoint: "http://localhost:8000/v1"
    api_key: ""
    output_format: "table"
    color: true
    timeout: 30
    verify_ssl: true
  production:
    api_endpoint: "https://api.example.com/v1"
    output_format: "json"
    color: false
    timeout: 10
    verify_ssl: true
active_profile: "default"
history_size: 1000
batch:
  concurrency: 5
  continue_on_error: false
  progress_bar: true
```