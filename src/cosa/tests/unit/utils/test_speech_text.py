"""
Unit tests for cosa.utils.speech_text.strip_markdown_links_for_speech.

Venue: :7999-eligible (pure unit, no server, no state).
"""

import pytest

from cosa.utils.speech_text import strip_markdown_links_for_speech as strip

ROW = "a3975cf4-c640-4659-9247-0a99fa8a5f4a"

# Shape written by task_approve_line (see the cosa-voice MCP tool docstring).
APPROVE_LINE = (
    f"- Speech reads only a label [approve ☐](/app/tasks/approve?row={ROW}) "
    f"[📋](/app/tasks/view?row={ROW})"
)


@pytest.mark.parametrize( "text, spoken", [
    ( "[label](http://x.test/a)",                 "label, URL omitted" ),
    ( "go [here](/app/docs?path=lupin/a.md) now", "go here, URL omitted now" ),
    ( "![diagram](http://x.test/d.png)",         "diagram, URL omitted" ),
    ( '[label](http://x.test "a title")',        "label, URL omitted" ),
    ( "[ a b ]( /app/x )",                       " a b , URL omitted" ),
    ( "[a [b] c](http://x.test)",                "a [b] c, URL omitted" ),
    ( "[label](/app/x?row=1(2))",                "label, URL omitted" ),
    ( "[x](http://a/b(c(d)))",                   "x, URL omitted" ),
    ( "[x](http://a/b(c(d(e)))) tail",           "x, URL omitted tail" ),
    ( "[x](http://a/b(c(d))) and [y](http://z/q(r(s)))", "x, URL omitted and y, URL omitted" ),
    ( "[](http://x.test)",                       "URL omitted" ),
    ( "[one](http://a.test) and [two](http://b.test)", "one, URL omitted and two, URL omitted" ),
    ( "see https://x.test/bare now",             "see URL omitted now" ),
    ( "see http://x.test/a?b=1&c=2.",            "see URL omitted." ),
    ( "(see http://x.test/a)",                   "(see URL omitted)" ),
    ( "ends with https://x.test/a, then",        "ends with URL omitted, then" ),
    ( "https://x.test and http://y.test",        "URL omitted and URL omitted" ),
    ( "[ref][id] and [alone]",                   "[ref][id] and [alone]" ),
    ( "ftp://x.test is not http",                "ftp://x.test is not http" ),
    ( "no links at all",                         "no links at all" ),
    ( "",                                        "" ),
] )
def test_table( text, spoken ):
    assert strip( text ) == spoken


def test_real_approve_line_speaks_labels_only():
    spoken = strip( APPROVE_LINE )
    assert spoken == "- Speech reads only a label approve ☐, URL omitted 📋, URL omitted"
    assert ROW not in spoken and "/app/" not in spoken


def test_a_link_is_never_dropped_silently():
    assert "URL omitted" in strip( "[x](http://a.test)" )
    assert "URL omitted" in strip( "http://a.test" )


def test_non_string_raises_naming_the_type():
    with pytest.raises( TypeError, match="got int" ):
        strip( 5 )


def _nested_link( depth ):
    """A link whose target holds `depth` levels of balanced parentheses."""
    return "[x](http://a/b" + "(c" * depth + ")" * depth + ")"


@pytest.mark.parametrize( "depth", [ 1, 2, 6, 7, 50, 3000 ] )
def test_any_depth_of_balanced_parentheses_is_one_link( depth ):
    assert strip( _nested_link( depth ) + " tail" ) == "x, URL omitted tail"


def test_balanced_deep_target_between_two_links_keeps_both_labels():
    text = _nested_link( 50 ) + " and [y](http://z/q(r(s)))"
    assert strip( text ) == "x, URL omitted and y, URL omitted"


@pytest.mark.parametrize( "text, spoken", [
    ( "[x](http://a/b(c(d tail",                "x, URL omitted tail" ),
    ( "[x](http://a/" + "b(" * 40 + " tail",     "x, URL omitted tail" ),
    ( "[x](http://a/b(c(d))",                    "x, URL omitted" ),
    ( "[x](http://a/b(c(d)) tail",               "x, URL omitted tail" ),
] )
def test_unbalanced_target_is_dropped_never_spoken( text, spoken ):
    out = strip( text )
    assert out == spoken
    assert "http" not in out and "a/b" not in out


def test_unbalanced_deep_parentheses_finish_quickly():
    import time
    text  = "[x](http://a/" + "b(" * 5000 + " tail"
    start = time.monotonic()
    out   = strip( text )
    assert time.monotonic() - start < 1.0
    assert out == "x, URL omitted tail"


def test_a_bracket_pair_followed_by_ordinary_parentheses_is_not_a_link():
    assert strip( "[a](b c) rest" ) == "[a](b c) rest"


def test_an_empty_target_is_not_a_link():
    assert strip( "[x]() rest" ) == "[x]() rest"
