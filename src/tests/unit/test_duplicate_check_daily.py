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
from tests.unit.test_librarian_tick import cron   # noqa: F401  (fixture: the fake crontab and the fake lock)

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
    doc = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path, backend=Boom() ) )
    assert doc[ "status" ] == "failed" and "boom" in doc[ "error" ], "the failure is recorded, not raised"
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
    assert set( parts ) == { "client", "backend", "data_dir", "version_fn", "verify", "structural", "filer", "auditor" } and callable( parts[ "structural" ] )


def lines_of( **over ):
    """Ensures: returns the cron lines for a fixed root, interpreter, log, cap and binary."""
    args = dict( root="/main", python="/py", log_path="/log/daily.log", cap=40, cli_path="/bin/claude" )
    return dd.cron_lines( **{ **args, **over } )


def test_the_daily_line_runs_at_twelve_oh_seven_with_trigger_cron_and_the_reboot_line_waits_after_a_boot_with_trigger_reboot():
    daily, reboot = lines_of()
    tail = "cd /main && LUPIN_ROOT=/main PYTHONPATH=/main/src /py -m lupin_mcp.duplicate_check_daily --cap 40 --claude-cli-path /bin/claude --trigger {} >> /log/daily.log 2>&1 # duplicate-check-daily"
    assert daily == "7 12 * * * " + tail.format( "cron" ) and reboot == "@reboot sleep 300 && " + tail.format( "reboot" )


def test_the_cron_lines_carry_the_named_environment_shell_quoted_and_nothing_else():
    daily, reboot = lines_of( carried={ "LUPIN_CONFIG_MGR_CLI_ARGS": "config_path=/c block=Lupin:+Dev x", "DEEPILY_DATA_DIR": "/mnt/d" } )
    for line in ( daily, reboot ):
        assert "LUPIN_CONFIG_MGR_CLI_ARGS='config_path=/c block=Lupin:+Dev x' DEEPILY_DATA_DIR=/mnt/d /py -m" in line
    assert "DEEPILY_DATA_DIR" not in lines_of()[ 0 ]


def test_the_default_branch_adds_nothing_to_the_cron_lines():
    assert lines_of( branch=dd.BRANCH ) == lines_of() and "--branch" not in "".join( lines_of( branch=dd.BRANCH ) )


def test_a_given_branch_goes_into_both_cron_lines_after_the_trigger():
    daily, reboot = lines_of( branch="wip-v0.2.2" )
    tail = "cd /main && LUPIN_ROOT=/main PYTHONPATH=/main/src /py -m lupin_mcp.duplicate_check_daily --cap 40 --claude-cli-path /bin/claude --trigger {} --branch wip-v0.2.2 >> /log/daily.log 2>&1 # duplicate-check-daily"
    assert daily == "7 12 * * * " + tail.format( "cron" ) and reboot == "@reboot sleep 300 && " + tail.format( "reboot" )


def test_a_branch_name_with_shell_characters_is_quoted_in_both_cron_lines():
    for line in lines_of( branch="feature/a b;rm -rf x" ):
        assert "--branch 'feature/a b;rm -rf x' >> /log/daily.log" in line


def test_print_install_and_install_carry_the_branch_given_on_the_command_line( tmp_path, cron ):
    base = [ "--cap", "40", "--claude-cli-path", "/bin/claude", "--python", "/py", "--branch", "wip-x" ]
    code, out, _ = cron_main( tmp_path, [ "--print-install", *base ], cron )
    assert code == 0 and out[ 0 ].count( "--branch wip-x >> " ) == 2
    assert cron_main( tmp_path, [ "--install", *base ], cron, cron[ "env" ] )[ 0 ] == 0
    assert cron[ "file" ].read_text().count( "--branch wip-x >> " ) == 2
    plain = cron_main( tmp_path, [ "--print-install", *base[ :-2 ] ], cron )[ 1 ][ 0 ]
    assert "--branch" not in plain


