# CLI Logic & Decision Making

## Command Processing Flowchart

Every CLI command passes through a decision pipeline: validation, permission checking, execution, and output format selection. The flowchart below captures branching logic at each stage.

```mermaid
flowchart TD
    Start(["Command Received"]) --> ValidateCmd["Validate Command<br/>Name, Args, Flags"]

    ValidateCmd --> CmdValid{"Command<br/>Valid?"}

    CmdValid -->|No| SuggestCommand{"Similar<br/>Command Found?"}
    SuggestCommand -->|Yes| ShowDidYouMean["Did you mean:<br/>&lt;similar&gt;?"]
    SuggestCommand -->|No| ShowUsage["Show Usage<br/>+ Available Commands"]
    ShowDidYouMean --> Exit2["Exit Code 2"]
    ShowUsage --> Exit2

    CmdValid -->|Yes| CheckArgs{"Required Args<br/>Present?"}

    CheckArgs -->|No| ShowMissingArgs["Missing: &lt;arg names&gt;"]
    ShowMissingArgs --> Exit2

    CheckArgs -->|Yes| ParseContext{"Context<br/>Provided?"}

    ParseContext -->|Yes| ValidateJSON{"Valid<br/>JSON?"}
    ValidateJSON -->|No| ShowJSONError["Invalid JSON<br/>+ Parse Error"]
    ShowJSONError --> Exit2
    ValidateJSON -->|Yes| CheckOutputFormat{"Output Format<br/>Specified?"}

    ParseContext -->|No| CheckOutputFormat

    CheckOutputFormat -->|Yes| FormatSupported{"Format<br/>Supported?"}
    FormatSupported -->|No| ShowFormats["Supported:<br/>json, yaml, table, ..."]
    ShowFormats --> Exit2
    FormatSupported -->|Yes| CheckConnection{"Config Has<br/>API Endpoint?"}

    CheckOutputFormat -->|No| UseDefault["Use Config Default Format"]
    UseDefault --> CheckConnection

    CheckConnection -->|No| ShowSetupPrompt["Not configured.<br/>Run: config set endpoint"]
    ShowSetupPrompt --> Exit3

    CheckConnection -->|Yes| CheckAuth{"Has API Key<br/>or Token?"}

    CheckAuth -->|No| ShowAuthPrompt["No auth configured.<br/>Run: config set api_key"]
    ShowAuthPrompt --> Exit3

    CheckAuth -->|Yes| BuildRequest["Build HTTP Request"]

    BuildRequest --> AddHeaders["Add Headers<br/>Authorization, Content-Type, Accept"]
    AddHeaders --> SendRequest["Send Request to API"]

    SendRequest --> ResponseCode{"Response<br/>Code?"}

    ResponseCode -->|200 OK| ParseResponse["Parse Response Body"]

    ResponseCode -->|401/403| TokenExpired{"Token<br/>Expired?"}
    TokenExpired -->|Yes| SuggestRefresh["Refresh token<br/>or re-authenticate"]
    TokenExpired -->|No| ShowForbidden["Insufficient permissions"]
    SuggestRefresh --> Exit3
    ShowForbidden --> Exit3

    ResponseCode -->|404| ShowNotFound["Resource not found"]
    ShowNotFound --> Exit4

    ResponseCode -->|422| ShowValidation["Validation error<br/>+ Field details"]
    ShowValidation --> Exit4

    ResponseCode -->|429| ShowRateLimit["Rate limited<br/>Retry-After: Xs"]
    ShowRateLimit --> Exit4

    ResponseCode -->|500| ShowServerError["Server error"]
    ShowServerError --> Exit4

    ResponseCode -->|Timeout| ShowTimeout["Request timed out"]
    ShowTimeout --> Exit6

    ParseResponse --> SelectFormat{"Format = ?"}

    SelectFormat -->|json| BuildJSON["json.dumps(data, indent=2)"]
    SelectFormat -->|yaml| BuildYAML["yaml.dump(data, default_flow_style=False)"]
    SelectFormat -->|table| BuildTable["Build ASCII Table<br/>rich.Table / tabulate"]
    SelectFormat -->|plain| BuildPlain["key=value lines"]
    SelectFormat -->|tree| BuildTree["Build nested tree<br/>with indentation"]
    SelectFormat -->|csv| BuildCSV["Add header + rows"]

    BuildJSON --> Colorize{"Color<br/>Enabled?"}
    BuildYAML --> Colorize
    BuildTable --> Colorize
    BuildPlain --> Colorize
    BuildTree --> Colorize
    BuildCSV --> Colorize

    Colorize -->|Yes| ApplySyntaxHighlight["Apply Pygments<br/>syntax highlighting"]
    Colorize -->|No| PrintPlain["Print raw output"]

    ApplySyntaxHighlight --> PrintStdout["Print to stdout"]
    PrintPlain --> PrintStdout

    PrintStdout --> Exit0(["Exit Code 0"])

    style Start fill:#1565C0,color:#fff
    style Exit0 fill:#2E7D32,color:#fff
    style Exit2 fill:#E65100,color:#fff
    style Exit3 fill:#C62828,color:#fff
    style Exit4 fill:#C62828,color:#fff
    style Exit6 fill:#C62828,color:#fff
```

