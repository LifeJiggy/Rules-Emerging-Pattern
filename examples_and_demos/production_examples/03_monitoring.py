"""Production Example: Monitoring Setup."""
from rules_emerging_pattern.rule_engines.monitoring.performance_monitor import PerformanceMonitor

def main():
    print("Monitoring Setup Demo")
    
    monitor = PerformanceMonitor()
    monitor.start_timer("operation_1")
    
    # Simulate work
    import time
    time.sleep(0.1)
    
    monitor.end_timer("operation_1", success=True)
    
    metrics = monitor.get_metrics()
    print(f"Metrics: {metrics}")

if __name__ == "__main__":
    main()
