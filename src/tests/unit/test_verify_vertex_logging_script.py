"""
Unit tests for the Vertex logging RUNNER (`src/scripts/verify_vertex_logging.py`).

Everything here is injected — clock, sleeper, query function, subprocess runner. NOTHING touches
the network, fires a prediction, or spends a cent.

The load-bearing test is `test_a_failed_bq_read_is_never_reported_as_no_rows`. A `bq` process that
exits non-zero has told us NOTHING, and the single most dangerous thing this runner could do is
quietly turn that silence into "no rows found" — which reads as "not logged", which is a false
negative against a lagging oracle. That is the founding bug of this entire cascade, and it would
have entered through the humblest possible door: an unchecked return code.
"""

import importlib.util
import os
import re
import sys

import pytest

from cosa.utils.vertex_logging import (
    DOCUMENTED_DEFAULT_TABLE,
    VertexLoggingError,
    mint_sentinel,
)


def _load_runner():
    """Load the script by path — it lives in src/scripts/, which is not an importable package."""
    path = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts", "verify_vertex_logging.py" )
    spec = importlib.util.spec_from_file_location( "verify_vertex_logging", path )
    module = importlib.util.module_from_spec( spec )
    sys.modules[ "verify_vertex_logging" ] = module
    spec.loader.exec_module( module )
    return module


runner_module = _load_runner()

PROJECT = "unit-test-project-000000"
BASE    = [ "--project-id", PROJECT ]

SCRIPT_PATH = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts", "verify_vertex_logging.py" )


def test_the_bootstrap_refuses_to_guess_the_project_root( monkeypatch ):
    """
    RED-FIRST on the bootstrap guard. A script that GUESSES its root resolves paths into whatever
    tree it happens to be launched from — so it fails loud instead. (Reachable, therefore tested;
    a pragma here would be a comment pretending to be a test.)
    """
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )

    spec   = importlib.util.spec_from_file_location( "verify_vertex_logging_no_root", SCRIPT_PATH )
    module = importlib.util.module_from_spec( spec )
    with pytest.raises( RuntimeError, match="LUPIN_ROOT not set" ):
        spec.loader.exec_module( module )


class FakeCompleted:
    def __init__( self, returncode=0, stdout="", stderr="" ):
        self.returncode = returncode
        self.stdout     = stdout
        self.stderr     = stderr


def make_clock( step=30 ):
    ticks = [ 0 ]
    def clock():
        ticks[ 0 ] += step
        return ticks[ 0 ]
    return clock


# ---------------------------------------------------------------------------
# The bq adapter
# ---------------------------------------------------------------------------

def test_bq_query_binds_the_sentinel_and_parses_rows():
    seen = {}
    def fake_run( command, capture_output, text ):
        seen[ "command" ] = command
        return FakeCompleted( stdout='[{"n": 3}]' )

    query_fn = runner_module.make_bq_query_fn( runner=fake_run )
    rows     = query_fn( "SELECT COUNT(*) AS n FROM t", { "sentinel" : "LUPIN-VLOG-abc123abc123" } )

    assert rows == [ { "n" : 3 } ]
    assert "--parameter=sentinel:STRING:LUPIN-VLOG-abc123abc123" in seen[ "command" ]
    assert "--use_legacy_sql=false" in seen[ "command" ]


def test_a_failed_bq_read_is_never_reported_as_no_rows():
    """
    🔑 THE MOST DANGEROUS BUG THIS RUNNER COULD HAVE.

    A `bq` process that exits non-zero has told us NOTHING. Turning that into "no rows" would make a
    BROKEN READ look exactly like "the data isn't there" — a false negative against a lagging oracle,
    which is the founding bug of this cascade. It fails LOUD instead.
    """
    def fake_run( command, capture_output, text ):
        return FakeCompleted( returncode=1, stderr="PERMISSION_DENIED: caller lacks bigquery.jobs.create" )

    query_fn = runner_module.make_bq_query_fn( runner=fake_run )
    with pytest.raises( VertexLoggingError, match="A failed READ is not an empty result" ):
        query_fn( "SELECT 1", {} )


def test_an_empty_bq_stdout_is_an_empty_result_set():
    def fake_run( command, capture_output, text ):
        return FakeCompleted( stdout="   \n" )
    assert runner_module.make_bq_query_fn( runner=fake_run )( "SELECT 1", {} ) == []


def test_bq_debug_narrates( capsys ):
    def fake_run( command, capture_output, text ):
        return FakeCompleted( stdout="[]" )
    runner_module.make_bq_query_fn( runner=fake_run, debug=True )( "SELECT 1\nFROM t", {} )
    assert "[bq]" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --plan (the default) fires nothing
