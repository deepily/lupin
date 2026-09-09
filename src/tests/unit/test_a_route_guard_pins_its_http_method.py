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
The predicate asks whether a module DISCRIMINATES ON THE VERB, and that is NECESSARY and
NOT SUFFICIENT: it catches the file that never considered the verb at all, which is the
whole population above. It cannot tell a correct method assertion from a decorative
mention of the word. A file can satisfy this guard and still misdiagnose — a weaker defect
than the one being closed, and not claimed to be closed.

🔴 IT WAS ALSO BLIND IN THE OTHER DIRECTION, AND REFUSED THE BETTER TECHNIQUE. The first
predicate was the literal attribute name `methods`, and THREE baselined files were never
verb-blind at all. They build an ASGI scope carrying a "method" and assert
`route.matches( scope )[ 0 ] == Match.FULL`, which never names that attribute. Measured on
`/api/tasks/manager-pull` against the assembled router, one request per verb:

    GET    -> get_manager_pull FULL,  set_manager_pull PARTIAL
    PATCH  -> set_manager_pull FULL,  get_manager_pull PARTIAL
    POST   -> nothing FULL, every route PARTIAL

⇒ Scope matching is STRICTLY STRONGER than reading `.methods`: it pins the verb AND proves
  resolution ORDER, which is the shadowing defect this router has shipped twice. So the
  guard was flagging the rigorous files while it would pass one that merely says the word
  "methods" in a comment. Exactly backwards, and the same shape as the regex/AST error this
  file already records one paragraph up — an ENUMERATION standing in for a predicate.
⇒ Widening it by naming a second attribute would have MOVED that defect, not closed it:
  the next spelling buys you until file #24. So `_pins_the_verb` is written as the question
  the spellings approximate, not as today's two spellings.

🔴 THE THREE NAMES THAT LEFT THE BASELINE WERE FALSE POSITIVES OF THIS GUARD — NOT FILES
ANYONE EXEMPTED, AND THE DIFFERENCE IS THE WHOLE LEGITIMACY OF THE REMOVAL. A reader
finding three names gone from a ratchet cannot tell "the guard was wrong about them" from
"someone quieted them", and only the first is allowed. They are:
`test_the_approval_settings_door_is_operator_only.py`,
`test_the_asynchronous_promotion_resolves_or_shouts.py`,
`test_the_manager_pull_write_path_is_validated.py`. Each pinned its verb the whole time,
by the stronger method, and every one of them still does — check any of them and you will
find `Match.FULL`. Nothing in them was edited to earn the removal.

🔴 A RATCHET RATHER THAN A HARD GATE, DELIBERATELY. Eight files carry the gap today, down
from twelve as written — and the two causes must be read apart, because one is progress on
the tree and the other is not. THREE were STRUCK as the false positives above, which fixed
nothing. ONE was genuinely FIXED:
`test_the_assembled_app_reaches_the_promotion_gate.py` now resolves a real POST request
against the assembled app and asserts it lands on the transition route, so it can no longer
blame the promotion gate for a moved verb. ⇒ 12->8 is one file of progress and three of
arithmetic. A hard gate means editing eight files, several of them peers', in one sitting —
and this tree has live seats in it. So: NEW violations are refused immediately, and the
existing eight are recorded below as a list that may only SHRINK. When the last one goes, delete the baseline and the
`not in BASELINE` clause; the guard becomes the hard gate he asked for with no other
change.
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


def _builds_a_scope_naming_a_method( tree ):
    """
    Whether this module hands Starlette a request scope that names an HTTP method.

    🔴 THE SECOND SPELLING OF THE PINNING QUESTION, AND THE STRONGER ONE. A file doing
    `route.matches( { "method": "PATCH", ... } )[ 0 ] == Match.FULL` has pinned the verb
    more tightly than any `.methods` read — `Match.FULL` requires BOTH the path and the
    method, so a moved verb degrades every route to `Match.PARTIAL` and the file fails by
    name. It also proves resolution ORDER, which `.methods` cannot speak to at all.

    ⚠️ A DICT LITERAL, NOT A VARIABLE, AND THE LIMIT BELONGS IN THE OPEN. A module building
    its scope dynamically — `scope[ "method" ] = verb` — is not seen here and would still be
    flagged. That is the same NECESSARY-not-SUFFICIENT trade the module docstring names,
    pointing the other way, and it is a smaller population than the one this closes: all
    three files it was written for use a literal.

    Requires:
        - tree is a parsed module

    Ensures:
        - returns True iff some dict literal in the module carries a "method" key
        - never raises for a well-formed tree
    """
    return any(
        isinstance( node, ast.Dict ) and any(
            isinstance( key, ast.Constant ) and key.value == "method" for key in node.keys )
        for node in ast.walk( tree ) )


