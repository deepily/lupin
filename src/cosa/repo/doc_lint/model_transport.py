"""
The one door the judge harness uses to reach a model (plan 1, section 5, billing path).

Bounded Claude Code: in-process sdk_query with tools=[], so the Max plan covers the cost and the
model can only emit text. The firewalled per-token SDK is never used here. Bounded CC has no
temperature setting, so callers get determinism from strict parsing and repeat-run checks.

Every call is hermetic. The Claude Code subprocess otherwise loads the operator's CLAUDE.md, MCP
servers, hooks and memory, so a measured model would answer under instructions that are not
in the prompt. The isolation profile below turns each of those off, and it is hashed into every
prompt version so a row made under another profile can never be replayed.
"""

import asyncio
import datetime
import fcntl
import hashlib
import json
import os
import secrets
import subprocess

from claude_agent_sdk import ClaudeAgentOptions, AssistantMessage, ResultMessage, TextBlock, query as sdk_query

import cosa.utils.util as cu

# With tools=[] there is nothing to permit. "plan" would put the model in plan mode and change
# what it writes (podcast_generator/api_client.py documents the failure), so it is "default".
PERMISSION_MODE = "default"
MAX_TURNS       = 1
NO_TOOLS        = []
TIMEOUT_SECONDS = 600


CLI_PATH = None
CWD      = None

# What the subprocess may not see. disableAllHooks drops the SessionStart and UserPromptSubmit
# hooks that inject context; claudeMdExcludes drops the global, project and local CLAUDE.md files;
# autoMemoryEnabled drops remembered notes.
ISOLATION_SETTINGS = {
    "disableAllHooks"   : True,
    "claudeMdExcludes"  : [ "**/CLAUDE.md", "**/CLAUDE.local.md", os.path.join( os.path.expanduser( "~" ), ".claude", "CLAUDE.md" ) ],
    "autoMemoryEnabled" : False,
}
# --strict-mcp-config with no --mcp-config loads no MCP server; skills are off. --bare is not an
# option: it refuses OAuth and would force the per-token key.
ISOLATION_ARGS     = { "settings": json.dumps( ISOLATION_SETTINGS, sort_keys=True ), "strict-mcp-config": None, "disable-slash-commands": None }
SETTING_SOURCES    = []
# The profile that is hashed names the home directory as "~", so the same options give the same
# prompt version for every user and machine; the settings actually sent carry the real path.
PORTABLE_SETTINGS  = dict( ISOLATION_SETTINGS, claudeMdExcludes=[ "~/.claude/CLAUDE.md" if pattern == os.path.join( os.path.expanduser( "~" ), ".claude", "CLAUDE.md" ) else pattern for pattern in ISOLATION_SETTINGS[ "claudeMdExcludes" ] ] )
CALL_PROFILE       = "hermetic-1|" + json.dumps( { "settings": PORTABLE_SETTINGS, "args": sorted( ISOLATION_ARGS ), "setting_sources": SETTING_SOURCES, "tools": NO_TOOLS }, sort_keys=True )


# What the probe still saw after the profile (11 context blocks before, 5 after). The
# report states these, because "hermetic" here means no operator instructions, not an empty context.
RESIDUAL_CONTEXT = [ "environment and working-directory block", "model name", "token budget", "account email header", "current date" ]


class ModelCallError( Exception ):
    """A model call returned nothing usable or raised."""


class CallBudgetExceeded( Exception ):
    """
    A call would pass the per-model cap, so it was refused before any model was contacted.

    Not a ModelCallError: a caller that retries on a failed call must not retry past a cap.
    """


BUDGET_LEDGER = None
BUDGET_CAPS   = {}


