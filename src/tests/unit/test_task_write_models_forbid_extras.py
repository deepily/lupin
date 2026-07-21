"""
Row 98854a4b — every task-store WRITE model must reject an undeclared field.

WHAT THIS PINS, and why it is not a style test: all five write models are the
wire contract for the unified task store. Four of them shipped on pydantic's
DEFAULT `extra=IGNORE`, so a field a caller cared enough to send vanished on a
2xx with no warning — measured live before the fix (POST /api/tasks carrying
`park_reason` + `nonsense` returned 201 with both gone). `TaskPatchIn` already
set `extra='forbid'` and its own docstring calls that a "HARD wire-level
invariant" — so the store held the right pattern and applied it to one surface
out of five.

PROVE IT CAN STILL FAIL: revert `model_config = ConfigDict( extra="forbid" )` on
ANY ONE of the five models and `test_every_write_model_forbids_extras` goes RED
naming that model. The parametrization is over the model list, so a model added
later without the config fails here rather than shipping silent.

Cross-ref: 9bb4debe (the create-path `next_chase_ts` discard that prompted the
sweep) · 21d6f3d9.
"""

import pytest
from pydantic import ValidationError

from cosa.rest.routers.tasks import (
    TaskAmendIn,
    TaskCorrelateIn,
    TaskCreateIn,
    TaskPatchIn,
    TaskTransitionIn,
)


# Every write model, with a MINIMAL valid payload for each. The payloads are
# deliberately minimal: this file asserts the extras policy, not field rules.
WRITE_MODELS = [
    ( TaskCreateIn,     { "item_class": "task", "title": "t", "project": "lupin", "created_by": "x" } ),
    ( TaskTransitionIn, { "to_status": "done", "actor": "x" } ),
    ( TaskCorrelateIn,  { "correlation_key": "ck", "actor": "x" } ),
    ( TaskAmendIn,      { "note": "n", "actor": "x" } ),
    ( TaskPatchIn,      { "actor": "x" } ),
]

MODEL_IDS = [ m.__name__ for m, _ in WRITE_MODELS ]


@pytest.mark.parametrize( "model,valid_payload", WRITE_MODELS, ids=MODEL_IDS )
def test_every_write_model_forbids_extras( model, valid_payload ):
    """An undeclared field is a 422-shaped rejection, never a silent drop."""
    # control: the minimal payload itself must be ACCEPTED, so a failure below
    # cannot be the payload being wrong rather than the extras policy working.
    model( **valid_payload )

    with pytest.raises( ValidationError ) as excinfo:
        model( **valid_payload, park_reason_typo="I AM A GHOST" )

    errors = excinfo.value.errors()
    assert any( e[ "type" ] == "extra_forbidden" for e in errors ), \
        f"{model.__name__} rejected the payload, but NOT for extra_forbidden: {errors}"


@pytest.mark.parametrize( "model,_payload", WRITE_MODELS, ids=MODEL_IDS )
def test_every_write_model_declares_forbid_explicitly( model, _payload ):
    """
    The policy must be DECLARED, not inherited from whatever pydantic defaults to.

    Separate from the behavioural test above on purpose: a future pydantic whose
    default flipped to 'forbid' would make that test pass for a reason this
    codebase never chose. This one fails if the declaration goes missing even
    while behaviour looks right.
    """
    assert model.model_config.get( "extra" ) == "forbid", \
        f"{model.__name__} does not DECLARE extra='forbid' (got {model.model_config.get( 'extra' )!r})"
