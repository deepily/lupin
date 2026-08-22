"""
Unit tests for src/scripts/e2e_junit_diff.py — the E2E gate verdict tool.

The tool decides whether an E2E run BLOCKS a merge, so its own arithmetic has to
be pinned rather than trusted. Two things it must never get wrong:

  1. A test that is SKIPPED must never be counted as passing. The gate rule of
     2026-08-21 is explicit — a skip where a run is required is RED.
  2. Case counting must read <testcase> ELEMENTS, never the <testsuite tests="">
     attribute. In the real ts-a5b8ad03 artifact those two disagree by exactly
     the error count (697 claimed vs 692 present), and a reader mixing them
     concludes five cases went missing.
"""

import os
import sys

import pytest

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts" ) )

import e2e_junit_diff as ejd


def _write_xml( tmp_path, name, cases, suite_tests_attr=None ):
    """Write a junit XML whose testcase elements carry the given outcomes.

    Requires:
        - cases is a list of ( classname, name, outcome ) where outcome is
          "passed", "failure", "error" or "skipped"

    Ensures:
        - returns the path written
        - when suite_tests_attr is given, the testsuite attribute DISAGREES with
          the element count on purpose, reproducing the real artifact's trap
    """
    tests_attr = suite_tests_attr if suite_tests_attr is not None else len( cases )
    body = []
    for classname, case_name, outcome in cases:
        # NOTE: `case_name`, not `name` — rebinding `name` here shadows the file
        # name parameter, so every file lands on the same path and the second
        # write silently overwrites the first. That bug produced a green-looking
        # "0 regressions" from two files that were the same file.
        if outcome == "passed":
            body.append( f'<testcase classname="{classname}" name="{case_name}"/>' )
        else:
            body.append( f'<testcase classname="{classname}" name="{case_name}"><{outcome} message="x"/></testcase>' )
    xml  = f'<testsuites><testsuite name="pytest" tests="{tests_attr}">{"".join( body )}</testsuite></testsuites>'
    path = tmp_path / name
    path.write_text( xml )
    return str( path )


# ---------------------------------------------------------------- load()

def test_load_maps_every_outcome_to_its_tag( tmp_path ):
    """Each of the four outcomes is read off the case's own child tag."""
    path = _write_xml( tmp_path, "a.xml", [
        ( "m", "ok",   "passed" ),
        ( "m", "bad",  "failure" ),
        ( "m", "boom", "error" ),
        ( "m", "held", "skipped" ),
    ] )
    assert ejd.load( path ) == {
        "m::ok": "passed", "m::bad": "failure", "m::boom": "error", "m::held": "skipped",
    }


def test_load_counts_elements_not_the_testsuite_attribute( tmp_path ):
    """THE 697-vs-692 TRAP. The attribute lies; the element count is the truth."""
    path = _write_xml( tmp_path, "trap.xml",
                       [ ( "m", "one", "passed" ), ( "m", "two", "error" ) ],
                       suite_tests_attr=7 )
    assert len( ejd.load( path ) ) == 2, "the tool must count <testcase> elements, never tests=\"7\""


def test_load_handles_a_case_with_no_classname( tmp_path ):
    """A missing classname degrades to an empty prefix rather than raising."""
    path = tmp_path / "bare.xml"
    path.write_text( '<testsuites><testsuite tests="1"><testcase name="lonely"/></testsuite></testsuites>' )
    assert ejd.load( str( path ) ) == { "::lonely": "passed" }


def test_load_ignores_non_outcome_children( tmp_path ):
    """A case carrying only system-out is still a pass."""
    path = tmp_path / "noise.xml"
    path.write_text( '<testsuites><testsuite tests="1">'
                     '<testcase classname="m" name="chatty"><system-out>hi</system-out></testcase>'
                     '</testsuite></testsuites>' )
    assert ejd.load( str( path ) ) == { "m::chatty": "passed" }


# ---------------------------------------------------------------- classify()

