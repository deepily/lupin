"""
The launch preflight refuses a used run name or a stale identity, and reads identity last.

The ledger is written by the real AccountLedger and the index and build info by the real producers (needset_freeze_helpers).
"""
import io
import json
import pathlib

import pytest

from lupin_mcp import reuse_ledger
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import freeze, launch_preflight as lp
from tests.unit.needset_freeze_helpers import built_pair

RUN = "needset-first-1000-20261101-m"


def make_ledger( tmp_path, *begun, end=True ):
    """Ensures: returns a real ledger that began each run, and ended it unless end is False."""
    led = reuse_ledger.AccountLedger.create( tmp_path / "ledger.jsonl", 1_000_000, "test", "fixture" )
    for name in begun:
        led.begin_run( name, 10 )
        if end: led.end_run( name )
    return led.path


def folder( base, name ):
    """Ensures: returns the new sub-folder base/name."""
    path = base / name
    path.mkdir()
    return path


def code_of( call, *args, **kw ):
    """Ensures: returns the code of the NeedsetError the call raises."""
    with pytest.raises( er.NeedsetError ) as e: call( *args, **kw )
    return e.value.code


def test_a_run_name_the_ledger_began_is_consumed_even_when_its_attempt_was_refused( tmp_path ):
    ledger = make_ledger( tmp_path, RUN )
    assert lp.begun_run_names( ledger ) == { RUN }
    assert code_of( lp.check_run_name, RUN, lp.begun_run_names( ledger ) ) == er.RUN_NAME_CONSUMED


def test_an_unused_name_passes_and_a_missing_ledger_has_begun_nothing( tmp_path ):
    assert lp.check_run_name( RUN, lp.begun_run_names( make_ledger( tmp_path, RUN + "x" ) ) ) is None
    assert lp.begun_run_names( tmp_path / "absent.jsonl" ) == set()


def test_a_blank_run_name_is_refused():
    assert code_of( lp.check_run_name, "", set() ) == er.RUN_NAME_CONSUMED


def test_the_refusal_names_the_next_letter_and_prints_the_rule( tmp_path ):
    with pytest.raises( er.NeedsetError ) as e: lp.check_run_name( RUN, { RUN } )
    assert "needset-first-1000-20261101-n" in e.value.detail and lp.RULE in e.value.detail


@pytest.mark.parametrize( "name,begun,want", [
    ( "x-m", { "x-m" }, "x-n" ),
    ( "x-m", { "x-m", "x-n", "x-o" }, "x-p" ),
    ( "x-m", set(), "x-m" ),
    ( "x-20261101", { "x-20261101" }, "x-20261101-b" ),
    ( "x-20261101", { "x-20261101", "x-20261101-b" }, "x-20261101-c" ),
] )
def test_next_run_name_letters_forward_past_every_begun_name( name, begun, want ):
    assert lp.next_run_name( name, begun ) == want


def test_next_run_name_refuses_when_the_letters_run_out():
    assert code_of( lp.next_run_name, "x-z", { "x-z" } ) == er.RUN_NAME_CONSUMED


def tree_of( recreated=False, log=None, was_locked=False ):
    """Ensures: returns a tree_fn for a stand-in tree that logs its call."""
    def tree():
        if log is not None: log.append( "tree" )
        return "/tree", recreated, was_locked
    return tree


def index_of( gen, log=None ):
    """Ensures: returns an index_fn that names gen and logs that it ran."""
    def index( tree ):
        if log is not None: log.append( "index" )
        return gen
    return index


def test_a_mismatched_vector_set_is_refused_by_the_identity_step( tmp_path ):
    gen, _ = built_pair( tmp_path, "one" )
    _, other_vec = built_pair( tmp_path, "two", extra_source="def extra():\n    return 1\n" )
    assert code_of( lp.preflight, RUN, make_ledger( tmp_path ), other_vec, tree_fn=tree_of(), index_fn=index_of( gen ) ) == er.VECTORS_NOT_FROM_INDEX


def test_a_vector_set_with_no_build_info_is_refused_as_incomplete( tmp_path ):
    gen, vec = built_pair( tmp_path )
    ( vec / "build-info.json" ).unlink()
    assert code_of( lp.preflight, RUN, make_ledger( tmp_path ), vec, tree_fn=tree_of(), index_fn=index_of( gen ) ) == er.FREEZE_INCOMPLETE


