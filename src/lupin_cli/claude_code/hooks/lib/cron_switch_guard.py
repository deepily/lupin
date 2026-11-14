"""
Deny a tool call that changes a scheduled job's on/off switch in `lupin-app.ini`.

Each job in `src/conf/job-registry.json` has one key in the main configuration file, written
`cron job <job> enabled = true|false`. Rick flips it through the admin endpoint, which writes the
line from Python and records who flipped it in `cron-job-switches-state.json`. Every seat runs as
the same Unix user, so no file permission stops a seat from flipping the line by hand instead.
This guard is the preventive control at the tool call. `cron_switch_commit_check` is the second one.
The drift flag on the accordion row is the detective control.

What is denied:

  - Edit, MultiEdit and Write on a file named `lupin-app.ini`, when the result would change
    or remove a switch line, or add one that the registry does not allow. The edit is applied to the file's current text and the two sets
    of switch lines are compared. So an edit to any other key is allowed. So is an edit that
    only carries a switch line along as unchanged context
  - a Bash command that writes a file named `lupin-app.ini`. That covers a redirect into it
    and `tee`. It covers an in-place editor (`sed -i`, `perl -i`, `awk -i inplace`, ed, ex, vi).
    It covers a copy or move onto it, `git checkout` or `git restore` of it, `rm` or `truncate`.
    It covers a Python payload that opens it for writing. Text matching cannot see which line a Bash write changes.
    So every Bash write to the file is denied, and the deny text points to the Edit tool
  - a Python payload that calls a switch writer (`write_switch`, `write_bool_to_disk`) on a
    `cron job` key, which bypasses the endpoint without naming the file

A line may be added when its job is in the `job-registry.json` beside the file and has no line yet.
The value must be true or false. That is how a registry job's key is first created.
The same rule covers a single `echo '<line>' >> lupin-app.ini`. It is the commit check's rule.

What stays allowed is reading the file (`cat`, `grep`, `git diff`, `git show`). So is text that
only mentions it: quoted strings, commit messages, heredoc bodies fed to a non-shell program.
So is the endpoint itself, which writes from the server process and passes through no tool call.

There is no escape hatch. Every seat runs as one Unix user, so a variable cannot be Rick's alone.
Rick needs none. He flips switches through the admin endpoint, and this guard binds only tool calls.

The threat model is accident, not evasion, as in stash_guard. Text matching cannot resolve a
variable that holds the path, an eval, or a base64 payload.

The guard fails closed for a tool call that touches a file named `lupin-app.ini`.
An unexpected error there denies the call. Every other call fails open and returns None.
Before this change it failed open for both.
"""
import json
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple

from lupin_cli.claude_code.hooks.lib.stash_guard import _NESTED_SHELL_RE, _normalise_spelling
from lupin_cli.claude_code.hooks.lib.branch_lock_guard import (
    _blank_preserving,
    _segment_program,
    _segments,
    _split_heredocs,
)


FILE_TOOL_NAMES = ( "Edit", "MultiEdit", "Write" )
BASH_TOOL_NAMES = ( "Bash", )

INI_BASENAME      = "lupin-app.ini"
REGISTRY_FILENAME = "job-registry.json"

# One switch line. The job id is one token; the value is everything after the equals sign.
_SWITCH_LINE_RE = re.compile(
    r"^[^\S\n]*cron[^\S\n]+job[^\S\n]+(?P<job>\S+)[^\S\n]+enabled[^\S\n]*=[^\S\n]*(?P<value>[^\n]*?)[^\S\n]*$",
    re.MULTILINE,
)

# A path naming the file: any directory prefix, then the basename, then a token end.
_INI_TOKEN = r"['\"]?[^\s;&|<>'\"]*lupin-app\.ini['\"]?(?=[\s;&|<>)]|$)"

_REDIRECT_INTO_RE = re.compile( rf"(?:^|[^<>&0-9])[0-9]?>{{1,2}}\|?[^\S\n]*{_INI_TOKEN}" )

# `echo '<one switch line>' >> <path>lupin-app.ini`, the one shell write the guard can judge.
_APPEND_RE = re.compile(
    r"""^\s*(?:echo|printf)\s+(?:-\w+\s+)*(?P<q>['"])(?P<text>[^'"]*)(?P=q)\s*>>\s*(?P<path>[^\s;&|<>'"]*lupin-app\.ini)\s*$"""
)

_IN_PLACE_PROGRAMS  = frozenset( { "sed", "gsed", "perl", "ruby" } )
_EDITOR_PROGRAMS    = frozenset( { "ed", "ex", "vi", "vim", "nvim", "nano", "emacs" } )
_DESTINATION_PROGS  = frozenset( { "cp", "mv", "install", "rsync", "ln" } )
_REMOVER_PROGRAMS   = frozenset( { "rm", "unlink", "truncate", "shred" } )
_PYTHON_PROGRAM_RE  = re.compile( r"^python[0-9.]*$" )

