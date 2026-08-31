"""
The control for row f42ac20c: unit tests whose result depends on the tree having a `.venv`.

THE DEFECT THIS WATCHES. `.venv` is gitignored, so `git worktree add` never produces one —
measured 2026-08-29, only 5 of 29 trees had a usable `.venv/bin/python`. A test that shells out
to `<PROJECT_ROOT>/.venv/bin/python` therefore PASSES in the main tree and FAILS in almost every
worktree with no code difference between them. Measured on ONE clean tree at ONE sha with only
a `.venv` symlink added and removed:

    no .venv    14 failed · 835 passed · 2 skipped
    .venv       1 failed · 848 passed · 2 skipped

(The remaining 1 is `test_pragma_reason_policy`, an unrelated genuine failure — not venue.)

WHAT THIS FILE IS: item 3 of the row — the control that reddens when the venv-dependent
population GROWS, so a remedy applied to today's files does not silently accumulate a fifth.
The remedy itself is `src/scripts/link-worktree-venv.sh`.

🔴 THE DETECTOR OVER-REPORTS, AND THE DECLARATION SAYS SO RATHER THAN HIDING IT.
Seven files name something that looks like a venv interpreter path. Only four actually break
without one. The other three are declared below with the measured reason they survive — two
because the path is test DATA rather than a command, one because it skips before ever reaching
the spawn. Recording "detected but harmless" separately from "breaks" is the point: a control
that quietly dropped the three would be a census hiding what its instrument saw, which is this
row's own defect family (cross-ref 5c3f3d94).

🔴 AND ONE CLAIM OF MINE WAS WRONG, recorded because this row exists because of a correction.
I first declared `test_runner_venv_pytest_guard.py` UNDETECTABLE by pattern, reasoning from its
failure MECHANISM: it breaks via the shared resolver (`src/scripts/lib/resolve-venv-pytest.sh`,
row c98bce3f) refusing with exit 3, not via a direct spawn. That part is true. What I inferred
without checking is that it therefore holds no `.venv` literal. It holds three, in live
assertion code. A different mechanism does not imply different detectability, and I asserted
the second from the first by eyeballing grep hits that happened to look like comments.
"""

import ast
import os

import cosa.utils.util as cu


UNIT_DIR = os.path.join( cu.get_project_root(), "src", "tests", "unit" )
SELF     = os.path.basename( __file__ )


# ── the population, measured rather than grepped ─────────────────────────────────
#
# Every classification below was PROVEN on 2026-08-29 by running the file twice in one clean
# tree at one sha with only a `.venv` symlink added and removed. Do not move a file between
# these sets on the strength of a pattern match — run it both ways.

BREAKS_WITHOUT_VENV = {
    "test_runner_coverage_blindness.py",        # 5 cases — joins PROJECT_ROOT/.venv/bin/pytest
    "test_v2_survives_v1_excision.py",          # 6 cases — joins PROJECT_ROOT/.venv/bin/python
    "test_coverage_frame_excludes_non_src.py",  # 1 case  — joins PROJECT_ROOT/.venv/bin/pytest
    # 1 case. Fails by a DIFFERENT mechanism — the shared resolver refuses with exit 3 in a
    # tree with no venv — but is still visible to the detector, which asserts on venv paths.
    "test_runner_venv_pytest_guard.py",
}

