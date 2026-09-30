"""
There is no server-side BATCH door for task verbs — pinned so it is not re-derived.

WHY THIS EXISTS. Asked whether batch approve / batch won't-fix are refused server-side, the
honest answer is that there is nothing server-side to refuse: no batch endpoint exists.
`_applyHoldingBatch` (notifications.js:12375) closes a whole group from one click by driving
the ORDINARY per-task transition door N times, sequentially. Every row therefore meets the
same authorization the single-row path meets, which is why the answer is "already refused
per row" and not "hidden in the UI".

🔴 THAT IS A LOAD-BEARING ABSENCE, AND AN ABSENCE IS THE ONE FINDING THAT LOOKS THE SAME
WHETHER YOU DID THE WORK OR NOT. It took a source read to establish and would take another
one next week. A future batch endpoint would be a NEW door onto the transition machinery,
bypassing whatever the per-row door enforces — so this fails loudly the day one appears,
rather than leaving the next reader to rediscover the shape.

⚠️ IT DOES NOT FORBID A BATCH ENDPOINT. It requires that adding one is a DELIBERATE act that
re-opens this question, with the gate and the approval check reconsidered at the new door.

⚠️ SCOPE, MEASURED 2026-09-04: `/api/embeddings/batch`, `/admin/users/batch-delete` and the
decision proxy's `/batch-id` all exist and are NOT task verbs. This asserts only that the
TASK router carries no batch door, so those three neither trip it nor are blessed by it.
"""

import pytest

from cosa.rest.routers import tasks as tasks_router_module


def _task_route_paths():
    return [ r.path for r in tasks_router_module.router.routes ]


def test_the_task_route_census_is_nonvacuous():
    """
    POSITIVE CONTROL for the absence test below — required, not decorative.

    That test asserts NO task route contains "batch". An empty route list satisfies it
    perfectly, so a refactor that renamed the router, moved the routes, or broke the import
    would turn the guard green while removing everything it guards. This proves the census
    reaches real routes first.

    Ensures:
        - the task router exposes a plausible number of routes
        - the transition door — the one a batch endpoint would bypass — is among them
    """
    paths = _task_route_paths()
    assert len( paths ) >= 5, (
        f"the task-route census found only {len( paths )} route(s): {paths}. The absence "
        f"test below cannot mean anything until this finds real routes."
    )
    assert any( p.endswith( "/transition" ) for p in paths ), (
        f"the transition door is missing from the census: {paths}. That door is precisely "
        f"what a batch endpoint would bypass, so its absence means this guard is pointed "
        f"at the wrong router."
    )


def test_no_batch_endpoint_exists_for_task_verbs():
    """
    No task route offers a batch door.

    Ensures:
        - fails the day a batch task endpoint is added, naming it
    """
    offenders = [ p for p in _task_route_paths() if "batch" in p.lower() ]
    assert not offenders, (
        f"a batch task endpoint now exists: {offenders}. Batch approve and batch won't-fix "
        f"are Rick-only, and today they are safe only because the client loops the "
        f"single-row transition door (_applyHoldingBatch, notifications.js:12375) so every "
        f"row meets the per-row authorization. A batch door is a NEW entrance to the same "
        f"machinery: re-check the approval gate AND the closed-vs-new ratio gate at it "
        f"before deleting this test — see test_a_wont_fix_spree_never_counts_as_closed."
    )
