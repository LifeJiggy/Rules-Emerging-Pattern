# Tools Module — Reasoning

## 1. Analysis Level Design

```mermaid
flowchart TB
    COST{Analysis Cost vs Benefit}

    COST --> BASIC["BASIC: 3 checks, O(n) time\nCatches obvious issues:\nunused code, dead branches"]
    COST --> STANDARD["STANDARD: 6 checks, O(n + m) time\nAdds complexity measurement,\nredundancy detection"]
    COST --> ADVANCED["ADVANCED: 8 checks, O(n * d) time\nAdds data flow tracing,\ntype safety validation"]
    COST --> COMPREHENSIVE["COMPREHENSIVE: 10 checks, O(n * d + s) time\nAdds security AST scan,\nperformance anti-patterns"]

    BASIC --> USE1["Use: quick lint on every save"]
    STANDARD --> USE2["Use: pre-commit hook"]
    ADVANCED --> USE3["Use: CI pipeline for complex rules"]
    COMPREHENSIVE --> USE4["Use: security audit, pre-release"]
```

**Decision:** Four analysis levels let consumers trade off speed vs. thoroughness:

- **BASIC** runs in O(n) and is suitable for real-time feedback (editor integration, on-save).
- **STANDARD** adds complexity and redundancy detection. Suitable for pre-commit hooks.
- **ADVANCED** adds data flow analysis. Data flow analysis requires building a control flow graph and tracing variable usage, which is O(n × d) where d is the nesting depth.
- **COMPREHENSIVE** adds security and performance checks. Security checks involve scanning for dangerous function calls (AST traversal), which is fast O(n). Performance checks look for anti-patterns in loops.

## 2. Debug Level Design

```mermaid
flowchart TB
    OVERHEAD{Debug Overhead vs Detail}

    NONE["NONE: zero overhead\nNo events captured"]
    ERROR["ERROR: minimal overhead\nOnly critical failures"]
    WARNING["WARNING: low overhead\nErrors + warnings"]
    INFO["INFO: moderate overhead\nGeneral flow events"]
    VERBOSE["VERBOSE: high overhead\n+ variable change tracking"]
    DEBUG["DEBUG: maximum overhead\n+ internal state dumps"]

    NONE --> USE0["Use: production"]
    ERROR --> USE1["Use: production with monitoring"]
    WARNING --> USE2["Use: staging/review"]
    INFO --> USE3["Use: development"]
    VERBOSE --> USE4["Use: troubleshooting complex bugs"]
    DEBUG --> USE5["Use: debugging the debugger"]
```

**Decision:** Debug levels control the verbosity of the trace buffer. Each level adds more event types:

- **NONE/ERROR** — Suitable for production. Only critical failures are recorded.
- **WARNING/INFO** — Suitable for staging. Adds general flow tracking.
- **VERBOSE** — Records variable changes. Useful for understanding state mutations.
- **DEBUG** — Records internal debug tool state. Used for tool development.

The trace buffer is circular (fixed capacity). When full, the oldest events are overwritten. This prevents unbounded memory growth regardless of debug level.

## 3. Circular Trace Buffer Design

```mermaid
flowchart TB
    subgraph Buffer Full
        B1[Event 1 oldest] --> B2[Event 2] --> B3[...] --> BN[Event N newest]
    end

    subgraph New Event Arrives
        NEW[Event N+1] --> OVERWRITE{Buffer full?}
        OVERWRITE -->|yes| REPLACE[Replace Event 1]
        OVERWRITE -->|no| APPEND[Append]
    end

    BENEFITS[Why Circular Buffer?]
    BENEFITS --> FIXED[Fixed memory: configurable max_trace_buffer]
    BENEFITS --> NO_ALLOC[No allocation: pointer wrap instead of resize]
    BENEFITS --> RECENT[Preserves most recent events always]
```

**Why circular instead of unbounded list:** An unbounded trace buffer would grow indefinitely during long debugging sessions, consuming all available memory. A circular buffer with a configurable capacity (default 10,000) provides:

1. Predictable memory usage
2. Always keeps the most recent events (most relevant for debugging)
3. O(1) append (no resize/copy cost)

## 4. Breakpoint Condition Evaluation

