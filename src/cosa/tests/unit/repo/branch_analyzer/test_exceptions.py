"""
Unit tests for cosa.repo.branch_analyzer.exceptions.

Tests the custom exception hierarchy used throughout the branch analyzer:
BranchAnalyzerError (base) plus GitCommandError, ConfigurationError,
ParserError, and ClassificationError. Coverage focuses on real behaviour:
context-dict construction, None-field omission, long-field truncation,
attribute preservation, __str__ rendering, and the inheritance contract.

Part of the CoSA 100% coverage campaign (repo module group).
"""
import pytest

from cosa.repo.branch_analyzer.exceptions import (
    BranchAnalyzerError,
    GitCommandError,
    ConfigurationError,
    ParserError,
    ClassificationError,
)


class TestBranchAnalyzerError:
    """The base exception: message + optional context, custom __str__."""

    def test_init_stores_message_and_defaults_context_to_empty_dict( self ):
        """
        Ensures:
            - message is stored verbatim
            - omitted context becomes an empty dict (not None)
        """
        err = BranchAnalyzerError( "something broke" )
        assert err.message == "something broke"
        assert err.context == {}

    def test_init_preserves_supplied_context( self ):
        """
        Ensures:
            - a supplied context dict is stored as-is
        """
        err = BranchAnalyzerError( "boom", context={ "stage": "init" } )
        assert err.context == { "stage": "init" }

    def test_str_without_context_returns_bare_message( self ):
        """
        Ensures:
            - __str__ returns just the message when context is empty
        """
        err = BranchAnalyzerError( "plain message" )
        assert str( err ) == "plain message"

    def test_str_with_context_appends_formatted_context( self ):
        """
        Ensures:
            - __str__ appends a "(Context: k=v)" suffix when context present
            - each key=value pair is rendered
        """
        err = BranchAnalyzerError( "bad", context={ "a": 1, "b": 2 } )
        rendered = str( err )
        assert rendered.startswith( "bad (Context: " )
        assert "a=1" in rendered
        assert "b=2" in rendered

    def test_is_an_exception( self ):
        """
        Ensures:
            - the base type is a real Exception subclass (can be raised/caught)
        """
        with pytest.raises( BranchAnalyzerError ):
            raise BranchAnalyzerError( "raise me" )


class TestGitCommandError:
    """git subprocess failures carry command/return_code/stderr/stdout."""

    def test_full_fields_are_stored_and_context_truncates_streams( self ):
        """
        Ensures:
            - command/return_code/stderr/stdout stored verbatim on attributes
            - context stderr/stdout are truncated to 200 chars
            - the raw attributes remain untruncated
        """
        long_err = "E" * 250
        long_out = "O" * 250
        err = GitCommandError(
            message     = "diff failed",
            command     = [ "git", "diff", "main...HEAD" ],
            return_code = 128,
            stderr      = long_err,
            stdout      = long_out,
        )
        # Raw attributes untouched
        assert err.command == [ "git", "diff", "main...HEAD" ]
        assert err.return_code == 128
        assert err.stderr == long_err
        assert err.stdout == long_out
        # Context truncates the noisy streams to 200 chars
        assert len( err.context[ "stderr" ] ) == 200
        assert len( err.context[ "stdout" ] ) == 200
        assert err.context[ "return_code" ] == 128

    def test_minimal_omits_none_fields_from_context( self ):
        """
        Ensures:
            - None-valued fields are dropped from the context dict
            - an all-None instance yields an empty context (bare __str__)
        """
        err = GitCommandError( "git missing" )
        assert err.context == {}
        assert "stderr" not in err.context
        assert str( err ) == "git missing"

    def test_zero_return_code_is_retained_not_dropped( self ):
        """
        Ensures:
            - return_code=0 survives the None-filter (0 is not None)
        """
        err = GitCommandError( "weird", return_code=0 )
        assert err.context[ "return_code" ] == 0

    def test_subclass_of_base( self ):
        """
        Ensures:
            - GitCommandError can be caught as BranchAnalyzerError
        """
        assert issubclass( GitCommandError, BranchAnalyzerError )


