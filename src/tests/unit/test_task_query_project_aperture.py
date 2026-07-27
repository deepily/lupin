"""
Aperture disclosure for project-scoped queries — bug `d23147e8`, item 3.

THE DEFECT THESE PIN: `project` is free text. `TaskCreateIn` validates only
`min_length=1, max_length=255` and `_canon_project` passes any non-aliased name
through unchanged, so a typo mints a project silently and permanently. A caller
who asks for `project="skills-distillation"` while a row sits under
`"google-skills-distillation"` gets a clean, plausible, SMALLER number and NOTHING
says a row was excluded. That is how `52c1c41e` stayed invisible to a census that
Rick's drop order was then executed against.

Item 2 of that row (grow the alias table) was STRUCK on measurement: the table has
exactly one entry and free text is unbounded, so you cannot enumerate aliases for
names nobody has agreed on. What scales is the query publishing its own blind spot.

⚠️ WHY THE RANKING TESTS ARE NOT COSMETIC. The first implementation sorted the
excluded buckets by count descending. An orphan spelling is RARE — that is what
makes it an orphan — so count-descending puts the one value worth seeing LAST,
behind every large unrelated project, where the top-N cut drops it first. Against
the live store that ordered the real defect ('google-skills-distillation'=1) at
position 8 of 8, under 'lupin'=838. A disclosure whose ordering hides its own
signal is the `park_reason_stale` failure mode: a flag readers learn to skip,
which disarms it permanently. `test_rare_near_miss_outranks_a_large_unrelated_project`
is the arm that goes RED if anyone restores a count-only sort.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

NOW = datetime( 2026, 7, 27, 0, 0, tzinfo=timezone.utc )

APERTURE_MARKER = "excluded by this filter"


def make_item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row",
        body                = None,
        project             = "skills-distillation",
        owner_persona       = "maria",
        accountable_manager = "mr radio",
        created_by          = "maria 697e9fef",
        status              = "queued",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P2",
        source_qid          = None,
        correlation_key     = None,
        created_ts          = NOW,
        updated_ts          = NOW,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def repo( monkeypatch ):
    fake = MagicMock()
    fake.count_tasks.return_value          = 1
    fake.statuses_for_ids.return_value     = { }
    # Real dict, not a MagicMock: `.items()` on a MagicMock iterates as nothing, so
    # the disclosure would emit no warning and every assertion below would pass
    # against unfixed code.
    fake.count_tasks_by_project.return_value = { }
    fake.query_tasks.return_value            = [ make_item() ]

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def client( repo ):
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


def aperture_warnings( response ):
    return [ w for w in response.json()[ "warnings" ] if APERTURE_MARKER in w ]


# ── The defect itself ────────────────────────────────────────────────────────

def test_excluded_project_is_disclosed( client, repo ):
    """The 52c1c41e case: an orphan spelling must appear in the response."""
    repo.count_tasks_by_project.return_value = {
        "skills-distillation"        : 287,
        "google-skills-distillation" : 1,
    }
    r = client.get( "/api/tasks", params={ "project": "skills-distillation" } )
    assert r.status_code == 200
    warns = aperture_warnings( r )
    assert len( warns ) == 1
    assert "google-skills-distillation" in warns[ 0 ]


def test_matched_project_is_never_listed_as_excluded( client, repo ):
    """The queried project is by definition matched — listing it would be a lie."""
    repo.count_tasks_by_project.return_value = {
        "skills-distillation"        : 287,
        "google-skills-distillation" : 1,
    }
    r = client.get( "/api/tasks", params={ "project": "skills-distillation" } )
    warns = aperture_warnings( r )
    assert "'skills-distillation'=" not in warns[ 0 ]


def test_excluded_row_count_is_reported( client, repo ):
    repo.count_tasks_by_project.return_value = { "skills-distillation": 5, "lupin": 838, "lookml": 1 }
    r = client.get( "/api/tasks", params={ "project": "skills-distillation" } )
    assert "839 row(s) under 2 OTHER project value(s)" in aperture_warnings( r )[ 0 ]


# ── Negative controls: the arms that must NOT fire ───────────────────────────

def test_no_project_filter_emits_no_aperture_warning( client, repo ):
    """
    NEGATIVE CONTROL. With no project filter the caller already sees every
    project, so there is no blind spot to declare. A disclosure that fired here
    would be pure noise on the most common query shape — and noise is how a
    real flag gets trained out of a reader.
    """
    repo.count_tasks_by_project.return_value = { "lupin": 838, "plan": 148 }
    r = client.get( "/api/tasks", params={ "unscoped_audit": "true" } )
    assert aperture_warnings( r ) == [ ]


def test_sole_project_emits_no_aperture_warning( client, repo ):
    """Nothing was excluded, so nothing is disclosed — an empty finding stays silent."""
    repo.count_tasks_by_project.return_value = { "skills-distillation": 287 }
    r = client.get( "/api/tasks", params={ "project": "skills-distillation" } )
    assert aperture_warnings( r ) == [ ]


def test_query_by_alias_does_not_report_the_canonical_rows_as_excluded( client, repo ):
    """
    `planning-is-prompting` canonicalizes to `plan` at the filter seam, so rows
    stored as `plan` DID match. Reporting them as excluded would manufacture a
    false finding out of the one alias the store actually handles.

    ⚠️ THIS ARM IS NOT A GUARD ON THE CANONICALIZATION, and it must not be read as
    one. The router canonicalizes `project` BEFORE the comparison, so both sides
    are already canonical here and a raw comparison passes it identically —
    verified by mutation: replacing `_canon_project( stored ) != project` with
    `stored != project` leaves this GREEN. The arm below is the one that bites.
    """
    repo.count_tasks_by_project.return_value = { "plan": 148, "lupin": 838 }
    r = client.get( "/api/tasks", params={ "project": "planning-is-prompting" } )
    warns = aperture_warnings( r )
    assert len( warns ) == 1
    assert "'plan'=" not in warns[ 0 ]
    assert "'lupin'=838" in warns[ 0 ]


def test_rows_STORED_under_the_raw_alias_are_not_reported_as_excluded( client, repo ):
    """
    ⚠️ THE ARM THAT MAKES `_canon_project( stored )` LOAD-BEARING.

    The filter value is canonicalized by the router, so comparing it against a
    RAW stored value is only wrong when the ROW is the non-canonical side — a row
    written `"planning-is-prompting"` by a non-wrapper POST while the query asks
    for `"plan"`. Those rows DO match (`_canon_project` is applied at the filter
    seam on the way into the repo), so reporting them excluded is a false finding
    pointing at the one alias the store already handles correctly.

    Drop the `_canon_project(...)` wrapper on `stored` and this goes RED. The
    sibling arm above does not, which is why both exist.
    """
    repo.count_tasks_by_project.return_value = { "planning-is-prompting": 5, "lupin": 838 }
    r = client.get( "/api/tasks", params={ "project": "plan" } )
    warns = aperture_warnings( r )
    assert len( warns ) == 1
    assert "planning-is-prompting" not in warns[ 0 ]
    assert "'lupin'=838" in warns[ 0 ]


# ── Ranking: the arm that fails if the sort regresses ────────────────────────

def test_rare_near_miss_outranks_a_large_unrelated_project( client, repo ):
    """
    ⚠️ THE LOAD-BEARING ARM. A count-descending sort puts the 1-row orphan last,
    behind an 838-row unrelated project, and the top-10 cut drops it first.
    Restore a count-only sort and this goes RED.
    """
    repo.count_tasks_by_project.return_value = {
        "skills-distillation"        : 287,
        "lupin"                      : 838,
        "google-skills-distillation" : 1,
    }
    r = client.get( "/api/tasks", params={ "project": "skills-distillation" } )
    warns = aperture_warnings( r )[ 0 ]
    listing = warns.split( "(nearest-first):" )[ 1 ]
    assert listing.index( "google-skills-distillation" ) < listing.index( "lupin" )


def test_near_miss_is_called_out_before_the_full_listing( client, repo ):
    repo.count_tasks_by_project.return_value = {
        "skills-distillation"        : 287,
        "lupin"                      : 838,
        "google-skills-distillation" : 1,
    }
    r = client.get( "/api/tasks", params={ "project": "skills-distillation" } )
    warns = aperture_warnings( r )[ 0 ]
    assert "LIKELY SAME PROJECT, DIFFERENT SPELLING" in warns
    assert warns.index( "LIKELY SAME PROJECT" ) < warns.index( "(nearest-first)" )


def test_no_near_miss_says_so_rather_than_leaving_the_reader_to_infer_it( client, repo ):
    """
    An absent callout and an absent NEAR-MISS are different facts. Saying
    'no near-miss detected' distinguishes "the check ran and found nothing" from
    "the check never ran" — the absence-with-two-meanings shape this row's own
    family (`00a6bde2`, `955ff71c`) exists to kill.
    """
    repo.count_tasks_by_project.return_value = { "skills-distillation": 287, "lupin": 838 }
    r = client.get( "/api/tasks", params={ "project": "skills-distillation" } )
    assert "No near-miss spelling detected" in aperture_warnings( r )[ 0 ]


def test_substring_match_is_directional_both_ways( client, repo ):
    """A near miss counts whether the stem is a prefix ON the query or ON the stored value."""
    repo.count_tasks_by_project.return_value = { "google-skills-distillation": 1, "skills-distillation": 287 }
    r = client.get( "/api/tasks", params={ "project": "google-skills-distillation" } )
    warns = aperture_warnings( r )[ 0 ]
    assert "LIKELY SAME PROJECT, DIFFERENT SPELLING: 'skills-distillation'" in warns


def test_a_null_project_bucket_is_disclosed_not_dropped( client, repo ):
    """A row with no project at all is exactly what a census must be able to see."""
    repo.count_tasks_by_project.return_value = { "skills-distillation": 287, None: 3 }
    r = client.get( "/api/tasks", params={ "project": "skills-distillation" } )
    assert "None=3" in aperture_warnings( r )[ 0 ]
