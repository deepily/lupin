"""
Kill guard — an unscoped process sweep can reach another seat's CLI (row cd332d2b).

WHAT IT COSTS, measured: on 2026-08-21 at 15:27:03Z a worker ran
`pkill -f "pytest src/tests/unit"`. The CLI's own shadow-`pkill` shell function
REFUSED it, verbatim: "this pattern matches the Claude CLI process (PID
127519)". Ten seconds later the same worker reproduced the sweep by hand as
`ps -eo pid,args | grep "[p]ytest src/tests/unit" | ... | while read p; do kill
$p; done` — a shape the shadow function does not see — and its own output names
the damage: "killed 125491 killed 127519 killed 171103 ..." — eight processes,
INCLUDING the 127519 the refusal had just named. Three worker seats stopped
within 612 ms; the author's was one of them. A fourth seat survived only
because its command line did not happen to match the pattern.

⇒ WHY A PATTERN THAT LOOKS LIKE A TEST PATH MATCHES A SEAT: a seat is launched
as `claude --model … <its entire spawn brief>`, so the brief is in its argv.
Any brief that so much as mentions `src/tests/unit` makes that seat a match for
a grep aimed at pytest. The pattern does not have to be careless to be lethal —
it only has to be a phrase somebody wrote down.

WHAT IS DENIED, and nothing wider:
  · SHAPE A — `kill <pid>` (any signal) naming a PID that /proc says is a LIVE
    `claude` process. Verified against /proc at hook time, so this is a fact
    about the box rather than a guess about the string.
  · SHAPE B — a system-wide process listing (`ps -e`/`ps aux`/`pgrep`) feeding a
    kill downstream in the same command.
  · SHAPE C — a `pkill`/`killall` PATTERN with no own-children scoping. The
    CLI's own shadow-`pkill` refuses only a pattern matching YOUR pid; one
    that matches another seat and not you goes through it untouched.
  · SHAPE D — `kill $(pgrep …)`, identical in behaviour to the piped form B
    already denies. This is the shape above, refused
    BEFORE any PID is known — which is the only moment it can still be refused,
    since the PIDs are not in the command text.

Heredoc BODIES are stripped before matching — a file that DOCUMENTS a sweep\nis data, not a sweep. (This module's own test file is such a file, and the\nguard denied it on first wiring, which is how the exclusion got written.)\n\nWHAT STAYS ALLOWED: killing your OWN children — `pkill -P $$`, `pgrep -P $$ |
xargs kill`, `ps --ppid $$`, `kill $!`, `kill %1` — and any listing with no kill
downstream. Read-only `ps`/`pgrep` are how you find out what is running.

SAFETY — this runs inside the hot-path PreToolUse hook (every tool call, every
session), so two non-negotiables:
  • FAIL-OPEN: ANY error → allow (return None). A guard must never break a tool
    call.
  • ESCAPE HATCH: LUPIN_ALLOW_UNSCOPED_KILL=1 disables the guard for a session
    that genuinely must sweep — after it has read the PIDs and confirmed none is
    a seat.

⚠️ DEFAULT-ON, deliberately. The rule this replaces already existed as advice
("narrow the pattern"), was delivered to the author ten seconds before the
event, and did not survive contact with a hurry.
"""
import os
import re
import shlex
import subprocess
from typing import List, Optional


# Bash tool name as it appears in the PreToolUse hook payload.
BASH_TOOL_NAMES = ( "Bash", )

_ENV_FLAG    = "LUPIN_ALLOW_UNSCOPED_KILL"
_TRUE_VALUES = ( "1", "true", "on", "yes" )

# A signal flag on a kill verb: `-9`, `-KILL`, `-SIGTERM`. Not a selector.
_SIGNAL_FLAG_RE = re.compile( r"-\d+|-(?:SIG)?[A-Z]+" )

# What /proc/<pid>/comm reads for a Claude Code CLI process.
CLAUDE_COMM = "claude"

# `kill` in COMMAND POSITION with at least one literal decimal PID. Signal flags
# (`-9`, `-KILL`, `-s TERM`, `--signal=9`) sit between the verb and the targets,
# so they are skipped rather than parsed. Job specs (`%1`) and expansions (`$!`,
# `$p`) carry no literal digits and never match here — SHAPE A is only ever
# about a PID the author typed.
_KILL_LITERAL_RE = re.compile(
    r"""
    (?:^|[;&|(`]|\n)             # command position
    \s*
    kill\b                       # the verb (not pkill/killall — different shapes)
    (?P<args>(?:\s+[^\s;&|)`\n]+)*)   # the remainder of THIS command only
    """,
    re.VERBOSE,
)

