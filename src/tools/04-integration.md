# Tools Module — Integration

## 1. Integration Overview

```mermaid
flowchart TB
    subgraph Consumers
        CLI[CLI Interface]
        API[REST API]
        IDE[IDE / Editor]
        CORE[Application Core]
        CICD[CI/CD Pipeline]
    end

    subgraph Tools Module
        RA[RuleAnalyzer]
        DT[DebugTool]
        PR[Profiler]
        TR[TestRunner]
        VZ[Visualizer]
    end

    subgraph Data Sources
        RULES[Rule Definitions]
        EXEC[Skill Executor]
        REG[Skill Registry]
    end

    CLI --> RA
    CLI --> TR
    CLI --> VZ
    API --> RA
    API --> TR
    API --> VZ
    IDE --> RA
    IDE --> DT
    CICD --> RA
    CICD --> TR
    CORE --> PR
    CORE --> DT

    RA --> RULES
    DT --> EXEC
    PR --> EXEC
    TR --> RULES
    VZ --> REG
    VZ --> RULES
```

## 2. Integration with CLI

The CLI provides command-line access to all five tools.

```mermaid
sequenceDiagram
    participant User
    participant CLI as CLI
    participant RA as RuleAnalyzer
    participant VZ as Visualizer
    participant TR as TestRunner

    User->>CLI: analyze rule.yaml
    CLI->>RA: analyze(rule_dict)
    RA-->>CLI: AnalysisReport
    CLI->>User: formatted report with issues

    User->>CLI: analyze rule.yaml --visualize
    CLI->>RA: analyze(rule_dict)
    RA-->>CLI: AnalysisReport
    CLI->>VZ: visualize_rule(rule_dict)
    VZ-->>CLI: mermaid diagram
    CLI->>User: formatted report + diagram

    User->>CLI: test run tests.yaml
    CLI->>TR: run(test_suite)
    TR-->>CLI: TestReport
    CLI->>User: formatted test results

    User->>CLI: test coverage rules/
    CLI->>TR: coverage(rules)
    TR-->>CLI: CoverageReport
    CLI->>User: formatted coverage table

    User->>CLI: visualize dependency registry
    CLI->>VZ: visualize_dependency(registry)
    VZ-->>CLI: mermaid string
    CLI->>User: rendered diagram
```

### CLI Command Mapping

| CLI Command | Tool Method |
|---|---|
| `analyze <rule>` | `RuleAnalyzer.analyze(rule)` |
| `analyze all <dir>` | `RuleAnalyzer.analyze_all(rules)` |
| `analyze <rule> --level BASIC` | `RuleAnalyzer.analyze(rule, level=BASIC)` |
| `debug trace <rule>` | `DebugTool.trace_event(...)` |
| `debug breakpoint <rule>:<line>` | `DebugTool.set_breakpoint(skill, line)` |
| `debug inspect <var>` | `DebugTool.inspect_variable(var)` |
| `debug snapshot` | `DebugTool.snapshot(context)` |
| `profile run <rule>` | `Profiler.profile_function(func, args)` |
| `profile report [--format json]` | `Profiler.report(format)` |
| `profile top [--n 10]` | `Profiler.top_calls(n)` |
| `test run <suite>` | `TestRunner.run(test_suite)` |
| `test all` | `TestRunner.run_all(suites)` |
| `test coverage <dir>` | `TestRunner.coverage(rules)` |
| `test fuzz <rule>` | `TestRunner.run_fuzz(rule, fuzzer)` |
| `visualize rule <rule>` | `Visualizer.visualize_rule(rule)` |
| `visualize deps` | `Visualizer.visualize_dependency(registry)` |
| `visualize exec <log>` | `Visualizer.visualize_execution(log)` |
| `visualize timeline <events>` | `Visualizer.visualize_timeline(events)` |

## 3. Integration with REST API

