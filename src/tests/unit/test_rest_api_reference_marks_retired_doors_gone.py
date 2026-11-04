"""
`rest-api-reference.md` must not present a retired queue door as a live endpoint.

WHY THIS FILE EXISTS. `test_retired_queue_doors_410.py` checks the doors thoroughly — it
mounts the real routers, posts to each retired path, and reads the refusal body. It never
opens `rest-api-reference.md`. So on 2026-09-28 the runtime was correct and the document
was ten rows stale: §11 still read
`| POST | /api/deep-research/submit | JWT | Submit research job to queue |` for a door
that had answered 410 since 2026-08-21, and the Job ID Prefixes table still named four
410 doors as the way to submit.

That is the worse half of a half-checked document. A wrong INSTRUCTION gets caught the
first time someone follows it — you post, you get a 410, the refusal names the new door.
A wrong REASSURANCE disarms the reader who would have caught it: a row that says `JWT`
and `Submit research job to queue` tells them the door is fine, so they go looking for
their bug somewhere else.

IT ASKS THE GATE, IT DOES NOT RESTATE IT. The door list here is `RETIRED_DOORS` itself,
imported. Nothing below enumerates a path, so the commit that retires door 18 turns this
suite red on the document rather than leaving the document to be noticed later. Two
pieces of code deciding one rule agree until they do not.

WHAT IT DOES NOT CHECK, said so the gap is visible. It reads markdown TABLE ROWS, and
only those that declare an endpoint or name a submit door. Prose is not checked: the
§🪦 header block's own "Retired door | Use instead" table is a list OF retirements, and a
paragraph may name a door for any reason. A door named only in prose is therefore
invisible here.
"""

import os
import re

import pytest

import cosa.utils.util as cu
from cosa.rest.routers._retired_doors import RETIRED_DOORS


DOC_RELATIVE_PATH = "src/docs/rest-api-reference.md"

# A row DECLARES AN ENDPOINT when its first cell is an HTTP method. That is the predicate,
# not a list of section numbers: every endpoint table in the document is shaped
# `| METHOD | \`path\` | … |`, and a table that is not shaped that way is not claiming a
# route is callable.
_ENDPOINT_ROW = re.compile( r"^\|\s*(?:POST|GET|PUT|DELETE|PATCH|WebSocket)\s*\|" )

# The Job ID Prefixes table's rows are `| \`xx-\` | Job Type | Submit Endpoint |` — the
# third cell answers "where do I submit this?", so a retired door there is a wrong answer.
_PREFIX_ROW = re.compile( r"^\|\s*`[a-z]+-`\s*\|" )

# What counts as saying the door is gone. Any ONE of these in the row is enough — the
# document uses all three spellings (`🪦 **GONE (410)**`, `❌ Retired 2026-05-05`,
# `410 Gone`) and this guard is about whether the reader is warned, not about which
# words did the warning.
_GONE_MARKERS = ( "410", "GONE", "Gone", "Retired", "retired" )


def _doc_lines():
    """
    Read the API reference from the project root: the index page and every part in its folder.

    Requires:
        - LUPIN_ROOT resolves to a checkout holding DOC_RELATIVE_PATH
        - the parts sit in the folder named after the page

    Ensures:
        - returns the index's lines, then each part's lines in file-name order, newline-stripped

    Raises:
        - FileNotFoundError if the document is missing, which is itself the finding
        - AssertionError if the folder holds no parts
    """
    root   = cu.get_project_root()
    lines  = []
    paths  = [ os.path.join( root, DOC_RELATIVE_PATH ) ]
    folder = os.path.join( root, DOC_RELATIVE_PATH[ : -len( ".md" ) ] )
    parts  = [ os.path.join( folder, name ) for name in sorted( os.listdir( folder ) ) if name.endswith( ".md" ) ] if os.path.isdir( folder ) else []
    assert len( parts ) > 0, f"no parts found in {folder}: the page is an index and the reference is in its parts"
    paths += parts
    for path in paths:
        with open( path ) as handle:
            lines += handle.read().splitlines()
    return lines


def _names_door( text, door ):
    """
    Whether a cell names one specific retired door and not merely a prefix of it.

    Requires:
        - door is a RETIRED_DOORS key

    Ensures:
        - True only when `door` appears delimited, so `/api/claude-code/submit` does not
          match inside `/api/claude-code/queue/submit`

    THE DELIMITER IS WHY THIS IS NOT AN `in` TEST. Two retired doors are a prefix pair:
    `/api/claude-code/submit` is a substring of nothing, but `/api/push` IS a substring of
    `/api/push-agentic`, and both are retired. A bare `in` would report the wrong door in
    the failure message and would call a correctly-marked `/api/push-agentic` row a
    `/api/push` violation.
    """
    for match in re.finditer( re.escape( door ), text ):
        after = text[ match.end() : match.end() + 1 ]
        if after in ( "", "`", " ", ")", ".", ",", "|" ): return True
    return False


def _rows_naming( door, matcher ):
    """
    Every row of the document that `matcher` accepts and that names `door`.

    Requires:
        - door is a RETIRED_DOORS key
        - matcher is a compiled pattern matched against the whole row

    Ensures:
        - returns a list of ( line_number, row ) pairs, 1-indexed
    """
    return [ ( number, row ) for number, row in enumerate( _doc_lines(), start=1 )
             if matcher.match( row ) and _names_door( row, door ) ]


# ── the corpus, asserted before anything loops over it ────────────────────────


