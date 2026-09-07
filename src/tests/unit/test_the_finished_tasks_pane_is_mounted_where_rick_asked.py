"""
Guard for row 7c616656 — Rick's P0, broadcast e254ec7d, 2026-09-07.

🔴 WHY THIS TEST EXISTS AT ALL, AND WHY IT READS THE FILE RATHER THAN A MODULE.

Five rows had already been spent on this feature before a single pixel rendered —
a design, an API door, that door's proof, a plan, and very nearly a rebuild of an
implementation that already existed on an unmerged branch. Every one of them was
correct and green. The thing nobody had was a check that answers "is it ON THE
PAGE, in the right place, wired to something".

That is this repo's § IMPLEMENTED BUT NOT INSTALLED, and the pane is exactly the
shape it warns about: a component can be complete, correct, fully covered and
entirely absent from the running system.

⚠️ SCOPE — LEGACY CLIENT ONLY, and deliberately so. María's ruling R4: legacy
ships first, the multiplexer port is its own row (470b7509). Nothing here may
open a multiplexer file.
"""
import re
from pathlib import Path

import pytest

import cosa.utils.util as cu


HTML = Path( cu.get_project_root() ) / "src/lupin_app/static/html/notifications.html"
JS   = Path( cu.get_project_root() ) / "src/lupin_app/static/js/notifications.js"
CSS  = Path( cu.get_project_root() ) / "src/lupin_app/static/css/task-list.css"


@pytest.fixture( scope="module" )
def html(): return HTML.read_text( encoding="utf-8" )


@pytest.fixture( scope="module" )
def js(): return JS.read_text( encoding="utf-8" )


def test_the_pane_sits_between_fleet_status_and_the_task_list( html ):
    """Rick named the position, not just the feature: "just beneath the fleet
    status accordion and before the task list accordion".

    Vertical order here is raw DOM order — no JS reorders these sections — so
    document position IS the rendered position.
    """
    fleet    = html.find( 'id="section-fleet-status"' )
    finished = html.find( 'id="section-finished-tasks"' )
    tasklist = html.find( 'id="section-task-list"' )

    # POSITIVE CONTROL: all three must be present, or the ordering assertion
    # below would pass vacuously on -1 < -1 < -1 being False... but also would
    # not tell you WHICH one is missing.
    assert fleet    != -1, "section-fleet-status is absent — wrong file or renamed"
    assert finished != -1, "section-finished-tasks is absent — the pane is NOT mounted"
    assert tasklist != -1, "section-task-list is absent — wrong file or renamed"

    assert fleet < finished < tasklist, (
        f"wrong order: fleet={fleet} finished={finished} tasklist={tasklist}"
    )


def test_every_control_lives_in_the_content_not_the_header( html ):
    """🔴 THE HEADER CARRIES onclick=toggleSection(...), SO A SLIDER PLACED THERE
    COLLAPSES THE PANEL ON EVERY DRAG.

    Documented twice in this file already (:830-834 and :703-708) and called out
    by María before the build. Pinned rather than trusted, because it is a
    placement mistake that reads as a mysterious UI bug rather than as a layout
    error.
    """
    section = html[ html.index( 'id="section-finished-tasks"' ) : ]
    section = section[ : section.index( 'id="section-task-list"' ) ]

    header  = section[ section.index( '<div class="section-header"' ) : section.index( '<div class="section-content"' ) ]
    content = section[ section.index( '<div class="section-content"' ) : ]

    for control in [ 'id="finished-tasks-window"', 'class="finished-tasks-pills"' ]:
        assert control not in header,  f"{control} is in the HEADER — it will collapse the panel on interaction"
        assert control in content,     f"{control} is not in the section CONTENT"


