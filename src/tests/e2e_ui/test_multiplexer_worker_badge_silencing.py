#!/usr/bin/env python3
"""
E2E — Multiplexer worker-badge silencing (Rick 2026-06-24, focus-bar parity v0.1.9).

Keystone predicate: a MANAGED worker = a sender whose `manager_persona` is
non-null (delivered on the `voice_persona_assigned` payload, same field
SessionStripStore reads). A managed worker's section-notifications card shows
NO numeric `.sender-new-count` and carries `data-worker="true"` so the shared
sheet (`notifications-surface.css`) renders a faint activity dot via
`.sender-stats-group::after`. A manager / root session (no manager) keeps its
numeric count and carries NO `data-worker`.

Drives the REAL mux wiring end-to-end via the test-hook EventBus:
  1. a regular notification creates the SenderRecord + card (unread → count),
  2. a `voice_persona_assigned` carrying `payload.manager_persona` flips
     `is_worker` → the renderer re-renders the card with the count suppressed.

Gap list / build plan:
  - src/rnd/v0.1.9/2026.06.24-notifications-multiplexer-focus-bar-parity-gap-list.md (§6 Decision A/B)
  - src/rnd/v0.1.9/2026.06.24-focus-bar-parity-build-plan.md (Lane A)

Venue: :8000 (monopolize, scheduled via /api/test-suite/submit) — the
`test_multiplexer_*` E2E batch. Per CLAUDE.local.md "THE USER IS NEVER A
TESTER": every assertion is AI-run; the Tester owns scheduling this on :8000.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_worker_badge_silencing.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_worker_badge_silencing.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

WORKER_SENDER = "claude.code@lupin.deepily.ai#wbsworker1"
ROOT_SENDER   = "claude.code@lupin.deepily.ai#wbsroot1"

TIBERIUS = { "name": "Tiberius", "icon": "👑", "color": "#3F51B5" }


# A regular notification — creates the SenderRecord (unread → count) + card.
_EMIT_NOTIFICATION_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            // id_hash is REQUIRED — NotificationStore.normalize() drops any
            // notification missing it (returns null), so without this the live
            // emit never lands in the store, renderSenderSection() paints the
            // empty-state, and no .sender-card ever appears (Tester fix,
            // 2026-06-24: every real server notification carries an id_hash).
            id_hash         : 'e2e-wbs-' + args.sender_id,
            type            : 'task',
            sender_id       : args.sender_id,
            timestamp       : args.ts,
            message         : 'work in progress',
            action_required : false,
        } },
        source  : 'e2e-worker-badge',
        ts      : Date.now(),
    });
    return true;
}
"""

