"""
The badge's number is the LOOP's, not the gate's — Rick's ruling, pinned.

🔴 WHAT THIS FILE GUARDS, AND WHY IT LOOKS LIKE AN OFF-BY-ONE. `ratio_loop_headroom`
returns ONE LESS than `ratio_gate_headroom` wherever the gate admits at all. That is
not a defect. Rick ruled it by keypress on 2026-09-05 at 13:11:13 EDT, on the option
labelled, verbatim:

    "Keep your three states - badge under-reports by one."

A real keypress, not a timeout default (relayed by Mr. Radio 🦉, who put four options
to him on row `307943fb`). The trade was named on the option he pressed: the badge says
there is no room while the gate would still take one more ticket. That is the SAFER
error for a moratorium, and the moratorium is why the feature exists.

⇒ SO A FUTURE READER WHO "FIXES" THE OFF-BY-ONE WOULD ALSO BE DELETING `FULL`, which
Rick ratified separately by keypress. `FULL` means N == 0, AT CAPACITY, STILL LEGAL.
Under gate semantics that state has NO INPUTS — headroom is 0 exactly when the gate
already refuses, which is the `CLOSE N` state. The two are one choice, not two.

🔴 AND THE LOAD-BEARING TEST IS NOT "loop == gate - 1". That arithmetic is a
restatement, and this project's own doctrine is that iterating over a restatement is
still a restatement. The test that carries the claim drives the ROW'S LITERAL LOOP —
quoted below from row `f7c4f537` — against the real advisory, one probe at a time, and
compares. Both sides driven; neither derived.

    "Loop: probe `created + 1`, `created + 2`, … recomputing the percentage each pass
     with `closed` HELD CONSTANT. Stop at the LAST increment that still PASSES the
     gate. That count is N."
"""
import pytest

from cosa.rest.task_store_rules import (
    ratio_gate_advisory,
    ratio_gate_headroom,
    ratio_gate_close_needed,
    ratio_loop_headroom,
)


def _the_rows_literal_loop( created, closed, allow_below, ceiling=4000 ):
    """
    Row f7c4f537's method, implemented literally and driven against the real gate.

    🔴 NOT A REIMPLEMENTATION OF THE THING UNDER TEST. It holds no threshold comparison
    — it asks `ratio_gate_advisory` whether the STATE AFTER k creates would be admitted,
    which is the row's "recomputing the percentage each pass". The function under test
    reaches the same number by a different route (the gate's own count, minus one), so
    the two sides have genuinely different provenance and the comparison can fail.

    Requires:
        - created / closed non-negative ints; allow_below the operator's threshold

    Ensures:
        - returns the LAST k >= 1 whose post-state still passes, or 0 if k == 1 already
          fails, or None if nothing fails below the ceiling
    """
    if ratio_gate_advisory( created, closed, allow_below=allow_below ) is not None:
        return None                      # already failing: CLOSE N's case, not the loop's

    last_passing = 0
    for k in range( 1, ceiling ):
        # "recomputing the percentage each pass" — the state AFTER k creates land.
        if ratio_gate_advisory( created + k, closed, allow_below=allow_below ) is None:
            last_passing = k
        else:
            return last_passing
    return None


# ---------------------------------------------------------------------------
# The load-bearing guard: the shipped function IS the row's loop.
# ---------------------------------------------------------------------------

GRID = [ ( c, cl, ab )
         for c  in ( 0, 1, 5, 9, 10, 14, 40, 100 )
         for cl in ( 0, 1, 3, 10, 13, 40 )
         for ab in ( 0.25, 0.5, 1.0, 2.0 ) ]


def test_the_shipped_number_equals_the_rows_own_loop_across_the_grid():
    """
    192 cells, both sides driven against the real advisory. This is the claim.
    """
    disagreements = [ ]
    for created, closed, allow_below in GRID:
        shipped = ratio_loop_headroom(     created, closed, allow_below )
        walked  = _the_rows_literal_loop(  created, closed, allow_below )
        if shipped != walked:
            disagreements.append( ( created, closed, allow_below, shipped, walked ) )

    assert disagreements == [ ], (
        "the badge must render the row's ratified loop, not something near it: "
        f"{disagreements[ :8 ]}"
    )


def test_the_grid_is_not_vacuous():
    """
    POSITIVE CONTROL. A loop over an all-None grid would pass the test above while
    measuring nothing — an empty discovery satisfies every per-item assertion.
    """
    answers = [ ratio_loop_headroom( c, cl, ab ) for c, cl, ab in GRID ]
    assert sum( a is not None for a in answers ) >= 20, "the grid must exercise real numbers"
    assert any( a == 0 for a in answers ),             "the grid must reach the FULL state"
    assert any( a  >  3 for a in answers ),            "the grid must reach ordinary room"


