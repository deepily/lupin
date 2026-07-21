"""
Store-only owed-work cutover — REAL-DATA E2E (disagreement proof).

Design: src/rnd/v0.1.8/2026.06.17-store-owed-cutover-e2e-design.md
Task:   c38e3134 (Tiberius's lane)

The CENTRAL claim of the 2026-06-17 cutover is that the Stop-hook owed-work
oracle reads owed counts FROM the unified store (via real HTTP count_only),
NOT from transcript replay. Every prior "proof" mocked the seam. Here we
ENGINEER A DISAGREEMENT between the two candidate sources so a green result can
ONLY mean the RIGHT source was read:

    S1  store=N , transcript=0    , flag ON   -> oracle MUST report N   (store IS the source)
    S2  store=0 , transcript=M    , flag ON   -> oracle MUST report 0   (transcript replay DEAD)
    S4  store=150, transcript=0   , flag ON   -> oracle MUST report 150 (count_only true COUNT, not page-cap)
    S5  store=0 , transcript=M    , flag OFF  -> oracle MUST report M   (FALSIFIABLE control)
    S6a store=K(lupin)+J(plan), session=lupin, flag ON -> oracle MUST report K (project-scoped read)
    S6b store=K(lupin)+J(plan), session=plan , flag ON -> oracle MUST report J (non-lupin reads its OWN rows)

The seam (urllib -> HTTP -> router -> repo -> SQL COUNT(*) on lupin_db_test) is
100% real. Only session-IDENTITY glue + config (persona, resolve_project_name,
the flag, the server URL) and non-seam side-effects (poke-cap FS, emit, tmux,
notify, the two LOCAL owed signals) are controlled — never the seam.
"""

import uuid

import pytest

import lupin_cli.claude_code.hooks.stop as stop
from lupin_cli.claude_code.hooks.lib import heartbeat_events

from .conftest import seed_store_rows, write_transcript


HEARTBEAT_PHASE = "heartbeat_oracle"


def _noop( *args, **kwargs ):
    return None


