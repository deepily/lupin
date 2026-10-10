"""
Denies Bash process sweeps that can signal another seat's Claude CLI.

Why a pattern that looks like a test path matches a seat: a seat launches as
`claude --model ... <its entire spawn brief>`. So the brief is in its argv.
Any brief that mentions `src/tests/unit` makes that seat match a grep aimed at pytest.
The pattern does not have to be careless to be lethal; it only has to be a phrase
somebody wrote down. The CLI's own shadow-`pkill` function refuses a pattern that
matches the CLI's own process.
It does not see a hand-built `ps | grep | while read p; do kill $p; done`.
One such sweep stopped three worker seats within 612 ms.

What is denied, and nothing wider:
  - Shape A: `kill <pid>` (any signal) naming a PID that /proc says is a live `claude` process.
    It is checked against /proc at hook time, so it is a fact about the box.
  - Shape B: a system-wide process listing (`ps -e`, `ps aux`, `pgrep`) feeding a kill
    downstream in the same command.
  - Shape C: a `pkill` or `killall` pattern with no own-children scoping.
    The shadow `pkill` refuses only a pattern matching your own pid.
    A pattern that matches another seat and not you goes through it untouched.
    It also refuses a pattern matching a process that is provably not the caller's;
    the ownership rule sits above `_ProcFs`.
  - Shape D: `kill $(pgrep ...)`, identical in behaviour to the piped form B denies.
    It is refused before any PID is known. That is the only moment it can still be
    refused, since the PIDs are not in the command text.

Heredoc bodies are stripped before matching: a file that documents a sweep is data, as this module's test file is.

What stays allowed: any listing with no kill downstream, and killing your own children.
A pattern sweep is allowed while every process it matches is yours.
Own-children forms: `pkill -P $$`, `pgrep -P $$ | xargs kill`, `ps --ppid $$`, `kill $!`, `kill %1`.
Read-only `ps` and `pgrep` stay allowed; they are how you find out what is running.

This runs inside the hot-path PreToolUse hook (every tool call, every session), so two
requirements are not negotiable:
  - The guard fails open: any error means allow (return None), so it never breaks a tool call.
  - The escape hatch is LUPIN_ALLOW_UNSCOPED_KILL=1. It disables the guard for a session that
    must sweep, after it has read the PIDs and confirmed none is a seat.

The guard is on by default. The earlier rule was advice ("narrow the pattern"), and advice
did not survive a hurry.
"""
import os
import re
import shlex
import signal
import subprocess
from bisect import bisect_left, bisect_right
from typing import List, Optional, Tuple


# Bash tool name as it appears in the PreToolUse hook payload.
BASH_TOOL_NAMES = ( "Bash", )

_ENV_FLAG    = "LUPIN_ALLOW_UNSCOPED_KILL"
_TRUE_VALUES = ( "1", "true", "on", "yes" )

# 🔴 EVERY COMMAND-POSITION PATTERN BELOW GOES THROUGH THIS SPAN (row 084adbaf).
#
# Until 2026-08-31 the patterns anchored the program directly to a command slot,
# so ANYTHING sitting between the two defeated the whole guard. MEASURED, one
# variable, with a positive control established per shape first:
#
#   shape                     bare   FOO=1   FOO=    sudo    env   nohup
#   A  literal kill <pid>     DENY   allow   allow   allow   allow  allow
#   B  the real incident      DENY   allow   allow   allow   allow  allow
#   C  pkill -f <pattern>     DENY   allow   allow   DENY    allow  allow
#   D  kill $(pgrep …)        DENY   allow   allow   DENY    allow  allow
#
# The row that filed this called it an env-assignment quirk. It is a CLASS: an env
# assignment, `env`, `nohup`, `sudo`, any transparent wrapper. All four shapes, not
# one — including the literal kill that names a live seat by pid.
#
# ⚠️ THE TELL THAT IT WAS THE MATCHER AND NOT THE HATCH: `LUPIN_ALLOW_UNSCOPED_KILL=0`
# — the FALSY spelling — also allowed. A working hatch refuses that. The guard was
# simply not seeing the command, exactly as stash_guard was not seeing its own.
#
# ⚠️ AND THE GUARD ALREADY HALF-KNEW: `_PATTERN_SWEEP_RE` and `_KILL_SUBST_RE`
# carried `(?:sudo\s+)?` while the literal and listing patterns did not. Two of four
# modelling one prefix is how this stayed invisible — the shapes could not be
# compared because they did not agree on what a command looked like. The span is
# shared so they cannot drift apart again.
#
# THE LOOKAHEAD IS NOT DECORATION. `\b` after the assignment cannot match between the
# `=` of an empty value and a following space (both non-word), which is the defect
# that let `FOO= ` through in the other two guards. But simply DROPPING it lets the
# greedy value backtrack INTO the program name, so `FOO=barkill 123` would match a
# `kill` that is part of a value — a false allow traded for a false deny. Pinning the
# value to a real token end does neither.
# Horizontal whitespace, or a backslash-newline continuation. A bare newline ends a command and is
# a command start of its own, so no prefix may cross one: a run of newlines would be re-scanned
# from each of them, and the guard went quadratic on it (measured: 8000 newlines took 15 s).
_WS = r"(?:[ \t]|\\\n)"
_WRAPPERS = r"(?:env|command|builtin|exec|sudo|doas|nohup|time|nice|stdbuf|setsid|ionice|unbuffer|taskset|chrt)"
# A wrapper may carry options, each with at most one value: `nice -n 5`, `sudo -u root`,
# `env -i`, `ionice -c3`. A value is never a wrapper, a verb or an assignment, so every
# word has exactly one reading and the pattern cannot backtrack exponentially: a command
# of fifty nested wrappers took more than ten seconds before this was pinned.
_WRAPPER_VALUE    = (
    r"(?!(?:[\w./+-]*/)?(?:" + _WRAPPERS[ 3: -1 ] + r"|pkill|killall|kill)\b)"
    r"(?![A-Za-z_][A-Za-z0-9_]*=)[^\s;&|()`-][^\s;&|()`]*"
)
_WRAPPER_OPERANDS = r"(?:" + _WS + r"+-[^\s;&|()`]+(?:" + _WS + r"+" + _WRAPPER_VALUE + r")?)*"
# `timeout` takes a duration (and options) before the command it wraps, so it is
# not a bare word like the others: `timeout 5 pkill ...`, `timeout -s KILL 5 pkill ...`.
_TIMEOUT_SPAN = (
    r"timeout(?:" + _WS + r"+(?:-[sk]" + _WS + r"+\w+|-\S+))*" + _WS + r"+\d+(?:\.\d*)?[smhd]?(?=\s)"
)
# A command word is judged by its basename: `/usr/bin/pkill`, `\pkill`, `"pkill"` all name pkill.
_WORD_PRE  = r"""\\?["']?(?:[\w./+~-]*/)?"""
_WORD_POST = r"""["']?(?![\w./-])"""

