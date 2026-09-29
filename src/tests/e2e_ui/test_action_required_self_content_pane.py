"""
E2E UI — self-content clicks inside an action-required card LIFTED into the Reading Pane.

Covers the live-only gap behind bug 11c01fbc (fixed 31ee0250) and its residual
bug 17ce50a5 (fixed 1abae42c). In horizontal layout an arriving action-required
notification LIFTS-AND-MOVES the live #action-required-content element into the
Reading Pane, which is SHARED with the live response buttons. Three self-content
click paths must therefore behave differently from FOREIGN (center-column) clicks:

  1. The card's OWN 📋 abstract indicator must open the in-tab tooltip, NOT the
     pane (routing it through _openContentPane would wipe the shared pane body).
  2. A doc link inside that card's abstract TOOLTIP must open a NEW TAB — NOT be
     routed into the pane. ⚠️ THE ROUTE CHANGED IN ROW 47759aa3 AND THE RULING DID
     NOT: it used to fall through to the anchor's baked-in target=_blank, which is
     no longer emitted for an in-app doc link, so the app now preventDefaults and
     calls window.open itself. Same tab for the user, different observable — this
     test reads preventDefault=True PLUS an explicit window.open, and also asserts
     the shared pane is untouched, which is the harm itself rather than a proxy. The
     tooltip is fixed-position and appended to <body>, so an ancestry-only
     self-test ( closest("#action-required-content") ) MISSES it; the fix widened
     the self-surface selector to include ".abstract-tooltip" (bug 17ce50a5).
  3. Control both directions: a FOREIGN abstract indicator still routes to the
     pane, and a FOREIGN doc link is still intercepted + preventDefault'd.

INSTRUMENT VALIDITY (the row's explicit requirement): the LAST test mutates the
running client AT RUNTIME — via an init script that wraps Element.closest so ONLY
the widened self-surface selector string behaves as its pre-17ce50a5 form — and
proves the SAME harness observes the bug (the tooltip doc link is routed INTO the pane
rather than opened in a tab). No
on-disk file is touched (both live containers serve the fixed notifications.js
unchanged); the mutation is scoped to this test's browser context.

That wrapper keys on the exact selector STRING, which makes it a control that could
expire silently: if the real selector later drifts (a third surface, a reorder, a
whitespace change) the wrapper would stop matching, never fire, and the red half
would prove nothing while the test stayed green. So the wrapper COUNTS its own hits
and the red-proof asserts it actually fired on the load-bearing click — a drifted
selector fails LOUDLY ("wrapper never fired — update _FIXED_SELECTOR"), never
silently. An instrument that cannot go red on the old behaviour cannot vouch for
the new — 6/6 unit tests and a four-vector review passed while the defect survived,
because every one asked about the CARD's DOM and none asked about the tooltip the
fix routes INTO.

Predicted failure text if the fix regresses (test 2):
    AssertionError: …it must open exactly one new tab EXPLICITLY. …; got openCount=0
  or, if a self-link leaks into the shared pane:
    AssertionError: the shared pane must be UNTOUCHED by a self-link click …

Venue: :8000 (scheduled monopolize-mode via /api/v2/submit).

Submit via:
    POST /api/v2/submit
    {
        "test_types"         : "e2e",
        "pytest_args"        : "-k test_action_required_self_content_pane",
        "scheduled_at"       : "<slot>",
        "auto_fix_on_failure": false
    }
"""

import pytest

from .conftest import BASE_URL, wait_for_ws_connected


# The exact self-surface selector the fix (1abae42c) widened. The red-proof below
# rewrites Element.closest so a call with this string behaves as the pre-fix form.
# If the real selector drifts from this literal, the red-proof wrapper stops firing
# and the test fails LOUDLY (by design) rather than silently covering nothing.
_FIXED_SELECTOR  = "#action-required-content, .abstract-tooltip"
_PREFIX_SELECTOR = "#action-required-content"

# A real, whitelisted doc path so the anchor is a genuine /app/docs?path= link
# (the doc-link interceptor only fires on that prefix).
_DOC_LINK_MD     = "[View design](/app/docs?path=lupin/CLAUDE.md)"


def _click_layout_toggle( page ):
    page.locator( "#layout-mode-toggle" ).click()
    page.wait_for_timeout( 100 )


