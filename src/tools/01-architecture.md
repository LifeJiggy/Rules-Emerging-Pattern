# Tools Module — Architecture

## Component Architecture

The Tools module consists of five independent tools, each with its own configuration and output types. They are connected through shared data formats and can be composed in pipelines.

```mermaid
flowchart TB
    subgraph Tools
        RA[RuleAnalyzer]
        DT[DebugTool]
        PR[Profiler]
        TR[TestRunner]
        VZ[Visualizer]
    end

    subgraph Config
        RA_C[AnalysisLevel]
        DT_C[DebugLevel]
        PR_C[ProfilingDepth]
        TR_C[CoverageMetric]
        VZ_C[VisualizationFormat]
    end

    subgraph Output
        RA_O[AnalysisReport\nIssue lists]
        DT_O[TraceBuffer\nSnapshots]
        PR_O[ProfileResult\nCallGraph]
        TR_O[TestReport\nCoverageReport]
        VZ_O[Mermaid/JSON/HTML\nGraph string]
    end

    RA --> RA_C
    DT --> DT_C
    PR --> PR_C
    TR --> TR_C
    VZ --> VZ_C

    RA --> RA_O
    DT --> DT_O
    PR --> PR_O
    TR --> TR_O
    VZ --> VZ_O
```

## RuleAnalyzer Architecture

```mermaid
classDiagram
    class RuleAnalyzer {
        -AnalysisLevel level
        -int max_iterations
        -int max_depth
        -Dict findings
        +analyze(rule) AnalysisReport
        +analyze_all(rules) AnalysisReport
        +find_dead_code(rule) List
        +find_unreachable(rule) List
        +find_infinite_loops(rule) List
        +find_redundancy(rule) List
        +find_unused_vars(rule) List
        +measure_complexity(rule) int
        +check_data_flow(rule) List
        +check_type_safety(rule) List
        +check_security(rule) List
        +check_performance(rule) List
    }

    class AnalysisReport {
        +str rule_name
        +AnalysisLevel level
        +int complexity_score
        +List findings
        +Dict metrics
        +float analysis_time
        +to_dict() Dict
        +summary() str
    }

    class IssueFinding {
        +IssueSeverity severity
        +IssueCategory category
        +str message
        +int line
        +int column
        +str code_snippet
        +str suggestion
        +to_dict() Dict
    }

    RuleAnalyzer --> AnalysisReport
    AnalysisReport --> IssueFinding
```

### Analysis Pipeline

```mermaid
flowchart TB
    RULE[Rule Definition] --> ANALYZE[analyze()]

    ANALYZE --> LEVEL{Analysis Level}

    LEVEL -->|BASIC| BASIC_CHECKS
    LEVEL -->|STANDARD| STD_CHECKS
    LEVEL -->|ADVANCED| ADV_CHECKS
    LEVEL -->|COMPREHENSIVE| ALL_CHECKS

    subgraph BASIC_CHECKS
        DC[find_dead_code]
        UR[find_unreachable]
        UV[find_unused_vars]
    end

    subgraph STD_CHECKS
        IL[find_infinite_loops]
        RD[find_redundancy]
        CX[measure_complexity]
    end

    subgraph ADV_CHECKS
        DF[check_data_flow]
        TS[check_type_safety]
    end

    subgraph ALL_CHECKS
        SC[check_security]
        PF[check_performance]
    end

    BASIC_CHECKS --> AGG
    STD_CHECKS --> AGG
    ADV_CHECKS --> AGG
    ALL_CHECKS --> AGG[aggregate findings]
    AGG --> REPORT[AnalysisReport]
```

## DebugTool Architecture

```mermaid
classDiagram
    class DebugTool {
        -DebugLevel level
        -List~TraceEvent~ trace_buffer
        -Dict breakpoints
        -List watchers
        -Dict snapshots
        +trace_event(event_type, context)
        +set_breakpoint(skill, line)
        +clear_breakpoint(skill, line)
        +step_over() Dict
        +step_into() Dict
        +step_out() Dict
        +continue() Dict
        +inspect_variable(name) Any
        +set_watch(expression)
        +remove_watch(expression)
        +watch(expression, context) Any
        +snapshot(context) Dict
        +compare_snapshots(snap_a, snap_b) Dict
    }

    class TraceEvent {
        +TraceEventType event_type
        +str skill_name
        +str function
        +int line
        +Dict context
        +float timestamp
        +to_dict() Dict
    }

    class Breakpoint {
        +str skill
        +int line
        +str condition
        +int hit_count
        +bool enabled
        +should_break(context) bool
    }

    DebugTool --> TraceEvent
    DebugTool --> Breakpoint
```

