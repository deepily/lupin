"""
The judge alone on the real labelled pairs of the first-thousand trial.

Each pair of the 25 Oct answer key has two sides, a and b, held only as source text. A side is found again by matching its text to an index record at the key's source commit.
A pair is refused and named, never judged, when a side matches no record or loses its record to the screen. The same goes for a side without a purpose line.

For each pair that stays, the existing drafter writes one need from side a, with its copy and leak checks run against side b too.
The judge then reads side b and side a, each as the lookup would prepare it, three times, each with its own run-index token.

Without --live this only prints the plan and contacts no model.
"""
import argparse
import collections
import json
import pathlib
import subprocess
import textwrap

from cosa.repo.duplicate_check.proof import label_load, proof_run
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import pair_labels as pl
from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.candidates import search as sx_search
from lupin_mcp import reuse_need_check as nc
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import call_cap, control_report, draft, expansion_run, first_thousand, forced_judge, source_at, strip
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import judge_probe as jp

STAGE_NAME    = "stage_c"
DRAFT_STAGE   = "stage_c_draft"
STRATA        = ( "flag", "monolith:structural", "monolith:neighbour" )
SAME_JOB      = forced_judge.SAME_JOB
NOT_SAME      = forced_judge.NOT_SAME
REPEATS       = jp.REPEATS
DRAFT_BUDGET  = 180                                                               # 86 pairs, one draft and at most one rewrite each
POST_BUDGET   = 270                                                               # 86 pairs x 3 repeats = 258 posts, with room for a split request
REPORT_FILE   = "stage-c-report.json"
DRAFT_LEDGER  = "ledger-stage-c-draft.jsonl"
UNMATCHED     = "unmatched"
DROPPED       = "dropped_by_screen"
NO_PURPOSE    = "no_purpose_line"
SAME_RECORD   = "same_record"


def norm_text( text ):
    """
    Put a definition's source text in a form two copies of it share.

    Ensures:
        - returns the text dedented, with trailing whitespace cut from every line and blank lines trimmed from both ends
    """
    return "\n".join( line.rstrip() for line in textwrap.dedent( text ).strip( "\n" ).splitlines() )


def text_index( records, source_lines ):
    """
    Map each index record's source text to the ids of the records that hold it.

    Requires:
        - records are index records with file, line, end_line and id
        - source_lines( file ) returns the file's lines at the key's source commit

    Ensures:
        - returns { normalised text: [ ids in record order ] }; a record without a line range is not indexed
        - a text with more than one id is ambiguous, and the caller sees that from the list
    """
    out = {}
    for r in records:
        if not ( r[ "line" ] and r[ "end_line" ] ): continue
        lines = source_lines( r[ "file" ] )
        out.setdefault( norm_text( "\n".join( lines[ r[ "line" ] - 1 : r[ "end_line" ] ] ) ), [] ).append( r[ "id" ] )
    return out


def git_source_lines( repo, commit ):
    """
    Build the function that reads a file's lines as they stood at a commit.

    Ensures:
        - returns source_lines( file ), which asks git once per file and keeps the answer
        - a file git cannot show gives no lines, so every record in it is simply unmatched
    """
    cache = {}

    def source_lines( file ):
        """Ensures: returns the file's lines at the commit, or [] when git cannot show it."""
        if file not in cache:
            run         = subprocess.run( [ "git", "-C", str( repo ), "show", f"{commit}:{file}" ], capture_output=True, text=True )
            cache[ file ] = run.stdout.splitlines() if run.returncode == 0 else []
        return cache[ file ]

    return source_lines


def check_pins( labels_dir, answer_key, expected_shas="pinned" ):
    """
    Check the label files and the answer key against their pinned hashes.

    Requires:
        - expected_shas is "pinned" for control_report.LABEL_PINS, a { file name: sha256 } mapping, or None to skip

    Raises:
        - NeedsetError CONTROL_LABELS_CHANGED naming each file whose hash differs
    """
    wanted = control_report.LABEL_PINS if expected_shas == "pinned" else expected_shas
    if wanted is None: return
    paths   = { **{ n: f"{labels_dir}/{n}" for n in control_report.LABEL_FILES }, control_report.KEY_FILE: answer_key }
    changed = sorted( n for n, p in paths.items() if control_report.file_sha( p ) != wanted[ n ] )
    if changed: raise er.NeedsetError( er.CONTROL_LABELS_CHANGED, f"the hash of {', '.join( changed )} is not the pinned one" )


