"""
The positive control's report for run -m, scored by the rules fixed before the run.

A pair is scored where it was lost. Retrieval asks if the plant is in the shortlist, the judge if it was rated relevant, and end to end both.
The plants are scored against their own originals on the same need, because the checker finds a known item about 7 times in 10.
The original stays in the pool and competes with the plant: one search per pair gives both places.
Pairs the human labels call a different job are a negative control, reported apart, and a plant found there is a false positive.
Nothing here makes a model call or reads a file except the label files and the answer key.
"""
import pathlib
import re

from cosa.repo.duplicate_check.proof import label_load, proof_run
from cosa.repo.symindex.candidates import rank_fusion as rf
from cosa.utils.file_hash import file_sha256
from lupin_mcp.reuse_e2e import wilson
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import judge_readings, loss_trace

NOT_SAME_JOB   = frozenset( ( "d-35e19468ee", "d-5270a48d23", "d-e4d0d1e147", "d-7a334b0576", "d-803557386f" ) )
LABEL_FILES    = ( "labels-rick.jsonl", "labels-reviewer-2.jsonl", "labels-jason.jsonl" )
KEY_FILE       = "answer-key.json"
LABEL_PINS     = { "labels-rick.jsonl": "e87e9ef367406fce4f921a720c7334eced80f9d4ed99f595ae3feae7a6e0f961", "labels-reviewer-2.jsonl": "947b20b8af234309ec6f53e753128f90eec89358d47669f0eb7c38f66a99c26b",
                   "labels-jason.jsonl": "2d7e4033a0263235f7c932323e3a3aca899d480ca18e6f32541d259ff7f3f5e2", "answer-key.json": "f17236f7cf913fcab41d5a6d9b0fab0c0a6dfc0e0caf9916d8e0d7bed22456e8" }
PASS_SLACK     = 2
ATTRIBUTION    = ( 27, 37 )


