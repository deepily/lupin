"""
Branch-lock guard — the readable PreToolUse layer in front of the branch lock (row 3a592920).

THE LOCK IT PROTECTS: a git reference-transaction hook (planning-is-prompting f820593,
installed in lupin, lupin-mobile and planning-is-prompting on 2026-09-29) refuses to
create a refs/heads/* branch when CLAUDECODE=1, unless BRANCH_GUARD_ALLOW names a
sanctioned creator (the spawner, the reaper). Rick's ruling, row 0a9b1d68: trust WHO is
asking, not what the branch is called.

THE HOLE IT CLOSES: a local hook is a backstop, not a wall. A shell can walk around it
four ways, and the hook's own header names them. This guard denies each one before the
command runs:

  | # | route around the lock                         | what it looks like              |
  |---|-----------------------------------------------|---------------------------------|
  | 1 | claim a sanctioned creator's pass             | `BRANCH_GUARD_ALLOW=x git …`    |
  | 2 | point git at a different hooks directory      | `git -c core.hooksPath=/x …`    |
  | 3 | edit or remove the hook itself                | `cp x .git/hooks/reference-…`   |
  | 4 | stop looking like a Claude session            | `env -u CLAUDECODE git …`       |

WHAT STAYS ALLOWED, because every one of these was measured in real fleet commands
(transcripts, 2026-09-15..29) and a guard that bites reading or writing ABOUT the lock is
a guard people learn to switch off:

  · reading: `ls .git/hooks`, `head .git/hooks/pre-commit`, `git config core.hooksPath`
  · text about the lock: quoted strings, commit messages, and heredoc bodies that feed a
    non-shell program (`cat > f <<EOF`, `git commit -F - <<EOF`)
  · `env -i` probes that run no git (cron-like environment checks)
  · the spawner and the reaper, which set BRANCH_GUARD_ALLOW in a subprocess env from
    Python — that is not a Bash command, so this guard never sees it

THE THREAT MODEL IS ACCIDENT, NOT EVASION, exactly as in stash_guard. Text matching cannot
resolve `v=BRANCH_GUARD_ALLOW; export $v=1`, an eval, a base64 payload, or a Python heredoc
that builds a subprocess env without CLAUDECODE. Nobody reaches for those by accident, and
claiming to catch them would be the defect this module exists to catch. The census
(`branch_guard.py census`) is what catches whatever gets past both layers.

ESCAPE HATCH, for Rick only: a flag in the HOOK PROCESS's own environment, which is set
when a session is launched and which no command typed inside the session can reach. There
is deliberately NO inline form. An earlier cut honoured the flag written as an assignment
in the command itself, and María caught it in review (2026-09-29): that made the hatch
self-service, so any seat could type its way past the lock. The flag's name is also kept
out of the deny text, so a refusal never teaches the reader the way round it.

FAIL-OPEN by contract: any unexpected error returns None, so the guard can never break a
tool call. DEFAULT-ON, for the reason stash_guard gives — a control that has to be switched
on is the courtesy version of itself.
"""
import os
import re
import subprocess
from typing import Iterable, List, Optional, Tuple

from lupin_cli.claude_code.hooks.lib.stash_guard import (
    _PREFIXES,
    _PROGRAM,
    _NESTED_SHELL_RE,
    _normalise_spelling,
)


BASH_TOOL_NAMES = ( "Bash", )

_ENV_FLAG    = "LUPIN_ALLOW_BRANCH_LOCK_BYPASS"
_TRUE_VALUES = ( "1", "true", "on", "yes" )

# A nested `sh -c` payload is scanned as a command of its own; this caps how deep.
_MAX_DEPTH = 3

# How long the hooks-directory lookup may take before the guard gives up on it.
_GIT_CONFIG_TIMEOUT_SECONDS = 2


# ─── Rewriting the command into something a regex can read ─────────────────────────

