#!/usr/bin/env python3
"""
Write one need sentence per sampled member with a bounded Claude Code call, tools off.

Each call runs in process through the Claude Agent SDK on the Max-plan login, with an empty tool
list, as the podcast generator does. It sees only the member's stripped text from need_input.
It never sees a twin, a group, the manifest or a Jev answer, and it makes no Jev call.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock
from claude_agent_sdk import query as sdk_query

import cosa.utils.util as cu
from cosa.agents.shared.sdk_error_result import error_result_text
from cosa.repo.doc_lint import model_transport as mt
from cosa.repo.symindex import need_input as ni

DEFAULT_MODEL    = "claude-sonnet-5-5"
MIN_WORDS        = 8
MAX_WORDS        = 40
MAX_ATTEMPTS     = 3
OPENERS          = { "function": "A function that ", "method": "A method that ", "class": "A class that " }
PLACEHOLDER      = re.compile( r"\b(NAME|CLASS|MODULE|ARG\d+|ATTR\d+)\b" )
SENTENCE_BREAK   = re.compile( r"[.?!]\s+\S" )
SYSTEM_PROMPT    = (
    "You describe what a piece of Python code does, for someone who will search a code base for "
    "something that does the same job. You never name or guess names. You answer with one sentence "
    "and nothing else."
)


@dataclass
class Reply:
    """
    One model reply.

    Requires:
        - cost_usd is the SDK's notional figure, covered by the Max plan
    """
    text          : str
    session_id    : str
    cost_usd      : float
    input_tokens  : int
    output_tokens : int


async def sdk_reply( prompt, system_prompt, model=DEFAULT_MODEL ):
    """
    Make one tools-off, short call and return its text and telemetry.

    Requires:
        - the Claude Code login is present on this host

    Ensures:
        - runs with the hermetic profile of the model transport: no hooks, no CLAUDE.md, no memory,
          no setting sources, no MCP servers, no skills
        - returns a Reply whose text joins every assistant text block
        - missing cost or usage in the result reads as zero

    Raises:
        - RuntimeError carrying the CLI's own text when the result is an error
        - RuntimeError when the stream ends with no result message
    """
    options = ClaudeAgentOptions(
        model           = model,
        system_prompt   = system_prompt,
        tools           = list( mt.NO_TOOLS ),
        permission_mode = mt.PERMISSION_MODE,
        max_turns       = 3,
        cwd             = cu.get_project_root(),
        setting_sources = list( mt.SETTING_SOURCES ),
        extra_args      = dict( mt.ISOLATION_ARGS ),
    )
    pieces  = []
    result  = None
    async for message in sdk_query( prompt=prompt, options=options ):
        if isinstance( message, AssistantMessage ):
            pieces += [ block.text for block in message.content if isinstance( block, TextBlock ) ]
        elif isinstance( message, ResultMessage ):
            if message.is_error: raise RuntimeError( error_result_text( message ) )
            result = message
    if result is None: raise RuntimeError( "the stream ended with no result message" )
    usage = result.usage or {}
    return Reply(
        text          = "".join( pieces ),
        session_id    = result.session_id,
        cost_usd      = result.total_cost_usd or 0.0,
        input_tokens  = usage.get( "input_tokens", 0 ),
        output_tokens = usage.get( "output_tokens", 0 ),
    )


def extract_sentence( reply_text ):
    """Ensures: returns the reply with quotes and ticks trimmed and whitespace collapsed."""
    return " ".join( reply_text.split() ).strip( " \"'`" )


def own_words_found( sentence, need ):
    """
    List the member's own names that appear in the sentence, outside its opening phrase.

    Requires:
        - need is the NeedInput the sentence was written from

    Ensures:
        - returns names from need.forbidden only, in that list's order
    """
    opener = OPENERS[ need.kind ]
    body   = sentence[ len( opener ): ] if sentence.startswith( opener ) else sentence
    return [ name for name in need.forbidden if re.search( r"(?<![A-Za-z0-9_])" + re.escape( name ) + r"(?![A-Za-z0-9_])", body ) ]


def check_form( sentence, need ):
    """
    Check the form rules this tool can see: opener, length, one sentence, no names.

    Requires:
        - need is the NeedInput the sentence was written from

    Ensures:
        - returns a sorted list of failure kinds, empty when the sentence passes
        - kinds: opener, word_count, one_sentence, placeholder, own_identifier
        - twin identifiers and copied word runs are not checked here; another script owns them
    """
    kinds = set()
    if own_words_found( sentence, need ): kinds.add( "own_identifier" )
    if not sentence.startswith( OPENERS[ need.kind ] ): kinds.add( "opener" )
    if not MIN_WORDS <= len( sentence.split() ) <= MAX_WORDS: kinds.add( "word_count" )
    if not sentence.endswith( ( ".", "?", "!" ) ) or SENTENCE_BREAK.search( sentence ): kinds.add( "one_sentence" )
    if PLACEHOLDER.search( sentence ): kinds.add( "placeholder" )
    return sorted( kinds )


def build_prompt( need, failures=None, own_words=None, last_words=None ):
    """
    Build the user prompt for one member.

    Ensures:
        - holds the stripped text and the form rules
        - when failures is given, ends with a note naming only the kinds of failure
        - own_words, when given, are named in that note; each must be one of the member's own names
        - last_words, when given with a word_count failure, states the length of the last sentence and
          tells a long one to aim ten words under the limit, a short one to say a little more

    Raises:
        - ValueError when an own word is not one of the member's own names
    """
    foreign = [ word for word in ( own_words or [] ) if word not in need.forbidden ]
    if foreign: raise ValueError( f"{foreign[ 0 ]} is not one of the member's own names" )
    prompt = (
        f"Below is the text of a Python {need.kind} with its names replaced by stand-ins "
        "(NAME, CLASS, MODULE, ARG1, ARG2, ATTR1 and so on). Do not use the stand-ins, and do not "
        "invent names.\n\n"
        f"Write one sentence that begins \"{OPENERS[ need.kind ]}\" and says what it does and what it returns, "
        f"in plain words, {MIN_WORDS} to {MAX_WORDS} words. Describe the job, not the steps, "
        "and do not copy phrases from its docstring. The plainest words for its inputs, such as "
        "text, data, value, item, name, path, result, function, class, method, type, may be names in the original code, so use a more "
        "specific everyday word for them. Use the opening phrase once and do not use the words "
        "function, class or method anywhere else.\n\n"
        f"{need.text}\n"
    )
    if failures: prompt += f"\nYour previous sentence was rejected. Failure kinds: {', '.join( failures )}. Write a different sentence."
    if failures and "word_count" in failures and last_words is not None:
        prompt += f" Your last sentence had {last_words} words; it must have {MIN_WORDS} to {MAX_WORDS}."
        if last_words > MAX_WORDS: prompt += f" Aim for {MAX_WORDS - 10} words or fewer by leaving out the least important detail."
        if last_words < MIN_WORDS: prompt += " Say a little more."
    if failures and "own_identifier" in failures:
        for word in own_words or []: prompt += f' In your last sentence the word "{word}" is a name in the original code; do not use it.'
        prompt += " A plain everyday word you used is also a name in the original code; choose a different word for it. Words that often double as names in code include limit, error, state, job, mode, store, seed, minutes, code, agent, result, budget; say those ideas in other words."
    return prompt


async def write_need( need, reply_fn, max_attempts=MAX_ATTEMPTS, failures=None ):
    """
    Ask for one sentence and retry on a form failure.

    Requires:
        - reply_fn is an async function of ( prompt, system_prompt ) returning a Reply

    Ensures:
        - returns a record with member_id, kind, ok, need, job_id, rewrites, attempts, cost_usd, tokens
        - need and job_id are None when no attempt passed
        - every attempt keeps its reply, failure kinds and telemetry
    """
    attempts  = []
    own_words = None
    last_words = None
    record    = { "member_id": need.member_id, "kind": need.kind, "ok": False, "need": None, "job_id": None, "rewrites": 0 }
    for _ in range( max_attempts ):
        try:
            reply = await reply_fn( build_prompt( need, failures, own_words, last_words ), SYSTEM_PROMPT )
        except RuntimeError as error:
            attempts.append( { "reply": str( error ), "failures": [ "call_error" ], "session_id": None, "cost_usd": 0.0,
                               "input_tokens": 0, "output_tokens": 0 } )
            failures, own_words, last_words = None, None, None
            continue
        sentence  = extract_sentence( reply.text )
        failures  = check_form( sentence, need )
        own_words = own_words_found( sentence, need )
        last_words = len( sentence.split() )
        attempts.append( { "reply": reply.text, "failures": failures, "session_id": reply.session_id, "cost_usd": reply.cost_usd,
                           "input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens } )
        if not failures:
            record.update( ok=True, need=sentence, job_id=reply.session_id )
            break
    record.update(
        attempts      = attempts,
        cost_usd      = sum( a[ "cost_usd" ] for a in attempts ),
        input_tokens  = sum( a[ "input_tokens" ] for a in attempts ),
        output_tokens = sum( a[ "output_tokens" ] for a in attempts ),
    )
    return record


async def run_members( member_ids, src_root, out_dir, reply_fn, redo=None, max_attempts=MAX_ATTEMPTS ):
    """
    Write a need for each member in order, one json file each, resuming over saved files.

    Requires:
        - member_ids holds no duplicate
        - redo maps a member id to the failure kinds that sent it back

    Ensures:
        - a member with a file and no redo entry is read back, not asked again
        - a redo entry replaces the file and counts one more rewrite
        - returns the records in member_ids order

    Raises:
        - ValueError on a duplicate member id
    """
    if len( set( member_ids ) ) != len( member_ids ): raise ValueError( "duplicate member id in the run list" )
    redo = redo or {}
    os.makedirs( out_dir, exist_ok=True )
    records = []
    for index, member_id in enumerate( member_ids, start=1 ):
        path  = os.path.join( out_dir, f"{index:03d}-{member_id}.json" )
        saved = None
        if os.path.exists( path ):
            with open( path, encoding="utf-8" ) as handle: saved = json.load( handle )
        if saved is not None and member_id not in redo:
            records.append( saved )
            continue
        record = await write_need( ni.build_input( member_id, src_root ), reply_fn, max_attempts, redo.get( member_id ) )
        if saved is not None: record[ "rewrites" ] = saved[ "rewrites" ] + 1
        with open( path, "w", encoding="utf-8" ) as handle: json.dump( record, handle, indent=2 )
        records.append( record )
    return records


def needs_document( run_dir, member_ids, sample_sha256 ):
    """
    Assemble the needs document the end-to-end driver reads.

    Requires:
        - run_dir holds the files run_members wrote for member_ids, in this order

    Ensures:
        - returns { format, sample_sha256, needs } with one entry per member in member_ids order
        - each entry carries member, need, kind, writer_job_id, attempts and rewrites

    Raises:
        - ValueError when a member has no file or no accepted need
    """
    needs = []
    for index, member_id in enumerate( member_ids, start=1 ):
        path = os.path.join( run_dir, f"{index:03d}-{member_id}.json" )
        if not os.path.exists( path ): raise ValueError( f"no accepted need for {member_id}: no file" )
        with open( path, encoding="utf-8" ) as handle: record = json.load( handle )
        if not record[ "ok" ]: raise ValueError( f"no accepted need for {member_id}: last run failed" )
        needs.append( { "member": member_id, "need": record[ "need" ], "kind": record[ "kind" ], "writer_job_id": record[ "job_id" ],
                        "attempts": len( record[ "attempts" ] ), "rewrites": record[ "rewrites" ] } )
    return { "format": "reuse-e2e-needs-1", "sample_sha256": sample_sha256, "needs": needs }


def sample_members( sample_path ):
    """
    Read the member ids from the frozen sample file, strata in file order.

    Ensures:
        - returns the list of member ids and nothing else from the file

    Raises:
        - ValueError when the file lists no members
    """
    with open( sample_path, encoding="utf-8" ) as handle: strata = json.load( handle )[ "strata" ]
    members = [ member for stratum in strata.values() for member in stratum[ "members" ] ]
    if not members: raise ValueError( f"no members in {sample_path}" )
    return members


def main( argv=None, reply_fn=None ):
    """
    Command line entry: write needs for the sample, or for its first --limit members.

    Ensures:
        - returns 0 when every member has an accepted need, else 1
        - reply_fn is injected by tests; the default is sdk_reply on the chosen model
    """
    parser = argparse.ArgumentParser( description="Write the need sentences for the end-to-end sample." )
    parser.add_argument( "--sample", required=True )
    parser.add_argument( "--src-root", default=None )
    parser.add_argument( "--out", required=True )
    parser.add_argument( "--limit", type=int, default=None )
    parser.add_argument( "--model", default=DEFAULT_MODEL )
    parser.add_argument( "--max-attempts", type=int, default=MAX_ATTEMPTS )
    parser.add_argument( "--assemble", default=None, help="write the needs document here and make no model call" )
    parser.add_argument( "--redo-file", default=None, help="json list of {member, check}; those members are rewritten" )
    args = parser.parse_args( argv )

    src_root = args.src_root or os.environ[ "LUPIN_ROOT" ] + "/src"
    members  = sample_members( args.sample )[ :args.limit ]
    if args.assemble:
        with open( args.sample, "rb" ) as handle: sample_sha = hashlib.sha256( handle.read() ).hexdigest()
        with open( args.assemble, "w", encoding="utf-8" ) as handle:
            json.dump( needs_document( args.out, members, sample_sha ), handle, indent=2 )
        return 0
    redo     = {}
    if args.redo_file:
        with open( args.redo_file, encoding="utf-8" ) as handle: rows = json.load( handle )
        for row in rows: redo.setdefault( row[ "member" ], [] ).append( row[ "check" ] )
    if reply_fn is None:
        async def reply_fn( prompt, system_prompt ): return await sdk_reply( prompt, system_prompt, args.model )
    records = asyncio.run( run_members( members, src_root, args.out, reply_fn, redo, args.max_attempts ) )
    failed  = [ r[ "member_id" ] for r in records if not r[ "ok" ] ]
    print( f"members={len( records )} ok={len( records ) - len( failed )} failed={len( failed )}" )
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - thin launcher, main() is tested
    sys.exit( main() )
