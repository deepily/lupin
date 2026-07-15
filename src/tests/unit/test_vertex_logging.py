"""
Unit tests for the Vertex request-response logging verification harness (§4 / §C).

RED-FIRST DISCIPLINE: every guard in `vertex_logging` gets a test that proves it FIRES —
a guard with no red-first test is an unproven guard, and an unproven guard is a comment.

THE TESTS THAT MATTER MOST are the ones asserting the harness REFUSES to render a verdict:
`test_canary_never_lands_is_INADMISSIBLE_not_refuted` and its siblings. It is easy to write
a harness that reports "no rows -> not logged." The whole point of this one is that it
cannot. A green that could not have been red is the same bug as a red that could not have
been green.
"""

import pytest

from cosa.utils.vertex_logging import (
    AC_D5_FIRED,
    AC_D5_INDETERMINATE,
    AC_D5_NOT_FIRED,
    BIGQUERY_ILLEGAL_LOCATIONS,
    CERTIFIED_LOCATION_PAIRINGS,
    DEFAULT_LOG_DATASET,
    DOCUMENTED_DEFAULT_TABLE,
    READOUT_CANARY_TABLE,
    READOUT_MATCH,
    READOUT_NO_MATCH,
    READOUT_TABLE_ABSENT,
    SENTINEL_PATTERN,
    VERDICT_INADMISSIBLE,
    VERDICT_PROVEN,
    VERDICT_REFUTED,
    LoggingReadout,
    ProbePlan,
    ProbeResult,
    VertexLoggingError,
    _expect_raises,
    _FakeReadout,
    _refusing_query_fn,
    assert_bigquery_location_legal,
    assert_double_write_retry_safe,
    assert_location_pairing_certified,
    assert_sentinel_wellformed,
    assert_traffic_config_coupling,
    build_full_config_write_body,
    classify_ac_d5,
    describe_live_calls,
    mint_sentinel,
    quick_smoke_test,
    readout_positive_control_sql,
    run_probe,
)


PROJECT = "hello-world-foo-423219"


class StubReadout:
    """
    A scriptable readout. Each entry in `script` is one poll: a dict of sentinel -> tables.

    It is a stub rather than a mock because the ORDER of appearance is the whole physics we
    are testing — the real readout lags, and a mock that returns a canned value cannot lag.
    """

    def __init__( self, script, tables=( DOCUMENTED_DEFAULT_TABLE, ) ):
        self.script       = list( script )
        self.tables       = tables
        self.poll         = -1
        self.queried_with = []

    def list_tables( self ):
        # run_probe discovers ONCE per poll, so this is the poll clock.
        self.poll += 1
        return self.tables

    def find_sentinel( self, sentinel, tables=None ):
        self.queried_with.append( sentinel )
        if not self.tables: return ( READOUT_TABLE_ABSENT, () )

        frame = self.script[ min( self.poll, len( self.script ) - 1 ) ]
        hits  = frame.get( sentinel )
        if hits: return ( READOUT_MATCH, tuple( hits ) )
        return ( READOUT_NO_MATCH, () )


def make_clock( step=30 ):
    """A monotonic fake clock. No wall time, no sleeps: the tests are instant and deterministic."""
    ticks = [ 0 ]
    def clock():
        ticks[ 0 ] += step
        return ticks[ 0 ]
    return clock


# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

def test_mint_sentinel_is_wellformed_and_unique():
    a = mint_sentinel()
    b = mint_sentinel()
    assert SENTINEL_PATTERN.match( a )
    assert a != b
    assert assert_sentinel_wellformed( a ) == a


@pytest.mark.parametrize( "bad", [ "test", "hello", "LUPIN-VLOG-", "LUPIN-VLOG-ZZZZZZZZZZZZ", "", None, 42 ] )
def test_ambient_sentinel_is_refused( bad ):
    """
    RED-FIRST. An ambient string could match a row THIS PROBE DID NOT WRITE, reporting a false
    PROVEN — the instrument lying in the direction nobody audits.
    """
    with pytest.raises( VertexLoggingError, match="not a minted sentinel" ):
        assert_sentinel_wellformed( bad )


# ---------------------------------------------------------------------------
# §C — the region-coupling trap
# ---------------------------------------------------------------------------

def test_bigquery_location_legal_accepts_a_real_location():
    assert assert_bigquery_location_legal( "US" ) == "US"


