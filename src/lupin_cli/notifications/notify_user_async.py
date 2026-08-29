#!/usr/bin/env python3
"""
Claude Code async notification client with Pydantic validation (Phase 2.4).

This script sends fire-and-forget notifications to Lupin via WebSocket delivery.
Uses Pydantic models for type-safe validation and structured responses.

Usage:
    python3 notify_user_async.py "Message text" --type task --priority high
    python3 notify_user_async.py "Build completed" --type task

Exit Codes:
    0: Success (notification queued or delivered)
    1: Error (validation, network, user not found)

Environment Variables:
    LUPIN_APP_SERVER_URL: Server URL (default: http://localhost:7999)
"""

import os
import sys
import time
import uuid as uuid_mod
import requests
import argparse
from typing import Optional
from pydantic import ValidationError

# Import Pydantic models
from lupin_cli.notifications.notification_models import (
    AsyncNotificationRequest,
    AsyncNotificationResponse,
    NotificationType,
    NotificationPriority
)

# Import config loader for dynamic configuration (Phase 2.5)
from cosa.utils.config_loader import get_api_config, load_api_key

# Import constants (fallbacks)
from lupin_cli.notifications.notification_types import (
    DEFAULT_SERVER_URL,
    ENV_SERVER_URL
)


def calculate_retry_intervals( timeout_seconds: int ) -> list:
    """
    Calculate adaptive retry intervals based on timeout duration.

    For short timeouts (≤10s): Aggressive linear retries to catch WebSocket
    auth completion (which takes 5-10 seconds empirically).

    For long timeouts (>10s): Exponential backoff with 5s cap to reduce
    server load while maintaining responsiveness.

    Requires:
        - timeout_seconds is a positive integer

    Ensures:
        - Returns list of intervals that fit within timeout (0.5s buffer)
        - Short timeouts: [1, 1, 2, 2, 3] pattern (aggressive)
        - Long timeouts: [1, 2, 4, 5, 5, 5...] pattern (exponential with cap)
        - Total interval time < timeout_seconds - 0.5

    Args:
        timeout_seconds: Total time budget for retries

    Returns:
        list: Retry intervals in seconds (e.g., [1, 1, 2, 2] = 4 attempts)
    """
    if timeout_seconds <= 10:
        # Aggressive retries for short timeouts (catch 5-10s WebSocket auth window)
        # Pattern: [1s, 1s, 2s, 2s, 3s] = 9s total
        intervals = [ 1, 1, 2, 2, 3 ]
    else:
        # Exponential backoff with 5s cap for long timeouts
        # Pattern: [1s, 2s, 4s, 5s, 5s, 5s...]
        intervals = []
        delay = 1
        while sum( intervals ) < timeout_seconds - 1:
            intervals.append( min( delay, 5 ) )  # Cap at 5s
            delay *= 2

    # Trim to fit within timeout (leave 0.5s buffer for final request)
    cumulative = 0
    result = []
    for interval in intervals:
        if cumulative + interval < timeout_seconds - 0.5:
            result.append( interval )
            cumulative += interval
        else:
            break

    return result


