"""
Lupin CLI Notifications - Notification types, models, and delivery clients.

This package provides the notification infrastructure for Claude Code
to communicate with users through the Lupin FastAPI application.

Main Components:
- notify_user: Send notifications to user via Lupin API
- notify_user_async: Fire-and-forget notifications with retry
- notify_user_sync: SSE-blocking synchronous notifications
- notification_types: Constants and enums for notification types
- notification_models: Pydantic models for type-safe validation
- test_notifications: End-to-end testing suite
"""

__version__ = "0.1.0"

# NOTE: Convenience imports removed to prevent any potential circular dependencies
# Use direct imports instead, e.g.:
#   from lupin_cli.notifications.notify_user import notify_user
#   from lupin_cli.notifications.notification_types import NotificationType, NotificationPriority