def _pins_the_verb( names, tree ):
    """
    THE PREDICATE BOTH SPELLINGS APPROXIMATE: does this module discriminate on the VERB?

    Written as the question rather than as an enumeration of the two ways a file answers it
    today, because this repo has now paid twice for an enumeration standing in for a
    predicate — the regex that under-reported `getattr`, and the `.methods` read that
    refused three scope-matching files.

    Requires:
        - names is the module's attribute-name set, tree its parsed module

    Ensures:
        - returns True iff the module reads `methods`, OR reads `matches` AND builds a
          scope naming a method
    """
    if "methods" in names: return True
    return "matches" in names and _builds_a_scope_naming_a_method( tree )


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
            tree = ast.parse( path.read_text( encoding="utf-8" ) )
        except SyntaxError:
            continue
        names = _attribute_names( tree )
        if "routes" in names and "path" in names:
            rel = path.relative_to( TESTS_ROOT )
            route_asserting.add( rel )
            if _pins_the_verb( names, tree ): pins_method.add( rel )
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
# 🔴 THIS LIST WENT 12 -> 8, AND ONLY ONE OF THE FOUR DEPARTURES WAS A FIX.
# `test_the_assembled_app_reaches_the_promotion_gate.py` was genuinely verb-blind — it built
# `paths` from `getattr( r, "path", None )`, asserted the path was mounted, then POSTed — and
# it was repaired: it now resolves a real POST scope and checks where that lands. The ratchet
# arm below is what forced this name out, exactly as designed; it failed by name the moment
# the file was fixed.
#
# The OTHER three that left were
# FALSE POSITIVES of the old `.methods` predicate — approval_settings_door_is_operator_only,
# asynchronous_promotion_resolves_or_shouts, manager_pull_write_path_is_validated — every
# one of which pinned its verb the whole time via `Match.FULL`, the stronger technique. See
# the module docstring. Nobody exempted them and nothing in them was edited. So the count of
# genuinely verb-blind files this guard has caused to be FIXED is still ZERO, and a reader
# comparing 12 to 9 must not read it as progress on the tree.
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
    "test_the_asynchronous_opt_in_refuses_a_string.py",
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


SCOPE_PINNERS = (
    "test_the_approval_settings_door_is_operator_only.py",
    "test_the_asynchronous_promotion_resolves_or_shouts.py",
    "test_the_manager_pull_write_path_is_validated.py",
)


def test_the_scope_half_of_the_predicate_is_ALIVE_and_can_still_FAIL():
    """
    🔴 A CONTROL PER HALF, BECAUSE A GUARD WITH TWO HALVES CAN LOSE ONE SILENTLY. The arms
    above prove the pair finds and splits a population; neither of them would notice the
    SCOPE half returning True for everything, or False for everything, because the
    `.methods` half alone still splits the tree. Mr. Radio 🦉 ruled this on 2026-09-09 —
    same argument María made for per-config typecheck arms: a wrong include blinds exactly
    one half, and a control aimed at the other half never sees it.

    So this arm does what the module docstring demands of every other detector here — it
    watches the half return a POSITIVE and a NEGATIVE, rather than only a positive.
    """
    reads_matches = { "matches", "routes", "path" }

    # ── the half says YES to a scope naming a method ──
    yes = ast.parse( 'route.matches( { "type": "http", "method": "PATCH", "path": DOOR } )' )
    assert _builds_a_scope_naming_a_method( yes )
    assert _pins_the_verb( reads_matches, yes )

    # ── and NO when the very same call carries no method — THE FAILING DIRECTION ──
    no = ast.parse( 'route.matches( { "type": "http", "path": DOOR } )' )
    assert not _builds_a_scope_naming_a_method( no ), (
        "the scope half answers True for a scope with no method in it, so it cannot refuse "
        "anything — a half that never says no is not a control"
    )
    assert not _pins_the_verb( reads_matches, no )

    # ── and the two halves are genuinely independent, not one wired to both outcomes ──
    assert _pins_the_verb( { "methods" }, no ), "the `.methods` half died when scope said no"
    assert not _pins_the_verb( { "routes", "path" }, yes ), (
        "a module that never reads `matches` is credited for a stray dict with a 'method' "
        "key — the scope half is not checking that the scope is handed to a router"
    )


@pytest.mark.parametrize( "name", SCOPE_PINNERS )
def test_a_scope_pinning_file_is_credited_by_the_SCOPE_half_and_not_the_other( name ):
    """
    🔴 THE ARM THAT KEEPS THE BASELINE REMOVAL HONEST. These three left BASELINE_UNPINNED
    because the guard was WRONG about them, not because anyone exempted them — and that
    claim is checkable, so it is checked here rather than only asserted in a comment.

    Each must be credited by the scope half SPECIFICALLY: it reads `matches`, builds a
    scope naming a method, and does NOT read `.methods`. If one ever gains a `.methods`
    read, this arm fails and tells the next reader the removal now rests on the other half
    — which is fine, but it must not happen silently, or the docstring above becomes a
    wrong reassurance about why three names are missing.
    """
    tree  = ast.parse( ( TESTS_ROOT / name ).read_text( encoding="utf-8" ) )
    names = _attribute_names( tree )

    assert "methods" not in names, (
        f"{name} now reads `.methods`, so it is no longer evidence that the SCOPE half "
        f"works. Re-point this arm at a file that still is, or the baseline removal loses "
        f"the measurement it was justified by."
    )
    assert _builds_a_scope_naming_a_method( tree ), f"{name} no longer builds a scope naming a method"
    assert _pins_the_verb( names, tree ), f"{name} is no longer credited as pinning its verb"


# ---------------------------------------------------------------------------
# THE REFUSAL
# ---------------------------------------------------------------------------

def test_a_new_route_guard_must_pin_its_http_method():
    """
    🔴 THE ARM THAT REFUSES. Any file asserting a route and not naming a method, other
    than the eight recorded in the baseline, fails here.
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