def test_the_schedule_is_thirty_minutes_after_the_shadow_audit_drain():
    from lupin_mcp import reuse_shadow
    assert reuse_shadow.CRON_SCHEDULE == "37 11 * * *" and dd.CRON_SCHEDULE == "7 12 * * *"


def cron_main( tmp_path, argv, cron, environ=None ):
    """Ensures: runs main in a cron mode and returns ( code, stdout lines, stderr lines )."""
    out, err = [], []
    code = dd.main( argv, environ={ "LUPIN_ROOT": str( tmp_path ), **( environ or { } ) }, out=out.append, err=err.append, crontab_cmd=cron[ "cmd" ] )
    return code, out, err


def test_print_install_prints_both_lines_and_changes_nothing( tmp_path, cron ):
    code, out, _ = cron_main( tmp_path, [ "--print-install", "--cap", "40", "--claude-cli-path", "/bin/claude", "--python", "/py" ], cron, { "LUPIN_CONFIG_MGR_CLI_ARGS": "a b" } )
    assert code == 0 and out[ 0 ].count( dd.CRON_TAG ) == 2 and "LUPIN_CONFIG_MGR_CLI_ARGS='a b'" in out[ 0 ] and not cron[ "file" ].exists()


def test_install_status_and_uninstall_keep_other_lines_and_hold_the_lock( tmp_path, cron ):
    cron[ "file" ].write_text( "0 * * * * other\n" )
    argv = [ "--install", "--cap", "40", "--claude-cli-path", "/bin/claude", "--python", "/py" ]
    assert cron_main( tmp_path, argv, cron, cron[ "env" ] )[ :2 ] == ( 0, [ "installed: 2 lines" ] )
    assert "lock-enter " + dd.LOCK_OWNER in cron[ "log" ].read_text()
    assert cron_main( tmp_path, [ "--status" ], cron, cron[ "env" ] )[ 1 ] == [ "installed: 2 lines" ]
    assert cron_main( tmp_path, [ "--uninstall" ], cron, cron[ "env" ] )[ 1 ] == [ "uninstalled" ]
    entered = [ line for line in cron[ "log" ].read_text().splitlines() if line.startswith( "lock-enter" ) ]
    assert entered == [ "lock-enter " + dd.LOCK_OWNER ] * 2, "the install and the uninstall each take the lock as this job, and nothing else enters it"
    assert cron[ "log" ].read_text().count( "lock-exit" ) == 2, "and each lets it go"
    text = cron[ "file" ].read_text()
    assert text.strip() == "0 * * * * other", "only the other line is left, and nothing was added"
    assert list( ( tmp_path / "io" / "duplicate-check-daily" / "crontab-backups" ).iterdir() ), "a backup is written before each change"


def test_status_says_not_installed_when_there_is_no_crontab( tmp_path, cron ):
    assert cron_main( tmp_path, [ "--status" ], cron, cron[ "env" ] )[ 1 ] == [ "not installed" ]


def test_an_install_without_the_shared_lock_is_refused_with_one_and_the_reason( tmp_path, cron ):
    code, out, err = cron_main( tmp_path, [ "--install", "--cap", "40", "--claude-cli-path", "/bin/claude" ], cron, { } )
    assert code == 1 and err[ 0 ].startswith( "duplicate-check-daily:" ) and out == [ ] and not cron[ "file" ].exists()


def test_the_cron_modes_that_build_lines_need_a_cap_and_status_and_uninstall_do_not( tmp_path, cron ):
    for mode in ( "--print-install", "--install" ):
        with pytest.raises( SystemExit ):
            cron_main( tmp_path, [ mode ], cron, cron[ "env" ] )
    assert cron_main( tmp_path, [ "--status" ], cron, cron[ "env" ] )[ 0 ] == 0


