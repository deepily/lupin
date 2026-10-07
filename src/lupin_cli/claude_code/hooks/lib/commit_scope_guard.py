"""
Commit scope guard: `git commit` takes the whole index, not the files you staged.

The mechanism: `git add <paths>` adds to a shared index and does not clear what is there.
With several live sessions, a peer's `git add` lands in your index and `git commit` carries
their files under your name. Staging five files by name still committed four files of
another seat's fix, because a `git status` scoped to your own paths cannot show contamination.
"Run `git diff --cached --name-only` unscoped" depends on remembering, so this installs it as a control.

On a `git commit` it denies once and shows the complete staged set: every path, the count,
and any large file. Re-run with the acknowledgement prefix to proceed.
  - It refuses only a contaminated index. The ownership oracle is `.claude-session.md`, the
    parallel-session manifest: this session's `### Touched Files` plus the sanctioned
    auto-includes. A staged path claimed only by a peer triggers the refusal naming that peer.
  - A clean single-seat index commits untouched. Denying once on every commit costs the whole
    fleet a round trip, and a control everyone pays for gets switched off.
  - A missing manifest fails open: no file, no section for this session, or an unreadable
    one allows. A seat that never adopted the manifest must not be wedged by it.
  - Residual: a stale section gives a false refusal, since a touched file left unrecorded reads
    as foreign. That direction is recoverable; the opposite silently commits a peer's work. If false refusals bite more often than contamination does, re-measure the trade rather than defend it.
  - Size is an independent trigger. A rotated 196 MB `voice-commands-xml-train.jsonl.prev`
    escaped the ignore pattern `**/voice-commands-xml-*.jsonl`, leaving 246 MB committable. A bare path list reads as harmless, so the refusal shows a size beside the path, such as `196.0 MB`.

Threat model: accident, not evasion. A miss costs a missing reminder, not a broken repo,
unlike stash_guard, where a miss lets through a command that had to be refused.

Safety, in the hot-path PreToolUse hook:
  - A `git commit` writes a different set by spelling, and the guard reviews that set. Plain
    `git commit` writes the index. `-a` adds every modified tracked file, staged after this hook
    returns. `git commit -- <paths>` takes those paths from the working tree, never the index.
    That pathspec shape is standing practice, so leaving it unreviewed would waive review everywhere.
  - Allow on doubt, and say so. An unparseable pathspec (unbalanced quoting, redirection,
    unrecognised long option, optional-argument option, magic) is allowed with a notice naming
    what went unreviewed. A guard that refuses honest commits gets switched off.
  - No guard here can close this: a pathspec commit takes each path's working-tree content, so
    a claimed file still commits what a peer left in it. The refusal points at `git diff -- <path>`. Only a private working tree closes the per-hunk gap, and reading the diff is the only existing control.
  - Fail-open: any error allows (returns None); the `git diff --cached` read is bounded by a timeout.
  - Escape hatch `LUPIN_COMMIT_SCOPE_ACK=1 git commit ...` is a prefix carve-out, not an env
    read. A hook is a separate process with its own environment.
    An inline `VAR=1 cmd` prefix belongs to a command that has not run yet.
    stash_guard's env-based hatch only appeared to work.
"""
import os
import re
import shlex
import subprocess
from typing import NamedTuple, Optional


BASH_TOOL_NAMES = ( "Bash", )

_ACK_FLAG    = "LUPIN_COMMIT_SCOPE_ACK"
_TRUE_VALUES = ( "1", "true", "on", "yes" )

# Anything at or above this is called out on its own line. The rotated training
# artifact was 196 MB; 10 MB is far below that and far above any source file.
LARGE_FILE_BYTES = 10 * 1024 * 1024

# WHICH SET THE GUARD REVIEWED. A refusal that does not say this leaves the seat
# looking for a file in the wrong place — the same defect the -a wording had, where
# "git restore --staged" pointed at a file that was never staged.
SCOPE_INDEX    = "index"
SCOPE_DASH_A   = "dash_a"
SCOPE_PATHSPEC = "pathspec"

_SCOPE_NOUN = {
    SCOPE_INDEX    : "staged file(s)",
    SCOPE_DASH_A   : "file(s) this commit would carry",
    SCOPE_PATHSPEC : "file(s) this commit names",
}
_SCOPE_HEADING = {
    SCOPE_INDEX    : "THE FULL STAGED SET ({n} file(s)) — this is the unscoped list:",
    SCOPE_DASH_A   : "THE FULL SET THIS COMMIT WOULD CARRY ({n} file(s)) — index + everything -a sweeps in:",
    SCOPE_PATHSPEC : "THE PATHS THIS COMMIT NAMES ({n} file(s)) — taken from the working tree, not the index:",
}
_SCOPE_REMEDY = {
    SCOPE_INDEX    : "  · not yours     →  git restore --staged <path>",
    SCOPE_DASH_A   : "  · not yours     →  drop -a and commit your paths by name",
    SCOPE_PATHSPEC : "  · not yours     →  drop it from the paths you name",
}
_SCOPE_EXPLAINER = {
    SCOPE_INDEX : (
        "`git add` does not clear the index, so a peer's staged work commits under "
        "YOUR name. That happened on 2026-08-25 (commit 7c8c4f83, four files): the "
        "staging was correct and the CHECK was path-scoped, which structurally "
        "cannot show you somebody else's file."
    ),
    SCOPE_DASH_A : (
        "`git commit -a` stages every modified TRACKED file at commit time, so it "
        "carries peer work you never staged and never saw in `git diff --cached`. "
        "Commit the paths you mean by name instead."
    ),
    SCOPE_PATHSPEC : (
        "A pathspec commit takes each named path's WORKING-TREE content, so naming "
        "a file you claim still commits whatever a peer has left uncommitted in it. "
        "Check the content, not just the name: `git diff -- <path>`."
    ),
}


