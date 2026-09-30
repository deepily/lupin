"""
CROSS-CLIENT COLUMN-HEADER PARITY — the gap that produced What/Title.

Row 67ffd249. Found and measured by Cheech 🌿 during a salvage on a lane already
declared dead, by reading landed source rather than by any instrument: "Nothing
anywhere compares column headers between the two clients."

=== WHAT WENT WRONG, AND WHY THREE INSTRUMENTS ALL MISSED IT ===

Rick ruled 2026-09-07 ~20:10 (row 86a5c818) that the `WHAT` column should read
`TITLE`. It shipped on the legacy client at 9cbad142 and did NOT reach the
multiplexer, whose own test asserted the superseded word — so that test PINNED
the defect rather than catching it.

  · The TS tier was GREEN, because a client's tests assert against THAT SAME
    client. A green tier says each client agrees with ITSELF. It can never say
    the two agree with EACH OTHER.
  · The parity oracle sounds like the right instrument and is not — measured:
    `test_tier1_accordions_cross_client.py` does not read column headers at all.
  · The gate wired that night touches this gap not at all.

=== WHY THIS LIVES IN THE UNIT TIER AND NOT IN THE PARITY ORACLE ===

The row required this choice be made deliberately and defended, because the
oracle is the OBVIOUS home and obvious is not the same as right. It goes here:

1. THE DEFECT CLASS IS A LITERAL THAT CHANGED IN ONE FILE AND NOT THE OTHER.
   Both headers are static text in a template string — verified before choosing
   this shape, and re-asserted below so the choice cannot rot silently. A source
   read is sufficient for that class, and sufficiency is the whole argument.

2. THE ORACLE'S CROSS-CLIENT TESTS DRIVE REAL PAGES. They need the dev container,
   and its own docstring documents the hazard: the container bind-mounts `./src`
   from the MAIN CHECKOUT, so a page served by :7999 is not necessarily the tree
   you are editing. It carries two served-tree guards for exactly that reason,
   and a documented false green on one field. A check that needs none of that
   should not inherit any of it.

3. A GUARD ONLY GUARDS IF IT RUNS. The oracle's cross-client tier is scheduled
   and venue-bound. This runs in the unit tier, on every tier, for free.

⇒ WHAT THIS DELIBERATELY DOES NOT COVER, said plainly rather than left implied:
   a header that is correct in SOURCE and wrong once RENDERED. That failure needs
   the oracle. If either client ever computes its headers instead of writing them
   out, `test_the_headers_are_static_literals_or_this_instrument_is_wrong` below
   goes red and this file must move rather than be patched.

⚠️ NOT ESTABLISHED, inherited from the row and not closed here: whether headers
are the only cross-client surface nobody compares, or merely the first one anyone
looked at. Nobody has swept. María's own note bets against headers being unique.
"""

import re
from pathlib import Path

import pytest

import cosa.utils.util as cu

LEGACY = Path( cu.get_project_root() ) / "src/lupin_app/static/js/notifications.js"
MUX    = Path( cu.get_project_root() ) / "src/lupin_app/static/js/multiplexer/render/templates/finishedTasksTable.ts"

# The table both clients render. Each anchors on its own data-testid, so this
# never silently compares two different tables that happen to carry a <thead>.
LEGACY_TESTID = 'data-testid="finished-tasks-table"'
MUX_TESTID    = 'data-testid="multiplexer-finished-tasks-table"'


