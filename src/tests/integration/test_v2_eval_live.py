"""
Integration wrapper — the CJ Flow v2 EVAL (unit F) driven against the live server.

WHY THIS FILE EXISTS. `POST /api/test-suite/submit` only runs REGISTERED pytest suites
(`test_types=integration|e2e`); it cannot invoke a standalone script. `v2_eval.py` is a
standalone two-pass harness, so this thin `@pytest.mark.integration` wrapper is the
sanctioned bridge that lets the harness be SCHEDULED on :8000 via that endpoint. It
calls `v2_eval.main()` against the running server and asserts the run produced a real,
integrity-checked report — never a silent-empty pass.

WHAT IT IS, AND IS NOT. This runs the harness's SINGLE (v2) arm: cold pass then warm
pass over the corpus, measuring v2's own cache-hit rate and latency distribution. It is
NOT the §1 go/no-go table — there is no v1 baseline here, so it produces no
INVEST/STOP/SPLIT verdict. The report itself prints that disclaimer at the top
(v2_eval.NOT_GONOGO_BANNER). The paired v1-vs-v2 verdict instrument is a separate build.

VENUE: :8000 SCHEDULED, post-midnight off-peak, via `POST /api/test-suite/submit` ONLY —
it spends real inference and needs the live server (Lupin venue rules; cascade R-D5).
Never :7999, never curl, never side-doored. On :7999 (or any server with the v2 flow
gate off) the harness's own integrity guard fails the run loudly, which is correct.

LIVE PRECONDITIONS (must hold on the target server or the run fails by construction):
  1. `v2 flow enabled = True` in the target's INI block — else /api/v2/ask returns 503,
     every request is a non-200, and the integrity guard (http-all-ok) raises. The
     [Lupin: Testing] block does NOT set this today; it must be enabled for :8000.
  2. `v2 trace dir` set — else no authoritative JSONL trace is written and the guard's
     trace-parity property has nothing to check against, so it raises.
  3. LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD set (the harness logs in itself).

Design: src/rnd/v0.2.0/2026.08.14-cj-flow-v2-phases-2-3-and-evaluation.md (§1, §7, §9);
scope split: src/rnd/v0.2.0/2026.08.14-krishna-unit-f-wiring-scope.md.
"""

import os
import sys

import pytest

# The harness lives under src/scripts, which is not on the default test path.
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SCRIPTS = os.path.join( _LUPIN_ROOT, "src", "scripts" )
    if _SCRIPTS not in sys.path:
        sys.path.insert( 0, _SCRIPTS )

import v2_eval as ve   # noqa: E402


# Per feedback_tests_parameterize_base_url — env var with the :8000 default.
BASE_URL  = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

# Utterances-per-command cap. Small default keeps an ad-hoc run cheap; the scheduled
# submission tunes it up via the LUPIN_TEST_ env allowlist (e.g. LUPIN_TEST_V2_EVAL_LIMIT=60
# for the pre-declared n=60/command sample). None = full corpus.
_LIMIT_RAW = os.environ.get( "LUPIN_TEST_V2_EVAL_LIMIT", "20" )
_LIMIT     = None if _LIMIT_RAW.strip().lower() in ( "", "none", "all" ) else int( _LIMIT_RAW )


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.mark.integration
def test_v2_eval_two_pass_live():
    """
    Run the two-pass v2-only eval against the live server and prove it is real.

    Requires:
        - the live server answers POST /api/v2/ask per the §8 contract (v2 flow enabled).
        - test credentials are set (the harness logs in and obtains its own bearer).

    Ensures:
        - main() completes WITHOUT raising EvalIntegrityError — i.e. the run's integrity
          properties (http-all-ok, trace-parity, router-liveness) all held. If it raises,
          this test fails, which is the whole point of the guard.
        - the report + records artifacts were written under io/v2-flow/eval-<ts>/.
        - the run was NOT silent-empty: the cold pass has n_ok > 0 and at least one
          first-useful latency was measured — an empty corpus is never the pass signal.
    """
    argv = [
        "--corpus",   "simple",
        "--passes",   "2",
        "--base-url", BASE_URL,
    ]
    if _LIMIT is not None:
        argv += [ "--limit", str( _LIMIT ) ]

    # main() builds its own authenticated HttpAskClient from the LUPIN_TEST_* creds and
    # raises EvalIntegrityError if the run lies. A clean return is the pass.
    result = ve.main( argv=argv )

    assert os.path.exists( result[ "paths" ][ "report" ] ),  "report.md was not written"
    assert os.path.exists( result[ "paths" ][ "records" ] ), "records.jsonl was not written"

    cold = result[ "cold" ]
    warm = result[ "warm" ]
    assert cold[ "n_ok" ] > 0, "cold pass returned zero 200s — silent-empty is never a pass"
    assert cold[ "p50_first_useful_ms" ] is not None, "no first-useful latency measured on the cold pass"

    # The warm pass is what the two-pass design exists to measure; its cache-hit rate is
    # a real number (possibly 0.0 on a cold-started isolated table), never None once there
    # is at least one 200.
    assert warm[ "n_ok" ] > 0, "warm pass returned zero 200s"
    assert warm[ "cache_hit_rate" ] is not None, "warm cache-hit rate is None despite 200s"

    # The report carries the v2-only disclaimer so its numbers are never read as go/no-go.
    with open( result[ "paths" ][ "report" ] ) as handle:
        report = handle.read()
    assert "NOT the go/no-go decision table" in report