def notify_user_async(
    request: AsyncNotificationRequest,
    server_url: Optional[str] = None,
    debug: bool = False
) -> AsyncNotificationResponse:
    """
    Send fire-and-forget notification with Pydantic validation.

    Sends notification to Lupin API for WebSocket delivery without waiting
    for user response. Uses Pydantic models for type-safe request/response.

    Requires:
        - request is a validated AsyncNotificationRequest model
        - server_url is None or a valid HTTP/HTTPS URL
        - debug is a boolean

    Ensures:
        - Returns AsyncNotificationResponse with status and details
        - Prints status messages to stdout (success) or stderr (errors)
        - Uses Pydantic validation for all data

    Raises:
        - No exceptions raised (all handled internally)

    Args:
        request: AsyncNotificationRequest model (already validated)
        server_url: Override server URL (uses env var if None)
        debug: Enable debug output to stderr

    Returns:
        AsyncNotificationResponse: Structured response with success, status, details
    """

    # Load configuration (Phase 2.5 - dynamic multi-environment config)
    try:
        # Determine environment (default: local)
        env = os.getenv( 'LUPIN_ENV', 'local' )

        # Load config for environment (precedence: env vars > file > defaults)
        config = get_api_config( env )

        # Load API key from configured file
        api_key = load_api_key( config['api_key_file'] )

        # Use configured API URL (can be overridden by server_url parameter)
        base_url = server_url or config['api_url']
        base_url = base_url.rstrip( '/' )

    except Exception as e:
        # Fallback to environment variables/defaults if config loading fails
        if debug:
            print( f"[DEBUG] Config loading failed, using fallback: {e}", file=sys.stderr )
        base_url = server_url or os.getenv( ENV_SERVER_URL, DEFAULT_SERVER_URL )
        base_url = base_url.rstrip( '/' )
        api_key = None  # Will cause authentication error (intentional - forces user to fix config)

    # Resolve target_user if not explicitly set
    if request.target_user is None:
        from lupin_cli.notifications.notification_models import resolve_target_user
        request = request.model_copy( update={ "target_user": resolve_target_user() } )

    # Generate idempotency key ONCE for all retry attempts (prevents duplicate notifications)
    if request.idempotency_key is None:
        request = request.model_copy( update={ "idempotency_key": str( uuid_mod.uuid4() ) } )

    # Calculate retry intervals based on timeout (Phase 2.7 - adaptive retry for WebSocket auth)
    retry_intervals = calculate_retry_intervals( request.timeout )
    all_delays = [ 0 ] + retry_intervals  # First attempt immediate, then configured delays
    total_attempts = len( all_delays )

    # Retry loop with enumeration to track last attempt
    for attempt_idx, retry_delay in enumerate( all_delays, start=1 ):
        if retry_delay > 0:
            if debug:
                print( f"[DEBUG] Retry {attempt_idx - 1} after {retry_delay}s (user connecting)...", file=sys.stderr )
            time.sleep( retry_delay )

        is_last_attempt = ( attempt_idx == total_attempts )

        try:
            url = f"{base_url}/api/notify"

            # Convert request to API params (Phase 2.5 - api_key moved to headers)
            params = request.to_api_params()

            # Create headers with API key authentication (Phase 2.5)
            headers = {
                'X-API-Key': api_key
            }

            if debug:
                print( f"[DEBUG] Attempt {attempt_idx}/{total_attempts}: Sending notification to: {url}", file=sys.stderr )
                if attempt_idx == 1:  # Only print verbose details on first attempt
                    print( f"[DEBUG] Environment: {env if 'env' in locals() else 'fallback'}", file=sys.stderr )
                    print( f"[DEBUG] Request model: {request.model_dump_json( indent=2 )}", file=sys.stderr )
                    print( f"[DEBUG] API params: {params}", file=sys.stderr )
                    # BOTH halves must be guarded. The second one was; the first was not,
                    # so `api_key[:20]` raised TypeError whenever config loading had fallen
                    # back (api_key=None) AND debug was on — and because this print sits
                    # BEFORE requests.post, the notification was never sent at all. It
                    # surfaced as `Unexpected error: 'NoneType' object is not subscriptable`
                    # from the catch-all below, i.e. as a transport failure. Row e2099400.
                    key_preview = f"{api_key[:20]}...{api_key[-10:]}" if api_key else "None"
                    print( f"[DEBUG] API key: {key_preview}", file=sys.stderr )

            # Send notification (fire-and-forget - no SSE streaming)
            response = requests.post(
                url,
                params  = params,
                headers = headers,
                timeout = request.timeout
            )

            if response.status_code == 200:
                # Parse JSON response
                data = response.json()

                if debug:
                    print( f"[DEBUG] Attempt {attempt_idx} response: {data}", file=sys.stderr )

                # Check if user_not_available and retries remaining
                status = data.get( "status", "queued" )

                # Fire-and-forget progress notifications are persisted to the
                # notifications DB unconditionally; the user will see them on the
                # notification history when they connect. Retrying on
                # `user_not_available` is wasted effort that inflates dispatch
                # latency by N×retry_intervals (≈30-40s in test environments
                # where the target user has no live UI). Only retry user-availability
                # for non-progress types where a live recipient is required.
                is_progress = ( request.notification_type == NotificationType.PROGRESS )
                if status == "user_not_available" and not is_last_attempt and not is_progress:
                    # User still connecting - retry
                    if debug:
                        print( f"[DEBUG] user_not_available (attempt {attempt_idx}), will retry...", file=sys.stderr )
                    continue

                # Success or final attempt - return result
                return AsyncNotificationResponse(
                    success          = True,
                    status           = status,
                    message          = data.get( "message" ),
                    target_user      = request.target_user,
                    target_system_id = data.get( "target_system_id" ),
                    connection_count = data.get( "connection_count", 0 )
                )

            else:
                # Retry transient HTTP errors (server overload / rate limiting)
                retryable = response.status_code in ( 429, 502, 503, 504 )
                if retryable and not is_last_attempt:
                    retry_after = response.headers.get( "Retry-After" )
                    if retry_after and retry_after.isdigit():
                        time.sleep( min( int( retry_after ), 5 ) )
                    if debug:
                        print( f"[DEBUG] HTTP {response.status_code} (attempt {attempt_idx}), will retry...", file=sys.stderr )
                    continue

                # Non-retryable or last attempt — fail
                error_text = response.text if response.text else "No error message"
                return AsyncNotificationResponse(
                    success     = False,
                    status      = "error",
                    message     = f"HTTP {response.status_code}: {error_text}",
                    target_user = request.target_user
                )

        except requests.exceptions.ConnectionError:
            if not is_last_attempt:
                if debug:
                    print( f"[DEBUG] ConnectionError (attempt {attempt_idx}), will retry...", file=sys.stderr )
                continue
            return AsyncNotificationResponse(
                success     = False,
                status      = "connection_error",
                message     = f"Cannot reach server at {base_url}. Check that Lupin is running and {ENV_SERVER_URL} is correct.",
                target_user = request.target_user
            )

        except requests.exceptions.Timeout:
            if not is_last_attempt:
                if debug:
                    print( f"[DEBUG] Timeout (attempt {attempt_idx}), will retry...", file=sys.stderr )
                continue
            return AsyncNotificationResponse(
                success     = False,
                status      = "timeout",
                message     = f"Server did not respond within {request.timeout} seconds",
                target_user = request.target_user
            )

        except requests.exceptions.RequestException as e:
            # Request errors - don't retry, fail immediately
            return AsyncNotificationResponse(
                success     = False,
                status      = "error",
                message     = f"Request error: {e}",
                target_user = request.target_user
            )

        except Exception as e:
            # Unexpected errors - don't retry, fail immediately
            return AsyncNotificationResponse(
                success     = False,
                status      = "error",
                message     = f"Unexpected error: {e}",
                target_user = request.target_user
            )

    # Exhausted all retries (should never reach here due to is_last_attempt logic)
    return AsyncNotificationResponse(
        success     = False,
        status      = "user_not_available",
        message     = f"User not available after {total_attempts} attempts",
        target_user = request.target_user
    )