```mermaid
flowchart TB
    BP[Breakpoint Definition] --> HAS_COND{Condition expression?}
    HAS_COND -->|no| ALWAYS[Always break]
    HAS_COND -->|yes| PARSE[Parse expression using ast.literal_eval or safe_eval]
    PARSE --> EVAL{Evaluate in context}
    EVAL -->|True| BREAK[Pause execution]
    EVAL -->|False| SKIP[Continue without pause]
    EVAL -->|Error| FALLBACK[Log error, break anyway]

    subgraph Safe Eval Approach
        SAFE1[Restrict to: variables, comparisons, boolean ops]
        SAFE2[Deny: function calls, imports, attribute access]
        SAFE3[Timeout: 100ms max evaluation time]
    end
```

**Why safe_eval instead of exec/eval:** Breakpoint conditions are user-provided expressions. Using raw `eval()` would allow arbitrary code execution in the debugger context. Instead, conditions are evaluated using a safe expression parser that only allows:

- Variable references (from current scope)
- Comparison operators (==, !=, <, >, <=, >=)
- Boolean operators (and, or, not)
- Arithmetic operators (+, -, *, /)
- Literals (numbers, strings, None, True, False)

## 5. Profiler Timing Modes

```mermaid
flowchart TB
    MODE{Timing Mode}

    MODE --> SELF["SELF_TIME: Time spent in function alone\n(excludes child calls)"]
    MODE --> CHILD["CHILD_TIME: Time spent in child calls\n(total_time - self_time)"]
    MODE --> WALL["WALL_CLOCK: Total elapsed wall time\n(includes I/O, sleep, contention)"]
    MODE --> CPU["CPU_TIME: Actual CPU time used\n(excludes I/O wait, sleep)"]

    SELF --> USE1[Best for: finding slow functions]
    CHILD --> USE2[Best for: finding overhead in callees]
    WALL --> USE3[Best for: end-to-end latency analysis]
    CPU --> USE4[Best for: CPU-bound optimization]

    WALL --> NOTE1["Note: wall time includes garbage collection,\ncontext switches, and other processes"]
    CPU --> NOTE2["Note: CPU time is OS-dependent;\non Python, use time.process_time()"]
```

**Decision:** The profiler supports multiple timing modes because:

- **Self time** answers "which function is slow by itself?"
- **Child time** answers "which function has expensive callees?"
- **Wall clock** answers "how long does the user wait?"
- **CPU time** answers "how much CPU does this consume?"

No single metric is sufficient for performance analysis.

## 6. Profiling Depth Options

```mermaid
flowchart TB
    DEPTH{Profiling Depth}

    DEPTH --> FUNCTION["FUNCTION: Profile function entry/exit only\nLowest overhead, best for high-level"]
    DEPTH --> LINE["LINE: Profile every line execution\nHigh overhead, best for hotspots"]
    DEPTH --> CALL_GRAPH["CALL_GRAPH: Build full call tree\nMedium overhead, best for understanding flow"]

    FUNCTION --> OVERHEAD1["Overhead: ~1μs per call (2 timer reads)"]
    LINE --> OVERHEAD2["Overhead: ~10μs per line (sys.settrace)"]
    CALL_GRAPH --> OVERHEAD3["Overhead: ~2μs per call + memory for tree"]

    LINE --> WARNING["WARNING: sys.settrace slows ALL Python code\nUse only on specific functions"]
```

**Why FUNCTION is the default:** `sys.settrace` (required for line-level profiling) can slow down execution by 10-100x because it fires on every Python line execution. Function-level profiling only adds overhead at function boundaries, making it suitable for production use.

**When to use CALL_GRAPH:** Call graph profiling is useful for understanding execution flow and finding unexpected call paths. It adds moderate overhead (parent/child tracking) but provides valuable insight into execution structure.

**When to use LINE profiling:** Line profiling is the nuclear option — use only when you've identified a specific function as a bottleneck and need to pinpoint which line within it is slow.

## 7. Test Types Design