def test_the_cron_modes_never_run_the_check( tmp_path, cron, monkeypatch ):
    monkeypatch.setattr( dd, "run", lambda *a, **k: pytest.fail( "the check ran" ) )
    monkeypatch.setattr( dd, "live_parts", lambda: pytest.fail( "the live parts were built" ) )
    assert cron_main( tmp_path, [ "--print-install", "--cap", "1", "--claude-cli-path", "/b" ], cron )[ 0 ] == 0


def test_the_root_of_the_cron_lines_falls_back_to_the_working_directory( tmp_path, cron, monkeypatch ):
    monkeypatch.chdir( tmp_path )
    out = []
    assert dd.main( [ "--print-install", "--cap", "1", "--claude-cli-path", "/b" ], environ={ }, out=out.append ) == 0 and f"cd {tmp_path} &&" in out[ 0 ]


def test_the_default_err_goes_to_standard_error_and_the_default_cron_command_is_crontab( tmp_path, cron, capsys, monkeypatch ):
    monkeypatch.setattr( dd.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess( cmd, 0, stdout="", stderr="" ) if cmd[ 0 ] == "crontab" else pytest.fail( cmd ) )
    out = []
    assert dd.main( [ "--status" ], environ={ "LUPIN_ROOT": str( tmp_path ) }, out=out.append ) == 0 and out == [ "not installed" ]
    assert dd.main( [ "--install", "--cap", "1", "--claude-cli-path", "/b" ], environ={ "LUPIN_ROOT": str( tmp_path ) }, out=out.append, crontab_cmd=cron[ "cmd" ] ) == 1
    assert "duplicate-check-daily:" in capsys.readouterr().err



def test_findings_are_one_per_new_definition_with_the_rest_of_the_cluster_and_no_session_without_session_of():
    fresh = [ { "id": "n1", "name": "a", "file": "f1.py", "line": 1, "text": "ta" } ]
    pool  = [ { "id": "p1", "name": "b", "file": "f2.py", "line": 2, "text": "tb" } ]
    win   = { "start": "s", "end": "e", "commits": 1 }
    got   = dd.findings_of( [ [ "n1", "p1" ], [ "p1", "x" ] ], fresh, pool, win, {} )
    assert got == [ { "id": "n1", "name": "a", "file": "f1.py", "line": 1, "text": "ta", "session_id": None, "commit": None, "window": win,
                      "others": [ { "id": "p1", "name": "b", "file": "f2.py" } ] } ], "pool-only members get no finding"
    seen = dd.findings_of( [ [ "n1", "p1" ] ], fresh, pool, win, { "session_of": lambda d: "sess-" + d[ "id" ] } )
    assert seen[ 0 ][ "session_id" ] == "sess-n1"


def test_a_run_with_a_filer_files_the_findings_and_records_the_answer_and_without_one_records_nothing( repo, tmp_path ):
    history( repo )
    calls = []
    def filer( findings, folder ):
        calls.append( ( findings, folder ) )
        return { "filed": len( findings ) }
    doc = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path, filer=filer ) )
    assert doc[ "filing" ] == { "filed": 3 } and len( calls ) == 1 and len( calls[ 0 ][ 0 ] ) == 3
    assert calls[ 0 ][ 1 ] == tmp_path / "io" / "duplicate-check-daily"
    assert json.loads( results( tmp_path )[ 0 ].read_text() )[ "filing" ] == { "filed": 3 }
    plain = dd.run( repo, NOW + datetime.timedelta( minutes=1 ), "cron", 10, "/bin/claude", parts_of( tmp_path ) )
    assert "filing" not in plain