## Interactive Shell Error Handling Decision Tree

The interactive shell uses a multi-layered error handling strategy. The decision tree below determines whether the shell should retry, recover, degrade, or terminate based on the error type and severity.

```mermaid
flowchart TD
    Start(["Error in Interactive Shell"]) --> Classify{"Error Type?"}

    Classify -->|Syntax| SyntaxErr["Command Syntax Error"]
    Classify -->|Runtime| RuntimeErr["Execution Error"]
    Classify -->|Connection| ConnErr["API Connection Error"]
    Classify -->|Internal| InternalErr["Internal Shell Error"]
    Classify -->|Signal| SigErr["OS Signal<br/>SIGINT / SIGTERM"]

    SyntaxErr --> ShowSyntaxHelp["Show Syntax:<br/>usage hint"]
    ShowSyntaxHelp --> PrintErrLine["Print Error Line"]
    PrintErrLine --> ReturnToPrompt["Return to Prompt"]

    RuntimeErr --> ClassifyRuntime{"Error Type?"}

    ClassifyRuntime -->|Validation| RuntimeValidation["Validation Failed"]
    ClassifyRuntime -->|API Error| RuntimeAPI["API Returned Error"]
    ClassifyRuntime -->|Timeout| RuntimeTimeout["Request Timed Out"]
    ClassifyRuntime -->|Auth| RuntimeAuth["Auth Expired"]

    RuntimeValidation --> ShowFieldErrors["Show Field-level Errors"]
    ShowFieldErrors --> ReturnToPrompt

    RuntimeAPI --> ShowAPIError["Show API Error Details"]
    ShowAPIError --> ReturnToPrompt

    RuntimeTimeout --> SuggestRetry["Suggest retry command"]
    SuggestRetry --> ReturnToPrompt

    RuntimeAuth --> AttemptRefresh{"Attempt Token<br/>Refresh?"}
    AttemptRefresh -->|Yes| RefreshToken["Call /auth/refresh"]
    RefreshToken --> RefreshOk{"Refresh<br/>OK?"}
    RefreshOk -->|Yes| ReExecute["Re-execute command"]
    ReExecute --> ReturnToPrompt
    RefreshOk -->|No| ShowNeedReauth["Session expired.<br/>Please re-authenticate"]
    ShowNeedReauth --> ReturnToPrompt
    AttemptRefresh -->|No| ShowNeedReauth

    ConnErr --> RetryCount{"Retry Count<br/>< 3?"}

    RetryCount -->|Yes| Backoff["Backoff: 2^retry seconds"]
    Backoff --> TryReconnect["Try Reconnect"]
    TryReconnect --> ReconnectOk{"Reconnect<br/>OK?"}
    ReconnectOk -->|Yes| ReExecute
    ReconnectOk -->|No| IncrementRetry["Increment Retry Count"]
    IncrementRetry --> RetryCount

    RetryCount -->|No| SwitchMode{"Switch to<br/>Offline Mode?"}
    SwitchMode -->|Yes| OfflineMode["Enable Offline Mode<br/>Limited command set"]
    SwitchMode -->|No| SuggestExit["Connection failed.<br/>Type 'exit' to quit"]
    OfflineMode --> ReturnToPrompt
    SuggestExit --> ReturnToPrompt

    InternalErr --> LogInternal["Log Error Details<br/>to debug file"]
    LogInternal --> Recover{"Can Recover<br/>State?"}
    Recover -->|Yes| RestoreState["Restore Last Known<br/>Good State"]
    Recover -->|No| ShowFatal["Fatal error.<br/>Restarting shell..."]
    RestoreState --> ReturnToPrompt
    ShowFatal --> Restart["Restart Shell Session"]

    SigErr --> CaptureSignal["Capture Signal"]
    CaptureSignal --> Cleanup["Cleanup Resources<br/>History, Temp Files"]
    Cleanup --> ConfirmExit{"Confirm<br/>Exit?"}
    ConfirmExit -->|Yes| ExitGracefully["Print goodbye message"]
    ConfirmExit -->|No| ReturnToPrompt
    ExitGracefully --> Exit(["Exit Shell"])

    style Start fill:#C62828,color:#fff
    style ReturnToPrompt fill:#F57F17,color:#fff
    style Exit fill:#1565C0,color:#fff
    style ExitGracefully fill:#1565C0,color:#fff
    style OfflineMode fill:#757575,color:#fff
    style Restart fill:#E65100,color:#fff
```