_PREFIXES = rf"(?:{_WS}*(?:[A-Za-z_][A-Za-z0-9_]*=[^\s;&|]*(?=[\s;&|]|$)|{_TIMEOUT_SPAN}|{_WORD_PRE}{_WRAPPERS}{_WORD_POST}{_WRAPPER_OPERANDS}))*"

# Where a command can start: a line, a separator, a group, a keyword, a negation or a case arm.
_CMD_START = r"(?:^|[;&|(`{)]|\n|(?<![^\s;&|(`{])!|\b(?:do|then|else|elif|if|while|until)\b)"


# A signal given as an option: `-9`, `-KILL`, `-SIGTERM`. The names come from the
# platform's own table, so `-P`, `-U` and `-G` stay options that select processes.
_SIGNAL_NAMES = frozenset(
    name[ 3: ] for name in signal.Signals.__members__ if name.startswith( "SIG" )
) | { "RTMIN", "RTMAX" }
_SIGNAL_FLAG_RE = re.compile( r"-(?:\d+|(?:SIG)?[A-Z][A-Z0-9]*(?:[+-]\d+)?)" )


def _is_signal_option( token: str ) -> bool:
    """True iff the token is a signal given as an option: `-9`, `-KILL`, `-SIGHUP`."""
    if not _SIGNAL_FLAG_RE.fullmatch( token ):
        return False
    body = token[ 1: ]
    if body.isdigit():
        return True
    body = re.sub( r"[+-]\d+$", "", body )
    return ( body[ 3: ] if body.startswith( "SIG" ) else body ) in _SIGNAL_NAMES


# What /proc/<pid>/comm reads for a Claude Code CLI process.
CLAUDE_COMM = "claude"

# `kill` in COMMAND POSITION with at least one literal decimal PID. Signal flags
# (`-9`, `-KILL`, `-s TERM`, `--signal=9`) sit between the verb and the targets,
# so they are skipped rather than parsed. Job specs (`%1`) and expansions (`$!`,
# `$p`) carry no literal digits and never match here — SHAPE A is only ever
# about a PID the author typed.
_KILL_LITERAL_RE = re.compile(
    r"""
    """ + _CMD_START + r"""       # command position
    """ + _PREFIXES + r"""       # env assignments / transparent wrappers (row 084adbaf)
    """ + _WS + r"""*
    """ + _WORD_PRE + r"""kill""" + _WORD_POST + r"""   # the verb (not pkill/killall — different shapes)
    (?P<args>(?:""" + _WS + r"""+[^\s;&|)`\n]+)*)   # the remainder of THIS command only
    """,
    re.VERBOSE,
)

# A process listing that is NOT scoped to the caller's own children. `ps` needs
# an all-processes selector; `pgrep` is fleet-wide unless told otherwise.
_UNSCOPED_LISTING_RE = re.compile(
    r"""
    """ + _CMD_START + r"""
    """ + _PREFIXES + r"""
    """ + _WS + r"""*
    """ + _WORD_PRE + r"""
    (?:
        ps\b(?=(?:""" + _WS + r"""+[^\s;&|)`\n]+)*""" + _WS + r"""+-?[aAe])   # ps -e / ps -A / ps aux / ps ax
      | pgrep\b
    )
    """,
    re.VERBOSE,
)

# Scoping that makes a listing safe: it can only ever return our own children.
# Only the shell's own pid scopes a listing to its children. A literal pid (`-P 1`, the
# subreaper every orphan reparents to) scopes it to somebody else's.
_OWN_PID = r"""["']?(?:\$\$|\$\{\$\}|\$PPID|\$\{PPID\}|\$BASHPID|\$\{BASHPID\}|\$!|\$\{!\})["']?"""
_OWN_CHILDREN_RE = re.compile( rf"(?:-P|--parent|--ppid)[ \t]*=?[ \t]*{_OWN_PID}" )

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
# An argument is a run of quoted spans and unquoted characters that end the command.
# A quoted span may hold `|`, `;`, `&`, `)` or a backtick: those are data inside it.
# A backslash takes the next character (`foo\ bar`). A lone quote with no partner falls
# through to the plain character class.
_ARG_CHAR = r"""(?:\\.|"[^"]*"|'[^']*'|[^\s;&|)`\n])"""
_PATTERN_SWEEP_RE = re.compile(
    rf"{_CMD_START}{_PREFIXES}{_WS}*{_WORD_PRE}(?P<verb>pkill|killall){_WORD_POST}(?P<args>(?:{_WS}+(?!#){_ARG_CHAR}+)*)"
)

# One raw (still quoted) argument, and the two redirection shapes. A redirection is
# the shell's, and pkill never sees it: `2>/dev/null`, `>/dev/null`, `2>&1`, `< in`.
_RAW_ARG_RE        = re.compile( r"""(?:\\.|"[^"]*"|'[^']*'|[^\s"'])+""" )
_REDIRECT_ATTACHED = re.compile( r"(?:\d*|&)(?:>>?|<{1,3})&?\S+" )
_REDIRECT_BARE     = re.compile( r"(?:\d*|&)(?:>>?|<{1,3})&?" )