_GIT_RESTORE_RE = re.compile( r"\bgit\b(?:\s+-[Cc]\s+\S+|\s+--?[^\s]+)*\s+(?:checkout|restore|rm|mv)\b" )
_AWK_INPLACE_RE = re.compile( r"(?:^|\s)-i\s*inplace\b" )
_DD_OUTPUT_RE   = re.compile( rf"\bof={_INI_TOKEN}" )

# Python forms that write a file. A bare `.replace(` is a string method, so only `os.replace` counts.
_PY_WRITE_RE = re.compile(
    r"""\.write(?:_text|_bytes)?\s*\("""
    r"""|\bopen\s*\([^)]*?['"](?:[rwa]\+|[wax])[bt]?['"]"""
    r"""|\bos\s*\.\s*(?:replace|rename|remove|unlink|truncate)\s*\("""
    r"""|\bshutil\s*\.\s*(?:copy|copy2|copyfile|move)\s*\("""
)
_PY_SWITCH_WRITER_RE = re.compile( r"\b(?:write_switch|write_bool_to_disk|write_value_to_disk)\s*\(" )

_MAX_DEPTH = 3


def switch_lines( text ) -> Dict[ str, Tuple[ str, ... ] ]:
    """
    Every switch line in a configuration text, by job.

    Requires:
        - text is a str

    Ensures:
        - returns { job: ( value, ... ) } with the values in file order, so a duplicated key
          shows as two values and differs from the same key held once
        - values are stripped and lowercased; `True` and `true` are the same switch
        - never raises
    """
    found: Dict[ str, List[ str ] ] = {}
    for match in _SWITCH_LINE_RE.finditer( text ):
        found.setdefault( match.group( "job" ), [] ).append( match.group( "value" ).strip().lower() )
    return { job: tuple( values ) for job, values in found.items() }


def changed_jobs( before, after ) -> List[ str ]:
    """
    The jobs whose switch lines differ between two configuration texts.

    Requires:
        - before and after are str

    Ensures:
        - returns the sorted job ids that were added, removed, duplicated or given a new value
        - returns [] when every switch line is the same in both
    """
    old = switch_lines( before )
    new = switch_lines( after )
    return sorted( job for job in set( old ) | set( new ) if old.get( job ) != new.get( job ) )


def registry_jobs_beside( ini_path ) -> Optional[ set ]:
    """
    The job ids of the registry that sits beside a configuration file.

    Requires:
        - ini_path is the path of a lupin-app.ini

    Ensures:
        - returns the ids listed in `job-registry.json` in the same folder
        - returns None when that file is missing or unreadable, so no added line is allowed
        - never raises
    """
    try:
        with open( os.path.join( os.path.dirname( ini_path ), REGISTRY_FILENAME ), "r", encoding="utf-8" ) as handle:
            return { entry[ "job" ] for entry in json.load( handle )[ "jobs" ] }
    except ( OSError, ValueError, KeyError, TypeError ):
        return None


def refused_changes( before, after, registry ) -> List[ str ]:
    """
    The jobs whose switch lines changed in a way the guard refuses.

    Requires:
        - before and after are str
        - registry is the set of registry job ids, or None when it is unknown

    Ensures:
        - a changed value, a removed line and a duplicated line are refused
        - a line added for a job in the registry, once, with the value true or false, is allowed:
          that is how a registry job's key is first created
        - returns the sorted job ids refused, [] when every change is allowed
    """
    old = switch_lines( before )
    new = switch_lines( after )
    refused = []
    for job in changed_jobs( before, after ):
        added = job not in old and len( new.get( job, () ) ) == 1 and new[ job ][ 0 ] in ( "true", "false" )
        if added and registry is not None and job in registry:
            continue
        refused.append( job )
    return refused


def _is_ini_path( path ) -> bool:
    """True iff path names a file called lupin-app.ini, in any folder."""
    return isinstance( path, str ) and os.path.basename( path ) == INI_BASENAME


def _read_text( path ) -> Optional[ str ]:
    """The file's text, "" when it does not exist, None when it cannot be read."""
    try:
        with open( path, "r", encoding="utf-8" ) as handle:
            return handle.read()
    except FileNotFoundError:
        return ""
    except ( OSError, UnicodeDecodeError ):
        return None


def _apply_edit( text, old, new, replace_all ) -> Optional[ str ]:
    """The text after one Edit, or None when old is absent (the Edit tool itself will refuse)."""
    if not isinstance( old, str ) or not isinstance( new, str ) or old not in text:
        return None
    return text.replace( old, new ) if replace_all else text.replace( old, new, 1 )


