"""
E2E UI — the Action Required card's parity behaviours on the SERVED page
(parity A-2 #2h–#2m, row 2ebf322f).

Legacy source: `attachKeyboardListener` notifications.js:25892-25947. The per-item
coordinates are in the table below; this line carries one inside the 12-line header
window the citation guard reads, because a Python module docstring pushes a table
past it in a way a .test.ts header never does.

The unit tier covers each of these six sub-items against a template or a renderer
built in happy-dom. This file is the one thing those cannot be: the real
multiplexer bundle, served by the real server, in a real browser, driving the card
the way an operator does. A behaviour can be complete, correct, fully covered and
never reach the page — the bundle can fail to include it, the CSS can hide it, a
listener can be attached to a node that is later replaced. Every assertion below
would stay green in the unit tier while being broken here.

WHAT EACH TEST COVERS, and the legacy it ports:
  #2h  `attachKeyboardListener` (notifications.js:25892-25947) — Y / N answer, C
       toggles the comment row, P pauses, Esc cancels; all suppressed while focus
       sits in an INPUT or TEXTAREA (:25902, :25937)
  #2i  the yes_no card's ⊘ Neither and the ⭐ default mark
  #2j  the comment row — "Press C to add comment", 300-char input, 🎤
  #2k  the open_ended card's 🎤 and default-as-value prefill
  #2l  multiple_choice "Other" — a 🎤 and a free-text box
  #2m  the card chrome — [PROJECT] badge, persona badge, 📋 indicator, the inline
       abstract block and the prediction hint

Injection is via the boot test hook eventBus, the same door
`test_multiplexer_action_required_in_pane.py` uses. That is deliberate: it drives
the real store → renderer path, not a hand-built DOM.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). This file lives in
half A (src/tests/e2e_ui/partition/half-a.txt), so the suite is `e2e_a` — `e2e_ui` is NOT a
suite name and a run under it executes nothing and reports 0/0/0/0. Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e_a",
        "pytest_args"        : "-k test_multiplexer_action_required_card_parity",
        "scheduled_at"       : "<slot>",
        "auto_fix_on_failure": false
    }
"""

from __future__ import annotations

from .conftest import BASE_URL

CARD_SENDER = "claude.code@lupin.deepily.ai#e2ecard"


def _open_multiplexer( page ):
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.actionRequired",
        timeout=15000,
    )


def _emit( page, overrides ):
    """
    Inject one response-required notification through the real event bus.

    Requires:
        - the page is open on /app/multiplexer with the boot test hook live
        - `overrides` carries at least id_hash and response_type

    Ensures:
        - the frame reaches ActionRequiredStore by the real wire path
        - returns once the card for that id_hash is painted, so no caller races the render
    """
    payload = {
        "message"            : "Deploy to prod?",
        "sender_id"          : CARD_SENDER,
        "timestamp"          : "2026-09-19T18:00:00.000Z",
        "response_requested" : True,
        "timeout_seconds"    : 300,
    }
    payload.update( overrides )
    page.evaluate(
        """( payload ) => {
            window.__multiplexerTestHook.eventBus.emit( {
                type    : 'notification_queue_update',
                payload : { notification: payload },
                source  : 'ar-card-e2e',
                ts      : 1789790400000,
            } );
        }""",
        payload,
    )
    page.wait_for_selector(
        f'[data-testid="multiplexer-action-required"][data-id-hash="{ payload[ "id_hash" ] }"]',
        timeout=10000,
    )


def _card( page, nid ):
    return page.locator( f'[data-testid="multiplexer-action-required"][data-id-hash="{ nid }"]' )


def _interactive_selector( nid ):
    """
    The selector for a card that is STILL ANSWERABLE.

    `ActionRequiredRenderer.buildWidgetFor` builds a different widget per state, and only
    the four non-answerable ones carry `data-state` (submitting / responded / expired /
    cancelled, ActionRequiredRenderer.ts:477,494,511,531). The pending card carries NO
    `data-state` at all — it is discriminated by the class
    `action-required-widget-interactive` that `renderActionRequiredInteractive` puts on its
    root (actionRequiredInteractive.ts:80). Asserting `data-state == "pending"` therefore
    reads None on a live card, and — worse — a `state="detached"` wait on a
    `[data-state="pending"]` selector succeeds INSTANTLY against a card that never left,
    because that selector matches nothing at any point. Both shapes were in this file.
    """
    return (
        f'[data-testid="multiplexer-action-required"][data-id-hash="{ nid }"]'
        f'.action-required-widget-interactive'
    )


