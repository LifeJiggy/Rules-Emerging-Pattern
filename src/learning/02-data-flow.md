# Learning Module Data Flow

## End-to-End Pipeline

The learning pipeline processes data through five stages: raw input, feature extraction, pattern detection, model training, and feedback learning. Each stage passes structured data to the next, with loops for continuous improvement.

```mermaid
flowchart LR
    subgraph Input["Input Layer"]
        A1[Raw Data Stream]
        A2[Historical Logs]
        A3[User Feedback]
    end

    subgraph PE["Pattern Engine<br/>pattern_engine.py"]
        B1[analyze_data]
        B2[Pattern Matching<br/>regex / keyword / semantic]
        B3[Confidence Scoring]
        B4[Pattern Clustering]
        B5[Correlation Analysis]
    end

    subgraph TA["Trend Analyzer<br/>trend_analyzer.py"]
        C1[add_data_point]
        C2[analyze_trends]
        C3[detect_anomalies]
        C4[forecast]
    end

    subgraph FE["Feature Extractor<br/>feature_extractor.py"]
        D1[extract]
        D2[Text Features]
        D3[Statistical Features]
        D4[Structural Features]
        D5[Content Features]
        D6[Feature Selection]
        D7[Normalization]
    end

    subgraph MT["Model Trainer<br/>model_trainer.py"]
        E1[create_model]
        E2[train]
        E3[cross_validate]
        E4[evaluate]
        E5[save / load model]
    end

    subgraph FL["Feedback Learner<br/>feedback_learner.py"]
        F1[record_feedback]
        F2[Q-Learning]
        F3[Bandit / Thompson]
        F4[Adjust Targets]
        F5[Export Feedback]
    end

    subgraph Output["Output Layer"]
        G1[Detected Patterns]
        G2[Trained Models]
        G3[Trend Summaries]
        G4[Adjustment Rules]
        G5[Feature Vectors]
        G6[Learning Curves]
    end

    A1 --> B1
    A2 --> B1
    A3 --> F1

    B1 --> B2
    B2 --> B3
    B3 --> B4
    B4 --> B5
    B5 --> C1
    B5 --> G1

    C1 --> C2
    C2 --> C3
    C2 --> C4
    C2 --> G3
    C3 --> D1
    C4 --> D1

    D1 --> D2
    D1 --> D3
    D1 --> D4
    D1 --> D5
    D2 --> D6
    D3 --> D6
    D4 --> D6
    D5 --> D6
    D6 --> D7
    D7 --> E4
    D7 --> G5

    E1 --> E2
    E2 --> E3
    E3 --> E4
    E4 --> E5
    E4 --> G2
    E4 --> F1

    F1 --> F2
    F1 --> F3
    F2 --> F4
    F3 --> F4
    F4 --> B3
    F4 --> E2
    F4 --> G4
    F5 --> G6
```

## Pattern Detection Sequence

This sequence shows how the `PatternRecognitionEngine.analyze_data()` method invokes internal matchers, updates pattern metadata, and triggers rule generation.

```mermaid
sequenceDiagram
    participant Client
    participant PE as PatternRecognitionEngine
    participant Matcher as Internal Matchers
    participant Store as Pattern Store
    participant RuleGen as Rules Generator

    Client->>PE: analyze_data(data, context)
    activate PE

    PE->>PE: Normalize & tokenize input
    PE->>Matcher: match_regex(data)
    activate Matcher
    Matcher-->>PE: regex_matches
    deactivate Matcher

    PE->>Matcher: match_keywords(data)
    activate Matcher
    Matcher-->>PE: keyword_matches
    deactivate Matcher

    PE->>Matcher: match_semantic(data)
    activate Matcher
    Matcher-->>PE: semantic_matches
    deactivate Matcher

    PE->>Matcher: match_structural(data)
    activate Matcher
    Matcher-->>PE: structural_matches
    deactivate Matcher

    PE->>PE: Deduplicate & merge matches
    PE->>PE: Score confidence for each pattern
    PE->>PE: Update occurrences & timestamps
    PE->>Store: upsert pattern
    activate Store
    Store-->>PE: updated pattern
    deactivate Store

    PE->>PE: Cluster related patterns
    PE->>PE: Find correlations

    alt confidence >= rule_generation_threshold
        PE->>RuleGen: generate_rules_from_patterns()
        activate RuleGen
        RuleGen-->>PE: rule_suggestions
        deactivate RuleGen
    end

    PE-->>Client: List[Pattern]
    deactivate PE
```

## Trend Analysis Sequence