# SHAPE D — a substitution feeding a kill DIRECTLY: `kill $(pgrep …)` has the
# exact semantics of `pgrep … | xargs kill`, which SHAPE B already denies.
# Denying one and not the other draws an arbitrary line through identical
# behaviour.
_KILL_SUBST_RE = re.compile(
    rf"{_CMD_START}{_PREFIXES}{_WS}*{_WORD_PRE}kill(?:all)?{_WORD_POST}[^;&|\n]*?"
    r"(?:\$\(|`)(?P<subst>[^)`]*)"
)

# `sudo` can sit before `xargs` OR between it and the kill (`xargs sudo kill`),
# so it is optional in BOTH slots rather than only the first.
_KILL_VERB_RE = re.compile(
    rf"{_CMD_START}{_PREFIXES}{_WS}*(?:xargs{_WS}+(?:-[^\s]+{_WS}+)*{_PREFIXES}{_WS}*)?{_WORD_PRE}kill(?:all)?{_WORD_POST}"
)


# A heredoc body is DATA, not commands. Writing a file that documents a sweep —
# this module's own test file does exactly that — must not read as running one.
# Caught by the guard denying its own test file's heredoc on first wiring.
_HEREDOC_RE = re.compile( r"<<-?\s*(['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)\1" )


def _strip_heredocs( command: str ) -> str:
    """
    Remove heredoc bodies, keeping the lines that carry real commands.

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


def _drop_redirections( raw_tokens: List[ str ] ) -> List[ str ]:
    """
    The raw arguments with shell redirections removed.

    Requires:
        - raw_tokens are whole arguments with their quotes still on

    Ensures:
        - an attached form (`2>/dev/null`, `>out`, `2>&1`, `<in`) is dropped
        - a bare operator (`>`, `>>`, `2>`, `<`, `>&`) is dropped with the token after it
        - a quoted argument is never a redirection, whatever it starts with
        - every other argument is kept in order
    """
    kept = []
    skip = False
    for token in raw_tokens:
        if skip:
            skip = False
            continue
        if _REDIRECT_BARE.fullmatch( token ):
            skip = True
            continue
        if _REDIRECT_ATTACHED.fullmatch( token ):
            continue
        kept.append( token )
    return kept


# Options of pkill (procps-ng) mapped to the pgrep spelling. Selecting options pass
# through; options that only change output or signalling are dropped.
_PKILL_VALUED   = frozenset( "gGOPstuUFr" )      # selecting options that take a value
_PKILL_DROP_VAL = frozenset( "dq" )              # delimiter and queue value: not selectors
_PKILL_DROP     = frozenset( "celawVh" )         # output, signalling, help
_PKILL_LONG     = {
    "parent": "P", "pgroup": "g", "group": "G", "session": "s", "terminal": "t",
    "euid": "u", "uid": "U", "pidfile": "F", "runstates": "r", "older": "O",
    "full": "f", "exact": "x", "ignore-case": "i", "newest": "n", "oldest": "o",
    "inverse": "v", "logpidfile": "L",
    "count": "c", "echo": "e", "list-name": "l", "list-full": "a", "lightweight": "w",
    "version": "V", "help": "h", "delimiter": "d", "queue": "q",
}
_PKILL_LONG_PLAIN = frozenset( ( "ns", "nslist" ) )   # long-only, valued, kept as given

# Options of killall (psmisc). Names are matched exactly against the command name.
# The kernel keeps 15 characters of a command name, so a longer name is probed on its first 15.
_COMM_LENGTH = 15
_KILLALL_VALUED   = frozenset( "suyoZn" )
_KILLALL_DROP     = frozenset( "egilqvwV" )
_KILLALL_LONG     = {
    "signal": "s", "user": "u", "younger-than": "y", "older-than": "o", "context": "Z",
    "ns": "n", "exact": "e", "process-group": "g", "interactive": "i", "list": "l",
    "quiet": "q", "verbose": "v", "wait": "w", "version": "V",
    "ignore-case": "I", "regexp": "r",
}


def _split_args( args: str ) -> List[ str ]:
    """
    The words of a sweep's argument text, shell-aware, with redirections removed.

    Ensures:
        - a quoted span or a backslash-escaped character stays inside one word
        - redirections are dropped; unbalanced quotes fall back to a whitespace split
    """
    args = args.replace( "\\\n", " " )
    try:
        shlex.split( args )
        words = []
        for raw in _drop_redirections( _RAW_ARG_RE.findall( args ) ):
            words.extend( shlex.split( raw ) )
        return words
    except ValueError:
        return args.split()


def _pkill_selector( words: List[ str ] ) -> List[ str ]:
    """
    The pgrep selector equivalent to a pkill argument list.

    Ensures:
        - a signal option (`-9`, `-KILL`, `--signal X`) is dropped
        - `-P`, `-U`, `-G`, `-u`, `-g`, `-s`, `-t`, `-F`, `-r`, `-O` keep their value, attached or separate
        - output-only options (`-e -l -a -c -w`) and `-q`/`-d` with their values are dropped
        - a word no table knows is kept, so pgrep decides and the guard refuses what it rejects
        - after `--` every word is a pattern
    """
    kept  = []
    index = 0
    while index < len( words ):
        word  = words[ index ]
        index += 1
        if word == "--":
            if words[ index: ]:
                kept.append( "--" )
                kept.extend( words[ index: ] )
            break
        if word.startswith( "--" ):
            name, equals, value = word[ 2: ].partition( "=" )
            if name == "signal":
                if not equals and index < len( words ):
                    index += 1
                continue
            if name in _PKILL_LONG_PLAIN:
                if not equals and index < len( words ):
                    value  = words[ index ]
                    index += 1
                kept.extend( [ f"--{name}", value ] )
                continue
            short = _PKILL_LONG.get( name )
            if short is None:
                kept.append( word )
                continue
            if short in _PKILL_DROP:
                continue
            if short in _PKILL_DROP_VAL or short in _PKILL_VALUED:
                if not equals and index < len( words ):
                    value  = words[ index ]
                    index += 1
                if short in _PKILL_VALUED:
                    kept.extend( [ f"-{short}", value ] )
                continue
            kept.append( f"-{short}" )
            continue
        if word.startswith( "-" ) and len( word ) > 1:
            if _is_signal_option( word ):
                continue
            cluster = word[ 1: ].lstrip( "0123456789" )          # `-9f`: a signal, then flags
            position = 0
            while position < len( cluster ):
                char      = cluster[ position ]
                position += 1
                if char in _PKILL_VALUED or char in _PKILL_DROP_VAL:
                    value = cluster[ position: ]
                    if not value and index < len( words ):
                        value  = words[ index ]
                        index += 1
                    if char in _PKILL_VALUED:
                        kept.extend( [ f"-{char}", value ] )
                    break
                if char in _PKILL_DROP:
                    continue
                kept.append( f"-{char}" )
            continue
        kept.append( word )
    return kept


def _killall_selectors( words: List[ str ] ) -> List[ List[ str ] ]:
    """
    One pgrep selector per name in a killall argument list.

    Ensures:
        - a name is an exact command-name match (`-x`), unless `-r` makes it a regexp
        - `-I` adds `-i`; `-u USER` is kept; signal, age, context, namespace and
          output options are dropped with their values
        - a killall with no name gives no selector
    """
    exact   = True
    ignore  = False
    user    = None
    names   = []
    index   = 0
    options_done = False
    while index < len( words ):
        word  = words[ index ]
        index += 1
        if options_done or not word.startswith( "-" ) or word == "-":
            names.append( word )
            continue
        if word == "--":
            options_done = True
            continue
        if word.startswith( "--" ):
            name, equals, value = word[ 2: ].partition( "=" )
            short = _KILLALL_LONG.get( name )
            if short is None:
                continue
            if short in _KILLALL_VALUED and not equals and index < len( words ):
                value  = words[ index ]
                index += 1
            if short == "u":
                user = value
            elif short == "I":
                ignore = True
            elif short == "r":
                exact = False
            continue
        if _is_signal_option( word ):
            continue
        cluster  = word[ 1: ]
        position = 0
        while position < len( cluster ):
            char      = cluster[ position ]
            position += 1
            if char in _KILLALL_VALUED:
                value = cluster[ position: ]
                if not value and index < len( words ):
                    value  = words[ index ]
                    index += 1
                if char == "u":
                    user = value
                break
            if char == "I":
                ignore = True
            elif char == "r":
                exact = False
    selectors = []
    for name in names:
        selector = []
        if exact:
            selector.append( "-x" )
            name = name[ :_COMM_LENGTH ]
        if ignore:
            selector.append( "-i" )
        if user:
            selector.extend( [ "-u", user ] )
        selector.append( name )
        selectors.append( selector )
    return selectors


def _has_expansion( word: str ) -> bool:
    """
    True iff a raw (still quoted) shell word holds an expansion the guard cannot read.

    Ensures:
        - `$NAME`, `${..}`, `$(..)`, `$1`, `$$`, `$'..'`, `$".."` and backticks count, quoted or not
        - a single-quoted span, a backslash-escaped `$`, and a `$` that ends the word or
          is followed by anything else (a regexp anchor) do not
    """
    in_single = False
    in_double = False
    index     = 0
    while index < len( word ):
        char = word[ index ]
        if char == "\\" and not in_single:
            index += 2
            continue
        if in_single:
            in_single = char != "'"
        elif char == "'" and not in_double:
            in_single = True
        elif char == '"':
            in_double = not in_double
        elif char == "`":
            return True
        elif char == "$":
            following = word[ index + 1 : index + 2 ]
            if following and ( following.isalnum() or following in "_{(@*#?!$" or ( following in "'\"" and not in_double ) ):
                return True
        index += 1
    return False


def _sweep_selectors( verb: str, args: str ) -> List[ List[ str ] ]:
    """
    The pgrep selectors equivalent to a `pkill`/`killall` argument list.

    Requires:
        - verb is `pkill` or `killall`; args is the text following the verb

    Ensures:
        - returns [] when nothing selects (a bare verb, only a signal), so the
          guard has nothing to probe
        - a pkill gives at most one selector; a killall gives one per name
        - raises `_SelectorRejected` when a word holds a variable, a substitution or an
          ANSI-C string: its value is unknown to a guard that runs before the shell does
        - the split is shell-aware and redirection-free (see `_split_args`)
    """
    for raw in _drop_redirections( _RAW_ARG_RE.findall( args ) ):
        if _has_expansion( raw ):
            raise _SelectorRejected( [ raw ], None, "expansion" )
    words = _split_args( args )
    if verb == "killall":
        return _killall_selectors( words )
    selector = _pkill_selector( words )
    return [ selector ] if selector else []


def _sweep_selector( args: str, verb: str = "pkill" ) -> List[ str ]:
    """The first selector of `_sweep_selectors`, or [] when there is none."""
    selectors = _sweep_selectors( verb, args )
    return selectors[ 0 ] if selectors else []


class _SelectorRejected( Exception ):
    """pgrep rejected the guard's selector, so the sweep's reach cannot be named."""

    def __init__( self, selector, exit_code, why="pgrep" ):
        super().__init__( f"{why} rejected {selector!r} (exit {exit_code})" )
        self.selector  = list( selector )
        self.exit_code = exit_code
        self.why       = why


def _log_probe_failure( selector: List[ str ], reason: str, exit_code: Optional[ int ] ) -> None:
    """
    Record that the pgrep probe could not answer, so failures can be counted.

    Requires:
        - selector is the argument list handed to pgrep, reason a short phrase

    Ensures:
        - appends one `kill_guard_probe_failed` line to the hook event stream
          (`<root>/io/claude_code_hooks/logs/hook-events.jsonl`)
        - never raises: a log that cannot be written must not break a tool call
    """
    try:
        from lupin_cli.claude_code.hooks.lib.hook_common import log_to_stream
        log_to_stream(
            "kill_guard_probe_failed", None,
            extra={ "selector": list( selector ), "exit_code": exit_code, "reason": reason },
        )
    except Exception:                    # pragma: no cover - logging backstop; the stream writer already swallows its own errors
        pass


def _default_pgrep_probe( selector: List[ str ] ) -> List[ str ]:
    """
    The PIDs `pgrep <selector>` reports right now.

    Requires:
        - selector is the argument list to hand pgrep

    Ensures:
        - returns the matching PIDs as strings, or [] when pgrep matches nothing
        - exit 1 is "no match" and is silent
        - exit 2 (a usage error: the selector is not one pgrep accepts) writes one log
          line and raises `_SelectorRejected`, so the caller refuses the sweep
        - exit 3 or more, a timeout, or a pgrep that cannot run returns [] and writes
          one log line: a probe that cannot answer must not manufacture a refusal,
          and must not pass for "no match" without a trace
    """
    if not selector:
        return []
    try:
        result = subprocess.run(
            [ "pgrep", *selector ], capture_output=True, text=True, timeout=5
        )
    except subprocess.TimeoutExpired:
        _log_probe_failure( selector, "pgrep timeout after 5s", None )
        return []
    except ( OSError, subprocess.SubprocessError ) as error:
        _log_probe_failure( selector, f"pgrep could not run: {error}", None )
        return []
    if result.returncode == 2:
        _log_probe_failure( selector, "pgrep rejected the selector", 2 )
        raise _SelectorRejected( selector, 2 )
    if result.returncode >= 3:
        _log_probe_failure( selector, "pgrep failed", result.returncode )
        return []
    return [ line.strip() for line in result.stdout.split( "\n" ) if line.strip().isdigit() ]


def _seats_a_sweep_would_hit( args: str, pgrep_probe, comm_reader, verb: str = "pkill" ) -> List[ str ]:
    """
    The live `claude` PIDs a `pkill`/`killall` pattern currently matches.

    Requires:
        - args is the sweep's argument list
        - pgrep_probe( selector ) -> list of PID strings
        - comm_reader( pid ) -> comm string or None

    Ensures:
        - returns the matching PIDs whose /proc comm is `claude`, in pgrep order
        - returns [] when the pattern matches no seat. This is the claude-only view,
          used when the payload carries no cwd to judge ownership by; with a cwd the
          caller is `_sweep_hits_with_owner`, which also refuses a match that is
          provably not the caller's
        - the reading is a snapshot: a seat that starts matching between this
          check and the command running is not covered. That race is accepted;
          it is far narrower than the risk, and no PreToolUse check can close it
    """
    hits = []
    for selector in _sweep_selectors( verb, args ):
        hits.extend( pid for pid in pgrep_probe( selector ) if comm_reader( pid ) == CLAUDE_COMM )
    return hits


# 🔴 CLOSING THE BYPASS CLOSED THE DOCUMENTED HATCH WITH IT, and this repairs that.
#
# The deny message has always ended "re-run with LUPIN_ALLOW_UNSCOPED_KILL=1" — the
# INLINE form. A PreToolUse hook is a SEPARATE PROCESS reading its OWN environment,
# and an inline `VAR=1 cmd` prefix belongs to a command that HAS NOT RUN YET, so
# `_guard_disabled` could never see it. The instruction appeared to work only because
# the env assignment pushed the program out of command position — indistinguishable
# from the bypass this row exists to close.
#
# MEASURED both directions across that change, and the middle row is the proof it was
# never the hatch:
#
#   case                          BEFORE the fix   AFTER the fix (no carve-out)
#   the documented inline hatch        allow            DENY
#   the hatch with a FALSY value       allow            DENY   <- a real hatch refuses this
#   flag merely ECHOED first           DENY             DENY
#
# A falsy value opening a hatch is not a hatch. So the "allow" was the matcher
# failing, and normalising the prefix span correctly removed it — along with the only
# way the documented instruction ever worked. stash_guard learned this same lesson the
# expensive way and carries the same carve-out; this is copied from there deliberately.
_INLINE_FLAG_RE = re.compile(
    rf"{_CMD_START}"
    rf"(?:{_WS}*(?:[A-Za-z_][A-Za-z0-9_]*=[^\s;&|]*(?=[\s;&|]|$)|{_TIMEOUT_SPAN}|{_WORD_PRE}{_WRAPPERS}{_WORD_POST}{_WRAPPER_OPERANDS}))*?"
    rf"{_WS}*{_ENV_FLAG}=(?P<value>[^\s;&|]*)"
)


def _hatch_in_prefix( command ) -> bool:
    """
    True iff the hatch flag is assigned truthy in a command-position prefix.

    Requires:
        - command is the raw shell command string

    Ensures:
        - reads the flag from the command, never from os.environ — see the note
          above for why an env read cannot honour an inline prefix
        - only an env-assignment prefix at a command slot counts, so a flag that
          merely appears elsewhere in the line (`echo FLAG=1; pkill …`) does not
          unlock the sweep that follows it
        - a FALSY value does not open it — the property whose absence proved the
          old "allow" was the matcher rather than the hatch
        - never raises
    """
    if not command: return False

    found = _INLINE_FLAG_RE.search( command )
    if not found: return False

    return found.group( "value" ).strip().strip( "'\"" ).lower() in _TRUE_VALUES


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


_STOP_RE        = re.compile( r"[;\n)]" )
_CLOSER_RE      = re.compile( r"\bdone\b|\}" )
_CLOSE_CHARS_RE = re.compile( r"[)`]" )


_TAIL_BUDGET_FACTOR = 16
_TAIL_BUDGET_FLOOR  = 16384


class _CommandIndex:
    """
    One pass over a command that answers every window question in logarithmic time.

    Each listing once sliced and searched the rest of the command, which is quadratic in
    the number of listings. Here every position is found once, then looked up by bisection.
    """

    def __init__( self, command: str ):
        """
        Index every position the window questions need, in one pass.

        Requires:
            - command is the shell command string

        Ensures:
            - quoted spans are blanked, so a `|` or `;` inside an argument is data
            - every list below is sorted by position
        """
        self.command     = command
        self.spans       = [ match.span() for match in _QUOTED_RE.finditer( command ) ]
        self.span_starts = [ start for start, _ in self.spans ]
        blanked          = _QUOTED_RE.sub( lambda match: " " * len( match.group( 0 ) ), command )
        self.blanked     = blanked
        self.stops       = [ match.start() for match in _STOP_RE.finditer( blanked ) ]
        self.compounds   = [ match.start() for match in _COMPOUND_RE.finditer( blanked ) ]
        closers          = list( _CLOSER_RE.finditer( blanked ) )
        self.closer_starts = [ match.start() for match in closers ]
        self.closer_ends   = [ match.end() for match in closers ]
        self.pipes       = [ match.start() for match in _PIPE_RE.finditer( blanked ) ]
        self.own         = [ match.start() for match in _OWN_CHILDREN_RE.finditer( blanked ) ]
        self.verbs       = [ match.end() for match in _KILL_VERB_RE.finditer( blanked ) ]
        fors             = list( _FOR_SUBST_RE.finditer( command ) )
        self.for_ends    = [ match.end() for match in fors ]
        self.for_vars    = [ match.group( "var" ) for match in fors ]
        self.closes      = [ match.start() for match in _CLOSE_CHARS_RE.finditer( command ) ]

    def inside_quote( self, position: int ) -> bool:
        """True iff `position` falls strictly inside a quoted span, so a tail cannot start there."""
        found = bisect_right( self.span_starts, position ) - 1
        if found < 0:
            return False
        start, end = self.spans[ found ]
        return start < position < end

    def window_end( self, start: int ) -> int:
        """
        The offset where the pipeline that begins at `start` ends.

        Ensures:
            - the first `;`, newline or `)` ends it, unless a compound keyword opens first, in
              which case it runs to the next `done` or `}` or to the end of the command
        """
        found = bisect_left( self.stops, start )
        if found == len( self.stops ):
            return len( self.blanked )
        stop     = self.stops[ found ]
        compound = bisect_left( self.compounds, start )
        if compound == len( self.compounds ) or self.compounds[ compound ] >= stop:
            return stop
        closer = bisect_left( self.closer_starts, start )
        return self.closer_ends[ closer ] if closer < len( self.closer_ends ) else len( self.blanked )

    def loop_variable( self, listing_end: int ) -> Optional[ str ]:
        """
        The variable of the `for X in $(` loop that this listing's output feeds, or None.

        Ensures:
            - a loop counts when it opens at or before the listing and nothing closed it since
            - of several, the earliest is returned
        """
        found      = bisect_left( self.closes, listing_end ) - 1
        last_close = self.closes[ found ] if found >= 0 else -1
        loop       = bisect_right( self.for_ends, last_close )
        if loop < len( self.for_ends ) and self.for_ends[ loop ] <= listing_end:
            return self.for_vars[ loop ]
        return None

    @staticmethod
    def _within( positions: List[ int ], low: int, high: int ) -> bool:
        """True iff some position p has low <= p < high."""
        found = bisect_left( positions, low )
        return found < len( positions ) and positions[ found ] < high

    def window_scoped( self, low: int, high: int ) -> bool:
        """True iff the window [low, high) names the shell's own children."""
        return self._within( self.own, low, high )

    def window_reaches_a_kill( self, low: int, high: int ) -> bool:
        """True iff the window holds a pipe and a kill verb: the listing feeds a kill."""
        if not self._within( self.pipes, low, high ):
            return False
        found = bisect_right( self.verbs, low )
        return found < len( self.verbs ) and self.verbs[ found ] <= high


