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

import datetime
import json
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


def _require_model_servers_live( config_mgr ):
    """
    Refuse the paired run unless EVERY configured vLLM endpoint answers.

    WHY IT IS A PRECONDITION AND NOT A RUNTIME ERROR. Both arms call the model server for
    hours. On 2026-08-17 the router at :3000 went down while :3001 stayed up, so the box
    read as alive to any check that probed one port, and the outage surfaced only when a
    THREE-HOUR job died on it with an API error three layers from the cause (row b9604f8c).

    Ensures:
        - raises ModelServerUnavailable NAMING the endpoint that did not answer, and what
          it did, before any measurement is taken
        - is a module-level seam so the bridge-reachability tests can neutralise it the
          same way they neutralise the other preconditions, without stubbing a socket
    """
    from cosa.utils.model_server_liveness import require_live
    return require_live( config_mgr=config_mgr, context="the paired go/no-go run" )


def _resolve_v1_paired_store() -> str:
    """
    The v1 arm's fully-qualified `database.table` snapshot store — its DEDICATED measurement
    database (lupin_db_v1baseline, design §2a/§4) and the snapshot table it writes. Resolved
    from the v1 arm's own constants so it tracks a rename, and kept distinct from the v2 store
    by construction (different database) so the VALIDITY check has two real targets to compare.
    """
    import v1_eval_arm
    return guard.fully_qualified( "lupin_db_v1baseline", v1_eval_arm.SNAPSHOT_TABLE )


def _open_v2_arm_connection():   # pragma: no cover - live DB boundary (real engine connect)
    """
    Open the v2 arm's LIVE DB connection for the per-arm clean-step.

    The v2 arm writes its own measurement database (lupin_db_test under LUPIN_ENV=testing,
    design decision B); this opens a real connection to it. Live boundary — the :7999
    reachability test injects a fake connection so no real TRUNCATE fires, and the real
    connect happens only in the scheduled :8000 run.
    """
    from sqlalchemy import create_engine
    from cosa.rest.db.database import get_database_url
    return create_engine( get_database_url() ).connect()


def _clean_v2_arm_store( config_mgr ) -> str:
    """
    Wire clean_v2_snapshot_store (the per-arm clean primitive) into the paired bridge.

    Opens the v2 arm's live connection (_open_v2_arm_connection, the injected boundary) and hands
    it + config_mgr to v2_eval.clean_v2_snapshot_store, which runs the CONFIG cross-check and the
    measurement-db assertion BEFORE any TRUNCATE (so a wrong config or wrong db never truncates).

    This is the caller the primitive lacked — bug 080821da: clean_v2_snapshot_store was unit-proven
    but nothing invoked it (the orphan defect, the exact shape of row d8d019f6 recurring inside the
    fix for it). The :7999 reachability test spies the REAL fn so the wiring is proven WITHOUT a
    live TRUNCATE; the scheduled :8000 run performs the real one (Tiberius's check).

    Ensures:
        - invokes v2_eval.clean_v2_snapshot_store( connection, config_mgr ) via the module attribute
          (late-bound, so a test spy on v2_eval.clean_v2_snapshot_store intercepts it) and returns
          the TRUNCATEd table name.
        - always closes the connection, even if the clean-step raises.
    """
    import v2_eval
    connection = _open_v2_arm_connection()
    try:
        return v2_eval.clean_v2_snapshot_store( connection, config_mgr )
    finally:
        connection.close()


