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

# ⚠️ AN INJECTED TABLE NOW NEEDS AN INJECTED comm READER TOO (2026-08-30). The finder asks
# BOTH what the command line looks like AND what the kernel calls the process, and these
# tables carry pids that do not exist on this box — the real reader correctly answers None
# for every one of them, which would empty every list below. Injecting an interpreter comm
# keeps these cases about the thing they were written to test.
_AN_INTERPRETER = lambda _pid: "python3.13"


def test_a_foreign_pytest_is_found():
    table = [ ( 4242, "/opt/venv/bin/pytest src/cosa/tests/" ),
              ( 4243, "sleep 30" ) ]
    assert cc.find_foreign_pytest( lambda: table, ancestors=[ 1, 99 ],
                                   comm_of=_AN_INTERPRETER ) == [ table[ 0 ] ]


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
    found = cc.find_foreign_pytest( lambda: table, ancestors=[], comm_of=_AN_INTERPRETER )
    assert [ pid for pid, _ in found ] == [ 100, 500, 900 ]


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


def test_a_seat_whose_brief_merely_quotes_a_pytest_command_is_dropped():
    """
    🔴 THE MEASURED FALSE POSITIVE, row 9078a035, 2026-08-30. A Claude seat carries its
    whole spawn brief in argv, so a brief that QUOTES `-m pytest` is argv-identical to a
    running suite. Two such seats (pids 22130 / 124554, both comm=claude) made the guard
    refuse a --cov run on a box whose only real suite appeared in NEITHER named row — and
    being long-lived, they would have kept it shut indefinitely.

    The cmdline still passes looks_like_pytest; comm is what discriminates.

    ⚠️ MOVED DOWN ONE LEVEL 2026-08-30, claim unchanged. This asserted on
    _default_process_table while a comm filter lived there as well as in
    find_foreign_pytest. Two gates meant the REAL path was filtered twice and an INJECTED
    table only once, so a test could pass against a shape production never sees. The table
    gate was removed; the discriminating now happens in one place, and this asserts it
    there. Krishna's measured pids and reasoning above are untouched — the gate moved, the
    evidence did not.
    """
    brief = "/home/rruiz/.local/bin/claude --model claude-opus-5 Run: python -m pytest src/"
    assert cc.looks_like_pytest( brief ) is True, "precondition: argv cannot tell"
    table = lambda: [ ( 22130, brief ) ]
    assert cc.find_foreign_pytest( process_table=table, ancestors=[],
                                   comm_of=lambda _pid: "claude" ) == [], \
        "a comm=claude seat is not a running suite"
    # the positive control: identical argv, interpreter comm -> still seen
    assert len( cc.find_foreign_pytest( process_table=table, ancestors=[],
                                        comm_of=lambda _pid: "python3" ) ) == 1


def test_an_unreadable_comm_keeps_the_process_in_the_table( monkeypatch ):
    """
    UNKNOWN MUST NOT BECOME A PASS. If comm cannot be read, the row stays — a guard that
    goes quiet when it cannot see is the defect it exists to prevent.
    """
    def _opener( path, *_args, **_kwargs ):
        if str( path ).endswith( "/comm" ): raise OSError( "gone" )
        return _Handle( b"/opt/venv/bin/pytest\x00-q\x00" )
    monkeypatch.setattr( cc.os, "listdir", lambda _p: [ "4242" ] )
    monkeypatch.setattr( cc, "open", _opener, raising=False )
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
    assert "ps -eo comm,args" in text,           "the message does not say how to check"


def test_the_refusal_no_longer_prescribes_the_check_that_caused_the_false_positive():
    """
    ⚠️ THE REMEDY LINE USED TO READ `pgrep -af pytest`, which is the very command that
    manufactured this defect: it searches command LINES, so it finds every agent seat whose
    briefing merely TALKS about running pytest. A refusal that hands the reader a broken
    check teaches the wrong habit at the exact moment they are looking for guidance.
    """
    text = cc.render_refusal( [ ( 4242, "/opt/venv/bin/pytest src/cosa/tests/" ) ] )
    assert "pgrep -af pytest" not in text, "the refusal still prescribes the command-line search"
    assert "comm" in text,                 "the refusal does not point at the process's identity"


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


