"""
The tools-on agent step: read each shortlisted candidate and rule it the same job or not.

The agent runs under the isolation profile of the model transport and has one tool, Read.
So its rulings are not made under the operator's instructions, memory or hooks.
"""
import inspect
import json
import os
import re

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolUseBlock
from claude_agent_sdk import query as sdk_query

from cosa.agents.shared.sdk_error_result import error_result_text
from cosa.repo.doc_lint import model_transport as mt
from lupin_mcp.reuse_needset import errors as er

TOOLS        = [ "Read" ]
MAX_TURNS    = 40
SAME_JOB     = ( "DUPLICATE", "EXTEND" )
RULINGS      = SAME_JOB + ( "DISTINCT", )
RULING_LINE  = re.compile( r"^RULING (\S+) :: (" + "|".join( RULINGS ) + r")\b" )
SYSTEM       = (
    "You review whether code that is about to be written already exists. You are given a need and the "
    "candidates a search found. Read the source of each candidate with the Read tool, then rule on it. "
    "You change nothing."
)
INSTRUCTION  = (
    "Read the source of every candidate listed below. Then answer with one line per candidate and nothing else, in this exact form:\n"
    "RULING <candidate id> :: DUPLICATE | EXTEND | DISTINCT\n"
    "DUPLICATE means the candidate already does the whole job. EXTEND means it does most of the job and the rest can be added to it. "
    "DISTINCT means it does another job."
)


def build_prompt( need, result ):
    """
    Build the user prompt from the need sentence and the checker's shortlist.

    Requires:
        - need is the need sentence; result is a checker receipt or result holding a shortlist of rows with an id

    Ensures:
        - returns the instruction, the need and one JSON line per shortlisted candidate
        - each candidate line holds the row without its text, so the agent reads the source instead of a summary
        - the key, the seed and the drafter's verdict are never in the prompt
    """
    rows = [ json.dumps( { k: v for k, v in row.items() if k != "text" }, sort_keys=True ) for row in result[ "shortlist" ] ]
    return f"{INSTRUCTION}\n\nNeed: {need}\n\nCandidates:\n" + "\n".join( rows )


def rulings( reply ):
    """
    Read the rulings out of the agent's reply.

    Requires:
        - reply is the agent's final text

    Ensures:
        - returns { candidate id: ruling } from the lines of the form `RULING id :: ruling`
        - returns {} when no line has that form
        - a candidate ruled twice with two different rulings is left out of the answer, so it reads as unruled
    """
    seen = {}
    for line in ( reply or "" ).splitlines():
        m = RULING_LINE.match( line.strip() )
        if m: seen.setdefault( m.group( 1 ), set() ).add( m.group( 2 ) )
    return { i: next( iter( r ) ) for i, r in seen.items() if len( r ) == 1 }


def read_files( transcript ):
    """
    List the Read calls the agent made.

    Requires:
        - transcript is the list of messages the stream produced

    Ensures:
        - returns [ { path, offset, limit } ] in call order, one per Read tool call of an assistant message
        - offset and limit are None when the call gave none, which means the whole file
    """
    out = []
    for message in transcript:
        if not isinstance( message, AssistantMessage ): continue
        for block in message.content:
            if isinstance( block, ToolUseBlock ) and block.name == "Read":
                out.append( { "path": block.input[ "file_path" ], "offset": block.input.get( "offset" ), "limit": block.input.get( "limit" ) } )
    return out


def serialize( transcript ):
    """
    Turn the assistant messages into plain dicts a ledger can hold.

    Ensures:
        - returns one { type, ... } dict per text block and per tool call, in order
    """
    out = []
    for message in transcript:
        if not isinstance( message, AssistantMessage ): continue
        for block in message.content:
            if isinstance( block, TextBlock ): out.append( { "type": "text", "text": block.text } )
            elif isinstance( block, ToolUseBlock ): out.append( { "type": "tool_use", "name": block.name, "input": block.input } )
    return out


