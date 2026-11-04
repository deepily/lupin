"""
Unit tests for the live wiring of the shadow audit.

They cover the token ceiling of the drain, the queueing hook in the live lookup, the sweep adapter,
the command line and the cron lines. Every sweep is a fake, the INI file is a dict and the crontab
is the librarian tests' fake script, so nothing leaves the process.
Venue: :7999-eligible.
"""
import json
import os
import re

import pytest

from cosa.repo.symindex import librarian_tick as lt
from cosa.repo.symindex.candidates import shadow_audit as sa
from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import reuse_ledger
from lupin_mcp import reuse_shadow as rs
from lupin_mcp import reuse_tools

from test_librarian_tick import cron  # noqa: F401  (fixture: the fake crontab and the fake lock)
from tests.unit.test_reuse_pack_route import env, no_jev_key  # noqa: F401  (fixtures: a fixture repository with its data and index folders, and no Jev key)
from tests.unit.test_reuse_tools import NEED, Recorder, ctx_for

SET_ID   = "gen-1"
INDEX = "idx-1"
LIVE  = { "verdict": "UNCERTAIN_READ_SOURCE", "candidate_ids": [ "a", "b" ] }
DAY   = "2026-10-25"
ON    = { rs.ENABLED_KEY: "true", rs.CEILING_KEY: "5000", rs.LIFETIME_KEY: "100000000", rs.WEEKLY_CAP_KEY: "4", rs.BUDGETS_KEY: "true" }


def reader_of( values ):
    """A settings reader over a dict."""
    return lambda key: values.get( key )


def sampled_need( *sets ):
    """Return the first need the sample takes under every given set id."""
    return next( f"need {n}" for n in range( 5000 ) if all( sa.is_sampled( f"need {n}", one ) for one in ( sets or ( SET_ID, ) ) ) )


def unsampled_need():
    """Return a need the sample leaves out."""
    return next( f"need {n}" for n in range( 5000 ) if not sa.is_sampled( f"need {n}", SET_ID ) )


def receipt_of( need, **extra ):
    """A stored check_exists receipt with a candidate stage, as run_question writes it."""
    base = { "tool": "check_exists", "query": need, "language": "py", "index_sha": INDEX, "verdict": LIVE[ "verdict" ],
             "candidate_stage": { "ids": LIVE[ "candidate_ids" ], "manifest_hash": SET_ID } }
    return { **base, **extra }


def queue_files( data ):
    """The queue files in a data folder."""
    return sorted( ( data / "shadow-pending" ).glob( "*.json" ) )


def queue_up( data, needs, day=DAY ):
    """Queue each need for audit at rate 1."""
    for need in needs: sa.enqueue_if_sampled( data, need, "py", SET_ID, INDEX, LIVE, day, rate=1 )


def result_of( verdict="REUSE", ids=( "z", ), tokens_in=60, tokens_out=40, cause="NO_MATCH" ):
    """A public lookup result as unstored_need_impl returns it."""
    return { "status": "ok", "verdict": verdict, "cause": cause, "shortlist": [ { "id": i } for i in ids ],
             "stats": { "tokens_in": tokens_in, "tokens_out": tokens_out } }


class TestRunPendingCeiling:
    """The additions to run_pending: the token ceiling and the language argument."""

    def test_a_drain_stops_before_a_sweep_that_could_pass_the_ceiling( self, tmp_path ):
        queue_up( tmp_path, [ "n1", "n2", "n3" ] )
        out = sa.run_pending( tmp_path, lambda need: { **result_of(), "causal_ids": [ "z" ], "tokens": 100 }, DAY, max_tokens=250 )
        assert ( out[ "audited" ], out[ "spent_tokens" ], out[ "stopped_by" ] ) == ( 2, 200, "ceiling" )
        assert len( queue_files( tmp_path ) ) == 1, "the third item waits for the next drain"

    def test_a_drain_that_fits_reports_no_stop( self, tmp_path ):
        queue_up( tmp_path, [ "n1", "n2" ] )
        out = sa.run_pending( tmp_path, lambda need: { "verdict": "REUSE", "causal_ids": [ "z" ], "tokens": 10 }, DAY, max_tokens=250 )
        assert ( out[ "audited" ], out[ "spent_tokens" ], out[ "stopped_by" ] ) == ( 2, 20, None )

    def test_the_first_sweep_may_pass_the_ceiling_and_then_the_drain_stops( self, tmp_path ):
        queue_up( tmp_path, [ "n1", "n2" ] )
        out = sa.run_pending( tmp_path, lambda need: { "verdict": "REUSE", "causal_ids": [ "z" ], "tokens": 100 }, DAY, max_tokens=50 )
        assert ( out[ "audited" ], out[ "spent_tokens" ], out[ "stopped_by" ] ) == ( 1, 100, "ceiling" )

    def test_the_ceiling_uses_the_largest_sweep_seen_not_the_last( self, tmp_path ):
        queue_up( tmp_path, [ "n1", "n2", "n3" ], day="2026-10-24" )
        sizes = iter( [ 100, 10, 10 ] )
        out   = sa.run_pending( tmp_path, lambda need: { "verdict": "REUSE", "causal_ids": [ "z" ], "tokens": next( sizes ) }, DAY, max_tokens=200 )
        assert ( out[ "audited" ], out[ "spent_tokens" ] ) == ( 2, 110 ), "110 + the largest sweep, 100, would pass 200; 110 + the last, 10, would not"

    @pytest.mark.parametrize( "tokens", [ None, -1, "5", True, 2.5 ] )
    def test_a_sweep_without_a_whole_token_count_fails_the_item( self, tmp_path, tokens ):
        queue_up( tmp_path, [ "n1" ] )
        answer = { "verdict": "REUSE", "causal_ids": [ "z" ] }
        if tokens is not None: answer[ "tokens" ] = tokens
        out = sa.run_pending( tmp_path, lambda need: answer, DAY, max_tokens=100 )
        assert ( out[ "audited" ], out[ "failed" ] ) == ( 0, 1 )
        assert json.loads( queue_files( tmp_path )[ 0 ].read_text() )[ "attempts" ] == 1

    def test_the_sweep_leaves_out_the_given_id_and_audit_inputs_reads_a_shortlist_receipt( self, tmp_path ):
        asked = []
        def ask( need, exclude, ctx, **kw ):
            asked.append( exclude )
            return result_of()
        rs.sweep_of( lambda name: None, ask )( "n1", "py", exclude_id="d1" )
        rs.sweep_of( lambda name: None, ask )( "n1", "py" )
        assert asked == [ "d1", None ]
        receipt = { "tool": "check_exists", "query": "q", "language": "py", "index_sha": "i", "verdict": "NEW", "candidate_stage": { "ids": [ "a" ], "manifest_hash": "g" } }
        assert rs.audit_inputs( receipt ) == ( "q", "py", "g", "i", { "verdict": "NEW", "candidate_ids": [ "a" ] } )

    def test_the_drain_stops_at_the_weekly_cap_it_is_given( self, tmp_path ):
        queue_up( tmp_path, [ "n1", "n2" ] )
        out = rs.drain( tmp_path, lambda name: None, lambda *a, **k: result_of( ids=( "z", ) ), DAY, 10_000, 1 )
        assert ( out[ "audited" ], out[ "stopped_by" ] ) == ( 1, "weekly_cap" )

    def test_without_a_ceiling_the_result_keeps_its_five_keys_and_tokens_are_ignored( self, tmp_path ):
        queue_up( tmp_path, [ "n1" ] )
        out = sa.run_pending( tmp_path, lambda need: { "verdict": "REUSE", "causal_ids": [ "z" ] }, DAY )
        assert sorted( out ) == [ "audited", "corrupt", "dropped", "failed", "receipts" ]

    def test_pass_language_hands_the_items_language_to_the_sweep( self, tmp_path ):
        sa.enqueue_if_sampled( tmp_path, "n1", "ts", SET_ID, INDEX, LIVE, DAY, rate=1 )
        seen = []
        def sweep( need, language ):
            seen.append( ( need, language ) )
            return { "verdict": "REUSE", "causal_ids": [ "z" ] }
        sa.run_pending( tmp_path, sweep, DAY, pass_language=True )
        assert seen == [ ( "n1", "ts" ) ]


