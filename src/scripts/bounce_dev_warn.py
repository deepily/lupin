#!/usr/bin/env python3
"""
Host-side warning broadcaster for the managed `:7999` bounce (R4, sanctioned path).

POSTs the pre-bounce warning to the running server, reads `recipients` from the
200 body, then polls `io/commons/broadcast-acks.md` until every recipient has
acked (deduped by distinct session) or a deadline. This is the ONLY proof the
warning was DELIVERED, not merely queued: a 200 means the fanout was SCHEDULED
(`emit_to_user_sync` never awaits its push future — websocket_manager.py:553),
so counting on 200 alone races the restart and can warn nobody.

Exit codes:
    0 — warning confirmed reached every recipient (or zero active sessions)
    1 — partial reach at the deadline (some recipients never acked)
    2 — transport / HTTP failure posting the warning (server likely wedged)

Invoked by `src/scripts/bounce-dev-server.sh` BEFORE it restarts the container.
The pure poll + dedupe logic lives in `cosa.rest.managed_bounce_broadcast` and is
unit-tested there; this file is the I/O boundary (HTTP + filesystem + clock).
"""

import os
import sys
import time

# ── Bootstrap: runs before `cosa` is importable (entry-point exception) ───────
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    print( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project", file=sys.stderr )
    sys.exit( 2 )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

from cosa.rest.managed_bounce_broadcast import build_bounce_message, poll_acks_until_satisfied, resolve_ack_timing
from lupin_cli.claude_code.hooks.lib.task_store_client import read_api_key, _request
from lupin_mcp.commons_store import CommonsStore


DEFAULT_BASE_URL       = "http://localhost:7999"
BROADCAST_PATH         = "/api/commons/broadcast-to-cc-sessions"
# Fallbacks ONLY — the live values come from config (see _ack_timing). ⚠️ 8s is a
# GUESS, not a measurement; it is the sharper-consequence duration (too short =
# restart while the warning is still in flight). Tune via the INI key, not here.
DEFAULT_ACK_DEADLINE_S = 8.0
DEFAULT_ACK_POLL_S     = 0.25


def _ack_timing():
    """
    Resolve the warning ack deadline + poll interval from config.

    The resolve LOGIC lives in the measured module (resolve_ack_timing); this
    function is only the fail-soft BOUNDARY — building a ConfigurationManager can
    raise in a bare host context, and the bounce must never be blocked by config
    plumbing, so on any failure it falls back to the module defaults and says so.
    """
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        cfg = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        return resolve_ack_timing( cfg, default_deadline=DEFAULT_ACK_DEADLINE_S, default_poll=DEFAULT_ACK_POLL_S )
    except Exception as e:                                        # noqa: BLE001 — config plumbing must never block a bounce
        print( f"[bounce-warn] config unavailable ({e}); using default ack timing {DEFAULT_ACK_DEADLINE_S}s / {DEFAULT_ACK_POLL_S}s", file=sys.stderr )
        return DEFAULT_ACK_DEADLINE_S, DEFAULT_ACK_POLL_S


def main() -> int:
    base_url = os.environ.get( "LUPIN_BOUNCE_BASE_URL", DEFAULT_BASE_URL )
    api_key  = read_api_key()
    # BOUNCE_DIRTY_FILES (row 7de5a09f) — the bounce script exports the dirty-tree
    # `git status --short` blob here so the warning NAMES the uncommitted files it
    # will deploy. Empty / unset when the tree is clean. This is how the owner of a
    # dirty file gets told during the ack window even when the bouncer is a non-TTY
    # agent whose confirmation prompt was skipped.
    dirty_files = os.environ.get( "BOUNCE_DIRTY_FILES" ) or None
    message  = build_bounce_message( "warning", dirty_files=dirty_files )
    ack_deadline_s, ack_poll_s = _ack_timing()

    # Post the warning. require_ack=True so each recipient's listener writes an
    # ack we can wait on.
    ok, status, body = _request(
        "POST", base_url + BROADCAST_PATH, api_key, timeout=10.0,
        body={ "message": message, "require_ack": True },
    )
    if not ok or not isinstance( body, dict ):
        print( f"[bounce-warn] ✗ could not post warning (status={status}): {body}", file=sys.stderr )
        return 2

    broadcast_id = body.get( "broadcast_id" )
    # Key the wait on `recipients` (successful PUSHES, commons.py:497), NOT
    # len(sessions)/expected_recipients (:492). recipients is what actually got a
    # push scheduled; a recipient whose push threw is not one we can wait for. Do
    # not "helpfully" change this to len(sessions) — it would wait forever on a
    # recipient that never receives.
    recipients   = body.get( "recipients", 0 )
    filtered_out = body.get( "filtered_out", [] )

    if recipients == 0:
        # Real branch, not an error: status "no-active-sessions" (commons.py:464).
        print( f"[bounce-warn] no active sessions to warn (filtered_out={len( filtered_out )}). Proceeding." )
        return 0

    store  = CommonsStore( lupin_root )
    result = poll_acks_until_satisfied(
        read_entries_fn       = lambda: store.read( "broadcast-acks", limit=1000 ),
        broadcast_id          = broadcast_id,
        expected_recipients   = recipients,
        deadline_seconds      = ack_deadline_s,
        poll_interval_seconds = ack_poll_s,
        now_fn                = time.monotonic,
        sleep_fn              = time.sleep,
    )

    if result[ "satisfied" ]:
        print( f"[bounce-warn] ✓ warning reached all {result[ 'acked' ]}/{recipients} recipient(s) in {result[ 'elapsed' ]:.2f}s." )
        return 0

    # Partial reach — proceed with the bounce but SAY how many of how many acked
    # before the kill ("warned N of M" is actionable; a silent proceed is the
    # guessed-pause failure this ack-confirmation replaced).
    print(
        f"[bounce-warn] ⚠ warned {result[ 'acked' ]} of {recipients} recipient(s) "
        f"before the {ack_deadline_s}s deadline. Proceeding with the bounce anyway.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit( main() )
