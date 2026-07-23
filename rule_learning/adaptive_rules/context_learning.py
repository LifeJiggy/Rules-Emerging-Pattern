"""Context learning engine for adaptive rule evaluation.

Provides context extraction, classification, and learning capabilities
to adapt rule behavior based on interaction context.
"""

import json
import logging
import math
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from rules_emerging_pattern.models.rule import Rule, RuleContext, RuleType

logger = logging.getLogger(__name__)


class LearningMode(str, Enum):
    """Supported context learning modes."""
    SUPERVISED = "supervised"
    UNSUPERVISED = "unsupervised"
    SEMI_SUPERVISED = "semi_supervised"
    REINFORCEMENT = "reinforcement"


class ContextDimension(str, Enum):
    """Context dimensions available for classification."""
    DOMAIN = "domain"
    USER_ROLE = "user_role"
    CONTENT_TYPE = "content_type"
    LANGUAGE = "language"
    ORGANIZATION = "organization"
    BUSINESS_PROCESS = "business_process"
    TIME_OF_DAY = "time_of_day"
    DAY_OF_WEEK = "day_of_week"
    USER_SEGMENT = "user_segment"
    INTERACTION_TYPE = "interaction_type"


@dataclass
class ContextProfile:
    """Profile for a learned context pattern."""
    context_id: str
    dimension: ContextDimension
    label: str
    confidence: float = 0.0
    sample_count: int = 0
    features: Dict[str, float] = field(default_factory=dict)
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def update_seen(self) -> None:
        """Update the last seen timestamp to now."""
        self.last_seen = datetime.utcnow()
        self.sample_count += 1

    def age_minutes(self) -> float:
        """Get age of this profile in minutes."""
        return (datetime.utcnow() - self.first_seen).total_seconds() / 60.0


@dataclass
class InteractionRecord:
    """Record of a single interaction for context learning."""
    interaction_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    raw_features: Dict[str, Any] = field(default_factory=dict)
    context_labels: Dict[str, str] = field(default_factory=dict)
    rule_id: Optional[str] = None
    rule_triggered: bool = False
    user_action: Optional[str] = None
    outcome: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextStatistics:
    """Aggregated statistics for context learning."""
    total_interactions: int = 0
    unique_domains: int = 0
    unique_user_roles: int = 0
    unique_content_types: int = 0
    profiles_by_dimension: Dict[str, int] = field(default_factory=dict)
    learning_accuracy: float = 0.0
    classification_latency_ms: float = 0.0
    last_learning_time: Optional[datetime] = None
    mode: str = "unsupervised"
    adaptation_count: int = 0


