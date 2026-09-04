"""
memento_repo_root.py — which repo OWNS this seat's memento (row af0c5700, ported).

🔴 THE DEFECT THIS CLOSES, AND IT IS A FIX THAT NEVER CROSSED A REPO BOUNDARY.
The memento WRITER — `planning-is-prompting → workflow/scripts/memento_io.py`,
`find_repo_root` — stopped using `--show-toplevel` on 2026-07-21 because in a linked
worktree it answers the WORKTREE, so every path built from it (record, pointer,
gitignore entry, mirror) pointed at `<worktree>/io/mementos/`. Its words:

    "The write SUCCEEDED and reported 'written', at a slot no reader reads and no
     reap verifies. Memento canonicality is a REPO question, and these are different
     questions that agree everywhere except the case that bites."

The writer was fixed. THE READERS IN THIS REPO WERE NOT, and they had three
different ways of getting it wrong — measured 2026-09-04 from
`lupin-wt-cc-author-maria-3`, against 623 records in the main checkout and 0 in the
worktree:

    memento_slot.resolve_repo_root      `git rev-parse --show-toplevel`  -> WORKTREE
    reap_memento.seat_repo_root         the bridge `cwd`, verbatim       -> WORKTREE
    register_session._resolve_repo_root nearest `.git` ANCESTOR          -> WORKTREE

⚠️ THE THIRD ONE IS WORTH ITS OWN SENTENCE BECAUSE IT LOOKS CORRECT. A worktree's
`.git` is a FILE, not a directory, so `os.path.exists( path/".git" )` is TRUE there
and the walk stops at the worktree. The same shape took the session listener down
the same day (Rio ⚡, `resolve_project_name`) — a `.git` test that does not ask WHAT
KIND of `.git` it found agrees with itself and answers about the wrong tree.

🔴 WHY THIS IS NOT SHARED WITH THE CREDENTIAL RESOLVER (María 🌸's ruling,
2026-09-04, kept here with the reason it survived rather than the reason it was
given). `hook_credentials._main_checkout_name` also collapses a worktree to its main
checkout and is correct to. It must NOT become one helper with this one, because
THIS one needs two carve-outs it does not:

  · a NESTED REPO owns its own records — `src/lupin-mobile/io/mementos/` holds 5 that
    are canonically its own, and hoisting them to the parent is a fresh bug wearing
    this fix's name (Tiffany 💍 caught that in the writer).
  · a true SUBMODULE's common dir is `<parent>/.git/modules/<name>`, and the parent
    of THAT is not a working tree at all.

Both fall out of the discriminator below rather than needing a special case, which is
why the discriminator is the design and not an implementation detail.

THE DISCRIMINATOR — `--git-dir` vs `--git-common-dir`. They differ in a linked
worktree and ONLY there:

    plain repo        git-dir == common-dir   -> --show-toplevel
    subdir of a repo  git-dir == common-dir   -> --show-toplevel
    nested repo       git-dir == common-dir   -> its OWN root (correct: own slot)
    SUBMODULE         git-dir == common-dir   -> its OWN root (parent-of-common is
                                                 not a working tree)
    linked worktree   git-dir != common-dir   -> parent of common dir  <- THE FIX

⇒ Mirrors `memento_io.find_repo_root` deliberately. It is duplicated rather than
imported because the writer lives in a DIFFERENT REPOSITORY that is not importable
from here — which is the very reason its July fix never arrived. The parity is
therefore a claim this module has to KEEP, not one it can inherit, and
`test_the_memento_readers_resolve_the_writers_tree.py` is what holds it.
"""

import subprocess
import sys

from pathlib import Path


def _default_warn( message ):   # pragma: no cover - stderr seam
    """
    Ensures: writes to STDERR, never stdout.

    🔴 STDOUT IS NOT AVAILABLE AND THE REASON IS EXPENSIVE. The SessionStart hook
    sends listener stdout into a shared, unprefixed, undated 130 MB log — which is
    exactly why a listener that exited 1 on a credential error was invisible for a
    day and cost four seats their ears (Rio ⚡, 2026-09-04). A degradation notice
    that lands there is a notice nobody will ever read.
    """
    print( message, file=sys.stderr )


