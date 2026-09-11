"""
Sender text cannot run script on the legacy page — measured in a real browser (row 6ce9f4a1).

THE DEFECT. notifications.js wrote sender-supplied strings — a question, an option label, a title, a
session name — into innerHTML unescaped. A payload such as `<img src=x onerror=…>` became an element and
its handler ran. There is no Content-Security-Policy on the page to stop it.

WHY A REAL BROWSER. The unit file (unit/notifications_js/sender_text_is_escaped_in_the_legacy_page.test.ts)
proves each payload PARSES as text. happy-dom never runs event handlers, so only a browser can show that
the handler does not run. This file renders every fixed site in Chromium, focuses every input it rendered,
waits for image errors to fire, and reads a counter the payload would bump.

THE CONTROL THAT MAKES A ZERO MEAN SOMETHING. `test_CONTROL_unescaped_markup_does_run_script_here` writes the
same payloads raw into the same page and watches the counter move. Without it, a page that could not run
script at all would pass every site below.

WHAT THIS FILE RUNS: the REAL notifications.js class (sliced before its DOM-ready init, the slice every
legacy unit test uses) in Chromium via set_content. It needs no server and rides the scheduled :8000 E2E run.
"""

import pytest

import cosa.utils.util as cu


STATIC = cu.get_project_root() + "/src/lupin_app/static"

SENDER = "claude.code@lupin.deepily.ai#abcdef12"

# The counter each payload bumps if its handler runs.
TAG_PAYLOAD  = '<img src="x-missing-image" onerror="window.__xss = ( window.__xss || 0 ) + 1">'
ATTR_PAYLOAD = 'x" onfocus="window.__xss = ( window.__xss || 0 ) + 1" data-broke="1'

# Each site: ( id, the payload shape it takes, JS that renders it and returns the root element ).
# The JS runs with `ui` (a stubbed NotificationsUI) and `P` (the payload) in scope.
SITES = [
    ( "tts_error_text", "tag", """
        ui.showTTSErrorModal( "E1", P, "" );
        return document.querySelector( ".tts-error-modal" );""" ),
    ( "tts_error_code", "tag", """
        ui.showTTSErrorModal( P, "boom", "" );
        return document.querySelector( ".tts-error-modal" );""" ),
    ( "sender_card_session_name", "tag", """
        mount( "notifications-list" );
        ui.senderGroups = new Map(); ui.sessionNames = { abcdef12: P }; ui.conversationModes = {};
        ui.senderPersonaMap = new Map(); ui.ccFocusState = { enabled: false, focused_sender_id: null };
        ui._applyFocusHiddenToCard = () => {}; ui._applyCardWorkerFlag = () => {}; ui._addStripIcon = () => {};
        ui.createSenderCard( SENDER );
        return document.getElementById( "notifications-list" );""" ),
    ( "minimized_card_message", "tag", """
        mount( "action-required-pending-queue" );
        ui.renderMinimizedNotificationDOM( { id: "m1", message: P, response_type: "yes_no", timeout_seconds: 30 }, 1 );
        return document.getElementById( "action-required-pending-queue" );""" ),
    ( "action_required_title", "tag", """
        mount( "action-required-active-slot" );
        ui.renderActionRequiredNotification( { id: "t1", title: P, message: "m", response_type: "yes_no", sender_id: SENDER } );
        return document.getElementById( "action-required-active-slot" );""" ),
    ( "open_ended_response_default", "attr", """
        mount( "action-required-active-slot" );
        ui.renderActionRequiredNotification( { id: "o1", title: "t", message: "m", response_type: "open_ended", response_default: P, sender_id: SENDER } );
        return document.getElementById( "action-required-active-slot" );""" ),
    ( "mc_question", "tag", """
        return mc( { question: P, header: "H", options: [ { label: "a" } ] } );""" ),
    ( "mc_option_label_text", "tag", """
        return mc( { question: "q", header: "H", options: [ { label: P } ] } );""" ),
    ( "mc_option_label_value", "attr", """
        return mc( { question: "q", header: "H", options: [ { label: P } ] } );""" ),
    ( "mc_option_description", "tag", """
        return mc( { question: "q", header: "H", options: [ { label: "a", description: P } ] } );""" ),
    ( "mc_other_answer", "attr", """
        ui.actionRequiredNotifications.set( "mc1", { collectedAnswers: { H: P } } );
        return mc( { question: "q", header: "H", options: [ { label: "a" } ] } );""" ),
    ( "prediction_hint_header", "tag", """
        const host = mount( "pred" );
        host.innerHTML = ui.buildPredictionHintSection( { id: "p1", response_type: "multiple_choice",
            prediction_hint: { confidence: 0.9, strategy: "cbr_retrieval", predicted_value: { answers: { [ P ]: "a" } } } } );
        return host;""" ),
    ( "expired_badge_default", "tag", """
        const card = mount( "action-required-e1" ); card.innerHTML = `<div class="response-buttons"></div>`;
        ui.actionRequiredNotifications.set( "e1", { notification: { id: "e1", response_type: "yes_no", response_default: P, sender_id: SENDER } } );
        ui.calculateDestination = () => null; ui.updateActionRequiredCount = () => {}; ui.saveActionRequiredState = () => {};
        ui.handleLocalTimeout( "e1" );
        return card;""" ),
    ( "responded_elsewhere_badge", "tag", """
        const card = mount( "action-required-r1" ); card.innerHTML = `<div class="response-buttons"></div>`;
        ui.actionRequiredNotifications.set( "r1", { notification: { id: "r1", response_type: "yes_no", sender_id: SENDER } } );
        ui.stopCountdownTimer = () => {}; ui.addNotificationToSenderGroup = () => {}; ui.updateTotalNotificationsCount = () => {};
        ui.updateActionRequiredCount = () => {}; ui.saveActionRequiredState = () => {};
        ui.handleNotificationResponded( { notification_id: "r1", response_value: P } );
        return card;""" ),
]