def test_the_live_filer_files_with_the_configured_manager_the_roster_and_the_live_store( monkeypatch, tmp_path ):
    import cosa.config.configuration_manager as cm
    import cosa.rest.voice_persona_helpers as vh
    seen = {}
    class Cfg:
        def __init__( self, env_var_name ): seen[ "env" ] = env_var_name
        def get( self, key, default=None ):
            seen[ "key" ] = key
            return seen.get( "value" )
    monkeypatch.setattr( cm, "ConfigurationManager", Cfg )
    monkeypatch.setattr( vh, "pick_declared_managers_from_env", lambda project: [ "roster-" + project ] )
    monkeypatch.setattr( dd.filing, "LiveStore", lambda: "store" )
    monkeypatch.setattr( dd.filing, "file_findings", lambda findings, folder, store, declared, roster: ( findings, folder, store, declared, roster ) )
    assert dd.live_filer( [ "f" ], tmp_path ) == ( [ "f" ], tmp_path, "store", "manager-on-duty", [ "roster-lupin" ] ), "an empty setting falls back to the placeholder"
    seen[ "value" ] = "real-manager"
    assert dd.live_filer( [ "f" ], tmp_path )[ 3 ] == "real-manager"
    assert seen[ "env" ] == "LUPIN_CONFIG_MGR_CLI_ARGS" and seen[ "key" ] == "arbiter manager on duty"


def test_a_filer_that_raises_is_recorded_and_the_run_still_writes_its_file_and_advances_last_success( repo, tmp_path ):
    c1, c2, c3 = history( repo )
    def broken( findings, folder ): raise ConnectionError( "store down" )
    doc = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path, filer=broken ) )
    assert doc[ "filing" ] == { "error": "ConnectionError: store down" } and doc[ "status" ] == "ok" and doc[ "advanced_to" ] == c3
    folder = tmp_path / "io" / "duplicate-check-daily"
    assert json.loads( ( folder / dd.LAST_SUCCESS ).read_text() )[ "commit" ] == c3, "the next run does not re-judge the day"
    assert json.loads( results( tmp_path )[ 0 ].read_text() )[ "filing" ] == doc[ "filing" ]


def test_the_cron_lines_carry_the_manager_roster_variable_when_the_installer_has_it():
    assert dd.CARRIED == ( "LUPIN_CONFIG_MGR_CLI_ARGS", "DEEPILY_DATA_DIR", "COSA_VOICE_MANAGERS__LUPIN" )
    assert "COSA_VOICE_MANAGERS__LUPIN=" in lines_of( carried={ "COSA_VOICE_MANAGERS__LUPIN": "a,b" } )[ 0 ]


def test_a_failure_while_building_the_pool_or_judging_writes_a_failed_file_with_the_error_and_leaves_last_success_alone( repo, tmp_path ):
    history( repo )
    def broken( tree, cfg ): raise RuntimeError( "embeddings answered 500" )
    doc = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path, structural=broken ) )
    assert ( doc[ "status" ], doc[ "stage" ], doc[ "error" ], doc[ "judge_calls" ] ) == ( "failed", dd.STAGE_JUDGING, "RuntimeError: embeddings answered 500", 0 )
    folder = tmp_path / "io" / "duplicate-check-daily"
    assert json.loads( results( tmp_path )[ 0 ].read_text() ) == doc and not ( folder / dd.LAST_SUCCESS ).exists(), "the day is judged again next time"
    assert len( worktrees( repo ) ) == 1, "the detached worktrees are gone"
    again = dd.run( repo, NOW + datetime.timedelta( minutes=1 ), "hand", 10, "/bin/claude", parts_of( tmp_path ) )
    assert again[ "status" ] == "ok" and again[ "judged" ] == 3, "a later run with a working setup judges the same window"


def test_findings_carry_the_commit_that_added_each_definition_when_the_map_is_given():
    fresh = [ { "id": "n1", "name": "a", "file": "f1.py", "line": 1, "text": "ta" } ]
    got   = dd.findings_of( [ [ "n1", "p1" ] ], fresh, [ { "id": "p1", "name": "b", "file": "f2.py", "line": 2, "text": "tb" } ], {}, {}, { "n1": "abc123" } )
    assert got[ 0 ][ "commit" ] == "abc123"