def _git_answer( start, flag, run_fn ):
    """
    One `git rev-parse <flag>` answer, as an absolute Path.

    Requires:
        - start is a path to resolve from; flag is a rev-parse path flag
        - run_fn( argv, cwd ) -> stdout str, or None when git cannot answer

    Ensures:
        - returns an absolute, symlink-resolved Path
        - resolves a RELATIVE answer against `start` — `--git-common-dir` is emitted
          relative for a plain repo (".git", "../../.git") and absolute for a
          worktree, so comparing the two raw strings compares different kinds of
          thing. (`--path-format=absolute` would do this in one call but needs git
          >= 2.31, and this runs on every operator's box.)
        - returns None when git fails, raises, or answers blank — the caller then
          degrades to today's answer rather than guessing a root
        - never raises
    """
    try:
        out = run_fn( [ "git", "-C", str( start ), "rev-parse", flag ], str( start ) )
    except Exception:
        return None
    if not isinstance( out, str ) or not out.strip():
        return None
    path = Path( out.strip() )
    if not path.is_absolute():
        path = Path( start ) / path
    try:
        return path.resolve()
    except Exception:
        return None


def _default_run( argv, cwd ):   # pragma: no cover - subprocess seam
    """Ensures: stdout of `argv` run in `cwd`, or None on any non-zero/failed run."""
    proc = subprocess.run( argv, cwd=cwd, capture_output=True, text=True )
    return proc.stdout if proc.returncode == 0 else None


def repo_root_owning( start, run_fn=None, warn_fn=None ):
    """
    The repo root whose `io/mementos/` is the canonical slot for a seat at `start` —
    NOT merely the working tree `start` happens to sit in.

    🔴 EVERY DEGRADED PATH ANNOUNCES ITSELF (Rio ⚡'s review finding, 2026-09-04).
    The first cut returned `None` or today's answer in SILENCE, and that is this
    repo's WEAKENED-CHECK species: it passes, having done less, and nobody
    investigates. It is worse here than usual — a silent degradation means a seat
    falls back, resolves the WRONG TREE, and the memento defect this module exists
    to close returns wearing a green. So each fallback prints one WARNING naming the
    tree it settled for, and a reader can tell "resolved" from "gave up".

    Requires:
        - start is a path inside a git working tree (str or Path)
        - run_fn( argv, cwd ) -> stdout str, or None/raise when git cannot answer
        - warn_fn( message ) -> None; defaults to a STDERR writer

    Ensures:
        - from a LINKED WORKTREE, returns the MAIN repo root — the tree the memento
          writer writes to
        - from a plain repo, a subdirectory, a NESTED repo, or a SUBMODULE, returns
          that tree's own `--show-toplevel`, unchanged from today
        - returns None when `start` is not inside a git working tree, or git cannot
          answer `--show-toplevel` at all. A caller that cannot afford None supplies
          its own fallback; this refuses rather than guessing, because a guessed root
          does not fail to find a memento — it finds a DIFFERENT one and reports on
          that.
        - never raises
    """
    warn = warn_fn if warn_fn is not None else _default_warn
    if start is None:
        warn( "[memento_repo_root] WARNING: asked to resolve a repo root from None — "
              "refusing rather than falling back to the process cwd, which is the "
              "ambient-root defect this resolver exists to end." )
        return None

    run      = run_fn if run_fn is not None else _default_run
    toplevel = _git_answer( start, "--show-toplevel", run )
    if toplevel is None:
        warn( f"[memento_repo_root] WARNING: git could not resolve a working tree at "
              f"{start!r} — refusing. A guessed root does not fail to find a memento, "
              f"it finds a DIFFERENT one and reports on that." )
        return None

    git_dir    = _git_answer( start, "--git-dir",        run )
    common_dir = _git_answer( start, "--git-common-dir", run )
    if git_dir is None or common_dir is None:
        # Cannot discriminate -> today's answer. Loud, because in a linked worktree
        # today's answer IS the bug: the writer collapses and this would not.
        warn( f"[memento_repo_root] WARNING: could not read the worktree discriminator "
              f"(--git-dir / --git-common-dir) at {start!r}; SETTLING FOR {str( toplevel )!r}. "
              f"If that is a linked worktree, the memento writer is using its MAIN "
              f"checkout and this reader is not." )
        return toplevel
    if git_dir == common_dir:
        return toplevel                     # plain / subdir / nested / submodule
    return common_dir.parent                # linked worktree -> the MAIN root