def _pipeline_window( tail: str ) -> str:
    """
    The text a listing's output can still reach: its own pipeline, no further.

    Requires:
        - tail is the command text following an unscoped listing

    Ensures:
        - quoted spans are blanked first, so a `|` inside an argument is not read
          as a pipeline operator
        - the window ends at the first `;`, newline, or `)`, except when a
          compound keyword (`while`/`for`/`until`/`do`/`{`) opens before it, in
          which case it runs to `done`/`}` or to the end of the string
    """
    index = _CommandIndex( tail )
    return index.blanked[ : index.window_end( 0 ) ]


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
    return _CommandIndex( command ).loop_variable( listing_end )


def _sweeps_unscoped( command: str ) -> bool:
    """
    True iff the command lists processes fleet-wide and kills what it finds.

    A kill that merely appears later is not enough: `kill $!` after a `pgrep -c` counter kills a job the shell owns.
    Reading that as a sweep is a false positive against safe code.
    The listing's output must reach the kill: down a pipeline, or through a `for … in $(…)` loop.

    Requires:
        - command is the shell command string

    Ensures:
        - True when an unscoped listing is piped into a kill, or bound by a
          `for … in $( … )` loop whose variable is killed
        - False when every listing is scoped to the caller's own children
        - False for a listing whose output no kill consumes
    """
    index   = _CommandIndex( command )
    checked = {}
    # A listing that sits inside a quoted span has its tail paired afresh, which costs a pass over
    # that tail. The budget keeps the total linear: a command that spends all of it is refused,
    # because the guard can no longer say what it does in bounded time.
    budget  = _TAIL_BUDGET_FACTOR * len( command ) + _TAIL_BUDGET_FLOOR
    for listing in _UNSCOPED_LISTING_RE.finditer( command ):
        end = listing.end()
        if index.inside_quote( end ):
            budget -= len( command ) - end
            if budget < 0:
                return True
            view, low = _CommandIndex( command[ end: ] ), 0     # the tail pairs its quotes afresh
        else:
            view, low = index, end
        high = view.window_end( low )
        if view.window_scoped( low, high ):
            continue
        if view.window_reaches_a_kill( low, high ):
            return True
        variable = index.loop_variable( end )
        if variable is None:
            continue
        if variable not in checked:
            checked[ variable ] = bool(
                re.search( r"kill\b[^;&|\n]*\$\{?" + re.escape( variable ) + r"\b", command )
            )
        if checked[ variable ]:
            return True

    # SHAPE D — the listing sits inside a substitution that IS the kill's argument.
    for subst in _KILL_SUBST_RE.finditer( command ):
        inner = subst.group( "subst" )
        if _UNSCOPED_LISTING_RE.search( "\n" + inner ) and not _OWN_CHILDREN_RE.search( inner ):
            return True

    return False