class TestReadCeiling:
    """The ceiling has no default."""

    def test_a_positive_whole_number_is_read( self ):
        assert rs.read_ceiling( reader_of( { rs.CEILING_KEY: " 4000 " } ) ) == 4000

    @pytest.mark.parametrize( "raw", [ None, "", "   ", "0", "-5", "abc", "2.5", "1e3" ] )
    def test_anything_else_is_refused_by_name( self, raw ):
        with pytest.raises( CandidateError ) as caught: rs.read_ceiling( reader_of( { rs.CEILING_KEY: raw } ) )
        assert caught.value.code == rs.AUDIT_CEILING_UNSET

    def test_an_unreadable_file_is_refused_and_names_the_read_error( self ):
        def broken( key ): raise OSError( "disk gone" )
        with pytest.raises( CandidateError ) as caught: rs.read_ceiling( broken )
        assert caught.value.code == rs.AUDIT_CEILING_UNSET and "disk gone" in caught.value.detail

    def test_the_shipped_ini_holds_the_switch_on_and_the_ceiling_at_five_million( self ):
        import cosa.utils.util as cu
        lines = { line.split( "=", 1 )[ 0 ].strip(): line.split( "=", 1 )[ 1 ].strip() for line in open( cu.get_project_root() + "/src/conf/lupin-app.ini", encoding="utf-8" )
                  if line.startswith( "reuse shadow audit" ) }
        assert lines == { rs.ENABLED_KEY: "true", rs.CEILING_KEY: "5000000", rs.LIFETIME_KEY: "100000000", rs.WEEKLY_CAP_KEY: "4", rs.BUDGETS_KEY: "true" }

    def test_both_keys_are_explained_in_the_splainer_file( self ):
        import cosa.utils.util as cu
        text = open( cu.get_project_root() + "/src/conf/lupin-app-splainer.ini", encoding="utf-8" ).read()
        assert all( f"\n{key}" in text for key in ( rs.ENABLED_KEY, rs.CEILING_KEY, rs.LIFETIME_KEY, rs.WEEKLY_CAP_KEY, rs.BUDGETS_KEY ) )


class TestQueueLookup:
    """The hook that offers a served lookup to the queue."""

    def test_nothing_happens_while_the_audit_is_off( self, tmp_path ):
        assert rs.queue_lookup( tmp_path, receipt_of( sampled_need() ), DAY, reader_of( { rs.ENABLED_KEY: "false" } ) ) is None
        assert not ( tmp_path / "receipts" ).exists() and not ( tmp_path / "shadow-pending" ).exists()

    def test_a_sampled_lookup_is_queued_with_its_redacted_need( self, tmp_path ):
        need = sampled_need()
        key  = rs.queue_lookup( tmp_path, receipt_of( need, query=need ), DAY, reader_of( ON ) )
        item = json.loads( queue_files( tmp_path )[ 0 ].read_text() )
        assert key == item[ "id" ] and item[ "need" ] == need
        assert item[ "live" ] == LIVE and item[ "generation" ] == SET_ID and item[ "index_sha" ] == INDEX and item[ "language" ] == "py"

    def test_an_unsampled_lookup_is_counted_and_not_queued( self, tmp_path ):
        assert rs.queue_lookup( tmp_path, receipt_of( unsampled_need() ), DAY, reader_of( ON ) ) is None
        assert sa.daily_volume( tmp_path ) == { DAY: { "lookups": 1, "audits": 0 } } and queue_files( tmp_path ) == []

    @pytest.mark.parametrize( "extra", [ { "tool": "fetch_similar" }, { "sweep_only": True }, { "include_tests": True }, { "question": "provides" }, { "exclude_id": "x" } ] )
    def test_measurement_and_neighbour_lookups_are_never_queued( self, tmp_path, extra ):
        assert rs.queue_lookup( tmp_path, receipt_of( sampled_need(), **extra ), DAY, reader_of( ON ) ) is None
        assert not ( tmp_path / "receipts" ).exists()

    def test_a_lookup_with_no_candidate_stage_is_never_queued( self, tmp_path ):
        receipt = receipt_of( sampled_need() )
        del receipt[ "candidate_stage" ]
        assert rs.queue_lookup( tmp_path, receipt, DAY, reader_of( ON ) ) is None

    def test_a_lookup_whose_stage_failed_is_never_queued( self, tmp_path ):
        receipt = receipt_of( sampled_need( None, SET_ID ) )       # sampled whatever the set id, so only the error guard keeps it out
        receipt[ "candidate_stage" ] = { "ids": [], "manifest_hash": None, "error": { "code": "X", "detail": "y" } }
        assert rs.queue_lookup( tmp_path, receipt, DAY, reader_of( ON ) ) is None
        assert queue_files( tmp_path ) == [] and not ( tmp_path / "receipts" ).exists()


