# evaluation_framework/monitoring/alerting_system.py

import logging

logger = logging.getLogger(__name__)


class AlertingSystem:
    def __init__(self):
        self.logger = logger
        self.alerts = []
    
    def trigger_alert(self, condition):
        self.logger.info('Triggering alert for condition')
        alert = {'condition': condition, 'status': 'triggered'}
        self.alerts.append(alert)
        return alert
