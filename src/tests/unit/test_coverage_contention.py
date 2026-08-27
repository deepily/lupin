"""
Row `e2099400`, decision 4 — the checker that refuses a coverage run on a contended box.

WHAT IS BEING PROTECTED. Measured 2026-08-26: a `pytest --cov` tier run sharing the box with
a second suite reported 82% / 1320 missing statements; the identical tree run alone minutes
later reported 89% / 853. Same command, same isolated COVERAGE_FILE, identical pass/skip/
xfail counts, no warning of any kind. coverage.py has no "I could not measure that" state,
so it prints a number under exactly the conditions where the number means nothing — and it
reads LOW, so the reflex is to go write tests for a hole that is not there.

⚠️ THE HARD PART IS NOT DETECTING PYTEST — IT IS NOT DETECTING YOURSELF. The runner script
that invokes this check is frequently named `run-pytest-direct.sh`, and the process running
these very tests IS a pytest. A checker that matched the bare word would have every coverage
run in the tree refuse itself, which is a guard that gets deleted within a day. Two
mechanisms carry that: invocation-shaped patterns (so a path merely CONTAINING the word does
not match) and an ancestor walk (so our own process tree is excluded). Both have negative
tests below; they are the point of this file, not padding.

⚠️ AND UNKNOWN IS NOT CLEAR. If the process table cannot be read, the checker exits 2, not 0.
"Reports OK under the condition where it cannot function" is the defect class this module
exists to close — a checker that softened its own blindness into a pass would be a member of
it. test_unreadable_process_table_is_unknown_not_clear is the pin.

Venue: :7999-eligible. Pure in-process calls against injected process tables plus a few
reads of this box's real /proc; no server, no state mutation, no network, milliseconds.
"""

import os

import pytest

from cosa.utils import coverage_contention as cc


# ── looks_like_pytest: an INVOCATION, not a mention ──────────────────────────

@pytest.mark.parametrize( "cmdline", [
    "/home/rruiz/.venv/bin/pytest src/tests/unit/",
    "/opt/venv/bin/pytest -q",
    "python3 -m pytest src/cosa/tests/",
    "/usr/bin/python -m pytest",
    "/usr/bin/pytest",                       # a path, no trailing args
    "pytest -q",                             # PATH-resolved, first on the line
    "env PY_COLORS=1 /opt/venv/bin/pytest --cov=cosa",  # the wrapper's own env-prefixed shape
] )
def test_invocation_shaped_command_lines_are_recognised( cmdline ):
    assert cc.looks_like_pytest( cmdline ) is True, f"missed a real invocation: {cmdline}"


@pytest.mark.parametrize( "cmdline", [
    "",                                                          # the empty-cmdline branch
    "/bin/bash /mnt/lupin/src/tests/run-pytest-direct.sh -q",     # a runner NAMED for pytest
    "vim /mnt/lupin/src/tests/unit/test_coverage_contention.py",  # an editor buffer
    "grep -rn pytest src/",                                       # a mention on a command line
    "/usr/bin/pytest-watch",                                      # a different program
] )
def test_mere_mentions_of_pytest_are_not_invocations( cmdline ):
    """
    ⚠️ THIS IS THE TEST THAT KEEPS THE GUARD INSTALLED. Every one of these strings is
    something that really appears in this repo's process table during a normal run. A
    checker that matched the bare word would refuse every coverage run in the tree.
    """
    assert cc.looks_like_pytest( cmdline ) is False, f"false positive on: {cmdline}"


# ── The wait-for-the-box loop is NOT a running suite ─────────────────────────
#
# WHAT HAPPENED, 2026-08-26 ~20:06 EDT. Three sessions wanted the box. Two were sitting in
# a shell loop polling `pgrep` until it went quiet; the third asked the runner for a
# coverage run and was REFUSED with "another test suite is already running on this box" and
# handed the waiter's pid as the culprit. Nothing was running. The waiters were waiting for
# each other, and the guard was the reason the queue could never drain.
#
# THE MECHANISM is one character wide. `cmdline.split()` chops the wait loop's script text
# on whitespace, and one of the pieces is the QUOTED SEARCH PATTERN `"bin/pytest` — whose
# basename is exactly "pytest" and which contains a slash. The old rule said a slash means
# a path means a program. So a string that exists only to LOOK FOR pytest was read as
# BEING pytest.
#
# This is the command line as it actually appeared in /proc, trimmed to the eval body.