The `TrendAnalyzer` pipeline: data points are added incrementally, trends are computed on demand, and anomalies are flagged when deviations exceed configurable thresholds.

```mermaid
sequenceDiagram
    participant Source as Data Source
    participant TA as TrendAnalyzer
    participant Store as Metric Store
    participant Detector as Anomaly Detector
    participant Forecaster as Forecast Engine

    Source->>TA: add_data_point(metric, value, timestamp, metadata)
    activate TA
    TA->>Store: store data point
    deactivate TA

    Client->>TA: analyze_trends(metric_name)
    activate TA
    TA->>Store: get time series data
    Store-->>TA: List[DataPoint]

    TA->>TA: compute moving average & slope
    TA->>TA: calculate trend direction
    TA->>TA: generate confidence score
    TA-->>Client: List[Trend]
    deactivate TA

    Client->>TA: detect_anomalies(metric_name, threshold)
    activate TA
    TA->>Store: get time series data
    Store-->>TA: List[DataPoint]
    TA->>Detector: z-score / iqr detection
    activate Detector
    Detector-->>TA: anomalous points
    deactivate Detector
    TA-->>Client: List[Anomaly]
    deactivate TA

    Client->>TA: forecast(metric, periods, method)
    activate TA
    TA->>Store: get time series data
    Store-->>TA: List[DataPoint]
    TA->>Forecaster: linear / ma / exp_smooth / arima / ensemble
    activate Forecaster
    Forecaster-->>TA: predicted values
    deactivate Forecaster
    TA-->>Client: List[float]
    deactivate TA
```

## Feature Extraction Sequence

The `FeatureExtractor` runs four parallel extraction pathways — text, statistical, structural, and content — then merges, filters, and normalizes results into a single `FeatureVector`.

```mermaid
sequenceDiagram
    participant Client
    participant FE as FeatureExtractor
    participant TextE as Text Extractor
    participant StatE as Statistical Extractor
    participant StructE as Structural Extractor
    participant ContE as Content Extractor
    participant Selector as Feature Selector
    participant Normalizer as Normalizer

    Client->>FE: extract(text, context)
    activate FE

    par Parallel Extraction
        FE->>TextE: extract text features
        activate TextE
        TextE-->>FE: word_count, char_count, ratio
        deactivate TextE

        FE->>StatE: extract statistical features
        activate StatE
        StatE-->>FE: entropy, vocabulary_richness, hapax
        deactivate StatE

        FE->>StructE: extract structural features
        activate StructE
        StructE-->>FE: paragraph_count, code_blocks
        deactivate StructE

        FE->>ContE: extract content features
        activate ContE
        ContE-->>FE: sentiment, readability, formality
        deactivate ContE
    end

    FE->>FE: merge all features into vector
    FE->>Selector: select_features(vector, method, top_k)
    activate Selector
    Selector-->>FE: selected feature names
    deactivate Selector

    FE->>FE: filter vector to selected features
    FE->>Normalizer: normalize(vector)
    activate Normalizer
    Normalizer-->>FE: normalized vector
    deactivate Normalizer

    FE-->>Client: FeatureVector
    deactivate FE
```

## Training & Evaluation Sequence

The `ModelTrainer` pipeline showing model creation, example collection, training with dataset splitting, evaluation, and persistence.

```mermaid
sequenceDiagram
    participant Client
    participant MT as ModelTrainer
    participant Model as BaseModel
    participant Splitter as Data Splitter
    participant Eval as Evaluator

    Client->>MT: create_model(model_id, model_type)
    activate MT
    MT->>Model: instantiate model
    activate Model
    Model-->>MT: model ready
    deactivate Model
    MT-->>Client: model instance
    deactivate MT

    Client->>MT: add_example(features, label, weight)
    activate MT
    MT->>MT: append to examples list
    MT-->>Client: TrainingExample
    deactivate MT

    Client->>MT: train(model_id, dataset)
    activate MT
    MT->>MT: prepare dataset from examples
    MT->>Splitter: split_data(train_ratio, val_ratio)
    activate Splitter
    Splitter-->>MT: train_set, val_set, test_set
    deactivate Splitter

    MT->>Model: fit(train_set)
    activate Model
    Model-->>MT: trained parameters
    deactivate Model

    MT->>Eval: evaluate(val_set)
    activate Eval
    Eval-->>MT: accuracy, precision, recall, f1, mcc, log_loss
    deactivate Eval

    MT->>MT: store metrics & version
    MT-->>Client: ModelMetrics
    deactivate MT

    Client->>MT: predict(model_id, features)
    activate MT
    MT->>Model: predict(features)
    activate Model
    Model-->>MT: prediction, confidence
    deactivate Model
    MT-->>Client: (prediction, confidence)
    deactivate MT
```

