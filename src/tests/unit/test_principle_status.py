"""
Principle status as of an ask, from synthetic evidence rows.

Each test names what it would catch:
  - a boundary that differs from the one as-of rule          -> test_usable_at_*, test_answer_known_at_ask_*
  - future evidence leaking into a status                    -> test_no_future_principle_*
  - a status from the wrong extractor version                -> test_other_version_rows_are_not_read
  - established without two sessions                         -> test_established_* and test_same_session_*
  - contested wrongly set or wrongly missed                  -> test_contested_*
  - a ruling that rewrites the past or dies at a version     -> test_ruling_*
The rows are plain objects with the model's column names; no database is touched.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cosa.agents.prediction_engine.history_context_rebuild import answer_known_at_ask
from cosa.agents.prediction_engine.principle_status import ( CONTESTED, ESTABLISHED, HYPOTHESIS, RETRACTED, derive_statuses, usable_at )

ASK  = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
HOUR = timedelta( hours=1 )
V1   = "sonnet|v1"
V2   = "sonnet|v2"


def principle( pid="p1", version=V1, dimension="ask.approval_needs_link", scope="global", owner="owner-a" ):
    """Build a principle row with the model's column names."""
    return SimpleNamespace( id=pid, owner_id=owner, scope=scope, dimension=dimension, extractor_version=version )


def row( pid="p1", note="n1", relation="supports", condition=None, answered=-HOUR, extracted=-HOUR, retracted=None, version=V1, source="extractor" ):
    """Build an evidence row; times are offsets from the ask."""
    return SimpleNamespace( principle_id=pid, notification_id=note, relation=relation, condition=condition, field_key="f",
                            answered_at=ASK + answered, extracted_at=ASK + extracted, retracted_at=None if retracted is None else ASK + retracted,
                            extractor_version=version, source=source )


def ruling( pid="p1", relation="supports", condition=None, answered=-HOUR, extracted=-HOUR, version=V1, retracted=None ):
    """Build a review-card ruling row."""
    return row( pid=pid, note="card", relation=relation, condition=condition, answered=answered, extracted=extracted, version=version, source="review_card", retracted=retracted )


SESSIONS = { "n1": "s1", "n2": "s2", "n3": "s1", "n4": None, "n5": None }
session_of = lambda note: SESSIONS.get( note )


def status_of( principles, evidence, at=ASK, version=V1, pid="p1" ):
    """Derive statuses and return the one named, so a test reads one result."""
    return derive_statuses( principles, evidence, at, version, session_of )[ pid ]


def test_answer_known_at_ask_is_the_one_rule_at_the_boundary():
    """
    The wrapper reads the ask boundary as the one as-of rule.

    The wrapper reads 'at the ask' as known, one second later as not, and a missing time as not.
    """
    assert answer_known_at_ask( ASK, ASK ) is True
    assert answer_known_at_ask( ASK + timedelta( seconds=1 ), ASK ) is False
    assert answer_known_at_ask( None, ASK ) is False
    assert answer_known_at_ask( ( ASK - HOUR ).isoformat(), ASK ) is True


@pytest.mark.parametrize( "kwargs, expected", [
    ( {},                                           True ),
    ( { "answered": HOUR },                         False ),
    ( { "answered": timedelta( 0 ) },               True ),
    ( { "extracted": HOUR },                        False ),
    ( { "extracted": timedelta( 0 ) },              True ),
    ( { "retracted": -HOUR },                       False ),
    ( { "retracted": timedelta( 0 ) },              False ),
    ( { "retracted": HOUR },                        True ),
] )
def test_usable_at_needs_answer_and_extraction_at_or_before_the_ask_and_no_earlier_retraction( kwargs, expected ):
    """
    A row is usable only when both times, and no retraction, precede the ask.

    A row is usable only if both times are at or before the ask and it was not retracted by then.
    """
    assert usable_at( row( **kwargs ), ASK ) is expected


def test_usable_at_reads_a_naive_stored_time_as_utc():
    """SQLite and some drivers return naive datetimes; they must not raise or shift."""
    naive = row( extracted=-HOUR )
    naive.extracted_at = naive.extracted_at.replace( tzinfo=None )
    naive.retracted_at = ( ASK + HOUR ).replace( tzinfo=None )
    assert usable_at( naive, ASK ) is True


