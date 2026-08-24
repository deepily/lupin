"""
Gate-reachability census for the Lupin test tree.

THE DEFECT THIS EXISTS TO DETECT (board row d97b024e): a test file that no
runner script, INI key, or `test_suite` test-type references is unreachable by
every control this project has. It contributes no coverage signal, it cannot
fail a merge gate, and — the part that matters — **it emits nothing when it
rots**. `src/tests/store_owed_cutover_e2e/` sat RED for roughly a month in
exactly that state and was found by hand.

The primitives here recompute, from the tree itself, which test files a gate
can actually reach. They derive the gate's targets from `SUITE_SCRIPTS` in
`cosa/agents/test_suite/job.py` and from the literal paths inside each of
those shell runners — NOT from a hardcoded list, because a hardcoded list rots
the same way the suites did.

Two failure shapes are measured, not one:

  · UNREFERENCED — a test file no runner names. Looks like coverage in the
    directory tree; reaches no gate.
  · ZERO-COLLECT — a `test_*.py` file that a runner DOES reach but which
    defines no test. It is inside the gate, correctly named, and still emits
    nothing. This is the harder class: the unreferenced files at least look
    unreferenced.

WHAT THE PREDICATE COUNTS: files on DISK matching pytest's configured
discovery pattern (`test_*.py`). Not git — an untracked file collects, and a
deleted-but-cached file does not.

WHAT IT CANNOT SEE: whether a reached test ASSERTS anything, and whether a
file that is merely IMPORTED by a collected file carries tests of its own.
Reachability is a necessary condition for a gate signal, never a sufficient one.
"""

import ast
import re

from pathlib import Path
from typing  import Dict, List, Set


# Directories excluded from the population. Sub-repos are managed separately
# (CLAUDE.md § GIT REPOSITORY MANAGEMENT); worktrees hold stale duplicates of
# the whole tree and would inflate any naive count several-fold — in the
# flattering direction.
EXCLUDED_PATH_PARTS = (
    ".claude",
    ".venv",
    "node_modules",
    "__pycache__",
    "lupin-mobile",
    "lupin-plugin-firefox",
    # `tmp` added 2026-08-23 (row c4dd7768). `src/tmp/` is a self-declared scratch
    # directory — its own README says "This directory is excluded from git tracking"
    # — and `.gitignore:5` ignores every `tmp` component, so git has never tracked a
    # byte of it. Its 14 `test_*.py` files existed on ONE developer's disk and in no
    # clone, worktree or CI checkout, yet the census scans DISK: they entered the
    # population here and nowhere else, and their 14 allowlist entries read as valid
    # here and as stale everywhere else. A census answer must not depend on which
    # checkout you ask from (the same shape as bug 5e6e0680).
    "tmp",
)

# The file whose SUITE_SCRIPTS map defines every gate-invocable runner.
SUITE_SCRIPTS_SOURCE = "src/cosa/agents/test_suite/job.py"

# Matches a repo-relative path token inside a shell runner, e.g.
# `src/tests/unit/` or `src/tests/smoke/test_presentation_render_only_smoke.py`.
#
# The trailing lookahead REJECTS a token that is merely the prefix of a glob.
# Without it, a runner line like `c8 tsx --test "src/tests/**/*.test.ts"`
# yields the token `src/tests` — a real directory — which would mark EVERY
# Python test file under `src/tests/` gate-reachable and silently switch this
# entire census off. Widening a predicate widens what it lets in; a glob root
# is not a target.
_PATH_TOKEN_RE = re.compile( r"src/[A-Za-z0-9_./-]+(?![A-Za-z0-9_./*-])" )

# Matches one `"key" : "src/....sh"` entry of the SUITE_SCRIPTS dict literal.
_SUITE_SCRIPT_RE = re.compile( r"^\s*\"[a-z_]+\"\s*:\s*\"(src/[^\"]+\.sh)\"" )


def read_suite_scripts( project_root: Path ) -> Set[ str ]:
    """
    Extract the runner-script paths from the SUITE_SCRIPTS dict literal.

    The literal is parsed from source text rather than imported, so this stays
    free of the heavy runtime dependencies `job.py` pulls in at import time.

    Requires:
        - project_root is a directory containing SUITE_SCRIPTS_SOURCE

    Ensures:
        - returns every `src/....sh` value of the SUITE_SCRIPTS literal
        - returns repo-relative POSIX paths

    Raises:
        - FileNotFoundError if SUITE_SCRIPTS_SOURCE is absent
    """
    source = ( project_root / SUITE_SCRIPTS_SOURCE ).read_text( encoding="utf-8" )

    scripts = set()
    for line in source.splitlines():
        match = _SUITE_SCRIPT_RE.match( line )
        if match: scripts.add( match.group( 1 ) )

    return scripts


