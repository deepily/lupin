"""Integration bridge — the CJ Flow v2 PAIRED (v1-vs-v2) go/no-go run (design step 6).

WHAT THIS IS. The sanctioned, schedulable entry point for the paired median-Δ
verdict. It runs both arms over the IDENTICAL seeded utterance list (design §6,
pairing preserved), serializes each arm's {metrics, provenance} artifact, and hands
the two to `paired_eval.main` — which owns ALL gate logic (this bridge re-implements
none of it, per Mr. Radio's 2026-08-16 ruling).

WHY IT IS GUARDED AND REFUSES TODAY. Two preconditions are proven-necessary and are
NOT met on the shared checkout as of 2026-08-16, so this bridge REFUSES to run rather
than produce an invalid or store-polluting result:

  1. SNAPSHOT-TABLE ISOLATION (bug 080821da, the serious one). `v2 snapshot writeback
     enabled = True` and the ORM writes the shared `solution_snapshots` table — there
     is no isolated table wired. A paired run would (a) write the live shared store
     (no-test-touches-a-live-dev-data-store) and (b) warm v2's cold pass from v1's
     writes (design §4). `eval_isolation_guard.require_isolated_snapshot_table` enforces
     this against the app's OWN runtime write target, not a hardcoded name.

  2. V1-ARM LIVE SEAM + WORKTREE SERVER (design §9 step 1, still open). `run_v1_baseline`
     needs a `ws_recv_events(job_id)` source to capture `job_state_transition` events;
     only the consumer stub exists (`v1_eval_arm._default_collect_fn`, marked live-WS-
     boundary). And the v1 arm must run against the PINNED worktree at b0735467 with
     LUPIN_ROOT exported to it (design §2a) — infra that must be stood up.

So today, selecting this test refuses at precondition 1 with the guard's exact reason.
That refusal is the point: an unproven guard is the same as no guard (the guard itself
is proven in src/tests/unit/test_eval_isolation_guard.py, 6/6, 100%).

VENUE + SELECTION. `@pytest.mark.paired_eval_live` (deselected from every default run by
pytest.ini addopts `-m "... and not paired_eval_live"`) + `@pytest.mark.integration`.
The scheduled paired run selects it explicitly: `POST /api/test-suite/submit` with
pytest_args `-m paired_eval_live`, :8000, post-midnight off-peak. Never :7999, never
curl, never side-doored (same pattern as test_v2_embedding_cost_live.py).

Precondition 3 (VALIDITY, now wired) — the two arms must write DISTINCT, CLEAN stores
(design §4): `eval_isolation_guard.assert_paired_isolation` queries each store's live
rowcount (`count_store_rows`, which targets the exact db.table the string names) and calls
`require_arms_distinct_and_clean`. It runs after preconditions 1+2 pass; the pure
distinct-and-clean decision + its composing caller are unit-proven in
test_eval_isolation_guard.py with a fake counter (happy / dirty / shared).

REMAINING WIRING once preconditions 1+2+3 land (kept as a checklist so nobody mistakes
the refusing scaffold for a finished run):
  a. one seed → stratified_sample once → drive BOTH arms with the SAME sampled list.
  b. v1 arm: run_v1_baseline( push_fn, collect_fn(ws_recv_events), class_to_command ) →
     serialize {metrics, provenance} to io/v2-flow/paired-<ts>/v1-artifact.json.
  c. v2 arm: v2_eval two-pass over the same sample → serialize {metrics, provenance}.
  d. paired_eval.main( --v1-artifact, --v2-artifact ) → verdict; assert both arms
     n_ok > 0, the provenance check PASSED (same corpus/seed/signature), and the
     verdict block rendered. Gate logic stays inside paired_eval.

Design: src/rnd/v0.2.0/2026.08.14-v2-paired-go-no-go-harness-design.md (§4, §6, §9).
"""

import os
import sys

import pytest

# The harness + guard live under src/scripts, not on the default test path.
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SCRIPTS = os.path.join( _LUPIN_ROOT, "src", "scripts" )
    if _SCRIPTS not in sys.path:
        sys.path.insert( 0, _SCRIPTS )

import eval_isolation_guard as guard   # noqa: E402


BASE_URL  = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


class PairedPreconditionMissing( RuntimeError ):
    """Raised to REFUSE the paired run when a live precondition (v1 seam / worktree) is absent."""