class TestLiveLookupHook:
    """check_exists_impl offers each answer to the queue; a queue failure stays hidden."""

    def stub( self, monkeypatch, receipt ):
        monkeypatch.setattr( reuse_tools, "run_question", lambda *a, **k: receipt )
        monkeypatch.setattr( reuse_tools, "_public", lambda r: { "status": "ok", "receipt_id": "r1" } )

    def test_a_served_lookup_is_queued_when_the_audit_is_on( self, tmp_path, monkeypatch ):
        need = sampled_need()
        self.stub( monkeypatch, receipt_of( need ) )
        monkeypatch.setattr( lt, "read_value", lambda key, reader=None, errors=None: ON[ key ] )
        out = reuse_tools.check_exists_impl( need, type( "Ctx", ( ), { "data": tmp_path } )(), language="py" )
        assert out == { "status": "ok", "receipt_id": "r1" } and len( queue_files( tmp_path ) ) == 1

    def test_nothing_is_queued_when_the_audit_is_off( self, tmp_path, monkeypatch ):
        need = sampled_need()
        self.stub( monkeypatch, receipt_of( need ) )
        monkeypatch.setattr( lt, "read_value", lambda key, reader=None, errors=None: "false" )
        reuse_tools.check_exists_impl( need, type( "Ctx", ( ), { "data": tmp_path } )(), language="py" )
        assert queue_files( tmp_path ) == []

    def test_a_queue_failure_is_printed_and_the_answer_is_unchanged( self, tmp_path, monkeypatch, capsys ):
        self.stub( monkeypatch, receipt_of( "need" ) )
        def boom( *a, **k ): raise OSError( "disk full" )
        monkeypatch.setattr( rs, "queue_lookup", boom )
        out = reuse_tools.check_exists_impl( "need", type( "Ctx", ( ), { "data": tmp_path } )(), language="py" )
        assert out == { "status": "ok", "receipt_id": "r1" }
        assert "shadow audit queue failed: disk full" in capsys.readouterr().err

    def test_a_candidate_error_from_the_queue_is_printed_too( self, tmp_path, monkeypatch, capsys ):
        self.stub( monkeypatch, receipt_of( "need" ) )
        def boom( *a, **k ): raise CandidateError( sa.AUDIT_RATE_INVALID, "2" )
        monkeypatch.setattr( rs, "queue_lookup", boom )
        reuse_tools.check_exists_impl( "need", type( "Ctx", ( ), { "data": tmp_path } )(), language="py" )
        assert "AUDIT_RATE_INVALID" in capsys.readouterr().err

    def test_a_refused_lookup_queues_nothing_and_keeps_its_error( self, tmp_path, monkeypatch ):
        def refuse( *a, **k ): raise reuse_tools.ReuseError( "BAD_BUDGET", "x" )
        monkeypatch.setattr( reuse_tools, "run_question", refuse )
        out = reuse_tools.check_exists_impl( "need", type( "Ctx", ( ), { "data": tmp_path } )(), language="py" )
        assert out == { "status": "error", "error": "BAD_BUDGET", "detail": "x" } and not ( tmp_path / "receipts" ).exists()


class TestSweepAdapter:
    """The adapter between run_pending and the full-sweep lookup."""

    def test_the_audit_sees_the_shortlist_ids_and_the_summed_tokens( self ):
        asked, names = [], []
        def ask( need, exclude_id, ctx, **kw ):
            asked.append( ( need, exclude_id, ctx, kw ) )
            return result_of( ids=( "z1", "z2" ) )
        sweep = rs.sweep_of( lambda name: names.append( name ) or name, ask )
        assert sweep( "n1", "ts" ) == { "verdict": "REUSE", "causal_ids": [ "z1", "z2" ], "tokens": 100 }
        assert asked[ 0 ][ 1 ] is None and asked[ 0 ][ 3 ] == { "language": "ts" }

    def test_an_uncertain_verdict_carries_its_cause( self ):
        sweep = rs.sweep_of( lambda name: None, lambda *a, **k: result_of( verdict="UNCERTAIN_READ_SOURCE", ids=() ) )
        assert sweep( "n", "py" )[ "cause" ] == "NO_MATCH"

    def test_every_sweep_gets_its_own_run_name( self ):
        names = []
        sweep = rs.sweep_of( lambda name: names.append( name ), lambda *a, **k: result_of() )
        sweep( "n1", "py" )
        sweep( "n2", "py" )
        assert len( set( names ) ) == 2 and all( re.fullmatch( rf"{rs.SWEEP_RUN_PREFIX}-\d{{4}}-\d{{2}}-\d{{2}}-{os.getpid()}-\d+-[0-9a-f]{{8}}", name ) for name in names )

    def test_an_error_answer_is_refused_by_name( self ):
        sweep = rs.sweep_of( lambda name: None, lambda *a, **k: { "status": "error", "error": "INDEX_STALE" } )
        with pytest.raises( CandidateError ) as caught: sweep( "n", "py" )
        assert caught.value.code == rs.AUDIT_SWEEP_REFUSED and "INDEX_STALE" in caught.value.detail


