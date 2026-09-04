"""
Cover `cosa.utils.worktree_artifacts` — the helper that gives a freshly created worktree
the untracked, non-secret artifacts it needs to run a WHOLE tier (row dde8b87a).

⚠️ THESE ARE THE HELPER'S OWN TESTS AND THEY PROVE NOTHING ABOUT THE WIRING. A component
can be complete, correct, fully covered and never reached by the running system. The
claim that the spawn path actually calls this lives in
`test_the_real_spawn_path_provisions_a_tier_capable_tree.py`, and the claim that a
worktree comes up usable lives in `test_new_worktrees_come_up_tier_capable.py`. Three
different claims, three files, on purpose.

The contract under test is FAIL-OPEN: this helper must never raise, whatever the script
does, because a seat missing `node_modules` is worse off and a spawn that dies because
provisioning failed is worse still.
"""

import logging
import os
import subprocess

import pytest

from cosa.utils import worktree_artifacts
from cosa.utils.worktree_artifacts import parse_artifact_outcomes, provision_worktree_artifacts


def _tree_with_script( tmp_path, body ):
    """A directory holding a stand-in provisioning script with the given body."""
    script_dir = tmp_path / "src" / "scripts"
    script_dir.mkdir( parents=True )
    script = script_dir / "link-worktree-artifacts.sh"
    script.write_text( body )
    script.chmod( 0o755 )
    return str( tmp_path )


class TestParsingTheScriptsMachineReadableLines:

    def test_the_four_outcome_keys_are_read( self ):
        parsed = parse_artifact_outcomes(
            "LINKED=node_modules\nALREADY=a\nSOURCE_ABSENT=b\nREFUSED=c\n"
        )
        assert parsed == { "node_modules": "LINKED", "a": "ALREADY",
                           "b": "SOURCE_ABSENT", "c": "REFUSED" }

    def test_prose_is_ignored_rather_than_guessed_at( self ):
        """
        The script prints human sentences too. A parser that tried to interpret them
        would turn a wording change into a moved verdict.
        """
        assert parse_artifact_outcomes( "Replacing a dangling symlink at /x\nLINKED=y\n" ) \
               == { "y": "LINKED" }

    def test_an_unknown_key_is_not_admitted( self ):
        assert parse_artifact_outcomes( "SOMETHING_ELSE=y\n" ) == {}

    def test_a_key_with_no_value_is_not_admitted( self ):
        assert parse_artifact_outcomes( "LINKED=\n" ) == {}

    def test_empty_and_none_are_empty_rather_than_an_error( self ):
        assert parse_artifact_outcomes( "" ) == {}
        assert parse_artifact_outcomes( None ) == {}


class TestTheHelperNeverRaisesAndAlwaysSaysWhatHappened:

    def test_a_falsy_target_is_a_no_op_and_not_an_error( self ):
        """
        An explicit project=None spawn inherits the caller's own cwd, which this helper
        does not know and must not guess at.
        """
        for target in ( None, "" ):
            result = provision_worktree_artifacts( target )
            assert result[ "status" ] == "no_target"
            assert result[ "provisioned" ] is False
            assert result[ "artifacts" ] == {}

    def test_a_tree_with_no_script_is_a_no_op_and_not_an_error( self, tmp_path ):
        """A foreign repo or an old checkout simply has nothing to run."""
        result = provision_worktree_artifacts( str( tmp_path ) )
        assert result[ "status" ] == "script_absent"
        assert result[ "provisioned" ] is False
        assert "link-worktree-artifacts.sh" in result[ "detail" ]

    def test_the_missing_script_is_narrated_under_debug( self, tmp_path, capsys ):
        provision_worktree_artifacts( str( tmp_path ), debug=True )
        assert "no script at" in capsys.readouterr().out

    def test_exit_zero_reports_ok_and_carries_the_outcomes( self, tmp_path ):
        tree   = _tree_with_script( tmp_path, '#!/usr/bin/env bash\necho "LINKED=node_modules"\n' )
        result = provision_worktree_artifacts( tree )
        assert result[ "provisioned" ] is True
        assert result[ "status" ]      == "ok"
        assert result[ "exit_code" ]   == 0
        assert result[ "artifacts" ]   == { "node_modules": "LINKED" }

    def test_the_outcomes_are_narrated_under_debug( self, tmp_path, capsys ):
        tree = _tree_with_script( tmp_path, '#!/usr/bin/env bash\necho "LINKED=node_modules"\n' )
        provision_worktree_artifacts( tree, debug=True )
        out = capsys.readouterr().out
        assert "node_modules" in out and tree in out

    def test_the_main_checkout_is_a_no_op_and_is_not_logged_twice( self, tmp_path, caplog ):
        """
        Exit 3 means the target owns the real artifacts. The LOCATION fact riding with it
        — this seat is in the shared tree — is already logged by `provision_worktree_venv`
        against the same target; a second copy would read as two seats in the main
        checkout rather than one.
        """
        tree = _tree_with_script( tmp_path, '#!/usr/bin/env bash\necho "MAIN"\nexit 3\n' )
        with caplog.at_level( logging.WARNING, logger="cosa.utils.worktree_artifacts" ):
            result = provision_worktree_artifacts( tree )
        assert result[ "status" ]      == "main_repo"
        assert result[ "provisioned" ] is False
        assert caplog.records == []

    def test_any_other_exit_is_a_failure_and_is_audible( self, tmp_path, caplog ):
        """
        The failure this row exists to kill is the one that looks like success, so a
        non-debug caller must hear about it without opening a nested dict.
        """
        tree = _tree_with_script( tmp_path, '#!/usr/bin/env bash\necho "REFUSED=node_modules"\nexit 5\n' )
        with caplog.at_level( logging.WARNING, logger="cosa.utils.worktree_artifacts" ):
            result = provision_worktree_artifacts( tree )
        assert result[ "status" ]    == "failed"
        assert result[ "exit_code" ] == 5
        assert result[ "artifacts" ] == { "node_modules": "REFUSED" }
        assert any( tree in r.getMessage() and "exit 5" in r.getMessage() for r in caplog.records )

    def test_stderr_is_used_as_detail_when_stdout_is_silent( self, tmp_path ):
        tree   = _tree_with_script( tmp_path, '#!/usr/bin/env bash\necho "boom" >&2\nexit 2\n' )
        result = provision_worktree_artifacts( tree )
        assert result[ "detail" ] == "boom"

    def test_a_script_that_cannot_run_at_all_does_not_take_the_spawn_down( self, tmp_path, monkeypatch, caplog ):
        """
        FAIL OPEN. Whatever subprocess does, this must return a dict rather than raise —
        a spawn that dies because provisioning failed is worse than a seat that has to
        symlink by hand.
        """
        tree = _tree_with_script( tmp_path, '#!/usr/bin/env bash\nexit 0\n' )

        def _explode( *a, **k ): raise OSError( "no exec for you" )

        monkeypatch.setattr( worktree_artifacts.subprocess, "run", _explode )
        with caplog.at_level( logging.WARNING, logger="cosa.utils.worktree_artifacts" ):
            result = provision_worktree_artifacts( tree )   # must NOT raise
        assert result[ "status" ]    == "failed"
        assert result[ "exit_code" ] is None
        assert "OSError" in result[ "detail" ]
        assert caplog.records

    def test_a_timeout_is_a_failure_and_not_an_exception( self, tmp_path, monkeypatch ):
        tree = _tree_with_script( tmp_path, '#!/usr/bin/env bash\nexit 0\n' )

        def _slow( *a, **k ): raise subprocess.TimeoutExpired( cmd="x", timeout=1 )

        monkeypatch.setattr( worktree_artifacts.subprocess, "run", _slow )
        assert provision_worktree_artifacts( tree )[ "status" ] == "failed"

    def test_the_script_path_is_relative_to_the_target_and_never_to_LUPIN_ROOT( self ):
        """
        A script shipped inside the tree it acts on can only be disagreed with by the
        environment, never informed by it. Resolving it from LUPIN_ROOT is the wrong-tree
        family that has bitten the pyc verifier, the purge script and the unit tier.
        """
        assert worktree_artifacts._SCRIPT_REL_PATH == \
               os.path.join( "src", "scripts", "link-worktree-artifacts.sh" )
        assert not os.path.isabs( worktree_artifacts._SCRIPT_REL_PATH )


