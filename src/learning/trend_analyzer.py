"""Trend analysis module for detecting emerging patterns."""
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

logger = logging.getLogger(__name__)


@dataclass
class Trend:
    """Represents a detected trend."""
    trend_id: str
    metric_name: str
    direction: str  # 'increasing', 'decreasing', 'stable'
    strength: float  # 0.0 to 1.0
    start_time: datetime
    end_time: datetime
    data_points: List[float]


class TrendAnalyzer:
    """Analyzes data to detect trends and anomalies."""
    
    def __init__(self, window_size: int = 24):
        """Initialize the trend analyzer.
        
        Args:
            window_size: Number of time periods to analyze
        """
        self.window_size = window_size
        self.time_series_data: Dict[str, List[Dict]] = defaultdict(list)
        self.detected_trends: Dict[str, Trend] = {}
        self.analysis_count = 0
        logger.info(f"TrendAnalyzer initialized (window_size={window_size})")
    
    def add_data_point(self, metric_name: str, value: float, timestamp: Optional[datetime] = None) -> None:
        """Add a data point for trend analysis.
        
        Args:
            metric_name: Name of the metric
            value: Value of the data point
            timestamp: Optional timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        self.time_series_data[metric_name].append({
            'value': value,
            'timestamp': timestamp
        })
        
        # Keep only recent data
        cutoff = timestamp - timedelta(hours=self.window_size)
        self.time_series_data[metric_name] = [
            d for d in self.time_series_data[metric_name]
            if d['timestamp'] > cutoff
        ]
        
        logger.debug(f"Added data point for {metric_name}: {value}")
    
    def analyze_trends(self, metric_name: Optional[str] = None) -> List[Trend]:
        """Analyze trends in the data.
        
        Args:
            metric_name: Specific metric to analyze (None for all)
            
        Returns:
            List of detected trends
        """
        trends = []
        metrics_to_analyze = [metric_name] if metric_name else list(self.time_series_data.keys())
        
        for metric in metrics_to_analyze:
            if not metric or metric not in self.time_series_data:
                continue
            
            data = self.time_series_data[metric]
            if len(data) < 3:
                continue
            
            values = [d['value'] for d in data]
            timestamps = [d['timestamp'] for d in data]
            
            # Calculate trend direction and strength
            trend_direction = self._calculate_trend_direction(values)
            trend_strength = self._calculate_trend_strength(values)
            
            trend = Trend(
                trend_id=f"{metric}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                metric_name=metric,
                direction=trend_direction,
                strength=trend_strength,
                start_time=min(timestamps),
                end_time=max(timestamps),
                data_points=values
            )
            
            trends.append(trend)
            self.detected_trends[trend.trend_id] = trend
        
        self.analysis_count += 1
        logger.info(f"Analysis #{self.analysis_count}: Found {len(trends)} trends")
        
        return trends
    
    def _calculate_trend_direction(self, values: List[float]) -> str:
        """Calculate the direction of a trend."""
        if len(values) < 2:
            return "stable"
        
        first_half = values[:len(values)//2]
        second_half = values[len(values)//2:]
        
        first_avg = statistics.mean(first_half) if first_half else 0
        second_avg = statistics.mean(second_half) if second_half else 0
        
        diff = second_avg - first_avg
        threshold = abs(first_avg) * 0.05 if first_avg != 0 else 0.1
        
        if diff > threshold:
            return "increasing"
        elif diff < -threshold:
            return "decreasing"
        else:
            return "stable"
    
    def _calculate_trend_strength(self, values: List[float]) -> float:
        """Calculate the strength of a trend (0.0 to 1.0)."""
        if len(values) < 2:
            return 0.0
        
        try:
            std_dev = statistics.stdev(values)
            mean_val = statistics.mean(values)
            
            if mean_val == 0:
                return 0.0
            
            coefficient_of_variation = std_dev / abs(mean_val)
            strength = min(1.0, max(0.0, 1.0 - coefficient_of_variation))
            
            return strength
        except statistics.StatisticsError:
            return 0.0
    
    def detect_anomalies(self, metric_name: str, threshold: float = 2.0) -> List[Dict]:
        """Detect anomalies in a metric.
        
        Args:
            metric_name: Name of the metric to check
            threshold: Standard deviations for anomaly detection
            
        Returns:
            List of detected anomalies
        """
        if metric_name not in self.time_series_data:
            return []
        
        data = self.time_series_data[metric_name]
        if len(data) < 5:
            return []
        
        values = [d['value'] for d in data]
        mean = statistics.mean(values)
        std_dev = statistics.stdev(values)
        
        anomalies = []
        for point in data:
            z_score = abs(point['value'] - mean) / std_dev if std_dev > 0 else 0
            
            if z_score > threshold:
                anomalies.append({
                    'timestamp': point['timestamp'],
                    'value': point['value'],
                    'z_score': z_score,
                    'expected_range': (mean - threshold * std_dev, mean + threshold * std_dev)
                })
        
        logger.info(f"Detected {len(anomalies)} anomalies in {metric_name}")
        return anomalies
    
    def get_trend_summary(self) -> Dict:
        """Get a summary of all detected trends.
        
        Returns:
            Dictionary with trend summary
        """
        direction_counts = defaultdict(int)
        for trend in self.detected_trends.values():
            direction_counts[trend.direction] += 1
        
        return {
            'total_trends': len(self.detected_trends),
            'direction_summary': dict(direction_counts),
            'metrics_analyzed': len(self.time_series_data),
            'analysis_count': self.analysis_count,
            'high_strength_trends': len([t for t in self.detected_trends.values() if t.strength > 0.8])
        }
    
    def forecast(self, metric_name: str, periods: int = 5) -> List[float]:
        """Simple forecasting based on trend.
        
        Args:
            metric_name: Name of the metric to forecast
            periods: Number of periods to forecast
            
        Returns:
            List of forecasted values
        """
        if metric_name not in self.time_series_data:
            return []
        
        data = self.time_series_data[metric_name]
        if len(data) < 3:
            return []
        
        values = [d['value'] for d in data]
        
        # Simple linear trend projection
        if len(values) >= 2:
            recent_avg = statistics.mean(values[-3:])
            older_avg = statistics.mean(values[:3])
            trend_per_period = (recent_avg - older_avg) / max(len(values) // 2, 1)
            
            last_value = values[-1]
            forecasted = [last_value + trend_per_period * (i + 1) for i in range(periods)]
            
            return forecasted
        
        return [statistics.mean(values)] * periods