@pytest.fixture
def drive_oracle( monkeypatch, e2e_server, tmp_path ):
    """
    Return a callable that drives the REAL stop._run_heartbeat owed seam and
    returns the oracle readout + the receipts produced by THIS drive.

    Controls (INPUTS to the seam, never the seam): the cutover flag, the owner
    persona, resolve_project_name, and the store URL (-> our ephemeral server).
    Neutralizes (non-seam side-effects): hold read, poke-cap FS, cap notify,
    emit_outcome, genuine-idle beacon, the poke announce + tmux inject, and the
    two LOCAL owed signals (so the verdict reflects ONLY the owed-items source).

    KEEPS REAL: _owed_count_from_store -> query_owed (urllib) -> HTTP -> router
    -> repo -> SQL COUNT, AND the transcript-replay fallback, AND
    _synthesize_owed_items + evaluate_work_owed + decide_heartbeat.
    """
    base_url      = e2e_server[ "base_url" ]
    http_receipts = e2e_server[ "http_receipts" ]
    sql_receipts  = e2e_server[ "sql_receipts" ]

    def drive( *, flag, persona, project, transcript_path ):
        # ── config / identity INPUTS ───────────────────────────────────────────
        monkeypatch.setattr( stop, "load_heartbeat_settings", lambda: {
            "enabled"                        : True,
            "poke_cap"                       : 1000,
            "count_inbound_questions_as_owed": False,
            "owed_source_from_store"         : flag,
            "verification_threshold_seconds" : 600,
        } )
        monkeypatch.setattr( stop, "load_task_store_settings", lambda: {
            "enabled"           : True,
            "api_base_url"      : base_url,
            "timeout_seconds"   : 5.0,
            "spool_ttl_seconds" : 3600.0,
        } )
        monkeypatch.setattr( stop, "get_voice_persona", lambda _sid: { "name": persona } )
        monkeypatch.setattr( stop, "resolve_project_name", lambda: project )

        # ── neutralize non-seam side-effects ───────────────────────────────────
        # The hold seam MOVED: stop imports `read_hold_resilient` (bug 1789f197 —
        # resolve across both the session cwd AND the project root), not the old
        # `read_hold`. Patch follows the seam. `None` is the REAL return shape for
        # "no hold on file", so this neutralizes without inventing a shape.
        monkeypatch.setattr( stop, "read_hold_resilient", lambda *a, **k: None )
        monkeypatch.setattr( stop, "get_poke_count", lambda _sid: 0 )
        monkeypatch.setattr( stop, "increment_poke_count", _noop )
        monkeypatch.setattr( stop, "_notify_cap_reached", _noop )
        monkeypatch.setattr( stop, "_announce_poke", _noop )
        monkeypatch.setattr( stop, "inject_qualifier_via_tmux", _noop )
        monkeypatch.setattr( stop, "_emit_genuine_idle", _noop )
        monkeypatch.setattr( stop, "_build_poke_abstract_safe", lambda *a, **k: "" )
        monkeypatch.setattr( heartbeat_events, "emit_outcome", _noop )
        # isolate the disagreement to the owed-items SOURCE only
        monkeypatch.setattr( stop, "_gather_outstanding_delegations", lambda _sid: [ ] )
        monkeypatch.setattr( stop, "_gather_unanswered_inbound_questions",
                             lambda _sid: { "owed": [ ], "stale": [ ] } )

        # ── capture the oracle log line ────────────────────────────────────────
        captured = [ ]
        real_log = stop.log_to_stream

        def _capturing_log( hook_name, payload, extra=None ):
            if extra is not None:
                captured.append( extra )
            return None

        monkeypatch.setattr( stop, "log_to_stream", _capturing_log )

        http_before = len( http_receipts )
        sql_before  = len( sql_receipts )

        session_id = f"e2e-{uuid.uuid4().hex[:8]}"
        stop._run_heartbeat( session_id, str( transcript_path ), cwd=str( tmp_path ) )

        monkeypatch.setattr( stop, "log_to_stream", real_log )

        oracle = next( ( e for e in captured if e.get( "phase" ) == HEARTBEAT_PHASE ), None )
        assert oracle is not None, f"no {HEARTBEAT_PHASE} log line emitted; captured phases: {[ e.get('phase') for e in captured ]}"

        return {
            "owed_items" : oracle[ "owed_items" ],
            "work_owed"  : oracle[ "work_owed" ],
            "outcome"    : oracle[ "outcome" ],
            "http_new"   : http_receipts[ http_before: ],
            "sql_new"    : sql_receipts[ sql_before: ],
        }

    return drive


def _report( scenario, *, flag, persona, project, store_owed, transcript_owed, expected, result ):
    """Print the per-scenario receipts (HTTP + SQL params) + verdict."""
    print( f"\n┌─ {scenario} " + "─" * ( 60 - len( scenario ) ) )
    print( f"│ flag={flag} persona={persona!r} project={project!r}" )
    print( f"│ store_owed={store_owed} transcript_owed={transcript_owed} expected_owed={expected}" )
    print( f"│ ACTUAL owed_items={result['owed_items']} work_owed={result['work_owed']} outcome={result['outcome']}" )
    print( f"│ HTTP receipts ({len( result['http_new'] )} requests):" )
    for r in result[ "http_new" ]:
        print( f"│   {r['method']} {r['path']} query={r['query']}" )
    print( f"│ SQL receipts ({len( result['sql_new'] )} COUNT statements):" )
    for s in result[ "sql_new" ]:
        print( f"│   {s['statement']}" )
        print( f"│     params={s['parameters']}" )
    print( "└" + "─" * 61 )


