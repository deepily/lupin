#!/usr/bin/env python3
"""
E2E — the multiplexer jobs pane speaks the legacy client's words (parity A-2 #10, row 0ef31897).
PARITY-CLAIM: A-2 #10
Build plan src/rnd/v0.2.1/2026.09.15-multiplexer-parity-build-plan.md §1 A-2 row 10; audit Phase 2
A12 (B9d, B10, Q2, Q5). The legacy code each check copies, read at 2847ea74:

    headings        #queues-section notifications.html:1163-1245 — the five category headings
                    inside it (🟡 TODO · 🔵 Running · ✅ Done · ❌ Dead · 📋 Job History)
    empty copy      notifications.js:5735 updateQueueEmptyMessage, :6622 loadJobHistory
    delete-all      notifications.js:6869 deleteAllQueueJobs
    history dedup   notifications.js:6622 loadJobHistory — live Done/Dead ids sent as exclude_ids

The unit tier (the_jobs_pane_speaks_the_legacy_words.test.ts) runs the same rules under happy-dom.
This file proves the SERVED bundle carries them: a stale build or an unbounced server is green
there and red here.

Every delete-all dialog is DISMISSED, so nothing is deleted. The one injected event is a
job_state_transition through the page's own test hook, the shape the WebSocket delivers — the
only way to put a job in the live Done bucket without running one.

Venue: :8000 (monopolize, scheduled) — logged_in_page wipes lupin_db_test. Run:
    LUPIN_ROOT=<tree> ./src/scripts/run-e2e-ui-tests.sh -k multiplexer_jobs_pane_legacy_words
"""

from urllib.parse import parse_qs, urlparse

from .conftest import BASE_URL

MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"
HISTORY_PATH    = "/api/job-history"
JOBS_PANE       = '[data-testid="multiplexer-jobs-pane"]'

LEGACY_HEADINGS = [
    ( "todo",    "🟡", "TODO" ),
    ( "running", "🔵", "Running" ),
    ( "done",    "✅", "Done" ),
    ( "dead",    "❌", "Dead" ),
    ( "history", "📋", "Job History" ),
]

_INJECT_DONE_JS = """
( id ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook not present — boot.ts test surface missing" );
    hook.eventBus.emit( {
        type    : "job_state_transition",
        payload : { job_id: id, id_hash: id, from_state: null, to_state: "completed", metadata: { agent_type: "DeepResearchJob" } },
        source  : "jobs-pane-legacy-words-e2e",
        ts      : Date.now(),
    } );
}
"""


def _is_history( url ):
    return urlparse( url ).path == HISTORY_PATH


def _open_multiplexer( page ):
    """
    Load the multiplexer, wait for its boot history read, and return the live list of history urls.

    Ensures:
        - the jobs pane is visible and its boot history read answered 200
    """
    history_urls = []
    page.on( "request", lambda req: history_urls.append( req.url ) if _is_history( req.url ) else None )
    with page.expect_response( lambda r: _is_history( r.url ), timeout=15000 ) as boot:
        page.goto( MULTIPLEXER_URL )
    assert boot.value.status == 200, f"boot history load answered {boot.value.status}"
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )
    page.wait_for_selector( JOBS_PANE, state="visible", timeout=10000 )
    return history_urls


def _confirm_text( page, bucket ):
    """Press a bucket's delete-all, DISMISS the dialog, and return its text."""
    seen = []

    def _dismiss( dialog ):
        seen.append( dialog.message )
        dialog.dismiss()

    page.once( "dialog", _dismiss )
    page.locator( f'{JOBS_PANE} .queue-delete-all-btn[data-bucket="{bucket}"]' ).click()
    page.wait_for_timeout( 300 )
    assert len( seen ) == 1, f"pressing the {bucket} delete-all raised {len( seen )} dialogs"
    return seen[ 0 ]


def test_each_bucket_carries_legacys_glyph_and_label( logged_in_page ):
    page = logged_in_page
    _open_multiplexer( page )
    for bucket, glyph, label in LEGACY_HEADINGS:
        header = page.locator( f"{JOBS_PANE} .jobs-bucket-{bucket} .jobs-bucket-header" )
        assert header.locator( ".jobs-bucket-glyph" ).text_content().strip() == glyph, f"{bucket} glyph"
        assert header.locator( ".jobs-bucket-label" ).text_content().strip() == label, f"{bucket} label"


def test_empty_buckets_use_legacys_copy( logged_in_page ):
    page = logged_in_page
    _open_multiplexer( page )
    # logged_in_page wiped lupin_db_test, so history holds nothing for this user.
    history_empty = page.locator( f"{JOBS_PANE} .jobs-bucket-history .jobs-bucket-empty" )
    assert history_empty.text_content().strip() == "No job history found"

    checked = 0
    for bucket in ( "todo", "running", "done", "dead" ):
        empty = page.locator( f"{JOBS_PANE} .jobs-bucket-{bucket} .jobs-bucket-empty" )
        if empty.count() == 0: continue   # the in-memory queue holds a job from an earlier test
        assert empty.text_content().strip() == "No jobs in queue", f"{bucket} empty copy"
        checked += 1
    assert checked > 0, "every live queue held a job, so the live empty copy was never read"


def test_delete_all_names_the_queue_and_the_history_window( logged_in_page ):
    page = logged_in_page
    _open_multiplexer( page )

    todo_count = page.locator( f"{JOBS_PANE} .jobs-bucket-todo .job-card" ).count()
    todo_jobs  = "job" if todo_count == 1 else "jobs"
    assert _confirm_text( page, "todo" ) == f"Remove all {todo_count} {todo_jobs} from the todo queue?"

    running_text = _confirm_text( page, "running" )
    assert running_text.startswith( "Cancel and remove all " ), running_text
    assert running_text.endswith( "? This will interrupt active jobs." ), running_text

    assert _confirm_text( page, "history" ) == "Delete all 0 history entries from last 30 days?"


def test_history_leaves_out_a_job_live_in_done( logged_in_page ):
    page         = logged_in_page
    history_urls = _open_multiplexer( page )
    live_id      = "e2e-live-done-0ef31897"

    page.evaluate( _INJECT_DONE_JS, live_id )
    page.wait_for_selector( f'{JOBS_PANE} .jobs-bucket-done .job-card[data-id-hash="{live_id}"]', state="attached", timeout=5000 )

    before = len( history_urls )
    with page.expect_response( lambda r: _is_history( r.url ), timeout=10000 ) as reread:
        page.locator( f"{JOBS_PANE} .history-time-select" ).select_option( "7" )
    assert reread.value.status == 200, f"history re-read answered {reread.value.status}"

    new_urls = history_urls[ before: ]
    assert len( new_urls ) >= 1, "the window change sent no history read"
    excluded = parse_qs( urlparse( new_urls[ -1 ] ).query ).get( "exclude_ids", [ "" ] )[ 0 ].split( "," )
    assert live_id in excluded, f"the history read did not exclude the live Done job: {new_urls[ -1 ]}"
