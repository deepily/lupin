"""
The derived history over Rick's real asks (the `local_data` tier).

The file is a read-only export of the notifications addressed to him, taken 18 Nov 2026 and cut at its 7,862nd row.
It sits in the main checkout's gitignored `io/write-ups/online-preference-learning/`. In a worktree the tests skip by name.
"""

import json

import pytest

from cosa.agents.prediction_engine.history_derive import derive_dataset, write_dataset
from cosa.utils.local_data_tier import require_local_file

pytestmark = pytest.mark.local_data


LAST_ROW_TAKEN = "2026-11-18T20:16:37.173818Z"


def _rows():
    """The export's rows up to the 7,862nd, as stored; the file grows with every new ask."""
    rows = [ json.loads( line ) for line in open( require_local_file( "2026.11.18-notification-asks-raw.jsonl" ) ) ]
    return [ r for r in rows if r[ "created_at" ] <= LAST_ROW_TAKEN ]


def test_the_real_export_derives_one_example_per_row_and_names_every_unread_answer():
    rows            = _rows()
    derived, counts = derive_dataset( rows )
    assert len( rows ) == 7862
    assert [ d[ "notification_id" ] for d in derived ] == [ r[ "id" ] for r in rows ]
    assert counts[ "unread_by_reason" ] == { "fields_not_readable": 5, "stance_not_recognised": 4 }
    assert counts[ "tiers" ] == { "unknown_actor": 3130, "timeout_default": 1498, "none": 1261, "recipient": 1972, "other_account": 1 }


def test_the_real_export_is_preserved_and_the_backfill_reproduces_its_hashes( tmp_path ):
    rows  = _rows()
    first = write_dataset( rows, str( tmp_path / "one" ) )
    again = write_dataset( rows, str( tmp_path / "two" ) )
    assert ( first[ "originals_sha256" ], first[ "derived_sha256" ] ) == ( again[ "originals_sha256" ], again[ "derived_sha256" ] )
    assert [ json.loads( line ) for line in open( tmp_path / "one" / "originals.jsonl" ) ] == rows