class TestDrain:
    """A whole drain over a queue, with a fake lookup."""

    def test_a_drain_audits_under_the_ceiling_and_stores_receipts( self, tmp_path ):
        queue_up( tmp_path, [ "n1", "n2", "n3" ] )
        out = rs.drain( tmp_path, lambda name: None, lambda *a, **k: result_of( ids=( "z", ) ), DAY, 250, 4 )
        assert ( out[ "audited" ], out[ "spent_tokens" ], out[ "stopped_by" ] ) == ( 2, 200, "ceiling" )
        assert len( sa.load_receipts( tmp_path ) ) == 2 and len( queue_files( tmp_path ) ) == 1


class TestCronLines:
    """The two cron lines."""

    def test_both_lines_end_with_the_tag_and_name_the_wrapper_and_carried_settings( self ):
        daily, reboot = rs.cron_lines( "/repo", "/py", "/log", { "LUPIN_REUSE_JEV_PACK_SIZE": "8" } )
        assert daily.startswith( rs.CRON_SCHEDULE ) and reboot.startswith( "@reboot sleep 300 && " )
        for line in ( daily, reboot ):
            assert line.endswith( rs.CRON_TAG ) and "/repo/src/scripts/reuse-shadow-audit.sh" in line
            assert "LUPIN_REUSE_JEV_PACK_SIZE=8" in line and "REUSE_SHADOW_AUDIT_PYTHON=/py" in line

    def test_without_carried_settings_the_lines_still_build( self ):
        assert len( rs.cron_lines( "/repo", "/py", "/log" ) ) == 2


class TestContextFactory:
    """The per-sweep context of the live drain."""

    def test_no_pack_size_is_refused_by_name( self ):
        with pytest.raises( CandidateError ) as caught: rs._context_factory( "/repo", {}, 100 )
        assert caught.value.code == rs.AUDIT_NEEDS_PACKED

    def test_each_context_carries_the_ceiling_and_its_run_name_and_the_environment_is_restored( self, monkeypatch ):
        seen = []
        monkeypatch.setattr( reuse_tools, "context_from_environment", lambda root: seen.append( ( root, os.environ[ reuse_tools.CEILING_VARIABLE ],
                                                                                              os.environ[ reuse_tools.RUN_NAME_VARIABLE ], os.environ[ reuse_tools.PACK_SIZE_VARIABLE ] ) ) or "ctx" )
        monkeypatch.setenv( reuse_tools.CEILING_VARIABLE, "old-ceiling" )
        monkeypatch.setenv( "SHADOW_TEST_BYSTANDER", "keep" )
        monkeypatch.delenv( reuse_tools.RUN_NAME_VARIABLE, raising=False )
        factory = rs._context_factory( "/repo", { reuse_tools.PACK_SIZE_VARIABLE: "8" }, 1234 )
        assert factory( "run-1" ) == "ctx"
        assert seen == [ ( "/repo", "1234", "run-1", "8" ) ]
        assert os.environ[ reuse_tools.CEILING_VARIABLE ] == "old-ceiling" and os.environ[ "SHADOW_TEST_BYSTANDER" ] == "keep"
        assert reuse_tools.RUN_NAME_VARIABLE not in os.environ and reuse_tools.PACK_SIZE_VARIABLE not in os.environ

    def test_the_environment_is_restored_when_the_context_fails( self, monkeypatch ):
        def boom( root ): raise reuse_tools.ReuseError( "BAD_SPEND_LIMIT", "x" )
        monkeypatch.setattr( reuse_tools, "context_from_environment", boom )
        monkeypatch.setenv( "SHADOW_TEST_BYSTANDER", "keep" )
        monkeypatch.setenv( reuse_tools.RUN_NAME_VARIABLE, "old-run" )
        with pytest.raises( reuse_tools.ReuseError ): rs._context_factory( "/repo", { reuse_tools.PACK_SIZE_VARIABLE: "8" }, 5 )( "r" )
        assert os.environ[ "SHADOW_TEST_BYSTANDER" ] == "keep" and os.environ[ reuse_tools.RUN_NAME_VARIABLE ] == "old-run"


class FakeOut:
    """A write target that keeps what was printed."""

    def __init__( self ): self.text = ""
    def write( self, s ): self.text += s
    def flush( self ): pass


@pytest.fixture
def world( tmp_path, monkeypatch ):
    """The data folder is a temporary folder."""
    monkeypatch.setattr( reuse_tools, "data_dir", lambda root: tmp_path / "data" )
    ledger_file = tmp_path / "ledger.jsonl"
    reuse_ledger.AccountLedger.create( ledger_file, 10**9, "test", "empty fleet ledger for main" )
    monkeypatch.setattr( reuse_ledger, "ledger_path", lambda root: ledger_file )
    return { "root": str( tmp_path / "repo" ), "data": tmp_path / "data" }


def run_main( world, argv, environ=None, reader=None, **extra ):
    """Run main and return ( code, stdout, stderr )."""
    out, err = FakeOut(), FakeOut()
    code     = rs.main( argv, environ={ "LUPIN_ROOT": world[ "root" ], **( environ or { } ) }, out=out, err=err, reader=reader, **extra )
    return code, out.text, err.text


