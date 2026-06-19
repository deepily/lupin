"""
Unit tests for cosa.repo.directory_analyzer.exceptions.

Tests the directory-analyzer exception hierarchy: DirectoryAnalyzerError (base)
plus ScannerError, ConfigurationError, and FileReadError. Coverage exercises
real behaviour: context-dict construction, None-field omission, original_error
str-coercion + 200-char truncation, value str-coercion + 100-char truncation,
attribute preservation, __str__ rendering (with/without context), and the
inheritance contract.

Part of the CoSA 100% coverage campaign (repo module group).
"""
import pytest

from cosa.repo.directory_analyzer.exceptions import (
    DirectoryAnalyzerError,
    ScannerError,
    ConfigurationError,
    FileReadError,
)


class TestDirectoryAnalyzerError:
    """The base exception: message + optional context, custom __str__."""

    def test_init_defaults_context_to_empty_dict( self ):
        """Ensures: message stored verbatim; omitted context becomes {} not None."""
        err = DirectoryAnalyzerError( "broke" )
        assert err.message == "broke"
        assert err.context == {}

    def test_init_preserves_supplied_context( self ):
        """Ensures: a supplied context dict is stored as-is."""
        err = DirectoryAnalyzerError( "boom", context={ "where": "scan" } )
        assert err.context == { "where": "scan" }

    def test_str_without_context_is_bare_message( self ):
        """Ensures: __str__ returns just the message when context is empty."""
        assert str( DirectoryAnalyzerError( "plain" ) ) == "plain"

    def test_str_with_context_appends_pairs( self ):
        """Ensures: __str__ appends a '(Context: k=v)' suffix when context present."""
        rendered = str( DirectoryAnalyzerError( "bad", context={ "a": 1, "b": 2 } ) )
        assert rendered.startswith( "bad (Context: " )
        assert "a=1" in rendered and "b=2" in rendered

    def test_is_raisable( self ):
        """Ensures: the base type is a real, raisable Exception."""
        with pytest.raises( DirectoryAnalyzerError ):
            raise DirectoryAnalyzerError( "raise me" )


class TestScannerError:
    """Filesystem-traversal failures carry path + original_error."""

    def test_full_fields_stored_and_original_error_truncated( self ):
        """
        Ensures:
            - path/original_error stored verbatim on attributes
            - context original_error is str()-coerced and truncated to 200 chars
            - the raw original_error attribute remains the live exception object
        """
        big = RuntimeError( "E" * 250 )
        err = ScannerError( "cannot scan", path="/protected", original_error=big )
        assert err.path == "/protected"
        assert err.original_error is big
        assert err.context[ "path" ] == "/protected"
        assert len( err.context[ "original_error" ] ) == 200

    def test_none_fields_omitted_from_context( self ):
        """Ensures: omitting path + original_error yields an empty context."""
        err = ScannerError( "cannot scan" )
        assert err.path is None
        assert err.original_error is None
        assert err.context == {}
        assert str( err ) == "cannot scan"

    def test_subclass_of_base( self ):
        """Ensures: catchable as DirectoryAnalyzerError."""
        assert issubclass( ScannerError, DirectoryAnalyzerError )


class TestConfigurationError:
    """Config failures carry config_path/field/value."""

    def test_full_fields_stored_and_value_stringified_truncated( self ):
        """
        Ensures:
            - config_path/field/value stored verbatim on attributes
            - context value is str()-coerced and truncated to 100 chars
        """
        big_value = "v" * 150
        err = ConfigurationError(
            message="bad cfg", config_path="/c.yaml",
            field="directory.exclude_dirs", value=big_value,
        )
        assert err.config_path == "/c.yaml"
        assert err.field == "directory.exclude_dirs"
        assert err.value == big_value
        assert len( err.context[ "value" ] ) == 100

    def test_non_string_value_stringified_in_context( self ):
        """Ensures: a non-string value is rendered via str() in context."""
        err = ConfigurationError( "bad", value=123 )
        assert err.context[ "value" ] == "123"

    def test_none_value_omitted( self ):
        """Ensures: value=None is dropped (distinct from value=0/'')."""
        err = ConfigurationError( "missing", field="git" )
        assert err.context == { "field": "git" }
        assert "value" not in err.context

    def test_subclass_of_base( self ):
        """Ensures: catchable as DirectoryAnalyzerError."""
        assert issubclass( ConfigurationError, DirectoryAnalyzerError )


class TestFileReadError:
    """File-read failures carry file_path/encoding/original_error."""

    def test_full_fields_stored_and_original_error_truncated( self ):
        """
        Ensures:
            - file_path/encoding/original_error stored verbatim on attributes
            - context original_error is str()-coerced and truncated to 200 chars
        """
        big = UnicodeDecodeError( "utf-8", b"", 0, 1, "boom" + "x" * 300 )
        err = FileReadError(
            message="cannot decode", file_path="/b.dat",
            encoding="utf-8", original_error=big,
        )
        assert err.file_path == "/b.dat"
        assert err.encoding == "utf-8"
        assert err.original_error is big
        assert err.context[ "file_path" ] == "/b.dat"
        assert err.context[ "encoding" ] == "utf-8"
        assert len( err.context[ "original_error" ] ) == 200

    def test_none_fields_omitted( self ):
        """Ensures: an all-optional-None FileReadError has empty context."""
        err = FileReadError( "cannot read" )
        assert err.file_path is None
        assert err.encoding is None
        assert err.original_error is None
        assert err.context == {}

    def test_subclass_of_base( self ):
        """Ensures: catchable as DirectoryAnalyzerError."""
        assert issubclass( FileReadError, DirectoryAnalyzerError )


class TestHierarchy:
    """All package exceptions share the DirectoryAnalyzerError base."""

    @pytest.mark.parametrize( "exc_cls", [
        ScannerError,
        ConfigurationError,
        FileReadError,
    ] )
    def test_all_catchable_as_base( self, exc_cls ):
        """Ensures: every package exception can be caught via the base type."""
        with pytest.raises( DirectoryAnalyzerError ):
            raise exc_cls( "boom" )
