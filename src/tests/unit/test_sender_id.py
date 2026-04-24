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

from unittest.mock import patch

from cosa.agents.utils.sender_id import detect_project, build_sender_id
from cosa.utils.notification_utils import is_known_project, KNOWN_PROJECTS


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
