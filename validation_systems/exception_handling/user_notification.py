# validation_systems/exception_handling/user_notification.py

import logging

logger = logging.getLogger(__name__)


class UserNotification:
    def __init__(self):
        self.logger = logger
        self.notifications = []
    
    def notify(self, user, message):
        self.logger.info('Sending user notification')
        notification = {
            'user': user,
            'message': message,
            'sent': True
        }
        self.notifications.append(notification)
        return notification
