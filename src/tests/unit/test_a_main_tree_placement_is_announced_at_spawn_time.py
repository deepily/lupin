"""
A seat spawned into the SHARED MAIN CHECKOUT must be told so, at a level a non-debug
caller sees (row 2026-09-02).

THE DEFECT. `link-worktree-venv.sh` exits 3 on the main repo — correctly, it is
declining to replace a real `.venv` directory with a link to itself — and that one exit
code carries TWO facts: provisioning has nothing to do, and whoever is about to work
here is standing in the tree the whole fleet shares. Only the first had a name. The
helper mapped exit 3 to status "main_repo" under the comment "is the main checkout -
nothing to do", printed it under `if debug:`, and the only human-readable text on the
whole path was the script's own `detail` — a sentence whose subject is a venv. Measured
2026-09-02: two workers landed in the main checkout, one wrote to it during a live
14-minute tier run, and a manager had to decide mid-run whether to discard the result. A
careful operator read that detail as a venv message BECAUSE IT IS ONE.

⚠️ WHAT THESE TESTS ASSERT, AND WHY IT IS NOT THE WORDING. A guard that pins a literal
string is the same defect one level up: it would go green for any message at any level
in any channel, so long as the characters matched, and red on a rewording that improved
it. So these assert the ACT — that a main-repo placement puts a record on a real logging
channel at a level a caller who passed no debug flag receives, and that the record names
the tree it happened to. The wording is free to change; the audibility is not.

⚠️ AND THE FIXTURES DISCRIMINATE, WHICH IS THE PART COVERAGE CANNOT SEE. The fake script
echoes the path it was handed, so a helper announcing a hardcoded tree, or the wrong
one, produces a visibly different record rather than an identical one. The silent-script
case exists for the same reason: it holds only if the announcement is generated here
rather than forwarded from the script's stdout, which is exactly the confusion that
produced the defect.
"""

import logging

import pytest

from cosa.utils.worktree_venv import provision_worktree_venv


def _make_tree( root, exit_code=3, stdout_line="REFUSING: it is the MAIN repo, which owns the real .venv" ):
    """
    Build a directory that looks like a repo, holding a fake part-1 script.

    Requires:
        - root is a pathlib.Path that may or may not exist yet

    Ensures:
        - the script echoes the argument it was given, so a caller passing the wrong
          path produces visibly different output
        - the script exits with `exit_code`, defaulting to the main-repo refusal
        - an empty `stdout_line` yields a script that says NOTHING at all
        - returns the tree root as a string
    """
    script_dir = root / "src" / "scripts"
    script_dir.mkdir( parents=True, exist_ok=True )
    script = script_dir / "link-worktree-venv.sh"
    body   = [ "#!/usr/bin/env bash" ]
    if stdout_line: body.append( f'echo "{stdout_line} arg=$1"' )
    body.append( f"exit {exit_code}" )
    script.write_text( "\n".join( body ) + "\n" )
    script.chmod( 0o755 )
    return str( root )


def _placement_records( caplog, target ):
    """Records at WARNING-or-above that name `target`."""
    return [ r for r in caplog.records
             if r.levelno >= logging.WARNING and target in r.getMessage() ]