# A heredoc: the operator, an optionally quoted tag, the rest of that line, then the body
# up to a line holding only the tag. The body is TEXT unless the program reading it is a
# shell or Python, so it is removed before matching — this is what keeps a probe script or
# a test file written through `cat > f <<EOF` from being refused for mentioning the lock.
_HEREDOC_RE = re.compile(
    r"<<-?[ \t]*(?P<q>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=q)(?P<head>[^\n]*)\n"
    r"(?P<body>.*?)\n[ \t]*(?P=tag)[ \t]*(?=\n|$)",
    re.DOTALL,
)
_SHELL_CONSUMER_RE  = re.compile( r"(?:^|[\s/;&|(])(?:ba|z|k|da)?sh(?:\s|$)" )
_PYTHON_CONSUMER_RE = re.compile( r"(?:^|[\s/;&|(])python[0-9.]*(?:\s|$)" )

# BALANCED quoted spans, blanked to the SAME LENGTH so every index in the blanked text
# still points at the same character in the original. That is what lets a segment be cut
# on the blanked text (a `;` inside quotes is not a separator) while its arguments are
# read from the original (a quoted path is still a path).
_QUOTED_SPAN_RE = re.compile( r'"[^"]*"' + "|" + r"'[^']*'" )

# `git -c 'core.hooksPath=/x'` — a quoted -c argument is unquoted before blanking, or the
# key would disappear with the quotes around it.
_QUOTED_DASH_C_RE = re.compile( r"""(-c\s+)(['"])([^'"\n]*)\2""" )

_SEGMENT_SEPARATOR_RE = re.compile( r"[;&|\n(){}]" )


# ─── 1. BRANCH_GUARD_ALLOW ───────────────────────────────────────────────────────────

_ALLOW_NAME = "BRANCH_GUARD_ALLOW"

# A shell assignment (`X=`, `export X=`, `env X=`), a `${X:=…}` default, or an export of
# the bare name. `$X` — a READ — is excluded by the lookbehind.
_ALLOW_SHELL_RE = re.compile(
    rf"(?<![\w$]){_ALLOW_NAME}\s*=(?!=)"
    rf"|\$\{{{_ALLOW_NAME}:?="
    rf"|\b(?:export|declare|typeset|readonly|local)\s+(?:-\w+\s+)*{_ALLOW_NAME}\b"
)
# The same thing spelled in Python, which is how `python -c` would set it.
_ALLOW_PYTHON_RE = re.compile(
    rf"""environ\s*\[\s*['"]?{_ALLOW_NAME}['"]?\s*\]\s*=(?!=)"""
    rf"""|environ\s*\.\s*(?:setdefault|update)\s*\([^)]*{_ALLOW_NAME}"""
    rf"""|putenv\s*\(\s*['"]?{_ALLOW_NAME}\b"""
)


# ─── 2. core.hooksPath ───────────────────────────────────────────────────────────────

# `git -c core.hooksPath=/x`, or the key written with a value anywhere in the command.
_HOOKSPATH_ASSIGN_RE = re.compile( r"(?i)(?<![\w.])(?:core\.)?hookspath\s*=(?!=)" )
# The environment forms of `-c`, which git reads as config.
_HOOKSPATH_ENV_RE = re.compile(
    r"(?i)(?<![\w])GIT_CONFIG_(?:PARAMETERS|KEY_\d+)=\S*hookspath"
)
_GIT_CONFIG_RE = re.compile(
    rf"""
    (?:^|[;&|(){{}}\n])
    {_PREFIXES}
    \s*
    {_PROGRAM}\b
    (?P<pre>(?:\s+(?:-[Cc]\s+[^\s;&|]+|-{{1,2}}[^\s;&|]+))*)
    \s+config\b
    (?P<rest>[^;&|\n]*)
    """,
    re.VERBOSE,
)
# `git config` options that take a separate value, so the value is not read as the key.
_CONFIG_OPTIONS_WITH_VALUE = frozenset( {
    "-f", "--file", "--blob", "--type", "--default", "--comment", "--value",
} )
_CONFIG_SETTING_OPTIONS    = frozenset( { "--add", "--replace-all" } )
_HOOKSPATH_KEY             = "core.hookspath"


