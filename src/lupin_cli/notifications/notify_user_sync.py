#!/usr/bin/env python3
"""
Claude Code synchronous notification client with SSE blocking (Phase 2.3).

This script allows Claude Code to send response-required notifications via SSE,
blocking until the user responds or timeout occurs. Uses Pydantic models for
type-safe validation and structured error handling.

Usage:
    python3 notify_user_sync.py "Message" --response-type yes_no --response-default yes
    python3 notify_user_sync.py "Enter API key" --response-type open_ended

Exit Codes:
    0: Success (response received or offline with default)
    1: Error (validation, network, user not found, etc.)
    2: Timeout (no response within timeout period)

Environment Variables:
    LUPIN_APP_SERVER_URL: Server URL (default: http://localhost:7999)
"""

import os
import sys
import time
import requests
import argparse
import json
from typing import Optional
from datetime import datetime, timedelta
from pydantic import ValidationError

# Import Pydantic models
from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    NotificationResponse,
    SSEEvent,
    RespondedEvent,
    ExpiredEvent,
    OfflineEvent,
    ErrorEvent,
    NotificationType,
    NotificationPriority,
    ResponseType
)

# Import config loader for dynamic configuration (Phase 2.5)
from cosa.utils.config_loader import get_api_config, load_api_key

# Import constants (fallbacks)
from lupin_cli.notifications.notification_types import (
    DEFAULT_SERVER_URL,
    ENV_SERVER_URL
)


def consume_sse_stream(
    response: requests.Response,
    timeout_seconds: int,
    debug: bool = False,
    ack_capture: Optional[dict] = None
) -> Optional[SSEEvent]:
    """
    Consume SSE stream from response-required notification endpoint.

    Parses Server-Sent Events stream and validates events using Pydantic models.
    Returns typed event objects (RespondedEvent, ExpiredEvent, etc.) for
    type-safe handling.

    Requires:
        - response is a requests.Response object with stream=True
        - timeout_seconds is a positive integer
        - debug is a boolean

    Ensures:
        - Returns SSEEvent subclass on success
        - Returns None on stream parsing errors or timeout
        - Prints debug messages to stderr if debug=True
        - Validates event structure with Pydantic

    Raises:
        - No exceptions raised (all handled internally)

    Args:
        response: Streaming HTTP response from /api/notify
        timeout_seconds: Timeout in seconds (client-side check)
        debug: Enable debug output to stderr

    Returns:
        SSEEvent: Typed event (RespondedEvent, ExpiredEvent, etc.) or None
    """

    try:
        start_time = datetime.now()

        for line in response.iter_lines():
            # Client-side timeout check (redundant with server, but safe)
            elapsed = ( datetime.now() - start_time ).total_seconds()
            if elapsed > timeout_seconds + 5:  # +5s grace period for network lag
                if debug:
                    print( f"[DEBUG] Client-side timeout after {elapsed:.1f}s", file=sys.stderr )
                return None

            if line:
                decoded = line.decode( 'utf-8' )

                # SSE format: "data: {...}"
                if decoded.startswith( 'data: ' ):
                    data_str = decoded[6:]  # Remove "data: " prefix

                    try:
                        # Parse raw JSON
                        raw_data = json.loads( data_str )

                        if debug:
                            print( f"[DEBUG] Raw SSE data: {raw_data}", file=sys.stderr )

                        # Determine event type and validate with Pydantic
                        status = raw_data.get( 'status' )

                        if status == 'ack':
                            # §4.5 E-a: the opening ack frame — capture this ask's
                            # notification_id for re-attach-after-stream-death, then
                            # keep reading (NOT a terminal event). Additive: a client
                            # that ignores it just continues, exactly as before.
                            if ack_capture is not None and raw_data.get( 'notification_id' ):
                                ack_capture[ 'notification_id' ] = raw_data[ 'notification_id' ]
                            if debug:
                                print( f"[DEBUG] Captured ack notification_id: {raw_data.get( 'notification_id' )}", file=sys.stderr )
                            continue

                        if status == 'responded':
                            event = RespondedEvent( **raw_data )
                        elif status == 'expired':
                            event = ExpiredEvent( **raw_data )
                        elif status == 'offline':
                            event = OfflineEvent( **raw_data )
                        elif status == 'error':
                            event = ErrorEvent( **raw_data )
                        else:
                            # Unknown event type, skip
                            if debug:
                                print( f"[DEBUG] Unknown status: {status}", file=sys.stderr )
                            continue

                        if debug:
                            print( f"[DEBUG] Validated SSE event: {event.model_dump_json()}", file=sys.stderr )

                        # Return final event
                        return event

                    except ValidationError as e:
                        print( f"✗ Invalid SSE event structure: {e}", file=sys.stderr )
                        if debug:
                            print( f"[DEBUG] Raw data: {data_str}", file=sys.stderr )
                        continue

                    except json.JSONDecodeError as e:
                        print( f"✗ Failed to parse SSE event JSON: {e}", file=sys.stderr )
                        if debug:
                            print( f"[DEBUG] Raw data: {data_str}", file=sys.stderr )
                        continue

        # Stream ended without result
        print( "✗ SSE stream ended without result", file=sys.stderr )
        return None

    except Exception as e:
        print( f"✗ SSE stream error: {e}", file=sys.stderr )
        if debug:
            import traceback
            traceback.print_exc( file=sys.stderr )
        return None