class TestThePlacementReachesACallerWhoPassedNoDebugFlag:
    """
    The whole failure was a channel choice: the fact existed and went to a channel
    nobody was listening on. These tests are about the channel, not the sentence.
    """

    @pytest.mark.parametrize( "kwargs", [ {}, { "debug": False } ] )
    def test_a_main_repo_placement_is_audible_without_asking_for_debug( self, tmp_path, caplog, kwargs ):
        tree = _make_tree( tmp_path / "shared-main" )
        with caplog.at_level( logging.WARNING ):
            result = provision_worktree_venv( tree, **kwargs )
        assert result[ "status" ] == "main_repo"
        assert _placement_records( caplog, tree ), "a main-repo placement produced no warning-level record naming the tree"

    def test_the_record_names_the_tree_it_actually_happened_to( self, tmp_path, caplog ):
        """
        A constant message would satisfy 'something was logged'. It must not satisfy
        'the RIGHT tree was named' — an operator's next move is to go look at it.
        """
        tree      = _make_tree( tmp_path / "the-one-we-landed-in" )
        elsewhere = str( tmp_path / "some-other-tree" )
        with caplog.at_level( logging.WARNING ):
            result = provision_worktree_venv( tree )
        # PIN THE BRANCH. Two code paths log at WARNING naming a target — this one and
        # the generic could-not-finish one — so "a warning naming the tree" alone is
        # satisfied by more than one state and cannot say which ran.
        assert result[ "status" ] == "main_repo"
        messages = " ".join( r.getMessage() for r in caplog.records )
        assert tree      in messages
        assert elsewhere not in messages

    def test_it_is_announced_even_when_the_script_itself_says_nothing( self, tmp_path, caplog ):
        """
        DISCRIMINATING, and the reason this file exists. If the announcement were
        forwarded from the script's stdout, a silent script would produce silence — and
        the message a reader got would be about a venv, because that is what the script
        talks about. This passes only if the placement fact is generated HERE.
        """
        tree = _make_tree( tmp_path / "silent-main", stdout_line="" )
        with caplog.at_level( logging.WARNING ):
            result = provision_worktree_venv( tree )
        assert result[ "status" ] == "main_repo"    # pin the branch, per above
        assert result[ "detail" ] == ""
        assert _placement_records( caplog, tree )

    def test_an_ordinary_worktree_is_announced_nowhere( self, tmp_path, caplog ):
        """
        A line on every ordinary spawn is a line readers learn to skip, and this signal
        is worth nothing the day it becomes background. Exit 0 stays silent.
        """
        tree = _make_tree( tmp_path / "wt", exit_code=0, stdout_line="Linked:" )
        with caplog.at_level( logging.WARNING ):
            result = provision_worktree_venv( tree )
        assert result[ "status" ] == "ok"
        assert caplog.records == []

    def test_provisioning_still_reports_nothing_to_do( self, tmp_path, caplog ):
        """
        The announcement must not turn a correct no-op into a failure. `provisioned`
        stays False and the status stays `main_repo`: the main checkout owns the real
        venv and there was never anything to provision.
        """
        tree = _make_tree( tmp_path / "main" )
        with caplog.at_level( logging.WARNING ):
            result = provision_worktree_venv( tree )
        assert result[ "provisioned" ] is False
        assert result[ "status" ]      == "main_repo"
        assert result[ "exit_code" ]   == 3


class TestTheSpawnResultCarriesThePlacement:
    """
    A manager reads the top of a spawn result. The log line reaches the MCP server's
    log; the payload field reaches the human who fired the spawn, which is who has to
    decide whether the seat may proceed.
    """

    def _spawn( self, monkeypatch, tmp_path, provisioning ):
        from lupin_mcp import session_spawner
        monkeypatch.setattr( session_spawner, "_resolve_project_root", lambda p: "/some/tree" )
        monkeypatch.setattr( session_spawner, "provision_worktree_venv", lambda *a, **k: provisioning )

        class _Runner:
            def __call__( self, argv, env=None ):
                class _R: returncode = 0; stdout = ""; stderr = ""
                return _R()

        return session_spawner.spawn_sessions(
            1, "task", "mgr-sid", script_path="x", project="lupin",
            runner=_Runner(), session_dir=tmp_path, dry_run=True,
        )

    def test_a_main_repo_placement_raises_a_top_level_alarm_naming_the_tree( self, monkeypatch, tmp_path ):
        res = self._spawn( monkeypatch, tmp_path, {
            "provisioned": False, "status": "main_repo", "exit_code": 3,
            "target": "/repos/lupin", "detail": "REFUSING: ... owns the real .venv ...",
        } )
        # TOP-LEVEL, not nested: the nested verdict is how the reap's honest per-seat
        # answers went unread (row 3b0c5f90).
        assert "placement_alarm" in res
        assert res[ "placement_alarm" ] is not None
        assert "/repos/lupin" in res[ "placement_alarm" ]

    def test_the_spawn_still_succeeds( self, monkeypatch, tmp_path ):
        """Fail open, deliberately — the same shape as stash_guard. Announce, never block."""
        res = self._spawn( monkeypatch, tmp_path, {
            "provisioned": False, "status": "main_repo", "exit_code": 3,
            "target": "/repos/lupin", "detail": "",
        } )
        assert res[ "spawned" ][ 0 ][ "status" ] == "spawned"

    def test_the_venv_alarm_stays_silent_on_a_main_repo_placement( self, monkeypatch, tmp_path ):
        """
        The two facts must not be welded back together. There is no venv problem here —
        the main checkout owns a real one — so a venv-named field claiming otherwise
        would recreate the defect with the polarity flipped.
        """
        res = self._spawn( monkeypatch, tmp_path, {
            "provisioned": False, "status": "main_repo", "exit_code": 3,
            "target": "/repos/lupin", "detail": "",
        } )
        assert res[ "venv_alarm" ] is None

    @pytest.mark.parametrize( "status,provisioned", [
        ( "ok", True ), ( "no_target", False ), ( "script_absent", False ), ( "failed", False ),
    ] )
    def test_every_other_outcome_raises_no_placement_alarm( self, monkeypatch, tmp_path, status, provisioned ):
        """A worktree, a foreign repo and a broken script are all NOT a main-tree landing."""
        res = self._spawn( monkeypatch, tmp_path, {
            "provisioned": provisioned, "status": status, "exit_code": 0,
            "target": "/some/tree", "detail": "",
        } )
        assert res[ "placement_alarm" ] is None