## Batch Processing Strategy Selection

The batch processor selects an execution strategy based on input size, concurrency setting, error tolerance, and available system resources.

```mermaid
flowchart TD
    Start(["Batch Start"]) --> ReadInput["Read Input File"]

    ReadInput --> CountItems["Count Items"]
    CountItems --> ItemsCheck{"Items<br/>Count?"}

    ItemsCheck -->|0| ErrEmpty["Error: Empty Input"]
    ItemsCheck -->|1..10| Sequential["Sequential Mode<br/>Process one by one"]
    ItemsCheck -->|11..1000| Threaded["Threaded Mode<br/>ThreadPoolExecutor"]
    ItemsCheck -->|1001+| Async["Async Mode<br/>aiohttp + asyncio"]

    Sequential --> ProgressBar{"Show Progress<br/>Bar?"}
    Threaded --> SetConcurrency{"Concurrency<br/>Specified?"}
    Async --> SetConcurrencyA{"Concurrency<br/>Specified?"}

    SetConcurrency -->|Yes| UseSpecifiedConc["Use Specified<br/>Concurrency Level"]
    SetConcurrency -->|No| DetectCPU{"Detect CPU<br/>Cores?"}
    UseSpecifiedConc --> BatchEndpoint{"Use Batch<br/>API Endpoint?"}
    DetectCPU --> UseCPUCount["Set concurrency =<br/>cpu_count * 2"]
    UseCPUCount --> BatchEndpoint

    SetConcurrencyA -->|Yes| UseSpecifiedAsync["Use Specified<br/>Concurrency"]
    SetConcurrencyA -->|No| UseHighAsync["Set concurrency = 50<br/>(default for async)"]
    UseSpecifiedAsync --> ProcessAsync["Process Asynchronously<br/>aiohttp session"]
    UseHighAsync --> ProcessAsync

    BatchEndpoint -->|Yes| ChunkBatch{"Chunk Size<br/>> 20?"}
    ChunkBatch -->|Yes| CreateChunks["Create chunks of 20"]
    ChunkBatch -->|No| SendDirect["Send all at once"]
    CreateChunks --> SendChunks["Send chunks in parallel"]
    SendDirect --> ProcessResponses["Process Response"]
    SendChunks --> ProcessResponses

    BatchEndpoint -->|No| ProcessIndividual["Process each item<br/>individually"]

    ProcessIndividual --> HandleErrors{"Continue on<br/>Error?"}
    ProcessResponses --> HandleErrors

    HandleErrors -->|Yes| SkipErrors["Skip failed items<br/>Track in failure list"]
    HandleErrors -->|No| StopOnFirst["Stop on first error"]

    SkipErrors --> UpdateProgress["Update Progress"]
    StopOnFirst --> UpdateProgress

    UpdateProgress --> AllDone{"All Items<br/>Processed?"}

    AllDone -->|No| ProcessNextItem["Process Next Item"] --> HandleErrors
    AllDone -->|Yes| AggregateResults["Aggregate Results"]

    AggregateResults --> BuildSummary["Build Summary<br/>Total, Succeeded, Failed, Time"]
    BuildSummary --> FailureCheck{"Failures > 0"}

    FailureCheck -->|Yes| PartialFailExit["Exit Code 5<br/>Partial Failure"]
    FailureCheck -->|No| SuccessExit["Exit Code 0<br/>Success"]

    ProgressBar -->|Yes| InitProgressBar["Initialize tqdm<br/>Progress Bar"]
    InitProgressBar --> ProcessIndividual
    ProgressBar -->|No| ProcessIndividual

    style Start fill:#1565C0,color:#fff
    style Sequential fill:#1976D2,color:#fff
    style Threaded fill:#F57C00,color:#fff
    style Async fill:#7B1FA2,color:#fff
    style SuccessExit fill:#2E7D32,color:#fff
    style PartialFailExit fill:#E65100,color:#fff
    style ErrEmpty fill:#C62828,color:#fff
```

