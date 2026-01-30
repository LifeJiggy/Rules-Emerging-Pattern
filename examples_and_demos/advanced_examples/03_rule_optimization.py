"""Example: Rule Optimization."""
from rules_emerging_pattern.rule_learning.rule_optimization.performance_optimizer import RulePerformanceOptimizer

def main():
    print("Rule Optimization Demo")
    
    optimizer = RulePerformanceOptimizer()
    optimizer.record_evaluation("rule_001", 50.0)
    
    print("Optimization metrics recorded")

if __name__ == "__main__":
    main()