def _poll_notification_response( notification_id, base_url, headers, timeout=5 ):
    """
    GET /api/notifications/response/{notification_id} — the re-attach poll read
    (§4.5 E-b). Returns the parsed { state, response_value, responded_at } dict, or
    None on any non-200 / transport failure. Never raises.
    """
    try:
        resp = requests.get(
            f"{base_url}/api/notifications/response/{notification_id}",
            headers = headers,
            timeout = ( 3, timeout )
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except ( requests.exceptions.RequestException, ValueError ):
        return None


def _reattach_after_stream_death(
    notification_id, remaining_seconds, base_url, headers,
    poll_fn=None, poll_interval=2.0, debug=False
):
    """
    Re-attach after the SSE stream died (§4.5 E-c). Poll the response-by-id endpoint
    against the remaining wall-clock budget; decide the outcome on the §3 invariant
    **`responded_at IS NOT NULL`** — never on `state` moving or `response_value`
    being non-null.

    ⚠️ POST-CASCADE CONTRACT AMENDMENT (María, ruling b): a LANDED answer is RETURNED
    to the caller and the row is LEFT OWED — **no ack fires here**. Acking on poll-land
    would mark the row delivered before the value reached the caller ("ack on consume,
    never on serve" one level in), so a death in that window would lose the answer. The
    receipt is the next-turn catch-up's ack (setter b). Fails toward re-delivery (a
    bounded double-SEE), never toward silence.

    Requires:
        - notification_id: the ack id captured from the opening frame (None ⇒ no
          re-attach is possible)
        - remaining_seconds: the wall-clock budget left for the whole ask
        - poll_fn(notification_id) -> row dict|None (dependency-injected in tests;
          defaults to _poll_notification_response)

    Ensures:
        - returns a NotificationResponse with `reattach_state` set:
            * `reattach_unavailable` when notification_id is None (surfaced LOUD)
            * `reattach_armed` once at least one poll has fired
        - responded_at NOT NULL ⇒ RespondedEvent-shaped (status="responded",
          default_used=False), NO ack
        - responded_at NULL WITH a response_value ⇒ manufactured default ⇒
          status="expired", default_used=True, is_timeout=True, NO ack, never responded
        - budget exhausted with no landed answer ⇒ status="expired", is_timeout=True
        - ALWAYS fires at least one poll before returning (E-V3), even at budget≤0
        - never raises
    """
    if not notification_id:
        # The ack id was never captured — no re-attach is possible. Surface it LOUD
        # (an assertable/queryable terminal signal, not a silent no-op).
        if debug:
            print( "[DEBUG] Re-attach unavailable: no ack notification_id captured", file=sys.stderr )
        return NotificationResponse(
            response_value = None, exit_code = 1, status = "stream_error",
            reattach_state = "reattach_unavailable"
        )

    if poll_fn is None:
        poll_fn = lambda nid: _poll_notification_response( nid, base_url, headers )

    deadline = datetime.now() + timedelta( seconds=max( 0, remaining_seconds ) )
    while True:
        # One poll ALWAYS fires before any budget check (E-V3: a dying stream at the
        # deadline still gets its terminal check).
        row = poll_fn( notification_id )
        if row is not None:
            responded_at   = row.get( "responded_at" )
            response_value = row.get( "response_value" )
            if responded_at is not None:
                # LANDED — a human answered. Return it; DO NOT ack (ruling b). Row stays
                # owed so the next-turn catch-up hands it back once and acks then.
                val = response_value.get( "value" ) if isinstance( response_value, dict ) else response_value
                if debug:
                    print( f"[DEBUG] Re-attach LANDED (responded_at set) — returning, leaving owed (no ack)", file=sys.stderr )
                return NotificationResponse(
                    response_value = val, exit_code = 0, status = "responded",
                    default_used = False, reattach_state = "reattach_armed"
                )
            if response_value is not None:
                # responded_at NULL but a value present = a machine default the server
                # manufactured (offline/expired persist), NOT a human answer. Terminal:
                # expired, default_used, no ack. NEVER responded (the §3 invariant).
                val = response_value.get( "value" ) if isinstance( response_value, dict ) else response_value
                return NotificationResponse(
                    response_value = val, exit_code = 2, status = "expired",
                    default_used = True, is_timeout = True, reattach_state = "reattach_armed"
                )
            # responded_at NULL and no value → not answered yet; keep polling until budget.
        if datetime.now() >= deadline:
            return NotificationResponse(
                response_value = None, exit_code = 2, status = "expired",
                is_timeout = True, reattach_state = "reattach_armed"
            )
        time.sleep( min( poll_interval, max( 0.0, ( deadline - datetime.now() ).total_seconds() ) ) )


def _send_sync_notification(
    request: NotificationRequest,
    server_url: Optional[str],
    debug: bool,
    api_key: str,
    base_url: str,
    env: str,
    bearer_token: Optional[str] = None
) -> NotificationResponse:
    """
    Internal helper to send a single sync notification request.

    Used by notify_user_sync() for retry logic. Separated to enable
    exponential backoff retries without code duplication.

    Requires:
        - request is a validated NotificationRequest model
        - At least one of api_key or bearer_token is provided
        - base_url is the server base URL

    Ensures:
        - Returns NotificationResponse with status and response_value
        - Handles all HTTP and SSE errors gracefully
        - Uses Bearer JWT auth when bearer_token is provided, else X-API-Key

    Args:
        request: NotificationRequest model (already validated)
        server_url: Override server URL (for debug output)
        debug: Enable debug output
        api_key: API key for authentication
        base_url: Server base URL
        env: Environment name (for debug output)
        bearer_token: Optional JWT for Bearer auth (takes priority over api_key)

    Returns:
        NotificationResponse: Result of the notification request
    """
    try:
        url = f"{base_url}/api/notify"

        # Convert request to API params (Phase 2.5 - api_key moved to headers)
        params = request.to_api_params()

        # Create auth headers: Bearer JWT (if available) or X-API-Key
        headers = {}
        if bearer_token:
            headers[ "Authorization" ] = f"Bearer {bearer_token}"
        elif api_key:
            headers[ "X-API-Key" ] = api_key

        if debug:
            print( f"[DEBUG] Sending notification to: {url}", file=sys.stderr )
            print( f"[DEBUG] Environment: {env}", file=sys.stderr )
            print( f"[DEBUG] Request model: {request.model_dump_json( indent=2 )}", file=sys.stderr )
            print( f"[DEBUG] API params: {params}", file=sys.stderr )
            print( f"[DEBUG] API key: {api_key[:20]}...{api_key[-10:] if api_key else 'None'}", file=sys.stderr )

        # Send notification with SSE stream.
        # timeout=(connect_timeout, read_timeout) — split tuple so that an
        # unreachable URL fails FAST (3s connect) instead of waiting up to
        # request.timeout_seconds + 10s on TCP SYN retries. Without this split,
        # the idle_waiter smoke test (which deliberately points at an
        # unreachable URL with a 15s subprocess budget) gets SIGKILL'd because
        # OS-level connect timeout dominates the read budget. Connect timeout
        # of 3s is plenty for any localhost or LAN target. Read timeout
        # remains tied to the user's notification window (e.g. 180s for a
        # confirmation prompt), which is the latency we actually need to
        # survive — the user clicking "yes" within their attention budget.
        # Mark the wall-clock start so the §4.5 E-c re-attach knows how much of the
        # ask's budget is left if the SSE stream dies mid-flight.
        _send_start = datetime.now()
        response = requests.post(
            url,
            params  = params,
            headers = headers,
            stream  = True,  # Critical for SSE streaming
            timeout = ( 3, request.timeout_seconds + 10 )
        )

        if response.status_code != 200:
            error_text = response.text if response.text else "No error message"
            print( f"✗ Failed to send notification: HTTP {response.status_code}", file=sys.stderr )
            print( f"  Error: {error_text}", file=sys.stderr )
            return NotificationResponse(
                response_value = None,
                exit_code      = 1,
                status         = f"http_error_{response.status_code}"
            )

        if debug:
            print( f"[DEBUG] ✓ SSE stream connected, waiting for response...", file=sys.stderr )

        # Consume SSE stream (returns typed Pydantic event); capture the opening ack
        # frame's notification_id so we can re-attach if the stream dies (§4.5 E-a/E-c).
        ack_capture = {}
        event = consume_sse_stream( response, request.timeout_seconds, debug, ack_capture=ack_capture )

        if not event:
            # §4.5 E-c (ruling b): the stream died before a terminal event. Rather than
            # returning a bare stream_error (which the caller reads as a false default),
            # re-attach — poll GET /notifications/response/{id} against the remaining
            # budget. A LANDED answer is returned and the row LEFT OWED (no ack here; the
            # next-turn catch-up acks on genuine consume). Fails toward re-delivery,
            # never toward silence. If the ack id was never captured, the re-attach is
            # unavailable and that is surfaced LOUD (reattach_unavailable).
            elapsed   = ( datetime.now() - _send_start ).total_seconds()
            remaining = request.timeout_seconds - elapsed
            print( "✗ SSE stream died — re-attaching via response-by-id poll", file=sys.stderr )
            return _reattach_after_stream_death(
                ack_capture.get( "notification_id" ), remaining, base_url, headers, debug=debug
            )

        if debug:
            print( f"[DEBUG] Final event: {event.model_dump_json()}", file=sys.stderr )

        # Handle different event types (type-safe with isinstance)
        if isinstance( event, RespondedEvent ):
            if debug:
                print( f"✓ Response received: {event.response}", file=sys.stderr )
            return NotificationResponse(
                response_value = event.response,
                exit_code      = 0,
                status         = "responded",
                default_used   = event.default_used
            )

        elif isinstance( event, ExpiredEvent ):
            if event.default_used and event.response:
                if debug:
                    print( f"⏱️ Timeout - using default: {event.response}", file=sys.stderr )
                return NotificationResponse(
                    response_value = event.response,
                    exit_code      = 2,
                    status         = "expired",
                    default_used   = True,
                    is_timeout     = True
                )
            else:
                print( "✗ Notification expired without default", file=sys.stderr )
                return NotificationResponse(
                    response_value = None,
                    exit_code      = 1,
                    status         = "expired_no_default",
                    is_timeout     = True
                )

        elif isinstance( event, OfflineEvent ):
            if debug:
                print( f"⚠️ User offline - used default: {event.response}", file=sys.stderr )
            return NotificationResponse(
                response_value = event.response,
                exit_code      = 0,  # Offline with default = success
                status         = "offline",
                default_used   = True
            )

        elif isinstance( event, ErrorEvent ):
            print( f"✗ Server error: {event.message}", file=sys.stderr )
            return NotificationResponse(
                response_value = None,
                exit_code      = 1,
                status         = "error"
            )

        else:
            # Should never happen with proper typing
            print( f"✗ Unknown event type: {type( event )}", file=sys.stderr )
            return NotificationResponse(
                response_value = None,
                exit_code      = 1,
                status         = "unknown_event"
            )

    except requests.exceptions.ConnectionError:
        print( f"✗ Connection error: Cannot reach server at {base_url}", file=sys.stderr )
        print( f"  Check that Lupin is running and {ENV_SERVER_URL} is correct", file=sys.stderr )
        return NotificationResponse(
            response_value = None,
            exit_code      = 1,
            status         = "connection_error"
        )

    except requests.exceptions.Timeout:
        print( f"✗ Request timeout: Server did not respond", file=sys.stderr )
        return NotificationResponse(
            response_value = None,
            exit_code      = 2,
            status         = "request_timeout",
            is_timeout     = True
        )

    except requests.exceptions.RequestException as e:
        print( f"✗ Request error: {e}", file=sys.stderr )
        return NotificationResponse(
            response_value = None,
            exit_code      = 1,
            status         = "request_exception"
        )

    except Exception as e:
        print( f"✗ Unexpected error: {e}", file=sys.stderr )
        if debug:
            import traceback
            traceback.print_exc( file=sys.stderr )
        return NotificationResponse(
            response_value = None,
            exit_code      = 1,
            status         = "unexpected_exception"
        )


def notify_user_sync(
    request: NotificationRequest,
    server_url: Optional[str] = None,
    debug: bool = False,
    retry_on_timeout: bool = False,
    max_attempts: int = 1,
    backoff_multiplier: float = 2.0,
    bearer_token: Optional[str] = None
) -> NotificationResponse:
    """
    Send response-required notification with SSE blocking.

    Sends notification to Lupin API and blocks until user responds or timeout.
    Uses Pydantic models for type-safe request/response handling.

    Requires:
        - request is a validated NotificationRequest model
        - server_url is None or a valid HTTP/HTTPS URL
        - debug is a boolean
        - If retry_on_timeout=True, max_attempts >= 1

    Ensures:
        - Returns NotificationResponse with exit_code and response_value
        - exit_code 0: Success (response received or offline with default)
        - exit_code 1: Error (network, validation, etc.)
        - exit_code 2: Timeout (no response within timeout)
        - If retry_on_timeout=True: Retries on timeout with exponential backoff
        - Respects max_attempts limit
        - Prints status messages to stderr
        - Uses SSE streaming for blocking until response

    Raises:
        - No exceptions raised (all handled internally)

    Args:
        request: NotificationRequest model (already validated)
        server_url: Override server URL (uses env var if None)
        debug: Enable debug output to stderr
        retry_on_timeout: Retry with exponential backoff on timeout (default: False)
        max_attempts: Maximum number of attempts if retry_on_timeout=True (default: 1)
        backoff_multiplier: Multiplier for timeout on each retry (default: 2.0)
        bearer_token: Optional JWT for Bearer auth (used instead of API key when provided)

    Returns:
        NotificationResponse: Typed response with exit_code, response_value, metadata
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
        env = "fallback"

    # Resolve target_user if not explicitly set
    if request.target_user is None:
        from lupin_cli.notifications.notification_models import resolve_target_user
        request = request.model_copy( update={ "target_user": resolve_target_user() } )

    # Track current timeout for exponential backoff
    current_timeout = request.timeout_seconds
    attempts_made = 0
    response = None

    while attempts_made < max_attempts:
        attempts_made += 1

        # Create a copy of the request with updated timeout for this attempt
        request_copy = request.model_copy()
        request_copy.timeout_seconds = current_timeout

        if debug:
            print( f"[SYNC] Attempt {attempts_made}/{max_attempts}, timeout={current_timeout}s", file=sys.stderr )

        response = _send_sync_notification(
            request_copy, server_url, debug, api_key, base_url, env, bearer_token
        )

        # Check if we got a response or should retry
        if response.status == "responded":
            # Success - user responded
            return response
        elif response.is_timeout and retry_on_timeout and attempts_made < max_attempts:
            # Timeout - retry with exponential backoff
            current_timeout = int( current_timeout * backoff_multiplier )
            if debug:
                print( f"[SYNC] Timeout on attempt {attempts_made}, retrying with {current_timeout}s...", file=sys.stderr )
            continue
        else:
            # Not retrying (offline, error, or final attempt)
            return response

    # Should have returned from the loop, but return last response as fallback
    return response


def main():
    """
    CLI entry point for notify_user_sync script.

    Parses command-line arguments, validates with Pydantic models, sends
    notification, and exits with appropriate status code.

    Requires:
        - argparse module is available
        - Pydantic models are importable
        - Command line arguments follow expected format

    Ensures:
        - Parses arguments with argparse
        - Validates with Pydantic (NotificationRequest)
        - Sends notification with notify_user_sync()
        - Outputs response value to stdout on success
        - Outputs error messages to stderr
        - Exits with code: 0=success, 1=error, 2=timeout

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
        description="Send response-required notification to Lupin (Phase 2.3 SSE blocking)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "Approve deployment?" --response-type yes_no --response-default yes
  %(prog)s "Delete database?" --response-type yes_no --response-default no --timeout 60
  %(prog)s "Enter API key" --response-type open_ended
  %(prog)s "Commit message?" --response-type open_ended --response-default "Auto-commit"

Exit Codes:
  0  Success (response received or offline with default)
  1  Error (validation, network, user not found, etc.)
  2  Timeout (no response within timeout period)

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
        "--response-type",
        required=True,
        choices=["yes_no", "open_ended"],
        help="Response type (yes_no or open_ended)"
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
        default=120,
        help="Response timeout in seconds (default: 120)"
    )

    parser.add_argument(
        "--response-default",
        help="Default response value for timeout/offline (e.g., 'yes', 'no', or custom text)"
    )

    parser.add_argument(
        "--title",
        help="Terse technical title for voice-first UX (optional)"
    )

    parser.add_argument(
        "--sender-id",
        help="Sender ID (e.g., claude.code@lupin.deepily.ai). Auto-extracted from [PREFIX] in message if not provided."
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output to stderr"
    )

    args = parser.parse_args()

    try:
        # Construct and validate request model (automatic Pydantic validation)
        request = NotificationRequest(
            message            = args.message,
            response_type      = ResponseType( args.response_type ),
            notification_type  = NotificationType( args.type ),
            priority           = NotificationPriority( args.priority ),
            target_user        = args.target_user,
            timeout_seconds    = args.timeout,
            response_default   = args.response_default,
            title              = args.title,
            sender_id          = args.sender_id
        )

    except ValidationError as e:
        # Beautiful error messages from Pydantic
        print( "✗ Invalid parameters:", file=sys.stderr )
        for error in e.errors():
            field = '.'.join( str( loc ) for loc in error['loc'] )
            msg = error['msg']
            print( f"  {field}: {msg}", file=sys.stderr )
        sys.exit( 1 )

    # Send notification and wait for response
    response = notify_user_sync(
        request    = request,
        server_url = args.server,
        debug      = args.debug
    )

    # Output response value to stdout (for bash script capture)
    if response.response_value:
        print( response.response_value )

    sys.exit( response.exit_code )


if __name__ == "__main__":
    main()