def same_job_labels( pairs, labels_dir, answer_key, expected_not_same=NOT_SAME_JOB, expected_shas="pinned" ):
    """
    Settle whether each pair is the same job.

    Requires:
        - pairs come from positive_control.load_pairs; labels_dir holds the three label files; answer_key is the run's answer-key path

    Ensures:
        - returns { same_job: { rewrite id: bool }, label_shas: { file name: sha256 }, answer_key_sha }
        - a pair both reviewers label alike takes that label, and a disputed one takes the third rater's, as label_load.resolved_labels settles it
        - the three label files and the answer key hash to expected_shas, unless that is None; the default "pinned" means LABEL_PINS, before anything is read from them
        - the pairs that are not the same job are exactly expected_not_same

    Raises:
        - NeedsetError CONTROL_LABELS_CHANGED naming the files whose hash differs, or the difference when the not-same set is not expected_not_same
        - ValueError from label_load when a label file is incomplete
    """
    first, second, third = ( f"{labels_dir}/{name}" for name in LABEL_FILES )
    shas      = { **{ name: file_sha256( f"{labels_dir}/{name}" ) for name in LABEL_FILES }, KEY_FILE: file_sha256( answer_key ) }
    wanted    = LABEL_PINS if expected_shas == "pinned" else expected_shas
    changed   = sorted( n for n in shas if wanted is not None and shas[ n ] != wanted[ n ] )
    if changed: raise er.NeedsetError( er.CONTROL_LABELS_CHANGED, f"the hash of {', '.join( changed )} is not the pinned one" )
    resolved  = label_load.resolved_labels( first, second, answer_key, third_path=third )
    same_job  = { p[ "rewrite" ][ "id" ]: bool( resolved[ proof_run.label_key( p[ "rewrite" ][ "id" ], p[ "original" ][ "id" ] ) ] ) for p in pairs }
    not_same  = frozenset( i for i, same in same_job.items() if not same )
    if not_same != expected_not_same:
        raise er.NeedsetError( er.CONTROL_LABELS_CHANGED, f"not the same job: {sorted( not_same )}; expected {sorted( expected_not_same )}" )
    return { "same_job": same_job, "label_shas": { name: shas[ name ] for name in LABEL_FILES }, "answer_key_sha": shas[ KEY_FILE ] }


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
        - when the check widened its shortlist the answer is the wide search's; the lists do not depend on the shortlist size, so the places agree

    Ensures:
        - returns { source name: place or None, ..., fused: place or None }
        - the merged list is the one the search fuses, read to the end: the same constants, no cut to the shortlist
    """
    lists = answer[ "lists" ]
    fused = rf.fuse( [ lists[ n ] for n in sorted( lists ) ], rf.FUSION_K, rf.FUSION_DEPTH, rf.FUSION_HEAD )
    return { **{ n: position( lists[ n ], ident ) for n in sorted( lists ) }, "fused": position( fused, ident ) }


def fusion_terms( answer, ident ):
    """
    Give what each source list added to an entry's fused score in one search.

    Requires:
        - answer is a search answer whose lists are whole, as ranks_of takes it

    Ensures:
        - returns { source name: term or None, ..., total }
        - a term is 1 / ( FUSION_K + place ), as rank_fusion.fuse adds it, for a place inside FUSION_DEPTH, the place counted in the list without repeated ids
        - a term is 0.0 for an entry present in a list beyond the depth, and None for an entry absent from the list
        - total is the sum of the terms rounded to SCORE_DIGITS places, the score fuse sorts on, so 0.0 for an entry no list scores
    """
    lists = answer[ "lists" ]
    terms = {}
    for n in sorted( lists ):
        place    = position( list( dict.fromkeys( lists[ n ] ) ), ident )                  # fuse counts a repeated id once, so the place is read in the list without repeats
        terms[ n ] = None if place is None else ( 1.0 / ( rf.FUSION_K + place ) if place <= rf.FUSION_DEPTH else 0.0 )
    return { **terms, "total": round( sum( t for t in terms.values() if t is not None ), rf.SCORE_DIGITS ) }


def reading( ident, receipt, answer ):
    """
    Read where one entry stood in one search.

    Requires:
        - receipt is a checker receipt and answer the planted stage's last answer for the same search

    Ensures:
        - returns { id, retrieved, ranks }; retrieved means in the ids sent to the judge, and ranks are ranks_of's
    """
    return { "id": ident, "retrieved": ident in set( loss_trace.asked_ids( receipt ) ), "ranks": ranks_of( answer, ident ) }


def pair_row( pair, label, need, live, line, original, bare, sweeps=None ):
    """
    Build the row of one drafted pair.

    Requires:
        - live and bare are ( receipt, answer ) pairs: the live check, and the same check over plants with no line
        - line is the plant's purpose line or None; original is { id, line }, id being its id in the index and line its stored line or None
        - the original is in the pool, because its id in the pair is not an index id and so nothing is left out

    Ensures:
        - returns { rewrite, lang, same_job, drafted, plant, plant_bare, original, purpose_line, leak }
        - plant and original are read from the one live search; accepted means retrieved and rated relevant by the judge
        - plant_bare is the same plant planted with no purpose line, read from the bare search
        - leak is the word overlap of the need with the plant's line and with the original's, None for a line that does not exist
        - sweeps is None, or the judge sweeps of the live check; then plant and original also carry fusion ( fusion_terms ) and judge ( judge_reading ), and without it the row is as before
    """
    rid                = pair[ "rewrite" ][ "id" ]
    receipt, answer    = live
    plant              = reading( rid, receipt, answer )
    plant[ "accepted" ] = plant[ "retrieved" ] and rid in { row[ "id" ] for row in receipt[ "shortlist" ] }
    other              = reading( original[ "id" ], receipt, answer )
    if sweeps is not None:
        for side in ( plant, other ): side.update( { "fusion": fusion_terms( answer, side[ "id" ] ), "judge": judge_readings.judge_reading( side[ "id" ], sweeps, side[ "retrieved" ] ) } )
    return { "rewrite": rid, "lang": pair[ "rewrite" ][ "lang" ], "same_job": label, "drafted": True, "plant": plant, "plant_bare": reading( rid, *bare ), "original": other,
             "purpose_line": line, "leak": { "plant": word_overlap( need, line ) if line is not None else None, "original": word_overlap( need, original[ "line" ] ) if original[ "line" ] is not None else None } }


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
        - retrieval_bare is the plants retrieved with no purpose line, the same count as retrieval
        - originals_retrieved is the originals retrieved of drafted, from the same search as the plant
        - pass_mark.a counts pairs where the original was retrieved and the plant not, b the reverse; passed when n is above 0 and a - b is at most PASS_SLACK
        - the original competes with the plants present, as in the replay of run -l
    """
    n     = len( rows )
    plant = lambda key: sum( 1 for r in rows if r[ "plant" ][ key ] )
    a     = sum( 1 for r in rows if r[ "original" ][ "retrieved" ] and not r[ "plant" ][ "retrieved" ] )
    b     = sum( 1 for r in rows if r[ "plant" ][ "retrieved" ] and not r[ "original" ][ "retrieved" ] )
    return { "drafted": n, "undrafted": undrafted_count, "retrieval": count( plant( "retrieved" ), n ), "judge": count( plant( "accepted" ), plant( "retrieved" ) ),
             "end_to_end": count( plant( "accepted" ), n ), "itt_retrieved": count( plant( "retrieved" ), n + undrafted_count ), "itt_end_to_end": count( plant( "accepted" ), n + undrafted_count ),
             "retrieval_bare": count( sum( 1 for r in rows if r[ "plant_bare" ][ "retrieved" ] ), n ), "originals_retrieved": count( sum( 1 for r in rows if r[ "original" ][ "retrieved" ] ), n ),
             "pass_mark": { "a": a, "b": b, "n": n, "slack": PASS_SLACK, "passed": n > 0 and a - b <= PASS_SLACK } }


