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
import contextlib
import contextvars
import datetime
import fcntl
import hashlib
import json
import math
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time

from claude_agent_sdk import ClaudeAgentOptions, AssistantMessage, ResultMessage, TextBlock, query as sdk_query

import cosa.utils.util as cu
from cosa.orchestration.agy import runtime as agy_runtime

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


THINKING_SETTINGS = ( "default", "off" )

# Which tool answers complete(). "claude" is bounded Claude Code, described above. "agy" sends the
# call to a Gemini model through the Antigravity command-line agent (cosa.orchestration.agy).
TRANSPORTS = ( "claude", "agy" )
TRANSPORT  = "claude"

# agy takes one prompt and has no system-prompt slot, so the two are joined with this text.
AGY_PROMPT_JOIN = "\n\n"

AGY_BIN     = None
AGY_PIN     = None
AGY_VERSION = None
AGY_RUNNER  = None

# Why the agy run stopped, once the binary is seen to differ from the pin; None while it matches.
# harness_runner.run_all raises the failure of the earliest pair, which under --parallel can be
# an ordinary failed call from another pair, so the command line reads the reason from here.
AGY_STOP = None

# Seconds to wait before each further try when agy answers that the service is unavailable (503).
# Three waits make four tries at the most. A 130-pair run was ended seven times by this answer
# in half an hour, and each time the next attempt, 45 seconds or more later, went through.
AGY_UNAVAILABLE_WAITS = ( 15, 45, 90 )
AGY_SLEEP             = time.sleep

# The agent every agy call runs as: a custom agent with no tools, written into the call's scratch
# directory, where agy looks for it. The Claude path runs with tools=[]; this is the same rule for agy.
# With agy's default agent a model can answer by trying a tool, such as a shell command to look at a
# file the docstring names; print mode refuses it and the answer comes back blank. It also carries
# about 13,000 input tokens of agent instructions and tool definitions a call, against about 3,400 here
# (both measured on agy 1.2.17 with a one-line prompt).
AGY_AGENT_NAME = "lupin-text-only"
AGY_AGENT_PATH = os.path.join( ".agents", "agents", AGY_AGENT_NAME + ".md" )
AGY_AGENT_TEXT = (
    "---\n"
    f"name: {AGY_AGENT_NAME}\n"
    "description: Answers from the text of the prompt only. Has no tools.\n"
    "tools: []\n"
    "---\n"
    "You answer from the text you are given and nothing else. You have no tools.\n"
)

# What an agy call runs under, for a report. It is not the Claude isolation profile above. The agent
# definition is hashed in, so a report made under another agent text names another profile.
# What a scratch directory holds when an answer left nothing behind: the agent definition and the
# two directories above it.
AGY_SCRATCH_ENTRIES = sorted( [ ".agents", os.path.join( ".agents", "agents" ), AGY_AGENT_PATH ] )

AGY_CALL_PROFILE     = "agy-print-2|new-project|disable-slash-commands|stream-json|scratch-cwd|no-edit-grant|agent=" + AGY_AGENT_NAME + "-" + hashlib.sha256( AGY_AGENT_TEXT.encode( "utf-8" ) ).hexdigest()[ :10 ]
AGY_RESIDUAL_CONTEXT = [ "agy's own framing around the custom agent, about 3,400 input tokens a call on agy 1.2.17" ]

