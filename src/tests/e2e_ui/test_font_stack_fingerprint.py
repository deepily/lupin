"""
The fonts the BROWSER selects for Lupin's CSS stacks must not move under the baselines.

WHY THIS EXISTS BESIDE `test_render_env_fingerprint.py` (row f0e00f01, 2026-09-15).
That guard asserts `fc-match` resolves three generics and three named fonts to DejaVu.
Measured against what Chromium actually does, both halves of its premise are wrong for
real Lupin pages:

  - It asserts `Helvetica Neue` -> DejaVu Sans. The browser never stops there. It walks
    the stack to `Helvetica` and `Arial`, which fontconfig aliases to Liberation Sans,
    so `"Helvetica Neue", Helvetica, Arial, sans-serif` renders in LIBERATION SANS while
    the guard certifies DejaVu. Measured: that stack is 402.91px, and Liberation Sans is
    402.91px, against DejaVu Sans at 455.23px.
  - It checks three named fonts and never checks `Oxygen`, `Ubuntu` or `Cantarell`, which
    are what actually decide the `lupin-base.css` stack. `Ubuntu` is a REAL Linux font:
    3 families on the dev host, ZERO in `lupin-rest-test`. So that one stack resolves to
    Ubuntu on the host and to something else in the container.

`fc-match` cannot answer this question even in principle: it always returns a best match
and so can never report "absent", and absence is exactly the signal that decides which
entry in a stack wins.

WHAT THIS GUARD DOES INSTEAD. It derives every stack the tree declares — from the tree,
not from a list someone maintains — and pins the width the browser gives each one. A
width moves if and only if a different font was selected, whatever the cause: a package
added or removed, an alias retargeted, a family renamed, a stylesheet edited. That is the
predicate the old name-enumeration was approximating.

THE FINGERPRINT IS RECORDED PER VENUE, and that is not a tolerance — it is the point.
The `lupin-base.css` stack is the standard SYSTEM-FONT stack, whose whole job is to render
in the platform's own UI font. It is SUPPOSED to resolve differently on a machine that has
Ubuntu installed than on one that does not. An earlier cut of this guard asserted that host
and container agree; Mr. Radio ruled that out on 2026-09-15, and he was right — the only way
to satisfy such an assertion is to trim the system stack, which degrades the product so a
test can pass, and it would not have touched the defect that started this anyway.

So the predicate is per venue: the fonts THIS venue selects must not have moved since THIS
venue was fingerprinted. Measured 2026-09-15: 21 of 22 stacks read identically in both, and
exactly one differs — the system stack, 402.91 in `lupin-rest-test` against 409.39 on the
host, because Ubuntu is installed on one and not the other. Both numbers are recorded; both
are correct; a change to either is a finding.

That is strictly MORE coverage than a cross-venue equality would give. It watches drift
inside the container, which is the class that actually moved dev-tools out from under its
own in-container baseline, AND drift on the host, which a container-only check would not
see at all.

Requires:
    - a Playwright browser (about:blank only — no server, no network)
    - `font-stack-fingerprint.json` beside this file
Ensures:
    - a stack added to the CSS without being fingerprinted fails, rather than going
      silently unguarded
    - a stack whose selected font changes fails, and the message names the font it
      changed to and the font it was
"""

import os

from font_stack_fingerprint import (
    current_venue,
    declared_font_stacks,
    identify_families,
    installed_families,
    load_fingerprint,
    measure_stacks,
)

import pytest


_THIS_DIR        = os.path.dirname( os.path.abspath( __file__ ) )
FINGERPRINT_PATH = os.path.join( _THIS_DIR, "font-stack-fingerprint.json" )


def _project_root():
    """Ensures: the repo root this run is measuring, from LUPIN_ROOT or two levels up."""
    return os.environ.get( "LUPIN_ROOT" ) or os.path.abspath( os.path.join( _THIS_DIR, "..", "..", ".." ) )


@pytest.fixture( scope="module" )
def committed():
    """
    Ensures:
        - returns the fingerprint block for THIS venue
        - fails, naming the venue, when no block exists for it — a venue nobody has
          fingerprinted is unguarded, and saying so is the whole point of the guard
    """
    data = load_fingerprint( FINGERPRINT_PATH )
    if data is None:                                       # pragma: no cover - only when the file is deleted
        pytest.fail( f"font-stack fingerprint missing at {FINGERPRINT_PATH} — regenerate it" )
    venue = current_venue()
    if venue not in data:
        pytest.fail(
            f"no font-stack fingerprint recorded for venue '{venue}' (have: {sorted( data )}). "
            f"This venue's font selection is UNGUARDED. Capture it here and commit the block."
        )
    return data[ venue ]


def test_every_declared_stack_is_fingerprinted( committed ):
    """
    A stack the CSS declares but the fingerprint does not cover is UNGUARDED.

    This is the enumeration-drift half: without it, adding a stylesheet with a new family
    silently widens the surface the other test is not watching.
    """
    declared = set( declared_font_stacks( _project_root() ) )
    assert declared, "no font-family declarations found — the sweep is broken, not the CSS"

    missing = sorted( declared - set( committed ) )
    stale   = sorted( set( committed ) - declared )
    assert not missing and not stale, (
        f"the font-stack fingerprint is out of date.\n"
        f"  declared in CSS but NOT fingerprinted ({len( missing )}): {missing}\n"
        f"  fingerprinted but no longer declared ({len( stale )}): {stale}\n"
        f"Regenerate the '{current_venue()}' block of {os.path.basename( FINGERPRINT_PATH )} in THIS "
        f"venue, and the other venue's block in that one."
    )


def test_each_stack_resolves_to_its_fingerprinted_font( page, committed ):
    """
    Every declared stack must resolve to the SAME font the fingerprint was taken with.

    A width move means a different font was selected. The message names both fonts, so
    the reader gets an actionable answer rather than a number that moved.
    """
    page.goto( "about:blank" )
    stacks   = sorted( committed )
    measured = measure_stacks( page, stacks )

    drifted = [ s for s in stacks if abs( measured[ s ] - committed[ s ] ) > 0.01 ]
    if not drifted:
        return

    families = installed_families()
    lines    = []
    for stack in drifted:
        was = identify_families( page, committed[ stack ], families ) or ( "not installed here", )
        now = identify_families( page, measured[ stack ], families )  or ( "unidentified", )
        lines.append(
            f"  {stack}\n"
            f"      fingerprint {committed[ stack ]}px  == {', '.join( was )}\n"
            f"      this run    {measured[ stack ]}px  == {', '.join( now )}"
        )

    pytest.fail(
        f"{len( drifted )} of {len( stacks )} CSS font stacks resolve to a DIFFERENT font than the "
        f"'{current_venue()}' fingerprint, so this venue's fonts moved since it was recorded:\n"
        + "\n".join( lines )
        + f"\n\nThis compares '{current_venue()}' against its OWN recorded block, so a host/container "
          "difference is NOT what reddened it — those are recorded separately and are expected to differ "
          "on the system-font stack. Something changed the fonts available in THIS venue: a package "
          "added or removed, a fontconfig alias retargeted, or a base-image bump. Find that change. Do "
          "NOT rebaseline around it, and do NOT trim the CSS stack to make the number agree."
    )