def _sweep_seat_hits( command: str, pgrep_probe, comm_reader ) -> List[ str ]:
    """
    Shape C: the live seats a `pkill`/`killall` in this command would kill.

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
        hits = _seats_a_sweep_would_hit( args, pgrep_probe, comm_reader, sweep.group( "verb" ) )
        if hits:
            return hits
    return []


# Ownership. Which processes a pattern reaches is only half the question; whose they
# are is the other half. Every read below answers None when the process cannot be
# read, and None is never evidence of anything.
#
# A process is the caller's iff it descends from the caller's `claude`, or its cwd is
# inside the caller's tree and that tree is a linked worktree. The main checkout is
# shared by several seats, so a cwd there proves nothing. A pattern kill from one
# seat's tree has stopped a unit tier running in another worktree.
_MAX_ANCESTOR_HOPS = 64
_MAX_FOREIGN_NAMED = 5


class _ProcFs:
    """The two /proc reads the ownership rule needs, behind one seam so tests can fake them."""

    def ppid( self, pid ) -> Optional[ int ]:
        """
        The parent pid of `pid`, or None when it is gone or unreadable.

        Requires:
            - pid is an int or a decimal string

        Ensures:
            - parses the field after the final `)`, because comm may hold spaces and parentheses
            - returns None on OSError or a malformed line, never raises
        """
        try:
            with open( f"/proc/{pid}/stat", "r" ) as handle:
                line = handle.read()
            return int( line[ line.rindex( ")" ) + 2 : ].split()[ 1 ] )
        except ( OSError, ValueError, IndexError ):
            return None

    def cwd( self, pid ) -> Optional[ str ]:
        """The working directory of `pid`, or None when it is gone or unreadable (other uid, zombie)."""
        try:
            return os.readlink( f"/proc/{pid}/cwd" )
        except OSError:
            return None


def _nearest_claude( start: int, comm_reader, proc ) -> Optional[ int ]:
    """
    The pid of the nearest `claude` at or above `start`, or None.

    Requires:
        - start is a pid, comm_reader( pid_str ) -> comm or None, proc has ppid( pid )

    Ensures:
        - walks at most 64 hops and stops at init or an unreadable parent
        - returns None when no ancestor reads `claude`
    """
    current = start
    for _ in range( _MAX_ANCESTOR_HOPS ):
        if comm_reader( str( current ) ) == CLAUDE_COMM:
            return current
        parent = proc.ppid( current )
        if parent is None or parent <= 1:
            return None
        current = parent
    return None


class _Ownership:
    """Answers, for a pid, whether it is provably not the caller's."""

    def __init__( self, caller_pid: int, tree_root: str, tree_is_worktree: bool, proc ):
        self.caller_pid       = caller_pid
        self.tree_root        = tree_root
        self.tree_is_worktree = tree_is_worktree
        self.proc             = proc

    def _descends_from_caller( self, pid ) -> Optional[ bool ]:
        """True/False when the walk reached an answer; None when a link was unreadable."""
        current = int( pid )
        for _ in range( _MAX_ANCESTOR_HOPS ):
            if current == self.caller_pid:
                return True
            parent = self.proc.ppid( current )
            if parent is None:
                return None
            if parent <= 1:
                return False
            current = parent
        return False

    def foreign_cwd( self, pid ) -> Optional[ str ]:
        """
        The pid's cwd when it is provably not the caller's, else None.

        Ensures:
            - None for a descendant of the caller's claude
            - None when any read fails: not evidence, so not counted
            - None for a cwd inside the tree when the tree is a linked worktree
            - the cwd string otherwise
        """
        descends = self._descends_from_caller( pid )
        if descends is None or descends:
            return None
        cwd = self.proc.cwd( pid )
        if cwd is None:
            return None
        inside = cwd == self.tree_root or cwd.startswith( self.tree_root + os.sep )
        if inside and self.tree_is_worktree:
            return None
        return cwd


