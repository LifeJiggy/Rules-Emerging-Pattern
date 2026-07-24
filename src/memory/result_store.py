"""In-memory result store with query, aggregation, retention pruning, and export."""

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class Severity(Enum):
    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class EvalResult:
    result_id: str
    rule_id: str
    tier: str
    severity: Severity
    score: float
    passed: bool
    details: Dict[str, Any]
    created_at: float = 0.0
    session_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: Set[str] = field(default_factory=set)


@dataclass
class ResultStoreConfig:
    max_results: int = 50000
    max_age_seconds: float = 86400.0
    prune_on_insert: bool = True
    prune_interval: float = 300.0
    enable_stats: bool = True
    max_results_per_rule: int = 1000
    max_results_per_session: int = 5000
    track_timestamps: bool = True
    default_export_format: str = "json"


class ResultStore:
    """In-memory result store with query, aggregation, retention pruning, and export."""

    def __init__(self, config: Optional[ResultStoreConfig] = None) -> None:
        self._config = config or ResultStoreConfig()
        self._results: Dict[str, EvalResult] = {}
        self._rule_index: Dict[str, Set[str]] = {}
        self._tier_index: Dict[str, Set[str]] = {}
        self._severity_index: Dict[Severity, Set[str]] = {}
        self._session_index: Dict[str, Set[str]] = {}
        self._tag_index: Dict[str, Set[str]] = {}
        self._lock = threading.RLock()
        self._total_inserts: int = 0
        self._total_queries: int = 0
        self._total_prunes: int = 0
        self._running = True
        if self._config.prune_interval > 0:
            self._start_prune_thread()

    def _start_prune_thread(self) -> None:
        def _loop() -> None:
            while self._running:
                time.sleep(self._config.prune_interval)
                try:
                    self.prune()
                except Exception as exc:
                    logger.error("Prune error: %s", exc)

        thread = threading.Thread(target=_loop, daemon=True)
        thread.start()

    def stop(self) -> None:
        self._running = False

    def _add_to_indexes(self, result: EvalResult) -> None:
        self._rule_index.setdefault(result.rule_id, set()).add(result.result_id)
        self._tier_index.setdefault(result.tier, set()).add(result.result_id)
        self._severity_index.setdefault(result.severity, set()).add(result.result_id)
        if result.session_id:
            self._session_index.setdefault(result.session_id, set()).add(result.result_id)
        for tag in result.tags:
            self._tag_index.setdefault(tag, set()).add(result.result_id)

    def _remove_from_indexes(self, result: EvalResult) -> None:
        self._rule_index.get(result.rule_id, set()).discard(result.result_id)
        self._tier_index.get(result.tier, set()).discard(result.result_id)
        self._severity_index.get(result.severity, set()).discard(result.result_id)
        if result.session_id:
            self._session_index.get(result.session_id, set()).discard(result.result_id)
        for tag in result.tags:
            self._tag_index.get(tag, set()).discard(result.result_id)

    def _enforce_max_results(self) -> None:
        if len(self._results) > self._config.max_results:
            excess = len(self._results) - self._config.max_results
            sorted_results = sorted(
                self._results.values(),
                key=lambda r: r.created_at,
            )
            for r in sorted_results[:excess]:
                self._remove_result(r.result_id)

    def _enforce_max_per_rule(self, rule_id: str) -> None:
        ids = self._rule_index.get(rule_id, set())
        if len(ids) > self._config.max_results_per_rule:
            excess = len(ids) - self._config.max_results_per_rule
            sorted_ids = sorted(ids, key=lambda rid: self._results[rid].created_at)
            for rid in sorted_ids[:excess]:
                self._remove_result(rid)

    def _enforce_max_per_session(self, session_id: str) -> None:
        if not session_id:
            return
        ids = self._session_index.get(session_id, set())
        if len(ids) > self._config.max_results_per_session:
            excess = len(ids) - self._config.max_results_per_session
            sorted_ids = sorted(ids, key=lambda rid: self._results[rid].created_at)
            for rid in sorted_ids[:excess]:
                self._remove_result(rid)

    def _remove_result(self, result_id: str) -> None:
        result = self._results.pop(result_id, None)
        if result is None:
            return
        self._remove_from_indexes(result)

    def store(
        self,
        result_id: str,
        rule_id: str,
        tier: str,
        severity: Severity,
        score: float,
        passed: bool,
        details: Optional[Dict[str, Any]] = None,
        session_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        now = time.time()
        result = EvalResult(
            result_id=result_id,
            rule_id=rule_id,
            tier=tier,
            severity=severity,
            score=score,
            passed=passed,
            details=details or {},
            created_at=now,
            session_id=session_id,
            metadata=metadata or {},
            tags=set(tags or []),
        )
        with self._lock:
            old = self._results.get(result_id)
            if old:
                self._remove_from_indexes(old)
            self._results[result_id] = result
            self._add_to_indexes(result)
            self._total_inserts += 1
            if self._config.prune_on_insert:
                self._enforce_max_results()
                self._enforce_max_per_rule(rule_id)
                if session_id:
                    self._enforce_max_per_session(session_id)

    def store_many(self, results: List[Dict[str, Any]]) -> int:
        count = 0
        for r in results:
            severity = r.get("severity", Severity.INFO)
            if isinstance(severity, str):
                severity = Severity[severity.upper()]
            self.store(
                result_id=r["result_id"],
                rule_id=r["rule_id"],
                tier=r.get("tier", "default"),
                severity=severity,
                score=r.get("score", 0.0),
                passed=r.get("passed", False),
                details=r.get("details"),
                session_id=r.get("session_id", ""),
                metadata=r.get("metadata"),
                tags=r.get("tags"),
            )
            count += 1
        return count

    def get(self, result_id: str) -> Optional[EvalResult]:
        with self._lock:
            self._total_queries += 1
            return self._results.get(result_id)

    def get_by_rule_id(self, rule_id: str) -> List[EvalResult]:
        with self._lock:
            self._total_queries += 1
            ids = self._rule_index.get(rule_id, set())
            return [self._results[rid] for rid in ids if rid in self._results]

    def get_by_tier(self, tier: str) -> List[EvalResult]:
        with self._lock:
            self._total_queries += 1
            ids = self._tier_index.get(tier, set())
            return [self._results[rid] for rid in ids if rid in self._results]

    def get_by_severity(self, severity: Severity) -> List[EvalResult]:
        with self._lock:
            self._total_queries += 1
            ids = self._severity_index.get(severity, set())
            return [self._results[rid] for rid in ids if rid in self._results]

    def get_by_session(self, session_id: str) -> List[EvalResult]:
        with self._lock:
            self._total_queries += 1
            ids = self._session_index.get(session_id, set())
            return [self._results[rid] for rid in ids if rid in self._results]

    def get_by_tag(self, tag: str) -> List[EvalResult]:
        with self._lock:
            self._total_queries += 1
            ids = self._tag_index.get(tag, set())
            return [self._results[rid] for rid in ids if rid in self._results]

    def get_by_time_range(self, start: float, end: float) -> List[EvalResult]:
        with self._lock:
            self._total_queries += 1
            return [
                r for r in self._results.values()
                if start <= r.created_at <= end
            ]

    def query(
        self,
        rule_id: Optional[str] = None,
        tier: Optional[str] = None,
        severity: Optional[Severity] = None,
        session_id: Optional[str] = None,
        tag: Optional[str] = None,
        passed: Optional[bool] = None,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[EvalResult]:
        with self._lock:
            self._total_queries += 1
            results = list(self._results.values())
            if rule_id is not None:
                ids = self._rule_index.get(rule_id, set())
                results = [r for r in results if r.result_id in ids]
            if tier is not None:
                ids = self._tier_index.get(tier, set())
                results = [r for r in results if r.result_id in ids]
            if severity is not None:
                ids = self._severity_index.get(severity, set())
                results = [r for r in results if r.result_id in ids]
            if session_id is not None:
                ids = self._session_index.get(session_id, set())
                results = [r for r in results if r.result_id in ids]
            if tag is not None:
                ids = self._tag_index.get(tag, set())
                results = [r for r in results if r.result_id in ids]
            if passed is not None:
                results = [r for r in results if r.passed == passed]
            if time_start is not None:
                results = [r for r in results if r.created_at >= time_start]
            if time_end is not None:
                results = [r for r in results if r.created_at <= time_end]
            if min_score is not None:
                results = [r for r in results if r.score >= min_score]
            if max_score is not None:
                results = [r for r in results if r.score <= max_score]
            results.sort(key=lambda r: r.created_at, reverse=True)
            if offset:
                results = results[offset:]
            if limit is not None:
                results = results[:limit]
            return results

    def aggregate_count(self, group_by: str = "severity") -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            if group_by == "severity":
                for sev, ids in self._severity_index.items():
                    counts[sev.name] = len(ids)
            elif group_by == "tier":
                for tier, ids in self._tier_index.items():
                    counts[tier] = len(ids)
            elif group_by == "rule_id":
                for rule, ids in self._rule_index.items():
                    counts[rule] = len(ids)
            elif group_by == "passed":
                passed = sum(1 for r in self._results.values() if r.passed)
                counts["passed"] = passed
                counts["failed"] = len(self._results) - passed
            return counts

    def aggregate_severity_distribution(self) -> Dict[str, int]:
        with self._lock:
            return {sev.name: len(ids) for sev, ids in self._severity_index.items()}

    def aggregate_score_stats(self) -> Dict[str, float]:
        with self._lock:
            scores = [r.score for r in self._results.values()]
            if not scores:
                return {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0, "count": 0}
            sorted_scores = sorted(scores)
            n = len(sorted_scores)
            median = sorted_scores[n // 2] if n % 2 == 1 else (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
            return {
                "min": min(scores),
                "max": max(scores),
                "avg": round(sum(scores) / n, 4),
                "median": median,
                "count": n,
            }

    def aggregate_by_time(self, interval_seconds: float = 3600.0) -> Dict[str, int]:
        with self._lock:
            buckets: Dict[str, int] = {}
            for r in self._results.values():
                bucket = int(r.created_at / interval_seconds) * interval_seconds
                key = str(bucket)
                buckets[key] = buckets.get(key, 0) + 1
            return buckets

    def aggregate_by_hour(self) -> Dict[str, int]:
        return self.aggregate_by_time(3600.0)

    def aggregate_by_day(self) -> Dict[str, int]:
        return self.aggregate_by_time(86400.0)

    def aggregate_passing_rate(self) -> float:
        with self._lock:
            if not self._results:
                return 0.0
            passed = sum(1 for r in self._results.values() if r.passed)
            return round(passed / len(self._results), 4)

    def aggregate_by_rule(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            result: Dict[str, Dict[str, Any]] = {}
            for rid, r in self._results.items():
                agg = result.setdefault(r.rule_id, {"count": 0, "passed": 0, "failed": 0, "avg_score": 0.0, "total_score": 0.0})
                agg["count"] += 1
                agg["total_score"] += r.score
                if r.passed:
                    agg["passed"] += 1
                else:
                    agg["failed"] += 1
            for rule_id in result:
                agg = result[rule_id]
                agg["avg_score"] = round(agg["total_score"] / agg["count"], 4) if agg["count"] > 0 else 0.0
                del agg["total_score"]
            return result

    def delete(self, result_id: str) -> bool:
        with self._lock:
            if result_id not in self._results:
                return False
            self._remove_result(result_id)
            return True

    def delete_by_rule_id(self, rule_id: str) -> int:
        with self._lock:
            ids = list(self._rule_index.get(rule_id, set()))
            for rid in ids:
                self._remove_result(rid)
            return len(ids)

    def delete_by_tier(self, tier: str) -> int:
        with self._lock:
            ids = list(self._tier_index.get(tier, set()))
            for rid in ids:
                self._remove_result(rid)
            return len(ids)

    def delete_by_session(self, session_id: str) -> int:
        with self._lock:
            ids = list(self._session_index.get(session_id, set()))
            for rid in ids:
                self._remove_result(rid)
            return len(ids)

    def delete_by_severity(self, severity: Severity) -> int:
        with self._lock:
            ids = list(self._severity_index.get(severity, set()))
            for rid in ids:
                self._remove_result(rid)
            return len(ids)

    def delete_older_than(self, max_age: float) -> int:
        now = time.time()
        with self._lock:
            to_remove = [rid for rid, r in self._results.items() if now - r.created_at > max_age]
            for rid in to_remove:
                self._remove_result(rid)
            return len(to_remove)

    def clear(self) -> int:
        with self._lock:
            count = len(self._results)
            self._results.clear()
            self._rule_index.clear()
            self._tier_index.clear()
            self._severity_index.clear()
            self._session_index.clear()
            self._tag_index.clear()
            logger.info("Cleared result store (%d results)", count)
            return count

    def prune(self) -> int:
        now = time.time()
        with self._lock:
            to_remove = [
                rid for rid, r in self._results.items()
                if now - r.created_at > self._config.max_age_seconds
            ]
            for rid in to_remove:
                self._remove_result(rid)
            if len(self._results) > self._config.max_results:
                excess = len(self._results) - self._config.max_results
                sorted_results = sorted(
                    self._results.values(),
                    key=lambda r: r.created_at,
                )
                for r in sorted_results[:excess]:
                    self._remove_result(r.result_id)
                    to_remove.append(r.result_id)
            self._total_prunes += len(to_remove)
            return len(to_remove)

    def batch_get(self, result_ids: List[str]) -> Dict[str, Optional[EvalResult]]:
        with self._lock:
            self._total_queries += 1
            return {rid: self._results.get(rid) for rid in result_ids}

    def get_recent(self, n: int = 10) -> List[EvalResult]:
        with self._lock:
            sorted_results = sorted(
                self._results.values(),
                key=lambda r: r.created_at,
                reverse=True,
            )
            return sorted_results[:n]

    def get_failed(self) -> List[EvalResult]:
        with self._lock:
            return [r for r in self._results.values() if not r.passed]

    def get_passed(self) -> List[EvalResult]:
        with self._lock:
            return [r for r in self._results.values() if r.passed]

    def get_high_severity(self, min_severity: Severity = Severity.HIGH) -> List[EvalResult]:
        with self._lock:
            return [r for r in self._results.values() if r.severity.value >= min_severity.value]

    def count(self) -> int:
        with self._lock:
            return len(self._results)

    def count_by_rule(self, rule_id: str) -> int:
        with self._lock:
            return len(self._rule_index.get(rule_id, set()))

    def count_by_tier(self, tier: str) -> int:
        with self._lock:
            return len(self._tier_index.get(tier, set()))

    def count_by_severity(self, severity: Severity) -> int:
        with self._lock:
            return len(self._severity_index.get(severity, set()))

    def count_by_session(self, session_id: str) -> int:
        with self._lock:
            return len(self._session_index.get(session_id, set()))

    def list_rules(self) -> List[str]:
        with self._lock:
            return list(self._rule_index.keys())

    def list_tiers(self) -> List[str]:
        with self._lock:
            return list(self._tier_index.keys())

    def list_sessions(self) -> List[str]:
        with self._lock:
            return list(self._session_index.keys())

    def list_tags(self) -> List[str]:
        with self._lock:
            return list(self._tag_index.keys())

    def export_json(self, pretty: bool = False) -> str:
        with self._lock:
            data = []
            for r in self._results.values():
                data.append({
                    "result_id": r.result_id,
                    "rule_id": r.rule_id,
                    "tier": r.tier,
                    "severity": r.severity.name,
                    "score": r.score,
                    "passed": r.passed,
                    "details": r.details,
                    "created_at": r.created_at,
                    "session_id": r.session_id,
                    "metadata": r.metadata,
                    "tags": list(r.tags),
                })
            if pretty:
                return json.dumps(data, indent=2, default=str)
            return json.dumps(data, default=str)

    def export_to_dict(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "result_id": r.result_id,
                    "rule_id": r.rule_id,
                    "tier": r.tier,
                    "severity": r.severity.name,
                    "score": r.score,
                    "passed": r.passed,
                    "details": r.details,
                    "created_at": r.created_at,
                    "session_id": r.session_id,
                    "metadata": r.metadata,
                    "tags": list(r.tags),
                }
                for r in self._results.values()
            ]

    def export_filtered(self, **filters: Any) -> str:
        results = self.query(**filters)
        data = [
            {
                "result_id": r.result_id,
                "rule_id": r.rule_id,
                "tier": r.tier,
                "severity": r.severity.name,
                "score": r.score,
                "passed": r.passed,
                "details": r.details,
                "created_at": r.created_at,
                "session_id": r.session_id,
                "metadata": r.metadata,
                "tags": list(r.tags),
            }
            for r in results
        ]
        return json.dumps(data, indent=2, default=str)

    def import_from_dict(self, data: List[Dict[str, Any]], reset: bool = False) -> int:
        if reset:
            self.clear()
        return self.store_many(data)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            severity_dist = self.aggregate_severity_distribution()
            score_stats = self.aggregate_score_stats()
            return {
                "total_results": len(self._results),
                "max_results": self._config.max_results,
                "max_age_seconds": self._config.max_age_seconds,
                "total_inserts": self._total_inserts,
                "total_queries": self._total_queries,
                "total_prunes": self._total_prunes,
                "unique_rules": len(self._rule_index),
                "unique_tiers": len(self._tier_index),
                "unique_sessions": len(self._session_index),
                "unique_tags": len(self._tag_index),
                "severity_distribution": severity_dist,
                "score_stats": score_stats,
                "passing_rate": self.aggregate_passing_rate(),
                "prune_on_insert": self._config.prune_on_insert,
            }

    def reset_stats(self) -> None:
        with self._lock:
            self._total_inserts = 0
            self._total_queries = 0
            self._total_prunes = 0

    def snapshot(self) -> Dict[str, Any]:
        stats = self.get_stats()
        return {
            "stats": stats,
            "rules": self.list_rules(),
            "tiers": self.list_tiers(),
            "sessions": self.list_sessions(),
        }

    def has_result(self, result_id: str) -> bool:
        with self._lock:
            return result_id in self._results

    def get_oldest(self, n: int = 10) -> List[EvalResult]:
        with self._lock:
            sorted_results = sorted(
                self._results.values(),
                key=lambda r: r.created_at,
            )
            return sorted_results[:n]

    def get_newest(self, n: int = 10) -> List[EvalResult]:
        return self.get_recent(n)

    def find_duplicates(self) -> Dict[str, List[str]]:
        with self._lock:
            groups: Dict[Tuple[str, str, str], List[str]] = {}
            for rid, r in self._results.items():
                key = (r.rule_id, r.tier, r.session_id)
                groups.setdefault(key, []).append(rid)
            return {str(k): v for k, v in groups.items() if len(v) > 1}

    def apply_retention_policy(self, max_results: Optional[int] = None, max_age: Optional[float] = None) -> int:
        total = 0
        if max_age is not None:
            total += self.delete_older_than(max_age)
        if max_results is not None:
            with self._lock:
                if len(self._results) > max_results:
                    excess = len(self._results) - max_results
                    sorted_results = sorted(
                        self._results.values(),
                        key=lambda r: r.created_at,
                    )
                    for r in sorted_results[:excess]:
                        self._remove_result(r.result_id)
                    total += excess
        return total

    def get_by_score_range(self, min_score: float, max_score: float) -> List[EvalResult]:
        with self._lock:
            return [r for r in self._results.values() if min_score <= r.score <= max_score]

    def get_summary(self) -> Dict[str, Any]:
        stats = self.get_stats()
        return {
            "total": stats["total_results"],
            "passing_rate": stats["passing_rate"],
            "severity_distribution": stats["severity_distribution"],
            "score_stats": stats["score_stats"],
            "unique_rules": stats["unique_rules"],
            "unique_tiers": stats["unique_tiers"],
        }

    def get_top_failing_rules(self, n: int = 10) -> List[Tuple[str, int]]:
        with self._lock:
            fail_counts: Dict[str, int] = {}
            for r in self._results.values():
                if not r.passed:
                    fail_counts[r.rule_id] = fail_counts.get(r.rule_id, 0) + 1
            sorted_rules = sorted(fail_counts.items(), key=lambda x: x[1], reverse=True)
            return sorted_rules[:n]

    def get_top_scoring_rules(self, n: int = 10) -> List[Tuple[str, float]]:
        with self._lock:
            avg_scores: Dict[str, List[float]] = {}
            for r in self._results.values():
                avg_scores.setdefault(r.rule_id, []).append(r.score)
            averages = [(rid, round(sum(scores) / len(scores), 4)) for rid, scores in avg_scores.items()]
            averages.sort(key=lambda x: x[1], reverse=True)
            return averages[:n]

    def __len__(self) -> int:
        return self.count()

    def __contains__(self, result_id: str) -> bool:
        return self.has_result(result_id)

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"ResultStore(results={stats['total_results']}/{stats['max_results']}, "
            f"passing_rate={stats['passing_rate']}, "
            f"rules={stats['unique_rules']})"
        )