def _fake_open( payload, comm="python3" ):
    """
    A stand-in for open() yielding `payload` (str for stat, bytes for cmdline).

    ⚠️ PATH-AWARE SINCE 2026-08-30 (row 9078a035). _default_process_table now reads
    /proc/<pid>/comm as well as /proc/<pid>/cmdline, because a command line cannot
    distinguish a running suite from a Claude seat whose spawn brief merely QUOTES one.
    A fake that returned the same bytes for every path handed the comm check the
    cmdline's bytes; `comm` defaults to an interpreter so existing cases still describe
    a real pytest, and a caller can pass another value to model a non-suite process.
    """
    def _opener( path, *_args, **_kwargs ):
        if str( path ).endswith( "/comm" ): return _Handle( comm )
        return _Handle( payload )
    return _opener


def _raising_open( error ):
    def _opener( *_args, **_kwargs ): raise error
    return _opener


# ── comm: what the process IS, not what its command line says ────────────────
#
# ⚠️ THE DEFECT THESE PIN, MEASURED 2026-08-30 ON THE LIVE BOX. The coverage gate refused
# both tiers, naming pid 22130 — whose comm was `claude`. It is a peer agent seat, and its
# SPAWN BRIEFING quotes `LUPIN_ROOT="$PWD" .venv/bin/python -m pytest src/tests/unit/...`,
# because a seat's briefing IS its command line. The shape test cannot tell that from a
# suite; comm can. Both the real suite and the seat below are cmdline-SHAPED — that is the
# whole point of the pair.

@pytest.mark.parametrize( "comm", [ "pytest", "python", "python3", "python3.13", "python3.9" ] )
def test_an_interpreter_comm_can_be_running_a_suite( comm ):
    assert cc.comm_could_be_pytest( comm ) is True


@pytest.mark.parametrize( "comm", [
    "claude",           # the live false positive: an agent seat quoting the command
    "sleep",            # the retired end-to-end fixture, `exec -a "/usr/bin/pytest x" sleep`
    "bash", "node", "code",
    "pytest-watch",       # a watcher that has started no suite
    "python-config",      # not an interpreter, despite the prefix
    "python3-config",     # present on /usr/bin here; startswith("python") called it one
    "python3.10-config",  # likewise. Krishna's measurement, checked before adopting
] )
def test_a_non_interpreter_comm_is_not_a_running_suite( comm ):
    assert cc.comm_could_be_pytest( comm ) is False


def test_an_unreadable_comm_is_kept_rather_than_cleared():
    """
    🔴 FAIL-CLOSED, and the ONE case that must not join the list above. An empty comm means
    the process is alive and we could not read what it is. This module never converts its
    own blindness into a pass — the same doctrine as main()'s exit 2 — so an unreadable
    comm KEEPS the process as a possible suite. The alternative loses a real running suite
    silently, which is the direction that takes somebody's box away.

    ⚠️ THIS ASSERTED False FOR "" UNTIL 2026-08-30, matching a predicate that failed OPEN
    while its own commit message claimed the opposite. The test agreed with the code rather
    than with the design, which is exactly why it did not catch it.
    """
    assert cc.comm_could_be_pytest( "" ) is True


def test_an_agent_seat_quoting_the_command_is_not_a_running_suite():
    """
    THE REGRESSION PIN, in the exact shape that broke the gate. The command line is
    invocation-shaped and would pass looks_like_pytest on its own; comm is what saves it.
    """
    briefing = ( 'claude --model claude-opus-5 PROVE THE GATE: '
                 'LUPIN_ROOT="$PWD" .venv/bin/python -m pytest src/tests/unit/test_x.py -q' )
    assert cc.looks_like_pytest( briefing ) is True, "precondition: the shape test is fooled"
    assert cc.find_foreign_pytest( process_table=lambda: [ ( 22130, briefing ) ],
                                   ancestors=[],
                                   comm_of=lambda _pid: "claude" ) == []