def _run_v1_arm( *, corpus, seed, n_per_command, base_url ):   # pragma: no cover - live boundary (real push to :7997 + WS collect + inference)
    """
    Run the v1 baseline arm against the pinned :7997 server and return its {metrics, provenance}
    artifact (headline = the WARM pass — the same pass run_v1_baseline reports).

    Live boundary: the real push, WS collect, and inference happen ONLY in the scheduled :8000
    run; the :7999 reachability test injects a canned artifact so no live work fires here. Assembles
    the seams the RUN wrapper is documented to supply — a WsJobEventListener (make_ws_recv_events)
    feeding _default_collect_fn, _default_push_fn, and the class→command map read from the PINNED
    worktree registry (load_v1_class_to_command, resolved through LUPIN_ROOT). run_v1_baseline itself
    proves the server is the pin (sha readback) before it spends.
    """
    import v1_eval_arm
    email                        = os.environ[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" ]
    token                        = f"mock_token_email_{email}"
    websocket_id                 = "v1-eval-listener"
    class_to_command, _ambiguous = v1_eval_arm.load_v1_class_to_command()
    listener, ws_recv_events     = v1_eval_arm.make_ws_recv_events( base_url, token, websocket_id )
    try:
        result = v1_eval_arm.run_v1_baseline(
            corpus=corpus, seed=seed, n_per_command=n_per_command, base_url=base_url,
            push_fn=v1_eval_arm._default_push_fn( base_url, websocket_id, token ),
            collect_fn=v1_eval_arm._default_collect_fn( ws_recv_events ),
            class_to_command=class_to_command,
            # assert_cold=False — RULED by Tiberius 2026-08-17 (row d8d019f6). The F3 cold-start guard
            # demands cache_hit_rate==0, but the snapshot manager's SIMILARITY cache self-warms within
            # the cold pass (deterministic 0.0126 over 300 UNIQUE utterances, IDENTICAL across a full
            # :7997 restart — so it is intra-pass, not stale state). The paired median-Δ is computed
            # WARM-vs-WARM over shared utterances (the gate never reads the cold pass), and the two
            # stores are ISOLATED (v1→lupin_db_v1baseline, v2→lupin_db_test) so no cross-arm warming.
            # Clean-start is still guarded by assert_paired_isolation (rowcount==0 at START); F3 only
            # caught the self-warming false positive. Disabling it forgoes a clean cold-start SECONDARY
            # number, never the gated warm-Δ.
            assert_cold=False,
        )
    finally:
        listener.stop()
    return { "metrics": result[ "warm" ], "provenance": result[ "provenance" ] }


def _run_v2_arm( *, corpus, seed, n_per_command, base_url ):   # pragma: no cover - live boundary (real two-pass inference + serialize)
    """
    Run the v2 arm (two-pass) against `base_url` and return its {metrics, provenance} artifact
    (headline = the WARM pass).

    Live boundary — real inference happens ONLY in the scheduled :8000 run; the :7999 reachability
    test injects a canned artifact. Delegates to v2_eval.main, which self-assembles the HttpAskClient
    from LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* and stamps the v2 provenance over the SAME (corpus, seed,
    n_per_command) the v1 arm uses — so the two arms' sample_signatures MATCH by construction and the
    paired provenance check binds them.
    """
    import v2_eval
    result = v2_eval.main( argv=[
        "--corpus", corpus, "--seed", str( seed ), "--n-per-command", str( n_per_command ),
        "--base-url", base_url, "--passes", "2",
        # --allow-warm-cold: SAME ruling as the v1 arm's assert_cold=False (Tiberius, row d8d019f6).
        # The similarity cache self-warms the cold pass; the Δ is warm-vs-warm and never reads cold;
        # stores are isolated so no cross-arm warming; VALIDITY still guards clean-start. Keeps the arms
        # SYMMETRIC — both skip the cold-start guard, so neither arm's cold-pass hit rate enters anything.
        "--allow-warm-cold",
    ] )
    return { "metrics": result[ "warm" ], "provenance": result[ "provenance" ] }


def _dump_paired_artifacts( v1_artifact, v2_artifact ):   # pragma: no cover - best-effort disk insurance
    """
    Persist BOTH arm artifacts to disk BEFORE the verdict step (row d8d019f6).

    The lesson from ts-217961e6: a KeyError in the verdict step destroyed ~2.5h of recoverable v1
    data (the v1 arm returns only in-memory; only the v2 arm self-persisted). Writing both here makes
    the median-Δ recomputable offline via `paired_eval.build_paired_verdict(v1, v2)` — so a downstream
    bug costs seconds, not hours. Best-effort: never let a dump failure mask the real run outcome.

    Ensures:
        - writes {v1,v2}-arm-artifact.json under LUPIN_PAIRED_ARTIFACT_DIR when set, else
          io/v2-flow/paired-run-latest/ (overwrite = always the newest).
        - stamps each file with written_at + written_by, so a reader can tell a LIVE run's
          artifact from one a test wrote. See the warning below for why that is not optional.
        - swallows any I/O error (the run's verdict is the product; this is only insurance).

    ⚠️ THIS FUNCTION WRITES A DIRECTORY PEOPLE TREAT AS RESULTS. It runs BEFORE the provenance
    assertion (that is the whole point — a downstream error must not destroy recoverable data),
    which means ANY caller that reaches this line publishes to paired-run-latest, including a
    unit test that patched both arms with canned fixtures. That is not hypothetical: on
    2026-08-17 this directory held a fake v1 n=3 / v2 n=2 pair written by
    test_v2_paired_bridge_reachability, and a previous session nearly read it as a real result.
    Tests MUST point LUPIN_PAIRED_ARTIFACT_DIR at a tmp path; the stamp below is the backstop
    for when someone forgets.
    """
    try:
        import cosa.utils.util as cu
        out_dir = os.environ.get( "LUPIN_PAIRED_ARTIFACT_DIR" ) or os.path.join(
            cu.get_project_root(), "io", "v2-flow", "paired-run-latest" )
        os.makedirs( out_dir, exist_ok=True )
        # A run id proves provenance of the FILE, the way git_sha proves provenance of the numbers
        # (row c9b43538). "unknown-caller" is the tell that nothing identified itself as a real run.
        written_by = os.environ.get( "LUPIN_TEST_SUITE_JOB_ID" ) or "unknown-caller"
        for name, art in ( ( "v1", v1_artifact ), ( "v2", v2_artifact ) ):
            stamped = dict( art )
            stamped[ "written_at" ] = datetime.datetime.now().isoformat()
            stamped[ "written_by" ] = written_by
            with open( os.path.join( out_dir, f"{name}-arm-artifact.json" ), "w" ) as fh:
                json.dump( stamped, fh, indent=2, default=str )
    except Exception as e:                                 # insurance must never mask the run outcome
        print( f"[paired] artifact-dump insurance failed (non-fatal): {e}" )


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

    # Precondition 2b — DEPENDENCY: every configured vLLM endpoint must answer (row b9604f8c).
    _require_model_servers_live( config_mgr )

    # Per-arm clean-step (design §4, decision B) — TRUNCATE the v2 arm's isolated snapshot store
    # so its cold pass starts genuinely cold, BEFORE the VALIDITY clean-start check below reads the
    # live rowcounts (truncate MAKES cold, exactly as v1_eval_arm.truncate_snapshots does; placing
    # it here is the only position where the clean-step is genuinely REACHABLE — VALIDITY would
    # otherwise refuse on a dirty store before clean ever ran). This is the caller
    # clean_v2_snapshot_store lacked — bug 080821da (the orphan defect). The live DB connection is
    # the injected boundary: a real TRUNCATE fires ONLY in the scheduled :8000 run; the :7999
    # reachability test spies the real fn so no live TRUNCATE happens here.
    _clean_v2_arm_store( config_mgr )

    # Precondition 3 — VALIDITY: the two arms must write DISTINCT, CLEAN stores (design §4).
    # Queries each store's LIVE rowcount and calls the distinct-and-clean check; count_store_rows
    # targets the exact db.table each string names. Reached only once preconditions 1+2 pass.
    v1_store = _resolve_v1_paired_store()
    guard.assert_paired_isolation( v1_store, v2_store, rowcount_fn=guard.count_store_rows )

    # ---- a–d: run BOTH arms and produce the PROVENANCE-GATED paired verdict (row d8d019f6) ----
    # This is the caller the paired verdict lacked: build_paired_verdict was wired into nothing,
    # so two arms that measured DIFFERENT samples would have passed a shape-only gate. The arm runs
    # are injected live boundaries — mocked on :7999, real only in the scheduled :8000 run.
    import paired_eval

    # a. ONE sampling spec drives BOTH arms: identical (corpus, seed, n_per_command) → identical
    #    seeded stratified sample → identical sample_signature, which paired_provenance_check BINDS
    #    in step d (design §6). The corpus is the same one precondition 0 proved leak-free.
    seed          = int( os.environ.get( "LUPIN_PAIRED_SEED", "1024" ) )
    n_per_command = int( os.environ.get( "LUPIN_PAIRED_N", "60" ) )
    v2_base_url   = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

    # b + c. Each arm → {metrics, provenance} (headline = the WARM pass). Live boundaries.
    v1_artifact = _run_v1_arm( corpus=corpus_name, seed=seed, n_per_command=n_per_command,
                               base_url=os.environ[ "LUPIN_V1_ARM_BASE_URL" ] )
    v2_artifact = _run_v2_arm( corpus=corpus_name, seed=seed, n_per_command=n_per_command,
                               base_url=v2_base_url )

    # INSURANCE (row d8d019f6): persist BOTH arm artifacts to disk BEFORE any downstream assertion,
    # so a bug past this point never costs another ~2.5h re-run — the median-Δ can be recomputed
    # offline via `paired_eval.build_paired_verdict(<v1>, <v2>)`. The v2 arm already writes its own
    # artifact; the v1 arm returns only in-memory, so its data was previously lost on any late failure.
    _dump_paired_artifacts( v1_artifact, v2_artifact )

    # d. The provenance-gated verdict. build_paired_verdict runs paired_provenance_check FIRST —
    #    binding both arms to the SAME corpus/seed/sample by SIGNATURE, not a shape-only compare —
    #    and only then fires the median-Δ gate. Both arms must have produced usable records.
    #    KEY ASYMMETRY (row d8d019f6): v1's compute_v1_metrics emits "ok_n", v2's compute_metrics
    #    emits "n_ok" — checking "n_ok" on BOTH KeyErrors on the v1 arm one line before the verdict
    #    (the canned unit artifact used n_ok for both arms, masking it). Use each arm's own key.
    assert v1_artifact[ "metrics" ][ "ok_n" ] > 0, "paired run: v1 arm produced 0 usable records"
    assert v2_artifact[ "metrics" ][ "n_ok" ] > 0, "paired run: v2 arm produced 0 usable records"
    verdict = paired_eval.build_paired_verdict( v1_artifact, v2_artifact )
    assert verdict[ "provenance_ok" ], (
        "paired run REFUSED — the two arms are not provenance-bound (they did not measure the same "
        f"sample): {verdict.get( 'reason' )}"
    )
    rendered = paired_eval.render_paired_verdict( verdict )
    assert rendered.strip(), "paired run: verdict rendered empty"
    return verdict
