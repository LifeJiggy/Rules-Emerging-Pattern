"""Model training module for supervised and unsupervised learning."""
import copy
import json
import logging
import math
import os
import pickle
import statistics
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple, Set, Callable, Iterator

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RulePattern

logger = logging.getLogger(__name__)


class ModelType(Enum):
    THRESHOLD = "threshold"
    WEIGHTED = "weighted"
    ENSEMBLE = "ensemble"
    BOOSTING = "boosting"
    BAGGING = "bagging"
    STACKING = "stacking"


class ModelStatus(Enum):
    TRAINING = "training"
    READY = "ready"
    EVALUATING = "evaluating"
    DEPLOYED = "deployed"
    DEPRECATED = "deprecated"
    FAILED = "failed"


class SplitMethod(Enum):
    RANDOM = "random"
    STRATIFIED = "stratified"
    TEMPORAL = "temporal"
    K_FOLD = "k_fold"


class MetricType(Enum):
    ACCURACY = "accuracy"
    PRECISION = "precision"
    RECALL = "recall"
    F1 = "f1"
    F05 = "f0.5"
    F2 = "f2"
    ROC_AUC = "roc_auc"
    LOG_LOSS = "log_loss"
    MATTHEWS_CC = "matthews_cc"
    COHENS_KAPPA = "cohens_kappa"


@dataclass
class TrainerConfig:
    test_split: float = 0.2
    validation_split: float = 0.15
    min_samples_for_training: int = 10
    max_samples_for_training: int = 100000
    default_model_type: str = "weighted"
    ensemble_method: str = "average"
    boosting_rounds: int = 10
    bagging_rounds: int = 5
    learning_rate: float = 0.1
    regularization_strength: float = 0.01
    positive_class_weight: float = 1.0
    negative_class_weight: float = 1.0
    early_stopping_rounds: int = 5
    early_stopping_threshold: float = 0.001
    random_seed: int = 42
    enable_cross_validation: bool = True
    cv_folds: int = 5
    save_best_model: bool = True
    max_models_per_type: int = 10
    auto_versioning: bool = True
    version_metadata: bool = True
    persist_directory: str = ""
    evaluation_batch_size: int = 1000


@dataclass
class TrainingExample:
    features: Dict[str, float]
    label: Any
    weight: float = 1.0
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    prediction: Optional[Any] = None
    prediction_score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Dataset:
    examples: List[TrainingExample]
    name: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> TrainingExample:
        return self.examples[idx]

    def shuffle(self, seed: Optional[int] = None) -> 'Dataset':
        import random
        rng = random.Random(seed)
        shuffled = list(self.examples)
        rng.shuffle(shuffled)
        return Dataset(examples=shuffled, name=self.name, metadata=self.metadata)

    def split_by_label(self) -> Dict[Any, List[TrainingExample]]:
        result: Dict[Any, List[TrainingExample]] = defaultdict(list)
        for ex in self.examples:
            result[ex.label].append(ex)
        return dict(result)

    def get_label_distribution(self) -> Dict[Any, int]:
        return dict(Counter(ex.label for ex in self.examples))

    def get_feature_names(self) -> List[str]:
        names: Set[str] = set()
        for ex in self.examples:
            names.update(ex.features.keys())
        return sorted(names)

    def filter_by_label(self, label: Any) -> 'Dataset':
        return Dataset(
            examples=[ex for ex in self.examples if ex.label == label],
            name=f"{self.name}_filtered_{label}",
            metadata=self.metadata
        )

    def sample(self, n: int, seed: Optional[int] = None) -> 'Dataset':
        import random
        rng = random.Random(seed)
        sampled = rng.sample(self.examples, min(n, len(self.examples)))
        return Dataset(examples=sampled, name=f"{self.name}_sampled", metadata=self.metadata)


@dataclass
class ModelMetrics:
    model_id: str
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    f05_score: float = 0.0
    f2_score: float = 0.0
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0
    total_samples: int = 0
    roc_auc: float = 0.0
    log_loss: float = float('inf')
    matthews_cc: float = 0.0
    cohens_kappa: float = 0.0
    average_precision: float = 0.0
    training_time_ms: float = 0.0
    evaluation_time_ms: float = 0.0
    evaluated_at: datetime = field(default_factory=datetime.now)
    threshold: float = 0.5
    class_metrics: Dict[str, Dict[str, float]] = field(default_factory=dict)
    confusion_matrix: List[List[int]] = field(default_factory=list)

    def to_summary(self) -> Dict:
        return {
            'model_id': self.model_id,
            'accuracy': round(self.accuracy, 4),
            'precision': round(self.precision, 4),
            'recall': round(self.recall, 4),
            'f1': round(self.f1_score, 4),
            'f05': round(self.f05_score, 4),
            'f2': round(self.f2_score, 4),
            'roc_auc': round(self.roc_auc, 4),
            'matthews_cc': round(self.matthews_cc, 4),
            'total_samples': self.total_samples,
            'threshold': self.threshold,
            'training_time_ms': round(self.training_time_ms, 2),
        }

    def is_better_than(self, other: 'ModelMetrics', metric: str = 'f1_score') -> bool:
        current = getattr(self, metric, 0.0)
        previous = getattr(other, metric, 0.0)
        return current > previous