def read_pairs( answer_key, packet, labels_dir, expected_shas="pinned" ):
    """
    Read every labelled pair of the three strata, with its label, raters and side texts.

    Requires:
        - packet is the packet file whose payloads hold the side texts a and b of each item

    Ensures:
        - returns pairs in key order, each { pair, stratum, label, unsure, raters, a_id, b_id, a_text, b_text }
        - label is SAME_JOB or NOT_SAME as label_load.resolved_labels settles it; unsure is True when any rater marked the pair unsure
        - raters is 3 when the third rater labelled the pair, else 2
        - a_id and b_id are the key's definition ids, which stay unmatched to records until split_pairs

    Raises:
        - NeedsetError CONTROL_LABELS_CHANGED from check_pins
    """
    check_pins( labels_dir, answer_key, expected_shas )
    names    = control_report.LABEL_FILES
    resolved = label_load.resolved_labels( f"{labels_dir}/{names[ 0 ]}", f"{labels_dir}/{names[ 1 ]}", answer_key, third_path=f"{labels_dir}/{names[ 2 ]}" )
    raw      = [ { l[ "item_id" ]: l for l in pk.read_labels( f"{labels_dir}/{n}" ) } for n in names ]
    items    = json.loads( pathlib.Path( answer_key ).read_text( encoding="utf-8" ) )[ "items" ]
    payloads = { r[ "item_id" ]: r[ "payload" ] for r in ( json.loads( l ) for l in pathlib.Path( packet ).read_text( encoding="utf-8" ).splitlines() ) }
    out      = []
    for item_id, v in items.items():
        if v[ "stratum" ] not in STRATA: continue
        same = resolved[ proof_run.label_key( v[ "a" ], v[ "b" ] ) ]
        out.append( { "pair": item_id, "stratum": v[ "stratum" ], "label": SAME_JOB if same else NOT_SAME, "unsure": any( item_id in r and pl.is_unsure( r[ item_id ] ) for r in raw ),
                      "raters": 3 if item_id in raw[ 2 ] else 2, "a_id": v[ "a" ], "b_id": v[ "b" ],
                      "a_text": payloads[ item_id ][ "a" ], "b_text": payloads[ item_id ][ "b" ] } )
    return out


def prepare_side( rec, purposes ):
    """
    Prepare one record the way the lookup shows it to the judge.

    Requires:
        - rec is an index record with a pin; purposes is { pin: purpose line }

    Ensures:
        - returns { record, text, has_doc, has_purpose, reason }
        - the record gets its stored purpose line and goes through reuse_tools.sendable_report, as the lookup does, and text is reuse_tools.entry_text of the result
        - reason is dropped_by_screen when the screen drops the record, else no_purpose_line when none is stored, else None; a record with a reason has no text
    """
    kept, _ = rt.sendable_report( sx_build.attach_purposes( [ rec ], purposes ) )
    if not kept: return { "record": None, "text": None, "has_doc": bool( rec[ "doc" ] ), "has_purpose": rec[ "pin" ] in purposes, "reason": DROPPED }
    side    = kept[ 0 ]
    purpose = "purpose" in side and bool( side[ "purpose" ] )
    return { "record": side, "text": rt.entry_text( side ) if purpose else None, "has_doc": bool( side[ "doc" ] ), "has_purpose": purpose, "reason": None if purpose else NO_PURPOSE }


