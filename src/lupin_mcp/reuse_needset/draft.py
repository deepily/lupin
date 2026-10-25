"""
Drafting: one sentence per seed, leak-checked, rewritten up to three times, else replaced.

Every model call goes through a ledger, so a stopped run resumes without repeating a call.
"""
import collections
import inspect

from cosa.repo.doc_lint import harness_runner, model_transport
from cosa.repo.symindex import need_input, need_writer
from lupin_mcp import reuse_need_check as nc
from lupin_mcp.reuse_needset import errors as er

DRAFTER_MODEL = "claude-fable-5-1"
MAX_TRIES     = 3
STAGE         = "draft"
NO_KEY        = "NO_KEY"


def parse_reply( text ):
    """
    Read the one sentence out of a drafter reply.

    Ensures:
        - returns the sentence, quotes and ticks trimmed and whitespace collapsed
        - returns None for an empty reply, a reply of more than one line or a reply with a code fence
    """
    lines = [ l for l in ( text or "" ).strip().splitlines() if l.strip() ]
    if len( lines ) != 1 or "```" in lines[ 0 ]: return None
    return need_writer.extract_sentence( lines[ 0 ] )


def prompt_version():
    """
    Name the prompt the drafter sends, so a change to it is a different version.

    Ensures:
        - returns model_transport.prompt_version over the system template, the prompt builder's source and the reply parser's source
    """
    return model_transport.prompt_version( "needset-draft", need_writer.SYSTEM_TEMPLATE, inspect.getsource( need_writer.build_prompt ), inspect.getsource( parse_reply ) )


def make_ledger( path, cli_path, server_label ):
    """
    Open the drafting ledger, bound to the Claude Code binary and the server label.

    Ensures:
        - the binding is the binary's reported version, or "bundled" for the SDK's own binary, then the label
        - a ledger written under another binary or label is refused by Ledger
    """
    return harness_runner.Ledger( path, binding=f"{model_transport.cli_version( cli_path ) or 'bundled'}|{server_label}" )


def drafter_call( model=DRAFTER_MODEL, query_fn=None ):
    """
    Build the function that sends one prompt to the drafter and returns its text.

    Ensures:
        - the returned function takes ( system_prompt, user_prompt ) and blocks until the reply arrives
        - it must not be called from a running event loop
    """
    import asyncio
    return lambda system, user: asyncio.run( model_transport.complete( model, system, user, query_fn=query_fn ) )


def stripped_input( seed_id, stripped ):
    """Return the NeedInput that need_writer.build_prompt reads, from a strip_member result."""
    return need_input.NeedInput( member_id=seed_id, kind=stripped[ "kind" ], text=stripped[ "text" ], forbidden=list( stripped[ "forbidden" ] ) )


def leak_check( sentence, seed, key_recs ):
    """
    Check a drafted sentence against the seed and every key symbol.

    Requires:
        - seed and each of key_recs are index records

    Ensures:
        - returns the failures of reuse_need_check.check_need: form, identifier, member_text_run and twin_text_run
        - the identifier tokens and the shared four-word runs of the seed and of every key symbol are checked
        - an empty list means the sentence may go to the second model
    """
    index  = { r[ "id" ]: r for r in [ seed, *key_recs ] }
    groups = { seed[ "id" ]: [ r[ "id" ] for r in key_recs ] }
    return nc.check_need( seed[ "id" ], sentence, index, groups )


def rewrite_request( seed_id, failures ):
    """
    Turn leak failures into what the writer may be told, which never includes the key.

    Ensures:
        - returns ( kinds, words ) where kinds are form, identifier or text_run, as the resend list names them, and words are bare lower-case words the sentence used
        - the failure details, which can name a key symbol, are dropped
    """
    sent        = nc.resend_list( { "rows": [ { "member": seed_id, "ok": False, "failures": failures } ] } )[ 0 ]
    redo, avoid = need_writer.redo_from_resend_list( [ sent ] )
    return redo[ seed_id ], [ w for w in avoid.get( seed_id, [] ) if need_writer.BARE_WORD.fullmatch( w ) ]


def ask_ledgered( ask, ledger, version, model_id, system, prompt, stripped_text, slot ):
    """Ask the drafter once, or read the ledger's answer to the same question."""
    key    = harness_runner.ledger_key( STAGE, { "old": stripped_text, "new": prompt }, version, model_id, slot )
    stored = ledger.get( key )
    if stored is not None: return stored
    reply = ask( system, prompt )
    ledger.put( key, reply )
    return reply


