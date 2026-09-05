"""
Row 84276b28 — the inbound gist path this fleet structurally cannot exercise.

THE GAP THIS CLOSES. `cc_notification_listener.py:594` returns before BOTH
`_inject_via_tmux` (:601) and `_send_gist_response` (:602) whenever a notification
carries `direction == "ai_to_ai"`. Every peer DM on this fleet sets that, so no seat
can drive the gist path by messaging another seat — the branch is live in production
and unreachable from inside the fleet. That is how a two-day outage sat in it.

=== THE FIXTURES ARE CAPTURED, NOT HAND-BUILT (María 🌸's instruction) ===
`fixtures/captured_user_initiated_notifications.json` holds THREE REAL ROWS pulled
from `lupin_db_dev.notifications` on 2026-09-05 — all 28 columns, one per direction,
newest of each. A hand-authored fixture is written from the parser's side of the
boundary and agrees with the author's model of the producer, which is the half that is
wrong when there is a bug.

⚠️ THREE FIELDS ARE REDACTED AND THE REDACTION IS PROVABLY INERT HERE.
`sender_id`, `recipient_id` and `message` were replaced — the real rows carry a live
person's address and their own words, which do not belong in a tracked fixture.
Audited: the code under test reads exactly SIX keys —

    direction · job_id · message · notification_type · title · type

(`grep -o 'notification\\.get( "..."' over :529-602`, and `_deliver_peer_dm` reads
none). `sender_id` and `recipient_id` are NEVER read, so redacting them cannot change
a result. `message` is read for truthiness only and then handed to `_inject_via_tmux`,
which is stubbed here — so its TEXT is inert while its non-emptiness is preserved.
**`job_id` is NOT redacted**: the listener is constructed with the captured row's own
`job_id` in `accepted_ids`, so the filter runs against the real value.

=== WHY THE GATE IS ASSERTED NEGATIVELY, WHICH IS THE POINT OF THIS FILE ===
The gate is not an allow-list of named shapes. It is `!= "ai_to_ai"`, so EVERY other
direction reaches the gist — including `ai_to_human`, which is the DEFAULT
(`postgres_models.py:577` default AND server_default, `notification_fifo_queue.py:21`,
`routers/notifications.py:429`), and including a legacy row with no `direction` key.

Measured 2026-09-05, database NAMED (`docker exec lupin-postgres psql -d lupin_db_dev`),
over the rows that actually reach this branch (`type = 'user_initiated_message'`):

    direction    | rows   | first      | last        | fixture
    -------------|--------|------------|-------------|------------------
    ai_to_ai     | 39,703 | 2026-06-15 | 2026-09-05  | CAPTURED
    ai_to_human  |  2,985 | 2026-03-04 | 2026-08-26  | CAPTURED
    human_to_ai  |  2,229 | 2026-06-16 | 2026-09-05  | CAPTURED
    <NULL>       |      0 |            |             | synthesised — see below

Positive control, same scan, whole table: ai_to_human 414,647 / ai_to_ai 39,999 /
human_to_ai 2,229 — the instrument reaches the population, so the zero is a finding
rather than a silence.

⚠️ TWO CASES ARE SYNTHESISED AND LABELLED, BECAUSE THE POPULATION IS EMPTY. There has
never been a row with no `direction` key, and never one with an unrecognised value, so
there is nothing to capture. They are derived from a captured row by deleting or
altering that single field, so every other byte still comes from production.

⇒ A guard that exercised only `human_to_ai` would stay GREEN while somebody narrowed
the gate to `== "human_to_ai"`, silently killing the default-direction and legacy
paths. The negative shape is the invariant, not the shapes anybody happened to name.
"""
import asyncio, copy, json, pathlib

import pytest

from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener


FIXTURE = pathlib.Path( __file__ ).parent / "fixtures" / "captured_user_initiated_notifications.json"
CAPTURED = { row[ "direction" ]: row for row in json.loads( FIXTURE.read_text() ) }


class _Spy( CCNotificationListener ):
    """The real listener with only its three OUTBOUND effects recorded. Everything
    above them — the event-type filter, action routing, the type filter, the job_id
    filter and the direction branch itself — runs unmodified."""

    def __init__( self, accepted ):
        super().__init__(
            email           = "test@example.com",
            password        = "unused-no-connection-is-made",
            session_id_hash = "deadbeef",
            accepted_ids    = { accepted },
        )
        self.calls = []

    def _deliver_peer_dm( self, notification ):            self.calls.append( "peer_dm" )
    def _inject_via_tmux( self, message_text, wrap=True ): self.calls.append( "tmux" )
    def _send_gist_response( self, notification ):         self.calls.append( "gist" )
    def _log( self, *a, **kw ):                            pass


