#!/usr/bin/env python3
"""
Unit tests — `agentic_job_factory` heartbeat_poker wiring.

Covers the `agent router go to heartbeat poker` branch added to
`create_agentic_job()`: argument parsing (recipients → `RecipientSpec` list,
`termination_signal_kinds` list/CSV, the `_parse_optional_int` defaults) and
`HeartbeatPokerJob` construction.

`LupinCommonsGateway.from_environment` is patched throughout — the factory
branch's only IO-boundary call — so these tests do zero CommonsStore/network.

Run: PYTHONPATH=src python -m pytest src/cosa/tests/unit/rest/test_agentic_job_factory_heartbeat.py -v
"""

from unittest.mock import patch

from cosa.rest.agentic_job_factory               import create_agentic_job
from cosa.agents.heartbeat_poker_job             import HeartbeatPokerJob, RecipientSpec
from cosa.agents.heartbeat_poker_commons_gateway import LupinCommonsGateway


class _FakeGateway:
    """Stand-in returned by the patched `from_environment` — never exercised here."""
    def send_to( self, recipient, body ): ...
    def last_post_ts( self, recipient ): return None
    def read_since( self, topic, since_iso ): return []


_HB_COMMAND = "agent router go to heartbeat poker"

_BASE_ARGS = {
    "recipients": [
        { "identifier": "tiberius", "identifier_type": "persona", "role": "watcher" },
        { "identifier": "maria",    "identifier_type": "persona", "role": "observer" },
    ],
    "cadence_seconds":          120,
    "termination_topic":        "impl-done",
    "termination_signal_kinds": [ "implementation_done", "implementation_blocked" ],
    "workstream_id":            "impl-99",
}


def _create( args ):
    """Run the factory for the heartbeat command with `from_environment` patched."""
    with patch.object( LupinCommonsGateway, "from_environment", return_value=_FakeGateway() ):
        return create_agentic_job(
            command    = _HB_COMMAND,
            args_dict  = args,
            user_id    = "u",
            user_email = "u@test.com",
            session_id = "s",
        )


def test_factory_builds_heartbeat_poker_job():
    job = _create( _BASE_ARGS )
    assert isinstance( job, HeartbeatPokerJob )
    assert job.job_type == "heartbeat_poker"


def test_factory_parses_recipients_into_recipientspec_list():
    job = _create( _BASE_ARGS )
    assert len( job.recipients ) == 2
    assert all( isinstance( r, RecipientSpec ) for r in job.recipients )
    assert ( job.recipients[ 0 ].identifier, job.recipients[ 0 ].role ) == ( "tiberius", "watcher" )
    assert job.recipients[ 1 ].role == "observer"


def test_factory_recipient_identifier_type_defaults_to_persona():
    args = dict( _BASE_ARGS, recipients=[ { "identifier": "x", "role": "watcher" } ] )
    assert _create( args ).recipients[ 0 ].identifier_type == "persona"


def test_factory_passes_core_config():
    job = _create( _BASE_ARGS )
    assert job.cadence_seconds == 120
    assert job.termination_topic == "impl-done"
    assert job.workstream_id == "impl-99"
    assert job.termination_signal_kinds == [ "implementation_done", "implementation_blocked" ]


def test_factory_termination_kinds_from_csv_string():
    args = dict( _BASE_ARGS, termination_signal_kinds="implementation_done, implementation_blocked" )
    assert _create( args ).termination_signal_kinds == [ "implementation_done", "implementation_blocked" ]


def test_factory_applies_defaults_when_args_omitted():
    args = {
        "recipients":               [ { "identifier": "t", "identifier_type": "persona", "role": "watcher" } ],
        "termination_topic":        "impl-done",
        "termination_signal_kinds": [ "implementation_done" ],
        "workstream_id":            "w",
    }
    job = _create( args )
    assert job.cadence_seconds == 180             # _parse_optional_int → None → default
    assert job.deadman_consecutive_pokes == 3
    assert job.max_duration_seconds == 43_200


def test_factory_passes_explicit_deadman_and_max_duration():
    args = dict( _BASE_ARGS, deadman_consecutive_pokes=5, max_duration_seconds=3600 )
    job  = _create( args )
    assert job.deadman_consecutive_pokes == 5
    assert job.max_duration_seconds == 3600


def test_factory_injects_commons_gateway():
    assert isinstance( _create( _BASE_ARGS )._commons, _FakeGateway )


def test_factory_sets_routing_command_and_original_args():
    job = _create( _BASE_ARGS )
    assert job.routing_command == _HB_COMMAND
    assert job.original_args[ "workstream_id" ] == "impl-99"


def test_factory_passes_scheduled_at_and_monopolize():
    args = dict( _BASE_ARGS, scheduled_at="2026-05-23T02:30:00-04:00", monopolize="yes" )
    job  = _create( args )
    assert job.scheduled_at == "2026-05-23T02:30:00-04:00"
    assert job.monopolize is True


def test_factory_unknown_command_returns_none():
    # Sanity: the factory's fall-through is intact alongside the new branch.
    assert create_agentic_job( "agent router go to nowhere", {}, "u", "u@t.com", "s" ) is None