## Output Format Selection Logic

```mermaid
flowchart TD
    Start(["Format Selection"]) --> ArgFormat{"--format<br/>Specified?"}

    ArgFormat -->|Yes| CheckSupported{"Supported<br/>Format?"}
    CheckSupported -->|Yes| UseArg["Use Specified Format"]
    CheckSupported -->|No| ShowSupportedFormats["Supported: json, yaml, table, plain, tree, csv"]
    ShowSupportedFormats --> UseDefaultFmt["Fall back to default<br/>(table)"]

    ArgFormat -->|No| ConfigFormat{"Config Default<br/>Format Set?"}
    ConfigFormat -->|Yes| UseConfig["Use Config Default"]
    ConfigFormat -->|No| AutoDetect{"Auto-detect<br/>Output Context?"}

    AutoDetect -->|Piped<br/>stdout| DetectPiped["Detect piped output"]
    AutoDetect -->|Terminal| DetectTerminal["Detect interactive terminal"]
    AutoDetect -->|Redirected<br/>to File| DetectFile["Detect file redirect"]

    DetectPiped --> UseJSON["Use JSON<br/>machine-readable"]
    DetectTerminal --> UseTable["Use Table<br/>human-readable"]
    DetectFile --> UseJSON

    UseArg --> ApplySettings["Apply color, width,<br/>pretty-print settings"]
    UseDefaultFmt --> ApplySettings
    UseConfig --> ApplySettings
    UseJSON --> ApplySettings
    UseTable --> ApplySettings

    ApplySettings --> CheckColor{"--color /<br/>config.color?"}
    CheckColor -->|Enabled| IsTTY{"stdout<br/>is TTY?"}
    IsTTY -->|Yes| EnableColor["Enable ANSI colors"]
    IsTTY -->|No| DisableColor["Disable colors<br/>(piped output)"]
    CheckColor -->|Disabled| DisableColor

    EnableColor --> Render["Render Output"]
    DisableColor --> Render

    Render --> Print["Print to stdout"]

    style Start fill:#1565C0,color:#fff
    style Render fill:#2E7D32,color:#fff
    style UseJSON fill:#F57F17,color:#fff
    style UseTable fill:#F57F17,color:#fff
```

## Retry and Backoff Strategy

The CLI uses an exponential backoff strategy with jitter for retryable errors:

```python
RETRY_CONFIG = {
    "max_retries": 3,
    "base_delay_ms": 500,
    "max_delay_ms": 10000,
    "jitter": True,
    "retryable_statuses": [429, 500, 502, 503, 504],
    "retryable_exceptions": [
        "ConnectionError",
        "TimeoutError",
        "SSLError",
        "ChunkedEncodingError"
    ]
}
```

| Attempt | Base Delay | With Jitter | Trigger |
|---|---|---|---|
| 1 | 500ms | 375-625ms | First retryable failure |
| 2 | 1000ms | 750-1250ms | Second consecutive failure |
| 3 | 2000ms | 1500-2500ms | Third consecutive failure |
| 4+ | 4000ms | 3000-5000ms | Subsequent (capped at 10s) |

After exhausting retries, the CLI enters degraded mode where further commands are attempted once without retry (fail-fast). The user is notified that the API appears unavailable.

## Cache Invalidation Rules

The CLI caches rule list data for 30 seconds. Cache is invalidated when:
- A `create`, `update`, or `delete` command succeeds
- The `--no-cache` flag is passed
- The config file timestamp changes (detected via mtime)
- The `RULES_CACHE_BUST` env var is set to a new value