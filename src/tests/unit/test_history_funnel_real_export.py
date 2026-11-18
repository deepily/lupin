"""
The yes/no family proved on Rick's real inventory and exports (the `local_data` tier).

The asks are cut at the 7,862nd, the non-asks at the same moment, and the inventory is the 17:53 UTC run.
All three sit in the main checkout's gitignored `io/write-ups/online-preference-learning/`.
"""

import json

import pytest

from cosa.agents.prediction_engine.history_context_rebuild import rebuild_context
from cosa.agents.prediction_engine.history_funnel import prove_import
from cosa.utils.local_data_tier import require_local_file

pytestmark = pytest.mark.local_data

LAST_ROW_TAKEN = "2026-11-18T20:16:37.173818Z"
INVENTORY_RUN  = "2026-11-18T17:53:24Z"
WINDOW_START   = "2026-11-04"


def _lines( name ):
    """The rows of one export file up to the 7,862nd ask; the files grow."""
    rows = [ json.loads( line ) for line in open( require_local_file( name ) ) ]
    return [ r for r in rows if r[ "created_at" ] <= LAST_ROW_TAKEN ]


def test_the_yes_no_family_reproduces_the_inventory_and_prints_this_funnel( tmp_path ):
    asks   = _lines( "2026.11.18-notification-asks-raw.jsonl" )
    pool   = _lines( "2026.11.18-notification-nonasks-raw.jsonl" ) + asks
    states = { a[ "id" ]: rebuild_context( a, pool )[ "context_state" ] for a in asks if a[ "response_type" ] == "yes_no" and a[ "created_at" ] >= WINDOW_START }
    got    = prove_import( asks, open( require_local_file( "2026.11.18-inventory-output.txt" ) ).read(), INVENTORY_RUN, "yes_no", states, str( tmp_path ) )
    assert got[ "inventory" ][ "reproduced" ] == { "created": 1, "expired": 1988, "responded": 1882 }
    assert got[ "inventory" ][ "matches" ] is True
    assert got[ "hashes_agree" ] is True
    assert [ ( s[ "stage" ], s[ "count" ] ) for s in got[ "funnel" ] ] == [
        ( "asks", 3886 ), ( "distinct eligible asks", 3761 ), ( "usable answers", 1813 ),
        ( "unambiguous typed labels", 765 ), ( "reconstructable context", 173 ), ( "independent families", 138 ) ]
    assert got[ "funnel" ][ 4 ][ "dropped" ] == { "before the context window": 589, "context ambiguous_only": 3 }
