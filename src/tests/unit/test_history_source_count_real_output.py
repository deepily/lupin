"""
The source count over the real baseline inventory output (the `local_data` tier).

The file is Rick's data, in the main checkout's gitignored `io/write-ups/online-preference-learning/`.
In a worktree the folder is absent and the tests skip by name.
"""

import pytest

from cosa.agents.prediction_engine.history_source_count import count_source_population
from cosa.utils.local_data_tier import require_local_file

pytestmark = pytest.mark.local_data


def _counts():
    return count_source_population( open( require_local_file( "2026.11.18-inventory-output.txt" ) ).read() )


def test_the_real_funnel_head_is_959376_then_8261_then_7831():
    assert [ c for _, c, _ in _counts()[ "funnel" ] ] == [ 959376, 8261, 7831 ]


def test_the_real_asks_by_type_are_these():
    by_type = {}
    for ( kind, _ ), count in _counts()[ "by_type_state" ].items(): by_type[ kind ] = by_type.get( kind, 0 ) + count
    assert by_type == { "multiple_choice": 3766, "open_ended": 170, "open_ended_batch": 24, "yes_no": 3871 }


def test_the_real_era_runs_from_may_to_november_2026():
    months = sorted( { m for m, _ in _counts()[ "by_era" ] } )
    assert ( months[ 0 ], months[ -1 ], len( months ) ) == ( "2026-05-01", "2026-11-01", 7 )
