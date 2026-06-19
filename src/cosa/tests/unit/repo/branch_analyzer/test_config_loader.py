"""
Unit tests for cosa.repo.branch_analyzer.config_loader.

Tests ConfigLoader: locates the shipped default_config.yaml, optionally
deep-merges a user YAML override, validates structure, and exposes a
dot-path get() accessor. Coverage drives the real load/merge/validate
pipeline plus every validation sub-branch (white-box calls into the
section validators for branches the always-valid default can't reach).

Part of the CoSA 100% coverage campaign (repo module group).
"""
from pathlib import Path
from unittest import mock

import yaml
import pytest

from cosa.repo.branch_analyzer.config_loader import ConfigLoader
from cosa.repo.branch_analyzer.exceptions import ConfigurationError


def _write_yaml( tmp_path, name, data ):
    """
    Write a YAML doc to tmp_path and return its string path.

    Requires:
        - tmp_path is a pytest tmp_path fixture dir
        - data is a YAML-serialisable object (or pre-formed string)

    Ensures:
        - returns the absolute path string to the written file
    """
    p = tmp_path / name
    if isinstance( data, str ):
        p.write_text( data, encoding="utf-8" )
    else:
        p.write_text( yaml.safe_dump( data ), encoding="utf-8" )
    return str( p )


class TestInit:
    """Construction locates the shipped default config."""

    def test_default_config_located( self ):
        """Ensures: a no-arg loader finds the shipped default_config.yaml."""
        loader = ConfigLoader()
        assert loader.default_path.name == "default_config.yaml"
        assert loader.default_path.exists()

    def test_missing_default_config_raises( self ):
        """
        Ensures:
            - if the shipped default cannot be found, __init__ raises
              ConfigurationError (defensive existence check)
        """
        with mock.patch.object( Path, "exists", return_value=False ):
            with pytest.raises( ConfigurationError ):
                ConfigLoader()


class TestLoadDefault:
    """Loading with no user config returns the validated default."""

    def test_load_returns_all_required_sections( self ):
        """
        Ensures:
            - the default config contains every required top-level section
            - file_types.extensions is a dict
        """
        config = ConfigLoader().load()
        for section in [ "git", "file_types", "analysis", "output", "formatting" ]:
            assert section in config
        assert isinstance( config[ "file_types" ][ "extensions" ], dict )

    def test_default_git_algorithm_is_valid( self ):
        """Ensures: the default diff_algorithm is one of the accepted values."""
        config = ConfigLoader().load()
        assert config[ "git" ][ "diff_algorithm" ] in (
            "myers", "minimal", "patience", "histogram"
        )


class TestDebugLogging:
    """debug=True exercises the init/load logging branches."""

    def test_debug_init_and_load_with_user_config_logs( self, tmp_path, capsys ):
        """
        Ensures:
            - debug=True at init logs both default and user config paths
            - load() logs default-loaded, user-loaded, and validated lines
        """
        user = _write_yaml( tmp_path, "user.yaml", { "git": { "default_base_branch": "develop" } } )
        loader = ConfigLoader( config_path=user, debug=True )
        loader.load()
        out = capsys.readouterr().out
        assert "Default config" in out
        assert "User config" in out
        assert "validated successfully" in out

    def test_debug_init_without_user_config_omits_user_line( self, capsys ):
        """
        Ensures:
            - debug=True with NO user config logs the default path but NOT a
              "User config" line (the config_path-falsy exit branch at init)
        """
        ConfigLoader( debug=True )
        out = capsys.readouterr().out
        assert "Default config" in out
        assert "User config" not in out


class TestLoadWithUserOverride:
    """A user YAML deep-merges over the default."""

    def test_user_value_overrides_default_scalar( self, tmp_path ):
        """
        Ensures:
            - a user override replaces the default scalar (deep merge)
        """
        user = _write_yaml( tmp_path, "user.yaml", { "git": { "default_base_branch": "develop" } } )
        config = ConfigLoader( config_path=user ).load()
        assert config[ "git" ][ "default_base_branch" ] == "develop"
        # untouched default sibling keys survive the merge
        assert "diff_algorithm" in config[ "git" ]

    def test_user_adds_new_extension_mapping( self, tmp_path ):
        """Ensures: a user can add a new extension mapping via deep merge."""
        user = _write_yaml( tmp_path, "user.yaml", { "file_types": { "extensions": { ".rs": "rust" } } } )
        config = ConfigLoader( config_path=user ).load()
        assert config[ "file_types" ][ "extensions" ][ ".rs" ] == "rust"

    def test_empty_user_file_is_treated_as_empty_dict( self, tmp_path ):
        """
        Ensures:
            - an empty user YAML (parses to None) becomes {} and merges cleanly,
              leaving the default intact
        """
        user = _write_yaml( tmp_path, "empty.yaml", "" )
        config = ConfigLoader( config_path=user ).load()
        assert "git" in config