class TestConfigurationError:
    """config load/validate failures carry config_path/field/value."""

    def test_full_fields_stored_and_value_stringified_and_truncated( self ):
        """
        Ensures:
            - config_path/field/value stored verbatim on attributes
            - context value is str()-coerced and truncated to 100 chars
        """
        big_value = "v" * 150
        err = ConfigurationError(
            message     = "bad config",
            config_path = "/etc/cfg.yaml",
            field       = "git.diff_algorithm",
            value       = big_value,
        )
        assert err.config_path == "/etc/cfg.yaml"
        assert err.field == "git.diff_algorithm"
        assert err.value == big_value
        assert len( err.context[ "value" ] ) == 100

    def test_non_string_value_is_stringified_in_context( self ):
        """
        Ensures:
            - a non-string value is rendered via str() in the context
        """
        err = ConfigurationError( "bad", value=123 )
        assert err.context[ "value" ] == "123"

    def test_none_value_is_omitted_from_context( self ):
        """
        Ensures:
            - value=None is dropped from context (distinct from value=0/'')
        """
        err = ConfigurationError( "missing section", field="git" )
        assert err.context == { "field": "git" }
        assert "value" not in err.context

    def test_subclass_of_base( self ):
        """Ensures: ConfigurationError is a BranchAnalyzerError."""
        assert issubclass( ConfigurationError, BranchAnalyzerError )


class TestParserError:
    """diff-parsing failures carry line_number/line_content/parser_stage."""

    def test_full_fields_stored_and_line_content_truncated( self ):
        """
        Ensures:
            - line_number/line_content/parser_stage stored verbatim
            - context line_content truncated to 100 chars
            - integer line_number passes through to context
        """
        big_line = "x" * 150
        err = ParserError(
            message      = "malformed hunk",
            line_number  = 42,
            line_content = big_line,
            parser_stage = "hunk_header",
        )
        assert err.line_number == 42
        assert err.line_content == big_line
        assert err.parser_stage == "hunk_header"
        assert err.context[ "line_number" ] == 42
        assert len( err.context[ "line_content" ] ) == 100

    def test_minimal_omits_none_fields( self ):
        """Ensures: an all-optional-None ParserError has empty context."""
        err = ParserError( "parse boom" )
        assert err.context == {}

    def test_subclass_of_base( self ):
        """Ensures: ParserError is a BranchAnalyzerError."""
        assert issubclass( ParserError, BranchAnalyzerError )


class TestClassificationError:
    """file/line classification failures carry filename/line_content/type."""

    def test_full_fields_stored_and_line_content_truncated( self ):
        """
        Ensures:
            - filename/line_content/classifier_type stored verbatim
            - context line_content truncated to 100 chars
        """
        big_line = "z" * 150
        err = ClassificationError(
            message         = "weird line",
            filename        = "test.py",
            line_content    = big_line,
            classifier_type = "line",
        )
        assert err.filename == "test.py"
        assert err.line_content == big_line
        assert err.classifier_type == "line"
        assert len( err.context[ "line_content" ] ) == 100

    def test_minimal_omits_none_fields( self ):
        """Ensures: an all-optional-None ClassificationError has empty context."""
        err = ClassificationError( "classify boom" )
        assert err.context == {}

    def test_subclass_of_base( self ):
        """Ensures: ClassificationError is a BranchAnalyzerError."""
        assert issubclass( ClassificationError, BranchAnalyzerError )


class TestExceptionHierarchy:
    """All package exceptions share the BranchAnalyzerError base."""

    @pytest.mark.parametrize( "exc_cls", [
        GitCommandError,
        ConfigurationError,
        ParserError,
        ClassificationError,
    ] )
    def test_all_subclasses_catchable_as_base( self, exc_cls ):
        """
        Ensures:
            - every package exception can be caught via the base type
        """
        with pytest.raises( BranchAnalyzerError ):
            raise exc_cls( "boom" )