def _file_tool_jobs( tool_name, tool_input ) -> List[ str ]:
    """
    The jobs whose switch a file tool call would change.

    Requires:
        - tool_name is one of FILE_TOOL_NAMES and tool_input names a lupin-app.ini file

    Ensures:
        - applies the call to the file's current text and compares switch lines before and after
        - when the file cannot be read, compares the call's own old and new text instead, and
          treats any switch line in either as a change when the two differ
        - returns [] when no switch changes
    """
    path    = tool_input.get( "file_path", "" )
    current = _read_text( path )

    if tool_name == "Write":
        content = tool_input.get( "content", "" )
        if not isinstance( content, str ):
            return []
        return refused_changes( current or "", content, registry_jobs_beside( path ) )

    edits = tool_input.get( "edits" ) if tool_name == "MultiEdit" else [ tool_input ]
    if not isinstance( edits, list ):
        return []

    if current is None:
        jobs = set()
        for edit in edits:
            if isinstance( edit, dict ):
                jobs.update( refused_changes( str( edit.get( "old_string", "" ) ), str( edit.get( "new_string", "" ) ), registry_jobs_beside( path ) ) )
        return sorted( jobs )

    after = current
    for edit in edits:
        if not isinstance( edit, dict ):
            return []
        applied = _apply_edit( after, edit.get( "old_string" ), edit.get( "new_string" ), bool( edit.get( "replace_all" ) ) )
        if applied is None:
            return []
        after = applied
    return refused_changes( current, after, registry_jobs_beside( path ) )


def _tokens( segment ) -> List[ str ]:
    """The whitespace-separated words of a segment, each with surrounding quotes removed."""
    return [ token.strip( "'\"" ) for token in segment.split() ]


def _is_allowed_append( original ) -> bool:
    """
    True iff one command appends a single new switch line for a registry job.

    Requires:
        - original is one simple command

    Ensures:
        - True only for `echo` or `printf` of one `cron job <job> enabled = true|false` line,
          appended with `>>` to a lupin-app.ini whose neighbouring registry lists the job
          and whose current text holds no line for it
        - False for anything else, including a changed value, a second line and an unreadable file
    """
    match = _APPEND_RE.match( original )
    if match is None:
        return False
    text = match.group( "text" ).strip()
    line = _SWITCH_LINE_RE.match( text )
    if line is None or line.group( 0 ) != text or line.group( "value" ).strip().lower() not in ( "true", "false" ):
        return False
    path     = match.group( "path" )
    registry = registry_jobs_beside( path )
    current  = _read_text( path )
    return registry is not None and current is not None and line.group( "job" ) in registry and line.group( "job" ) not in switch_lines( current )


def _segment_writes_ini( original, blanked ) -> bool:
    """
    True iff one simple command writes a lupin-app.ini file.

    Requires:
        - original is one simple command and blanked is the same text with quoted spans blanked

    Ensures:
        - True for a redirect into the file, tee, an in-place editor, an interactive editor,
          a copy or move whose destination is the file, `dd of=`, git checkout, restore, rm or mv
          of the file, and rm, unlink, truncate or shred of it
        - False when the file is only read or only named inside a quoted argument of a reader
    """
    if INI_BASENAME not in original:
        return False
    if _is_allowed_append( original ):
        return False
    if _REDIRECT_INTO_RE.search( original ):
        return True
    program = _segment_program( blanked )
    if program is None:
        return False
    tokens   = _tokens( original )
    ini_args = [ token for token in tokens if _is_ini_path( token ) ]
    if not ini_args:
        return False
    if program == "tee" or program in _EDITOR_PROGRAMS or program in _REMOVER_PROGRAMS:
        return True
    if program in _IN_PLACE_PROGRAMS:
        return any( token.startswith( "--in-place" ) or ( token.startswith( "-" ) and not token.startswith( "--" ) and "i" in token ) for token in tokens )
    if program in ( "awk", "gawk" ):
        return bool( _AWK_INPLACE_RE.search( blanked ) )
    if program in _DESTINATION_PROGS:
        operands = [ token for token in tokens[ 1: ] if not token.startswith( "-" ) ]
        return bool( operands ) and _is_ini_path( operands[ -1 ] )
    if program == "dd":
        return bool( _DD_OUTPUT_RE.search( original ) )
    if program == "git":
        return bool( _GIT_RESTORE_RE.search( blanked ) )
    return False


def _python_writes_switch( code ) -> bool:
    """True iff Python source writes a lupin-app.ini file or calls a switch writer on a cron key."""
    if INI_BASENAME in code and _PY_WRITE_RE.search( code ):
        return True
    return bool( _PY_SWITCH_WRITER_RE.search( code ) ) and "cron job" in code


