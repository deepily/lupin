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

from cosa.repo.doc_lint import model_transport
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
DRAFTS_PER_PAIR = 2                                                              # the first draft and at most one targeted rewrite
HEADROOM_PERCENT = 5                                                             # budgets sit this far above the planned calls, for a split request or a repeated unreadable reply
REPORT_FILE   = "stage-c-report.json"
DRAFT_LEDGER  = "ledger-stage-c-draft.jsonl"
REJECTS_FILE  = "stage-c-rejected-drafts.json"
REDRAFT_FILE  = "stage-c-redraft.json"
REDRAFT_CALLS = "call-ledger-redraft.jsonl"                                      # its own count, so the judge run that follows starts from none
REDRAFT_STAGE = "stage_c_redraft"
EXTRA_TRIES   = 2                                                                # sentences tried beyond the drafter's own limit, for a pair that still has none
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
        if why: refused.append( { "pair": p[ "pair" ], "stratum": p[ "stratum" ], "label": p[ "label" ], "reasons": why } ); continue
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


def with_headroom( calls ):
    """Ensures: returns the planned calls plus HEADROOM_PERCENT of them, rounded up."""
    return calls + ( calls * HEADROOM_PERCENT + 99 ) // 100


def budgets_for( rows, draft_budget=None, post_budget=None, limit=None ):
    """
    Derive the call budgets from the pairs that will run, unless the caller names them.

    Requires:
        - each override is None or a whole number of calls

    Ensures:
        - returns { drafts_planned, drafts_budget, posts_planned, posts_budget, limit, headroom_percent, overridden, short }
        - drafts_planned is DRAFTS_PER_PAIR for each row and posts_planned is one post per row and repeat
        - a budget not overridden is its planned figure plus HEADROOM_PERCENT, rounded up; the limit is the two budgets together
        - overridden names the flags used, and short names each budget or limit below its planned figure
    """
    drafts, posts = DRAFTS_PER_PAIR * len( rows ), len( rows ) * len( REPEATS )
    d, q          = with_headroom( drafts ) if draft_budget is None else draft_budget, with_headroom( posts ) if post_budget is None else post_budget
    cap           = d + q if limit is None else limit
    given         = { "draft_budget": draft_budget, "post_budget": post_budget, "limit": limit }
    return { "drafts_planned": drafts, "drafts_budget": d, "posts_planned": posts, "posts_budget": q, "limit": cap, "headroom_percent": HEADROOM_PERCENT,
             "overridden": [ n for n, v in given.items() if v is not None ], "short": [ n for n, low in ( ( "draft_budget", d < drafts ), ( "post_budget", q < posts ), ( "limit", cap < drafts + posts ) ) if low ] }


def plan_of( rows, refused, sides, budgets ):
    """
    Describe the run without making a call.

    Ensures:
        - returns { pairs_total, pairs_judged, refused, by_stratum, by_label, ambiguous, calls, would_share, budgets, audit, shown }
        - calls holds drafts_min and drafts_max (one to two per judged pair), posts (one two-question post per pair and repeat) and posts_if_shared (the posts left when twin_pairs' later pairs are not posted again)
        - would_share lists each pair twin_pairs would fold into an earlier one, as { pair, with }; the live run folds by the drafted body, so this is the most it can fold
        - budgets is budgets_for's answer, so the planned and the budgeted figures print together
        - shown lists, for every judged pair and side, the id and the purpose line the judge text carries
        - refused is the full list of refused pairs with their reasons
    """
    posting, shared = twin_pairs( rows )
    shown = [ { "pair": r[ "pair" ], "side": s, "id": r[ f"side_{s}" ][ "record" ][ "id" ], "purpose_line": r[ f"side_{s}" ][ "record" ][ "purpose" ] } for r in rows for s in ( "a", "b" ) ]
    return { "pairs_total": len( rows ) + len( refused ), "pairs_judged": len( rows ), "refused": refused, "by_stratum": dict( collections.Counter( r[ "stratum" ] for r in rows ) ),
             "by_label": dict( collections.Counter( r[ "label" ] for r in rows ) ), "ambiguous": [ r[ "pair" ] for r in rows if r[ "ambiguous" ] ],
             "calls": { "drafts_min": len( rows ), "drafts_max": 2 * len( rows ), "posts": len( rows ) * len( REPEATS ), "posts_if_shared": len( posting ) * len( REPEATS ) },
             "would_share": [ { "pair": r[ "pair" ], "with": p } for p, rs in shared.items() for r in rs ], "budgets": budgets, "audit": audit_sides( sides ), "shown": shown }


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