class TestTheSpawnPayloadAlarm:
    """
    `artifact_alarm` is deliberately NOT a clause inside `venv_alarm`. The two answer
    different questions and failed independently for months: a tree can have a perfectly
    good interpreter and be unable to run a single `.test.ts`.
    """

    def test_nothing_wrong_is_silent( self ):
        from lupin_mcp.session_spawner import artifact_alarm
        assert artifact_alarm( None ) is None
        assert artifact_alarm( { "status": "ok" } ) is None
        assert artifact_alarm( { "status": "main_repo" } ) is None
        assert artifact_alarm( { "status": "script_absent" } ) is None

    def test_source_absent_is_not_an_alarm( self ):
        """
        A box that never ran `npm install` has nothing to lend. Alarming on it would
        fire on every spawn on a fresh host, and an alarm that always fires is one
        nobody reads.
        """
        from lupin_mcp.session_spawner import artifact_alarm
        assert artifact_alarm( { "status": "ok",
                                 "artifacts": { "node_modules": "SOURCE_ABSENT" } } ) is None

    def test_a_failure_names_the_tree_the_artifacts_and_the_exit_code( self ):
        from lupin_mcp.session_spawner import artifact_alarm
        line = artifact_alarm( { "status": "failed", "target": "/tmp/seat", "exit_code": 5,
                                 "artifacts": { "node_modules": "REFUSED",
                                                "src/scripts/cloud-run.env": "LINKED" } } )
        assert "/tmp/seat" in line
        assert "node_modules" in line
        assert "cloud-run.env" not in line, "an artifact that LANDED must not be named as unlanded"
        assert "exit 5" in line

    def test_a_failure_with_nothing_itemised_still_says_something( self ):
        """
        The script can fail before it reports any per-artifact outcome. A blank list
        would render an alarm that names no subject at all.
        """
        from lupin_mcp.session_spawner import artifact_alarm
        line = artifact_alarm( { "status": "failed", "target": "/tmp/seat", "exit_code": 2 } )
        assert "nothing reported" in line

    def test_the_alarming_seat_picker_notices_an_artifact_only_failure( self ):
        """
        🔴 THE SUMMARY MUST NOT DESCRIBE A DIFFERENT SEAT FROM THE ONE IT ALARMS ABOUT.
        Without this, a seat whose ONLY problem is artifacts would never be picked, and
        the top-level `artifact_alarm` would be computed from seat 0's clean verdict —
        the exact defect the per-seat picker was built to remove, re-created one level up.
        """
        from lupin_mcp.session_spawner import _alarming_seat
        clean   = { "session_name": "seat-0", "venv": { "status": "ok" },
                    "artifacts": { "status": "ok" } }
        broken  = { "session_name": "seat-1", "venv": { "status": "ok" },
                    "artifacts": { "status": "failed", "target": "/t", "exit_code": 5 } }
        assert _alarming_seat( [ clean, broken ] )[ "session_name" ] == "seat-1"
        assert _alarming_seat( [ clean ] )[ "session_name" ]         == "seat-0"
        assert _alarming_seat( [] ) is None