@dataclass
class ModelVersion:
    version_id: str
    model_id: str
    version_number: int
    model_type: str
    metrics: ModelMetrics
    training_samples: int
    feature_names: List[str]
    created_at: datetime = field(default_factory=datetime.now)
    file_path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: ModelStatus = ModelStatus.READY
    tags: List[str] = field(default_factory=list)
    parent_version_id: Optional[str] = None
    training_config: Dict[str, Any] = field(default_factory=dict)

    def get_summary(self) -> Dict:
        return {
            'version_id': self.version_id,
            'model_id': self.model_id,
            'version': self.version_number,
            'model_type': self.model_type,
            'metrics': self.metrics.to_summary(),
            'training_samples': self.training_samples,
            'feature_count': len(self.feature_names),
            'created_at': self.created_at.isoformat(),
            'status': self.status.value,
            'tags': self.tags,
        }


class BaseModel:
    def __init__(self, model_id: str, model_type: ModelType):
        self.model_id = model_id
        self.model_type = model_type
        self.feature_names: List[str] = []
        self.is_fitted: bool = False
        self.training_count: int = 0

    def fit(self, dataset: Dataset) -> ModelMetrics:
        raise NotImplementedError

    def predict(self, features: Dict[str, float]) -> Tuple[Any, float]:
        raise NotImplementedError

    def predict_batch(self, examples: List[Dict[str, float]]) -> List[Tuple[Any, float]]:
        return [self.predict(f) for f in examples]

    def get_params(self) -> Dict:
        return {'model_id': self.model_id, 'model_type': self.model_type.value,
                'is_fitted': self.is_fitted, 'training_count': self.training_count}