def test_bigquery_rejects_global_because_it_is_a_vertex_word():
    """RED-FIRST. `global` is a legal VERTEX location and NOT a legal BIGQUERY one (§4e)."""
    assert "global" in BIGQUERY_ILLEGAL_LOCATIONS
    with pytest.raises( VertexLoggingError, match="VERTEX location, not a BIGQUERY location" ):
        assert_bigquery_location_legal( "global" )


def test_bigquery_rejects_an_empty_location_rather_than_defaulting():
    """RED-FIRST. `bq mk` would silently default to US. A default nobody chose is not a decision."""
    with pytest.raises( VertexLoggingError, match="silently default" ):
        assert_bigquery_location_legal( "" )


def test_the_settled_pairing_is_certified_and_cites_its_evidence():
    note = assert_location_pairing_certified( "global", "US" )
    assert "847218789178146816" in note
    assert ( "global", "US" ) in CERTIFIED_LOCATION_PAIRINGS


def test_an_uncertified_pairing_is_refused_not_guessed():
    """RED-FIRST. A guessed pairing yields a config that reads back beautifully and logs nothing."""
    with pytest.raises( VertexLoggingError, match="NOT CERTIFIED" ):
        assert_location_pairing_certified( "global", "EU" )


def test_pairing_check_rejects_an_illegal_bigquery_location_first():
    with pytest.raises( VertexLoggingError, match="VERTEX location, not a BIGQUERY location" ):
        assert_location_pairing_certified( "global", "global" )


def test_traffic_config_coupling_passes_when_they_agree():
    assert assert_traffic_config_coupling( "global", "global" ) == "global"


def test_traffic_config_mismatch_is_the_trap_that_already_fired():
    """
    RED-FIRST — and this is a REPRODUCTION, not a hypothetical. On 2026-07-13 the first two real
    Vertex calls in this project served at `global` while the design still froze the config at
    `us-central1`. They ran, they billed, and they were ALREADY invisible to the config we were
    about to write.
    """
    with pytest.raises( VertexLoggingError, match="REGION-COUPLING TRAP" ) as exc:
        assert_traffic_config_coupling( "us-central1", "global" )
    assert "us-central1" in str( exc.value ) and "global" in str( exc.value )


def test_unset_cloud_ml_region_is_a_coin_flip_not_a_default():
    """RED-FIRST. An UNCONFIGURED client lands on `global` — which may not be where the config lives."""
    with pytest.raises( VertexLoggingError, match="coin flip" ):
        assert_traffic_config_coupling( "", "global" )


# ---------------------------------------------------------------------------
# §4c — the clobber trap
# ---------------------------------------------------------------------------

def test_a_write_body_cannot_be_built_without_a_prior_fetch():
    """
    RED-FIRST, and the most load-bearing guard in the module. There is NO updateMask: every write
    is a FULL-OBJECT SET. A config now EXISTS (logging enabled, samplingRate 1). A body assembled
    from scratch would SILENTLY WIPE it.
    """
    for empty in ( None, {} ):
        with pytest.raises( VertexLoggingError, match="without a prior fetch" ):
            build_full_config_write_body( empty, { "loggingConfig" : { "enabled" : False } } )


def test_read_modify_write_preserves_fields_this_codebase_has_never_heard_of():
    """
    The clobber trap is disarmed BY CONSTRUCTION, not by discipline: a field we do not model —
    a future `claudeFeatureConfig` key, a server-added default — survives the round trip.
    """
    fetched = {
        "loggingConfig"       : { "enabled" : True, "samplingRate" : 1,
                                  "bigqueryDestination" : { "outputUri" : f"bq://{PROJECT}.vertex_logging" } },
        "claudeFeatureConfig" : { "advancedAiEnabled" : True },
        "someFutureKey"       : { "weHaveNeverHeardOfThis" : "and it must survive" },
    }
    body = build_full_config_write_body( fetched, { "loggingConfig" : { "samplingRate" : 0.5 } } )
    config = body[ "publisherModelConfig" ]

    assert config[ "loggingConfig" ][ "samplingRate" ] == 0.5                              # the mutation applied
    assert config[ "loggingConfig" ][ "enabled" ] is True                                  # its sibling survived
    assert config[ "loggingConfig" ][ "bigqueryDestination" ][ "outputUri" ].endswith( "vertex_logging" )
    assert config[ "claudeFeatureConfig" ][ "advancedAiEnabled" ] is True                  # the OTHER half survived
    assert config[ "someFutureKey" ] == { "weHaveNeverHeardOfThis" : "and it must survive" }
    assert fetched[ "loggingConfig" ][ "samplingRate" ] == 1                               # the input was not mutated