class TestMain:
    """The command line."""

    def test_print_install_prints_both_lines_and_changes_nothing( self, world ):
        rc, out, _ = run_main( world, [ "--print-install", "--python", "/py" ], environ={ "DEEPILY_DATA_DIR": "/mnt/d", reuse_tools.PACK_SIZE_VARIABLE: "8" } )
        assert rc == 0 and out.count( rs.CRON_TAG ) == 2 and "DEEPILY_DATA_DIR=/mnt/d" in out and f"{reuse_tools.PACK_SIZE_VARIABLE}=8" in out
        assert not world[ "data" ].exists()

    def test_install_status_and_uninstall_keep_other_lines( self, world, cron ):
        cron[ "file" ].write_text( "0 * * * * other\n" )
        env = cron[ "env" ]
        rc, out, _ = run_main( world, [ "--install", "--python", "/py" ], environ=env, crontab_cmd=cron[ "cmd" ] )
        assert ( rc, out.strip() ) == ( 0, "installed: 2 lines" )
        assert "lock-enter " + rs.LOCK_OWNER in cron[ "log" ].read_text()
        assert run_main( world, [ "--status" ], environ=env, crontab_cmd=cron[ "cmd" ] )[ 1 ].strip() == "installed: 2 lines"
        assert run_main( world, [ "--uninstall" ], environ=env, crontab_cmd=cron[ "cmd" ] )[ 1 ].strip() == "uninstalled"
        text = cron[ "file" ].read_text()
        assert rs.CRON_TAG not in text and "other" in text

    def test_status_reads_not_installed_when_there_is_no_crontab( self, world, cron ):
        assert run_main( world, [ "--status" ], environ=cron[ "env" ], crontab_cmd=cron[ "cmd" ] )[ 1 ].strip() == "not installed"

    def test_an_install_without_the_shared_lock_is_refused_and_returns_one( self, world, cron ):
        rc, _, err = run_main( world, [ "--install" ], environ={ }, crontab_cmd=cron[ "cmd" ] )
        assert rc == 1 and err.startswith( "reuse-shadow-audit:" ) and not cron[ "file" ].exists()

    def test_a_switched_off_job_logs_one_line_and_returns_three_before_reading_the_ceiling( self, world ):
        rc, out, _ = run_main( world, [ ], reader=reader_of( { rs.ENABLED_KEY: "false" } ), factory=lambda name: pytest.fail( "no context" ) )
        assert rc == rs.EXIT_DISABLED and json.loads( out ) == { "ran": False, "reason": "switched off" }
        assert "switched off" in ( world[ "data" ] / "shadow-audit" / rs.LOG_NAME ).read_text()

    def test_a_blank_ceiling_is_exit_two_with_the_code_and_no_sweep( self, world ):
        queue_up( world[ "data" ], [ "n1" ] )
        rc, out, _ = run_main( world, [ ], reader=reader_of( { rs.ENABLED_KEY: "true" } ), factory=lambda name: pytest.fail( "no context" ), ask=lambda *a, **k: pytest.fail( "no sweep" ) )
        assert rc == rs.EXIT_NAMED and json.loads( out )[ "error" ] == rs.AUDIT_CEILING_UNSET
        assert len( queue_files( world[ "data" ] ) ) == 1

    def test_a_blank_lifetime_limit_is_exit_two_with_its_own_code_and_no_sweep( self, world ):
        queue_up( world[ "data" ], [ "n1" ] )
        rc, out, _ = run_main( world, [ ], reader=reader_of( { **ON, rs.LIFETIME_KEY: "" } ), factory=lambda name: pytest.fail( "no context" ), ask=lambda *a, **k: pytest.fail( "no sweep" ) )
        assert rc == rs.EXIT_NAMED and json.loads( out )[ "error" ] == rs.AUDIT_LIFETIME_UNSET and len( queue_files( world[ "data" ] ) ) == 1

    def test_a_drain_prints_its_summary_and_returns_zero( self, world ):
        queue_up( world[ "data" ], [ "n1", "n2" ] )
        rc, out, _ = run_main( world, [ ], reader=reader_of( ON ), factory=lambda name: name, ask=lambda *a, **k: result_of() )
        assert rc == 0 and json.loads( out ) == { "audited": 2, "failed": 0, "corrupt": 0, "dropped": 0, "spent_tokens": 200, "stopped_by": None }
        assert "drain done" in ( world[ "data" ] / "shadow-audit" / rs.LOG_NAME ).read_text()

    def test_an_empty_queue_is_a_clean_zero( self, world ):
        rc, out, _ = run_main( world, [ ], reader=reader_of( ON ), factory=lambda name: name, ask=lambda *a, **k: result_of() )
        assert rc == 0 and json.loads( out )[ "audited" ] == 0

    def test_a_drain_where_every_item_failed_returns_one( self, world ):
        queue_up( world[ "data" ], [ "n1" ] )
        rc, out, _ = run_main( world, [ ], reader=reader_of( ON ), factory=lambda name: name, ask=lambda *a, **k: { "status": "error", "error": "INDEX_STALE" } )
        assert rc == rs.EXIT_FAILED and json.loads( out )[ "failed" ] == 1

    def test_a_missing_pack_size_is_exit_two_when_no_factory_is_injected( self, world ):
        rc, out, _ = run_main( world, [ ], reader=reader_of( ON ) )
        assert rc == rs.EXIT_NAMED and json.loads( out )[ "error" ] == rs.AUDIT_NEEDS_PACKED

    def test_the_root_defaults_to_the_working_directory( self, world, monkeypatch, tmp_path ):
        monkeypatch.chdir( tmp_path )
        out = FakeOut()
        assert rs.main( [ "--print-install" ], environ={ }, out=out ) == 0 and str( tmp_path ) in out.text

    def test_the_default_arguments_read_the_process_environment_and_clock( self, world, monkeypatch, capsys ):
        monkeypatch.setenv( "LUPIN_ROOT", world[ "root" ] )
        assert rs.main( [ "--print-install" ] ) == 0
        assert rs.CRON_TAG in capsys.readouterr().out