## Feedback Learning Sequence

The `FeedbackLearner` runs episodic reinforcement learning: feedback is recorded via multiple sources, aggregated, then used to update target adjustments via Q-learning or bandit strategies.

```mermaid
sequenceDiagram
    participant Source as Feedback Source
    participant FL as FeedbackLearner
    participant Buffer as Feedback Buffer
    participant RL as RL Strategies
    participant Target as Target Store

    Source->>FL: record_feedback(target_id, value, source, type)
    activate FL
    FL->>Buffer: store in feedback_history
    FL-->>Source: FeedbackEntry
    deactivate FL

    Source->>FL: record_user_feedback(target_id, rating, explicit)
    activate FL
    FL->>Buffer: store with user source
    FL-->>Source: FeedbackEntry
    deactivate FL

    Client->>FL: run_episode(feedback_batch)
    activate FL

    FL->>Buffer: retrieve batch entries
    Buffer-->>FL: filtered entries

    FL->>FL: aggregate by target_id
    FL->>RL: select strategy
    activate RL

    RL-->>FL: selected strategy

    FL->>FL: compute adjustment using Q-Learning
    FL->>FL: update q_table (state, action, reward)

    FL->>Target: update adjustment(target_id)
    activate Target
    Target-->>FL: adjustment applied
    deactivate Target

    FL->>FL: record LearningProgress

    FL-->>Client: LearningProgress
    deactivate FL

    Client->>FL: get_adjustment(target_id)
    activate FL
    FL->>Target: lookup current adjustment
    Target-->>FL: float adjustment
    FL-->>Client: float
    deactivate FL

    Client->>FL: get_learning_curve()
    activate FL
    FL-->>Client: List[Dict] progress
    deactivate FL
```

## Pattern-to-Rule Flow

High-confidence patterns automatically trigger rule generation. This diagram shows how patterns pass the threshold gate, convert to rule specifications, and are validated before integration.

```mermaid
flowchart TD
    P[Discovered Pattern] --> QC{confidence ><br/>min_confidence?}
    QC -->|no| Drop[Archived / Ignored]
    QC -->|yes| Thresh{occurrences ><br/>min_occurrences?}
    Thresh -->|no| Drop
    Thresh -->|yes| Val[Validate Pattern]
    Val --> Valid{Is valid?}
    Valid -->|no| Drop
    Valid -->|yes| Gen[Generate Rule Spec]
    Gen --> RU[Rule Object]
    RU --> RU_VALID{Passes validation?}
    RU_VALID -->|no| Drop
    RU_VALID -->|yes| Store[Persist to Rule Store]
    Store --> Notify[Notify Rule Engine]
    Notify --> Active[Active Rule Set]
```

## Anomaly Decision Flow

How the `TrendAnalyzer.detect_anomalies()` method decides whether a data point is anomalous.

```mermaid
flowchart TD
    DP[Data Point] --> ZSCORE[Compute z-score<br/>from rolling mean/std]
    ZSCORE --> ZC{abs(z) > threshold?}
    ZC -->|no| IQR[Compute IQR bounds]
    IQR --> IQC{outside Q1-1.5IQR<br/>or Q3+1.5IQR?}
    IQC -->|no| Normal[Mark Normal]
    IQC -->|yes| Anomaly[Mark Anomaly]
    ZC -->|yes| Anomaly
    Anomaly --> Ctx{Check contextual<br/>metadata filter?}
    Ctx -->|passes| Flag[Flag as Anomaly]
    Ctx -->|filtered| Normal
```

## Data Flow Diagram

```mermaid
flowchart LR
    subgraph DataLayer["Data Layer"]
        D1[(Raw Events)]
        D2[(Pattern Store)]
        D3[(Metric Store)]
        D4[(Model Registry)]
        D5[(Feedback Store)]
    end

    subgraph Processing["Processing"]
        P1[Pattern Engine]
        P2[Trend Analyzer]
        P3[Feature Extractor]
        P4[Model Trainer]
        P5[Feedback Learner]
    end

    D1 --> P1
    P1 --> D2
    D2 --> P2
    D2 --> P3
    D1 --> P2
    P2 --> D3
    P3 --> P4
    P4 --> D4
    P5 --> D4
    D5 --> P5
    P4 --> P5
    P1 --> P5
    P5 --> P1
```