class FeatureExtractor:
    """Extracts numerical and categorical features from interaction data."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._feature_cache: Dict[str, Dict[str, float]] = {}
        logger.info("FeatureExtractor initialized with config: %s", self.config)

    def extract(self, interaction: Dict[str, Any]) -> Dict[str, float]:
        """Extract feature vector from raw interaction data."""
        features: Dict[str, float] = {}

        try:
            interaction_id = interaction.get("id", str(uuid.uuid4()))
            if interaction_id in self._feature_cache:
                return dict(self._feature_cache[interaction_id])

            features.update(self._extract_text_features(interaction))
            features.update(self._extract_temporal_features(interaction))
            features.update(self._extract_categorical_features(interaction))
            features.update(self._extract_numerical_features(interaction))
            features.update(self._extract_behavioral_features(interaction))

            cache_enabled = self.config.get("feature_cache", True)
            if cache_enabled:
                self._feature_cache[interaction_id] = dict(features)
                max_cache = self.config.get("max_cache_size", 1000)
                if len(self._feature_cache) > max_cache:
                    oldest = next(iter(self._feature_cache))
                    del self._feature_cache[oldest]

        except Exception as exc:
            logger.error("Feature extraction failed: %s", exc, exc_info=True)
            features = self._get_default_features()

        return features

    def _extract_text_features(self, interaction: Dict[str, Any]) -> Dict[str, float]:
        """Extract features from text content."""
        features: Dict[str, float] = {}
        content = interaction.get("content", "")
        if not isinstance(content, str):
            return features
        features["content_length"] = float(len(content))
        features["word_count"] = float(len(content.split()))
        features["avg_word_length"] = (
            sum(len(w) for w in content.split()) / max(len(content.split()), 1)
        )
        features["char_diversity"] = (
            len(set(content.lower())) / max(len(content), 1)
        )
        return features

    def _extract_temporal_features(self, interaction: Dict[str, Any]) -> Dict[str, float]:
        """Extract time-based features."""
        features: Dict[str, float] = {}
        ts = interaction.get("timestamp")
        if isinstance(ts, datetime):
            features["hour_of_day"] = float(ts.hour)
            features["day_of_week"] = float(ts.weekday())
            features["day_of_month"] = float(ts.day)
            features["month"] = float(ts.month)
            features["is_weekend"] = 1.0 if ts.weekday() >= 5 else 0.0
            features["is_business_hours"] = 1.0 if 9 <= ts.hour < 17 else 0.0
        return features

    def _extract_categorical_features(self, interaction: Dict[str, Any]) -> Dict[str, float]:
        """Extract one-hot-like features from categorical fields."""
        features: Dict[str, float] = {}
        context = interaction.get("context", {})
        if isinstance(context, dict):
            for key in ("domain", "user_role", "content_type", "language"):
                val = context.get(key)
                if val:
                    feature_key = f"{key}__{str(val).lower().replace(' ', '_')}"
                    features[feature_key] = 1.0
        return features

    def _extract_numerical_features(self, interaction: Dict[str, Any]) -> Dict[str, float]:
        """Extract numeric fields from interaction."""
        features: Dict[str, float] = {}
        for key in ("priority", "threshold", "score", "confidence"):
            val = interaction.get(key)
            if isinstance(val, (int, float)):
                features[key] = float(val)
        context = interaction.get("context", {})
        if isinstance(context, dict):
            content_length = context.get("content_length")
            if isinstance(content_length, (int, float)):
                features["context_content_length"] = float(content_length)
        return features

    def _extract_behavioral_features(self, interaction: Dict[str, Any]) -> Dict[str, float]:
        """Extract features from user behavior signals."""
        features: Dict[str, float] = {}
        features["user_action_override"] = 1.0 if interaction.get("user_action") == "override" else 0.0
        features["user_action_accept"] = 1.0 if interaction.get("user_action") == "accept" else 0.0
        features["user_action_reject"] = 1.0 if interaction.get("user_action") == "reject" else 0.0
        features["rule_triggered"] = 1.0 if interaction.get("rule_triggered") else 0.0
        return features

    def _get_default_features(self) -> Dict[str, float]:
        """Return safe default feature vector on error."""
        return {
            "content_length": 0.0,
            "word_count": 0.0,
            "avg_word_length": 0.0,
            "char_diversity": 0.0,
            "is_weekend": 0.0,
            "is_business_hours": 0.0,
            "rule_triggered": 0.0,
        }

    def clear_cache(self) -> None:
        """Clear the internal feature cache."""
        self._feature_cache.clear()
        logger.debug("Feature cache cleared")


class ContextClassifier:
    """Classifies interaction context into known categories."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._profiles: Dict[str, Dict[str, ContextProfile]] = defaultdict(dict)
        self._similarity_threshold = self.config.get("similarity_threshold", 0.6)
        logger.info("ContextClassifier initialized, similarity_threshold=%.2f", self._similarity_threshold)

    def classify(
        self,
        features: Dict[str, float],
        dimension: ContextDimension,
    ) -> Tuple[str, float]:
        """Classify features into a context label for the given dimension."""
        dimension_profiles = self._profiles.get(dimension.value, {})

        if not dimension_profiles:
            return ("unknown", 0.0)

        best_label = "unknown"
        best_score = 0.0

        try:
            for label, profile in dimension_profiles.items():
                similarity = self._compute_similarity(features, profile.features)
                confidence = similarity * profile.confidence
                if confidence > best_score:
                    best_score = confidence
                    best_label = label

            if best_score < self._similarity_threshold:
                return ("unknown", best_score)

        except Exception as exc:
            logger.error("Classification failed for dimension %s: %s", dimension.value, exc)
            return ("unknown", 0.0)

        return (best_label, best_score)

    def learn(
        self,
        label: str,
        features: Dict[str, float],
        dimension: ContextDimension,
        confidence: float = 0.5,
    ) -> ContextProfile:
        """Learn or update a context profile with new features."""
        dimension_key = dimension.value
        dim_profiles = self._profiles[dimension_key]

        if label in dim_profiles:
            profile = dim_profiles[label]
            merged = self._merge_features(profile.features, features)
            profile.features = merged
            profile.confidence = min(1.0, profile.confidence + (confidence * 0.1))
            profile.update_seen()
        else:
            profile = ContextProfile(
                context_id=str(uuid.uuid4()),
                dimension=dimension,
                label=label,
                confidence=confidence,
                sample_count=1,
                features=dict(features),
            )
            dim_profiles[label] = profile

        logger.debug(
            "Learned profile for %s/%s (confidence=%.3f, samples=%d)",
            dimension_key, label, profile.confidence, profile.sample_count,
        )
        return profile

    def _compute_similarity(
        self,
        features_a: Dict[str, float],
        features_b: Dict[str, float],
    ) -> float:
        """Compute cosine similarity between two feature vectors."""
        all_keys = set(features_a) | set(features_b)
        if not all_keys:
            return 0.0

        dot_product = 0.0
        norm_a = 0.0
        norm_b = 0.0

        for key in all_keys:
            va = features_a.get(key, 0.0)
            vb = features_b.get(key, 0.0)
            dot_product += va * vb
            norm_a += va * va
            norm_b += vb * vb

        denom = math.sqrt(norm_a) * math.sqrt(norm_b)
        if denom == 0.0:
            return 0.0

        return dot_product / denom

    def _merge_features(
        self,
        existing: Dict[str, float],
        incoming: Dict[str, float],
    ) -> Dict[str, float]:
        """Merge incoming features into existing using exponential moving average."""
        alpha = self.config.get("merge_alpha", 0.3)
        merged = dict(existing)
        for key, val in incoming.items():
            if key in merged:
                merged[key] = (1.0 - alpha) * merged[key] + alpha * val
            else:
                merged[key] = val
        return merged

    def get_profile(self, dimension: ContextDimension, label: str) -> Optional[ContextProfile]:
        """Get a specific context profile."""
        return self._profiles.get(dimension.value, {}).get(label)

    def get_all_profiles(self, dimension: Optional[ContextDimension] = None) -> List[ContextProfile]:
        """Get all profiles, optionally filtered by dimension."""
        result: List[ContextProfile] = []
        dims = [dimension.value] if dimension else list(self._profiles.keys())
        for dim_key in dims:
            for profile in self._profiles.get(dim_key, {}).values():
                result.append(profile)
        return result

    def profile_count(self, dimension: Optional[ContextDimension] = None) -> int:
        """Count profiles, optionally per dimension."""
        if dimension:
            return len(self._profiles.get(dimension.value, {}))
        return sum(len(p) for p in self._profiles.values())

    def remove_profile(self, dimension: ContextDimension, label: str) -> bool:
        """Remove a profile by dimension and label."""
        dim_profiles = self._profiles.get(dimension.value, {})
        if label in dim_profiles:
            del dim_profiles[label]
            logger.info("Removed profile %s/%s", dimension.value, label)
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize profiles to dictionary."""
        result: Dict[str, Any] = {}
        for dim_key, profiles in self._profiles.items():
            result[dim_key] = {
                label: {
                    "context_id": p.context_id,
                    "label": p.label,
                    "confidence": p.confidence,
                    "sample_count": p.sample_count,
                    "first_seen": p.first_seen.isoformat(),
                    "last_seen": p.last_seen.isoformat(),
                    "features": p.features,
                }
                for label, p in profiles.items()
            }
        return result

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore profiles from dictionary."""
        for dim_key, profiles_data in data.items():
            try:
                dimension = ContextDimension(dim_key)
            except ValueError:
                logger.warning("Unknown dimension key: %s, skipping", dim_key)
                continue
            for label, pdata in profiles_data.items():
                profile = ContextProfile(
                    context_id=pdata.get("context_id", str(uuid.uuid4())),
                    dimension=dimension,
                    label=label,
                    confidence=pdata.get("confidence", 0.0),
                    sample_count=pdata.get("sample_count", 0),
                    features=pdata.get("features", {}),
                    first_seen=datetime.fromisoformat(pdata["first_seen"]) if "first_seen" in pdata else datetime.utcnow(),
                    last_seen=datetime.fromisoformat(pdata["last_seen"]) if "last_seen" in pdata else datetime.utcnow(),
                )
                self._profiles[dim_key][label] = profile
        logger.info("Restored %d dimensions from dictionary", len(data))


