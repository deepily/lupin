"""
The board notice sits ON the toolbar row, not under it (Rick via Mr. Radio, 2026-09-17).

WHAT BROKE. a180b230 moved the truncation banner, the holding-area note and the
verbatim server warning out of `#task-list-container` — which every render
overwrote — into `#task-list-notices`, a sibling inside `div.task-lookup`. The
move was right and the placement was not: `.task-list-notices` carried
`flex-basis: 100%`, and a 100% basis inside a `flex-wrap: wrap` parent forces a
line break unconditionally. So the notice shared the toolbar and never the line,
at EVERY width. It read like a phone-width wrap and was not one.

WHY THIS TEST EXISTS RATHER THAN A CSS REVIEW. Nothing in the unit tier can see
this. `src/tests/unit/notifications_js/` runs under happy-dom, which parses CSS
but does not lay it out — every box there is 0x0, so "is the notice on the same
row as the input" has no answer. Only a real engine can be asked. That is the
whole reason the defect survived a green suite.

🔴 HOW THIS TEST NEARLY LIED, recorded because the next person will reach for the
same wrong predicate. The first cut asked `notice.top == input.top`. That is NOT
"same row": `.task-lookup` sets `align-items: center`, so items of different
heights sit on one row with DIFFERENT tops, and the check scored the FIXED layout
as still broken. A same-row predicate has to be that the two boxes' vertical
ranges OVERLAP. The bug flattered the defect — it would have hidden a working
fix — but the same predicate reports a false PASS the moment two stacked
elements happen to share a top coordinate, which is exactly what a zero-height
element does. Overlap is the predicate; top-equality is a coincidence detector.

VENUE. This file lives in e2e_ui because it needs a real layout engine, but it
needs NO SERVER and no login: it reads the shipped stylesheet off disk and lays
out the real toolbar markup with `set_content`. It runs in about five seconds.
It is listed in `partition/half-b.txt` like every other file here — see
`test_e2e_halves_partition.py`, which fails on a file in neither half or both.
"""

import pathlib

import pytest

import cosa.utils.util as cu

# The two viewports the ruling is stated in terms of.
DESKTOP_WIDTH = 1280
PHONE_WIDTH   = 390

# A short banner and a long one, because the long one is what used to grow the
# toolbar to 112px at phone width.
SHORT_BANNER = "✂️ Board truncated: showing 139 of 1171."
LONG_BANNER  = (
    "✂️ Board truncated: showing 139 of 1171. ⚠️ Server: limit clamped to 500 · "
    "include_terminal ignored on this endpoint · offset beyond total"
)

# Lifted verbatim from notifications.html's div.task-lookup: the id search, its
# two buttons, ＋ New, the lookup result and the notices mount. If that markup
# changes shape, this harness should be updated with it.
TOOLBAR = """
<div class="task-lookup">
  <input type="text" id="task-lookup-input" class="task-lookup-input" placeholder="Find ticket by id…">
  <button type="button" id="task-lookup-go" class="task-lookup-go">🔎</button>
  <button type="button" id="task-lookup-clear" class="task-lookup-clear">✕</button>
  <button type="button" id="task-new-ticket" class="task-new-ticket">＋ New</button>
  <div id="task-lookup-result" class="task-lookup-result"></div>
  <div id="task-list-notices" class="task-list-notices" role="status">
    <p class="task-list-message task-list-truncated">{banner}</p>
  </div>
</div>
"""

_RECTS = """() => {
  const box = id => {
    const b = document.getElementById( id ).getBoundingClientRect();
    return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, width: b.width };
  };
  return {
    input   : box( "task-lookup-input" ),
    newBtn  : box( "task-new-ticket" ),
    notices : box( "task-list-notices" ),
  };
}"""


def _stylesheet() -> str:
    """
    The SHIPPED stylesheet, read from disk.

    Requires:
        - src/lupin_app/static/css/task-list.css exists under the project root

    Ensures:
        - returns its full text, so the assertions below run against the rule the
          browser would actually serve rather than a copy pasted into this file
    """
    path = pathlib.Path( cu.get_project_root() ) / "src/lupin_app/static/css/task-list.css"
    return path.read_text( encoding="utf-8" )


def _measure( page, width, banner ):
    """
    Lay the real toolbar out at `width` and return the three boxes.

    Requires:
        - page is an open Playwright page
        - width is a positive viewport width in CSS pixels

    Ensures:
        - the page contains only the toolbar markup and the shipped stylesheet
        - returns a dict with 'input', 'newBtn' and 'notices' bounding boxes
    """
    page.set_viewport_size( { "width": width, "height": 800 } )
    page.set_content(
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + _stylesheet()
        + "</style></head><body>"
        + TOOLBAR.format( banner=banner )
        + "</body></html>"
    )
    return page.evaluate( _RECTS )


