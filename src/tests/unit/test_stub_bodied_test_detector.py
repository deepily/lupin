#!/usr/bin/env python3
"""
`find_stub_bodied_tests` — the detector for vacuity shape 5 (row ac37dc5a).

THE DEFECT IT HUNTS. A test whose whole body is a docstring is collected, runs,
passes, and adds a green result to the number a human reads before merging. Eight
sat in the integration tier at HEAD — the FINAL merge gate — each carrying a
numbered description of the flow it would exercise, then `pass`. A reviewer
scanning names saw timeout handling, duplicate-response prevention and offline
defaults covered. None of it was.

⚠️ NOTHING ELSE LOOKS FOR THIS. The gate-reachability census answers "does any
runner reach this file"; no control answered "does this test assert anything".

Venue: :7999-eligible. Pure AST reads over literal fixtures; no server, no docker.
"""
import ast
import textwrap

import pytest

from cosa.repo.gate_reachability import _body_is_vacuous


def _fn( src ):
    """Parse one function definition out of a source snippet."""
    tree = ast.parse( textwrap.dedent( src ) )
    return next( n for n in ast.walk( tree )
                 if isinstance( n, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) )


# ── the shapes that ARE vacuous ──────────────────────────────────────────────

@pytest.mark.parametrize( "body,label", [
    ( "    pass",                          "bare pass" ),
    ( "    ...",                           "ellipsis" ),
    ( "    assert True",                   "assert True" ),
    ( "    raise NotImplementedError",     "raise bare" ),
    ( "    raise NotImplementedError()",   "raise called" ),
] )
def test_a_body_that_asserts_nothing_is_vacuous( body, label ):
    assert _body_is_vacuous( _fn( f"def test_x():\n{body}\n" ) ), label


def test_a_docstring_plus_pass_is_vacuous():
    """The exact integration-tier shape: a detailed description, then nothing.
    Describing a test is not testing it."""
    assert _body_is_vacuous( _fn( '''
        def test_timeout_scenario():
            """
            Flow:
            1. CLI sends the notification
            2. Server times out and returns the default
            """
            pass
    ''' ) )


def test_assert_True_is_vacuous_even_when_a_comment_excuses_it():
    """Both real cases say in a comment that the check lives elsewhere — in a SQL
    WHERE clause, in a policy. That is honest, and it still passes unconditionally
    and still reports green. A documented placeholder is not a check."""
    assert _body_is_vacuous( _fn( '''
        def test_running_always_interrupted():
            assert True  # Structural assertion — the SQL handles this
    ''' ) )


# ── the shapes that are NOT vacuous — the arms that must be able to fail ─────

def test_a_real_assertion_is_not_vacuous():
    assert not _body_is_vacuous( _fn( "def test_x():\n    assert 1 == 2\n" ) )


def test_assert_False_is_not_vacuous():
    """Direction matters. `assert True` can never fail; `assert False` always does.
    A detector that keyed on 'is this an assert on a constant' would swallow both
    and call a permanently-red test vacuous."""
    assert not _body_is_vacuous( _fn( "def test_x():\n    assert False\n" ) )


def test_a_docstring_plus_a_real_call_is_not_vacuous():
    assert not _body_is_vacuous( _fn( '''
        def test_x():
            """Described AND written."""
            result = compute()
            assert result == 3
    ''' ) )


def test_raising_something_other_than_NotImplementedError_is_not_vacuous():
    """`raise NotImplementedError` marks unwritten work; any other raise is the
    test doing something."""
    assert not _body_is_vacuous( _fn( "def test_x():\n    raise ValueError( 'boom' )\n" ) )


def test_a_trailing_pass_after_real_work_is_not_vacuous():
    """A `pass` is only damning when it is the WHOLE body."""
    assert not _body_is_vacuous( _fn( "def test_x():\n    assert 1 == 1\n    pass\n" ) )


def test_an_async_test_is_read_the_same_way():
    assert _body_is_vacuous( _fn( "async def test_x():\n    pass\n" ) )
    assert not _body_is_vacuous( _fn( "async def test_x():\n    assert await f()\n" ) )


def test_a_docstring_alone_is_vacuous_but_a_bare_string_expression_is_not():
    """A docstring is dropped because it is documentation. A string sitting later in
    the body is a statement the author wrote on purpose, and the detector must not
    quietly treat every string as prose."""
    assert _body_is_vacuous( _fn( 'def test_x():\n    """doc"""\n' ) )
    assert not _body_is_vacuous( _fn( 'def test_x():\n    """doc"""\n    "not a docstring"\n' ) )
