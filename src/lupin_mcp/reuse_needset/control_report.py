"""
The positive control's report for run -m, scored by the rules fixed before the run.

A pair is scored where it was lost. Retrieval asks if the plant is in the shortlist, the judge if it was rated relevant, and end to end both.
The plants are scored against their own originals on the same need, because the checker finds a known item about 7 times in 10.
Pairs the human labels call a different job are a negative control, reported apart, and a plant found there is a false positive.
Nothing here makes a model call or reads a file except the label files and the answer key.
"""
import hashlib
import pathlib
import re

from cosa.repo.duplicate_check.proof import label_load, proof_run
from cosa.repo.symindex.candidates import rank_fusion as rf
from lupin_mcp.reuse_e2e import wilson
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import loss_trace

NOT_SAME_JOB   = frozenset( ( "d-35e19468ee", "d-5270a48d23", "d-e4d0d1e147", "d-7a334b0576", "d-803557386f" ) )
LABEL_FILES    = ( "labels-rick.jsonl", "labels-reviewer-2.jsonl", "labels-jason.jsonl" )
PASS_SLACK     = 2
ORIGINAL_FLOOR = 0.57


def file_sha( path ):
    """Ensures: returns the sha256 of the file's bytes as hex."""
    return hashlib.sha256( pathlib.Path( path ).read_bytes() ).hexdigest()


def same_job_labels( pairs, labels_dir, answer_key, expected_not_same=NOT_SAME_JOB ):
    """
    Settle whether each pair is the same job.

    Requires:
        - pairs come from positive_control.load_pairs; labels_dir holds the three label files; answer_key is the run's answer-key path

    Ensures:
        - returns { same_job: { rewrite id: bool }, label_shas: { file name: sha256 }, answer_key_sha }
        - a pair both reviewers label alike takes that label, and a disputed one takes the third rater's, as label_load.resolved_labels settles it
        - the pairs that are not the same job are exactly expected_not_same

    Raises:
        - NeedsetError CONTROL_LABELS_CHANGED naming the difference when the not-same set is not expected_not_same
        - ValueError from label_load when a label file is incomplete
    """
    first, second, third = ( f"{labels_dir}/{name}" for name in LABEL_FILES )
    resolved  = label_load.resolved_labels( first, second, answer_key, third_path=third )
    same_job  = { p[ "rewrite" ][ "id" ]: bool( resolved[ proof_run.label_key( p[ "rewrite" ][ "id" ], p[ "original" ][ "id" ] ) ] ) for p in pairs }
    not_same  = frozenset( i for i, same in same_job.items() if not same )
    if not_same != expected_not_same:
        raise er.NeedsetError( er.CONTROL_LABELS_CHANGED, f"not the same job: {sorted( not_same )}; expected {sorted( expected_not_same )}" )
    return { "same_job": same_job, "label_shas": { name: file_sha( f"{labels_dir}/{name}" ) for name in LABEL_FILES }, "answer_key_sha": file_sha( answer_key ) }


def content_words( text ):
    """Ensures: returns the lower-case words of three or more characters in the text."""
    return set( re.findall( r"[a-z][a-z0-9]{2,}", text.lower() ) )


def word_overlap( need, line ):
    """
    Measure how many words a need and a purpose line share.

    Ensures:
        - returns shared words over all words of the two, from 0.0 to 1.0, rounded to 3 places
        - returns 0.0 when neither holds a word
    """
    a, b = content_words( need ), content_words( line )
    return round( len( a & b ) / len( a | b ), 3 ) if a | b else 0.0


def position( ranked, ident ):
    """Ensures: returns the 1-based place of ident in ranked, or None if absent."""
    return ranked.index( ident ) + 1 if ident is not None and ident in ranked else None


def ranks_of( answer, ident ):
    """
    Give an entry's place in each source list and in the merged list of one search.

    Requires:
        - answer is a search answer whose lists are whole, as PlantedCandidateStage.last_answer holds them

    Ensures:
        - returns { source name: place or None, ..., fused: place or None }
        - the merged list is the one the search fuses, read to the end: the same constants, no cut to the shortlist
    """
    lists = answer[ "lists" ]
    fused = rf.fuse( [ lists[ n ] for n in sorted( lists ) ], rf.FUSION_K, rf.FUSION_DEPTH, rf.FUSION_HEAD )
    return { **{ n: position( lists[ n ], ident ) for n in sorted( lists ) }, "fused": position( fused, ident ) }


