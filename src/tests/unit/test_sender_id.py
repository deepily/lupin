"""
Unit tests for sender_id utilities and is_known_project registry.

Tests detect_project(), build_sender_id(), and the KNOWN_PROJECTS registry
used by the MCP server for strict project detection.

detect_project() uses git-repo-boundary walk-up: from cwd, walks up until
a directory containing .git is found; its basename (lowercased, with legacy
aliases applied) is the project name. Tests that exercise this behavior use
the pytest `tmp_path` fixture to build synthetic repo trees with real .git
markers and mock os.getcwd to point inside them.
"""

import subprocess

from pathlib import Path
from unittest.mock import patch

import pytest

from cosa.agents.utils.sender_id import (
    detect_project, build_sender_id, _worktree_owner_basename, canonicalize_project_name
)
from cosa.utils.notification_utils import is_known_project, KNOWN_PROJECTS


class TestCanonicalizeProjectName:
    """
    The bare name-in -> name-out alias step shared by the task-store write/read
    seams (bug c6751cf8). Same `_PROJECT_ALIASES` table detect_project() uses.
    """

    def test_known_alias_maps_to_short_name( self ):
        assert canonicalize_project_name( "planning-is-prompting" ) == "plan"

    def test_already_canonical_short_name_unchanged( self ):
        # "plan" is the alias VALUE, not a key -> passes through untouched.
        assert canonicalize_project_name( "plan" ) == "plan"

    def test_non_aliased_repo_unchanged( self ):
        assert canonicalize_project_name( "lupin" ) == "lupin"

    def test_none_returns_none( self ):
        # No-op for optional query filters (project=None means "all projects").
        assert canonicalize_project_name( None ) is None


class TestIsKnownProject:
    """Test suite for is_known_project() function."""

    def test_lupin_is_known( self ):
        assert is_known_project( "lupin" ) is True

    def test_cosa_is_known( self ):
        assert is_known_project( "cosa" ) is True

    def test_plan_is_known( self ):
        assert is_known_project( "plan" ) is True

    def test_lupin_mobile_is_known( self ):
        assert is_known_project( "lupin-mobile" ) is True

    def test_lupin_plugin_firefox_is_known( self ):
        assert is_known_project( "lupin-plugin-firefox" ) is True

    def test_unknown_is_not_known( self ):
        assert is_known_project( "unknown" ) is False

    def test_newrepo_is_not_known( self ):
        assert is_known_project( "newrepo" ) is False

    def test_empty_string_is_not_known( self ):
        assert is_known_project( "" ) is False

    def test_known_projects_dict_has_correct_mappings( self ):
        assert KNOWN_PROJECTS[ "/lupin" ]                == "lupin"
        assert KNOWN_PROJECTS[ "/cosa" ]                 == "cosa"
        assert KNOWN_PROJECTS[ "/planning-is-prompting" ] == "plan"
        assert KNOWN_PROJECTS[ "/lupin-mobile" ]         == "lupin-mobile"
        assert KNOWN_PROJECTS[ "/lupin-plugin-firefox" ] == "lupin-plugin-firefox"

    def test_known_projects_dict_length( self ):
        """Ensure no accidental additions without test coverage."""
        assert len( KNOWN_PROJECTS ) == 5