def validate_environment() -> bool:
    """
    Validate environment setup for notification system.

    Requires:
        - urllib.parse module is available

    Ensures:
        - Returns True if all environment checks pass
        - Returns False if any validation issues found
        - Prints detailed validation results

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

    # Validate URL format
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
    CLI entry point for notify_user_async script.

    Parses command-line arguments, validates with Pydantic models, sends
    notification, and exits with appropriate status code.

    Requires:
        - argparse module is available
        - Pydantic models are importable
        - Command line arguments follow expected format

    Ensures:
        - Parses arguments with argparse
        - Validates with Pydantic (AsyncNotificationRequest)
        - Sends notification with notify_user_async()
        - Outputs status messages
        - Exits with code: 0=success, 1=error

    Raises:
        - SystemExit with appropriate exit code
    """

    # Load config early to get global_notification_recipient default (Phase 2.5.4)
    try:
        env = os.getenv( 'LUPIN_ENV', 'local' )
        config = get_api_config( env )
        # NOTE: Config key is 'global_notification_recipient' but CLI flag is '--target-user'
        # for backward compatibility. This naming mismatch is intentional.
        # TODO: Future version should rename CLI flag to --notification-recipient
        default_target_user = config.get( 'global_notification_recipient' )
    except Exception:
        # Config loading failed - no default target_user
        default_target_user = None

    parser = argparse.ArgumentParser(
        description="Send fire-and-forget notification to Lupin (Phase 2.4 with Pydantic)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "Build completed successfully" --type task --priority medium
  %(prog)s "Starting deployment" --type progress --priority low
  %(prog)s "Critical error detected" --type alert --priority urgent
  %(prog)s "Custom message" --type custom

Exit Codes:
  0  Success (notification queued or delivered)
  1  Error (validation, network, user not found)

Environment Variables:
  LUPIN_APP_SERVER_URL            Server URL (default: http://localhost:7999)
  LUPIN_ENV                      Environment name (default: local)
  LUPIN_DEV_EMAIL                Global notification recipient email (overrides config file)
        """
    )

    parser.add_argument(
        "message",
        help="Notification message text"
    )

    parser.add_argument(
        "--type",
        choices=["task", "progress", "alert", "custom"],
        default="custom",
        help="Notification type (default: custom)"
    )

    parser.add_argument(
        "--priority",
        choices=["low", "medium", "high", "urgent"],
        default="medium",
        help="Priority level (default: medium)"
    )

    # Use configured global_notification_recipient if available, otherwise require explicit --target-user
    target_user_help = "Target user email address"
    if default_target_user:
        target_user_help += f" (default from config: {default_target_user})"
    else:
        target_user_help += " (required - configure in ~/.lupin/config or use --target-user)"

    parser.add_argument(
        "--target-user",
        default=default_target_user,
        required=(default_target_user is None),
        help=target_user_help
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
        "--sender-id",
        help="Sender ID (e.g., claude.code@lupin.deepily.ai). Auto-extracted from [PREFIX] in message if not provided."
    )

    parser.add_argument(
        "--validate-env",
        action="store_true",
        help="Validate environment configuration and exit"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output to stderr"
    )

    args = parser.parse_args()

    # Validate environment if requested
    if args.validate_env:
        is_valid = validate_environment()
        sys.exit( 0 if is_valid else 1 )

    try:
        # Construct and validate request model (automatic Pydantic validation)
        request = AsyncNotificationRequest(
            message           = args.message,
            notification_type = NotificationType( args.type ),
            priority          = NotificationPriority( args.priority ),
            target_user       = args.target_user,
            timeout           = args.timeout,
            sender_id         = args.sender_id
        )

    except ValidationError as e:
        # Beautiful error messages from Pydantic
        print( "✗ Invalid parameters:", file=sys.stderr )
        for error in e.errors():
            field = '.'.join( str( loc ) for loc in error['loc'] )
            msg = error['msg']
            print( f"  {field}: {msg}", file=sys.stderr )
        sys.exit( 1 )

    # Send notification
    response = notify_user_async(
        request    = request,
        server_url = args.server,
        debug      = args.debug
    )

    # Output based on response
    if response.success:
        print( f"✓ Notification sent: {response.status}" )
        if response.connection_count > 0:
            print( f"  {response.connection_count} connection(s)" )
        if args.debug and response.target_system_id:
            print( f"  User ID: {response.target_system_id}", file=sys.stderr )
    else:
        print( f"✗ {response.status}: {response.message}", file=sys.stderr )

    sys.exit( 0 if response.success else 1 )


if __name__ == "__main__":
    main()