def _shares_row( a, b ):
    """
    True when two boxes sit on the SAME visual row.

    Requires:
        - a and b are bounding boxes carrying 'top' and 'bottom'

    Ensures:
        - returns True iff their vertical ranges overlap by more than zero
        - does NOT compare tops for equality: `.task-lookup` centers its items,
          so one row routinely holds different tops (see this module's docstring)
    """
    return min( a[ "bottom" ], b[ "bottom" ] ) - max( a[ "top" ], b[ "top" ] ) > 0


# `page` is pytest-playwright's own fixture — no server, no cookies, no login is needed,
# since _measure() sets its content directly. This file used to launch its OWN
# `sync_playwright()` here. That passes when the file runs alone and errors at setup
# ("Sync API inside the asyncio loop") in the suite, where pytest-playwright already
# runs a loop for every other test: e2e_b 20260918-231051, 4 errors.
# test_multiplexer_fleet_status.py records the same trap on `_open_with_fleet`.


@pytest.mark.parametrize( "banner", [ SHORT_BANNER, LONG_BANNER ], ids=[ "short", "long" ] )
def test_notice_shares_the_toolbar_row_on_desktop( page, banner ):
    """At desktop width the notice sits beside the id search and ＋ New, whatever its length."""
    m = _measure( page, DESKTOP_WIDTH, banner )

    assert _shares_row( m[ "notices" ], m[ "input" ] ), (
        f"the board notice is not on the id-search row at {DESKTOP_WIDTH}px — "
        f"notice top={m['notices']['top']:.0f} bottom={m['notices']['bottom']:.0f}, "
        f"input top={m['input']['top']:.0f} bottom={m['input']['bottom']:.0f}. "
        "The usual cause is a flex-basis or width on .task-list-notices that fills "
        "the line: in a flex-wrap:wrap parent that forces a break unconditionally."
    )
    assert _shares_row( m[ "notices" ], m[ "newBtn" ] ), (
        "the notice shares a row with the input but not with ＋ New, which means the "
        "toolbar itself wrapped — check whether a control grew."
    )


def test_a_long_notice_is_clipped_rather_than_growing_the_toolbar( page ):
    """
    The long banner must not make the notice taller than the short one.

    This is what `text-overflow: ellipsis` buys and it is the half of the ruling
    that is easy to regress: drop `white-space: nowrap` and everything above still
    passes while the toolbar silently grows.
    """
    short = _measure( page, DESKTOP_WIDTH, SHORT_BANNER )[ "notices" ]
    long_ = _measure( page, DESKTOP_WIDTH, LONG_BANNER )[ "notices" ]

    short_h = short[ "bottom" ] - short[ "top" ]
    long_h  = long_[ "bottom" ] - long_[ "top" ]
    assert long_h == pytest.approx( short_h, abs=1.0 ), (
        f"a long notice grew the row from {short_h:.0f}px to {long_h:.0f}px — the banner is "
        "wrapping instead of being clipped. Check white-space:nowrap + text-overflow:ellipsis "
        "on .task-list-notices .task-list-message."
    )


def test_phone_width_puts_the_notice_on_its_own_line_and_that_is_the_ruling( page ):
    """
    🔴 THIS TEST PINS AN ACCEPTED LIMITATION, NOT A SUCCESS.

    Mr. Radio 🦉 ruled option 1 of three on 2026-09-17: share the row wherever there
    is room, and take one honest wrap on a phone. At 390px the controls already own
    the row — the id box alone is 219px at its max-width:26ch, and ＋ New's right
    edge lands at x=367 of 390. The alternatives were shrinking the id box on the
    device where typing is hardest, or dropping the ✕ that Rick added as "the real
    clear" (row 700f0e1d). Both were refused.

    If someone later makes the notice share the row at phone width TOO, this test
    fails — and that failure is a prompt to re-read the ruling, not a defect. Change
    the ruling first, then this test.
    """
    m = _measure( page, PHONE_WIDTH, SHORT_BANNER )

    assert not _shares_row( m[ "notices" ], m[ "input" ] ), (
        "the notice now shares the toolbar row at phone width. That may well be an "
        "improvement, but it contradicts the 2026-09-17 ruling this test records — "
        "get the ruling changed, then update this test with it."
    )
    assert m[ "newBtn" ][ "right" ] <= PHONE_WIDTH, (
        f"＋ New overflows the {PHONE_WIDTH}px viewport (right={m['newBtn']['right']:.0f}). "
        "The controls must still fit their own line even when the notice takes another."
    )
