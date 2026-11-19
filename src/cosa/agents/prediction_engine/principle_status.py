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

A ruling applies across extractor versions, the one exception to "the current version only".
Retraction of an evidence row (``retracted_at``) takes it out from that moment on.
"""

from cosa.agents.prediction_engine.history_context_rebuild import answer_known_at_ask
from cosa.utils.iso_timestamp import aware_moment

HYPOTHESIS  = "hypothesis"
ESTABLISHED = "established"
CONTESTED   = "contested"
RETRACTED   = "retracted"

SOURCE_RULING   = "review_card"
SOURCE_EXTRACT  = "extractor"
SUPPORTING      = ( "supports", "refines" )
CONTRADICTING   = "contradicts"
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


def _ruling_applies( ruling, ruled, principle ):
    """
    Say whether one ruling speaks for one principle.

    Requires:
        - ruling is a ruling evidence row, ruled the principle it names, principle the one asked about

    Ensures:
        - True when the ruling names this principle
        - True when the ruled principle has another extractor version and the same owner, scope and
          dimension, so a re-extracted principle inherits the ruling
        - False otherwise, in particular for another principle of the same extractor version
    """
    if ruling.principle_id == principle.id: return True
    return ( ruled is not None and ruled.extractor_version != principle.extractor_version
             and ( ruled.owner_id, ruled.scope, ruled.dimension ) == ( principle.owner_id, principle.scope, principle.dimension ) )


def _sessions( rows, session_of ):
    """
    Name the distinct sessions behind some evidence rows.

    Requires:
        - rows have notification_id; session_of maps a notification id to its session key or None

    Ensures:
        - returns the set of non-None session keys; an episode with no known session adds none
    """
    return { key for key in ( session_of( row.notification_id ) for row in rows ) if key is not None }


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


def _ruled( principle, rulings, principles_by_id, asked_at ):
    """
    Find the latest ruling that speaks for a principle and was usable at the ask.

    Requires:
        - rulings are evidence rows with source review_card; principles_by_id maps an id to a principle

    Ensures:
        - returns the usable ruling with the latest ( answered_at, extracted_at ), or None
    """
    found = [ r for r in rulings if usable_at( r, asked_at ) and _ruling_applies( r, principles_by_id.get( r.principle_id ), principle ) ]
    return max( found, key=lambda r: ( aware_moment( r.answered_at ), aware_moment( r.extracted_at ) ), default=None )


def derive_statuses( principles, evidence, asked_at, current_version, session_of ):
    """
    Derive the status of every principle as of one ask.

    Requires:
        - principles are all of one owner's principle rows, whatever their extractor version
        - evidence is all of the evidence rows for those principles
        - asked_at is an aware datetime; current_version is the extractor version the config names
        - session_of maps a notification id to a session key, or None when it has none

    Ensures:
        - returns { principle.id: result }; result is None when no evidence was usable at the ask
          (so a principle first extracted after the ask is not there), else
          { status, conditions, episodes, sessions, ruled }
        - extractor rows count only for the current version and for their own principle
        - a ruling counts across versions; the latest usable one decides: supports stands, refines stands
          under its condition, contradicts retracts
        - a standing ruling clears contested; contradicting rows are then ignored
        - no row is read or written outside the arguments, and none is changed
    """
    by_id    = { p.id: p for p in principles }
    rulings  = [ e for e in evidence if e.source == SOURCE_RULING ]
    own      = [ e for e in evidence if e.source == SOURCE_EXTRACT and e.extractor_version == current_version and usable_at( e, asked_at ) ]
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
        elif ruling is not None: status = ESTABLISHED if len( sessions ) >= MIN_SESSIONS else HYPOTHESIS
        elif not supporting: status = RETRACTED
        elif _contested( supporting, contra ): status = CONTESTED
        else: status = ESTABLISHED if len( sessions ) >= MIN_SESSIONS else HYPOTHESIS
        if ruling is not None and ruling.condition and ruling.condition not in conditions: conditions.append( ruling.condition )
        statuses[ principle.id ] = { "status": status, "conditions": conditions, "episodes": len( { e.notification_id for e in supporting } ),
                                     "sessions": len( sessions ), "ruled": ruling is not None }
    return statuses