def pair_row( pair, label, need, receipt, answer, line, original_id, original_line ):
    """
    Build the row of one drafted pair.

    Requires:
        - receipt is the checker's receipt for the need; answer is the planted stage's last answer for that search
        - line is the plant's purpose line or None; original_id is the original's id in the index or None; original_line is its stored line or None

    Ensures:
        - returns { rewrite, lang, same_job, drafted, plant, original, purpose_line, leak }
        - retrieved means in the ids sent to the judge, and accepted means retrieved and rated relevant by the judge
        - leak is the word overlap of the need with the plant's line and with the original's, None for a line that does not exist
    """
    rid      = pair[ "rewrite" ][ "id" ]
    asked    = set( loss_trace.asked_ids( receipt ) )
    rated    = { row[ "id" ] for row in receipt[ "shortlist" ] }
    side     = lambda ident: { "id": ident, "retrieved": ident in asked, "accepted": ident in asked and ident in rated, "ranks": ranks_of( answer, ident ) }
    return { "rewrite": rid, "lang": pair[ "rewrite" ][ "lang" ], "same_job": label, "drafted": True, "plant": side( rid ), "original": side( original_id ), "purpose_line": line,
             "leak": { "plant": word_overlap( need, line ) if line is not None else None, "original": word_overlap( need, original_line ) if original_line is not None else None } }


def count( k, n ):
    """Ensures: returns { k, n, interval } with the Wilson interval of k in n."""
    return { "k": k, "n": n, "interval": wilson( k, n ) }


def figures( rows, undrafted_count ):
    """
    Score one population of drafted pairs.

    Requires:
        - rows are pair_row results; undrafted_count is how many pairs of this population never drafted

    Ensures:
        - retrieval is plants retrieved of drafted, judge is plants accepted of retrieved, end_to_end is plants accepted of drafted
        - itt counts every undrafted pair as a miss: retrieved and accepted of drafted plus undrafted
        - originals_retrieved and originals_accepted are the same counts for the originals
        - pass_mark.a counts pairs where the original was retrieved and the plant not, b the reverse; passed when a - b is at most PASS_SLACK, on retrieval
        - pass_mark_end_to_end is the same count on acceptance, reported beside it and not gating
    """
    n     = len( rows )
    plant = lambda key: sum( 1 for r in rows if r[ "plant" ][ key ] )
    orig  = lambda key: sum( 1 for r in rows if r[ "original" ][ key ] )
    marks = lambda key: ( lambda a, b: { "a": a, "b": b, "slack": PASS_SLACK, "passed": a - b <= PASS_SLACK } )(
        sum( 1 for r in rows if r[ "original" ][ key ] and not r[ "plant" ][ key ] ), sum( 1 for r in rows if r[ "plant" ][ key ] and not r[ "original" ][ key ] ) )
    return { "drafted": n, "undrafted": undrafted_count, "retrieval": count( plant( "retrieved" ), n ), "judge": count( plant( "accepted" ), plant( "retrieved" ) ),
             "end_to_end": count( plant( "accepted" ), n ), "itt_retrieved": count( plant( "retrieved" ), n + undrafted_count ), "itt_end_to_end": count( plant( "accepted" ), n + undrafted_count ),
             "originals_retrieved": count( orig( "retrieved" ), n ), "originals_accepted": count( orig( "accepted" ), n ),
             "pass_mark": marks( "retrieved" ), "pass_mark_end_to_end": marks( "accepted" ) }


def scored( rows, undrafted, same_job ):
    """
    Assemble the control's scored report from its drafted rows and its undrafted pairs.

    Requires:
        - rows are pair_row results; undrafted are the stage's undrafted entries, each with pair ( the rewrite id ), seed, reason and history
        - same_job maps every rewrite id to its label

    Ensures:
        - returns { rows, primary, secondary, false_positives, originals_floor, stop }
        - primary is figures over the same-job pairs and secondary over the others, the negative control
        - rows holds a row for each undrafted pair too, with drafted False, its reason and its word history, so no pair is dropped from the count
        - false_positives counts the not-the-same-job plants the judge accepted
        - stop is True only when the originals retrieved of all drafted pairs fall under ORIGINAL_FLOOR, because then the needs broke and the plants did not; a plant miss never sets it
    """
    absent  = [ { "rewrite": u[ "pair" ], "same_job": same_job[ u[ "pair" ] ], "drafted": False, "reason": u[ "reason" ], "history": u[ "history" ] } for u in undrafted ]
    sides   = { key: [ r for r in rows if r[ "same_job" ] is want ] for key, want in ( ( "primary", True ), ( "secondary", False ) ) }
    lost    = { key: sum( 1 for a in absent if a[ "same_job" ] is want ) for key, want in ( ( "primary", True ), ( "secondary", False ) ) }
    kept    = sum( 1 for r in rows if r[ "original" ][ "retrieved" ] )
    rate    = kept / len( rows ) if rows else 0.0
    return { "rows": [ *rows, *absent ], "primary": figures( sides[ "primary" ], lost[ "primary" ] ), "secondary": figures( sides[ "secondary" ], lost[ "secondary" ] ),
             "false_positives": sum( 1 for r in sides[ "secondary" ] if r[ "plant" ][ "accepted" ] ), "originals_floor": { "floor": ORIGINAL_FLOOR, "rate": rate, "n": len( rows ) }, "stop": rate < ORIGINAL_FLOOR }
