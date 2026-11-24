#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A three-way stance predictor for yes/no asks: yes, no or neither.

It is the challenger to the engine's fixed "no" margin rule, and it stays in shadow until a paired
comparison says otherwise. It reads only what was known at the ask: the ask's vector, its sender,
and the earlier answered cases.

The probabilities come from two sources. Neighbours of the ask vote, weighted by cosine, recency
and independence. Behind them stands a prior that backs off from the ask's family to its project
to Rick's overall answers. The qualifier is chosen apart from the stance.
"""

from typing import Any, Dict, List, Optional, Tuple

from cosa.agents.prediction_engine.ask_family import UNKNOWN_PROJECT, classify_asks
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.utils.iso_timestamp import aware_moment
from cosa.utils.notification_utils import extract_qualifier_comment
from cosa.utils.recency_weight import recency_weight

STANCES               = ( "yes", "no", "neither" )
NEIGHBOUR_COUNT       = 10
COSINE_FLOOR          = 0.5
DUPLICATE_COSINE      = 0.98
PRIOR_STRENGTH        = 2.0
BACKOFF_STRENGTH      = 2.0
LAPLACE_PSEUDO_COUNT  = 1.0

# The ask fields classify_asks reads. A case without all of them has no family or project.
LEVEL_FIELDS          = ( "response_type", "category", "title", "message", "sender_id", "asked_at" )


def is_owners_human_answer( case: Dict[str, Any], owner_id: str ) -> bool:
    """
    Say whether a case is a human's answer, owned by this owner and not thumbed down.

    Requires:
        - case has answer_source, owner_user_id and ratification_state
        - owner_id is the ask's owner as text

    Ensures:
        - returns True only when answer_source is "human", owner_user_id equals owner_id and ratification_state is not "rejected" in any letter case
        - an absent ratification state counts as not rejected
    """
    return case[ "answer_source" ] == "human" and case[ "owner_user_id" ] == owner_id and ( case[ "ratification_state" ] or "" ).lower() != "rejected"


def usable_cases( ask: Dict[str, Any], cases: List[Dict[str, Any]] ) -> List[Dict[str, Any]]:
    """
    Keep the cases that may cast a personal stance vote on this ask.

    Requires:
        - ask has owner_user_id, or None for an ask that names no owner
        - each case has response_type, decision_value, answer_source, owner_user_id, ratification_state
          and responded_at

    Ensures:
        - keeps a yes/no case with a readable stance, answered by a human, owned by the ask's owner, not
          thumbed down, and answered at or before the ask when the ask carries asked_at
        - an ask that names no owner keeps nothing, as the engine's personal filter does
        - the cases keep their order
    """
    owner = ask[ "owner_user_id" ]
    if owner is None: return []
    asked = aware_moment( ask[ "asked_at" ] ) if ask.get( "asked_at" ) is not None else None
    kept  = []
    for case in cases:
        if case[ "response_type" ] != "yes_no": continue
        if not is_owners_human_answer( case, str( owner ) ): continue
        if extract_qualifier_comment( case[ "decision_value" ] )[ 0 ] is None: continue
        if asked is not None and ( case[ "responded_at" ] is None or aware_moment( case[ "responded_at" ] ) > asked ): continue
        kept.append( case )
    return kept


def levels_of( row: Dict[str, Any] ) -> Tuple[Optional[tuple], Optional[str]]:
    """
    Give a row its family and project, the two back-off levels above the overall prior.

    Requires:
        - row is an ask or case dict

    Ensures:
        - returns ( family, project ) as classify_asks defines them
        - a row missing any of LEVEL_FIELDS returns ( None, None ), so the back-off skips both levels for it
        - a project of "unknown" comes back as None, because an unknown project is not a group
    """
    if any( field not in row for field in LEVEL_FIELDS ): return None, None
    info    = classify_asks( [ row ] )[ 0 ]
    project = None if info[ "project" ] == UNKNOWN_PROJECT else info[ "project" ]
    return info[ "family" ], project


def _smoothed( counts: Dict[str, float], prior: Dict[str, float], strength: float ) -> Dict[str, float]:
    """
    Pull class counts toward a prior.

    Requires:
        - counts and prior have the three stance keys; prior sums to 1; strength is positive

    Ensures:
        - returns ( count + strength * prior ) / ( total + strength ) per stance, summing to 1
        - with zero counts it returns the prior unchanged
    """
    total = sum( counts.values() )
    return { stance: ( counts[ stance ] + strength * prior[ stance ] ) / ( total + strength ) for stance in STANCES }


def backoff_prior( ask: Dict[str, Any], cases: List[Dict[str, Any]], half_life_days: float ) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """
    Estimate the stance prior by backing off from family to project to the overall answers.

    Requires:
        - ask has asked_at; cases are usable_cases of the ask, each with responded_at
        - half_life_days is positive

    Ensures:
        - returns ( prior, levels ); prior sums to 1 over the three stances
        - the overall level is the recency-weighted stance counts of all the cases, each class plus one
          pseudo count; with no cases it is uniform
        - the project level pulls its own counts toward the overall prior, and is skipped when the ask's
          project is unknown
        - the family level pulls its own counts toward the project level, and is skipped when the ask has
          no family
        - a level with no cases of its own returns the level below it unchanged, so at zero family and
          project counts the prior is the overall prior
        - levels names the case counts used at each level
    """
    asked_at          = aware_moment( ask[ "asked_at" ] )
    family, project   = levels_of( ask )
    overall           = { stance: 0.0 for stance in STANCES }
    by_project        = { stance: 0.0 for stance in STANCES }
    by_family         = { stance: 0.0 for stance in STANCES }
    sizes             = { "overall": 0, "project": 0, "family": 0 }
    for case in cases:
        stance, _     = extract_qualifier_comment( case[ "decision_value" ] )
        weight        = recency_weight( ( asked_at - aware_moment( case[ "responded_at" ] ) ).total_seconds(), half_life_days )
        case_family, case_project = levels_of( case )
        overall[ stance ] += weight
        sizes[ "overall" ] += 1
        if project is not None and case_project == project:
            by_project[ stance ] += weight
            sizes[ "project" ] += 1
        if family is not None and case_family == family:
            by_family[ stance ] += weight
            sizes[ "family" ] += 1
    uniform           = { stance: 1.0 / len( STANCES ) for stance in STANCES }
    prior             = _smoothed( overall, uniform, LAPLACE_PSEUDO_COUNT * len( STANCES ) )
    if project is not None: prior = _smoothed( by_project, prior, BACKOFF_STRENGTH )
    if family is not None:  prior = _smoothed( by_family, prior, BACKOFF_STRENGTH )
    return prior, sizes


def neighbours_of( ask: Dict[str, Any], cases: List[Dict[str, Any]], half_life_days: float ) -> List[Dict[str, Any]]:
    """
    Pick the nearest cases and weight each by cosine, recency and independence.

    Requires:
        - ask has question_embedding and asked_at; cases are usable_cases of the ask
        - half_life_days is positive

    Ensures:
        - returns up to NEIGHBOUR_COUNT neighbours with cosine at least COSINE_FLOOR, strongest first, each
          { case, stance, qualifier, cosine, recency, independence, weight }
        - weight is cosine * recency * independence
        - independence is 1 / ( 1 + the number of stronger chosen neighbours whose own cosine to this one
          is at least DUPLICATE_COSINE ), so copies of one question share a single vote between them
        - a case with no vector is never a neighbour
    """
    asked_at = aware_moment( ask[ "asked_at" ] )
    scored   = []
    for case in cases:
        if case[ "question_embedding" ] is None: continue
        similarity = PredictionEngine._cosine_similarity( ask[ "question_embedding" ], case[ "question_embedding" ] )
        if similarity >= COSINE_FLOOR: scored.append( ( similarity, case ) )
    scored.sort( key=lambda pair: -pair[ 0 ] )
    chosen = []
    for similarity, case in scored[ :NEIGHBOUR_COUNT ]:
        stance, qualifier = extract_qualifier_comment( case[ "decision_value" ] )
        copies    = sum( 1 for earlier in chosen
                         if PredictionEngine._cosine_similarity( earlier[ "case" ][ "question_embedding" ], case[ "question_embedding" ] ) >= DUPLICATE_COSINE )
        recency   = recency_weight( ( asked_at - aware_moment( case[ "responded_at" ] ) ).total_seconds(), half_life_days )
        chosen.append( {
            "case"         : case,
            "stance"       : stance,
            "qualifier"    : qualifier,
            "cosine"       : similarity,
            "recency"      : recency,
            "independence" : 1.0 / ( 1 + copies ),
            "weight"       : similarity * recency / ( 1 + copies ),
        } )
    return chosen


def predict_qualifier( neighbours: List[Dict[str, Any]], stance: str ) -> Optional[str]:
    """
    Choose the qualifier on its own, from the neighbours that gave the predicted stance.

    Requires:
        - neighbours are those neighbours_of returns

    Ensures:
        - returns the qualifier of the heaviest neighbour that gave this stance and wrote one
        - returns None when none did
        - the stance probabilities play no part in the choice
    """
    qualified = [ n for n in neighbours if n[ "stance" ] == stance and n[ "qualifier" ] ]
    return max( qualified, key=lambda n: n[ "weight" ] )[ "qualifier" ] if qualified else None


def three_way_forecast( ask: Dict[str, Any], cases: List[Dict[str, Any]], half_life_days: float ) -> Dict[str, Any]:
    """
    Forecast yes, no or neither for a yes/no ask, with the three probabilities.

    Requires:
        - ask has question_embedding, asked_at and owner_user_id
        - cases are rows with the fields usable_cases and neighbours_of read
        - half_life_days is positive

    Ensures:
        - returns { value, qualifier, confidence, probabilities, neighbour_ids, levels }
        - probabilities sum to 1 over the three stances: the weighted neighbour counts pulled toward the back-off prior
        - value is the likeliest stance; a tie goes to yes, then no, then neither
        - there is no margin: a "no" or a "neither" stands whenever it is likeliest
        - confidence is the probability of value
        - with no usable case the probabilities are uniform and value is yes
    """
    usable            = usable_cases( ask, cases )
    prior, levels     = backoff_prior( ask, usable, half_life_days )
    neighbours        = neighbours_of( ask, usable, half_life_days )
    counts            = { stance: 0.0 for stance in STANCES }
    for neighbour in neighbours: counts[ neighbour[ "stance" ] ] += neighbour[ "weight" ]
    probabilities     = _smoothed( counts, prior, PRIOR_STRENGTH )
    value             = max( STANCES, key=lambda stance: ( probabilities[ stance ], -STANCES.index( stance ) ) )
    levels[ "neighbours" ] = len( neighbours )
    return {
        "value"         : value,
        "qualifier"     : predict_qualifier( neighbours, value ),
        "confidence"    : probabilities[ value ],
        "probabilities" : probabilities,
        "neighbour_ids" : [ n[ "case" ][ "id" ] for n in neighbours ],
        "levels"        : levels,
    }
