"""
Accuracy comparators — per-response-type functions for measuring prediction accuracy.

Each comparator takes predicted and actual values and returns (match, detail_dict).
Used by PredictionEngine.record_outcome() to populate accuracy_match and accuracy_detail
in the prediction_log table.
"""

from typing import Tuple, Dict, Any, Optional

from cosa.agents.prediction_engine.config import (
    RESPONSE_TYPE_YES_NO,
    RESPONSE_TYPE_MULTIPLE_CHOICE,
    RESPONSE_TYPE_OPEN_ENDED,
    RESPONSE_TYPE_OPEN_ENDED_BATCH,
    MULTI_SELECT_JACCARD_THRESHOLD,
    OPEN_ENDED_SIMILARITY_THRESHOLD,
)


def compare_yes_no( predicted: Optional[Dict], actual: Optional[Dict] ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Compare yes/no prediction against actual response.

    Requires:
        - predicted and actual are dicts with "value" key, or None
        - value is "yes" or "no" (possibly with "[comment: ...]" suffix)

    Ensures:
        - Returns (match_bool, detail_dict)
        - match is True if base binary values match
        - detail includes predicted_binary, actual_binary, and qualifier info
        - Returns (None, {}) if either input is None
    """
    if predicted is None or actual is None:
        return ( None, { "reason": "missing_data" } )

    predicted_value = predicted.get( "value", "" )
    actual_value    = actual.get( "value", "" )

    # Extract base binary value (strip "[comment: ...]" suffix)
    predicted_binary = _extract_binary( predicted_value )
    actual_binary    = _extract_binary( actual_value )

    match = predicted_binary == actual_binary

    detail = {
        "predicted_binary" : predicted_binary,
        "actual_binary"    : actual_binary,
        "match"            : match,
    }

    # Check for qualifier (comment) in actual
    actual_qualifier = _extract_qualifier( actual_value )
    if actual_qualifier:
        detail[ "actual_qualifier" ] = actual_qualifier

    # Check for qualifier (comment) in predicted
    predicted_qualifier = predicted.get( "qualifier" )
    if predicted_qualifier:
        detail[ "predicted_qualifier" ] = predicted_qualifier

    return ( match, detail )


def compare_multiple_choice_single( predicted: Optional[Dict], actual: Optional[Dict] ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Compare single-select multiple choice prediction against actual.

    Requires:
        - predicted and actual are dicts with "answers" key containing {"Header": "OptionLabel"}
        - Or None

    Ensures:
        - Returns (match_bool, detail_dict)
        - match is True if all header→option pairs match exactly
        - Returns (None, {}) if either is None
    """
    if predicted is None or actual is None:
        return ( None, { "reason": "missing_data" } )

    predicted_answers = predicted.get( "answers", {} )
    actual_answers    = actual.get( "answers", {} )

    if not predicted_answers or not actual_answers:
        return ( None, { "reason": "empty_answers" } )

    matches     = 0
    total       = 0
    mismatches  = []

    for header, actual_option in actual_answers.items():
        total += 1
        predicted_option = predicted_answers.get( header )
        if predicted_option == actual_option:
            matches += 1
        else:
            mismatches.append( {
                "header"    : header,
                "predicted" : predicted_option,
                "actual"    : actual_option,
            } )

    match = matches == total and total > 0

    detail = {
        "matches"    : matches,
        "total"      : total,
        "mismatches" : mismatches,
    }

    return ( match, detail )


def compare_multiple_choice_multi( predicted: Optional[Dict], actual: Optional[Dict] ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Compare multi-select multiple choice prediction against actual using Jaccard similarity.

    Requires:
        - predicted and actual are dicts with "answers" key containing {"Header": ["A", "B"]}
        - Or None

    Ensures:
        - Returns (match_bool, detail_dict)
        - match is True if Jaccard similarity >= MULTI_SELECT_JACCARD_THRESHOLD (0.5)
        - detail includes per-header Jaccard scores
    """
    if predicted is None or actual is None:
        return ( None, { "reason": "missing_data" } )

    predicted_answers = predicted.get( "answers", {} )
    actual_answers    = actual.get( "answers", {} )

    if not predicted_answers or not actual_answers:
        return ( None, { "reason": "empty_answers" } )

    header_scores = {}
    overall_jaccard_sum = 0.0
    header_count        = 0

    for header, actual_options in actual_answers.items():
        predicted_options = predicted_answers.get( header, [] )

        # Normalize to sets
        actual_set    = set( actual_options ) if isinstance( actual_options, list ) else { actual_options }
        predicted_set = set( predicted_options ) if isinstance( predicted_options, list ) else { predicted_options }

        intersection = actual_set & predicted_set
        union        = actual_set | predicted_set

        jaccard = len( intersection ) / len( union ) if len( union ) > 0 else 0.0

        header_scores[ header ] = {
            "jaccard"   : round( jaccard, 3 ),
            "predicted" : sorted( predicted_set ),
            "actual"    : sorted( actual_set ),
        }

        overall_jaccard_sum += jaccard
        header_count += 1

    avg_jaccard = overall_jaccard_sum / header_count if header_count > 0 else 0.0
    match       = avg_jaccard >= MULTI_SELECT_JACCARD_THRESHOLD

    detail = {
        "avg_jaccard"   : round( avg_jaccard, 3 ),
        "threshold"     : MULTI_SELECT_JACCARD_THRESHOLD,
        "header_scores" : header_scores,
    }

    return ( match, detail )


def compare_open_ended( predicted: Optional[Dict], actual: Optional[Dict] ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Compare open-ended prediction against actual response.

    Uses two strategies:
    1. Embedding cosine similarity if _embedding_similarity was injected
    2. Fallback to exact string match (case-insensitive, stripped)

    Requires:
        - predicted and actual are dicts with "value" key
        - Or None
        - actual may contain transient "_embedding_similarity" float from enrichment

    Ensures:
        - Returns (match_bool, detail_dict)
        - match is True if embedding similarity >= OPEN_ENDED_SIMILARITY_THRESHOLD (0.85)
        - Falls back to exact string match if no embedding similarity available
    """
    if predicted is None or actual is None:
        return ( None, { "reason": "missing_data" } )

    predicted_value = predicted.get( "value", "" )
    actual_value    = actual.get( "value", "" )

    # Strategy 1: Embedding cosine similarity (injected by _enrich_with_embedding_similarity)
    embedding_sim = actual.get( "_embedding_similarity" )
    if isinstance( embedding_sim, ( int, float ) ):
        match = embedding_sim >= OPEN_ENDED_SIMILARITY_THRESHOLD
        detail = {
            "method"     : "embedding_similarity",
            "similarity" : round( float( embedding_sim ), 4 ),
            "threshold"  : OPEN_ENDED_SIMILARITY_THRESHOLD,
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


def compare_open_ended_batch( predicted: Optional[Dict], actual: Optional[Dict] ) -> Tuple[Optional[bool], Dict[str, Any]]:
    """
    Compare open_ended_batch prediction against actual response.

    Per-header comparison using embedding similarity or exact match fallback.
    Overall match = average similarity across all headers >= threshold.

    Requires:
        - predicted and actual are dicts with "answers" key
        - Or None
        - actual may contain "_embedding_similarity" dict of per-header floats

    Ensures:
        - Returns (match_bool, detail_dict)
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
    match          = avg_similarity >= OPEN_ENDED_SIMILARITY_THRESHOLD

    detail = {
        "avg_similarity"  : round( avg_similarity, 4 ),
        "threshold"       : OPEN_ENDED_SIMILARITY_THRESHOLD,
        "header_details"  : header_details,
    }

    return ( match, detail )


def get_comparator( response_type: str, actual_value: Any = None ):
    """
    Return the appropriate comparator function for a given response type.

    Requires:
        - response_type is a valid response type string
        - actual_value: optional actual response dict for data-driven dispatch
          (used to detect multi-select multiple_choice)

    Ensures:
        - Returns a callable (predicted, actual) -> (match, detail)
        - For multiple_choice: inspects actual_value answers for list values
          to choose compare_multiple_choice_multi vs compare_multiple_choice_single
        - Returns compare_open_ended as fallback for unknown types
    """
    # Data-driven dispatch for multiple_choice: detect multi-select from answer values
    if response_type == RESPONSE_TYPE_MULTIPLE_CHOICE and actual_value is not None:
        answers = actual_value.get( "answers", {} ) if isinstance( actual_value, dict ) else {}
        for v in answers.values():
            if isinstance( v, list ):
                return compare_multiple_choice_multi

    comparators = {
        RESPONSE_TYPE_YES_NO           : compare_yes_no,
        RESPONSE_TYPE_MULTIPLE_CHOICE  : compare_multiple_choice_single,
        RESPONSE_TYPE_OPEN_ENDED       : compare_open_ended,
        RESPONSE_TYPE_OPEN_ENDED_BATCH : compare_open_ended_batch,
    }

    return comparators.get( response_type, compare_open_ended )


def _extract_binary( value: str ) -> str:
    """
    Extract binary yes/no from a value that may include a qualifier.

    Examples:
        "yes"                    → "yes"
        "no"                     → "no"
        "yes [comment: only old]" → "yes"
    """
    if not value:
        return ""

    value_lower = value.strip().lower()

    if value_lower.startswith( "yes" ):
        return "yes"
    elif value_lower.startswith( "no" ):
        return "no"

    return value_lower


def _extract_qualifier( value: str ) -> Optional[str]:
    """
    Extract qualifier comment from a yes/no response.

    Example: "yes [comment: only the March ones]" → "only the March ones"
    """
    if not value:
        return None

    marker = "[comment:"
    idx = value.lower().find( marker )
    if idx == -1:
        return None

    # Extract text between "[comment:" and "]"
    start = idx + len( marker )
    end   = value.find( "]", start )
    if end == -1:
        return value[ start: ].strip()

    return value[ start:end ].strip()


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

        # Test 5: multiple choice single
        print( "Testing multiple_choice single comparator..." )
        match, detail = compare_multiple_choice_single(
            { "answers": { "Database": "PostgreSQL" } },
            { "answers": { "Database": "PostgreSQL" } }
        )
        assert match is True
        print( "✓ multiple_choice single match works" )

        # Test 6: multiple choice multi (Jaccard)
        print( "Testing multiple_choice multi comparator..." )
        match, detail = compare_multiple_choice_multi(
            { "answers": { "Features": [ "Auth", "Caching" ] } },
            { "answers": { "Features": [ "Auth", "Logging" ] } }
        )
        # Jaccard = 1/3 ≈ 0.333 < 0.5, so match should be False
        assert match is False
        assert detail[ "avg_jaccard" ] < 0.5
        print( "✓ multiple_choice multi Jaccard works" )

        # Test 7: get_comparator dispatch
        print( "Testing get_comparator dispatch..." )
        comp = get_comparator( "yes_no" )
        assert comp is compare_yes_no
        comp = get_comparator( "unknown_type" )
        assert comp is compare_open_ended
        print( "✓ get_comparator dispatch works" )

        # Test 8: get_comparator with multi-select actual (data-driven dispatch)
        print( "Testing get_comparator multi-select dispatch..." )
        comp = get_comparator( "multiple_choice", actual_value={ "answers": { "Features": [ "A", "B" ] } } )
        assert comp is compare_multiple_choice_multi
        print( "✓ get_comparator multi-select dispatch works" )

        # Test 9: get_comparator with single-select actual (backward compat)
        print( "Testing get_comparator single-select dispatch..." )
        comp = get_comparator( "multiple_choice", actual_value={ "answers": { "DB": "PG" } } )
        assert comp is compare_multiple_choice_single
        print( "✓ get_comparator single-select dispatch works" )

        # Test 10: get_comparator with no actual_value (backward compat)
        print( "Testing get_comparator no actual_value..." )
        comp = get_comparator( "multiple_choice" )
        assert comp is compare_multiple_choice_single
        print( "✓ get_comparator backward compat works" )

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