# ---------------------------------------------------------------------------

def test_the_default_mode_fires_nothing_and_names_the_authority( capsys ):
    assert runner_module.main( BASE ) == 0
    out = capsys.readouterr().out
    assert "nothing below has been fired" in out
    assert "L0-subject-maas" in out and "L2-canary-anthropic" in out and "L1-readout-control" in out
    assert "Mr. Radio" in out                       # the authority is NAMED, not assumed
    assert "will not fire them" in out


def test_the_plan_prints_the_MECHANISM_as_OPEN_beside_the_conclusion( capsys ):
    """
    A limitation the reader never sees is not a limitation. The plan prints the MaaS null's conclusion
    (the privacy answer) and, immediately beneath it, that the MECHANISM is OPEN — so nobody can carry
    the conclusion away without the limit that governs it.

    Rio, cold review: "I'll be checking the conclusions, not the caveat." This is the caveat made
    STRUCTURAL — a separate printed field, asserted here, rather than a sentence one may skim past.
    """
    assert runner_module.main( BASE ) == 0
    out = capsys.readouterr().out

    assert "MECHANISM : OPEN" in out
    assert "publisher-scope" in out.lower() and "location-scope" in out.lower()   # BOTH worlds, neither picked
    assert "13c3c480" in out                                                      # the receipt for the blind axis


def test_a_missing_project_id_is_a_usage_error_not_a_guess( capsys ):
    assert runner_module.main( [ "--project-id", "" ] ) == 2
    assert "Never hardcode it" in capsys.readouterr().err


def test_an_uncertified_pairing_refuses_even_to_PLAN( capsys ):
    assert runner_module.main( BASE + [ "--vertex-location", "us-east5" ] ) == 2
    assert "REFUSED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --emit
# ---------------------------------------------------------------------------

def test_emit_prints_the_subject_BEFORE_the_canary( capsys ):
    """ORDERING IS EVIDENCE — and the emitted runbook must not invite the wrong order."""
    assert runner_module.main( BASE + [ "--emit" ] ) == 0
    out = capsys.readouterr().out

    assert out.index( "L0 — SUBJECT" ) < out.index( "L2 — CANARY" )
    assert "FIRE THIS FIRST" in out and "FIRE THIS SECOND" in out
    assert "gpt-oss-120b-maas" in out and "claude-opus-4-8" in out
    assert "harness_readout_canary" in out                      # L1 is emitted too
    assert "RUN THIS BEFORE TRUSTING ANY NULL" in out
    assert "locations/global" in out

    # The two publishers ride DIFFERENT surfaces. Emitting :rawPredict for a MaaS model would 404 —
    # a runbook that cannot be run is worse than no runbook, because somebody debugs the wrong thing.
    assert "publishers/anthropic/models/claude-opus-4-8:rawPredict" in out
    assert "endpoints/openapi/chat/completions" in out
    assert "publishers/openai" not in out


def test_emit_states_the_limitation_the_region_blind_endpoint_forces():
    """
    Bug 13c3c480: the MaaS endpoint ignores its locations/ segment. So a NULL from L0 answers the
    PRIVACY question ("is CoT being persisted?") but CANNOT isolate the mechanism (publisher-scope vs
    location-scope). Two worlds, one observation. The runbook must SAY so rather than let the next
    reader invent which one explained it.
    """
    import io, contextlib
    buffer = io.StringIO()
    with contextlib.redirect_stdout( buffer ):
        runner_module.main( BASE + [ "--emit" ] )
    out = buffer.getvalue()

    assert "13c3c480" in out
    assert "IGNORES its locations/ segment" in out
    assert "narnia-1" in out
    assert "does NOT" in out and "isolate the MECHANISM" in out
    assert "leave the" in out and "mechanism OPEN" in out


def test_emit_mints_three_distinct_sentinels( capsys ):
    """
    Subject, canary, and readout-control each get their OWN sentinel. A shared one would make the
    instrument unable to tell which call landed — and an observation that cannot distinguish two
    worlds is not an observation.

    (Regex, not split(): the control sentinel is quoted INSIDE the emitted SQL, so it is not a
    whitespace-delimited word.)
    """
    runner_module.main( BASE + [ "--emit" ] )
    out       = capsys.readouterr().out
    sentinels = set( re.findall( r"LUPIN-VLOG-[0-9a-f]{12}", out ) )
    assert len( sentinels ) == 3                                # subject, canary, readout control