class TestDetectProject:
    """Test suite for detect_project() function."""

    def test_returns_string( self ):
        project = detect_project()
        assert isinstance( project, str )
        assert len( project ) > 0

    def test_lupin_with_nested_cosa( self, tmp_path ):
        """CoSA nested inside Lupin returns 'cosa' — walk-up finds inner .git first."""
        lupin = tmp_path / "lupin"
        cosa  = lupin / "src" / "cosa"
        cosa.mkdir( parents=True )
        ( lupin / ".git" ).mkdir()
        ( cosa / ".git" ).mkdir()
        with patch( "os.getcwd", return_value=str( cosa ) ):
            assert detect_project() == "cosa"

    def test_lupin_with_nested_mobile( self, tmp_path ):
        """Mobile submodule returns 'lupin-mobile', not 'lupin'."""
        lupin  = tmp_path / "lupin"
        mobile = lupin / "src" / "lupin-mobile"
        mobile.mkdir( parents=True )
        ( lupin / ".git" ).mkdir()
        ( mobile / ".git" ).mkdir()
        with patch( "os.getcwd", return_value=str( mobile ) ):
            assert detect_project() == "lupin-mobile"

    def test_lupin_with_nested_firefox_plugin( self, tmp_path ):
        """Firefox-plugin submodule returns 'lupin-plugin-firefox', not 'lupin'."""
        lupin   = tmp_path / "lupin"
        firefox = lupin / "src" / "lupin-plugin-firefox"
        firefox.mkdir( parents=True )
        ( lupin / ".git" ).mkdir()
        ( firefox / ".git" ).mkdir()
        with patch( "os.getcwd", return_value=str( firefox ) ):
            assert detect_project() == "lupin-plugin-firefox"

    def test_lupin_root( self, tmp_path ):
        """Cwd at Lupin root returns 'lupin'."""
        lupin = tmp_path / "lupin"
        lupin.mkdir()
        ( lupin / ".git" ).mkdir()
        with patch( "os.getcwd", return_value=str( lupin ) ):
            assert detect_project() == "lupin"

    def test_standalone_cosa( self, tmp_path ):
        """Standalone CoSA (not nested inside lupin) returns 'cosa'."""
        cosa = tmp_path / "cosa"
        cosa.mkdir()
        ( cosa / ".git" ).mkdir()
        with patch( "os.getcwd", return_value=str( cosa ) ):
            assert detect_project() == "cosa"

    def test_git_as_file_gitlink( self, tmp_path ):
        """Submodule gitlinks store .git as a FILE, not a dir — detection must handle this."""
        lupin = tmp_path / "lupin"
        cosa  = lupin / "src" / "cosa"
        cosa.mkdir( parents=True )
        ( lupin / ".git" ).mkdir()
        ( cosa / ".git" ).write_text( "gitdir: ../../.git/modules/cosa\n" )
        with patch( "os.getcwd", return_value=str( cosa ) ):
            assert detect_project() == "cosa"

    def test_planning_is_prompting_alias( self, tmp_path ):
        """'planning-is-prompting' repo name aliases to legacy short name 'plan'."""
        pip = tmp_path / "planning-is-prompting"
        pip.mkdir()
        ( pip / ".git" ).mkdir()
        with patch( "os.getcwd", return_value=str( pip ) ):
            assert detect_project() == "plan"

    def test_unknown_falls_back_to_basename( self, tmp_path ):
        """Dir with no .git ancestor falls back to cwd basename (lowercased)."""
        my_repo = tmp_path / "my-new-repo"
        my_repo.mkdir()
        with patch( "os.getcwd", return_value=str( my_repo ) ):
            assert detect_project() == "my-new-repo"

    def test_basename_is_lowercased( self, tmp_path ):
        """Project name is always lowercased regardless of filesystem casing."""
        mixed_case = tmp_path / "MyProject"
        mixed_case.mkdir()
        ( mixed_case / ".git" ).mkdir()
        with patch( "os.getcwd", return_value=str( mixed_case ) ):
            assert detect_project() == "myproject"