WAITING_SESSION_CMDLINE = (
    'eval until ! pgrep -f "m pytest src/tests" >/dev/null 2>&1 '
    '&& ! pgrep -f "pytest src/tests/unit" >/dev/null 2>&1 '
    '&& ! pgrep -f "bin/pytest src/" >/dev/null 2>&1; do sleep 20; done'
)


def test_a_session_waiting_for_the_box_is_not_a_running_suite():
    """
    THE REGRESSION. Verbatim command line, not a paraphrase of one — a shortened
    reconstruction would not carry the `"bin/pytest` fragment that does the damage,
    and a test that cannot fail on the original is not a guard against it.
    """
    assert cc.looks_like_pytest( WAITING_SESSION_CMDLINE ) is False, (
        "a session POLLING for pytest was read as RUNNING pytest — this is the defect "
        "that refused every coverage run in the tree on 2026-08-26"
    )


def test_the_waiting_session_still_gets_no_answer_through_the_public_finder():
    """One rung up: the false positive must not survive in find_foreign_pytest either."""
    table = [ ( 4242, WAITING_SESSION_CMDLINE ), ( 4243, "sleep 20" ) ]
    assert cc.find_foreign_pytest( process_table=lambda: table, ancestors=[] ) == []


def test_the_absolute_path_that_the_runners_actually_use_is_still_caught():
    """
    THE CONTROL ON THE FIX. Narrowing a guard can always be done by making it match
    nothing. This is the exact shape run-unit-tests.sh prints — `using pytest at
    /mnt/DATA01/.../.venv/bin/pytest` — and it must still be seen.
    """
    real = "/mnt/DATA01/include/www.deepily.ai/projects/lupin/.venv/bin/pytest src/tests/unit -q --cov"
    assert cc.looks_like_pytest( real ) is True


# ── find_foreign_pytest: whose pytest is it? ─────────────────────────────────

def test_a_foreign_pytest_is_found():
    table = [ ( 4242, "/opt/venv/bin/pytest src/cosa/tests/" ),
              ( 4243, "sleep 30" ) ]
    assert cc.find_foreign_pytest( lambda: table, ancestors=[ 1, 99 ] ) == [ table[ 0 ] ]


def test_our_own_process_tree_is_never_reported():
    """
    The self-refusal case. This process IS a pytest, and so is whatever invoked it; if the
    ancestor exclusion failed, a coverage run of this very suite would refuse itself.
    """
    table = [ ( 500, "/opt/venv/bin/pytest src/tests/unit/" ),      # "us"
              ( 501, "python3 -m pytest src/tests/unit/" ) ]        # our parent
    assert cc.find_foreign_pytest( lambda: table, ancestors=[ 500, 501 ] ) == []


def test_a_clean_box_returns_an_empty_list():
    table = [ ( 10, "/usr/lib/systemd/systemd" ), ( 11, "sleep 30" ) ]
    assert cc.find_foreign_pytest( lambda: table, ancestors=[ 1 ] ) == []


def test_offenders_come_back_sorted_by_pid():
    """Two callers must see the same order — an unstable list makes two logs disagree."""
    table = [ ( 900, "/opt/venv/bin/pytest a" ),
              ( 100, "/opt/venv/bin/pytest b" ),
              ( 500, "/opt/venv/bin/pytest c" ) ]
    assert [ pid for pid, _ in cc.find_foreign_pytest( lambda: table, ancestors=[] ) ] == [ 100, 500, 900 ]


def test_the_default_ancestor_walk_is_used_when_none_is_supplied():
    """
    With ancestors left to default, THIS process must be excluded — the real /proc walk has
    to reach it. Feed a table that claims our own pid is running pytest (it is) and assert
    it is filtered out anyway.
    """
    table = [ ( os.getpid(), "/opt/venv/bin/pytest src/tests/unit/" ) ]
    assert cc.find_foreign_pytest( lambda: table ) == []


# ── the /proc readers ────────────────────────────────────────────────────────

