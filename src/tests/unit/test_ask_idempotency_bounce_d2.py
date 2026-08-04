"""
D2 (bug f433fbae) — the cross-bounce residual of ask idempotency.

Clayton's D2 dedups a re-POSTed blocking ask by an in-memory index
(`_ask_idempotency_index` in `cosa.rest.routers.notifications`): a second POST with
the same idempotency_key re-attaches to the original card instead of minting a second.
That closes the retry-within-one-process case.

It does NOT survive a server restart. The index is a module-level OrderedDict, so a
:7999 bounce — the exact scenario in Rick's complaint (`src/rnd/v0.1.9/2026.08.01-late-answer-handback.md`
§1: "three notifications arrive … then the server gets rebooted") — wipes it. The same
idempotency_key after the bounce finds nothing and mints a NEW card: the duplicate
prompt, reborn across a restart.

Clayton scoped the cross-bounce case OUT of D2 explicitly; a durable (DB-backed)
idempotency index is a schema change, not tonight's job. So this is committed as a
STRICT xfail, not left out of the suite and not committed red:
  - it keeps running (documents the gap, does not break the coverage gate);
  - the day someone makes the index durable it XPASSES, and strict xfail turns that
    unexpected pass into a failure — the loud signal to delete this marker and fold the
    guarantee into the normal suite.

This is a test file only — it touches no production code.
"""

import importlib
import uuid

import pytest

from cosa.rest.routers import notifications as _notifications_probe   # noqa: F401 — import-guard


_REASON = (
    "D2 cross-bounce residual (f433fbae): ask idempotency lives in the in-memory "
    "_ask_idempotency_index, which a :7999 bounce wipes — the same idempotency_key after "
    "a restart mints a NEW card. Clayton scoped the cross-bounce case out of D2; a durable "
    "index is a schema change. XPASS here = idempotency became durable → remove this xfail."
)


@pytest.mark.xfail( strict=True, reason=_REASON )
def test_d2_ask_idempotency_survives_a_bounce():
    """
    An ask idempotency mapping must survive a server restart.

    Records key→id, then simulates a :7999 bounce by reloading the module (a restart
    re-imports it with empty globals — the faithful wipe). The same key must still
    resolve to the original ask id.

    RED today: the reloaded module's index is empty → lookup returns None → a re-POST
    would mint a second card. That is the residual this xfail documents.
    """
    import cosa.rest.routers.notifications as N

    key = "d2-bounce-" + uuid.uuid4().hex
    original_nid = "notif-original-1"

    # HERMETICITY (Tiffany, 2026-08-03): snapshot the module's original bindings BEFORE
    # the reload. `importlib.reload` re-executes the module, rebinding every function in
    # it — including `get_notification_queue` — to a NEW object, and reload has no undo.
    # Left un-restored, that reloaded module outlived this test: any LATER test that keyed
    # a dependency override on a RUNTIME-imported `notifications.get_notification_queue`
    # then keyed the new object, while dm.py's route Depends still held the one captured at
    # dm import — the override missed and the send fell through to the real (None-in-tests)
    # queue, 500-ing a DM-send test ~150 files downstream. Restoring in `finally` contains
    # the reload's blast radius to this test.
    _saved_bindings = dict( N.__dict__ )

    # In-process, Clayton's index already dedups — sanity that we are testing the RIGHT
    # thing (not a vacuous red): the mapping resolves before the bounce.
    N._record_ask_idempotency( key, original_nid )
    assert N._lookup_ask_idempotency( key ) == original_nid

    try:
        # Simulate a :7999 bounce: a restart re-imports the module with fresh, empty globals.
        # importlib.reload reproduces exactly that — every in-memory index is wiped.
        N = importlib.reload( N )

        # DESIRED (durable idempotency): the same key still resolves to the original ask
        # after the restart, so the re-POST re-attaches instead of minting a duplicate.
        # ACTUAL today: the in-memory index did not survive → None → duplicate card.
        assert N._lookup_ask_idempotency( key ) == original_nid, (
            "ask idempotency did not survive a simulated bounce — the same key mints a new "
            "card after a restart (the D2 cross-bounce residual)"
        )
    finally:
        # Put the pre-reload bindings back so module identity is preserved session-wide.
        N.__dict__.clear()
        N.__dict__.update( _saved_bindings )