# ── S1 — store IS the source ───────────────────────────────────────────────────
def test_s1_store_is_the_source( clean_tasks, drive_oracle, tmp_path ):
    """store=N (mix queued+in_progress), transcript=0, flag ON -> oracle == N."""
    persona, project = "arnold", "lupin"
    store_owed = seed_store_rows( persona, project, n_queued=4, n_in_progress=3 )   # 7
    tp = tmp_path / "s1.jsonl"
    transcript_owed = write_transcript( tp, n_owed=0 )

    result = drive_oracle( flag=True, persona=persona, project=project, transcript_path=tp )
    _report( "S1 store-is-source", flag=True, persona=persona, project=project,
             store_owed=store_owed, transcript_owed=transcript_owed, expected=store_owed, result=result )

    assert result[ "owed_items" ] == store_owed == 7
    assert result[ "work_owed" ] is True
    # ── receipt assertions — scoped by OWNER FIELD, not by request count ───────
    # SHAPE CHANGE (2026-07-19 PARKED build): the old "one count_only GET per
    # owed status, summed client-side" loop is DELETED — query_owed now issues
    # ONE request behind `owed_only=true` and the SERVER owns the status set
    # (task_store_client.query_owed docstring). The second count_only request on
    # the wire is NOT ours: it is Face A's manager-backlog read
    # (_backlog_count_from_store, `accountable_manager=`), a different consumer.
    #
    # ⚠️ The assertion this replaces (`len( counts_only ) == 2`) went on PASSING
    # across that change while measuring something else entirely — two CONSUMERS
    # instead of two STATUSES. It is restated by owner field so it can no longer
    # be satisfied by an unrelated caller appearing on the wire.
    owner_counts = [ r for r in result[ "http_new" ]
                     if r[ "query" ].get( "count_only" ) == "true"
                     and "owner_persona" in r[ "query" ] ]
    assert len( owner_counts ) == 1, result[ "http_new" ]
    owner_q = owner_counts[ 0 ][ "query" ]
    assert owner_q[ "owed_only" ]      == "true"
    assert owner_q[ "owner_persona" ]  == persona
    assert owner_q[ "project" ]        == project
    # TRIPWIRE — NO DEMONSTRATED RED, and that is stated rather than implied.
    # It guards a silent RESTORATION of the retired per-status client loop. Every
    # mutant that re-adds a client-side `status=` was caught EARLIER by the count
    # assertions above, because the server still HONORS status (measured: adding
    # status=queued to an owed_only request dropped the count 7 -> 4). So this
    # line can only fire in a future where the server stops honoring `status`
    # while a client re-adds it — a scenario that cannot be simulated from the
    # client today. Kept as a cheap tripwire, NOT counted as armed coverage.
    assert "status" not in owner_q, \
        "owed status set is SERVER-owned behind owed_only; a client-side status= is the deleted shape"
    assert len( result[ "sql_new" ] ) >= 2, "expected real COUNT(*) SQL on lupin_db_test"
    assert any( "owner_persona" in s[ "statement" ] for s in result[ "sql_new" ] ), \
        "the owed COUNT(*) must be owner-scoped SQL, not inferred from the backlog read"


# ── S2 — transcript replay is DEAD under the flag (inverse) ─────────────────────
def test_s2_transcript_replay_is_dead_under_flag( clean_tasks, drive_oracle, tmp_path ):
    """store=0, transcript=5 owed, flag ON -> oracle == 0 (replay ignored)."""
    persona, project = "arnold", "lupin"
    store_owed = seed_store_rows( persona, project, n_queued=0, n_in_progress=0 )    # 0
    tp = tmp_path / "s2.jsonl"
    transcript_owed = write_transcript( tp, n_owed=5 )                               # 5 owed in transcript

    result = drive_oracle( flag=True, persona=persona, project=project, transcript_path=tp )
    _report( "S2 inverse (replay dead)", flag=True, persona=persona, project=project,
             store_owed=store_owed, transcript_owed=transcript_owed, expected=0, result=result )

    assert transcript_owed == 5                       # the transcript genuinely carries owed work
    assert result[ "owed_items" ] == 0                # ...but the oracle ignores it under the flag
    assert result[ "work_owed" ] is False