def test_a_mutation_that_would_drop_a_subtree_is_refused():
    """
    RED-FIRST on the belt-to-the-suspenders check. Replacing a dict with a scalar DROPS its
    leaves — a full-object SET would erase them silently.
    """
    fetched = { "loggingConfig" : { "enabled" : True, "samplingRate" : 1 } }
    with pytest.raises( VertexLoggingError, match="DROPS previously-present fields" ) as exc:
        build_full_config_write_body( fetched, { "loggingConfig" : "off" } )
    assert "loggingConfig.enabled" in str( exc.value )


def test_an_empty_subtree_is_a_leaf_and_survives():
    fetched = { "loggingConfig" : { "enabled" : True }, "claudeFeatureConfig" : {} }
    body    = build_full_config_write_body( fetched, { "loggingConfig" : { "enabled" : False } } )
    assert body[ "publisherModelConfig" ][ "claudeFeatureConfig" ] == {}
    assert body[ "publisherModelConfig" ][ "loggingConfig" ][ "enabled" ] is False


# ---------------------------------------------------------------------------
# The readout
# ---------------------------------------------------------------------------

def test_the_default_query_function_refuses_to_touch_gcp():
    """A harness that reaches the network by DEFAULT fires a live call the first time somebody looks around."""
    readout = LoggingReadout( PROJECT )
    with pytest.raises( VertexLoggingError, match="does not touch GCP by default" ):
        readout.list_tables()
    with pytest.raises( VertexLoggingError, match="does not touch GCP by default" ):
        _refusing_query_fn( "SELECT 1", {} )


@pytest.mark.parametrize( "project,dataset,expected", [
    ( "",      DEFAULT_LOG_DATASET, "project_id is required" ),
    ( PROJECT, "",                  "dataset is required" ),
] )
def test_readout_refuses_to_be_built_without_identity( project, dataset, expected ):
    with pytest.raises( VertexLoggingError, match=expected ):
        LoggingReadout( project, dataset=dataset )


def test_list_tables_discovers_rather_than_assumes( capsys ):
    """
    The outputUri is DATASET-level, so VERTEX names the table. A per-publisher config could land
    rows in a table we never guessed — and a bare SELECT FROM request_response_logging would miss
    them and report a null we would have believed.
    """
    captured = {}
    def query_fn( sql, params ):
        captured[ "sql" ] = sql
        return [ { "table_name" : "request_response_logging" }, { "table_name" : "some_other_table" } ]

    readout = LoggingReadout( PROJECT, query_fn=query_fn, debug=True )
    assert readout.list_tables() == ( "request_response_logging", "some_other_table" )
    assert "INFORMATION_SCHEMA.TABLES" in captured[ "sql" ]
    assert "tables in vertex_logging" in capsys.readouterr().out


def test_count_rows_names_no_column():
    """§4f: the row shape is output-only and versioned. Naming a column turns a schema bump into a false failure."""
    captured = {}
    def query_fn( sql, params ):
        captured[ "sql" ] = sql
        return [ { "n" : 7 } ]

    readout = LoggingReadout( PROJECT, query_fn=query_fn )
    assert readout.count_rows( DOCUMENTED_DEFAULT_TABLE ) == 7
    assert "COUNT(*)" in captured[ "sql" ]


def test_sentinel_search_is_schema_agnostic_AND_attributable():
    """
    THE §4f TENSION, DISSOLVED. TO_JSON_STRING( t ) serializes the WHOLE ROW whatever its schema,
    so the query names ZERO columns (survives a v1 -> v2 bump) while still finding MY row rather
    than somebody else's ambient traffic.
    """
    sentinel = mint_sentinel()
    captured = {}
    def query_fn( sql, params ):
        captured[ "sql" ]    = sql
        captured[ "params" ] = params
        return [ { "n" : 1 } ]

    readout = LoggingReadout( PROJECT, query_fn=query_fn )
    assert readout.count_sentinel( DOCUMENTED_DEFAULT_TABLE, sentinel ) == 1
    assert "TO_JSON_STRING" in captured[ "sql" ]
    assert captured[ "params" ] == { "sentinel" : sentinel }
    # The sentinel is BOUND, never interpolated — and no payload column is named.
    assert sentinel not in captured[ "sql" ]
    assert "requestResponseLoggingSchemaVersion" not in captured[ "sql" ]


