"""
The end-to-end runner's command line, on the stand-in transport.

The sample, the needs and the manifest are generated here with their own hashes. No live path is taken.
"""
import hashlib
import json

import pytest

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_e2e_run as run
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from tests.unit.test_reuse_e2e_run import IDS, ask_old, make_wide_repo


def put( path, record ):
    text = json.dumps( record, sort_keys=True )
    path.write_text( text, encoding="utf-8" )
    return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()


class Setup:
    """A scratch tree with generated inputs, and the argument lists that point at them."""

    def __init__( self, tmp_path ):
        self.root    = make_wide_repo( tmp_path )
        self.data    = tmp_path / "data"
        self.ledger  = tmp_path / "ledger.jsonl"
        members      = IDS[ :100 ]
        sample       = { "strata": { "has_exact_cluster": { "members": members[ :58 ] }, "near_only": { "members": members[ 58: ] } } }
        needs        = { "format": e2e.NEEDS_FORMAT, "needs": [ { "member": m, "need": f"A function number {i} that does a distinct job." } for i, m in enumerate( members ) ] }
        manifest     = { "exact": [ { "members": [ { "id": IDS[ i ] }, { "id": IDS[ i + 100 ] } ] } for i in range( 5 ) ], "near": [] }
        self.sample  = tmp_path / "sample.json";   self.sample_sha   = put( self.sample, sample )
        self.needs   = tmp_path / "needs.json";    self.needs_sha    = put( self.needs, needs )
        self.mani    = tmp_path / "manifest.json"; self.mani_sha     = put( self.mani, manifest )

    def plain( self, command ): return [ "--root", str( self.root ), "--data", str( self.data ), "--ledger", str( self.ledger ), command ]

    def args( self, *command, live=False, extra=() ):
        base = [ "--root", str( self.root ) ] + ( [ "--live" ] if live else [ "--data", str( self.data ), "--ledger", str( self.ledger ) ] )
        inputs = [ "--sample", str( self.sample ), "--sample-sha", self.sample_sha, "--needs", str( self.needs ), "--needs-sha", self.needs_sha,
                   "--manifest", str( self.mani ), "--manifest-sha", self.mani_sha ]
        return base + list( extra ) + list( command[ :1 ] ) + inputs + list( command[ 1: ] )


@pytest.fixture
def setup( tmp_path, capsys ):
    s = Setup( tmp_path )
    assert run.cli( [ "--root", str( s.root ), "--data", str( s.data ), "--ledger", str( s.ledger ), "ledger-init" ] ) == 0
    capsys.readouterr()
    return s


def test_ledger_init_is_for_a_stand_in_run_only( tmp_path, capsys ):
    s = Setup( tmp_path )
    assert run.cli( [ "--root", str( s.root ), "--live", "--data", str( s.data ), "--ledger", str( s.ledger ), "ledger-init" ] ) == 2
    assert "ledger-init is for a stand-in run" in capsys.readouterr().err and not s.ledger.exists()


def test_a_stand_in_run_needs_its_own_data_folder_and_ledger_and_will_not_use_the_real_ones( tmp_path ):
    s = Setup( tmp_path )
    assert run.cli( [ "--root", str( s.root ), "status" ] ) == 2
    assert run.cli( [ "--root", str( s.root ), "--data", str( s.data ), "status" ] ) == 2


def test_the_canary_the_approval_the_run_and_the_report_go_through_the_command_line( setup, capsys ):
    assert run.cli( setup.args( "canary", "--ceiling", "100000000" ) ) == 0
    out = capsys.readouterr().out
    assert "ledger total before the first send: 0" in out and "projection" in out
    assert run.cli( setup.args( "run", "--ceiling", "100000000" ) ) == 2                       # not approved yet
    capsys.readouterr()
    assert run.cli( setup.args( "approve", "--by", "cheech", "--why", "tokens read" ) ) == 0
    assert run.cli( setup.args( "run", "--ceiling", "300000000" ) ) == 0
    out = capsys.readouterr().out
    assert "95 searches" in out or "complete 95" in out
    assert run.cli( setup.args( "report" ) ) == 0
    out = capsys.readouterr().out
    assert "100 searches, one per twin group" in out and "no TypeScript or JavaScript" in out
    assert "old" in out and "twin on the shortlist" in out and "n run: 100 of 100" in out


