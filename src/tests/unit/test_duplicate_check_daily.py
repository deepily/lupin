"""The daily duplicate check, run on a fixture git repository."""
import datetime
import json
import os
import subprocess

import pytest

from cosa.repo.duplicate_check import config as cf
from cosa.repo.duplicate_check import errors as err
from cosa.repo.duplicate_check import judge as jd
from cosa.repo.duplicate_check.proof import proof_cli
from lupin_mcp import duplicate_check_daily as dd
from tests.unit.test_duplicate_check_score_run import JSCPD, SCRUB, FakeBackend, FakeClient, function

NOW = datetime.datetime( 2026, 11, 3, 12, 0, tzinfo=datetime.timezone.utc )


def git( repo, *args, when=None ):
    """Ensures: runs git in the repo, at the given time, and returns its stripped stdout."""
    env = { **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x" }
    if when is not None: env.update( GIT_AUTHOR_DATE=when.isoformat(), GIT_COMMITTER_DATE=when.isoformat() )
    return subprocess.run( [ "git", *args ], cwd=repo, env=env, capture_output=True, text=True, check=True ).stdout.strip()


def commit( repo, files, message, hours_ago ):
    """Ensures: commits the files at a set hour, returns the sha."""
    for name, text in files.items():
        ( repo / name ).parent.mkdir( parents=True, exist_ok=True )
        ( repo / name ).write_text( text, encoding="utf-8" )
    git( repo, "add", "-A" )
    git( repo, "commit", "-q", "-m", message, when=NOW - datetime.timedelta( hours=hours_ago ) )
    return git( repo, "rev-parse", "HEAD" )


@pytest.fixture
def repo( tmp_path, monkeypatch ):
    """Ensures: an empty git repository on main, the binary version stubbed."""
    root = tmp_path / "repo"
    root.mkdir()
    git( root, "init", "-q", "-b", "main" )
    monkeypatch.setattr( proof_cli.model_transport, "cli_version", lambda path: "9.9" )
    return root


def parts_of( tmp_path, **over ):
    """Ensures: returns run's parts with a stand-in for each outside call."""
    backend = FakeBackend()
    cfg     = cf.build_config( "max-plan", "unsettable:bounded-cc", "stub", *jd.prompt_parts(), SCRUB, 4000, JSCPD, min_nodes=10 )
    base    = { "client": FakeClient(), "backend": backend, "data_dir": str( tmp_path / "io" ), "version_fn": lambda p: "9.9", "verify": lambda: cfg,
                "structural": lambda tree, c: ( lambda defs: [] ) }
    return { **base, **over }


def history( repo ):
    """Ensures: three commits, an old one, then two new functions, then one; returns the shas."""
    c1 = commit( repo, { "server/s1.py": function( "s1", [ "MARKB" ], 50 ), "client/old.py": function( "old", [ "MARKC" ], 3 ) }, "old", 48 )
    c2 = commit( repo, { "client/a1.py": function( "a1", [ "MARKA" ], 2 ), "client/a2.py": function( "a2", [ "MARKA" ], 4 ) }, "a1 a2", 5 )
    c3 = commit( repo, { "client/a0.py": function( "a3", [ "MARKA" ], 6 ) }, "a3 in a0.py", 2 )     # a0.py sorts before a1.py, so file order is not commit order
    return c1, c2, c3


def worktrees( repo ): return [ l for l in git( repo, "worktree", "list" ).splitlines() ]


def results( tmp_path ):
    folder = tmp_path / "io" / "duplicate-check-daily"
    return sorted( p for p in folder.glob( "*.json" ) if p.name != dd.LAST_SUCCESS )


def test_a_first_run_judges_the_last_24_hours_once_clusters_the_duplicates_and_advances_last_success( repo, tmp_path ):
    c1, c2, c3 = history( repo )
    parts = parts_of( tmp_path )
    doc   = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts )
    assert doc[ "window" ] == { "start": c1, "end": c3, "commits": 2 }, "the 24 hour window starts at the newest commit older than a day"
    assert doc[ "status" ] == "ok" and doc[ "judged" ] == 3 and doc[ "judge_calls" ] == 3 and doc[ "carried" ] == [] and doc[ "advanced_to" ] == c3
    assert len( doc[ "clusters" ] ) == 1 and len( doc[ "clusters" ][ 0 ] ) == 3, "a1, a2 and a3 share a marker"
    assert doc[ "trigger" ] == "hand" and doc[ "elapsed_seconds" ] >= 0 and doc[ "cap" ] == 10
    assert json.loads( ( tmp_path / "io" / "duplicate-check-daily" / dd.LAST_SUCCESS ).read_text() )[ "commit" ] == c3
    assert json.loads( results( tmp_path )[ 0 ].read_text() ) == doc and results( tmp_path )[ 0 ].name == "2026-11-03-120000-hand.json"
    assert len( worktrees( repo ) ) == 1, "the detached worktrees are gone"


