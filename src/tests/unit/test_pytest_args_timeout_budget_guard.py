"""
The per-test-timeout / suite-budget contradiction guard (row 64677f38).

WHAT THIS PROTECTS: attempt 11 of the v2 paired eval carried `--timeout 5400` in its
submit request. pytest-timeout is PER TEST, so it capped at 90 minutes a test the
operator had deliberately granted 8.3 hours (SUITE_TIMEOUTS_SECONDS["integration"] was
raised to 30000s for exactly that run). ~4.8 hours of live traffic died at the cap.

🔴 THE REASON THE EXISTING GUARD COULD NOT SEE IT: test_paired_n_fits_integration_timeout.py
compares the corpus size against the SUITE budget and PASSES — both numbers live in files
it can read. The 90-minute cap was never in a file; it was typed into a request. So the
first test below supplies the ACTUAL KILLING VALUE and proves the new guard goes red on it.
A guard proven only on the happy path is a guard nobody has tested.
"""

import pytest

from cosa.rest.pytest_args_policy import (
    PytestArgsRejected,
    find_per_test_timeout,
    validate_timeout_against_suite_budget,
)

# The real numbers from the night this cost 4.8 hours.
_BUDGETS   = { "integration": 30000, "unit": 300 }
_DEFAULT   = 600
_ATTEMPT11 = [ "-m", "paired_eval_live", "src/tests/integration/test_v2_paired_live.py",
               "-v", "--timeout", "5400" ]


def _validate( tokens, test_types ):
    return validate_timeout_against_suite_budget( tokens, test_types, _BUDGETS, _DEFAULT )


# ---------------------------------------------------------------------------
# The killing value itself
# ---------------------------------------------------------------------------
def test_attempt_elevens_exact_submit_is_refused():
    """RED-ON-THE-REAL-DEFECT. This is the submit that died, verbatim."""
    with pytest.raises( PytestArgsRejected ) as caught:
        _validate( _ATTEMPT11, "integration" )
    message = str( caught.value )
    assert "5400" in message and "30000" in message      # names BOTH numbers
    assert "integration" in message                       # and the suite they clash on
    assert "drop --timeout" in message                    # and a way forward


def test_the_refusal_names_a_remedy_rather_than_just_saying_no():
    """A refusal that does not say what to do instead gets worked around, not obeyed."""
    with pytest.raises( PytestArgsRejected ) as caught:
        _validate( _ATTEMPT11, "integration" )
    message = str( caught.value )
    assert "raise it to at least 30000" in message
    assert "lower the 'integration' suite budget" in message


# ---------------------------------------------------------------------------
# What it must NOT refuse — a guard that cries wolf gets disabled
# ---------------------------------------------------------------------------
def test_a_timeout_equal_to_the_budget_passes():
    """Equal is not a contradiction: the test may use exactly what the suite was granted."""
    assert _validate( [ "--timeout", "30000" ], "integration" ) is None


def test_a_timeout_longer_than_the_budget_passes():
    """The suite budget stops it first. Harmless, so it is not this guard's business."""
    assert _validate( [ "--timeout", "99999" ], "integration" ) is None


def test_no_timeout_flag_passes():
    """The overwhelmingly common submit. Must cost nothing."""
    assert _validate( [ "-m", "paired_eval_live", "-v" ], "integration" ) is None


def test_empty_args_pass():
    assert _validate( [], "integration" ) is None


# ---------------------------------------------------------------------------
# Both spellings, or half the hazard walks through
# ---------------------------------------------------------------------------
def test_the_equals_spelling_is_caught_too():
    """`--timeout=5400` reaches pytest identically; a guard that reads only the
    two-token form would be trivially bypassed by a submitter who never knew it existed."""
    with pytest.raises( PytestArgsRejected ):
        _validate( [ "--timeout=5400" ], "integration" )


def test_find_per_test_timeout_reads_both_spellings():
    assert find_per_test_timeout( [ "--timeout", "90" ] )  == 90.0
    assert find_per_test_timeout( [ "--timeout=90" ] )     == 90.0
    assert find_per_test_timeout( [ "-v" ] )               is None


def test_a_trailing_timeout_with_no_value_is_not_this_guards_problem():
    """The allowlist owns well-formedness. Two guards policing one thing drift apart."""
    assert find_per_test_timeout( [ "--timeout" ] ) is None
    assert _validate( [ "--timeout" ], "integration" ) is None


def test_a_non_numeric_timeout_is_not_this_guards_problem():
    assert find_per_test_timeout( [ "--timeout", "soon" ] ) is None
    assert _validate( [ "--timeout", "soon" ], "integration" ) is None


# ---------------------------------------------------------------------------
# Multi-suite + shape of test_types
# ---------------------------------------------------------------------------
def test_it_refuses_on_ANY_suite_the_cap_is_short_for():
    """A submit naming two suites runs under both budgets; the longest one is the
    one the cap silently truncates, and it is not always listed first."""
    with pytest.raises( PytestArgsRejected ) as caught:
        _validate( [ "--timeout", "400" ], "unit,integration" )
    assert "integration" in str( caught.value )