class TestTheRealUnknownEntryAnswer:
    """The drop rule against the real lookup tool's words, not an error written by hand."""

    def test_the_real_unknown_entry_answer_through_sweep_of_drops_the_item_on_its_third_attempt( self, env, tmp_path ):
        data     = tmp_path / "audit"
        sweep    = rs.sweep_of( lambda name: ctx_for( env, Recorder() ), reuse_tools.unstored_need_impl )
        real     = reuse_tools.unstored_need_impl( NEED, "no.such.id", ctx_for( env, Recorder() ), language="py" )
        assert real == { "status": "error", "error": "UNKNOWN_ENTRY", "entry": "no.such.id" }, "the tool's own answer, before any request"
        sa.enqueue_pending( data, NEED, "py", SET_ID, INDEX, LIVE, DAY, known_miss=True, exclude_id="no.such.id", tie="ruling" )
        outs = [ sa.run_pending( data, sweep, DAY, pass_language=True ) for _ in range( sa.UNKNOWN_ENTRY_TRIES ) ]
        assert [ o[ "dropped" ] for o in outs ] == [ 0, 0, 1 ] and [ o[ "failed" ] for o in outs ] == [ 1, 1, 1 ]
        assert queue_files( data ) == [], "gone on the third attempt, with no receipt"

    def test_the_drop_is_red_when_sweep_of_wraps_the_error_text_differently( self, env, tmp_path, monkeypatch ):
        data  = tmp_path / "audit"
        real  = reuse_tools.unstored_need_impl
        wrapped = lambda need, exclude, ctx, **kw: { **real( need, exclude, ctx, **kw ), "error": "error: UNKNOWN_ENTRY" }
        sweep = rs.sweep_of( lambda name: ctx_for( env, Recorder() ), wrapped )
        sa.enqueue_pending( data, NEED, "py", SET_ID, INDEX, LIVE, DAY, known_miss=True, exclude_id="no.such.id" )
        outs = [ sa.run_pending( data, sweep, DAY, pass_language=True ) for _ in range( sa.UNKNOWN_ENTRY_TRIES + 1 ) ]
        assert [ o[ "dropped" ] for o in outs ] == [ 0 ] * ( sa.UNKNOWN_ENTRY_TRIES + 1 ) and len( queue_files( data ) ) == 1, "a different wording is never dropped"



FIXTURE = os.path.join( os.path.dirname( __file__ ), "..", "fixtures", "reuse_shadow_audit", "real-shadow-audit-ledger-lines.jsonl" )
REAL_SPEND = 3_324_735                     # the one real audit, run 2f6b83a1, as the ledger held it on 3 Nov 2026
CEILING    = 5_000_000


def real_ledger( tmp_path ):
    """The lines captured from the real ledger: its limit row and every shadow-audit row."""
    path = tmp_path / "real-ledger.jsonl"
    path.write_text( open( FIXTURE, encoding="utf-8" ).read() )
    return reuse_ledger.AccountLedger( path )


def spent_row( run, tokens ):
    """One spend row on a run, in the shape the real ledger writes."""
    return json.dumps( { "at": "2026-11-03T12:00:00-0500", "kind": "spend", "run": run, "tokens": tokens }, sort_keys=True ) + "\n"


def add_audit_spend( ledger, tokens, closed=True ):
    """Add one more shadow-audit run to a ledger, so its total reaches a chosen figure."""
    run = reuse_ledger.make_run_name( rs.SWEEP_RUN_PREFIX )
    ledger.begin_run( run, 1 )
    ledger.spend( run, tokens )
    if closed: ledger.end_run( run )


class TestLifetimeLimit:
    """Rick's 3 Nov ruling: a drain refuses once lifetime audit spend would pass the INI limit."""

    def test_the_fixture_holds_real_lines_and_totals_the_measured_spend( self, tmp_path ):
        kinds = [ json.loads( line )[ "kind" ] for line in open( FIXTURE, encoding="utf-8" ) ]
        assert kinds.count( "limit" ) == 1 and kinds.count( "begin" ) == 1 and kinds.count( "end" ) == 1 and kinds.count( "spend" ) == 203
        assert real_ledger( tmp_path ).held_by_prefix( rs.LEDGER_RUN_PREFIX ) == REAL_SPEND

    def test_a_drain_just_under_the_limit_runs( self, tmp_path ):
        led = real_ledger( tmp_path )
        assert rs.check_lifetime_limit( led, REAL_SPEND + CEILING, CEILING ) == REAL_SPEND          # spent + ceiling equals the limit: it does not pass it

    def test_a_drain_at_the_limit_is_refused( self, tmp_path ):
        led = real_ledger( tmp_path )
        with pytest.raises( CandidateError ) as caught: rs.check_lifetime_limit( led, REAL_SPEND, CEILING )     # spent equals the limit
        assert caught.value.code == rs.AUDIT_LIFETIME_REACHED and str( REAL_SPEND ) in caught.value.detail and rs.LIFETIME_KEY in caught.value.detail

    def test_a_ceiling_that_would_cross_the_limit_is_refused_though_the_spend_is_under_it( self, tmp_path ):
        led = real_ledger( tmp_path )
        with pytest.raises( CandidateError ) as caught: rs.check_lifetime_limit( led, REAL_SPEND + CEILING - 1, CEILING )   # one token short of room
        assert caught.value.code == rs.AUDIT_LIFETIME_REACHED

    def test_an_open_audit_run_counts_at_its_ceiling( self, tmp_path ):
        led = real_ledger( tmp_path )
        add_audit_spend( led, 10, closed=False )                       # begun at ceiling 1, spent 10: counts at 10
        with pytest.raises( CandidateError ): rs.check_lifetime_limit( led, REAL_SPEND + 10 + CEILING - 1, CEILING )
        assert rs.check_lifetime_limit( led, REAL_SPEND + 10 + CEILING, CEILING ) == REAL_SPEND + 10

    def test_only_shadow_audit_runs_are_counted( self, tmp_path ):
        led = real_ledger( tmp_path )
        other = reuse_ledger.make_run_name( "s1-q1-single" )
        led.begin_run( other, 1 )
        led.spend( other, 9_000_000 )
        led.end_run( other )
        assert rs.check_lifetime_limit( led, REAL_SPEND + CEILING, CEILING ) == REAL_SPEND

    @pytest.mark.parametrize( "raw", [ None, "", "   ", "0", "-5", "1e8", "100M", "2.5" ] )
    def test_a_blank_or_garbled_limit_is_a_named_error_never_unlimited( self, raw ):
        with pytest.raises( CandidateError ) as caught: rs.read_lifetime_limit( reader_of( { rs.LIFETIME_KEY: raw } ) )
        assert caught.value.code == rs.AUDIT_LIFETIME_UNSET and rs.LIFETIME_KEY in caught.value.detail

    def test_a_good_limit_is_read_and_an_unreadable_file_names_the_read_error( self ):
        assert rs.read_lifetime_limit( reader_of( { rs.LIFETIME_KEY: " 100000000 " } ) ) == 100_000_000
        def broken( key ): raise OSError( "disk gone" )
        with pytest.raises( CandidateError ) as caught: rs.read_lifetime_limit( broken )
        assert caught.value.code == rs.AUDIT_LIFETIME_UNSET and "disk gone" in caught.value.detail

    def test_a_ledger_that_cannot_be_read_refuses_by_name( self, tmp_path ):
        with pytest.raises( CandidateError ) as caught: rs.check_lifetime_limit( reuse_ledger.AccountLedger( tmp_path / "missing.jsonl" ), 10**9, CEILING )
        assert caught.value.code == rs.AUDIT_LEDGER_UNREADABLE

    def test_there_is_no_constant_for_the_limit_in_the_module( self ):
        source = open( rs.__file__, encoding="utf-8" ).read()
        assert "100000000" not in source and "100_000_000" not in source

    def test_changing_only_the_ini_value_changes_the_decision( self, world, tmp_path ):
        led = real_ledger( tmp_path )
        queue_up( world[ "data" ], [ "n1" ] )
        keep = { **ON, rs.CEILING_KEY: str( CEILING ) }
        refused = run_main( world, [ ], reader=reader_of( { **keep, rs.LIFETIME_KEY: str( REAL_SPEND + CEILING - 1 ) } ), ledger=led, factory=lambda name: pytest.fail( "no context" ), ask=lambda *a, **k: pytest.fail( "no sweep" ) )
        allowed = run_main( world, [ ], reader=reader_of( { **keep, rs.LIFETIME_KEY: str( REAL_SPEND + CEILING ) } ), ledger=led, factory=lambda name: name, ask=lambda *a, **k: result_of() )
        assert refused[ 0 ] == rs.EXIT_NAMED and json.loads( refused[ 1 ] )[ "error" ] == rs.AUDIT_LIFETIME_REACHED
        assert allowed[ 0 ] == 0 and json.loads( allowed[ 1 ] )[ "audited" ] == 1

    def test_a_refused_drain_spends_nothing_logs_one_line_and_leaves_the_queue_and_ledger_alone( self, world, tmp_path ):
        led = real_ledger( tmp_path )
        before = led.path.read_bytes()
        queue_up( world[ "data" ], [ "n1", "n2" ] )
        rc, out, _ = run_main( world, [ ], reader=reader_of( { **ON, rs.LIFETIME_KEY: str( REAL_SPEND ) } ), ledger=led, factory=lambda name: pytest.fail( "no context" ), ask=lambda *a, **k: pytest.fail( "no sweep" ) )
        assert rc == rs.EXIT_NAMED and json.loads( out )[ "error" ] == rs.AUDIT_LIFETIME_REACHED
        assert len( queue_files( world[ "data" ] ) ) == 2 and led.path.read_bytes() == before
        assert "drain refused" in ( world[ "data" ] / "shadow-audit" / rs.LOG_NAME ).read_text()

    def test_main_builds_the_fleet_ledger_from_the_root_when_none_is_given( self, world ):
        rc, out, _ = run_main( world, [ ], reader=reader_of( ON ), factory=lambda name: name, ask=lambda *a, **k: result_of() )       # world points ledger_path at an empty ledger
        assert rc == 0 and json.loads( out )[ "audited" ] == 0