def test_a_rerun_of_the_same_window_makes_zero_backend_calls_and_a_run_after_it_has_nothing_to_judge( repo, tmp_path ):
    history( repo )
    parts = parts_of( tmp_path )
    first = dd.run( repo, NOW, "cron", 10, "/bin/claude", parts )
    ( tmp_path / "io" / "duplicate-check-daily" / dd.LAST_SUCCESS ).unlink()
    again = dd.run( repo, NOW + datetime.timedelta( minutes = 1 ), "cron", 10, "/bin/claude", parts )
    assert again[ "judge_calls" ] == 0 and again[ "clusters" ] == first[ "clusters" ] and again[ "judged" ] == 3
    empty = dd.run( repo, NOW + datetime.timedelta( minutes = 2 ), "reboot", 10, "/bin/claude", parts )
    assert empty[ "judged" ] == 0 and empty[ "judge_calls" ] == 0 and empty[ "window" ][ "commits" ] == 0 and empty[ "clusters" ] == []
    assert [ p.name for p in results( tmp_path ) ] == [ "2026-11-03-120000-cron.json", "2026-11-03-120100-cron.json", "2026-11-03-120200-reboot.json" ]


def test_the_cap_stops_at_a_commit_boundary_and_the_rest_carries_with_progress_kept_per_function( repo, tmp_path ):
    c1, c2, c3 = history( repo )
    parts = parts_of( tmp_path )
    one   = dd.run( repo, NOW, "cron", 1, "/bin/claude", parts )
    assert one[ "status" ] == "carried" and one[ "judge_calls" ] == 1 and len( one[ "carried" ] ) == 2 and one[ "advanced_to" ] == c1 and one[ "judged" ] == 1
    two   = dd.run( repo, NOW + datetime.timedelta( minutes=5 ), "cron", 10, "/bin/claude", parts )
    assert two[ "judge_calls" ] == 2, "the function judged yesterday came from the ledger, the other two were asked"
    assert two[ "status" ] == "ok" and two[ "advanced_to" ] == c3 and two[ "window" ][ "start" ] == c1


def test_a_commit_that_needs_more_calls_than_the_cap_is_finished_over_several_runs( repo, tmp_path ):
    c1, c2, c3 = history( repo )
    parts = parts_of( tmp_path )
    seen  = []
    for step in range( 3 ):
        doc = dd.run( repo, NOW + datetime.timedelta( minutes=step ), "cron", 1, "/bin/claude", parts )
        seen.append( ( doc[ "judge_calls" ], doc[ "advanced_to" ] ) )
    assert seen == [ ( 1, c1 ), ( 1, c2 ), ( 1, c3 ) ], "a cap of one call finishes the two commits in three runs, one function a run"


