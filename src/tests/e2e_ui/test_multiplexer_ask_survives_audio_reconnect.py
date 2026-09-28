"""
E2E UI — a REAL ask reaches the multiplexer before AND after its audio socket
reconnects (row d2b1b59a, FINDING 5).

WHAT BROKE, measured 2026-09-10 on :7999: the multiplexer opened /ws/queue and
/ws/audio under ONE session id. The server keeps one socket + one subscription
list per id, so every audio (re)registration overwrote the queue socket's
subscriptions and the server declined every notification to the tab —
"declined=2 (slow zebra, calm dolphin)". Rick's P0 petition asks and every
ordinary ask never reached it. Fix 7221b484: the audio socket gets its own id.
Write-up: src/rnd/2026.09.10-multiplexer-misses-petition-ask.md

WHY THE RECONNECT: the defect was a RACE decided by which socket registered
last, so a single cold load could pass by luck of ordering. An audio reconnect
re-runs the audio connect + audio auth AFTER the queue socket is settled — the
exact order that deafened the tab — so the "after" ask is the discriminating arm.

REAL WIRE PATH, nothing injected: the ask is a response-required POST
/api/notify to the logged-in user; the server pushes notification_queue_update
over the queue socket; ActionRequiredStore takes it; the renderer paints
[data-testid="multiplexer-action-required"][data-id-hash=<id>]. The audio
socket is closed from the page with a non-permanent code (3001), so the
transport's normal socket_close → backoff → reconnect path reopens it.

ONE CARD AT A TIME: 5e1851a0 (row 360de81b) landed 2h52m after this file and
made the pane paint the store's FIRST item in the active slot and every other
item as a minimized row carrying data-testid="multiplexer-action-required-queued"
instead. Closing the asker's SSE stream is walking away, not answering, so an
unanswered before-ask holds the active slot for its full 120s timeout and the
after-ask can only paint as a queued row — which is what made the after-reconnect
arm red from 2026-09-10 on, at the paint step, never at the store step. Each ask
is now drained through the real answer door before the next is raised, so both
are measured by the same full-widget selector.

EXPECTED AGAINST THE PRE-FIX BUNDLE (inferred from the measured mechanism, not
run on :8000): the after-reconnect ask never reaches the store, and the
session-id assertion fails because both sockets carry one id.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). It
registers a user and persists notifications, so it is not :7999-eligible.

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e",
        "pytest_args"        : "-k test_multiplexer_ask_survives_audio_reconnect",
        "auto_fix_on_failure": false
    }
"""

from __future__ import annotations

import json
import uuid
from urllib.parse import unquote, urlparse

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .conftest import BASE_URL


E2E_SENDER = "claude.code@lupin.deepily.ai#e2eaudio"

# Wraps window.WebSocket BEFORE boot so the test can see every socket the
# multiplexer opens, when each authenticated, and close one on demand.
# ws-channel resolves globalThis.WebSocket at construction, so the wrapper is
# what it instantiates. The prototype and ready-state constants are preserved.
TRACK_SOCKETS = """
(() => {
  const Native  = window.WebSocket;
  const tracked = [];
  function TrackedWebSocket( url, protocols ) {
    const ws  = protocols === undefined ? new Native( url ) : new Native( url, protocols );
    const rec = { url: String( url ), ws, authed: false };
    ws.addEventListener( "message", ( e ) => {
      if ( typeof e.data === "string" && e.data.includes( '"auth_success"' ) ) rec.authed = true;
    } );
    tracked.push( rec );
    return ws;
  }
  TrackedWebSocket.prototype = Native.prototype;
  Object.assign( TrackedWebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 } );
  window.WebSocket     = TrackedWebSocket;
  window.__e2eSockets  = tracked;
})();
"""


def _open_multiplexer( page ):
    page.context.add_init_script( TRACK_SOCKETS )
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.actionRequired",
        timeout=15000,
    )


def _wait_authed_sockets( page, kind, count ):
    """Wait until at least `count` sockets on /ws/<kind>/ are OPEN and have received auth_success."""
    page.wait_for_function(
        """( [ kind, count ] ) => ( window.__e2eSockets || [] ).filter( r =>
              r.url.includes( `/ws/${ kind }/` ) && r.authed && r.ws.readyState === 1
           ).length >= count""",
        arg=[ kind, count ],
        timeout=20000,
    )


def _live_session_ids( page ):
    """The session id of the newest OPEN socket per channel, decoded from its URL."""
    urls = page.evaluate(
        """() => {
            const newest = ( kind ) => ( window.__e2eSockets || [] )
                .filter( r => r.url.includes( `/ws/${ kind }/` ) && r.ws.readyState === 1 )
                .map( r => r.url ).pop() || null;
            return { queue: newest( "queue" ), audio: newest( "audio" ) };
        }"""
    )
    return { kind: ( unquote( urlparse( url ).path.rsplit( "/", 1 )[ -1 ] ) if url else None )
             for kind, url in urls.items() }


