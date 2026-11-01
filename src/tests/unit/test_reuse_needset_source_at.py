"""
The source tree of one commit, exported once and read in place of the working tree.
"""
import io
import subprocess
import tarfile

import pytest

from lupin_mcp.reuse_needset import errors as er, source_at, strip

BEFORE = "def f( x ):\n    return x + 1\n"
AFTER  = "# a peer added a line above\n\ndef g():\n    return 0\n\n\ndef f( x ):\n    return x + 2\n"


def git( repo, *argv ):
    """Run git in repo and return its stdout."""
    return subprocess.run( [ "git", "-C", str( repo ), *argv ], check=True, capture_output=True, text=True ).stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    """A repository whose commit holds the old text and whose working tree has since moved on."""
    root = tmp_path / "repo"
    ( root / "src" / "cosa" ).mkdir( parents=True )
    ( root / "src" / "lupin_mcp" ).mkdir()
    ( root / "src" / "cosa" / "m.py" ).write_text( BEFORE, encoding="utf-8" )
    ( root / "src" / "lupin_mcp" / "keep.py" ).write_text( "X = 1\n", encoding="utf-8" )
    ( root / "outside.txt" ).write_text( "not under src\n", encoding="utf-8" )
    git( root, "init", "-q" )
    git( root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "." )
    git( root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first" )
    return root


def head( repo ):
    """Return the full sha of the repository's commit."""
    return git( repo, "rev-parse", "HEAD" )


def test_the_export_holds_the_commits_files_even_after_the_working_tree_changed( repo, tmp_path ):
    sha = head( repo )
    ( repo / "src" / "cosa" / "m.py" ).write_text( AFTER, encoding="utf-8" )
    ( repo / "src" / "cosa" / "new.py" ).write_text( "Y = 2\n", encoding="utf-8" )
    out = source_at.export( repo, sha, tmp_path / "at" )
    assert ( out / "src" / "cosa" / "m.py" ).read_text( encoding="utf-8" ) == BEFORE
    assert not ( out / "src" / "cosa" / "new.py" ).exists() and not ( out / "outside.txt" ).exists()
    assert ( out / source_at.MARKER ).read_text( encoding="utf-8" ).strip() == sha and not ( tmp_path / "at.part" ).exists()


def test_a_second_export_of_the_same_commit_reuses_the_folder_and_another_commit_is_refused( repo, tmp_path ):
    sha = head( repo )
    out = source_at.export( repo, sha, tmp_path / "at" )
    ( out / "src" / "cosa" / "m.py" ).write_text( "touched\n", encoding="utf-8" )
    assert source_at.export( repo, "HEAD", tmp_path / "at" ) == out and ( out / "src" / "cosa" / "m.py" ).read_text( encoding="utf-8" ) == "touched\n"
    ( repo / "src" / "cosa" / "m.py" ).write_text( AFTER, encoding="utf-8" )
    git( repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "second" )
    with pytest.raises( er.NeedsetError ) as e: source_at.export( repo, "HEAD", tmp_path / "at" )
    assert e.value.code == er.SOURCE_EXPORT_MISMATCH and "at" in e.value.detail
    ( tmp_path / "plain" ).mkdir()
    with pytest.raises( er.NeedsetError ) as e: source_at.export( repo, sha, tmp_path / "plain" )
    assert e.value.code == er.SOURCE_EXPORT_MISMATCH


def test_a_stale_partial_export_is_cleared_and_an_unknown_commit_or_missing_src_fails_by_name( repo, tmp_path ):
    part = tmp_path / "at.part"
    part.mkdir()
    ( part / "junk" ).write_text( "left by a stopped export", encoding="utf-8" )
    out = source_at.export( repo, head( repo ), tmp_path / "at" )
    assert not ( out / "junk" ).exists() and not part.exists()
    with pytest.raises( er.NeedsetError ) as e: source_at.export( repo, "0" * 40, tmp_path / "other" )
    assert e.value.code == er.SOURCE_EXPORT_FAILED and not ( tmp_path / "other" ).exists()
    bare = tmp_path / "bare"
    bare.mkdir()
    ( bare / "readme" ).write_text( "x", encoding="utf-8" )
    git( bare, "init", "-q" )
    git( bare, "-c", "user.name=t", "-c", "user.email=t@t", "add", "." )
    git( bare, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "no src" )
    with pytest.raises( er.NeedsetError ) as e: source_at.export( bare, head( bare ), tmp_path / "nosrc" )
    assert e.value.code == er.SOURCE_EXPORT_FAILED and not ( tmp_path / "nosrc" ).exists()


def test_git_failing_after_a_readable_archive_still_refuses_and_leaves_no_folder( repo, tmp_path, monkeypatch ):
    buf = io.BytesIO()
    with tarfile.open( fileobj=buf, mode="w" ) as tar: pass

    class Fake:
        stdout = io.BytesIO( buf.getvalue() )
        stderr = io.BytesIO( b"fatal: boom" )
        def wait( self ): return 128

    real = subprocess.Popen
    monkeypatch.setattr( source_at.subprocess, "Popen", lambda argv, **k: Fake() if "archive" in argv else real( argv, **k ) )
    with pytest.raises( er.NeedsetError ) as e: source_at.export( repo, head( repo ), tmp_path / "at" )
    assert e.value.code == er.SOURCE_EXPORT_FAILED and "boom" in e.value.detail and not ( tmp_path / "at" ).exists()


def test_the_tracked_list_is_the_commits_files_under_src_not_the_working_trees( repo ):
    sha = head( repo )
    ( repo / "src" / "cosa" / "m.py" ).unlink()
    ( repo / "src" / "cosa" / "untracked.py" ).write_text( "Z = 3\n", encoding="utf-8" )
    assert source_at.tracked_at( repo, sha ) == { "src/cosa/m.py", "src/lupin_mcp/keep.py" }
    with pytest.raises( er.NeedsetError ) as e: source_at.tracked_at( repo, "nope" )
    assert e.value.code == er.SOURCE_EXPORT_FAILED


def test_a_strip_over_the_export_reads_the_commit_while_the_same_strip_over_the_moved_tree_reads_the_newer_file( repo, tmp_path ):
    rec = { "id": "cosa.m.f", "name": "f", "file": "src/cosa/m.py", "lang": "py", "line": 1 }
    ( repo / "src" / "cosa" / "m.py" ).write_text( AFTER, encoding="utf-8" )
    out = source_at.export( repo, head( repo ), tmp_path / "at" )
    assert "return x + 1" in strip.bodies_for( [ rec ], out )[ "cosa.m.f" ]
    assert "return x + 2" in strip.bodies_for( [ rec ], repo )[ "cosa.m.f" ]
    assert "x + 1" in strip.python_text( rec, out ) and strip.strip_member( rec, out )[ "kind" ]