# ── S4 — count_only true COUNT(*), not page-cap saturation ─────────────────────
def test_s4_saturation_guard_over_100_rows( clean_tasks, drive_oracle, tmp_path ):
    """store=150 queued (> the 100 page cap), transcript=0, flag ON -> oracle == 150."""
    persona, project = "arnold", "lupin"
    store_owed = seed_store_rows( persona, project, n_queued=150 )                   # 150 > 100
    tp = tmp_path / "s4.jsonl"
    write_transcript( tp, n_owed=0 )

    result = drive_oracle( flag=True, persona=persona, project=project, transcript_path=tp )
    _report( "S4 saturation (>100)", flag=True, persona=persona, project=project,
             store_owed=store_owed, transcript_owed=0, expected=150, result=result )

    assert store_owed == 150
    assert result[ "owed_items" ] == 150, \
        "count_only must return the TRUE COUNT(*), not a page-length saturating at 100"
    assert result[ "work_owed" ] is True


# ── S5 — FALSIFIABLE negative control (same inputs as S2, flag OFF) ─────────────
def test_s5_flag_off_negative_control( clean_tasks, drive_oracle, tmp_path ):
    """store=0, transcript=5 owed, flag OFF -> oracle == 5 (transcript path).

    This is the falsifiability pair with S2: IDENTICAL inputs, only the flag
    differs, and the verdict FLIPS (0 under ON vs 5 under OFF). If the flag did
    nothing, S2 and S5 could not both pass.
    """
    persona, project = "arnold", "lupin"
    seed_store_rows( persona, project, n_queued=0, n_in_progress=0 )                 # store empty
    tp = tmp_path / "s5.jsonl"
    transcript_owed = write_transcript( tp, n_owed=5 )

    result = drive_oracle( flag=False, persona=persona, project=project, transcript_path=tp )
    _report( "S5 flag-OFF control", flag=False, persona=persona, project=project,
             store_owed=0, transcript_owed=transcript_owed, expected=transcript_owed, result=result )

    assert result[ "owed_items" ] == transcript_owed == 5   # transcript replay IS the source under OFF
    assert result[ "work_owed" ] is True
    # The store must not have been read FOR THE OWED COUNT under flag OFF.
    # NOT "no HTTP at all": Face A's manager-backlog read
    # (_backlog_count_from_store, `accountable_manager=`) is a DIFFERENT consumer
    # and is deliberately NOT gated by owed_source_from_store — the flag governs
    # the owed-count SOURCE, not every store read in the hook. The control is
    # therefore stated by owner field: an owner_persona-scoped count IS the
    # cutover read, and under OFF there must be none of them.
    owner_http = [ r for r in result[ "http_new" ] if "owner_persona" in r[ "query" ] ]
    assert owner_http == [ ], "flag OFF must not read the OWED COUNT from the store over HTTP"
    owner_sql  = [ s for s in result[ "sql_new" ] if "owner_persona" in s[ "statement" ] ]
    assert owner_sql == [ ], "flag OFF must not run an owner-scoped store COUNT"


# ── S6 — lupin AND non-lupin/plan dimension (project-scoped read) ───────────────
def test_s6a_lupin_session_reads_only_lupin_rows( clean_tasks, drive_oracle, tmp_path ):
    """Cross-project store; a lupin session counts ONLY its lupin rows (no plan leak)."""
    persona = "arnold"
    seed_store_rows( persona, "lupin", n_queued=6 )     # K = 6
    seed_store_rows( persona, "plan",  n_queued=9 )     # J = 9
    tp = tmp_path / "s6a.jsonl"
    write_transcript( tp, n_owed=0 )

    result = drive_oracle( flag=True, persona=persona, project="lupin", transcript_path=tp )
    _report( "S6a lupin scope", flag=True, persona=persona, project="lupin",
             store_owed="6 lupin + 9 plan", transcript_owed=0, expected=6, result=result )

    assert result[ "owed_items" ] == 6, "lupin session must NOT see the 9 plan rows"
    assert all( r[ "query" ][ "project" ] == "lupin" for r in result[ "http_new" ] if "project" in r[ "query" ] )


