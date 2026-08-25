"""
Commit scope guard — `git commit` takes the WHOLE INDEX, not the files you staged.

THE MECHANISM. `git add <paths>` adds to a shared index; it does not clear what
is already there. `git commit` then writes everything the index holds. On a tree
with several live sessions, a peer's `git add` lands in the same index as yours,
and your commit carries their files under your name.

WHAT IT COST, 2026-08-25. I staged five files BY NAME — no `git add -A`, no bare
add — and committed four files belonging to another seat's in-flight fix. The
staging was correct. What failed was the CHECK: I ran `git status --short` scoped
to my own five paths, and a path-scoped check cannot show you the contamination
it exists to catch. Nothing was pushed, so the tip was rewritten and the peer's
work verified byte-identical, but had it been pushed it was theirs, on my row,
with nothing in the git output naming the owner.

⇒ THE RULE THAT REPLACED IT WAS STILL A RULE. "Run `git diff --cached
--name-only` UNSCOPED before committing" is correct and depends entirely on
remembering, which is the property that made the first failure possible. This
module is that rule installed as a control. (Prompted by mr radio 🦉, who asked
why it was a note and not a hook.)

WHAT IT DOES: on a `git commit`, DENY ONCE and put the complete staged set in
front of the committer — every path, the count, and any file large enough to
matter. Re-run with the acknowledgement prefix to proceed.

⇒ IT REFUSES ONLY A CONTAMINATED INDEX, not every commit. The ownership oracle
is `.claude-session.md`, the parallel-session manifest: this session's own
`### Touched Files` section is what it claims, plus the sanctioned auto-includes.
A staged path claimed by nobody-but-a-peer is what triggers the refusal, and the
message names the peer's session.

⇒ A CLEAN SINGLE-SEAT INDEX COMMITS UNTOUCHED — zero friction, and that is a
REQUIREMENT rather than a nicety (row 53c4900f). My first cut denied once on
EVERY commit and asked the committer to acknowledge the list. That is
refuse-always wearing a guard's clothes: it imposes a round trip on every commit
in the fleet, and a control everyone pays for on every use is a control someone
eventually switches off. The row's negative control exists precisely to reject
that shape, and it was right to.

⇒ FAIL-OPEN ON A MISSING MANIFEST, which is most of the fleet. No manifest file,
no section for this session, or an unreadable one → ALLOW. A seat that never
adopted the manifest discipline must never be wedged by it.

⚠️ AND THE RESIDUAL, named rather than hidden: a STALE section produces a FALSE
REFUSAL — the seat touched a file and did not record it, so the guard reads it as
foreign. That is the recoverable direction (the hatch is one prefix away, and the
remedy — update your section — is an existing mandate), where the opposite
direction silently commits a peer's work. But it is real friction, and if it
turns out to bite more often than contamination does, this trade should be
re-measured rather than defended.

SIZE IS AN INDEPENDENT TRIGGER, because the second incident was a size incident
and it had nothing to do with ownership: the files were the committer's own.
Rotation (row 11390b57)
wrote `voice-commands-xml-train.jsonl.prev` — 196 MB — and the ignore pattern
`**/voice-commands-xml-*.jsonl` did not match it, because it ends `.jsonl.prev`.
246 MB across three files sat committable for about forty minutes. A path list
alone reads as harmless; a path list with `196.0 MB` beside it does not.

THREAT MODEL — ACCIDENT, NOT EVASION, and the matcher is sized to that. It
recognises the natural spellings of `git commit` in command position. Somebody
determined to route around it can, and it does not matter: the failure mode of a
miss is a MISSING REMINDER, not a broken repo. That is the opposite of
stash_guard, where a miss lets through a command that had to be refused — which
is why that module needs total normalisation and this one does not. Claiming
completeness here would be the same defect this fleet keeps catching.

SAFETY — this runs inside the hot-path PreToolUse hook, so two non-negotiables:
  • FAIL-OPEN: ANY error → allow (return None). A guard must never break a tool
    call. The `git diff --cached` read is bounded by a timeout and every failure
    mode of it — not a repo, git absent, slow disk — returns None.
  • ESCAPE HATCH / ACK: `LUPIN_COMMIT_SCOPE_ACK=1 git commit ...`.

    🔴 HONOURED BY A PREFIX CARVE-OUT, NOT AN ENV READ, and this is not a
    shortcut — it is the only thing that can work. A PreToolUse hook is a
    SEPARATE PROCESS reading its OWN environment, and an inline `VAR=1 cmd`
    prefix belongs to a command that HAS NOT RUN YET. stash_guard learned this
    the expensive way: its documented hatch was broken for most of its life and
    appeared to work only because the env assignment pushed the program out of
    command position. The carve-out is copied from there deliberately.
"""
import os
import re
import subprocess
from typing import Optional


