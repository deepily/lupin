"""
Unit tests for `src/tests/e2e_ui/selector_guard.py` — row `04735b66`.

THE THING BEING GUARDED IS A GUARD, so these tests are written against the property that
matters: it must be able to FAIL. A classifier that returns SHIPPED for everything passes
every test written only over shipped selectors, so every case below that asserts a positive
verdict is paired with one that asserts a refusal.

The fixture tree is written from literals here rather than read from the real checkout. A test
whose expected value is derived from the same source the code reads is a tautology wearing an
assertion's clothes — it agrees with the product by construction and cannot notice a parse
that has stopped working.
"""
import os, pathlib, sys

import pytest

sys.path.insert( 0, str( pathlib.Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui" ) )

import selector_guard as sg


# --------------------------------------------------------------------------------------
# fixture tree — a miniature of the real layout, with every anchor family represented
# --------------------------------------------------------------------------------------
MUX_HTML = """
<div id="fleet-status-pane" data-testid="multiplexer-fleet-status-pane"></div>
<div id="task-list-pane" data-testid="multiplexer-task-list-pane"></div>
"""

LEGACY_HTML = """
<div class="collapsible-section" id="section-fleet-status">
  <span id="auth-status" data-testid="notifications-auth-status"></span>
  <div class="section-content" id="fleet-status-section"></div>
</div>
"""

TOOLBAR_TS = """
export const SECTION_TOGGLES = [
  { sectionId: "fleet-status-pane", label: "Fleet" },
  { sectionId: "commons-activity-pane", label: "Commons" },
];
"""

RENDER_TS = """
el.setAttribute( "data-testid", "multiplexer-holding-area-badge" );
btn.setAttribute( "data-testid", `multiplexer-jobs-filter-${mode}-btn` );
pill.setAttribute( "data-testid", `multiplexer-${ pillIdFor( status ) }` );
const node = document.querySelector( "#commons-activity-pane" );
const other = document.getElementById( "runtime-only-pane" );
const helper = range( "multiplexer-flow-ratio-threshold", "0", "200" );
"""


@pytest.fixture
def root( tmp_path ):
    """A minimal checkout the guard can parse. Written from literals, not copied."""
    ( tmp_path / "src/lupin_app/static/html" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/js/multiplexer/render/templates" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/js/shared" ).mkdir( parents=True )
    ( tmp_path / "src/lupin_app/static/js/nav" ).mkdir( parents=True )
    ( tmp_path / sg.MULTIPLEXER_HTML   ).write_text( MUX_HTML )
    ( tmp_path / sg.NOTIFICATIONS_HTML ).write_text( LEGACY_HTML )
    ( tmp_path / sg.SECTION_TOOLBAR    ).write_text( TOOLBAR_TS )
    ( tmp_path / "src/lupin_app/static/js/multiplexer/render/R.ts" ).write_text( RENDER_TS )
    ( tmp_path / "src/lupin_app/static/js/notifications.js"        ).write_text( "// legacy\n" )
    ( tmp_path / "src/lupin_app/static/js/broadcast-panel.js"      ).write_text( "// panel\n" )
    return tmp_path


@pytest.fixture
def parsed( root ):
    return sg.load_registry( root ), sg.load_page_anchors( root )


# --------------------------------------------------------------------------------------
# _root
# --------------------------------------------------------------------------------------
def test_root_prefers_the_explicit_argument_over_the_environment( root, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", "/not/this/one" )
    assert sg._root() == pathlib.Path( "/not/this/one" )


def test_root_refuses_when_lupin_root_is_unset( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( RuntimeError, match="LUPIN_ROOT not set" ):
        sg._root()


# --------------------------------------------------------------------------------------
# load_registry — and its refusal, which is the interesting half
# --------------------------------------------------------------------------------------
def test_load_registry_reads_the_products_own_section_list( root ):
    assert sg.load_registry( root ) == { "fleet-status-pane", "commons-activity-pane" }


def test_load_registry_refuses_an_empty_parse_rather_than_passing_vacuously( root ):
    """An empty registry makes every selector look RUNTIME_INJECTED — the guard would pass
    on exactly the selectors it exists to refuse."""
    ( root / sg.SECTION_TOOLBAR ).write_text( "export const SECTION_TOGGLES = [];" )
    with pytest.raises( RuntimeError, match="ZERO sectionIds" ):
        sg.load_registry( root )


def test_load_registry_falls_back_to_the_environment_root( root, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
    assert "fleet-status-pane" in sg.load_registry()


# --------------------------------------------------------------------------------------
# load_page_anchors — the provenance split is the whole point
# --------------------------------------------------------------------------------------
def test_anchors_are_split_by_provenance_across_both_surfaces( parsed ):
    _registry, a = parsed
    assert "fleet-status-pane"             in a[ "html_ids"     ]   # multiplexer page
    assert "section-fleet-status"          in a[ "html_ids"     ]   # legacy page
    assert "multiplexer-fleet-status-pane" in a[ "html_testids" ]
    assert "notifications-auth-status"     in a[ "html_testids" ]
    assert "commons-activity-pane"         in a[ "ts_ids"       ]   # querySelector in TS
    assert "runtime-only-pane"             in a[ "ts_ids"       ]   # getElementById in TS
    assert "multiplexer-holding-area-badge" in a[ "ts_testids"  ]   # setAttribute in TS


def test_a_testid_passed_to_a_render_helper_is_an_anchor( parsed ):
    """`range( "multiplexer-flow-ratio-threshold", … )` never touches an attribute in that
    file, and dropping this family turned four live anchors into false DEAD verdicts."""
    _registry, a = parsed
    assert "multiplexer-flow-ratio-threshold" in a[ "ts_testids" ]


def test_template_composed_testids_are_collected_as_patterns( parsed ):
    _registry, a = parsed
    assert "multiplexer-jobs-filter-${mode}-btn" in a[ "ts_testid_patterns" ]


def test_anchors_refuse_an_html_parse_that_found_nothing( root ):
    ( root / sg.MULTIPLEXER_HTML   ).write_text( "<div></div>" )
    ( root / sg.NOTIFICATIONS_HTML ).write_text( "<div></div>" )
    with pytest.raises( RuntimeError, match="no ids or no testids" ):
        sg.load_page_anchors( root )


def test_anchors_refuse_an_html_with_ids_but_no_testids( root ):
    ( root / sg.MULTIPLEXER_HTML   ).write_text( '<div id="a"></div>' )
    ( root / sg.NOTIFICATIONS_HTML ).write_text( '<div id="b"></div>' )
    with pytest.raises( RuntimeError, match="no ids or no testids" ):
        sg.load_page_anchors( root )


def test_anchors_refuse_a_script_parse_that_found_no_testids( root ):
    ( root / "src/lupin_app/static/js/multiplexer/render/R.ts" ).write_text( "// nothing\n" )
    with pytest.raises( RuntimeError, match="script anchor parse found no testids" ):
        sg.load_page_anchors( root )


def test_anchors_fall_back_to_the_environment_root( root, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
    assert sg.load_page_anchors()[ "html_ids" ]


# --------------------------------------------------------------------------------------
# template handling — the part the negative control caught twice
# --------------------------------------------------------------------------------------
def test_template_to_regex_escapes_literal_segments():
    """An unescaped `.` would widen the match to any character."""
    rx = sg.template_to_regex( "a.b-${x}-c" )
    assert rx.fullmatch( "a.b-zz-c" )
    assert not rx.fullmatch( "aXb-zz-c" )


def test_template_holes_require_at_least_one_character():
    rx = sg.template_to_regex( "pane-${x}-end" )
    assert rx.fullmatch( "pane-a-end" )
    assert not rx.fullmatch( "pane--end" )


@pytest.mark.parametrize( "template, ok, why", [
    ( "multiplexer-jobs-filter-${mode}-btn", True,  "bounded on both sides" ),
    ( "${ tid }-${ field }",                 False, "hole-first: matches nearly every name" ),
    ( "multiplexer-${ pillIdFor(s) }",       False, "hole-last: vouches for every multiplexer- name" ),
    ( "ab-${x}-c",                           False, "leading literal shorter than the floor" ),
    ( "pane-${a}${b}-x",                     False, "two adjacent holes leave an unbounded middle" ),
    ( "no-holes-at-all",                     False, "not a template" ),
] )
def test_only_a_bounded_template_may_vouch_for_a_name( template, ok, why ):
    assert sg.is_anchoring_template( template ) is ok, why


def test_matching_template_returns_the_template_so_the_message_can_name_it():
    tpls = { "multiplexer-jobs-filter-${mode}-btn" }
    assert sg.matching_template( "multiplexer-jobs-filter-own-btn",
                                 tpls ) == "multiplexer-jobs-filter-${mode}-btn"


def test_matching_template_returns_none_for_a_name_no_template_builds():
    assert sg.matching_template( "multiplexer-nope", { "multiplexer-x-${m}-btn" } ) is None


def test_matching_template_refuses_an_open_ended_template():
    """The exact case the self-test's negative control caught: an absorbent template must not
    be allowed to explain a name."""
    assert sg.matching_template( "multiplexer-not-a-real-surface", { "${ tid }-${ field }" } ) is None


# --------------------------------------------------------------------------------------
# classify_selector — four states, each with a positive AND a refusal
# --------------------------------------------------------------------------------------
def test_an_id_in_the_served_page_is_shipped( parsed ):
    registry, anchors = parsed
    state, detail = sg.classify_selector( "#fleet-status-pane", registry, anchors )
    assert state == "SHIPPED_ID"
    assert "fleet-status-pane" in detail


def test_a_legacy_id_is_shipped_too_and_not_falsely_dead( parsed ):
    """The hole found by the census: a multiplexer-only authority called 206 live legacy
    selectors DEAD."""
    registry, anchors = parsed
    assert sg.classify_selector( "#section-fleet-status", registry, anchors )[ 0 ] == "SHIPPED_ID"


def test_an_id_named_only_by_the_registry_is_runtime_injected( parsed ):
    registry, anchors = parsed
    state, detail = sg.classify_selector( "#commons-activity-pane", registry, anchors )
    assert state == "RUNTIME_INJECTED"
    assert "created at runtime" in detail


def test_an_id_in_no_source_at_all_is_dead( parsed ):
    registry, anchors = parsed
    state, detail = sg.classify_selector( "#no-such-pane", registry, anchors )
    assert state == "DEAD"
    assert "neither the served page" in detail


def test_a_testid_in_the_served_page_is_shipped( parsed ):
    registry, anchors = parsed
    assert sg.classify_selector(
        '[data-testid="multiplexer-fleet-status-pane"]', registry, anchors )[ 0 ] == "SHIPPED_TESTID"


def test_a_testid_set_from_typescript_is_runtime_injected( parsed ):
    registry, anchors = parsed
    state, detail = sg.classify_selector(
        '[data-testid="multiplexer-holding-area-badge"]', registry, anchors )
    assert state == "RUNTIME_INJECTED"
    assert "set from TypeScript" in detail


def test_a_template_composed_testid_is_runtime_injected_and_names_its_template( parsed ):
    registry, anchors = parsed
    state, detail = sg.classify_selector(
        '[data-testid="multiplexer-jobs-filter-own-btn"]', registry, anchors )
    assert state == "RUNTIME_INJECTED"
    assert "COMPOSED at runtime" in detail
    assert "multiplexer-jobs-filter-${mode}-btn" in detail


def test_the_selector_that_caused_this_module_is_still_dead( parsed ):
    """`multiplexer-fleet-pane` is the original defect. Every widening since has been checked
    against it — a guard that stops failing here has stopped working."""
    registry, anchors = parsed
    state, detail = sg.classify_selector(
        '[data-testid="multiplexer-fleet-pane"]', registry, anchors )
    assert state == "DEAD"
    assert "shipped by nothing" in detail
    assert "nearest shipped" in detail


def test_a_dead_testid_with_no_near_miss_says_so_without_a_suggestion( parsed ):
    registry, anchors = parsed
    state, detail = sg.classify_selector( '[data-testid="zzz-unrelated"]', registry, anchors )
    assert state == "DEAD"
    assert "nearest shipped" not in detail


def test_an_unrecognised_shape_is_dead_rather_than_silently_skipped( parsed ):
    registry, anchors = parsed
    state, detail = sg.classify_selector( "div.section > span", registry, anchors )
    assert state == "DEAD"
    assert "unrecognised selector shape" in detail


# --------------------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------------------
def test_preflight_returns_a_verdict_per_selector_when_all_resolve( root ):
    v = sg.preflight( [ "#fleet-status-pane", '[data-testid="multiplexer-task-list-pane"]' ], root )
    assert set( v ) == { "#fleet-status-pane", '[data-testid="multiplexer-task-list-pane"]' }
    assert all( st.startswith( "SHIPPED" ) for st, _d in v.values() )


def test_preflight_names_every_dead_selector_not_merely_the_first( root ):
    """Reporting one at a time hides the rest behind a fix-and-rerun cycle each."""
    with pytest.raises( sg.DeadSelector ) as e:
        sg.preflight( [ "#fleet-status-pane", "#ghost-one", "#ghost-two" ], root )
    msg = str( e.value )
    assert "#ghost-one" in msg and "#ghost-two" in msg
    assert "2 of 3 selectors" in msg
    assert "PROBE BUG" in msg


def test_preflight_falls_back_to_the_environment_root( root, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
    assert sg.preflight( [ "#fleet-status-pane" ] )


# --------------------------------------------------------------------------------------
# self_test — the guard's own five cases, run against the REAL checkout
# --------------------------------------------------------------------------------------
def test_self_test_passes_against_the_real_checkout( monkeypatch, capsys ):
    """This is the case that would have caught every widening regression in this module. It
    runs the shipped self_test over the real tree, not the fixture."""
    monkeypatch.setenv( "LUPIN_ROOT", str( pathlib.Path( __file__ ).resolve().parents[ 3 ] ) )
    sg.self_test()
    assert "self-test passed 5/5" in capsys.readouterr().out


def test_self_test_raises_when_a_case_is_wrong( root, monkeypatch ):
    """Prove the self-test can fail. A self-test that cannot fail is decoration — and this one
    DID fail, twice, on the template widening, which is the only reason that widening is
    correct."""
    monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
    # Ship the selector the self-test expects to be DEAD; its case must now go wrong.
    ( root / sg.MULTIPLEXER_HTML ).write_text(
        MUX_HTML + '<div data-testid="multiplexer-fleet-pane"></div>' )
    with pytest.raises( SystemExit, match="self-test FAILED" ):
        sg.self_test()