def _tree_root_of( cwd: str ) -> Tuple[ Optional[ str ], bool ]:
    """
    The nearest directory at or above `cwd` holding a `.git`, and whether it is a worktree.

    Ensures:
        - ( None, False ) when no `.git` exists above cwd
        - the flag is True iff `.git` is a plain file (a linked worktree), False for a directory
    """
    current = os.path.realpath( cwd )
    while True:
        marker = os.path.join( current, ".git" )
        if os.path.exists( marker ):
            return current, os.path.isfile( marker )
        parent = os.path.dirname( current )
        if parent == current:
            return None, False
        current = parent


def _resolve_ownership( cwd, caller_pid, comm_reader, proc ) -> Optional[ _Ownership ]:
    """
    Build the ownership view, or None when the caller or its tree cannot be established.

    Requires:
        - cwd is the payload's working directory (any value; non-strings and "" give None)
        - caller_pid is the caller's claude pid, or None to find it from this process

    Ensures:
        - None means "skip the ownership check", never "deny"
    """
    if not isinstance( cwd, str ) or not cwd:
        return None
    if caller_pid is None:
        caller_pid = _nearest_claude( os.getpid(), comm_reader, proc )
    if caller_pid is None:
        return None
    root, is_worktree = _tree_root_of( cwd )
    if root is None:
        return None
    return _Ownership( caller_pid, root, is_worktree, proc )


