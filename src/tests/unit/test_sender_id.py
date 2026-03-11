"""
Unit tests for sender_id utilities and is_known_project registry.

Tests detect_project(), build_sender_id(), and the KNOWN_PROJECTS registry
used by the MCP server for strict project detection.
"""

import pytest
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

    def test_unknown_is_not_known( self ):
        assert is_known_project( "unknown" ) is False

    def test_newrepo_is_not_known( self ):
        assert is_known_project( "newrepo" ) is False

    def test_empty_string_is_not_known( self ):
        assert is_known_project( "" ) is False

    def test_known_projects_dict_has_correct_mappings( self ):
        assert KNOWN_PROJECTS[ "/lupin" ] == "lupin"
        assert KNOWN_PROJECTS[ "/cosa" ] == "cosa"
        assert KNOWN_PROJECTS[ "/planning-is-prompting" ] == "plan"

    def test_known_projects_dict_length( self ):
        """Ensure no accidental additions without test coverage."""
        assert len( KNOWN_PROJECTS ) == 3


class TestDetectProject:
    """Test suite for detect_project() function."""

    def test_returns_string( self ):
        project = detect_project()
        assert isinstance( project, str )
        assert len( project ) > 0

    @patch( "os.getcwd", return_value="/mnt/data/projects/lupin/src/cosa" )
    def test_lupin_with_nested_cosa( self, mock_cwd ):
        """CoSA nested inside lupin should detect as lupin."""
        assert detect_project() == "lupin"

    @patch( "os.getcwd", return_value="/home/user/projects/cosa" )
    def test_standalone_cosa( self, mock_cwd ):
        assert detect_project() == "cosa"

    @patch( "os.getcwd", return_value="/home/user/projects/planning-is-prompting" )
    def test_planning_is_prompting( self, mock_cwd ):
        assert detect_project() == "plan"

    @patch( "os.getcwd", return_value="/home/user/projects/my-new-repo" )
    def test_unknown_falls_back_to_basename( self, mock_cwd ):
        assert detect_project() == "my-new-repo"


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