```mermaid
sequenceDiagram
    participant Client
    participant API as REST API
    participant RA as RuleAnalyzer
    participant TR as TestRunner
    participant VZ as Visualizer

    Client->>API: POST /tools/analyze {rule}
    API->>RA: analyze(rule)
    RA-->>API: AnalysisReport
    API-->>Client: 200 {complexity, issues, ...}

    Client->>API: POST /tools/analyze/batch {rules}
    API->>RA: analyze_all(rules)
    RA-->>API: AnalysisReport
    API-->>Client: 200 {aggregate_issues, ...}

    Client->>API: POST /tools/test {suite}
    API->>TR: run(suite)
    TR-->>API: TestReport
    API-->>Client: 200 {passed, failed, pass_rate, ...}

    Client->>API: POST /tools/coverage {rules}
    API->>TR: coverage(rules)
    TR-->>API: CoverageReport
    API-->>Client: 200 {line, branch, function, ...}

    Client->>API: POST /tools/visualize/rule {rule, format}
    API->>VZ: visualize_rule(rule)
    VZ-->>API: mermaid/html string
    API-->>Client: 200 {diagram: "..."}

    Client->>API: POST /tools/visualize/deps
    API->>VZ: visualize_dependency(registry)
    VZ-->>API: diagram string
    API-->>Client: 200 {diagram: "..."}
```

### API Endpoint Mapping

| HTTP Method | Endpoint | Tool Method |
|---|---|---|
| `POST` | `/tools/analyze` | `RuleAnalyzer.analyze()` |
| `POST` | `/tools/analyze/batch` | `RuleAnalyzer.analyze_all()` |
| `GET` | `/tools/analyze/levels` | (returns enum info) |
| `POST` | `/tools/test` | `TestRunner.run()` |
| `POST` | `/tools/test/all` | `TestRunner.run_all()` |
| `POST` | `/tools/coverage` | `TestRunner.coverage()` |
| `POST` | `/tools/visualize/rule` | `Visualizer.visualize_rule()` |
| `POST` | `/tools/visualize/deps` | `Visualizer.visualize_dependency()` |
| `POST` | `/tools/visualize/exec` | `Visualizer.visualize_execution()` |
| `POST` | `/tools/visualize/timeline` | `Visualizer.visualize_timeline()` |

## 4. Integration with Skills Module

The tools consume and operate on data from the Skills module.

```mermaid
flowchart TB
    subgraph Skills Module
        LOAD[SkillLoader]
        REG[SkillRegistry]
        EXEC[SkillExecutor]
    end

    subgraph Tools Module
        RA[RuleAnalyzer]
        DT[DebugTool]
        PR[Profiler]
        TR[TestRunner]
        VZ[Visualizer]
    end

    LOAD --> RA: skill definitions to analyze
    LOAD --> TR: skill definitions to test
    REG --> VZ: dependency graph to visualize
    EXEC --> DT: execution events to trace
    EXEC --> PR: execution to profile
    EXEC --> TR: execution results to verify
    RA --> VZ: analysis findings to visualize
    PR --> VZ: profile data to visualize
    TR --> VZ: test results to visualize
```

### Specific Integration Points

| Skills Component | Tool | Integration |
|---|---|---|
| `RuleSkill` | `RuleAnalyzer` | `analyze(rule.to_dict())` |
| `RuleSkill` | `TestRunner` | `run(rule_test_suite)` |
| `SkillRegistry` | `Visualizer` | `visualize_dependency(registry)` |
| `SkillExecutor` | `DebugTool` | `trace_event(call, context)` on each execution |
| `SkillExecutor` | `Profiler` | `start(name) / stop(name)` around execution |
| `SkillLoader` | `RuleAnalyzer` | `analyze(loaded_skill)` on load |
| `SkillValidator` | `RuleAnalyzer` | `analyze(rule)` for deeper validation |

## 5. Integration with CI/CD Pipeline

```mermaid
sequenceDiagram
    participant DEV as Developer
    participant REPO as Git Repository
    participant CI as CI/CD
    participant TR as TestRunner
    participant RA as RuleAnalyzer
    participant VZ as Visualizer

    DEV->>REPO: git push (rule changes)
    REPO->>CI: trigger pipeline

    CI->>RA: analyze_all(rules, level=STANDARD)
    RA-->>CI: AnalysisReport
    CI->>CI: check max_issue_severity < ERROR
    alt Issues found
        CI-->>DEV: Pipeline failed - fix issues
    end

    CI->>TR: run_all(test_suites)
    TR-->>CI: TestReport
    CI->>CI: check pass_rate >= 1.0
    alt Tests failed
        CI-->>DEV: Pipeline failed - fix tests
    end

    CI->>TR: coverage(rules)
    TR-->>CI: CoverageReport
    CI->>CI: check line_coverage >= 80%
    alt Coverage too low
        CI-->>DEV: Pipeline warning - add more tests
    end

    CI->>VZ: visualize_rule(changed_rules)
    VZ-->>CI: mermaid diagrams
    CI-->>REPO: PR comment with diagrams
    CI-->>DEV: Pipeline passed
```