def _emit_action_required( page, nid, abstract ):
    """
    Drive the real handleNotificationUpdate → addActionRequiredNotification →
    renderActionRequiredNotification path with an abstract that carries a doc link.
    In horizontal mode this LIFTS #action-required-content into the pane.
    """
    page.evaluate(
        """( args ) => {
            window.notificationsUI.handleNotificationUpdate( {
                notification: {
                    id                 : args.nid,
                    id_hash            : args.nid,
                    type               : 'custom',
                    response_requested : true,
                    response_type      : 'yes_no',
                    message            : 'Deploy to prod?',
                    title              : 'Deploy to prod?',
                    abstract           : args.abstract,
                    timeout_seconds    : 300,
                    sender_id          : 'claude.code@lupin.deepily.ai#arself1'
                }
            } );
        }""",
        { "nid": nid, "abstract": abstract },
    )
    page.wait_for_timeout( 300 )


def _install_doc_click_probe( page ):
    """
    Register a document-level bubble listener that runs AFTER the app's doc-link
    interceptor (later registration → later in the same bubble phase). It records
    the app's decision ( ev.defaultPrevented ) for any /app/docs anchor click, then
    calls preventDefault itself so a self-link's real target=_blank does not spawn a
    popup tab during the run. Reading BEFORE preventing keeps the recorded value the
    app's, not ours.
    """
    page.evaluate(
        """() => {
            window.__docProbe = { href: null, prevented: null, count: 0, opened: null, openCount: 0 };
            // Row 47759aa3 — window.open is now LOAD-BEARING for the two exception
            // surfaces. Before that row they kept their tab by falling through to the
            // anchor's baked-in target="_blank"; that attribute is gone for doc links,
            // so the app calls window.open explicitly instead. A probe that watched
            // only defaultPrevented could no longer tell "opened a tab" from
            // "swallowed the click".
            const realOpen = window.open;
            window.open = function( url, target, features ) {
                window.__docProbe.opened     = { url: url, target: target, features: features };
                window.__docProbe.openCount += 1;
                return null;   // never actually spawn a tab during the run
            };
            window.__docProbeRestoreOpen = () => { window.open = realOpen; };
            document.addEventListener( 'click', ( ev ) => {
                const a = ev.target.closest( 'a[href]' );
                if ( !a ) return;
                const href = a.getAttribute( 'href' ) || '';
                if ( href.indexOf( '/app/docs?path=' ) === -1 ) return;
                window.__docProbe.href      = href;
                window.__docProbe.prevented = ev.defaultPrevented;  // the app's decision
                window.__docProbe.count    += 1;
                ev.preventDefault();                                // suppress the real popup in-test
            }, false );
        }"""
    )


def _read_probe( page ):
    return page.evaluate( "() => window.__docProbe" )


def _pane_signature( page ):
    """
    A fingerprint of the SHARED pane body — the thing bugs 11c01fbc and 17ce50a5 were
    about. `_renderContentPaneEntry` clears this body, so a self-link that leaked into
    the pane would delete the live response buttons the user is mid-press on.

    Returns the lifted element's identity plus its live-button count, because either
    one changing is the harm: the element being re-parented away, or its buttons being
    wiped while it stays put. A length alone would miss the second.
    """
    return page.evaluate(
        """() => {
            const body    = document.getElementById( 'content-pane-body' );
            const content = document.getElementById( 'action-required-content' );
            return {
                lifted  : !!( body && content && content.parentNode === body ),
                buttons : content ? content.querySelectorAll( 'button' ).length : -1,
                bodyKids: body ? body.children.length : -1,
            };
        }"""
    )


def _pane_open( page ):
    return page.evaluate( "() => !!document.querySelector( '.content-shell.pane-open' )" )


def _tooltip_visible( page ):
    return page.evaluate(
        "() => { const t = document.getElementById( 'abstract-tooltip' ); return !!t && t.classList.contains( 'visible' ); }"
    )


def _lifted_into_pane( page ):
    return page.evaluate(
        """() => {
            const content = document.getElementById( 'action-required-content' );
            const body    = document.getElementById( 'content-pane-body' );
            return ( content && body ) ? ( content.parentNode === body ) : false;
        }"""
    )


def _own_indicator( page ):
    """The action-required card's OWN 📋 indicator, inside #action-required-content."""
    return page.locator( "#action-required-content .abstract-indicator" ).first


def _tooltip_doc_anchor( page ):
    return page.locator(
        "#abstract-tooltip .abstract-tooltip-content a[href*='/app/docs']"
    ).first