def _notice_for( why: str ) -> str:
    """
    The non-blocking notice that a commit went unreviewed, and why.

    Ensures:
        - names why the pathspec was not parsed and what the seat should do
        - never refuses; this is the allow path
    """
    return (
        f"⚠️ Commit scope guard: NOT REVIEWED — {why}.\n"
        "This commit was allowed unexamined. The guard gives up rather than refuse an "
        "honest commit on a guess. If it names paths, check them yourself:\n"
        "  git diff -- <paths you named>\n"
        "A commit whose message rides a heredoc is the common case. The shape that gets "
        "reviewed writes the message FIRST and keeps the heredoc OFF the commit line:\n"
        "  cat > msg.txt <<'EOF' ... EOF\n"
        "  git commit -F msg.txt -- <paths>\n"
        "`-F <file>` ALONE is not enough — measured 2026-09-01, `git commit -F msg.txt -- "
        "<paths> <<'EOF'` is still unreviewed. It is the ATTACHMENT that defeats the parse, "
        "not where the message comes from."
    )


# How long the staged-set read may take before the guard gives up and allows.
GIT_TIMEOUT_SECONDS = 5

# Command position, then optional env-assignment / wrapper prefixes, then the
# program however it is spelled. Same shape as stash_guard's, deliberately —
# but see the threat-model note above for why this one is not exhaustive.
_COMMAND_POSITION = r"(?:^|[;&|(){}\n]|\bthen\b|\bdo\b|\belse\b|\belif\b)"
_WRAPPERS         = r"(?:env|command|builtin|exec|sudo|nohup|time|nice|stdbuf)"
# 🔴 AN EMPTY ENV ASSIGNMENT USED TO WALK STRAIGHT PAST THIS (found 2026-08-31 by
# a merge_head_guard test, measured in BOTH guards). The `\b` sat AFTER the whole
# alternation, and a word boundary cannot exist between the `=` of `FOO=` and the
# space that follows - two non-word characters. So the prefix group failed, the
# match backtracked to zero prefixes, and the anchored program never matched:
#
#     FOO=1 git stash pop      DENIED
#     FOO=  git stash pop      ALLOWED    <-- and `GIT_DIR= git stash pop` with it
#
# THE FIX IS A LOOKAHEAD, NOT A DROPPED `\b`. Simply removing the boundary lets the
# greedy value backtrack INTO the program name, so `FOO=bargit commit` would match
# a `git` that is part of the value - trading a false allow for a false deny, which
# is the trade this fleet's guards exist to refuse. `(?=[\s;&|]|$)` pins the value
# to a real token end instead, so it can neither swallow the program nor give back
# part of itself. Measured both ways: the empty assignment now matches and
# `FOO=bargit commit` still does not.
_PREFIXES         = rf"(?P<prefix>(?:\s*(?:[A-Za-z_][A-Za-z0-9_]*=[^\s;&|]*(?=[\s;&|]|$)|{_WRAPPERS}\b))*)"
_PROGRAM          = r"(?:[\w./~+-]*/)?git"

_GIT_COMMIT_RE = re.compile(
    rf"""
    {_COMMAND_POSITION}
    {_PREFIXES}
    \s*
    {_PROGRAM}\b
    (?P<pre>(?:\s+(?:-[Cc]\s+[^\s;&|]+|-{{1,2}}[^\s;&|]+))*)
    \s+
    commit(?![\w-])
    """,
    re.VERBOSE,
)

_QUOTED_SPAN_RE = re.compile( '"[^"]*"' + "|" + "'[^']*'" )
_INLINE_ACK_RE  = re.compile( rf"\b{_ACK_FLAG}=(?P<value>[^\s;&|]*)" )


def _blank_quoted_spans( command: str ) -> str:
    """
    Blank balanced quoted spans so a separator inside a literal is not a command position.

    Ensures:
        - every balanced single- or double-quoted span becomes the same number of spaces, so
          the blanked string is character-for-character aligned with the original and a match
          offset taken here still points at the same place there
        - text with unbalanced quotes is returned unchanged, so nothing can hide
        - never raises

    Length preservation is required. When each span collapsed to one space, `_pathspec_of`
    sliced the raw command at an offset taken from the blanked string, saw an empty command,
    and reviewed a pathspec commit as naming nothing, falling back to the index it does not write.
    """
    return _QUOTED_SPAN_RE.sub( lambda m: " " * len( m.group( 0 ) ), command )


