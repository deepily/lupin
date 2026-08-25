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
