#!/usr/bin/env python3
"""
Smoke test — HeartbeatPokerJob CJ Flow ingestion readiness (task I6, smoke tier).

Validates that the job OBJECT is correctly shaped for CJ Flow ingestion:
satisfies the `QueueableJob` protocol, is an `AgenticJobBase` (so CJ Flow
dispatches it to the agentic `ThreadPoolExecutor`), and honors `scheduled_at`
/ `monopolize`. Non-destructive, no server, fast — :7999-eligible /
AI-discretionary per §TESTING VENUES.

Run: PYTHONPATH=src python -m pytest src/cosa/tests/smoke/test_heartbeat_poker_smoke.py -v
"""

from cosa.agents.heartbeat_poker_job             import HeartbeatPokerJob, RecipientSpec
from cosa.agents.agentic_job_base                import AgenticJobBase
from cosa.rest.queue_protocol                    import is_queueable_job


class _NullGateway:
    """Minimal CommonsGateway — the smoke tier never runs the poke loop."""
    def send_to( self, recipient, body ): ...
    def last_post_ts( self, recipient ): return None
    def read_since( self, topic, since_iso ): return []


def _make_job( scheduled_at=None, monopolize=False ):
    return HeartbeatPokerJob(
        recipients               = [ RecipientSpec( identifier="tiberius", identifier_type="persona", role="watcher" ) ],
        cadence_seconds          = 180,
        termination_topic        = "impl-done",
        termination_signal_kinds = [ "implementation_done", "implementation_blocked" ],
        workstream_id            = "smoke-ws",
        commons                  = _NullGateway(),
        scheduled_at             = scheduled_at,
        monopolize               = monopolize,
        user_id                  = "u",
        user_email               = "u@test.com",
        session_id               = "s",
    )


def test_job_constructs_for_cj_flow():
    job = _make_job()
    assert job.job_type == "heartbeat_poker"
    assert job.id_hash.startswith( "hp-" )


def test_job_is_agentic_job_base():
    # CJ Flow dispatches AgenticJobBase subclasses to the agentic ThreadPoolExecutor.
    assert isinstance( _make_job(), AgenticJobBase )


def test_job_satisfies_queueable_protocol():
    assert is_queueable_job( _make_job() )


def test_scheduled_at_flows_through():
    job = _make_job( scheduled_at="2026-05-23T02:30:00-04:00" )
    assert job.scheduled_at == "2026-05-23T02:30:00-04:00"


def test_scheduled_at_defaults_none_for_immediate():
    assert _make_job().scheduled_at is None


def test_monopolize_flows_through():
    assert _make_job( monopolize=True ).monopolize is True


def test_job_is_not_cacheable():
    job = _make_job()
    assert job.is_cacheable is False
    assert job.is_cache_hit is False


def test_last_question_asked_renders_for_queue_ui():
    assert "smoke-ws" in _make_job().last_question_asked