class ThresholdModel(BaseModel):
    def __init__(self, model_id: str, threshold: float = 0.5,
                 pos_label: Any = True, neg_label: Any = False):
        super().__init__(model_id, ModelType.THRESHOLD)
        self.threshold = threshold
        self.pos_label = pos_label
        self.neg_label = neg_label
        self.feature_weights: Dict[str, float] = {}
        self.bias: float = 0.0
        self.optimal_threshold: float = threshold
        self.positive_ratio: float = 0.5
        self.label_map: Dict[Any, float] = {}

    def fit(self, dataset: Dataset) -> ModelMetrics:
        start_time = time.time() * 1000
        self.feature_names = dataset.get_feature_names()
        self.training_count += 1
        labels = [ex.label for ex in dataset.examples]
        unique_labels = set(labels)
        if len(unique_labels) == 2:
            self.label_map = {l: i for i, l in enumerate(sorted(unique_labels))}
        elif len(unique_labels) == 1:
            label = next(iter(unique_labels))
            self.label_map = {label: 1.0}
        else:
            for i, l in enumerate(sorted(unique_labels)):
                self.label_map[l] = float(i)
        feature_values: Dict[str, List[float]] = defaultdict(list)
        label_values: List[float] = []
        for ex in dataset.examples:
            mapped = self.label_map.get(ex.label, 0.0)
            label_values.append(mapped)
            for name, value in ex.features.items():
                feature_values[name].append(value)
        self.positive_ratio = statistics.mean(label_values) if label_values else 0.5
        for name, values in feature_values.items():
            if len(values) < 2:
                self.feature_weights[name] = 0.0
                continue
            try:
                pos_vals = [v for v, l in zip(values, label_values) if l > 0.5]
                neg_vals = [v for v, l in zip(values, label_values) if l <= 0.5]
                if pos_vals and neg_vals:
                    pos_mean = statistics.mean(pos_vals)
                    neg_mean = statistics.mean(neg_vals)
                    self.feature_weights[name] = pos_mean - neg_mean
                else:
                    self.feature_weights[name] = 0.0
            except statistics.StatisticsError:
                self.feature_weights[name] = 0.0
        if self.feature_weights:
            max_weight = max(abs(w) for w in self.feature_weights.values()) or 1.0
            for name in self.feature_weights:
                self.feature_weights[name] /= max_weight
        self.bias = 0.0
        scores = self.predict_batch([ex.features for ex in dataset.examples])
        predictions = [s[0] for s in scores]
        elapsed = time.time() * 1000 - start_time
        metrics = self._evaluate(labels, predictions, scores)
        metrics.training_time_ms = elapsed
        self.is_fitted = True
        self._optimize_threshold(dataset)
        logger.info(f"ThresholdModel[{self.model_id}] trained: F1={metrics.f1_score:.4f}")
        return metrics

    def predict(self, features: Dict[str, float]) -> Tuple[Any, float]:
        if not self.is_fitted:
            return self.neg_label, 0.5
        score = self.bias
        for name, weight in self.feature_weights.items():
            score += weight * features.get(name, 0.0)
        score = 1.0 / (1.0 + math.exp(-score))
        prediction = self.pos_label if score >= self.optimal_threshold else self.neg_label
        return prediction, score

    def _optimize_threshold(self, dataset: Dataset) -> None:
        scores = self.predict_batch([ex.features for ex in dataset.examples])
        labels = [ex.label for ex in dataset.examples]
        label_map = {l: i for i, l in enumerate(sorted(set(labels)))} if len(set(labels)) > 1 else {labels[0]: 0}
        thresholds = [i / 100.0 for i in range(5, 96, 5)]
        best_f1 = 0.0
        best_threshold = self.optimal_threshold
        for t in thresholds:
            preds = [self.pos_label if s[1] >= t else self.neg_label for s in scores]
            tp = sum(1 for p, l in zip(preds, labels) if p == self.pos_label and l == self.pos_label)
            fp = sum(1 for p, l in zip(preds, labels) if p == self.pos_label and l == self.neg_label)
            fn = sum(1 for p, l in zip(preds, labels) if p == self.neg_label and l == self.pos_label)
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
            if f1 > best_f1:
                best_f1 = f1
                best_threshold = t
        self.optimal_threshold = best_threshold

    def _evaluate(self, true_labels: List[Any], predictions: List[Any],
                  scores: List[Tuple[Any, float]]) -> ModelMetrics:
        metrics = ModelMetrics(model_id=self.model_id)
        metrics.total_samples = len(true_labels)
        tp = sum(1 for p, l in zip(predictions, true_labels) if p == self.pos_label and l == self.pos_label)
        fp = sum(1 for p, l in zip(predictions, true_labels) if p == self.pos_label and l == self.neg_label)
        tn = sum(1 for p, l in zip(predictions, true_labels) if p == self.neg_label and l == self.neg_label)
        fn = sum(1 for p, l in zip(predictions, true_labels) if p == self.neg_label and l == self.pos_label)
        metrics.true_positives = tp
        metrics.false_positives = fp
        metrics.true_negatives = tn
        metrics.false_negatives = fn
        metrics.accuracy = (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) > 0 else 0.0
        metrics.precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        metrics.recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        metrics.f1_score = (2 * metrics.precision * metrics.recall /
                            (metrics.precision + metrics.recall)) if (metrics.precision + metrics.recall) > 0 else 0.0
        if metrics.precision + metrics.recall > 0:
            metrics.f05_score = ((1 + 0.25) * metrics.precision * metrics.recall /
                                 (0.25 * metrics.precision + metrics.recall))
            metrics.f2_score = ((1 + 4) * metrics.precision * metrics.recall /
                                (4 * metrics.precision + metrics.recall))
        metrics.matthews_cc = ((tp * tn) - (fp * fn)) / math.sqrt(
            (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
        ) if (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn) > 0 else 0.0
        metrics.threshold = self.optimal_threshold
        metrics.confusion_matrix = [[int(tn), int(fp)], [int(fn), int(tp)]]
        pred_probs = [s[1] for s in scores]
        log_loss = 0.0
        for i, (prob, label) in enumerate(zip(pred_probs, true_labels)):
            true_val = 1.0 if label == self.pos_label else 0.0
            prob = max(1e-15, min(1 - 1e-15, prob))
            log_loss += true_val * math.log(prob) + (1 - true_val) * math.log(1 - prob)
        metrics.log_loss = -log_loss / len(true_labels) if true_labels else float('inf')
        return metrics


class WeightedModel(BaseModel):
    def __init__(self, model_id: str):
        super().__init__(model_id, ModelType.WEIGHTED)
        self.feature_weights: Dict[str, float] = {}
        self.class_weights: Dict[Any, float] = {}
        self.bias: float = 0.0
        self.learning_rate: float = 0.01
        self.regularization: float = 0.001
        self.iterations: int = 100
        self.classes: List[Any] = []

    def fit(self, dataset: Dataset) -> ModelMetrics:
        start_time = time.time() * 1000
        self.feature_names = dataset.get_feature_names()
        self.training_count += 1
        labels = [ex.label for ex in dataset.examples]
        self.classes = sorted(set(labels))
        for cls in self.classes:
            cls_count = sum(1 for l in labels if l == cls)
            self.class_weights[cls] = len(labels) / (len(self.classes) * cls_count) if cls_count > 0 else 1.0
        for name in self.feature_names:
            self.feature_weights[name] = 0.0
        self.bias = 0.0
        for iteration in range(self.iterations):
            total_loss = 0.0
            for ex in dataset.examples:
                score = self.bias
                for name, weight in self.feature_weights.items():
                    score += weight * ex.features.get(name, 0.0)
                target = 1.0 if ex.label == self.classes[-1] else 0.0
                prob = 1.0 / (1.0 + math.exp(-max(-30, min(30, score))))
                error = prob - target
                weight_mult = ex.weight * self.class_weights.get(ex.label, 1.0)
                self.bias -= self.learning_rate * error * weight_mult
                for name in self.feature_weights:
                    grad = error * ex.features.get(name, 0.0) * weight_mult
                    reg = self.regularization * self.feature_weights[name]
                    self.feature_weights[name] -= self.learning_rate * (grad + reg)
                total_loss += -target * math.log(max(1e-15, prob)) - (1 - target) * math.log(max(1e-15, 1 - prob))
            if iteration > 0 and iteration % 20 == 0:
                self.learning_rate *= 0.95
        self.is_fitted = True
        scores = self.predict_batch([ex.features for ex in dataset.examples])
        predictions = [s[0] for s in scores]
        elapsed = time.time() * 1000 - start_time
        metrics = self._compute_metrics(labels, predictions, scores)
        metrics.training_time_ms = elapsed
        logger.info(f"WeightedModel[{self.model_id}] trained: F1={metrics.f1_score:.4f}")
        return metrics

    def predict(self, features: Dict[str, float]) -> Tuple[Any, float]:
        if not self.is_fitted:
            return self.classes[-1] if self.classes else None, 0.5
        score = self.bias
        for name, weight in self.feature_weights.items():
            score += weight * features.get(name, 0.0)
        prob = 1.0 / (1.0 + math.exp(-max(-30, min(30, score))))
        prediction = self.classes[-1] if prob >= 0.5 else self.classes[0] if self.classes else None
        return prediction, prob

    def _compute_metrics(self, true_labels: List[Any], predictions: List[Any],
                         scores: List[Tuple[Any, float]]) -> ModelMetrics:
        metrics = ModelMetrics(model_id=self.model_id)
        metrics.total_samples = len(true_labels)
        pos_cls = self.classes[-1] if self.classes else None
        neg_cls = self.classes[0] if len(self.classes) > 1 else None
        if pos_cls is None:
            return metrics
        tp = sum(1 for p, l in zip(predictions, true_labels) if p == pos_cls and l == pos_cls)
        fp = sum(1 for p, l in zip(predictions, true_labels) if p == pos_cls and l != pos_cls)
        tn = sum(1 for p, l in zip(predictions, true_labels) if p != pos_cls and l != pos_cls)
        fn = sum(1 for p, l in zip(predictions, true_labels) if p != pos_cls and l == pos_cls)
        metrics.true_positives = tp
        metrics.false_positives = fp
        metrics.true_negatives = tn
        metrics.false_negatives = fn
        metrics.accuracy = (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) > 0 else 0.0
        metrics.precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        metrics.recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        metrics.f1_score = (2 * metrics.precision * metrics.recall /
                            (metrics.precision + metrics.recall)) if (metrics.precision + metrics.recall) > 0 else 0.0
        pred_probs = [s[1] for s in scores]
        log_loss = 0.0
        for i, (prob, label) in enumerate(zip(pred_probs, true_labels)):
            true_val = 1.0 if label == pos_cls else 0.0
            prob = max(1e-15, min(1 - 1e-15, prob))
            log_loss += true_val * math.log(prob) + (1 - true_val) * math.log(1 - prob)
        metrics.log_loss = -log_loss / len(true_labels) if true_labels else float('inf')
        metrics.confusion_matrix = [[int(tn), int(fp)], [int(fn), int(tp)]]
        return metrics

    def get_params(self) -> Dict:
        return {**super().get_params(), 'learning_rate': self.learning_rate,
                'regularization': self.regularization, 'iterations': self.iterations,
                'classes': self.classes}


class EnsembleModel(BaseModel):
    def __init__(self, model_id: str, method: str = "average"):
        super().__init__(model_id, ModelType.ENSEMBLE)
        self.method = method
        self.base_models: List[BaseModel] = []
        self.model_weights: List[float] = []
        self.voting: str = "soft"

    def add_model(self, model: BaseModel, weight: float = 1.0) -> None:
        self.base_models.append(model)
        self.model_weights.append(weight)

    def fit(self, dataset: Dataset) -> ModelMetrics:
        start_time = time.time() * 1000
        self.feature_names = dataset.get_feature_names()
        self.training_count += 1
        metrics_list = []
        for i, model in enumerate(self.base_models):
            try:
                m = model.fit(dataset)
                metrics_list.append(m)
            except Exception as e:
                logger.warning(f"Ensemble base model {i} failed: {e}")
                self.model_weights[i] = 0.0
        total_weight = sum(self.model_weights) or 1.0
        self.model_weights = [w / total_weight for w in self.model_weights]
        self.is_fitted = True
        labels = [ex.label for ex in dataset.examples]
        scores = self.predict_batch([ex.features for ex in dataset.examples])
        predictions = [s[0] for s in scores]
        elapsed = time.time() * 1000 - start_time
        metrics = self._ensemble_metrics(labels, predictions, scores)
        metrics.training_time_ms = elapsed
        logger.info(f"EnsembleModel[{self.model_id}] trained: F1={metrics.f1_score:.4f}")
        return metrics

    def predict(self, features: Dict[str, float]) -> Tuple[Any, float]:
        if not self.is_fitted or not self.base_models:
            return None, 0.5
        if self.voting == "soft":
            weighted_sum = 0.0
            total_weight = 0.0
            predictions = []
            for model, weight in zip(self.base_models, self.model_weights):
                if weight <= 0:
                    continue
                try:
                    pred, score = model.predict(features)
                    weighted_sum += score * weight
                    total_weight += weight
                    predictions.append((pred, score))
                except Exception:
                    continue
            if total_weight <= 0:
                return None, 0.5
            avg_score = weighted_sum / total_weight
            pos_preds = sum(1 for p, _ in predictions if p is not None and bool(p))
            majority = pos_preds > len(predictions) / 2
            return majority, avg_score
        else:
            predictions = []
            for model, weight in zip(self.base_models, self.model_weights):
                if weight <= 0:
                    continue
                try:
                    pred, _ = model.predict(features)
                    predictions.append(pred)
                except Exception:
                    continue
            if not predictions:
                return None, 0.5
            counter = Counter(predictions)
            return counter.most_common(1)[0][0], counter.most_common(1)[1] / len(predictions)

    def _ensemble_metrics(self, true_labels: List[Any], predictions: List[Any],
                          scores: List[Tuple[Any, float]]) -> ModelMetrics:
        metrics = ModelMetrics(model_id=self.model_id)
        metrics.total_samples = len(true_labels)
        pos_cls = True
        tp = sum(1 for p, l in zip(predictions, true_labels) if bool(p) and bool(l))
        fp = sum(1 for p, l in zip(predictions, true_labels) if bool(p) and not bool(l))
        tn = sum(1 for p, l in zip(predictions, true_labels) if not bool(p) and not bool(l))
        fn = sum(1 for p, l in zip(predictions, true_labels) if not bool(p) and bool(l))
        metrics.true_positives = tp
        metrics.false_positives = fp
        metrics.true_negatives = tn
        metrics.false_negatives = fn
        metrics.accuracy = (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) > 0 else 0.0
        metrics.precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        metrics.recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        metrics.f1_score = (2 * metrics.precision * metrics.recall /
                            (metrics.precision + metrics.recall)) if (metrics.precision + metrics.recall) > 0 else 0.0
        metrics.confusion_matrix = [[int(tn), int(fp)], [int(fn), int(tp)]]
        return metrics

    def get_params(self) -> Dict:
        return {**super().get_params(), 'method': self.method, 'voting': self.voting,
                'num_models': len(self.base_models), 'model_weights': self.model_weights}


class ModelTrainer:
    def __init__(self, config: Optional[TrainerConfig] = None):
        self.config = config or TrainerConfig()
        self.examples: List[TrainingExample] = []
        self.models: Dict[str, BaseModel] = {}
        self.model_metrics: Dict[str, ModelMetrics] = {}
        self.model_versions: Dict[str, List[ModelVersion]] = defaultdict(list)
        self.version_counter: Dict[str, int] = defaultdict(int)
        self.training_history: List[Dict] = []
        self.latest_metrics: Dict[str, ModelMetrics] = {}
        self.datasets: Dict[str, Dataset] = {}
        self._rng_state: Optional[int] = None
        logger.info(f"ModelTrainer initialized (model_type={self.config.default_model_type})")

    def add_example(self, features: Dict[str, float], label: Any, weight: float = 1.0,
                    source: str = "", metadata: Optional[Dict] = None) -> TrainingExample:
        ex = TrainingExample(
            features=features, label=label, weight=weight,
            source=source, metadata=metadata or {}
        )
        self.examples.append(ex)
        return ex

    def add_examples_batch(self, feature_list: List[Dict[str, float]], labels: List[Any],
                           weights: Optional[List[float]] = None) -> List[TrainingExample]:
        if weights is None:
            weights = [1.0] * len(feature_list)
        examples = []
        for feats, label, weight in zip(feature_list, labels, weights):
            ex = self.add_example(feats, label, weight)
            examples.append(ex)
        return examples

    def create_dataset(self, examples: Optional[List[TrainingExample]] = None,
                       name: str = "", split: bool = True) -> Tuple[Dataset, Dataset, Dataset]:
        if examples is None:
            examples = self.examples
        if not examples:
            return Dataset([]), Dataset([]), Dataset([])
        if not name:
            name = f"dataset_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        full = self._stratified_split(examples) if split else (examples, [], [])
        train_ex, val_ex, test_ex = full
        train_ds = Dataset(examples=train_ex, name=f"{name}_train")
        val_ds = Dataset(examples=val_ex, name=f"{name}_validation")
        test_ds = Dataset(examples=test_ex, name=f"{name}_test")
        self.datasets[train_ds.name] = train_ds
        self.datasets[val_ds.name] = val_ds
        self.datasets[test_ds.name] = test_ds
        logger.info(f"Created dataset '{name}': train={len(train_ex)}, val={len(val_ex)}, test={len(test_ex)}")
        return train_ds, val_ds, test_ds

    def _stratified_split(self, examples: List[TrainingExample]) -> Tuple[List[TrainingExample],
                                                                          List[TrainingExample],
                                                                          List[TrainingExample]]:
        import random
        random.seed(self.config.random_seed)
        labels = list(set(ex.label for ex in examples))
        label_examples: Dict[Any, List[TrainingExample]] = {l: [] for l in labels}
        for ex in examples:
            label_examples[ex.label].append(ex)
        train, val, test = [], [], []
        val_ratio = self.config.validation_split
        test_ratio = self.config.test_split
        for label, exs in label_examples.items():
            random.shuffle(exs)
            n = len(exs)
            n_test = max(1, int(n * test_ratio))
            n_val = max(1, int(n * val_ratio))
            n_train = n - n_test - n_val
            if n_train <= 0:
                train.extend(exs[:max(1, n // 2)])
                val.extend([])
                test.extend(exs[max(1, n // 2):])
            else:
                train.extend(exs[:n_train])
                val.extend(exs[n_train:n_train + n_val])
                test.extend(exs[n_train + n_val:])
        random.shuffle(train)
        random.shuffle(val)
        random.shuffle(test)
        return train, val, test

    def create_model(self, model_id: Optional[str] = None,
                     model_type: Optional[str] = None) -> BaseModel:
        if model_id is None:
            model_id = f"model_{uuid.uuid4().hex[:8]}"
        if model_type is None:
            model_type = self.config.default_model_type
        if model_type == ModelType.THRESHOLD.value or model_type == "threshold":
            model = ThresholdModel(model_id)
        elif model_type == ModelType.WEIGHTED.value or model_type == "weighted":
            model = WeightedModel(model_id)
        elif model_type == ModelType.ENSEMBLE.value or model_type == "ensemble":
            model = EnsembleModel(model_id)
        else:
            model = WeightedModel(model_id)
        self.models[model_id] = model
        logger.info(f"Created model: {model_id} ({model_type})")
        return model

    def train(self, model_id: str, dataset: Optional[Dataset] = None,
              validation_set: Optional[Dataset] = None) -> ModelMetrics:
        if model_id not in self.models:
            raise ValueError(f"Model {model_id} not found. Create it first.")
        model = self.models[model_id]
        if dataset is None:
            train_ds, val_ds, _ = self.create_dataset()
        else:
            train_ds = dataset
            val_ds = validation_set or dataset
        if len(train_ds) < self.config.min_samples_for_training:
            logger.warning(f"Too few training samples: {len(train_ds)} < {self.config.min_samples_for_training}")
            metrics = ModelMetrics(model_id=model_id)
            return metrics
        metrics = model.fit(train_ds)
        self.model_metrics[model_id] = metrics
        self.latest_metrics[model_id] = metrics
        if val_ds and len(val_ds) > 0:
            val_metrics = self.evaluate(model_id, val_ds)
            metrics.evaluation_time_ms = val_metrics.evaluation_time_ms
        if self.config.auto_versioning:
            self._save_version(model_id, metrics, len(train_ds))
        self.training_history.append({
            'model_id': model_id,
            'timestamp': datetime.now(),
            'train_samples': len(train_ds),
            'val_samples': len(val_ds) if val_ds else 0,
            'accuracy': metrics.accuracy,
            'f1_score': metrics.f1_score,
            'training_time_ms': metrics.training_time_ms,
        })
        return metrics

    def _save_version(self, model_id: str, metrics: ModelMetrics, num_samples: int) -> ModelVersion:
        self.version_counter[model_id] += 1
        version_num = self.version_counter[model_id]
        model = self.models.get(model_id)
        version_id = f"{model_id}_v{version_num}"
        version = ModelVersion(
            version_id=version_id,
            model_id=model_id,
            version_number=version_num,
            model_type=model.model_type.value if model else "unknown",
            metrics=metrics,
            training_samples=num_samples,
            feature_names=model.feature_names if model and model.is_fitted else [],
            training_config={
                'learning_rate': self.config.learning_rate,
                'regularization_strength': self.config.regularization_strength,
                'model_type': self.config.default_model_type,
            }
        )
        if self.config.persist_directory:
            version.file_path = self._persist_model(model_id, version_id)
        self.model_versions[model_id].append(version)
        self._enforce_version_limits(model_id)
        return version

    def _enforce_version_limits(self, model_id: str) -> None:
        if model_id not in self.model_versions:
            return
        versions = self.model_versions[model_id]
        if len(versions) > self.config.max_models_per_type:
            versions.sort(key=lambda v: (v.metrics.f1_score, v.version_number), reverse=True)
            keep = versions[:self.config.max_models_per_type]
            for v in versions[self.config.max_models_per_type:]:
                if v.file_path and os.path.exists(v.file_path):
                    try:
                        os.remove(v.file_path)
                    except OSError:
                        pass
            self.model_versions[model_id] = keep

    def evaluate(self, model_id: str, dataset: Dataset) -> ModelMetrics:
        if model_id not in self.models:
            raise ValueError(f"Model {model_id} not found")
        model = self.models[model_id]
        start_time = time.time() * 1000
        labels = [ex.label for ex in dataset.examples]
        scores = model.predict_batch([ex.features for ex in dataset.examples])
        predictions = [s[0] for s in scores]
        elapsed = time.time() * 1000 - start_time
        if isinstance(model, ThresholdModel):
            metrics = model._evaluate(labels, predictions, scores)
        elif isinstance(model, WeightedModel):
            metrics = model._compute_metrics(labels, predictions, scores)
        elif isinstance(model, EnsembleModel):
            metrics = model._ensemble_metrics(labels, predictions, scores)
        else:
            metrics = self._compute_generic_metrics(labels, predictions, scores, model_id)
        metrics.evaluation_time_ms = elapsed
        logger.info(f"Evaluated {model_id}: accuracy={metrics.accuracy:.4f}, F1={metrics.f1_score:.4f}")
        return metrics

    def _compute_generic_metrics(self, true_labels: List[Any], predictions: List[Any],
                                  scores: List[Tuple[Any, float]], model_id: str) -> ModelMetrics:
        metrics = ModelMetrics(model_id=model_id)
        metrics.total_samples = len(true_labels)
        correct = sum(1 for p, l in zip(predictions, true_labels) if p == l)
        metrics.accuracy = correct / len(true_labels) if true_labels else 0.0
        return metrics

    def predict(self, model_id: str, features: Dict[str, float]) -> Tuple[Any, float]:
        if model_id not in self.models:
            raise ValueError(f"Model {model_id} not found")
        return self.models[model_id].predict(features)

    def predict_batch(self, model_id: str, feature_list: List[Dict[str, float]]) -> List[Tuple[Any, float]]:
        if model_id not in self.models:
            raise ValueError(f"Model {model_id} not found")
        return self.models[model_id].predict_batch(feature_list)

    def cross_validate(self, model_id: str, dataset: Optional[Dataset] = None,
                       folds: int = 5) -> Dict:
        if dataset is None:
            _, _, examples = self.create_dataset(split=False)
            dataset = examples if isinstance(examples, Dataset) else Dataset(examples)
        if len(dataset) < folds:
            logger.warning(f"Too few samples for {folds}-fold CV: {len(dataset)}")
            return {'error': 'insufficient_samples', 'folds': folds, 'samples': len(dataset)}
        import random
        random.seed(self.config.random_seed)
        indices = list(range(len(dataset)))
        random.shuffle(indices)
        fold_size = len(indices) // folds
        fold_metrics = []
        for fold in range(folds):
            test_start = fold * fold_size
            test_end = test_start + fold_size if fold < folds - 1 else len(indices)
            test_idx = indices[test_start:test_end]
            train_idx = indices[:test_start] + indices[test_end:]
            train_exs = [dataset[i] for i in train_idx]
            test_exs = [dataset[i] for i in test_idx]
            train_ds = Dataset(examples=train_exs, name=f"cv_{fold}_train")
            test_ds = Dataset(examples=test_exs, name=f"cv_{fold}_test")
            model = self.create_model(f"{model_id}_cv{fold}")
            model.fit(train_ds)
            m = self.evaluate(model.model_id, test_ds)
            fold_metrics.append(m)
        avg_metrics = ModelMetrics(model_id=model_id)
        avg_metrics.accuracy = statistics.mean(m.accuracy for m in fold_metrics) if fold_metrics else 0.0
        avg_metrics.precision = statistics.mean(m.precision for m in fold_metrics) if fold_metrics else 0.0
        avg_metrics.recall = statistics.mean(m.recall for m in fold_metrics) if fold_metrics else 0.0
        avg_metrics.f1_score = statistics.mean(m.f1_score for m in fold_metrics) if fold_metrics else 0.0
        fold_summaries = [m.to_summary() for m in fold_metrics]
        logger.info(f"Cross-validation ({folds} folds): avg F1={avg_metrics.f1_score:.4f}")
        return {'average_metrics': avg_metrics.to_summary(), 'folds': fold_summaries}

    def get_best_model(self, metric: str = 'f1_score') -> Optional[str]:
        best_id = None
        best_val = float('-inf')
        for mid, metrics in self.model_metrics.items():
            val = getattr(metrics, metric, 0.0)
            if val > best_val:
                best_val = val
                best_id = mid
        return best_id

    def save_model(self, model_id: str, filepath: str) -> str:
        if model_id not in self.models:
            raise ValueError(f"Model {model_id} not found")
        model = self.models[model_id]
        data = {
            'model': pickle.dumps(model),
            'metrics': self.model_metrics.get(model_id),
            'versions': self.model_versions.get(model_id, []),
            'saved_at': datetime.now().isoformat(),
        }
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'wb') as f:
            pickle.dump(data, f)
        logger.info(f"Saved model {model_id} to {filepath}")
        return filepath

    def load_model(self, filepath: str) -> str:
        with open(filepath, 'rb') as f:
            data = pickle.load(f)
        model = pickle.loads(data['model']) if isinstance(data['model'], bytes) else data['model']
        self.models[model.model_id] = model
        if data.get('metrics'):
            self.model_metrics[model.model_id] = data['metrics']
        if data.get('versions'):
            self.model_versions[model.model_id] = data['versions']
        logger.info(f"Loaded model {model.model_id} from {filepath}")
        return model.model_id

    def _persist_model(self, model_id: str, version_id: str) -> str:
        directory = self.config.persist_directory or os.path.join(
            os.getcwd(), '.models'
        )
        os.makedirs(directory, exist_ok=True)
        filepath = os.path.join(directory, f"{version_id}.pkl")
        self.save_model(model_id, filepath)
        return filepath

    def get_model_versions(self, model_id: str) -> List[ModelVersion]:
        return self.model_versions.get(model_id, [])

    def get_best_version(self, model_id: str) -> Optional[ModelVersion]:
        versions = self.model_versions.get(model_id, [])
        if not versions:
            return None
        return max(versions, key=lambda v: v.metrics.f1_score)

    def get_training_history(self, model_id: Optional[str] = None) -> List[Dict]:
        if model_id:
            return [h for h in self.training_history if h['model_id'] == model_id]
        return self.training_history

    def export_model_data(self, model_id: str) -> Dict:
        model = self.models.get(model_id)
        metrics = self.model_metrics.get(model_id)
        versions = self.model_versions.get(model_id, [])
        return {
            'model_id': model_id,
            'model_type': model.model_type.value if model else None,
            'is_fitted': model.is_fitted if model else False,
            'metrics': metrics.to_summary() if metrics else None,
            'versions': [v.get_summary() for v in versions],
            'params': model.get_params() if model else {},
        }

    def get_statistics(self) -> Dict:
        model_summaries = {}
        for mid, model in self.models.items():
            metrics = self.model_metrics.get(mid)
            model_summaries[mid] = {
                'type': model.model_type.value,
                'is_fitted': model.is_fitted,
                'training_count': model.training_count,
                'feature_count': len(model.feature_names),
                'metrics': metrics.to_summary() if metrics else None,
                'versions': len(self.model_versions.get(mid, [])),
            }
        return {
            'total_examples': len(self.examples),
            'total_models': len(self.models),
            'total_training_runs': len(self.training_history),
            'total_datasets': len(self.datasets),
            'models': model_summaries,
            'config': {
                'test_split': self.config.test_split,
                'validation_split': self.config.validation_split,
                'model_type': self.config.default_model_type,
                'min_samples': self.config.min_samples_for_training,
                'learning_rate': self.config.learning_rate,
                'regularization': self.config.regularization_strength,
                'auto_versioning': self.config.auto_versioning,
                'cv_folds': self.config.cv_folds,
            }
        }

    def reset(self) -> None:
        self.examples.clear()
        self.models.clear()
        self.model_metrics.clear()
        self.model_versions.clear()
        self.version_counter.clear()
        self.training_history.clear()
        self.latest_metrics.clear()
        self.datasets.clear()
        logger.info("ModelTrainer reset")
