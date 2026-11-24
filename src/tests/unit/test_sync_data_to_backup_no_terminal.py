"""
Unit tests for the version prompt of the data backup sync script.

The script paused at "Press Enter to continue" whenever its version differed from the canonical one.
A seat's Bash call has no terminal, so nothing answered and the run sat for 2h20m.
Every run here is a dry run over temporary folders, so nothing under DATA02 or the real projects-data is read or written.
"""

import os
import pty
import subprocess
import sys
from pathlib import Path

import pytest

import cosa.utils.util as cu

SCRIPT       = Path( cu.get_project_root() ) / "src" / "scripts" / "sync-data-to-backup.sh"
LIMIT        = 30
PROMPT_TEXT  = "Press Enter to continue"
NO_TERMINAL  = "No terminal on stdin: continuing with the current version."
DRY_COMPLETE = "DRY RUN COMPLETE"


@pytest.fixture
def folders( tmp_path ):
    """
    Give temporary source and destination folders and a differing canonical script.

    The canonical script names another version than the script's. The destination's parent exists, as the script requires, and the destination itself is empty.
    """
    source = tmp_path / "source"
    dest   = tmp_path / "backups" / "dest"
    root   = tmp_path / "pip-root"
    source.mkdir()
    dest.parent.mkdir()
    ( source / "a.txt" ).write_text( "payload\n", encoding="utf-8" )
    ( root / "scripts" ).mkdir( parents=True )
    ( root / "scripts" / "rsync-backup.sh" ).write_text( "#!/bin/bash\n# rsync-backup.sh v9.9\n", encoding="utf-8" )
    assert not str( dest ).startswith( "/mnt/DATA02" ) and not str( source ).startswith( "/mnt/DATA01" )
    return { "source": source, "dest": dest, "root": root }


def script_env( folders, **extra ):
    """Build the run's environment: the temporary folders, the canonical root and no skip switch."""
    env = { k: v for k, v in os.environ.items() if k != "SKIP_VERSION_CHECK" }
    env.update( { "DEEPILY_DATA_DIR": str( folders[ "source" ] ), "DEEPILY_BACKUP_DEST_DIR": str( folders[ "dest" ] ),
                  "PLANNING_IS_PROMPTING_ROOT": str( folders[ "root" ] ) } )
    env.update( extra )
    return env


def test_a_silent_open_stdin_does_not_hang_the_version_prompt( folders ):
    """
    A stdin that is open and never answers must not stop the run.

    This is the shape of the bug: a pipe that stays open, not a closed one. Without the terminal check, read waits on it.
    """
    proc = subprocess.Popen( [ "bash", str( SCRIPT ) ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=script_env( folders ), text=True )
    try: proc.wait( timeout=LIMIT )
    except subprocess.TimeoutExpired:
        proc.kill()
        out = proc.stdout.read()
        pytest.fail( f"the script waited on an open stdin for over {LIMIT}s; output so far: {out[ -300: ]!r}" )
    out = proc.stdout.read()
    proc.stdin.close()
    assert proc.returncode == 0 and "Update Available" in out and NO_TERMINAL in out and DRY_COMPLETE in out
    assert PROMPT_TEXT not in out
    assert list( folders[ "dest" ].iterdir() ) == [] if folders[ "dest" ].exists() else True


def test_a_closed_stdin_prints_the_warning_and_carries_on( folders ):
    """A closed stdin gets the version warning and a finished dry run."""
    done = subprocess.run( [ "bash", str( SCRIPT ) ], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=script_env( folders ), timeout=LIMIT )
    assert done.returncode == 0 and "Local version:" in done.stdout and "Canonical version: " in done.stdout and "v9.9" in done.stdout
    assert NO_TERMINAL in done.stdout and DRY_COMPLETE in done.stdout and PROMPT_TEXT not in done.stdout


def test_skip_version_check_still_skips_the_warning( folders ):
    """SKIP_VERSION_CHECK keeps working: no warning and no notice about the terminal."""
    done = subprocess.run( [ "bash", str( SCRIPT ) ], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=script_env( folders, SKIP_VERSION_CHECK="1" ), timeout=LIMIT )
    assert done.returncode == 0 and "Update Available" not in done.stdout and NO_TERMINAL not in done.stdout and DRY_COMPLETE in done.stdout


def test_a_terminal_on_stdin_still_gets_the_prompt_and_continues_on_enter( folders ):
    """
    With a terminal on stdin the prompt is shown and Enter lets the run go on.

    A pseudo-terminal stands in for the person.
    """
    if sys.platform == "win32": pytest.skip( "needs a pseudo-terminal" )
    parent, child = pty.openpty()
    try:
        proc = subprocess.Popen( [ "bash", str( SCRIPT ) ], stdin=child, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=script_env( folders ), text=True )
        os.write( parent, b"\n" )
        try: out, _ = proc.communicate( timeout=LIMIT )
        except subprocess.TimeoutExpired:
            proc.kill()
            pytest.fail( "the script did not continue after Enter on a terminal" )
    finally:
        os.close( child )
        os.close( parent )
    assert proc.returncode == 0 and PROMPT_TEXT in out and NO_TERMINAL not in out and DRY_COMPLETE in out


def test_the_dry_run_leaves_the_temporary_destination_empty( folders ):
    """A dry run copies nothing, into the temporary destination the environment names."""
    done = subprocess.run( [ "bash", str( SCRIPT ) ], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=script_env( folders ), timeout=LIMIT )
    assert f"Destination: {folders[ 'dest' ]}/" in done.stdout and "/mnt/DATA02" not in done.stdout
    assert not folders[ "dest" ].exists() or list( folders[ "dest" ].iterdir() ) == []