def _ack_in_prefix( prefix ) -> bool:
    """
    True when this invocation's own env-assignment prefix carries a truthy ack.

    Requires:
        - prefix is the matched prefix span, or None

    Ensures:
        - reads the flag from the command, never from os.environ; see the module
          docstring for why an env read cannot work here
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


def git_commit_match( command: str ):
    """
    The one `git commit` matcher in this tree, public so other guards share it.

    `merge_head_guard` sits on the same trigger surface, a Bash `git commit`, and asks a
    different question about it. A second regex would put two spellings of "is this a git
    commit" in the tree, and the second drifts once either is fixed.

    Requires:
        - command is a str

    Ensures:
        - returns the re.Match whose "prefix" group carries any env-assignment
          prefix and whose "pre" group carries pre-subcommand options, or None
        - quoted literals cannot manufacture a command position
        - never raises

    Warning: it is not exhaustive, by the module threat model. Every caller must tolerate a miss.
    """
    return _mentions_git_commit( command )


_HEREDOC_RE = re.compile( r"<<(?P<dash>-?)\s*(?P<q>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=q)" )


def _strip_heredoc_bodies( command: str ):
    """
    Remove every heredoc body so a quoted `git commit` is not mistaken for the command.

    `_mentions_git_commit` searches from the left. A `git commit` quoted in a heredoc body
    matched first, and the real `git commit -F msg.txt -- <paths>` was never examined.
    That left the standard `-F <file>` shape unreviewed. Data was read as command.

    Requires:
        - command is the raw Bash command

    Ensures:
        - returns the command with each heredoc's body and terminator line removed,
          the redirection operator itself left in place
        - returns None when a heredoc opens and its terminator never appears; an
          unterminated body could hide anything, so the caller allows and says so
        - a command with no heredoc is returned unchanged
        - never raises
    """
    if "<<" not in command: return command

    lines, out, i = command.splitlines(), [], 0
    while i < len( lines ):
        line  = lines[ i ]
        out.append( line )
        opener = _HEREDOC_RE.search( line )
        i += 1
        if opener is None: continue

        tag, dash = opener.group( "tag" ), opener.group( "dash" )
        while i < len( lines ):
            candidate = lines[ i ].strip() if dash else lines[ i ]
            i += 1
            if candidate.rstrip() == tag: break
        else:
            return None                      # opened and never closed

    return "\n".join( out )


def _commits_the_whole_worktree( command: str, match ) -> bool:
    """
    True when this `git commit` carries -a or --all, so it commits files the index lacks.

    The guard weighs `git diff --cached`, but `git commit -a` stages every modified tracked file
    inside git at commit time, after this hook has returned. On a `-a` commit the reviewed set
    is not the written set, and a `git commit -am` with an empty index was allowed outright.

    Requires:
        - command is the raw Bash command; match is the _mentions_git_commit match

    Ensures:
        - True for `-a`, `--all`, and short clusters carrying an a (`-am`, `-va`)
        - False for `--amend`, which is a different flag that merely starts the
          same way, and for an `a` inside a quoted message
        - never raises
    """
    # BOUND THE SCAN TO THIS COMMAND. Measured the moment this shipped: my own
    # `git commit -F - <<'EOF'` was refused as a `-a`, because the heredoc BODY
    # quoted `git commit -am "x"` and an unbounded tail scan walked straight into
    # it. A flag scan that runs past the end of the command reads the next
    # command's flags — and a guard that refuses honest commits gets switched off.
    tail = _blank_quoted_spans( command )[ match.end(): ]
    tail = re.split( r"[;&|\n]", tail, maxsplit=1 )[ 0 ]
    for token in tail.split():
        if token == "--all": return True
        if token.startswith( "--" ): continue          # --amend and friends are not --all
        if token.startswith( "-" ) and "a" in token[ 1: ]: return True
    return False


def _modified_tracked_paths( cwd=None ) -> Optional[ list ]:
    """
    Every tracked file with unstaged modifications, which is what `-a` sweeps in.

    Ensures:
        - returns the list of modified tracked paths, possibly empty
        - `--no-relative` for the same required reason as _staged_paths: a
          relative read from a subdirectory silently returns fewer paths, and
          fewer paths reads to the caller as less to object to
        - returns None when the read fails for any reason (caller then allows)
    """
    try:
        done = subprocess.run(
            [ "git", "diff", "--no-relative", "--name-only" ],
            cwd            = cwd,
            capture_output = True,
            text           = True,
            timeout        = GIT_TIMEOUT_SECONDS,
        )
        if done.returncode != 0: return None

        return [ line for line in done.stdout.splitlines() if line.strip() ]

    except Exception:
        return None


# git-commit options that CONSUME THE NEXT TOKEN. Miss one and its argument reads
# as a pathspec — `git commit -m fix` would "name the path fix". Short forms are
# also the cluster-tail case: in `-am x`, the m takes x.
_OPTS_TAKING_AN_ARG = {
    "-m", "--message", "-F", "--file", "-c", "--reedit-message", "-C", "--reuse-message",
    "--author", "--date", "-t", "--template", "--fixup", "--squash", "--trailer",
    "--cleanup", "--pathspec-from-file",
}
_SHORT_TAKING_AN_ARG = set( "mFcCt" )

# Options whose argument is OPTIONAL. Whether the next token is their argument or a
# pathspec cannot be decided from the command line alone — so we decide nothing.
_OPTS_WITH_OPTIONAL_ARG = { "-S", "--gpg-sign", "-u", "--untracked-files" }
_SHORT_WITH_OPTIONAL_ARG = set( "Su" )

# Long options taking NO argument. An unrecognised long option might take one, and
# then the token after it is its argument rather than a path — so unrecognised
# means unsure, and unsure means allow.
_LONG_NO_ARG = {
    "--all", "--amend", "--no-edit", "--edit", "--verbose", "--quiet", "--signoff",
    "--no-signoff", "--no-verify", "--verify", "--allow-empty", "--allow-empty-message",
    "--dry-run", "--short", "--long", "--null", "--porcelain", "--status", "--no-status",
    "--reset-author", "--patch", "--include", "--only", "--no-post-rewrite",
    "--interactive", "--branch", "--no-branch", "--no-gpg-sign", "--no-all",
}

# Pathspec magic (`:(exclude)…`, `:!…`) and globs. Git resolves these against the
# whole tree; a guard that treated the literal string as a path would name a file
# that does not exist and miss every file that does.
_PATHSPEC_MAGIC = ( ":", "*", "?", "[" )


_REDIRECTION_RE = re.compile( r"^\d*(?:>>|>|<)&?\d*$" )


def _without_redirections( tokens ):
    """
    Drop `2>&1`, `> file`, `>> file` and `< file` from a commit's token list.

    A redirection changes where output goes, never which files a commit carries. Treating
    any < or > as unsure made the standard `git commit -- <paths>` shape unreviewable.
    Nearly every commit here ends `2>&1 | tail -3`. A guard that gives up on the common case is off.

    Requires:
        - tokens is the shlex-split token list after `commit`

    Ensures:
        - returns the tokens with redirection operators and their targets removed
        - a bare operator (`>`, `2>`) also consumes the token after it; that is
          its filename, and reading it as a path would name a file the commit does
          not touch
        - returns None if `<<` survives here: the heredoc stripper should have
          removed it, so its presence means something was not understood
        - never raises
    """
    if any( "<<" in token for token in tokens ): return None

    kept, i = [], 0
    while i < len( tokens ):
        token = tokens[ i ]
        if _REDIRECTION_RE.match( token ):
            i += 2 if token.endswith( ( ">", "<" ) ) else 1      # bare operator eats its target
            continue
        if token.startswith( ( ">", ">>", "<" ) ) or re.match( r"^\d+[<>]", token ):
            i += 1                                              # >file / 2>file — target attached
            continue
        kept.append( token )
        i += 1

    return kept


def _pathspec_of( command: str, match ):
    """
    The paths a `git commit <paths>` names, or a reason the guard is unsure.

    A pathspec commit never reads the shared index, so the guard would see an empty index and
    review nothing. Any ambiguity means allow and say why, since a guard that refuses honest
    commits gets switched off.

    Requires:
        - command is the raw Bash command; match is the _mentions_git_commit match

    Ensures:
        - returns ( paths, None ) when the pathspec is unambiguous: everything
          after `--`, or the bare tokens once every option and option-argument is
          accounted for
        - returns ( [], None ) when the command names no paths at all (an ordinary
          index commit; the caller reviews the index as before)
        - returns ( None, why ) when any doubt remains: quoting that will not parse,
          a heredoc the stripper did not remove, an unrecognised long option, an
          optional-argument option, or pathspec magic. The caller allows and says `why`
        - ordinary redirections (`2>&1`, `> log`) are dropped, not a reason to give
          up; they change where output goes, never what the commit carries
        - never raises
    """
    tail = command[ match.end(): ]

    # 🔴 COLLAPSE BACKSLASH-NEWLINE FIRST, OR EVERY MULTI-LINE COMMIT GOES UNREVIEWED.
    # The newline split below is what keeps the guard reading only the git command and
    # not whatever follows a `;` or `|`. But a shell line-continuation is a newline the
    # command OWNS, and splitting there truncated `... -- \` to a dangling backslash,
    # which `shlex.split` refuses — so the guard answered "quoting does not parse" and
    # allowed the commit unexamined. Measured 2026-09-01: identical commands parsed
    # single-line and failed continued, with the continuation as the only variable.
    #
    # ⚠️ It failed exactly where it mattered most. A commit naming several paths is the
    # one a seat writes across continued lines, and it is also the one whose scope is
    # worth reviewing — so the guard reviewed the easy cases and gave up on the hard ones.
    tail = re.sub( r"\\\n", " ", tail )
    tail = re.split( r"[;&|\n]", tail, maxsplit=1 )[ 0 ]

    try:
        tokens = shlex.split( tail )
    except ValueError:
        return None, "the command's quoting does not parse"

    tokens = _without_redirections( tokens )
    if tokens is None:
        return None, "the command carries a redirection this guard will not try to read"

    paths, i = [], 0
    while i < len( tokens ):
        token = tokens[ i ]

        if token == "--":
            rest = tokens[ i + 1: ]
            if any( m in path for path in rest for m in _PATHSPEC_MAGIC ):
                return None, "the pathspec uses magic or globs, which only git can resolve"
            return rest, None

        if token in _OPTS_WITH_OPTIONAL_ARG:
            return None, f"`{token}` takes an optional argument, so what follows it is ambiguous"

        if token in _OPTS_TAKING_AN_ARG:
            i += 2                                   # the option and its argument
            continue

        if token.startswith( "--" ):
            if "=" in token:                         # --author=x carries its own argument
                i += 1
                continue
            if token not in _LONG_NO_ARG:
                return None, f"`{token}` is not an option this guard knows, so it may take an argument"
            i += 1
            continue

        if token.startswith( "-" ) and len( token ) > 1:
            cluster = token[ 1: ]
            if _SHORT_WITH_OPTIONAL_ARG & set( cluster ):
                return None, f"`{token}` carries an option whose argument is optional"
            i += 2 if ( _SHORT_TAKING_AN_ARG & set( cluster ) ) else 1
            continue

        if any( m in token for m in _PATHSPEC_MAGIC ):
            return None, "the pathspec uses magic or globs, which only git can resolve"
        paths.append( token )
        i += 1

    return paths, None


def _staged_paths( cwd=None ) -> Optional[ list ]:
    """
    The full staged set, unscoped: the read the rule asked a human to remember.

    Requires:
        - cwd is a directory to run in, or None for the process's own

    Ensures:
        - returns the list of staged paths, possibly empty
        - the list is repo-wide regardless of `cwd` or of git config, enforced by
          `--no-relative` and not assumed
        - returns None when the read fails for any reason (not a repo, git
          missing, timeout), which the caller treats as allow
        - never raises

    The fail-open is declared. A nonzero return code or any exception yields None and the caller
    allows the commit, since a PreToolUse hook must never wedge a commit because git was briefly
    unreadable. So this guard cannot serve as a security boundary; it catches an honest mistake.

    `--no-relative` is required. Without it "unscoped" holds only while `diff.relative` is
    unset. With `-c diff.relative=true`, running from src/ with a file staged outside src/ returned
    an empty list, which reads as nothing to object to, so the guard waved through the
    cross-scope commit it exists to stop.
    """
    try:
        done = subprocess.run(
            [ "git", "diff", "--cached", "--no-relative", "--name-only" ],
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
    Format a byte count as a short human-readable size.

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

# A heading may carry a parenthetical note after the id —
# `## Session: d54262de (Mr. Radio 🦉 — lupin manager)`. The strict form read that
# as NO section, which is the fail-open signal: the seat's every commit went
# unreviewed and nothing said so (row 22957fe9).
_SECTION_RE = re.compile( r"^##\s+Session:\s*(?P<sid>[^\s(]+)(?:\s+\(.*)?\s*$" )
_TOUCHED_RE = re.compile( r"^-\s+(?P<ts>[^|]+)\|\s*(?P<path>.+?)\s*$" )

# ── THE DRIFTED BULLET FORMS (row 22957fe9) ───────────────────────────────────
# The documented entry is `- <timestamp> | <path>` (planning-is-prompting →
# workflow/session-start.md), and _TOUCHED_RE is faithful to it. The fleet writes
# two others. Measured 2026-09-18 across the lupin and planning-is-prompting
# manifests: 25 sections; 10 carry a backtick or bare-path bullet, 4 of them with
# NO documented-form line at all — sections that matched and claimed nothing.
#
#     - `src/a.py`                       backtick, optionally followed by a note
#     - src/a.py                         bare path, optionally ` (note)` / ` — note`
#
# ⚠️ READ ONLY UNDER `### Touched Files`, unlike the documented form, which has
# always been read anywhere in the section. A bare-path bullet under `### Notes`
# is prose, and claiming it would widen what a seat owns by accident.
#
# ⚠️ A BARE PATH MUST LOOK LIKE ONE — it contains a `/` or a `.`. Without that,
# `- none` and `- In flight: …` claim the files `none` and `In`, and a prose
# bullet that happens to name a real file would claim it silently.
#
# ⇒ ACCEPTING THEM IS NOT THE FIX ON ITS OWN, and must never be read as one. A
# bullet in a FOURTH form still claims nothing, so every Touched Files bullet that
# no form reads is kept and NAMED in the refusal. Silence is what let the drift
# spread; the refusal is what stops the next one.
_TOUCHED_HEADING_RE = re.compile( r"^###\s+Touched Files\b" )
_BACKTICK_RE        = re.compile( r"^-\s+`(?P<path>[^`\s]+)`(?:\s.*)?$" )
_BARE_PATH_RE       = re.compile( r"^-\s+(?P<path>[^\s`|]*[/.][^\s`|]*)(?:\s+(?:\(|—|--).*)?$" )

# The forms a Touched Files bullet can take, as printed in a refusal.
READABLE_FORMS = "`- <timestamp> | <path>` (documented), `- `path``, or `- path`, each optionally followed by ` (note)`"

# A path followed by a parenthetical NOTE. Manifest sections carry these by
# long-standing convention — "(merge 1f5d872e — Krishna)", "(DELETED — Rick's
# ruling)", "(renamed from …)" — and _TOUCHED_RE folds the note INTO the path,
# so the section claims a string no file will ever equal.
#
# Measured 2026-09-01 against the live manifest: 332 claimed paths, 10 of them
# mis-claimed this way, six in one seat's section. Every one read as claimed by
# NOBODY, so a commit naming those files was refused with "claimed by no
# session" — the guard blocking work it should have allowed. The parse never
# failed; it succeeded and produced a wrong answer, which is why nothing
# surfaced it.
#
# The path is required to be a single non-space token before the " (" so this
# cannot swallow a genuine path that merely contains a space and a bracket.
_ANNOTATED_PATH_RE = re.compile( r"^(?P<bare>\S+)\s+\(.*$" )


# ─────────────────────────────────────────────────────────────────────────────
# MEASURED AND REJECTED 2026-09-01 (Rio, endorsed by Mr. Radio): DO NOT ADD A
# WARNING FOR A CLAIMED PATH THAT DOES NOT EXIST.
#
# The idea is obvious and it is wrong here, so it is recorded rather than left
# for the next person to re-derive. A manifest entry naming a path not on disk
# claims nothing — a typo in your own section reads to this guard exactly like no
# claim at all, and you are refused with no hint why. Warning on it looks free.
#
# It is not. Measured against the live manifest: 29 sections, 349 claims, 270
# distinct paths.
#
#     claims naming nothing on disk ............ 33
#     of those, actually a defect ..............  1
#         "(DELETED, V1 excision) 7 scripts + 10 test files + pinned worktree"
#         — prose in the path field, silently accepted as a claim
#
# The other 32 are files legitimately deleted or never merged, sitting in
# sections from previous days. A control firing 32 times per real case trains
# people to read past it, at which point it is worse than absent — the same
# ground on which the stale-section markers were retracted the same evening.
#
# THE NARROW VERSION HOLDS, if anyone ever needs it: restricted to sections whose
# Last Activity is TODAY, the false-positive count is ZERO — five live sections,
# thirty claims between them, none naming a missing file. Left unbuilt
# deliberately: nobody has hit that typo, and a control for a defect nobody has
# had is a maintenance cost with no receipt.
# ─────────────────────────────────────────────────────────────────────────────


def _parse_manifest_report( text: str ):
    """
    Map each session id to the paths its section claims and to its unreadable bullets.

    Requires:
        - text is the manifest file's contents

    Ensures:
        - returns ( claims, unreadable ): claims is { session_id: set(paths) } and
          unreadable is { session_id: [ bullet line, ... ] }, both possibly empty
        - a section with no touched files maps to an empty set, which is not the
          same as an absent section: absent means "no discipline here, fail
          open", empty means "this seat claims nothing"
        - the documented `- <ts> | <path>` form is read anywhere in a section; the
          drifted forms only under `### Touched Files`
        - never raises
    """
    claims     = {}
    unreadable = {}
    current    = None
    in_touched = False

    for line in text.splitlines():
        stripped = line.strip()
        section  = _SECTION_RE.match( stripped )
        if section:
            current    = section.group( "sid" )
            in_touched = False
            claims.setdefault( current, set() )
            unreadable.setdefault( current, [] )
            continue

        if current is None: continue

        if stripped.startswith( "#" ):
            in_touched = bool( _TOUCHED_HEADING_RE.match( stripped ) )
            continue

        drifted = ( _BACKTICK_RE.match( stripped ) or _BARE_PATH_RE.match( stripped ) ) if in_touched else None
        if drifted:
            claims[ current ].add( drifted.group( "path" ) )
            continue

        touched = _TOUCHED_RE.match( stripped )
        if touched:
            path = touched.group( "path" ).strip()
            if len( path ) > 2 and path.startswith( "`" ) and path.endswith( "`" ):
                path = path[ 1:-1 ]
            claims[ current ].add( path )
            # Also claim the bare path when a parenthetical note follows it.
            # Both forms are kept: the raw string preserves today's behaviour
            # for any real path containing " (", and the bare form is what the
            # author meant. Claiming the annotated form alone claims nothing.
            annotated = _ANNOTATED_PATH_RE.match( path )
            if annotated:
                claims[ current ].add( annotated.group( "bare" ) )
            continue

        if in_touched and stripped.startswith( "- " ):
            unreadable[ current ].append( stripped )

    return claims, unreadable


def _parse_manifest( text: str ) -> dict:
    """Ensures: the claims half of _parse_manifest_report — { session_id: set(paths) }."""
    return _parse_manifest_report( text )[ 0 ]


def _is_mine( session_id, sid ) -> bool:
    """Sections are keyed by the 8-char prefix; the hook has the full UUID. Either direction."""
    return session_id.startswith( sid ) or sid.startswith( session_id )


def _section_report( session_id, cwd=None ):
    """
    What this session claims, what other sections claim, and its unread Touched Files bullets.

    Ensures:
        - returns ( mine, others, unreadable ): mine and others exactly as
          _claims_for_session; unreadable is this session's unread bullet lines
          ([] when it has no section)
        - never raises
    """
    if not session_id: return None, {}, []

    try:
        with open( os.path.join( cwd or "", MANIFEST_FILENAME ), "r" ) as f:
            claims, unread = _parse_manifest_report( f.read() )
    except Exception:
        return None, {}, []

    mine       = None
    unreadable = []
    others     = {}
    for sid, paths in claims.items():
        if _is_mine( session_id, sid ):
            mine = set() if mine is None else mine
            mine |= paths
            unreadable.extend( unread[ sid ] )
            continue
        for path in paths:
            others.setdefault( path, sid )

    return mine, others, unreadable


def _claims_for_session( session_id, cwd=None ):
    """
    What this session claims, and what every other section claims.

    Sections are keyed by the 8-char session prefix while the hook is handed the
    full UUID, so the match is by prefix in either direction.

    Requires:
        - session_id is the hook payload's session id, or falsy

    Ensures:
        - returns ( mine, others ) where mine is a set of paths or None when this
          session has no section; None is the fail-open signal, distinct from an
          empty set
        - others maps path -> session id, for naming the apparent owner
        - never raises
    """
    mine, others, _ = _section_report( session_id, cwd )
    return mine, others


def _large_files( paths: list, cwd=None ) -> list:
    """Ensures: returns [ (path, size) ] for staged files at or above the cap."""
    found = []
    for path in sorted( paths ):
        size = _size_of( path, cwd )
        if size is not None and size >= LARGE_FILE_BYTES:
            found.append( ( path, size ) )

    return found


def _deny_reason_for( foreign: dict, large: list, staged: list, cwd=None, *, scope=SCOPE_INDEX ) -> str:
    """
    Compose the refusal: the foreign files and their apparent owner, then sizes.

    Requires:
        - foreign maps a staged path -> the session id that claims it (or None
          when no section claims it at all)
        - large is [ (path, size) ] for oversized staged files
        - at least one of foreign / large is non-empty

    Ensures:
        - names every offending file, and the peer session where one is known
        - always prints the full set, because the unscoped list is the thing the
          original defect was missing
        - names which set it reviewed (the index, the index plus everything `-a`
          sweeps in, or the paths the command itself names) and gives the remedy
          that fits that set. Telling a seat to `git restore --staged` a file it
          never staged sends it somewhere the file is not
        - never raises
    """
    lines = []
    noun  = _SCOPE_NOUN[ scope ]

    if foreign:
        lines.append(
            f"`git commit` writes the WHOLE INDEX, and {len( foreign )} {noun} are "
            "NOT claimed by this session's manifest section:"
        )
        lines.append( "" )
        for path in sorted( foreign ):
            owner = foreign[ path ]
            lines.append( f"  {path}" + ( f"   ← claimed by session {owner}" if owner else "   ← claimed by no session" ) )
        lines.append( "" )
        lines.append( _SCOPE_EXPLAINER[ scope ] )
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

    lines.append( _SCOPE_HEADING[ scope ].format( n=len( staged ) ) )
    for path in sorted( staged ):
        lines.append( f"  {path}" )

    lines.extend( [
        "",
        _SCOPE_REMEDY[ scope ],
        "  · yours         →  add it to your section of .claude-session.md, or",
        "                     re-run with LUPIN_COMMIT_SCOPE_ACK=1 git commit ...",
        "",
        "A clean single-seat commit is never refused — if you are seeing this, something "
        "this commit would carry is unaccounted for.",
    ] )

    return "\n".join( lines )


# How many unread bullets a refusal quotes before summarising the rest.
_UNREADABLE_SHOWN = 5


def _section_hint( mine: set, unreadable: list ) -> str:
    """
    The part of a refusal about the seat's own section rather than the files.

    A seat whose Touched Files were all in an unread form was refused with "claimed by no
    session" for a file its own section listed.
    The reason sent it looking at the file. This names the section as the cause.

    Requires:
        - mine is this session's claimed set (possibly empty)
        - unreadable is this session's Touched Files bullets that claimed nothing

    Ensures:
        - "" when the section claims something and every bullet was read
        - otherwise a paragraph, ending in a blank line, that says the section
          claims zero paths (when it does), quotes up to _UNREADABLE_SHOWN unread
          bullets, and names the forms that are read
        - never raises
    """
    if mine and not unreadable: return ""

    lines = []
    if not mine:
        lines.append(
            "⚠️ YOUR MANIFEST SECTION MATCHED BUT CLAIMS ZERO PATHS, so every file below "
            "reads as unclaimed — including any your section meant to list."
        )
    if unreadable:
        lines.append(
            f"⚠️ {len( unreadable )} bullet(s) under your `### Touched Files` are in no form "
            "this guard reads, and claimed nothing:"
        )
        for bullet in unreadable[ :_UNREADABLE_SHOWN ]:
            lines.append( f"  {bullet}" )
        if len( unreadable ) > _UNREADABLE_SHOWN:
            lines.append( f"  … and {len( unreadable ) - _UNREADABLE_SHOWN} more" )
    lines.append( f"Readable forms: {READABLE_FORMS}." )
    lines.append( "" )
    return "\n".join( lines ) + "\n"


class CommitScopeVerdict( NamedTuple ):
    """
    What the guard decided, and what it looked at to decide it.

    `deny_reason` is the refusal (None means allow). `notice` is the non-blocking note that a
    commit was allowed and what could not be reviewed. The seat must be told when a commit
    went unreviewed, because the standing `git commit -- <paths>` shape is one the guard cannot
    always parse. Silence would make every compliant commit unexamined.
    """
    deny_reason : Optional[ str ] = None
    notice      : Optional[ str ] = None


def evaluate_commit_scope(
    tool_name,
    tool_input,
    *,
    session_id      = None,
    cwd             = None,
    staged_reader   = None,
    modified_reader = None,
) -> CommitScopeVerdict:
    """
    Decide a Bash `git commit`: refuse it, allow it, or allow it with a notice.

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - tool_input is the hook payload's tool_input (dict) carrying "command"
        - session_id is the hook payload's session id (full UUID or 8-char)
        - staged_reader is None (real git) or injected for testing
        - modified_reader is None (real git) or injected for testing; the
          modified-tracked set a `-a` commit sweeps in on top of the index

    Ensures:
        - deny_reason is None unless all hold: tool_name is Bash, the command
          invokes `git commit` in command position, the ack prefix is absent, the
          reviewed set is readable and non-empty, and it contains either a path
          this session's manifest section does not claim or an oversized file
        - the reviewed set is whatever that command would actually write, and the refusal
          names which of the three it was: the paths the command names (`git commit -- <paths>`),
          the index plus every modified file (`git commit -a`), or the index (everything else)
        - notice is set, with deny_reason None, when the command names paths this
          guard will not parse confidently; allow, and say what went unreviewed
        - a clean single-seat index returns both None, so it is not refuse-always
        - fail-open: any unexpected error, and any absence of a manifest section
          for this session, returns both None
    """
    allow = CommitScopeVerdict()
    try:
        if tool_name not in BASH_TOOL_NAMES: return allow
        if not isinstance( tool_input, dict ): return allow

        command = tool_input.get( "command", "" )
        if not isinstance( command, str ) or not command: return allow

        # CHEAP PRE-FILTER FIRST. Without it, every Bash command carrying an
        # unterminated heredoc got a commit-scope notice — including the ones that
        # commit nothing at all. A guard that talks about commits during commands
        # that are not commits is noise, and noise is how a notice stops being read.
        if _mentions_git_commit( command ) is None: return allow

        # A `git commit` quoted inside a heredoc is DATA, not the command being run.
        command = _strip_heredoc_bodies( command )
        if command is None:
            return CommitScopeVerdict( None, _notice_for( "a heredoc opens and never closes, so what is command and what is text cannot be told apart" ) )

        match = _mentions_git_commit( command )
        if match is None: return allow                # the only `git commit` was inside the heredoc

        if _ack_in_prefix( match.group( "prefix" ) ): return allow

        # A pathspec commit takes its content from the WORKING TREE and never reads
        # the index, so on one of those the index is the wrong thing to review —
        # and mr radio's ruling makes it the standing shape. Unsure ⇒ allow + say so.
        named, unsure = _pathspec_of( command, match )
        if unsure is not None:
            return CommitScopeVerdict( None, _notice_for( unsure ) )

        sweeps = _commits_the_whole_worktree( command, match )

        if named:
            reviewed, scope = named, SCOPE_PATHSPEC
        else:
            reviewed = ( staged_reader or _staged_paths )( cwd )
            scope    = SCOPE_INDEX
            # `-a` commits what the INDEX never held (row 292dd3d8), so the set to
            # review is the index PLUS every modified tracked file. Read it the same
            # fail-open way: unreadable → nothing extra, never wedge.
            if sweeps:
                swept    = ( modified_reader or _modified_tracked_paths )( cwd ) or []
                reviewed = list( dict.fromkeys( list( reviewed or [] ) + swept ) )
                scope    = SCOPE_DASH_A

        # Unreadable index → allow (fail-open). Empty set → the commit fails on its
        # own and there is nothing to review.
        if not reviewed: return allow

        large = _large_files( reviewed, cwd )

        mine, others, unreadable = _section_report( session_id, cwd )
        if mine is None:
            # No manifest, or no section for this session: this seat never adopted
            # the discipline, so it must not be wedged by it. Size alone can still
            # refuse — that hazard has nothing to do with ownership.
            if not large: return allow
            return CommitScopeVerdict( _deny_reason_for( {}, large, reviewed, cwd, scope=scope ) )

        foreign = {}
        for path in reviewed:
            if path in mine or os.path.basename( path ) in AUTO_INCLUDES: continue
            foreign[ path ] = others.get( path )

        if not foreign and not large: return allow

        reason = _deny_reason_for( foreign, large, reviewed, cwd, scope=scope )
        if foreign: reason = _section_hint( mine, unreadable ) + reason
        return CommitScopeVerdict( reason )

    except Exception:                    # pragma: no cover - fail-open backstop: every statement above is total over the validated inputs; kept because a hot-path guard must never raise
        return allow


def commit_scope_deny_reason( *args, **kwargs ) -> Optional[ str ]:
    """
    The deny half of evaluate_commit_scope, for callers that only refuse.

    Ensures:
        - returns evaluate_commit_scope( ... ).deny_reason, unchanged semantics
    """
    return evaluate_commit_scope( *args, **kwargs ).deny_reason


def build_commit_scope_notice_response( notice: str ) -> dict:
    """
    Build the allow-with-context envelope for a commit the guard could not review.

    Ensures:
        - returns { hookSpecificOutput: { hookEventName: "PreToolUse",
          additionalContext: <notice> } } with no permissionDecision, so the commit
          runs; the seat is told, not blocked
    """
    return {
        "hookSpecificOutput": {
            "hookEventName"     : "PreToolUse",
            "additionalContext" : notice,
        }
    }


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