def test_a_real_suite_is_still_caught_when_comm_agrees():
    """The other direction. A guard that never fires is not a guard."""
    row = ( 4242, "/opt/venv/bin/pytest src/cosa/tests/" )
    assert cc.find_foreign_pytest( process_table=lambda: [ row ],
                                   ancestors=[],
                                   comm_of=lambda _pid: "python3.13" ) == [ row ]


def test_a_process_that_exits_between_the_table_read_and_the_comm_read_is_dropped():
    """comm_of returns None for a vanished pid. A dead process cannot contend for the box."""
    assert cc.find_foreign_pytest( process_table=lambda: [ ( 4242, "/opt/venv/bin/pytest -q" ) ],
                                   ancestors=[],
                                   comm_of=lambda _pid: None ) == []


def test_a_live_process_whose_comm_cannot_be_read_is_not_silently_cleared():
    """
    An empty comm means /proc/<pid> still EXISTS but could not be read. It is reported as
    an empty string rather than None precisely so the two cases stay distinguishable.

    🔴 THE ASSERTION HERE USED TO READ `== []`, which is the OPPOSITE of what this test's
    name and docstring say, and it pinned the defect in place. Corrected 2026-08-30 (row
    9078a035): a live process we could not read STAYS an offender. "Could not look" is not
    "nothing there", and the cost is asymmetric — refusing costs a wait, passing costs a
    silently wrong coverage number, which is the whole reason this module exists.
    """
    row = ( 4242, "/opt/venv/bin/pytest -q" )
    assert cc._default_comm_of.__doc__ is not None
    assert cc.find_foreign_pytest( process_table=lambda: [ row ], ancestors=[],
                                   comm_of=lambda _pid: "" ) == [ row ]


def test_the_real_comm_reader_names_this_very_process():
    """The instrument check, matching test_the_real_process_table_sees_this_running_pytest."""
    assert cc.comm_could_be_pytest( cc._default_comm_of( os.getpid() ) ) is True


def test_the_real_comm_reader_returns_none_for_a_pid_that_does_not_exist():
    assert cc._default_comm_of( 2 ** 22 ) is None


def test_the_real_comm_reader_returns_empty_for_a_live_but_unreadable_process( monkeypatch ):
    monkeypatch.setattr( cc, "open", _raising_open( OSError( "denied" ) ), raising=False )
    monkeypatch.setattr( cc.os.path, "exists", lambda _p: True )
    assert cc._default_comm_of( 4242 ) == ""


def test_the_default_comm_reader_is_used_when_none_is_supplied( monkeypatch ):
    """Without this, every test above could pass on injected readers while production reads nothing."""
    seen = []
    monkeypatch.setattr( cc, "_default_comm_of", lambda pid: seen.append( pid ) or "claude" )
    assert cc.find_foreign_pytest( process_table=lambda: [ ( 4242, "/opt/venv/bin/pytest -q" ) ],
                                   ancestors=[] ) == []
    assert seen == [ 4242 ], "the real comm reader was never consulted"


# ── comm's three values are three different facts ────────────────────────────────
#
# Row 9078a035, measured against HEAD 2026-08-30. find_foreign_pytest passed comm
# straight to the predicate, which returned False for "" — so a LIVE
# process whose comm could not be read was waved through, while _default_comm_of's own
# docstring promised the caller was fail-closed on exactly that value. Neither function
# was wrong alone; the two contracts did not meet.

_REAL_PYTEST_CMD = "/opt/venv/bin/python -m pytest src/tests/unit/ -q --cov"


@pytest.mark.parametrize( "comm,is_offender,why", [
    ( "python3", True,  "a real interpreter running a pytest-shaped command line" ),
    ( "pytest",  True,  "pytest invoked as a script" ),
    ( "claude",  False, "a seat whose spawn brief merely quotes the command" ),
    ( "bash",    False, "a named non-interpreter" ),
    ( "",        True,  "ALIVE but comm unreadable — could-not-look is not nothing-there" ),
    ( None,      False, "the process has exited; there is nothing to contend with" ),
] )
def test_all_three_comm_values_are_distinguished( comm, is_offender, why ):
    """
    ⚠️ A CONTROL THAT SUPPLIES ONE VALUE CANNOT SEE THE DEFECT THIS PINS. Under the old
    code "" and None both produced [], so a fixture exercising only a readable interpreter
    name passes identically before and after the fix. All three shapes must be supplied.
    """
    found = cc.find_foreign_pytest(
        process_table = lambda: [ ( 999, _REAL_PYTEST_CMD ) ],
        ancestors     = [ 1 ],
        comm_of       = lambda _pid: comm,
    )
    assert bool( found ) is is_offender, why