def scored( rows, undrafted, same_job ):
    """
    Assemble the control's scored report from its drafted rows and its undrafted pairs.

    Requires:
        - rows are pair_row results; undrafted are the stage's undrafted entries, each with pair ( the rewrite id ), seed, reason and history
        - same_job maps every rewrite id to its label

    Ensures:
        - returns { rows, primary, secondary, false_positives, originals, attribution }
        - primary is figures over the same-job pairs and secondary over the others, the negative control
        - rows holds a row for each undrafted pair too, with drafted False, its reason and its word history, so no pair is dropped from the count
        - false_positives counts the not-the-same-job plants the judge accepted
        - originals is the originals retrieved of all drafted pairs, and attribution the attribution stage's 27 of 37, each with a Wilson interval and gating nothing
        - nothing in the report stops the run: a plant miss and a low originals rate are figures
    """
    absent  = [ { "rewrite": u[ "pair" ], "same_job": same_job[ u[ "pair" ] ], "drafted": False, "reason": u[ "reason" ], "history": u[ "history" ] } for u in undrafted ]
    sides   = { key: [ r for r in rows if r[ "same_job" ] is want ] for key, want in ( ( "primary", True ), ( "secondary", False ) ) }
    lost    = { key: sum( 1 for a in absent if a[ "same_job" ] is want ) for key, want in ( ( "primary", True ), ( "secondary", False ) ) }
    return { "rows": [ *rows, *absent ], "primary": figures( sides[ "primary" ], lost[ "primary" ] ), "secondary": figures( sides[ "secondary" ], lost[ "secondary" ] ),
             "false_positives": sum( 1 for r in sides[ "secondary" ] if r[ "plant" ][ "accepted" ] ), "originals": count( sum( 1 for r in rows if r[ "original" ][ "retrieved" ] ), len( rows ) ), "attribution": count( *ATTRIBUTION ) }