def find_gate_targets( project_root: Path ) -> Set[ str ]:
    """
    Collect every repo-relative path a gate-invocable runner names.

    Walks the SUITE_SCRIPTS runners, following `.sh` references (run-all-tests.sh
    delegates to the per-suite runners), and keeps the `src/...` tokens that
    exist on disk. Comment lines are skipped — usage examples in a runner's
    header name paths the runner does not run.

    Requires:
        - project_root is a directory containing SUITE_SCRIPTS_SOURCE

    Ensures:
        - returns only paths that exist under project_root
        - returns directories and `.py` files; `.sh` files are followed, not returned
        - terminates even if two runners reference each other
    """
    pending = read_suite_scripts( project_root )
    seen    = set()
    targets = set()

    while pending:
        script = pending.pop()
        if script in seen: continue
        seen.add( script )

        script_path = project_root / script
        if not script_path.is_file(): continue

        for line in script_path.read_text( encoding="utf-8" ).splitlines():
            if line.lstrip().startswith( "#" ): continue
            for token in _PATH_TOKEN_RE.findall( line ):
                token     = token.rstrip( "/" )
                candidate = project_root / token
                if not candidate.exists(): continue
                if token.endswith( ".sh" ):
                    pending.add( token )
                elif candidate.is_dir() or token.endswith( ".py" ):
                    targets.add( token )

    return targets


def find_test_file_population( project_root: Path ) -> Set[ str ]:
    """
    Every `test_*.py` file on disk that pytest's discovery pattern would match.

    Requires:
        - project_root is a directory containing a `src` subdirectory

    Ensures:
        - returns repo-relative POSIX paths
        - excludes every path containing an EXCLUDED_PATH_PARTS component
        - reflects DISK state, not git state
    """
    population = set()
    for path in ( project_root / "src" ).rglob( "test_*.py" ):
        # Filter on the RELATIVE parts, not the absolute ones.
        #
        # `.claude` is an excluded part, and a git worktree lives at
        # `<repo>/.claude/worktrees/<name>` — so every absolute path inside a
        # worktree contains `.claude` and the census excluded ITSELF. Measured
        # 2026-08-17: 1,319 test files from the main checkout, ZERO from a
        # worktree. find_unreferenced_test_files then returns an empty list
        # there, so the gate reports perfectly clean in exactly the place new
        # work is written (bug 5e6e0680, found by Clayton 😎).
        #
        # The exclusions are about where a file sits WITHIN the project; asking
        # that question of the absolute path lets the project's own location
        # answer it.
        relative = path.relative_to( project_root )
        if any( part in EXCLUDED_PATH_PARTS for part in relative.parts ): continue
        population.add( relative.as_posix() )

    return population


def find_unreferenced_test_files( project_root: Path, allowlist: Dict[ str, str ] ) -> List[ str ]:
    """
    The census: test files no gate-invocable runner can reach.

    A file is reachable when a runner names it directly or names one of its
    ancestor directories.

    Requires:
        - project_root is a directory containing a `src` subdirectory
        - allowlist maps a repo-relative path to a reason string

    Ensures:
        - returns a sorted list of repo-relative paths
        - returns no path present in allowlist
    """
    targets      = find_gate_targets( project_root )
    unreferenced = []

    for relative in find_test_file_population( project_root ):
        if relative in allowlist: continue
        if _is_reachable( relative, targets ): continue
        unreferenced.append( relative )

    return sorted( unreferenced )


def find_zero_collect_test_files( project_root: Path, allowlist: Dict[ str, str ] ) -> List[ str ]:
    """
    Reachable `test_*.py` files that define no test — the invisible-visible class.

    These sit INSIDE a gated root and are correctly named, so every surface a
    reader consults says "covered", while the file contributes nothing pytest
    can run. A gate that catches unreferenced files but misses these answers
    half its own question.

    Detection is static: a file counts as collectible when it defines a
    module-level `test_*` function (sync or async) or a `Test*` class, matching
    pytest.ini's `python_functions` / `python_classes` patterns. A file pytest
    cannot parse is NOT reported here — a syntax error already fails collection
    loudly, which is the opposite of the silence this hunts.

    Requires:
        - project_root is a directory containing a `src` subdirectory
        - allowlist maps a repo-relative path to a reason string

    Ensures:
        - returns a sorted list of repo-relative paths
        - returns only files reachable by a gate-invocable runner
        - returns no path present in allowlist
    """
    targets  = find_gate_targets( project_root )
    barren   = []

    for relative in find_test_file_population( project_root ):
        if relative in allowlist: continue
        if not _is_reachable( relative, targets ): continue
        if _defines_a_test( project_root / relative ): continue
        barren.append( relative )

    return sorted( barren )