def split_pairs( pairs, index, by_id, purposes ):
    """
    Split the pairs into those the judge can read and those refused, with the reason.

    Requires:
        - index is text_index's map; by_id maps an index id to its record; purposes is { pin: purpose line }

    Ensures:
        - returns ( rows, refused, sides ): a row holds the pair's fields, need_seed (side a's record), side_a and side_b (prepare_side results) and ambiguous (True when a side's text has more than one id)
        - a pair is refused, with every reason listed, when a side matches no record, the screen drops it, it has no purpose line, or both sides are one record
        - sides lists one { pair, stratum, side, id, matched, has_doc, has_purpose, ambiguous, reason } for every side of every pair, refused ones included
    """
    rows, refused, sides = [], [], []
    for p in pairs:
        found, why, ambiguous = {}, [], False
        for s in ( "a", "b" ):
            ids = index[ norm_text( p[ f"{s}_text" ] ) ] if norm_text( p[ f"{s}_text" ] ) in index else []
            if not ids:
                why.append( f"side {s} text matches no index record" )
                sides.append( { "pair": p[ "pair" ], "stratum": p[ "stratum" ], "side": s, "id": None, "matched": False, "has_doc": None, "has_purpose": None, "ambiguous": False, "reason": UNMATCHED } )
                continue
            prepared = prepare_side( by_id[ ids[ 0 ] ], purposes )
            ambiguous = ambiguous or len( ids ) > 1
            found[ s ] = ( ids[ 0 ], prepared )
            sides.append( { "pair": p[ "pair" ], "stratum": p[ "stratum" ], "side": s, "id": ids[ 0 ], "matched": True, "has_doc": prepared[ "has_doc" ], "has_purpose": prepared[ "has_purpose" ],
                            "ambiguous": len( ids ) > 1, "reason": prepared[ "reason" ] } )
            if prepared[ "reason" ] is not None: why.append( f"side {s} {prepared[ 'reason' ]}: {ids[ 0 ]}" )
        if len( found ) == 2 and found[ "a" ][ 0 ] == found[ "b" ][ 0 ]: why.append( f"{SAME_RECORD}: both sides are {found[ 'a' ][ 0 ]}" )
        if why: refused.append( { "pair": p[ "pair" ], "stratum": p[ "stratum" ], "reasons": why } ); continue
        rows.append( { **{ k: p[ k ] for k in ( "pair", "stratum", "label", "unsure", "raters" ) }, "need_seed": by_id[ found[ "a" ][ 0 ] ], "side_a": found[ "a" ][ 1 ], "side_b": found[ "b" ][ 1 ], "ambiguous": ambiguous } )
    return rows, refused, sides


def audit_sides( sides ):
    """
    Count what became of the sides and name every one that did not reach the judge in full.

    Ensures:
        - returns { sides, matched, with_docstring, with_purpose_line, named }
        - named lists every side that is unmatched, dropped, without a purpose line or without a docstring, with the reasons in plain words
    """
    named = []
    for s in sides:
        why = [ "no index record" ] if not s[ "matched" ] else []
        if s[ "matched" ] and s[ "reason" ] == DROPPED: why.append( "dropped by the screen" )
        if s[ "matched" ] and not s[ "has_purpose" ]: why.append( "no purpose line" )
        if s[ "matched" ] and not s[ "has_doc" ]: why.append( "no docstring" )
        if why: named.append( { "pair": s[ "pair" ], "side": s[ "side" ], "id": s[ "id" ], "why": why } )
    return { "sides": len( sides ), "matched": sum( s[ "matched" ] for s in sides ), "with_docstring": sum( bool( s[ "has_doc" ] ) for s in sides ),
             "with_purpose_line": sum( bool( s[ "has_purpose" ] ) for s in sides ), "named": named }


def plan_of( rows, refused, sides, budget=POST_BUDGET ):
    """
    Describe the run without making a call.

    Ensures:
        - returns { pairs_total, pairs_judged, refused, by_stratum, by_label, ambiguous, calls, audit, shown }
        - calls holds drafts_min and drafts_max (one to two per judged pair) and posts (one two-question post per pair and repeat)
        - shown lists, for every judged pair and side, the id and the purpose line the judge text carries
        - refused is the full list of refused pairs with their reasons
    """
    shown = [ { "pair": r[ "pair" ], "side": s, "id": r[ f"side_{s}" ][ "record" ][ "id" ], "purpose_line": r[ f"side_{s}" ][ "record" ][ "purpose" ] } for r in rows for s in ( "a", "b" ) ]
    return { "pairs_total": len( rows ) + len( refused ), "pairs_judged": len( rows ), "refused": refused, "by_stratum": dict( collections.Counter( r[ "stratum" ] for r in rows ) ),
             "by_label": dict( collections.Counter( r[ "label" ] for r in rows ) ), "ambiguous": [ r[ "pair" ] for r in rows if r[ "ambiguous" ] ],
             "calls": { "drafts_min": len( rows ), "drafts_max": 2 * len( rows ), "posts": len( rows ) * len( REPEATS ), "post_budget": budget }, "audit": audit_sides( sides ), "shown": shown }


def cue_of( need, side_b ):
    """Ensures: returns True when the need shares a name piece with side b's record."""
    return bool( nc.need_words( need ).keys() & nc.name_pieces( side_b[ "record" ] ) )


def draft_job( row, strip_fn ):
    """
    Build the job the drafter takes for one pair.

    Requires:
        - strip_fn( record ) returns { kind, text, forbidden } for the record

    Ensures:
        - the seed is side a's record and the one key is side b's, so the copy and leak checks run against both
        - the sentence is written in the seed's language
    """
    seed = row[ "need_seed" ]
    return { "seed": seed, "keys": [ row[ "side_b" ][ "record" ] ], "stripped": strip_fn( seed ), "write_lang": seed[ "lang" ], "meta": { "stage_c": row[ "pair" ] } }


