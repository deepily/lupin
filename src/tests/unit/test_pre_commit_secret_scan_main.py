"""
The staged-diff entry points of `src/scripts/pre-commit-secret-scan.py`.

The sibling file feeds the hunk reader a canned diff.
These cases stage real files in a throwaway repo and run the hook against it.
The hook exits 1 only for a credential value on a line this commit adds.
"""

import importlib.util
import subprocess

import pytest

import cosa.utils.util as cu


def _load_hook():
    spec = importlib.util.spec_from_file_location(
        "precommit_secret_scan_main", cu.get_project_root() + "/src/scripts/pre-commit-secret-scan.py" )
    hook = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( hook )
    return hook


@pytest.fixture
def staged_repo( tmp_path, monkeypatch ):
    """A repo with one committed file; the hook runs with it as the working directory."""
    def git( *args ):
        subprocess.run( [ "git", "-C", str( tmp_path ), *args ], check=True, capture_output=True )
    git( "init", "-q" )
    git( "config", "user.email", "g@example.com" )
    git( "config", "user.name", "g" )
    ( tmp_path / "base.py" ).write_text( "x = 1\n" )
    git( "add", "-A" )
    git( "commit", "-q", "-m", "base" )
    monkeypatch.chdir( tmp_path )
    return tmp_path, git


# Built at run time so this file never carries a flaggable literal of its own.
CREDENTIAL_LINE = "db_" + "password = 'Zq81xKd93LmPw0Tn'\n"


def test_the_default_diff_is_the_staged_one_with_no_relative_scoping( staged_repo ):
    """With no diff given the hook reads the index, and sees a file staged outside the cwd."""
    root, git = staged_repo
    ( root / "sub" ).mkdir()
    ( root / "sub" / "new.py" ).write_text( "a = 1\nb = 2\n" )
    git( "add", "sub/new.py" )
    assert _load_hook().added_lines_by_file() == { "sub/new.py": { 1, 2 } }


def test_the_default_diff_runs_git_with_the_no_relative_flag( monkeypatch ):
    seen = {}
    def fake_run( cmd, **kw ):
        seen[ "cmd" ] = cmd
        class _Done: stdout = ""
        return _Done()
    hook = _load_hook()
    monkeypatch.setattr( hook.subprocess, "run", fake_run )
    assert hook.added_lines_by_file() == { }
    assert "--no-relative" in seen[ "cmd" ] and "--cached" in seen[ "cmd" ]


def test_nothing_staged_passes( staged_repo ):
    assert _load_hook().main() == 0


def test_a_staged_credential_blocks_the_commit_and_masks_the_value( staged_repo, capsys ):
    root, git = staged_repo
    ( root / "cfg.py" ).write_text( "ok = 1\n" + CREDENTIAL_LINE )
    git( "add", "cfg.py" )
    assert _load_hook().main() == 1
    err = capsys.readouterr().err
    assert "COMMIT BLOCKED" in err
    assert "cfg.py:2" in err and "db_password" in err
    assert "Zq81xKd93LmPw0Tn" not in err
    assert "1 flagged line(s)." in err


def test_a_credential_on_a_line_this_commit_did_not_add_passes( staged_repo ):
    """The old line stays; only an added line is judged."""
    root, git = staged_repo
    ( root / "cfg.py" ).write_text( CREDENTIAL_LINE )
    git( "add", "cfg.py" )
    git( "commit", "-q", "--no-verify", "-m", "old secret" )
    ( root / "cfg.py" ).write_text( CREDENTIAL_LINE + "harmless = 2\n" )
    git( "add", "cfg.py" )
    assert _load_hook().main() == 0


def test_a_staged_binary_path_is_not_scanned( staged_repo ):
    root, git = staged_repo
    ( root / "blob.png" ).write_text( CREDENTIAL_LINE )
    git( "add", "blob.png" )
    assert _load_hook().main() == 0


def test_a_path_git_cannot_show_is_skipped_even_if_it_printed_something( monkeypatch ):
    """A failed show is not a blob: whatever it printed is never scanned."""
    hook = _load_hook()
    monkeypatch.setattr( hook, "added_lines_by_file", lambda diff=None: { "ghost.py": { 1 } } )
    class _Failed:
        returncode = 128
        stdout     = CREDENTIAL_LINE.encode()
    monkeypatch.setattr( hook.subprocess, "run", lambda *a, **k: _Failed() )
    assert hook.main() == 0
