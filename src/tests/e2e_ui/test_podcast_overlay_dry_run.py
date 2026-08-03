"""
E2E UI — a DRY-RUN submit's overlay actually PLAYS the committed fixture (2026-08-03).

WHY THIS EXISTS. `test_podcast_overlay_playhere.py` proves the overlay path, but it
targets a ~6.3MB user podcast under io/podcasts/<email>/ that is NOT committed —
CI-fragile (host-resident dependency). This test proves the SAME path using the
git-tracked dry-run fixture (io/fixtures/podcast-dry-run/podcast-dry-run.mp3), so it
round-trips into a fresh :8000 / CI container with no host dependency.

It also closes the loop on the dry-run feature itself: right now a dry-run submit's
completion card had nothing to click. After PodcastGeneratorJob._execute_dry_run was
wired to emit Play Here / Listen / Download for the fixture, a dry-run submit is a
zero-cost end-to-end exercise of the whole overlay path — link emission →
&embed=1 interception → iframe render → blob-fetch auth → auto-start.

FAITHFUL EMIT. The abstract rendered here is captured from the REAL
_execute_dry_run (voice_io mocked), not hand-built — so if the emit shape drifts,
this test drifts with it and the click target changes accordingly.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e_ui",
        "pytest_args"        : "-k test_podcast_overlay_dry_run",
        "scheduled_at"       : "<slot>",
        "auto_fix_on_failure": false
    }
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from .test_podcast_overlay_playhere import (
    OVERLAY,
    ABS_HOST,
    _click_play_here,
    _assert_frame_audio_playing,
)

FIXTURE_ENC = "fixtures/podcast-dry-run/podcast-dry-run.mp3"


# Shared consume predicate — the SINGLE source of truth for "did the done card
# render the abstract with a clickable Play Here?". Both the real promotion test
# and the negative control call THIS exact function, so the control proves MY
# predicate detects the bug, not some second hand-rolled check.
_ABSTRACT_PREDICATE_JS = """
( card ) => {
    const ab = card && card.querySelector( '.job-abstract' );
    const a  = ab && ab.querySelector( "a[href*='embed=1']" );
    const abstractText = ab ? ( ab.textContent || '' ).trim() : '';
    const playHref     = a ? a.getAttribute( 'href' ) : null;
    const playVisible  = !!( a && a.offsetParent !== null );
    return {
        abstractText : abstractText,
        playHref     : playHref,
        playVisible  : playVisible,
        ok : abstractText.length > 0 && !!playHref && playHref.indexOf( 'embed=1' ) !== -1 && playVisible
    };
}
"""


def _consume_predicate_by_job_id( page, job_id ):
    """Run the shared consume predicate against the live card for job_id."""
    return page.evaluate(
        "( jobId ) => ( " + _ABSTRACT_PREDICATE_JS
        + " )( document.getElementById( 'job-card-' + jobId ) )",
        job_id,
    )


def _capture_dry_run_abstract() -> str:
    """Run the REAL _execute_dry_run with voice_io mocked and return the completion
    abstract it emits — the exact markdown a dry-run submit shows the user.

    Runs on a dedicated thread with its own event loop: the Playwright sync API
    drives an event loop in the test thread, so `asyncio.run()` here would raise
    'cannot be called from a running event loop'. A fresh thread has no ambient
    loop, so `asyncio.run()` is safe there.
    """
    import threading

    from cosa.agents.podcast_generator.job import PodcastGeneratorJob

    box: dict = {}

    def _worker():
        job = PodcastGeneratorJob(
            research_path = "/io/dr/report.md",
            user_id       = "u1",
            user_email    = "dry-run-e2e@test.com",
            session_id    = "s1",
        )
        voice_io       = MagicMock()
        voice_io.notify = AsyncMock()
        cosa_interface = MagicMock()
        cosa_interface._get_sender_id.return_value = "sid"

        with patch( "asyncio.sleep", AsyncMock() ):
            asyncio.run( job._execute_dry_run( voice_io, cosa_interface ) )

        completion = next(
            c for c in voice_io.notify.await_args_list if c.kwargs.get( "abstract" )
        )
        box[ "abstract" ] = completion.kwargs[ "abstract" ]

    t = threading.Thread( target=_worker )
    t.start()
    t.join()
    return box[ "abstract" ]


def _render_md( page, md: str ):
    """Render arbitrary abstract markdown through the app's OWN renderer into a
    pinned host so its anchors are actionable (mirrors playhere._render_abstract)."""
    page.evaluate(
        """( md ) => {
            const host = document.createElement( 'div' );
            host.dataset.testPodcastAbstract = '1';
            host.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:2147483647;background:#222;padding:8px;';
            host.innerHTML = window.notificationsUI.renderAbstractSection( md );
            document.body.appendChild( host );
        }""",
        md,
    )


class TestPodcastOverlayDryRun:
    """A dry-run completion abstract's Play Here opens the overlay and plays the fixture."""

    def test_dry_run_abstract_targets_committed_fixture( self ):
        """The emitted abstract points Play Here at the git-tracked fixture (unit-ish
        guard so a CI failure localizes to emit-vs-render)."""
        abstract = _capture_dry_run_abstract()
        assert f"/app/audio?path={FIXTURE_ENC}&embed=1" in abstract
        assert "🧪" in abstract
        assert "not a real podcast" in abstract.lower()

    def test_dry_run_play_here_plays_fixture_in_overlay( self, notifications_page ):
        page = notifications_page
        _render_md( page, _capture_dry_run_abstract() )
        # Sanity: the rendered anchor is the fixture's &embed=1 URL.
        assert page.locator(
            f"{ABS_HOST} a[href*='{FIXTURE_ENC}'][href*='embed=1']"
        ).count() == 1

        _click_play_here( page )
        page.locator( OVERLAY ).wait_for( state="visible", timeout=5000 )
        _assert_frame_audio_playing( page )