def test_hypothesis_is_one_supporting_episode():
    """One supporting row is a hypothesis with one episode and one session."""
    result = status_of( [ principle() ], [ row() ] )
    assert ( result[ "status" ], result[ "episodes" ], result[ "sessions" ], result[ "ruled" ] ) == ( HYPOTHESIS, 1, 1, False )


def test_established_needs_supporting_episodes_from_two_sessions():
    """Two episodes from two sessions establish; refines counts as support."""
    result = status_of( [ principle() ], [ row( note="n1" ), row( note="n2", relation="refines", condition="field asks for approval" ) ] )
    assert ( result[ "status" ], result[ "episodes" ], result[ "sessions" ] ) == ( ESTABLISHED, 2, 2 )
    assert result[ "conditions" ] == [ "field asks for approval" ]


def test_same_session_twice_and_unknown_sessions_stay_a_hypothesis():
    """
    Two episodes from one or unknown sessions stay a hypothesis.

    Two episodes from one session, or from sessions that cannot be named, are not two sessions.
    """
    assert status_of( [ principle() ], [ row( note="n1" ), row( note="n3" ) ] )[ "status" ] == HYPOTHESIS
    assert status_of( [ principle() ], [ row( note="n4" ), row( note="n5" ) ] )[ "status" ] == HYPOTHESIS


def test_contested_when_one_condition_holds_both_sides():
    """
    The same condition on both sides is contested, whatever its case.

    Supporting and contradicting evidence under the same (here empty) condition is contested, whatever its case.
    """
    assert status_of( [ principle() ], [ row( note="n1" ), row( note="n2", relation="contradicts" ) ] )[ "status" ] == CONTESTED
    both = [ row( note="n1", condition="Field Asks" ), row( note="n2", relation="contradicts", condition="field asks" ) ]
    assert status_of( [ principle() ], both )[ "status" ] == CONTESTED


def test_not_contested_when_the_sides_hold_different_conditions():
    """
    A split that gave each side its own condition is not a conflict.

    A split that gave each side its own condition leaves two conditional claims, not a conflict.
    """
    rows = [ row( note="n1", condition="plan A" ), row( note="n2", relation="contradicts", condition="plan B" ) ]
    assert status_of( [ principle() ], rows )[ "status" ] == HYPOTHESIS


def test_only_contradicting_evidence_is_retracted():
    """No supporting row and a contradicting one reads as retracted."""
    assert status_of( [ principle() ], [ row( relation="contradicts" ) ] )[ "status" ] == RETRACTED


def test_no_future_principle_when_all_evidence_is_later_than_the_ask():
    """Evidence answered, or extracted, after the ask leaves no status at all."""
    assert status_of( [ principle() ], [ row( answered=HOUR ) ] ) is None
    assert status_of( [ principle() ], [ row( extracted=HOUR ) ] ) is None
    assert status_of( [ principle() ], [ row( answered=HOUR ), row( note="n2" ) ] )[ "episodes" ] == 1


def test_other_version_rows_are_not_read():
    """
    Rows of an older extractor version give no status for the current one.

    Rows of an older extractor version give no status for the current one; the older rows stay in the table.
    """
    assert status_of( [ principle() ], [ row( version=V1 ) ], version=V2 ) is None
    assert status_of( [ principle() ], [ row( version=V1 ), row( note="n2", version=V2 ) ], version=V2 )[ "episodes" ] == 1


def test_a_row_belongs_to_its_own_principle_only():
    """Evidence of one principle never counts for another."""
    statuses = derive_statuses( [ principle( "p1" ), principle( "p2" ) ], [ row( pid="p1" ) ], ASK, V1, session_of )
    assert statuses[ "p1" ][ "status" ] == HYPOTHESIS and statuses[ "p2" ] is None


def contested_rows():
    """Two sides, one condition: a contested principle whose supporting side spans two sessions."""
    return [ row( note="n1" ), row( note="n2" ), row( note="n3", relation="contradicts" ) ]


def test_ruling_stands_clears_contested():
    """
    A stands ruling clears contested.

    A 'stands' ruling answers the conflict: the principle is no longer contested and keeps its sessions.
    """
    result = status_of( [ principle() ], contested_rows() + [ ruling( relation="supports" ) ] )
    assert ( result[ "status" ], result[ "ruled" ] ) == ( ESTABLISHED, True )