### Debug Architecture

```mermaid
flowchart TB
    EXEC[Rule Execution] --> DT[DebugTool]
    DT --> TRACE[trace_event]
    DT --> BP{Breakpoint Hit?}
    BP -->|no| CONTINUE[Continue Execution]
    BP -->|yes| PAUSE[Pause Execution]

    PAUSE --> CM{Command}
    CM -->|step_over| STEP_OVER[Execute next line,\nskip functions]
    CM -->|step_into| STEP_INTO[Enter function call]
    CM -->|step_out| STEP_OUT[Complete current function]
    CM -->|continue| RESUME[Resume until next breakpoint]
    CM -->|inspect| INSPECT[Show variable value]
    CM -->|watch| WATCH[Evaluate expression]

    INSPECT --> MORE{More commands?}
    WATCH --> MORE
    STEP_OVER --> MORE
    STEP_INTO --> MORE
    STEP_OUT --> MORE
    RESUME --> BP
    MORE -->|yes| PAUSE
    MORE -->|no| DONE[Resume execution]
```

### Trace Buffer Architecture

```mermaid
flowchart LR
    EVENTS[Trace Events] --> BUFFER[Circular Trace Buffer]
    BUFFER --> CAPACITY[max_trace_buffer entries]
    BUFFER --> OLDEST[Oldest entry\noverwritten on full]

    BUFFER --> EXPORT[Export to Visualizer]
    BUFFER --> REPLAY[Replay execution]
    BUFFER --> ANALYZE[Analyze execution pattern]
```

## Profiler Architecture

```mermaid
classDiagram
    class Profiler {
        -ProfilerConfig config
        -Dict profile_data
        -int call_depth
        -List stack
        +start(name)
        +stop(name)
        +reset()
        +profile_function(fn, args) ProfileResult
        +profile_line(module, line) ProfileResult
        +profile_call_graph(entry) CallGraph
        +report(format) str
        +merge(other) Profiler
        +filter(target) Profiler
        +top_calls(n) List
        +slowest_paths(n) List
    }

    class ProfilerConfig {
        +ProfilingTarget target
        +ProfilingDepth depth
        +ReportFormat report_format
        +str timing
        +int max_depth
        +bool track_children
    }

    class ProfileResult {
        +str name
        +float start_time
        +float end_time
        +float elapsed
        +List children
        +int call_count
        +float total_time
        +float min_time
        +float max_time
        +to_dict() Dict
    }

    class CallGraph {
        +str entry_point
        +Dict nodes
        +List edges
        +float total_time
        +float overhead
    }

    Profiler --> ProfilerConfig
    Profiler --> ProfileResult
    Profiler --> CallGraph
```

### Profiling Pipeline

```mermaid
flowchart TB
    START[start(name)] --> RECORD[Record start_time + stack push]
    RECORD --> EXEC[Execute code section]
    EXEC --> STOP[stop(name)]
    STOP --> COMPUTE[elapsed = end - start]
    COMPUTE --> AGG[Update: call_count, total_time, min/max]
    AGG --> PUSH[Append to profile_data[name]]
    PUSH --> PARENT{Has parent?}
    PARENT -->|yes| CHILD_ADD[Add to parent.children]
    PARENT -->|no| TOP[Top-level measurement]
    CHILD_ADD --> DONE
    TOP --> DONE

    subgraph Profile Data Structure
        D1["profile_data = { 'func_a': [ProfileResult, ...], 'func_b': [ProfileResult, ...] }"]
    end
```

### Call Graph Construction