# ─── 3. writing into the hooks directory ─────────────────────────────────────────────

# The default hooks directory, in the main checkout or a linked worktree's private dir.
_DEFAULT_HOOKS_DIR_RE = r"\.git/(?:worktrees/[^/\s'\"]+/)?hooks(?![\w.-])"

_WRITE_PROGRAMS = frozenset( {
    "cp", "mv", "ln", "install", "rm", "rmdir", "unlink", "touch", "truncate", "chmod",
    "chown", "chgrp", "tee", "rsync", "dd", "patch", "mkdir", "shred",
} )
_IN_PLACE_EDITORS = frozenset( { "sed", "perl", "ruby" } )
_IN_PLACE_FLAG_RE = re.compile( r"(?:^|\s)-(?:i|[A-Za-z]*i)\S*|--in-place" )
_FIND_WRITE_RE    = re.compile( r"\s-(?:delete|exec|execdir|ok|fprint\w*)\b" )
_CHANGE_DIR       = frozenset( { "cd", "pushd" } )
# A redirection, and the word it writes to.
_REDIRECT_RE = re.compile( r"""(?<![<0-9&])(?:[0-9]?>>?\|?|&>>?)\s*(?P<target>"[^"]*"|'[^']*'|[^\s;&|]+)""" )
# The first program of a segment, past env assignments and transparent wrappers.
_SEGMENT_PROGRAM_RE = re.compile( rf"^{_PREFIXES}\s*(?P<program>[^\s;&|]+)" )


# ─── 4. CLAUDECODE ───────────────────────────────────────────────────────────────────

_CLAUDE_NAME = "CLAUDECODE"

_CLAUDE_ASSIGN_RE = re.compile( rf"(?<![\w$]){_CLAUDE_NAME}=" )
_CLAUDE_UNSET_RE  = re.compile(
    rf"\bunset\s+(?:-\w+\s+)*(?:\w+\s+)*{_CLAUDE_NAME}\b"
    rf"|\bexport\s+-n\s+(?:\w+\s+)*{_CLAUDE_NAME}\b"
    rf"|(?<![\w-])env\b[^;&|\n]*?\s(?:-u\s*|--unset[=\s]\s*){_CLAUDE_NAME}\b"
)
_ENV_CLEAR_RE = re.compile(
    r"(?<![\w-])env\s+(?:[^\s;&|]+\s+)*?(?:-i|-|--ignore-environment)(?=\s|$)"
)
_RUNS_GIT_RE = re.compile( r"(?<![\w.-])git(?![\w.-])" )
_CLAUDE_PYTHON_RE = re.compile(
    rf"""environ\s*\.\s*pop\s*\(\s*['"]?{_CLAUDE_NAME}\b"""
    rf"""|del\s+(?:os\.)?environ\s*\[\s*['"]?{_CLAUDE_NAME}\b"""
    rf"""|environ\s*\[\s*['"]?{_CLAUDE_NAME}['"]?\s*\]\s*=(?!=)"""
    rf"""|unsetenv\s*\(\s*['"]?{_CLAUDE_NAME}\b"""
)


# ─── The deny text ───────────────────────────────────────────────────────────────────