# Detected, but measured GREEN without a venv. Each entry states why it survives, so the next
# reader can refute the classification instead of re-deriving it.
DETECTED_BUT_DOES_NOT_BREAK = {
    "test_purge_pycache_args.py":
        "the two `.venv/bin/python` strings are ASSERTION SUBJECTS, not paths this file "
        "walks. One is the literal the drift check greps for inside both shell scripts "
        "(`PYTHON=\"${PYTHON:-$LUPIN_ROOT/.venv/bin/python}\"`), the other is prose in a "
        "docstring. Every subprocess here runs a COPY of the script planted in a tmp_path "
        "checkout, and every interpreter is either `sys.executable` or a deliberately "
        "nonexistent path used to prove the refusal fires. Measured BOTH ways at 998dd427 "
        "in this worktree, the `.venv` symlink moved aside and restored between the two "
        "runs: 10 passed without, 10 passed with.",
    "test_coverage_contention.py":
        "the `.venv/bin/pytest` strings are FIXTURE DATA — command lines the checker under "
        "test is asked to parse. Nothing is executed, so no interpreter is needed.",
    "test_run_unit_tests_fail_loud.py":
        "`_REAL_VENV_PATHS` holds the literals the test string-replaces inside a patched copy "
        "of the runner. They are the subject of a substitution, not a command that runs.",
    "test_contended_coverage_guard.py":
        "the single `.venv/bin/python` is inside a BRIEFING STRING at line 403 — the fake "
        "spawn-brief argv the guard must NOT mistake for a running suite. It is handed to "
        "`exec -a` as a process name and never executed; the file's only interpreter spawn "
        "(line 361) uses `sys.executable`, whatever that happens to be. Measured green in a "
        "tree with no `.venv` (lupin-wt-krishna-f99bed95, 31 passed) — ⚠️ that checkout is "
        "125 commits behind, so the run corroborates the MECHANISM rather than this exact "
        "revision; the current revision's independent evidence is the grep (one hit, at 403) "
        "plus the sys.executable spawn.",
    "test_v2_eligible_routing_denominator.py":
        "does spawn PROJECT_ROOT/.venv/bin/python, but skips first when the pinned baseline "
        "worktree is absent — which it is. Reaching the spawn again in an unprovisioned tree "
        "WOULD break it, so this entry is a live hazard, not a permanent exemption.",
}

KNOWN_VENV_PATH_BUILDERS = BREAKS_WITHOUT_VENV | set( DETECTED_BUT_DOES_NOT_BREAK )


def _builds_a_venv_interpreter_path( tree ):
    """
    True when the module contains an expression naming a path into a `.venv` bin directory.

    Reads the AST rather than grepping because two spellings are already in the tree:
    `os.path.join( ROOT, ".venv", "bin", X )` and a literal containing ".venv/bin/".

    Deliberately NOT a bare ".venv" substring test — fixture strings like
    "/mnt/repo/.venv/lib/python3.13/site-packages/..." mention it without depending on it.
    Docstrings and bare string statements are skipped for the same reason: they are
    `ast.Constant` nodes too, so a module that merely DESCRIBES `.venv/bin/pytest` would
    otherwise read as depending on it.
    """
    prose = {
        id( node.value )
        for node in ast.walk( tree )
        if isinstance( node, ast.Expr ) and isinstance( node.value, ast.Constant )
    }

    for node in ast.walk( tree ):
        if isinstance( node, ast.Call ):
            target  = node.func
            is_join = (
                isinstance( target, ast.Attribute ) and target.attr == "join"
                and any(
                    isinstance( a, ast.Constant ) and a.value == ".venv"
                    for a in node.args
                )
            )
            if is_join:
                return True
        if isinstance( node, ast.Constant ) and isinstance( node.value, str ):
            if id( node ) in prose:
                continue
            if ".venv/bin/" in node.value:
                return True
    return False


def _scan():
    """Return the set of unit-test filenames that name a venv interpreter path."""
    found = set()
    for entry in sorted( os.listdir( UNIT_DIR ) ):
        if not ( entry.startswith( "test_" ) and entry.endswith( ".py" ) ):
            continue
        if entry == SELF:
            # this control NAMES venv-dependent files; scanning itself would be circular
            continue
        with open( os.path.join( UNIT_DIR, entry ), encoding="utf-8" ) as handle:
            tree = ast.parse( handle.read(), filename=entry )
        if _builds_a_venv_interpreter_path( tree ):
            found.add( entry )
    return found


# ── the control ──────────────────────────────────────────────────────────────────

def test_no_new_test_has_started_naming_a_venv_that_worktrees_lack():
    """
    THE GUARD. A file that builds `<root>/.venv/bin/<interpreter>` passes in the main tree and
    fails in the ~24 of 29 trees without one. When a new one appears this reddens and names it,
    so the author classifies it deliberately instead of leaving the tier's answer dependent on
    which tree happened to run it.
    """
    unexpected = _scan() - KNOWN_VENV_PATH_BUILDERS

    assert not unexpected, (
        "A NEW unit test names a path into `.venv/bin/`, which only 5 of 29 trees have:\n"
        + "".join( f"    {name}\n" for name in sorted( unexpected ) )
        + "\nRun it BOTH ways before classifying it — with and without a `.venv` — then:\n"
          "  - if it BREAKS without one: provision the tree with\n"
          "    src/scripts/link-worktree-venv.sh, and add it to BREAKS_WITHOUT_VENV;\n"
          "  - if it is green without one: add it to DETECTED_BUT_DOES_NOT_BREAK with the\n"
          "    measured reason it survives;\n"
          "  - if it chooses an interpreter for real work, route it through the shared\n"
          "    resolver src/scripts/lib/resolve-venv-pytest.sh (row c98bce3f), which refuses\n"
          "    honestly with exit 3 rather than degrading to whatever python is on PATH.\n"
          "Do NOT silence it with a bare skip: skips measured identical at 2 in both arms, so\n"
          "nothing hides today, and a skip would trade a loud red for a quiet green."
    )


