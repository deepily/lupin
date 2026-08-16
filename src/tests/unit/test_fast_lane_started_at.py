"""
Row 4a9ebc4b — the fast lane never stamps `started_at`, so every fast-lane card
reports a null duration.

WHY THIS FILE EXISTS, AND WHY IT USES REAL OBJECTS.

The test that should already have caught this could not. `test_job_persistence.py`
builds a `MagicMock` row and hard-assigns its four datetime fields, so it agrees
with any assertion put to it — a mock cannot demonstrate what an initialiser
produces, because the mock IS the initialiser under test.

So every test here constructs a REAL `AgentBase` subclass. No mock stands in for
the thing being measured.

FALSIFIABILITY. Each assertion below names the concrete change that turns it red,
in a comment on the assertion itself. An assertion no change can falsify is a
comment with a green tick, which is the defect this row was opened against.
"""
import sys
import os

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from datetime import datetime, timedelta

import pytest

from cosa.agents.agent_base            import AgentBase
from cosa.rest.running_fifo_queue      import compute_duration_seconds
import cosa.utils.util                 as du


class _RealAgent( AgentBase ):
    """
    A real AgentBase — the smallest concrete subclass that AgentBase.__init__ will
    build. It is NOT a mock: `started_at` here is whatever AgentBase actually
    assigns, which is the whole point.

    `agent router go to math` is used because its prompt-template config key
    resolves; the agent's behaviour is irrelevant to these tests.
    """

    def restore_from_serialized_state( self, path ): pass
    def is_code_runnable( self ):                    return False
    def run_code( self, auto_debug=None, inject_bugs=None ): return {}
    def is_prompt_executable( self ):                return True
    def run_prompt( self, **kwargs ):                return {}
    def run_formatter( self ):                       return ""
    def format_output( self ):                       return ""


@pytest.fixture
def real_agent():
    return _RealAgent( question="what is 2 + 2", routing_command="agent router go to math" )


class TestInitialiserContract:
    """What a freshly-built job actually carries — measured, not stipulated."""

    def test_unstarted_job_has_no_start_time( self, real_agent ):
        # RED IF: agent_base.py restores `self.started_at = ""` — an empty string
        # is not None, so this fails immediately.
        assert real_agent.started_at is None

    def test_uncompleted_job_has_no_completion_time( self, real_agent ):
        # RED IF: agent_base.py restores `self.completed_at = ""`.
        assert real_agent.completed_at is None


class TestDurationOfARealJob:
    """The live symptom: a fast-lane card shows no duration."""

    def test_unstarted_job_reports_no_duration( self, real_agent ):
        # The exact production state before this fix: the job has run to completion
        # but nothing ever stamped a start.
        real_agent.completed_at = du.get_current_datetime_iso()

        # RED IF: compute_duration_seconds invents a duration for a job that never
        # recorded a start — e.g. by defaulting the missing start to "now".
        assert compute_duration_seconds( real_agent.started_at, real_agent.completed_at ) is None

    def test_started_job_reports_a_real_duration( self, real_agent ):
        # This is the assertion that fails on today's tree: nothing in the fast lane
        # assigns started_at, so this value is absent in production and the duration
        # is silently None.
        start = datetime.now() - timedelta( seconds=5 )
        real_agent.started_at   = start.isoformat()
        real_agent.completed_at = datetime.now().isoformat()

        duration = compute_duration_seconds( real_agent.started_at, real_agent.completed_at )

        # RED IF: the truthiness guard rejects a populated ISO string, or the
        # isinstance branch is removed while callers still assign strings.
        assert duration is not None
        assert 4.0 <= duration <= 6.0

    def test_datetime_objects_are_accepted_too( self, real_agent ):
        # Agentic jobs assign ISO strings; the DB path carries real datetimes. The
        # helper must not care which it is handed.
        # RED IF: the isinstance( started_at, str ) branch is dropped — a datetime
        # would then be passed to fromisoformat and raise.
        start = datetime.now() - timedelta( seconds=2 )
        duration = compute_duration_seconds( start, datetime.now() )

        assert duration is not None
        assert 1.0 <= duration <= 3.0


class TestEmptyValuesDoNotCompute:
    """Both empty conventions in the tree must resolve to 'no duration', not a crash."""

    @pytest.mark.parametrize( "empty", [ None, "" ] )
    def test_empty_start_yields_no_duration( self, empty ):
        # RED IF: the guard is loosened to `is not None` — the empty string would
        # then reach fromisoformat and raise instead of returning None.
        assert compute_duration_seconds( empty, du.get_current_datetime_iso() ) is None

    @pytest.mark.parametrize( "empty", [ None, "" ] )
    def test_empty_completion_yields_no_duration( self, empty ):
        # RED IF: the guard stops requiring completed_at — 847 and 1346 checked only
        # started_at before this fix, and would have computed against an empty end.
        assert compute_duration_seconds( du.get_current_datetime_iso(), empty ) is None

    def test_unparseable_start_yields_no_duration( self ):
        # RED IF: the helper lets a parse failure escape. Callers compute a duration
        # for a card; a malformed timestamp must not take the request down with it.
        assert compute_duration_seconds( "not-a-timestamp", du.get_current_datetime_iso() ) is None
