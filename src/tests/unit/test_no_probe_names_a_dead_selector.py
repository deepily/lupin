"""
THE GATE — no probe may name a selector the product does not ship. Row `485442ea`.

WHY THIS IS A UNIT TEST AND NOT AN e2e FIXTURE (Mr. Radio's ruling, 2026-09-23 18:18 EDT)
------------------------------------------------------------------------------------------
The guard has existed since 2026-09-22 and was wired into NOTHING: 2 selectors of 379 were
checked in fact. The obvious home was an e2e fixture, and it is the weaker one:

  · an e2e fixture can only guard the selectors of the tests ACTUALLY SELECTED. A `-k` filter
    or a half-split silently narrows it and then reports green over the smaller corpus —
    which is this epic's own defect, committed by the control meant to end it;
  · unit is merge gate 3, e2e is gates 10 and 11, so a dead selector dies six gates and the
    better part of an hour earlier;
  · the static half needs no page at all, so paying for a browser to run it buys nothing.

The page-DEPENDENT halves stay in e2e, where they belong: `assert_live_dom` for build drift
and `assert_section_altitude` for a selector at the wrong level.

WHAT IT REFUSES, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------
It refuses a selector whose ROOT anchor is shipped by nothing — the case that made
`multiplexer-fleet-pane` report a missing pane as a finding about the product. It does NOT
refuse a class-rooted selector, a jsdom query, or an interpolated name; each is declined for a
stated reason in `selector_census`, because a guard that returns a verdict it cannot support
is the thing being guarded against.

🔴 THE NEGATIVE CONTROL BELOW IS NOT DECORATION. A tree-wide sweep sees the guard's own
deliberate DEAD fixtures and cannot tell them from real defects — six of them at 65810c0e. A
gate written without that case goes red on day one and gets "fixed" with an allowlist, which
is an enumeration defect inside the fix for one.
"""
import pathlib, re, subprocess, sys

import pytest