def test_every_declared_file_is_still_actually_detected():
    """
    Keeps the declaration honest in the other direction. If a declared file stops matching —
    fixed, renamed, or deleted — the list is stale and the guard is watching for something no
    longer there. A stale allow-list is how a control keeps passing after it stopped covering
    anything.
    """
    stale = KNOWN_VENV_PATH_BUILDERS - _scan()

    assert not stale, (
        "Declared as naming a venv path, but no longer detected:\n"
        + "".join( f"    {name}\n" for name in sorted( stale ) )
        + "\nIf they were fixed, remove them so the declaration keeps describing the tree.\n"
          "If they were renamed, update the entry."
    )


def test_every_surviving_file_records_why_it_survives():
    """
    A file in DETECTED_BUT_DOES_NOT_BREAK is an exception to the guard, and an exception with
    no stated reason is indistinguishable from an oversight. This forces each to carry an
    explanation a later reader can check or refute.
    """
    for name, reason in sorted( DETECTED_BUT_DOES_NOT_BREAK.items() ):
        assert reason and len( reason ) > 40, (
            f"{name} is exempted from the venv guard without a usable reason. Say what makes "
            f"it green in a tree with no venv, measured — not assumed."
        )


def test_the_two_sets_do_not_overlap():
    """
    A file cannot both break and not break. An overlap means the classification was edited in
    one place and not the other, and the guard would still pass.
    """
    overlap = BREAKS_WITHOUT_VENV & set( DETECTED_BUT_DOES_NOT_BREAK )

    assert not overlap, f"classified as both breaking and surviving: {sorted( overlap )}"


def test_the_detector_ignores_a_venv_mention_that_cannot_break_anything():
    """
    The detector's negative control, and why it is not a substring search. Fixture strings
    naming site-packages inside a `.venv` are data, not a dependency — counting them would
    inflate the population with files that run fine in a tree with no venv at all.
    """
    harmless = ast.parse(
        'PATHS = [ "/mnt/repo/.venv/lib/python3.13/site-packages/pytest/__init__.py",\n'
        '          "/mnt/repo/.venv/src/editable-package/module.py" ]\n'
        'SKIP_DIRS = { "__pycache__", ".venv", "node_modules" }\n'
    )

    assert not _builds_a_venv_interpreter_path( harmless )


def test_the_detector_does_not_mistake_documentation_for_a_dependency():
    """
    The negative control I owed and did not have. Docstrings are `ast.Constant` nodes like any
    other string, so a file that merely DESCRIBES `.venv/bin/pytest` in its prose read as a
    dependency — which is how the first version of this detector classified a file on the
    strength of its own documentation rather than its behaviour.
    """
    documented = ast.parse(
        '"""A module explaining it must not settle for .venv/bin/pytest on PATH."""\n'
        'def f():\n'
        '    """Explains that .venv/bin/python is the subject, without ever running it."""\n'
        '    return 1\n'
    )

    assert not _builds_a_venv_interpreter_path( documented )


def test_the_detector_catches_both_spellings_that_exist_in_the_tree():
    """
    The positive control. Two spellings are already present, so a detector handling only one
    would under-report and the guard would pass while blind — the exact shape of the defect
    this row was split out of.
    """
    joined  = ast.parse( 'import os\nP = os.path.join( ROOT, ".venv", "bin", "python" )\n' )
    literal = ast.parse( 'CMD = f"{root}/.venv/bin/pytest"\n' )

    assert _builds_a_venv_interpreter_path( joined ),  "the os.path.join spelling was missed"
    assert _builds_a_venv_interpreter_path( literal ), "the string-literal spelling was missed"