BASH_TOOL_NAMES = ( "Bash", )

_ACK_FLAG    = "LUPIN_COMMIT_SCOPE_ACK"
_TRUE_VALUES = ( "1", "true", "on", "yes" )

# Anything at or above this is called out on its own line. The rotated training
# artifact was 196 MB; 10 MB is far below that and far above any source file.
LARGE_FILE_BYTES = 10 * 1024 * 1024

# How long the staged-set read may take before the guard gives up and allows.
GIT_TIMEOUT_SECONDS = 5

# Command position, then optional env-assignment / wrapper prefixes, then the
# program however it is spelled. Same shape as stash_guard's, deliberately —
# but see the threat-model note above for why this one is not exhaustive.
_COMMAND_POSITION = r"(?:^|[;&|(){}\n]|\bthen\b|\bdo\b|\belse\b|\belif\b)"
_WRAPPERS         = r"(?:env|command|builtin|exec|sudo|nohup|time|nice|stdbuf)"
_PREFIXES         = rf"(?P<prefix>(?:\s*(?:[A-Za-z_][A-Za-z0-9_]*=[^\s;&|]*|{_WRAPPERS})\b)*)"
_PROGRAM          = r"(?:[\w./~+-]*/)?git"

_GIT_COMMIT_RE = re.compile(
    rf"""
    {_COMMAND_POSITION}
    {_PREFIXES}
    \s*
    {_PROGRAM}\b
    (?P<pre>(?:\s+(?:-[Cc]\s+[^\s;&|]+|-{{1,2}}[^\s;&|]+))*)
    \s+
    commit\b
    """,
    re.VERBOSE,
)

_QUOTED_SPAN_RE = re.compile( '"[^"]*"' + "|" + "'[^']*'" )
_INLINE_ACK_RE  = re.compile( rf"\b{_ACK_FLAG}=(?P<value>[^\s;&|]*)" )


def _blank_quoted_spans( command: str ) -> str:
    """
    Blank BALANCED quoted spans so a separator inside a literal is not read as a
    command position — the over-block stash_guard had to fix (row e062580e).

    Ensures:
        - every balanced single- or double-quoted span becomes one space
        - text with unbalanced quotes is returned unchanged, so nothing can hide
        - never raises
    """
    return _QUOTED_SPAN_RE.sub( " ", command )


def _ack_in_prefix( prefix ) -> bool:
    """
    True iff THIS invocation's own env-assignment prefix carries the ack, truthy.

    Requires:
        - prefix is the matched prefix span, or None

    Ensures:
        - reads the flag from the COMMAND, never from os.environ — see the
          module docstring for why an env read cannot work here
        - scoped to this invocation's prefix, so an unrelated `echo ACK=1`
          earlier in the line cannot acknowledge a later commit
        - never raises
    """
    if not prefix: return False

    found = _INLINE_ACK_RE.search( prefix )
    if not found: return False

    return found.group( "value" ).strip().strip( "'\"" ).lower() in _TRUE_VALUES


def _mentions_git_commit( command: str ):
    """
    The match for a `git commit` in command position, or None.

    Requires:
        - command is a str

    Ensures:
        - returns the re.Match (whose "prefix" group carries any env prefix)
        - quoted literals cannot manufacture a command position
        - never raises
    """
    return _GIT_COMMIT_RE.search( _blank_quoted_spans( command ) )


def _staged_paths( cwd=None ) -> Optional[ list ]:
    """
    The full staged set, unscoped — the read the rule asked a human to remember.

    Requires:
        - cwd is a directory to run in, or None for the process's own

    Ensures:
        - returns the list of staged paths, possibly empty
        - returns None when the read fails for ANY reason (not a repo, git
          missing, timeout), which the caller treats as allow
        - never raises
    """
    try:
        done = subprocess.run(
            [ "git", "diff", "--cached", "--name-only" ],
            cwd            = cwd,
            capture_output = True,
            text           = True,
            timeout        = GIT_TIMEOUT_SECONDS,
        )
        if done.returncode != 0: return None

        return [ line for line in done.stdout.splitlines() if line.strip() ]

    except Exception:
        return None