class TestWeeklyCapAndCapacityFollowTheIni:
    """The weekly cap and the capacity arithmetic read the drain's INI keys, with no fallback."""

    @pytest.mark.parametrize( "raw", [ None, "", "0", "-1", "four", "4.0" ] )
    def test_a_bad_weekly_cap_is_a_named_error_never_unlimited( self, raw ):
        with pytest.raises( CandidateError ) as caught: rs.read_weekly_cap( reader_of( { rs.WEEKLY_CAP_KEY: raw } ) )
        assert caught.value.code == rs.AUDIT_WEEKLY_CAP_UNSET and rs.WEEKLY_CAP_KEY in caught.value.detail

    def test_a_blank_weekly_cap_stops_the_drain_before_any_sweep( self, world ):
        queue_up( world[ "data" ], [ "n1" ] )
        rc, out, _ = run_main( world, [ ], reader=reader_of( { **ON, rs.WEEKLY_CAP_KEY: "" } ), factory=lambda name: pytest.fail( "no context" ), ask=lambda *a, **k: pytest.fail( "no sweep" ) )
        assert rc == rs.EXIT_NAMED and json.loads( out )[ "error" ] == rs.AUDIT_WEEKLY_CAP_UNSET and len( queue_files( world[ "data" ] ) ) == 1

    def test_changing_only_the_weekly_cap_in_the_ini_changes_how_many_audits_run( self, world ):
        queue_up( world[ "data" ], [ "n1", "n2" ], day=DAY )
        first  = run_main( world, [ ], reader=reader_of( { **ON, rs.WEEKLY_CAP_KEY: "1" } ), factory=lambda name: name, ask=lambda *a, **k: result_of() )
        second = run_main( world, [ ], reader=reader_of( { **ON, rs.WEEKLY_CAP_KEY: "2" } ), factory=lambda name: name, ask=lambda *a, **k: result_of() )
        assert ( json.loads( first[ 1 ] )[ "audited" ], json.loads( first[ 1 ] )[ "stopped_by" ] ) == ( 1, "weekly_cap" )       # cap 1: one audit, one left queued
        assert ( json.loads( second[ 1 ] )[ "audited" ], json.loads( second[ 1 ] )[ "stopped_by" ] ) == ( 1, None )             # cap raised to 2 in the INI alone: the other one runs

    def test_capacity_takes_the_audit_ceiling_and_weekly_cap_from_the_ini( self, tmp_path ):
        led = real_ledger( tmp_path )
        few  = rs.live_capacity( led, reader=reader_of( { rs.CEILING_KEY: "1000", rs.WEEKLY_CAP_KEY: "2" } ) )
        more = rs.live_capacity( led, reader=reader_of( { rs.CEILING_KEY: "2000", rs.WEEKLY_CAP_KEY: "3" } ) )
        assert few[ "audit_week_tokens" ] == 2000 and more[ "audit_week_tokens" ] == 6000
        assert few[ "open_tokens" ] == reuse_ledger.SEATS_AT_ONCE * reuse_ledger.LOOKUP_CEILING_TOKENS + 1000

    def test_capacity_refuses_a_bad_key_by_name_and_passes_its_other_settings_on( self, tmp_path ):
        led = real_ledger( tmp_path )
        with pytest.raises( CandidateError ) as caught: rs.live_capacity( led, reader=reader_of( { rs.CEILING_KEY: "", rs.WEEKLY_CAP_KEY: "2" } ) )
        assert caught.value.code == rs.AUDIT_CEILING_UNSET
        with pytest.raises( CandidateError ) as caught: rs.live_capacity( led, reader=reader_of( { rs.CEILING_KEY: "1000" } ) )
        assert caught.value.code == rs.AUDIT_WEEKLY_CAP_UNSET
        assert rs.live_capacity( led, { "seats": 1, "lookup_ceiling": 10 }, reader_of( { rs.CEILING_KEY: "5", rs.WEEKLY_CAP_KEY: "1" } ) )[ "open_tokens" ] == 15