def test_the_document_is_there_and_has_endpoint_tables():
    """
    State the denominator. A loop over nothing passes every assertion inside it, so the
    two guards below are worth nothing until this says how much they are reading.
    """
    lines    = _doc_lines()
    endpoint = [ row for row in lines if _ENDPOINT_ROW.match( row ) ]
    prefix   = [ row for row in lines if _PREFIX_ROW.match( row ) ]
    assert len( lines )    > 400, f"{DOC_RELATIVE_PATH} is {len( lines )} lines — too short to be the reference"
    assert len( endpoint ) > 100, f"only {len( endpoint )} endpoint rows found — the predicate has stopped matching"
    assert len( prefix )   >= 8,  f"only {len( prefix )} job-prefix rows found — the predicate has stopped matching"


def test_the_door_list_under_test_is_not_empty():
    """RETIRED_DOORS is the corpus for every parametrised test below."""
    assert len( RETIRED_DOORS ) > 0


# ── the two guards ────────────────────────────────────────────────────────────


@pytest.mark.parametrize( "door", sorted( RETIRED_DOORS ), ids=sorted( RETIRED_DOORS ) )
def test_no_endpoint_row_presents_a_retired_door_as_live( door ):
    """
    Every endpoint-table row naming a retired door says it is gone.

    Requires:
        - door is a RETIRED_DOORS key

    Ensures:
        - each `| METHOD | door | … |` row carries a gone-marker

    A door with no endpoint row at all passes — that is an omission, a different finding,
    and this guard would have to know the document's intended shape to judge it.
    """
    for number, row in _rows_naming( door, _ENDPOINT_ROW ):
        assert any( marker in row for marker in _GONE_MARKERS ), (
            f"{DOC_RELATIVE_PATH}:{number} presents {door} as a live endpoint, but it "
            f"answers 410 and retires into {RETIRED_DOORS[ door ]}:\n  {row}"
        )


@pytest.mark.parametrize( "door", sorted( RETIRED_DOORS ), ids=sorted( RETIRED_DOORS ) )
def test_no_job_prefix_row_sends_a_caller_to_a_retired_door( door ):
    """
    The Job ID Prefixes table never answers "where do I submit?" with a retired door.

    Requires:
        - door is a RETIRED_DOORS key

    Ensures:
        - a prefix row naming the door also says it is 410, so the reader is not sent to
          a door that refuses
    """
    for number, row in _rows_naming( door, _PREFIX_ROW ):
        assert any( marker in row for marker in _GONE_MARKERS ), (
            f"{DOC_RELATIVE_PATH}:{number} names {door} as the submit endpoint, but that "
            f"door answers 410 — submission moved to {RETIRED_DOORS[ door ]}:\n  {row}"
        )


@pytest.mark.parametrize( "door", sorted( RETIRED_DOORS ), ids=sorted( RETIRED_DOORS ) )
def test_every_retired_door_is_tombstoned_somewhere_in_an_endpoint_table( door ):
    """
    Every retired door has an endpoint row, and that row says it is gone.

    Requires:
        - door is a RETIRED_DOORS key

    Ensures:
        - at least one `| METHOD | door | … |` row exists and carries a gone-marker

    WHY AN OMISSION NEEDS ITS OWN TEST, and why the two guards above do not cover it.
    They quantify over the rows that EXIST — "no row lies" — so a door with no row at all
    satisfies both vacuously. That is how four of the twelve sat unmentioned on
    2026-09-28: `/api/bug-fix-expediter/submit`, `/api/deep-research-to-presentation/
    submit`, `/api/presentation-generator/submit` and `/api/push-agentic` appeared only in
    the §🪦 header table, which a reader scanning §11 or §16 never reaches.

    An absent row and a correct row read identically to anyone searching the document for
    a door and finding nothing: both say "not here". Only one of them means the door is
    not there. (Mr Radio's ruling, 2026-09-28: the guard should catch the omission as well
    as the stale row.)
    """
    rows = _rows_naming( door, _ENDPOINT_ROW )
    assert rows, (
        f"{door} is retired but {DOC_RELATIVE_PATH} has no endpoint row for it — a reader "
        f"who searches its section finds nothing, which reads the same as a door that was "
        f"never there. Add a tombstone row naming {RETIRED_DOORS[ door ]}."
    )
    marked = [ number for number, row in rows if any( marker in row for marker in _GONE_MARKERS ) ]
    assert marked, (
        f"{door} has {len( rows )} endpoint row(s) in {DOC_RELATIVE_PATH} and none says it "
        f"is gone: {[ number for number, _ in rows ]}"
    )


# ── the helper's own discriminating case, guarded rather than reasoned about ──


def test_a_door_name_does_not_match_inside_a_longer_door_name():
    """
    `_names_door` distinguishes `/api/push` from `/api/push-agentic`.

    Ensures:
        - the shorter door does NOT match a row naming only the longer one
        - the longer door does match that row

    WHY THIS IS NOT OBVIOUS FROM THE DOCUMENT. Both rows are currently marked gone, so
    the guards above pass whether or not this distinction works — they would agree by
    coincidence. Two retired doors form a prefix pair here, and a bare `in` test would
    report a correctly-tombstoned `/api/push-agentic` row as a `/api/push` violation and
    name the wrong door in the failure. The row below is a literal on purpose: pinning one
    side stops this becoming a tautology over whatever the document happens to say today.
    """
    row = "| POST | `/api/push-agentic` | JWT | a live-looking row |"
    assert _names_door( row, "/api/push-agentic" ) is True
    assert _names_door( row, "/api/push" ) is False, (
        "'/api/push' matched inside '/api/push-agentic' — the delimiter check is not working, "
        "so a failure would name the wrong door"
    )
