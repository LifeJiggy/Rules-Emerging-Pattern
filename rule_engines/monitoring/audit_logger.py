# rule_engines/monitoring/audit_logger.py

import logging

logger = logging.getLogger(__name__)


class AuditLogger:
    def __init__(self):
        self.logger = logger
        self.audit_trail = []
    
    def log_event(self, event):
        self.logger.info('Logging audit event')
        audit_entry = {
            'event': event,
            'timestamp': None
        }
        self.audit_trail.append(audit_entry)
        return audit_entry
