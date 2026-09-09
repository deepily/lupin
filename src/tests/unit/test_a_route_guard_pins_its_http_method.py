"""
A ROUTE GUARD THAT DOES NOT PIN ITS METHOD MISDIAGNOSES A MOVED DOOR — the ratchet.

Mr. Radio 🦉 asked for this on 2026-09-09, in his words: "a guard that refuses. One test
that enumerates every test asserting a route and requires each to pin the HTTP method. It
must ask the population, not restate it."

🔴 THE DEFECT IT INSTALLS A REFUSAL AGAINST, measured on
`test_rick_alone_promotes_and_demotes.py` the same afternoon. That file asserted its route
PATH was mounted and said nothing about the METHOD. Two arms off one sha:

    verb moved to PATCH, method guard PRESENT -> 8 errors, each reading
        "mounted for ['POST'], and these arms send PATCH — a routing change wearing a
         permissions failure"
    verb moved to PATCH, method guard REMOVED -> 8 failures, each reading
        "promote was not refused for an account-less manager"

Same mutation, same production code. The second sends the next reader into the permissions
system for a routing change — and a wrong mechanism costs more than a wrong number,
because a wrong number gets re-derived and a wrong mechanism gets investigated.

⚠️ WHAT THIS GUARD CAN AND CANNOT SEE, said plainly so nobody reads more into a green.
The predicate is "this module reads `.methods` somewhere". That is NECESSARY and NOT
SUFFICIENT: it catches the file that never considered the verb at all, which is the whole
population above. It cannot tell a correct method assertion from a decorative mention of
the word. A file can satisfy this guard and still misdiagnose — that would be a weaker
defect than the one being closed, and it is not claimed to be closed.

🔴 A RATCHET RATHER THAN A HARD GATE, DELIBERATELY. Twelve files carry the gap today. A
hard gate means editing twelve files, several of them peers', in one sitting — and this
tree has live seats in it. So: NEW violations are refused immediately, and the existing
twelve are recorded below as a list that may only SHRINK. When the last one goes, delete
the baseline and the `not in BASELINE` clause; the guard becomes the hard gate he asked
for with no other change.
"""

import ast
import functools
import pathlib

import pytest


# 🔴 THE POPULATION IS DERIVED, NEVER LISTED. `rglob` walks whatever is on disk, so a test
# file added tomorrow is in scope the moment it exists. A hardcoded list is a rule that
# depends on somebody remembering to extend it, which is the shape this guard exists to
# replace.
TESTS_ROOT = pathlib.Path( __file__ ).resolve().parent


def _attribute_names( tree ):
    """
    Every attribute name this module reads, however it reads it.

    🔴 AST RATHER THAN A REGEX, AND THE REASON IS THIS REPO'S OWN RULE ABOUT CHARACTER
    CLASSES AND ALTERNATIONS UNDER-REPORTING. A text search for `.methods` misses
    `getattr( route, "methods", set() )` — which is precisely how a careful author writes
    it, so the sloppier the file the more likely a regex is to FIND it and the more
    careful the file the more likely a regex is to MISS it. Exactly backwards.

    ⚠️ MEASURED: a grep-based census of the same population, run an hour before this
    file, reported 22 route-asserting files. The AST finds 23 and disagrees about which —
    the grep both missed a `commons/` subdirectory file and counted files whose only
    "routes" hit was in prose. The grep was an approximation; this is the measurement.

    Requires:
        - tree is a parsed module

    Ensures:
        - returns the set of attribute names reached by attribute access AND by
          `getattr( x, "<literal>" )`
        - a non-literal getattr key is ignored rather than guessed at
        - never raises for a well-formed tree
    """
    names = set()
    for node in ast.walk( tree ):
        if isinstance( node, ast.Attribute ):
            names.add( node.attr )
        elif ( isinstance( node, ast.Call )
               and isinstance( node.func, ast.Name ) and node.func.id == "getattr"
               and len( node.args ) >= 2
               and isinstance( node.args[ 1 ], ast.Constant )
               and isinstance( node.args[ 1 ].value, str ) ):
            names.add( node.args[ 1 ].value )
    return names


# ⚠️ CACHED BECAUSE THIS PARSES ~975 FILES AND FIVE ARMS ASK FOR IT. Uncached the file
# cost 7.2s, which is the shape of guard people start deselecting. The cache is keyed on
# nothing, so it is one walk per session — fine for a guard that reads a tree pytest has
# already frozen by collecting it.
@functools.lru_cache( maxsize=1 )
def _classify():
    """
    Walk the tree once and split it: route-asserting, and of those, method-pinning.

    ROUTE-ASSERTING is `reads .routes AND reads .path` — a file looking through an app's
    route table for a path. That is the predicate the enumeration was approximating, and
    it is written as the predicate rather than as today's twenty-three filenames.

    ⚠️ A FILE THAT CANNOT BE PARSED IS COUNTED AS NEITHER, AND THAT IS A HOLE WORTH
    NAMING: a syntactically broken test is already failing collection loudly, so this
    guard staying quiet about it does not hide anything — but it does mean this
    denominator is "files that parse", not "files".

    Ensures:
        - returns ( route_asserting, pins_method ), both sets of paths relative to
          TESTS_ROOT, with pins_method a subset of route_asserting
    """
    route_asserting, pins_method = set(), set()
    for path in sorted( TESTS_ROOT.rglob( "*.py" ) ):
        if path.name == "__init__.py": continue
        try:
            names = _attribute_names( ast.parse( path.read_text( encoding="utf-8" ) ) )
        except SyntaxError:
            continue
        if "routes" in names and "path" in names:
            rel = path.relative_to( TESTS_ROOT )
            route_asserting.add( rel )
            if "methods" in names: pins_method.add( rel )
    # FROZEN before returning: a cached mutable set is one arm's edit away from being
    # another arm's input, and that failure reads as a flaky test rather than a shared
    # object.
    return frozenset( route_asserting ), frozenset( pins_method )