def _inject_foreign_indicator( page, abstract_text ):
    """A .abstract-indicator OUTSIDE #action-required-content (center/left column)."""
    page.evaluate(
        """( txt ) => {
            const container = document.querySelector( '.left-column .container' ) || document.body;
            const host = document.createElement( 'div' );
            host.className = 'sender-card';
            const ind = document.createElement( 'span' );
            ind.className = 'abstract-indicator';
            ind.dataset.abstract    = encodeURIComponent( txt );
            ind.dataset.testForeign = '1';
            ind.textContent = '📋';
            host.appendChild( ind );
            container.appendChild( host );
        }""",
        abstract_text,
    )


def _inject_foreign_doc_link( page ):
    """A /app/docs anchor OUTSIDE #action-required-content and outside any tooltip."""
    page.evaluate(
        """() => {
            const container = document.querySelector( '.left-column .container' ) || document.body;
            const host = document.createElement( 'div' );
            host.className = 'sender-card';
            const a = document.createElement( 'a' );
            a.href   = '/app/docs?path=lupin/CLAUDE.md';
            a.target = '_blank';
            a.dataset.testForeign = '1';
            a.textContent = 'Foreign design';
            host.appendChild( a );
            container.appendChild( host );
        }"""
    )


class TestActionRequiredSelfContentPane:
    """
    Self-content vs foreign-content click routing while an action-required card is
    lifted into the shared Reading Pane (horizontal mode).
    """

    def test_own_abstract_indicator_shows_tooltip_not_pane( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )                                # → horizontal
        _emit_action_required( page, "ar-self-1", _DOC_LINK_MD )
        assert _lifted_into_pane( page ) is True, \
            "action-required card must lift into the shared pane in horizontal mode"

        _own_indicator( page ).click()
        page.wait_for_timeout( 150 )
        assert _tooltip_visible( page ) is True, \
            "the card's OWN 📋 must open the in-tab tooltip (never re-route the shared pane)"

    def test_tooltip_self_doc_link_opens_new_tab_via_explicit_window_open( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )                                # → horizontal
        _emit_action_required( page, "ar-self-2", _DOC_LINK_MD )
        assert _lifted_into_pane( page ) is True

        _own_indicator( page ).click()
        page.wait_for_timeout( 150 )
        anchor = _tooltip_doc_anchor( page )
        assert anchor.count() > 0, \
            "the abstract's doc link must render as an anchor inside the tooltip"

        _install_doc_click_probe( page )
        before = _pane_signature( page )
        assert before[ "lifted" ] is True and before[ "buttons" ] > 0, (
            "the fixture must start with the live card lifted INTO the pane and carrying "
            f"response buttons, or the untouched-pane assertion below is vacuous; got {before}"
        )
        anchor.click()
        page.wait_for_timeout( 150 )
        probe = _read_probe( page )
        assert probe[ "count" ] == 1, "the doc-link probe must observe exactly one click"
        # 🔴 ROW 47759aa3 CHANGED THE ROUTE, NOT THE RULING. This assertion read
        # `prevented is False` and pinned the OLD mechanism: the anchor's baked-in
        # target="_blank" opening the tab. That attribute is no longer emitted for an
        # in-app doc link (María's design (a)), so a bare fall-through would now
        # navigate the CURRENT tab and destroy the shared pane — the exact harm bugs
        # 11c01fbc and 17ce50a5 bought this exception to prevent. The app therefore
        # preventDefaults AND calls window.open itself. Same outcome for the user, a
        # new tab; a different observable, and this is the observable.
        assert probe[ "prevented" ] is True, (
            "tooltip self doc link must be claimed (preventDefault) now that the anchor "
            "carries no target=_blank to fall through to — an unclaimed click would "
            f"navigate the current tab and wipe the shared pane; got prevented={probe[ 'prevented' ]}"
        )
        assert probe[ "openCount" ] == 1, (
            "…and it must open exactly one new tab EXPLICITLY. This is the half that makes "
            "the assertion above safe: preventDefault alone would mean the link silently "
            f"did nothing at all; got openCount={probe[ 'openCount' ]}"
        )
        assert probe[ "opened" ][ "target" ] == "_blank", \
            f"the explicit open must target a new tab; got {probe[ 'opened' ]}"
        assert "/app/docs?path=" in ( probe[ "opened" ][ "url" ] or "" ), (
            "and it must open the DOC the user clicked, not some other url; "
            f"got {probe[ 'opened' ][ 'url' ]!r}"
        )
        # AND WHAT THE USER SEES IN THE PANE — Mr. Radio's ruling 2026-09-27. The tab is
        # only half the contract; the other half is that the pane the user was working in
        # is still there. This is the assertion that would have caught the harm directly,
        # rather than by proxy through a route.
        after = _pane_signature( page )
        assert after == before, (
            "the shared pane must be UNTOUCHED by a self-link click — that is the whole "
            "reason this exception exists (bugs 11c01fbc, 17ce50a5). A changed signature "
            "means the live response buttons were re-parented or wiped mid-interaction; "
            f"before={before} after={after}"
        )

    def test_foreign_doc_link_still_intercepted_into_pane( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )                                # → horizontal
        _inject_foreign_doc_link( page )
        _install_doc_click_probe( page )

        page.locator( "a[data-test-foreign='1']" ).first.click()
        page.wait_for_timeout( 150 )
        probe = _read_probe( page )
        assert probe[ "prevented" ] is True, (
            "a FOREIGN center-column doc link must still be intercepted "
            f"(preventDefault); got prevented={probe[ 'prevented' ]}"
        )
        assert _pane_open( page ) is True, \
            "the intercepted foreign doc link must open the Reading Pane"

    def test_foreign_abstract_indicator_routes_to_pane( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )                                # → horizontal
        _inject_foreign_indicator( page, "**Foreign abstract**" )

        page.locator( ".abstract-indicator[data-test-foreign='1']" ).first.click()
        page.wait_for_timeout( 150 )
        assert _pane_open( page ) is True, \
            "a FOREIGN abstract indicator must route to the Reading Pane"
        assert _tooltip_visible( page ) is False, \
            "a foreign indicator must NOT open the in-tab tooltip in horizontal mode"

    def test_pre_fix_selector_reintroduces_the_bug( self, logged_in_page ):
        """
        Instrument-validity red-proof (runtime mutation, no file touched): before
        notifications.js loads, wrap Element.closest so a call with the widened
        self-surface selector behaves as its pre-17ce50a5 form (dropping
        ".abstract-tooltip") AND counts each such substitution. Every OTHER
        closest() call is untouched, so only the single line the fix changed
        reverts.

        The wrapper's hit counter is load-bearing: the red-proof asserts it fired
        on the tooltip-anchor click BEFORE trusting the prevented result. If the
        real selector ever drifts from _FIXED_SELECTOR, the wrapper never matches,
        the counter stays 0, and this test fails loudly naming the cause — instead
        of the control quietly proving nothing.
        """
        page = logged_in_page

        page.add_init_script(
            """
            ( () => {
                const FIXED  = "%s";
                const PREFIX = "%s";
                window.__closestWrapHits = 0;
                const orig = Element.prototype.closest;
                Element.prototype.closest = function( selector ) {
                    if ( selector === FIXED ) {
                        window.__closestWrapHits += 1;
                        return orig.call( this, PREFIX );
                    }
                    return orig.call( this, selector );
                };
            } )();
            """ % ( _FIXED_SELECTOR, _PREFIX_SELECTOR )
        )
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( page )

        _click_layout_toggle( page )                                # → horizontal
        _emit_action_required( page, "ar-prefix-1", _DOC_LINK_MD )
        assert _lifted_into_pane( page ) is True

        _own_indicator( page ).click()
        page.wait_for_timeout( 150 )
        anchor = _tooltip_doc_anchor( page )
        assert anchor.count() > 0, "tooltip anchor must still render under the reverted selector"

        hits_before = page.evaluate( "() => window.__closestWrapHits" )
        _install_doc_click_probe( page )
        anchor.click()
        page.wait_for_timeout( 150 )
        hits_after = page.evaluate( "() => window.__closestWrapHits" )

        assert hits_after > hits_before, (
            "RED-PROOF CONTROL EXPIRED: the closest() wrapper never fired on the "
            "doc-link click — the widened self-surface selector has drifted from "
            f"_FIXED_SELECTOR ({_FIXED_SELECTOR!r}). Update the literal so the "
            "red-proof matches the real line again."
        )
        probe = _read_probe( page )
        assert probe[ "prevented" ] is True, (
            "RED-PROOF FAILED: with the pre-17ce50a5 selector the tooltip doc link "
            "must be intercepted (prevented=True) — the bug this harness guards. "
            f"got prevented={probe[ 'prevented' ]}"
        )
