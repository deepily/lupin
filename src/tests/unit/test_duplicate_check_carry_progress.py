"""The carry command moves recorded progress across a squash merge, on a fixture git repo."""
import fcntl
import json

import pytest

from lupin_mcp import duplicate_check_daily as dd
from tests.unit.test_duplicate_check_daily import NOW, git, history, parts_of, repo   # noqa: F401  (repo is the fixture)

OLD = "wip-old"
NEW = "wip-new"


def squash( repo, branch, tree_of="main" ):
    """Ensures: commits the tree of tree_of with no parent, points branch at it, returns the sha."""
    sha = git( repo, "commit-tree", git( repo, "rev-parse", f"{tree_of}^{{tree}}" ), "-m", "squash" )
    git( repo, "branch", branch, sha )
    return sha


def folder_of( tmp_path ): return tmp_path / "io" / "duplicate-check-daily"


def record( tmp_path, frontier, baseline_end=None ):
    """Ensures: records the frontier, and the baseline end when given, on the old branch."""
    folder = folder_of( tmp_path )
    dd.write_json( folder / dd.LAST_SUCCESS, { "commit": frontier, "at": NOW.isoformat(), "branch": OLD } )
    if baseline_end is not None: dd.write_json( folder / dd.BASELINE, { "status": dd.BASELINE_DONE, "end": baseline_end, "left_to_judge": 0, "at": NOW.isoformat(), "branch": OLD } )
    return folder


def snapshot( folder ): return { path.name: path.read_bytes() for path in sorted( folder.glob( "*.json" ) ) }


@pytest.fixture
def squashed( repo, tmp_path ):
    """Ensures: wip-new squashes main's tree and both files are recorded on wip-old."""
    c1, c2, c3 = history( repo )
    git( repo, "branch", OLD )
    target = squash( repo, NEW )
    return repo, tmp_path, record( tmp_path, c3, c1 ), ( c1, c3, target )


