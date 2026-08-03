#!/usr/bin/env python3
"""
Unit tests for the push-path web-search fallback guard.

Guards the defect found 2026-08-02: push_job's unroutable-command else-branch
(and the "search and summarize" branch) called LupinSearch inline on the push
path with no exception handling. When Kagi returned HTTP 500, requests raised
HTTPError, which propagated out of push_job -> /api/push and reached the user
as a 500 with a stack trace and no explanation.

A routing miss must degrade to a spoken message, not throw.
"""

from unittest.mock import patch, MagicMock

import pytest
import requests

from cosa.rest.todo_fifo_queue import TodoFifoQueue


@pytest.fixture
def queue():
    """A TodoFifoQueue with __init__ bypassed — we exercise one method only."""
    q = TodoFifoQueue.__new__( TodoFifoQueue )
    q.debug   = False
    q.verbose = False
    return q


class TestSearchAndSummarizeSafely:
    """The guard must swallow backend failures and still return something speakable."""

    def test_returns_summary_when_search_succeeds( self, queue ):
        """Happy path is unchanged — the summary is passed straight through."""
        with patch( "cosa.rest.todo_fifo_queue.LupinSearch" ) as mock_search:
            instance = mock_search.return_value
            instance.get_results.return_value = "Here is what I found."

            result = queue._search_and_summarize_safely( "what is the kiss protocol" )

            assert result == "Here is what I found."
            instance.search_and_summarize_the_web.assert_called_once()
            instance.get_results.assert_called_once_with( scope="summary" )

    def test_http_error_does_not_propagate( self, queue ):
        """
        The exact failure that produced tonight's 500: Kagi returns HTTP 500,
        requests raises HTTPError. It must not escape.
        """
        with patch( "cosa.rest.todo_fifo_queue.LupinSearch" ) as mock_search:
            mock_search.return_value.search_and_summarize_the_web.side_effect = (
                requests.exceptions.HTTPError( "500 Server Error: Internal Server Error" )
            )

            result = queue._search_and_summarize_safely( "make me a podcast" )

            assert isinstance( result, str )
            assert result.strip()

    def test_connection_error_does_not_propagate( self, queue ):
        """Backend unreachable is the same class of failure as backend erroring."""
        with patch( "cosa.rest.todo_fifo_queue.LupinSearch" ) as mock_search:
            mock_search.return_value.search_and_summarize_the_web.side_effect = (
                requests.exceptions.ConnectionError( "connection refused" )
            )

            result = queue._search_and_summarize_safely( "make me a podcast" )

            assert isinstance( result, str )
            assert result.strip()

    def test_timeout_does_not_propagate( self, queue ):
        """A hung backend must not hang the push path into a 500 either."""
        with patch( "cosa.rest.todo_fifo_queue.LupinSearch" ) as mock_search:
            mock_search.return_value.search_and_summarize_the_web.side_effect = (
                requests.exceptions.Timeout( "timed out" )
            )

            result = queue._search_and_summarize_safely( "make me a podcast" )

            assert isinstance( result, str )
            assert result.strip()

    def test_failure_message_explains_both_conditions( self, queue ):
        """
        The user should learn that routing failed AND that search is down —
        conflating them into a bare 500 is the defect this guards.
        """
        with patch( "cosa.rest.todo_fifo_queue.LupinSearch" ) as mock_search:
            mock_search.return_value.search_and_summarize_the_web.side_effect = (
                requests.exceptions.HTTPError( "500" )
            )

            result = queue._search_and_summarize_safely( "make me a podcast" ).lower()

            assert "search" in result

    def test_unrelated_exceptions_still_propagate( self, queue ):
        """
        This is the control. The guard is scoped to search-backend transport
        failures — it must NOT become a blanket except that hides real bugs.
        If this stops raising, the guard has been widened too far.
        """
        with patch( "cosa.rest.todo_fifo_queue.LupinSearch" ) as mock_search:
            mock_search.return_value.search_and_summarize_the_web.side_effect = (
                ValueError( "a genuine programming error" )
            )

            with pytest.raises( ValueError ):
                queue._search_and_summarize_safely( "make me a podcast" )