def test_a_function_changed_on_two_days_is_judged_once_by_its_latest_text( repo, tmp_path ):
    c1 = commit( repo, { "client/a1.py": function( "a1", [ "MARKA" ], 2 ) }, "v0", 48 )
    commit( repo, { "client/a1.py": function( "a1", [ "MARKA", "MARKD" ], 3 ) }, "v1", 5 )
    commit( repo, { "client/a1.py": function( "a1", [ "MARKA", "MARKE" ], 4 ) }, "v2", 2 )
    doc = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path ) )
    assert doc[ "judged" ] == 1 and doc[ "judge_calls" ] == 1


def test_an_unchanged_function_in_a_touched_file_is_not_judged_again_and_a_changed_and_a_new_one_are( repo, tmp_path ):
    commit( repo, { "client/m.py": function( "same", [ "MARKA" ], 2 ) + "\n\n" + function( "edit", [ "MARKB" ], 3 ) }, "base", 48 )
    commit( repo, { "client/m.py": function( "same", [ "MARKA" ], 2 ) + "\n\n" + function( "edit", [ "MARKB", "MARKC" ], 4 ) + "\n\n" + function( "added", [ "MARKD" ], 5 ) }, "touch", 2 )
    window = dd.window_of( repo, None, NOW )
    tree   = dd.source_at.ensure_worktree( repo, window[ "end" ], repo / ".wt-test" )
    try: names = sorted( d[ "name" ] for d in dd.new_definitions( tree, repo, window )[ "defs" ] )
    finally: dd.release( repo, tree )
    assert names == [ "added", "edit" ], "the function the window's start already held is left out"


def test_a_function_brought_in_by_a_merged_branch_belongs_to_the_merge_commit_on_the_first_parent_line( repo, tmp_path ):
    c1 = commit( repo, { "server/s1.py": function( "s1", [ "MARKB" ], 50 ) }, "old", 48 )
    git( repo, "checkout", "-q", "-b", "side" )
    side = commit( repo, { "client/a1.py": function( "a1", [ "MARKA" ], 2 ) }, "side work", 6 )
    git( repo, "checkout", "-q", "main" )
    commit( repo, { "client/a2.py": function( "a2", [ "MARKA" ], 3 ) }, "main work", 4 )
    git( repo, "merge", "-q", "--no-ff", "-m", "merge side", "side", when=NOW - datetime.timedelta( hours=2 ) )
    merge  = git( repo, "rev-parse", "HEAD" )
    window = dd.window_of( repo, { "commit": c1 }, NOW )
    assert side not in window[ "commits" ] and merge in window[ "commits" ] and len( window[ "commits" ] ) == 2
    first = dd.run( repo, NOW, "hand", 1, "/bin/claude", parts_of( tmp_path ) )
    assert first[ "status" ] == "carried" and first[ "advanced_to" ] == window[ "commits" ][ 0 ], "a2 came on main first and was judged; a1 came with the merge and is carried"
    rest  = dd.run( repo, NOW + datetime.timedelta( minutes=1 ), "hand", 10, "/bin/claude", parts_of( tmp_path ) )
    assert rest[ "status" ] == "ok" and rest[ "advanced_to" ] == merge


def test_a_new_definition_is_never_paired_with_its_own_earlier_version( repo, tmp_path, monkeypatch ):
    c1 = commit( repo, { "client/a1.py": function( "a1", [ "MARKA" ], 2 ), "client/other.py": function( "other", [ "MARKB" ], 5 ) }, "old", 48 )
    commit( repo, { "client/a1.py": function( "a1", [ "MARKA", "MARKD" ], 3 ) }, "change a1", 2 )
    dropped = []
    real    = dd.pool_without_earlier_versions
    monkeypatch.setattr( dd, "pool_without_earlier_versions", lambda tree, fresh: dropped.append( [ d[ "name" ] for d in fresh ] ) or real( tree, fresh ) )
    ledgers = []
    real_led = proof_cli.proof_ledger
    monkeypatch.setattr( dd.proof_cli, "proof_ledger", lambda *a, **k: ledgers.append( real_led( *a, **k ) ) or ledgers[ -1 ] )
    dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path ) )
    assert dropped == [ [ "a1" ] ]
    tree = repo
    pool = dd.pool_without_earlier_versions( tree, [ { "file": "client/a1.py", "name": "a1" } ] )
    assert [ d[ "name" ] for d in pool ] == [ "other" ], "the earlier a1 is not in the pool, the other function is"


