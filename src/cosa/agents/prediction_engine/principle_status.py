"""
What the preference learner believes about a principle at the moment of one ask.

Status is derived, never stored. It is read from the append-only ``preference_evidence`` rows usable at the ask.
A row is usable when the answer was given at or before the ask (the one as-of rule, ``answer_known_at_ask``).
The extractor must also have written it at or before the ask (``extracted_at``).
A later row, or a later ruling, is invisible, so a replay of an ask sees what the live system saw.

The four statuses:

- ``hypothesis``  supporting evidence from one episode, or from sessions that cannot be told apart
- ``established`` supporting evidence from two or more distinct sessions
- ``contested``   the same condition holds both supporting and contradicting evidence
- ``retracted``   only contradicting evidence, or Rick ruled it out

A ruling is an evidence row with ``source = review_card``: Rick's answer to a contested principle.
The extractor never reads it; this module does. The row keeps its relation and condition, so the three
choices are three rows (the mapping is this module's, because no writer exists yet):

- relation ``supports``, no condition   the principle stands as stated
- relation ``refines``, with a condition  it stands, under that condition
- relation ``contradicts``              it is retracted

A split is a ruling the system makes itself: two rows with source ``split_step``, written together.
A card feature separated the supporting episodes from the contradicting ones.
The ``refines`` row holds the supporting side's condition, and the ``contradicts`` row holds the other side's. Both name the feature as their field key.
The ``refines`` row is read as a ruling is: it clears contested from the moment it was written, and not before.
The ``contradicts`` row only says which card feature values belong to the other side, so it never retracts the principle.
A contradiction answered after the split belongs to the other side if its ask has a value there.
It then does not contest the principle.
One with a value on neither side still contests it.

A ruling covers the contradicting rows answered up to its own answer time. A later contradiction counts again.
A ruling applies across extractor versions, the one exception to "the current version only".
A principle re-extracted under a new version names the one it continues (``continues_principle_id``), and inherits that one's rulings.
Retraction of an evidence row (``retracted_at``) takes it out from that moment on.
"""

from cosa.agents.prediction_engine.history_context_rebuild import answer_known_at_ask
from cosa.utils.iso_timestamp import aware_moment

HYPOTHESIS  = "hypothesis"
ESTABLISHED = "established"
CONTESTED   = "contested"
RETRACTED   = "retracted"

SOURCE_RULING   = "review_card"
SOURCE_SPLIT    = "split_step"
RULING_SOURCES  = ( SOURCE_RULING, SOURCE_SPLIT )
VALUE_JOIN      = " or "
SOURCE_EXTRACT  = "extractor"
SUPPORTING      = ( "supports", "refines" )
CONTRADICTING   = "contradicts"
UNINFORMATIVE   = "uninformative"
MIN_SESSIONS    = 2


def usable_at( row, asked_at ):
    """
    Say whether one evidence row existed, as an answer and as a stored row, at the ask.

    Requires:
        - row has answered_at, extracted_at and retracted_at (aware datetimes; retracted_at may be None)
        - asked_at is an aware datetime

    Ensures:
        - returns True only when the answer was known at the ask, the row was extracted at or before it,
          and the row was not retracted at or before it
    """
    if not answer_known_at_ask( row.answered_at, asked_at ): return False
    if aware_moment( row.extracted_at ) > asked_at: return False
    return row.retracted_at is None or aware_moment( row.retracted_at ) > asked_at


def _lineage( principle, by_id ):
    """
    List the ids of a principle and of every earlier principle it continues.

    Requires:
        - principle has id and continues_principle_id; by_id maps an id to a principle

    Ensures:
        - returns the set holding the principle's own id, then its continues_principle_id, then that principle's, and so on
        - stops at a principle with no related id, at an id missing from by_id, and at an id already seen, so a loop ends
    """
    seen    = { principle.id }
    current = principle
    while current.continues_principle_id is not None and current.continues_principle_id not in seen:
        seen.add( current.continues_principle_id )
        current = by_id.get( current.continues_principle_id )
        if current is None: break
    return seen


def _sessions( rows, session_of ):
    """
    Name the distinct sessions behind some evidence rows.

    Requires:
        - rows have notification_id and session_key (a string or None)
        - session_of maps a notification id to its session key or None

    Ensures:
        - a row's own session_key is read first; session_of is asked only for a row that has none
        - returns the set of non-None session keys; an episode with no known session adds none
    """
    return { key for key in ( row.session_key if row.session_key is not None else session_of( row.notification_id ) for row in rows ) if key is not None }


def _conditions( rows ):
    """
    List the conditions of some rows once each, in the order first met.

    Requires:
        - rows have condition, a string or None

    Ensures:
        - returns the non-blank conditions without repeats
    """
    seen = []
    for row in rows:
        if row.condition and row.condition not in seen: seen.append( row.condition )
    return seen


def _contested( supporting, contradicting ):
    """
    Say whether some condition holds both supporting and contradicting evidence.

    Requires:
        - supporting and contradicting are lists of evidence rows with condition

    Ensures:
        - conditions are compared case-folded; no condition is its own group
        - returns True when one group holds a row of each side
    """
    key = lambda row: ( row.condition or "" ).strip().casefold()
    return bool( { key( row ) for row in supporting } & { key( row ) for row in contradicting } )


