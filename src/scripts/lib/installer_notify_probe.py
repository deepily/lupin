#!/usr/bin/env python3
"""
Send one test notification for install-cosa-voice.sh and say what happened.

The installer used to print `fail` for every unsuccessful reply, hide stderr, and exit 0.
This helper keeps the notifier's own status and message, and separates three outcomes.

Usage:
    installer_notify_probe.py <server_url>        (LUPIN_ROOT must be set)

Prints one line: `ok: ...`, `skipped: ...` or `fail: <status>: <message>`.
Exit codes:  0 delivered  ·  3 skipped, nobody is listening  ·  1 failed
"""
import os
import sys

EXIT_OK      = 0
EXIT_FAILED  = 1
EXIT_SKIPPED = 3

# The server accepted and authenticated the request but no WebSocket listener is connected.
NO_LISTENER_STATUS = "user_not_available"


def classify( resp ):
    """
    Turn a notifier reply into an exit code and a one-line verdict.

    Requires:
        - resp is an AsyncNotificationResponse-like object, or None

    Ensures:
        - returns ( exit_code, line ); the line starts with ok, skipped or fail
    """
    if resp is None: return EXIT_FAILED, "fail: no response from the notifier"
    # The server answers a no-listener send with success=True and this status, so the status
    # is read first: checking success first reported "delivered" for a send nobody received.
    if resp.status == NO_LISTENER_STATUS:
        return EXIT_SKIPPED, f"skipped: {resp.status}: {resp.message}"
    if resp.success: return EXIT_OK, f"ok: {resp.status}"
    return EXIT_FAILED, f"fail: {resp.status}: {resp.message}"


def main( argv ):
    """Run the probe. Requires LUPIN_ROOT in the environment and a server URL argument."""
    lupin_root = os.environ.get( "LUPIN_ROOT" )
    if lupin_root is None: raise RuntimeError( "LUPIN_ROOT not set" )
    if len( argv ) != 2:   raise RuntimeError( "usage: installer_notify_probe.py <server_url>" )
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path: sys.path.insert( 0, src_path )
    from lupin_cli.notifications.notify_user_async import notify_user_async
    from lupin_cli.notifications.notification_models import (
        AsyncNotificationRequest, NotificationType, NotificationPriority )
    try:
        req = AsyncNotificationRequest(
            message           = "cosa-voice bootstrapper: test notification",
            notification_type = NotificationType.PROGRESS,
            priority          = NotificationPriority.LOW,
            sender_id         = "claude.code@installer.deepily.ai",
            server_url        = argv[ 1 ]
        )
        resp = notify_user_async( req )
    except Exception as e:
        print( f"fail: {type( e ).__name__}: {e}" )
        return EXIT_FAILED
    rc, line = classify( resp )
    print( line )
    return rc


if __name__ == "__main__":
    sys.exit( main( sys.argv ) )