def test_each_prerequisite_that_fails_writes_a_failed_record_naming_it_and_judges_nothing( repo, tmp_path ):
    history( repo )
    def broken_info():
        raise OSError( "refused" )
    bad_client = FakeClient()
    bad_client.info = broken_info
    def drifted(): raise err.DuplicateCheckError( err.CONFIG_DRIFT, "the prompt changed" )
    cases = [ ( "embedding_endpoint", { "client": bad_client }, "/bin/claude" ), ( "claude_binary", { "version_fn": lambda p: "unreadable" }, "/bin/claude" ),
              ( "claude_binary", { }, None ), ( "frozen_config", { "verify": drifted }, "/bin/claude" ) ]
    for i, ( name, over, cli ) in enumerate( cases ):
        parts = parts_of( tmp_path, **over )
        doc   = dd.run( repo, NOW + datetime.timedelta( minutes=i ), "cron", 10, cli, parts )
        assert doc[ "status" ] == "failed" and doc[ "prerequisite" ] == name and doc[ "judge_calls" ] == 0 and "elapsed_seconds" in doc and doc[ "trigger" ] == "cron"
        assert json.loads( results( tmp_path )[ -1 ].read_text() ) == doc
        assert parts[ "backend" ].calls == 0
    assert not ( tmp_path / "io" / "duplicate-check-daily" / dd.LAST_SUCCESS ).exists() and len( worktrees( repo ) ) == 1
    assert "the prompt changed" in doc[ "detail" ]


def test_the_worktrees_are_removed_when_the_run_fails_part_way( repo, tmp_path ):
    history( repo )
    class Boom( FakeBackend ):
        async def complete( self, *a ): raise RuntimeError( "boom" )
    with pytest.raises( RuntimeError, match="boom" ):
        dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path, backend=Boom() ) )
    assert len( worktrees( repo ) ) == 1 and not ( tmp_path / "io" / "duplicate-check-daily" / dd.LAST_SUCCESS ).exists()


def test_an_unknown_trigger_is_refused_before_anything_is_read( repo, tmp_path ):
    with pytest.raises( ValueError, match="trigger" ):
        dd.run( repo, NOW, "weekly", 10, "/bin/claude", parts_of( tmp_path ) )


def test_the_run_uses_the_one_shared_wiring_builder_and_its_own_ledger_folder( repo, tmp_path, monkeypatch ):
    history( repo )
    seen = []
    real = proof_cli.base_wiring
    monkeypatch.setattr( dd.proof_cli, "base_wiring", lambda *a, **k: seen.append( a ) or real( *a, **k ) )
    dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path ) )
    assert len( seen ) == 1 and str( seen[ 0 ][ 0 ] ) == str( tmp_path / "io" / "duplicate-check-daily" / "vectors" )
    assert ( tmp_path / "io" / "duplicate-check-daily" / "judge-ledger.jsonl" ).exists() and not ( tmp_path / "io" / "proof" ).exists()


def test_the_window_starts_at_the_first_commit_when_no_commit_is_a_day_old( repo ):
    c = commit( repo, { "client/a1.py": function( "a1", [ "MARKA" ], 2 ) }, "only", 1 )
    w = dd.window_of( repo, None, NOW )
    assert w == { "start": c, "end": c, "commits": [] }


def test_the_window_after_a_good_run_starts_at_its_commit( repo ):
    c1, c2, c3 = history( repo )
    assert dd.window_of( repo, { "commit": c2 }, NOW ) == { "start": c2, "end": c3, "commits": [ c3 ] }