def _other_side_values( ruling, split_rows ):
    """
    Read the card feature values a split gives to the other side.

    Requires:
        - ruling is a split_step row that refines; split_rows are evidence rows

    Ensures:
        - returns the set of values in the contradicts row written with it: same principle, same feature, same extraction time
        - returns the empty set when there is no such row, or its condition does not read "<feature> is <values>"
    """
    partner = next( ( r for r in split_rows if r.source == SOURCE_SPLIT and r.relation == CONTRADICTING and r.principle_id == ruling.principle_id
                      and r.field_key == ruling.field_key and r.extracted_at == ruling.extracted_at ), None )
    prefix  = f"{ruling.field_key} is "
    if partner is None or not ( partner.condition or "" ).startswith( prefix ): return set()
    return set( partner.condition[ len( prefix ): ].split( VALUE_JOIN ) )


def _ruled( principle, rulings, principles_by_id, asked_at ):
    """
    Find the latest ruling that speaks for a principle and was usable at the ask.

    Requires:
        - rulings are evidence rows with source review_card or split_step; principles_by_id maps an id to a principle

    Ensures:
        - a ruling speaks for the principle it names, and for a principle whose continues_principle_id chain reaches that one
        - owner, scope and dimension are never used to match, so another principle in the same dimension is not ruled
        - a split's contradicts row is never a ruling, because it only names the other side
        - returns the usable ruling with the latest ( answered_at, extracted_at ), or None
    """
    lineage = _lineage( principle, principles_by_id )
    found   = [ r for r in rulings if usable_at( r, asked_at ) and r.principle_id in lineage and not ( r.source == SOURCE_SPLIT and r.relation == CONTRADICTING ) ]
    return max( found, key=lambda r: ( aware_moment( r.answered_at ), aware_moment( r.extracted_at ) ), default=None )


def derive_statuses( principles, evidence, asked_at, current_version, session_of, features_of=None ):
    """
    Derive the status of every principle as of one ask.

    Requires:
        - principles are all of one owner's principle rows, whatever their extractor version
        - evidence is all of the evidence rows for those principles
        - asked_at is an aware datetime; current_version is the extractor version the config names
        - session_of maps a notification id to a session key, or None when it has none
        - features_of is None, or maps a notification id to its card features, or None when unknown

    Ensures:
        - returns { principle.id: result }; result is None when no evidence was usable at the ask
          (so a principle first extracted after the ask is not there), else
          { status, conditions, episodes, sessions, ruled }
        - extractor rows count only for the current version and for their own principle
        - an uninformative row (a bare yes whose principle's antecedent the card lacks) counts for nothing: statuses are the same with it and without it
        - a ruling or split row counts across versions; the latest usable one decides: supports stands, refines stands
          under its condition, contradicts retracts
        - a standing ruling clears contested for the contradicting rows answered at or before the ruling's own answer time
          only; a contradiction answered later counts, and can make the principle contested again
        - after a split, a contradiction answered later whose ask has a feature value on the split's other side does not count against the principle;
          with features_of None, or a value on neither side, it counts as before
        - a retracting ruling is final
        - no row is read or written outside the arguments, and none is changed
    """
    by_id    = { p.id: p for p in principles }
    rulings  = [ e for e in evidence if e.source in RULING_SOURCES ]
    own      = [ e for e in evidence if e.source == SOURCE_EXTRACT and e.extractor_version == current_version and e.relation != UNINFORMATIVE and usable_at( e, asked_at ) ]
    statuses = {}
    for principle in principles:
        rows        = [ e for e in own if e.principle_id == principle.id ]
        supporting  = [ e for e in rows if e.relation in SUPPORTING ]
        contra      = [ e for e in rows if e.relation == CONTRADICTING ]
        if not rows:
            statuses[ principle.id ] = None
            continue
        ruling      = _ruled( principle, rulings, by_id, asked_at )
        sessions    = _sessions( supporting, session_of )
        conditions  = _conditions( supporting )
        if ruling is not None and ruling.relation == CONTRADICTING: status = RETRACTED
        elif ruling is not None:
            later = [ e for e in contra if aware_moment( e.answered_at ) > aware_moment( ruling.answered_at ) ]
            if ruling.source == SOURCE_SPLIT and features_of is not None:
                other = _other_side_values( ruling, rulings )
                later = [ e for e in later if str( ( features_of( e.notification_id ) or {} ).get( ruling.field_key ) ) not in other ]
            if _contested( supporting, later ): status = CONTESTED
            else: status = ESTABLISHED if len( sessions ) >= MIN_SESSIONS else HYPOTHESIS
        elif not supporting: status = RETRACTED
        elif _contested( supporting, contra ): status = CONTESTED
        else: status = ESTABLISHED if len( sessions ) >= MIN_SESSIONS else HYPOTHESIS
        if ruling is not None and ruling.condition and ruling.condition not in conditions: conditions.append( ruling.condition )
        statuses[ principle.id ] = { "status": status, "conditions": conditions, "episodes": len( { e.notification_id for e in supporting } ),
                                     "sessions": len( sessions ), "ruled": ruling is not None }
    return statuses