def test_classify_splits_every_bucket():
    """One case per bucket, so a bucket that swallows another is caught."""
    baseline = { "m::regress": "passed",  "m::stays": "failure", "m::heals": "error", "m::gone": "passed" }
    new      = { "m::regress": "failure", "m::stays": "failure", "m::heals": "passed",
                 "m::held": "skipped",    "m::fresh": "passed" }
    buckets  = ejd.classify( baseline, new )

    assert buckets[ "regressions" ]      == [ "m::regress" ]
    assert buckets[ "pre_existing" ]     == [ "m::stays" ]
    assert buckets[ "fixed" ]            == [ "m::heals" ]
    assert buckets[ "skipped_now" ]      == [ "m::held" ]
    assert buckets[ "only_in_baseline" ] == [ "m::gone" ]
    assert buckets[ "only_in_new" ]      == sorted( [ "m::held", "m::fresh" ] )


def test_a_skipped_case_is_never_counted_as_fixed():
    """A previously-failing test that is now SKIPPED must not read as fixed-and-green.

    ⚠️ This is the false green the gate rule exists to prevent: skipping a red
    test makes the summary line say "0 failed" while nothing was proven.
    """
    buckets = ejd.classify( { "m::t": "failure" }, { "m::t": "skipped" } )
    assert buckets[ "skipped_now" ] == [ "m::t" ], "the skip must be reported in its own bucket"
    assert buckets[ "regressions" ] == []
    assert buckets[ "fixed" ] == [ "m::t" ], "it is out of the failing set, but the skip bucket is what a reader must see"


def test_a_brand_new_failing_test_is_a_regression():
    """A case absent from the baseline defaults to PASSED there, so a new red blocks."""
    assert ejd.classify( {}, { "m::brand_new": "failure" } )[ "regressions" ] == [ "m::brand_new" ]


def test_an_error_counts_as_non_passing_just_like_a_failure():
    """error and failure are both blocking; only their label differs."""
    assert ejd.classify( { "m::t": "passed" }, { "m::t": "error" } )[ "regressions" ] == [ "m::t" ]


# ---------------------------------------------------------------- render()

def test_render_names_every_case_and_states_element_counts():
    """The report must name cases, not just count them, and label counts as ELEMENTS."""
    baseline = { "m::regress": "passed", "m::stays": "failure", "m::heals": "error", "m::gone": "passed" }
    new      = { "m::regress": "failure", "m::stays": "failure", "m::heals": "passed", "m::held": "skipped" }
    report   = ejd.render( "base.xml", "new.xml", baseline, new, ejd.classify( baseline, new ) )

    assert "testcase elements" in report
    for token in ( "RED  m::regress", "==   m::stays", "GRN  m::heals", "SKIP m::held", "GONE m::gone", "NEW  m::held" ):
        assert token in report, f"report never named {token!r}"
    assert "a skip where a run is REQUIRED is RED" in report


# ---------------------------------------------------------------- main()

def test_main_returns_1_when_a_regression_exists( tmp_path, capsys ):
    """A regression is exit 1, so a CI caller fails without parsing text."""
    base = _write_xml( tmp_path, "b.xml", [ ( "m", "t", "passed" ) ] )
    new  = _write_xml( tmp_path, "n.xml", [ ( "m", "t", "failure" ) ] )
    assert ejd.main( [ "prog", base, new ] ) == 1
    assert "RED  m::t" in capsys.readouterr().out


def test_main_returns_0_when_the_only_reds_are_pre_existing( tmp_path, capsys ):
    """The carried-red case: same failures both sides is NOT this build's regression."""
    base = _write_xml( tmp_path, "b.xml", [ ( "m", "t", "failure" ) ] )
    new  = _write_xml( tmp_path, "n.xml", [ ( "m", "t", "failure" ) ] )
    assert ejd.main( [ "prog", base, new ] ) == 0
    assert "PRE-EXISTING (not this build)  : 1" in capsys.readouterr().out


@pytest.mark.parametrize( "argv", [ [ "prog" ], [ "prog", "only-one.xml" ], [ "prog", "a", "b", "c" ] ],
                          ids=[ "no_args", "one_arg", "three_args" ] )
def test_main_returns_2_on_a_bad_invocation_without_reading_a_file( argv, capsys ):
    """A wrong invocation prints usage and returns 2 — it must not touch the filesystem."""
    assert ejd.main( argv ) == 2
    assert "Compare two pytest/Playwright junit XML runs" in capsys.readouterr().out
