"""
Integration wrapper — the Lane-2 voice-driven podcast E2E, driven against a live server.

WHY THIS FILE EXISTS (row c076245f). `POST /api/test-suite/submit` only launches
REGISTERED pytest suites; it cannot invoke a standalone script. The Lane-2 harness
(`src/rnd/v0.2.0/2026.08.04-lane2-e2e-tiffany-harness.py`) is a standalone script, so
until now the one instrument for the voice-driven podcast path could ONLY be hand-run
against a live :7999. That routed around the venue rubric every single time.

It should never have been a :7999 run. It fails all three :7999 criteria at once — it
mutates persistent state, it enqueues a real job, and it takes ~11 minutes for real
audio generation. Hand-running it on the shared dev box on 2026-08-13 left a real
`pg-` job orphaned there. It completed, but that was luck, not design.

This thin `@pytest.mark.integration` wrapper is the sanctioned bridge, mirroring
`test_v2_eval_live.py`: it lets the harness be SCHEDULED on :8000 through the normal
endpoint like every other :8000-bucket suite.

WHAT IT IS, AND IS NOT. This runs the harness's own acceptance sequence — push,
route to the podcast generator, resolve the vague description to the seeded document,
job to done, and verify the finished artifact names the planted facts. It asserts
CONTENT, not filename, which is the whole point of the seed. It is NOT a unit test of
any component and it does not stand in for the podcast unit tiers.

VENUE: :8000 SCHEDULED, 10 AM - 1 PM EDT, via `POST /api/test-suite/submit`
ONLY. It spends real inference and needs a live server.

🔴 NOT post-midnight. This header used to say "post-midnight off-peak"; the host is
powered off overnight and usually still down past 8:52 AM, so a job placed there does
not run late, it does not run until the next boot. CLAUDE.md § Off-peak scheduling rule
has overturned that window twice (2026-08-17, 2026-08-20) and is the source of truth —
re-derive with `last -x reboot | head -20` rather than trusting any copy of it. Never :7999, never curl,
never side-doored.

LIVE PRECONDITIONS (the run fails by construction without them):
  1. LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD set — the harness logs itself
     in and seeds the document into that user's own corpus.
  2. `websockets` importable in the running interpreter — the harness auto-answers
     every interactive ask over a live socket, which is exactly what the test-user
     account otherwise lacks.
Both are checked below and SKIP rather than fail, because a missing credential is a
harness-environment fact, not a product defect. A skip is visible in the report; a
false red would not be honest.

Design + acceptance stages: the harness docstring, and row 68198c9f.
"""

import os
import sys

import pytest

# The harness lives under src/rnd/v0.2.0, which is not on the default test path.
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _HARNESS_DIR = os.path.join( _LUPIN_ROOT, "src", "rnd", "v0.2.0" )
    if _HARNESS_DIR not in sys.path:
        sys.path.insert( 0, _HARNESS_DIR )

# The filename starts with a date and contains dots, so it is not a legal module
# name for a plain `import`. Load it by path instead.
import importlib.util                                                    # noqa: E402

_HARNESS_PATH = (
    os.path.join( _LUPIN_ROOT, "src", "rnd", "v0.2.0",
                  "2026.08.04-lane2-e2e-tiffany-harness.py" )
    if _LUPIN_ROOT else None
)


def _load_harness():
    """Import the date-named harness by path. Returns the module, or None if absent."""
    if not _HARNESS_PATH or not os.path.exists( _HARNESS_PATH ):
        return None
    spec = importlib.util.spec_from_file_location( "lane2_e2e_harness", _HARNESS_PATH )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


# Per feedback_tests_parameterize_base_url — env var with the :8000 default.
BASE_URL  = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD and _LUPIN_ROOT ),
    reason = "Requires LUPIN_ROOT + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/_PASSWORD",
)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.timeout( 1500 )
def test_lane2_voice_driven_podcast_e2e():
    """
    Drive the vague-request podcast path end to end on the configured server.

    Requires:
        - a live server at BASE_URL with the podcast path enabled
        - test credentials (the harness logs in and seeds its own document)

    Ensures:
        - the harness's main() returns 0 — its own acceptance sequence held: push
          accepted, routed to the podcast generator, the vague description resolved
          to the seeded doc, the job reached done, and the artifact named at least
          two planted facts
        - the run targeted BASE_URL, not the harness's :7999 default. This is
          asserted rather than assumed: the default is what made the row a bug, and
          a wrapper that silently kept it would reintroduce the exact defect while
          looking like the fix.
    """
    harness = _load_harness()
    if harness is None:
        pytest.skip( f"Lane-2 harness not found at {_HARNESS_PATH}" )
    if harness.websockets is None:
        pytest.skip( "`websockets` not importable — the harness cannot auto-answer" )

    rc = harness.main( [ "--base-url", BASE_URL, "--no-mode" ] )

    assert harness.BASE_HTTP == BASE_URL.rstrip( "/" ), (
        f"harness ran against {harness.BASE_HTTP!r}, not the configured {BASE_URL!r} — "
        f"the hardcoded-:7999 defect (row c076245f) is back"
    )
    assert f"{harness.WS_HOST}:{harness.WS_PORT}" in BASE_URL, (
        f"websocket target {harness.WS_HOST}:{harness.WS_PORT} does not match "
        f"{BASE_URL} — HTTP and socket are pointed at different servers"
    )
    # The harness returns three codes, and the difference is the whole point of
    # row 1cd30181: 0 = every stage observed and green, 1 = the harness watched the
    # product do the wrong thing, 2 = the harness could not tell.
    #
    # Both 1 and 2 fail this test, because a gate that cannot tell must never go
    # green. They are reported differently on purpose. Before the fix, a run whose
    # job finished a few seconds after the poll cutoff came back as a red that read
    # like a broken podcast chain; whoever picked it up would go looking for a
    # product defect that was not there.
    if rc == 2:
        pytest.fail(
            "Lane-2 podcast E2E is INCONCLUSIVE (exit 2) — the harness could not "
            "observe some stages, so this is an INSTRUMENT result and not evidence "
            "of a product defect. Check the [observe] lines in the captured output: "
            "the usual causes are the run outrunning LANE2_TIMEOUT_S (the script-review "
            "gate fails open after 600s, so a run nobody answers lands near 733s), the "
            "auto-answer websocket dying, or the queue API not answering. Do not open a "
            "product bug from this result."
        )
    assert rc == 0, (
        f"Lane-2 podcast E2E FAILED with exit code {rc} — the harness observed the "
        f"product doing the wrong thing. The stage table above names which stage; "
        f"stages marked INCONCLUSIVE are not part of this verdict."
    )