class TestDryRunDoneCardConsumeSeam:
    """
    The CONSUME side (bug 9b481811): when a dry-run podcast job promotes
    running→done, the card must render its abstract (with a clickable Play Here)
    IN THE LIVE BROWSER, WITHOUT a page reload.

    This is the seam that broke on Rick's rehearsal: unit tests asserted the done
    EVENT carries an abstract (emit), but nobody asserted the CARD renders it
    (consume). A green unit suite and a blank on-stage card coexisted all day. The
    no-reload part IS the test — refreshing is the workaround that hides the bug.

    CONTROL (predict the failure text): against code that does NOT store
    artifacts["abstract"] on the dry-run path, the done promotion carries no
    abstract, .job-abstract stays empty, and this fails with
    "abstract empty on done card" / "Play Here absent" — NOT a bare timeout.

    DETECTION IS PROVEN TWO WAYS (phase-2 timed-revert is DROPPED, not deferred —
    :8000 and :7999 bind the same src mount, so reverting the fix to force a real
    red would revert it out from under a live rehearsal):
      - The real test below rides the FULL running→done WebSocket promotion and
        asserts the abstract renders.
      - `test_negative_control_predicate_detects_omitted_abstract` proves the
        SAME predicate goes RED when the done event omits the abstract — the exact
        symptom the server bug produced — with no server on buggy code and no reload.

    Venue: :8000 (scheduled) — a real dry-run submit enqueues + mutates queue
    state and needs the consumer running. Dry run = no LLM/ElevenLabs spend.
    """

    def test_dry_run_done_card_renders_abstract_no_reload( self, notifications_page, test_user_credentials ):
        import os
        import cosa.utils.util as cu

        page  = notifications_page
        email = test_user_credentials[ "email" ]

        # Seed a research doc so the submit's direct-mode existence check passes.
        # podcast_generator.py:491 checks os.path.exists BEFORE the dry_run flag is
        # applied (:501), so a fake path 404s at submit even for a dry run. dry_run
        # then skips actually reading it, so the content is irrelevant.
        research_dir = cu.get_project_root() + f"/io/deep-research/{email}"
        os.makedirs( research_dir, exist_ok=True )
        seed = research_dir + "/2026.08.03-dry-run-consume-e2e.md"
        with open( seed, "w", encoding="utf-8" ) as f:
            f.write( "# Dry-run consume E2E seed\n\nIrrelevant — dry_run skips reading this.\n" )

        try:
            # Submit a DRY-RUN podcast through the app's own API AS THIS logged-in
            # user, so the job's running/done events land on THIS page's WebSocket.
            job_id = page.evaluate(
                """async ( source ) => {
                    const tok = localStorage.getItem( 'lupin_access_token' );
                    const res = await fetch( '/api/podcast-generator/submit', {
                        method  : 'POST',
                        headers : { 'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json' },
                        body    : JSON.stringify( { research_source: source, dry_run: true } )
                    } );
                    const j = await res.json();
                    return j.job_id || null;
                }""",
                f"/io/deep-research/{email}/2026.08.03-dry-run-consume-e2e.md",
            )
            assert job_id, "podcast dry-run submit did not return a job_id"

            # (req 3) Prove the card passes THROUGH a pre-done state during the test,
            # so a stale done card can't false-pass. First wait for the card to exist
            # (todo/running), then assert it is NOT already done.
            page.wait_for_function(
                "( jobId ) => !!document.getElementById( 'job-card-' + jobId )",
                arg=job_id,
                timeout=20000,
            )
            predone = page.evaluate(
                """( jobId ) => {
                    const c = document.getElementById( 'job-card-' + jobId );
                    const r = c && c.querySelector( '.job-response' );
                    const done = !!r && r.style.display !== 'none' && ( r.textContent || '' ).trim().length > 0;
                    return done ? 'already-done' : 'pending';
                }""",
                job_id,
            )
            assert predone == "pending", \
                f"card was already done at first observation ({predone}) — running→done not exercised"

            # NO RELOAD from here. Wait on the DONE SIGNAL, not the abstract:
            # insertJobMetadata() shows .job-response (from response_text) on EVERY
            # completion, independent of the abstract. Keying the wait on
            # .job-response proves the running→done promotion happened WITHOUT a
            # reload and decouples "reached done" from "abstract rendered" — so on
            # pre-fix code the wait still SUCCEEDS and the failure surfaces as the
            # abstract ASSERTION below, not a bare timeout a broken selector could
            # also produce.
            page.wait_for_function(
                """( jobId ) => {
                    const card = document.getElementById( 'job-card-' + jobId );
                    if ( !card ) return false;
                    const resp = card.querySelector( '.job-response' );
                    return !!resp && resp.style.display !== 'none'
                           && ( resp.textContent || '' ).trim().length > 0;
                }""",
                arg=job_id,
                timeout=45000,
            )

            # Card promoted to DONE (no reload). Assert the CONSUME seam via the
            # SHARED predicate. On pre-fix code the done event carries no abstract →
            # .job-abstract stays empty → PREDICTED text, not a timeout.
            state = _consume_predicate_by_job_id( page, job_id )
            assert state[ "abstractText" ], "abstract empty on done card (no reload)"
            assert state[ "playHref" ] and "embed=1" in state[ "playHref" ], \
                "Play Here absent on done card (no reload)"
            assert state[ "playVisible" ], "Play Here present but not clickable/visible"
            assert state[ "ok" ], "shared consume predicate failed on the real done card"
        finally:
            if os.path.exists( seed ):
                os.remove( seed )

    def test_negative_control_predicate_detects_omitted_abstract( self, notifications_page ):
        """
        NEGATIVE CONTROL — proves the SHARED consume predicate goes RED on the bug's
        exact symptom: a running→done completion that OMITS the abstract. Drives the
        app's OWN completion handler (notificationsUI.insertJobMetadata) with a done
        payload lacking `abstract`, then runs the SAME predicate the real test uses.

        LIMIT (stated plainly): this proves the CLIENT detects an omitted abstract.
        It does NOT prove the real test's wait-for-promotion logic is sound — it
        injects metadata directly and bypasses the WebSocket running→done promotion
        the real test rides. The real test above owns that half; this owns detection.
        """
        page = notifications_page
        result = page.evaluate(
            "() => {"
            "  const ui = window.notificationsUI;"
            "  const card = document.createElement( 'div' );"
            "  card.className = 'job-card';"
            "  card.id = 'job-card-NEGCTRL';"
            "  card.innerHTML = '<div class=\"job-response\" style=\"display:none\"></div>"
            "<div class=\"job-abstract\" style=\"display:none\"></div>';"
            "  document.body.appendChild( card );"
            # Real completion handler, done payload WITHOUT abstract (the buggy shape).
            "  ui.insertJobMetadata( 'NEGCTRL', card, { response_text: 'Dry run complete.' } );"
            "  const resp = card.querySelector( '.job-response' );"
            "  const handlerRan = !!resp && resp.style.display !== 'none'"
            "                     && ( resp.textContent || '' ).trim().length > 0;"
            "  const verdict = ( " + _ABSTRACT_PREDICATE_JS + " )( card );"
            "  return { handlerRan: handlerRan, verdict: verdict };"
            "}"
        )
        # The handler DID run (response rendered) — so an empty abstract is because it
        # was OMITTED, not because insertJobMetadata no-op'd or the name drifted.
        assert result[ "handlerRan" ], \
            "insertJobMetadata did not run — negative control proves nothing (check the handler name)"
        v = result[ "verdict" ]
        assert v[ "ok" ] is False, "predicate should be RED when the abstract is omitted"
        assert not v[ "abstractText" ], "abstract should be empty when omitted"
        assert not v[ "playHref" ], "Play Here should be absent when abstract omitted"
