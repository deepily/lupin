"""
GET /api/tasks/flow-ratio — the verdict, and the edge cases that decide whether it works.

DESIGN: planning-is-prompting/src/rnd/2026.09.01-closed-vs-new-ratio-gate.md @ 845a34b.

🔴 THE VERDICT IS COMPUTED IN THE ENDPOINT, ON PURPOSE. The board's header and the
creation gate are both consumers of this one number. If each computed its own verdict from
the raw counts they could disagree — the header showing green while the gate refuses — and
a user would have no way to tell which was lying. One producer, one answer.

⚠️ THE DIVIDE-BY-ZERO CASE IS THE COMMON ONE, not an exotic edge. `closed == 0` with
creations present is a quiet day where nothing got finished, which is precisely what the
gate exists to catch, so it REFUSES. `0/0` is an idle window, which is not a failing
window, so it ALLOWS. Getting those two backwards would either gate the fleet on an empty
Sunday or wave through the exact condition the gate was filed against — which is why they
have named tests rather than riding on a single `if closed:`.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from cosa.rest.routers import tasks as tasks_router


def _call( created, closed, window_hours=24, project=None ):
    """
    Drive the endpoint function directly with a stubbed repository.

    Direct call rather than TestClient: the auth dependency and a live DB are not what
    these tests are about, and standing up both would make the verdict cases slower and
    no more truthful. The route's REGISTRATION is asserted separately below, so "the
    function is right" and "the function is reachable" are two facts with two tests
    rather than one test that quietly covers only one of them.
    """
    fake_repo = MagicMock()
    fake_repo.count_created_and_closed.return_value = {
        "created"      : created,
        "closed"       : closed,
        "window_start" : datetime( 2026, 9, 1, tzinfo=timezone.utc ),
        "window_end"   : None,
        "project"      : project,
    }

    ctx = MagicMock()
    ctx.__enter__.return_value = MagicMock()

    with patch.object( tasks_router, "get_db", return_value=ctx ), \
         patch.object( tasks_router, "TaskRepository", return_value=fake_repo ):
        return tasks_router.get_flow_ratio(
            authenticated_user_id = "test-user",
            window_hours          = window_hours,
            project               = project,
        )


# --------------------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "created, closed, expected_ratio, expected_verdict, why",
    [
        (  9, 10, 0.9,  "allow",  "closing faster than filing — the healthy case" ),
        ( 10, 13, 0.77, "allow",  "the live board on 2026-09-01, 24h window" ),
        ( 10, 10, 1.0,  "refuse", "EXACTLY 1.0 refuses — the gate opens BELOW 1.0" ),
        ( 11, 10, 1.1,  "refuse", "filing faster than closing" ),
        ( 211,191, 1.1, "refuse", "the live board on 2026-09-01, 168h window" ),
    ],
)
def test_the_verdict_follows_the_ratio( created, closed, expected_ratio, expected_verdict, why ):
    """
    The ruled boundary, including the exact-1.0 case.

    🔴 1.0 REFUSES. Rick's words were "adding to list requires that the threshold or ratio
    be less than 1.0", so the comparison is strict. A row at exactly 1.0 means the fleet
    filed exactly as many as it closed — treading water — and the gate exists to make the
    list shrink, not hold. An `<=` here would be a one-character change that quietly
    permits a steady state forever.
    """
    result = _call( created, closed )
    assert result[ "ratio" ]   == expected_ratio, why
    assert result[ "verdict" ] == expected_verdict, why


def test_nothing_closed_but_things_filed_refuses():
    """
    🔴 THE COMMON CASE ON A QUIET DAY, and the one a naive `created / closed` would crash on.

    A window where nothing was finished and rows were still minted is exactly what the gate
    is for. It refuses, and `ratio` is None rather than infinity or a sentinel — a consumer
    that tries to compare None fails loudly instead of silently treating a sentinel as a
    real reading.
    """
    result = _call( created=5, closed=0 )
    assert result[ "ratio" ]   is None
    assert result[ "verdict" ] == "refuse"


def test_an_idle_window_allows_rather_than_refusing():
    """
    `0/0` — nothing happened at all. An idle window is not a failing window.

    ⚠️ THIS AND THE TEST ABOVE ARE THE SAME `closed == 0` BRANCH, and they must not be
    collapsed. Both are division-by-zero; they resolve OPPOSITE ways, and only `created`
    separates them. A single test covering "closed is zero" would pass on an
    implementation that refused both — gating the fleet on an empty Sunday.
    """
    result = _call( created=0, closed=0 )
    assert result[ "ratio" ]   is None
    assert result[ "verdict" ] == "idle"


def test_idle_and_starved_are_different_verdicts_on_one_branch():
    """
    Stated as its own assertion because the pair above is the whole point of the branch.
    """
    assert _call( created=0, closed=0 )[ "verdict" ] != _call( created=1, closed=0 )[ "verdict" ]


# --------------------------------------------------------------------------------------
# What the response has to carry
# --------------------------------------------------------------------------------------

def test_the_window_is_echoed_back():
    """
    A ratio without the window it was taken over is a rumour with a timestamp.

    Not decorative: the 24h and 168h windows on the same live board produce OPPOSITE
    verdicts (0.77 allow / 1.10 refuse, measured 2026-09-01 minutes apart). A consumer
    rendering a number without saying which window produced it is showing something the
    reader cannot interpret.
    """
    result = _call( created=1, closed=2, window_hours=168 )
    assert result[ "window_hours" ] == 168

    # window_start is the endpoint's OWN computed value, not anything the repository
    # returned — the stub's window_start is deliberately ignored by the response. So this
    # checks it is a real timestamp about 168 hours back, rather than pinning a date.
    #
    # ⚠️ My first cut asserted `.startswith( "2026-09-01" )` and it FAILED, correctly: a
    # 168-hour window starts a week ago, not today. The test was wrong and the code was
    # right. Pinning a literal date would also have rotted tomorrow.
    started = datetime.fromisoformat( result[ "window_start" ] )
    hours_back = ( datetime.now( timezone.utc ) - started ).total_seconds() / 3600
    assert 167.9 < hours_back < 168.1, f"expected ~168h back, got {hours_back:.2f}h"


def test_the_window_reaches_the_repository_rather_than_only_the_response():
    """
    ⚠️ ECHOING THE WINDOW BACK AND MEASURING IT ARE DIFFERENT THINGS.

    An implementation that returned `window_hours` from its own argument while always
    querying 24 hours would pass the test above and be wrong. This asserts the value
    actually reached the query — the response field is a claim, and this is the check on it.
    """
    fake_repo = MagicMock()
    fake_repo.count_created_and_closed.return_value = {
        "created": 0, "closed": 0,
        "window_start": datetime( 2026, 9, 1, tzinfo=timezone.utc ),
        "window_end": None, "project": None,
    }
    ctx = MagicMock()
    ctx.__enter__.return_value = MagicMock()

    with patch.object( tasks_router, "get_db", return_value=ctx ), \
         patch.object( tasks_router, "TaskRepository", return_value=fake_repo ):
        tasks_router.get_flow_ratio( authenticated_user_id="u", window_hours=1, project=None )

    since = fake_repo.count_created_and_closed.call_args.kwargs[ "since" ]
    delta = datetime.now( timezone.utc ) - since
    assert 0.9 < delta.total_seconds() / 3600 < 1.1, (
        f"window_hours=1 should query roughly one hour back, queried {delta}"
    )


def test_fleet_wide_is_the_default():
    """Rick ruled scope FLEET-WIDE (Q5). Absent a project, none is passed down."""
    result = _call( created=1, closed=2 )
    assert result[ "project" ] is None


def test_a_project_scope_is_passed_through():
    result = _call( created=1, closed=2, project="lupin" )
    assert result[ "project" ] == "lupin"


def test_the_route_is_registered_and_authenticated():
    """
    The function being correct says nothing about it being reachable, or guarded.

    Both are asserted here because a route that is right and unwired is invisible, and one
    that is right and unguarded is worse than absent — it hands the board's state to anyone.
    """
    route = next( ( r for r in tasks_router.router.routes
                    if getattr( r, "path", None ) == "/api/tasks/flow-ratio" ), None )
    assert route is not None, "the endpoint is not registered on the router"
    assert "GET" in route.methods

    params = route.dependant.query_params + [ d.call for d in route.dependant.dependencies ]
    assert route.dependant.dependencies, "the route declares no dependency — auth is missing"
