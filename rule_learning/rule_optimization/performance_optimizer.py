"""Performance optimizer for rules."""
import logging
from typing import Dict, List, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class RulePerformanceOptimizer:
    """Optimize rule performance based on evaluation metrics."""
    
    def __init__(self):
        self.performance_data = defaultdict(lambda: {
            "total_evaluations": 0,
            "total_time_ms": 0,
            "cache_hits": 0,
            "cache_misses": 0
        })
        
    def record_evaluation(self, rule_id: str, execution_time_ms: float, cached: bool = False) -> None:
        """Record performance data for a rule evaluation."""
        data = self.performance_data[rule_id]
        data["total_evaluations"] += 1
        data["total_time_ms"] += execution_time_ms
        
        if cached:
            data["cache_hits"] += 1
        else:
            data["cache_misses"] += 1
    
    def get_average_execution_time(self, rule_id: str) -> float:
        """Get average execution time for a rule."""
        data = self.performance_data.get(rule_id, {})
        total = data.get("total_evaluations", 0)
        if total == 0:
            return 0.0
        return data.get("total_time_ms", 0) / total
    
    def get_slow_rules(self, threshold_ms: float = 100.0) -> List[str]:
        """Get rules that are slower than threshold."""
        slow_rules = []
        for rule_id, data in self.performance_data.items():
            avg_time = self.get_average_execution_time(rule_id)
            if avg_time > threshold_ms:
                slow_rules.append(rule_id)
        return slow_rules
    
    def suggest_optimizations(self, rule_id: str) -> List[str]:
        """Suggest optimizations for a rule."""
        suggestions = []
        data = self.performance_data.get(rule_id, {})
        
        # Check cache hit rate
        total = data.get("cache_hits", 0) + data.get("cache_misses", 0)
        if total > 0:
            hit_rate = data.get("cache_hits", 0) / total
            if hit_rate < 0.5:
                suggestions.append("Consider increasing cache TTL")
        
        # Check execution time
        avg_time = self.get_average_execution_time(rule_id)
        if avg_time > 50:
            suggestions.append("Rule is slow, consider pattern optimization")
        
        return suggestions