# A process listing that is NOT scoped to the caller's own children. `ps` needs
# an all-processes selector; `pgrep` is fleet-wide unless told otherwise.
_UNSCOPED_LISTING_RE = re.compile(
    r"""
    (?:^|[;&|(`]|\n)\s*
    (?:
        ps\b(?=(?:\s+[^\s;&|)`\n]+)*\s+-?[aAe])   # ps -e / ps -A / ps aux / ps ax
      | pgrep\b
    )
    """,
    re.VERBOSE,
)

# Scoping that makes a listing safe: it can only ever return our own children.
_OWN_CHILDREN_RE = re.compile( r"(?:-P|--parent|--ppid)\s*=?\s*\S" )

# Quoted spans, removed before any structural test. `pgrep -f "node|esbuild"`
# carries a pipe INSIDE an argument; reading that as a pipeline is how the guard
# first mis-flagged a real monitoring loop that killed only its own `$!`.
_QUOTED_RE = re.compile( r'''\'[^\']*\'|"[^"]*"''' )

# A single `|` — the pipeline operator. `||` is control flow and pipes nothing.
_PIPE_RE = re.compile( r"(?<!\|)\|(?!\|)" )

# A compound that carries the pipeline's last segment past a `;` — the `while
# read p; do kill $p; done` tail of the incident command lives here.
_COMPOUND_RE = re.compile( r"\b(?:while|for|until|do)\b|\{" )

# `for <var> in $( <listing> )` — the substitution form, where the listing feeds
# a loop variable rather than a pipe.
_FOR_SUBST_RE = re.compile( r"\bfor\s+(?P<var>\w+)\s+in\s+(?:\$\(|`)" )

# A kill downstream of the listing. `xargs kill`, a `while read … kill` loop, a
# bare `kill` in a later command — all reach the same PIDs.
# SHAPE C — a PATTERN sweep: `pkill`/`killall` selects across the whole box by
# name or `-f` pattern. The CLI ships a shadow-`pkill` that refuses a pattern
# matching ITS OWN pid, and that is narrower than the hazard: a pattern matching
# ANOTHER seat and not yours sails straight through it. Found by Krishna
# 2026-08-24 while reviewing this guard, together with SHAPE D below.
_PATTERN_SWEEP_RE = re.compile(
    r"(?:^|[;&|(`{]|\n|\bdo\b)\s*(?:sudo\s+)?(?:pkill|killall)\b(?P<args>(?:\s+[^\s;&|)`\n]+)*)"
)

# SHAPE D — a substitution feeding a kill DIRECTLY: `kill $(pgrep …)` has the
# exact semantics of `pgrep … | xargs kill`, which SHAPE B already denies.
# Denying one and not the other draws an arbitrary line through identical
# behaviour.
_KILL_SUBST_RE = re.compile(
    r"(?:^|[;&|(`{]|\n|\bdo\b)\s*(?:sudo\s+)?kill(?:all)?\b[^;&|\n]*?"
    r"(?:\$\(|`)(?P<subst>[^)`]*)"
)

# `sudo` can sit before `xargs` OR between it and the kill (`xargs sudo kill`),
# so it is optional in BOTH slots rather than only the first.
_KILL_VERB_RE = re.compile(
    r"(?:^|[;&|(`{]|\n|\bdo\b)\s*(?:sudo\s+)?(?:xargs\s+(?:-[^\s]+\s+)*(?:sudo\s+)?)?kill(?:all)?\b"
)


# A heredoc body is DATA, not commands. Writing a file that documents a sweep —
# this module's own test file does exactly that — must not read as running one.
# Caught by the guard denying its own test file's heredoc on first wiring.
_HEREDOC_RE = re.compile( r"<<-?\s*(['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)\1" )


def _strip_heredocs( command: str ) -> str:
    """
    Remove heredoc BODIES, keeping the lines that carry real commands.

    Requires:
        - command is the shell command string

    Ensures:
        - every line strictly between a `<<TAG` line and its terminator line is
          dropped; the introducing line and the terminator are kept
        - an unterminated heredoc drops the rest of the string (that text is
          data no matter where it ends)
        - a command with no heredoc is returned unchanged
    """
    match = _HEREDOC_RE.search( command )
    if not match:
        return command
    lines = command.split( "\n" )
    kept  = []
    tag   = None
    for line in lines:
        if tag is None:
            kept.append( line )
            found = _HEREDOC_RE.search( line )
            if found:
                tag = found.group( "tag" )
        elif line.strip() == tag:
            kept.append( line )
            tag = None
    return "\n".join( kept )