def test_the_stand_in_folder_is_marked_and_a_live_run_will_not_read_it( setup ):
    assert run.cli( setup.plain( "status" ) ) == 0
    assert ( setup.data / rr.STAND_IN_MARKER ).exists()


def test_the_new_question_is_refused_until_it_is_wired_and_runs_once_it_is( setup, monkeypatch, capsys ):
    monkeypatch.setattr( run, "NEW_ASK", None )
    assert run.cli( setup.args( "canary", "--ceiling", "100000000", extra=[ "--questions", "old,new" ] ) ) == 2
    assert "new question is not wired" in capsys.readouterr().err
    monkeypatch.setattr( run, "NEW_ASK", lambda ctx, item: ask_old( ctx, { **item, "need": item[ "need" ] + " (new)" } ) )
    assert run.cli( setup.args( "canary", "--ceiling", "100000000", extra=[ "--questions", "old,new" ] ) ) == 0
    assert "searches 10" in capsys.readouterr().out


def test_an_unknown_question_name_and_a_wrong_hash_are_refused_with_exit_two( setup, capsys ):
    assert run.cli( setup.args( "canary", "--ceiling", "100000000", extra=[ "--questions", "other" ] ) ) == 2
    bad = setup.args( "canary", "--ceiling", "100000000" )
    bad[ bad.index( "--needs-sha" ) + 1 ] = "0" * 64
    assert run.cli( bad ) == 2 and "sha256" in capsys.readouterr().err


def test_status_prints_the_ledger_and_the_pack_size( setup, capsys ):
    assert run.cli( setup.plain( "status" ) ) == 0
    out = capsys.readouterr().out
    assert "pack size 50" in out and "ledger" in out


def test_the_report_gives_the_paired_comparison_when_both_questions_ran( setup, monkeypatch, capsys ):
    monkeypatch.setattr( run, "NEW_ASK", lambda ctx, item: ask_old( ctx, { **item, "need": item[ "need" ] + " (new)" } ) )
    both = [ "--questions", "old,new" ]
    assert run.cli( setup.args( "canary", "--ceiling", "100000000", extra=both ) ) == 0
    assert run.cli( setup.args( "report", extra=both ) ) == 0
    out = capsys.readouterr().out
    assert "paired on_shortlist" in out and "paired ranked_first" in out and "paired top_ten" in out


def test_a_live_environment_takes_the_real_paths_and_no_stand_in_transport( setup, monkeypatch, capsys ):
    monkeypatch.setattr( rr, "check_paths", lambda root, data, ledger, live: ( setup.data, setup.ledger ) )
    env = run._open_env( setup.root, None, None, True, {}, 50 )
    assert env.live and env.transport_factory is not rr.StandIn


def test_a_run_with_no_root_and_no_environment_root_is_refused( monkeypatch, capsys ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert run.cli( [ "status" ] ) == 2 and "--root" in capsys.readouterr().err


def test_a_refused_new_question_is_refused_before_any_run_is_opened_or_request_is_sent( setup, capsys ):
    before = rl.AccountLedger( setup.ledger ).snapshot()
    assert run.cli( setup.args( "canary", "--ceiling", "100000000", extra=[ "--questions", "old,new" ] ) ) == 2
    assert not ( setup.data / "e2e-results" ).exists() and rl.AccountLedger( setup.ledger ).snapshot() == before
    with pytest.raises( s1.DriverRefused, match="not wired" ): run._asks( [ "new" ] )