```mermaid
sequenceDiagram
    participant Client
    participant P as Profiler

    Client->>P: start("main")
    Client->>P: start("parse")
    Client->>P: stop("parse")
    Client->>P: start("transform")
    Client->>P: start("validate")
    Client->>P: stop("validate")
    Client->>P: stop("transform")
    Client->>P: stop("main")

    P->>P: profile_call_graph("main")
    P->>P: build nodes from stack trace
    P->>P: compute edges from parent/child
    P-->>Client: CallGraph

    Note over P: Result graph:\nmain → parse\nmain → transform → validate
```

## TestRunner Architecture

```mermaid
classDiagram
    class TestRunner {
        -int total_tests
        -int passed
        -int failed
        -int skipped
        -TestStatus status
        -Dict results
        -float coverage_target
        +run(test_suite) TestReport
        +run_all(suites) TestReport
        +run_property_based(property_fn, generator) TestResult
        +run_snapshot(rule, input_data) TestResult
        +run_fuzz(rule, fuzzer) TestResult
        +run_comparison(rule_a, rule_b, method) TestResult
        +run_threshold(rule, threshold_fn) TestResult
        +run_regression(rule, inputs, expected) TestResult
        +run_golden(rule, golden_path) TestResult
        +coverage(rules) CoverageReport
    }

    class TestReport {
        +int total
        +int passed
        +int failed
        +int skipped
        +float duration
        +Dict results
        +float pass_rate
        +str summary()
    }

    class TestResult {
        +str test_name
        +TestStatus status
        +Dict input
        +Any expected
        +Any actual
        +float duration
        +Optional~str~ error
        +to_dict() Dict
    }

    class CoverageReport {
        +float line_coverage
        +float branch_coverage
        +float path_coverage
        +float condition_coverage
        +float function_coverage
        +Dict details
        +str summary()
    }

    TestRunner --> TestReport
    TestRunner --> TestResult
    TestRunner --> CoverageReport
```

### Test Execution Pipeline

```mermaid
flowchart TB
    SUITE[Test Suite] --> DISPATCH{Dispatch by type}

    DISPATCH -->|property| PROP[Generate random inputs\nfrom generator]
    DISPATCH -->|snapshot| SNAP[Serialize rule output\ncompare to stored]
    DISPATCH -->|fuzz| FUZZ[Feed random/mutated\ninputs]
    DISPATCH -->|comparison| COMP[Execute both rules\ncompare by method]
    DISPATCH -->|threshold| THRESH[Execute rule\nassert predicate]
    DISPATCH -->|regression| REGR[Execute with known inputs\nassert expected]
    DISPATCH -->|golden| GOLD[Execute rule\ncompare to golden file]

    PROP --> RESULT[TestResult]
    SNAP --> RESULT
    FUZZ --> RESULT
    COMP --> RESULT
    THRESH --> RESULT
    REGR --> RESULT
    GOLD --> RESULT

    RESULT --> AGG[TestReport aggregation]
    AGG --> PASS{pand pass_rate?}
    PASS -->|>= threshold| SUCCESS[PASS]
    PASS -->|< threshold| FAILURE[FAIL]
```

## Visualizer Architecture

```mermaid
classDiagram
    class Visualizer {
        -VisualizationConfig config
        -Dict themes
        -Dict custom_nodes
        -Dict custom_edges
        +visualize_execution(execution_log) str
        +visualize_dependency(registry) str
        +visualize_tree(execution_tree) str
        +visualize_data_flow(data_flow) str
        +visualize_rule(rule) str
        +visualize_comparison(rules) str
        +visualize_timeline(events) str
        +set_theme(theme)
        +customize_node(node_id, style)
        +customize_edge(from_id, to_id, style)
    }

    class VisualizationConfig {
        +VisualizationFormat format
        +GraphOrientation orientation
        +str theme
        +int max_nodes
        +int max_edges
        +bool show_labels
        +bool show_timestamps
        +str font_size
        +bool highlight_critical_path
    }

    class NodeStyle {
        +NodeShape shape
        +str color
        +str border_color
        +int border_width
        +str font_size
        +str tooltip
    }

    class EdgeStyle {
        +EdgeStyle style
        +str color
        +int width
        +str label
        +bool dashed
    }

    Visualizer --> VisualizationConfig
    Visualizer --> NodeStyle
    Visualizer --> EdgeStyle
```