sys.path.insert( 0, str( pathlib.Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui" ) )

import selector_census as sc

ROOT = pathlib.Path( __file__ ).resolve().parents[ 3 ]


# ==========================================================================================
# THE GATE
# ==========================================================================================
def test_no_enforceable_probe_names_a_dead_selector():
    """
    Ensures:
        - every selector at a page-driving locator call site resolves to something the
          product ships
        - the failure NAMES each dead selector, the guard's near-miss suggestion, and every
          file that uses it, so acting on it needs no second search
    """
    dead = sc.dead_in_enforced_population( ROOT )
    assert not dead, (
        "A probe names a selector the product ships NOWHERE. This is a PROBE BUG, not a\n"
        "finding about the product — a dead selector cannot tell you whether a surface is\n"
        "present, so no verdict about it is reportable.\n\n"
        + "\n".join( f"  {lit}\n      {detail}\n      used by: {files}"
                     for lit, ( detail, files ) in sorted( dead.items() ) ) )


def test_the_gate_states_its_denominator():
    """
    A guard that cannot say how many selectors it covers is describing its corpus, not the
    surface — the finding row 04735b66 exists for. This pins that the enforced population is
    non-trivial, so the gate above can never pass by guarding almost nothing.
    """
    population = sc.enforced_population( ROOT )
    rooted     = [ lit for lit in population if sc.root_anchor( lit ) is not None ]
    assert len( population ) >= 150, (
        f"the enforced population collapsed to {len( population )} selectors; the gate is now "
        "green over a corpus too small to mean anything — find out what stopped matching" )
    assert len( rooted ) >= 150


# ==========================================================================================
# CONTROLS — a gate nobody has watched fail is a gate nobody has tested
# ==========================================================================================
@pytest.fixture
def tree( tmp_path ):
    """A minimal checkout with one real probe, one jsdom test, and one guard-importing file."""
    ( tmp_path / "src/tests/e2e_ui" ).mkdir( parents=True )
    ( tmp_path / "src/tests/unit" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/html" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/js/multiplexer/render/templates" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/js/shared" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/js/nav" ).mkdir( parents=True )

    ( tmp_path / "src/lupin_app/static/html/multiplexer.html" ).write_text(
        '<div id="fleet-status-pane" data-testid="multiplexer-fleet-status-pane"></div>' )
    ( tmp_path / "src/lupin_app/static/html/notifications.html" ).write_text(
        '<div id="section-fleet-status"></div>' )
    ( tmp_path / "src/lupin_app/static/js/multiplexer/render/templates/sectionToolbar.ts" ).write_text(
        'export const T = [ { sectionId: "fleet-status-pane" } ];' )
    ( tmp_path / "src/lupin_app/static/js/multiplexer/render/R.ts" ).write_text(
        'el.setAttribute( "data-testid", "multiplexer-live-thing" );' )
    ( tmp_path / "src/lupin_app/static/js/notifications.js"   ).write_text( "// legacy\n" )
    ( tmp_path / "src/lupin_app/static/js/broadcast-panel.js" ).write_text( "// panel\n" )

    ( tmp_path / "src/tests/e2e_ui/test_real_probe.py" ).write_text(
        "def t( page ):\n"
        "    page.locator( '[data-testid=\"multiplexer-fleet-status-pane\"]' ).click()\n"
        "    page.locator( '#section-fleet-status .inner' ).count()\n" )

    subprocess.run( [ "git", "init", "-q" ], cwd=tmp_path, check=True )
    subprocess.run( [ "git", "add", "-A" ], cwd=tmp_path, check=True )
    subprocess.run( [ "git", "-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-qm", "seed" ], cwd=tmp_path, check=True )
    return tmp_path


def _commit( tree ):
    subprocess.run( [ "git", "add", "-A" ], cwd=tree, check=True )
    subprocess.run( [ "git", "-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-qm", "more" ], cwd=tree, check=True )


def test_control_a_clean_tree_is_green( tree ):
    """ARM A. Without this, the arm below is consistent with a gate that fires on everything."""
    assert sc.dead_in_enforced_population( tree ) == { }


def test_control_a_dead_selector_at_a_locator_call_reddens_the_gate( tree ):
    """ARM B. The gate must FIRE, and must name the file so the failure carries its own fix."""
    ( tree / "src/tests/e2e_ui/test_new_probe.py" ).write_text(
        "def t( page ):\n    page.locator( '[data-testid=\"multiplexer-ghost-pane\"]' ).click()\n" )
    _commit( tree )
    dead = sc.dead_in_enforced_population( tree )
    assert '[data-testid="multiplexer-ghost-pane"]' in dead
    _detail, files = dead[ '[data-testid="multiplexer-ghost-pane"]' ]
    assert files == [ "src/tests/e2e_ui/test_new_probe.py" ]


def test_control_a_dead_ROOT_under_a_compound_selector_also_reddens_it( tree ):
    """The 93 COMPOUND selectors go dead at the root exactly as a plain one does."""
    # The root must be SURFACE-SPELLED to be in scope at all: `#ghost-root` names neither
    # surface, so the surface predicate declines it before the guard is ever consulted.
    ( tree / "src/tests/e2e_ui/test_compound.py" ).write_text(
        "def t( page ):\n"
        "    page.locator( '[data-testid=\"multiplexer-ghost-root\"] .inner span' ).count()\n" )
    _commit( tree )
    dead = sc.dead_in_enforced_population( tree )
    assert '[data-testid="multiplexer-ghost-root"] .inner span' in dead


def test_control_the_guards_own_dead_fixtures_do_NOT_redden_it( tree ):
    """
    🔴 THE DAY-ONE CASE. Six deliberate DEAD literals live in the guard's own self-test and
    fixtures. A tree-wide sweep cannot tell them from real defects, and a gate that refuses
    them is red the moment it is written.
    """
    ( tree / "src/tests/unit/test_the_guard.py" ).write_text(
        "import selector_guard\n"
        "def t( page ):\n    page.locator( '[data-testid=\"multiplexer-ghost-pane\"]' ).click()\n" )
    _commit( tree )
    assert sc.dead_in_enforced_population( tree ) == { }, \
        "a file that imports the guard is the guard's own corpus, not a probe"


def test_control_a_jsdom_test_does_not_redden_it( tree ):
    """A jsdom test queries its own rendered output; the served page is the wrong oracle."""
    ( tree / "src/tests/unit/thing.test.ts" ).write_text(
        'page.locator( \'[data-testid="multiplexer-ghost-pane"]\' );\n' )
    _commit( tree )
    assert sc.dead_in_enforced_population( tree ) == { }


def test_control_a_dead_name_that_is_NOT_at_a_locator_call_does_not_redden_it( tree ):
    """
    A quoted CSS-shaped string in a list or a dict is not a lookup. Treating one as a lookup
    is how the census once invented selectors nobody had written and then reported them DEAD.
    """
    ( tree / "src/tests/e2e_ui/test_table.py" ).write_text(
        "CASES = [ '[data-testid=\"multiplexer-ghost-pane\"]' ]\n" )
    _commit( tree )
    assert sc.dead_in_enforced_population( tree ) == { }


def test_control_an_empty_population_refuses_rather_than_passing( tmp_path ):
    """A gate over nothing passes every assertion in it, and would report green forever."""
    ( tmp_path / "src/tests" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/html" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/html/multiplexer.html" ).write_text( '<div id="a" data-testid="b"></div>' )
    ( tmp_path / "src/lupin_app/static/html/notifications.html" ).write_text( '<div id="c"></div>' )
    ( tmp_path / "src/tests/nothing.py" ).write_text( "x = 1\n" )
    subprocess.run( [ "git", "init", "-q" ], cwd=tmp_path, check=True )
    subprocess.run( [ "git", "add", "-A" ], cwd=tmp_path, check=True )
    subprocess.run( [ "git", "-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-qm", "seed" ], cwd=tmp_path, check=True )
    with pytest.raises( RuntimeError, match="EMPTY" ):
        sc.enforced_population( tmp_path )


# ==========================================================================================
# the guard corpus must stay the guard corpus
# ==========================================================================================
def test_guard_corpus_is_exactly_the_guard_modules():
    """
    `GUARD_MODULES` is the one hand-written part of the exclusion, so it is the one part that
    can silently become an allowlist. Every name in it must really be a guard module that
    exists and defines guard API — otherwise somebody could exempt a probe by adding its
    filename here.
    """
    e2e = ROOT / "src/tests/e2e_ui"
    for name in sc.GUARD_MODULES:
        path = e2e / name
        assert path.is_file(), f"{name} is listed as a guard module but does not exist"
        body = path.read_text()
        assert re.search( r'\bdef (classify_selector|preflight|assert_live_dom|census'
                          r'|classify_altitude|enforced_population)\b', body ), \
            f"{name} is exempted as a guard module but defines no guard API"


def test_every_enforceable_file_is_excluded_for_a_derived_reason():
    """
    The three exclusion clauses must each be derived from what a file IS or DOES. This pins
    the behaviour rather than the wording: a fabricated file matching each clause is excluded,
    and a plain probe is not.
    """
    assert not sc.is_enforceable_file( "src/tests/unit/x.test.ts", "" )
    assert not sc.is_enforceable_file( "src/tests/e2e_ui/selector_guard.py", "" )
    assert not sc.is_enforceable_file( "src/tests/unit/t.py", "import selector_altitude\n" )
    assert not sc.is_enforceable_file( "src/tests/unit/t.py", "from .live_dom_check import x\n" )
    assert sc.is_enforceable_file( "src/tests/e2e_ui/test_thing.py", "page.locator( '#a' )\n" )


def test_control_a_class_rooted_selector_is_DECLINED_not_passed_and_not_failed( tree ):
    """
    A selector rooted at a CLASS (`.card [data-testid="multiplexer-ghost"]`) names the surface
    but gives the guard nothing it has authority over — the leading token is a class, and the
    guard knows nothing about classes.

    It is therefore SKIPPED rather than judged. That is the distinction this whole epic is
    about: declining to answer is a different act from answering "fine", and a guard that
    silently converts the first into the second is back to two states sharing one
    representation.
    """
    ( tree / "src/tests/e2e_ui/test_class_rooted.py" ).write_text(
        "def t( page ):\n"
        "    page.locator( '.card [data-testid=\"multiplexer-ghost\"]' ).count()\n" )
    _commit( tree )

    population = sc.enforced_population( tree )
    literal    = '.card [data-testid="multiplexer-ghost"]'
    assert literal in population, "it is in scope — it names the surface"
    assert sc.root_anchor( literal ) is None, "but it offers no anchor the guard can classify"
    assert sc.dead_in_enforced_population( tree ) == { }, "so the gate declines rather than failing it"