class TestBudgetsSwitch:
    """Rick's toggle: true applies both budgets; the drain ceiling holds either way."""

    @pytest.mark.parametrize( "raw, expected", [ ( "true", True ), ( " TRUE ", True ), ( "False", False ), ( "false", False ) ] )
    def test_true_and_false_are_read_in_any_case( self, raw, expected ):
        assert rs.read_budgets_enabled( reader_of( { rs.BUDGETS_KEY: raw } ) ) is expected

    @pytest.mark.parametrize( "raw", [ None, "", "  ", "yes", "0", "1", "ture", "off" ] )
    def test_a_missing_or_garbled_switch_is_a_named_error_never_false( self, raw ):
        with pytest.raises( CandidateError ) as caught: rs.read_budgets_enabled( reader_of( { rs.BUDGETS_KEY: raw } ) )
        assert caught.value.code == rs.AUDIT_BUDGETS_SWITCH and rs.BUDGETS_KEY in caught.value.detail

    def test_an_unreadable_file_names_the_read_error( self ):
        def broken( key ): raise OSError( "disk gone" )
        with pytest.raises( CandidateError ) as caught: rs.read_budgets_enabled( broken )
        assert caught.value.code == rs.AUDIT_BUDGETS_SWITCH and "disk gone" in caught.value.detail

    def test_a_garbled_switch_stops_the_drain_before_any_sweep( self, world ):
        queue_up( world[ "data" ], [ "n1" ] )
        rc, out, _ = run_main( world, [ ], reader=reader_of( { **ON, rs.BUDGETS_KEY: "" } ), factory=lambda name: pytest.fail( "no context" ), ask=lambda *a, **k: pytest.fail( "no sweep" ) )
        assert rc == rs.EXIT_NAMED and json.loads( out )[ "error" ] == rs.AUDIT_BUDGETS_SWITCH and len( queue_files( world[ "data" ] ) ) == 1

    def test_flipping_only_the_switch_changes_a_lifetime_refusal_into_a_run( self, world, tmp_path ):
        led   = real_ledger( tmp_path )
        tight = { **ON, rs.LIFETIME_KEY: str( REAL_SPEND ) }                     # at the limit: refused while the budgets are on
        queue_up( world[ "data" ], [ "n1" ] )
        on  = run_main( world, [ ], reader=reader_of( tight ), ledger=led, factory=lambda name: pytest.fail( "no context" ), ask=lambda *a, **k: pytest.fail( "no sweep" ) )
        off = run_main( world, [ ], reader=reader_of( { **tight, rs.BUDGETS_KEY: "false" } ), ledger=led, factory=lambda name: name, ask=lambda *a, **k: result_of() )
        assert on[ 0 ] == rs.EXIT_NAMED and json.loads( on[ 1 ] )[ "error" ] == rs.AUDIT_LIFETIME_REACHED
        assert off[ 0 ] == 0 and json.loads( off[ 1 ] )[ "audited" ] == 1

    def test_switched_off_the_weekly_cap_is_not_applied_and_the_drain_logs_one_line( self, world ):
        queue_up( world[ "data" ], [ "n1", "n2", "n3" ] )
        rc, out, _ = run_main( world, [ ], reader=reader_of( { **ON, rs.BUDGETS_KEY: "false", rs.WEEKLY_CAP_KEY: "1" } ), factory=lambda name: name, ask=lambda *a, **k: result_of() )
        assert rc == 0 and json.loads( out )[ "audited" ] == 3 and json.loads( out )[ "stopped_by" ] is None
        assert ( world[ "data" ] / "shadow-audit" / rs.LOG_NAME ).read_text().count( "budgets are off" ) == 1

    def test_switched_off_the_lifetime_and_weekly_keys_are_not_even_read( self, world ):
        blank = { rs.ENABLED_KEY: "true", rs.CEILING_KEY: "5000", rs.BUDGETS_KEY: "false" }
        rc, out, _ = run_main( world, [ ], reader=reader_of( blank ), factory=lambda name: name, ask=lambda *a, **k: result_of() )
        assert rc == 0 and json.loads( out )[ "audited" ] == 0

    def test_switched_off_the_per_drain_ceiling_still_stops_the_drain( self, world ):
        queue_up( world[ "data" ], [ "n1", "n2" ] )
        rc, out, _ = run_main( world, [ ], reader=reader_of( { **ON, rs.BUDGETS_KEY: "false", rs.CEILING_KEY: "150" } ), factory=lambda name: name, ask=lambda *a, **k: result_of() )
        assert rc == 0 and json.loads( out )[ "audited" ] == 1 and json.loads( out )[ "stopped_by" ] == "ceiling"
        rc, out, _ = run_main( world, [ ], reader=reader_of( { **ON, rs.BUDGETS_KEY: "false", rs.CEILING_KEY: "" } ), factory=lambda name: pytest.fail( "no context" ) )
        assert rc == rs.EXIT_NAMED and json.loads( out )[ "error" ] == rs.AUDIT_CEILING_UNSET