AGY_USAGE_FIELDS = ( "input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "total_tokens" )

# Tokens agy reported, summed per model id for this process. Calls run in worker threads.
AGY_USAGE       = {}
_AGY_USAGE_LOCK = threading.Lock()

# The plan for the model calls made under a record_calls() block, one per context (an asyncio task has its own),
# so pairs in flight at once cannot write into each other's tally. It is kept here, and not passed down through
# claim_extractor and claim_judge, because those modules' source is hashed into their prompt versions: editing them
# would orphan every existing ledger.
_SCOPE = contextvars.ContextVar( "model_call_scope", default=None )


class _CallScope:
    """What record_calls() keeps for its block: the finished calls, and which stage and thinking setting the next call has."""

    def __init__( self, plan ):
        self.plan   = plan
        self.issued = 0
        self.calls  = []

    def next_call( self ):
        """Return ( stage, thinking ) for the next call issued in the block; the last plan entry repeats."""
        entry        = self.plan[ min( self.issued, len( self.plan ) - 1 ) ]
        self.issued += 1
        return entry


@contextlib.contextmanager
def record_calls( plan=( ( "call", "default" ), ) ):
    """
    Collect ( stage, seconds ) for every call to complete() made inside the block, in this context only.

    Requires:
        - plan is a non-empty tuple of ( stage, thinking ), one per call in the order the block issues them;
          the last entry stands for every call after it. The judge block is ( ( "judge", setting ), ( "escalation", "default" ) ):
          the first call is the first-pass judge and any later call is the escalation, so the thinking
          setting reaches the first pass only

    Ensures:
        - yields a list that grows by one ( stage, seconds ) per finished call; a call that fails is not recorded
        - a call whose own thinking argument is "default" takes the plan's thinking setting
        - the previous scope is restored on exit, so blocks nest
    """
    scope = _CallScope( plan )
    token = _SCOPE.set( scope )
    try:
        yield scope.calls
    finally:
        _SCOPE.reset( token )


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


def configure_agy( agy_bin=agy_runtime.DEFAULT_AGY_BIN, runner=None ):
    """
    Send every later call through agy, pinned to the binary on disk now, for this process.

    Requires:
        - agy_bin is a command name on the search path, or a path to the agy binary
        - runner, when given, stands in for subprocess.run in tests, for the version call and every model call

    Ensures:
        - later calls to complete go to agy, and the token tally starts empty
        - the version is read first and the fingerprint second, because asking agy for its
          version can start its updater
        - returns the ledger binding: the binary's path, size, modification time and version, then
          the call profile. A ledger written under one binary, or under another call profile such
          as another agent definition, is refused
        - a binary that changes later stops the run: complete raises AgyBinaryChanged

    Raises:
        - ValueError if the binary cannot be found or does not report a version
    """
    global TRANSPORT, AGY_BIN, AGY_PIN, AGY_VERSION, AGY_RUNNER, AGY_STOP
    try:
        version = agy_runtime.agy_version( agy_bin, runner=runner )
        pin     = agy_runtime.binary_fingerprint( agy_bin )
    except agy_runtime.AgyCallError as e:
        raise ValueError( f"agy binary {agy_bin!r} is not usable: {e}" ) from e
    TRANSPORT   = "agy"
    AGY_BIN     = agy_bin
    AGY_PIN     = pin
    AGY_VERSION = version
    AGY_RUNNER  = runner
    AGY_STOP    = None
    with _AGY_USAGE_LOCK: AGY_USAGE.clear()
    return f"agy={pin[ 'path' ]}|size={pin[ 'size' ]}|mtime_ns={pin[ 'mtime_ns' ]}|version={version}|profile={AGY_CALL_PROFILE}"


def configure_claude():
    """
    Send every later call through bounded Claude Code again, and forget the agy pin.

    Ensures:
        - the transport is "claude", the default, and the agy binary, pin, version, runner and stop
          reason are None
    """
    global TRANSPORT, AGY_BIN, AGY_PIN, AGY_VERSION, AGY_RUNNER, AGY_STOP
    TRANSPORT   = "claude"
    AGY_BIN     = None
    AGY_PIN     = None
    AGY_VERSION = None
    AGY_RUNNER  = None
    AGY_STOP    = None


def _require_pinned_binary():
    """
    Refuse the next agy call when the binary on disk is not the one configure_agy pinned.

    Ensures:
        - returns None while the binary matches the pin
        - the first mismatch is kept as the stop reason, and every later call is refused with it
          without reading the disk again
        - a binary that can no longer be found counts as changed

    Raises:
        - AgyBinaryChanged carrying the stop reason
    """
    global AGY_STOP
    if AGY_STOP is None:
        try:
            now = agy_runtime.binary_fingerprint( AGY_BIN )
        except agy_runtime.AgyCallError:
            now = None
        if now != AGY_PIN: AGY_STOP = f"agy binary changed since the run began: pinned {AGY_PIN}, now {now}"
    if AGY_STOP is not None: raise agy_runtime.AgyBinaryChanged( AGY_STOP )


def agy_usage_summary():
    """
    Return the tokens agy reported so far, per model id, for a report to print.

    Ensures:
        - returns { model: { "calls": n, "input_tokens": n, "output_tokens": n, "thinking_tokens": n,
          "cache_read_tokens": n, "total_tokens": n } }; {} when no agy call has finished
        - the result is a copy, so a caller cannot change the tally
    """
    with _AGY_USAGE_LOCK: return { model: dict( tally ) for model, tally in AGY_USAGE.items() }


def _agy_whole_seconds( timeout_seconds ):
    """
    Turn a time limit into the whole seconds agy takes, one at the least.

    Requires:
        - timeout_seconds is a finite number above zero; agy reads zero as no limit, so there is no
          way to ask for none

    Ensures:
        - returns the limit rounded down to whole seconds, and 1 for anything below one second

    Raises:
        - ValueError if timeout_seconds is not a number, is a boolean, is not finite, or is not above zero
    """
    if isinstance( timeout_seconds, bool ) or not isinstance( timeout_seconds, ( int, float ) ) or not math.isfinite( timeout_seconds ) or timeout_seconds <= 0:
        raise ValueError( f"timeout_seconds must be a finite number above zero under agy, got {timeout_seconds!r}" )
    return max( 1, int( timeout_seconds ) )


def _agy_call( model, prompt, timeout_seconds ):
    """
    Make one agy call, trying again after a wait when agy answers unavailable.

    Requires:
        - configure_agy has run; prompt is the joined system and user prompt
        - timeout_seconds is a whole number of seconds from _agy_whole_seconds

    Ensures:
        - returns what _agy_call_once returns
        - an AgyUnavailable is tried again after each wait in AGY_UNAVAILABLE_WAITS, in a new
          scratch directory each time; no other failure is tried again here
        - the caller's budget is not charged again: complete charges before calling this

    Raises:
        - ModelCallError naming the number of tries when every try was answered unavailable
        - whatever _agy_call_once raises otherwise
    """
    waits = list( AGY_UNAVAILABLE_WAITS )
    tries = len( waits ) + 1
    while True:
        try:
            return _agy_call_once( model, prompt, timeout_seconds )
        except agy_runtime.AgyUnavailable as e:
            if not waits:
                raise ModelCallError( f"model call to {model} failed, unavailable on each of {tries} tries: {e}" ) from e
            AGY_SLEEP( waits.pop( 0 ) )


def _agy_call_once( model, prompt, timeout_seconds ):
    """
    Make one agy call in a fresh scratch directory that holds only the agent definition.

    Requires:
        - configure_agy has run; prompt is the joined system and user prompt
        - timeout_seconds is a whole number of seconds from _agy_whole_seconds

    Ensures:
        - agy runs as the no-tools agent, with a temporary directory as its working directory that
          holds the agent definition and nothing else
        - the scratch directory is removed afterwards when it can be; a removal that fails is
          ignored, so it cannot replace the answer or the failure of the call
        - returns the answer stripped, and adds the call's tokens to the tally for model; a token
          field agy leaves out, or reports as something other than a whole number, adds nothing
        - a binary change run_agy itself reports is kept as the stop reason
        - an answer is refused when agy tried a tool action, left any other file or directory in
          the scratch directory, or changed the agent definition: a tool attempt is not a text answer.
          A directory that cannot be listed counts as changed

    Raises:
        - ModelCallError if agy fails, tried a tool action, wrote into the scratch directory or changed
          the agent definition, or if the scratch directory cannot be made or listed, or the agent
          definition cannot be written or read back
        - AgyUnavailable if agy answered that the service is unavailable, for _agy_call to try again
        - AgyBinaryChanged if the binary differs from the pin; it is not a ModelCallError, so a
          caller that retries failed calls does not retry under another binary
    """
    global AGY_STOP
    try:
        scratch = tempfile.mkdtemp( prefix="agy-call-" )
    except OSError as e:
        raise ModelCallError( f"model call to {model} could not make its scratch directory: {e}" ) from e
    try:
        agent_file = os.path.join( scratch, AGY_AGENT_PATH )
        try:
            os.makedirs( os.path.dirname( agent_file ) )
            with open( agent_file, "w", encoding="utf-8" ) as f: f.write( AGY_AGENT_TEXT )
        except OSError as e:
            raise ModelCallError( f"model call to {model} could not write its agent definition: {e}" ) from e
        try:
            result = agy_runtime.run_agy( prompt, model=model, workspace_dir=scratch, timeout_seconds=timeout_seconds, agent=AGY_AGENT_NAME,
                                          agy_bin=AGY_BIN, pinned_fingerprint=AGY_PIN, runner=AGY_RUNNER )
        except agy_runtime.AgyUnavailable:
            raise
        except agy_runtime.AgyCallError as e:
            raise ModelCallError( f"model call to {model} failed: {e}" ) from e
        except agy_runtime.AgyBinaryChanged as e:
            if AGY_STOP is None: AGY_STOP = str( e )
            raise
        try:
            holds = _scratch_entries( scratch )
        except OSError as e:
            raise ModelCallError( f"model call to {model} left a scratch directory that cannot be listed: {e}" ) from e
        intact = holds == AGY_SCRATCH_ENTRIES
        if intact:
            try:
                with open( agent_file, encoding="utf-8" ) as f: intact = f.read() == AGY_AGENT_TEXT
            except ( OSError, UnicodeDecodeError ) as e:
                raise ModelCallError( f"model call to {model} left an agent definition that cannot be read back: {e}" ) from e
    finally:
        shutil.rmtree( scratch, ignore_errors=True )
    if result.denied_actions:
        raise ModelCallError( f"model call to {model} tried tool actions and was refused them: {result.denied_actions}" )
    if not intact:
        raise ModelCallError( f"model call to {model} changed its scratch directory, which now holds: {holds}" )
    with _AGY_USAGE_LOCK:
        tally = AGY_USAGE.setdefault( model, dict( { field: 0 for field in AGY_USAGE_FIELDS }, calls=0 ) )
        tally[ "calls" ] += 1
        for field in AGY_USAGE_FIELDS:
            count = result.usage.get( field )
            if isinstance( count, int ) and not isinstance( count, bool ): tally[ field ] += count
    return result.response.strip()


def _scratch_entries( scratch ):
    """
    List every file and directory under a scratch directory, as sorted paths relative to it.

    Requires:
        - scratch is an existing directory

    Ensures:
        - directories are listed as well as files, so an empty directory an answer left behind is seen
        - a symbolic link to a directory is listed and not followed

    Raises:
        - OSError if any directory under scratch cannot be listed; os.walk would otherwise skip it
          and report nothing
    """
    def refuse( error ): raise error
    return sorted( os.path.relpath( os.path.join( folder, name ), scratch )
                   for folder, folders, files in os.walk( scratch, onerror=refuse ) for name in folders + files )


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


async def complete( model, system_prompt, user_prompt, query_fn=None, timeout_seconds=TIMEOUT_SECONDS, thinking="default" ):
    """
    Send one prompt to a model and return its text, through Claude Code or agy.

    Requires:
        - model is a non-empty string naming a model id; there is no default
        - query_fn, when given, is an async generator function with sdk_query's signature
          ( prompt=..., options=... ), used by tests to stand in for the SDK

    Ensures:
        - tools are disabled, so the model can only write text
        - returns the concatenated text blocks of the assistant messages, stripped
        - the text is never empty
        - a model with a cap (set_budget) is charged one call before the model is contacted
        - thinking "default" sends exactly the options sent before this setting existed; "off" adds
          the SDK's thinking-disabled option
        - a finished call is added to the enclosing record_calls() list as ( stage, wall-clock seconds )
        - an enclosing record_calls() block decides the thinking setting when thinking is "default"
        - under agy the system prompt and the user prompt are joined by AGY_PROMPT_JOIN and sent as one
          prompt, query_fn is not used, and the call runs in a worker thread so calls can overlap
        - under agy the reasoning level is part of the model id, so thinking must resolve to "default"

    Raises:
        - ValueError if model is empty, thinking is not one of THINKING_SETTINGS, or thinking resolves
          to "off" under agy; nothing is charged or contacted
        - ValueError, under agy, if timeout_seconds is not a finite number above zero; nothing is charged
        - AgyBinaryChanged, under agy, if the binary differs from the one configure_agy pinned. A change
          seen before the call costs nothing against a cap; one that happens while the call runs is
          found after the charge
        - CallBudgetExceeded if the model has used its cap; nothing is contacted
        - ModelCallError if the call raises, times out, ends in an error result, or returns no text
    """
    if not model: raise ValueError( "model id is required: the harness has no default model" )
    if thinking not in THINKING_SETTINGS: raise ValueError( f"thinking must be one of {THINKING_SETTINGS}, got {thinking!r}" )
    scope = _SCOPE.get()
    stage = None
    if scope is not None:
        stage, planned = scope.next_call()
        if thinking == "default": thinking = planned
    if TRANSPORT == "agy":
        if thinking != "default": raise ValueError( "thinking 'off' has no agy setting: choose the model id with the reasoning level wanted, such as one ending in -low" )
        limit = _agy_whole_seconds( timeout_seconds )
        _require_pinned_binary()
        _charge( model )
        started = time.monotonic()
        text    = await asyncio.to_thread( _agy_call, model, system_prompt + AGY_PROMPT_JOIN + user_prompt, limit )
        if scope is not None: scope.calls.append( ( stage, time.monotonic() - started ) )
        return text
    _charge( model )
    query_fn = sdk_query if query_fn is None else query_fn
    extra    = { "thinking": { "type": "disabled" } } if thinking == "off" else {}
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
        **extra,
    )
    parts = []
    started = time.monotonic()

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
    if scope is not None: scope.calls.append( ( stage, time.monotonic() - started ) )
    return text