def _drive( row ):
    """Replay a captured row through the REAL handler, inside the REAL envelope that
    notification_fifo_queue.py:491 builds."""
    spy   = _Spy( row[ "job_id" ] )
    event = { "queue_name": "notification", "value": 1, "notification": row }
    asyncio.run( spy._handle_event( "notification_queue_update", event ) )
    return spy.calls


# --------------------------------------------------- the gate, CAPTURED rows --
@pytest.mark.parametrize( "direction", [ "human_to_ai", "ai_to_human" ] )
def test_a_captured_non_peer_notification_reaches_the_gist( direction ):
    """Replayed verbatim from production. `ai_to_human` is the case the row's own
    framing missed, and it outnumbers `human_to_ai` at this branch 2,985 to 2,229."""
    assert _drive( copy.deepcopy( CAPTURED[ direction ] ) ) == [ "tmux", "gist" ]


def test_a_captured_peer_dm_returns_before_the_gist_and_before_the_tmux_injection():
    """María's control. Without it the test above is satisfied by a listener that
    simply always gists, and the file would measure nothing about direction."""
    assert _drive( copy.deepcopy( CAPTURED[ "ai_to_ai" ] ) ) == [ "peer_dm" ]


# ------------------------------------ the gate, SYNTHESISED where none exist --
def test_a_legacy_row_with_no_direction_key_still_reaches_the_gist():
    """SYNTHESISED — zero such rows have ever existed, so there is nothing to capture.
    Derived from a captured row by deleting one key; every other byte is production's.
    The code comment at :591-593 names this shape explicitly, so it is a live contract
    even though nothing has produced it."""
    row = copy.deepcopy( CAPTURED[ "human_to_ai" ] )
    del row[ "direction" ]
    assert _drive( row ) == [ "tmux", "gist" ]


def test_an_unrecognised_direction_value_still_reaches_the_gist():
    """SYNTHESISED, same derivation. This is what makes the assertion NEGATIVE rather
    than an allow-list: the gate admits anything that is not the literal 'ai_to_ai'."""
    row = copy.deepcopy( CAPTURED[ "human_to_ai" ] )
    row[ "direction" ] = "some_future_direction"
    assert _drive( row ) == [ "tmux", "gist" ]


# ------------------------------------------------- the filters ABOVE the gate -
def test_a_non_user_initiated_type_never_reaches_the_gate_at_all():
    """The type filter sits ABOVE the direction branch, so it is a SECOND SUFFICIENT
    CAUSE for 'no gist'. Pinned so a regression there cannot be misread as a gate change."""
    row = copy.deepcopy( CAPTURED[ "human_to_ai" ] )
    row[ "type" ] = "task"
    assert _drive( row ) == []


def test_a_foreign_job_id_never_reaches_the_gate_at_all():
    """The other sufficient cause. Here the listener accepts a hash the row does not carry."""
    row = copy.deepcopy( CAPTURED[ "human_to_ai" ] )
    spy = _Spy( "f0f0f0f0" )
    asyncio.run( spy._handle_event( "notification_queue_update",
                                    { "queue_name": "notification", "value": 1, "notification": row } ) )
    assert spy.calls == []


def test_the_wrong_event_type_is_ignored():
    row = copy.deepcopy( CAPTURED[ "human_to_ai" ] )
    spy = _Spy( row[ "job_id" ] )
    asyncio.run( spy._handle_event( "some_other_event",
                                    { "queue_name": "notification", "value": 1, "notification": row } ) )
    assert spy.calls == []


# --------------------------------------------------- controls on the FIXTURE --
def test_the_captured_rows_are_real_and_carry_the_fields_the_gate_reads():
    """A POSITIVE CONTROL ON THE FIXTURE ITSELF. If the capture were malformed — a
    missing `direction`, a wrong `type` — every case above would collapse onto the
    legacy shape and the file would go green while measuring one case five times."""
    assert set( CAPTURED ) == { "human_to_ai", "ai_to_human", "ai_to_ai" }
    for direction, row in CAPTURED.items():
        assert row[ "direction" ] == direction
        assert row[ "type" ]      == "user_initiated_message"
        assert row[ "job_id" ]
        assert row[ "message" ]
        assert len( row ) >= 28, "captured rows must keep the full column set"


def test_the_redaction_is_recorded_in_the_fixture_itself():
    """The redaction must be discoverable from the artifact, not only from this
    docstring — a reader who opens the JSON has to be able to see what was changed."""
    for row in CAPTURED.values():
        assert row[ "_REDACTED" ] == [ "sender_id", "recipient_id", "message" ]
        assert row[ "sender_id" ] == "<redacted-sender>"
        assert "lupin_db_dev" in row[ "_CAPTURED_FROM" ]