def find_stale_allowlist_entries( project_root: Path, allowlist: Dict[ str, str ] ) -> List[ str ]:
    """
    Allowlist entries that no longer describe an unreachable test file.

    The ledger excuses two conditions — UNREFERENCED and ZERO-COLLECT — so an
    entry earns its place by satisfying either one. It goes stale when it
    satisfies neither: the file was deleted, or it was both wired into a gate
    AND given real tests, and the exemption was never withdrawn. Both leave a
    standing excuse for a condition that no longer holds — the same shape as a
    doc asserting coverage that stopped existing.

    Requires:
        - project_root is a directory containing a `src` subdirectory
        - allowlist maps a repo-relative path to a reason string

    Ensures:
        - returns a sorted list of allowlisted paths that are absent, or that are
          both gate-reachable and test-defining
        - never reports an entry that is still unreferenced or still zero-collect
    """
    targets    = find_gate_targets( project_root )
    population = find_test_file_population( project_root )

    stale = []
    for relative in allowlist:
        if relative not in population:
            stale.append( relative )
        elif _is_reachable( relative, targets ) and _defines_a_test( project_root / relative ):
            stale.append( relative )

    return sorted( stale )


def _is_reachable( relative: str, targets: Set[ str ] ) -> bool:
    """
    Whether `relative` is named by a target, directly or via an ancestor directory.

    Requires:
        - relative is a repo-relative POSIX path
        - targets holds repo-relative POSIX paths with no trailing slash

    Ensures:
        - returns True iff relative equals a target or sits under a target directory
    """
    if relative in targets: return True

    return any( parent.as_posix() in targets for parent in Path( relative ).parents )


def _defines_a_test( path: Path ) -> bool:
    """
    Whether a file defines anything pytest would collect as a test.

    pytest collects by TWO independent rules, and this hunts for files that
    satisfy NEITHER. The `python_classes = Test*` name prefix is only the first;
    the second is `unittest.TestCase` inheritance, which pytest collects
    REGARDLESS of the class name. A detector that knew only the prefix reported
    every `class FooTests( unittest.TestCase )` file as contributing nothing —
    three such files, each holding real passing tests, were named as barren on
    2026-08-01 (row 663433a7).

    Requires:
        - path names an existing file

    Ensures:
        - returns True if a module-level `test_*` function or `Test*` class is defined
        - returns True for a module-level `unittest.TestCase` subclass that defines
          at least one `test_*` method
        - returns False for a TestCase subclass with NO test method — pytest
          collects nothing from it, which is exactly the silence this hunts
        - returns True when the file cannot be parsed — an unparseable file fails
          collection loudly and is not the silent class this hunts
    """
    try:
        tree = ast.parse( path.read_text( encoding="utf-8" ) )
    except SyntaxError:
        return True

    for node in tree.body:
        if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) and node.name.startswith( "test_" ): return True
        if isinstance( node, ast.ClassDef ):
            if node.name.startswith( "Test" ): return True
            if _is_test_case_subclass( node ) and _has_a_test_method( node ): return True

    return False


def _is_test_case_subclass( node: ast.ClassDef ) -> bool:
    """
    Whether a class declares a `TestCase`-shaped base.

    Keyed on the base's trailing NAME so both import spellings land — bare
    `TestCase` and dotted `unittest.TestCase` — plus the async variant
    `IsolatedAsyncioTestCase`. It CANNOT see inheritance through a project-local
    intermediate base (`class Mine( OurBase )`); such a file still reads as
    barren and needs a ledger entry. Deliberately narrow: any base at all would
    admit files pytest does not collect, which is the opposite failure.

    Requires:
        - node is an ast.ClassDef

    Ensures:
        - returns True iff some base's trailing identifier ends with "TestCase"
    """
    for base in node.bases:
        if   isinstance( base, ast.Name      ) and base.id.endswith(   "TestCase" ): return True
        elif isinstance( base, ast.Attribute ) and base.attr.endswith( "TestCase" ): return True

    return False


def _has_a_test_method( node: ast.ClassDef ) -> bool:
    """
    Whether a class body defines at least one `test_*` method.

    The narrowing half of the TestCase rule: a TestCase subclass holding only
    helpers emits nothing, so accepting it on inheritance alone would let a
    genuinely barren file through the census.

    Requires:
        - node is an ast.ClassDef

    Ensures:
        - returns True iff some direct body member is a (sync or async) function
          whose name starts with "test_"
    """
    return any(
        isinstance( child, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) and child.name.startswith( "test_" )
        for child in node.body
    )
