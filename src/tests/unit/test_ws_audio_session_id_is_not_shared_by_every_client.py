"""
Guard: the docs must not claim EVERY client shares one session id between its
queue and audio WebSockets. Two of the three clients do; the live web app does
not, and the docs said otherwise in three places.

WHAT WAS MEASURED (2026-09-01, worker Rio, at the sha this file lands on):

| client                                                    | queue id | audio id |
|-----------------------------------------------------------|----------|----------|
| lupin-mobile `enhanced_websocket_service.dart:740-741`     | `_sessionId`        | the SAME `_sessionId` |
| web multiplexer `multiplexer/boot.ts:623-624`              | `sessionId`         | the SAME `sessionId`  |
| web app `static/js/notifications.js:2441-2442`             | `notifications_queue_session_id` | `notifications_audio_session_id` — a SEPARATE `/api/get-session-id` fetch |

So the observed pair 'foolish goat' (queue) / 'slow zebra' (audio) under one
user is notifications.js behaving exactly as written, not a defect. It is also
not an accident: TTS requests from that client carry `audioSessionId`
explicitly (notifications.js:4308, 4316, 4368, 4376), so the audio socket is
ADDRESSED by its own id rather than reached through the queue id.

WHY THE DRIFT COST SOMETHING. `emit_to_user` fans out to every session under a
user, so the audio socket sees — and correctly declines — queue events. That
decline path produced 749 "not subscribed" lines on row 88347f65 and three
seats spent six hours reading them as a subscription bug, because the docs said
the two sockets could not have different ids in the first place.

WHAT THIS GUARD HOLDS. Both sides of the drift, so it fires whichever one moves:
  1. the client really does keep two ids (if that is unified, come re-read the docs)
  2. no doc restates the falsified universal claim

WHAT ELSE WAS SWEPT, AND THE NEGATIVE RESULT (an absence is only worth what
its positive control is worth, so both are named):

  1. Every other doc/source restatement of the claim. `git grep` over *.md /
     *.py / *.ts / *.js for "sharing the same `session_id`", "same session_id",
     "same session ID", "queue-WS session id". POSITIVE CONTROL: the search
     returns the three sites this guard holds, so it can see a hit. The other
     ~20 hits are (a) history/ and bug-fix-queue.md records, (b) a different
     topic entirely — RECONNECTING on the same id — and (c) the 2025 R&D doc
     `src/rnd/v0.0.6/2025.07.24-fastapi-websocket-async-bridge.md:27`, which is
     where the belief originated. That one is left alone: a research record is
     a record of what was thought then, not a live instruction.

  2. Whether any SERVER code assumes the two sockets share an id — the thing
     that would make the split a real defect rather than a doc error. It does
     not. `stream_tts_hybrid` and `stream_tts_elevenlabs` (`speech.py:841`,
     `:943`) are handed a `session_id` straight from the TTS request body
     (`speech.py:568`, `:722`) and address `active_connections[session_id]`
     directly; nothing derives an audio session from a queue session.
     POSITIVE CONTROL: an earlier grep for `stream_tts_msg` returned zero, and
     that was the WRONG NAME, not an empty codebase — the real names above were
     found by listing the module's defs before trusting the silence.

  The one consequence of the split that IS real is benign and already handled:
  `get_tts_audio` registers the audio session under the user
  (`speech.py:550`), so `emit_to_user` fans out to it and it declines queue
  events. That decline is correct, and it is now logged with its delivery
  count beside it.

The reuse claim is TRUE when scoped to the mobile app, and that scoping is load
bearing: an absent `client_type` on a shared-id audio connect must not downgrade
an established "mobile" marker (F-S6-1, Rachel R1). Keep the claim, keep the
scope.
"""
from pathlib import Path

import pytest

import cosa.utils.util as cu


ROOT = Path( cu.get_project_root() )