def test_find_sentinel_searches_every_discovered_table():
    sentinel = mint_sentinel()
    def query_fn( sql, params ):
        if "INFORMATION_SCHEMA" in sql: return [ { "table_name" : "t_one" }, { "table_name" : "t_two" } ]
        return [ { "n" : 1 if "t_two" in sql else 0 } ]

    readout = LoggingReadout( PROJECT, query_fn=query_fn )
    state, hits = readout.find_sentinel( sentinel )
    assert state == READOUT_MATCH
    assert hits == ( "t_two", )


def test_find_sentinel_reports_no_match_distinctly_from_table_absent():
    """
    "We cannot see" and "there is nothing to see" are DIFFERENT findings. Vertex creates the table
    on first write, so TABLE_ABSENT means it has NEVER written a row — a diagnostic a bare
    zero-count would have flattened into silence.
    """
    sentinel = mint_sentinel()

    def empty_dataset( sql, params ):
        return []
    absent_state, _ = LoggingReadout( PROJECT, query_fn=empty_dataset ).find_sentinel( sentinel )
    assert absent_state == READOUT_TABLE_ABSENT

    def present_but_silent( sql, params ):
        if "INFORMATION_SCHEMA" in sql: return [ { "table_name" : DOCUMENTED_DEFAULT_TABLE } ]
        return [ { "n" : 0 } ]
    quiet_state, hits = LoggingReadout( PROJECT, query_fn=present_but_silent ).find_sentinel( sentinel )
    assert quiet_state == READOUT_NO_MATCH
    assert hits == ()


def test_find_sentinel_accepts_a_caller_supplied_table_list():
    """The probe loop discovers tables ONCE per poll and reuses the list for both sentinels."""
    sentinel = mint_sentinel()
    calls    = []
    def query_fn( sql, params ):
        calls.append( sql )
        return [ { "n" : 0 } ]

    readout = LoggingReadout( PROJECT, query_fn=query_fn )
    state, _ = readout.find_sentinel( sentinel, tables=( "only_this_one", ) )
    assert state == READOUT_NO_MATCH
    assert not any( "INFORMATION_SCHEMA" in sql for sql in calls )


def test_readout_positive_control_emits_sql_and_does_not_run_it():
    """
    The calibration that upgrades a null from "we cannot see ANYTHING" to "the Vertex write pipeline
    produced nothing." It is a GCP WRITE, so the harness EMITS it and a human authorizes it.
    """
    sentinel     = mint_sentinel()
    write, verify = readout_positive_control_sql( PROJECT, DEFAULT_LOG_DATASET, sentinel )
    assert READOUT_CANARY_TABLE in write and READOUT_CANARY_TABLE in verify
    assert "CREATE TABLE IF NOT EXISTS" in write and "INSERT INTO" in write
    assert sentinel in write and sentinel in verify
    assert "TO_JSON_STRING" in verify


def test_readout_positive_control_refuses_an_ambient_sentinel():
    with pytest.raises( VertexLoggingError, match="not a minted sentinel" ):
        readout_positive_control_sql( PROJECT, DEFAULT_LOG_DATASET, "canary" )


# ---------------------------------------------------------------------------
# ProbePlan — the validations that happen BEFORE any live call is fired
# ---------------------------------------------------------------------------

def test_a_valid_plan_builds():
    plan = ProbePlan( mint_sentinel(), canary_fired_at=100, subject_sentinel=mint_sentinel(),
                      subject_fired_at=50, max_wait_s=600, poll_interval_s=15 )
    assert plan.max_wait_s == 600 and plan.poll_interval_s == 15


def test_plan_refuses_a_subject_fired_AFTER_the_canary():
    """
    RED-FIRST on ORDERING IS EVIDENCE. If the subject were fired last, its silence would be
    explainable by ingest lag alone — the probe could not have come out otherwise, and an
    observation that could not have come out otherwise is not an observation.
    """
    with pytest.raises( VertexLoggingError, match="ordering is evidence" ):
        ProbePlan( mint_sentinel(), canary_fired_at=50, subject_sentinel=mint_sentinel(), subject_fired_at=100 )


def test_plan_refuses_a_shared_sentinel():
    shared = mint_sentinel()
    with pytest.raises( VertexLoggingError, match="could not then distinguish" ):
        ProbePlan( shared, canary_fired_at=100, subject_sentinel=shared, subject_fired_at=50 )