_WHY = (
    "Claude sessions may not create branches (branch lock, Rick's ruling 2026-09-29, "
    "row 0a9b1d68). A git reference-transaction hook enforces it; this guard refuses the "
    "routes around that hook (row 3a592920)."
)
_INSTEAD = (
    "Commit in your seat's tree — a detached HEAD is fine — and your manager lands the work "
    "by merge. If you are only WRITING about the lock, put the text in a file with the Write "
    "tool, or inside a quoted string. If you believe you need one of these routes, ask Rick; "
    "a Claude seat has no way past this guard."
)
DENY_ALLOW_FLAG = (
    f"Setting {_ALLOW_NAME} is denied: it is the pass the spawner and the reaper give their "
    "own subprocesses, and a Claude command that sets it creates a branch the lock was "
    "built to refuse."
)
DENY_HOOKSPATH = (
    "Changing core.hooksPath is denied: pointing git at another hooks directory switches "
    "the branch lock off for that command. Reading it (`git config core.hooksPath`) is fine."
)
DENY_HOOKS_WRITE = (
    "Writing into the git hooks directory is denied: editing, replacing or removing a hook "
    "switches the branch lock off for everyone on this repo. Reading hooks (`ls`, `cat`, "
    "`head`) is fine."
)
DENY_CLAUDECODE = (
    f"Unsetting or overriding {_CLAUDE_NAME} is denied: the branch lock uses it to tell a "
    "Claude session from a human, so removing it makes a Claude command look human. "
    "(`env -i` is allowed when the command runs no git.)"
)


# ─── Helpers ─────────────────────────────────────────────────────────────────────────

def _truthy( value ) -> bool:
    """True iff value reads as an enabling flag value."""
    return str( value ).strip().strip( "'\"" ).lower() in _TRUE_VALUES


def _guard_disabled( env=None ) -> bool:
    """True iff the escape hatch is set truthy in the hook's own environment."""
    env = env if env is not None else os.environ
    return _truthy( env.get( _ENV_FLAG, "" ) )


def _blank_preserving( text ) -> str:
    """
    Ensures:
        - returns text with every balanced quoted span replaced by spaces of the same length
        - len( result ) == len( text ), so indices line up
    """
    return _QUOTED_SPAN_RE.sub( lambda m: " " * len( m.group( 0 ) ), text )


def _split_heredocs( command ) -> Tuple[ str, List[ str ], List[ str ] ]:
    """
    Pull heredoc bodies out of a command.

    Requires:
        - command is a str

    Ensures:
        - returns ( outer, shell_bodies, python_bodies )
        - outer is the command with every heredoc body removed (the operator line stays)
        - shell_bodies are the bodies a shell will run, scanned later as commands
        - python_bodies are the bodies Python will run, scanned later for Python forms
        - a body fed to any other program is text, and is dropped
    """
    shell_bodies  = []
    python_bodies = []

    def _classify( match ):
        line_start = command.rfind( "\n", 0, match.start() ) + 1
        consumer   = command[ line_start:match.start() ] + match.group( "head" )
        if _SHELL_CONSUMER_RE.search( consumer ):
            shell_bodies.append( match.group( "body" ) )
        elif _PYTHON_CONSUMER_RE.search( consumer ):
            python_bodies.append( match.group( "body" ) )
        return "<<" + match.group( "tag" ) + match.group( "head" ) + "\n"

    outer = _HEREDOC_RE.sub( _classify, command )
    return outer, shell_bodies, python_bodies


def _segments( text, blanked ) -> Iterable[ Tuple[ str, str ] ]:
    """
    Cut a command into simple commands.

    Requires:
        - blanked is _blank_preserving( text )

    Ensures:
        - yields ( original, blanked ) slices for each simple command, in order
        - cuts only at separators OUTSIDE quotes
    """
    start = 0
    for sep in _SEGMENT_SEPARATOR_RE.finditer( blanked ):
        yield text[ start:sep.start() ], blanked[ start:sep.start() ]
        start = sep.end()
    yield text[ start: ], blanked[ start: ]


def _segment_program( blanked_segment ) -> Optional[ str ]:
    """The basename of a segment's program, past assignments and wrappers, or None."""
    found = _SEGMENT_PROGRAM_RE.match( blanked_segment )
    if not found:
        return None
    return found.group( "program" ).rsplit( "/", 1 )[ -1 ]


