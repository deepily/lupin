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

# addNotificationToList with its audio and clear-button collaborators stubbed; MESSAGE is replaced per site.
LIST_LINE = """
        mount( "notifications-list" );
        ui.formatNotificationTTSMessage = () => ""; ui.addAudioControlListeners = () => {}; ui.updateClearButtonState = () => {};
        ui.addNotificationToList( { message: MESSAGE, type: "task", priority: "low", source: "s", timestamp: 0, id_hash: "l1" } );
        return document.getElementById( "notifications-list" );"""

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
    # Row b5e13bd0 — the notification list line (addNotificationToList): no prefix, after a [PREFIX], title.
    ( "list_line_message", "tag", LIST_LINE.replace( "MESSAGE", "P" ) ),
    ( "list_line_after_prefix", "tag", LIST_LINE.replace( "MESSAGE", "`[LUPIN] ${ P }`" ) ),
    ( "list_line_title", "attr", LIST_LINE.replace( "MESSAGE", "P" ) ),
]

# Sites that show a truncated message rather than the whole one: what each one shows of the payload.
#   renderMinimizedNotificationDOM: over 60 characters → the first 57 + "..."
#   addNotificationToList after "[LUPIN] ": "LUPIN: " is 7 of its 80 shown characters → the first 70 + "..."
TRUNCATING_SITES = { "minimized_card_message": 57, "list_line_after_prefix": 70 }

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
        shown    : root.textContent,
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
        # The minimized card truncates to 57 characters + "..." (measured: ts-7b4ba9f4 failed this
        # arm on the full 78-character payload while its handler and <img> checks passed), so it is
        # held to its own contract: the truncated payload, shown as text.
        cut      = TRUNCATING_SITES.get( site_id )
        expected = TAG_PAYLOAD if cut is None else TAG_PAYLOAD[ :cut ] + "..."
        assert expected in out[ "shown" ], f"{site_id}: the payload is not shown as text"
    else:
        assert out[ "broke" ] == 0, f"{site_id}: the payload broke out of value=\"…\""


# ── onclick buttons whose value used to sit inside a JavaScript string (row 2515ede4) ──────────────
#
# An HTML escape cannot protect a JavaScript string inside onclick="…": the browser decodes the
# entities before the handler runs. The fix moved each value into a data-* attribute and made the
# onclick a constant that passes this.dataset. Each payload below holds ' \ and " and is built to
# break the OLD line for its site: retry's quote-only escape let a backslash close the string, and
# re-render's escapeHtml was decoded straight back to a quote.

ONCLICK_HARNESS = """
async ( [ render, selector, payload ] ) => {
    window.__xss = 0;
    document.body.replaceChildren();
    const calls = [];
    const ui = Object.create( NotificationsUI.prototype );
    ui.debug = false; ui.log = () => {}; ui.error = () => {};
    ui.retryHistoryJob  = ( ...args ) => { calls.push( [ "retry",  ...args ] ); };
    ui.deleteHistoryJob = ( ...args ) => { calls.push( [ "delete", ...args ] ); };
    ui.submitRerender   = ( ...args ) => { calls.push( [ "rerender", ...args ] ); };
    window.notificationsUI = ui;
    const host = document.createElement( "div" );
    host.innerHTML = ( new Function( "ui", "P", render ) )( ui, payload );
    document.body.appendChild( host );
    const button = host.querySelector( selector );
    if ( !button ) return { rendered: false };
    button.click();
    await new Promise( ( r ) => setTimeout( r, 100 ) );
    return { rendered: true, ran: window.__xss, calls, onclick: button.getAttribute( "onclick" ) };
}
"""

RETRY_PAYLOAD    = 'a\\\');window.__xss = ( window.__xss || 0 ) + 1;//"b'
RERENDER_PAYLOAD = 'x\');window.__xss = ( window.__xss || 0 ) + 1;//\\"'