def test_a_matching_pair_passes_and_returns_the_identity_and_the_tree( tmp_path ):
    gen, vec = built_pair( tmp_path )
    got = lp.preflight( RUN, make_ledger( tmp_path ), vec, tree_fn=tree_of(), index_fn=index_of( gen ) )
    assert got[ "identity" ] == freeze.identity( gen, vec ) and got[ "run_name" ] == RUN and got[ "advanced_from" ] is None
    assert got[ "tree" ] == "/tree" and got[ "tree_recreated" ] is False


def test_the_name_is_judged_first_then_the_tree_then_the_index_then_the_identity_last( tmp_path ):
    log = []
    def identity( g, v ):
        log.append( "identity" )
        return {}
    lp.preflight( RUN + "-q", make_ledger( tmp_path, RUN ), "v", tree_fn=tree_of( log=log ), index_fn=index_of( "g", log ), identity_fn=identity )
    assert log == [ "tree", "index", "identity" ]


def test_a_refused_name_touches_no_tree_and_reads_no_identity( tmp_path ):
    log = []
    assert code_of( lp.preflight, RUN, make_ledger( tmp_path, RUN ), "v", tree_fn=tree_of( log=log ), index_fn=index_of( "g", log ), identity_fn=lambda g, v: log.append( "identity" ) ) == er.RUN_NAME_CONSUMED
    assert log == []


STATES = [ ( True, False, [ "/tree" ] ), ( False, False, [ "/tree" ] ), ( False, True, [] ) ]   # ( made now, locked before, unlocked after a failure )


@pytest.mark.parametrize( "recreated,was_locked,want", STATES )
def test_a_refusal_unlocks_a_tree_unless_it_was_locked_before_the_call( tmp_path, recreated, was_locked, want ):
    def stale( g, v ): raise er.NeedsetError( er.VECTORS_NOT_FROM_INDEX, "built from another index" )
    unlocked = []
    assert code_of( lp.preflight, RUN, make_ledger( tmp_path ), "v", tree_fn=tree_of( recreated, was_locked=was_locked ), index_fn=index_of( "g" ), identity_fn=stale, unlock_fn=unlocked.append ) == er.VECTORS_NOT_FROM_INDEX
    assert unlocked == want


@pytest.mark.parametrize( "recreated,was_locked,want", STATES )
def test_a_crash_in_the_index_step_unlocks_a_tree_unless_it_was_locked_before_and_re_raises( tmp_path, recreated, was_locked, want ):
    def crash( tree ): raise RuntimeError( "index build died" )
    unlocked = []
    with pytest.raises( RuntimeError, match="index build died" ): lp.preflight( RUN, make_ledger( tmp_path ), "v", tree_fn=tree_of( recreated, was_locked=was_locked ), index_fn=crash, unlock_fn=unlocked.append )
    assert unlocked == want


def test_a_stale_identity_after_the_tree_was_recreated_says_so_and_names_the_rebuild( tmp_path ):
    def stale( g, v ): raise er.NeedsetError( er.VECTORS_NOT_FROM_INDEX, "built from index 344e45fe3646, the index is 18a0b4a16647" )
    ledger = make_ledger( tmp_path )
    for recreated, said in ( ( True, True ), ( False, False ) ):
        with pytest.raises( er.NeedsetError ) as e: lp.preflight( RUN, ledger, "v", tree_fn=tree_of( recreated ), index_fn=index_of( "g" ), identity_fn=stale )
        assert e.value.code == er.VECTORS_NOT_FROM_INDEX and ( "rebuild_vectors" in e.value.detail ) is said and "344e45fe3646" in e.value.detail


def test_advance_letters_a_consumed_name_forward_instead_of_refusing( tmp_path ):
    got = lp.preflight( RUN, make_ledger( tmp_path, RUN ), "v", advance=True, tree_fn=tree_of(), index_fn=index_of( "g" ), identity_fn=lambda g, v: {} )
    assert got[ "run_name" ] == "needset-first-1000-20261101-n" and got[ "advanced_from" ] == RUN


def test_without_live_nothing_is_checked_even_a_consumed_name_and_no_tree_is_made( tmp_path ):
    log = []
    got = lp.preflight( RUN, make_ledger( tmp_path, RUN ), "nowhere", live=False, tree_fn=tree_of( log=log ) )
    assert got[ "live" ] is False and got[ "identity" ] is None and got[ "tree" ] is None and log == []