def _human_size( num_bytes: int ) -> str:
    """
    Ensures:
        - returns a short human-readable size, largest unit that fits
        - GB is the last unit, so the loop always returns and there is no
          implicit fall-through to cover
        - never raises
    """
    size  = float( num_bytes )
    units = ( "B", "KB", "MB", "GB" )
    for unit in units[ :-1 ]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0

    return f"{size:.1f} {units[ -1 ]}"


def _size_of( path: str, cwd=None ) -> Optional[ int ]:
    """Ensures: returns the file's size in bytes, or None if it cannot be read."""
    try:
        return os.path.getsize( os.path.join( cwd or "", path ) )
    except Exception:
        return None


# The parallel-session manifest, and the files sanctioned to ride along with any
# session's commit (CLAUDE.md § PARALLEL SESSION SAFETY).
MANIFEST_FILENAME = ".claude-session.md"
AUTO_INCLUDES     = frozenset( {
    "history.md", "TODO.md", "CLAUDE.md", "CLAUDE.local.md", "bug-fix-queue.md",
    MANIFEST_FILENAME,
} )

_SECTION_RE = re.compile( r"^##\s+Session:\s*(?P<sid>\S+)\s*$" )
_TOUCHED_RE = re.compile( r"^-\s+(?P<ts>[^|]+)\|\s*(?P<path>.+?)\s*$" )


def _parse_manifest( text: str ) -> dict:
    """
    Map each session id in the manifest to the set of paths its section claims.

    Requires:
        - text is the manifest file's contents

    Ensures:
        - returns { session_id: set(paths) }, possibly empty
        - a section with no touched files maps to an empty set, which is NOT the
          same as an absent section — absent means "no discipline here, fail
          open", empty means "this seat claims nothing"
        - never raises
    """
    claims  = {}
    current = None

    for line in text.splitlines():
        section = _SECTION_RE.match( line.strip() )
        if section:
            current = section.group( "sid" )
            claims.setdefault( current, set() )
            continue

        if current is None: continue

        touched = _TOUCHED_RE.match( line.strip() )
        if touched:
            claims[ current ].add( touched.group( "path" ).strip() )

    return claims


def _claims_for_session( session_id, cwd=None ):
    """
    What THIS session claims, and what every other section claims.

    Sections are keyed by the 8-char session prefix while the hook is handed the
    full UUID, so the match is by prefix in either direction.

    Requires:
        - session_id is the hook payload's session id, or falsy

    Ensures:
        - returns ( mine, others ) where mine is a set of paths or None when this
          session has NO section — None is the fail-open signal, distinct from an
          empty set
        - others maps path -> session id, for naming the apparent owner
        - never raises
    """
    if not session_id: return None, {}

    try:
        with open( os.path.join( cwd or "", MANIFEST_FILENAME ), "r" ) as f:
            claims = _parse_manifest( f.read() )
    except Exception:
        return None, {}

    mine = None
    for sid, paths in claims.items():
        if session_id.startswith( sid ) or sid.startswith( session_id ):
            mine = set() if mine is None else mine
            mine |= paths

    others = {}
    for sid, paths in claims.items():
        if session_id.startswith( sid ) or sid.startswith( session_id ): continue
        for path in paths:
            others.setdefault( path, sid )

    return mine, others


def _large_files( paths: list, cwd=None ) -> list:
    """Ensures: returns [ (path, size) ] for staged files at or above the cap."""
    found = []
    for path in sorted( paths ):
        size = _size_of( path, cwd )
        if size is not None and size >= LARGE_FILE_BYTES:
            found.append( ( path, size ) )

    return found