def test_history_retry_passes_the_question_verbatim_and_runs_no_script( legacy_page ):
    render = 'return ui.renderHistoryActions( { id_hash: "j1", status: "failed", question_text: P } );'
    out    = legacy_page.evaluate( ONCLICK_HARNESS, [ render, ".retry-btn", RETRY_PAYLOAD ] )
    assert out[ "rendered" ], "the Retry button was not rendered"
    assert out[ "ran" ] == 0, f"the question's script ran {out[ 'ran' ]} time(s)"
    assert out[ "calls" ] == [ [ "retry", "j1", RETRY_PAYLOAD ] ], out[ "calls" ]
    assert out[ "onclick" ] == "event.stopPropagation(); window.notificationsUI.retryHistoryJob( this.dataset.jobId, this.dataset.question )", (
        "the Retry onclick is no longer the constant — a value has been put back into JavaScript source" )


def test_history_delete_passes_the_job_id_from_its_data_attribute( legacy_page ):
    render = 'return ui.renderHistoryActions( { id_hash: "j1", status: "done", question_text: P } );'
    out    = legacy_page.evaluate( ONCLICK_HARNESS, [ render, ".delete-btn", RETRY_PAYLOAD ] )
    assert out[ "rendered" ], "the Delete button was not rendered"
    assert out[ "calls" ] == [ [ "delete", "j1" ] ], out[ "calls" ]
    assert out[ "onclick" ] == "event.stopPropagation(); window.notificationsUI.deleteHistoryJob( this.dataset.jobId )"


def test_rerender_passes_the_yaml_path_verbatim_and_runs_no_script( legacy_page ):
    render = 'return ui.renderReportLinkSection( "report.md", "presentation", P, null, null );'
    out    = legacy_page.evaluate( ONCLICK_HARNESS, [ render, ".rerender-btn", RERENDER_PAYLOAD ] )
    assert out[ "rendered" ], "the Re-render button was not rendered"
    assert out[ "ran" ] == 0, f"the path's script ran {out[ 'ran' ]} time(s)"
    assert out[ "calls" ] == [ [ "rerender", RERENDER_PAYLOAD ] ], out[ "calls" ]
    assert out[ "onclick" ] == "window.notificationsUI.submitRerender( this.dataset.yamlPath )", (
        "the Re-render onclick is no longer the constant — a value has been put back into JavaScript source" )


def test_CONTROL_the_onclick_payloads_do_run_script_through_the_old_lines( legacy_page ):
    """
    Both payloads, written into the OLD onclick shapes on this page, run their script — so the zeros
    above are findings, not a page that cannot run an inline handler.
    """
    out = legacy_page.evaluate( """async ( [ retry, rerender ] ) => {
        window.__xss = 0;
        window.notificationsUI = { retryHistoryJob: () => {}, submitRerender: () => {} };
        const ui = Object.create( NotificationsUI.prototype );
        const questionSafe = retry.replace( /'/g, "\\\\'" ).replace( /"/g, '&quot;' ).substring( 0, 100 );
        const host = document.createElement( "div" );
        host.innerHTML = `<button id="r" onclick="window.notificationsUI.retryHistoryJob( 'j1', '${ questionSafe }' )">r</button>`
                       + `<button id="y" onclick="window.notificationsUI.submitRerender( '${ ui.escapeHtml( rerender ) }' )">y</button>`;
        document.body.replaceChildren( host );
        host.querySelector( "#r" ).click();
        host.querySelector( "#y" ).click();
        await new Promise( ( r ) => setTimeout( r, 100 ) );
        return window.__xss;
    }""", [ RETRY_PAYLOAD, RERENDER_PAYLOAD ] )
    assert out == 2, f"expected both payloads to run through the old onclick lines, counter read {out}"


def test_the_site_list_matches_the_census():
    """
    Fourteen reachable wraps from row 6ce9f4a1 (plan §Build scope) plus the three list-line sites of row
    b5e13bd0 (the [PREFIX] escape is not a site: its regex admits only A-Z). A site added or dropped must
    update both.
    """
    assert len( SITES ) == 17
    assert len( { s[ 0 ] for s in SITES } ) == 17