# ── THE BASELINE — IT MAY ONLY SHRINK ──────────────────────────────────────────
#
# Every file here asserts a route is mounted and says nothing about the method, as of
# 2026-09-09. They are not broken and none of them is a false green: a missing door
# answers 404 or 405 and their assertions name specific statuses, so they DO redden. What
# they would do is blame the wrong subsystem.
#
# 🔴 REMOVE A NAME WHEN YOU FIX THAT FILE. `test_the_baseline_has_not_gone_stale` FAILS if
# a listed file has been fixed or deleted, so the list cannot quietly rot into a
# permanent exemption — the one way a ratchet stops ratcheting.
BASELINE_UNPINNED = frozenset( {
    "test_decision_store.py",
    "test_dm_sender_project_required.py",
    "test_epic_stories_endpoint.py",
    "test_late_answer_reattach.py",
    "test_no_batch_door_for_task_verbs.py",
    "test_the_approval_settings_door_is_operator_only.py",
    "test_the_assembled_app_reaches_the_promotion_gate.py",
    "test_the_asynchronous_opt_in_refuses_a_string.py",
    "test_the_asynchronous_promotion_resolves_or_shouts.py",
    "test_the_manager_pull_write_path_is_validated.py",
    "test_v2_agents_endpoint.py",
    "test_versioned_static_assets_carry_a_cache_policy.py",
} )


# ---------------------------------------------------------------------------
# THE POSITIVE CONTROLS FIRST — a detector that finds nothing reports "clean"
# ---------------------------------------------------------------------------

def test_the_detector_finds_a_population_at_all():
    """
    🔴 WITHOUT THIS, A BROKEN PREDICATE PASSES EVERY ARM BELOW BY FINDING NOTHING. A
    negative result is worth nothing until you have watched the same search return a
    positive one, and an empty answer from a broken detector prints exactly like an empty
    answer from a clean tree.
    """
    route_asserting, _ = _classify()
    assert len( route_asserting ) >= 20, (
        f"the detector found only {len( route_asserting )} route-asserting files. It found "
        f"23 on 2026-09-09; a collapse means the predicate stopped matching, not that the "
        f"tree got tidy."
    )


def test_the_detector_can_tell_a_pinned_file_from_an_unpinned_one():
    """
    The discriminating control. The arm above proves the detector finds files; this proves
    it SPLITS them — a predicate that answered True for everything would satisfy the other
    one and refuse nothing.
    """
    route_asserting, pins_method = _classify()

    assert pins_method, "no file reads `.methods` — the pinning half of the predicate is dead"
    assert pins_method < route_asserting, (
        "every route-asserting file counts as pinned, so this guard cannot refuse anything"
    )
    assert pathlib.Path( "test_rick_alone_promotes_and_demotes.py" ) in pins_method, (
        "the file this guard was written from no longer reads `.methods` — either it "
        "regressed, or the predicate has stopped seeing it"
    )


# ---------------------------------------------------------------------------
# THE REFUSAL
# ---------------------------------------------------------------------------

def test_a_new_route_guard_must_pin_its_http_method():
    """
    🔴 THE ARM THAT REFUSES. Any file asserting a route and not naming a method, other
    than the twelve recorded in the baseline, fails here.
    """
    route_asserting, pins_method = _classify()
    unpinned = { str( p ) for p in ( route_asserting - pins_method ) }

    offenders = sorted( unpinned - BASELINE_UNPINNED )
    assert not offenders, (
        "these files look through an app's route table for a PATH and never check the "
        f"METHOD: {offenders}. A door that changes verbs then leaves the route assertion "
        "GREEN and reddens the arms below it with a message about permissions — a routing "
        "change wearing a permissions failure, which sends the next reader into innocent "
        "code. Assert the method too: find the matching route, union its `.methods`, and "
        "check it carries the verb your arms actually send. "
        "`test_rick_alone_promotes_and_demotes.py` is the worked example. Do NOT add a "
        "name to BASELINE_UNPINNED — that list may only shrink."
    )


def test_the_baseline_has_not_gone_stale():
    """
    🔴 THIS IS WHAT MAKES IT A RATCHET RATHER THAN A LIST OF EXEMPTIONS. A baseline nobody
    is forced to prune becomes permanent, and then the guard is measuring its own corpus
    instead of the tree.

    Fixing a listed file FAILS this arm, on purpose, with the instruction to delete the
    name. So does deleting the file.
    """
    route_asserting, pins_method = _classify()
    unpinned = { str( p ) for p in ( route_asserting - pins_method ) }

    fixed_or_gone = sorted( BASELINE_UNPINNED - unpinned )
    assert not fixed_or_gone, (
        f"these are in BASELINE_UNPINNED but no longer unpinned: {fixed_or_gone}. If you "
        f"fixed them, DELETE their names from the baseline — that is the ratchet tightening "
        f"and it is the point of this arm. If you deleted the files, delete the names too. "
        f"When the baseline reaches empty, remove it along with the `- BASELINE_UNPINNED` "
        f"clause above and this guard becomes the hard gate it was always meant to be."
    )


@pytest.mark.parametrize( "name", sorted( BASELINE_UNPINNED ) )
def test_every_baselined_file_still_exists( name ):
    """
    A baseline naming a file nobody can find is a rule about nothing. Separate from the
    arm above so a DELETED file and a FIXED one fail with different sentences — the two
    call for different edits, and a shared message would make the reader guess which.
    """
    assert ( TESTS_ROOT / name ).exists(), (
        f"BASELINE_UNPINNED names {name}, which is not on disk. Delete the name."
    )
