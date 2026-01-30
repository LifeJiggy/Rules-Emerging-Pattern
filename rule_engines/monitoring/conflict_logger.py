# rule_engines/monitoring/conflict_logger.py

import logging

logger = logging.getLogger(__name__)


class ConflictLogger:
    def __init__(self):
        self.logger = logger
        self.conflicts = []
    
    def log_conflict(self, conflict):
        self.logger.info('Logging conflict')
        self.conflicts.append(conflict)
        return {'conflict_id': conflict.get('id'), 'logged': True}
