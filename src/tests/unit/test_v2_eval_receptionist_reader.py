"""
Row c242166d — the eval harness must not report a deliberate receptionist as a failure.

THE SHAPE. Two different outcomes arrive with the same `path`:

    somebody ASKED FOR the receptionist   -> route_reason "user_picked_receptionist"
    nothing could serve the request       -> route_reason "unknown_command"

`path` staying "receptionist" for both is correct — the receptionist genuinely served the
request either way. What differs is WHY it was reached, and route_reason is the field whose
job is naming which rule fired. Row 1568269d landed that marker at ced053a1, so the FLOW can
tell them apart. This row is about the READERS that still could not.

⚠️ LATENT, NOT LIVE — and that distinction belongs in the record so nobody reads this as a
miscount that shipped. `PATH_RECEPTIONIST` was declared in v2_eval.py and never used
anywhere in the file; only PATH_REPLAY was ever read. Nothing was being scored wrongly. The
constant was a loaded trap for whoever reached for it next, which is exactly how Clayton put
it when he recommended the marker: it is "unused today, which means the next person to use
it inherits the conflation." Bug 38815328 is the precedent from the other side — a warm pass
where 117 of 300 requests came back as the receptionist and 115 could not say why.

WHAT THE TRAP WOULD HAVE COST, measured rather than assumed (2026-08-24, seven warm-pass
artifacts under io/v2-flow/): 910 receptionist outcomes in total, 26-31% of each recent
100-request run and 197 of 300 on the 08-17 pass. A reader scoring receptionist outcomes as
failures would mis-score roughly a quarter of every warm pass from the day it was wired up.

⚠️ SO THE POINT OF THIS FILE IS THE SOURCE GUARD AS MUCH AS THE PREDICATE. A predicate
nobody is obliged to call fixes nothing — it is the same inert constant with a longer name.
test_no_bare_receptionist_failure_test_in_the_harness fails the build if a bare
`== PATH_RECEPTIONIST` comparison reappears in v2_eval.py, so the trap cannot be inherited.

Venue: :7999-eligible. Pure function calls plus one source read; no server, no state
mutation, no network.
"""

import os
import re
import sys

import pytest

import cosa.utils.util as cu

# v2_eval lives in src/scripts/, which is not a package on the default path.
_SCRIPTS = os.path.join( cu.get_project_root(), "src", "scripts" )
if _SCRIPTS not in sys.path:
    sys.path.insert( 0, _SCRIPTS )

import v2_eval                                                    # noqa: E402


HARNESS_SRC = os.path.join( _SCRIPTS, "v2_eval.py" )


def _record( path, route_reason, ok=True ):
    """
    Build a harness record the accessors can read.

    Ensures:
        - shape matches what response_path / response_route_reason expect: an "ok" flag
          plus a decoded "payload"
        - a key is OMITTED rather than set to None when the value is None, so the
          missing-marker case is genuinely missing and not merely null
    """
    payload = {}
    if path         is not None: payload[ "path" ]         = path
    if route_reason is not None: payload[ "route_reason" ] = route_reason
    return { "ok": ok, "payload": payload }


# ---------------------------------------------------------------------------
# The distinction itself
# ---------------------------------------------------------------------------

def test_a_deliberately_picked_receptionist_is_NOT_a_degrade():
    """THE BUG. Somebody asked for the receptionist and got it: the system worked."""
    r = _record( "receptionist", "user_picked_receptionist" )
    assert v2_eval.is_receptionist_degrade( r ) is False, \
        "a deliberate pick was reported as a routing failure — the exact defect of row c242166d"


def test_an_unroutable_request_that_fell_through_IS_a_degrade():
    """
    The other door, and the control that keeps the test above from being vacuous. If this
    were False too the predicate would simply never fire and would 'pass' by seeing nothing —
    the failure mode this whole family of rows is about.
    """
    r = _record( "receptionist", "unknown_command" )
    assert v2_eval.is_receptionist_degrade( r ) is True, \
        "a real routing failure was not counted — the predicate is blind, not lenient"


def test_a_receptionist_with_NO_marker_at_all_counts_as_a_degrade():
    """
    Every degrade looked like this before the ced053a1 marker existed, and all seven
    artifacts on disk still do. Treating an absent marker as a pick would silently un-count
    exactly the failures this predicate is for — so absence means degrade, and that choice is
    asserted here rather than left to whoever reads the implementation.
    """
    r = _record( "receptionist", None )
    assert v2_eval.is_receptionist_degrade( r ) is True


