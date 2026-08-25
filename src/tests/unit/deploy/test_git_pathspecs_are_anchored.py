"""
Shell `git` calls that carry a pathspec must not depend on the caller's directory.

WHY THIS FILE EXISTS (row 0adf242e, 2026-08-25). A bare pathspec — `git diff -- pyproject.toml`
— resolves against the CALLER'S CWD, not the repository root. Run from `src/` it means
`src/pyproject.toml`, which does not exist, so git reports NO DIFFERENCE and the caller
concludes nothing changed.

Two deploy guards had it, and both failed in the direction that ships bad code:

    dctl_detect_axis  — a real dependency change read as "code-only", routing the deploy
                        down the bind-mount path: new code against STALE DEPS.
    dctl_check_clean  — the guard that stops a deploy shipping UNCOMMITTED code returned
                        0 ("clean") from src/ on a tree with three modified files.

It is silent by construction: the answer is well-formed and plausible, and a `2>/dev/null`
makes a pathspec that matches nothing look identical to a clean diff. It survived because
the tier is documented as `pytest src/tests/unit/` from the repo root, where it is invisible.

⇒ A ONE-TIME SWEEP DOES NOT HOLD. This is the sweep as a standing check.

THE TWO SAFE FORMS:
    git -C "<root>" diff ... -- path      (anchor the process)
    git diff ... -- :/path                (anchor the pathspec — git's ":/" magic prefix)
"""
import re
from pathlib import Path

import pytest

import cosa.utils.util as cu


SCRIPTS_DIR = Path( cu.get_project_root() ) / "src/scripts"

# git verbs whose trailing arguments are PATHS, so a bare relative one is CWD-sensitive.
_PATH_TAKING = r"(?:diff|status|ls-files|check-ignore|add|archive|stash|clean|rev-list|grep|log)"

# A `git <verb> ... -- <something>` or `git archive <ref> <path>` line. Deliberately loose:
# this is a tripwire, and a false positive costs one anchoring, while a false negative costs
# a silent deploy of the wrong tree.
_GIT_CALL = re.compile( rf"(?<!\w)git\s+(?:-C\s+\S+\s+)?(?:--\S+\s+)*{_PATH_TAKING}\b[^\n]*" )


def _shell_files():
    return sorted( SCRIPTS_DIR.rglob( "*.sh" ) )


def _offending_lines( text ):
    """
    Yield ( lineno, line ) for git calls carrying what looks like a bare relative pathspec.

    Ensures:
        - comment lines are ignored (the fix's own explanation quotes the bad form)
        - `git -C <dir>` is accepted — the process is anchored
        - `:/`-prefixed pathspecs are accepted — the pathspec is anchored
        - a variable-expanded pathspec ("${anchored[@]}") is accepted; the anchoring is
          then the variable's job and is covered by that function's own tests
    """
    for i, raw in enumerate( text.splitlines(), start=1 ):
        line = raw.strip()
        if line.startswith( "#" ) or not line:
            continue
        m = _GIT_CALL.search( line )
        if not m:
            continue
        # Skip a `git ...` that sits INSIDE a string literal — `log "… -> git archive src/ -> SCP …"`
        # is prose describing a deploy, not an invocation. An odd number of double quotes before
        # the match means we are inside one. (Real calls quote their ARGS, not the verb, so the
        # count before `git` is even.) Caught by deploy-cloud-test.sh:168 on the first run.
        if line[ : m.start() ].count( '"' ) % 2 == 1:
            continue
        call = m.group( 0 )
        if re.search( r"(?<!\w)git\s+-C\s", call ):        # process anchored
            continue
        if " -- " not in call and " archive " not in call:  # no pathspec at all
            continue

        # The argument tail after the pathspec separator (or after the ref, for archive).
        tail = call.split( " -- ", 1 )[ 1 ] if " -- " in call else call.split( " archive ", 1 )[ 1 ]
        # Anchored, or handed off to a variable that anchors.
        if ":/" in tail or "${" in tail or "$(" in tail:
            continue
        # A bare relative path is left. `--format=...`-style flags are not paths.
        bare = [ t for t in tail.split() if not t.startswith( "-" ) and not t.startswith( '"' ) ]
        # For `archive`, the first bare token is the REF, not a path.
        if " archive " in call:
            bare = bare[ 1: ]
        if bare:
            yield i, line, bare


@pytest.mark.parametrize( "path", _shell_files(), ids=lambda p: p.name )
def test_shell_git_pathspecs_are_anchored_to_the_repo_root( path ):
    """
    No shell script may ask git a path question in a way that changes answer with CWD.

    KNOWN AND ACCEPTED: deploy-cloud-test.sh's `git archive --format=tar "$SHA" src/` is
    CWD-sensitive but FAILS CLOSED — measured, it exits 128 ("pathspec 'src/' did not match
    any files") and the script runs under `set -euo pipefail`, so the deploy aborts rather
    than shipping an empty tar. It is listed here so the exemption is a decision on the
    record rather than a gap in the regex.
    """
    accepted = {
        # file name -> set of line substrings that are known CWD-sensitive but fail closed
        "deploy-cloud-test.sh": { 'git archive --format=tar "$SHA" src/' },
    }
    allowed = accepted.get( path.name, set() )

    offenders = [
        ( n, line, bare ) for n, line, bare in _offending_lines( path.read_text( encoding="utf-8" ) )
        if not any( a in line for a in allowed )
    ]

    assert not offenders, (
        f"{path.relative_to( Path( cu.get_project_root() ) )} passes a bare relative pathspec to git; "
        f"it will answer differently depending on the caller's directory. "
        f"Anchor it with `git -C <root>` or a `:/` pathspec. Offending lines: "
        + "; ".join( f"L{n}: {line}  (bare: {bare})" for n, line, bare in offenders )
    )