def _bash_reason( command, depth ) -> Optional[ str ]:
    """
    The deny reason for one shell text, scanning heredoc bodies and nested shells too.

    Ensures:
        - returns DENY_BASH_WRITE or DENY_PYTHON_WRITE for the first finding, or None
        - recurses into shell heredocs and `sh -c` payloads up to _MAX_DEPTH
    """
    outer, shell_bodies, python_bodies = _split_heredocs( command )
    normal  = _normalise_spelling( outer )
    blanked = _blank_preserving( normal )

    for original, blank in _segments( normal, blanked ):
        if _segment_writes_ini( original, blank ):
            return DENY_BASH_WRITE
        # Any word of the segment, so `uv run python -c` and `.venv/bin/python3 -c` count too.
        runs_python = any( _PYTHON_PROGRAM_RE.match( os.path.basename( word ) ) for word in blank.split() )
        if runs_python and _python_writes_switch( original ):
            return DENY_PYTHON_WRITE

    for body in python_bodies:
        if _python_writes_switch( body ):
            return DENY_PYTHON_WRITE

    if depth < _MAX_DEPTH:
        nested: Iterable[ str ] = list( shell_bodies ) + [ m.group( "payload" ) for m in _NESTED_SHELL_RE.finditer( outer ) ]
        for text in nested:
            reason = _bash_reason( text, depth + 1 )
            if reason:
                return reason
    return None


_WHY = (
    "Each `cron job <job> enabled` line in lupin-app.ini is a switch Rick flips through the "
    "scheduled-jobs accordion. The endpoint writes the line and records who flipped it in "
    "cron-job-switches-state.json; a hand edit has no record, shows as drift on the accordion, "
    "and the pre-commit check refuses to commit it."
)
_INSTEAD = (
    "To turn a job on or off, ask Rick to flip it in the accordion. To edit any other key in "
    "lupin-app.ini, use the Edit tool: it compares the switch lines before and after, and "
    "allows every change that leaves them as they are."
)

DENY_BASH_WRITE = (
    "Denied: this command writes lupin-app.ini from the shell. A shell write cannot be checked "
    "line by line, so every one is refused."
)
DENY_UNJUDGED = (
    "Denied: this call touches lupin-app.ini and the guard could not judge it, so it is refused "
    "rather than allowed."
)
DENY_PYTHON_WRITE = (
    "Denied: this Python code writes lupin-app.ini, or calls a switch writer on a `cron job` key, "
    "outside the endpoint."
)


def _deny_file_tool( jobs ) -> str:
    """The deny reason for a file tool call that changes the named jobs' switches."""
    return f"Denied: this edit changes the on/off switch of {', '.join( jobs )} in lupin-app.ini."


def _touches_ini( tool_name, tool_input ) -> bool:
    """
    True iff a tool call names a file called lupin-app.ini.

    Ensures:
        - True for a file tool whose path is one, and for a Bash command that contains the name
        - False for anything else, and for input it cannot read
        - never raises
    """
    try:
        if tool_name in FILE_TOOL_NAMES:
            return _is_ini_path( tool_input.get( "file_path" ) )
        if tool_name in BASH_TOOL_NAMES:
            return INI_BASENAME in tool_input.get( "command", "" )
    except ( AttributeError, TypeError ):
        return False
    return False


def cron_switch_deny_reason( tool_name, tool_input ) -> Optional[ str ]:
    """
    Return a deny reason iff a tool call would change a cron job switch by hand.

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - tool_input is the hook payload's tool_input (dict)

    Ensures:
        - None unless the call is an Edit, MultiEdit or Write that changes a switch line of a
          lupin-app.ini file, or a Bash command that writes such a file or writes a switch from Python
        - a line added for a registry job that has none is not refused
        - the reason says what was refused, why, and what to do instead
        - fail-closed for a call that touches lupin-app.ini: an unexpected error returns DENY_UNJUDGED
        - fail-open for every other call: an unexpected error returns None
    """
    try:
        if not isinstance( tool_input, dict ):
            return None
        if tool_name in FILE_TOOL_NAMES:
            if not _is_ini_path( tool_input.get( "file_path" ) ):
                return None
            jobs = _file_tool_jobs( tool_name, tool_input )
            if not jobs:
                return None
            return f"{_deny_file_tool( jobs )}\n{_WHY}\n{_INSTEAD}"
        if tool_name in BASH_TOOL_NAMES:
            command = tool_input.get( "command", "" )
            if not isinstance( command, str ) or not command:
                return None
            reason = _bash_reason( command, depth=0 )
            if reason is None:
                return None
            return f"{reason}\n{_WHY}\n{_INSTEAD}"
        return None
    except Exception:
        return f"{DENY_UNJUDGED}\n{_WHY}\n{_INSTEAD}" if _touches_ini( tool_name, tool_input ) else None


def build_cron_switch_deny_response( reason: str ) -> dict:
    """
    Build the PreToolUse deny envelope.

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
