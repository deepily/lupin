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
  • THREE SHAPES, THREE SETS (row 292dd3d8). A `git commit` writes a different set
    depending on how it is spelled, and the guard reviews whichever one applies:
      · `git commit`            → the index
      · `git commit -a`         → the index PLUS every modified tracked file, which
                                  git stages at commit time, after this hook returns
      · `git commit -- <paths>` → those paths, taken from the WORKING TREE; the
                                  index is never read, so reviewing it reviews nothing
    The pathspec shape is standing practice as of mr radio's 2026-08-25 ruling
    (it eliminates the shared-index race rather than narrowing it), which is exactly
    why it could not stay unreviewed: mandating the safe shape would otherwise have
    made every compliant commit an unexamined one.
  • ALLOW ON DOUBT, AND SAY SO. Where the pathspec cannot be parsed confidently —
    unbalanced quoting, a redirection, an unrecognised long option, an option whose
    argument is optional, pathspec magic — the guard ALLOWS and emits a notice
    naming what went unreviewed. The argument for that direction is this guard's own
    false-positive: it refused the commit carrying its own message, because the flag
    scan walked into the heredoc. A guard that refuses honest commits gets switched
    off, and an off guard reviews nothing at all.
  • WHAT NO GUARD HERE CAN CLOSE: a pathspec commit takes each named path's
    WORKING-TREE content, so naming a file your section legitimately claims still
    commits whatever a peer has left uncommitted inside it. The manifest is per-FILE,
    not per-hunk. Only a private working tree closes that one; the refusal text points
    at `git diff -- <path>` because reading the diff is the only control that exists.
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
    The non-blocking "I could not review this one" (mr radio's ruling, 2026-08-25).

    Ensures:
        - names WHY the pathspec was not parsed and what the seat should do
        - never refuses — this is the allow path
    """
    return (
        f"⚠️ Commit scope guard: NOT REVIEWED — {why}.\n"
        "This commit was allowed unexamined. The guard gives up rather than refuse an "
        "honest commit on a guess. If it names paths, check them yourself:\n"
        "  git diff -- <paths you named>\n"
        "A commit whose message rides a heredoc is the common case; `git commit -F <file>` "
        "parses cleanly and gets reviewed."
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
        - every balanced single- or double-quoted span becomes THE SAME NUMBER OF
          SPACES, so the blanked string is character-for-character aligned with the
          original and a match offset taken here still points at the same place there
        - text with unbalanced quotes is returned unchanged, so nothing can hide
        - never raises

    🔴 LENGTH-PRESERVING IS LOAD-BEARING. It collapsed each span to ONE space until
    2026-08-25, and then `_pathspec_of` took a match offset from the blanked string
    and sliced the RAW command with it. Measured: `python3 - "$MSG" <<'EOF' … EOF`
    followed by `git commit -F "$MSG" -- <paths>` put the offset 12 characters
    early, the tail began with a newline, the bounded scan saw an EMPTY command, and
    a pathspec commit was reviewed as though it named nothing — falling back to the
    index, which is precisely the set a pathspec commit does not write.
    """
    return _QUOTED_SPAN_RE.sub( lambda m: " " * len( m.group( 0 ) ), command )


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


def git_commit_match( command: str ):
    """
    THE ONE `git commit` MATCHER IN THIS TREE, made public on purpose.

    `merge_head_guard` sits on the SAME trigger surface — a Bash `git commit` —
    and asks a different question about it. Giving it its own regex would put two
    spellings of "is this a git commit" into the tree, and the second one drifts
    the moment either is fixed. Row f3306404's ruling says to model the new guard
    on an existing reviewed implementation rather than keep two shapes in sync;
    that reasoning covers the matcher as much as the enforcement point.

    Requires:
        - command is a str

    Ensures:
        - returns the re.Match whose "prefix" group carries any env-assignment
          prefix and whose "pre" group carries pre-subcommand options, or None
        - quoted literals cannot manufacture a command position
        - never raises

    WARNING: it is NOT exhaustive, deliberately — see this module's threat-model
    note. Every caller must be able to tolerate a miss.
    """
    return _mentions_git_commit( command )


_HEREDOC_RE = re.compile( r"<<(?P<dash>-?)\s*(?P<q>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=q)" )


def _strip_heredoc_bodies( command: str ):
    """
    Remove every heredoc BODY, so a `git commit` quoted inside one is not mistaken
    for the command being run (row 292dd3d8).

    Measured on this guard's own commit: the message was written with
    `cat > msg.txt <<'EOF' … EOF` and the body contained the line
    `git commit  -> the index`. `_mentions_git_commit` searches from the left, so it
    matched THAT occurrence — inside prose — and the real `git commit -F msg.txt --
    <paths>` further down was never the thing examined. The guard gave up, which is
    the safe direction, but it means the newly-mandated `-F <file>` shape goes
    unreviewed for anyone who writes the message in the same command. It is the same
    defect as the heredoc false-positive one commit earlier, one level up: text that
    is DATA was read as COMMAND.

    Requires:
        - command is the raw Bash command

    Ensures:
        - returns the command with each heredoc's body and terminator line removed,
          the redirection operator itself left in place
        - returns None when a heredoc opens and its terminator never appears — an
          unterminated body could hide anything, so the caller ALLOWS and says so
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
    Does this `git commit` carry -a / --all — i.e. will it commit files the index
    never held? (row 292dd3d8)

    The guard weighs `git diff --cached`. `git commit -a` stages every modified
    TRACKED file inside git, at commit time — after this hook has already returned.
    So on a `-a` commit the set this guard reviewed is not the set that gets
    written, and measured 2026-08-25 a `git commit -am` with an empty index was
    ALLOWED unconditionally while carrying every peer modification in the tree.

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
    Every tracked file with unstaged modifications — precisely what `-a` sweeps in.

    Ensures:
        - returns the list of modified tracked paths, possibly empty
        - `--no-relative` for the same load-bearing reason as _staged_paths: a
          relative read from a subdirectory silently returns fewer paths, and
          fewer paths reads to the caller as less to object to
        - returns None when the read fails for ANY reason (caller then ALLOWS)
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
    Drop `2>&1`, `> file`, `>> file`, `< file` — a redirection changes where output
    GOES, never which files a commit carries.

    It used to be a reason to give up entirely, and that was measured wrong the
    moment it shipped: almost every commit this fleet runs ends `2>&1 | tail -3`,
    so "any < or > means unsure" made the mandated `git commit -- <paths>` shape
    unreviewable in practice. A guard that gives up on the common case is off.

    Requires:
        - tokens is the shlex-split token list after `commit`

    Ensures:
        - returns the tokens with redirection operators and their targets removed
        - a BARE operator (`>`, `2>`) also consumes the token after it — that is
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
    The paths a `git commit <paths>` names — or an "I am not sure" (row 292dd3d8).

    Why it must exist: mr radio's 2026-08-25 ruling makes `git commit -- <paths>`
    standing practice, because it commits named paths straight from the working
    tree and never reads the shared index. That closes the race — and it hands the
    guard an EMPTY index, which read to the guard as nothing to object to. Mandating
    the safe shape would have made every compliant commit an unreviewed one.

    Why it gives up so readily: the guard's own false-positive on the heredoc that
    carried its commit message. A guard that refuses honest commits gets switched
    off, so every ambiguity here resolves to "allow, and say why".

    Requires:
        - command is the raw Bash command; match is the _mentions_git_commit match

    Ensures:
        - returns ( paths, None ) when the pathspec is unambiguous — everything
          after `--`, or the bare tokens once every option and option-argument is
          accounted for
        - returns ( [], None ) when the command names no paths at all (an ordinary
          index commit — the caller reviews the index as before)
        - returns ( None, why ) when ANY doubt remains: quoting that will not parse,
          a heredoc the stripper did not remove, an unrecognised long option, an
          optional-argument option, or pathspec magic. The caller ALLOWS and says `why`
        - ordinary redirections (`2>&1`, `> log`) are DROPPED, not a reason to give
          up — they change where output goes, never what the commit carries
        - never raises
    """
    tail = command[ match.end(): ]
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
    The full staged set, unscoped — the read the rule asked a human to remember.

    Requires:
        - cwd is a directory to run in, or None for the process's own

    Ensures:
        - returns the list of staged paths, possibly empty
        - the list is REPO-WIDE regardless of `cwd` or of git config — enforced by
          `--no-relative`, not assumed (row 0adf242e)
        - returns None when the read fails for ANY reason (not a repo, git
          missing, timeout), which the caller treats as allow
        - never raises

    ⚠️ THE FAIL-OPEN ON THE THIRD LINE IS DELIBERATE AND DECLARED, not incidental:
    a returncode != 0 or any exception yields None and the caller ALLOWS the commit.
    That is the correct trade for a PreToolUse hook, which must never wedge a commit
    because git was momentarily unreadable — but it means this guard cannot be relied
    on as a security boundary. It catches an honest mistake, not a determined one.

    🔴 `--no-relative` IS LOAD-BEARING. The first line of this docstring promises the
    set is "unscoped", and without the flag that promise is only true because
    `diff.relative` happens to be unset in this repo. With `-c diff.relative=true`,
    measured: run from src/ with a file staged outside src/, this command returns an
    EMPTY list — and an empty staged set reads to the caller as "nothing to object
    to", so the guard would wave through exactly the cross-scope commit it exists to
    stop. A contract that says "unscoped" must enforce it.
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
        - always prints the FULL set, because the unscoped list is the thing the
          original defect was missing
        - NAMES WHICH SET IT REVIEWED — the index, the index plus everything `-a`
          sweeps in, or the paths the command itself names — and gives the remedy
          that fits that set. Telling a seat to `git restore --staged` a file it
          never staged sends it somewhere the file is not (row 292dd3d8)
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


class CommitScopeVerdict( NamedTuple ):
    """
    What the guard decided, and what it looked at to decide it.

    `deny_reason` is the refusal (None = allow). `notice` is the non-blocking
    "I allowed this and here is what I could not review" — mr radio's ruling of
    2026-08-25 requires the seat be TOLD when a commit went unreviewed, because
    the same ruling makes the unreviewable shape (`git commit -- <paths>`) the
    standing practice. Silence would have converted every compliant commit into
    an unexamined one.
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
        - modified_reader is None (real git) or injected for testing — the
          modified-tracked set a `-a` commit sweeps in on top of the index

    Ensures:
        - deny_reason is None unless ALL hold: tool_name is Bash, the command
          invokes `git commit` in command position, the ack prefix is absent, the
          reviewed set is readable and non-empty, and it contains either a path
          this session's manifest section does not claim or an oversized file
        - THE REVIEWED SET IS WHATEVER THAT COMMAND WOULD ACTUALLY WRITE, and the
          refusal names which of the three it was:
            · the paths the command names          (`git commit -- <paths>`)
            · the index plus every modified file   (`git commit -a`)
            · the index                            (everything else)
        - notice is set, with deny_reason None, when the command names paths this
          guard will not parse confidently — allow, and say what went unreviewed
        - a CLEAN single-seat index returns both None — not refuse-always
        - FAIL-OPEN: any unexpected error, and any absence of a manifest section
          for this session, → both None
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

        mine, others = _claims_for_session( session_id, cwd )
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

        return CommitScopeVerdict( _deny_reason_for( foreign, large, reviewed, cwd, scope=scope ) )

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
    Build the ALLOW-with-context envelope for a commit the guard could not review.

    Ensures:
        - returns { hookSpecificOutput: { hookEventName: "PreToolUse",
          additionalContext: <notice> } } — NO permissionDecision, so the commit
          runs; the seat is told, not blocked (mr radio's ruling, 2026-08-25)
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
