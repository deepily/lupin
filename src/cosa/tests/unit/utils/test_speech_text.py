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
    ( "[label](http://x.test/a)",                 "label" ),
    ( "go [here](/app/docs?path=lupin/a.md) now", "go here now" ),
    ( "![diagram](http://x.test/d.png)",         "diagram" ),
    ( '[label](http://x.test "a title")',        "label" ),
    ( "[ a b ]( /app/x )",                       " a b " ),
    ( "[a [b] c](http://x.test)",                "a [b] c" ),
    ( "[label](/app/x?row=1(2))",                "label" ),
    ( "[](http://x.test)",                       "" ),
    ( "[one](http://a.test) and [two](http://b.test)", "one and two" ),
    ( "see https://x.test/bare now",             "see https://x.test/bare now" ),
    ( "[ref][id] and [alone]",                   "[ref][id] and [alone]" ),
    ( "no links at all",                         "no links at all" ),
    ( "",                                        "" ),
] )
def test_table( text, spoken ):
    assert strip( text ) == spoken


def test_real_approve_line_speaks_labels_only():
    spoken = strip( APPROVE_LINE )
    assert spoken == "- Speech reads only a label approve ☐ 📋"
    assert ROW not in spoken and "/app/" not in spoken


def test_non_string_raises_naming_the_type():
    with pytest.raises( TypeError, match="got int" ):
        strip( 5 )