```mermaid
flowchart TB
    TEST{Test Type Selection}

    TEST --> PROPERTY["PROPERTY: invariant-based\n'output should always be sorted'"]
    TEST --> SNAPSHOT["SNAPSHOT: output comparison\n'output should match stored reference'"]
    TEST --> FUZZ["FUZZ: random inputs\n'no crashes on any input'"]
    TEST --> COMPARISON["COMPARISON: cross-rule\n'rule A and rule B should agree'"]
    TEST --> THRESHOLD["THRESHOLD: performance/reliability\n'execution time < 100ms'"]
    TEST --> REGRESSION["REGRESSION: known inputs\n'known bug should stay fixed'"]
    TEST --> GOLDEN["GOLDEN: file-based\n'output should match golden file'"]

    PROPERTY --> USE1[Best for: mathematical invariants,\nidempotence, commutativity]
    SNAPSHOT --> USE2[Best for: refactoring safety net,\noutput format changes]
    FUZZ --> USE3[Best for: robustness,\nsecurity edge cases]
    COMPARISON --> USE4[Best for: A/B testing,\nmigration validation]
    THRESHOLD --> USE5[Best for: SLA verification,\nperformance budgets]
    REGRESSION --> USE6[Best for: bug fix verification,\nCI pipelines]
    GOLDEN --> USE7[Best for: complex output,\nUI rendering, reports]
```

**Why support 7 test types:** Different aspects of rule correctness require different testing strategies:

1. **Property-based** — Catches edge cases that explicit test cases miss. The generator produces random inputs, and properties are invariants that should hold for all inputs.
2. **Snapshot** — Captures the full output and compares it to a stored reference. When the output changes intentionally, the snapshot is updated.
3. **Fuzz** — Tests robustness by generating random, mutated, or boundary inputs. Find crashes and unexpected exceptions.
4. **Comparison** — When replacing or modifying a rule, compare its output to the original. Ensures behavioral equivalence.
5. **Threshold** — Not just correctness but performance and reliability. Assert that execution time, memory usage, or error rate stays within bounds.
6. **Regression** — The standard testing approach. Known inputs produce known outputs.
7. **Golden** — Like snapshot but uses external files (useful for complex or large outputs).

## 8. Visualizer Output Format Selection

```mermaid
flowchart TB
    FORMAT{Output Format}

    FORMAT --> MERMAID["MERMAID: Mermaid.js diagram\nBest for: embedding in Markdown,\ndocs, GitHub"]
    FORMAT --> DOT["DOT: Graphviz DOT language\nBest for: complex graphs,\ncustom rendering"]
    FORMAT --> JSON["JSON: structured graph data\nBest for: programmatic consumption,\ncustom renderers"]
    FORMAT --> HTML["HTML: self-contained SVG\nBest for: web dashboards,\ninteractive exploration"]
    FORMAT --> PLAINTEXT["PLAINTEXT: ASCII art\nBest for: terminal display,\nquick debugging"]

    MERMAID --> MERMAID_PRO["Rich ecosystem, GitHub native,\nsimple text format"]
    DOT --> DOT_PRO["Mature layout engine (neato, dot),\nhandles large graphs]
    JSON --> JSON_PRO["Language-agnostic,\neasy to transform"]
    HTML --> HTML_PRO["Interactive (zoom, pan, search),\nembedded styling"]
    PLAINTEXT --> PLAINTEXT_PRO["Zero dependencies,\nworks in any terminal"]
```

**Why MERMAID is the default:** Mermaid.js has become the de facto standard for diagrams in Markdown documentation. It is natively supported by GitHub, GitLab, and many documentation tools. The text-based format is easy to version control and diff.

**When to choose other formats:**
- **DOT** — For graphs with more than 50 nodes, Graphviz's layout engine produces better results.
- **JSON** — When the graph needs to be consumed by a custom frontend.
- **HTML/SVG** — For interactive dashboards where the user needs to explore the graph.
- **PLAINTEXT** — When working over SSH or in environments without a browser.

## 9. Node and Edge Customization