# ---------------------------------------------------------------------------
# --verify — read-only, and where the discipline lives
# ---------------------------------------------------------------------------

def _verify_argv( canary, subject=None, subject_at=None, max_wait=90 ):
    argv = BASE + [ "--verify", "--canary-sentinel", canary, "--canary-fired-at", "100",
                    "--max-wait-s", str( max_wait ), "--poll-interval-s", "30" ]
    if subject: argv += [ "--subject-sentinel", subject, "--subject-fired-at", str( subject_at ) ]
    return argv


def _query_fn_finding( sentinels_present ):
    """A fake BigQuery that contains exactly the given sentinels."""
    def query_fn( sql, params ):
        if "INFORMATION_SCHEMA" in sql: return [ { "table_name" : DOCUMENTED_DEFAULT_TABLE } ]
        return [ { "n" : 1 if params.get( "sentinel" ) in sentinels_present else 0 } ]
    return query_fn


def test_verify_without_a_canary_is_a_usage_error( capsys ):
    """Without a canary there is no instrument, and without an instrument there is no verdict."""
    assert runner_module.main( BASE + [ "--verify" ] ) == 2
    assert "no instrument" in capsys.readouterr().err


def test_verify_reports_PROVEN_and_exits_zero( capsys ):
    canary = mint_sentinel()
    code   = runner_module.main( _verify_argv( canary ), clock=make_clock(), sleeper=lambda s: None,
                                 query_fn=_query_fn_finding( { canary } ) )
    out = capsys.readouterr().out
    assert code == 0
    assert "VERDICT: PROVEN" in out


def test_verify_reports_INADMISSIBLE_and_exits_ONE( capsys ):
    """
    🔑 An unproven instrument is NOT a pass. The runner exits 1 and says so in words, so that a CI
    green can never be manufactured out of a silence nobody calibrated.
    """
    canary = mint_sentinel()
    code   = runner_module.main( _verify_argv( canary ), clock=make_clock(), sleeper=lambda s: None,
                                 query_fn=_query_fn_finding( set() ) )
    out = capsys.readouterr().out
    assert code == 1
    assert "VERDICT: INADMISSIBLE" in out
    assert "NOT a pass and NOT a fail" in out
    assert "never proved it was awake" in out


def test_verify_reports_REFUTED_with_its_residuals_printed( capsys ):
    """A REFUTED verdict must arrive WITH its caveats, so no reader inherits the conclusion without them."""
    canary  = mint_sentinel()
    subject = mint_sentinel()
    code    = runner_module.main( _verify_argv( canary, subject, subject_at=50 ),
                                  clock=make_clock(), sleeper=lambda s: None,
                                  query_fn=_query_fn_finding( { canary } ) )
    out = capsys.readouterr().out
    assert code == 0
    assert "VERDICT: REFUTED" in out
    assert "PUBLISHER-DEPENDENT" in out                 # the residual is PRINTED, not buried
    assert "readout failure is excluded" in out


def test_verify_HALTS_LOUD_when_the_maas_subject_lands( capsys ):
    """🔴 The privacy alarm. If the MaaS sentinel lands, we are persisting chain-of-thought."""
    canary  = mint_sentinel()
    subject = mint_sentinel()
    code    = runner_module.main( _verify_argv( canary, subject, subject_at=50 ),
                                  clock=make_clock(), sleeper=lambda s: None,
                                  query_fn=_query_fn_finding( { canary, subject } ) )
    out = capsys.readouterr().out
    assert code == 0
    assert "VERDICT: PROVEN" in out
    assert "THE SUBJECT LANDED" in out
    assert "chain-of-thought" in out
    assert "Do NOT dump the row" in out
    assert "HALT" in out


def test_verify_refuses_a_subject_fired_after_the_canary( capsys ):
    """RED-FIRST. The runner inherits ProbePlan's ordering guard and reports it as a refusal."""
    canary  = mint_sentinel()
    subject = mint_sentinel()
    code    = runner_module.main( _verify_argv( canary, subject, subject_at=500 ),
                                  clock=make_clock(), sleeper=lambda s: None,
                                  query_fn=_query_fn_finding( { canary } ) )
    assert code == 2
    assert "ordering is evidence" in capsys.readouterr().err


def test_verify_debug_passes_through( capsys ):
    canary = mint_sentinel()
    code   = runner_module.main( _verify_argv( canary ) + [ "--debug" ], clock=make_clock(),
                                 sleeper=lambda s: None, query_fn=_query_fn_finding( { canary } ) )
    assert code == 0
    assert "canary visible" in capsys.readouterr().out
