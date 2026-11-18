"""
Every multiple-choice decoder reads one stored value as the same headers and picks.

Five readers stay in the tree, each with its own job. The sibling parser is the per-field one.
The rest return the raw answers map, flatten it for a card check, or serve the voice client.
Where one reader gives a different reading for a stated reason, the test pins that difference by name.
"""

import json
from pathlib import Path

import pytest

from cosa.agents.notification_proxy.option_sentinels import _answer_values
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.utils.local_data_tier import require_local_file
from cosa.utils.notification_utils import parse_field_selections
from lupin_mcp.cosa_voice_mcp import _parse_multiple_choice_response

SYNTHETIC = Path( __file__ ).resolve().parents[ 1 ] / "fixtures" / "preference_learning" / "synthetic-export.json"
EXPORT    = "2026.11.17-recent-predictions-285.json"
NEIGHBOURS = "2026.11.17-recent-predictions-285-neighbours.json"

INLINE = [
    { "answers": { "DB": "PostgreSQL" } },
    { "answers": { "Features": [ "Auth", "Caching" ], "DB": "PG" } },
    { "answers": { "Tags": [] , "Mode": "Narrow" } },
    { "answers": { "Mode": "A hybrid mode", "Note": "free text, with a comma" } },
]


def _picks( value ):
    """One field's picks as a sorted list; a blank string is no pick."""
    values = value if isinstance( value, list ) else [ value ]
    return sorted( v.strip() for v in values if isinstance( v, str ) and v.strip() )


def _by_header( answers ):
    """An answers map as { header: sorted picks }."""
    return { header: _picks( value ) for header, value in answers.items() }


def readings( stored ):
    """What each decoder reads from one stored JSON string."""
    return {
        "sibling"  : { h: sorted( f[ "selected" ] ) for h, f in parse_field_selections( stored ).items() },
        "mc"       : _by_header( PredictionEngine._parse_mc_decision_value( stored )[ "answers" ] ),
        "batch"    : _by_header( PredictionEngine._parse_batch_decision_value( stored )[ "answers" ] ),
        "client"   : _by_header( _parse_multiple_choice_response( stored )[ "answers" ] ),
        "flatten"  : sorted( v for v in _answer_values( stored ) if v ),
    }


def is_wrapped( stored ):
    """True when the stored JSON keeps its answers as a string under value."""
    decoded = json.loads( stored )
    return isinstance( decoded, dict ) and "answers" not in decoded and isinstance( decoded.get( "value" ), str )


def assert_agree( stored ):
    """Every decoder reads the same headers and picks."""
    if is_wrapped( stored ):
        return assert_wrapped_is_read_only_by_the_sibling( stored )
    got = readings( stored )
    for name in ( "sibling", "mc", "batch", "client" ):
        assert got[ name ] == got[ "sibling" ], f"{name} disagrees with the sibling parser on {stored!r}"
    if got[ "sibling" ] == {}:
        assert _answer_values( stored ) == [ stored ], f"the flattener must report an empty map as itself: {stored!r}"
        return
    assert got[ "flatten" ] == sorted( p for picks in got[ "sibling" ].values() for p in picks ), f"flatten disagrees on {stored!r}"


def assert_wrapped_is_read_only_by_the_sibling( stored ):
    """
    The one difference that is real, pinned here by name: a wrapped answer.

    The sibling reads the answers inside the wrapper. The other four read none, so a change that
    teaches any of them to unwrap turns this assertion red and has to move it.
    """
    inner = json.loads( stored )[ "value" ]
    assert parse_field_selections( stored ) == parse_field_selections( inner )
    assert PredictionEngine._parse_mc_decision_value( stored ) is None
    assert not isinstance( PredictionEngine._parse_batch_decision_value( stored ), dict ) or "answers" not in PredictionEngine._parse_batch_decision_value( stored )
    assert "answers" not in _parse_multiple_choice_response( stored )
    assert _answer_values( stored ) == [ stored ]


@pytest.mark.parametrize( "answers", INLINE )
def test_every_decoder_agrees_on_the_inline_shapes( answers ):
    assert_agree( json.dumps( answers ) )


def test_a_wrapped_answer_is_read_only_by_the_sibling():
    wrapped = json.dumps( { "value": json.dumps( { "answers": { "DB": "PG", "Tags": [ "a", "b" ] } } ) } )
    assert is_wrapped( wrapped )
    assert_agree( wrapped )
    assert parse_field_selections( wrapped )[ "Tags" ][ "selected" ] == [ "a", "b" ]


def test_every_decoder_agrees_on_every_multiple_choice_row_of_the_synthetic_export():
    rows = [ r for r in json.loads( SYNTHETIC.read_text() )[ "predictions" ] if r[ "response_type" ] == "multiple_choice" ]
    assert len( rows ) == 9
    for row in rows:
        assert_agree( json.dumps( row[ "actual" ] ) )


def test_an_empty_answers_map_is_the_one_value_the_flattener_reports_as_itself():
    """The flattener reports an empty map as itself, never as no values."""
    stored = json.dumps( { "answers": {} } )
    got    = readings( stored )
    assert got[ "sibling" ] == got[ "mc" ] == got[ "batch" ] == got[ "client" ] == {}
    assert _answer_values( stored ) == [ stored ]


@pytest.mark.local_data
def test_every_decoder_agrees_on_every_stored_multiple_choice_value():
    """All five decoders agree on the real export's multiple-choice values."""
    export     = json.load( open( require_local_file( EXPORT ) ) )[ "predictions" ]
    neighbours = json.load( open( require_local_file( NEIGHBOURS ) ) )[ "neighbours" ]
    rows       = [ p for p in export if p[ "response_type" ] == "multiple_choice" ]
    assert len( rows ) == 140
    checked = wrapped_seen = 0
    for row in rows:
        values = [ json.dumps( row[ "actual" ] ) ] + [ c[ "answer" ] for c in neighbours[ row[ "neighbours_ref" ] ][ "by_dot" ] ]
        for stored in values:
            assert_agree( stored )
            checked     += 1
            wrapped_seen += is_wrapped( stored )
    assert checked > 140
    assert wrapped_seen == 6
