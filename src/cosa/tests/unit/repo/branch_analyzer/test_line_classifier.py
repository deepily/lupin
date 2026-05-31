"""
Unit tests for cosa.repo.branch_analyzer.line_classifier.

Tests LineClassifier: stateful classification of source lines into
code / comment / docstring / blank for Python and JS/TS, with multiline
construct tracking (Python triple-quote docstrings, JS block comments).
Coverage drives the real state machine: single- and multi-line constructs,
the blank/None path, the unknown-language fall-through, and the accessor
helpers.

Part of the CoSA 100% coverage campaign (repo module group).
"""
import pytest

from cosa.repo.branch_analyzer.line_classifier import LineClassifier


@pytest.fixture
def classifier():
    """A LineClassifier with the default supported-language set."""
    return LineClassifier( {} )


def _run( classifier, lines, language ):
    """
    Drive a sequence of lines through the classifier, threading state.

    Requires:
        - lines is a list of raw source strings
        - language is a supported language key

    Ensures:
        - returns the list of category results in order
    """
    state = classifier.create_state( language )
    results = []
    for line in lines:
        category, state = classifier.classify_line( line, language, state )
        results.append( category )
    return results


class TestInit:
    """Supported languages come from config, with a sensible default."""

    def test_default_supported_languages( self, classifier ):
        """Ensures: python/javascript/typescript supported by default."""
        langs = classifier.get_supported_languages()
        assert set( langs ) == { "python", "javascript", "typescript" }

    def test_config_overrides_supported_languages( self ):
        """Ensures: an explicit analysis.supported_languages list is honoured."""
        clf = LineClassifier( { "analysis": { "supported_languages": [ "python" ] } } )
        assert clf.get_supported_languages() == [ "python" ]

    def test_debug_init_logs_supported_languages( self, capsys ):
        """Ensures: debug=True emits the supported-languages line at init."""
        LineClassifier( {}, debug=True )
        assert "Supported languages" in capsys.readouterr().out

    def test_supports_language_reflects_membership( self, classifier ):
        """Ensures: supports_language() is True/False by membership."""
        assert classifier.supports_language( "python" ) is True
        assert classifier.supports_language( "rust" ) is False

    def test_get_supported_languages_returns_copy( self, classifier ):
        """Ensures: the returned list is a defensive copy."""
        langs = classifier.get_supported_languages()
        langs.append( "rust" )
        assert "rust" not in classifier.get_supported_languages()


class TestCreateState:
    """create_state() seeds language-appropriate tracking fields."""

    def test_python_state_shape( self, classifier ):
        """Ensures: python state tracks docstring flag + delimiter."""
        state = classifier.create_state( "python" )
        assert state == { "in_docstring": False, "docstring_delimiter": None, "language": "python" }

    def test_javascript_state_shape( self, classifier ):
        """Ensures: javascript state tracks block-comment flag."""
        state = classifier.create_state( "javascript" )
        assert state == { "in_block_comment": False, "language": "javascript" }

    def test_typescript_shares_js_state_shape( self, classifier ):
        """Ensures: typescript uses the JS-style block-comment state."""
        state = classifier.create_state( "typescript" )
        assert state == { "in_block_comment": False, "language": "typescript" }

    def test_unknown_language_minimal_state( self, classifier ):
        """Ensures: an unknown language gets a minimal language-only state."""
        assert classifier.create_state( "rust" ) == { "language": "rust" }


class TestBlankAndUnknown:
    """Blank lines classify as None; unknown languages classify as code."""

    def test_blank_line_returns_none( self, classifier ):
        """Ensures: a whitespace-only line classifies as None (blank)."""
        state = classifier.create_state( "python" )
        category, _ = classifier.classify_line( "   ", "python", state )
        assert category is None

    def test_unknown_language_is_code( self, classifier ):
        """Ensures: a non-blank line in an unknown language is 'code'."""
        state = classifier.create_state( "rust" )
        category, _ = classifier.classify_line( "fn main() {}", "rust", state )
        assert category == "code"


class TestPython:
    """Python: comments, single/multi-line docstrings, and code."""

    def test_single_line_comment( self, classifier ):
        """Ensures: a '#'-prefixed line is a comment."""
        assert _run( classifier, [ "# hi" ], "python" ) == [ "comment" ]

    def test_plain_code( self, classifier ):
        """Ensures: an ordinary statement is code."""
        assert _run( classifier, [ "x = 42" ], "python" ) == [ "code" ]

    def test_single_line_docstring( self, classifier ):
        """Ensures: a one-line triple-quoted string is a docstring (count>=2)."""
        assert _run( classifier, [ '"""one liner"""' ], "python" ) == [ "docstring" ]

    def test_multiline_docstring_spans_lines( self, classifier ):
        """
        Ensures:
            - an opening triple-quote starts docstring mode
            - interior lines remain docstring
            - the closing triple-quote ends the run, all tagged docstring
        """
        lines = [ '"""', "body line", '"""', "y = 1" ]
        assert _run( classifier, lines, "python" ) == [ "docstring", "docstring", "docstring", "code" ]

    def test_single_quote_multiline_docstring( self, classifier ):
        """Ensures: the ''' delimiter variant also opens/closes a docstring."""
        lines = [ "'''", "body", "'''" ]
        assert _run( classifier, lines, "python" ) == [ "docstring", "docstring", "docstring" ]


class TestJavaScript:
    """JS/TS: line comments, block comments (single/multi-line), and code."""

    def test_line_comment( self, classifier ):
        """Ensures: a '//' line is a comment."""
        assert _run( classifier, [ "// note" ], "javascript" ) == [ "comment" ]

    def test_plain_code( self, classifier ):
        """Ensures: an ordinary statement is code."""
        assert _run( classifier, [ "var x = 42;" ], "javascript" ) == [ "code" ]

    def test_single_line_block_comment( self, classifier ):
        """Ensures: a self-contained /* ... */ is a comment."""
        assert _run( classifier, [ "/* inline */" ], "javascript" ) == [ "comment" ]

    def test_multiline_block_comment( self, classifier ):
        """
        Ensures:
            - an unterminated '/*' opens block-comment mode
            - interior + '*'-prefixed lines stay comment
            - the '*/' line closes it; following code is code
        """
        lines = [ "/* start", " * mid", " end */", "z = 1;" ]
        assert _run( classifier, lines, "javascript" ) == [ "comment", "comment", "comment", "code" ]

    def test_star_prefixed_line_outside_block_is_comment( self, classifier ):
        """Ensures: a lone '*'-prefixed line is treated as comment continuation."""
        assert _run( classifier, [ "* doc continuation" ], "javascript" ) == [ "comment" ]

    def test_inline_block_comment_start_not_at_bol_is_code( self, classifier ):
        """Ensures: code with a trailing '/*' (not at line start) stays code."""
        assert _run( classifier, [ "x = 1; /* tail" ], "javascript" ) == [ "code" ]