class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess used in branch tests."""

    def __init__( self, returncode, stdout ):
        self.returncode = returncode
        self.stdout     = stdout


class TestWorktreeOwnerBasename:
    """Branch-coverage suite for the _worktree_owner_basename() helper."""

    def test_oserror_returns_none( self, monkeypatch ):
        """git binary missing (OSError) → None (fail toward existing behavior)."""
        def _raise( *a, **k ):
            raise OSError( "git not found" )
        monkeypatch.setattr( "cosa.agents.utils.sender_id.subprocess.run", _raise )
        assert _worktree_owner_basename( Path( "/tmp/whatever" ) ) is None

    def test_subprocess_error_returns_none( self, monkeypatch ):
        """git timeout (SubprocessError subclass) → None."""
        def _raise( *a, **k ):
            raise subprocess.TimeoutExpired( cmd="git", timeout=5 )
        monkeypatch.setattr( "cosa.agents.utils.sender_id.subprocess.run", _raise )
        assert _worktree_owner_basename( Path( "/tmp/whatever" ) ) is None

    def test_nonzero_returncode_returns_none( self, monkeypatch ):
        """git rev-parse fatal (rc != 0) → None."""
        monkeypatch.setattr(
            "cosa.agents.utils.sender_id.subprocess.run",
            lambda *a, **k: _FakeCompleted( 128, "" )
        )
        assert _worktree_owner_basename( Path( "/tmp/whatever" ) ) is None

    def test_empty_stdout_returns_none( self, monkeypatch ):
        """rc 0 but empty stdout → None."""
        monkeypatch.setattr(
            "cosa.agents.utils.sender_id.subprocess.run",
            lambda *a, **k: _FakeCompleted( 0, "   \n" )
        )
        assert _worktree_owner_basename( Path( "/tmp/whatever" ) ) is None

    def test_submodule_common_dir_returns_none( self, monkeypatch ):
        """Submodule common-dir (.git/modules/<name>) basename != '.git' → None."""
        monkeypatch.setattr(
            "cosa.agents.utils.sender_id.subprocess.run",
            lambda *a, **k: _FakeCompleted( 0, "/home/x/lupin/.git/modules/cosa\n" )
        )
        assert _worktree_owner_basename( Path( "/home/x/lupin/src/cosa" ) ) is None

    def test_worktree_absolute_common_dir( self, monkeypatch ):
        """Worktree absolute common-dir → MAIN repo basename (lowercased)."""
        monkeypatch.setattr(
            "cosa.agents.utils.sender_id.subprocess.run",
            lambda *a, **k: _FakeCompleted( 0, "/home/x/Lupin/.git\n" )
        )
        assert _worktree_owner_basename( Path( "/tmp/wt-foo" ) ) == "lupin"

    def test_worktree_relative_common_dir_is_resolved( self, monkeypatch, tmp_path ):
        """Relative common-dir is resolved against candidate before basename check."""
        main = tmp_path / "lupin"
        ( main / ".git" ).mkdir( parents=True )
        candidate = tmp_path / "lupin" / "wt"
        candidate.mkdir()
        # git reports a RELATIVE common dir ("../.git") from the worktree candidate
        monkeypatch.setattr(
            "cosa.agents.utils.sender_id.subprocess.run",
            lambda *a, **k: _FakeCompleted( 0, "../.git\n" )
        )
        assert _worktree_owner_basename( candidate ) == "lupin"


class TestDetectProjectWorktree:
    """detect_project() worktree-aware resolution via REAL git worktrees."""

    @staticmethod
    def _git( *args, cwd ):
        subprocess.run(
            [ "git", *args ], cwd=str( cwd ),
            check=True, capture_output=True, text=True
        )

    def _make_main_repo( self, root, name ):
        main = root / name
        main.mkdir()
        self._git( "init", "-q", cwd=main )
        self._git( "config", "user.email", "t@test.local", cwd=main )
        self._git( "config", "user.name", "t", cwd=main )
        self._git( "commit", "-q", "--allow-empty", "-m", "init", cwd=main )
        return main

    def test_worktree_resolves_to_main_repo( self, tmp_path ):
        """A worktree of 'lupin' detects as 'lupin', NOT the worktree dir name."""
        main = self._make_main_repo( tmp_path, "lupin" )
        link = tmp_path / "wt-delegation-signal"
        self._git( "worktree", "add", "-q", str( link ), cwd=main )
        with patch( "os.getcwd", return_value=str( link ) ):
            assert detect_project() == "lupin"

    def test_worktree_applies_alias( self, tmp_path ):
        """A worktree of 'planning-is-prompting' maps through the alias to 'plan'."""
        main = self._make_main_repo( tmp_path, "planning-is-prompting" )
        link = tmp_path / "wt-pip"
        self._git( "worktree", "add", "-q", str( link ), cwd=main )
        with patch( "os.getcwd", return_value=str( link ) ):
            assert detect_project() == "plan"

    def test_subdir_inside_worktree_still_resolves_main( self, tmp_path ):
        """cwd in a SUBDIR of a worktree still walks up + resolves to main repo."""
        main = self._make_main_repo( tmp_path, "lupin" )
        link = tmp_path / "wt-sub"
        self._git( "worktree", "add", "-q", str( link ), cwd=main )
        sub = link / "src" / "deep"
        sub.mkdir( parents=True )
        with patch( "os.getcwd", return_value=str( sub ) ):
            assert detect_project() == "lupin"

    def test_normal_repo_unaffected_no_subprocess( self, tmp_path, monkeypatch ):
        """A normal repo (.git is a dir) never invokes git — fast path preserved."""
        repo = tmp_path / "lupin"
        repo.mkdir()
        ( repo / ".git" ).mkdir()
        def _boom( *a, **k ):
            raise AssertionError( "subprocess.run must NOT fire for a normal .git dir" )
        monkeypatch.setattr( "cosa.agents.utils.sender_id.subprocess.run", _boom )
        with patch( "os.getcwd", return_value=str( repo ) ):
            assert detect_project() == "lupin"


class TestBuildSenderId:
    """Test suite for build_sender_id() function."""

    def test_basic_sender_id( self ):
        sid = build_sender_id( "deep.research", project="lupin" )
        assert sid == "deep.research@lupin.deepily.ai"

    def test_with_suffix( self ):
        sid = build_sender_id( "claude.code", project="lupin", suffix="a1b2c3d4" )
        assert sid == "claude.code@lupin.deepily.ai#a1b2c3d4"

    def test_no_suffix_no_hash( self ):
        sid = build_sender_id( "claude.code", project="lupin" )
        assert "#" not in sid


# ---------------------------------------------------------------------------
# Dangling-gitlink fallback (2026-06-11 incident regression)
#
# The 2026-06-11 fleet incident deleted the main repo's entire
# `.git/worktrees/` admin directory while worktree dirs survived. Live git
# then fails inside each worktree, and pre-fix detect_project() degraded to
# the WORKTREE dir basename ("sam-debt-sweep") — spamming urgent
# no-credentials notifications. The static gitlink parse must recover the
# MAIN repo identity without git.
# ---------------------------------------------------------------------------

import shutil

from cosa.agents.utils.sender_id import _dangling_gitlink_owner_basename


class TestDanglingGitlinkOwnerBasename:
    """Branch-coverage suite for the _dangling_gitlink_owner_basename() helper."""

    def test_absolute_worktree_gitdir_resolves_main_basename( self, tmp_path ):
        gitlink = tmp_path / ".git"
        gitlink.write_text( "gitdir: /home/x/Lupin/.git/worktrees/sam-debt-sweep\n" )
        assert _dangling_gitlink_owner_basename( gitlink ) == "lupin"

    def test_relative_worktree_gitdir_is_resolved( self, tmp_path ):
        wt = tmp_path / "wt-foo"
        wt.mkdir()
        gitlink = wt / ".git"
        gitlink.write_text( "gitdir: ../lupin/.git/worktrees/wt-foo\n" )
        assert _dangling_gitlink_owner_basename( gitlink ) == "lupin"

    def test_submodule_modules_gitdir_returns_none( self, tmp_path ):
        gitlink = tmp_path / ".git"
        gitlink.write_text( "gitdir: /home/x/lupin/.git/modules/cosa\n" )
        assert _dangling_gitlink_owner_basename( gitlink ) is None

    def test_unreadable_gitlink_returns_none( self, tmp_path ):
        assert _dangling_gitlink_owner_basename( tmp_path / "does-not-exist" ) is None

    def test_malformed_content_returns_none( self, tmp_path ):
        gitlink = tmp_path / ".git"
        gitlink.write_text( "this is not a gitlink\n" )
        assert _dangling_gitlink_owner_basename( gitlink ) is None

    def test_gitdir_without_worktrees_segment_returns_none( self, tmp_path ):
        gitlink = tmp_path / ".git"
        gitlink.write_text( "gitdir: /somewhere/else/entirely\n" )
        assert _dangling_gitlink_owner_basename( gitlink ) is None


def _make_main_repo_with_worktree( tmp_path ):
    """Real-git fixture: main repo `lupin` with one linked worktree."""
    main = tmp_path / "lupin"
    main.mkdir()
    subprocess.run( [ "git", "init", "-q" ], cwd=main, check=True )
    ( main / "README.md" ).write_text( "x\n" )
    subprocess.run( [ "git", "add", "." ], cwd=main, check=True )
    subprocess.run(
        [ "git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init" ],
        cwd=main, check=True
    )
    worktree = tmp_path / "wt-sam-debt-sweep"
    subprocess.run( [ "git", "worktree", "add", "-q", str( worktree ) ], cwd=main, check=True )
    return main, worktree


class TestDanglingWorktreeRegression:
    """End-to-end detect_project() against REAL git worktrees."""

    def test_healthy_worktree_resolves_to_main_repo( self, tmp_path ):
        """Sanity: the live-git path (06-10 fix) answers while the admin dir exists."""
        _main, worktree = _make_main_repo_with_worktree( tmp_path )
        with patch( "os.getcwd", return_value=str( worktree ) ):
            assert detect_project() == "lupin"

    def test_broken_worktree_resolves_to_main_repo_not_basename( self, tmp_path ):
        """THE 2026-06-11 incident: admin dir deleted under a live worktree —
        detection must still say 'lupin', NEVER 'wt-sam-debt-sweep'."""
        main, worktree = _make_main_repo_with_worktree( tmp_path )
        shutil.rmtree( main / ".git" / "worktrees" )
        with patch( "os.getcwd", return_value=str( worktree ) ):
            assert detect_project() == "lupin"


def test_build_sender_id_auto_detects_project( monkeypatch ):
    """project=None triggers detect_project() auto-detection."""
    monkeypatch.setattr( "cosa.agents.utils.sender_id.detect_project", lambda: "lupin" )
    assert build_sender_id( "deep.research" ) == "deep.research@lupin.deepily.ai"