def cache_only( system, user ):
    """
    Stand in for the drafter when a saved ledger must answer every question.

    Raises:
        - NeedsetError BAD_NEED, because an unanswered prompt would need a model call
    """
    raise er.NeedsetError( er.BAD_NEED, "the saved draft ledger has no answer for this prompt, so replaying it would need a model call" )


def draft_all( rows, strip_fn, ask, ledger, max_tries=draft.MAX_TRIES ):
    """
    Draft one need per pair.

    Requires:
        - ask( system_prompt, user_prompt ) returns the reply text; ledger is a drafting ledger

    Ensures:
        - returns ( needs, undrafted, rejected ): needs is { pair: sentence } for each pair whose draft passed
        - undrafted lists { pair, stratum, label, unsure, raters, reason } for the others
        - rejected lists every sentence a check refused, whether or not the pair was later accepted, as { pair, stratum, label, unsure, raters, try, sentence, failures, outcome }
        - outcome is accepted_later or undrafted
    """
    needs, undrafted, rejected = {}, [], []
    for row in rows:
        rec = draft.draft_need( draft_job( row, strip_fn ), ask, ledger, max_tries=max_tries )
        who = { k: row[ k ] for k in ( "pair", "stratum", "label", "unsure", "raters" ) }
        if rec[ "ok" ]: needs[ row[ "pair" ] ] = rec[ "need" ]
        else: undrafted.append( { **who, "reason": rec[ "reason" ] } )
        rejected += [ { **who, "try": r[ "try" ], "sentence": r[ "sentence" ], "failures": r[ "failures" ], "outcome": "accepted_later" if rec[ "ok" ] else "undrafted" } for r in rec[ "rejections" ] ]
    return needs, undrafted, rejected


def tries_of( args ):
    """Ensures: returns --max-tries, or the drafter's own limit when none was given."""
    return draft.MAX_TRIES if args.max_tries is None else args.max_tries