def test_an_unreadable_live_comm_refuses_rather_than_passes():
    """
    The direction matters, not just the discrimination. Refusing costs a wait; passing
    costs a silently wrong coverage number, which is the whole reason this module exists.
    """
    assert cc._comm_admits_a_running_suite( "" ) is True
    assert cc._comm_admits_a_running_suite( None ) is False


def test_default_comm_of_still_produces_the_two_distinct_absences( monkeypatch ):
    """
    The seam only works if the producer keeps "" and None apart. Pinned here because the
    caller's correctness now DEPENDS on that distinction, which it did not before.
    """
    monkeypatch.setattr( cc, "open", _raising_open( OSError( "no perms" ) ), raising=False )
    monkeypatch.setattr( cc.os.path, "exists", lambda _p: True )
    assert cc._default_comm_of( 4242 ) == "", "a live but unreadable process must give ''"
    monkeypatch.setattr( cc.os.path, "exists", lambda _p: False )
    assert cc._default_comm_of( 4242 ) is None, "an exited process must give None"


# ── the docstring's two relative-path examples, pinned ────────────────────────────────
# Rachel's review, 2026-08-30: looks_like_pytest's "KNOWN GAPS" note named
# `.venv/bin/pytest -q` as the uncovered shape. The code CATCHES that one — the token
# leads the line — and misses the SCRIPT form instead, which is how `run-*-tests.sh`
# actually launches. The docstring was corrected; these pin both halves so the example
# cannot drift from the code again without a red test.
@pytest.mark.parametrize( "cmdline,expected,why", [
    ( ".venv/bin/pytest -q",                                  True,
      "a relative path that LEADS the line is a real invocation (index 0)" ),
    ( ".venv/bin/python3 .venv/bin/pytest src/tests/unit/ -q", False,
      "the script form — relative and non-leading — is the gap the docstring now names" ),
] )
def test_the_documented_relative_path_examples_match_the_code( cmdline, expected, why ):
    assert cc.looks_like_pytest( cmdline ) is expected, why


# ── clause 2: an interpreter running a TEST FILE directly ─────────────────────────────
# Found by Rachel 🕊️ 2026-08-30, measured by Tiberius 👑. A test file invoked as
# `python <file>.py` runs a real suite and contains NO pytest token anywhere, so
# looks_like_pytest cannot see it and the process never reaches the comm gate — which
# would have admitted it (comm=python3.13). 181 of the 699 files under src/tests/unit/
# run this way, via pytest.main(...) / unittest.main(...) in __main__.
#
# ⚠️ EVERY TEST BELOW ASSERTS AGAINST looks_like_a_running_suite, THE COMPOSED GATE, and
# the independence test asserts both clauses separately on ONE string. Asserting only the
# new clause would pass whether or not it was ever wired into find_foreign_pytest.

A_REAL_DIRECT_RUN = ".venv/bin/python src/tests/unit/test_outreach_ledger.py"


def test_a_test_file_run_directly_is_a_suite_and_clause_one_cannot_see_it():
    """
    THE DISCRIMINATING TEST. Both halves on ONE string, because either alone is weak:
    the first would pass if clause 2 merely duplicated clause 1, and the second is
    already true at HEAD before any fix.

    Measured 2026-08-30: this exact command prints "12 passed in 0.17s".
    """
    assert cc.looks_like_pytest( A_REAL_DIRECT_RUN ) is False, (
        "precondition — the pytest-token rule genuinely cannot see this line; if this "
        "ever goes True the token rule was widened, which is what clause 2 exists to avoid"
    )
    assert cc.looks_like_a_direct_test_file_run( A_REAL_DIRECT_RUN ) is True
    assert cc.looks_like_a_running_suite( A_REAL_DIRECT_RUN ) is True, (
        "the composed gate must catch it — this is the wiring, not the clause"
    )


