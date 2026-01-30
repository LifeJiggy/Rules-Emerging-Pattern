"""Performance monitoring for rule engine."""
import logging
import time
from typing import Dict, Any
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """Monitor rule engine performance metrics."""
    
    def __init__(self):
        self.metrics = defaultdict(lambda: {
            "count": 0,
            "total_time": 0.0,
            "min_time": float("inf"),
            "max_time": 0.0,
            "errors": 0
        })
        self.start_times: Dict[str, float] = {}
        
    def start_timer(self, operation_id: str) -> None:
        """Start timing an operation."""
        self.start_times[operation_id] = time.time()
        
    def end_timer(self, operation_id: str, success: bool = True) -> float:
        """End timing an operation and record metrics."""
        if operation_id not in self.start_times:
            return 0.0
        
        elapsed = time.time() - self.start_times[operation_id]
        
        metrics = self.metrics[operation_id]
        metrics["count"] += 1
        metrics["total_time"] += elapsed
        metrics["min_time"] = min(metrics["min_time"], elapsed)
        metrics["max_time"] = max(metrics["max_time"], elapsed)
        
        if not success:
            metrics["errors"] += 1
        
        del self.start_times[operation_id]
        return elapsed
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all performance metrics."""
        result = {}
        for op_id, data in self.metrics.items():
            count = data["count"]
            result[op_id] = {
                "count": count,
                "avg_time_ms": (data["total_time"] / count * 1000) if count > 0 else 0,
                "min_time_ms": data["min_time"] * 1000 if data["min_time"] != float("inf") else 0,
                "max_time_ms": data["max_time"] * 1000,
                "error_rate": (data["errors"] / count * 100) if count > 0 else 0,
                "timestamp": datetime.utcnow().isoformat()
            }
        return result
    
    def get_slow_operations(self, threshold_ms: float = 100.0) -> Dict[str, float]:
        """Get operations slower than threshold."""
        slow_ops = {}
        metrics = self.get_metrics()
        for op_id, data in metrics.items():
            if data["avg_time_ms"] > threshold_ms:
                slow_ops[op_id] = data["avg_time_ms"]
        return slow_ops
