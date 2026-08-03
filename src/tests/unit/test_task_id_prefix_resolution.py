"""
Unit tests for 8-hex prefix resolution on GET /api/tasks/{task_id} (f45b37a9 leg 1).

THE DEFECT THIS CLOSES
----------------------
Every brief, DM and cross-reference in this fleet names rows by 8-hex prefix —
`86ce4c43`, `f45b37a9`, `9bb4debe`. NO READ VERB ACCEPTED THAT FORM:

    task_get( task_id="86ce4c43" )
    -> 422 {"type":"uuid_parsing","msg":"Input should be a valid UUID,
            invalid length: expected length 32 for simple format, found 8"}

The identifier the fleet actually communicates in could not fetch the thing it
names. Two seats hit that 422 on 2026-07-21 alone; one of them (me) could only
open a row assigned by id by querying the manager's whole board on a hunch.

SCOPE — READS ONLY, DELIBERATELY
--------------------------------
Prefix resolution lands on GET only. The mutating routes keep `uuid.UUID` and
stay strict. A prefix that resolves to the wrong row on a READ is merely wrong;
on a transition it is DESTRUCTIVE — it would move a row nobody named. The
convenience is worth having exactly where the blast radius is zero.

AMBIGUITY IS AN ERROR, NEVER A SILENT FIRST-MATCH
-------------------------------------------------
If a prefix matches more than one row the request FAILS and NAMES the
candidates. Silently picking one would be the same class of defect as the row
this came from: an identifier that resolves to something other than what the
caller meant, with nothing saying so.
"""

import os
import sys
import uuid
from unittest.mock import MagicMock

import pytest

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from cosa.rest.task_store_rules import classify_task_ref, TASK_REF_FULL, TASK_REF_PREFIX, TASK_REF_INVALID


# ---------------------------------------------------------------------------
# The pure classifier — what SHAPE of reference did the caller supply?
# ---------------------------------------------------------------------------

def test_a_full_canonical_uuid_classifies_as_full():
    kind, value = classify_task_ref( "86ce4c43-3ba9-4ef7-a3a0-f1fa0b263e2a" )

    assert kind == TASK_REF_FULL
    assert value == uuid.UUID( "86ce4c43-3ba9-4ef7-a3a0-f1fa0b263e2a" )


def test_the_8_hex_form_every_brief_uses_classifies_as_prefix():
    # THE WHOLE POINT OF THE ROW.
    kind, value = classify_task_ref( "86ce4c43" )

    assert kind == TASK_REF_PREFIX
    assert value == "86ce4c43"


@pytest.mark.parametrize( "ref", [ "86ce4c4", "86ce4c43a", "86ce4c43-3ba9" ] )
def test_other_hex_lengths_are_accepted_as_prefixes_too( ref ):
    # A 7- or 9-hex prefix is not less valid than 8 — 8 is a fleet convention,
    # not a property of the id. Hyphens are tolerated because that is how a
    # partially-copied UUID looks.
    kind, _ = classify_task_ref( ref )

    assert kind == TASK_REF_PREFIX


@pytest.mark.parametrize( "ref", [ "", "   ", "zzzzzzzz", "86ce4c43!", "../etc/passwd", None ] )
def test_junk_classifies_as_invalid_never_as_a_prefix( ref ):
    # An invalid ref must NOT become a prefix query — a LIKE against arbitrary
    # caller text is how an id filter turns into a search surface.
    kind, _ = classify_task_ref( ref )

    assert kind == TASK_REF_INVALID


def test_a_single_hex_char_is_not_a_usable_prefix():
    # Guard against the degenerate case: "8" would match a large fraction of the
    # table and the ambiguity error would be useless. Too short to be a REF.
    kind, _ = classify_task_ref( "8" )

    assert kind == TASK_REF_INVALID


def test_classification_is_case_insensitive_on_hex():
    kind, value = classify_task_ref( "86CE4C43" )

    assert kind == TASK_REF_PREFIX
    assert value == "86ce4c43"   # normalized down, because the column is lowercase


# ---------------------------------------------------------------------------
# The repository lookup
# ---------------------------------------------------------------------------

def test_repository_exposes_a_prefix_finder():
    from cosa.rest.db.repositories.task_repository import TaskRepository

    session = MagicMock()
    repo    = TaskRepository( session )

    assert hasattr( repo, "find_by_id_prefix" ), \
        "TaskRepository must expose find_by_id_prefix for 8-hex resolution"