### CI Configuration Example

```yaml
# .github/workflows/rule-ci.yml
jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Analyze rules
        run: python -m tools analyze level STANDARD ./rules
      - name: Run tests
        run: python -m tools test all
      - name: Check coverage
        run: python -m tools test coverage --target 80
```

## 6. Integration with IDE / Editor

```mermaid
sequenceDiagram
    participant IDE as IDE / Editor
    participant LSP as Language Server
    participant RA as RuleAnalyzer
    participant VZ as Visualizer

    Note over IDE: On file open
    IDE->>LSP: didOpen(rule.yaml)
    LSP->>RA: analyze(rule, level=BASIC)
    RA-->>LSP: AnalysisReport
    LSP->>IDE: publishDiagnostics(issues)

    Note over IDE: On file change
    IDE->>LSP: didChange(rule.yaml)
    LSP->>RA: analyze(rule, level=BASIC)
    RA-->>LSP: AnalysisReport
    LSP->>IDE: publishDiagnostics(updated issues)

    Note over IDE: On hover
    IDE->>LSP: hover(rule.yaml:line 42)
    LSP->>RA: (find analysis for line 42)
    RA-->>LSP: issue details inline
    LSP->>IDE: hover text

    Note over IDE: On command
    IDE->>CP: Command: Visualize Rule
    CP->>VZ: visualize_rule(rule)
    VZ-->>CP: mermaid diagram
    CP->>IDE: Show diagram in side panel
```

### LSP Integration

```python
# LSP handler pseudocode
def on_diagnostic(params):
    rule = load_rule(params.uri)
    report = analyzer.analyze(rule, level=AnalysisLevel.BASIC)
    diagnostics = []
    for finding in report.findings:
        diagnostics.append({
            "range": {"start": {"line": finding.line, "character": finding.column}},
            "severity": finding.severity.value,
            "message": finding.message,
            "source": "rule-analyzer"
        })
    return {"uri": params.uri, "diagnostics": diagnostics}
```

## 7. Integration with Monitoring System

```mermaid
flowchart LR
    subgraph Tools Metrics
        RA[RuleAnalyzer] --> AM1[analysis_time]
        RA --> AM2[issues_found]
        RA --> AM3[complexity_scores]

        DT[DebugTool] --> DM1[trace_buffer_usage]
        DT --> DM2[breakpoint_hits]

        PR[Profiler] --> PM1[execution_time]
        PR --> PM2[call_count]
        PR --> PM3[slowest_paths]
        PR --> PM4[gc_pause_time]

        TR[TestRunner] --> TM1[test_pass_rate]
        TR --> TM2[coverage_percent]
        TR --> TM3[test_duration]
    end

    subgraph Monitoring
        PROM[Prometheus]
        GRAF[Grafana]
        LOG[Structured Logs]
    end

    AM1 --> PROM
    AM2 --> PROM
    PM1 --> PROM
    PM2 --> PROM
    TM1 --> GRAF
    TM2 --> GRAF
    DM1 --> LOG
    DM2 --> LOG
```

## 8. Integration with Storage Module

```mermaid
sequenceDiagram
    participant TR as TestRunner
    participant RS as RuleStorage
    participant FS as FileStore

    Note over TR: Snapshot testing
    TR->>RS: read("snapshot_rule_a")
    RS->>FS: read("tests/snapshots/rule_a.yaml")
    FS-->>RS: stored snapshot
    RS-->>TR: expected output
    TR->>TR: compare actual vs expected

    Note over TR: Golden testing
    TR->>FS: read("tests/golden/rule_a_output.txt")
    FS-->>TR: golden file content
    TR->>TR: compare actual output vs golden

    Note over TR: Test results persistance
    TR->>RS: write("test_report_latest", report_dict)
    RS->>FS: atomic_write("reports/test_report.yaml", report)
    FS-->>RS: True
    RS-->>TR: True
```

## 9. Integration Patterns

### Pattern 1: Analyze Before Execution