class TestThePlacementAlarmHelperOnItsOwn:

    def test_none_in_none_out( self ):
        from lupin_mcp.session_spawner import placement_alarm
        assert placement_alarm( None ) is None

    def test_an_empty_dict_is_not_an_alarm( self ):
        from lupin_mcp.session_spawner import placement_alarm
        assert placement_alarm( {} ) is None

    def test_the_line_names_the_tree_and_says_plainly_what_it_is( self, ):
        from lupin_mcp.session_spawner import placement_alarm
        line = placement_alarm( { "status": "main_repo", "exit_code": 3,
                                  "target": "/repos/lupin", "detail": "" } )
        # Two things a reader needs to act: WHICH tree, and that it is the shared one.
        # Asserted as substance rather than wording — "main" and "shared" are the claim.
        assert "/repos/lupin" in line
        assert "main"   in line.lower()
        assert "shared" in line.lower()

    def test_two_different_trees_produce_two_different_lines( self ):
        """
        THE THIN-MARGIN CASE. `test_the_line_names_the_tree...` checks that one target
        appears; a constant line mentioning some other tree would fail it, but a line
        built from the WRONG field of the same dict might not. Two calls that differ
        only in `target` must differ in their output — that is what "names the tree"
        means, and it cannot be satisfied by any constant.
        """
        from lupin_mcp.session_spawner import placement_alarm
        a = placement_alarm( { "status": "main_repo", "exit_code": 3, "target": "/tree/a", "detail": "" } )
        b = placement_alarm( { "status": "main_repo", "exit_code": 3, "target": "/tree/b", "detail": "" } )
        assert a != b
        assert "/tree/a" in a and "/tree/a" not in b
        assert "/tree/b" in b and "/tree/b" not in a

    def test_the_two_alarms_are_never_both_raised_for_one_outcome( self ):
        """
        THE OTHER THIN-MARGIN CASE, stated as the invariant rather than as one status.
        One provisioning result describes one outcome; a venv failure and a main-tree
        landing are different outcomes and cannot both be true of it. If both fields
        ever populate together, the two facts have been welded back into one channel —
        which is the defect this whole change exists to undo.
        """
        from lupin_mcp.session_spawner import placement_alarm, venv_alarm
        for status in ( "ok", "no_target", "script_absent", "main_repo", "failed" ):
            p = { "provisioned": status == "ok", "status": status, "exit_code": 3,
                  "target": "/some/tree", "detail": "" }
            raised = [ f for f in ( placement_alarm( p ), venv_alarm( p ) ) if f is not None ]
            assert len( raised ) <= 1, f"{status}: both alarms fired for one outcome"

    def test_it_does_not_describe_the_landing_as_a_venv_problem( self ):
        """
        The subject of this line is a LOCATION. A reader who is told about a venv goes
        and looks at a venv — measured, twice, on 2026-09-02.
        """
        from lupin_mcp.session_spawner import placement_alarm
        line = placement_alarm( { "status": "main_repo", "exit_code": 3,
                                  "target": "/repos/lupin", "detail": "" } )
        assert "venv" not in line.lower()
