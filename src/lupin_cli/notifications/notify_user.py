#!/usr/bin/env python3
"""
Claude Code notification script for Lupin communication

This script allows Claude Code to send notifications to users through the 
Lupin FastAPI application. Notifications are delivered via
WebSocket and converted to audio using the HybridTTS system.

Usage:
    python3 notify_user.py "Message text" --type task --priority high
    python3 notify_user.py "Build completed" --type task
    
Environment Variables:
    LUPIN_APP_SERVER_URL: Server URL (default: http://localhost:7999)
"""

import os
import sys
import requests
import argparse
from typing import Optional
from datetime import datetime

# Import notification types
from lupin_cli.notifications.notification_types import (
    NotificationType, NotificationPriority, 
    DEFAULT_TYPE, DEFAULT_PRIORITY, 
    DEFAULT_API_KEY, DEFAULT_SERVER_URL, ENV_SERVER_URL
)


def notify_user(
    message: str,
    notification_type: str = DEFAULT_TYPE,
    priority: str = DEFAULT_PRIORITY,
    target_user: str = "ricardo.felipe.ruiz@gmail.com",
    server_url: Optional[str] = None,
    timeout: int = 5
) -> bool:
    """
    Send notification to user via Lupin API.
    
    Requires:
        - message is a non-empty string
        - notification_type is one of: task, progress, alert, custom
        - priority is one of: low, medium, high, urgent
        - target_user is a valid email address format
        - server_url is None or a valid HTTP/HTTPS URL
        - timeout is a positive integer
        
    Ensures:
        - Returns True if notification sent successfully
        - Returns False if validation fails or network error occurs
        - Validates notification_type and priority against allowed values
        - Uses environment variable or default server URL if not provided
        - Prints status messages for debugging
        
    Raises:
        - None (handles all exceptions gracefully)
        
    Args:
        message: The notification message text
        notification_type: Type of notification (task, progress, alert, custom)
        priority: Priority level (low, medium, high, urgent)
        target_user: Target user email address (default: ricardo.felipe.ruiz@gmail.com)
        server_url: Override server URL (uses env var if None)
        timeout: Request timeout in seconds
        
    Returns:
        bool: True if notification sent successfully, False otherwise
    """
    
    # Validate notification type
    if notification_type not in NotificationType.values():
        print( f"✗ Invalid notification type: {notification_type}" )
        print( f"  Valid types: {', '.join( NotificationType.values() )}" )
        return False
    
    # Validate priority
    if priority not in NotificationPriority.values():
        print( f"✗ Invalid priority: {priority}" )
        print( f"  Valid priorities: {', '.join( NotificationPriority.values() )}" )
        return False
    
    # Determine server URL
    base_url = server_url or os.getenv( ENV_SERVER_URL, DEFAULT_SERVER_URL )
    
    # Remove trailing slash if present
    base_url = base_url.rstrip( '/' )
    
    try:
        # Prepare request
        url = f"{base_url}/api/notify"
        params = {
            "message": message,
            "type": notification_type,
            "priority": priority,
            "target_user": target_user,
            "api_key": DEFAULT_API_KEY
        }
        
        if debug:
            print( f"Sending notification to: {url}" )
            print( f"Parameters: {params}" )
        
        # Send notification
        response = requests.post(
            url,
            params=params,
            timeout=timeout
        )
        
        if response.status_code == 200:
            print( f"✓ Notification sent: {notification_type}/{priority}" )
            if debug:
                print( f"  Response: {response.json()}" )
            return True
        else:
            print( f"✗ Failed to send notification: HTTP {response.status_code}" )
            if response.text:
                print( f"  Error: {response.text}" )
            return False
            
    except requests.exceptions.ConnectionError:
        print( f"✗ Connection error: Cannot reach server at {base_url}" )
        print( f"  Check that Lupin is running and {ENV_SERVER_URL} is correct" )
        return False
        
    except requests.exceptions.Timeout:
        print( f"✗ Timeout error: Server did not respond within {timeout} seconds" )
        return False
        
    except requests.exceptions.RequestException as e:
        print( f"✗ Request error: {e}" )
        return False
        
    except Exception as e:
        print( f"✗ Unexpected error: {e}" )
        return False


def validate_environment() -> bool:
    """
    Validate environment setup for notification system.
    
    Requires:
        - urllib.parse module is available for URL validation
        
    Ensures:
        - Returns True if all environment checks pass
        - Returns False if any validation issues found
        - Checks server URL format and validity
        - Prints detailed validation results and issues
        - Validates URL scheme (http/https) requirements
        
    Raises:
        - None (handles all exceptions gracefully)
        
    Returns:
        bool: True if environment is properly configured
    """
    
    issues = []
    
    # Check server URL
    server_url = os.getenv( ENV_SERVER_URL, DEFAULT_SERVER_URL )
    if not server_url.startswith( ('http://', 'https://') ):
        issues.append( f"{ENV_SERVER_URL} must start with http:// or https://" )
    
    # Check if server is reachable (basic check)
    try:
        import urllib.parse
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


def main():
    """
    CLI entry point for notify_user script.
    
    Requires:
        - argparse module is available
        - All imported notification modules are accessible
        - Command line arguments follow expected format
        
    Ensures:
        - Parses command line arguments correctly
        - Validates environment if requested
        - Sends notification with provided parameters
        - Exits with appropriate status code (0 for success, 1 for failure)
        - Handles debug mode and validation options
        
    Raises:
        - SystemExit with appropriate exit code
    """
    
    parser = argparse.ArgumentParser(
        description="Send notification to Lupin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "Build completed successfully" --type task --priority medium
  %(prog)s "Starting deployment" --type progress --priority low  
  %(prog)s "Critical error detected" --type alert --priority urgent
  %(prog)s "Custom message" --type custom

Environment Variables:
  LUPIN_APP_SERVER_URL   Server URL (default: http://localhost:7999)
        """
    )
    
    parser.add_argument(
        "message", 
        help="Notification message text"
    )
    
    parser.add_argument(
        "--type", 
        choices=NotificationType.values(),
        default=DEFAULT_TYPE,
        help=f"Notification type (default: {DEFAULT_TYPE})"
    )
    
    parser.add_argument(
        "--priority", 
        choices=NotificationPriority.values(),
        default=DEFAULT_PRIORITY, 
        help=f"Priority level (default: {DEFAULT_PRIORITY})"
    )
    
    parser.add_argument(
        "--target-user",
        default="ricardo.felipe.ruiz@gmail.com",
        help="Target user email address (default: ricardo.felipe.ruiz@gmail.com)"
    )
    
    parser.add_argument(
        "--server",
        help=f"Server URL (overrides {ENV_SERVER_URL})"
    )
    
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Request timeout in seconds (default: 5)"
    )
    
    parser.add_argument(
        "--validate-env",
        action="store_true",
        help="Validate environment configuration and exit"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true", 
        help="Enable debug output"
    )
    
    args = parser.parse_args()
    
    # Enable debug mode globally for this module
    global debug
    debug = args.debug
    
    # Validate environment if requested
    if args.validate_env:
        is_valid = validate_environment()
        sys.exit( 0 if is_valid else 1 )
    
    # Send notification
    success = notify_user(
        message=args.message,
        notification_type=args.type,
        priority=args.priority,
        target_user=args.target_user,
        server_url=args.server,
        timeout=args.timeout
    )
    
    sys.exit( 0 if success else 1 )


# Global debug flag
debug = False


if __name__ == "__main__":
    main()