NOTIFICATIONS_JS = ROOT / "src" / "lupin_app" / "static" / "js" / "notifications.js"
ARCHITECTURE_MD  = ROOT / "src" / "docs" / "websocket-architecture.md"
TROUBLESHOOT_MD  = ROOT / "src" / "docs" / "websocket-troubleshooting.md"
WS_MANAGER_PY    = ROOT / "src" / "cosa" / "rest" / "websocket_manager.py"


def _read( path ):
    """
    Read a tracked artifact, failing loudly when it is missing.

    Requires:
        - path is a Path

    Ensures:
        - returns the file's text

    Raises:
        - pytest.fail if the file does not exist (a moved file must not read as
          a silently-passing absence check — see the empty-result rule)
    """
    if not path.exists(): pytest.fail( f"expected artifact is missing: {path}" )
    return path.read_text( encoding="utf-8" )


def test_the_web_app_really_does_keep_two_session_ids():
    """
    Leg 1 — the measurement the doc claims is impossible.

    Ensures:
        - notifications.js declares two DISTINCT localStorage keys
        - it asks for both a 'queue' and an 'audio' id
    """
    src = _read( NOTIFICATIONS_JS )

    assert "'notifications_queue_session_id'" in src
    assert "'notifications_audio_session_id'" in src
    assert "getOrCreateSessionId( 'queue' )" in src
    assert "getOrCreateSessionId( 'audio' )" in src, (
        "notifications.js no longer requests a separate audio session id. If the "
        "client was deliberately unified, re-read src/docs/websocket-architecture.md "
        "and this guard together — do not just delete the assertion."
    )


def test_the_audio_socket_is_addressed_by_its_own_id():
    """
    Leg 1b — the split is used, not merely declared.

    Ensures:
        - the audio WebSocket URL is built from audioSessionId
        - TTS requests carry audioSessionId, so the audio channel is addressed
          by its own id rather than reached through the queue id
    """
    src = _read( NOTIFICATIONS_JS )

    assert "/ws/audio/${this.audioSessionId}" in src
    assert "session_id: this.audioSessionId" in src or "session_id : this.audioSessionId" in src


@pytest.mark.parametrize(
    "path, banned, why",
    [
        (
            ARCHITECTURE_MD,
            "two** WebSocket connections sharing the same `session_id`",
            "notifications.js opens two connections under two DIFFERENT ids",
        ),
        (
            TROUBLESHOOT_MD,
            "Audio and queue WebSockets must use the same `session_id`",
            "this sends a debugger to unify ids the live web client keeps apart",
        ),
    ],
)
def test_no_doc_restates_the_falsified_universal_claim( path, banned, why ):
    """
    Leg 2 — the docs must not carry the unscoped claim.

    Requires:
        - path is a tracked markdown doc

    Ensures:
        - the falsified sentence is absent
    """
    assert banned not in _read( path ), f"{path.name} still claims: {banned!r} — {why}"


def test_the_reuse_claim_is_kept_but_scoped_to_the_mobile_app():
    """
    Leg 3 — the F-S6-1 reasoning is TRUE for the mobile app and must survive.

    Ensures:
        - websocket_manager.py still explains the no-downgrade guard
        - every place it states the reuse names the mobile app, so no reader
          generalises it back to every client
    """
    src = _read( WS_MANAGER_PY )

    assert "reuses the queue-WS session id" in src, (
        "the F-S6-1 no-downgrade rationale was removed; it is load bearing for "
        "the mobile app, whose audio-WS connect really does share the queue id"
    )
    for line_no, line in enumerate( src.splitlines(), start=1 ):
        if "reuses the queue-WS session id" not in line: continue
        window = "\n".join( src.splitlines()[ max( 0, line_no - 4 ) : line_no + 1 ] )
        assert "mobile app" in window.lower(), (
            f"websocket_manager.py:{line_no} states the session-id reuse without "
            "scoping it to the mobile app — the web app notifications.js does not reuse"
        )
