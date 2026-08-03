"""
E2E UI — legacy worker-badge silencing (Rick 2026-06-24, focus-bar parity v0.1.9).

A MANAGED worker (managerPersonaMap holds a non-null persona) keeps its faint
activity pulse but NEVER surfaces a numeric count — neither the focus-bar strip
icon's `data-unread-count` ::after circle nor the per-card `.sender-new-count`
"N new" badge. Unmanaged / manager / root sessions keep their count.

Drives the real `window.notificationsUI` so the full client wiring is exercised
in a live browser:
  - strip carve: managerPersonaMap → _addStripIcon sets data-worker; focus-mode
    _markStripIconActivity keeps data-unread but writes no data-unread-count.
  - card carve: createSenderCard / updateSenderCardHeader set data-worker on the
    .sender-card and suppress the .sender-new-count number.

Gap list / build plan:
  - src/rnd/v0.1.9/2026.06.24-notifications-multiplexer-focus-bar-parity-gap-list.md (§6 Decision A/B)
  - src/rnd/v0.1.9/2026.06.24-focus-bar-parity-build-plan.md (Lane A)

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). Per
CLAUDE.local.md "THE USER IS NEVER A TESTER" every assertion is AI-run; the
Tester owns scheduling this on :8000.
"""

from .conftest import BASE_URL   # noqa: F401  (kept for parity with sibling legacy e2e files)

WORKER = "claude.code@lupin.deepily.ai#legwbsworker1"
ROOT   = "claude.code@lupin.deepily.ai#legwbsroot1"

MANAGER = { "icon": "👑", "initial": "T", "color": "#3F51B5", "name": "Tiberius" }


def _set_manager( page, sender_id, manager_persona ):
    """Plant manager lineage (what voice_persona_assigned's payload would do)."""
    page.evaluate(
        """( args ) => {
            if ( args.manager === null ) {
                window.notificationsUI.managerPersonaMap.delete( args.sender_id );
            } else {
                window.notificationsUI.managerPersonaMap.set( args.sender_id, args.manager );
            }
        }""",
        { "sender_id": sender_id, "manager": manager_persona },
    )


def _add_strip_icon( page, sender_id, session_hash ):
    page.evaluate(
        """( args ) => {
            window.notificationsUI._addStripIcon(
                args.sender_id, 'lupin', { name: 'Rio', color: '#28a745' }, args.session_hash
            );
        }""",
        { "sender_id": sender_id, "session_hash": session_hash },
    )


def _enable_focus_on_other( page, other_sender_id="claude.code@lupin.deepily.ai#someoneelse" ):
    """Focus mode ON, focused on a DIFFERENT session so activity bumps unread."""
    page.evaluate(
        "( focused ) => { window.notificationsUI.ccFocusState = { enabled: true, focused_sender_id: focused }; }",
        other_sender_id,
    )


def _mark_activity( page, sender_id ):
    page.evaluate( "( sid ) => window.notificationsUI._markStripIconActivity( sid )", sender_id )


def _strip_surfaces( page, sender_id ):
    return page.evaluate(
        """( sender ) => {
            const icon = document.getElementById( window.notificationsUI._stripIconIdFor( sender ) );
            if ( !icon ) return null;
            return {
                data_worker  : icon.getAttribute( 'data-worker' ),
                data_unread  : icon.getAttribute( 'data-unread' ),
                unread_count : icon.getAttribute( 'data-unread-count' ),
            };
        }""",
        sender_id,
    )


def _inject_card( page, sender_id, total_count, new_count, session_hash ):
    """Seed a sender group + create the card, then prime updateSenderCardHeader."""
    page.evaluate(
        """( args ) => {
            const ui = window.notificationsUI;
            ui.senderGroups.set( args.sender_id, {
                senderId    : args.sender_id,
                project     : 'lupin',
                sessionHash : args.session_hash,
                isActive    : true,
                totalCount  : args.total_count,
                newCount    : args.new_count,
                dateGroups  : new Map(),
                lastActivity: new Date().toISOString()
            } );
            ui.createSenderCard( args.sender_id, true );
            ui.updateSenderCardHeader( args.sender_id );
        }""",
        { "sender_id": sender_id, "total_count": total_count, "new_count": new_count, "session_hash": session_hash },
    )
    page.wait_for_timeout( 100 )


def _card_surfaces( page, sender_id ):
    sanitized = sender_id.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
    return page.evaluate(
        """( cardId ) => {
            const card = document.getElementById( cardId );
            if ( !card ) return null;
            const nc = card.querySelector( '.sender-new-count' );
            return {
                data_worker    : card.getAttribute( 'data-worker' ),
                new_count_text : nc ? nc.textContent : null,
                new_count_disp : nc ? nc.style.display : null,
            };
        }""",
        f"sender-card-{sanitized}",
    )


class TestLegacyStripCarve:

    def test_worker_strip_icon_pulses_without_numeric_count( self, notifications_page ):
        page = notifications_page
        _set_manager( page, WORKER, MANAGER )
        _add_strip_icon( page, WORKER, "legwbsworker1" )
        _enable_focus_on_other( page )
        _mark_activity( page, WORKER )

        s = _strip_surfaces( page, WORKER )
        assert s is not None, "worker strip icon must exist"
        assert s[ "data_worker" ]  == "true", "worker icon carries data-worker (CSS hides ::after count)"
        assert s[ "data_unread" ]  == "true", "faint pulse kept (sign of life)"
        assert s[ "unread_count" ] is None,   "numeric count attribute never written for a worker"

    def test_root_strip_icon_shows_numeric_count( self, notifications_page ):
        page = notifications_page
        _set_manager( page, ROOT, None )   # no manager
        _add_strip_icon( page, ROOT, "legwbsroot1" )
        _enable_focus_on_other( page )
        _mark_activity( page, ROOT )
        _mark_activity( page, ROOT )

        s = _strip_surfaces( page, ROOT )
        assert s is not None, "root strip icon must exist"
        assert s[ "data_worker" ]  is None,  "root icon not flagged worker"
        assert s[ "data_unread" ]  == "true"
        assert s[ "unread_count" ] == "2",   "count rendered for a non-worker"


class TestLegacyCardCarve:

    def test_worker_card_suppresses_new_count_and_flags_data_worker( self, notifications_page ):
        page = notifications_page
        _set_manager( page, WORKER, MANAGER )
        _inject_card( page, WORKER, total_count=9, new_count=4, session_hash="legwbsworker1" )

        s = _card_surfaces( page, WORKER )
        assert s is not None, "worker card must exist"
        assert s[ "data_worker" ]    == "true", "worker card carries data-worker"
        assert s[ "new_count_disp" ] == "none", "'N new' badge hidden for a worker"

    def test_root_card_shows_new_count( self, notifications_page ):
        page = notifications_page
        _set_manager( page, ROOT, None )
        _inject_card( page, ROOT, total_count=9, new_count=4, session_hash="legwbsroot1" )

        s = _card_surfaces( page, ROOT )
        assert s is not None, "root card must exist"
        assert s[ "data_worker" ]    is None,        "root card not flagged worker"
        assert s[ "new_count_text" ] == "4 new",     "'N new' badge rendered for a non-worker"
        assert s[ "new_count_disp" ] == "inline-block"