def test_all_three_terminal_pills_are_present_and_only_done_starts_lit( html ):
    """DONE pre-lit is non-negotiable (design §1.2), and the other two must EXIST
    at zero rather than appear later.

    "Zero is a claim, not a default": a pill that renders only when its count is
    non-zero converts "nothing was refused today" into "this feature does not
    exist", and makes the control bar change width as the day goes on.
    """
    section = html[ html.index( 'id="section-finished-tasks"' ) : html.index( 'id="section-task-list"' ) ]

    pills = re.findall( r'data-status="(\w+)"\s+\n?\s*aria-pressed="(\w+)"', section )
    assert dict( pills ) == { "done": "true", "dropped": "false", "wont_fix": "false" }, (
        f"pill set/initial state wrong: {pills}"
    )


def test_the_window_slider_defaults_to_one_day_and_steps_by_one( html ):
    """Rick: "defaults to the last 24 hours and goes further back in time one day
    at a time, just like the holding area's window slider"."""
    section = html[ html.index( 'id="section-finished-tasks"' ) : html.index( 'id="section-task-list"' ) ]
    slider  = section[ section.index( 'id="finished-tasks-window"' ) : ]
    slider  = slider[ : slider.index( "/>" ) ]

    for attr in [ 'min="1"', 'max="14"', 'step="1"', 'value="1"' ]:
        assert attr in slider, f"slider is missing {attr}"


def test_the_pane_reads_the_event_stream_and_not_the_task_door( js ):
    """🔴 THE DOOR IS A RULING (Rick's R5 via María, 2026-09-07 19:21), NOT A
    STYLE CHOICE, so it is pinned.

    /api/tasks cannot answer "which rows became terminal in the last 24 hours":
    there is no terminal-timestamp column anywhere in the schema, so its
    updated_ts moves on every write; and it orders by created_ts, so a row
    finished ten minutes ago can sort below 500 rows created today.

    A future edit that "simplifies" this back onto /api/tasks would produce a
    plausible pane showing the wrong rows in the wrong order — the failure this
    assertion exists to make loud.
    """
    body = js[ js.index( "async fetchFinishedTasks(" ) : js.index( "renderFinishedTasks(" ) ]
    assert "/api/tasks/events?" in body, "the pane is not reading the event stream"
    assert "to_status=" in body
    assert "/api/tasks?" not in body, "the pane reached for the task door — see R5"


def test_the_badge_never_shows_a_zero_it_has_not_measured( js ):
    """An unmeasured pane shows an em dash, never 0.

    0 is a claim that something was counted. Before the first poll returns,
    nothing has been — and "0 finished today" is a materially different statement
    from "not loaded yet", especially to the person who asked for this pane
    because work was going unfinished.
    """
    body = js[ js.index( "renderFinishedTasks( eventsByStatus, error )" ) : ]
    body = body[ : body.index( "_finishedTasksTable( rows )" ) ]
    assert 'measured ? String( visible.length ) : "—"' in body, (
        "the header badge does not fall back to an em dash before first measurement"
    )


def test_the_pane_declares_its_persistence_polarity( html ):
    """Design §9: this file carries THREE conventions and two of them are inverted
    relative to each other — collapsedOwners is an ARRAY of COLLAPSED keys,
    groupState is a MAP of key -> isEXPANDED. Copying one from the other inverts a
    user's saved state and fails INVISIBLY.

    The section axis has its own settled convention (boolean, isOPEN), and this
    pane must be registered on it rather than inventing a fourth.
    """
    block = html[ html.index( "LUPIN_ACCORDION_PERSIST_KEYS" ) : ]
    block = block[ : block.index( "};" ) ]
    assert "'finished-tasks-section'" in block, "the pane is not registered on the section-axis persistence"


def test_the_stylesheet_that_carries_the_pane_is_actually_linked( html ):
    """🔴 § IMPLEMENTED BUT NOT INSTALLED, in its CSS form — and this repo has
    already eaten it once.

    Gap G2 of the accordion build spec was exactly this: `epic-board.css` held a
    correct collapse rule and NOTHING LOADED THE FILE, so a correct renderer
    produced a broken page for a day. The pane's styles live in task-list.css
    precisely because notifications.html already links it.
    """
    assert "/static/css/task-list.css" in html, "task-list.css is not linked — the pane will render unstyled"
    assert ".finished-pill" in CSS.read_text( encoding="utf-8" ), "the pane's styles are not in the linked sheet"