def request_for( row, need, repeat ):
    """
    Build the request for one pair and repeat.

    Ensures:
        - returns a judge_probe request whose entries are side b, then side a, under the production template with the repeat's run-index token
        - it carries the pair's stratum, unsure mark, rater count and cue, which ask_pair copies into the result
    """
    return { "pair": row[ "pair" ], "label": row[ "label" ], "arm": STAGE_NAME, "repeat": repeat, "need": need, "entries": [ row[ "side_b" ][ "record" ], row[ "side_a" ][ "record" ] ],
             "template": jp.repeat_template( rt.PROMPT_TEMPLATE, repeat ), "stratum": row[ "stratum" ], "unsure": row[ "unsure" ], "raters": row[ "raters" ], "cue": cue_of( need, row[ "side_b" ] ) }


def ask_pair( transport, request, budget=None, send=rp.send_pack ):
    """
    Post one request and read both sides' ratings.

    Ensures:
        - returns judge_probe.ask_request's result, with side_b (the plant slot) and side_a (the original slot) beside the pair's stratum, unsure, raters and cue
        - the cache is never consulted
    """
    got = jp.ask_request( transport, request, budget, send )
    return { **got, "stratum": request[ "stratum" ], "unsure": request[ "unsure" ], "raters": request[ "raters" ], "cue": request[ "cue" ], "side_b": got[ "plant" ], "side_a": got[ "original" ] }


def draft_all( rows, strip_fn, ask, ledger ):
    """
    Draft one need per pair.

    Requires:
        - ask( system_prompt, user_prompt ) returns the reply text; ledger is a drafting ledger

    Ensures:
        - returns ( needs, undrafted ): needs is { pair: sentence } for each pair whose draft passed; undrafted lists { pair, stratum, label, unsure, raters, reason } for the others
    """
    needs, undrafted = {}, []
    for row in rows:
        rec = draft.draft_need( draft_job( row, strip_fn ), ask, ledger )
        if rec[ "ok" ]: needs[ row[ "pair" ] ] = rec[ "need" ]
        else: undrafted.append( { **{ k: row[ k ] for k in ( "pair", "stratum", "label", "unsure", "raters" ) }, "reason": rec[ "reason" ] } )
    return needs, undrafted