def run_main( tmp_path, ledger, *argv, identity_fn=lambda g, v: { "ok": 1 }, environ=None, log=None ):
    """Ensures: returns ( exit code, stdout, stderr ) of main over a real ledger."""
    out, err = io.StringIO(), io.StringIO()
    env = { "LUPIN_REUSE_JEV_RUN_NAME": RUN, "LUPIN_REUSE_CANDIDATE_VECTORS_DIR": "/v" } if environ is None else environ
    rc = lp.main( [ "--root", str( tmp_path ), "--source-commit", "abc", "--ledger", str( ledger ), *argv ], environ=env, out=out, err=err, identity_fn=identity_fn,
                  tree_fn=tree_of( log=log ), index_fn=index_of( "/g" ), unlock_fn=lambda tree: None )
    return rc, out.getvalue(), err.getvalue()


def test_main_refuses_a_consumed_name_with_exit_two_and_the_rule( tmp_path ):
    rc, out, err = run_main( tmp_path, make_ledger( tmp_path, RUN ), "--live" )
    assert rc == lp.EXIT_REFUSED == 2 and out == "" and "RUN_NAME_CONSUMED" in err and lp.RULE in err


def test_main_refuses_a_stale_identity_with_exit_two( tmp_path ):
    def stale( g, v ): raise er.NeedsetError( er.VECTORS_NOT_FROM_INDEX, "built from another index" )
    rc, out, err = run_main( tmp_path, make_ledger( tmp_path ), "--live", identity_fn=stale )
    assert rc == 2 and "VECTORS_NOT_FROM_INDEX" in err


def test_main_refuses_a_live_launch_with_no_source_commit( tmp_path ):
    out, err = io.StringIO(), io.StringIO()
    rc = lp.main( [ "--root", str( tmp_path ), "--ledger", str( make_ledger( tmp_path ) ), "--live" ], environ={ "LUPIN_REUSE_JEV_RUN_NAME": RUN }, out=out, err=err )
    assert rc == 2 and "--source-commit" in err.getvalue()


def test_main_passes_with_the_launch_arguments_it_does_not_know( tmp_path ):
    rc, out, err = run_main( tmp_path, make_ledger( tmp_path ), "--live", "--limit", "2314" )
    assert rc == 0 and json.loads( out )[ "run_name" ] == RUN and err == ""


def test_main_prints_the_new_name_and_the_rule_when_advancing( tmp_path ):
    rc, out, err = run_main( tmp_path, make_ledger( tmp_path, RUN ), "--live", "--advance" )
    assert rc == 0 and "RUN_NAME=needset-first-1000-20261101-n" in out and lp.RULE in out


def test_main_without_live_checks_nothing_and_makes_no_tree( tmp_path ):
    log = []
    rc, out, err = run_main( tmp_path, make_ledger( tmp_path, RUN ), log=log )
    assert rc == 0 and json.loads( out )[ "live" ] is False and log == []


def test_main_reads_the_default_ledger_from_the_root_when_none_is_given( tmp_path, monkeypatch ):
    monkeypatch.setattr( reuse_ledger, "ledger_path", lambda root: make_ledger( tmp_path, RUN ) )
    out, err = io.StringIO(), io.StringIO()
    rc = lp.main( [ "--root", str( tmp_path ), "--source-commit", "abc", "--live" ], environ={ "LUPIN_REUSE_JEV_RUN_NAME": RUN }, out=out, err=err, identity_fn=lambda g, v: {}, tree_fn=tree_of(), index_fn=index_of( "g" ) )
    assert rc == 2 and "RUN_NAME_CONSUMED" in err.getvalue()


def test_the_real_source_tree_reports_made_and_locked_before_and_tree_is_locked_reads_git( tmp_path ):
    import subprocess
    from lupin_mcp.reuse_needset import source_at
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in ( [ "init", "-q" ], [ "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "c" ] ): subprocess.run( [ "git", "-C", str( repo ), *cmd ], check=True, capture_output=True )
    path = source_at.worktree_path( repo, "HEAD" )
    assert lp.tree_is_locked( repo, path ) is False
    first = lp.source_tree_of( repo, "HEAD" )
    again = lp.source_tree_of( repo, "HEAD" )
    assert first == ( path, True, False ) and again == ( path, False, True ) and lp.tree_is_locked( repo, path ) is True
    source_at.unlock( repo, path )
    assert lp.tree_is_locked( repo, path ) is False
    assert lp.source_tree_of( repo, "HEAD" ) == ( path, False, False ) and lp.tree_is_locked( repo, path ) is True


def test_a_ledger_line_that_is_not_json_is_skipped_not_fatal( tmp_path ):
    path = make_ledger( tmp_path, RUN )
    with path.open( "a", encoding="utf-8" ) as f: f.write( "not json\n[1]\n" )
    assert lp.begun_run_names( path ) == { RUN }
