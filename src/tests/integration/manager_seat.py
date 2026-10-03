"""
A declared manager seat for an integration test's caller — the one way the priority firewall
lets a test file above P5.

HOW THE FIREWALL DECIDES (src/cosa/rest/task_priority_firewall.py, `caller_is_manager_by_bridge`
→ `session_id_from_actor` → `manager_figure.is_manager_figure`): the create door takes the
caller's `actor` string, reads the LAST whitespace token as a session id (8+ hex characters),
finds that session's bridge file under the sessions directory, and answers True when the
bridge's `role` is "manager". Nothing else is consulted, and nothing here widens it.

WHAT THIS DOES: writes one bridge file `cc-itest-mgr-<8 hex>.json` with `role: "manager"` into
the same sessions directory the server container reads (the rw bind the cc-transcript fixture
already uses), hands back the matching `actor`, and removes the file on exit. It uses no
operator credential and it supplies NO login account, so it cannot admit a row out of
`not_approved`, close one as won't-fix, or create at P0 — those stay the operator's, by rule.

⚠️ THE FILE NAME MATTERS TWICE. `cc-itest-*.json` is what `swept_cc_itest_bridges` removes at
session start after a crashed run, and a name that is not `cc-<pid>.json` is never read as a
PID, so the liveness skip does not apply to it.
"""

import json
import os
import uuid
from contextlib import contextmanager

# Overridable for a non-default compose setup; the same variable the cc-transcript fixture reads.
HOST_SESSIONS_DIR = os.environ.get( "LUPIN_HOST_SESSIONS_DIR", os.path.expanduser( "~/.claude/sessions" ) )

BRIDGE_PREFIX = "cc-itest-mgr-"


def new_seat_ids():
    """
    A fresh ( session_id, actor ) pair for one manager seat.

    Ensures:
        - session_id is a full UUID string
        - actor is "itest manager <first 8 hex of session_id>", which is the shape
          `session_id_from_actor` reads: the last token, hex, 8 or more characters
    """
    session_id = str( uuid.uuid4() )
    return session_id, f"itest manager {session_id[ :8 ]}"


@contextmanager
def manager_seat( session_id, role="manager", sessions_dir=None ):
    """
    Hold a session bridge declaring `role` for `session_id`, and remove it on exit.

    Requires:
        - session_id is a UUID string, the one `new_seat_ids` returned
        - sessions_dir is a writable directory, or None for HOST_SESSIONS_DIR

    Ensures:
        - the bridge file appears atomically (a rename), so no scanner can read it half-written
        - the bridge file exists for the whole `with` body and is gone after it, including
          when the body raises
        - a failed write leaves no scratch file and no bridge behind
        - the file carries `session_id`, `stable_session_id`, `role` and `project`, the
          fields a real bridge carries that the firewall's reader uses
        - yields the bridge's path
        - role other than "manager" is allowed so a test can prove the control: a worker
          bridge must NOT pass the firewall
    """
    directory = sessions_dir if sessions_dir is not None else HOST_SESSIONS_DIR
    path      = os.path.join( directory, f"{BRIDGE_PREFIX}{session_id[ :8 ]}.json" )
    payload   = {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "role"              : role,
        "project"           : "lupin",
        "persona_name"      : "Itest Manager Seat",
    }
    # ATOMIC: the bridge appears whole or not at all. Scanners glob `cc-*.json` and count a file
    # they cannot parse as an unattributable bridge, so the content is written under a name that
    # glob does not match and moved into place with one rename.
    scratch = os.path.join( directory, f".{BRIDGE_PREFIX}{session_id[ :8 ]}.tmp" )
    try:
        with open( scratch, "w", encoding="utf-8" ) as handle:
            json.dump( payload, handle, indent=2 )
        os.replace( scratch, path )
    finally:
        if os.path.exists( scratch ): os.remove( scratch )
    try:
        yield path
    finally:
        if os.path.exists( path ): os.remove( path )
