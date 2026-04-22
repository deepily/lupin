"""
Unit tests for FifoQueue._notify() abstract auto-propagation.

When a job populates `self.artifacts["abstract"]`, the framework-level
job-complete notification must forward that abstract on the resulting
AsyncNotificationRequest so the primary UI task card carries the same
rich context the job's explicit progress row already carries.

Regression guard for the 2026-04-21 finding: ts-f55d172d / tfe-e830cd75
both had rich abstracts stored in job.artifacts but the user-facing
high-priority task notification had NULL in the DB's abstract column.
"""

from unittest.mock import patch, MagicMock

import pytest

from cosa.rest.fifo_queue import FifoQueue


class _MinimalJob:
    """Smallest possible job shape that FifoQueue._notify accepts."""

    def __init__( self, *, artifacts=None, user_email="ricardo.felipe.ruiz@gmail.com" ):
        self.id_hash    = "tfe-abc12345"        # matches ^[a-z]+-[a-f0-9]{8}$ job_id regex
        self.user_email = user_email
        if artifacts is not None:
            self.artifacts = artifacts
        # Attributes probed by _get_notification_job_id
        self.routing_command = "test"


def _make_queue():
    """Build a FifoQueue in the minimal state _notify needs."""
    q = FifoQueue.__new__( FifoQueue )      # bypass heavy __init__
    q.queue_name = "run"                     # lowercase, no hyphens — matches sender_id regex
    q.debug      = False
    return q


class TestNotifyAbstractAutoPropagation:

    def test_abstract_auto_read_from_job_artifacts( self ):
        """job.artifacts['abstract'] → AsyncNotificationRequest.abstract."""
        q   = _make_queue()
        job = _MinimalJob( artifacts={ "abstract": "**Test Suite Results**\n- unit PASS\n- e2e FAIL" } )

        with patch( "cosa.rest.fifo_queue.notify_user_async" ) as mock_notify:
            q._notify( "Job done", job=job )

        assert mock_notify.called, "notify_user_async must be called"
        req = mock_notify.call_args[ 0 ][ 0 ]
        assert req.abstract is not None
        assert "Test Suite Results" in req.abstract

    def test_explicit_abstract_overrides_job_artifacts( self ):
        """Explicit abstract kwarg wins over job.artifacts['abstract']."""
        q   = _make_queue()
        job = _MinimalJob( artifacts={ "abstract": "job-sourced" } )

        with patch( "cosa.rest.fifo_queue.notify_user_async" ) as mock_notify:
            q._notify( "Job done", job=job, abstract="caller-sourced" )

        req = mock_notify.call_args[ 0 ][ 0 ]
        assert req.abstract == "caller-sourced"

    def test_no_abstract_when_job_missing_artifacts_key( self ):
        """Job.artifacts without 'abstract' key → AsyncNotificationRequest.abstract is None."""
        q   = _make_queue()
        job = _MinimalJob( artifacts={ "report_path": "foo.md" } )   # no "abstract" key

        with patch( "cosa.rest.fifo_queue.notify_user_async" ) as mock_notify:
            q._notify( "Job done", job=job )

        req = mock_notify.call_args[ 0 ][ 0 ]
        assert req.abstract is None

    def test_no_abstract_when_job_has_no_artifacts_attribute( self ):
        """Job without .artifacts attribute (e.g. AgentBase, SolutionSnapshot) → abstract is None."""
        q = _make_queue()
        # _MinimalJob built without artifacts kwarg skips setting the attribute
        job = _MinimalJob()
        assert not hasattr( job, "artifacts" )

        with patch( "cosa.rest.fifo_queue.notify_user_async" ) as mock_notify:
            q._notify( "Job done", job=job )

        req = mock_notify.call_args[ 0 ][ 0 ]
        assert req.abstract is None

    def test_no_abstract_when_no_job_given( self ):
        """When job=None, abstract defaults to None."""
        q = _make_queue()

        with patch( "cosa.rest.fifo_queue.notify_user_async" ) as mock_notify:
            q._notify( "Job done", job=None, target_user="ricardo.felipe.ruiz@gmail.com" )

        req = mock_notify.call_args[ 0 ][ 0 ]
        assert req.abstract is None
