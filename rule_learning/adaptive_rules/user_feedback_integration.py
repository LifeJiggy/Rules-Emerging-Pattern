"""User feedback integration for adaptive rule learning.

Provides multiple feedback channels, scoring and aggregation,
feedback-driven rule improvement suggestions, and per-user profiles.
"""

import csv
import io
import json
import logging
import math
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from rules_emerging_pattern.models.rule import Rule, RuleSeverity, RuleTier

logger = logging.getLogger(__name__)


class FeedbackChannel(str, Enum):
    """Channels through which feedback can be received."""
    EXPLICIT_RATING = "explicit_rating"
    IMPLICIT_SIGNAL = "implicit_signal"
    OVERRIDE_PATTERN = "override_pattern"
    USER_REPORT = "user_report"
    ADMIN_REVIEW = "admin_review"
    SYSTEM_AUDIT = "system_audit"
    SURVEY = "survey"
    API_CALLBACK = "api_callback"


class FeedbackType(str, Enum):
    """Types of feedback signals."""
    RULE_TOO_STRICT = "rule_too_strict"
    RULE_TOO_LENIENT = "rule_too_lenient"
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"
    SUGGESTION = "suggestion"
    COMPLAINT = "complaint"
    PRAISE = "praise"
    CORRECTION = "correction"
    CUSTOM = "custom"


class FeedbackSentiment(str, Enum):
    """Sentiment classification of feedback."""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


@dataclass
class FeedbackRecord:
    """A single feedback entry."""
    feedback_id: str
    rule_id: str
    user_id: str
    channel: FeedbackChannel
    feedback_type: FeedbackType
    sentiment: FeedbackSentiment
    rating: float = 0.0
    weight: float = 1.0
    comment: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    processed: bool = False
    applied: bool = False

    def age_hours(self) -> float:
        """Get age in hours."""
        return (datetime.utcnow() - self.created_at).total_seconds() / 3600.0


@dataclass
class UserFeedbackProfile:
    """Feedback profile for a single user."""
    user_id: str
    total_feedback_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    average_rating: float = 0.0
    rating_variance: float = 0.0
    override_rate: float = 0.0
    reliability_score: float = 1.0
    recent_sentiment: float = 0.0
    active_rules_feedback: Set[str] = field(default_factory=set)
    first_feedback: Optional[datetime] = None
    last_feedback: Optional[datetime] = None
    preferred_channels: List[str] = field(default_factory=list)

    def update(self, record: FeedbackRecord) -> None:
        """Update profile with a new feedback record."""
        self.total_feedback_count += 1
        self.active_rules_feedback.add(record.rule_id)

        if record.sentiment == FeedbackSentiment.POSITIVE:
            self.positive_count += 1
        elif record.sentiment == FeedbackSentiment.NEGATIVE:
            self.negative_count += 1
        else:
            self.neutral_count += 1

        old_avg = self.average_rating
        n = self.total_feedback_count
        self.average_rating = old_avg + (record.rating - old_avg) / n
        self.rating_variance = (
            (n - 1) * self.rating_variance + (record.rating - old_avg) * (record.rating - self.average_rating)
        ) / n if n > 1 else 0.0

        if self.first_feedback is None:
            self.first_feedback = record.created_at
        self.last_feedback = record.created_at

        if record.channel not in self.preferred_channels:
            self.preferred_channels.append(record.channel.value)

        alpha = 0.3
        signal = 1.0 if record.sentiment == FeedbackSentiment.POSITIVE else (
            -1.0 if record.sentiment == FeedbackSentiment.NEGATIVE else 0.0
        )
        self.recent_sentiment = (1.0 - alpha) * self.recent_sentiment + alpha * signal

        if record.rating < 0.3:
            self.reliability_score = max(0.1, self.reliability_score - 0.01)
        elif record.rating > 0.7:
            self.reliability_score = min(1.0, self.reliability_score + 0.005)


@dataclass
class FeedbackStatistics:
    """Aggregated feedback statistics."""
    total_feedback: int = 0
    positive_feedback: int = 0
    negative_feedback: int = 0
    neutral_feedback: int = 0
    unique_users: int = 0
    unique_rules: int = 0
    average_rating: float = 0.0
    average_reliability: float = 0.0
    feedback_by_channel: Dict[str, int] = field(default_factory=dict)
    feedback_by_type: Dict[str, int] = field(default_factory=dict)
    feedback_by_rule: Dict[str, int] = field(default_factory=dict)
    override_rate: float = 0.0
    feedback_per_user: float = 0.0
    recent_trend: str = "stable"
    last_feedback_time: Optional[datetime] = None


