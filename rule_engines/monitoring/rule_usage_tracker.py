# rule_engines/monitoring/rule_usage_tracker.py

import logging

logger = logging.getLogger(__name__)


class RuleUsageTracker:
    def __init__(self):
        self.logger = logger
        self.usage_stats = {}
    
    def track_usage(self, rule_id):
        self.logger.info('Tracking rule usage')
        if rule_id not in self.usage_stats:
            self.usage_stats[rule_id] = 0
        self.usage_stats[rule_id] += 1
        return {'rule_id': rule_id, 'usage_count': self.usage_stats[rule_id]}
