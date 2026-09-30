"""
Guard for row 86a5c818 — Rick's P0, 2026-09-07 ~20:10 by voice.

Rick looked at the live pane and said: "it doesn't know what to display in the WHAT
column. To me it's pretty obvious that the WHAT column should actually read TITLE,
because that's the most interesting or relevant piece. Also I want an icon for type —
done, dropped or won't fix — on a per-row basis."

🔴 THE BLANK COLUMN WAS NOT A CODE DEFECT AND THIS FILE DOES NOT GUARD IT.

Both sides were already correct. The running :7999 process had started 2026-09-07
17:43:49 EDT and the merge that put `title` on the wire (86920d8f) landed 19:36:37 EDT
— the server predated its own serializer by 1h53m, auto-reload is OFF, and a saved file
is not a served file. A bounce fixed it with no edit. Two symptoms shared that one
cause: `title` absent from the JSON, AND `to_status` not filtering, because c30e7c3b
added both in one commit and FastAPI silently ignores a query param a process has never
heard of. Recorded here so nobody reads this file as the fix for the blank column.

What IS guarded here is the two things that needed code: the header word, and the glyph.

⚠️ SCOPE — LEGACY CLIENT ONLY (María's ruling R4: legacy ships first, the multiplexer
port is row 470b7509). Nothing here may open a multiplexer file.
"""
import re
from pathlib import Path

import pytest

import cosa.utils.util as cu


HTML = Path( cu.get_project_root() ) / "src/lupin_app/static/html/notifications.html"
JS   = Path( cu.get_project_root() ) / "src/lupin_app/static/js/notifications.js"
CSS  = Path( cu.get_project_root() ) / "src/lupin_app/static/css/task-list.css"

# The store's own three terminal words. Named once so a test that finds none of them
# fails as a POPULATION error rather than passing vacuously over an empty loop.
FINISHED_STATUSES = ( "done", "dropped", "wont_fix" )


@pytest.fixture( scope="module" )
def html(): return HTML.read_text( encoding="utf-8" )


@pytest.fixture( scope="module" )
def js(): return JS.read_text( encoding="utf-8" )


@pytest.fixture( scope="module" )
def css(): return CSS.read_text( encoding="utf-8" )


@pytest.fixture( scope="module" )
def table_fn( js ):
    """The body of _finishedTasksTable, isolated.

    Scoping to ONE function matters: `<th>` and the word "Title" both occur elsewhere
    in a 24k-line file, so a whole-file search would pass on somebody else's markup and
    tell us nothing about this pane.
    """
    start = js.find( "    _finishedTasksTable( rows ) {" )
    assert start != -1, "_finishedTasksTable is absent — renamed, or wrong file"
    end = js.find( "\n    _finishedTasksRelative(", start )
    assert end != -1, "could not find the end of _finishedTasksTable"
    return js[ start:end ]


def test_the_header_reads_title_and_no_longer_reads_what( table_fn ):
    """Rick's ruling, overriding design §6.1's "WHEN / WHAT / WHO / WHY"."""
    header = re.search( r"<thead>.*?</thead>", table_fn, re.S )
    assert header, "the table has no <thead> — the header row is gone entirely"
    header = header.group( 0 )

    assert "<th>Title</th>" in header, f"header does not say Title:\n{header}"
    assert "<th>What</th>" not in header, (
        f"header still says What — Rick's rename did not land:\n{header}"
    )
    # The other three are untouched by this row. Asserting them makes this a check on
    # ONE renamed column rather than on a header that merely contains the word Title.
    for kept in ( "<th>When</th>", "<th>Who</th>", "<th>Why</th>" ):
        assert kept in header, f"{kept} went missing — this row renamed one column, not four"


def test_the_css_class_deliberately_still_says_what( table_fn, css ):
    """The class and the header DISAGREE ON PURPOSE, and that is the whole risk.

    Renaming `finished-what` would churn the stylesheet and every selector in the guards
    to buy nothing a reader can see. This test exists so the next person who notices the
    mismatch finds a decision here instead of "fixing" it — and so that if they DO rename
    it, they are made to rename it in both places at once.
    """
    assert 'class="finished-what"' in table_fn, "the title cell lost its finished-what class"
    assert ".finished-what" in css, "the stylesheet and the markup disagree about finished-what"