def test_a_cap_above_every_named_suites_budget_passes():
    assert _validate( [ "--timeout", "30000" ], "unit,integration" ) is None


def test_test_types_may_be_a_list_as_well_as_a_comma_string():
    """The router passes the raw comma string; TestSuiteJob passes its parsed list.
    One guard serves both call sites, so it must accept both shapes or the
    authoritative copy silently never fires."""
    with pytest.raises( PytestArgsRejected ):
        _validate( _ATTEMPT11, [ "integration" ] )


def test_an_unknown_suite_falls_back_to_the_default_budget():
    with pytest.raises( PytestArgsRejected ) as caught:
        _validate( [ "--timeout", "60" ], "some_new_suite" )
    assert "600" in str( caught.value )


def test_empty_test_types_cannot_contradict_anything():
    assert _validate( _ATTEMPT11, "" ) is None
    assert _validate( _ATTEMPT11, [] ) is None
    assert _validate( _ATTEMPT11, None ) is None


def test_whitespace_around_suite_names_is_tolerated():
    """`"integration, e2e"` is a shape a human types."""
    with pytest.raises( PytestArgsRejected ):
        _validate( _ATTEMPT11, " integration , unit " )


# ═══════════════════════════════════════════════════════════════════════════════
# THE WIRING. A guard function that nothing calls is not a control.
# ═══════════════════════════════════════════════════════════════════════════════
#
# Both call sites are tested because they exist for different reasons and can
# drift apart independently: the constructor is the AUTHORITATIVE gate (every
# execution path runs through it, including persistence rehydration and
# side-channel resubmits), and the router is the DOOR (so a submitter gets a 400
# naming both numbers instead of finding out four hours in).

def test_the_job_constructor_refuses_attempt_elevens_submit():
    """The authoritative gate. RED if the constructor call is ever removed."""
    from cosa.agents.test_suite.job import TestSuiteJob

    with pytest.raises( PytestArgsRejected ) as caught:
        TestSuiteJob(
            test_types  = [ "integration" ],
            pytest_args = _ATTEMPT11,
            user_id     = "user-123",
            user_email  = "test@test.com",
            session_id  = "wise-penguin",
        )
    assert "30000" in str( caught.value )


def test_the_job_constructor_still_builds_a_normal_paired_submit():
    """The negative control: attempt 12's actual args — same run, no --timeout — build fine.
    Without this, a guard that refused everything would look identical to a guard that works."""
    from cosa.agents.test_suite.job import TestSuiteJob

    job = TestSuiteJob(
        test_types  = [ "integration" ],
        pytest_args = [ "-m", "paired_eval_live",
                        "src/tests/integration/test_v2_paired_live.py", "-v" ],
        user_id     = "user-123",
        user_email  = "test@test.com",
        session_id  = "wise-penguin",
    )
    assert job.pytest_args[ -1 ] == "-v"


def test_the_constructors_budgets_are_the_REAL_ones_not_a_fixture():
    """The guard is only worth anything if it reads the budgets the runner actually
    enforces. RED if the constructor is ever wired to a different or stale map."""
    from cosa.agents.test_suite.job import SUITE_TIMEOUTS_SECONDS, SUITE_TIMEOUT_DEFAULT_SECONDS

    assert SUITE_TIMEOUTS_SECONDS[ "integration" ] >= 30000   # raised 08-17 for the n=60 paired run
    assert SUITE_TIMEOUT_DEFAULT_SECONDS > 0


def test_PytestArgsRejected_is_a_ValueError_so_the_router_renders_it_as_a_400():
    """The router's existing `except ValueError` is what turns this into a clean 400.
    If the exception base ever changes, a refusal becomes a 500 and reads as a server
    bug rather than as the submitter's contradiction."""
    assert issubclass( PytestArgsRejected, ValueError )


def test_the_submit_endpoint_returns_400_naming_both_numbers():
    """THE DOOR, end to end through the real endpoint function.

    This is the surface attempt 11 actually went through, and the one a human sees. A
    contradiction must come back as a 400 the submitter can read and act on — not a 500,
    and above all not a queued job that dies four hours later.
    """
    import asyncio
    from fastapi import HTTPException

    from cosa.rest.routers.test_suite import submit_test_suite, TestSuiteSubmitRequest

    class _NeverReachedQueue:
        """If the guard works, nothing here is ever called."""
        def push( self, job ): raise AssertionError( "a contradictory submit reached the queue" )
        def size( self ):      raise AssertionError( "a contradictory submit reached the queue" )

    request = TestSuiteSubmitRequest(
        test_types  = "integration",
        pytest_args = "-m paired_eval_live src/tests/integration/test_v2_paired_live.py -v --timeout 5400",
    )
    with pytest.raises( HTTPException ) as caught:
        asyncio.run( submit_test_suite(
            request_body = request,
            current_user = { "uid": "user-123", "email": "test@test.com" },
            todo_queue   = _NeverReachedQueue(),
        ) )
    assert caught.value.status_code == 400
    assert "5400"  in caught.value.detail
    assert "30000" in caught.value.detail
