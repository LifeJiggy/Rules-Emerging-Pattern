"""Monitoring dashboard for system metrics."""
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class Metric:
    """Represents a system metric."""
    name: str
    value: float
    unit: str
    timestamp: datetime
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class DashboardWidget:
    """Represents a dashboard widget."""
    widget_id: str
    widget_type: str
    title: str
    metric_names: List[str]
    config: Dict[str, Any] = field(default_factory=dict)


class MonitoringDashboard:
    """Dashboard for monitoring system health and metrics."""
    
    def __init__(self, dashboard_id: str = "main"):
        """Initialize the monitoring dashboard.
        
        Args:
            dashboard_id: Unique identifier for the dashboard
        """
        self.dashboard_id = dashboard_id
        self.metrics: Dict[str, List[Metric]] = defaultdict(list)
        self.widgets: Dict[str, DashboardWidget] = {}
        self.refresh_interval = 30  # seconds
        self.last_refresh = datetime.now()
        self.alerts_enabled = True
        logger.info(f"MonitoringDashboard '{dashboard_id}' initialized")
    
    def record_metric(
        self,
        name: str,
        value: float,
        unit: str = "count",
        labels: Optional[Dict[str, str]] = None
    ) -> Metric:
        """Record a metric value.
        
        Args:
            name: Metric name
            value: Metric value
            unit: Unit of measurement
            labels: Optional labels/tags
            
        Returns:
            The recorded metric
        """
        metric = Metric(
            name=name,
            value=value,
            unit=unit,
            timestamp=datetime.now(),
            labels=labels or {}
        )
        
        self.metrics[name].append(metric)
        
        # Keep only last 1000 data points per metric
        if len(self.metrics[name]) > 1000:
            self.metrics[name] = self.metrics[name][-1000:]
        
        logger.debug(f"Recorded metric {name}: {value} {unit}")
        return metric
    
    def add_widget(self, widget: DashboardWidget) -> None:
        """Add a widget to the dashboard.
        
        Args:
            widget: DashboardWidget to add
        """
        self.widgets[widget.widget_id] = widget
        logger.info(f"Added widget: {widget.title} ({widget.widget_id})")
    
    def get_current_metrics(self) -> Dict[str, Metric]:
        """Get current (latest) value for all metrics.
        
        Returns:
            Dictionary of metric names to latest Metric
        """
        current = {}
        for name, metric_list in self.metrics.items():
            if metric_list:
                current[name] = metric_list[-1]
        return current
    
    def get_metric_history(
        self,
        metric_name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Metric]:
        """Get historical data for a metric.
        
        Args:
            metric_name: Name of the metric
            start_time: Optional start time filter
            end_time: Optional end time filter
            
        Returns:
            List of matching metrics
        """
        if metric_name not in self.metrics:
            return []
        
        metrics = self.metrics[metric_name]
        
        if start_time:
            metrics = [m for m in metrics if m.timestamp >= start_time]
        if end_time:
            metrics = [m for m in metrics if m.timestamp <= end_time]
        
        return metrics
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get a summary of the current dashboard state.
        
        Returns:
            Dictionary with dashboard summary
        """
        summary = {
            'dashboard_id': self.dashboard_id,
            'total_metrics': len(self.metrics),
            'total_widgets': len(self.widgets),
            'last_refresh': self.last_refresh.isoformat(),
            'refresh_interval': self.refresh_interval,
            'current_values': {},
            'system_health': 'healthy'
        }
        
        # Add current metric values
        for name, metric_list in self.metrics.items():
            if metric_list:
                latest = metric_list[-1]
                summary['current_values'][name] = {
                    'value': latest.value,
                    'unit': latest.unit,
                    'timestamp': latest.timestamp.isoformat()
                }
        
        # Simple health check based on metric freshness
        from datetime import timedelta
        stale_threshold = timedelta(minutes=5)
        stale_metrics = []
        
        for name, metric_list in self.metrics.items():
            if metric_list:
                latest = metric_list[-1]
                if datetime.now() - latest.timestamp > stale_threshold:
                    stale_metrics.append(name)
        
        if stale_metrics:
            summary['system_health'] = 'degraded'
            summary['stale_metrics'] = stale_metrics
        
        return summary
    
    def calculate_aggregates(self, metric_name: str) -> Dict[str, float]:
        """Calculate aggregate statistics for a metric.
        
        Args:
            metric_name: Name of the metric
            
        Returns:
            Dictionary with aggregate statistics
        """
        if metric_name not in self.metrics or not self.metrics[metric_name]:
            return {}
        
        values = [m.value for m in self.metrics[metric_name]]
        
        return {
            'count': len(values),
            'sum': sum(values),
            'avg': sum(values) / len(values),
            'min': min(values),
            'max': max(values),
            'latest': values[-1]
        }
    
    def export_dashboard_data(self) -> Dict[str, Any]:
        """Export all dashboard data for external use.
        
        Returns:
            Dictionary with all dashboard data
        """
        export_data = {
            'dashboard_id': self.dashboard_id,
            'exported_at': datetime.now().isoformat(),
            'metrics': {},
            'widgets': {}
        }
        
        # Export metrics
        for name, metric_list in self.metrics.items():
            export_data['metrics'][name] = [
                {
                    'value': m.value,
                    'unit': m.unit,
                    'timestamp': m.timestamp.isoformat(),
                    'labels': m.labels
                }
                for m in metric_list
            ]
        
        # Export widgets
        for widget_id, widget in self.widgets.items():
            export_data['widgets'][widget_id] = {
                'widget_type': widget.widget_type,
                'title': widget.title,
                'metric_names': widget.metric_names,
                'config': widget.config
            }
        
        return export_data