class TestLoadYamlErrors:
    """_load_yaml_file rejects missing/invalid/non-dict YAML."""

    def test_missing_user_file_raises( self, tmp_path ):
        """Ensures: a nonexistent config_path raises ConfigurationError."""
        missing = str( tmp_path / "nope.yaml" )
        with pytest.raises( ConfigurationError ):
            ConfigLoader( config_path=missing ).load()

    def test_invalid_yaml_raises( self, tmp_path ):
        """Ensures: malformed YAML syntax raises ConfigurationError."""
        bad = _write_yaml( tmp_path, "bad.yaml", "key: : : nope\n  - broken" )
        with pytest.raises( ConfigurationError ):
            ConfigLoader( config_path=bad ).load()

    def test_non_dict_yaml_raises( self, tmp_path ):
        """Ensures: a top-level YAML list (not a dict) raises ConfigurationError."""
        listy = _write_yaml( tmp_path, "list.yaml", [ "a", "b" ] )
        with pytest.raises( ConfigurationError ):
            ConfigLoader( config_path=listy ).load()


class TestGet:
    """get() does dot-path traversal with a default and a not-loaded guard."""

    def test_get_before_load_raises_value_error( self ):
        """Ensures: calling get() before load() raises ValueError."""
        with pytest.raises( ValueError ):
            ConfigLoader().get( "git.default_base_branch" )

    def test_get_returns_nested_value( self ):
        """Ensures: a valid dot-path returns the nested value."""
        loader = ConfigLoader()
        loader.load()
        assert loader.get( "git.diff_algorithm" ) in (
            "myers", "minimal", "patience", "histogram"
        )

    def test_get_missing_path_returns_default( self ):
        """Ensures: an unknown dot-path returns the supplied default."""
        loader = ConfigLoader()
        loader.load()
        assert loader.get( "git.nonexistent.key", default="fallback" ) == "fallback"


class TestValidationBranches:
    """White-box validation: each section validator's failure branch.

    The shipped default is always valid and merge can only add keys, so these
    branches are unreachable through load() alone. We exercise the validators
    directly with crafted configs — each raising ConfigurationError on the
    specific malformed field is real behaviour worth pinning.
    """

    @pytest.fixture
    def loader( self ):
        """A loaded ConfigLoader (validators are instance methods)."""
        ld = ConfigLoader()
        ld.load()
        return ld

    def test_missing_required_section_raises( self, loader ):
        """Ensures: a config missing a required top-level section raises."""
        with pytest.raises( ConfigurationError ) as exc:
            loader._validate_config( { "git": {} } )  # missing file_types, etc.
        assert exc.value.field in (
            "file_types", "analysis", "output", "formatting", "git"
        )

    def test_missing_git_field_raises( self, loader ):
        """Ensures: a git section missing a required field raises."""
        with pytest.raises( ConfigurationError ):
            loader._validate_git_section( { "default_base_branch": "main" } )

    def test_invalid_diff_algorithm_raises( self, loader ):
        """Ensures: an unsupported diff_algorithm raises."""
        with pytest.raises( ConfigurationError ):
            loader._validate_git_section( {
                "default_base_branch": "main",
                "default_head_branch": "HEAD",
                "diff_algorithm"     : "bogus",
            } )

    def test_file_types_missing_extensions_raises( self, loader ):
        """Ensures: file_types lacking 'extensions' raises."""
        with pytest.raises( ConfigurationError ):
            loader._validate_file_types_section( {} )

    def test_file_types_non_dict_extensions_raises( self, loader ):
        """Ensures: file_types.extensions that is not a dict raises."""
        with pytest.raises( ConfigurationError ):
            loader._validate_file_types_section( { "extensions": [ ".py" ] } )

    def test_analysis_non_bool_field_raises( self, loader ):
        """Ensures: a non-bool analysis flag raises."""
        with pytest.raises( ConfigurationError ):
            loader._validate_analysis_section( { "track_docstrings": "yes" } )

    def test_analysis_valid_bool_passes( self, loader ):
        """Ensures: a valid bool analysis flag does not raise (happy branch)."""
        loader._validate_analysis_section( { "track_docstrings": True } )

    def test_output_invalid_format_raises( self, loader ):
        """Ensures: an unsupported output.default_format raises."""
        with pytest.raises( ConfigurationError ):
            loader._validate_output_section( { "default_format": "pdf" } )

    def test_output_valid_format_passes( self, loader ):
        """Ensures: a valid output.default_format does not raise."""
        loader._validate_output_section( { "default_format": "json" } )

    def test_output_without_default_format_passes( self, loader ):
        """Ensures: an output section lacking default_format is a no-op (exit branch)."""
        loader._validate_output_section( {} )

    def test_formatting_without_column_widths_passes( self, loader ):
        """Ensures: a formatting section lacking column_widths is a no-op (exit branch)."""
        loader._validate_formatting_section( {} )

    def test_formatting_non_dict_column_widths_raises( self, loader ):
        """Ensures: formatting.column_widths that is not a dict raises."""
        with pytest.raises( ConfigurationError ):
            loader._validate_formatting_section( { "column_widths": 80 } )

    def test_formatting_valid_column_widths_passes( self, loader ):
        """Ensures: a dict column_widths does not raise."""
        loader._validate_formatting_section( { "column_widths": { "file_type": 15 } } )