def test_a_squash_with_the_same_tree_carries_both_files_to_the_new_branch_and_the_next_run_resumes_with_nothing_to_judge( squashed ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    refused = dd.run( repo, NOW, "cron", 10, "/bin/claude", parts_of( tmp_path ), branch=NEW )
    assert refused[ "refusal" ] == dd.BRANCH_CHANGED, "without the carry the new branch is refused, so the carry is what lets it run"
    answer = dd.carry_progress( repo, folder, NEW, target, NOW )
    origin = { "branch": OLD, "commit": c3 }
    assert answer == { "carried": True, "branch": NEW, "commit": target, "carried_from": origin, "overridden": [] }
    assert json.loads( ( folder / dd.LAST_SUCCESS ).read_text() ) == { "commit": target, "at": NOW.isoformat(), "branch": NEW, "carried_from": origin }
    assert json.loads( ( folder / dd.BASELINE ).read_text() ) == { "status": dd.BASELINE_DONE, "end": c1, "left_to_judge": 0, "at": NOW.isoformat(), "branch": NEW, "carried_from": origin }
    done = dd.run( repo, NOW, "cron", 10, "/bin/claude", parts_of( tmp_path ), branch=NEW )
    assert ( done[ "status" ], done[ "judged" ], done[ "judge_calls" ], done[ "backlog_total" ] ) == ( "ok", 0, 0, 0 )
    base = dd.run( repo, NOW, "cron", None, "/bin/claude", parts_of( tmp_path ), branch=NEW, ceiling=10, baseline=True )
    assert ( base[ "status" ], base[ "note" ] ) == ( "ok", "baseline complete" ), "the carried baseline stays complete on the new branch"


def test_a_different_tree_is_refused_with_both_files_untouched_and_an_override_carries_it_and_says_so( squashed ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    git( repo, "checkout", "-q", "-b", "other", "main" )
    ( repo / "client" ).joinpath( "extra.py" ).write_text( "x = 1\n" )
    git( repo, "add", "-A" )
    git( repo, "commit", "-q", "-m", "more" )
    moved = squash( repo, "wip-moved", tree_of="other" )
    before = snapshot( folder )
    answer = dd.carry_progress( repo, folder, "wip-moved", moved, NOW )
    assert answer == { "carried": False, "refusal": dd.CARRY_TREE, "recorded": c3, "target": moved }
    assert snapshot( folder ) == before
    forced = dd.carry_progress( repo, folder, "wip-moved", moved, NOW, allow_tree_change=True )
    assert ( forced[ "carried" ], forced[ "overridden" ] ) == ( True, [ dd.CARRY_TREE ] )
    assert json.loads( ( folder / dd.LAST_SUCCESS ).read_text() )[ "commit" ] == moved


def test_no_record_is_refused_and_nothing_is_written( repo, tmp_path ):
    history( repo )
    answer = dd.carry_progress( repo, folder_of( tmp_path ), "main", "main", NOW )
    assert answer == { "carried": False, "refusal": dd.CARRY_NO_RECORD }
    assert not folder_of( tmp_path ).exists()


def test_a_target_that_is_not_on_the_branch_or_not_a_commit_is_refused_even_with_the_override( squashed ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    git( repo, "checkout", "-q", "-b", "side", "main" )
    off = git( repo, "commit-tree", git( repo, "rev-parse", "main^{tree}" ), "-p", c3, "-m", "off" )
    before = snapshot( folder )
    assert dd.carry_progress( repo, folder, NEW, off, NOW, allow_tree_change=True ) == { "carried": False, "refusal": dd.CARRY_TARGET, "commit": off, "branch": NEW }
    assert dd.carry_progress( repo, folder, NEW, "no-such-ref", NOW, allow_tree_change=True ) == { "carried": False, "refusal": dd.CARRY_TARGET, "commit": "no-such-ref", "branch": NEW }
    assert snapshot( folder ) == before


def test_a_recorded_commit_this_checkout_does_not_hold_is_refused_even_with_the_override( squashed ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    gone = "0" * 40
    record( tmp_path, gone )
    before = snapshot( folder )
    assert dd.carry_progress( repo, folder, NEW, target, NOW, allow_tree_change=True ) == { "carried": False, "refusal": dd.CARRY_UNKNOWN, "commit": gone }
    assert snapshot( folder ) == before


def test_a_baseline_that_ends_off_the_judged_lineage_is_refused_and_an_override_carries_it_and_says_so( squashed ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    git( repo, "checkout", "-q", "-b", "side", c1 )
    stray = git( repo, "commit-tree", git( repo, "rev-parse", "main^{tree}" ), "-p", c1, "-m", "stray" )
    record( tmp_path, c3, stray )
    before = snapshot( folder )
    assert dd.carry_progress( repo, folder, NEW, target, NOW ) == { "carried": False, "refusal": dd.CARRY_LINEAGE, "baseline_end": stray, "judged": c3 }
    assert snapshot( folder ) == before
    forced = dd.carry_progress( repo, folder, NEW, target, NOW, allow_tree_change=True )
    assert ( forced[ "carried" ], forced[ "overridden" ] ) == ( True, [ dd.CARRY_LINEAGE ] )


def test_a_baseline_end_the_checkout_does_not_hold_fails_the_lineage_check_and_is_not_an_error( squashed ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    record( tmp_path, c3, "1" * 40 )
    assert dd.carry_progress( repo, folder, NEW, target, NOW )[ "refusal" ] == dd.CARRY_LINEAGE


def test_with_only_last_success_recorded_no_baseline_file_appears( squashed ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    ( folder / dd.BASELINE ).unlink()
    assert dd.carry_progress( repo, folder, NEW, target, NOW )[ "carried" ] is True
    assert not ( folder / dd.BASELINE ).exists()
    assert json.loads( ( folder / dd.LAST_SUCCESS ).read_text() )[ "branch" ] == NEW


def test_with_only_a_baseline_recorded_its_end_is_the_frontier_that_must_match_and_last_success_is_not_created( squashed ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    ( folder / dd.LAST_SUCCESS ).unlink()
    assert dd.carry_progress( repo, folder, NEW, target, NOW )[ "refusal" ] == dd.CARRY_TREE, "c1's tree is not the target's"
    record( tmp_path, c3, c3 )
    ( folder / dd.LAST_SUCCESS ).unlink()
    answer = dd.carry_progress( repo, folder, NEW, target, NOW )
    assert ( answer[ "carried" ], answer[ "carried_from" ] ) == ( True, { "branch": OLD, "commit": c3 } )
    assert not ( folder / dd.LAST_SUCCESS ).exists() and json.loads( ( folder / dd.BASELINE ).read_text() )[ "branch" ] == NEW


def test_carry_mode_prints_the_answer_and_returns_zero_when_it_moved_and_three_when_refused( squashed ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    shown = []
    assert dd.carry_mode( repo, parts_of( tmp_path ), NEW, "no-such-ref", NOW, False, shown.append ) == dd.REFUSED_EXIT
    assert json.loads( shown[ -1 ] )[ "refusal" ] == dd.CARRY_TARGET
    assert dd.carry_mode( repo, parts_of( tmp_path ), NEW, target, NOW, False, shown.append ) == 0
    assert json.loads( shown[ -1 ] )[ "commit" ] == target


def test_carry_mode_writes_nothing_while_another_run_holds_the_run_lock( squashed ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    before, shown = snapshot( folder ), []
    with open( folder / dd.RUN_LOCK, "a" ) as handle:
        fcntl.flock( handle, fcntl.LOCK_EX | fcntl.LOCK_NB )
        assert dd.carry_mode( repo, parts_of( tmp_path ), NEW, target, NOW, False, shown.append ) == dd.REFUSED_EXIT
    assert json.loads( shown[ -1 ] ) == { "carried": False, "refusal": dd.CARRY_RUNNING }
    assert snapshot( folder ) == before


def test_main_carry_progress_runs_the_carry_with_no_limit_and_no_binary_and_resolves_the_branch( squashed, capsys ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    code = dd.main( [ "--carry-progress", "--branch", NEW, "--to-commit", target, "--root", str( repo ) ], parts=parts_of( tmp_path ), now=NOW, config=None )
    assert code == 0 and json.loads( capsys.readouterr().out )[ "branch" ] == NEW


def test_main_carry_progress_builds_the_live_parts_when_none_are_given( squashed, monkeypatch, capsys ):
    repo, tmp_path, folder, ( c1, c3, target ) = squashed
    monkeypatch.setattr( dd, "live_parts", lambda: parts_of( tmp_path ) )
    assert dd.main( [ "--carry-progress", "--branch", NEW, "--to-commit", target, "--root", str( repo ) ] ) == 0
    assert json.loads( capsys.readouterr().out )[ "carried" ] is True


@pytest.mark.parametrize( "argv", [ [ "--carry-progress" ], [ "--carry-progress", "--to-commit", "x", "--adaptive" ], [ "--carry-progress", "--to-commit", "x", "--baseline" ],
                                    [ "--carry-progress", "--to-commit", "x", "--status" ], [ "--to-commit", "x" ], [ "--allow-tree-change" ] ] )
def test_main_refuses_a_carry_flag_in_a_combination_it_does_not_belong_to( argv, capsys ):
    with pytest.raises( SystemExit ) as stop: dd.main( argv )
    assert stop.value.code == 2 and "carry-progress" in capsys.readouterr().err


def test_the_continuity_refusal_names_the_carry_command_and_keeps_the_other_two_ways_out():
    refusal = { "refusal": dd.BRANCH_CHANGED, "branch": NEW, "previous": OLD, "newest": None }
    spoken, abstract = dd.refusal_message( refusal, None )
    assert f"python -m lupin_mcp.duplicate_check_daily --carry-progress --branch {NEW} --to-commit <commit>" in abstract
    assert f"--branch {OLD}" in abstract and "delete last-success.json and baseline.json" in abstract