def test_a_run_with_an_auditor_records_its_answer_and_a_raising_auditor_is_recorded_without_stopping_the_run( repo, tmp_path ):
    c1, c2, c3 = history( repo )
    seen = []
    def auditor( findings, folder ):
        seen.append( ( [ f[ "commit" ] for f in findings ], folder ) )
        return { "queued": len( findings ) }
    doc = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path, auditor=auditor ) )
    assert doc[ "audit" ] == { "queued": 3 } and "filing" not in doc and sorted( seen[ 0 ][ 0 ] ) == sorted( [ c2, c2, c3 ] )
    def broken( findings, folder ): raise OSError( "disk full" )
    bad = dd.run( repo, NOW + datetime.timedelta( minutes=1 ), "hand", 10, "/bin/claude", parts_of( tmp_path, auditor=broken, filer=lambda f, d: { "filed": 0 } ) )
    assert bad[ "audit" ] == { "error": "OSError: disk full" } and bad[ "filing" ] == { "filed": 0 } and bad[ "status" ] == "ok"


def test_the_live_auditor_ties_each_finding_with_the_lookup_tools_logs_and_queues_in_its_data_folder( tmp_path, monkeypatch ):
    class Ctx: root, data = tmp_path / "root", tmp_path / "data"
    seen = {}
    monkeypatch.setattr( dd.rt, "context_from_environment", lambda: Ctx )
    monkeypatch.setattr( dd.eg, "merge_call_logs", lambda folder: ( seen.setdefault( "logs", folder ) and [ "rec" ], [] ) )
    monkeypatch.setattr( dd.behaviour, "read_refusals", lambda data: [ "row" ] )
    monkeypatch.setattr( dd.tie_mod, "find_tie", lambda sid, rows, records, root, sha: ( sid, rows, records, root, sha ) )
    monkeypatch.setattr( dd.rt, "load_receipt", lambda ctx, rid: ( ctx, rid ) )
    def queue( findings, tie_of, receipt_of, data_dir, today ):
        seen.update( tie=tie_of( findings[ 0 ] ), receipt=receipt_of( "r1" ), data_dir=data_dir, today=today )
        return "queued"
    monkeypatch.setattr( dd.audit, "queue_audits", queue )
    assert dd.live_auditor( [ { "id": "d1", "commit": "abc" } ], tmp_path ) == "queued"
    assert seen[ "logs" ] == Ctx.data / "call-log" and seen[ "tie" ] == ( "d1", [ "row" ], [ "rec" ], Ctx.root, "abc" )
    assert seen[ "receipt" ] == ( Ctx, "r1" ) and seen[ "data_dir" ] == Ctx.data and seen[ "today" ] == datetime.date.today().isoformat()


def test_a_failed_file_after_some_judge_calls_were_made_counts_the_calls_made( repo, tmp_path ):
    history( repo )
    class Dies( FakeBackend ):
        async def complete( self, *a ):
            if self.calls >= 1: self.calls += 1; raise RuntimeError( "backend gone" )
            return await super().complete( *a )
    backend = Dies()
    doc     = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path, backend=backend ) )
    assert doc[ "status" ] == "failed" and "backend gone" in doc[ "error" ]
    assert doc[ "judge_calls" ] == backend.calls and doc[ "judge_calls" ] >= 2, "the calls made before the failure are counted, the failing one too"
    assert json.loads( results( tmp_path )[ 0 ].read_text() )[ "judge_calls" ] == doc[ "judge_calls" ]


def moved( repo, old, new, text, hours_ago ):
    """Ensures: renames a file with git, writes the new text and commits; returns the sha."""
    git( repo, "mv", old, new )
    return commit( repo, { new: text }, f"rename {old}", hours_ago )