def test_the_ancestor_walk_reaches_at_least_this_process_and_its_parent():
    chain = cc._default_ancestors()
    assert chain[ 0 ] == os.getpid()
    assert os.getppid() in chain, "the walk never reached our own parent"
    assert len( set( chain ) ) == len( chain ), "the walk repeated a pid — it can loop"
    # It must stop BELOW init. Walking into pid 1 puts a pid nobody's suite owns into the
    # exclusion set, and every process on the box is a descendant of it.
    assert 1 not in chain, f"the walk climbed into init: {chain}"


def test_the_ancestor_walk_accepts_an_explicit_starting_pid():
    assert cc._default_ancestors( pid=os.getppid() )[ 0 ] == os.getppid()


def test_the_ancestor_walk_stops_on_an_unreadable_stat_file( monkeypatch ):
    """A pid that dies mid-walk ends the chain; it must not raise into the caller."""
    monkeypatch.setattr( cc, "open", _raising_open( OSError( "vanished" ) ), raising=False )
    assert cc._default_ancestors( pid=4242 ) == [ 4242 ]


def test_the_ancestor_walk_stops_on_a_malformed_stat_file( monkeypatch ):
    """/proc/<pid>/stat with no ')' — the ValueError/IndexError branch, not a crash."""
    monkeypatch.setattr( cc, "open", _fake_open( "no closing paren here" ), raising=False )
    assert cc._default_ancestors( pid=4242 ) == [ 4242 ]


def test_the_ancestor_walk_handles_a_comm_containing_spaces_and_parens( monkeypatch ):
    """
    ⚠️ THE FIELD IS NOT SPLITTABLE BY WHITESPACE. A process named `(my proc) x` puts both
    spaces AND parentheses inside field 2, so `.split()[3]` reads the wrong number. The
    module rsplits on the LAST ')' for exactly this; a real box has such processes.
    """
    monkeypatch.setattr( cc, "open", _fake_open( "4242 ((my proc) hack) S 777 4242 4242 0" ), raising=False )
    chain = cc._default_ancestors( pid=4242 )
    assert chain[ :2 ] == [ 4242, 777 ], f"ppid parsed wrong from a hostile comm: {chain}"


def test_the_real_process_table_sees_this_running_pytest():
    """
    The instrument check. If /proc reading were broken, every other test here would still
    pass on injected tables while the module found nothing at all in production.
    """
    rows = cc._default_process_table()
    assert any( pid == os.getpid() for pid, _ in rows ), "our own pid is not in the table"
    assert all( isinstance( pid, int ) and isinstance( cmd, str ) for pid, cmd in rows )


def test_the_process_table_skips_a_process_that_exits_mid_scan( monkeypatch ):
    """listdir sees a pid, the open fails a microsecond later. It is skipped, not fatal."""
    monkeypatch.setattr( cc.os, "listdir", lambda _p: [ "4242", "self", "meminfo" ] )
    monkeypatch.setattr( cc, "open", _raising_open( OSError( "gone" ) ), raising=False )
    assert cc._default_process_table() == []


def test_the_process_table_decodes_nul_separated_cmdlines( monkeypatch ):
    monkeypatch.setattr( cc.os, "listdir", lambda _p: [ "4242", "cpuinfo" ] )
    monkeypatch.setattr( cc, "open", _fake_open( b"/opt/venv/bin/pytest\x00-q\x00" ), raising=False )
    assert cc._default_process_table() == [ ( 4242, "/opt/venv/bin/pytest -q" ) ]


# ── the escape hatch ─────────────────────────────────────────────────────────

@pytest.mark.parametrize( "raw", [ "1", "true", "TRUE", "yes", "on", " 1 " ] )
def test_an_explicit_truthy_value_engages_the_escape_hatch( raw ):
    assert cc.escape_hatch_engaged( { cc.ESCAPE_HATCH_ENV: raw } ) is True


@pytest.mark.parametrize( "raw", [ "0", "false", "no", "off", "", "  " ] )
def test_a_falsey_value_does_not_engage_it( raw ):
    """
    A leftover `export LUPIN_ALLOW_CONTENDED_COVERAGE=0` in a shell profile reads to a human
    as "off". If any non-empty value engaged the hatch, that profile would silently disable
    the guard for everything that shell ever runs.
    """
    assert cc.escape_hatch_engaged( { cc.ESCAPE_HATCH_ENV: raw } ) is False