def configured_hooks_dirs( cwd=None, *, runner=None ) -> List[ str ]:
    """
    The hooks directory core.hooksPath names, when it is NOT the default `.git/hooks`.

    Requires:
        - cwd is the session's working directory, or None
        - runner is a subprocess.run-compatible callable, injected for testing

    Ensures:
        - returns [] when core.hooksPath is unset, unreadable, or already under `.git/hooks`
          (the default pattern covers it)
        - otherwise returns the configured path, and its realpath when that differs
        - FAIL-OPEN: any error or timeout returns []
    """
    runner = runner if runner is not None else subprocess.run
    try:
        args = [ "git" ] + ( [ "-C", cwd ] if cwd else [] ) + [ "config", "--get", "core.hooksPath" ]
        result = runner( args, capture_output=True, text=True, timeout=_GIT_CONFIG_TIMEOUT_SECONDS )
        path   = ( result.stdout or "" ).strip() if result.returncode == 0 else ""
        if not path or re.search( _DEFAULT_HOOKS_DIR_RE, path ):
            return []
        paths = [ path.rstrip( "/" ) ]
        real  = os.path.realpath( path ).rstrip( "/" )
        if real not in paths:
            paths.append( real )
        return paths
    except Exception:
        return []


def _hooks_dir_re( extra_dirs ) -> "re.Pattern":
    """The pattern for a hooks-directory path: the default, plus any configured one."""
    alternatives = [ _DEFAULT_HOOKS_DIR_RE ]
    alternatives += [ re.escape( d ) + r"(?![\w.-])" for d in extra_dirs ]
    return re.compile( "|".join( alternatives ) )


def _is_hookspath_set( rest ) -> bool:
    """
    True iff the arguments after `git config` WRITE core.hooksPath.

    Requires:
        - rest is the text following `config` within one command

    Ensures:
        - True for `core.hooksPath <value>`, `set core.hooksPath <value>`, and `--add` /
          `--replace-all` forms
        - False for a read (`git config core.hooksPath`, `--get`, `--list`) or an unset
    """
    tokens      = rest.split()
    positionals = []
    setting     = False
    skip_next   = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token.startswith( "-" ):
            if token in _CONFIG_OPTIONS_WITH_VALUE:
                skip_next = True
            if token in _CONFIG_SETTING_OPTIONS:
                setting = True
            continue
        positionals.append( token )
    if positionals and positionals[ 0 ].lower() == "set":
        positionals = positionals[ 1: ]
        setting     = len( positionals ) >= 2
    if not positionals or positionals[ 0 ].lower() != _HOOKSPATH_KEY:
        return False
    return setting or len( positionals ) >= 2


# ─── The four checks, over one command text ──────────────────────────────────────────