@pytest.mark.parametrize( "cmdline,why", [
    ( A_REAL_DIRECT_RUN,                              "the measured case" ),
    ( "python3 src/tests/unit/test_x.py",             "a PATH-resolved interpreter" ),
    ( "/usr/bin/python3.13 /abs/path/test_x.py",      "absolute interpreter, absolute script" ),
    ( "/usr/bin/python3.13 /abs/path/foo_test.py",    "the *_test.py spelling" ),
    ( "python3 -B -u src/tests/unit/test_x.py",       "options before the script" ),
] )
def test_direct_test_file_runs_are_recognised( cmdline, why ):
    assert cc.looks_like_a_running_suite( cmdline ) is True, f"missed a real suite: {why}"


@pytest.mark.parametrize( "cmdline,why", [
    # 🔴 THESE FOUR ARE THE DISCRIMINATING ONES, AND MY FIRST CUT OF THIS LIST WAS NOT.
    # Mutation-measured 2026-08-30: deleting the -c/-m abort, and deleting the regex's
    # trailing anchor, BOTH survived — because the fixtures I first wrote here reach
    # neither guard. `python3 -c "import x; run( 'test_x.py' )"` splits so that the CODE
    # token is the first non-option token and is not test-shaped, so the line returns
    # False whether or not -c aborts; same for `-m json.tool`. The fixture agreed with the
    # code for the wrong reason. These four separate the guards from their absence:
    ( "python3 -c test_x.py",
      "-c: the code is the literal string 'test_x.py'. WITHOUT the -c abort this reads as a "
      "script and returns True — the only shape that reaches that guard" ),
    ( "python3 -m test_x.py",
      "-m: same, one option over. A real -m pytest is clause 1's job" ),
    ( "python3 src/tests/unit/test_x.pyc",
      "BYTECODE, not source. WITHOUT the regex's trailing $ anchor, `test_.+\\.py` matches "
      "the PREFIX of test_x.pyc and this reads as a suite" ),
    ( "python3 test_x.py.bak",
      "a backup file — the same missing anchor, a different suffix" ),
    ( 'python3 -c "import x; run( \'test_x.py\' )"',
      "-c with a realistic code string. Kept as CORROBORATION, not proof: it passes with or "
      "without the abort, which is exactly why it could not carry this on its own" ),
    ( "python3 -m json.tool test_x.py",
      "-m with a real module. Corroboration for the same reason" ),
    ( "python3 manage.py test",
      "an ordinary script that merely takes 'test' as an argument" ),
    ( "python3 src/scripts/run_something.py --file test_x.py",
      "only the FIRST non-option token is examined — a test path in a later ARGUMENT is not "
      "the program being run" ),
    ( "vim src/tests/unit/test_x.py",       "an editor buffer — the leader is not an interpreter" ),
    ( "grep -rn test_x.py src/",            "a grep" ),
    ( "python3-config --ldflags test_x.py", "not an interpreter; the whole-name comm rule again" ),
    ( "",                                   "empty" ),
] )
def test_clause_two_does_not_fire_on_a_mention( cmdline, why ):
    assert cc.looks_like_a_direct_test_file_run( cmdline ) is False, f"false positive: {why}"
    assert cc.looks_like_a_running_suite( cmdline ) is False, f"false positive via the gate: {why}"