def reply_text( transcript ):
    """
    Return the text of the last assistant message that holds text.

    Ensures:
        - returns its text blocks joined, or an empty string when no message holds text
    """
    last = ""
    for message in transcript:
        if isinstance( message, AssistantMessage ):
            texts = [ b.text for b in message.content if isinstance( b, TextBlock ) ]
            if texts: last = "".join( texts )
    return last


def covers( read, root, file, line, end_line ):
    """
    Say whether one Read call shows a symbol's whole definition.

    Requires:
        - file is the symbol's path under root; line and end_line bound its definition

    Ensures:
        - true when the call names that file and either gives no range or a range that holds line through end_line
        - an offset starts at line 1; a limit counts lines from the offset
    """
    want = os.path.normpath( os.path.join( root, file ) )
    got  = os.path.normpath( os.path.join( root, read[ "path" ] ) )
    if want != got: return False
    first = read[ "offset" ] if read[ "offset" ] is not None else 1
    last = None if read[ "limit" ] is None else first + read[ "limit" ] - 1
    return first <= line and ( last is None or last >= end_line )


def probe_profile():
    """
    Return the text that names the probe's tools and turn limit.

    Ensures:
        - returns JSON that the prompt version hashes, so a change to either is a new version
    """
    return json.dumps( { "tools": TOOLS, "max_turns": MAX_TURNS, "cli_path": mt.CLI_PATH is not None }, sort_keys=True )


def prompt_version():
    """
    Name the prompt the probe sends, so a change to it is a different version.

    Ensures:
        - returns model_transport.prompt_version over the system text, the instruction, the sources of the prompt builder and the reply parser, and the probe profile
        - the transport's call profile is part of the hash, as it is for every other call
    """
    return mt.prompt_version( "needset-probe", SYSTEM, INSTRUCTION, inspect.getsource( build_prompt ), inspect.getsource( rulings ), probe_profile() )


def probe_options( root, model ):
    """
    Build the agent options of the probe.

    Requires:
        - root is the read-only tree of the need's source commit

    Ensures:
        - returns options with the Read tool only, the hermetic isolation arguments and no setting source
        - the working directory is root
    """
    return ClaudeAgentOptions( model=model, system_prompt=SYSTEM, tools=list( TOOLS ), permission_mode=mt.PERMISSION_MODE, max_turns=MAX_TURNS, cwd=root,
                               cli_path=mt.CLI_PATH, setting_sources=list( mt.SETTING_SOURCES ), extra_args=dict( mt.ISOLATION_ARGS ) )


async def _stream( prompt, options, query_fn ):
    """
    Run one agent stream.

    Ensures:
        - returns the messages in order

    Raises:
        - RuntimeError carrying the CLI's own text when the result is an error
        - RuntimeError when the stream ends with no result message
    """
    messages, done = [], False
    async for message in query_fn( prompt=prompt, options=options ):
        messages.append( message )
        if isinstance( message, ResultMessage ):
            if message.is_error: raise RuntimeError( error_result_text( message ) )
            done = True
    if not done: raise RuntimeError( "the stream ended with no result message" )
    return messages


async def run_probe( need, result, root, model, query_fn=sdk_query ):
    """
    Let the agent read the shortlisted candidates and rule on each.

    Requires:
        - need is the need sentence; result holds the checker's shortlist; root is a read-only tree

    Ensures:
        - returns { reply, rulings, reads, transcript } where reads is read_files of the stream
        - an unreadable reply is asked again once with the same prompt
        - the stream is the only thing run, so nothing is written

    Raises:
        - NeedsetError PROBE_UNREADABLE when neither reply holds a ruling
        - RuntimeError from the stream
    """
    prompt = build_prompt( need, result )
    for _ in range( 2 ):
        messages = await _stream( prompt, probe_options( root, model ), query_fn )
        text     = reply_text( messages )
        ruled    = rulings( text )
        if ruled: return { "reply": text, "rulings": ruled, "reads": read_files( messages ), "transcript": serialize( messages ) }
    raise er.NeedsetError( er.PROBE_UNREADABLE, f"no ruling in either reply for the need {need!r}" )