@pytest.mark.parametrize( "kwargs,expected", [
    ( { "subject_sentinel" : "LUPIN-VLOG-aaaaaaaaaaaa" },                            "Half a subject" ),
    ( { "subject_fired_at" : 10 },                                                   "Half a subject" ),
    ( { "max_wait_s"      : 0 },                                                     "max_wait_s must be positive" ),
    ( { "poll_interval_s" : 0 },                                                     "poll_interval_s must be positive" ),
] )
def test_plan_guards_fire( kwargs, expected ):
    with pytest.raises( VertexLoggingError, match=expected ):
        ProbePlan( mint_sentinel(), canary_fired_at=100, **kwargs )


def test_plan_refuses_an_ambient_canary_sentinel():
    with pytest.raises( VertexLoggingError, match="not a minted sentinel" ):
        ProbePlan( "canary", canary_fired_at=100 )


# ---------------------------------------------------------------------------
# run_probe — THE CANARY LAW. These are the tests that matter.
# ---------------------------------------------------------------------------

def test_canary_lands_late_and_the_lag_does_not_become_a_false_negative():
    """AC-D7's positive: the row shows up on poll 3. A bare SELECT at t=0 would have called this a failure."""
    canary  = mint_sentinel()
    readout = StubReadout( [ {}, {}, { canary : [ DOCUMENTED_DEFAULT_TABLE ] } ] )
    plan    = ProbePlan( canary, canary_fired_at=0, max_wait_s=600, poll_interval_s=30 )

    result = run_probe( readout, plan, clock=make_clock() )

    assert result.verdict == VERDICT_PROVEN
    assert result.canary_tables == ( DOCUMENTED_DEFAULT_TABLE, )
    assert result.readout_state == READOUT_MATCH
    assert result.polls == 3
    assert result.is_admissible()


def test_canary_never_lands_is_INADMISSIBLE_not_refuted():
    """
    🔑 THE TEST THIS WHOLE MODULE EXISTS FOR.

    The canary does not land inside the bound. A naive harness reports "no rows -> logging is
    broken." This one reports INADMISSIBLE: the instrument never proved it was awake, so its
    silence says NOTHING. Not a pass. Not a fail. No verdict.
    """
    canary  = mint_sentinel()
    readout = StubReadout( [ {}, {} ] )
    plan    = ProbePlan( canary, canary_fired_at=0, max_wait_s=90, poll_interval_s=30 )

    result = run_probe( readout, plan, clock=make_clock() )

    assert result.verdict == VERDICT_INADMISSIBLE
    assert result.verdict != VERDICT_REFUTED
    assert not result.is_admissible()
    assert "NOT evidence that logging is off" in result.residual_assumptions[ 0 ]


def test_a_subjectless_probe_can_never_return_REFUTED():
    """
    AC-D7 is a ONE-SIDED TEST and the harness enforces it. The canary IS the subject there, so
    nothing else can calibrate the null: AC-D7 can CONFIRM logging and can NEVER REFUTE it.
    "No rows" is not "logging is broken", and this function will not let anyone report it as such.
    """
    for script in ( [ { } ], [ {}, {}, {} ] ):
        canary = mint_sentinel()
        plan   = ProbePlan( canary, canary_fired_at=0, max_wait_s=90, poll_interval_s=30 )
        result = run_probe( StubReadout( script ), plan, clock=make_clock() )
        assert result.verdict in ( VERDICT_PROVEN, VERDICT_INADMISSIBLE )
        assert result.verdict != VERDICT_REFUTED


def test_subject_landing_is_PROVEN_immediately_because_a_positive_needs_no_canary():
    """
    The ALARM branch for the MaaS coverage question (823be9cc). If the openai/deepseek sentinel
    lands, raw chain-of-thought IS being persisted to BigQuery at 100% sampling. Presence proves
    itself — we do NOT wait for the canary before believing our eyes.
    """
    canary  = mint_sentinel()
    subject = mint_sentinel()
    readout = StubReadout( [ { subject : [ DOCUMENTED_DEFAULT_TABLE ] } ] )
    plan    = ProbePlan( canary, canary_fired_at=100, subject_sentinel=subject, subject_fired_at=50,
                         max_wait_s=600, poll_interval_s=30 )

    result = run_probe( readout, plan, clock=make_clock() )

    assert result.verdict == VERDICT_PROVEN
    assert result.subject_tables == ( DOCUMENTED_DEFAULT_TABLE, )
    assert result.canary_seen_at is None          # we did not need it. A positive needs no canary.
    assert result.residual_assumptions == ()