# A voice_persona_assigned — optionally carrying payload.manager_persona, which
# is exactly what flips is_worker in SenderStore.
_EMIT_ASSIGNED_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    const notification = {
        type          : 'voice_persona_assigned',
        sender_id     : args.sender_id,
        timestamp     : args.ts,
        voice_persona : {
            name        : args.name,
            voice_id    : 'vid_' + args.sender_id,
            icon        : '🎤',
            color       : '#28a745',
            borrowed    : false,
            assigned_at : args.ts,
        },
    };
    if ( args.manager !== null ) {
        notification.payload = { manager_persona: args.manager };
    }
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: notification },
        source  : 'e2e-worker-badge',
        ts      : Date.now(),
    });
    return true;
}
"""


def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def _login_tokens() -> tuple[ str, str ]:
    email, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _open( page ):
    """Seed auth, navigate to the multiplexer, wait for the test hook."""
    access, refresh = _login_tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )


def _emit_notification( page, sender_id: str, ts: str = "2026-06-24T18:00:00.000Z" ):
    page.evaluate( _EMIT_NOTIFICATION_JS, { "sender_id": sender_id, "ts": ts } )


def _assign( page, sender_id: str, manager: dict | None, ts: str = "2026-06-24T18:00:01.000Z" ):
    page.evaluate( _EMIT_ASSIGNED_JS, {
        "sender_id" : sender_id,
        "name"      : "Worker",
        "manager"   : manager,
        "ts"        : ts,
    } )


def _card_selector( sender_id: str ) -> str:
    # Mux sender cards mount to #sender-cards-container (NotificationsListRenderer
    # senderCardsMount, multiplexer.html). #section-notifications is the LEGACY
    # client's container id (absent from the mux DOM) — using it here timed out
    # all three mux assertions. Aligned to the same selector the passing
    # cold-load hydration e2e uses (Tester fix, 2026-06-24).
    return f'#sender-cards-container .sender-card[data-sender-id="{sender_id}"]'


def _card_surfaces( page, sender_id: str ) -> dict | None:
    return page.evaluate(
        """( sel ) => {
            const card = document.querySelector( sel );
            if ( !card ) return null;
            const newCount = card.querySelector( '.sender-new-count' );
            return {
                data_worker     : card.getAttribute( 'data-worker' ),
                has_new_count   : newCount !== null,
                new_count_text  : newCount ? newCount.textContent : null,
                has_stats_group : card.querySelector( '.sender-stats-group' ) !== null,
            };
        }""",
        _card_selector( sender_id ),
    )


def test_managed_worker_card_suppresses_count_and_flags_data_worker( page ):
    """
    Ensures:
        - A worker (assignment carries payload.manager_persona) renders its
          section-notifications card with NO numeric .sender-new-count and
          data-worker="true" (the shared-sheet faint-pulse anchor).
        - The .sender-stats-group container still renders (number-only
          suppression — the pulse lives on its ::after).
    """
    _open( page )
    _emit_notification( page, WORKER_SENDER )
    page.wait_for_selector( _card_selector( WORKER_SENDER ), timeout=3_000 )
    _assign( page, WORKER_SENDER, manager=TIBERIUS )
    # Wait for the re-render to apply the worker flag.
    page.wait_for_function(
        """( sel ) => {
            const card = document.querySelector( sel );
            return card && card.getAttribute( 'data-worker' ) === 'true';
        }""",
        arg=_card_selector( WORKER_SENDER ),
        timeout=3_000,
    )

    s = _card_surfaces( page, WORKER_SENDER )
    assert s is not None, "worker card must exist"
    assert s[ "data_worker" ]     == "true", "managed-worker card must carry data-worker"
    assert s[ "has_new_count" ]   is False,  "numeric .sender-new-count must be suppressed for a worker"
    assert s[ "has_stats_group" ] is True,   "stats-group (pulse anchor) still renders"


def test_root_session_card_keeps_count_and_no_data_worker( page ):
    """
    Ensures:
        - A root/manager session (assignment WITHOUT manager_persona) keeps its
          numeric .sender-new-count and carries NO data-worker.
    """
    _open( page )
    _emit_notification( page, ROOT_SENDER )
    page.wait_for_selector( _card_selector( ROOT_SENDER ), timeout=3_000 )
    _assign( page, ROOT_SENDER, manager=None )
    page.wait_for_timeout( 300 )   # allow any (incorrect) worker flag to render

    s = _card_surfaces( page, ROOT_SENDER )
    assert s is not None, "root card must exist"
    assert s[ "data_worker" ]   is None,  "root card must NOT carry data-worker"
    assert s[ "has_new_count" ] is True,  "root card keeps its numeric count"
    assert s[ "new_count_text" ] == "1",  "count reflects the single unread notification"


def test_reparent_worker_to_root_restores_count( page ):
    """
    Ensures:
        - is_worker is current-state (authoritative on every assignment), not
          sticky: a worker re-assigned WITHOUT a manager clears data-worker and
          re-shows the count.
    """
    _open( page )
    _emit_notification( page, WORKER_SENDER )
    page.wait_for_selector( _card_selector( WORKER_SENDER ), timeout=3_000 )
    _assign( page, WORKER_SENDER, manager=TIBERIUS )
    page.wait_for_function(
        """( sel ) => {
            const card = document.querySelector( sel );
            return card && card.getAttribute( 'data-worker' ) === 'true';
        }""",
        arg=_card_selector( WORKER_SENDER ),
        timeout=3_000,
    )

    # Re-parent to a root role (no manager) — the flag must clear.
    _assign( page, WORKER_SENDER, manager=None, ts="2026-06-24T18:00:05.000Z" )
    page.wait_for_function(
        """( sel ) => {
            const card = document.querySelector( sel );
            return card && card.getAttribute( 'data-worker' ) === null;
        }""",
        arg=_card_selector( WORKER_SENDER ),
        timeout=3_000,
    )

    s = _card_surfaces( page, WORKER_SENDER )
    assert s[ "data_worker" ]   is None, "re-parented session no longer flagged worker"
    assert s[ "has_new_count" ] is True, "count restored after re-parent to root"