def _check_text( text, hooks_re, depth ) -> Optional[ str ]:
    """
    The deny reason for one command text, or None.

    Requires:
        - text is a command, with its spelling not yet normalised
        - hooks_re matches a hooks-directory path

    Ensures:
        - scans the outer command, then each shell heredoc body and `sh -c` payload as a
          command of its own (to _MAX_DEPTH), and each Python heredoc body for Python forms
        - returns the FIRST deny reason found, else None
    """
    if depth > _MAX_DEPTH:
        return None

    outer, shell_bodies, python_bodies = _split_heredocs( text )
    normal  = _QUOTED_DASH_C_RE.sub( r"\1\3", _normalise_spelling( outer ) )
    blanked = _blank_preserving( normal )

    # 1. BRANCH_GUARD_ALLOW
    if _ALLOW_SHELL_RE.search( blanked ) or _ALLOW_PYTHON_RE.search( normal ):
        return DENY_ALLOW_FLAG

    # 2. core.hooksPath
    if _HOOKSPATH_ASSIGN_RE.search( blanked ) or _HOOKSPATH_ENV_RE.search( normal ):
        return DENY_HOOKSPATH
    for match in _GIT_CONFIG_RE.finditer( blanked ):
        rest = normal[ match.start( "rest" ):match.end( "rest" ) ]
        if _is_hookspath_set( rest ):
            return DENY_HOOKSPATH

    # 3 and 4 are judged one simple command at a time.
    inside_hooks_dir = False
    for original, blank in _segments( normal, blanked ):
        program     = _segment_program( blank )
        names_hooks = bool( hooks_re.search( original ) )

        # 3. writing into the hooks directory
        if program in _CHANGE_DIR:
            inside_hooks_dir = names_hooks
            continue
        writes = (
            program in _WRITE_PROGRAMS
            or ( program in _IN_PLACE_EDITORS and bool( _IN_PLACE_FLAG_RE.search( blank ) ) )
            or ( program == "find" and bool( _FIND_WRITE_RE.search( blank ) ) )
        )
        if writes and ( names_hooks or inside_hooks_dir ):
            return DENY_HOOKS_WRITE
        # Matched on the ORIGINAL so a quoted target is still read, but only where the
        # `>` itself sits outside quotes — a `>` inside a quoted string redirects nothing.
        for redirect in _REDIRECT_RE.finditer( original ):
            if blank[ redirect.start() ] != original[ redirect.start() ]:
                continue
            if inside_hooks_dir or hooks_re.search( redirect.group( "target" ) ):
                return DENY_HOOKS_WRITE

        # 4. CLAUDECODE
        for assign in _CLAUDE_ASSIGN_RE.finditer( blank ):
            # `CLAUDECODE=1` restates the truth and is harmless; any other value hides it.
            value = original[ assign.end(): ].split( None, 1 )
            if not value or value[ 0 ].strip( "'\"" ) != "1":
                return DENY_CLAUDECODE
        if _CLAUDE_UNSET_RE.search( blank ):
            return DENY_CLAUDECODE
        if _ENV_CLEAR_RE.search( blank ) and _RUNS_GIT_RE.search( original ):
            return DENY_CLAUDECODE

    if _CLAUDE_PYTHON_RE.search( normal ):
        return DENY_CLAUDECODE

    # The nested commands: a shell heredoc body, and each `sh -c` payload.
    nested = list( shell_bodies )
    nested += [ m.group( "payload" ) for m in _NESTED_SHELL_RE.finditer( outer ) if m.group( "payload" ) ]
    for inner in nested:
        reason = _check_text( inner, hooks_re, depth + 1 )
        if reason:
            return reason

    for body in python_bodies:
        if _ALLOW_PYTHON_RE.search( body ):
            return DENY_ALLOW_FLAG
        if _CLAUDE_PYTHON_RE.search( body ):
            return DENY_CLAUDECODE

    return None


# ─── Public API ──────────────────────────────────────────────────────────────────────

def branch_lock_deny_reason(
    tool_name,
    tool_input,
    *,
    cwd        = None,
    enabled    : Optional[ bool ] = None,
    env        = None,
    hooks_dirs : Optional[ List[ str ] ] = None,
) -> Optional[ str ]:
    """
    Return a deny-reason string iff a Bash call would route around the branch lock.

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - tool_input is the hook payload's tool_input (dict) with a "command" key
        - cwd is the payload's working directory, used to read core.hooksPath
        - enabled, env and hooks_dirs are None in production and injected for testing

    Ensures:
        - None unless ALL hold: the guard is enabled, tool_name is Bash, and the command
          matches one of the four routes
        - the escape hatch is read ONLY from the hook process's environment; a hatch
          written into the command is ignored, so the route is still denied
        - the reason names the route and what to do instead
        - FAIL-OPEN: any unexpected error returns None
    """
    try:
        if enabled is None:
            enabled = not _guard_disabled( env )
        if not enabled:
            return None
        if tool_name not in BASH_TOOL_NAMES or not isinstance( tool_input, dict ):
            return None
        command = tool_input.get( "command", "" )
        if not isinstance( command, str ) or not command:
            return None
        if hooks_dirs is None:
            hooks_dirs = configured_hooks_dirs( cwd )
        reason = _check_text( command, _hooks_dir_re( hooks_dirs ), depth=0 )
        if reason is None:
            return None
        return f"{reason}\n{_WHY}\n{_INSTEAD}"
    except Exception:                    # pragma: no cover - fail-open backstop: every statement above is total over the validated inputs, so no input reaches it; kept because a hot-path guard must never raise
        return None


def build_branch_lock_deny_response( reason: str ) -> dict:
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
