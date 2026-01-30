# evaluation_framework/rule_evaluation/effectiveness_metrics.py

import logging

logger = logging.getLogger(__name__)


class EffectivenessMetrics:
    def __init__(self):
        self.logger = logger
        self.metrics = {}
    
    def evaluate(self, rule):
        self.logger.info('Evaluating rule effectiveness')
        return {'rule_id': rule.get('id'), 'score': 0.0}
