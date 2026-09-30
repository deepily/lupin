"""
THE task_create DESCRIPTION TELLS A MANAGER HOW TO FILE A P0 RICK ORDERED — row d2b1b59a,
done-means 5.

Until this landed a seat had to DISCOVER `authority="user_direct"`: the description
listed the value among three with no word on what it does. These tests read the
REGISTERED `FunctionTool.description` — what a seat actually receives — and tie every
fact in it to the code that decides that fact, so the text cannot drift from the door
without reddening a named test here.

⚠️ READ THROUGH A PINNED-TREE IMPORT, NOT THROUGH A LIVE MCP SUBPROCESS. A seat's stdio
MCP server was started with the seat and keeps serving the description it loaded then,
so it cannot see this change. `test_the_description_is_read_from_the_tree_under_test`
proves the import came from LUPIN_ROOT rather than some other checkout.

The petition's KEYS are captured from the real create door (the harness of
`test_the_petition_at_the_real_create_door.py`), never restated here: a hand-written key
list would agree with a hand-written docstring and prove nothing.

Venue: :7999-eligible (pure unit — no server, no DB, every seam monkeypatched).
"""

import os
from datetime import datetime, timezone

import pytest

import lupin_mcp.cosa_voice_mcp as cv
from cosa.rest import task_priority_firewall as firewall
from cosa.rest import task_promotion_gate as promotion_gate
from cosa.rest import task_promotion_resolver as promotion_resolver
from cosa.rest import task_store_rules as rules

# The real create-door harness, imported rather than copied so the two cannot drift.
from tests.unit.test_the_petition_at_the_real_create_door import (  # noqa: F401  (fixtures)
    added, created_items, manager_bridge, repo, resolver_calls, settings, _client, _create,
)


@pytest.fixture
def description():
    """The description a seat receives for task_create, from the registered tool."""
    return cv.task_create.description


def test_the_description_is_read_from_the_tree_under_test():
    root = os.environ.get( "LUPIN_ROOT" )
    assert root, "LUPIN_ROOT must be pinned — an unpinned run reads whichever tree the shell names"
    assert os.path.realpath( cv.__file__ ).startswith( os.path.realpath( root ) + os.sep )


def test_the_registered_description_is_the_docstring( description ):
    """The block must survive registration, not only sit in `.fn.__doc__`."""
    assert description.strip() == cv.task_create.fn.__doc__.strip()
    assert "FILING A P0 THAT RICK ORDERED" in description


def test_it_names_the_call_that_files_the_petition( description ):
    """
    The INSTRUCTION sentence, not the bare values: the example below also carries both,
    so asserting the values alone passed with the instruction deleted (revert arm F).
    """
    assert (
        f'Call with `priority="{firewall.OPERATOR_ONLY_PRIORITY}"` AND '
        f'`authority="{firewall.PETITIONABLE_AUTHORITY}"`'
    ) in description


def test_the_petitionable_authority_is_what_the_firewall_accepts():
    """Positive control: the value the text names really is the one that opens a petition."""
    assert firewall.petition_is_available(
        firewall.OPERATOR_ONLY_PRIORITY, firewall.PETITIONABLE_AUTHORITY, bridge_role="manager"
    ) is True
    assert firewall.petition_is_available(
        firewall.OPERATOR_ONLY_PRIORITY, "standing", bridge_role="manager"
    ) is False


def test_it_says_a_P0_edit_on_an_existing_row_is_refused( description ):
    assert "task_edit" in description
    assert "the petition exists only at create" in description


def test_it_names_the_holding_priority_and_status( description ):
    assert f'minted_at: "{firewall.PETITION_HOLDING_PRIORITY}"' in description
    assert f'requesting: "{firewall.OPERATOR_ONLY_PRIORITY}"' in description
    assert f"`{rules.NOT_APPROVED_STATUS}`" in description


def test_it_names_every_key_the_real_door_returns(
    description, settings, repo, manager_bridge, resolver_calls, added
):
    r = _create( _client() )
    assert r.status_code == 201
    assert "201" in description
    petition = r.json()[ "petition" ]
    assert petition, "the door returned no petition keys — the loop below would pass vacuously"
    for key in petition:
        assert key in description, f"the door returns petition key {key!r} and the description never names it"
    assert f'check_with: "{petition[ "check_with" ]}"' in description


def test_it_gives_ricks_window_and_the_stall_deadline_as_different_numbers( description ):
    """
    The answer window is the ask timeout; `resolves_by` is the stall deadline. The stall
    figure is derived from the real deadline function at its fallbacks, not re-added here.
    """
    window    = promotion_gate.FALLBACK_ASK_TIMEOUT_SECONDS
    minted_at = datetime( 2026, 9, 10, tzinfo=timezone.utc )
    stall     = int( (
        promotion_resolver.resolves_by_for(
            minted_at,
            timeout_fn = lambda: promotion_gate.FALLBACK_ASK_TIMEOUT_SECONDS,
            grace_fn   = lambda: promotion_resolver.FALLBACK_NOTIFICATION_GRACE_SECONDS,
        ) - minted_at
    ).total_seconds() )
    assert window != stall
    assert f"({window}s by default)" in description
    assert f"{stall}s by default" in description
    assert "`resolves_by` is NOT his window" in description
    assert "STALL deadline" in description


def test_it_says_a_timeout_is_not_a_grant( description ):
    assert "A TIMEOUT IS NOT A GRANT" in description
    assert "Never report the P0 as landed from the 201" in description


def test_it_names_every_ticket_state( description ):
    """
    Matched as ONE run of text, whitespace-collapsed, so "pending" appearing anywhere else
    in the description cannot satisfy it. The set is checked against the module's own
    terminal-state set, so a sixth state reddens here.
    """
    ordered = (
        promotion_resolver.TICKET_PENDING,  promotion_resolver.TICKET_APPROVED,
        promotion_resolver.TICKET_REFUSED,  promotion_resolver.TICKET_SUPERSEDED,
        promotion_resolver.TICKET_STALLED,
    )
    assert set( ordered ) == { promotion_resolver.TICKET_PENDING } | set( promotion_resolver.TICKET_TERMINAL_STATES )
    flat = " ".join( description.split() )
    assert "task_promotion_status(ticket_id)`: " + " | ".join( ordered ) + "." in flat


def test_the_example_files_a_petition( description ):
    assert 'priority="P0", authority="user_direct")' in description
    assert "task_promotion_status(ticket_id=<petition.ticket_id>)" in description
