"""
Notification types and priority constants for Claude Code notifications

This module defines the standard notification types and priority levels
used by the Claude Code notification system.
"""

import os
import urllib.parse
from enum import Enum
from typing import List


class NotificationType(Enum):
    """
    Standard notification types for Claude Code communications.
    
    Provides enumerated values for different categories of notifications
    that can be sent through the Claude Code notification system.
    
    Requires:
        - None
        
    Ensures:
        - Provides consistent notification type values
        - Supports conversion to list of string values
        - Maintains type safety for notification categories
    """
    
    TASK = "task"                                       # Task completion (success/failure)
    PROGRESS = "progress"                               # Progress updates during long operations
    ALERT = "alert"                                     # Warnings and important messages
    CUSTOM = "custom"                                   # User-defined messages
    USER_INITIATED_MESSAGE = "user_initiated_message"   # User-to-session voice/text input
    
    @classmethod
    def values(cls) -> List[str]:
        """
        Get list of all notification type values.

        Requires:
            - None

        Ensures:
            - Returns list of all enum values as strings
            - Order matches enum declaration order
            - List contains exactly 5 elements

        Raises:
            - None
        """
        return [item.value for item in cls]


class NotificationPriority(Enum):
    """
    Priority levels for notifications.
    
    Defines the urgency levels for Claude Code notifications,
    from background information to critical alerts.
    
    Requires:
        - None
        
    Ensures:
        - Provides consistent priority level values
        - Supports conversion to list of string values
        - Maintains hierarchical priority ordering
    """
    
    LOW = "low"         # Background information
    MEDIUM = "medium"   # Normal notifications (default)
    HIGH = "high"       # Important messages
    URGENT = "urgent"   # Critical alerts
    
    @classmethod  
    def values(cls) -> List[str]:
        """
        Get list of all priority values.
        
        Requires:
            - None
            
        Ensures:
            - Returns list of all enum values as strings
            - Order reflects priority hierarchy (low to urgent)
            - List contains exactly 4 elements
            
        Raises:
            - None
        """
        return [item.value for item in cls]


# Default values
DEFAULT_TYPE = NotificationType.CUSTOM.value
DEFAULT_PRIORITY = NotificationPriority.MEDIUM.value

# API Configuration
DEFAULT_API_KEY = "claude_code_simple_key"
DEFAULT_SERVER_URL = "http://localhost:7999"

# Environment variable names
ENV_CLI_PATH = "COSA_CLI_PATH"
ENV_SERVER_URL = "LUPIN_APP_SERVER_URL"


def validate_server_environment() -> bool:
    """
    Validate the server URL the notification CLIs will post to.

    Requires:
        - os and urllib.parse are importable

    Ensures:
        - Reads ENV_SERVER_URL, falling back to DEFAULT_SERVER_URL
        - Reports a URL that does not start with http:// or https://
        - Reports a URL with no host, and any urlparse exception
        - Prints each issue and returns False if any was found
        - Prints the validated URL and returns True otherwise

    Raises:
        - None (all exceptions are reported as issues)
    """
    issues = []

    server_url = os.getenv( ENV_SERVER_URL, DEFAULT_SERVER_URL )
    if not server_url.startswith( ( "http://", "https://" ) ):
        issues.append( f"{ENV_SERVER_URL} must start with http:// or https://" )

    try:
        parsed = urllib.parse.urlparse( server_url )
        if not parsed.netloc:
            issues.append( f"Invalid server URL format: {server_url}" )
    except Exception as e:
        issues.append( f"Error parsing server URL: {e}" )

    if issues:
        print( "❌ Environment validation failed:" )
        for issue in issues:
            print( f"  - {issue}" )
        return False

    print( "✅ Environment validation passed" )
    print( f"  Server URL: {server_url}" )
    return True