def _close_audio_socket( page ):
    closed = page.evaluate(
        """() => {
            const open = ( window.__e2eSockets || [] ).filter( r => r.url.includes( "/ws/audio/" ) && r.ws.readyState === 1 );
            open.forEach( r => r.ws.close( 3001, "e2e: force audio reconnect" ) );
            return open.length;
        }"""
    )
    assert closed == 1, f"expected exactly one open audio socket to close, found { closed }"


def _raise_ask( page, email, label ):
    """
    POST a real response-required yes/no ask to the logged-in user.

    Returns (streaming response, notification_id). The response stays open
    until the caller closes it; closing it walks away without answering.
    """
    token = page.evaluate( "() => localStorage.getItem( 'lupin_access_token' )" )
    resp  = requests.post(
        f"{BASE_URL}/api/notify",
        params  = {
            "message"            : f"[E2E-AUDIO-RECONNECT] { label } { uuid.uuid4().hex[ :8 ] }",
            "type"               : "custom",
            "priority"           : "high",
            "target_user"        : email,
            "response_requested" : "true",
            "response_type"      : "yes_no",
            "timeout_seconds"    : 120,
            "sender_id"          : E2E_SENDER,
            "suppress_ding"      : "true",
        },
        headers = { "Authorization": f"Bearer { token }" },
        stream  = True,
        timeout = 20,
    )
    assert resp.status_code == 200, f"notify POST failed: { resp.status_code } { resp.text[ :300 ] }"
    for line in resp.iter_lines( decode_unicode=True ):
        if line and line.startswith( "data:" ):
            frame = json.loads( line[ len( "data:" ): ].strip() )
            assert frame.get( "status" ) == "ack", f"first SSE frame was not the ack: { frame }"
            return resp, frame[ "notification_id" ]
    raise AssertionError( "SSE stream ended before the ack frame" )


def _wait_ask_rendered( page, notification_id ):
    """
    Wait for an ask to reach the store AND to be the card holding the slot.

    🔴 THE TWO WAITS ANSWER DIFFERENT QUESTIONS, AND THE SECOND ONE USED TO FAIL MUTE.
    Wait 1 is delivery: the frame reached this browser session's store. Wait 2 is
    rendering: a widget on the page carries the ask's `data-id-hash`. Only `items[0]`
    — the ACTIVE card in the slot — ever carries that attribute; every other item is a
    queue row (`ActionRequiredRenderer.render`).

    So a bare "selector timed out" from wait 2 is the least informative thing this
    helper can say. It was measured saying exactly that, three times, in ts-b5a9744a
    (2026-09-27) and produced no diagnosis on its own: the notification had arrived, the
    store had it, and the message named neither that fact nor the branch that withheld
    the widget.

    ⚠️ THE BRANCH TO SUSPECT FIRST is `ActionRequiredRenderer.ts:320`:

        if ( isAwaitingActivation( items[ 0 ] ) ) { this.slot.replaceChildren(); ... }

    with `isAwaitingActivation` = `state === "pending" && expires_at === null`
    (`stores/ActionRequiredStore.ts:100`, Parity A-2 #2d, 76c67fcd0). A card matching
    that predicate EMPTIES the slot and renders as queue row #1, so nothing carries its
    hash — which looks identical to "the ask never arrived" unless the store is dumped.

    ⇒ On a wait-2 timeout this reads the store's own copy back and puts `state` and
    `expires_at` in the failure message, because those two fields distinguish the two
    live explanations: the server never setting `expires_at` on a response-required
    notify (a product bug), versus activation never happening in a container with no
    audio device (a test-environment interaction). They have different owners, so the
    message names both rather than asserting one.

    Requires:
        - page is on /app/multiplexer with `__multiplexerTestHook` wired
        - notification_id is the `notification_id` from the notify ack frame

    Ensures:
        - returns once a widget carrying that id_hash is attached

    Raises:
        - AssertionError naming the store's state/expires_at and the suspect branch,
          instead of a bare selector timeout
    """
    page.wait_for_function(
        "( nid ) => window.__multiplexerTestHook.stores.actionRequired.getById( nid ) !== undefined",
        arg=notification_id,
        timeout=15000,
    )
    try:
        page.wait_for_selector(
            f'[data-testid="multiplexer-action-required"][data-id-hash="{ notification_id }"]',
            state="attached",
            timeout=5000,
        )
    except PlaywrightTimeoutError as timeout:
        raise AssertionError( _slot_withheld_report( page, notification_id ) ) from timeout


