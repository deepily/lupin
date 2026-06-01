"""
Cosa-voice speakerphone endpoints.

Per-session "speakerphone" toggle backed by the SessionStart bridge file
at ~/.claude/sessions/cc-{PPID}.json. When `speakerphone_on=True`, Claude
auto-calls notify(full_text, suppress_ding=True) after every assistant turn so
the user can hold a voice dialogue at a distance (notification UI listening via
TTS rather than reading the terminal). Default = mode-aware: False in solo,
True in chorus (see lupin-app.ini `tts interaction mode`).

Activation surfaces (all four converge here or on the cosa-voice MCP tool):
    - Voice phrase: "enable speakerphone" → MCP enable_speakerphone()
    - Slash command: /speakerphone-on → MCP enable_speakerphone()
    - MCP tool: enable_speakerphone() / disable_speakerphone() (writes bridge directly)
    - UI toggle button: POST to this router (writes bridge AND broadcasts WS event)

The bridge file is the single source of truth. UI clients hold a localStorage
read-through cache, hydrated by the GET endpoint and the speakerphone_changed
WebSocket event broadcast on POST.

## Mode-conditional behavior (Phase 3 of solo/chorus refactor)

Activation behavior branches on `get_tts_interaction_mode()` from
cosa.utils.util:

- **Solo branch** (preserve today's monopoly behavior pixel-perfect):
  asyncio.Lock + scan-for-active + atomic displace + activate self + broadcast.
  Response includes `displaced_sessions: [...]` listing the SIDs the activation
  pushed off.

- **Chorus branch** (new): no Lock, no scan. Activate self + broadcast.
  Response includes `displaced_sessions: []` (always empty; kept in schema for
  response-shape stability so UI clients don't need to special-case modes).

Deactivate is mode-independent: same set-speakerphone-false + broadcast +
self-action push under both branches.

Generated on: 2026-04-27, renamed + mode-conditionalized 2026-05-12.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..middleware.api_key_auth import require_api_key_or_jwt
from ..notification_fifo_queue import NotificationFifoQueue

# Bridge helpers live in the parent Lupin tree, but importing them is fine
# (only git ops on src/cosa/ are restricted from parent context — imports are not).
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_speakerphone, set_speakerphone, find_session_path_by_id,
    find_active_speakerphone_sessions, build_sender_id_for_cc
)

# TTS interaction mode helper (Phase 1). Defers actual read to function-call time
# so module import is side-effect-free and avoids any circular-import risk.
from cosa.utils import util as cu


router = APIRouter( prefix="/api/cosa-voice", tags=[ "cosa-voice" ] )

# Module-level lock serializes activate-POSTs in SOLO mode so the scan + displace
# + activate sequence is atomic within this process. If two tabs POST concurrently
# to activate different sessions, the lock ensures one fully completes (including
# displacing the other's previously-active session) before the second runs.
# Single-process uvicorn assumed — see "Risks / gotchas" #7 in the design doc
# addendum at src/rnd/v0.1.7/2026.04.27-conversation-mode-design.md §11 for
# the multi-worker caveat. NOT taken in chorus mode (no displacement).
_speakerphone_lock = asyncio.Lock()


# ── Dependency injection (mirrors notifications.router pattern) ──────────────

def get_notification_queue():
    """
    Dependency to get the singleton NotificationFifoQueue from main module.

    Ensures:
        - Returns the singleton NotificationFifoQueue instance
        - Raises ImportError if main module not yet initialized
    """
    import fastapi_app.main as main_module
    return main_module.jobs_notification_queue


# ── Models ───────────────────────────────────────────────────────────────────

class SpeakerphoneBody( BaseModel ):
    """
    POST body for setting speakerphone state.

    Requires:
        - on is a bool (True to enable speakerphone, False to disable)
    """
    on: bool


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get(
    "/speakerphone/{session_id}",
    summary     = "Get speakerphone flag for a session",
    description = "Returns the speakerphone_on flag from the cosa-voice session bridge file."
)
async def get_speakerphone_endpoint(
    session_id: str,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ]
) -> JSONResponse:
    """
    Read speakerphone_on for the given Claude Code session_id.

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)
        - Caller is authenticated (JWT or API key)

    Ensures:
        - Returns 200 with {session_id, on: bool} when bridge exists
        - Returns 404 when no bridge file matches the session_id
        - When bridge exists but speakerphone_on field is absent, uses the
          mode-aware default from get_speakerphone (solo→False, chorus→True)

    Args:
        session_id: Claude Code session ID to look up
        authenticated_user_id: Auth dependency (unused but required for gating)

    Returns:
        JSONResponse: {"session_id": str, "on": bool}
    """
    if not find_session_path_by_id( session_id ):
        raise HTTPException( status_code=404, detail=f"No active session bridge found for session_id={session_id}" )

    on = get_speakerphone( session_id )
    return JSONResponse( content={ "session_id": session_id, "on": on } )


@router.post(
    "/speakerphone/{session_id}",
    summary     = "Set speakerphone flag for a session",
    description = "Writes speakerphone_on to the bridge file and broadcasts a speakerphone_changed WebSocket event so all connected UI tabs sync. In solo mode, activating displaces any other active session. In chorus mode, multiple sessions can be active simultaneously."
)
async def set_speakerphone_endpoint(
    session_id: str,
    body: SpeakerphoneBody,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    notification_queue: NotificationFifoQueue = Depends( get_notification_queue )
) -> JSONResponse:
    """
    Flip speakerphone_on for the given session_id and broadcast.

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)
        - body.on is a bool
        - Caller is authenticated

    Ensures:
        - Writes speakerphone_on to the matching bridge file
        - Returns 200 with {session_id, on, broadcast_delivered, displaced_sessions} on success
        - Returns 404 if no bridge matches
        - Returns 500 if bridge found but write failed
        - In SOLO mode + body.on=True: scans for other active speakerphone sessions
          and displaces them atomically (asyncio.Lock-serialized) before activating self
        - In CHORUS mode + body.on=True: no displacement; only self is activated;
          response still includes displaced_sessions=[] for shape stability
        - Broadcasts speakerphone_changed event to the authenticated user's
          WebSocket sessions (other tabs of the same user). Broadcast failures are
          logged but do not fail the endpoint — the bridge write is the canonical
          state.

    Args:
        session_id: Claude Code session ID to flip
        body: { on: bool }
        authenticated_user_id: Auth dependency, also used as broadcast target
        notification_queue: NotificationFifoQueue dependency for WS broadcast

    Returns:
        JSONResponse: {"session_id", "on", "broadcast_delivered", "displaced_sessions"}
    """
    if not find_session_path_by_id( session_id ):
        raise HTTPException( status_code=404, detail=f"No active session bridge found for session_id={session_id}" )

    displaced_sessions = []
    mode               = cu.get_tts_interaction_mode()

    # Activation path — diverges by mode.
    # SOLO: lock + scan + displace + activate (today's monopoly behavior).
    # CHORUS: no lock, no scan; just activate self.
    # Deactivation (body.on=False) is mode-independent and takes neither lock
    # nor scan in either mode.
    if body.on:
        if mode == "solo":
            async with _speakerphone_lock:
                others = find_active_speakerphone_sessions( exclude_session_id=session_id )
                for _other_path, other_sid in others:
                    if not set_speakerphone( other_sid, False ):
                        print( f"[SPEAKERPHONE] ⚠️ Failed to displace session {other_sid} (bridge write failed)" )
                        continue
                    displaced_sessions.append( other_sid )
                    # Broadcast displaced event so the affected session's tabs flip
                    # their toggle, unpin the card, and pause any in-flight TTS.
                    # Routed through the canonical notification subsystem with a
                    # custom type value (see 2026.04.29 ws-event-cleanup R&D doc).
                    try:
                        notification_queue.push_notification(
                            message            = "",
                            type               = "speakerphone_changed",
                            user_id            = authenticated_user_id,
                            sender_id          = build_sender_id_for_cc( other_sid ),
                            suppress_ding      = True,
                            response_requested = False,
                            payload            = {
                                "session_id"   : other_sid,
                                "on"           : False,
                                "displaced"    : True,
                                "displaced_by" : session_id
                            }
                        )
                    except Exception as ws_err:
                        # Bridge write succeeded; broadcast is best-effort
                        print( f"[SPEAKERPHONE] ⚠️ Displace-notify push failed for {other_sid}: {ws_err}" )

                    # Action push: nudge the displaced session's listener to
                    # inject the speakerphone-exit system-reminder into tmux.
                    # This corrects the model's in-context assumption that
                    # speakerphone is still active — the bridge flip alone is
                    # silent to the model. The listener filters by 8-char
                    # job_id; cc_notification_listener._handle_action routes
                    # title="action:disable_speakerphone" through the
                    # _inject_disable_speakerphone_reminder shim which calls
                    # hook_common.speakerphone_exit_reminder( mode ) for the
                    # mode-appropriate body.
                    try:
                        notification_queue.push_notification(
                            message            = "",
                            type               = "user_initiated_message",
                            title              = "action:disable_speakerphone",
                            user_id            = authenticated_user_id,
                            sender_id          = build_sender_id_for_cc( other_sid ),
                            job_id             = other_sid[:8],
                            suppress_ding      = True,
                            response_requested = False,
                        )
                    except Exception as action_err:
                        # Listener push is best-effort; if it fails, the next
                        # user prompt will still hydrate correctly via the
                        # UserPromptSubmit hook reading the (now-false) bridge.
                        print( f"[SPEAKERPHONE] ⚠️ Disable-action push failed for {other_sid}: {action_err}" )

                # Now activate ours inside the same critical section so no parallel
                # request can sneak in between displace and activate.
                ok = set_speakerphone( session_id, body.on )
                if not ok:  # pragma: no branch - async-with __aexit__ trailing-if artifact: last stmt in the SOLO `async with _speakerphone_lock` body, so the ok=True false-arc exit (254->270) routes through the implicit __aexit__ lock-release and is not a markable bytecode edge though the success path is exercised; both write arms (success + 500) are tested
                    raise HTTPException( status_code=500, detail=f"Bridge write failed for session_id={session_id}" )
        else:
            # CHORUS mode: no Lock, no scan. Multiple sessions can be active.
            ok = set_speakerphone( session_id, body.on )
            if not ok:
                raise HTTPException( status_code=500, detail=f"Bridge write failed for session_id={session_id}" )
    else:
        # Deactivation — mode-independent, no Lock needed.
        ok = set_speakerphone( session_id, body.on )
        if not ok:
            raise HTTPException( status_code=500, detail=f"Bridge write failed for session_id={session_id}" )

    # Route the self-state-change broadcast through the canonical notification subsystem
    # with a custom type value. See:
    # src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md
    broadcast_delivered = False
    try:
        notification_queue.push_notification(
            message            = "",
            type               = "speakerphone_changed",
            user_id            = authenticated_user_id,
            sender_id          = build_sender_id_for_cc( session_id ),
            suppress_ding      = True,
            response_requested = False,
            payload            = {
                "session_id" : session_id,
                "on"         : body.on
            }
        )
        broadcast_delivered = True
    except Exception as ws_err:
        # Log but do not fail — bridge write succeeded; broadcast is best-effort
        print( f"[SPEAKERPHONE] ⚠️ Notification push failed for session {session_id}: {ws_err}" )

    # Self-exit symmetry: when deactivating, also push the listener-targeted
    # action so the model's in-context state catches up to the bridge flip.
    # Mirror of the displace branch's per-session action push above (search
    # for title="action:disable_speakerphone" in the activate path); the
    # listener filters by job_id matching the 8-char session hash, then
    # cc_notification_listener._handle_action routes the title through the
    # _inject_disable_speakerphone_reminder shim which calls
    # hook_common.speakerphone_exit_reminder for the body (Phase 5 rename).
    # See: src/rnd/v0.1.7/2026.05.05-conv-mode-self-exit-signal-gap/01-design.md
    if not body.on:
        try:
            notification_queue.push_notification(
                message            = "",
                type               = "user_initiated_message",
                title              = "action:disable_speakerphone",
                user_id            = authenticated_user_id,
                sender_id          = build_sender_id_for_cc( session_id ),
                job_id             = session_id[:8],
                suppress_ding      = True,
                response_requested = False,
                payload            = { "session_id": session_id, "reason": "self" }
            )
        except Exception as action_err:
            # Best-effort — bridge flip is canonical; the next prompt will
            # still hydrate correctly via the gated layers (speakerphone_wrap,
            # speakerphone_reminder_block) that read the now-false bridge.
            print( f"[SPEAKERPHONE] ⚠️ Self-disable action push failed for {session_id}: {action_err}" )

    return JSONResponse( content={
        "session_id"          : session_id,
        "on"                  : body.on,
        "broadcast_delivered" : broadcast_delivered,
        "displaced_sessions"  : displaced_sessions
    } )
