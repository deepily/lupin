"""
Antigravity (agy) CLI runtime: one prompt in, one raw answer out.

Runs Google's `agy` command-line agent as a subprocess in print mode. Lupin code hands
it a single prompt for a Gemini model and reads back the text of the answer.

Design:
    - The prompt travels on standard input as one stream-json message, never on the
      command line. Prompts hold quotes and newlines, and one argv string is capped by
      the kernel at 131,072 bytes.
    - The answer is the `response` of the final `result` event on standard output. It is
      returned unparsed; the caller decides what the text means.
    - agy is an agent with tools and it runs unsandboxed. The subprocess starts with its
      working directory set to a caller-supplied scratch directory. No flag that grants
      edits is passed, so print mode refuses tool actions that need approval. Point
      `workspace_dir` at a disposable directory, never at a repository.
    - agy replaces its own binary when it finds an update, including in the middle of a
      run. `binary_fingerprint` identifies the binary on disk. Pass the fingerprint taken
      at the start of a run as `pinned_fingerprint`, and `run_agy` refuses to call a
      binary that has changed since.
    - There is no retry here. A timeout, a non-zero exit, a missing or failed result, and
      an empty answer all raise `AgyCallError`; the caller owns the retry policy.

The message shape and the result shape were read from agy 1.2.17.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time

from dataclasses import dataclass


DEFAULT_AGY_BIN         = "agy"
DEFAULT_TIMEOUT_SECONDS = 300

# The outer subprocess timeout exceeds agy's own --print-timeout by this many seconds, so
# agy reports its timeout itself before the subprocess is killed.
OUTER_TIMEOUT_HEADROOM_SECONDS = 60

STDERR_TAIL_CHARS = 2000


class AgyCallError( Exception ):
    """Raised when an agy call produced no usable answer."""


class AgyBinaryChanged( Exception ):
    """Raised when the agy binary on disk differs from the pinned fingerprint."""


@dataclass
class AgyResult:
    """
    The outcome of one successful agy call.

    Requires:
        - built by `run_agy` from a result event whose status is `SUCCESS`

    Ensures:
        - response is the model's answer exactly as agy reported it
        - response_bytes and response_sha describe the UTF-8 encoding of response
        - usage is agy's token report for the call (input_tokens, output_tokens,
          thinking_tokens, cache_read_tokens, total_tokens)
        - denied_actions lists tool actions print mode refused, empty when none
        - fingerprint identifies the binary that produced the answer
    """

    response         : str
    model            : str
    effort           : object
    conversation_id  : str
    num_turns        : int
    duration_seconds : float
    wall_seconds     : float
    usage            : dict
    denied_actions   : list
    response_bytes   : int
    response_sha     : str
    fingerprint      : dict


def binary_fingerprint( agy_bin=DEFAULT_AGY_BIN ):
    """
    Identify the agy binary on disk without starting it.

    Starting agy can trigger its updater, so the identity is read from the file itself.

    Requires:
        - agy_bin is a command name on the search path, or a path to the binary

    Ensures:
        - returns a dict with the resolved real path, the size in bytes and the
          modification time in nanoseconds
        - two calls return equal dicts exactly when the file was not replaced between them

    Raises:
        - AgyCallError if agy_bin cannot be found
    """

    resolved = shutil.which( agy_bin )
    if resolved is None:
        raise AgyCallError( f"agy binary not found: {agy_bin!r} is not on PATH and is not an executable path" )

    real_path = os.path.realpath( resolved )
    stat      = os.stat( real_path )

    return {
        "path"     : real_path,
        "size"     : stat.st_size,
        "mtime_ns" : stat.st_mtime_ns
    }


def agy_version( agy_bin=DEFAULT_AGY_BIN, runner=None ):
    """
    Ask agy for its version string.

    This starts agy, which may trigger its updater. Call it once at the start of a run,
    then take the fingerprint.

    Requires:
        - agy_bin is a command name on the search path, or a path to the binary
        - runner (optional) is a subprocess.run-compatible callable

    Ensures:
        - returns the first line of `agy --version`, stripped

    Raises:
        - AgyCallError if agy exits non-zero, times out, or prints nothing
    """

    runner = runner if runner is not None else subprocess.run

    try:
        result = runner( [ agy_bin, "--version" ], capture_output=True, text=True, timeout=60 )
    except subprocess.TimeoutExpired:
        raise AgyCallError( "agy --version timed out after 60s" )

    lines = ( result.stdout or "" ).strip().splitlines()
    if result.returncode != 0 or not lines:
        raise AgyCallError( f"agy --version failed: exit={result.returncode}, stderr={( result.stderr or '' )[ :500 ]}" )

    return lines[ 0 ].strip()


def build_argv( *, model, timeout_seconds, effort=None, agy_bin=DEFAULT_AGY_BIN ):
    """
    Build the agy print-mode command line for one call.

    Requires:
        - model is an agy model identifier, for example "gemini-3.1-pro-high"
        - timeout_seconds is a positive integer
        - effort is None or one of agy's reasoning effort names

    Ensures:
        - the prompt flag is attached empty (`-p=`); the prompt itself goes on stdin
        - the time limit carries a unit ("300s"); agy rejects a bare integer
        - carries --new-project so calls share no conversation state
        - carries --disable-slash-commands so a prompt beginning with "/" is sent as text
        - never carries --mode accept-edits, --sandbox or --dangerously-skip-permissions
        - carries --effort only when effort is given
    """

    argv = [
        agy_bin,
        "-p=",
        "--model", model,
        "--print-timeout", f"{timeout_seconds}s",
        "--new-project",
        "--disable-slash-commands",
        "--input-format", "stream-json",
        "--output-format", "stream-json"
    ]

    if effort is not None: argv.extend( [ "--effort", effort ] )

    return argv


def build_stdin( prompt ):
    """
    Encode a prompt as the single stream-json line agy reads from standard input.

    Requires:
        - prompt is a non-empty string

    Ensures:
        - returns one newline-terminated JSON line carrying a user message
        - quotes, backslashes, newlines and non-ASCII text survive unchanged

    Raises:
        - ValueError if prompt is empty or whitespace
    """

    if not prompt.strip():
        raise ValueError( "prompt is empty" )

    message = {
        "event"   : "user",
        "message" : { "role" : "user", "content" : prompt }
    }

    return json.dumps( message, ensure_ascii=False ) + "\n"


def parse_result( stdout ):
    """
    Find the final result event in agy's stream-json output.

    Requires:
        - stdout is the captured standard output of a print-mode call, or None

    Ensures:
        - returns the `result` object of the last event whose `event` is "result"
        - lines that are not JSON objects are skipped

    Raises:
        - AgyCallError if no result event is present
    """

    found = None

    for line in ( stdout or "" ).splitlines():
        try:
            event = json.loads( line )
        except json.JSONDecodeError:
            continue

        if isinstance( event, dict ) and event.get( "event" ) == "result":
            found = event[ "result" ]

    if found is None:
        raise AgyCallError( "agy printed no result event" )

    return found


def run_agy( prompt, *, model, workspace_dir, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, effort=None,
             agy_bin=DEFAULT_AGY_BIN, pinned_fingerprint=None, runner=None ):
    """
    Send one prompt to a model through agy and return its raw answer.

    Requires:
        - prompt is a non-empty string
        - model is an agy model identifier
        - workspace_dir is an existing scratch directory; agy runs with it as its working
          directory and can see what is in it
        - pinned_fingerprint (optional) is a `binary_fingerprint` taken earlier
        - runner (optional) is a subprocess.run-compatible callable, injected by tests

    Ensures:
        - refuses before calling when the binary differs from pinned_fingerprint
        - the prompt is passed on standard input
        - returns an AgyResult only for exit 0 with a `SUCCESS` result and a non-blank answer

    Raises:
        - ValueError if prompt is empty or workspace_dir is not a directory
        - AgyBinaryChanged if the binary on disk differs from pinned_fingerprint
        - AgyCallError on timeout, non-zero exit, missing result event, a result whose
          status is not `SUCCESS`, or a blank answer
    """

    if not os.path.isdir( workspace_dir ):
        raise ValueError( f"workspace_dir is not a directory: {workspace_dir}" )

    stdin_text  = build_stdin( prompt )
    fingerprint = binary_fingerprint( agy_bin )

    if pinned_fingerprint is not None and fingerprint != pinned_fingerprint:
        raise AgyBinaryChanged( f"agy binary changed since the run began: pinned {pinned_fingerprint}, now {fingerprint}" )

    runner = runner if runner is not None else subprocess.run
    argv   = build_argv( model=model, timeout_seconds=timeout_seconds, effort=effort, agy_bin=agy_bin )

    outer_timeout = timeout_seconds + OUTER_TIMEOUT_HEADROOM_SECONDS
    started       = time.monotonic()

    try:
        completed = runner( argv, input=stdin_text, capture_output=True, text=True, timeout=outer_timeout, cwd=workspace_dir )
    except subprocess.TimeoutExpired:
        raise AgyCallError( f"agy timed out after {outer_timeout}s (model {model})" )

    wall_seconds = round( time.monotonic() - started, 3 )
    stderr_tail  = ( completed.stderr or "" )[ -STDERR_TAIL_CHARS: ]

    if completed.returncode != 0:
        raise AgyCallError( f"agy exited {completed.returncode} (model {model}); stderr: {stderr_tail}" )

    result = parse_result( completed.stdout )

    if result[ "status" ] != "SUCCESS":
        raise AgyCallError( f"agy result status {result[ 'status' ]} (model {model}): {result.get( 'error', '' )}" )

    response = result[ "response" ]
    if not response.strip():
        raise AgyCallError( f"agy returned a blank answer (model {model})" )

    encoded = response.encode( "utf-8" )

    return AgyResult(
        response         = response,
        model            = model,
        effort           = effort,
        conversation_id  = result[ "conversation_id" ],
        num_turns        = result[ "num_turns" ],
        duration_seconds = result[ "duration_seconds" ],
        wall_seconds     = wall_seconds,
        usage            = result[ "usage" ],
        # agy includes denied_actions only when print mode refused a tool action.
        denied_actions   = result.get( "denied_actions", [] ),
        response_bytes   = len( encoded ),
        response_sha     = hashlib.sha256( encoded ).hexdigest(),
        fingerprint      = fingerprint
    )