def _sweep_selector( args: str ) -> List[ str ]:
    """
    The `pgrep` selector equivalent to a `pkill`/`killall` argument list.

    Requires:
        - args is the text following the pkill/killall verb

    Ensures:
        - signal flags are dropped — `-9`, `-KILL`, `-TERM`, `-s TERM`,
          `--signal=9`, `--signal 9` — because pgrep rejects them
        - `--signal`'s and `-s`'s separate VALUE is dropped with it
        - every other token is kept in order, so the selector matches exactly
          what the sweep would have matched
        - the split is SHELL-AWARE, so a quoted pattern containing spaces stays
          one token — `pkill -f "pytest src/tests/unit"` selects on the whole
          phrase, exactly as the shell would have handed it to pkill
        - unbalanced quotes fall back to a whitespace split rather than giving up
    """
    # shlex, NOT split() — `pkill -f "pytest src/tests/unit"` is ONE pattern with
    # spaces in it. Splitting on whitespace hands pgrep three patterns, pgrep
    # refuses more than one, the probe comes back empty, and the guard allows the
    # exact command that killed three seats. Caught by replaying real traffic.
    try:
        tokens = shlex.split( args )
    except ValueError:
        tokens = args.split()   # unbalanced quotes — fall back rather than refuse to look
    kept = []
    skip = False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token in ( "--signal", "-s" ):
            skip = True
            continue
        if token.startswith( "--signal=" ):
            continue
        if _SIGNAL_FLAG_RE.fullmatch( token ):
            continue
        kept.append( token )
    return kept


def _default_pgrep_probe( selector: List[ str ] ) -> List[ str ]:
    """
    The PIDs `pgrep <selector>` reports right now.

    Requires:
        - selector is the argument list to hand pgrep

    Ensures:
        - returns the matching PIDs as strings, or [] when pgrep matches nothing
        - returns [] on any failure (pgrep missing, timeout, OSError) — a probe
          that cannot answer must not manufacture a refusal
    """
    if not selector:
        return []
    try:
        result = subprocess.run(
            [ "pgrep", *selector ], capture_output=True, text=True, timeout=5
        )
        return [ line.strip() for line in result.stdout.split( "\n" ) if line.strip().isdigit() ]
    except ( OSError, subprocess.SubprocessError ):
        return []


def _seats_a_sweep_would_hit( args: str, pgrep_probe, comm_reader ) -> List[ str ]:
    """
    The live `claude` PIDs a `pkill`/`killall` pattern currently matches.

    Requires:
        - args is the sweep's argument list
        - pgrep_probe( selector ) -> list of PID strings
        - comm_reader( pid ) -> comm string or None

    Ensures:
        - returns the matching PIDs whose /proc comm is `claude`, in pgrep order
        - returns [] when the pattern matches no seat — which is the ordinary
          case and must stay ALLOWED: 21 of 6,492 real fleet commands are this
          shape, nearly all of them a seat stopping its OWN superseded test run.
          Refusing all of them is how a guard gets routed around, and routing
          around the refusal is exactly what killed three seats on 2026-08-21.
        - the reading is a SNAPSHOT: a seat that starts matching between this
          check and the command running is not covered. That race is accepted —
          it is far narrower than the hazard, and no PreToolUse check can close it
    """
    selector = _sweep_selector( args )
    if not selector:
        return []
    return [ pid for pid in pgrep_probe( selector ) if comm_reader( pid ) == CLAUDE_COMM ]


def _guard_disabled( env=None ) -> bool:
    """True iff LUPIN_ALLOW_UNSCOPED_KILL is set truthy (the escape hatch)."""
    env = env if env is not None else os.environ
    return str( env.get( _ENV_FLAG, "" ) ).strip().lower() in _TRUE_VALUES


def _default_comm_reader( pid: str ) -> Optional[ str ]:
    """
    Read /proc/<pid>/comm, or None when the PID is gone or unreadable.

    Requires:
        - pid is a decimal PID string

    Ensures:
        - returns the stripped comm value for a live process
        - returns None on any OSError (dead PID, permission, no procfs)
    """
    try:
        with open( f"/proc/{pid}/comm", "r" ) as handle:
            return handle.read().strip()
    except OSError:
        return None


def _literal_pids( args: str ) -> list:
    """
    The literal decimal PIDs in a `kill` argument list.

    Requires:
        - args is the text following the `kill` verb within one command

    Ensures:
        - returns every bare all-digit token, in order
        - skips flags (`-9`, `-s`, `--signal=9`) and their values, and skips any
          token carrying an expansion or a job spec — those name no PID here
    """
    pids = []
    for token in args.split():
        if token.startswith( "-" ):
            continue
        if token.isdigit():
            pids.append( token )
    return pids