def set_budget( ledger_path, caps ):
    """
    Cap the number of calls per model id for this process, counted from a ledger file that outlives it.

    Requires:
        - ledger_path is a file path in an existing directory, outside the repo; the file may not exist yet
        - caps is a dict of model id to a maximum number of calls, each an int of zero or more
        - every script that calls the same model names the same ledger, or the cap covers only one of them

    Ensures:
        - later calls to complete charge a model named in caps against that ledger
        - a model not named in caps is not charged and not capped
        - set_budget( None, {} ) removes the cap

    Raises:
        - ValueError if a cap is not an int of zero or more, a model id is empty, caps names a model but
          ledger_path is None, or the ledger's directory does not exist
    """
    global BUDGET_LEDGER, BUDGET_CAPS
    for model, cap in caps.items():
        if not model: raise ValueError( "a cap needs a model id" )
        if isinstance( cap, bool ) or not isinstance( cap, int ) or cap < 0: raise ValueError( f"cap for {model} must be an int of zero or more, got {cap!r}" )
    if caps and ledger_path is None: raise ValueError( "caps need a ledger path" )
    if ledger_path is not None and not os.path.isdir( os.path.dirname( os.path.abspath( ledger_path ) ) ):
        raise ValueError( f"ledger directory for {ledger_path!r} does not exist" )
    BUDGET_LEDGER = ledger_path
    BUDGET_CAPS   = dict( caps )


def calls_used( model, ledger_path=None ):
    """
    Count the calls charged to a model in the ledger file, so the figure survives a restart.

    Requires:
        - ledger_path is a ledger file path or None for the one set_budget named; a missing file counts as zero

    Ensures:
        - returns the number of ledger lines naming the model; a torn last line, even one cut inside a multibyte character, is not counted
    """
    path = BUDGET_LEDGER if ledger_path is None else ledger_path
    if path is None or not os.path.exists( path ): return 0
    used = 0
    with open( path, encoding="utf-8", errors="replace" ) as f:
        for line in f:
            try: row = json.loads( line )
            except ValueError: continue
            if row.get( "model" ) == model: used += 1
    return used


def budget_summary():
    """
    Return the count and the cap of every capped model, for a result to print.

    Ensures:
        - returns { model: { "used": n, "cap": cap } } read from the ledger now; {} when no cap is set
    """
    return { model: { "used": calls_used( model ), "cap": cap } for model, cap in BUDGET_CAPS.items() }


def _charge( model ):
    """
    Charge one call to a capped model, or refuse it; writes the ledger line before the call is made.

    Requires:
        - model is a non-empty model id

    Ensures:
        - a model with no cap is not charged
        - the count is read from the ledger under an exclusive file lock, so two processes cannot both take the last call
        - a call that would pass the cap raises CallBudgetExceeded and writes nothing
        - a ledger whose last line was cut off mid-write (no trailing newline) is closed with a newline first, so the
          torn fragment cannot fuse with the new row and hide it from the count
        - the line is flushed to disk before the model is contacted, so a crashed call still counts

    Raises:
        - CallBudgetExceeded when the model has used its cap
    """
    cap = BUDGET_CAPS.get( model )
    if cap is None: return
    with open( BUDGET_LEDGER, "a+", encoding="utf-8" ) as f:
        fcntl.flock( f, fcntl.LOCK_EX )
        used    = calls_used( model )
        allowed = used < cap
        if allowed:
            size = os.fstat( f.fileno() ).st_size
            if size > 0 and os.pread( f.fileno(), 1, size - 1 ) != b"\n": f.write( "\n" )
            f.write( json.dumps( { "model": model, "n": used + 1, "ts": datetime.datetime.now( datetime.timezone.utc ).isoformat() } ) + "\n" )
            f.flush()
            os.fsync( f.fileno() )
    if not allowed: raise CallBudgetExceeded( f"{model} has used {used} of its {cap} calls; no model was contacted" )


def configure( cli_path=None, cwd=None ):
    """
    Choose the Claude Code binary and the working directory every later call uses, for this process.

    The SDK ships its own binary, and a newer model id can need a newer binary than the one it
    ships. Run config, not a default: the harness command line sets it once.

    Requires:
        - cli_path is None (the SDK's own binary) or the path of an executable file
        - cwd is None (the project root) or an existing directory

    Ensures:
        - later calls to complete pass cli_path and cwd to the SDK; None restores the default

    Raises:
        - ValueError if cli_path is given and is not an executable file, or cwd is not a directory
    """
    global CLI_PATH, CWD
    if cli_path is not None and not ( os.path.isfile( cli_path ) and os.access( cli_path, os.X_OK ) ):
        raise ValueError( f"cli path {cli_path!r} is not an executable file" )
    if cwd is not None and not os.path.isdir( cwd ):
        raise ValueError( f"cwd {cwd!r} is not a directory" )
    CLI_PATH = cli_path
    CWD      = cwd


