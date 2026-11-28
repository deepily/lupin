"""
Accuracy comparators — per-response-type functions for measuring prediction accuracy.

Each comparator takes predicted and actual values and returns (match, detail_dict).
Used by PredictionEngine.record_outcome() to populate accuracy_match and accuracy_detail
in the prediction_log table.
"""

from functools import partial
from typing import Tuple, Dict, Any, Optional

from cosa.agents.prediction_engine.config import (
    RESPONSE_TYPE_YES_NO,
    RESPONSE_TYPE_MULTIPLE_CHOICE,
    RESPONSE_TYPE_OPEN_ENDED,
    RESPONSE_TYPE_OPEN_ENDED_BATCH,
    OPEN_ENDED_SIMILARITY_THRESHOLD,
    FIELD_OUTCOME_EXACT,
    FIELD_OUTCOME_MISS,
    FIELD_OUTCOME_OTHER_WRITE_IN,
)
from cosa.utils.notification_utils import extract_qualifier_comment, parse_field_selections


def compare_yes_no( predicted: Optional[Dict], actual: Optional[Dict] ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Compare yes/no prediction against actual response.

    Requires:
        - predicted and actual are dicts with "value" key, or None
        - value is "yes", "no" or "neither" (possibly with "[comment: ...]" suffix)

    Ensures:
        - Returns (match_bool, detail_dict)
        - match is True only when both sides carry the same recognised stance; a value with
          no stance reads as "" and never matches, not even another such value
        - detail includes predicted_binary, actual_binary, and qualifier info
        - detail["qualifier_match"] says whether the two comments agree, apart from `match`,
          so a right stance with a different comment is told from a wrong stance
        - Returns (None, {}) if either input is None
    """
    if predicted is None or actual is None:
        return ( None, { "reason": "missing_data" } )

    predicted_value = predicted.get( "value", "" )
    actual_value    = actual.get( "value", "" )

    # The one stance parser. A value it does not recognise has no stance and reads as "".
    predicted_stance, predicted_comment = extract_qualifier_comment( predicted_value )
    actual_stance,    actual_qualifier  = extract_qualifier_comment( actual_value )
    predicted_binary = predicted_stance or ""
    actual_binary    = actual_stance or ""

    # A side with no recognised stance cannot be right, so two unrecognised values do not match
    match = predicted_binary != "" and predicted_binary == actual_binary

    detail = {
        "predicted_binary" : predicted_binary,
        "actual_binary"    : actual_binary,
        "match"            : match,
    }

    if actual_qualifier:
        detail[ "actual_qualifier" ] = actual_qualifier

    # The predictor's own qualifier arrives beside the value, as a key, not inside it
    predicted_qualifier = predicted.get( "qualifier" ) or predicted_comment
    if predicted_qualifier:
        detail[ "predicted_qualifier" ] = predicted_qualifier

    # A qualifier-only difference: the stance is right, the comment is not the same.
    # It is reported apart from stance errors, which are the `match` key.
    detail[ "qualifier_match" ] = ( predicted_qualifier or None ) == ( actual_qualifier or None )

    return ( match, detail )


def compare_open_ended( predicted: Optional[Dict], actual: Optional[Dict], threshold: Optional[float] = None ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Compare open-ended prediction against actual response.

    Uses two strategies:
    1. Embedding cosine similarity if _embedding_similarity was injected
    2. Fallback to exact string match (case-insensitive, stripped)

    Requires:
        - predicted and actual are dicts with "value" key
        - Or None
        - actual may contain transient "_embedding_similarity" float from enrichment
        - threshold is a float in [0, 1], or None to use OPEN_ENDED_SIMILARITY_THRESHOLD

    Ensures:
        - Returns (match_bool, detail_dict)
        - match is True if embedding similarity >= threshold (default 0.75; INI key
          "prediction engine open ended match threshold" supplies it in production)
        - detail[ "threshold" ] records the threshold actually applied
        - Falls back to exact string match if no embedding similarity available
    """
    if predicted is None or actual is None:
        return ( None, { "reason": "missing_data" } )

    predicted_value = predicted.get( "value", "" )
    actual_value    = actual.get( "value", "" )

    if threshold is None: threshold = OPEN_ENDED_SIMILARITY_THRESHOLD

    # Strategy 1: Embedding cosine similarity (injected by _enrich_with_embedding_similarity)
    embedding_sim = actual.get( "_embedding_similarity" )
    if isinstance( embedding_sim, ( int, float ) ):
        match = embedding_sim >= threshold
        detail = {
            "method"     : "embedding_similarity",
            "similarity" : round( float( embedding_sim ), 4 ),
            "threshold"  : threshold,
            "predicted"  : predicted_value[ :100 ],
            "actual"     : actual_value[ :100 ],
        }
        return ( match, detail )

    # Strategy 2: Fallback to exact string match
    match = predicted_value.strip().lower() == actual_value.strip().lower()

    detail = {
        "method"    : "exact_match",
        "predicted" : predicted_value[ :100 ],
        "actual"    : actual_value[ :100 ],
    }

    return ( match, detail )


def compare_open_ended_batch( predicted: Optional[Dict], actual: Optional[Dict], threshold: Optional[float] = None ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Compare open_ended_batch prediction against actual response.

    Per-header comparison using embedding similarity or exact match fallback.
    Overall match = average similarity across all headers >= threshold.

    Requires:
        - predicted and actual are dicts with "answers" key
        - Or None
        - actual may contain "_embedding_similarity" dict of per-header floats
        - threshold is a float in [0, 1], or None to use OPEN_ENDED_SIMILARITY_THRESHOLD

    Ensures:
        - Returns (match_bool, detail_dict)
        - detail[ "threshold" ] records the threshold actually applied
        - Per-header comparison with aggregated match decision
        - Falls back to exact string match per header if no embedding similarity
    """
    if predicted is None or actual is None:
        return ( None, { "reason": "missing_data" } )

    predicted_answers = predicted.get( "answers", {} )
    actual_answers    = actual.get( "answers", {} )

    if not predicted_answers or not actual_answers:
        return ( None, { "reason": "empty_answers" } )

    # Per-header embedding similarity (injected by _enrich_with_embedding_similarity)
    embedding_sims = actual.get( "_embedding_similarity" )
    use_embedding  = isinstance( embedding_sims, dict ) and len( embedding_sims ) > 0

    if threshold is None: threshold = OPEN_ENDED_SIMILARITY_THRESHOLD

    header_details = {}
    similarity_sum = 0.0
    header_count   = 0

    for header, actual_text in actual_answers.items():
        predicted_text = str( predicted_answers.get( header, "" ) )
        actual_text    = str( actual_text )

        if use_embedding and header in embedding_sims:
            sim = float( embedding_sims[ header ] )
            header_details[ header ] = {
                "method"     : "embedding_similarity",
                "similarity" : round( sim, 4 ),
                "predicted"  : predicted_text[ :100 ],
                "actual"     : actual_text[ :100 ],
            }
            similarity_sum += sim
        else:
            # Fallback: exact match yields 1.0 or 0.0
            exact = predicted_text.strip().lower() == actual_text.strip().lower()
            sim   = 1.0 if exact else 0.0
            header_details[ header ] = {
                "method"     : "exact_match",
                "similarity" : sim,
                "predicted"  : predicted_text[ :100 ],
                "actual"     : actual_text[ :100 ],
            }
            similarity_sum += sim

        header_count += 1

    avg_similarity = similarity_sum / header_count if header_count > 0 else 0.0
    match          = avg_similarity >= threshold

    detail = {
        "avg_similarity"  : round( avg_similarity, 4 ),
        "threshold"       : threshold,
        "header_details"  : header_details,
    }

    return ( match, detail )


CONFIDENCE_BAND_EDGES = ( 0.4, 0.6, 0.8, 1.0 )


def confidence_band( confidence ):
    """
    Name the confidence band a forecast falls in, by the band's lower edge.

    The bands are [0, 0.4), [0.4, 0.6), [0.6, 0.8) and [0.8, 1.0]. A confidence exactly on
    an edge belongs to the band that starts there, and 1.0 closes the top band. The 0.6 edge
    lines up with the display threshold.

    Requires:
        - confidence is a number or None

    Ensures:
        - Returns 0.0, 0.4, 0.6 or 0.8
        - Returns None for None, NaN, or a confidence below 0 or above 1
    """
    if confidence is None or confidence != confidence or confidence < 0 or confidence > 1: return None
    lower = 0.0
    for edge in CONFIDENCE_BAND_EDGES[ :-1 ]:
        if confidence >= edge: lower = edge
    return lower


def offered_labels( field_schema ):
    """
    Name the labels one field of a stored schema offered.

    Requires:
        - field_schema is a dict (one entry of a notification's response_options "questions" list)

    Ensures:
        - Returns the set of stripped string labels of the field's option dicts
        - Returns an empty set when the field lists no options or "options" is not a list of dicts
    """
    options = field_schema.get( "options" )
    if not isinstance( options, list ): return set()
    return { option[ "label" ].strip() for option in options if isinstance( option, dict ) and isinstance( option.get( "label" ), str ) }


def score_field( field_schema, predicted, actual, per_field=False ):
    """
    Score one answer field by the mode its schema names, ignoring the shape of the answers.

    Requires:
        - field_schema is a dict with "header" and optionally "multi_select" (the shape of
          one entry of a notification's response_options "questions" list)
        - predicted and actual are the field's values: a string, a list or None
        - per_field is True only when the per-field multiple-choice switch is on

    Ensures:
        - Returns { "header", "mode", "exact", "jaccard", "predicted", "actual" }
        - with per_field True the record also carries "outcome": "other_write_in" when the field's
          schema lists its options and the actual picks include one that is not an offered label,
          else "exact" or "miss" by "exact"; a field that lists no options is never other_write_in
        - with per_field False the record has no "outcome" key, exactly as before
        - mode is "multi" or "single", taken from the schema
        - jaccard is a float for "multi" and None for "single"; two empty sets give 1.0
        - predicted and actual are the sorted picks, so the record does not depend on order

    A multi-select field is exact when the two sets of picks are equal, and carries the
    Jaccard overlap of the sets. Any other field is exact when its single pick is equal.
    Both sides are read through parse_field_selections, so write-ins, free text and
    empty sets are scored the same way as listed options.
    """
    header = field_schema[ "header" ]
    multi  = bool( field_schema.get( "multi_select" ) )
    picks  = {}
    for side, value in ( ( "predicted", predicted ), ( "actual", actual ) ):
        fields       = parse_field_selections( { "answers": { header: [] if value is None else value } } )
        picks[ side ] = sorted( set( fields[ header ][ "selected" ] ) )

    exact   = picks[ "predicted" ] == picks[ "actual" ]
    jaccard = None
    if multi:
        union   = set( picks[ "predicted" ] ) | set( picks[ "actual" ] )
        jaccard = len( set( picks[ "predicted" ] ) & set( picks[ "actual" ] ) ) / len( union ) if union else 1.0

    record = {
        "header"    : header,
        "mode"      : "multi" if multi else "single",
        "exact"     : exact,
        "jaccard"   : None if jaccard is None else round( jaccard, 3 ),
        "predicted" : picks[ "predicted" ],
        "actual"    : picks[ "actual" ],
    }
    if per_field:
        offered = offered_labels( field_schema )
        if offered and any( pick not in offered for pick in picks[ "actual" ] ):
            record[ "outcome" ] = FIELD_OUTCOME_OTHER_WRITE_IN
        else:
            record[ "outcome" ] = FIELD_OUTCOME_EXACT if exact else FIELD_OUTCOME_MISS

    return record


def predicted_answers_of( predicted ):
    """
    Read every field a multiple-choice forecast answered, typed fields included.

    Requires:
        - predicted is a forecast dict, with an "answers" map and optionally the full-answer "fields" map

    Ensures:
        - returns { header: pick } holding the forecast's "answers", plus the write-in or re-frame text of each
          field in "fields" that "answers" lacks, because parse_full_reply leaves a typed field out of "answers"
        - an entry in "answers" is never replaced by one in "fields"
        - a field of "fields" holding option ids or a batch gist adds nothing
    """
    answers = dict( predicted.get( "answers" ) or {} )
    for header, selection in ( predicted.get( "fields" ) or {} ).items():
        if header in answers or not isinstance( selection, dict ): continue
        typed = selection.get( "write_in", selection.get( "reframe" ) )
        if typed is not None: answers[ header ] = typed
    return answers


def schema_questions( response_options ):
    """
    Read the field list of a stored multiple-choice schema, or say it is malformed.

    Requires:
        - response_options is anything: a stored schema, None, or a value of any other type

    Ensures:
        - returns the "questions" list when response_options is a dict whose "questions" is a list of dicts that each
          carry a string "header"; a dict with no "questions" key gives an empty list
        - returns None for anything else, the case compare_multiple_choice reports as "malformed_schema"
    """
    questions = response_options.get( "questions", [] ) if isinstance( response_options, dict ) else None
    if not isinstance( questions, list ) or not all( isinstance( q, dict ) and isinstance( q.get( "header" ), str ) for q in questions ): return None
    return questions


def compare_multiple_choice( predicted, actual, response_options, per_field=False ):
    """
    Score a multiple-choice card field by field, by the schema stored with the notification.

    Requires:
        - predicted and actual are dicts with an "answers" map, or None
        - response_options is a dict whose "questions" list gives each field's "header"
          and "multi_select", or anything else, which is reported rather than raised

    Ensures:
        - Returns ( match, detail ); ( None, reason ) when a side is missing or has no answers
        - When response_options is not a dict, or its "questions" is not a list of dicts that each
          carry a string "header", the card is scored with every field as a single select and
          detail["schema_reason"] is "malformed_schema"; the answer is never dropped
        - match is the strict whole-card result: every field exact
        - detail["matches"] and detail["total"] count the exact fields over the fields
          scored, so a half-right card is 1 of 2 with match False
        - detail["fields"] holds one score_field record per header the actual answer has;
          a header the schema does not list is scored as single-select
        - with per_field True (the per-field switch is on):
          a header the forecast does not answer abstained, and a field whose actual pick is a typed
          Other (outcome other_write_in) is its own outcome; neither is a miss and neither is in
          "total", so match and "matches" / "total" cover the fields the forecast answered and the
          answer chose from the offered labels
        - detail["other_write_in"] counts the other fields, detail["abstained"] the abstained ones,
          and detail["field_coverage"] is the scored fields over all fields (0.0 for none), so an abstained field and
          an answered field that turned out to be a typed Other are both outside it
        - a card with nothing left to score returns ( None, detail ), so it is not scored at all
        - a record's "abstained" is True for an abstained field, so an abstained Other is told from an answered one
    """
    if predicted is None or actual is None:
        return ( None, { "reason": "missing_data" } )

    predicted_answers = predicted_answers_of( predicted )
    actual_answers    = actual.get( "answers", {} )
    if not predicted_answers or not actual_answers:
        return ( None, { "reason": "empty_answers" } )

    questions = schema_questions( response_options )
    malformed = questions is None
    schemas   = {} if malformed else { q[ "header" ]: q for q in questions }
    fields  = [
        score_field( schemas.get( header, { "header": header } ), predicted_answers.get( header ), value, per_field=per_field )
        for header, value in actual_answers.items()
    ]

    if not per_field:
        matches = sum( 1 for f in fields if f[ "exact" ] )
        detail  = { "matches": matches, "total": len( fields ), "fields": fields }
        if malformed: detail[ "schema_reason" ] = "malformed_schema"
        return ( matches == len( fields ), detail )

    for f in fields: f[ "abstained" ] = f[ "header" ] not in predicted_answers
    scored  = [ f for f in fields if f[ "outcome" ] != FIELD_OUTCOME_OTHER_WRITE_IN and not f[ "abstained" ] ]
    matches = sum( 1 for f in scored if f[ "exact" ] )
    detail  = {
        "matches"        : matches,
        "total"          : len( scored ),
        "other_write_in" : sum( 1 for f in fields if f[ "outcome" ] == FIELD_OUTCOME_OTHER_WRITE_IN ),
        "abstained"      : sum( 1 for f in fields if f[ "abstained" ] ),
        "field_coverage" : round( len( scored ) / len( fields ), 3 ),
        "fields"         : fields,
    }
    if malformed: detail[ "schema_reason" ] = "malformed_schema"

    return ( matches == len( scored ) if scored else None, detail )


def decompose_atoms( predicted_atoms, actual_atoms, single_groups=() ):
    """
    Score a forecast's condition atoms against the answer's, atom by atom, in plain code.

    Requires:
        - predicted_atoms and actual_atoms are iterables of ( group, atom ) pairs whose atoms are option ids,
          labels or stances, never free text; a group is the field the atom belongs to
        - single_groups names the groups that take one atom only

    Ensures:
        - returns { precision, recall, hits, contradictions, omissions, additions }
        - a contradiction is a forecast atom the answer did not give, in a single group where the answer gave another atom
        - an addition is any other forecast atom the answer did not give: unsupported by it
        - an omission is an answer atom the forecast lacks, in a group that holds no contradiction
        - the three flags are disjoint and sorted, so one miss is never counted under two names
        - precision is hits over forecast atoms and recall is hits over answer atoms; an empty side gives 1.0
    """
    predicted      = set( predicted_atoms )
    actual         = set( actual_atoms )
    hits           = predicted & actual
    actual_groups  = { group for group, _ in actual }
    contradictions = { atom for atom in predicted - actual if atom[ 0 ] in single_groups and atom[ 0 ] in actual_groups }
    additions      = ( predicted - actual ) - contradictions
    omissions      = { atom for atom in actual - predicted if atom[ 0 ] not in { group for group, _ in contradictions } }
    return {
        "precision"      : len( hits ) / len( predicted ) if predicted else 1.0,
        "recall"         : len( hits ) / len( actual ) if actual else 1.0,
        "hits"           : sorted( hits ),
        "contradictions" : sorted( contradictions ),
        "omissions"      : sorted( omissions ),
        "additions"      : sorted( additions ),
    }


def _abstained_detail( reason="abstained" ):
    """
    Build the detail of a forecast that gave no answer to score.

    Requires:
        - reason is a short word

    Ensures:
        - returns a detail dict that says abstained and fails the plain-code part, so the caller scores no success
    """
    return { "reason": reason, "abstained": True, "plain_code_match": False }


def _ask_judge( judge, predicted_text, actual_text ):
    """
    Put one pair of free-text conditions to the injected judge.

    Requires:
        - judge is a callable( predicted_text, actual_text ) returning { keeps_every_restriction, invents_nothing }
          as booleans; either text may be None for a side that wrote no condition

    Ensures:
        - returns ( passed, verdict ); passed is True only when the judge says both
        - the judge is called once, and only here
    """
    verdict = judge( predicted_text, actual_text )
    return ( bool( verdict[ "keeps_every_restriction" ] ) and bool( verdict[ "invents_nothing" ] ), verdict )


def _same_text( predicted_text, actual_text ):
    """
    Say whether two free-text conditions are the same words, ignoring case and outer space.

    Requires:
        - each is a string or None

    Ensures:
        - returns True when both are empty or None, or equal once stripped and lower-cased
    """
    return ( predicted_text or "" ).strip().lower() == ( actual_text or "" ).strip().lower()


def compare_complete_action_yes_no( predicted: Optional[Dict], actual: Optional[Dict], judge=None ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Score a yes/no forecast by the whole action: the stance, then its condition.

    Requires:
        - predicted and actual are as compare_yes_no reads them, or None
        - judge is None, or a callable as _ask_judge describes; it is called only for two different free-text
          conditions on a right stance

    Ensures:
        - returns ( match, detail ); ( None, missing_data ) when there is no answer to score
        - an abstention, a forecast with no stance, scores ( False, ... ): no success, with detail["abstained"] True
        - a wrong stance scores False and never calls the judge
        - a right stance with the same condition, or none on either side, scores True with no judge
        - a right stance with differing conditions is decided by the judge; with no judge it is ( None, judge_required )
        - detail["plain_code_match"] is the stance verdict, which stands without the judge
        - detail["stance"] holds compare_yes_no's own detail
    """
    if actual is None: return ( None, { "reason": "missing_data" } )
    if predicted is None: return ( False, _abstained_detail() )
    stance_match, stance_detail = compare_yes_no( predicted, actual )
    detail = { "plain_code_match": stance_match, "stance": stance_detail, "abstained": False }
    if stance_detail[ "predicted_binary" ] == "": detail[ "abstained" ] = True
    if not stance_match:
        detail[ "conditions_by" ] = "not_reached"
        return ( False, detail )
    predicted_condition = stance_detail.get( "predicted_qualifier" )
    actual_condition    = stance_detail.get( "actual_qualifier" )
    if _same_text( predicted_condition, actual_condition ):
        detail[ "conditions_by" ] = "plain_code"
        return ( True, detail )
    if judge is None:
        detail[ "conditions_by" ] = "undecided"
        detail[ "reason" ]        = "judge_required"
        return ( None, detail )
    passed, verdict = _ask_judge( judge, predicted_condition, actual_condition )
    detail[ "conditions_by" ] = "judge"
    detail[ "judge" ]         = verdict
    return ( passed, detail )


def compare_complete_action_multiple_choice( predicted, actual, response_options, judge=None ):
    """
    Score a multiple-choice forecast by the whole card: every field must pass.

    Requires:
        - predicted, actual and response_options are as compare_multiple_choice reads them
        - judge is accepted so every comparator takes the same keyword; it is never called, because the picks,
          write-ins included, are compared exactly

    Ensures:
        - returns ( match, detail ); ( None, ... ) when there is no answer to score
        - a forecast that is None or answers no field scores ( False, abstained )
        - one abstained field fails the card, and so does one inexact field; the rule reads score_field's records
          from compare_multiple_choice and adds no per-field logic
        - detail holds fields_total, fields_passed, fields_abstained, the atom decomposition over ( header, pick ) and
          plain_code_match
    """
    if actual is None or not actual.get( "answers" ): return ( None, { "reason": "missing_data" if actual is None else "empty_answers" } )
    if predicted is None or not predicted_answers_of( predicted ): return ( False, _abstained_detail() )
    _, base      = compare_multiple_choice( predicted, actual, response_options, per_field=True )
    fields       = base[ "fields" ]
    single       = { f[ "header" ] for f in fields if f[ "mode" ] == "single" }
    passed       = sum( 1 for f in fields if f[ "exact" ] and not f[ "abstained" ] )
    abstained    = sum( 1 for f in fields if f[ "abstained" ] )
    complete     = passed == len( fields )
    detail       = {
        "fields_total"     : len( fields ),
        "fields_passed"    : passed,
        "fields_abstained" : abstained,
        "atoms"            : decompose_atoms( [ ( f[ "header" ], pick ) for f in fields for pick in f[ "predicted" ] ],
                                          [ ( f[ "header" ], pick ) for f in fields for pick in f[ "actual" ] ], single ),
        "plain_code_match" : complete,
        "abstained"        : abstained > 0,
        "fields"           : fields,
    }
    if "schema_reason" in base: detail[ "schema_reason" ] = base[ "schema_reason" ]
    return ( complete, detail )


def compare_complete_action_open_ended( predicted: Optional[Dict], actual: Optional[Dict], threshold: Optional[float] = None, judge=None ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Score an open-ended forecast by the whole action, not only by text similarity.

    Requires:
        - predicted and actual are as compare_open_ended reads them, or None
        - judge is None, or a callable as _ask_judge describes

    Ensures:
        - returns ( match, detail ); ( None, missing_data ) when there is no answer to score
        - a blank or missing forecast scores ( False, abstained ): no success
        - the same words score True with no judge; different words are decided by the judge, and with none the
          result is ( None, judge_required )
        - detail["similarity"] holds compare_open_ended's own verdict beside the measure, never in its place
    """
    if actual is None: return ( None, { "reason": "missing_data" } )
    if predicted is None or not ( predicted.get( "value" ) or "" ).strip(): return ( False, _abstained_detail() )
    similarity_match, similarity_detail = compare_open_ended( predicted, actual, threshold )
    detail = { "similarity": similarity_detail, "similarity_match": similarity_match, "abstained": False }
    if _same_text( predicted[ "value" ], actual.get( "value" ) ):
        detail[ "plain_code_match" ] = True
        return ( True, detail )
    detail[ "plain_code_match" ] = False
    if judge is None:
        detail[ "reason" ] = "judge_required"
        return ( None, detail )
    passed, verdict = _ask_judge( judge, predicted[ "value" ], actual.get( "value" ) )
    detail[ "judge" ] = verdict
    return ( passed, detail )


def compare_complete_action_open_ended_batch( predicted: Optional[Dict], actual: Optional[Dict], threshold: Optional[float] = None, judge=None ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Score an open-ended batch forecast by the whole card: every question's answer must pass.

    Requires:
        - predicted and actual are as compare_open_ended_batch reads them, or None
        - judge is None, or a callable as _ask_judge describes

    Ensures:
        - returns ( match, detail ); ( None, ... ) when there is no answer to score
        - a forecast that answers no question, or leaves one out, scores False with that field abstained
        - an answered question with the same words passes with no judge; different words go to the judge, and if
          any is left undecided with no judge and none has failed, the card is ( None, judge_required )
        - detail holds fields_total, fields_passed, fields_abstained and the similarity verdict beside it
    """
    if actual is None or not actual.get( "answers" ): return ( None, { "reason": "missing_data" if actual is None else "empty_answers" } )
    if predicted is None or not predicted.get( "answers" ): return ( False, _abstained_detail() )
    similarity_match, similarity_detail = compare_open_ended_batch( predicted, actual, threshold )
    passed = abstained = failed = undecided = 0
    for header, actual_text in actual[ "answers" ].items():
        if header not in predicted[ "answers" ]:
            abstained += 1
        elif _same_text( str( predicted[ "answers" ][ header ] ), str( actual_text ) ):
            passed += 1
        elif judge is None:
            undecided += 1
        elif _ask_judge( judge, str( predicted[ "answers" ][ header ] ), str( actual_text ) )[ 0 ]:
            passed += 1
        else:
            failed += 1
    total  = len( actual[ "answers" ] )
    detail = { "fields_total": total, "fields_passed": passed, "fields_abstained": abstained,
               "similarity": similarity_detail, "similarity_match": similarity_match,
               "plain_code_match": passed == total, "abstained": abstained > 0 }
    if abstained or failed: return ( False, detail )
    if undecided:
        detail[ "reason" ] = "judge_required"
        return ( None, detail )
    return ( True, detail )


def _complete_action_comparator( response_type, open_ended_threshold, response_options, judge ):
    """
    Bind the complete-action comparator of one response type.

    Requires:
        - the arguments are get_comparator's

    Ensures:
        - returns a callable( predicted, actual ) -> ( match, detail ) bound to the schema, threshold and judge it takes
        - an unknown type gets the open-ended one, as get_comparator's fallback does
    """
    if response_type == RESPONSE_TYPE_MULTIPLE_CHOICE:
        return partial( compare_complete_action_multiple_choice, response_options={} if response_options is None else response_options, judge=judge )
    if response_type == RESPONSE_TYPE_YES_NO:
        return partial( compare_complete_action_yes_no, judge=judge )
    comparator = compare_complete_action_open_ended_batch if response_type == RESPONSE_TYPE_OPEN_ENDED_BATCH else compare_complete_action_open_ended
    return partial( comparator, threshold=open_ended_threshold, judge=judge )


def get_comparator( response_type: str, open_ended_threshold: Optional[float] = None, response_options: Optional[Dict] = None, per_field: bool = False, complete_action: bool = False, judge=None ):
    """
    Return the appropriate comparator function for a given response type.

    Requires:
        - response_type is a valid response type string
        - open_ended_threshold: float in [0, 1] or None (None keeps OPEN_ENDED_SIMILARITY_THRESHOLD)
        - response_options: the notification's stored schema, or None for a card that has none
        - per_field: True when the per-field multiple-choice switch is on
        - complete_action: True only when the complete-action scoring switch is on
        - judge: None, or the injected free-text judge, bound only when complete_action is True

    Ensures:
        - Returns a callable (predicted, actual) -> (match, detail)
        - with complete_action True, every response type returns its compare_complete_action_* comparator,
          bound to the same schema, threshold and judge; with it False the binding is exactly as before
        - For multiple_choice: compare_multiple_choice bound to response_options, whatever shape
          the answers have, and to per_field only when it is True; with no schema every field is scored as a single select
        - When open_ended_threshold is given, the open-ended and batch comparators
          (including the unknown-type fallback) are bound to it
        - Returns compare_open_ended as fallback for unknown types
    """
    if complete_action:
        return _complete_action_comparator( response_type, open_ended_threshold, response_options, judge )

    if response_type == RESPONSE_TYPE_MULTIPLE_CHOICE:
        bound = { "response_options": {} if response_options is None else response_options }
        if per_field: bound[ "per_field" ] = True   # bound only when on, so the switch-off binding is exactly as before
        return partial( compare_multiple_choice, **bound )

    comparators = {
        RESPONSE_TYPE_YES_NO           : compare_yes_no,
        RESPONSE_TYPE_OPEN_ENDED       : compare_open_ended,
        RESPONSE_TYPE_OPEN_ENDED_BATCH : compare_open_ended_batch,
    }

    comparator = comparators.get( response_type, compare_open_ended )

    if open_ended_threshold is not None and comparator in ( compare_open_ended, compare_open_ended_batch ):
        return partial( comparator, threshold=open_ended_threshold )

    return comparator


def quick_smoke_test():
    """Quick smoke test for accuracy comparators."""
    import cosa.utils.util as cu

    cu.print_banner( "Accuracy Comparators Smoke Test", prepend_nl=True )

    try:
        # Test 1: yes/no match
        print( "Testing yes/no comparator..." )
        match, detail = compare_yes_no(
            { "value": "yes" },
            { "value": "yes" }
        )
        assert match is True
        print( "✓ yes/no match works" )

        # Test 2: yes/no mismatch
        match, detail = compare_yes_no(
            { "value": "yes" },
            { "value": "no" }
        )
        assert match is False
        print( "✓ yes/no mismatch works" )

        # Test 3: yes/no with qualifier
        match, detail = compare_yes_no(
            { "value": "yes" },
            { "value": "yes [comment: only the old ones]" }
        )
        assert match is True
        assert detail[ "actual_qualifier" ] == "only the old ones"
        print( "✓ yes/no with qualifier works" )

        # Test 3.5: yes/no with both predicted and actual qualifiers
        match, detail = compare_yes_no(
            { "value": "yes", "qualifier": "only the March ones" },
            { "value": "yes [comment: only the old ones]" }
        )
        assert match is True
        assert detail[ "predicted_qualifier" ] == "only the March ones"
        assert detail[ "actual_qualifier" ] == "only the old ones"
        print( "✓ yes/no with predicted and actual qualifiers works" )

        # Test 4: None handling
        match, detail = compare_yes_no( None, { "value": "yes" } )
        assert match is None
        print( "✓ None handling works" )

        # Test 5: multiple choice scored by schema
        print( "Testing multiple_choice schema comparator..." )
        card = { "questions": [ { "header": "DB" }, { "header": "Features", "multi_select": True } ] }
        match, detail = compare_multiple_choice(
            { "answers": { "DB": "PG", "Features": [ "Auth", "Caching" ] } },
            { "answers": { "DB": "PG", "Features": [ "Auth", "Logging" ] } },
            card
        )
        # One field of two is exact, so the card is not a match
        assert match is False
        assert ( detail[ "matches" ], detail[ "total" ] ) == ( 1, 2 )
        print( "✓ multiple_choice half-right card scores 1 of 2" )

        # Test 6: get_comparator dispatch
        print( "Testing get_comparator dispatch..." )
        assert get_comparator( "yes_no" ) is compare_yes_no
        assert get_comparator( "unknown_type" ) is compare_open_ended
        assert get_comparator( "multiple_choice", response_options=card ).func is compare_multiple_choice
        print( "✓ get_comparator dispatch works" )

        # Test 11: compare_open_ended with embedding similarity
        print( "Testing compare_open_ended with embedding similarity..." )
        match, detail = compare_open_ended(
            { "value": "proceed with deployment" },
            { "value": "go ahead with deployment", "_embedding_similarity": 0.92 }
        )
        assert match is True
        assert detail[ "method" ] == "embedding_similarity"
        assert detail[ "similarity" ] == 0.92
        print( "✓ compare_open_ended embedding similarity works" )

        # Test 12: compare_open_ended exact match fallback
        print( "Testing compare_open_ended exact match fallback..." )
        match, detail = compare_open_ended(
            { "value": "proceed" },
            { "value": "proceed" }
        )
        assert match is True
        assert detail[ "method" ] == "exact_match"
        print( "✓ compare_open_ended exact match fallback works" )

        # Test 13: compare_open_ended_batch with per-header similarity
        print( "Testing compare_open_ended_batch..." )
        match, detail = compare_open_ended_batch(
            { "answers": { "Topic": "quantum computing", "Budget": "no limit" } },
            { "answers": { "Topic": "quantum computing", "Budget": "no limit" },
              "_embedding_similarity": { "Topic": 0.95, "Budget": 0.90 } }
        )
        assert match is True
        assert detail[ "avg_similarity" ] >= 0.85
        print( "✓ compare_open_ended_batch works" )

        # Test 14: get_comparator for open_ended_batch dispatches to batch comparator
        print( "Testing get_comparator open_ended_batch dispatch..." )
        comp = get_comparator( "open_ended_batch" )
        assert comp is compare_open_ended_batch
        print( "✓ get_comparator open_ended_batch dispatch works" )

        print( "\n✓ All accuracy comparator smoke tests passed!" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        cu.print_stack_trace( e, caller="accuracy_comparators.quick_smoke_test()" )


if __name__ == "__main__":
    quick_smoke_test()