# ---------------------------------------------------------------------------
# The ruling itself, stated as behaviour rather than as arithmetic.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "created,closed,allow_below,loop,gate", [
    ( 10, 13, 1.0, 2,  3 ),      # the worked case from the row
    (  9, 10, 1.0, 0,  1 ),      # FULL — and the gate would still take one
    (  0, 10, 1.0, 9, 10 ),
    (  0, 10, 0.5, 4,  5 ),
    (  0,  0, 1.0, 0,  1 ),      # idle: FULL on an empty board
] )
def test_the_badge_under_reports_the_gate_by_exactly_one( created, closed, allow_below, loop, gate ):
    """
    Rick's ruling, in the only form that can fail if someone reverts it. Every row of
    this table is from row f7c4f537's own measured comparison.
    """
    assert ratio_gate_headroom( created, closed, allow_below ) == gate, "the gate's number"
    assert ratio_loop_headroom( created, closed, allow_below ) == loop, "what the badge renders"
    assert loop == gate - 1, "under-reports by exactly one, which is what he pressed"


def test_full_is_reachable_which_is_the_substance_of_the_ruling():
    """
    🔴 THE TEST THAT WOULD CATCH A REVERT TO GATE SEMANTICS. Under the gate's framing
    this assertion is unsatisfiable — 0 arrives only when the gate refuses, which the
    function reports as None. A reader who "fixed" the off-by-one would redden this and
    should then read the docstring rather than delete the test.
    """
    assert ratio_loop_headroom( 9, 10, 1.0 ) == 0, "at capacity and still legal — FULL"
    assert ratio_gate_advisory( 9, 10, allow_below=1.0 ) is None, "and the gate does still admit"


def test_an_already_failing_gate_returns_none_so_close_n_owns_it():
    """
    The honest answer past the line is NEGATIVE, not zero. Folding it into 0 would
    render FULL — making a breach and a healthy edge look identical, which row f7c4f537
    forbids in as many words.
    """
    for created, closed in ( ( 14, 3 ), ( 5, 0 ), ( 100, 10 ) ):
        assert ratio_loop_headroom( created, closed, 1.0 ) is None
        assert ratio_gate_close_needed( created, closed, 1.0 ) > 0, "CLOSE N has the answer"


def test_a_zero_threshold_yields_no_number_in_either_direction():
    """
    No closure opens a gate set to 0, so neither badge has a target. A number here would
    name one that does not exist — worse than no badge.
    """
    assert ratio_loop_headroom(     10, 13, 0.0 ) is None
    assert ratio_gate_close_needed( 10, 13, 0.0 ) is None


def test_it_never_reads_the_settings_module( monkeypatch ):
    """
    PURITY. The threshold is a live operator dial; two reads a second apart can differ,
    and then the badge and the gate describe different worlds while both are "correct".
    The caller reads it ONCE and passes it down. Booby-trap every getter.
    """
    from cosa.rest import flow_ratio_settings as frs

    def _boom( *a, **k ):
        raise AssertionError( "ratio_loop_headroom read the settings module" )

    monkeypatch.setattr( frs, "get_allow_below",        _boom )
    monkeypatch.setattr( frs, "get_window_hours",       _boom )
    monkeypatch.setattr( frs, "get_enforcement_active", _boom )

    assert ratio_loop_headroom( 10, 13, 1.0 ) == 2


def test_the_booby_trap_would_actually_fire( monkeypatch ):
    """
    POSITIVE CONTROL for the test above. A monkeypatch that silently failed to bind
    would make the purity test pass for the wrong reason — it would be asserting that
    nothing exploded when nothing was armed.
    """
    from cosa.rest import flow_ratio_settings as frs

    def _boom( *a, **k ):
        raise AssertionError( "armed" )

    monkeypatch.setattr( frs, "get_allow_below", _boom )
    with pytest.raises( AssertionError, match="armed" ):
        frs.get_allow_below()


# ---------------------------------------------------------------------------
# The distinction has to reach an API CONSUMER, not just a source reader.
# ---------------------------------------------------------------------------

def _flow_ratio_openapi_description():
    """
    The description FastAPI actually publishes for GET /api/tasks/flow-ratio.

    🔴 READ FROM THE ASSEMBLED SPEC, NOT FROM THE SOURCE TEXT. A test that grepped
    `tasks.py` would pass even if the description were never attached to the route —
    which is the whole failure this guard exists to prevent. This builds the router into
    an app and asks the app what it publishes.
    """
    from fastapi import FastAPI
    from cosa.rest.routers import tasks

    app = FastAPI()
    app.include_router( tasks.router )
    spec = app.openapi()

    paths = [ p for p in spec[ "paths" ] if p.endswith( "/tasks/flow-ratio" ) ]
    assert len( paths ) == 1, f"expected exactly one flow-ratio path, found {paths}"
    return spec[ "paths" ][ paths[ 0 ] ][ "get" ][ "description" ]