def _slot_withheld_report( page, notification_id ):
    """
    Describe WHY no widget carries `notification_id`, from the page's own store.

    Kept separate from the helper above so it can be unit-reasoned about and so the
    happy path carries no cost. It is deliberately tolerant: a diagnostic that raises
    while explaining a failure replaces the finding with its own stack trace.

    Requires:
        - page is a live Playwright page

    Ensures:
        - returns a multi-line str naming the store's copy of the item, the id_hash the
          slot currently holds, the queue depth, and the branch to check first
        - never raises; a failure to read the store is reported as part of the message
    """
    try:
        probe = page.evaluate(
            """( nid ) => {
                const store = window.__multiplexerTestHook.stores.actionRequired;
                const item  = store.getById( nid );
                const slot  = document.querySelector(
                    '[data-testid="multiplexer-action-required"][data-id-hash]'
                );
                return {
                    found       : item !== undefined,
                    state       : item ? item.state       : null,
                    expires_at  : item ? item.expires_at  : null,
                    slot_holds  : slot ? slot.getAttribute( "data-id-hash" ) : null,
                    // The queue row's real testid and class, read off
                    // render/templates/actionRequiredQueueRow.ts:56-58 — NOT guessed. A
                    // diagnostic built on an invented selector counts 0 forever and reads
                    // as "nothing queued", which is the opposite of the truth here.
                    queue_depth : document.querySelectorAll(
                        '[data-testid="multiplexer-action-required-queued"]'
                    ).length,
                    // 🔴 THE DECISIVE FIELD. A queue row carries `data-id-hash` TOO, under a
                    // different testid, so this says outright whether the ask rendered as a
                    // QUEUED row rather than not rendering at all.
                    queued_here : document.querySelector(
                        '[data-testid="multiplexer-action-required-queued"][data-id-hash="' + nid + '"]'
                    ) !== null,
                };
            }""",
            notification_id,
        )
    except Exception as read_failure:                      # noqa: BLE001 — see the docstring
        return (
            f"no widget carries data-id-hash={ notification_id }, and the store could not be "
            f"read to say why: { read_failure!r }"
        )

    awaiting = probe[ "state" ] == "pending" and probe[ "expires_at" ] is None
    if awaiting and probe[ "queued_here" ]:
        verdict = (
            "AWAITING ACTIVATION, CONFIRMED BOTH WAYS — state is 'pending' with expires_at "
            "null AND the ask is on screen as a QUEUED row. ActionRequiredRenderer.ts:320 "
            "emptied the slot. Two candidate causes with DIFFERENT OWNERS: (a) the server "
            "never set expires_at on a response-required notify, or (b) it sets it at "
            "activation and activation never happened (no audio device in this container). "
            "Do not pick one from this message alone."
        )
    elif awaiting:
        verdict = (
            "the predicate at ActionRequiredRenderer.ts:320 matches (pending + null "
            "expires_at) but the ask is NOT on screen as a queued row either, so it is not "
            "merely losing the slot — it is not being rendered at all."
        )
    elif probe[ "queued_here" ]:
        verdict = (
            "the ask IS on screen as a queued row and is NOT awaiting activation, so "
            "something ahead of it holds the slot. Only items[0] carries the slot's "
            "data-id-hash — check what slot_holds names above."
        )
    else:
        verdict = (
            "NOT awaiting activation and NOT queued on screen. ActionRequiredRenderer.ts:320 "
            "is not the cause; the item is in the store and reaching neither render path."
        )
    return (
        f"no widget carries data-id-hash={ notification_id } after 5s, although the store "
        f"HAS the item (so it was delivered).\n"
        f"  store.found  : { probe[ 'found' ] }\n"
        f"  store.state  : { probe[ 'state' ]!r }\n"
        f"  expires_at   : { probe[ 'expires_at' ]!r }\n"
        f"  slot holds   : { probe[ 'slot_holds' ]!r }\n"
        f"  queue depth  : { probe[ 'queue_depth' ] }\n"
        f"  queued here  : { probe[ 'queued_here' ] }\n"
        f"  => { verdict }"
    )


def _answer_and_wait_gone( page, notification_id ):
    """
    Answer an ask through the REAL door and wait for it to leave the store.

    respondAndAwait is the store's only answer path (bcf15f08), so this is a real
    POST /api/notify/response with nothing stubbed; the asker's SSE stream is still
    open at the call, which is the shape ed863226 proved. The store shows the
    answered card for RESPONDED_GRACE_MS (600ms) and then removes it, so the wait
    is on the removal, not on the POST.
    """
    page.evaluate(
        "( nid ) => window.__multiplexerTestHook.stores.actionRequired.respondAndAwait( nid, 'yes' )",
        notification_id,
    )
    page.wait_for_function(
        "( nid ) => window.__multiplexerTestHook.stores.actionRequired.getById( nid ) === undefined",
        arg=notification_id,
        timeout=10000,
    )