def _sweep_hits_with_owner( command: str, pgrep_probe, comm_reader, owner: _Ownership ) -> Tuple[ list, list ]:
    """
    Shape C with ownership: ( claude pids, foreign rows ) for the first sweep that hits.

    Requires:
        - command is the shell command string; owner answers foreign_cwd( pid )

    Ensures:
        - claude pids win: when a sweep matches a live claude the foreign list is []
        - a foreign row is ( pid, comm, cwd )
        - ( [], [] ) for scoped sweeps, empty selectors, and matches that are all the caller's
    """
    for sweep in _PATTERN_SWEEP_RE.finditer( command ):
        args = sweep.group( "args" )
        if not args.strip() or _OWN_CHILDREN_RE.search( args ):
            continue
        pids = []
        for selector in _sweep_selectors( sweep.group( "verb" ), args ):
            pids.extend( pid for pid in pgrep_probe( selector ) if pid not in pids )
        claude = [ pid for pid in pids if comm_reader( pid ) == CLAUDE_COMM ]
        if claude:
            return claude, []
        foreign = []
        for pid in pids:
            cwd = owner.foreign_cwd( pid )
            if cwd is not None:
                foreign.append( ( pid, comm_reader( pid ) or "?", cwd ) )
        if foreign:
            return [], foreign
    return [], []