def test_ruling_under_a_condition_adds_the_condition():
    """Both sides under a condition: not contested, and the condition is carried."""
    result = status_of( [ principle() ], contested_rows() + [ ruling( relation="refines", condition="only for plans" ) ] )
    assert result[ "status" ] == ESTABLISHED and result[ "conditions" ] == [ "only for plans" ]
    again = status_of( [ principle() ], [ row( condition="only for plans" ) ] + [ ruling( relation="refines", condition="only for plans" ) ] )
    assert again[ "conditions" ] == [ "only for plans" ]


def test_ruling_retracts():
    """A 'retract' ruling retracts the principle whatever its evidence says."""
    assert status_of( [ principle() ], contested_rows() + [ ruling( relation="contradicts" ) ] )[ "status" ] == RETRACTED


def test_ruling_is_as_of_a_replay_before_the_ruling_still_sees_contested():
    """An ask made before the ruling reads contested; one after it does not; no row was changed."""
    rows   = contested_rows() + [ ruling( answered=HOUR, extracted=2 * HOUR ) ]
    before = status_of( [ principle() ], rows, at=ASK )
    assert before[ "status" ] == CONTESTED and before[ "ruled" ] is False
    assert status_of( [ principle() ], rows, at=ASK + 3 * HOUR )[ "status" ] == ESTABLISHED
    answered_not_yet_extracted = contested_rows() + [ ruling( answered=-HOUR, extracted=HOUR ) ]
    assert status_of( [ principle() ], answered_not_yet_extracted )[ "status" ] == CONTESTED


def test_the_latest_usable_ruling_decides_and_a_retracted_ruling_does_not_count():
    """Rick may change his mind; a ruling taken back is as if never given."""
    rows = contested_rows() + [ ruling( relation="contradicts", answered=-3 * HOUR, extracted=-3 * HOUR ), ruling( relation="supports", answered=-2 * HOUR, extracted=-2 * HOUR ) ]
    assert status_of( [ principle() ], rows )[ "status" ] == ESTABLISHED
    taken_back = contested_rows() + [ ruling( relation="supports", retracted=-HOUR ) ]
    assert status_of( [ principle() ], taken_back )[ "status" ] == CONTESTED


def test_ruling_survives_a_version_switch_when_the_new_version_joins_the_same_principle():
    """
    A V1 ruling still clears a principle the V2 evidence joined.

    The config moves to V2 and V2 evidence lands on the ruled principle: the V1 ruling still clears it.
    """
    rows = [ row( note="n1", version=V2 ), row( note="n2", version=V2 ), row( note="n3", relation="contradicts", version=V2 ), ruling( version=V1 ) ]
    assert status_of( [ principle( "p1", V1 ) ], rows, version=V2 )[ "status" ] == ESTABLISHED


def test_ruling_survives_a_version_switch_when_the_new_version_made_a_new_principle():
    """
    A V2 principle in the ruled one's dimension inherits the ruling.

    A V2 principle with the same owner, scope and dimension as the ruled V1 one inherits the ruling.
    """
    old, new = principle( "p1", V1 ), principle( "p9", V2 )
    rows     = [ row( pid="p9", note="n1", version=V2 ), row( pid="p9", note="n2", version=V2 ), row( pid="p9", note="n3", relation="contradicts", version=V2 ), ruling( pid="p1", version=V1 ) ]
    assert status_of( [ old, new ], rows, version=V2, pid="p9" )[ "status" ] == ESTABLISHED
    assert status_of( [ old, new ], rows, version=V2, pid="p1" ) is None


@pytest.mark.parametrize( "other", [
    principle( "p9", V2, dimension="another.dimension" ),
    principle( "p9", V2, scope="project:lupin" ),
    principle( "p9", V2, owner="owner-b" ),
    principle( "p9", V1 ),
] )
def test_a_ruling_does_not_speak_for_a_different_principle( other ):
    """
    A ruling does not speak for a different principle.

    Another dimension, scope, owner, or another principle of the same version is not covered by the ruling.
    """
    rows = [ row( pid="p9", note="n1", version=other.extractor_version ), row( pid="p9", note="n2", relation="contradicts", version=other.extractor_version ),
             ruling( pid="p1", version=V1 ) ]
    assert status_of( [ principle( "p1", V1 ), other ], rows, version=other.extractor_version, pid="p9" )[ "status" ] == CONTESTED


def test_a_ruling_for_an_unknown_principle_is_ignored():
    """
    A ruling for an unknown principle speaks for nobody else.

    Its principle row is missing from the ledger, so it matches only by its own id.
    """
    rows = contested_rows() + [ ruling( pid="ghost" ) ]
    assert status_of( [ principle() ], rows )[ "status" ] == CONTESTED