def test_subject_silent_while_canary_lands_is_an_ADMISSIBLE_null():
    """
    The expected shape of the coverage probe: the subject (fired FIRST) stays silent while the
    canary (fired SECOND) lands. The silence happened inside a window where the instrument
    DEMONSTRABLY spoke — so the null is admissible, and it is labelled with its residual.
    """
    canary  = mint_sentinel()
    subject = mint_sentinel()
    readout = StubReadout( [ {}, { canary : [ DOCUMENTED_DEFAULT_TABLE ] }, {} ] )
    plan    = ProbePlan( canary, canary_fired_at=100, subject_sentinel=subject, subject_fired_at=50,
                         max_wait_s=120, poll_interval_s=30 )

    result = run_probe( readout, plan, clock=make_clock() )

    assert result.verdict == VERDICT_REFUTED
    assert result.canary_seen_at is not None
    assert result.subject_tables == ()
    assert result.is_admissible()
    assert any( "PUBLISHER-DEPENDENT" in note for note in result.residual_assumptions )
    assert any( "readout failure is excluded" in note for note in result.residual_assumptions )


def test_probe_keeps_polling_for_the_subject_after_the_canary_lands():
    """
    Free reads buy more evidence, so the probe does NOT short-circuit on the canary when a subject
    is in play. If the subject lands late, we catch it rather than filing a false REFUTED.
    """
    canary  = mint_sentinel()
    subject = mint_sentinel()
    readout = StubReadout( [ { canary : [ "t" ] }, {}, { subject : [ "t" ] } ] )
    plan    = ProbePlan( canary, canary_fired_at=100, subject_sentinel=subject, subject_fired_at=50,
                         max_wait_s=600, poll_interval_s=30 )

    result = run_probe( readout, plan, clock=make_clock() )

    assert result.verdict == VERDICT_PROVEN
    assert result.subject_tables == ( "t", )
    assert result.canary_seen_at is not None     # seen earlier, but it did not stop the search


def test_probe_never_sleeps_a_fixed_wait_in_place_of_evidence():
    """
    Google declares NO ingest delay for this pipeline (metadata.ingestDelay: None), so any
    hardcoded wait is an assumption wearing a constant's clothing. The probe POLLS to a bound; the
    canary — not the clock — licenses the verdict.
    """
    canary  = mint_sentinel()
    slept   = []
    readout = StubReadout( [ {}, { canary : [ "t" ] } ] )
    plan    = ProbePlan( canary, canary_fired_at=0, max_wait_s=600, poll_interval_s=30 )

    run_probe( readout, plan, clock=make_clock(), sleeper=slept.append )

    assert slept == [ 30 ]                       # one interval between two polls — no fixed pre-wait


def test_probe_debug_narrates_both_landings( capsys ):
    canary  = mint_sentinel()
    subject = mint_sentinel()

    run_probe( StubReadout( [ { canary : [ "t" ] } ] ),
               ProbePlan( canary, canary_fired_at=0, max_wait_s=60, poll_interval_s=30 ),
               clock=make_clock(), debug=True )
    assert "canary visible" in capsys.readouterr().out

    run_probe( StubReadout( [ { subject : [ "t" ] } ] ),
               ProbePlan( canary, canary_fired_at=100, subject_sentinel=subject, subject_fired_at=50,
                          max_wait_s=60, poll_interval_s=30 ),
               clock=make_clock(), debug=True )
    assert "SUBJECT LANDED" in capsys.readouterr().out


def test_probe_reports_table_absent_in_the_inadmissible_result():
    """Vertex creates the table on first write. TABLE_ABSENT => it has NEVER written a row."""
    canary  = mint_sentinel()
    readout = StubReadout( [ {} ], tables=() )
    plan    = ProbePlan( canary, canary_fired_at=0, max_wait_s=60, poll_interval_s=30 )

    result = run_probe( readout, plan, clock=make_clock() )

    assert result.verdict == VERDICT_INADMISSIBLE
    assert result.readout_state == READOUT_TABLE_ABSENT


def test_probe_result_repr_is_readable():
    result = ProbeResult( VERDICT_PROVEN, canary_tables=( "t", ) )
    assert "PROVEN" in repr( result ) and "canary_tables=('t',)" in repr( result )


# ---------------------------------------------------------------------------
# AC-D5 precedence (F-D18)
# ---------------------------------------------------------------------------