### Visualization Rendering Pipeline

```mermaid
flowchart TB
    DATA[Input Data] --> PARSE[Parse to intermediate graph]
    PARSE --> GRAPH[Build Graph: nodes + edges]
    GRAPH --> APPLY_THEME[Apply theme colors/styles]
    APPLY_THEME --> CUSTOMIZE[Apply custom node/edge overrides]
    CUSTOMIZE --> LAYOUT[Compute graph layout]

    LAYOUT --> FORMAT{Output Format}
    FORMAT -->|MERMAID| MERMAID[Generate Mermaid.js string]
    FORMAT -->|DOT| DOT[Generate Graphviz DOT]
    FORMAT -->|JSON| JSON[Generate JSON graph]
    FORMAT -->|HTML| HTML[Generate HTML+SVG]
    FORMAT -->|PLAINTEXT| PLAINTEXT[Generate ASCII art]

    MERMAID --> OUTPUT[Output string]
    DOT --> OUTPUT
    JSON --> OUTPUT
    HTML --> OUTPUT
    PLAINTEXT --> OUTPUT
```

### Orientation Support

```mermaid
flowchart LR
    subgraph TB[Top-to-Bottom]
        direction TB
        A --> B --> C
    end

    subgraph LR[Left-to-Right]
        direction LR
        A2 --> B2 --> C2
    end

    subgraph RL[Right-to-Left]
        direction RL
        A3 --> B3 --> C3
    end

    subgraph BT[Bottom-to-Top]
        direction BT
        A4 --> B4 --> C4
    end
```

## Shared Data Types

```mermaid
classDiagram
    class IssueSeverity {
        <<enum>>
        INFO
        WARNING
        ERROR
        CRITICAL
    }

    class IssueCategory {
        <<enum>>
        DEAD_CODE
        UNREACHABLE
        INFINITE_LOOP
        REDUNDANCY
        UNUSED_VAR
        COMPLEXITY
        DATA_FLOW
        TYPE_SAFETY
        SECURITY
        PERFORMANCE
    }

    class TraceEventType {
        <<enum>>
        FUNCTION_CALL
        FUNCTION_RETURN
        VARIABLE_CHANGE
        CONDITION_EVAL
        LOOP_ITERATION
        EXCEPTION
        BREAKPOINT_HIT
        WATCH_TRIGGERED
        PIPELINE_STEP
        MIDDLEWARE
    }

    class DebugLevel {
        <<enum>>
        NONE
        ERROR
        WARNING
        INFO
        VERBOSE
        DEBUG
    }
```

## Configuration Relationship

```mermaid
flowchart TB
    GLOBAL[Global Config: tools.yaml]
    GLOBAL --> RA_C[analyzer config]
    GLOBAL --> DT_C[debug config]
    GLOBAL --> PR_C[profiler config]
    GLOBAL --> TR_C[test config]
    GLOBAL --> VZ_C[visualizer config]

    RA_C --> RA[RuleAnalyzer]
    DT_C --> DT[DebugTool]
    PR_C --> PR[Profiler]
    TR_C --> TR[TestRunner]
    VZ_C --> VZ[Visualizer]
```

Each tool reads its own configuration subset on initialization. If a config key is missing, sensible defaults are used. Configuration can be updated at runtime by calling the tool's config update method.

## Thread Safety

The Tools module tools are designed to be single-threaded:

```mermaid
flowchart TB
    subgraph Thread-Safe
        PR[Profiler: stateless,\nmeasurements are independent]
        VZ[Visualizer: pure functions,\nno mutable state]
    end

    subgraph Not Thread-Safe
        DT[DebugTool: shared\nbreakpoints, watchers, buffer]
        RA[RuleAnalyzer: shared\nfindings accumulator]
        TR[TestRunner: shared\nresults accumulator]
    end

    T1[Thread 1] --> DT
    T2[Thread 2] --> DT
    note for DT: DebugTool is designed for single-threaded debugging
    note for RA: Analysis calls should be serialized
```

`Profiler` and `Visualizer` are effectively stateless and can be used concurrently. `DebugTool`, `RuleAnalyzer`, and `TestRunner` maintain internal mutable state and should be used from a single thread or protected by external synchronization.