def draft_need( job, ask, ledger, model_id=DRAFTER_MODEL ):
    """
    Draft the sentence for one seed, rewriting on a failed check.

    Requires:
        - job holds seed (an index record), keys (index records), stripped (a strip.strip_member result) and write_lang
        - ask( system_prompt, user_prompt ) returns the reply text

    Ensures:
        - returns { ok, seed, key, need, tries, history, reason }
        - at most MAX_TRIES sentences are checked; an unreadable reply is asked again once with the same prompt
        - a rewrite request names the failure kinds and the seed's own offending words, never a key symbol or its text
        - ok is False with reason UNREADABLE_REPLY when both replies were unreadable, and with reason NEED_LEAKS_KEY after MAX_TRIES failed checks
        - history lists, per try, the failure kinds and the words, and holds no key text
    """
    seed, write_lang, stripped = job[ "seed" ], job[ "write_lang" ], stripped_input( job[ "seed" ][ "id" ], job[ "stripped" ] )
    version, system = prompt_version(), need_writer.system_prompt( job[ "write_lang" ] )
    failures, avoid, history = None, None, []
    record = { "ok": False, "seed": seed[ "id" ], "key": [ r[ "id" ] for r in job[ "keys" ] ], "need": None, "tries": 0, "history": history, "reason": er.NEED_LEAKS_KEY }
    for attempt in range( MAX_TRIES ):
        prompt   = need_writer.build_prompt( stripped, failures, None, None, avoid, write_lang )
        sentence = None
        for retry in range( 2 ):
            sentence = parse_reply( ask_ledgered( ask, ledger, version, model_id, system, prompt, stripped.text, f"{attempt}.{retry}" ) )
            if sentence is not None: break
        record[ "tries" ] = attempt + 1
        if sentence is None:
            history.append( { "try": attempt, "failures": [ er.UNREADABLE_REPLY ], "words": [] } )
            record[ "reason" ] = er.UNREADABLE_REPLY
            return record
        found = leak_check( sentence, seed, job[ "keys" ] )
        if not found:
            record.update( ok=True, need=sentence, reason=None )
            return record
        failures, avoid = rewrite_request( seed[ "id" ], found )
        history.append( { "try": attempt, "failures": failures, "words": avoid } )
    return record


def draft_cell( cell, wanted, order, make_job, ask, ledger, model_id=DRAFTER_MODEL ):
    """
    Draft one cell: walk the seeds in draw order, replacing each failed seed with the next.

    Requires:
        - order is the draw's primaries followed by its spares, for this cell; wanted is the cell's quota
        - make_job( seed_id ) returns a job for draft_need, or None when no key was found for the seed

    Ensures:
        - returns { cell, wanted, original, final, accepted, failed, replacements }
        - original is the first `wanted` ids of order, kept beside final, the seeds that were accepted
        - replacements maps each failure reason to the number of seeds replaced for it
        - a failed seed is listed in failed with its reason and its history

    Raises:
        - NeedsetError QUOTA_UNFILLABLE when the seeds run out before wanted needs are accepted
    """
    accepted, failed, replacements = [], [], collections.Counter()
    for seed_id in order:
        if len( accepted ) == wanted: break
        job = make_job( seed_id )
        if job is None:
            failed.append( { "seed": seed_id, "reason": NO_KEY, "history": [] } )
            replacements[ NO_KEY ] += 1
            continue
        record = draft_need( job, ask, ledger, model_id )
        if record[ "ok" ]:
            accepted.append( record )
        else:
            failed.append( { "seed": seed_id, "reason": record[ "reason" ], "history": record[ "history" ] } )
            replacements[ record[ "reason" ] ] += 1
    if len( accepted ) < wanted: raise er.NeedsetError( er.QUOTA_UNFILLABLE, f"{cell}: {len( accepted )} of {wanted} needs accepted from {len( order )} seeds" )
    return { "cell": cell, "wanted": wanted, "original": list( order[ :wanted ] ), "final": [ r[ "seed" ] for r in accepted ],
             "accepted": accepted, "failed": failed, "replacements": dict( replacements ) }


def replacement_report( cells ):
    """
    Summarise the replacements for the manifest, per cell and per reason.

    Ensures:
        - returns { cell: { total, by_reason, original, final } } for each result of draft_cell
        - the original seed list is kept beside the final one
    """
    return { c[ "cell" ]: { "total": sum( c[ "replacements" ].values() ), "by_reason": dict( c[ "replacements" ] ), "original": list( c[ "original" ] ), "final": list( c[ "final" ] ) }
             for c in cells }