@dataclass
class ImprovementSuggestion:
    """Suggestion for rule improvement based on feedback."""
    suggestion_id: str
    rule_id: str
    title: str
    description: str
    priority: float = 0.0
    confidence: float = 0.0
    supporting_feedback_count: int = 0
    suggested_action: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    implemented: bool = False
    implemented_at: Optional[datetime] = None


class FeedbackScorer:
    """Handles feedback scoring and aggregation."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._time_decay_hours = self.config.get("time_decay_hours", 168.0)
        self._rolling_window = self.config.get("rolling_window", 100)
        logger.info("FeedbackScorer initialized (decay=%.1fh, window=%d)", self._time_decay_hours, self._rolling_window)

    def score_feedback(self, record: FeedbackRecord, user_profile: Optional[UserFeedbackProfile] = None) -> float:
        """Compute a weighted score for a single feedback record.

        Combines explicit rating, user reliability, time decay, and channel weight.

        Returns:
            Normalized score between 0.0 and 1.0.
        """
        base = max(0.0, min(1.0, record.rating))
        base = (base - 0.5) * 2.0

        time_weight = self._time_decay_weight(record)

        reliability = 1.0
        if user_profile:
            reliability = user_profile.reliability_score

        channel_weight = self._channel_weight(record.channel)

        total = base * time_weight * reliability * channel_weight
        return max(-1.0, min(1.0, total))

    def aggregate_scores(
        self,
        records: List[FeedbackRecord],
        user_profiles: Optional[Dict[str, UserFeedbackProfile]] = None,
    ) -> float:
        """Aggregate multiple feedback records into a single weighted score.

        Uses a weighted average with time decay and reliability weighting.

        Returns:
            Aggregated score between -1.0 and 1.0.
        """
        if not records:
            return 0.0

        total_weight = 0.0
        total_score = 0.0

        for record in records:
            profile = None
            if user_profiles:
                profile = user_profiles.get(record.user_id)

            score = self.score_feedback(record, profile)
            weight = record.weight * (
                user_profiles[record.user_id].reliability_score
                if user_profiles and record.user_id in user_profiles
                else 1.0
            )

            total_score += score * weight
            total_weight += weight

        if total_weight == 0.0:
            return 0.0

        return max(-1.0, min(1.0, total_score / total_weight))

    def rolling_average(
        self,
        records: List[FeedbackRecord],
        window: Optional[int] = None,
    ) -> List[float]:
        """Compute rolling average of feedback ratings.

        Args:
            records: Sorted feedback records (oldest first).
            window: Window size (defaults to config value).

        Returns:
            List of rolling average values.
        """
        window = window or self._rolling_window
        if not records:
            return []

        values: List[float] = []
        for i in range(len(records)):
            start = max(0, i - window + 1)
            segment = records[start:i + 1]
            avg = sum(r.rating for r in segment) / len(segment)
            values.append(avg)

        return values

    def _time_decay_weight(self, record: FeedbackRecord) -> float:
        """Compute exponential time decay weight."""
        age_hours = record.age_hours()
        half_life = self._time_decay_hours
        return math.exp(-math.log(2) * age_hours / max(half_life, 1.0))

    def _channel_weight(self, channel: FeedbackChannel) -> float:
        """Get reliability weight for a feedback channel."""
        weights = {
            FeedbackChannel.EXPLICIT_RATING: 1.0,
            FeedbackChannel.ADMIN_REVIEW: 0.95,
            FeedbackChannel.USER_REPORT: 0.8,
            FeedbackChannel.SURVEY: 0.75,
            FeedbackChannel.OVERRIDE_PATTERN: 0.6,
            FeedbackChannel.IMPLICIT_SIGNAL: 0.4,
            FeedbackChannel.SYSTEM_AUDIT: 0.3,
            FeedbackChannel.API_CALLBACK: 0.5,
        }
        return weights.get(channel, 0.5)


class UserFeedbackIntegration:
    """Main integration point for user feedback in adaptive rule learning.

    Handles multiple feedback channels, scoring, aggregation, history
    management, per-user profiles, and rule improvement suggestions.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._scorer = FeedbackScorer(self.config.get("scorer", {}))
        self._feedback_history: deque = deque(
            maxlen=self.config.get("max_history", 10000)
        )
        self._user_profiles: Dict[str, UserFeedbackProfile] = {}
        self._pending_suggestions: List[ImprovementSuggestion] = []
        self._implemented_suggestions: List[ImprovementSuggestion] = []
        self._override_tracker: Dict[str, int] = defaultdict(int)
        self._start_time = datetime.utcnow()

        logger.info(
            "UserFeedbackIntegration initialized (max_history=%d)",
            self.config.get("max_history", 10000),
        )

    def submit_feedback(
        self,
        rule_id: str,
        user_id: str,
        channel: FeedbackChannel,
        feedback_type: FeedbackType,
        rating: float,
        sentiment: Optional[FeedbackSentiment] = None,
        comment: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FeedbackRecord:
        """Submit a new feedback record.

        Args:
            rule_id: The rule this feedback targets.
            user_id: Identifier for the user.
            channel: How the feedback was received.
            feedback_type: Type of feedback signal.
            rating: Numeric rating (0.0 to 1.0).
            sentiment: Optional sentiment override.
            comment: Optional textual comment.
            context: Optional context dictionary.
            weight: Relative weight of this feedback.
            metadata: Additional metadata.

        Returns:
            The created FeedbackRecord.
        """
        if sentiment is None:
            sentiment = self._infer_sentiment(rating)

        record = FeedbackRecord(
            feedback_id=str(uuid.uuid4()),
            rule_id=rule_id,
            user_id=user_id,
            channel=channel,
            feedback_type=feedback_type,
            sentiment=sentiment,
            rating=max(0.0, min(1.0, rating)),
            weight=weight,
            comment=comment,
            context=context or {},
            metadata=metadata or {},
        )

        self._feedback_history.append(record)

        self._update_user_profile(record)

        if channel == FeedbackChannel.OVERRIDE_PATTERN:
            self._override_tracker[rule_id] += 1

        if self._should_generate_suggestion(record):
            suggestion = self._generate_suggestion(record)
            self._pending_suggestions.append(suggestion)

        logger.debug(
            "Feedback submitted: rule=%s user=%s channel=%s rating=%.2f sentiment=%s",
            rule_id, user_id, channel.value, rating, sentiment.value,
        )

        return record

    def submit_override_feedback(
        self,
        rule_id: str,
        user_id: str,
        override_type: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> FeedbackRecord:
        """Submit feedback from an override action (implicit signal).

        Args:
            rule_id: The rule that was overridden.
            user_id: The user who overrode.
            override_type: "block_override", "warning_dismiss", etc.
            context: Optional context.

        Returns:
            FeedbackRecord for the implicit feedback.
        """
        rating_map = {
            "block_override": 0.1,
            "warning_dismiss": 0.2,
            "suggestion_accept": 0.7,
            "block_accept": 0.9,
        }

        rating = rating_map.get(override_type, 0.5)

        return self.submit_feedback(
            rule_id=rule_id,
            user_id=user_id,
            channel=FeedbackChannel.OVERRIDE_PATTERN,
            feedback_type=FeedbackType.RULE_TOO_STRICT
            if rating < 0.5
            else FeedbackType.FALSE_POSITIVE,
            rating=rating,
            sentiment=FeedbackSentiment.NEGATIVE if rating < 0.5 else FeedbackSentiment.POSITIVE,
            context=context,
            weight=0.6,
        )

    def submit_batch_feedback(
        self,
        feedback_entries: List[Dict[str, Any]],
    ) -> List[FeedbackRecord]:
        """Submit multiple feedback records in batch.

        Args:
            feedback_entries: List of dicts with feedback parameters.

        Returns:
            List of created FeedbackRecord instances.
        """
        records: List[FeedbackRecord] = []
        for entry in feedback_entries:
            record = self.submit_feedback(
                rule_id=entry["rule_id"],
                user_id=entry["user_id"],
                channel=FeedbackChannel(entry.get("channel", "explicit_rating")),
                feedback_type=FeedbackType(entry.get("feedback_type", "custom")),
                rating=entry.get("rating", 0.5),
                sentiment=FeedbackSentiment(entry["sentiment"]) if "sentiment" in entry else None,
                comment=entry.get("comment"),
                context=entry.get("context"),
                weight=entry.get("weight", 1.0),
            )
            records.append(record)

        logger.info("Batch submitted %d feedback records", len(records))
        return records

    def get_rule_feedback(
        self,
        rule_id: str,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
        sentiment: Optional[FeedbackSentiment] = None,
    ) -> List[FeedbackRecord]:
        """Get feedback records for a specific rule.

        Args:
            rule_id: The rule to query.
            limit: Max results.
            since: Only feedback after this datetime.
            sentiment: Filter by sentiment.

        Returns:
            List of matching FeedbackRecord.
        """
        records = [r for r in self._feedback_history if r.rule_id == rule_id]

        if since:
            records = [r for r in records if r.created_at >= since]
        if sentiment:
            records = [r for r in records if r.sentiment == sentiment]

        records.sort(key=lambda r: r.created_at, reverse=True)

        if limit:
            records = records[:limit]

        return records

    def get_user_feedback(
        self,
        user_id: str,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[FeedbackRecord]:
        """Get feedback records for a specific user."""
        records = [r for r in self._feedback_history if r.user_id == user_id]

        if since:
            records = [r for r in records if r.created_at >= since]

        records.sort(key=lambda r: r.created_at, reverse=True)

        if limit:
            records = records[:limit]

        return records

    def get_user_profile(self, user_id: str) -> Optional[UserFeedbackProfile]:
        """Get the feedback profile for a user."""
        return self._user_profiles.get(user_id)

    def get_all_user_profiles(self) -> Dict[str, UserFeedbackProfile]:
        """Get all user feedback profiles."""
        return dict(self._user_profiles)

    def get_rule_score(
        self,
        rule_id: str,
        time_window: Optional[timedelta] = None,
    ) -> float:
        """Get aggregated feedback score for a rule.

        Args:
            rule_id: The rule to score.
            time_window: Optional time window restriction.

        Returns:
            Aggregated score between -1.0 (negative) and 1.0 (positive).
        """
        records = self.get_rule_feedback(rule_id)
        if time_window:
            cutoff = datetime.utcnow() - time_window
            records = [r for r in records if r.created_at >= cutoff]

        return self._scorer.aggregate_scores(records, self._user_profiles)

    def get_rule_scores(
        self,
        rule_ids: Optional[List[str]] = None,
        time_window: Optional[timedelta] = None,
    ) -> Dict[str, float]:
        """Get aggregated scores for multiple rules.

        Args:
            rule_ids: Rules to score (all if None).
            time_window: Optional time window.

        Returns:
            Dict of rule_id -> score.
        """
        if rule_ids is None:
            rule_ids = list({r.rule_id for r in self._feedback_history})

        scores: Dict[str, float] = {}
        for rid in rule_ids:
            scores[rid] = self.get_rule_score(rid, time_window)

        return scores

    def get_improvement_suggestions(
        self,
        min_priority: float = 0.0,
        max_count: Optional[int] = None,
        include_implemented: bool = False,
    ) -> List[ImprovementSuggestion]:
        """Get pending rule improvement suggestions.

        Args:
            min_priority: Minimum priority threshold.
            max_count: Maximum suggestions to return.
            include_implemented: Include already-implemented suggestions.

        Returns:
            Sorted list of ImprovementSuggestion.
        """
        suggestions: List[ImprovementSuggestion] = []
        suggestions.extend(self._pending_suggestions)

        if include_implemented:
            suggestions.extend(self._implemented_suggestions)

        suggestions = [s for s in suggestions if s.priority >= min_priority]
        suggestions.sort(key=lambda s: s.priority, reverse=True)

        if max_count:
            suggestions = suggestions[:max_count]

        return suggestions

    def mark_suggestion_implemented(self, suggestion_id: str) -> bool:
        """Mark an improvement suggestion as implemented."""
        for suggestion in self._pending_suggestions:
            if suggestion.suggestion_id == suggestion_id:
                suggestion.implemented = True
                suggestion.implemented_at = datetime.utcnow()
                self._implemented_suggestions.append(suggestion)
                self._pending_suggestions.remove(suggestion)
                logger.info("Suggestion %s marked as implemented", suggestion_id)
                return True
        return False

    def export_feedback(
        self,
        format: str = "json",
        rule_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> str:
        """Export feedback history as JSON or CSV.

        Args:
            format: "json" or "csv".
            rule_id: Optional rule filter.
            since: Optional datetime filter.

        Returns:
            Formatted string.
        """
        records = list(self._feedback_history)
        if rule_id:
            records = [r for r in records if r.rule_id == rule_id]
        if since:
            records = [r for r in records if r.created_at >= since]

        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "feedback_id", "rule_id", "user_id", "channel", "feedback_type",
                "sentiment", "rating", "weight", "comment", "created_at",
            ])
            for r in records:
                writer.writerow([
                    r.feedback_id, r.rule_id, r.user_id, r.channel.value,
                    r.feedback_type.value, r.sentiment.value, r.rating,
                    r.weight, r.comment or "", r.created_at.isoformat(),
                ])
            return output.getvalue()

        data = [
            {
                "feedback_id": r.feedback_id,
                "rule_id": r.rule_id,
                "user_id": r.user_id,
                "channel": r.channel.value,
                "feedback_type": r.feedback_type.value,
                "sentiment": r.sentiment.value,
                "rating": r.rating,
                "weight": r.weight,
                "comment": r.comment,
                "context": r.context,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]
        return json.dumps(data, indent=2, default=str)

    def clear_feedback(
        self,
        rule_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """Clear feedback records.

        Args:
            rule_id: Clear only for this rule.
            user_id: Clear only for this user.

        Returns:
            Number of records cleared.
        """
        if rule_id:
            before = len(self._feedback_history)
            self._feedback_history = deque(
                (r for r in self._feedback_history if r.rule_id != rule_id),
                maxlen=self._feedback_history.maxlen,
            )
            cleared = before - len(self._feedback_history)
        elif user_id:
            before = len(self._feedback_history)
            self._feedback_history = deque(
                (r for r in self._feedback_history if r.user_id != user_id),
                maxlen=self._feedback_history.maxlen,
            )
            if user_id in self._user_profiles:
                del self._user_profiles[user_id]
            cleared = before - len(self._feedback_history)
        else:
            cleared = len(self._feedback_history)
            self._feedback_history.clear()
            self._user_profiles.clear()
            self._pending_suggestions.clear()

        logger.info("Cleared %d feedback records", cleared)
        return cleared

    def get_statistics(self) -> FeedbackStatistics:
        """Get aggregated feedback statistics."""
        total = len(self._feedback_history)
        if total == 0:
            return FeedbackStatistics()

        pos = sum(1 for r in self._feedback_history if r.sentiment == FeedbackSentiment.POSITIVE)
        neg = sum(1 for r in self._feedback_history if r.sentiment == FeedbackSentiment.NEGATIVE)
        neu = sum(1 for r in self._feedback_history if r.sentiment == FeedbackSentiment.NEUTRAL)

        unique_users = len({r.user_id for r in self._feedback_history})
        unique_rules = len({r.rule_id for r in self._feedback_history})

        avg_rating = sum(r.rating for r in self._feedback_history) / max(total, 1)

        reliabilities = [p.reliability_score for p in self._user_profiles.values()]
        avg_reliability = sum(reliabilities) / max(len(reliabilities), 1)

        by_channel: Dict[str, int] = defaultdict(int)
        by_type: Dict[str, int] = defaultdict(int)
        by_rule: Dict[str, int] = defaultdict(int)
        for r in self._feedback_history:
            by_channel[r.channel.value] += 1
            by_type[r.feedback_type.value] += 1
            by_rule[r.rule_id] += 1

        override_count = sum(self._override_tracker.values())
        override_rate = override_count / max(total, 1)

        last_time = max(r.created_at for r in self._feedback_history) if total > 0 else None

        if total >= 20:
            recent = list(self._feedback_history)[-10:]
            older = list(self._feedback_history)[:10]
            recent_avg = sum(r.rating for r in recent) / max(len(recent), 1)
            older_avg = sum(r.rating for r in older) / max(len(older), 1)
            trend = "improving" if recent_avg > older_avg + 0.05 else (
                "declining" if recent_avg < older_avg - 0.05 else "stable"
            )
        else:
            trend = "stable"

        return FeedbackStatistics(
            total_feedback=total,
            positive_feedback=pos,
            negative_feedback=neg,
            neutral_feedback=neu,
            unique_users=unique_users,
            unique_rules=unique_rules,
            average_rating=round(avg_rating, 4),
            average_reliability=round(avg_reliability, 4),
            feedback_by_channel=dict(by_channel),
            feedback_by_type=dict(by_type),
            feedback_by_rule=dict(by_rule),
            override_rate=round(override_rate, 4),
            feedback_per_user=round(total / max(unique_users, 1), 2),
            recent_trend=trend,
            last_feedback_time=last_time,
        )

    def get_rule_feedback_summary(self, rule_id: str) -> Dict[str, Any]:
        """Get a summary of feedback for a specific rule."""
        records = self.get_rule_feedback(rule_id)
        if not records:
            return {"rule_id": rule_id, "total_feedback": 0}

        pos = sum(1 for r in records if r.sentiment == FeedbackSentiment.POSITIVE)
        neg = sum(1 for r in records if r.sentiment == FeedbackSentiment.NEGATIVE)
        neu = sum(1 for r in records if r.sentiment == FeedbackSentiment.NEUTRAL)

        scores = self._scorer.rolling_average(records)
        trend = "improving" if len(scores) > 5 and scores[-1] > scores[0] else (
            "declining" if len(scores) > 5 and scores[-1] < scores[0] else "stable"
        )

        recent = [r for r in records if r.age_hours() < 24]
        recent_score = self._scorer.aggregate_scores(recent, self._user_profiles) if recent else 0.0

        return {
            "rule_id": rule_id,
            "total_feedback": len(records),
            "positive_count": pos,
            "negative_count": neg,
            "neutral_count": neu,
            "sentiment_ratio": pos / max(len(records), 1),
            "average_rating": sum(r.rating for r in records) / max(len(records), 1),
            "aggregate_score": self.get_rule_score(rule_id),
            "recent_24h_score": round(recent_score, 4),
            "trend": trend,
            "override_count": self._override_tracker.get(rule_id, 0),
            "unique_users": len({r.user_id for r in records}),
        }

    def _infer_sentiment(self, rating: float) -> FeedbackSentiment:
        """Infer sentiment from a numeric rating."""
        if rating >= 0.7:
            return FeedbackSentiment.POSITIVE
        if rating <= 0.3:
            return FeedbackSentiment.NEGATIVE
        return FeedbackSentiment.NEUTRAL

    def _update_user_profile(self, record: FeedbackRecord) -> None:
        """Update or create a user feedback profile."""
        if record.user_id not in self._user_profiles:
            self._user_profiles[record.user_id] = UserFeedbackProfile(
                user_id=record.user_id,
            )

        self._user_profiles[record.user_id].update(record)

    def _should_generate_suggestion(self, record: FeedbackRecord) -> bool:
        """Determine if a feedback record should trigger a suggestion."""
        if record.sentiment == FeedbackSentiment.NEGATIVE and record.rating < 0.3:
            freq = self.config.get("suggestion_frequency", 5)
            rule_records = self.get_rule_feedback(record.rule_id)
            negative_count = sum(
                1 for r in rule_records
                if r.sentiment == FeedbackSentiment.NEGATIVE
            )
            return negative_count % freq == 0

        return False

    def _generate_suggestion(self, record: FeedbackRecord) -> ImprovementSuggestion:
        """Generate an improvement suggestion from a feedback record."""
        rule_records = self.get_rule_feedback(record.rule_id)

        negative_count = sum(
            1 for r in rule_records
            if r.sentiment == FeedbackSentiment.NEGATIVE
        )
        total_count = len(rule_records)
        negative_ratio = negative_count / max(total_count, 1)

        if record.feedback_type in (FeedbackType.RULE_TOO_STRICT, FeedbackType.FALSE_POSITIVE):
            title = f"Rule {record.rule_id} may be too strict"
            description = (
                f"Received {negative_count} negative feedback entries "
                f"({negative_ratio:.0%} negative ratio). Consider relaxing thresholds."
            )
            suggested_action = "relax"
        elif record.feedback_type == FeedbackType.RULE_TOO_LENIENT:
            title = f"Rule {record.rule_id} may be too lenient"
            description = (
                f"Received feedback indicating rule is not catching violations. "
                f"Consider tightening thresholds."
            )
            suggested_action = "tighten"
        else:
            title = f"Review rule {record.rule_id} based on feedback"
            description = f"Feedback type: {record.feedback_type.value}. Rating: {record.rating:.2f}"
            suggested_action = "review"

        priority = min(1.0, negative_ratio * record.weight)
        confidence = min(1.0, total_count / max(self.config.get("suggestion_frequency", 5), 1) * 0.5)

        return ImprovementSuggestion(
            suggestion_id=str(uuid.uuid4()),
            rule_id=record.rule_id,
            title=title,
            description=description,
            priority=round(priority, 4),
            confidence=round(confidence, 4),
            supporting_feedback_count=negative_count,
            suggested_action=suggested_action,
            parameters={
                "negative_ratio": round(negative_ratio, 4),
                "latest_rating": record.rating,
                "latest_channel": record.channel.value,
            },
        )
