"""Pattern recognition for rule usage."""
import logging
from typing import Dict, List, Any, Optional
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RuleUsagePatternAnalyzer:
    """Analyze patterns in rule usage."""
    
    def __init__(self):
        self.usage_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.pattern_cache: Dict[str, Any] = {}
        
    def record_usage(self, rule_id: str, context: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Record a rule usage event."""
        usage_record = {
            "timestamp": datetime.utcnow(),
            "rule_id": rule_id,
            "context": context,
            "triggered": result.get("triggered", False),
            "blocked": result.get("blocked", False)
        }
        self.usage_history[rule_id].append(usage_record)
        
    def detect_patterns(self, rule_id: str, time_window: timedelta = timedelta(days=7)) -> Dict[str, Any]:
        """Detect usage patterns for a rule."""
        cutoff = datetime.utcnow() - time_window
        recent_usage = [
            u for u in self.usage_history.get(rule_id, [])
            if u["timestamp"] > cutoff
        ]
        
        if not recent_usage:
            return {"patterns": [], "frequency": 0}
        
        # Calculate frequency
        frequency = len(recent_usage) / time_window.days if time_window.days > 0 else 0
        
        # Detect common contexts
        context_patterns = defaultdict(int)
        for usage in recent_usage:
            domain = usage["context"].get("domain", "unknown")
            context_patterns[domain] += 1
        
        # Detect trigger rate
        triggered_count = sum(1 for u in recent_usage if u["triggered"])
        trigger_rate = triggered_count / len(recent_usage) if recent_usage else 0
        
        return {
            "rule_id": rule_id,
            "frequency_per_day": frequency,
            "total_uses": len(recent_usage),
            "trigger_rate": trigger_rate,
            "common_contexts": dict(context_patterns),
            "peak_usage_times": self._get_peak_times(recent_usage)
        }
    
    def _get_peak_times(self, usage_records: List[Dict[str, Any]]) -> List[str]:
        """Identify peak usage times."""
        hourly_counts = defaultdict(int)
        for usage in usage_records:
            hour = usage["timestamp"].hour
            hourly_counts[hour] += 1
        
        # Return top 3 hours
        sorted_hours = sorted(hourly_counts.items(), key=lambda x: x[1], reverse=True)
        return [f"{h}:00" for h, _ in sorted_hours[:3]]
    
    def get_underutilized_rules(self, threshold: int = 10) -> List[str]:
        """Get rules with low usage."""
        underutilized = []
        for rule_id, history in self.usage_history.items():
            if len(history) < threshold:
                underutilized.append(rule_id)
        return underutilized
    
    def get_overutilized_rules(self, threshold: int = 1000) -> List[str]:
        """Get rules with extremely high usage."""
        overutilized = []
        for rule_id, history in self.usage_history.items():
            if len(history) > threshold:
                overutilized.append(rule_id)
        return overutilized