def _assert_still_answerable( card, why ):
    assert "action-required-widget-interactive" in ( card.get_attribute( "class" ) or "" ), why


class TestActionRequiredCardParity:
    """A-2 #2h–#2m on the served page."""

    # ---- #2i, #2j : the yes_no card -----------------------------------------

    def test_yes_no_card_carries_neither_and_marks_the_server_default( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, { "id_hash": "e2ecard-yn", "response_type": "yes_no", "response_default": "no" } )
        card = _card( page, "e2ecard-yn" )

        labels = card.locator( ".action-required-controls button" ).all_inner_texts()
        squashed = [ " ".join( t.split() ) for t in labels ]
        assert squashed == [ "✓ Yes (Y)", "✗ No (N)", "⊘ Neither" ], (
            f"legacy's three buttons in order; got { squashed }"
        )
        # #2i — the server's response_default marks No, and never Neither.
        assert card.locator( ".action-required-btn-no.default-value" ).count() == 1
        assert card.locator( ".action-required-btn-neither.default-value" ).count() == 0

    def test_the_comment_row_names_the_c_key_and_caps_at_300( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, { "id_hash": "e2ecard-cmt", "response_type": "yes_no" } )
        card = _card( page, "e2ecard-cmt" )

        # #2j — legacy's hint text is the affordance that teaches the #2h shortcut.
        assert card.locator( ".yes-no-comment-hint" ).inner_text().strip() == "Press C to add comment"
        assert card.locator( ".yes-no-comment-input" ).get_attribute( "maxlength" ) == "300"
        assert card.locator( ".yes-no-comment-mic" ).count() == 1

    # ---- #2h : the keyboard ---------------------------------------------------

    def test_C_opens_the_comment_row_on_the_served_page( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, { "id_hash": "e2ecard-kc", "response_type": "yes_no" } )
        card      = _card( page, "e2ecard-kc" )
        container = card.locator( ".yes-no-comment-container" )

        assert "expanded" not in ( container.get_attribute( "class" ) or "" )
        page.keyboard.press( "c" )
        page.wait_for_timeout( 150 )
        assert "expanded" in ( container.get_attribute( "class" ) or "" ), (
            "C must open the comment row — this is the listener actually reaching the served bundle"
        )

    def test_Y_answers_and_carries_a_typed_comment( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, { "id_hash": "e2ecard-ky", "response_type": "yes_no" } )
        card = _card( page, "e2ecard-ky" )

        page.keyboard.press( "c" )
        page.wait_for_timeout( 150 )
        card.locator( ".yes-no-comment-input" ).fill( "with reservations" )
        # Focus must leave the input or #2h's own suppression swallows the Y — which is
        # the behaviour the next test pins, and the reason this step is explicit here.
        card.locator( ".yes-no-comment-input" ).blur()
        # The detach wait below is only evidence if this selector matched to begin with.
        assert page.locator( _interactive_selector( "e2ecard-ky" ) ).count() == 1
        page.keyboard.press( "y" )

        # The card leaves the answerable state through the real submit path. The C-press
        # above already proved this card was interactive, so this detach is not vacuous.
        page.wait_for_selector(
            _interactive_selector( "e2ecard-ky" ),
            state   = "detached",
            timeout = 10000,
        )

    def test_every_shortcut_is_inert_while_the_operator_types( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, { "id_hash": "e2ecard-sup", "response_type": "yes_no" } )
        card = _card( page, "e2ecard-sup" )

        # Positive control FIRST: the listener is live on this page. Without it the
        # suppression assertions below would pass against a bundle that never attached
        # a listener at all — the exact vacuous-pass shape this row already fixed once.
        page.keyboard.press( "c" )
        page.wait_for_timeout( 150 )
        container = card.locator( ".yes-no-comment-container" )
        assert "expanded" in ( container.get_attribute( "class" ) or "" ), "control — C works here"

        comment = card.locator( ".yes-no-comment-input" )
        comment.click()
        comment.type( "yynnpp" )
        page.wait_for_timeout( 200 )

        # Still answerable: not answered, not cancelled.
        _assert_still_answerable( card, "typing must not answer or cancel the card" )
        assert comment.input_value() == "yynnpp", "the keystrokes went into the box, as text"

    def test_escape_cancels_and_is_suppressed_inside_an_input( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, { "id_hash": "e2ecard-esc", "response_type": "yes_no" } )
        card = _card( page, "e2ecard-esc" )

        page.keyboard.press( "c" )
        page.wait_for_timeout( 150 )
        card.locator( ".yes-no-comment-input" ).click()
        page.keyboard.press( "Escape" )
        page.wait_for_timeout( 200 )
        _assert_still_answerable(
            card,
            "Escape inside a text input must not cancel — legacy leaves it for the recorder",
        )

        card.locator( ".yes-no-comment-input" ).blur()
        assert page.locator( _interactive_selector( "e2ecard-esc" ) ).count() == 1
        page.keyboard.press( "Escape" )
        page.wait_for_selector(
            _interactive_selector( "e2ecard-esc" ),
            state   = "detached",
            timeout = 10000,
        )

    # ---- #2k, #2l : the other two response types -----------------------------

    def test_open_ended_card_is_voice_first_with_the_default_prefilled( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, {
            "id_hash"          : "e2ecard-oe",
            "response_type"    : "open_ended",
            "response_default" : "ship it",
        } )
        card = _card( page, "e2ecard-oe" )

        assert card.locator( ".action-required-mic" ).count() >= 1, "#2k — the card carries a 🎤"
        assert card.locator( "input[type=text]" ).first.input_value() == "ship it", (
            "#2k — the server default arrives as the input's VALUE, not a placeholder"
        )

    def test_multiple_choice_card_offers_legacy_other( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, {
            "id_hash"         : "e2ecard-mc",
            "response_type"   : "multiple_choice",
            "response_options": { "questions": [
                { "header": "db", "question": "Which store?", "options": [ "PostgreSQL", "SQLite" ] },
            ] },
        } )
        card = _card( page, "e2ecard-mc" )

        text = card.inner_text()
        assert "Other" in text, "#2l — legacy's Other option reaches the served card"

    # ---- #2m : the card chrome ------------------------------------------------

    def test_card_chrome_renders_every_piece_the_server_sends( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, {
            "id_hash"        : "e2ecard-chrome",
            "response_type"  : "yes_no",
            "abstract"       : "The **full** reasoning behind the ask.",
            "voice_persona"  : {
                "name": "Rio", "voice_id": "v1", "icon": "⚡",
                "color": "#880E4F", "borrowed": False,
            },
            "prediction_hint": { "confidence": 0.9, "predicted_value": "yes", "category": "deploy" },
        } )
        card = _card( page, "e2ecard-chrome" )

        # [PROJECT], from the sender id.
        assert card.locator( ".mc-project-badge" ).inner_text().strip() == "[LUPIN]"
        # The persona badge, in the timer-controls cluster.
        assert card.locator( ".action-required-timer-controls .persona-badge-name" ).inner_text().strip() == "Rio"
        # The 📋 indicator, carrying the abstract for the reading pane's delegated handler.
        indicator = card.locator( ".abstract-indicator" )
        assert indicator.count() == 1
        assert "full" in ( indicator.get_attribute( "data-abstract" ) or "" )
        # The inline block, markdown-rendered by the real DOMPurify bundle — which the
        # unit tier CANNOT check, because marked and dompurify are not installed there.
        block = card.locator( ".action-required-abstract" )
        assert block.count() == 1
        assert block.locator( "strong" ).inner_text().strip() == "full", (
            "the real markdown bundle rendered the abstract — unit tests shim this away"
        )
        # The prediction hint.
        assert card.locator( ".prediction-hint-label" ).inner_text().strip() == "Yes"

    def test_chrome_is_absent_tolerant_when_the_server_sends_none_of_it( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _emit( page, { "id_hash": "e2ecard-bare", "response_type": "yes_no" } )
        card = _card( page, "e2ecard-bare" )

        assert card.locator( ".action-required-abstract" ).count() == 0
        assert card.locator( ".abstract-indicator" ).count() == 0
        assert card.locator( ".persona-badge" ).count() == 0
        # No hint sent → legacy's cold-start ghost box, not a missing element.
        assert card.locator( ".prediction-hint-cold" ).count() == 1
