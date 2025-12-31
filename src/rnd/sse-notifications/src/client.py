#!/usr/bin/env python3
"""
Python SSE Client with Timeout Handling

Consumes Server-Sent Events stream from FastAPI server with:
- Timeout handling (2-minute default)
- Stream multiplexing (stderr for diagnostics, stdout for result)
- Graceful error handling

Usage:
    python client.py <message> [heartbeat_interval] [timeout]

Examples:
    python client.py "Test message" 5 120
    python client.py "Quick test" 5 30
"""

import requests
import json
import sys
from datetime import datetime, timedelta


def consume_sse( url: str, message: str, heartbeat_interval: int = 5, timeout_seconds: int = 120 ):
    """
    Consumes SSE stream with timeout handling.

    Requires:
        - url is a valid HTTP URL string
        - message is a string (can be empty)
        - heartbeat_interval is a positive integer (seconds)
        - timeout_seconds is a positive integer (seconds)

    Ensures:
        - Returns final result string on success
        - Returns None on timeout or error
        - Diagnostics printed to stderr
        - Result printed to stdout (by caller)

    Raises:
        - No exceptions raised (all handled internally)

    Returns:
        - str: Final result on success
        - None: On timeout or error
    """
    payload = {
        "message": message,
        "heartbeat_interval": heartbeat_interval
    }

    try:
        start_time = datetime.now()

        with requests.post(
            url,
            json=payload,
            stream=True,
            timeout=( 10, timeout_seconds )  # (connect timeout, read timeout)
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines():
                # Check timeout
                if ( datetime.now() - start_time ).total_seconds() > timeout_seconds:
                    print( f"ERROR: Timeout after {timeout_seconds}s", file=sys.stderr )
                    return None

                if line:
                    decoded = line.decode( 'utf-8' )

                    # SSE format: "data: "
                    if decoded.startswith( 'data: ' ):
                        data_str = decoded[6:]  # Remove "data: " prefix

                        try:
                            event = json.loads( data_str )
                            event_type = event.get( 'type' )

                            if event_type == 'ack':
                                print( f"[ACK] {event.get( 'message' )}", file=sys.stderr )

                            elif event_type == 'heartbeat':
                                print( f"[HEARTBEAT] Elapsed: {event.get( 'elapsed' )}s", file=sys.stderr )

                            elif event_type == 'result':
                                # Final result - return it
                                return event.get( 'data' )

                        except json.JSONDecodeError as e:
                            print( f"ERROR: Failed to parse event: {e}", file=sys.stderr )

            # Stream ended without result
            print( "ERROR: Stream ended without result", file=sys.stderr )
            return None

    except requests.exceptions.Timeout:
        print( f"ERROR: Request timeout after {timeout_seconds}s", file=sys.stderr )
        return None
    except requests.exceptions.RequestException as e:
        print( f"ERROR: Request failed: {e}", file=sys.stderr )
        return None


if __name__ == "__main__":
    if len( sys.argv ) < 2:
        print( "Usage: python client.py <message> [heartbeat_interval] [timeout]", file=sys.stderr )
        sys.exit( 1 )

    message = sys.argv[1]
    heartbeat_interval = int( sys.argv[2] ) if len( sys.argv ) > 2 else 5
    timeout = int( sys.argv[3] ) if len( sys.argv ) > 3 else 120

    url = "http://localhost:8000/process"
    result = consume_sse( url, message, heartbeat_interval, timeout )

    if result:
        print( result )  # stdout for the result
        sys.exit( 0 )
    else:
        sys.exit( 1 )