def test_a_renamed_file_is_listed_by_its_new_path_and_maps_to_its_old_one( repo ):
    two  = function( "same", [ "MARKA" ], 2 ) + "\n\n" + function( "edit", [ "MARKB" ], 3 )
    c1   = commit( repo, { "client/m.py": two, "client/keep.py": function( "keep", [ "MARKC" ], 4 ), "client/gone.py": function( "gone", [ "MARKD" ], 5 ) }, "base", 48 )
    moved( repo, "client/m.py", "client/n.py", two + "\n", 5 )
    commit( repo, { "client/keep.py": function( "keep", [ "MARKC", "MARKE" ], 6 ), "client/fresh.py": function( "fresh", [ "MARKF" ], 7 ) }, "edit and add", 4 )
    git( repo, "rm", "-q", "client/gone.py" )
    commit( repo, {}, "delete", 3 )
    window = dd.window_of( repo, { "commit": c1 }, NOW )
    assert sorted( dd.changes( repo, window ), key=str ) == sorted( [ ( "client/keep.py", "client/keep.py" ), ( "client/m.py", "client/n.py" ), ( None, "client/fresh.py" ) ], key=str )
    assert dd.changed_files( repo, window ) == [ "client/fresh.py", "client/keep.py", "client/n.py" ], "the renamed file is listed, the deleted one is not"
    assert dd.old_paths( repo, window ) == { "client/n.py": "client/m.py" }, "only a renamed file has an old path"


def test_a_rename_alone_leaves_its_functions_out_and_an_edit_beside_it_judges_only_that_function( repo ):
    two = function( "same", [ "MARKA" ], 2 ) + "\n\n" + function( "edit", [ "MARKB" ], 3 )
    c1  = commit( repo, { "client/m.py": two }, "base", 48 )
    moved( repo, "client/m.py", "client/n.py", two, 5 )
    window = dd.window_of( repo, { "commit": c1 }, NOW )
    tree   = dd.source_at.ensure_worktree( repo, window[ "end" ], repo / ".wt-test" )
    try: assert dd.new_definitions( tree, repo, window )[ "defs" ] == [], "a pure rename holds the same functions it had"
    finally: dd.release( repo, tree )
    moved( repo, "client/n.py", "client/o.py", function( "same", [ "MARKA" ], 2 ) + "\n\n" + function( "edit", [ "MARKB", "MARKC" ], 4 ) + "\n\n" + function( "added", [ "MARKD" ], 5 ), 3 )
    window = dd.window_of( repo, { "commit": c1 }, NOW )
    tree   = dd.source_at.ensure_worktree( repo, window[ "end" ], repo / ".wt-test2" )
    try: names = sorted( d[ "name" ] for d in dd.new_definitions( tree, repo, window )[ "defs" ] )
    finally: dd.release( repo, tree )
    assert names == [ "added", "edit" ], "the renamed and edited file is read against its old path"


def test_a_new_definition_naming_the_lookup_tool_is_left_unjudged_and_counted_and_the_run_goes_on_to_advance( repo, tmp_path ):
    c1 = commit( repo, { "server/s1.py": function( "s1", [ "MARKB" ], 50 ) }, "old", 48 )
    c2 = commit( repo, { "client/a1.py": function( "a1", [ "MARKA" ], 2 ), "client/a2.py": function( "a2", [ "MARKA" ], 4 ), "client/leak.py": "def leak( x ):\n    return check_exists( x )\n" }, "a1, a2 and a leak", 3 )
    doc = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path ) )
    assert doc[ "status" ] == "ok" and doc[ "advanced_to" ] == c2 and doc[ "judge_calls" ] == 2, "only the two clean definitions were asked"
    assert [ ( u[ "code" ], "check_exists" in u[ "detail" ] ) for u in doc[ "unreadable" ] ] == [ ( err.BLINDNESS_BREACH, True ) ]
    assert doc[ "carried" ] == [], "a definition that can never be shown is not carried to the next run"