HARNESS = """
async ( [ body, payload, sender ] ) => {
    window.__xss = 0;
    document.body.replaceChildren();
    const P      = payload;
    const SENDER = sender;
    const ui = Object.create( NotificationsUI.prototype );
    ui.debug = false; ui.log = () => {}; ui.error = () => {};
    ui.actionRequiredNotifications = new Map();
    const mount = ( id ) => { const el = document.createElement( "div" ); el.id = id; document.body.appendChild( el ); return el; };
    const mc = ( question ) => {
        const host = mount( "mc-host" );
        host.innerHTML = ui.renderMultipleChoiceUI( { id: "mc1", sender_id: SENDER, response_type: "multiple_choice",
                                                      response_options: { questions: [ question ] } }, 0 );
        return host;
    };
    const root = ( new Function( "ui", "P", "SENDER", "mount", "mc", body ) )( ui, P, SENDER, mount, mc );
    if ( !root ) return { rendered: false };
    for ( const input of root.querySelectorAll( "input, textarea" ) ) input.focus();
    await new Promise( ( r ) => setTimeout( r, 400 ) );
    return {
        rendered : true,
        ran      : window.__xss,
        imgs     : root.querySelectorAll( "img" ).length,
        broke    : root.querySelectorAll( "[data-broke]" ).length,
        text     : root.textContent.includes( payload ),
    };
}
"""


@pytest.fixture( scope="module" )
def ui_source():
    """
    notifications.js up to its DOM-ready init, with the class exposed on globalThis.

    Ensures:
        - returns script text that defines globalThis.NotificationsUI and starts nothing
        - fails the fixture when the init marker is gone, rather than running the whole page
    """
    full = open( f"{STATIC}/js/notifications.js" ).read()
    idx  = full.find( "// Initialize when DOM is ready" )
    assert idx > 0, "notifications.js no longer carries its DOM-ready init marker — the slice would run the page"
    return full[ :idx ] + "\n;globalThis.NotificationsUI = NotificationsUI;"


@pytest.fixture
def legacy_page( page, ui_source ):
    """A blank page carrying the legacy class and nothing from any server."""
    page.set_content( "<!doctype html><html><body></body></html>" )
    page.add_script_tag( content=ui_source )
    return page


def test_CONTROL_unescaped_markup_does_run_script_here( legacy_page ):
    """Both payload shapes, written raw, run their handler on this page — so a zero below is a finding."""
    out = legacy_page.evaluate( """async ( [ tag, attr ] ) => {
        window.__xss = 0;
        const host = document.createElement( "div" );
        host.innerHTML = `<div>${ tag }</div><input value="${ attr }">`;
        document.body.replaceChildren( host );
        host.querySelector( "input" ).focus();
        await new Promise( ( r ) => setTimeout( r, 400 ) );
        return window.__xss;
    }""", [ TAG_PAYLOAD, ATTR_PAYLOAD ] )
    assert out == 2, f"expected both raw payloads to run their handler, counter read {out}"


@pytest.mark.parametrize( "site_id,shape,body", SITES, ids=[ s[ 0 ] for s in SITES ] )
def test_sender_text_at_this_site_runs_no_script( legacy_page, site_id, shape, body ):
    payload = TAG_PAYLOAD if shape == "tag" else ATTR_PAYLOAD
    out = legacy_page.evaluate( HARNESS, [ body, payload, SENDER ] )
    assert out[ "rendered" ], f"{site_id}: nothing rendered"
    assert out[ "ran" ] == 0, f"{site_id}: the payload's handler ran {out[ 'ran' ]} time(s)"
    if shape == "tag":
        assert out[ "imgs" ] == 0, f"{site_id}: the payload became an <img>"
        assert out[ "text" ], f"{site_id}: the payload is not shown as text"
    else:
        assert out[ "broke" ] == 0, f"{site_id}: the payload broke out of value=\"…\""


def test_the_site_list_matches_the_census():
    """Fourteen reachable wraps in this row (plan §Build scope); a site added or dropped must update both."""
    assert len( SITES ) == 14
    assert len( { s[ 0 ] for s in SITES } ) == 14