```mermaid
sequenceDiagram
    participant APP as Application
    participant RA as RuleAnalyzer
    participant EXEC as SkillExecutor

    APP->>RA: analyze(rule, level=BASIC)
    RA-->>APP: AnalysisReport
    APP->>APP: check for ERROR-level issues
    alt No errors
        APP->>EXEC: execute(rule, inputs)
        EXEC-->>APP: ExecutionResult
    else Errors found
        APP->>APP: log warning, skip execution
    end
```

### Pattern 2: Debug on Failure

```mermaid
sequenceDiagram
    participant APP as Application
    participant EXEC as SkillExecutor
    participant DT as DebugTool

    APP->>EXEC: execute(rule, inputs)
    EXEC-->>APP: ExecutionResult(FAILURE)
    APP->>DT: snapshot(execution_context)

    alt Replay with breakpoints
        APP->>DT: set_breakpoint(rule, line=42)
        APP->>EXEC: execute(rule, inputs) [debug mode]
        EXEC->>DT: trace_event(...)
        DT-->>APP: breakpoint hit at line 42
        APP->>DT: inspect_variable("x")
        DT-->>APP: {"x": None}
    end
```

### Pattern 3: Profile and Visualize

```mermaid
sequenceDiagram
    participant DEV as Developer
    participant PR as Profiler
    participant VZ as Visualizer

    DEV->>PR: start("pipeline")
    DEV->>PR: start("step_1")
    DEV->>PR: stop("step_1")
    DEV->>PR: start("step_2")
    DEV->>PR: stop("step_2")
    DEV->>PR: stop("pipeline")

    DEV->>PR: top_calls(3)
    PR-->>DEV: [ProfileResult, ...]

    DEV->>VZ: visualize_timeline(PR.profile_data)
    VZ-->>DEV: mermaid timeline diagram

    DEV->>PR: report(format="flamegraph")
    PR-->>DEV: folded stack format
```

### Pattern 4: CI Gate

```mermaid
flowchart TB
    PR[Pull Request] --> ANALYZE[Run RuleAnalyzer]
    ANALYZE --> CHECK{ERROR issues?}
    CHECK -->|yes| REJECT[Reject PR]
    CHECK -->|no| TEST[Run TestRunner]
    TEST --> CHECK2{Tests pass?}
    CHECK2 -->|no| REJECT
    CHECK2 -->|yes| COVERAGE[Check coverage]
    COVERAGE --> CHECK3{Coverage >= 80%?}
    CHECK3 -->|no| WARN[Warning comment]
    CHECK3 -->|yes| APPROVE[Approve PR]
    WARN --> APPROVE
```

### Pattern 5: Continuous Profiling

```mermaid
sequenceDiagram
    participant APP as Application
    participant PR as Profiler
    participant MON as Monitoring

    loop Every hour
        APP->>PR: reset()
        APP->>PR: profile_function(critical_rule)
        PR-->>APP: ProfileResult
        APP->>MON: push metric "execution_time_p99"
        APP->>MON: push metric "call_count"
    end

    alt Execution time > threshold
        MON->>PR: report(format="json")
        PR-->>MON: detailed profile
        MON->>MON: trigger alert
    end
```

## 10. Tool Interoperability Matrix

| Tool | Consumes From | Produces For |
|---|---|---|
| `RuleAnalyzer` | `RuleSkill`, `SkillLoader` | `Visualizer`, reports |
| `DebugTool` | `SkillExecutor` | `TestRunner` (replay), `Visualizer` (trace) |
| `Profiler` | `SkillExecutor` | `Visualizer` (timeline), reports |
| `TestRunner` | `RuleSkill`, `RuleAnalyzer` | `Visualizer` (results), coverage reports |
| `Visualizer` | All tools | CLI output, REST response, file export |

## 11. Configuration Integration

```yaml
# Main application config for tools
tools:
  analyzer:
    default_level: "comprehensive"
    max_iterations: 100000
    max_depth: 50

  debug:
    default_level: "info"
    max_trace_buffer: 50000
    capture_snapshots: true

  profiler:
    default_target: "function"
    default_depth: "call_graph"
    default_timing: "wall_clock"

  test_runner:
    timeout: 60.0
    coverage_enabled: true
    coverage_target: 80
    default_format: "json"

  visualizer:
    default_format: "mermaid"
    default_orientation: "TB"
    max_nodes: 100
    max_edges: 500
```

The Tools module reads its configuration from a shared config object on initialization. Individual tools can be reconfigured at runtime by calling their configure methods after initialization.