def _require_v1_live_seam_and_worktree():
    """
    Refuse unless the pinned-worktree v1 server is configured. The WS-recv seam is SHIPPED.

    The live capture seam (`ws_recv_events`) now exists — WsJobEventListener /
    make_ws_recv_events in v1_eval_arm, tested against a real socket — so this guard no
    longer names it as missing (a precondition that keeps refusing after its condition is
    met is the next reader's wasted hour). What remains is the pinned-worktree server,
    which is stood up out of band (Mr. Radio owns it).

    Ensures:
        - imports the seam, so a REGRESSION that removed it fails loudly here rather than
          at run time.
        - raises PairedPreconditionMissing while LUPIN_V1_ARM_BASE_URL is unset — the
          pinned-b0735467 worktree server must be running with LUPIN_ROOT exported to it,
          or the v1 arm would measure the dirty main tree. The message states the seam is
          wired so no one re-builds it.
        - set-ness is NOT enough: after the var is present, PROVES the server is the
          pinned tree by reading its OWN sha (GET /api/code-identity) and asserting it
          equals the pin. Refuses — NAMING the sha it saw — when a wrong-tree (e.g. main)
          server answers, which satisfies the env var identically (row 275cb0b9 follow-up).
    """
    from v1_eval_arm import (                                  # noqa: E402
        V1_PIN_SHA, make_ws_recv_events,                       # noqa: F401 - import PROVES the seam is present
        read_running_server_sha, assert_measured_sha, EvalIntegrityError,
    )
    v1_base = os.environ.get( "LUPIN_V1_ARM_BASE_URL" )       # the pinned-worktree server, when stood up
    if not v1_base:
        raise PairedPreconditionMissing(
            f"v1-arm live WS-recv seam IS wired (make_ws_recv_events / WsJobEventListener, real-socket "
            f"tested) — the remaining gate is the pinned-worktree server: set LUPIN_V1_ARM_BASE_URL to a "
            f"v1 server at pin {V1_PIN_SHA} with LUPIN_ROOT exported to that worktree. Refusing the paired run."
        )

    # Set-ness proves a URL is configured, NOT that the server behind it is the right
    # tree: a main-tree server pointed at this var passes the check above identically.
    # PROVE the tree — ask the running server its OWN sha and assert it IS the pin, before
    # any measurement is recorded. On mismatch the refusal NAMES the sha it saw, so the
    # operator learns which tree answered instead of a bare "wrong server".
    observed_sha = read_running_server_sha( v1_base )
    try:
        assert_measured_sha( observed_sha )                  # raises EvalIntegrityError, quoting observed vs pin
    except EvalIntegrityError as e:
        raise PairedPreconditionMissing(
            f"LUPIN_V1_ARM_BASE_URL={v1_base} is set, but the server there reports sha "
            f"{observed_sha!r}, not the pinned v1 sha {V1_PIN_SHA!r} — it is NOT the b0735467 "
            f"worktree. Point the var at the pinned-worktree server. Refusing the paired run."
        ) from e


def _resolve_v1_paired_store() -> str:
    """
    The v1 arm's fully-qualified `database.table` snapshot store — its DEDICATED measurement
    database (lupin_db_v1baseline, design §2a/§4) and the snapshot table it writes. Resolved
    from the v1 arm's own constants so it tracks a rename, and kept distinct from the v2 store
    by construction (different database) so the VALIDITY check has two real targets to compare.
    """
    import v1_eval_arm
    return guard.fully_qualified( "lupin_db_v1baseline", v1_eval_arm.SNAPSHOT_TABLE )


@pytest.mark.paired_eval_live
@pytest.mark.integration
def test_v2_paired_go_no_go_live():
    """Run both arms on the identical sample and hand the artifacts to paired_eval's gate.

    Requires (enforced as loud refusals, not warnings):
        - an isolated v2 snapshot table wired to the app's real write target (bug 080821da).
        - the v1-arm live WS-recv seam + pinned-worktree server (design §9 step 1, §2a).

    Ensures:
        - refuses via IsolationNotConfigured / PairedPreconditionMissing when a precondition
          is absent (today's state), so a scheduled run can never write the shared store nor
          report a one-armed comparison as a verdict.
        - once preconditions hold: runs both arms on the identical seeded sample, serializes
          two {metrics, provenance} artifacts, and asserts paired_eval rendered a real,
          provenance-matched verdict (see the REMAINING WIRING checklist in the module docstring).
    """
    from cosa.config.configuration_manager import ConfigurationManager

    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    # Precondition 0 — CORPUS: the corpus must not route to an arg-extracting command whose
    # fallback_defaults leak (bug 8aa89f42) is unfixed at the pinned v1 sha b0735467. Runs FIRST,
    # BEFORE SAFETY, so it is ALWAYS reached — a guard behind a guard that refuses today never
    # runs. Corpus name from the run env (default the pure-routing 'simple'); load_corpus gives
    # the (utterance, command) pairs, and the command set is what the leak check keys on.
    from v2_eval import load_corpus
    corpus_name     = os.environ.get( "LUPIN_PAIRED_CORPUS", "simple" )
    corpus_commands = { command for _utterance, command in load_corpus( corpus_name ) }
    guard.require_leak_free_corpus( corpus_commands )

    # Precondition 1 — SAFETY: the v2 write destination must be a permitted non-live store.
    # Refuses TODAY (writeback on, empty allowlist), proving the guard fires at the integration
    # boundary too. The blessed fully-qualified destination is captured for precondition 3, so
    # the clean-start rowcount attests to the SAME store SAFETY approved (one identity).
    v2_store = guard.require_isolated_snapshot_table( config_mgr )

    # Precondition 2 — v1-arm live seam + pinned-worktree server. Refuses until step 1 lands.
    _require_v1_live_seam_and_worktree()

    # Precondition 3 — VALIDITY: the two arms must write DISTINCT, CLEAN stores (design §4).
    # Queries each store's LIVE rowcount and calls the distinct-and-clean check; count_store_rows
    # targets the exact db.table each string names. Reached only once preconditions 1+2 pass.
    v1_store = _resolve_v1_paired_store()
    guard.assert_paired_isolation( v1_store, v2_store, rowcount_fn=guard.count_store_rows )

    # REMAINING WIRING (a–d in the module docstring) runs only once all preconditions pass.
    # It is intentionally not stubbed as a fake pass: a paired verdict that never ran both
    # arms is exactly the failure this bridge exists to prevent.
    pytest.fail( "unreachable: a precondition guard must have refused before this line" )