def test_a_blind_instrument_is_never_reported_as_a_negative():
    """
    🔑 F-D18. AC-D5 rides the BigQuery log — it is the only place a tool-use block is visible. So if
    AC-D7 is not PROVEN, an absent search block means "WE CANNOT SEE", not "search didn't fire".
    Reporting a blind instrument as a negative is how a team learns something false and rolls back the
    wrong thing.
    """
    assert classify_ac_d5( VERDICT_INADMISSIBLE, search_block_found=False ) == AC_D5_INDETERMINATE
    assert classify_ac_d5( VERDICT_REFUTED,      search_block_found=False ) == AC_D5_INDETERMINATE
    assert classify_ac_d5( VERDICT_INADMISSIBLE, search_block_found=False ) != AC_D5_NOT_FIRED


def test_a_real_negative_requires_a_proven_log():
    assert classify_ac_d5( VERDICT_PROVEN, search_block_found=False ) == AC_D5_NOT_FIRED


@pytest.mark.parametrize( "verdict", [ VERDICT_PROVEN, VERDICT_REFUTED, VERDICT_INADMISSIBLE ] )
def test_a_found_search_block_is_FIRED_whatever_the_logging_verdict( verdict ):
    """The canary asymmetry again: a POSITIVE needs no calibration. If we can SEE the block, the log worked."""
    assert classify_ac_d5( verdict, search_block_found=True ) == AC_D5_FIRED


def test_ac_d5_refuses_a_verdict_nobody_rendered():
    with pytest.raises( VertexLoggingError, match="Unknown logging verdict" ):
        classify_ac_d5( "PASSED", search_block_found=False )


# ---------------------------------------------------------------------------
# OSQ C-4 — the double-write proof
# ---------------------------------------------------------------------------

DONE_CLEAN = { "done" : True, "error" : None }


def test_double_write_is_retry_safe_when_the_second_write_lands_clean_and_changes_nothing():
    config = { "loggingConfig" : { "enabled" : True } }
    assert assert_double_write_retry_safe( DONE_CLEAN, DONE_CLEAN, config, dict( config ) ) is True


@pytest.mark.parametrize( "first,second,expected", [
    ( { "done" : False, "error" : None }, DONE_CLEAN,                          "first write's LRO is NOT done" ),
    ( DONE_CLEAN,                         { "done" : False, "error" : None },  "second write's LRO is NOT done" ),
    ( { "done" : True, "error" : "boom" }, DONE_CLEAN,                         "first write's LRO carries an error" ),
    ( DONE_CLEAN,                         { "done" : True, "error" : "boom" }, "second write's LRO carries an error" ),
] )
def test_an_unpolled_or_failed_lro_is_never_retry_safe( first, second, expected ):
    """RED-FIRST. HTTP 200 means ACCEPTED, not APPLIED. An unpolled LRO is an assumption wearing a status code."""
    with pytest.raises( VertexLoggingError, match=expected ):
        assert_double_write_retry_safe( first, second, {}, {} )


def test_a_second_write_that_succeeds_but_mutates_the_config_is_the_clobber_trap_in_green():
    """
    RED-FIRST, and the subtlest guard here. A second write that 200s while silently mangling the config
    is NOT retry-safety — it is the clobber trap passing as a green tick.
    """
    with pytest.raises( VertexLoggingError, match="clobber trap passing as a green tick" ):
        assert_double_write_retry_safe(
            DONE_CLEAN, DONE_CLEAN,
            { "loggingConfig" : { "enabled" : True }, "claudeFeatureConfig" : { "advancedAiEnabled" : True } },
            { "loggingConfig" : { "enabled" : True } },      # the other half vanished
        )


# ---------------------------------------------------------------------------
# The live-call manifest
# ---------------------------------------------------------------------------

def test_live_call_manifest_enumerates_everything_and_fires_nothing():
    calls = describe_live_calls( PROJECT, "global", "US" )
    ids   = [ call[ "id" ] for call in calls ]

    assert ids == [ "L1-readout-control", "L0-subject-maas", "L2-canary-anthropic" ]
    # The subject is listed BEFORE the canary because it must be FIRED before it — ordering is evidence.
    assert ids.index( "L0-subject-maas" ) < ids.index( "L2-canary-anthropic" )
    assert all( call[ "spend" ] for call in calls )
    assert all( call[ "proves" ] for call in calls )

    maas = next( call for call in calls if call[ "id" ] == "L0-subject-maas" )
    assert "chain-of-thought" in maas[ "if_yes" ].lower()
    assert "reasoning_content" in maas[ "if_yes" ]


