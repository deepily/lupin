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
      - The real test below drives the app's OWN promotion handler
        (handleJobStateTransition) with synthesized queued→running→completed
        events — NO live job — and asserts the done card renders the abstract.
      - `test_negative_control_predicate_detects_omitted_abstract` proves the
        SAME predicate goes RED when the done event omits the abstract — the exact
        symptom the server bug produced — with no server on buggy code and no reload.

    REDESIGN (2026-08-03): the real test no longer submits a live dry-run job.
    A real submit cannot complete inside a monopolizing test-suite run (Gate B
    defers the foreign job), and is separately fragile because an approval gate
    can be re-aimed at an offline operator. Both say a consume-seam test must not
    depend on a live job completing — so it drives the client promotion path
    directly. This proves the CLIENT renders what the server SAYS it sends; the
    emit half (that the server sends it) is owned by the podcast_generator unit
    tests, not this file.

    Venue: :8000 (scheduled) per the E2E-UI venue convention. It no longer needs
    server monopoly or the consumer — it drives client JS only, mutates no queue
    state, and is immune to the monopolize-defer that killed the first version.
    """

    def test_dry_run_done_card_renders_abstract_no_reload( self, notifications_page ):
        """
        The CONSUME seam, driven through the app's REAL WebSocket promotion
        handler (handleJobStateTransition) with NO live job.

        WHY NOT A REAL SUBMIT (this is the redesign — 2026-08-03). The first
        version submitted a real dry-run podcast and waited for the queue to
        promote it. That cannot work here for TWO independent reasons, both
        proven the same night:
          1. A test-suite job runs monopolize=True; Gate B defers any FOREIGN
             submit's todo→running promotion while the monopolizer holds, so the
             submitted job sits 'pending' and the wait times out (never the
             consume bug — the job never runs).
          2. Even outside a monopolizer, an approval gate can be re-aimed at an
             offline operator (503, fail-closed), so a real job is not a reliable
             way to reach 'done' in an unattended run.
        Both say the same thing: a CONSUME-seam test must NOT depend on a live
        job completing. So we drive the client's own promotion path directly.

        WHAT THIS PROVES: on a running→completed transition whose metadata carries
        an abstract, the CLIENT renders that abstract (with a clickable Play Here)
        into the done card via renderJobCard, WITHOUT a page reload.

        WHAT THIS DOES NOT PROVE (stated so no future reader conflates the ends):
        that the SERVER actually SENDS that abstract in the done-transition
        metadata. Synthesized envelopes prove the client renders the shape the
        server claims to send — not that the server sends it. The emit half is
        owned by the podcast_generator unit tests (job.py 100%, bug 9b481811).
        Only the two together close the seam.

        FAITHFUL PAYLOAD: the abstract driven in is the REAL one captured from
        _execute_dry_run (not hand-built), so if the emit shape drifts this test
        drifts with it.

        RED-BEFORE-GREEN: the shared predicate is validated by
        test_negative_control_predicate_detects_omitted_abstract, which drives a
        done payload OMITTING the abstract through the client and asserts the SAME
        predicate goes RED on the bug's exact symptom. A predicate that has been
        red on that symptom is what makes this green trustworthy.
        """
        page     = notifications_page
        abstract = _capture_dry_run_abstract()
        job_id   = "pg-e2e-consume-seam"        # synthetic — there is no real job

        # 1) queued→running: the app creates the card in the run container. This is
        #    the pre-done state — a stale done card cannot false-pass. Driving the
        #    REAL handler (not a hand-built card) exercises the app's own path.
        page.evaluate(
            """( jobId ) => window.notificationsUI.handleJobStateTransition( {
                job_id     : jobId,
                from_state : 'queued',
                to_state   : 'running',
                metadata   : { question_text: 'Dry-run consume seam', agent_type: 'podcast', status: 'running' }
            } )""",
            job_id,
        )
        predone = page.evaluate(
            """( jobId ) => {
                const c = document.getElementById( 'job-card-' + jobId );
                if ( !c ) return 'absent';
                const r = c.querySelector( '.job-response' );
                const done = !!r && r.style.display !== 'none' && ( r.textContent || '' ).trim().length > 0;
                return done ? 'already-done' : 'pending';
            }""",
            job_id,
        )
        assert predone == "pending", \
            f"card not in a pre-done state after the running transition ({predone}) — running→done not exercised"

        # 2) running→completed WITH the real abstract. handleJobStateTransition
        #    re-renders the card into the done container via renderJobCard. NO RELOAD.
        page.evaluate(
            """( args ) => window.notificationsUI.handleJobStateTransition( {
                job_id     : args.jobId,
                from_state : 'running',
                to_state   : 'completed',
                metadata   : {
                    question_text : 'Dry-run consume seam',
                    agent_type    : 'podcast',
                    status        : 'completed',
                    response_text : 'Dry run complete.',
                    abstract      : args.abstract
                }
            } )""",
            { "jobId": job_id, "abstract": abstract },
        )

        # 3) Card promoted to DONE without a reload. Assert the CONSUME seam via the
        #    SHARED predicate. With the abstract omitted (negative control) the same
        #    predicate goes RED — so a green here is the abstract actually rendering.
        state = _consume_predicate_by_job_id( page, job_id )
        assert state[ "abstractText" ], "abstract empty on promoted done card (no reload)"
        assert state[ "playHref" ] and "embed=1" in state[ "playHref" ], \
            "Play Here absent on promoted done card (no reload)"
        assert state[ "playVisible" ], "Play Here present but not clickable/visible"
        assert state[ "ok" ], "shared consume predicate failed on the promoted done card"

    def test_promotion_path_negative_control_omitted_abstract_is_red( self, notifications_page ):
        """
        PATH-MATCHED negative control — the red that makes the positive test's green
        trustworthy on the SAME render path it uses.

        `test_negative_control_predicate_detects_omitted_abstract` drives the
        predicate through insertJobMetadata; the positive test above renders via
        renderJobCard (handleJobStateTransition). A predicate proven red on one
        render path does not prove it red on the other. This drives the EXACT
        positive path — queued→running→completed with the abstract OMITTED — and
        asserts (a) the promotion ran (card reached done, .job-response shown) and
        (b) the shared predicate goes RED. Without this, the positive green could
        hide a renderJobCard that shows .job-abstract unconditionally.
        """
        page   = notifications_page
        job_id = "pg-e2e-consume-seam-negctrl"

        page.evaluate(
            """( jobId ) => window.notificationsUI.handleJobStateTransition( {
                job_id: jobId, from_state: 'queued', to_state: 'running',
                metadata: { question_text: 'Neg ctrl', agent_type: 'podcast', status: 'running' }
            } )""",
            job_id,
        )
        # Done transition with response_text but NO abstract — the bug's exact shape.
        result = page.evaluate(
            """( jobId ) => {
                window.notificationsUI.handleJobStateTransition( {
                    job_id: jobId, from_state: 'running', to_state: 'completed',
                    metadata: { question_text: 'Neg ctrl', agent_type: 'podcast',
                                status: 'completed', response_text: 'Dry run complete.' }
                } );
                const card = document.getElementById( 'job-card-' + jobId );
                const resp = card && card.querySelector( '.job-response' );
                const handlerRan = !!resp && resp.style.display !== 'none'
                                   && ( resp.textContent || '' ).trim().length > 0;
                const verdict = ( """ + _ABSTRACT_PREDICATE_JS + """ )( card );
                return { handlerRan: handlerRan, verdict: verdict };
            }""",
            job_id,
        )
        # Promotion actually happened (so an empty abstract is because it was OMITTED,
        # not because the card never reached done or the handler no-op'd).
        assert result[ "handlerRan" ], \
            "done promotion did not render on the renderJobCard path — control proves nothing"
        v = result[ "verdict" ]
        assert v[ "ok" ] is False, "predicate should be RED when the abstract is omitted (renderJobCard path)"
        assert not v[ "abstractText" ], "abstract should be empty when omitted"
        assert not v[ "playHref" ], "Play Here should be absent when abstract omitted"

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