def parse_args( argv ):
    """
    Read the command line.

    Ensures:
        - the repo, run folder, answer key, packet, labels folder, symbols file, purpose file and source commit are required
        - live is false unless --live is given; a live run also needs --run-name, --from-run and --cli-path
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    for name in ( "root", "run_dir", "answer_key", "packet", "labels_dir", "symbols", "purposes", "source_commit" ):
        ap.add_argument( "--" + name.replace( "_", "-" ), required=True )
    for name in ( "from_run", "run_name", "cli_path" ): ap.add_argument( "--" + name.replace( "_", "-" ), default=None )
    ap.add_argument( "--limit", type=int, default=DRAFT_BUDGET + POST_BUDGET )
    ap.add_argument( "--draft-budget", type=int, default=DRAFT_BUDGET )
    ap.add_argument( "--post-budget", type=int, default=POST_BUDGET )
    ap.add_argument( "--ceiling", type=int, default=jp.CEILING )
    ap.add_argument( "--server", default="max-plan" )
    ap.add_argument( "--live", action="store_true" )
    return ap.parse_args( argv )


def collect_rows( args, deps ):
    """
    Read the inputs and split the pairs.

    Ensures:
        - returns ( rows, refused, sides ) from split_pairs; nothing is written and no model is touched
    """
    recs = [ json.loads( l ) for l in pathlib.Path( args.symbols ).read_text( encoding="utf-8" ).splitlines() ]
    pairs = read_pairs( args.answer_key, args.packet, args.labels_dir, deps[ "expected_shas" ] if "expected_shas" in deps else "pinned" )
    lines = deps[ "source_lines" ] if "source_lines" in deps else git_source_lines( args.root, args.source_commit )
    return split_pairs( pairs, text_index( recs, lines ), { r[ "id" ]: r for r in recs }, sx_search.read_purposes( args.purposes ) )


def main( argv=None, deps=None ):
    """
    Plan the run from files; with --live draft the needs and ask the judge.

    Requires:
        - deps is None for the real parts, or a mapping that replaces any of: source_lines, expected_shas, source_root, context, close_run, ask, drafter

    Ensures:
        - without --live returns { live False, mode, plan } and contacts nothing: no model, no search, no spend ledger, no file written
        - with --live and a run name, drafts one need per pair, posts each pair three times under the call cap and the token ceiling, writes REPORT_FILE and closes the spend-ledger run however it ends

    Raises:
        - NeedsetError BAD_NEED on a live run without --run-name or --from-run; NO_CLI_PATH on a live run without --cli-path
    """
    args = parse_args( argv )
    deps = {} if deps is None else deps
    rows, refused, sides = collect_rows( args, deps )
    plan = plan_of( rows, refused, sides, args.post_budget )
    if not args.live: return { "live": False, "mode": "stage_c", "plan": plan }
    if not args.run_name or not args.from_run: raise er.NeedsetError( er.BAD_NEED, "a live run needs --run-name, a spend-ledger run name that was not used before, and --from-run for its environment" )
    if args.cli_path is None: raise er.NeedsetError( er.NO_CLI_PATH, "the ledgers are bound to the Claude Code binary's version" )
    return live( args, rows, plan, deps )


def live( args, rows, plan, deps ):
    """
    Draft the needs, ask the judge and write the report.

    Ensures:
        - returns { live True, mode, plan, undrafted, report, closed_run, close_error }
        - REPORT_FILE holds the run_variant report plus undrafted; the spend-ledger run is closed whatever happens
    """
    import os
    os.environ.update( { **expansion_run.read_env_file( f"{args.from_run}/run-env.sh" ), rt.RUN_NAME_VARIABLE: args.run_name, rt.CEILING_VARIABLE: str( args.ceiling ) } )
    pathlib.Path( args.run_dir ).mkdir( parents=True, exist_ok=True )
    made, root = "source_root" not in deps, None
    root       = source_at.ensure_worktree( args.root, args.source_commit ) if made else deps[ "source_root" ]( args )
    try:
        ctx   = ( deps[ "context" ] if "context" in deps else rt.context_from_environment )( root )
        close = deps[ "close_run" ] if "close_run" in deps else rt.close_run
        try:
            rt.prepare( ctx )
            report, undrafted = judge_all( args, rows, root, ctx, deps )
        except BaseException:
            try: close( ctx )
            except Exception as error: print( f"close_run failed while another error was raised: {error!r}" )
            raise
        try:
            closed, close_error = close( ctx ), None
        except Exception as error:
            closed, close_error = None, repr( error )
        return { "live": True, "mode": "stage_c", "plan": plan, "undrafted": undrafted, "report": report, "closed_run": closed, "close_error": close_error }
    finally:
        if made: source_at.unlock( args.root, root )


def judge_all( args, rows, root, ctx, deps ):
    """
    Draft under its own stage budget, then post every pair and repeat.

    Ensures:
        - returns ( report, undrafted ); the report is run_variant's, written again with undrafted as REPORT_FILE
        - the posts are checked for distinct bodies before the first goes out
    """
    cap = call_cap.CallCap( f"{args.run_dir}/{first_thousand.CALLS_FILE}", args.limit, { DRAFT_STAGE: args.draft_budget } )
    ask = deps[ "drafter" ] if "drafter" in deps else draft.drafter_call()
    ledger = draft.make_ledger( f"{args.run_dir}/{DRAFT_LEDGER}", args.cli_path, args.server )
    with cap.installed():
        with call_cap.stage( DRAFT_STAGE ):
            needs, undrafted = draft_all( rows, lambda rec: strip.strip_member( rec, root ), ask, ledger )
    requests = [ request_for( r, needs[ r[ "pair" ] ], n ) for r in rows if r[ "pair" ] in needs for n in REPEATS ]
    jp.distinct_bodies( requests )
    send   = deps[ "ask" ] if "ask" in deps else ( lambda request: ask_pair( ctx.transport, request, ctx.transport.budget ) )
    report = jp.run_variant( args.run_dir, requests, send, args.limit, args.post_budget )
    pathlib.Path( f"{args.run_dir}/{REPORT_FILE}" ).write_text( json.dumps( { **report, "undrafted": undrafted }, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    return report, undrafted


exit_status = expansion_run.exit_status


def run_cli( argv=None, deps=None, out=print ):
    """
    Run main, print its result as JSON and return the exit status.

    Ensures:
        - the JSON goes to out before the status is returned; a plan exits 0
    """
    result = main( argv, deps )
    out( json.dumps( result, indent=4, sort_keys=True ) )
    return exit_status( result )


if __name__ == "__main__":  # pragma: no cover  reason: the command line entry; run_cli is tested with stand-ins
    import sys
    sys.exit( run_cli() )