def save_rejects( run_dir, rejected ):
    """
    Write every rejected sentence beside the check that refused it.

    Ensures:
        - REJECTS_FILE in run_dir holds { count, rejected } as sorted-key JSON, replacing an earlier file
        - returns the path written
    """
    path = pathlib.Path( run_dir ) / REJECTS_FILE
    path.write_text( json.dumps( { "count": len( rejected ), "rejected": rejected }, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    return path


def parse_args( argv ):
    """
    Read the command line.

    Ensures:
        - the repo, run folder, answer key, packet, labels folder, symbols file, purpose file and source commit are required
        - live is false unless --live is given; a live run also needs --run-name, --from-run and --cli-path
        - the call limit and the two budgets are None unless named, and then budgets_for derives them from the planned calls
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    for name in ( "root", "run_dir", "answer_key", "packet", "labels_dir", "symbols", "purposes", "source_commit" ):
        ap.add_argument( "--" + name.replace( "_", "-" ), required=True )
    for name in ( "from_run", "run_name", "cli_path" ): ap.add_argument( "--" + name.replace( "_", "-" ), default=None )
    for name in ( "limit", "draft_budget", "post_budget" ): ap.add_argument( "--" + name.replace( "_", "-" ), type=int, default=None )
    ap.add_argument( "--ceiling", type=int, default=jp.CEILING )
    ap.add_argument( "--server", default="max-plan" )
    ap.add_argument( "--live", action="store_true" )
    ap.add_argument( "--max-tries", type=int, default=None, help="sentences the drafter may check per pair; default the drafter's own limit" )
    ap.add_argument( "--redraft", action="store_true", help="try again, up to --extra-tries more sentences, only for pairs the saved draft ledger left without a need; rates nothing" )
    ap.add_argument( "--extra-tries", type=int, default=EXTRA_TRIES )
    ap.add_argument( "--save-rejects", action="store_true", help="replay the saved draft ledger, make no model call, and write the rejected sentences" )
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
        - with --save-rejects replays the saved draft ledger without a model call and writes only REJECTS_FILE
        - with --redraft prints the pairs still undrafted and the calls planned and writes no file; with --live too it makes those calls and writes REJECTS_FILE and REDRAFT_FILE
        - with --live and a run name, drafts one need per pair, posts each pair three times under the call cap and the token ceiling, writes REPORT_FILE and closes the spend-ledger run however it ends

    Raises:
        - NeedsetError BAD_NEED on a live run without --run-name or --from-run; NO_CLI_PATH on a live run without --cli-path
    """
    args = parse_args( argv )
    deps = {} if deps is None else deps
    rows, refused, sides = collect_rows( args, deps )
    if args.save_rejects: return replay_rejects( args, rows, deps )
    if args.redraft: return redraft( args, rows, deps )
    plan = plan_of( rows, refused, sides, budgets_for( rows, args.draft_budget, args.post_budget, args.limit ) )
    if not args.live: return { "live": False, "mode": "stage_c", "plan": plan }
    if not args.run_name or not args.from_run: raise er.NeedsetError( er.BAD_NEED, "a live run needs --run-name, a spend-ledger run name that was not used before, and --from-run for its environment" )
    if args.cli_path is None: raise er.NeedsetError( er.NO_CLI_PATH, "the ledgers are bound to the Claude Code binary's version" )
    model_transport.configure( cli_path=args.cli_path )
    return live( args, rows, refused, plan, deps )


def in_source_tree( args, deps, work ):
    """
    Call work with the source tree at --source-commit and release the tree afterwards.

    Ensures:
        - the tree is made by source_at.ensure_worktree unless deps names source_root, as the live run does
        - a tree this call made is unlocked when work ends, by an error too; one the caller named is left alone
    """
    made = "source_root" not in deps
    root = source_at.ensure_worktree( args.root, args.source_commit ) if made else deps[ "source_root" ]( args )
    try:
        return work( root )
    finally:
        if made: source_at.unlock( args.root, root )


def replay_rejects( args, rows, deps ):
    """
    Read the saved draft ledger back and write the sentences its checks refused.

    Requires:
        - run_dir holds the ledger of an earlier run, and --cli-path names the binary it was bound to

    Ensures:
        - the stripped texts are read in the source tree at --source-commit, made and released as a live run does, so a prompt is the one the ledger holds
        - no model is called: a prompt the ledger cannot answer raises BAD_NEED
        - returns { live False, mode, drafted, undrafted, rejected, path } and writes REJECTS_FILE
    """
    if args.cli_path is None: raise er.NeedsetError( er.NO_CLI_PATH, "the ledger is bound to the Claude Code binary's version" )
    ledger_path = pathlib.Path( args.run_dir ) / DRAFT_LEDGER
    if not ledger_path.exists(): raise er.NeedsetError( er.BAD_NEED, f"{ledger_path} does not exist: there is no saved draft ledger to replay" )
    needs, undrafted, rejected = in_source_tree( args, deps, lambda root: draft_all( rows, lambda rec: strip.strip_member( rec, root ), cache_only, draft.make_ledger( str( ledger_path ), args.cli_path, args.server ), tries_of( args ) ) )
    path = save_rejects( args.run_dir, rejected )
    return { "live": False, "mode": "stage_c_save_rejects", "drafted": len( needs ), "undrafted": undrafted, "rejected": len( rejected ), "path": str( path ) }


def redraft_plan( count, extra ):
    """
    Describe the extra drafting without making a call.

    Ensures:
        - returns { undrafted, extra_tries, calls_planned, calls_budget }
        - calls_planned is one call per extra sentence and pair; the budget adds HEADROOM_PERCENT for a reply asked again
    """
    planned = count * extra
    return { "undrafted": count, "extra_tries": extra, "calls_planned": planned, "calls_budget": with_headroom( planned ) }


def redraft( args, rows, deps ):
    """
    Try again, for a few more sentences, on the pairs the saved ledger left without a need.

    Requires:
        - run_dir holds the ledger of an earlier run, and --cli-path names the binary it was bound to

    Ensures:
        - the stripped texts are read in the source tree at --source-commit, made and released as a live run does, so a prompt is the one the ledger holds
        - the pairs are found by replaying the ledger with no model call: those that drafted before are not touched
        - the replay uses --max-tries and each pair may then try --extra-tries more sentences, the first of which asks the drafter
        - without --live returns { live False, mode, plan, pairs } and writes nothing
        - with --live returns { live True, mode, plan, accepted, still_failing, calls, path }, writes REDRAFT_FILE and REJECTS_FILE, and counts its calls in REDRAFT_CALLS under its own budget
        - a pair still failing stays without a need, and no rating is read or posted
    """
    if args.cli_path is None: raise er.NeedsetError( er.NO_CLI_PATH, "the ledger is bound to the Claude Code binary's version" )
    ledger_path = pathlib.Path( args.run_dir ) / DRAFT_LEDGER
    if not ledger_path.exists(): raise er.NeedsetError( er.BAD_NEED, f"{ledger_path} does not exist: there is no saved draft ledger to redraft from" )
    return in_source_tree( args, deps, lambda root: redraft_in( args, rows, deps, root, ledger_path ) )


def redraft_in( args, rows, deps, root, ledger_path ):
    """Ensures: does redraft's work with the stripped texts read in root, and returns its answer."""
    strip_fn = lambda rec: strip.strip_member( rec, root )
    ledger = draft.make_ledger( str( ledger_path ), args.cli_path, args.server )
    _needs, undrafted, rejected = draft_all( rows, strip_fn, cache_only, ledger, tries_of( args ) )
    pairs  = [ u[ "pair" ] for u in undrafted ]
    plan   = redraft_plan( len( pairs ), args.extra_tries )
    if not args.live: return { "live": False, "mode": "stage_c_redraft", "plan": plan, "pairs": pairs }
    model_transport.configure( cli_path=args.cli_path )
    again = [ r for r in rows if r[ "pair" ] in pairs ]
    cap   = call_cap.CallCap( f"{args.run_dir}/{REDRAFT_CALLS}", plan[ "calls_budget" ], { REDRAFT_STAGE: plan[ "calls_budget" ] } )
    ask   = deps[ "drafter" ] if "drafter" in deps else draft.drafter_call()
    with cap.installed():
        with call_cap.stage( REDRAFT_STAGE ):
            accepted, still, more = draft_all( again, strip_fn, ask, ledger, tries_of( args ) + args.extra_tries )
    save_rejects( args.run_dir, [ r for r in rejected if r[ "pair" ] not in pairs ] + more )
    path = pathlib.Path( args.run_dir ) / REDRAFT_FILE
    path.write_text( json.dumps( { "tries": tries_of( args ) + args.extra_tries, "accepted": accepted, "still_failing": still, "calls": cap.used(), "by_stage": cap.by_stage() }, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    return { "live": True, "mode": "stage_c_redraft", "plan": plan, "accepted": len( accepted ), "still_failing": len( still ), "calls": cap.used(), "path": str( path ) }


def live( args, rows, refused, plan, deps ):
    """
    Draft the needs, ask the judge and write the report.

    Ensures:
        - returns { live True, mode, plan, undrafted, report, closed_run, close_error }
        - REPORT_FILE holds the run_variant report plus undrafted and refused; the spend-ledger run is closed whatever happens
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
            report, undrafted = judge_all( args, rows, refused, plan[ "budgets" ], root, ctx, deps )
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


def share_bodies( rows, needs ):
    """
    Find the pairs whose posts would repeat an earlier pair's body.

    Requires:
        - needs is { pair: sentence } for the drafted pairs

    Ensures:
        - returns ( posting, shared ): posting lists the first drafted row of each distinct body, in order, and shared is { posting pair: [ later rows with that body ] }
        - the body is judge_probe's hash of the first repeat, so two pairs on one record pair in one order with one drafted need count as one
        - a pair without a draft is in neither
    """
    def body_of( row ):
        if row[ "pair" ] not in needs: return None
        return jp.body_hash( request_for( row, needs[ row[ "pair" ] ], REPEATS[ 0 ] ) )
    return group_rows( rows, body_of )


def twin_pairs( rows ):
    """
    Find the pairs that sit on one record pair in one order, which needs no model output.

    Ensures:
        - returns ( posting, shared ) as share_bodies does, grouping on side b's record id and side a's record id
        - the plan calls this before any draft; share_bodies makes the same grouping on the posted body once the needs exist, so two pairs here may still differ by their drafted need
    """
    return group_rows( rows, lambda row: ( row[ "side_b" ][ "record" ][ "id" ], row[ "side_a" ][ "record" ][ "id" ] ) )


def group_rows( rows, key_of ):
    """
    Group rows that have one key, keeping the first of each.

    Requires:
        - key_of( row ) returns a hashable key, or None for a row to leave out

    Ensures:
        - returns ( posting, shared ): posting lists the first row of each distinct key, in order, and shared is { posting pair: [ later rows with that key ] }
    """
    posting, shared, first = [], {}, {}
    for row in rows:
        key = key_of( row )
        if key is None: continue
        if key in first: shared[ first[ key ] ].append( row )
        else:
            first[ key ] = row[ "pair" ]
            shared[ row[ "pair" ] ] = []
            posting.append( row )
    return posting, shared


def fan_out( results, shared ):
    """
    Give each pair that shares a body the posted pair's results as its own.

    Ensures:
        - returns results followed by one copy per result and sharing pair, carrying that pair's id, stratum, label, unsure mark and rater count, and shared_with naming the pair that was posted
        - the copies are not new posts; they carry the same request hash and token counts as the original
    """
    copies = [ { **r, "pair": row[ "pair" ], "stratum": row[ "stratum" ], "label": row[ "label" ], "unsure": row[ "unsure" ], "raters": row[ "raters" ], "shared_with": r[ "pair" ] }
               for r in results for row in shared.get( r[ "pair" ], [ ] ) ]
    return results + copies


def judge_all( args, rows, refused, budgets, root, ctx, deps ):
    """
    Draft under its own stage budget, then post every pair and repeat.

    Ensures:
        - returns ( report, undrafted ); the report is run_variant's, written again with undrafted, refused and shared as REPORT_FILE
        - a pair whose body repeats an earlier pair's is not posted again: it takes that pair's results, marked shared_with, and is listed in shared
        - the posts are checked for distinct bodies before the first goes out
    """
    cap = call_cap.CallCap( f"{args.run_dir}/{first_thousand.CALLS_FILE}", budgets[ "limit" ], { DRAFT_STAGE: budgets[ "drafts_budget" ] } )
    ask = deps[ "drafter" ] if "drafter" in deps else draft.drafter_call()
    ledger = draft.make_ledger( f"{args.run_dir}/{DRAFT_LEDGER}", args.cli_path, args.server )
    with cap.installed():
        with call_cap.stage( DRAFT_STAGE ):
            needs, undrafted, rejected = draft_all( rows, lambda rec: strip.strip_member( rec, root ), ask, ledger, tries_of( args ) )
    save_rejects( args.run_dir, rejected )
    posting, shared = share_bodies( rows, needs )
    requests = [ request_for( r, needs[ r[ "pair" ] ], n ) for r in posting for n in REPEATS ]
    jp.distinct_bodies( requests )
    send   = deps[ "ask" ] if "ask" in deps else ( lambda request: ask_pair( ctx.transport, request, ctx.transport.budget ) )
    report = jp.run_variant( args.run_dir, requests, send, budgets[ "limit" ], budgets[ "posts_budget" ] )
    report = { **report, "results": fan_out( report[ "results" ], shared ) }
    pathlib.Path( f"{args.run_dir}/{REPORT_FILE}" ).write_text( json.dumps( { **report, "undrafted": undrafted, "refused": refused, "shared": [ { "pair": r[ "pair" ], "with": p } for p, rs in shared.items() for r in rs ] }, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    return report, undrafted


def exit_status( result ):
    """
    Say what the process should exit with for the result main returned.

    Requires:
        - result is what main returned: a plan, a judge run, or the answer of --save-rejects or --redraft

    Ensures:
        - a save-rejects or redraft result exits 0, since it holds no judge report and no run to close
        - any other result is expansion_run.exit_status's answer
    """
    if result[ "mode" ] in ( "stage_c_save_rejects", "stage_c_redraft" ): return 0
    return expansion_run.exit_status( result )


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