@pytest.mark.parametrize( "path", [ "replay", "agent", "needs_input" ] )
def test_a_non_receptionist_path_is_never_a_receptionist_degrade( path ):
    """Scoped to its own question. A replay or an agent answer has nothing to do with this
    predicate, whatever route_reason happens to say."""
    assert v2_eval.is_receptionist_degrade( _record( path, "unknown_command" ) ) is False


def test_a_request_that_did_not_complete_is_not_counted_here():
    """`ok` False means there is no reported path to read. Counting it as a receptionist
    degrade would invent a routing outcome for a request that never reported one."""
    assert v2_eval.is_receptionist_degrade( _record( "receptionist", "unknown_command", ok=False ) ) is False


def test_the_two_door_markers_match_the_strings_the_flow_actually_emits():
    """
    The seam. These constants are only useful if they are the SAME strings flow.py writes; a
    private copy that drifted would make every assertion above true about nothing. Asserted
    against the flow's own helper, not against a literal repeated in this file.
    """
    from cosa.rest.v2.flow import AskFlow

    receptionist = AskFlow.RECEPTIONIST_COMMAND
    assert AskFlow._unresolved_route_reason( receptionist ) == v2_eval.ROUTE_USER_PICKED_RECEPTIONIST
    assert AskFlow._unresolved_route_reason( "agent router go to nowhere" ) == v2_eval.ROUTE_UNKNOWN_COMMAND


# ---------------------------------------------------------------------------
# The guard that stops the trap being inherited
# ---------------------------------------------------------------------------

_OFFENDING_COMPARISON = re.compile( r"[=!]=\s*PATH_RECEPTIONIST|PATH_RECEPTIONIST\s*[=!]=" )


def test_no_bare_receptionist_failure_test_in_the_harness():
    """
    `PATH_RECEPTIONIST` must never be used as a bare equality test in v2_eval.py.

    This is the assertion that actually closes row c242166d rather than merely providing a
    better tool. The original defect was not a wrong number — nothing used the constant at
    all. It was a constant that would produce a wrong number for whoever picked it up. A
    predicate they are free to ignore does not fix that; a build failure does.

    The comparison inside is_receptionist_degrade itself is where the path check
    legitimately lives, so that function's body is excluded.
    """
    src = open( HARNESS_SRC, encoding="utf-8" ).read()

    marker = "def is_receptionist_degrade("
    assert marker in src, "is_receptionist_degrade is gone — this guard is now checking nothing"
    before, _, rest     = src.partition( marker )
    predicate, _, after = rest.partition( "\ndef " )

    hits = [ line.strip()
             for chunk in ( before, after )
             for line in chunk.splitlines()
             if _OFFENDING_COMPARISON.search( line ) and not line.strip().startswith( "#" ) ]

    assert not hits, (
        "v2_eval.py compares against PATH_RECEPTIONIST outside is_receptionist_degrade:\n"
        + "\n".join( f"    {h}" for h in hits )
        + "\nA receptionist outcome is NOT a failure by itself — a deliberate pick lands on the"
          "\nsame path. Use is_receptionist_degrade( record ), which reads route_reason (row c242166d)."
    )


def test_that_guard_can_actually_fire():
    """
    The guard above is a regex over source, so if the pattern were wrong it would report
    clean forever and this file would be one more green check that cannot see — the thing
    row c242166d is about. The pattern is therefore exercised against lines that SHOULD trip
    it and lines that should not, instead of being trusted because the real file is clean.
    """
    for bad in (
        'failures = [ r for r in ok if response_path( r ) == PATH_RECEPTIONIST ]',
        'if response_path( r ) != PATH_RECEPTIONIST: continue',
        'if PATH_RECEPTIONIST == response_path( r ): count += 1',
    ):
        assert _OFFENDING_COMPARISON.search( bad ), f"the guard's pattern does not catch: {bad}"

    for good in (
        'PATH_RECEPTIONIST = "receptionist"',
        'assert v2_eval.is_receptionist_degrade( r ) is True',
    ):
        assert not _OFFENDING_COMPARISON.search( good ), f"the guard's pattern false-positives on: {good}"