@pytest.mark.parametrize( "cmdline,why", [
    ( "python3",                     "the bare interpreter — a REPL, no script at all" ),
    ( "python3 -v",                  "options only; the loop never meets a non-option token" ),
    ( "/usr/bin/python3.13 -O",      "an absolute interpreter with a flag and nothing to run" ),
    ( "python3 -X importtime",       "CORROBORATION ONLY, and measured as such: 'importtime' is "
                                     "a non-option token, so this returns from the line ABOVE the "
                                     "fall-through and passes with or without the mutation" ),
    ( "   ",                         "whitespace only — non-empty, so the empty-string guard lets "
                                     "it through, but it splits to ZERO tokens. A SECOND branch "
                                     "nothing reached: the file read 99% with 215->exit partial" ),
] )
def test_an_interpreter_with_no_script_at_all_is_not_a_direct_test_run( cmdline, why ):
    """
    RACHEL'S SURVIVOR (found 2026-08-30; measured surviving here at sha f1e9491aa10e).
    The final `return False` — reached only when the token loop finds NO non-option token
    — was mutated to `return True` and the whole file stayed green, 107 passed either way.
    With these cases the same sha fails 3 of 5 by name; the other two are noted in the list.

    The twelve cases in test_clause_two_does_not_fire_on_a_mention are correct and none of
    them can see it: every one bails at the interpreter check, at the -c/-m abort, or by
    returning a non-test basename from the line ABOVE the fall-through. So the list is
    named for false positives and cannot reach the only shape that produces this one —
    read the fixture, not the assertions (row 9ad838d6).

    Nothing subjective rides on it either: this fall-through is the module's stated
    fail-safe direction. Returning True here is a FALSE REFUSAL, which the function's own
    docstring says blocks every coverage run in the tree, where a miss blocks none.
    """
    assert cc.looks_like_a_direct_test_file_run( cmdline ) is False, f"false refusal: {why}"
    assert cc.looks_like_a_running_suite( cmdline ) is False, f"false refusal via the gate: {why}"


def test_the_accepted_narrowing_is_pinned_rather_than_left_to_drift():
    """
    An option taking a SEPARATE value before the script reads as a miss. Documented in
    looks_like_a_direct_test_file_run's docstring as deliberate: it fails toward a MISS,
    never a false refusal, and no sanctioned invocation uses the form. Pinned so the
    docstring cannot quietly stop matching the code — which is the exact defect Rachel
    found in clause 1's own "KNOWN GAPS" note.
    """
    assert cc.looks_like_a_direct_test_file_run( "python3 -X importtime test_x.py" ) is False


def test_clause_one_is_untouched_by_the_addition():
    """
    The token rule has been tightened twice and must not move. Both prior false positives
    stay closed, and the still-open script form stays exactly as documented.
    """
    assert cc.looks_like_pytest( 'pgrep -f "bin/pytest src/"' ) is False, "the quoted pattern"
    assert cc.looks_like_pytest( ".venv/bin/python3 .venv/bin/pytest src/tests/unit/ -q" ) is False, (
        "the script form is gap 2 and clause 2 must NOT accidentally close it — clause 2 keys "
        "on a test_*.py script, and 'pytest' is not one"
    )
    assert cc.looks_like_pytest( "/opt/venv/bin/pytest -q" ) is True, "a real invocation"


def test_a_direct_test_file_run_reaches_the_public_finder():
    """End to end: the gap closes where it matters, not merely in the predicate."""
    table = [ ( 777, A_REAL_DIRECT_RUN ) ]
    assert cc.find_foreign_pytest( lambda: table, ancestors=[], comm_of=_AN_INTERPRETER ) == table


def test_a_seat_brief_quoting_a_direct_run_is_still_dropped_by_comm():
    """
    Clause 2 widens the SHAPE half, so it owes the argument against itself: does it re-open
    the spawn-brief false positive that forced the comm gate? No — comm is what discriminates,
    exactly as it does for clause 1, and the widening does not touch it.
    """
    brief = A_REAL_DIRECT_RUN
    table = [ ( 22130, brief ) ]
    assert cc.looks_like_a_running_suite( brief ) is True, "precondition: argv cannot tell"
    assert cc.find_foreign_pytest( lambda: table, ancestors=[],
                                   comm_of=lambda _pid: "claude" ) == [], (
        "a seat whose brief quotes the command is not a running suite"
    )
    assert cc.find_foreign_pytest( lambda: table, ancestors=[],
                                   comm_of=_AN_INTERPRETER ) == table, (
        "the positive control — the same line under a real interpreter IS one"
    )