def _rejected_deny_reason( rejected: "_SelectorRejected" ) -> str:
    """Compose the deny text for a sweep whose selector pgrep rejected."""
    shown = " ".join( shlex.quote( word ) for word in rejected.selector )
    if rejected.why == "expansion":
        return (
            f"This `pkill`/`killall` holds an expansion the guard cannot read: `{rejected.selector[ 0 ]}`. "
            "A variable, a command substitution or a `$'..'` string has no value yet when this check "
            "runs, so the guard cannot say what the pattern or option value reaches.\n"
            "USE INSTEAD:\n"
            "  · write the literal value (`-u rruiz`, not `-u $USER`);\n"
            "  · kill YOUR OWN children — `pkill -P $$ -f <pattern>`;\n"
            "  · read first, then kill by a PID you have checked: `cat /proc/<pid>/comm` and "
            "`readlink /proc/<pid>/cwd` must show a process that is yours.\n"
            "If you have read the PIDs and confirmed none is another seat's, re-run with "
            "LUPIN_ALLOW_UNSCOPED_KILL=1."
        )
    return (
        "This `pkill`/`killall` could not be checked: pgrep rejected the selector the guard "
        f"built from it (`pgrep {shown}`, exit {rejected.exit_code}). A selector pgrep cannot "
        "read is a command whose reach the guard cannot name, and a seat's unit tier has "
        "been stopped by exactly such a sweep (row 7479a389).\n"
        "Usual causes: a variable or backtick in the pattern, two patterns, or an option "
        "pgrep does not take.\n"
        "USE INSTEAD:\n"
        "  · kill YOUR OWN children — `pkill -P $$ -f <pattern>`, or "
        "`pgrep -P $$ -f <pattern> | xargs -r kill`;\n"
        "  · read first, then kill by a PID you have checked: `cat /proc/<pid>/comm` and "
        "`readlink /proc/<pid>/cwd` must show a process that is yours.\n"
        "If you have read the PIDs and confirmed none is another seat's, re-run with "
        "LUPIN_ALLOW_UNSCOPED_KILL=1."
    )


def _foreign_deny_reason( foreign: list ) -> str:
    """Compose the deny text for a pattern that reaches processes the caller does not own."""
    shown = foreign[ : _MAX_FOREIGN_NAMED ]
    lines = [ f"  pid {pid}  comm={comm}  cwd={cwd}" for pid, comm, cwd in shown ]
    more  = len( foreign ) - len( shown )
    if more > 0:
        lines.append( f"  ... and {more} more" )
    listing = "\n".join( lines )
    return (
        "This `pkill`/`killall` pattern matches process(es) that this session did not "
        "start and that are not in this tree:\n"
        f"{listing}\n"
        "They belong to another seat or another job. On 2026-10-09 "
        "`pkill -f \"pytest src/tests/unit/\"` from one seat's tree stopped a unit tier "
        "running in another worktree (row 7479a389).\n"
        "USE INSTEAD:\n"
        "  · kill YOUR OWN children — `pkill -P $$ -f <pattern>`, or "
        "`pgrep -P $$ -f <pattern> | xargs -r kill`;\n"
        "  · a job you started in this shell — `kill %1`, `kill $!`;\n"
        "  · read first, then kill by a PID you have checked: `cat /proc/<pid>/comm` and "
        "`readlink /proc/<pid>/cwd` must show a process that is yours.\n"
        "If you have read the PIDs and confirmed none is another seat's, re-run with "
        "LUPIN_ALLOW_UNSCOPED_KILL=1."
    )


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
    cwd         = None,
    proc        = None,
    caller_pid  = None,
) -> Optional[ str ]:
    """
    Return a deny-reason string iff a Bash call can signal a seat it does not own.

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - tool_input is the hook payload's tool_input (dict) whose "command"
          key carries the shell command, when present
        - enabled is None (resolved from env) or injected for testing
        - comm_reader is None (real /proc) or injected for testing
        - cwd is the payload's working directory; None skips the ownership check
        - proc is None (real /proc) or an object with ppid( pid ) and cwd( pid )
        - caller_pid is None (found by walking up from this process) or the caller's claude pid

    Ensures:
        - None unless the guard is enabled and tool_name is Bash and the command
          matches Shape A (kills a PID /proc reports as `claude`), Shape B (an
          unscoped listing with a kill downstream), Shape C (a pkill/killall
          pattern reaching a live `claude`, or, given a cwd, any process that is
          provably not the caller's) or Shape D (a kill fed by a listing)
        - Shape A is reported in preference to Shape B — it can name the victims
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
        # The hatch, read from the COMMAND. Placed after the heredoc strip so a flag
        # quoted inside a heredoc body is data and cannot unlock anything.
        if _hatch_in_prefix( command ):
            return None
        reader      = comm_reader if comm_reader is not None else _default_comm_reader
        claude_pids = _claude_pids_targeted( command, reader )
        if claude_pids:
            return _deny_reason_for( claude_pids )
        prober      = pgrep_probe if pgrep_probe is not None else _default_pgrep_probe
        owner       = None
        if _PATTERN_SWEEP_RE.search( command ):
            owner = _resolve_ownership( cwd, caller_pid, reader, proc if proc is not None else _ProcFs() )
        try:
            if owner is not None:
                sweep_hits, foreign = _sweep_hits_with_owner( command, prober, reader, owner )
                if foreign:
                    return _foreign_deny_reason( foreign )
            else:
                sweep_hits = _sweep_seat_hits( command, prober, reader )
        except _SelectorRejected as rejected:
            return _rejected_deny_reason( rejected )
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