def test_every_finished_status_has_a_glyph_and_the_three_differ( js ):
    """Three statuses, three DIFFERENT glyphs — Rick asked to tell them apart."""
    block = re.search( r"static get FINISHED_STATUS_GLYPHS\(\).*?return \{(.*?)\};", js, re.S )
    assert block, "FINISHED_STATUS_GLYPHS is absent"
    body = block.group( 1 )

    glyphs = { }
    for status in FINISHED_STATUSES:
        found = re.search( status + r"\s*:\s*\"([^\"]+)\"", body )
        assert found, f"no glyph declared for {status}"
        glyphs[ status ] = found.group( 1 )

    # POSITIVE CONTROL: the loop above must actually have run over three statuses. An
    # empty FINISHED_STATUSES would satisfy every assertion in it without measuring one.
    assert len( glyphs ) == 3, f"expected 3 glyphs, mapped {len( glyphs )}: {glyphs}"
    assert len( set( glyphs.values() ) ) == 3, (
        f"two statuses share a glyph, so the row cannot tell them apart: {glyphs}"
    )


def test_the_row_glyph_and_the_filter_pill_show_the_same_character( js, html ):
    """A pill and a row disagreeing about what "dropped" looks like is drift nobody
    reports and everybody misreads. The pill markup is the source; the map answers to it.
    """
    block = re.search( r"static get FINISHED_STATUS_GLYPHS\(\).*?return \{(.*?)\};", js, re.S )
    assert block, "FINISHED_STATUS_GLYPHS is absent"
    body = block.group( 1 )

    compared = 0
    for status in FINISHED_STATUSES:
        pill = re.search(
            r'data-status="' + status + r'".*?</button>', html, re.S
        )
        assert pill, f"no filter pill found for {status} — wrong file, or the pills moved"

        declared = re.search( status + r'\s*:\s*"([^"]+)"', body )
        assert declared, f"no glyph declared for {status}"
        glyph = declared.group( 1 )

        assert glyph in pill.group( 0 ), (
            f"the {status} row glyph {glyph!r} does not appear in its own pill — "
            f"pill and row have drifted apart"
        )
        compared += 1

    # POSITIVE CONTROL: without this, a FINISHED_STATUSES that had gone empty would make
    # this test pass having compared nothing at all.
    assert compared == 3, f"compared {compared} pills, expected 3"


def test_the_glyph_rides_inside_the_when_cell_and_is_not_a_fifth_column( table_fn ):
    """Design §6.4, and it is load-bearing: the grid must not reshuffle across the seven
    filter combinations, so the glyph is a PREFIX in WHEN rather than a column of its own.
    """
    row = re.search( r"<tr class=\"finished-task-row\".*?</tr>", table_fn, re.S )
    assert row, "the row template is gone"
    row = row.group( 0 )

    assert row.count( "<td" ) == 4, (
        f"the row has {row.count( '<td' )} cells, not 4 — a fifth column reshuffles the "
        f"grid across filter combinations, which design §6.4 rejects:\n{row}"
    )

    when = re.search( r"<td class=\"finished-when\".*?</td>", row, re.S )
    assert when, "the WHEN cell is gone"
    assert "finished-status-glyph" in when.group( 0 ), (
        f"the glyph is not inside the WHEN cell:\n{when.group( 0 )}"
    )


def test_the_glyph_is_looked_up_on_the_raw_status_not_the_escaped_one( table_fn ):
    """The map is keyed on the store's own word. Looking it up with an HTML-escaped key
    would miss on any status containing an escapable character and silently render no
    glyph — a blank where a reader expects a symbol, with nothing saying why.
    """
    assert "FINISHED_STATUS_GLYPHS[ rawStatus ]" in table_fn, (
        "the glyph lookup does not use the raw status"
    )
    # And the ESCAPED value is still what reaches the markup, or this fix would have
    # opened an injection hole while closing a lookup bug.
    assert 'data-status="${ status }"' in table_fn, "the row no longer escapes data-status"


def test_an_unknown_status_renders_no_glyph_rather_than_a_borrowed_one( table_fn ):
    """Unreachable today — the pane only fetches the three terminal statuses. If it ever
    fires, a blank prefix is honest and a borrowed glyph is a confident wrong answer.
    """
    assert re.search( r"FINISHED_STATUS_GLYPHS\[ rawStatus \] \|\| \"\"", table_fn ), (
        "no empty-string fallback — an unknown status would render `undefined`"
    )