def test_the_tripwire_actually_catches_the_original_defect():
    """
    A guard that cannot go red is decoration. This feeds the tripwire the EXACT line that
    shipped the bug and asserts it is caught.
    """
    original = 'if git diff --quiet "$prev_sha" "$sha" -- pyproject.toml uv.lock 2>/dev/null; then'
    found    = list( _offending_lines( original ) )
    assert found, "the tripwire no longer catches the pathspec bug it was written for"


def test_the_tripwire_accepts_both_anchored_forms():
    """The two sanctioned fixes must not be flagged, or the check becomes noise."""
    anchored_pathspec = 'git diff --quiet "$a" "$b" -- :/pyproject.toml :/uv.lock'
    anchored_process  = 'git -C "$root" diff --quiet "$a" "$b" -- pyproject.toml'
    assert not list( _offending_lines( anchored_pathspec ) ), ":/ pathspec must be accepted"
    assert not list( _offending_lines( anchored_process  ) ), "git -C must be accepted"


# ═══════════════════════════════════════════════════════════════════════════════
# The Python call sites: anchored, not coincidentally correct (row 0adf242e)
# ═══════════════════════════════════════════════════════════════════════════════

import subprocess


def _repo( tmp_path ):
    """A throwaway repo with a subdirectory and one file staged OUTSIDE it."""
    def sh( *a ):
        return subprocess.run( a, cwd=tmp_path, capture_output=True, text=True )

    sh( "git", "init", "-q" )
    sh( "git", "config", "user.email", "t@t.t" )
    sh( "git", "config", "user.name", "t" )
    ( tmp_path / "src" ).mkdir()
    ( tmp_path / "src" / "keep.py" ).write_text( "x = 1\n" )
    sh( "git", "add", "-A" ); sh( "git", "commit", "-qm", "base" )

    ( tmp_path / "outside.txt" ).write_text( "PASSWORD = 'hunter2'\n" )
    sh( "git", "add", "outside.txt" )
    return tmp_path


def test_diff_relative_really_can_blind_a_cached_read( tmp_path ):
    """
    THE ASSUMPTION, ASSERTED RATHER THAN TRUSTED. The pathspec-free `git diff --cached`
    calls in this repo are repo-wide only because `diff.relative` is unset. That is a
    COINCIDENCE, not an invariant — nothing stops someone setting it.

    This test proves the hazard is real, so the `--no-relative` flags on those call
    sites read as load-bearing rather than as noise a future reader might tidy away.
    """
    root = _repo( tmp_path )
    bare = subprocess.run(
        [ "git", "-c", "diff.relative=true", "diff", "--cached", "--name-only" ],
        cwd=root / "src", capture_output=True, text=True ).stdout.split()
    assert bare == [], (
        "diff.relative no longer scopes a cached read to CWD — if git changed this, the "
        "--no-relative flags are still harmless, but this test's premise needs rewriting"
    )


def test_no_relative_defeats_it( tmp_path ):
    """The flag the call sites use must actually restore the repo-wide view."""
    root = _repo( tmp_path )
    fixed = subprocess.run(
        [ "git", "-c", "diff.relative=true", "diff", "--cached", "--no-relative", "--name-only" ],
        cwd=root / "src", capture_output=True, text=True ).stdout.split()
    assert fixed == [ "outside.txt" ], f"--no-relative did not restore the repo-wide view: {fixed}"


@pytest.mark.parametrize( "rel_path", [
    "src/scripts/pre-commit-secret-scan.py",
    "src/lupin_cli/claude_code/hooks/lib/commit_scope_guard.py",
] )
def test_cached_reads_in_guards_carry_no_relative( rel_path ):
    """
    Every `git diff --cached` in a GUARD must carry --no-relative.

    These two decide whether a commit is allowed to proceed. Scoped silently to a
    subdirectory, both fail in the same direction: an empty result reads as "nothing to
    object to", so the guard passes the commit it exists to stop.
    """
    text = ( Path( cu.get_project_root() ) / rel_path ).read_text( encoding="utf-8" )
    for i, line in enumerate( text.splitlines(), start=1 ):
        if '"--cached"' in line and not line.strip().startswith( "#" ):
            window = "\n".join( text.splitlines()[ i - 1 : i + 2 ] )
            assert "--no-relative" in window, (
                f"{rel_path}:{i} runs a --cached read without --no-relative; it will go "
                f"blind to files staged outside the CWD if diff.relative is ever set."
            )


def test_secret_scanner_worktree_mode_is_anchored_to_the_repo_root():
    """
    `git ls-files` is CWD-SCOPED BY DEFAULT — no config needed, unlike the diff cases.

    Measured on this repo before the fix: 4826 files from the root, 4638 from src/ — and
    running the scanner from src/cosa found 38 findings where the root found 256. A secret
    scanner that quietly covers a fraction of the tree and still reports its result is the
    worst shape available, because the clean number is believed.
    """
    text = ( Path( cu.get_project_root() ) / "src/scripts/secret_scan.py" ).read_text( encoding="utf-8" )
    assert '"git", "-C", root, "ls-files"' in text, (
        "secret_scan.py worktree mode must run ls-files anchored to the repo root"
    )
    assert "os.path.join( root, f )" in text, (
        "ls-files emits repo-root-relative paths — opening them from another CWD raises "
        "OSError, which the surrounding except swallows, turning a coverage hole silent"
    )