```mermaid
flowchart TB
    CUSTOMIZE[Customization API]
    CUSTOMIZE --> NODE[customize_node(id, style)]
    CUSTOMIZE --> EDGE[customize_edge(from, to, style)]

    NODE --> SHAPE[Shape: rect, circle, diamond, ellipse, hexagon, parallelogram]
    NODE --> COLOR[Fill color: hex/rgb]
    NODE --> BORDER[Border: color, width]
    NODE --> TEXT[Font size, tooltip]

    EDGE --> STYLE[EdgeStyle: solid, dashed, dotted, bold]
    EDGE --> COLOR2[Color: hex/rgb]
    EDGE --> WIDTH[Width: pixels]
    EDGE --> LABEL[Label text]
    EDGE --> DIR[Arrow direction: forward, both, none]

    SHAPE --> RATIONALE["Why multiple shapes?\nDifferentiate node types visually\ncircle = start/end, diamond = decision,\nrectangle = process"]
```

## 10. Profiler Merge and Filter

```mermaid
sequenceDiagram
    participant Client
    participant P1 as Profiler (before fix)
    participant P2 as Profiler (after fix)

    Client->>P1: profile_function(slow_func)
    P1-->>Client: profile_data
    Client->>P2: profile_function(slow_func)
    P2-->>Client: profile_data

    Client->>P1: merge(P2)
    P1->>P1: combine profile_data dicts
    P1->>P1: deduplicate by (name, start_time)
    P1->>P1: recompute aggregated stats
    P1-->>Client: merged Profiler

    Client->>P1: filter(target="parse")
    P1->>P1: keep only entries where name matches "parse"
    P1->>P1: rebuild parent/child relationships
    P1-->>Client: filtered Profiler
```

**Why merge and filter:** In performance analysis, you often need to:
- **Merge** results from multiple runs (before/after a fix) to compare performance.
- **Filter** to focus on specific functions or modules, excluding noise from unrelated code.

## 11. TestRunner Coverage Metrics

```mermaid
flowchart TB
    COV{Coverage Metric}

    COV --> LINE["LINE: % of code lines executed\nSimple, well-understood metric"]
    COV --> BRANCH["BRANCH: % of if/else branches taken\nCatches missing else branches"]
    COV --> PATH["PATH: % of possible execution paths\nExponential complexity, rarely 100%"]
    COV --> CONDITION["CONDITION: % of boolean sub-expressions evaluated\nCatches short-circuit gaps"]
    COV --> FUNCTION["FUNCTION: % of functions called\nMinimal baseline"]

    LINE --> USE1[Target: 80%+]
    BRANCH --> USE2[Target: 70%+]
    PATH --> USE3[Target: 50%+ for critical paths only]
    CONDITION --> USE4[Target: 60%+ for complex conditions]
    FUNCTION --> USE5[Target: 90%+]

    PATH --> WARNING2["WARNING: Path coverage grows exponentially\nwith decision points. Use only for small functions."]
```

**Why multiple coverage metrics:** Line coverage alone is misleading — 100% line coverage can still miss untaken branches. Branch coverage catches missing else paths. Condition coverage catches short-circuit evaluation gaps (e.g., `x or y` where `y` is never evaluated because `x` is always True).

## 12. Tool Composition

```mermaid
flowchart TB
    COMPOSE{Tool Composition Strategies}

    COMPOSE --> PIPELINE["Pipeline: output of A → input of B"]
    COMPOSE --> AGGREGATE["Aggregate: A + B → merged result"]
    COMPOSE --> SELECTIVE["Selective: choose tool based on context"]

    PIPELINE --> P1["RuleAnalyzer → Visualizer\n(analyze rule, visualize results)"]
    PIPELINE --> P2["Profiler → Visualizer\n(profile execution, visualize timeline)"]
    PIPELINE --> P3["DebugTool → TestRunner\n(record trace, replay as test)"]

    AGGREGATE --> A1["Profiler.merge()\n(combine before/after profiles)"]
    AGGREGATE --> A2["TestRunner.run_all()\n(aggregate multiple test suites)"]

    SELECTIVE --> S1["DebugTool.INFO for dev\nDebugTool.ERROR for prod"]
    SELECTIVE --> S2["RuleAnalyzer.BASIC on save\nRuleAnalyzer.COMPREHENSIVE in CI"]
```

**Why composition over monolithic tools:** Each tool has a single responsibility. Composition lets consumers build custom workflows by chaining tools:

- `analyze → visualize` produces a diagram of rule issues
- `profile → visualize` produces a performance flamegraph
- `debug → test` converts a debugging session into a regression test