def test_s7_queued_row_with_future_chase_still_counts_as_owed( clean_tasks, drive_oracle, tmp_path ):
    """A SCHEDULED queued row is still OWED — the fence, ruled 2026-07-21.

    THE GAP THIS CLOSES (found on row 9bb4debe, reported before it could bite):
    every other scenario here seeds rows with a NULL chase, so this suite — the
    instrument sitting closest to the owed oracle — was GREEN-BLIND to any change
    on the chase axis. The `next_chase_ts` decoupling (Arnold, rows 86ce4c43 /
    9bb4debe) makes a chase legal without a blocker, and the tempting way to
    implement it is to copy the `parked` suppression clause onto `queued`.

    THAT COPY IS THE DEFECT THIS TEST EXISTS TO CATCH. `parked` earns its
    suppression because A HUMAN RULED THE ROW NOT-NOW and must quote a
    park_reason; the chase is the bounded expiry on that ruling. A chase on a
    queued row is a SCHEDULE WITH NOBODY'S RULING BEHIND IT — suppressing on it
    would let any caller silence a row from the owed oracle with a timestamp, no
    human in the loop and no reason to refute.

    Ruled by Mr. Radio 2026-07-21: owed semantics are FENCED — a scheduled row
    does NOT stop counting as owed.
    """
    from datetime import datetime, timedelta, timezone

    persona, project = "arnold", "lupin"
    future = datetime.now( timezone.utc ) + timedelta( hours=6 )
    store_owed = seed_store_rows( persona, project, n_queued=3, next_chase_ts=future )
    tp = tmp_path / "s7.jsonl"
    write_transcript( tp, n_owed=0 )

    result = drive_oracle( flag=True, persona=persona, project=project, transcript_path=tp )
    _report( "S7 scheduled-is-still-owed", flag=True, persona=persona, project=project,
             store_owed=f"{store_owed} queued, chase {future.isoformat()}",
             transcript_owed=0, expected=store_owed, result=result )

    assert store_owed == 3
    assert result[ "owed_items" ] == 3, \
        "a queued row with a FUTURE chase must still count as owed — suppressing on the " \
        "chase alone would let a bare timestamp silence a row no human ruled not-now"
    assert result[ "work_owed" ] is True


def test_s6b_plan_session_reads_only_plan_rows( clean_tasks, drive_oracle, tmp_path ):
    """Same cross-project store; a non-lupin/plan session reads its OWN rows.

    The historical mirror write-gate DROPPED non-lupin writes (a WRITE-path bug,
    now retired/no-op). This proves the READ path scopes correctly: a plan
    session sees exactly its 9 plan rows, none of the lupin rows.
    """
    persona = "arnold"
    seed_store_rows( persona, "lupin", n_queued=6 )
    seed_store_rows( persona, "plan",  n_queued=9 )
    tp = tmp_path / "s6b.jsonl"
    write_transcript( tp, n_owed=0 )

    result = drive_oracle( flag=True, persona=persona, project="plan", transcript_path=tp )
    _report( "S6b plan scope", flag=True, persona=persona, project="plan",
             store_owed="6 lupin + 9 plan", transcript_owed=0, expected=9, result=result )

    assert result[ "owed_items" ] == 9, "plan session must read its OWN 9 rows, not the lupin rows"
    assert all( r[ "query" ][ "project" ] == "plan" for r in result[ "http_new" ] if "project" in r[ "query" ] )