def cli_version( cli_path, run_fn=None ):
    """
    Return the version string a Claude Code binary reports, so a report names the binary and not just its path.

    Requires:
        - cli_path is None or the path of an executable file; run_fn, when given, stands in for subprocess.run

    Ensures:
        - returns the first line of the binary's --version output, or None when cli_path is None
          (the SDK's bundled binary, whose version this module does not read)
        - never raises: a binary that fails to report is "unreadable"
    """
    if cli_path is None: return None
    run_fn = subprocess.run if run_fn is None else run_fn
    try:
        done = run_fn( [ cli_path, "--version" ], capture_output=True, text=True, timeout=30 )
        return done.stdout.strip().splitlines()[ 0 ] if done.returncode == 0 and done.stdout.strip() else "unreadable"
    except ( OSError, subprocess.SubprocessError ):
        return "unreadable"


def prompt_version( name, *parts ):
    """
    Derive a prompt version from the text and code behind a prompt, so it cannot go stale.

    Requires:
        - name is a short label; parts are the strings (prompt text, parser source) to hash

    Ensures:
        - returns "<name>-<10 hex digits>" and a change to any part changes it
    """
    return name + "-" + hashlib.sha256( "\0".join( ( CALL_PROFILE, *parts ) ).encode( "utf-8" ) ).hexdigest()[ :10 ]


def new_suffix( *texts ):
    """
    Return a random tag suffix that occurs in none of the given texts.

    Requires:
        - texts are the strings that will sit between the tags

    Ensures:
        - a closing tag built with this suffix cannot be forged by anything in texts
    """
    while True:
        suffix = secrets.token_hex( 4 )
        if not any( suffix in text for text in texts ): return suffix


def wrap( label, suffix, body ):
    """Return body between an opening and a closing tag named label_suffix."""
    return f"<{label}_{suffix}>\n{body}\n</{label}_{suffix}>"


async def complete( model, system_prompt, user_prompt, query_fn=None, timeout_seconds=TIMEOUT_SECONDS ):
    """
    Send one prompt to a bounded Claude Code model and return its text.

    Requires:
        - model is a non-empty string naming a model id; there is no default
        - query_fn, when given, is an async generator function with sdk_query's signature
          ( prompt=..., options=... ), used by tests to stand in for the SDK

    Ensures:
        - tools are disabled, so the model can only write text
        - returns the concatenated text blocks of the assistant messages, stripped
        - the text is never empty
        - a model with a cap (set_budget) is charged one call before the model is contacted

    Raises:
        - ValueError if model is empty
        - CallBudgetExceeded if the model has used its cap; nothing is contacted
        - ModelCallError if the call raises, times out, ends in an error result, or returns no text
    """
    if not model: raise ValueError( "model id is required: the harness has no default model" )
    _charge( model )
    query_fn = sdk_query if query_fn is None else query_fn
    options  = ClaudeAgentOptions(
        model           = model,
        system_prompt   = system_prompt,
        tools           = NO_TOOLS,
        permission_mode = PERMISSION_MODE,
        max_turns       = MAX_TURNS,
        cli_path        = CLI_PATH,
        cwd             = CWD if CWD is not None else cu.get_project_root(),
        setting_sources = list( SETTING_SOURCES ),
        extra_args      = dict( ISOLATION_ARGS ),
    )
    parts = []

    async def collect():
        async for message in query_fn( prompt=user_prompt, options=options ):
            if isinstance( message, AssistantMessage ):
                parts.extend( block.text for block in message.content if isinstance( block, TextBlock ) )
            elif isinstance( message, ResultMessage ) and message.is_error:
                raise ModelCallError( f"model call to {model} ended in an error result: {message.subtype}: {str( message.result )[ :300 ]}" )

    try:
        await asyncio.wait_for( collect(), timeout_seconds )
    except ModelCallError:
        raise
    except asyncio.TimeoutError as e:
        raise ModelCallError( f"model call to {model} timed out after {timeout_seconds}s" ) from e
    except Exception as e:
        raise ModelCallError( f"model call to {model} failed: {e}" ) from e
    text = "".join( parts ).strip()
    if not text: raise ModelCallError( f"model call to {model} returned no text" )
    return text