def test_an_absent_variable_does_not_engage_it():
    assert cc.escape_hatch_engaged( {} ) is False


def test_it_reads_the_real_environment_when_none_is_passed( monkeypatch ):
    monkeypatch.setenv( cc.ESCAPE_HATCH_ENV, "1" )
    assert cc.escape_hatch_engaged() is True
    monkeypatch.delenv( cc.ESCAPE_HATCH_ENV )
    assert cc.escape_hatch_engaged() is False


# ── the refusal message ──────────────────────────────────────────────────────

def test_the_refusal_names_the_offender_and_the_remedy():
    text = cc.render_refusal( [ ( 4242, "/opt/venv/bin/pytest src/cosa/tests/" ) ] )
    assert "4242" in text,                       "the message does not say WHICH process"
    assert "/opt/venv/bin/pytest" in text,       "the message does not say what it is"
    assert cc.ESCAPE_HATCH_ENV in text,          "the message does not offer the deliberate path"
    assert "pgrep -af pytest" in text,           "the message does not say how to check"


def test_a_very_long_command_line_is_truncated():
    """A 4000-character cmdline must not turn one refusal into a screenful of noise."""
    text = cc.render_refusal( [ ( 7, "/opt/venv/bin/pytest " + "x" * 4000 ) ] )
    assert len( max( text.splitlines(), key=len ) ) < 200


# ── main(): the four exits ───────────────────────────────────────────────────

def test_main_exits_clear_on_an_idle_box( monkeypatch, capsys ):
    monkeypatch.delenv( cc.ESCAPE_HATCH_ENV, raising=False )
    monkeypatch.setattr( cc, "find_foreign_pytest", lambda: [] )
    assert cc.main() == cc.EXIT_CLEAR
    assert capsys.readouterr().err == "", "a clear box must be silent"


def test_main_exits_contended_and_explains_itself( monkeypatch, capsys ):
    monkeypatch.delenv( cc.ESCAPE_HATCH_ENV, raising=False )
    monkeypatch.setattr( cc, "find_foreign_pytest", lambda: [ ( 4242, "/opt/venv/bin/pytest x" ) ] )
    assert cc.main() == cc.EXIT_CONTENDED
    assert "4242" in capsys.readouterr().err


def test_main_exits_unknown_when_the_process_table_cannot_be_read( monkeypatch, capsys ):
    """
    ⚠️ UNKNOWN IS NOT CLEAR. This is the whole reason the module has three exit codes rather
    than two: a checker that answered "clear" when it could not look would be a member of the
    very defect class it was written to close.
    """
    monkeypatch.delenv( cc.ESCAPE_HATCH_ENV, raising=False )
    def _boom(): raise OSError( "/proc is not mounted" )
    monkeypatch.setattr( cc, "find_foreign_pytest", _boom )
    assert cc.main() == cc.EXIT_UNKNOWN
    assert "UNKNOWN" in capsys.readouterr().err


def test_main_skips_the_check_entirely_when_the_hatch_is_engaged( monkeypatch, capsys ):
    """And says so — a silently-skipped guard is indistinguishable from a passing one."""
    monkeypatch.setenv( cc.ESCAPE_HATCH_ENV, "1" )
    def _never_called(): raise AssertionError( "the check ran despite the escape hatch" )
    monkeypatch.setattr( cc, "find_foreign_pytest", _never_called )
    assert cc.main() == cc.EXIT_CLEAR
    assert cc.ESCAPE_HATCH_ENV in capsys.readouterr().err


def test_the_three_exit_codes_are_distinct():
    """Two of them collapsing would erase the clear/unknown distinction above."""
    assert len( { cc.EXIT_CLEAR, cc.EXIT_CONTENDED, cc.EXIT_UNKNOWN } ) == 3


# ── helpers ──────────────────────────────────────────────────────────────────

class _Handle:
    def __init__( self, payload ): self._payload = payload
    def read( self ): return self._payload
    def __enter__( self ): return self
    def __exit__( self, *_exc ): return False


def _fake_open( payload ):
    """A stand-in for open() that always yields `payload` (str for stat, bytes for cmdline)."""
    def _opener( *_args, **_kwargs ): return _Handle( payload )
    return _opener


def _raising_open( error ):
    def _opener( *_args, **_kwargs ): raise error
    return _opener
