"""Pattern recognition engine for rule learning."""
import logging
import json
import math
import re
import statistics
from typing import Dict, List, Any, Optional, Tuple, Set, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from enum import Enum
from itertools import combinations
import uuid

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RulePattern

logger = logging.getLogger(__name__)


class MatchStrategy(Enum):
    REGEX = "regex"
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    STRUCTURAL = "structural"
    HYBRID = "hybrid"


@dataclass
class PatternConfig:
    min_confidence: float = 0.7
    learning_rate: float = 0.05
    decay_rate: float = 0.01
    decay_interval_hours: int = 24
    cluster_similarity_threshold: float = 0.75
    correlation_min_occurrences: int = 3
    max_pattern_age_days: int = 90
    enable_auto_decay: bool = True
    enable_clustering: bool = True
    enable_correlation: bool = True
    max_patterns_per_type: int = 1000
    export_include_history: bool = True
    export_include_metadata: bool = True
    min_occurrences_for_rule: int = 3


@dataclass
class Pattern:
    pattern_id: str
    pattern_type: str
    confidence: float
    occurrences: int
    first_seen: datetime
    last_seen: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    match_strategy: MatchStrategy = MatchStrategy.REGEX
    cluster_id: Optional[str] = None
    decay_factor: float = 1.0
    correlation_scores: Dict[str, float] = field(default_factory=dict)


@dataclass
class PatternCluster:
    cluster_id: str
    pattern_type: str
    pattern_ids: List[str] = field(default_factory=list)
    centroid_confidence: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PatternCorrelation:
    source_id: str
    target_id: str
    correlation_score: float
    co_occurrence_count: int
    last_observed: datetime
    relationship_type: str = "co_occurrence"