def _headers_after( source, testid, whose ):
    """
    The <th> texts of the FIRST <thead> following `testid`.

    Requires:
        - source is the file's text
        - testid is the table's data-testid attribute, present exactly once

    Ensures:
        - returns the header cell texts as a list, in render order
        - raises AssertionError naming `whose` if the table, its <thead>, or any
          header cell is absent — an empty list must never read as agreement
    """
    assert source.count( testid ) == 1, (
        f"{whose}: expected exactly one {testid}, found {source.count( testid )} — "
        "this instrument compares ONE table per client and cannot choose between two"
    )

    start = source.find( testid )
    thead = re.search( r"<thead>(.*?)</thead>", source[ start: ], re.DOTALL )
    assert thead is not None, f"{whose}: no <thead> follows {testid}"

    cells = re.findall( r"<th[^>]*>(.*?)</th>", thead.group( 1 ), re.DOTALL )
    # A loop over zero cells passes every per-item assertion inside it, so the
    # emptiness is refused here rather than downstream.
    assert cells, f"{whose}: the <thead> after {testid} carries no <th> cells"
    return [ c.strip() for c in cells ]


@pytest.fixture( scope="module" )
def legacy_headers():
    return _headers_after( LEGACY.read_text( encoding="utf-8" ), LEGACY_TESTID, "legacy" )


@pytest.fixture( scope="module" )
def mux_headers():
    return _headers_after( MUX.read_text( encoding="utf-8" ), MUX_TESTID, "multiplexer" )


def test_the_two_clients_render_the_same_column_headers_in_the_same_order( legacy_headers, mux_headers ):
    """
    🔴 THE POINT OF THE FILE. Not a count, not a subset — the LIST and its ORDER.

    A count passes when four wrong words are present. A subset check passes when
    one client grows a fifth column. Equality is the only shape that fails on the
    divergence this row was opened for.
    """
    assert legacy_headers == mux_headers, (
        f"the two clients disagree on column headers.\n"
        f"  legacy      {legacy_headers}\n"
        f"  multiplexer {mux_headers}\n"
        "A header ruled on one client must reach the other. This is the What/Title "
        "divergence class (row 86a5c818): the TS tier stays green through it, because "
        "each client's tests only ever ask whether that client agrees with itself."
    )


def test_the_headers_carry_the_word_Rick_ruled( legacy_headers, mux_headers ):
    """
    The equality test above is satisfied by BOTH clients being wrong together.

    So this pins the one header whose text the operator actually ruled — `Title`,
    2026-09-07 ~20:10, row 86a5c818 — on each client independently. Without it, a
    revert of `Title` back to `What` on BOTH clients passes the parity test with
    nothing to say.
    """
    assert "Title" in legacy_headers, f"legacy lost Rick's ruled header: {legacy_headers}"
    assert "Title" in mux_headers, f"multiplexer lost Rick's ruled header: {mux_headers}"
    assert "What" not in legacy_headers, f"legacy still reads the superseded word: {legacy_headers}"
    assert "What" not in mux_headers, f"multiplexer still reads the superseded word: {mux_headers}"


def test_the_headers_are_static_literals_or_this_instrument_is_wrong():
    """
    🔴 THE SELF-INVALIDATING GUARD, and the reason this file may live in the unit
    tier at all.

    Reading SOURCE is sufficient only while both clients write their headers out
    as literal text. The moment either one computes them — a map, a loop, a
    config lookup — a source read stops being evidence about what renders, and
    this whole file becomes a comfortable false green.

    So the assumption is asserted rather than assumed. If this goes red, do NOT
    patch it: move the check to the parity oracle, which measures rendered output
    and is the correct instrument for a computed header.
    """
    for path, testid, whose in ( ( LEGACY, LEGACY_TESTID, "legacy" ),
                                 ( MUX, MUX_TESTID, "multiplexer" ) ):
        source = path.read_text( encoding="utf-8" )
        start  = source.find( testid )
        thead  = re.search( r"<thead>(.*?)</thead>", source[ start: ], re.DOTALL )
        assert thead is not None, f"{whose}: no <thead> follows {testid}"

        body = thead.group( 1 )
        assert "${" not in body, (
            f"{whose}: the header row now interpolates — a source read no longer "
            "proves what renders. Move this to the parity oracle rather than patching here."
        )
        for token in ( "map(", "for(", "for (", ".join(" ):
            assert token not in body, (
                f"{whose}: the header row is built with `{token}` — it is computed, "
                "not literal. Move this to the parity oracle rather than patching here."
            )
