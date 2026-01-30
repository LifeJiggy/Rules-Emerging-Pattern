# conflict_resolution/resolution_strategies/fallback_resolution.py

import logging

logger = logging.getLogger(__name__)


class FallbackResolver:
    def __init__(self):
        self.logger = logger
        self.default_resolution = 'abort'
    
    def resolve(self, conflict):
        self.logger.info('Applying fallback resolution for conflict')
        resolution = {
            'status': 'resolved',
            'method': 'fallback',
            'action': self.default_resolution,
            'timestamp': None
        }
        return resolution