def test_a_maas_null_answers_PRIVACY_and_names_NO_mechanism():
    """
    Rio, cold review 2026-07-14: "Stating a limitation and then quietly reasoning past it two sections
    later is the commonest form of this bug — and prose that confesses is disarming, which is what makes
    it dangerous. A CONFESSION IS NOT A CORRECTION. I'll be checking the conclusions, not the caveat."

    He was right, and this test exists because he was. The first draft of this manifest CONFESSED the
    region-blindness of the MaaS endpoint (13c3c480) and then, in the very same field, concluded "the
    config does not cover that publisher" — a PUBLISHER-SCOPE verdict the null never earned. One
    observation, two worlds; the null selects neither.

    So the CONCLUSION field is held MECHANISM-FREE by assertion. It may state the privacy answer. It may
    not name a mechanism — because the probe that produced it cannot see one.
    """
    calls = describe_live_calls( PROJECT, "global", "US" )
    maas  = next( call for call in calls if call[ "id" ] == "L0-subject-maas" )

    conclusion = maas[ "if_no" ].lower()

    # It answers the PRIVACY question — the one question a null here CAN answer.
    assert "privacy" in conclusion
    assert "chain-of-thought" in conclusion
    assert "not being persisted" in conclusion

    # And it says NOTHING about WHY. Mechanism vocabulary is BANNED from the conclusion field: each of
    # these words, in this field, would be a claim the observation could not have falsified.
    for banned in ( "publisher", "scope", "region", "us-central1", "global" ):
        assert banned not in conclusion, (
            f"The CONCLUSION field names a mechanism ('{banned}') that the null cannot isolate. "
            f"That is reasoning past the limitation — put it in if_no_mechanism, or do not claim it."
        )


def test_the_maas_mechanism_is_left_OPEN_with_BOTH_worlds_named():
    """
    The mechanism field must PRESENT the two worlds and PICK NEITHER. If it ever names one, the module is
    asserting something the probe cannot see — which is the exact defect this pair of tests was born from.
    """
    calls = describe_live_calls( PROJECT, "global", "US" )
    maas  = next( call for call in calls if call[ "id" ] == "L0-subject-maas" )

    mechanism = maas[ "if_no_mechanism" ]
    lowered   = mechanism.lower()

    assert mechanism.startswith( "OPEN" )            # the verdict on the mechanism is: there isn't one
    assert "cannot select" in lowered                # ...and it says WHY it cannot be closed

    # BOTH worlds are named. Naming only one would be picking one.
    assert "publisher-scope" in lowered
    assert "location-scope"  in lowered

    # The blind axis is cited WITH ITS RECEIPT — a limitation without a receipt is just a mood.
    assert "13c3c480" in mechanism
    assert "narnia-1" in mechanism


def test_live_call_manifest_can_exclude_the_maas_probe():
    calls = describe_live_calls( PROJECT, "global", "US", include_maas_probe=False )
    assert [ call[ "id" ] for call in calls ] == [ "L1-readout-control", "L2-canary-anthropic" ]


def test_live_call_manifest_refuses_an_uncertified_pairing():
    """You cannot even DESCRIBE a run against a pairing nobody has certified."""
    with pytest.raises( VertexLoggingError, match="NOT CERTIFIED" ):
        describe_live_calls( PROJECT, "us-east5", "US" )


# ---------------------------------------------------------------------------
# The smoke test and its helpers
# ---------------------------------------------------------------------------

def test_expect_raises_returns_the_exception_when_the_guard_fires():
    raised = _expect_raises( VertexLoggingError, assert_bigquery_location_legal, "global" )
    assert isinstance( raised, VertexLoggingError )


def test_expect_raises_fails_loud_when_a_guard_stays_asleep():
    with pytest.raises( AssertionError, match="the guard is asleep" ):
        _expect_raises( VertexLoggingError, mint_sentinel )


def test_fake_readout_lags_then_lands():
    fake = _FakeReadout( lands_on_poll=2 )
    assert fake.list_tables() == ( DOCUMENTED_DEFAULT_TABLE, )
    assert fake.find_sentinel( "x" )[ 0 ] == READOUT_NO_MATCH
    assert fake.find_sentinel( "x" )[ 0 ] == READOUT_MATCH


def test_quick_smoke_test_passes( capsys ):
    quick_smoke_test()
    out = capsys.readouterr().out
    assert "smoke test PASSED" in out
    assert "INADMISSIBLE" in out
