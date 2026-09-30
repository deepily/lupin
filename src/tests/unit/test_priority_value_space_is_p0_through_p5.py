"""
Guard for row `0107c19e` — Rick's broadcast e254ec7d, 2026-09-07:
"you need to have a range of P0 through P5" and "The default Priority from
here on now will be P5."

WHY THE NEGATIVE ARMS ARE NOT CEREMONY
---------------------------------------
A test that only asserts the six ACCEPTED values passes just as happily
against a validator that accepts EVERYTHING — delete the membership check
entirely and every positive arm stays green. The `P6` / `P-1` arms are what
prove the validator still discriminates rather than merely permits, and they
are the reason this file can be trusted as a guard instead of a description.

Same reasoning for the default arms: asserting "the default is P5" against a
signature default is a fact about a Python function object. The arms below
also drive the DECLARED default on the HTTP request model, because that is
the value a caller who omits the field actually receives.
"""
import inspect

import pytest

import cosa.rest.task_store_rules as rules


EXPECTED_PRIORITIES = ( "P0", "P1", "P2", "P3", "P4", "P5" )


def test_the_value_space_is_exactly_p0_through_p5():
    """The tuple itself — ordered, complete, and nothing extra."""
    assert rules.VALID_PRIORITIES == EXPECTED_PRIORITIES


@pytest.mark.parametrize( "priority", EXPECTED_PRIORITIES )
def test_every_priority_p0_through_p5_is_accepted_on_create( priority ):
    """All six pass the create validator — P4 and P5 included, which is the change."""
    errors = rules.validate_create(
        item_class = "task",
        gate_class = "none",
        priority   = priority,
        authority  = "standing",
        urgency    = "normal"
    )
    assert errors == [ ], f"'{priority}' was refused on create: {errors}"


@pytest.mark.parametrize( "priority", EXPECTED_PRIORITIES )
def test_every_priority_p0_through_p5_is_accepted_on_edit( priority ):
    """The edit path reads the same tuple — pinned separately, because a
    reader who widens one validator and not the other breaks only this arm."""
    assert rules.validate_patch( { "priority": priority } ) == [ ]


@pytest.mark.parametrize( "bogus", [ "P6", "P-1", "P10", "p5", "", "5", "PRIORITY_5" ] )
def test_a_value_outside_p0_through_p5_is_still_refused_on_create( bogus ):
    """THE DISCRIMINATING ARM. Widening an enum is one keystroke away from
    deleting the check; without this, that deletion is invisible."""
    errors = rules.validate_create(
        item_class = "task",
        gate_class = "none",
        priority   = bogus,
        authority  = "standing",
        urgency    = "normal"
    )
    assert errors, f"'{bogus}' was ACCEPTED — the membership check is gone"


@pytest.mark.parametrize( "bogus", [ "P6", "P-1", "p5", "" ] )
def test_a_value_outside_p0_through_p5_is_still_refused_on_edit( bogus ):
    assert rules.validate_patch( { "priority": bogus } ), f"'{bogus}' accepted on edit"


def test_the_http_create_door_declares_p5_as_its_default():
    """The value a caller who OMITS priority actually gets.

    Read off the request model rather than off the rules module: this is the
    field a client hits, and it carried "P2" independently of the enum until
    row 0107c19e moved it.
    """
    from cosa.rest.routers.tasks import TaskCreateIn

    field = TaskCreateIn.model_fields[ "priority" ]
    assert field.default == "P5", f"HTTP door still defaults to {field.default!r}"


def test_the_repository_layer_defaults_to_p5():
    """The second of the four sites — a different door, its own default."""
    from cosa.rest.db.repositories.task_repository import TaskRepository

    sig = inspect.signature( TaskRepository.create_item )
    assert sig.parameters[ "priority" ].default == "P5"


def test_the_orm_column_defaults_to_p5_on_both_halves():
    """The model's TWO defaults. `default` fires when the ORM builds the
    INSERT; `server_default` fires when an INSERT omits the column entirely.
    A code-only change moves the first and leaves the second — which is the
    exact half migration 9a1c4f27bd30 exists to carry, so both are pinned."""
    from cosa.rest.postgres_models import TaskItem

    column = TaskItem.__table__.columns[ "priority" ]
    assert column.default.arg              == "P5"
    assert column.server_default.arg       == "P5"


def test_the_widened_space_still_fits_the_column_width():
    """No migration widens this column, so nothing may outgrow it.

    Fails loudly the day someone adds "P10" without noticing String( 2 ).
    """
    from cosa.rest.postgres_models import TaskItem

    width = TaskItem.__table__.columns[ "priority" ].type.length
    too_long = [ p for p in rules.VALID_PRIORITIES if len( p ) > width ]
    assert too_long == [ ], f"{too_long} exceed the String( {width} ) column"
