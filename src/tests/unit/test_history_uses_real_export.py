"""
The uses assigned over Rick's real asks since 4 Nov 2026 (the `local_data` tier).

The context window is the non-ask export, which starts on 4 Nov, so only asks from then on get a context
state. Both files are read-only exports in the main checkout's gitignored `io/write-ups/online-preference-learning/`.
"""

import collections
import json

import pytest

from cosa.agents.prediction_engine.history_context_rebuild import rebuild_context
from cosa.agents.prediction_engine.history_derive import derive_dataset
from cosa.agents.prediction_engine.history_uses import assign_uses
from cosa.utils.local_data_tier import require_local_file

pytestmark = pytest.mark.local_data

WINDOW_START   = "2026-11-04"
LAST_ROW_TAKEN = "2026-11-18T20:16:37.173818Z"


def _lines( name ):
    """The rows of one export file up to the 7,862nd ask; the files grow."""
    rows = [ json.loads( line ) for line in open( require_local_file( name ) ) ]
    return [ r for r in rows if r[ "created_at" ] <= LAST_ROW_TAKEN ]


def test_the_534_real_asks_in_the_context_window_get_these_uses():
    asks       = _lines( "2026.11.18-notification-asks-raw.jsonl" )
    pool       = _lines( "2026.11.18-notification-nonasks-raw.jsonl" ) + asks
    recent     = [ a for a in asks if a[ "created_at" ] >= WINDOW_START ]
    derived    = { d[ "notification_id" ]: d for d in derive_dataset( asks )[ 0 ] }
    states     = { a[ "id" ]: rebuild_context( a, pool )[ "context_state" ] for a in recent }
    assignments, counts = assign_uses( [ derived[ a[ "id" ] ] for a in recent ], states )
    assert len( recent ) == 534
    assert collections.Counter( states.values() ) == { "reconstructed": 528, "no_context": 3, "ambiguous_only": 3 }
    assert { use: sum( reasons.values() ) for use, reasons in counts.items() } == { "train_or_test": 349, "prompt_only": 5, "sensitivity": 0, "vocabulary_only": 180 }
    assert [ a for a in assignments if a[ "frozen_cohort" ] ] == []


def test_the_7328_real_asks_before_the_window_have_these_attribution_tiers():
    """They predate the context window, so none is assigned a use here."""
    asks    = _lines( "2026.11.18-notification-asks-raw.jsonl" )
    older   = [ a for a in asks if a[ "created_at" ] < WINDOW_START ]
    derived = derive_dataset( older )[ 0 ]
    assert len( older ) == 7328
    tiers   = collections.Counter( d[ "attribution_tier" ] for d in derived )
    assert tiers == { "unknown_actor": 3130, "timeout_default": 1417, "none": 1162, "recipient": 1618, "other_account": 1 }