class PatternRecognitionEngine:
    def __init__(self, config: Optional[PatternConfig] = None):
        self.config = config or PatternConfig()
        self.patterns: Dict[str, Pattern] = {}
        self.pattern_templates: Dict[str, str] = {}
        self.keyword_patterns: Dict[str, List[str]] = defaultdict(list)
        self.pattern_history: List[Dict] = []
        self.observation_count = 0
        self.clusters: Dict[str, PatternCluster] = {}
        self.correlations: Dict[str, Dict[str, PatternCorrelation]] = defaultdict(dict)
        self.confidence_history: Dict[str, List[float]] = defaultdict(list)
        self._archived_patterns: Dict[str, Dict] = {}
        self._subscriptions: List[Dict] = []
        self._custom_extractors: Dict[str, Callable] = {}
        self._initialize_builtin_matchers()
        logger.info(f"PatternRecognitionEngine initialized (min_confidence={self.config.min_confidence})")

    def _initialize_builtin_matchers(self) -> None:
        self.register_template("url_pattern", r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*")
        self.register_template("email_pattern", r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        self.register_template("ip_address", r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
        self.register_template("uuid_v4", r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
        self.register_template("json_path", r"\$\.(?:[a-zA-Z_]\w*\.)*[a-zA-Z_]\w*")
        self.register_template("hexadecimal", r"\b0x[0-9a-fA-F]+\b")
        self.register_keywords("code_keyword", ["class", "def", "function", "import", "from", "return", "if", "else", "for", "while"])
        self.register_keywords("data_keyword", ["data", "value", "key", "result", "response", "error"])
        self.register_keywords("security_keyword", ["password", "token", "secret", "auth", "permission", "access"])

    def register_template(self, pattern_type: str, template: str) -> None:
        try:
            re.compile(template)
            self.pattern_templates[pattern_type] = template
            logger.info(f"Registered pattern template: {pattern_type}")
        except re.error as e:
            logger.error(f"Invalid template for {pattern_type}: {e}")

    def register_keywords(self, pattern_type: str, keywords: List[str]) -> None:
        self.keyword_patterns[pattern_type] = keywords
        logger.info(f"Registered keyword pattern: {pattern_type} ({len(keywords)} keywords)")

    def analyze_data(self, data: Any, context: Optional[Dict] = None) -> List[Pattern]:
        found_patterns = []
        self.observation_count += 1
        if isinstance(data, str):
            found_patterns.extend(self._analyze_text_regex(data, context))
            found_patterns.extend(self._analyze_text_keywords(data, context))
            found_patterns.extend(self.analyze_text_semantic(data, context))
        elif isinstance(data, dict):
            found_patterns.extend(self._analyze_structure(data, context))
            for value in data.values():
                if isinstance(value, str):
                    found_patterns.extend(self._analyze_text_regex(value, context))
                    found_patterns.extend(self._analyze_text_keywords(value, context))
        elif isinstance(data, list):
            found_patterns.extend(self._analyze_collection(data, context))
            for item in data:
                if isinstance(item, str):
                    found_patterns.extend(self._analyze_text_regex(item, context))
                    found_patterns.extend(self._analyze_text_keywords(item, context))
        found_patterns = self._deduplicate_patterns(found_patterns)
        for pattern in found_patterns:
            if pattern.pattern_id in self.patterns:
                existing = self.patterns[pattern.pattern_id]
                existing.occurrences += 1
                existing.last_seen = datetime.now()
                increment = self.config.learning_rate * (1.0 - existing.confidence)
                existing.confidence = min(1.0, existing.confidence + increment)
                if pattern.metadata and context:
                    existing.metadata['last_context'] = context
                    existing.metadata['last_value'] = str(data)[:200]
                self.confidence_history[pattern.pattern_id].append(existing.confidence)
            else:
                self.patterns[pattern.pattern_id] = pattern
                self.confidence_history[pattern.pattern_id].append(pattern.confidence)
            self.pattern_history.append({
                'pattern_id': pattern.pattern_id,
                'pattern_type': pattern.pattern_type,
                'timestamp': datetime.now(),
                'observation': self.observation_count,
                'context': context
            })
        if self.config.enable_auto_decay and self.observation_count % 10 == 0:
            self._apply_pattern_decay()
        if self.config.enable_clustering and len(self.patterns) > 5 and self.observation_count % 20 == 0:
            self._cluster_patterns()
        if self.config.enable_correlation and len(self.pattern_history) > 10:
            self._update_correlations(found_patterns)
        self._enforce_pattern_limits()
        logger.debug(f"Analysis #{self.observation_count}: found {len(found_patterns)} patterns")
        return found_patterns

    def _analyze_text_regex(self, text: str, context: Optional[Dict]) -> List[Pattern]:
        patterns = []
        for pattern_type, template in self.pattern_templates.items():
            matches = re.findall(template, text)
            if matches:
                pattern_id = f"regex_{pattern_type}_{hash(template) % 100000}"
                raw_confidence = min(1.0, len(matches) * 0.15)
                adjusted_confidence = self._adjust_confidence_with_context(raw_confidence, pattern_type, context)
                pattern = Pattern(
                    pattern_id=pattern_id,
                    pattern_type=pattern_type,
                    confidence=adjusted_confidence,
                    occurrences=len(matches),
                    first_seen=datetime.now(),
                    last_seen=datetime.now(),
                    metadata={
                        'matches': matches[:10],
                        'match_strategy': 'regex',
                        'context': context,
                        'template': template
                    },
                    match_strategy=MatchStrategy.REGEX
                )
                patterns.append(pattern)
        return patterns

    def _analyze_text_keywords(self, text: str, context: Optional[Dict]) -> List[Pattern]:
        patterns = []
        text_lower = text.lower()
        for pattern_type, keywords in self.keyword_patterns.items():
            found_keywords = []
            for keyword in keywords:
                if keyword in text_lower:
                    found_keywords.append(keyword)
            if found_keywords:
                pattern_id = f"keyword_{pattern_type}_{hash(tuple(keywords)) % 100000}"
                density = len(found_keywords) / len(keywords) if keywords else 0
                raw_confidence = min(1.0, density * 0.8 + 0.2)
                adjusted_confidence = self._adjust_confidence_with_context(raw_confidence, pattern_type, context)
                pattern = Pattern(
                    pattern_id=pattern_id,
                    pattern_type=f"keyword_{pattern_type}",
                    confidence=adjusted_confidence,
                    occurrences=len(found_keywords),
                    first_seen=datetime.now(),
                    last_seen=datetime.now(),
                    metadata={
                        'keywords_found': found_keywords,
                        'keyword_density': density,
                        'match_strategy': 'keyword',
                        'context': context
                    },
                    match_strategy=MatchStrategy.KEYWORD
                )
                patterns.append(pattern)
        return patterns

    def _analyze_structure(self, data: dict, context: Optional[Dict]) -> List[Pattern]:
        patterns = []
        keys = sorted(data.keys())
        key_types = {k: type(v).__name__ for k, v in data.items()}
        key_pattern = f"structure_{len(keys)}_keys"
        pattern_id = f"structure_{hash(tuple(keys)) % 100000}"
        pattern = Pattern(
            pattern_id=pattern_id,
            pattern_type=key_pattern,
            confidence=0.75,
            occurrences=1,
            first_seen=datetime.now(),
            last_seen=datetime.now(),
            metadata={
                'keys': keys,
                'key_types': key_types,
                'depth': self._compute_dict_depth(data),
                'context': context
            },
            match_strategy=MatchStrategy.STRUCTURAL
        )
        patterns.append(pattern)
        nested_dicts = {k: v for k, v in data.items() if isinstance(v, dict)}
        if nested_dicts:
            for key, nested in nested_dicts.items():
                nested_patterns = self._analyze_structure(nested, {**(context or {}), 'parent_key': key})
                patterns.extend(nested_patterns)
        return patterns

    def _analyze_collection(self, data: list, context: Optional[Dict]) -> List[Pattern]:
        patterns = []
        element_types = Counter(type(v).__name__ for v in data[:100])
        dominant_type = element_types.most_common(1)[0][0] if element_types else "unknown"
        pattern_id = f"collection_{dominant_type}_{len(data)}_items"
        pattern = Pattern(
            pattern_id=pattern_id,
            pattern_type=f"collection_{dominant_type}",
            confidence=min(0.9, 0.5 + len(data) * 0.01),
            occurrences=len(data),
            first_seen=datetime.now(),
            last_seen=datetime.now(),
            metadata={
                'size': len(data),
                'element_types': dict(element_types),
                'dominant_type': dominant_type,
                'context': context
            },
            match_strategy=MatchStrategy.STRUCTURAL
        )
        patterns.append(pattern)
        if all(isinstance(v, dict) for v in data[:50]):
            dict_patterns = self._analyze_homogeneous_dict_collection(data, context)
            patterns.extend(dict_patterns)
        return patterns

    def _analyze_homogeneous_dict_collection(self, data: List[dict], context: Optional[Dict]) -> List[Pattern]:
        patterns = []
        if not data:
            return patterns
        all_keys = set()
        key_frequencies = Counter()
        for item in data:
            keys = tuple(sorted(item.keys()))
            all_keys.add(keys)
            key_frequencies[keys] += 1
        most_common_key_set = key_frequencies.most_common(1)[0][0] if key_frequencies else tuple()
        if len(most_common_key_set) >= 2:
            pattern_id = f"collection_schema_{hash(most_common_key_set) % 100000}"
            pattern = Pattern(
                pattern_id=pattern_id,
                pattern_type="collection_schema",
                confidence=min(0.95, key_frequencies[most_common_key_set] / len(data)),
                occurrences=key_frequencies[most_common_key_set],
                first_seen=datetime.now(),
                last_seen=datetime.now(),
                metadata={
                    'schema_keys': list(most_common_key_set),
                    'schema_frequency': key_frequencies[most_common_key_set] / len(data),
                    'unique_schemas': len(all_keys),
                    'context': context
                },
                match_strategy=MatchStrategy.STRUCTURAL
            )
            patterns.append(pattern)
        return patterns

    def _compute_dict_depth(self, data: dict, depth: int = 0) -> int:
        if not isinstance(data, dict) or not data:
            return depth
        return max(self._compute_dict_depth(v, depth + 1) for v in data.values() if isinstance(v, dict))

    def _adjust_confidence_with_context(self, base_confidence: float, pattern_type: str, context: Optional[Dict]) -> float:
        if not context:
            return base_confidence
        adjustment = 0.0
        context_relevance = 0
        for key in ['domain', 'user_role', 'content_type']:
            if key in context:
                context_relevance += 1
        if context_relevance > 0:
            adjustment += 0.05 * context_relevance
        if 'importance' in context:
            importance = context['importance']
            if isinstance(importance, (int, float)) and 0 <= importance <= 1:
                adjustment += importance * 0.1
        return min(1.0, max(0.1, base_confidence + adjustment))

    def _deduplicate_patterns(self, patterns: List[Pattern]) -> List[Pattern]:
        seen = {}
        deduped = []
        for pattern in patterns:
            key = f"{pattern.pattern_type}_{pattern.pattern_id}"
            if key not in seen:
                seen[key] = pattern
                deduped.append(pattern)
            else:
                seen[key].occurrences += pattern.occurrences
        return deduped

    def _apply_pattern_decay(self) -> None:
        now = datetime.now()
        decayed_count = 0
        for pattern_id, pattern in list(self.patterns.items()):
            hours_since_last_seen = (now - pattern.last_seen).total_seconds() / 3600
            if hours_since_last_seen > self.config.decay_interval_hours:
                decay_amount = self.config.decay_rate * (hours_since_last_seen / self.config.decay_interval_hours)
                pattern.confidence = max(0.1, pattern.confidence - decay_amount)
                pattern.decay_factor = max(0.1, 1.0 - decay_amount)
                decayed_count += 1
            age_days = (now - pattern.first_seen).total_seconds() / 86400
            if age_days > self.config.max_pattern_age_days and pattern.confidence < 0.3:
                del self.patterns[pattern_id]
                if pattern_id in self.confidence_history:
                    del self.confidence_history[pattern_id]
        if decayed_count > 0:
            logger.debug(f"Applied decay to {decayed_count} patterns")

    def _cluster_patterns(self) -> None:
        patterns_by_type = defaultdict(list)
        for pattern in self.patterns.values():
            patterns_by_type[pattern.pattern_type].append(pattern)
        for pattern_type, type_patterns in patterns_by_type.items():
            if len(type_patterns) < 2:
                continue
            existing_cluster_ids = {p.cluster_id for p in type_patterns if p.cluster_id}
            for p1, p2 in combinations(type_patterns, 2):
                similarity = self._compute_pattern_similarity(p1, p2)
                if similarity >= self.config.cluster_similarity_threshold:
                    if p1.cluster_id and p2.cluster_id and p1.cluster_id == p2.cluster_id:
                        continue
                    if p1.cluster_id is None and p2.cluster_id is None:
                        cluster_id = f"cluster_{pattern_type}_{len(self.clusters)}"
                        cluster = PatternCluster(
                            cluster_id=cluster_id,
                            pattern_type=pattern_type,
                            pattern_ids=[p1.pattern_id, p2.pattern_id],
                            centroid_confidence=(p1.confidence + p2.confidence) / 2,
                            metadata={'similarity': similarity}
                        )
                        self.clusters[cluster_id] = cluster
                        p1.cluster_id = cluster_id
                        p2.cluster_id = cluster_id
                    elif p1.cluster_id and not p2.cluster_id:
                        p2.cluster_id = p1.cluster_id
                        if p1.cluster_id in self.clusters:
                            self.clusters[p1.cluster_id].pattern_ids.append(p2.pattern_id)
                            self.clusters[p1.cluster_id].last_updated = datetime.now()
                    elif p2.cluster_id and not p1.cluster_id:
                        p1.cluster_id = p2.cluster_id
                        if p2.cluster_id in self.clusters:
                            self.clusters[p2.cluster_id].pattern_ids.append(p1.pattern_id)
                            self.clusters[p2.cluster_id].last_updated = datetime.now()
                    elif p1.cluster_id and p2.cluster_id and p1.cluster_id != p2.cluster_id:
                        self._merge_clusters(p1.cluster_id, p2.cluster_id, pattern_type)
            for cluster in self.clusters.values():
                if cluster.pattern_type == pattern_type and cluster.pattern_ids:
                    cluster_patterns = [self.patterns[pid] for pid in cluster.pattern_ids if pid in self.patterns]
                    if cluster_patterns:
                        cluster.centroid_confidence = sum(p.confidence for p in cluster_patterns) / len(cluster_patterns)
                        cluster.last_updated = datetime.now()

    def _compute_pattern_similarity(self, p1: Pattern, p2: Pattern) -> float:
        from difflib import SequenceMatcher
        scores = []
        if p1.pattern_type == p2.pattern_type:
            scores.append(0.3)
        if isinstance(p1.metadata, dict) and isinstance(p2.metadata, dict):
            keys1 = set(p1.metadata.get('keys', [])) if 'keys' in p1.metadata else set()
            keys2 = set(p2.metadata.get('keys', [])) if 'keys' in p2.metadata else set()
            if keys1 and keys2:
                jaccard = len(keys1 & keys2) / len(keys1 | keys2) if keys1 | keys2 else 0
                scores.append(jaccard * 0.4)
            matches1 = set(p1.metadata.get('matches', [])) if 'matches' in p1.metadata else set()
            matches2 = set(p2.metadata.get('matches', [])) if 'matches' in p2.metadata else set()
            if matches1 and matches2:
                jaccard = len(matches1 & matches2) / len(matches1 | matches2) if matches1 | matches2 else 0
                scores.append(jaccard * 0.3)
        confidence_diff = 1.0 - abs(p1.confidence - p2.confidence)
        scores.append(confidence_diff * 0.2)
        occ_diff = 1.0 - min(abs(p1.occurrences - p2.occurrences) / max(p1.occurrences, p2.occurrences, 1), 1.0)
        scores.append(occ_diff * 0.1)
        return sum(scores) if scores else 0.0

    def _merge_clusters(self, cluster_id_1: str, cluster_id_2: str, pattern_type: str) -> None:
        if cluster_id_1 not in self.clusters or cluster_id_2 not in self.clusters:
            return
        cluster_1 = self.clusters[cluster_id_1]
        cluster_2 = self.clusters[cluster_id_2]
        target = cluster_1 if len(cluster_1.pattern_ids) >= len(cluster_2.pattern_ids) else cluster_2
        source = cluster_2 if target == cluster_1 else cluster_1
        target.pattern_ids.extend(source.pattern_ids)
        target.pattern_ids = list(set(target.pattern_ids))
        target.last_updated = datetime.now()
        for pid in source.pattern_ids:
            if pid in self.patterns:
                self.patterns[pid].cluster_id = target.cluster_id
        del self.clusters[source.cluster_id]

    def _update_correlations(self, new_patterns: List[Pattern]) -> None:
        base_ids = set(p.pattern_id for p in new_patterns)
        if not base_ids:
            return
        recent_window = max(50, len(self.pattern_history) // 2)
        recent_history = self.pattern_history[-recent_window:]
        for hist_entry in recent_history:
            hist_pid = hist_entry['pattern_id']
            if hist_pid in base_ids:
                continue
            for base_pid in base_ids:
                if base_pid not in self.correlations:
                    self.correlations[base_pid] = {}
                if hist_pid not in self.correlations[base_pid]:
                    self.correlations[base_pid][hist_pid] = PatternCorrelation(
                        source_id=base_pid,
                        target_id=hist_pid,
                        correlation_score=0.0,
                        co_occurrence_count=0,
                        last_observed=datetime.now()
                    )
                corr = self.correlations[base_pid][hist_pid]
                corr.co_occurrence_count += 1
                corr.last_observed = datetime.now()
                corr.correlation_score = min(1.0, corr.co_occurrence_count / recent_window * 5)
        for pid in base_ids:
            if pid in self.patterns:
                scores = {}
                if pid in self.correlations:
                    for other_pid, corr in self.correlations[pid].items():
                        if corr.correlation_score > 0.3 and other_pid in self.patterns:
                            scores[other_pid] = corr.correlation_score
                self.patterns[pid].correlation_scores = scores

    def _enforce_pattern_limits(self) -> None:
        type_counts = Counter(p.pattern_type for p in self.patterns.values())
        for pattern_type, count in type_counts.items():
            if count > self.config.max_patterns_per_type:
                to_remove = sorted(
                    [p for p in self.patterns.values() if p.pattern_type == pattern_type],
                    key=lambda p: (p.confidence, p.occurrences)
                )[:count - self.config.max_patterns_per_type]
                for p in to_remove:
                    del self.patterns[p.pattern_id]
                    if p.pattern_id in self.confidence_history:
                        del self.confidence_history[p.pattern_id]
                    if p.pattern_id in self.correlations:
                        del self.correlations[p.pattern_id]

    def get_patterns_by_type(self, pattern_type: str) -> List[Pattern]:
        return [p for p in self.patterns.values() if p.pattern_type == pattern_type]

    def get_patterns_by_cluster(self, cluster_id: str) -> List[Pattern]:
        return [p for p in self.patterns.values() if p.cluster_id == cluster_id]

    def get_top_patterns(self, limit: int = 10) -> List[Pattern]:
        sorted_patterns = sorted(
            self.patterns.values(),
            key=lambda p: (p.confidence, p.occurrences),
            reverse=True
        )
        return sorted_patterns[:limit]

    def get_decaying_patterns(self, threshold: float = 0.5) -> List[Pattern]:
        return [p for p in self.patterns.values() if p.decay_factor < threshold]

    def get_correlated_patterns(self, pattern_id: str, min_score: float = 0.5) -> List[Tuple[str, float]]:
        if pattern_id not in self.correlations:
            return []
        return sorted(
            [(pid, corr.correlation_score) for pid, corr in self.correlations[pattern_id].items()
             if corr.correlation_score >= min_score and pid in self.patterns],
            key=lambda x: x[1],
            reverse=True
        )

    def find_similar_patterns(self, target: Pattern, top_n: int = 5) -> List[Tuple[str, float]]:
        scores = []
        for pattern in self.patterns.values():
            if pattern.pattern_id == target.pattern_id:
                continue
            similarity = self._compute_pattern_similarity(target, pattern)
            scores.append((pattern.pattern_id, similarity))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_n]

    def generate_rules_from_patterns(self) -> List[Dict]:
        suggested_rules = []
        for pattern in self.patterns.values():
            if pattern.confidence >= self.config.min_confidence and pattern.occurrences >= self.config.min_occurrences_for_rule:
                rule = {
                    'rule_id': f"auto_{pattern.pattern_id}",
                    'pattern_type': pattern.pattern_type,
                    'confidence': pattern.confidence,
                    'occurrences': pattern.occurrences,
                    'based_on_pattern': pattern.pattern_id,
                    'cluster_id': pattern.cluster_id,
                    'correlations': pattern.correlation_scores,
                    'suggested_action': 'review',
                    'created_at': datetime.now().isoformat()
                }
                suggested_rules.append(rule)
        for cluster in self.clusters.values():
            if len(cluster.pattern_ids) >= 3 and cluster.centroid_confidence >= self.config.min_confidence:
                rule = {
                    'rule_id': f"cluster_{cluster.cluster_id}",
                    'pattern_type': cluster.pattern_type,
                    'confidence': cluster.centroid_confidence,
                    'occurrences': len(cluster.pattern_ids),
                    'based_on_pattern': cluster.pattern_type,
                    'cluster_patterns': cluster.pattern_ids,
                    'suggested_action': 'review_cluster',
                    'created_at': datetime.now().isoformat()
                }
                suggested_rules.append(rule)
        logger.info(f"Generated {len(suggested_rules)} rule suggestions")
        return suggested_rules

    def export_patterns(self, include_history: Optional[bool] = None) -> Dict:
        if include_history is None:
            include_history = self.config.export_include_history
        data = {
            'export_version': '1.0',
            'exported_at': datetime.now().isoformat(),
            'config': asdict(self.config),
            'patterns': {},
            'clusters': {},
            'statistics': self.get_statistics()
        }
        for pid, pat in self.patterns.items():
            pat_dict = asdict(pat)
            pat_dict['first_seen'] = pat.first_seen.isoformat()
            pat_dict['last_seen'] = pat.last_seen.isoformat()
            pat_dict['match_strategy'] = pat.match_strategy.value
            data['patterns'][pid] = pat_dict
        for cid, clus in self.clusters.items():
            clus_dict = asdict(clus)
            clus_dict['created_at'] = clus.created_at.isoformat()
            clus_dict['last_updated'] = clus.last_updated.isoformat()
            data['clusters'][cid] = clus_dict
        if include_history:
            data['history'] = [
                {k: v.isoformat() if isinstance(v, datetime) else v for k, v in h.items()}
                for h in self.pattern_history[-500:]
            ]
        return data

    def import_patterns(self, data: Dict) -> Tuple[int, int]:
        imported_patterns = 0
        imported_clusters = 0
        if 'patterns' in data:
            for pid, pat_dict in data['patterns'].items():
                if pid in self.patterns:
                    continue
                pat_dict_cpy = dict(pat_dict)
                pat_dict_cpy['first_seen'] = datetime.fromisoformat(pat_dict_cpy['first_seen'])
                pat_dict_cpy['last_seen'] = datetime.fromisoformat(pat_dict_cpy['last_seen'])
                if 'match_strategy' in pat_dict_cpy:
                    pat_dict_cpy['match_strategy'] = MatchStrategy(pat_dict_cpy['match_strategy'])
                pat = Pattern(**pat_dict_cpy)
                self.patterns[pid] = pat
                imported_patterns += 1
        if 'clusters' in data:
            for cid, clus_dict in data['clusters'].items():
                if cid in self.clusters:
                    continue
                clus_dict_cpy = dict(clus_dict)
                clus_dict_cpy['created_at'] = datetime.fromisoformat(clus_dict_cpy['created_at'])
                clus_dict_cpy['last_updated'] = datetime.fromisoformat(clus_dict_cpy['last_updated'])
                clus = PatternCluster(**clus_dict_cpy)
                self.clusters[cid] = clus
                imported_clusters += 1
        logger.info(f"Imported {imported_patterns} patterns and {imported_clusters} clusters")
        return imported_patterns, imported_clusters

    def get_pattern_confidence_trend(self, pattern_id: str) -> Optional[Dict]:
        if pattern_id not in self.confidence_history or len(self.confidence_history[pattern_id]) < 2:
            return None
        hist = self.confidence_history[pattern_id]
        return {
            'pattern_id': pattern_id,
            'current_confidence': hist[-1],
            'initial_confidence': hist[0],
            'max_confidence': max(hist),
            'min_confidence': min(hist),
            'change': hist[-1] - hist[0],
            'volatility': statistics.stdev(hist) if len(hist) > 1 else 0,
            'observations': len(hist)
        }

    def reset(self) -> None:
        self.patterns.clear()
        self.pattern_history.clear()
        self.observation_count = 0
        self.clusters.clear()
        self.correlations.clear()
        self.confidence_history.clear()
        self._archived_patterns.clear()
        self._subscriptions.clear()
        self._custom_extractors.clear()
        logger.info("PatternRecognitionEngine reset")

    def get_statistics(self) -> Dict:
        pattern_types = Counter(p.pattern_type for p in self.patterns.values())
        match_strategies = Counter(p.match_strategy.value for p in self.patterns.values())
        active_today = sum(
            1 for p in self.patterns.values()
            if p.last_seen.date() == datetime.now().date()
        )
        return {
            'total_patterns': len(self.patterns),
            'pattern_types': dict(pattern_types),
            'match_strategies': dict(match_strategies),
            'observations': self.observation_count,
            'templates': len(self.pattern_templates),
            'keyword_patterns': sum(len(v) for v in self.keyword_patterns.values()),
            'total_clusters': len(self.clusters),
            'active_today': active_today,
            'high_confidence_patterns': len([p for p in self.patterns.values() if p.confidence >= 0.9]),
            'decaying_patterns': len([p for p in self.patterns.values() if p.decay_factor < 0.5]),
            'correlated_pattern_pairs': sum(len(c) for c in self.correlations.values()),
            'average_confidence': statistics.mean([p.confidence for p in self.patterns.values()]) if self.patterns else 0,
            'average_occurrences': statistics.mean([p.occurrences for p in self.patterns.values()]) if self.patterns else 0,
            'total_history_entries': len(self.pattern_history),
            'config': asdict(self.config)
        }

    def get_detailed_report(self) -> Dict:
        stats = self.get_statistics()
        top_patterns = self.get_top_patterns(20)
        top_patterns_data = []
        for p in top_patterns:
            confidence_trend = self.get_pattern_confidence_trend(p.pattern_id)
            correlations = self.get_correlated_patterns(p.pattern_id)
            top_patterns_data.append({
                'pattern_id': p.pattern_id,
                'pattern_type': p.pattern_type,
                'confidence': p.confidence,
                'occurrences': p.occurrences,
                'decay_factor': p.decay_factor,
                'cluster_id': p.cluster_id,
                'match_strategy': p.match_strategy.value,
                'first_seen': p.first_seen.isoformat(),
                'last_seen': p.last_seen.isoformat(),
                'confidence_trend': confidence_trend,
                'correlation_count': len(correlations)
            })
        return {
            'statistics': stats,
            'top_patterns': top_patterns_data,
            'clusters': [
                {
                    'cluster_id': c.cluster_id,
                    'pattern_type': c.pattern_type,
                    'pattern_count': len(c.pattern_ids),
                    'centroid_confidence': c.centroid_confidence,
                    'age_days': (datetime.now() - c.created_at).total_seconds() / 86400
                }
                for c in self.clusters.values()
            ],
            'template_summary': {
                t: self.pattern_templates[t] for t in list(self.pattern_templates.keys())[:20]
            },
            'keyword_summary': {
                t: len(kw) for t, kw in list(self.keyword_patterns.items())[:20]
            }
        }

    def validate_pattern(self, pattern: Pattern) -> Dict:
        checks = {
            'has_id': bool(pattern.pattern_id),
            'has_type': bool(pattern.pattern_type),
            'confidence_valid': 0.0 <= pattern.confidence <= 1.0,
            'occurrences_valid': pattern.occurrences >= 0,
            'dates_valid': pattern.first_seen <= pattern.last_seen,
            'decay_valid': 0.0 <= pattern.decay_factor <= 1.0,
            'strategy_valid': isinstance(pattern.match_strategy, MatchStrategy),
            'metadata_valid': isinstance(pattern.metadata, dict),
        }
        issues = []
        if not checks['has_id']:
            issues.append("Missing pattern_id")
        if not checks['has_type']:
            issues.append("Missing pattern_type")
        if not checks['confidence_valid']:
            issues.append(f"Confidence {pattern.confidence} out of range [0,1]")
        if not checks['dates_valid']:
            issues.append("first_seen after last_seen")
        if pattern.occurrences < 0:
            issues.append("Negative occurrences")
        if checks['decay_valid'] and pattern.decay_factor < 0.3:
            issues.append(f"Pattern decaying: factor={pattern.decay_factor:.2f}")
        score = sum(1 for v in checks.values() if v) / len(checks) if checks else 1.0
        return {
            'pattern_id': pattern.pattern_id,
            'is_valid': len(issues) == 0,
            'validation_score': score,
            'checks': checks,
            'issues': issues,
            'needs_attention': score < 0.7 or len(issues) > 0,
            'validated_at': datetime.now().isoformat(),
        }

    def validate_all_patterns(self) -> Dict:
        results = {}
        valid_count = 0
        for pid, pattern in self.patterns.items():
            result = self.validate_pattern(pattern)
            results[pid] = result
            if result['is_valid']:
                valid_count += 1
        issues_summary = Counter()
        for result in results.values():
            for issue in result['issues']:
                issues_summary[issue] += 1
        return {
            'total_patterns': len(self.patterns),
            'valid_patterns': valid_count,
            'invalid_patterns': len(self.patterns) - valid_count,
            'validation_rate': valid_count / max(len(self.patterns), 1),
            'per_pattern': results,
            'common_issues': dict(issues_summary.most_common(10)),
        }

    def get_pattern_lifecycle_summary(self) -> Dict:
        now = datetime.now()
        age_buckets = {'<1h': 0, '1-24h': 0, '1-7d': 0, '7-30d': 0, '>30d': 0}
        for pattern in self.patterns.values():
            age_hours = (now - pattern.first_seen).total_seconds() / 3600
            if age_hours < 1:
                age_buckets['<1h'] += 1
            elif age_hours < 24:
                age_buckets['1-24h'] += 1
            elif age_hours < 168:
                age_buckets['1-7d'] += 1
            elif age_hours < 720:
                age_buckets['7-30d'] += 1
            else:
                age_buckets['>30d'] += 1
        inactive = [p for p in self.patterns.values()
                    if (now - p.last_seen).total_seconds() > 86400 * 7]
        stale = [p for p in self.patterns.values()
                 if p.confidence < 0.3 and p.decay_factor < 0.5]
        return {
            'total_patterns': len(self.patterns),
            'age_distribution': age_buckets,
            'inactive_7d': len(inactive),
            'stale_patterns': len(stale),
            'archivable_patterns': len(inactive) + len(stale),
            'most_recent': max((p.last_seen for p in self.patterns.values()), default=now).isoformat(),
            'oldest': min((p.first_seen for p in self.patterns.values()), default=now).isoformat(),
        }

    def archive_stale_patterns(self, age_days: int = 30, confidence_threshold: float = 0.3) -> int:
        now = datetime.now()
        to_archive = []
        for pid, pattern in list(self.patterns.items()):
            age_days_val = (now - pattern.last_seen).total_seconds() / 86400
            if age_days_val > age_days and pattern.confidence < confidence_threshold:
                to_archive.append(pid)
        for pid in to_archive:
            archived = {
                'pattern': asdict(self.patterns[pid]),
                'archived_at': now.isoformat(),
                'confidence_history': self.confidence_history.get(pid, []),
            }
            self._archived_patterns[pid] = archived
            del self.patterns[pid]
            if pid in self.confidence_history:
                del self.confidence_history[pid]
            if pid in self.correlations:
                del self.correlations[pid]
        logger.info(f"Archived {len(to_archive)} stale patterns")
        return len(to_archive)

    def restore_archived_pattern(self, pattern_id: str) -> bool:
        if pattern_id not in self._archived_patterns:
            return False
        archived = self._archived_patterns.pop(pattern_id)
        pat_dict = archived['pattern']
        pat_dict['first_seen'] = datetime.fromisoformat(pat_dict['first_seen'])
        pat_dict['last_seen'] = datetime.now()
        pat_dict['match_strategy'] = MatchStrategy(pat_dict['match_strategy'])
        pattern = Pattern(**pat_dict)
        self.patterns[pattern_id] = pattern
        if archived.get('confidence_history'):
            self.confidence_history[pattern_id] = archived['confidence_history']
        logger.info(f"Restored archived pattern: {pattern_id}")
        return True

    def analyze_text_semantic(self, text: str, context: Optional[Dict] = None) -> List[Pattern]:
        patterns = []
        words = text.lower().split()
        if len(words) < 3:
            return patterns
        word_freq = Counter(words)
        total = len(words)
        ngrams = self._extract_ngrams(words, 2)
        trigrams = self._extract_ngrams(words, 3)
        semantic_clusters = {
            'technical': {'api', 'endpoint', 'request', 'response', 'server', 'client',
                          'database', 'cache', 'protocol', 'schema', 'query', 'payload'},
            'security': {'auth', 'token', 'password', 'permission', 'access', 'role',
                         'encrypt', 'hash', 'salt', 'certificate', 'session', 'cookie'},
            'data': {'json', 'xml', 'csv', 'record', 'field', 'attribute', 'value',
                     'key', 'entry', 'row', 'column', 'table', 'index'},
            'error': {'error', 'fail', 'exception', 'timeout', 'crash', 'invalid',
                      'missing', 'denied', 'rejected', 'abort', 'broken'},
            'structure': {'class', 'function', 'method', 'variable', 'module', 'package',
                          'import', 'config', 'setting', 'option', 'param'},
        }
        for cluster_name, cluster_words in semantic_clusters.items():
            matches = [w for w in words if w in cluster_words]
            if matches:
                density = len(matches) / max(len(cluster_words), 1)
                if density > 0.1:
                    pattern_id = f"semantic_{cluster_name}_{hash(text) % 100000}"
                    adjusted_conf = self._adjust_confidence_with_context(
                        min(0.8, density * 1.5), f"semantic_{cluster_name}", context
                    )
                    pattern = Pattern(
                        pattern_id=pattern_id,
                        pattern_type=f"semantic_{cluster_name}",
                        confidence=adjusted_conf,
                        occurrences=len(matches),
                        first_seen=datetime.now(),
                        last_seen=datetime.now(),
                        metadata={
                            'matches': matches[:10],
                            'words_matched': len(matches),
                            'cluster': cluster_name,
                            'match_strategy': 'semantic',
                            'context': context,
                        },
                        match_strategy=MatchStrategy.SEMANTIC
                    )
                    patterns.append(pattern)
        freq_terms = [word for word, count in word_freq.most_common(5) if count > 1]
        if len(freq_terms) >= 3:
            pattern_id = f"semantic_freq_{hash(tuple(freq_terms)) % 100000}"
            pattern = Pattern(
                pattern_id=pattern_id,
                pattern_type="semantic_frequent_terms",
                confidence=min(0.6, len(freq_terms) * 0.12),
                occurrences=len(freq_terms),
                first_seen=datetime.now(),
                last_seen=datetime.now(),
                metadata={
                    'frequent_terms': freq_terms,
                    'match_strategy': 'semantic',
                    'context': context,
                },
                match_strategy=MatchStrategy.SEMANTIC
            )
            patterns.append(pattern)
        if ngrams:
            top_bigram = ngrams.most_common(1)[0]
            if top_bigram[1] >= 2:
                pattern_id = f"semantic_bigram_{hash(top_bigram[0]) % 100000}"
                pattern = Pattern(
                    pattern_id=pattern_id,
                    pattern_type="semantic_bigram",
                    confidence=min(0.5, top_bigram[1] * 0.1),
                    occurrences=top_bigram[1],
                    first_seen=datetime.now(),
                    last_seen=datetime.now(),
                    metadata={
                        'bigram': top_bigram[0],
                        'count': top_bigram[1],
                        'match_strategy': 'semantic',
                        'context': context,
                    },
                    match_strategy=MatchStrategy.SEMANTIC
                )
                patterns.append(pattern)
        return patterns

    def _extract_ngrams(self, words: List[str], n: int) -> Counter:
        if len(words) < n:
            return Counter()
        ngrams = tuple(' '.join(words[i:i + n]) for i in range(len(words) - n + 1))
        return Counter(ngrams)

    def analyze_data_advanced(self, data: Any, context: Optional[Dict] = None,
                               strategies: Optional[List[MatchStrategy]] = None) -> List[Pattern]:
        all_patterns = []
        if strategies is None:
            strategies = [MatchStrategy.REGEX, MatchStrategy.KEYWORD,
                          MatchStrategy.SEMANTIC, MatchStrategy.STRUCTURAL]
        if isinstance(data, str):
            if MatchStrategy.REGEX in strategies:
                all_patterns.extend(self._analyze_text_regex(data, context))
            if MatchStrategy.KEYWORD in strategies:
                all_patterns.extend(self._analyze_text_keywords(data, context))
            if MatchStrategy.SEMANTIC in strategies:
                all_patterns.extend(self.analyze_text_semantic(data, context))
        elif isinstance(data, dict):
            if MatchStrategy.STRUCTURAL in strategies:
                all_patterns.extend(self._analyze_structure(data, context))
            for value in data.values():
                if isinstance(value, str):
                    all_patterns.extend(self.analyze_data_advanced(value, context, strategies))
        elif isinstance(data, list):
            if MatchStrategy.STRUCTURAL in strategies:
                all_patterns.extend(self._analyze_collection(data, context))
            for item in data:
                all_patterns.extend(self.analyze_data_advanced(item, context, strategies))
        all_patterns = self._deduplicate_patterns(all_patterns)
        for pattern in all_patterns:
            self._register_or_update_pattern(pattern, context, data)
        if self.config.enable_auto_decay and self.observation_count % 10 == 0:
            self._apply_pattern_decay()
        if self.config.enable_clustering and len(self.patterns) > 5 and self.observation_count % 20 == 0:
            self._cluster_patterns()
        if self.config.enable_correlation and len(self.pattern_history) > 10:
            self._update_correlations(all_patterns)
        self._enforce_pattern_limits()
        return all_patterns

    def _register_or_update_pattern(self, pattern: Pattern, context: Optional[Dict], data: Any) -> None:
        self.observation_count += 1
        if pattern.pattern_id in self.patterns:
            existing = self.patterns[pattern.pattern_id]
            existing.occurrences += 1
            existing.last_seen = datetime.now()
            increment = self.config.learning_rate * (1.0 - existing.confidence)
            existing.confidence = min(1.0, existing.confidence + increment)
            if pattern.metadata and context:
                existing.metadata['last_context'] = context
                existing.metadata['last_value'] = str(data)[:200]
            self.confidence_history[pattern.pattern_id].append(existing.confidence)
        else:
            self.patterns[pattern.pattern_id] = pattern
            self.confidence_history[pattern.pattern_id].append(pattern.confidence)
        self.pattern_history.append({
            'pattern_id': pattern.pattern_id,
            'pattern_type': pattern.pattern_type,
            'timestamp': datetime.now(),
            'observation': self.observation_count,
            'context': context,
        })

    def get_pattern_dependencies(self, pattern_id: str) -> Dict:
        if pattern_id not in self.patterns:
            return {}
        pattern = self.patterns[pattern_id]
        deps = {
            'depends_on': [],
            'depended_by': [],
        }
        for other_id, other in self.patterns.items():
            if other_id == pattern_id:
                continue
            if other.pattern_type == pattern.pattern_type:
                deps['depends_on'].append({
                    'pattern_id': other_id,
                    'pattern_type': other.pattern_type,
                    'confidence': other.confidence,
                    'correlation': other.correlation_scores.get(pattern_id, 0.0),
                })
            if pattern_id in other.correlation_scores:
                deps['depended_by'].append({
                    'pattern_id': other_id,
                    'pattern_type': other.pattern_type,
                    'correlation': other.correlation_scores[pattern_id],
                })
        deps['depends_on'].sort(key=lambda x: abs(x['correlation']), reverse=True)
        deps['depended_by'].sort(key=lambda x: abs(x['correlation']), reverse=True)
        return deps

    def analyze_batch(self, data_items: List[Any], context: Optional[Dict] = None) -> List[Dict]:
        results = []
        for i, item in enumerate(data_items):
            item_context = {**(context or {}), 'batch_index': i}
            patterns = self.analyze_data(item, item_context)
            results.append({
                'index': i,
                'patterns_found': len(patterns),
                'pattern_types': list(set(p.pattern_type for p in patterns)),
                'top_confidence': max((p.confidence for p in patterns), default=0.0),
            })
        return results

    def get_engine_performance(self) -> Dict:
        pattern_counts = []
        for pid in list(self.patterns.keys())[:100]:
            conf_hist = self.confidence_history.get(pid, [])
            if conf_hist:
                trend = conf_hist[-1] - conf_hist[0] if len(conf_hist) > 0 else 0
                pattern_counts.append(trend)
        avg_confidence_trend = statistics.mean(pattern_counts) if pattern_counts else 0.0
        type_distribution = Counter(p.pattern_type for p in self.patterns.values())
        strategy_distribution = Counter(p.match_strategy.value for p in self.patterns.values())
        return {
            'total_observations': self.observation_count,
            'total_patterns': len(self.patterns),
            'total_templates': len(self.pattern_templates),
            'total_clusters': len(self.clusters),
            'total_correlations': sum(len(c) for c in self.correlations.values()),
            'average_confidence_trend': round(avg_confidence_trend, 4),
            'type_distribution': dict(type_distribution.most_common(10)),
            'strategy_distribution': dict(strategy_distribution),
            'active_today': sum(1 for p in self.patterns.values()
                                if p.last_seen.date() == datetime.now().date()),
            'decaying_count': len([p for p in self.patterns.values() if p.decay_factor < 0.5]),
            'llm_ready': len(self.patterns) <= 500,
            'memory_estimate_bytes': sum(
                len(pid) + len(json.dumps(asdict(p))) for pid, p in self.patterns.items()
            ) if self.patterns else 0,
        }

    def get_hit_rate(self, pattern_id: str, recent_window: int = 100) -> Optional[float]:
        if pattern_id not in self.patterns:
            return None
        pattern = self.patterns[pattern_id]
        recent_history = [h for h in self.pattern_history[-recent_window:]
                          if h['pattern_id'] == pattern_id]
        if not recent_history:
            return 0.0
        total_recent = len(recent_history)
        if total_recent == 0:
            return 0.0
        return total_recent / min(recent_window, len(self.pattern_history))

    def get_top_patterns_by_type(self, pattern_type: str, limit: int = 10) -> List[Pattern]:
        filtered = [p for p in self.patterns.values() if p.pattern_type == pattern_type]
        filtered.sort(key=lambda p: (p.confidence, p.occurrences), reverse=True)
        return filtered[:limit]

    def get_pattern_evolution(self, pattern_id: str) -> Optional[Dict]:
        if pattern_id not in self.patterns:
            return None
        pattern = self.patterns[pattern_id]
        confidence_hist = self.confidence_history.get(pattern_id, [])
        history_entries = [h for h in self.pattern_history if h['pattern_id'] == pattern_id]
        return {
            'pattern_id': pattern_id,
            'pattern_type': pattern.pattern_type,
            'first_seen': pattern.first_seen.isoformat(),
            'last_seen': pattern.last_seen.isoformat(),
            'lifetime_hours': (pattern.last_seen - pattern.first_seen).total_seconds() / 3600,
            'total_occurrences': pattern.occurrences,
            'confidence_evolution': confidence_hist,
            'confidence_volatility': statistics.stdev(confidence_hist) if len(confidence_hist) > 1 else 0.0,
            'observation_timeline': [
                {'observation': h['observation'], 'timestamp': h['timestamp'].isoformat()}
                for h in history_entries[-20:]
            ],
            'correlation_count': len(pattern.correlation_scores),
            'cluster_affiliation': pattern.cluster_id,
            'current_decay_factor': pattern.decay_factor,
            'match_strategy': pattern.match_strategy.value,
        }

    def compute_pattern_type_statistics(self) -> Dict:
        types = set(p.pattern_type for p in self.patterns.values())
        type_stats = {}
        for pt in types:
            type_patterns = [p for p in self.patterns.values() if p.pattern_type == pt]
            confidences = [p.confidence for p in type_patterns]
            occurrences = [p.occurrences for p in type_patterns]
            type_stats[pt] = {
                'count': len(type_patterns),
                'mean_confidence': statistics.mean(confidences) if confidences else 0.0,
                'max_confidence': max(confidences) if confidences else 0.0,
                'min_confidence': min(confidences) if confidences else 0.0,
                'total_occurrences': sum(occurrences),
                'mean_occurrences': statistics.mean(occurrences) if occurrences else 0.0,
                'strategies': list(set(p.match_strategy.value for p in type_patterns)),
                'cluster_count': len(set(p.cluster_id for p in type_patterns if p.cluster_id)),
            }
        return {
            'total_types': len(type_stats),
            'per_type': type_stats,
            'dominant_type': max(type_stats, key=lambda t: type_stats[t]['count']) if type_stats else None,
            'rarest_type': min(type_stats, key=lambda t: type_stats[t]['count']) if type_stats else None,
        }

    def generate_subscription(self, pattern_type: Optional[str] = None,
                               min_confidence: float = 0.0,
                               callback: Optional[Callable] = None) -> Dict:
        sub_id = f"sub_{uuid.uuid4().hex[:8]}" if hasattr(__import__('uuid'), 'uuid4') else f"sub_{len(self._subscriptions)}"
        subscription = {
            'subscription_id': sub_id,
            'pattern_type': pattern_type,
            'min_confidence': min_confidence,
            'callback': callback,
            'created_at': datetime.now().isoformat(),
            'trigger_count': 0,
            'last_triggered': None,
        }
        self._subscriptions.append(subscription)
        logger.info(f"Created subscription {sub_id} for pattern_type={pattern_type}")
        return {'subscription_id': sub_id, 'active_subscriptions': len(self._subscriptions)}

    def _notify_subscriptions(self, pattern: Pattern) -> None:
        for sub in self._subscriptions:
            if sub['pattern_type'] is not None and sub['pattern_type'] != pattern.pattern_type:
                continue
            if sub['min_confidence'] > 0 and pattern.confidence < sub['min_confidence']:
                continue
            sub['trigger_count'] += 1
            sub['last_triggered'] = datetime.now().isoformat()
            if sub['callback']:
                try:
                    sub['callback'](pattern)
                except Exception as e:
                    logger.warning(f"Subscription callback failed: {e}")

    def train_from_history(self) -> Dict:
        if len(self.pattern_history) < 10:
            return {'trained': False, 'reason': 'insufficient_history'}
        old_count = len(self.patterns)
        time_based_patterns = Counter()
        context_clusters = defaultdict(set)
        for entry in self.pattern_history:
            time_based_patterns[entry['pattern_type']] += 1
            if entry.get('context'):
                ctx_str = json.dumps(entry['context'], sort_keys=True)
                context_clusters[ctx_str].add(entry['pattern_id'])
        pattern_type_freq = Counter()
        for entry in self.pattern_history:
            pattern_type_freq[entry['pattern_type']] += 1
        for ptype, freq in pattern_type_freq.most_common(5):
            if freq >= self.config.min_occurrences_for_rule * 2:
                self.register_template(f"historical_{ptype}", r".*")
                logger.debug(f"Trained historical template: {ptype} (freq={freq})")
        if self.config.enable_clustering:
            for ctx, pids in context_clusters.items():
                if len(pids) >= 3:
                    cluster_id = f"context_cluster_{hash(ctx) % 100000}"
                    for pid in pids:
                        if pid in self.patterns:
                            self.patterns[pid].cluster_id = cluster_id
                    if cluster_id not in self.clusters:
                        self.clusters[cluster_id] = PatternCluster(
                            cluster_id=cluster_id,
                            pattern_type="context_cluster",
                            pattern_ids=list(pids),
                            metadata={'context': ctx}
                        )
        new_count = len(self.patterns)
        return {
            'trained': True,
            'patterns_before': old_count,
            'patterns_after': new_count,
            'new_clusters': len(self.clusters),
            'historical_types_learned': len(pattern_type_freq),
            'context_clusters': len(context_clusters),
        }

    def merge_patterns(self, source_pattern_ids: List[str], target_id: Optional[str] = None) -> Optional[Pattern]:
        valid_ids = [pid for pid in source_pattern_ids if pid in self.patterns]
        if len(valid_ids) < 2:
            return None
        patterns_to_merge = [self.patterns[pid] for pid in valid_ids]
        merged_type = patterns_to_merge[0].pattern_type
        merged_confidence = statistics.mean(p.confidence for p in patterns_to_merge)
        merged_occurrences = sum(p.occurrences for p in patterns_to_merge)
        merged_first_seen = min(p.first_seen for p in patterns_to_merge)
        merged_last_seen = max(p.last_seen for p in patterns_to_merge)
        merged_metadata = {}
        for p in patterns_to_merge:
            merged_metadata.update(p.metadata)
        merged_metadata['merged_from'] = valid_ids
        merged_metadata['merge_count'] = len(valid_ids)
        merged_id = target_id or f"merged_{hash(tuple(valid_ids)) % 100000}"
        merged_pattern = Pattern(
            pattern_id=merged_id,
            pattern_type=merged_type,
            confidence=merged_confidence,
            occurrences=merged_occurrences,
            first_seen=merged_first_seen,
            last_seen=merged_last_seen,
            metadata=merged_metadata,
            match_strategy=MatchStrategy.HYBRID,
        )
        self.patterns[merged_id] = merged_pattern
        for pid in valid_ids:
            if pid != merged_id:
                del self.patterns[pid]
                if pid in self.confidence_history:
                    del self.confidence_history[pid]
        logger.info(f"Merged {len(valid_ids)} patterns into {merged_id}")
        return merged_pattern