def test_prefix_finder_is_bounded_so_an_ambiguous_prefix_cannot_pull_the_table():
    """
    A 1-char prefix is already refused by the classifier, but the finder must
    ALSO cap what it returns: the caller only needs to know 'more than one', and
    an unbounded LIKE on a growing table is the unscoped-query defect again.
    """
    import inspect
    from cosa.rest.db.repositories.task_repository import TaskRepository

    src = inspect.getsource( TaskRepository.find_by_id_prefix )

    assert "limit" in src, "find_by_id_prefix must bound its result set"


# ---------------------------------------------------------------------------
# Ambiguity — the behaviour that must NEVER be a silent first-match
# ---------------------------------------------------------------------------

def test_ambiguous_prefix_raises_and_names_every_candidate():
    from cosa.rest.routers.tasks import _resolve_task_ref
    from fastapi import HTTPException

    a = "86ce4c43-3ba9-4ef7-a3a0-f1fa0b263e2a"
    b = "86ce4c43-0000-4000-8000-000000000000"

    repo = MagicMock()
    repo.find_by_id_prefix.return_value = [ MagicMock( id=uuid.UUID( a ) ),
                                            MagicMock( id=uuid.UUID( b ) ) ]

    with pytest.raises( HTTPException ) as exc:
        _resolve_task_ref( repo, "86ce4c43" )

    assert exc.value.status_code == 422
    detail = str( exc.value.detail )
    # BOTH candidates named — a caller cannot disambiguate from a count.
    assert a in detail and b in detail


def test_unique_prefix_resolves_to_the_one_row():
    from cosa.rest.routers.tasks import _resolve_task_ref

    only = MagicMock( id=uuid.UUID( "86ce4c43-3ba9-4ef7-a3a0-f1fa0b263e2a" ) )
    repo = MagicMock()
    repo.find_by_id_prefix.return_value = [ only ]

    assert _resolve_task_ref( repo, "86ce4c43" ) is only


def test_prefix_matching_nothing_404s_naming_the_ref_the_caller_typed():
    from cosa.rest.routers.tasks import _resolve_task_ref
    from fastapi import HTTPException

    repo = MagicMock()
    repo.find_by_id_prefix.return_value = [ ]

    with pytest.raises( HTTPException ) as exc:
        _resolve_task_ref( repo, "deadbeef" )

    assert exc.value.status_code == 404
    assert "deadbeef" in str( exc.value.detail )


def test_a_full_uuid_goes_STRAIGHT_to_get_by_id_and_never_prefix_scans():
    # Behaviour-preserving for every existing caller: a full UUID must not
    # acquire a LIKE scan it never had.
    from cosa.rest.routers.tasks import _resolve_task_ref

    found = MagicMock()
    repo  = MagicMock()
    repo.get_by_id.return_value = found

    assert _resolve_task_ref( repo, "86ce4c43-3ba9-4ef7-a3a0-f1fa0b263e2a" ) is found
    repo.find_by_id_prefix.assert_not_called()


def test_invalid_ref_422s_without_touching_the_database():
    from cosa.rest.routers.tasks import _resolve_task_ref
    from fastapi import HTTPException

    repo = MagicMock()

    with pytest.raises( HTTPException ) as exc:
        _resolve_task_ref( repo, "zzzz" )

    assert exc.value.status_code == 422
    repo.get_by_id.assert_not_called()
    repo.find_by_id_prefix.assert_not_called()


# ---------------------------------------------------------------------------
# WRITES STAY STRICT — the scope fence, asserted rather than described
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "handler_name", [
    "transition_task", "correlate_task", "amend_task", "patch_task", "reassign_task",
] )
def test_mutating_routes_keep_strict_uuid_typing( handler_name ):
    """
    A prefix that resolves wrong on a READ is merely wrong; on a WRITE it moves a
    row nobody named. If a future change relaxes a mutating route's `task_id` to
    `str`, this fails and asks for that decision to be made deliberately.
    """
    import inspect
    from cosa.rest.routers import tasks

    handler = getattr( tasks, handler_name, None )
    if handler is None:
        pytest.skip( f"{handler_name} not present in this build" )

    annotation = inspect.signature( handler ).parameters[ "task_id" ].annotation
    assert annotation is uuid.UUID, \
        f"{handler_name} must keep uuid.UUID typing — prefix resolution is READ-only"