def test_the_published_api_docs_say_which_number_to_render():
    """
    🔴 A `#` COMMENT INSIDE A DICT LITERAL REACHES NOBODY OUTSIDE THIS REPO. Mr. Radio's
    call, 2026-09-05: the `room_for` / `headroom` distinction has to live where an API
    consumer will meet it, because a consumer holding two plausible capacity numbers will
    pick the one whose name sounds right and nothing will stop them.

    ⚠️ AND THE COST IS ASYMMETRIC: picking `headroom` does not merely report one too many,
    it destroys the `FULL` state Rick ratified — so the warning has to travel with the
    field, not sit in a source file the consumer never opens.
    """
    desc = _flow_ratio_openapi_description()

    for required in ( "room_for", "headroom", "close_needed" ):
        assert required in desc, f"the published description must name `{required}`"

    assert "RENDER `room_for`" in desc,  "it must say WHICH number to display"
    assert "Diagnostic only" in desc,    "it must mark `headroom` as not-for-display"
    assert "13:11:13" in desc,           "the ruling must be dated, or it reads as an opinion"
    assert "819dc891" in desc,           "and it must cite the ARTIFACT, not just a time"

    # 🔴 THE COLUMN, NOT JUST THE VALUE. `notifications` carries THREE timestamps —
    # created_at (question sent), responded_at (the keypress), expires_at. This stamp
    # was mis-stated twice in one hour by two people reading the wrong one, so the
    # published receipt names which column it came from and warns about the others.
    assert "responded_at" in desc,       "the receipt must name the COLUMN, not just the value"
    assert "created_at"  in desc,        "and warn about the column that is easy to grab instead"
    assert "FULL" in desc,               "the cost of switching fields must be named"


def test_the_description_probe_would_notice_an_empty_description():
    """
    POSITIVE CONTROL. Every assertion above is an `in` over a string; against an empty or
    missing description they would all fail, but against a description that merely LOST
    the warning they must still fail for the right reason. This pins that the probe
    reaches a real, substantial published document rather than a stub.
    """
    desc = _flow_ratio_openapi_description()
    assert len( desc ) > 800, f"published description is suspiciously short: {len( desc )} chars"
    assert "counted in SQL" in desc, "the pre-existing description must still be there too"


def test_the_published_worked_example_matches_what_the_code_actually_returns():
    """
    🔴 THE DOC'S NUMBERS ARE CHECKED AGAINST THE FUNCTIONS, NOT AGAINST A STRING.

    Mr. Radio's ask, 2026-09-05: put a worked example in the docs so nobody has to
    reconstruct the direction from prose. A worked example is the most useful thing in a
    doc and the first thing to go stale — it is written once, read forever, and nothing
    fails when the code moves out from under it.

    ⇒ So this test PARSES the numbers out of the published description and asserts they
    are what `ratio_loop_headroom` and `ratio_gate_headroom` really return for the stated
    inputs. If either function changes, the DOC goes red — which is the only way an
    example stays true.

    ⚠️ It also pins the DIRECTION, because that is the thing two readers got backwards
    today: `headroom` is `room_for` PLUS ONE, never minus. Both phrasings of that one fact
    are in the tree ("one MORE than room_for", "one LOWER than this number") and they are
    the same statement seen from opposite ends — which is precisely why an example beats
    another sentence.
    """
    import re

    desc = _flow_ratio_openapi_description()

    m = re.search( r"created (\d+), closed (\d+), allow_below ([\d.]+)", desc )
    assert m, "the published description must carry a worked example with stated inputs"
    created, closed, allow_below = int( m.group( 1 ) ), int( m.group( 2 ) ), float( m.group( 3 ) )

    doc_room = re.search( r"`room_for` \| \*\*(\d+)\*\*", desc )
    doc_head = re.search( r"`headroom` \| \*\*(\d+)\*\*", desc )
    assert doc_room and doc_head, "the example must state BOTH numbers, or it settles nothing"

    real_room = ratio_loop_headroom( created, closed, allow_below )
    real_head = ratio_gate_headroom( created, closed, allow_below )

    assert int( doc_room.group( 1 ) ) == real_room, (
        f"the docs claim room_for {doc_room.group( 1 )} for ({created},{closed},{allow_below}) "
        f"but the code returns {real_room}" )
    assert int( doc_head.group( 1 ) ) == real_head, (
        f"the docs claim headroom {doc_head.group( 1 )} for ({created},{closed},{allow_below}) "
        f"but the code returns {real_head}" )

    assert real_head == real_room + 1, "the direction: headroom is room_for PLUS one"
    assert "`headroom` is always `room_for` + 1" in desc, "and the docs must say so in words too"