def test_progress_carries_a_capped_or_failed_definition_and_not_an_unreadable_one():
    window = { "start": "s", "end": "e", "commits": [ "c1", "c2" ] }
    of     = { "d1": "c1", "d2": "c2", "d3": "c2" }
    assert dd.progress( [ ], of, [ ], window ) == { "advanced_to": "e", "carried": [] }
    assert dd.progress( [ ], of, [ { "id": "d2", "code": err.JUDGE_UNREADABLE } ], window ) == { "advanced_to": "e", "carried": [] }
    assert dd.progress( [ ], of, [ { "id": "d2", "code": err.JUDGE_CAP_REACHED } ], window ) == { "advanced_to": "c1", "carried": [ "d2" ] }
    assert dd.progress( [ ], of, [ { "id": "d1", "code": err.JUDGE_CALL_FAILED } ], window ) == { "advanced_to": "s", "carried": [ "d1" ] }
    assert dd.progress( [ ], { "d9": "elsewhere" }, [ { "id": "d9", "code": err.JUDGE_CAP_REACHED } ], window )[ "advanced_to" ] == "s", "a commit the window does not list blocks everything"
    assert dd.progress( [ ], of, [ { "id": "d3", "code": err.JUDGE_CAP_REACHED }, { "id": "d2", "code": err.JUDGE_CALL_FAILED } ], window )[ "advanced_to" ] == "c1"


def test_main_runs_with_the_given_parts_prints_the_json_and_returns_one_on_a_failed_prerequisite( repo, tmp_path, monkeypatch ):
    history( repo )
    configured = []
    monkeypatch.setattr( dd.model_transport, "configure", lambda path=None: configured.append( path ) )
    out = []
    rc  = dd.main( [ "--cap", "10", "--root", str( repo ), "--trigger", "cron", "--claude-cli-path", "/bin/claude" ], parts=parts_of( tmp_path ), now=NOW, out=out.append )
    assert rc == 0 and json.loads( out[ 0 ] )[ "trigger" ] == "cron"
    bad = dd.main( [ "--cap", "10", "--root", str( repo ) ], parts=parts_of( tmp_path ), now=NOW + datetime.timedelta( hours=1 ), out=out.append )
    assert bad == 1 and json.loads( out[ 1 ] )[ "prerequisite" ] == "claude_binary" and configured == [ "/bin/claude", None ]


def test_main_finds_the_root_from_the_working_directory_when_none_is_given( repo, tmp_path, monkeypatch ):
    history( repo )
    monkeypatch.chdir( repo )
    monkeypatch.setattr( dd.model_transport, "configure", lambda path=None: None )
    out = []
    assert dd.main( [ "--cap", "10", "--claude-cli-path", "/bin/claude" ], parts=parts_of( tmp_path ), now=NOW, out=out.append ) == 0
    assert json.loads( out[ 0 ] )[ "window" ][ "end" ] == git( repo, "rev-parse", "main" )


def test_main_needs_a_cap():
    with pytest.raises( SystemExit ):
        dd.main( [ "--root", "." ] )


def test_the_counting_backend_counts_each_call_and_passes_the_answer_through():
    import asyncio
    inner = FakeBackend( garbage=True )
    count = dd.Counting( inner )
    assert asyncio.run( count.complete( "m", "s", "u" ) ) == "not json" and count.calls == 1 and count.server_label == "max-plan"


def test_git_names_the_command_when_it_fails( tmp_path ):
    with pytest.raises( RuntimeError, match="rev-parse" ):
        dd.git( tmp_path, "rev-parse", "--verify", "nothing" )


def test_the_live_parts_are_built_without_a_call():
    parts = dd.live_parts()
    assert set( parts ) == { "client", "backend", "data_dir", "version_fn", "verify", "structural" } and callable( parts[ "structural" ] )