def _claude_pids_targeted( command: str, comm_reader ) -> list:
    """
    The PIDs this command kills that /proc says are live `claude` processes.

    Requires:
        - command is the shell command string
        - comm_reader is a callable( pid ) -> comm string or None

    Ensures:
        - returns the matching PIDs in the order they appear in the command
        - returns [] when no literal PID is targeted, or none of them is a seat
    """
    hits = []
    for match in _KILL_LITERAL_RE.finditer( command ):
        for pid in _literal_pids( match.group( "args" ) ):
            if comm_reader( pid ) == CLAUDE_COMM:
                hits.append( pid )
    return hits


def _pipeline_window( tail: str ) -> str:
    """
    The text a listing's output can still reach: its own pipeline, no further.

    Requires:
        - tail is the command text following an unscoped listing

    Ensures:
        - quoted spans are blanked first, so a `|` inside an argument is not read
          as a pipeline operator
        - the window ends at the first `;`, newline, or `)` — EXCEPT when a
          compound keyword (`while`/`for`/`until`/`do`/`{`) opens before it, in
          which case it runs to `done`/`}` or to the end of the string
    """
    blanked = _QUOTED_RE.sub( lambda m: " " * len( m.group( 0 ) ), tail )
    stop    = re.search( r"[;\n)]", blanked )
    if stop is None:
        return blanked
    head = blanked[ : stop.start() ]
    if not _COMPOUND_RE.search( head ):
        return head
    closer = re.search( r"\bdone\b|\}", blanked )
    return blanked[ : closer.end() ] if closer else blanked


def _loop_variable_fed_by( command: str, listing_end: int ) -> Optional[ str ]:
    """
    The loop variable a `for X in $( <listing> )` binds this listing's output to.

    Requires:
        - command is the shell command string
        - listing_end is the offset just past the matched listing verb

    Ensures:
        - returns the variable name when a `for … in $(`/backtick opens before
          the listing and has not closed before it
        - returns None when no such loop introduces this listing
    """
    for match in _FOR_SUBST_RE.finditer( command, 0, listing_end ):
        between = command[ match.end() : listing_end ]
        if ")" in between or "`" in between:
            continue
        return match.group( "var" )
    return None


def _sweeps_unscoped( command: str ) -> bool:
    """
    True iff the command lists processes fleet-wide and KILLS WHAT IT FINDS.

    A kill that merely appears later is not enough — `kill $!` after a `pgrep -c`
    counter kills a background job the shell already owns, and reading that as a
    sweep is a false positive against real, safe code. The listing's output must
    actually reach the kill: down a pipeline, or through a `for … in $(…)` loop.

    Requires:
        - command is the shell command string

    Ensures:
        - True when an unscoped listing is piped into a kill, or bound by a
          `for … in $( … )` loop whose variable is killed
        - False when every listing is scoped to the caller's own children
        - False for a listing whose output no kill consumes
    """
    for listing in _UNSCOPED_LISTING_RE.finditer( command ):
        tail   = command[ listing.end(): ]
        window = _pipeline_window( tail )
        if _OWN_CHILDREN_RE.search( window ):
            continue
        if _PIPE_RE.search( window ) and _KILL_VERB_RE.search( window ):
            return True
        variable = _loop_variable_fed_by( command, listing.end() )
        if variable and re.search( r"kill\b[^;&|\n]*\$\{?" + re.escape( variable ) + r"\b", command ):
            return True

    # SHAPE D — the listing sits inside a substitution that IS the kill's argument.
    for subst in _KILL_SUBST_RE.finditer( command ):
        inner = subst.group( "subst" )
        if _UNSCOPED_LISTING_RE.search( "\n" + inner ) and not _OWN_CHILDREN_RE.search( inner ):
            return True

    return False


def _sweep_seat_hits( command: str, pgrep_probe, comm_reader ) -> List[ str ]:
    """
    SHAPE C — the live seats a `pkill`/`killall` in this command would kill.

    Requires:
        - command is the shell command string
        - pgrep_probe / comm_reader are the injected probes

    Ensures:
        - returns the `claude` PIDs the first seat-hitting sweep would reach
        - returns [] for a sweep scoped to own children (`pkill -P $$`), for a
          bare `pkill` with no selector, and for any pattern matching no seat
    """
    for sweep in _PATTERN_SWEEP_RE.finditer( command ):
        args = sweep.group( "args" )
        if not args.strip() or _OWN_CHILDREN_RE.search( args ):
            continue
        hits = _seats_a_sweep_would_hit( args, pgrep_probe, comm_reader )
        if hits:
            return hits
    return []


