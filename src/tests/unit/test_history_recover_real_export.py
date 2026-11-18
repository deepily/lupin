"""
Recovery by response family over Rick's real asks (the `local_data` tier).

The export is the read-only ask file of 18 Nov 2026 in the main checkout's gitignored
`io/write-ups/online-preference-learning/`. Recovery here does not read context, so every ask is
given the state "no_context"; only the open-ended pairing passes it through.
"""

import collections
import json

import pytest

from cosa.agents.prediction_engine.history_derive import derive_dataset
from cosa.agents.prediction_engine.history_recover import recover_by_family
from cosa.utils.local_data_tier import require_local_file

pytestmark = pytest.mark.local_data

LAST_ROW_TAKEN = "2026-11-18T20:16:37.173818Z"
FIELD_TYPES    = ( "multiple_choice", "open_ended_batch" )


def _recovered():
    """The real asks up to the 7,862nd, recovered; the file grows, so the cut is fixed."""
    asks    = [ r for r in ( json.loads( line ) for line in open( require_local_file( "2026.11.18-notification-asks-raw.jsonl" ) ) ) if r[ "created_at" ] <= LAST_ROW_TAKEN ]
    derived = derive_dataset( asks )[ 0 ]
    return asks, recover_by_family( asks, derived, { a[ "id" ]: "no_context" for a in asks } )


def test_the_7862_real_asks_recover_with_these_statuses_by_response_type():
    asks, ( recovered, counts ) = _recovered()
    assert len( asks ) == len( recovered ) == 7862
    assert { t: c[ "rows" ] for t, c in counts.items() } == { "multiple_choice": 3781, "open_ended": 171, "open_ended_batch": 24, "yes_no": 3886 }
    assert { t: { s: n for s, n in c[ "statuses" ].items() if n } for t, c in counts.items() } == {
        "multiple_choice" : { "recovered": 3088, "unread": 5, "no_answer": 688 },
        "open_ended"      : { "recovered": 142, "no_answer": 29 },
        "open_ended_batch": { "recovered": 24 },
        "yes_no"          : { "recovered": 3338, "unread": 4, "no_answer": 544 } }


def test_every_real_ask_is_counted_once_in_its_type_and_in_its_family():
    _, ( _, counts ) = _recovered()
    for c in counts.values():
        assert sum( c[ "statuses" ].values() ) == c[ "rows" ] == sum( f[ "rows" ] for f in c[ "families" ].values() )
    assert { t: len( c[ "families" ] ) for t, c in counts.items() } == { "multiple_choice": 3401, "open_ended": 155, "open_ended_batch": 12, "yes_no": 1787 }


def test_the_real_yes_no_answers_split_by_stance_and_by_whether_they_carry_a_comment():
    _, ( recovered, _ ) = _recovered()
    seen = collections.Counter( ( r[ "recovered" ][ "stance" ], r[ "recovered" ][ "qualified" ] ) for r in recovered if r[ "response_type" ] == "yes_no" and r[ "status" ] == "recovered" )
    assert seen == { ( "yes", False ): 1714, ( "yes", True ): 245, ( "no", False ): 1107, ( "no", True ): 67, ( "neither", False ): 7, ( "neither", True ): 198 }


def test_the_real_field_picks_split_into_offered_options_and_write_ins():
    """A pick outside the offer is a write-in; 1,271 of the 1,389 share no text with any option."""
    _, ( recovered, _ ) = _recovered()
    seen = collections.Counter( f[ "in_offer" ] for r in recovered if r[ "response_type" ] in FIELD_TYPES and r[ "status" ] == "recovered"
                                for f in r[ "recovered" ][ "fields" ].values() )
    assert seen == { True: 2540, False: 1389 }
