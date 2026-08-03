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

            # NO RELOAD from here. The card is created (todo), runs ~5s of dry-run
            # breadcrumbs, then promotes running→done over the SAME WebSocket. The
            # done promotion is the ONLY thing that fills .job-abstract
            # (notifications.js updateJobCardWithCompletion). If the done event
            # carries no abstract, .job-abstract stays empty and this times out.
            page.wait_for_function(
                """( jobId ) => {
                    const card = document.getElementById( 'job-card-' + jobId );
                    if ( !card ) return false;
                    const ab = card.querySelector( '.job-abstract' );
                    if ( !ab ) return false;
                    const txt = ( ab.textContent || '' ).trim();
                    const playHere = ab.querySelector( "a[href*='embed=1']" );
                    return txt.length > 0 && !!playHere;
                }""",
                arg=job_id,
                timeout=45000,
            )

            # Explicit assertions so a regression reads as the PREDICTED text, not a
            # bare wait-timeout.
            state = page.evaluate(
                """( jobId ) => {
                    const card = document.getElementById( 'job-card-' + jobId );
                    const ab   = card && card.querySelector( '.job-abstract' );
                    const a    = ab && ab.querySelector( "a[href*='embed=1']" );
                    return {
                        abstractText : ab ? ( ab.textContent || '' ).trim() : '',
                        playHref     : a ? a.getAttribute( 'href' ) : null,
                        playVisible  : !!( a && a.offsetParent !== null ),
                    };
                }""",
                job_id,
            )
            assert state[ "abstractText" ], "abstract empty on done card (no reload)"
            assert state[ "playHref" ] and "embed=1" in state[ "playHref" ], \
                "Play Here absent on done card (no reload)"
            assert state[ "playVisible" ], "Play Here present but not clickable/visible"
        finally:
            if os.path.exists( seed ):
                os.remove( seed )