def _deny_reason_for( claude_pids: list ) -> str:
    """Compose the deny text, naming the seats at risk and the substitute."""
    if claude_pids:
        head = (
            f"This `kill` names PID(s) {', '.join( claude_pids )}, which /proc says "
            "are LIVE Claude Code sessions. Killing another seat destroys its "
            "context with no memento and no tombstone."
        )
    else:
        head = (
            "This command lists processes fleet-wide (`ps -e`/`ps aux`/`pgrep`) and "
            "kills what it finds. That sweep sees EVERY seat on the box, not just "
            "yours."
        )
    return (
        f"{head}\n"
        "WHY THE PATTERN DOES NOT HAVE TO LOOK DANGEROUS: a seat runs as "
        "`claude … <its whole spawn brief>`, so its argv contains the brief. A grep "
        "for a test path matches any seat whose brief mentions that path. On "
        "2026-08-21 exactly this took out three seats in 612 ms, including the "
        "author's own — ten seconds after `pkill` had refused the same pattern by "
        "name (row cd332d2b).\n"
        "USE INSTEAD:\n"
        "  · kill YOUR OWN children — `pkill -P $$ -f <pattern>`, or "
        "`pgrep -P $$ -f <pattern> | xargs -r kill`;\n"
        "  · a job you started in this shell — `kill %1`, `kill $!`;\n"
        "  · read first, then kill by a PID you have checked: "
        "`cat /proc/<pid>/comm` must NOT say `claude`.\n"
        "`ps` and `pgrep` with no kill downstream stay allowed. If you have read "
        "the PIDs and confirmed none is a seat, re-run with "
        "LUPIN_ALLOW_UNSCOPED_KILL=1."
    )


def kill_deny_reason(
    tool_name,
    tool_input,
    *,
    enabled     : Optional[ bool ] = None,
    env         = None,
    comm_reader = None,
    pgrep_probe = None,
) -> Optional[ str ]:
    """
    Return a deny-reason string iff a Bash call can signal a seat it does not own.

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - tool_input is the hook payload's tool_input (dict) whose "command"
          key carries the shell command, when present
        - enabled is None (resolved from env) or injected for testing
        - comm_reader is None (real /proc) or injected for testing

    Ensures:
        - None unless the guard is enabled AND tool_name is Bash AND the command
          matches SHAPE A (kills a PID /proc reports as `claude`) or SHAPE B (an
          unscoped listing with a kill downstream)
        - SHAPE A is reported in preference to SHAPE B — it can name the victims
        - None for own-children sweeps and for listings with no kill downstream
        - FAIL-OPEN: any unexpected error → None
    """
    try:
        if enabled is None:
            enabled = not _guard_disabled( env )
        if not enabled:
            return None
        if tool_name not in BASH_TOOL_NAMES:
            return None
        if not isinstance( tool_input, dict ):
            return None
        command = tool_input.get( "command", "" )
        if not isinstance( command, str ) or not command:
            return None
        command     = _strip_heredocs( command )
        reader      = comm_reader if comm_reader is not None else _default_comm_reader
        claude_pids = _claude_pids_targeted( command, reader )
        if claude_pids:
            return _deny_reason_for( claude_pids )
        prober      = pgrep_probe if pgrep_probe is not None else _default_pgrep_probe
        sweep_hits  = _sweep_seat_hits( command, prober, reader )
        if sweep_hits:
            return _deny_reason_for( sweep_hits )
        if _sweeps_unscoped( command ):
            return _deny_reason_for( [] )
        return None
    except Exception:                    # pragma: no cover - fail-open backstop; NOT decorative: a missing `import subprocess` in the probe path landed here on 2026-08-24 and turned every verdict into a silent allow, which is why the guard is replayed against real traffic rather than trusted to its unit tests
        return None


def build_kill_deny_response( reason: str ) -> dict:
    """
    Build the PreToolUse deny envelope (mirrors build_stash_deny_response).

    Ensures:
        - returns { hookSpecificOutput: { hookEventName: "PreToolUse",
          permissionDecision: "deny", permissionDecisionReason: <reason> } }
    """
    return {
        "hookSpecificOutput": {
            "hookEventName"            : "PreToolUse",
            "permissionDecision"       : "deny",
            "permissionDecisionReason" : reason,
        }
    }