class TestMultiplexerAskSurvivesAudioReconnect:

    def test_sockets_use_different_ids_and_an_ask_arrives( self, logged_in_page, test_user_credentials ):
        page = logged_in_page
        _open_multiplexer( page )
        _wait_authed_sockets( page, "queue", 1 )
        _wait_authed_sockets( page, "audio", 1 )

        ids = _live_session_ids( page )
        assert ids[ "queue" ] and ids[ "audio" ], f"both sockets must be open: { ids }"
        assert ids[ "queue" ] != ids[ "audio" ], f"queue and audio sockets share a session id: { ids }"

        resp, nid = _raise_ask( page, test_user_credentials[ "email" ], "before reconnect" )
        try:
            _wait_ask_rendered( page, nid )
        finally:
            resp.close()

    def test_an_ask_still_arrives_after_the_audio_socket_reconnects( self, logged_in_page, test_user_credentials ):
        page  = logged_in_page
        email = test_user_credentials[ "email" ]
        _open_multiplexer( page )
        _wait_authed_sockets( page, "queue", 1 )
        _wait_authed_sockets( page, "audio", 1 )

        before, before_id = _raise_ask( page, email, "before reconnect" )
        try:
            _wait_ask_rendered( page, before_id )
            # Drain it BEFORE raising the after-ask, or the after-ask paints as a
            # queued row and never carries the selector above (see ONE CARD AT A
            # TIME in the module docstring). Answered while the stream is open.
            _answer_and_wait_gone( page, before_id )
        finally:
            before.close()

        _close_audio_socket( page )
        # A NEW audio socket must open and authenticate: two authed audio
        # records in total, the newest of them OPEN.
        page.wait_for_function(
            """() => ( window.__e2eSockets || [] ).filter( r => r.url.includes( "/ws/audio/" ) && r.authed ).length >= 2
                  && ( window.__e2eSockets || [] ).some( r => r.url.includes( "/ws/audio/" ) && r.authed && r.ws.readyState === 1 )""",
            timeout=20000,
        )

        ids = _live_session_ids( page )
        # PRESENCE BEFORE DIFFERENCE (row f0e00f01, Tiffany's reviewer).
        # _live_session_ids yields None for a channel with no OPEN socket, and
        # None != "wise lion" is true — so the inequality ALONE was satisfied by the
        # very failure it exists to catch, a channel with no socket. Hence the
        # presence check first. Each remaining check can fail on its own:
        #   queue non-empty — nothing between the queue socket's auth at test start
        #     and this line re-checks it, and an audio reconnect disturbing the queue
        #     socket is the exact 7221b484 failure family. Nothing upstream watches it.
        #   queue != audio — the 7221b484 regression itself: both channels back on one id.
        # There is deliberately NO `assert ids[ "audio" ]`. The wait_for_function above
        # already requires an authed audio socket in readyState 1, and _live_session_ids
        # selects on readyState 1 alone — a strictly weaker condition — so a non-null
        # audio id is guaranteed by that wait, and an assert here could only fire in the
        # microseconds between two consecutive statements. An assertion that cannot fail
        # independently earns nothing and costs a reader's attention (Mr. Radio, row
        # f0e00f01). The never-reopens case is likewise the wait's to catch, not ours.
        #
        # 🔴 THE audio-None GAP IS UNCOVERABLE — DO NOT RE-ADD THE ASSERT. If the audio
        # socket closes between the wait and the read, `ids[ "audio" ]` is None, and
        # None != "wise lion" is true, so the inequality passes and this arm goes green
        # when it should not. Tiberius MEASURED (2026-09-15, before the f0e00f01 merge)
        # that the wait CANNOT be tightened to close it. My own d6a40fb3 commit message
        # says the answer is to "tighten the WAIT" — that is WRONG, and this note is
        # where the correction lives, because a commit message cannot be edited and
        # nobody reads one before touching a test anyway. A re-added assert would not
        # close the gap either: it would sit one statement further from the wait and
        # carry the same race. If the arm is ever seen going green wrongly, it needs a
        # different instrument, not another line here.
        assert ids[ "queue" ], f"the queue socket must still be open after the audio reconnect: { ids }"
        assert ids[ "queue" ] != ids[ "audio" ], f"after reconnect the sockets share a session id: { ids }"

        after, after_id = _raise_ask( page, email, "after audio reconnect" )
        try:
            _wait_ask_rendered( page, after_id )
        finally:
            after.close()