class ContextLearningEngine:
    """Main engine for context learning and adaptation.

    Extracts features from interaction data, classifies context dimensions,
    and maintains learned profiles to adapt rule behavior.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._mode = LearningMode(self.config.get("mode", "unsupervised"))
        self._feature_extractor = FeatureExtractor(self.config.get("feature_extractor", {}))
        self._classifier = ContextClassifier(self.config.get("classifier", {}))
        self._interaction_history: deque = deque(
            maxlen=self.config.get("max_history", 10000)
        )
        self._labeled_data: List[InteractionRecord] = []
        self._active_dimensions: Set[ContextDimension] = self._resolve_dimensions()
        self._adaptation_count: int = 0
        self._total_classification_time_ms: float = 0.0
        self._classification_count: int = 0
        self._correct_predictions: int = 0
        self._total_predictions: int = 0
        self._last_learning_time: Optional[datetime] = None

        logger.info(
            "ContextLearningEngine initialized (mode=%s, dimensions=%s, max_history=%d)",
            self._mode.value,
            [d.value for d in self._active_dimensions],
            self.config.get("max_history", 10000),
        )

    def _resolve_dimensions(self) -> Set[ContextDimension]:
        """Resolve active context dimensions from config."""
        configured = self.config.get("dimensions")
        if configured:
            result: Set[ContextDimension] = set()
            for d in configured:
                try:
                    result.add(ContextDimension(d))
                except ValueError:
                    logger.warning("Unknown dimension '%s' in config, skipping", d)
            return result or set(ContextDimension)
        return set(ContextDimension)

    def process_interaction(self, interaction: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single interaction: extract features and classify context.

        Args:
            interaction: Raw interaction data dictionary.

        Returns:
            Dictionary with learned context labels and confidence scores.
        """
        record_id = interaction.get("id", str(uuid.uuid4()))
        logger.debug("Processing interaction %s", record_id)

        try:
            features = self._feature_extractor.extract(interaction)
            classifications: Dict[str, Dict[str, Any]] = {}
            start_time = datetime.utcnow()

            for dimension in self._active_dimensions:
                label, confidence = self._classifier.classify(features, dimension)
                classifications[dimension.value] = {
                    "label": label,
                    "confidence": round(confidence, 4),
                }

            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000.0
            self._total_classification_time_ms += elapsed
            self._classification_count += 1

            record = InteractionRecord(
                interaction_id=record_id,
                raw_features=features,
                context_labels={dim: classifications[dim]["label"] for dim in classifications},
                rule_id=interaction.get("rule_id"),
                rule_triggered=interaction.get("rule_triggered", False),
                user_action=interaction.get("user_action"),
                outcome=interaction.get("outcome"),
            )
            self._interaction_history.append(record)

            if self._mode in (LearningMode.SUPERVISED, LearningMode.SEMI_SUPERVISED):
                expected = interaction.get("expected_context", {})
                if expected:
                    self._store_labeled_data(record, expected)

            self._maybe_trigger_learning()

            result: Dict[str, Any] = {
                "interaction_id": record_id,
                "classifications": classifications,
                "processing_time_ms": round(elapsed, 2),
            }
            return result

        except Exception as exc:
            logger.error("Failed to process interaction %s: %s", record_id, exc, exc_info=True)
            return {
                "interaction_id": record_id,
                "classifications": {},
                "error": str(exc),
                "processing_time_ms": 0.0,
            }

    def _store_labeled_data(self, record: InteractionRecord, expected: Dict[str, str]) -> None:
        """Store labeled interaction for supervised learning."""
        matched = all(
            record.context_labels.get(k) == v
            for k, v in expected.items()
        )
        if matched:
            self._correct_predictions += 1
        self._total_predictions += 1
        self._labeled_data.append(record)

        max_labeled = self.config.get("max_labeled_data", 5000)
        if len(self._labeled_data) > max_labeled:
            self._labeled_data = self._labeled_data[-max_labeled:]

    def _maybe_trigger_learning(self) -> None:
        """Trigger learning cycle based on interaction count."""
        batch_size = self.config.get("learning_batch_size", 100)
        if len(self._interaction_history) % batch_size == 0:
            self._run_learning_cycle()

    def _run_learning_cycle(self) -> None:
        """Execute a context learning cycle."""
        logger.info("Starting learning cycle (%d interactions)", len(self._interaction_history))
        start_time = datetime.utcnow()

        try:
            if self._mode == LearningMode.SUPERVISED:
                self._supervised_learning()
            elif self._mode == LearningMode.UNSUPERVISED:
                self._unsupervised_learning()
            elif self._mode == LearningMode.SEMI_SUPERVISED:
                self._semi_supervised_learning()
            elif self._mode == LearningMode.REINFORCEMENT:
                self._reinforcement_learning()

            self._adaptation_count += 1
            self._last_learning_time = datetime.utcnow()
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                "Learning cycle completed in %.2fs (adaptation #%d)",
                elapsed, self._adaptation_count,
            )

        except Exception as exc:
            logger.error("Learning cycle failed: %s", exc, exc_info=True)

    def _supervised_learning(self) -> None:
        """Run supervised learning using labeled data."""
        if not self._labeled_data:
            logger.warning("No labeled data available for supervised learning")
            return

        correct = self._correct_predictions
        total = self._total_predictions
        accuracy = correct / max(total, 1)

        for record in self._labeled_data:
            for dimension_key, label in record.context_labels.items():
                try:
                    dimension = ContextDimension(dimension_key)
                except ValueError:
                    continue
                self._classifier.learn(
                    label=label,
                    features=record.raw_features,
                    dimension=dimension,
                    confidence=accuracy,
                )

        logger.info(
            "Supervised learning completed (accuracy=%.3f, samples=%d)",
            accuracy, len(self._labeled_data),
        )

    def _unsupervised_learning(self) -> None:
        """Run unsupervised learning by clustering interactions."""
        dimension_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for record in self._interaction_history:
            for dim_key, label in record.context_labels.items():
                if label != "unknown":
                    dimension_counts[dim_key][label] += 1

        for dim_key, labels in dimension_counts.items():
            try:
                dimension = ContextDimension(dim_key)
            except ValueError:
                continue
            total = sum(labels.values())
            for label, count in labels.items():
                confidence = count / max(total, 1)
                profile = self._classifier.get_profile(dimension, label)
                if profile:
                    profile.confidence = min(1.0, profile.confidence + (confidence * 0.05))
                    profile.sample_count += count
                else:
                    self._classifier.learn(
                        label=label,
                        features={},
                        dimension=dimension,
                        confidence=confidence * 0.5,
                    )

    def _semi_supervised_learning(self) -> None:
        """Run semi-supervised learning combining labeled and unlabeled data."""
        self._supervised_learning()

        unlabeled_window = self.config.get("semi_supervised_window", 500)
        unlabeled = list(self._interaction_history)[-unlabeled_window:]
        labeled_ids = {r.interaction_id for r in self._labeled_data}
        unlabeled = [r for r in unlabeled if r.interaction_id not in labeled_ids]

        for record in unlabeled:
            for dim_key, label in record.context_labels.items():
                if label == "unknown":
                    continue
                try:
                    dimension = ContextDimension(dim_key)
                except ValueError:
                    continue
                profile = self._classifier.get_profile(dimension, label)
                if profile and profile.confidence > 0.7:
                    profile.sample_count += 1

        logger.info(
            "Semi-supervised learning: %d unlabeled records assimilated",
            len(unlabeled),
        )

    def _reinforcement_learning(self) -> None:
        """Run reinforcement learning using outcome-based rewards."""
        for record in self._interaction_history:
            reward = self._compute_reward(record)
            if reward == 0.0:
                continue

            for dim_key, label in record.context_labels.items():
                try:
                    dimension = ContextDimension(dim_key)
                except ValueError:
                    continue
                profile = self._classifier.get_profile(dimension, label)
                if profile:
                    adjustment = reward * self.config.get("rl_learning_rate", 0.01)
                    profile.confidence = max(0.0, min(1.0, profile.confidence + adjustment))

    def _compute_reward(self, record: InteractionRecord) -> float:
        """Compute reward signal based on interaction outcome."""
        if record.outcome == "success":
            return 1.0
        if record.outcome == "failure":
            return -1.0
        if record.user_action == "accept":
            return 0.5
        if record.user_action == "reject":
            return -0.5
        if record.user_action == "override":
            return -0.3
        return 0.0

    def get_context_profile(
        self,
        dimension: ContextDimension,
        label: str,
    ) -> Optional[ContextProfile]:
        """Get a learned profile for a specific dimension and label."""
        return self._classifier.get_profile(dimension, label)

    def get_all_profiles(
        self,
        dimension: Optional[ContextDimension] = None,
    ) -> List[ContextProfile]:
        """Get all learned context profiles."""
        return self._classifier.get_all_profiles(dimension)

    def classify_context(
        self,
        context: RuleContext,
    ) -> Dict[str, Dict[str, Any]]:
        """Classify a RuleContext into learned context labels."""
        interaction = {
            "id": str(uuid.uuid4()),
            "context": context.get_effective_context(),
            "timestamp": context.timestamp,
        }
        result = self.process_interaction(interaction)
        return result.get("classifications", {})

    def get_statistics(self) -> ContextStatistics:
        """Get aggregated statistics about the learning engine."""
        unique_domains = set()
        unique_roles = set()
        unique_content = set()

        for record in self._interaction_history:
            if "domain" in record.context_labels:
                unique_domains.add(record.context_labels["domain"])
            if "user_role" in record.context_labels:
                unique_roles.add(record.context_labels["user_role"])
            if "content_type" in record.context_labels:
                unique_content.add(record.context_labels["content_type"])

        accuracy = (
            self._correct_predictions / max(self._total_predictions, 1)
            if self._mode in (LearningMode.SUPERVISED, LearningMode.SEMI_SUPERVISED)
            else 0.0
        )

        avg_latency = (
            self._total_classification_time_ms / max(self._classification_count, 1)
        )

        return ContextStatistics(
            total_interactions=len(self._interaction_history),
            unique_domains=len(unique_domains),
            unique_user_roles=len(unique_roles),
            unique_content_types=len(unique_content),
            profiles_by_dimension={
                d.value: self._classifier.profile_count(ContextDimension(d))
                for d in self._active_dimensions
            },
            learning_accuracy=round(accuracy, 4),
            classification_latency_ms=round(avg_latency, 2),
            last_learning_time=self._last_learning_time,
            mode=self._mode.value,
            adaptation_count=self._adaptation_count,
        )

    def process_batch(
        self,
        interactions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Process a batch of interactions."""
        return [self.process_interaction(interaction) for interaction in interactions]

    def get_interaction_history(
        self,
        limit: Optional[int] = None,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[InteractionRecord]:
        """Get filtered interaction history.

        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            filters: Optional filters (e.g., {"rule_triggered": True}).

        Returns:
            List of matching InteractionRecord instances.
        """
        records = list(self._interaction_history)

        if filters:
            for key, val in filters.items():
                records = [r for r in records if getattr(r, key, None) == val]

        records = records[offset:]
        if limit:
            records = records[:limit]

        return records

    def export_profiles(self) -> Dict[str, Any]:
        """Export all learned profiles as a serializable dictionary."""
        return {
            "engine_version": "1.0.0",
            "mode": self._mode.value,
            "adaptation_count": self._adaptation_count,
            "classifier": self._classifier.to_dict(),
            "exported_at": datetime.utcnow().isoformat(),
        }

    def import_profiles(self, data: Dict[str, Any]) -> bool:
        """Import previously exported profiles.

        Args:
            data: Dictionary from export_profiles().

        Returns:
            True if import succeeded.
        """
        try:
            classifier_data = data.get("classifier", {})
            if classifier_data:
                self._classifier.from_dict(classifier_data)

            mode_str = data.get("mode", "unsupervised")
            self._mode = LearningMode(mode_str)

            self._adaptation_count = data.get("adaptation_count", 0)
            logger.info("Imported profiles from export (mode=%s)", mode_str)
            return True

        except Exception as exc:
            logger.error("Failed to import profiles: %s", exc, exc_info=True)
            return False

    def clear_history(self) -> int:
        """Clear interaction history.

        Returns:
            Number of records cleared.
        """
        count = len(self._interaction_history)
        self._interaction_history.clear()
        self._labeled_data.clear()
        self._correct_predictions = 0
        self._total_predictions = 0
        logger.info("Cleared %d interaction records", count)
        return count

    def set_mode(self, mode: LearningMode) -> None:
        """Change the learning mode."""
        self._mode = mode
        logger.info("Learning mode changed to %s", mode.value)

    def get_mode(self) -> LearningMode:
        """Get the current learning mode."""
        return self._mode