def _deny_reason_for( foreign: dict, large: list, staged: list, cwd=None ) -> str:
    """
    Compose the refusal: the foreign files and their apparent owner, then sizes.

    Requires:
        - foreign maps a staged path -> the session id that claims it (or None
          when no section claims it at all)
        - large is [ (path, size) ] for oversized staged files
        - at least one of foreign / large is non-empty

    Ensures:
        - names every offending file, and the peer session where one is known
        - always prints the FULL staged set, because the unscoped list is the
          thing the original defect was missing
        - never raises
    """
    lines = []

    if foreign:
        lines.append(
            f"`git commit` writes the WHOLE INDEX, and {len( foreign )} staged file(s) are "
            "NOT claimed by this session's manifest section:"
        )
        lines.append( "" )
        for path in sorted( foreign ):
            owner = foreign[ path ]
            lines.append( f"  {path}" + ( f"   ← claimed by session {owner}" if owner else "   ← claimed by no session" ) )
        lines.append( "" )
        lines.append(
            "`git add` does not clear the index, so a peer's staged work commits under "
            "YOUR name. That happened on 2026-08-25 (commit 7c8c4f83, four files): the "
            "staging was correct and the CHECK was path-scoped, which structurally "
            "cannot show you somebody else's file."
        )
        lines.append( "" )

    if large:
        lines.append( f"🔴 {len( large )} LARGE FILE(S) STAGED:" )
        for path, size in large:
            lines.append( f"  {path}   ⚠️ {_human_size( size )}" )
        lines.append(
            "On 2026-08-25 three rotated training artifacts totalling 246 MB sat "
            "committable because an ignore pattern missed them by one suffix. Confirm "
            "these belong in git history."
        )
        lines.append( "" )

    lines.append( f"THE FULL STAGED SET ({len( staged )} file(s)) — this is the unscoped list:" )
    for path in sorted( staged ):
        lines.append( f"  {path}" )

    lines.extend( [
        "",
        "  · not yours     →  git restore --staged <path>",
        "  · yours         →  add it to your section of .claude-session.md, or",
        "                     re-run with LUPIN_COMMIT_SCOPE_ACK=1 git commit ...",
        "",
        "A clean single-seat index is never refused — if you are seeing this, something "
        "staged is unaccounted for.",
    ] )

    return "\n".join( lines )


def commit_scope_deny_reason(
    tool_name,
    tool_input,
    *,
    session_id    = None,
    cwd           = None,
    staged_reader = None,
) -> Optional[ str ]:
    """
    Return a deny-reason iff a Bash `git commit` would carry unaccounted files.

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - tool_input is the hook payload's tool_input (dict) carrying "command"
        - session_id is the hook payload's session id (full UUID or 8-char)
        - staged_reader is None (real git) or injected for testing

    Ensures:
        - None unless ALL hold: tool_name is Bash, the command invokes `git
          commit` in command position, the ack prefix is absent, the staged set
          is readable and non-empty, and it contains either a path this session's
          manifest section does not claim or an oversized file
        - a CLEAN single-seat index returns None — the guard is not refuse-always
        - FAIL-OPEN: any unexpected error, and any absence of a manifest section
          for this session, → None
    """
    try:
        if tool_name not in BASH_TOOL_NAMES: return None
        if not isinstance( tool_input, dict ): return None

        command = tool_input.get( "command", "" )
        if not isinstance( command, str ) or not command: return None

        match = _mentions_git_commit( command )
        if match is None: return None

        if _ack_in_prefix( match.group( "prefix" ) ): return None

        reader = staged_reader or _staged_paths
        staged = reader( cwd )
        # Unreadable index → allow (fail-open). Empty index → the commit fails on
        # its own and there is nothing to review.
        if not staged: return None

        large = _large_files( staged, cwd )

        mine, others = _claims_for_session( session_id, cwd )
        if mine is None:
            # No manifest, or no section for this session: this seat never adopted
            # the discipline, so it must not be wedged by it. Size alone can still
            # refuse — that hazard has nothing to do with ownership.
            return _deny_reason_for( {}, large, staged, cwd ) if large else None

        foreign = {}
        for path in staged:
            if path in mine or os.path.basename( path ) in AUTO_INCLUDES: continue
            foreign[ path ] = others.get( path )

        if not foreign and not large: return None

        return _deny_reason_for( foreign, large, staged, cwd )

    except Exception:                    # pragma: no cover - fail-open backstop: every statement above is total over the validated inputs; kept because a hot-path guard must never raise
        return None


def build_commit_scope_deny_response( reason: str ) -> dict:
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
