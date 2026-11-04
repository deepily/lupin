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
