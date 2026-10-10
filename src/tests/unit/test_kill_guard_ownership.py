"""
Unit tests for the kill guard's ownership rule.

A `pkill` or `killall` pattern is refused when it matches a process that is provably
not the caller's. A process is the caller's if it descends from the caller's `claude`.
It is also the caller's if its cwd is inside the caller's tree and that tree is a
linked worktree. The main checkout is shared by several seats, so a cwd there proves
nothing.

The incident: a pattern kill from one seat's tree sent SIGTERM to another seat's unit
tier in another worktree. The guard then denied only a pattern matching a live `claude`.

Two kinds of test live here. Stubbed tests fake the /proc view and drive every verdict.
Driven tests start real second processes and use the real `pgrep` and the real /proc.
They signal only processes this module started, and only by pid.
"""
import os
import subprocess
import sys
import time
import uuid

import pytest

from lupin_cli.claude_code.hooks.lib import kill_guard
from lupin_cli.claude_code.hooks.lib.kill_guard import kill_deny_reason, CLAUDE_COMM

CALLER = 4000   # stand-in for the caller's claude pid in the stubbed tests


class FakeProc:
    """A fake /proc view: absent pids read as gone or unreadable."""

    def __init__( self, ppids=None, cwds=None ):
        self.ppids = ppids or {}
        self.cwds  = cwds  or {}

    def ppid( self, pid ):
        return self.ppids.get( int( pid ) )

    def cwd( self, pid ):
        return self.cwds.get( int( pid ) )


def _comm( table=None ):
    """A comm reader stub: the caller reads `claude`, a table pid reads its comm."""
    table = table or {}
    def reader( pid ):
        pid = int( pid )
        if pid == CALLER: return CLAUDE_COMM
        return table.get( pid, "pytest" )
    return reader


@pytest.fixture
def worktree( tmp_path ):
    """A linked-worktree-shaped tree: `.git` is a plain file."""
    root = tmp_path / "wt"
    ( root / "src" ).mkdir( parents=True )
    ( root / ".git" ).write_text( "gitdir: /elsewhere\n" )
    return str( root )


@pytest.fixture
def main_checkout( tmp_path ):
    """A main-checkout-shaped tree: `.git` is a directory."""
    root = tmp_path / "main"
    ( root / "src" ).mkdir( parents=True )
    ( root / ".git" ).mkdir()
    return str( root )


@pytest.fixture
def elsewhere( tmp_path ):
    other = tmp_path / "other-tree"
    other.mkdir()
    return str( other )


def _guard( command, pids, proc, cwd, comm=None, caller=CALLER ):
    return kill_deny_reason(
        "Bash", { "command": command }, enabled=True,
        comm_reader=comm or _comm(), pgrep_probe=lambda selector: [ str( p ) for p in pids ],
        cwd=cwd, proc=proc, caller_pid=caller,
    )


PATTERN = 'pkill -f "pytest src/tests/unit/"'


# ---------------------------------------------------------------------------
# The verdict, stubbed
# ---------------------------------------------------------------------------

def test_a_match_in_another_tree_that_this_session_did_not_start_is_denied( worktree, elsewhere ):
    proc   = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    reason = _guard( PATTERN, [ 700 ], proc, worktree )
    assert reason is not None
    assert "700" in reason
    assert elsewhere in reason
    assert "pytest" in reason


def test_a_match_this_session_started_is_allowed_even_when_it_changed_directory( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 650, 650: CALLER }, cwds={ 700: elsewhere } )
    assert _guard( PATTERN, [ 700 ], proc, worktree ) is None


def test_an_orphan_whose_cwd_is_inside_a_linked_worktree_is_mine( worktree ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: worktree + "/src" } )
    assert _guard( PATTERN, [ 700 ], proc, worktree ) is None


def test_D1_an_orphan_inside_the_MAIN_checkout_is_not_proof_of_ownership( main_checkout ):
    """Several seats run in the main checkout, so a cwd there says nothing about whose it is."""
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: main_checkout + "/src" } )
    reason = _guard( PATTERN, [ 700 ], proc, main_checkout )
    assert reason is not None
    assert "700" in reason


def test_D1_a_descendant_in_the_main_checkout_is_still_mine( main_checkout ):
    proc = FakeProc( ppids={ 700: CALLER }, cwds={ 700: main_checkout } )
    assert _guard( PATTERN, [ 700 ], proc, main_checkout ) is None


def test_a_worktree_seat_pattern_reaching_a_main_checkout_process_is_denied( worktree, main_checkout ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: main_checkout } )
    assert _guard( PATTERN, [ 700 ], proc, worktree ) is not None


def test_one_foreign_match_among_own_matches_denies_and_names_only_the_foreign( worktree, elsewhere ):
    proc = FakeProc(
        ppids={ 701: CALLER, 702: 1 },
        cwds ={ 701: worktree, 702: elsewhere },
    )
    reason = _guard( PATTERN, [ 701, 702 ], proc, worktree )
    assert reason is not None
    assert "702" in reason
    assert "701" not in reason


def test_a_second_sweep_is_checked_when_the_first_matches_only_my_own( worktree, elsewhere ):
    proc = FakeProc( ppids={ 701: CALLER, 702: 1 }, cwds={ 702: elsewhere } )
    seen = []
    def probe( selector ):
        seen.append( selector )
        return [ "701" ] if len( seen ) == 1 else [ "702" ]
    reason = kill_deny_reason(
        "Bash", { "command": 'pkill -f mine; pkill -f theirs' }, enabled=True,
        comm_reader=_comm(), pgrep_probe=probe, cwd=worktree, proc=proc, caller_pid=CALLER,
    )
    assert reason is not None
    assert "702" in reason
    assert len( seen ) == 2


def test_a_claude_match_keeps_its_own_message_and_wins_over_a_foreign_one( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1, 701: 1 }, cwds={ 700: elsewhere, 701: elsewhere } )
    reason = _guard( PATTERN, [ 700, 701 ], proc, worktree, comm=_comm( { 701: CLAUDE_COMM } ) )
    assert reason is not None
    assert "LIVE Claude Code sessions" in reason
    assert "701" in reason


def test_the_message_says_what_to_do_instead( worktree, elsewhere ):
    proc   = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    reason = _guard( PATTERN, [ 700 ], proc, worktree )
    assert "/proc/<pid>/comm" in reason
    assert "pkill -P $$" in reason
    assert "LUPIN_ALLOW_UNSCOPED_KILL=1" in reason


def test_the_message_lists_five_foreign_processes_and_counts_the_rest( worktree, elsewhere ):
    pids = list( range( 800, 808 ) )
    proc = FakeProc( ppids={ p: 1 for p in pids }, cwds={ p: elsewhere for p in pids } )
    reason = _guard( PATTERN, pids, proc, worktree )
    assert "800" in reason and "804" in reason
    assert "805" not in reason
    assert "3 more" in reason


# ---------------------------------------------------------------------------
# What the check must not do: every uncertainty allows
# ---------------------------------------------------------------------------

def test_a_process_that_is_gone_is_not_counted( worktree ):
    assert _guard( PATTERN, [ 700 ], FakeProc(), worktree ) is None


def test_a_process_with_an_unreadable_cwd_is_not_counted( worktree ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={} )
    assert _guard( PATTERN, [ 700 ], proc, worktree ) is None


def test_a_parent_chain_that_breaks_midway_is_not_counted( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 650 }, cwds={ 700: elsewhere } )   # 650 unreadable
    assert _guard( PATTERN, [ 700 ], proc, worktree ) is None


def test_a_parent_loop_is_bounded_and_falls_through_to_the_cwd_test( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 701, 701: 700 }, cwds={ 700: elsewhere } )
    assert _guard( PATTERN, [ 700 ], proc, worktree ) is not None
    inside = FakeProc( ppids={ 700: 701, 701: 700 }, cwds={ 700: worktree } )
    assert _guard( PATTERN, [ 700 ], inside, worktree ) is None


def test_no_claude_ancestor_means_the_check_is_skipped( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    reason = kill_deny_reason(
        "Bash", { "command": PATTERN }, enabled=True, comm_reader=lambda pid: "bash",
        pgrep_probe=lambda s: [ "700" ], cwd=worktree, proc=proc, caller_pid=None,
    )
    assert reason is None


def test_no_git_above_the_cwd_means_the_check_is_skipped( tmp_path, elsewhere ):
    bare = tmp_path / "no-git-here"
    bare.mkdir()
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( PATTERN, [ 700 ], proc, str( bare ) ) is None


@pytest.mark.parametrize( "cwd", [ None, "", 123 ] )
def test_an_absent_or_malformed_cwd_skips_the_check( cwd, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( PATTERN, [ 700 ], proc, cwd ) is None


def test_own_children_scoping_still_bypasses_the_check( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( "pkill -P $$ -f pytest", [ 700 ], proc, worktree ) is None


def test_a_sweep_with_no_selector_bypasses_the_check( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( "pkill", [ 700 ], proc, worktree ) is None
    assert _guard( "pkill -9", [ 700 ], proc, worktree ) is None


def test_the_hatch_still_opens_the_guard( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( "LUPIN_ALLOW_UNSCOPED_KILL=1 " + PATTERN, [ 700 ], proc, worktree ) is None


def test_a_pattern_matching_nothing_is_allowed( worktree ):
    assert _guard( PATTERN, [], FakeProc(), worktree ) is None


def test_an_error_inside_the_new_check_fails_open( worktree, elsewhere, monkeypatch ):
    def boom( *args, **kwargs ):
        raise RuntimeError( "proc exploded" )
    monkeypatch.setattr( kill_guard, "_resolve_ownership", boom )
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( PATTERN, [ 700 ], proc, worktree ) is None


# ---------------------------------------------------------------------------
# The helpers, directly
# ---------------------------------------------------------------------------

def test_the_real_proc_view_reads_this_process():
    view = kill_guard._ProcFs()
    assert view.ppid( os.getpid() ) == os.getppid()
    assert view.cwd( os.getpid() ) == os.path.realpath( os.getcwd() )


def test_the_real_proc_view_returns_none_for_a_pid_that_is_gone():
    view = kill_guard._ProcFs()
    assert view.ppid( 2 ** 22 + 12345 ) is None
    assert view.cwd( 2 ** 22 + 12345 ) is None


def test_a_stat_line_with_parentheses_in_the_name_is_parsed( monkeypatch, tmp_path ):
    """A comm with spaces and `)` still yields the parent pid after the final `)`."""
    real_open = open
    def fake_open( path, *args, **kwargs ):
        if str( path ) == "/proc/99999/stat":
            fake = tmp_path / "stat"
            fake.write_text( "99999 (a) b (c)) S 4242 1 1 0 -1\n" )
            return real_open( fake, *args, **kwargs )
        return real_open( path, *args, **kwargs )
    monkeypatch.setattr( "builtins.open", fake_open )
    assert kill_guard._ProcFs().ppid( 99999 ) == 4242


def test_a_malformed_stat_line_reads_as_unreadable( monkeypatch, tmp_path ):
    real_open = open
    def fake_open( path, *args, **kwargs ):
        if str( path ) == "/proc/99998/stat":
            fake = tmp_path / "stat2"
            fake.write_text( "garbage with no paren\n" )
            return real_open( fake, *args, **kwargs )
        return real_open( path, *args, **kwargs )
    monkeypatch.setattr( "builtins.open", fake_open )
    assert kill_guard._ProcFs().ppid( 99998 ) is None


def test_the_caller_is_found_by_walking_up_to_the_nearest_claude():
    proc = FakeProc( ppids={ 10: 20, 20: 30, 30: 1 } )
    comm = lambda pid: { "20": "sh", "30": CLAUDE_COMM }.get( str( pid ), "python" )
    assert kill_guard._nearest_claude( 10, comm, proc ) == 30


def test_the_caller_search_gives_up_at_init_and_on_a_loop():
    assert kill_guard._nearest_claude( 10, lambda p: "bash", FakeProc( ppids={ 10: 1 } ) ) is None
    assert kill_guard._nearest_claude( 10, lambda p: "bash", FakeProc( ppids={ 10: 11, 11: 10 } ) ) is None
    assert kill_guard._nearest_claude( 10, lambda p: "bash", FakeProc() ) is None


def test_with_no_caller_pid_given_the_walk_starts_at_this_process( worktree, elsewhere, monkeypatch ):
    me   = os.getpid()
    proc = FakeProc( ppids={ me: CALLER, 700: 1 }, cwds={ 700: elsewhere } )
    reason = kill_deny_reason(
        "Bash", { "command": PATTERN }, enabled=True, comm_reader=_comm(),
        pgrep_probe=lambda s: [ "700" ], cwd=worktree, proc=proc,
    )
    assert reason is not None
    assert "700" in reason


def test_with_no_proc_view_given_the_real_proc_is_used( worktree ):
    impossible = "nomatch-" + uuid.uuid4().hex
    assert kill_deny_reason(
        "Bash", { "command": f'pkill -f "{impossible}"' }, enabled=True, cwd=worktree,
        caller_pid=os.getpid(),
    ) is None


# ---------------------------------------------------------------------------
# Driven: real processes, the real pgrep, the real /proc
# ---------------------------------------------------------------------------

_SLEEPER = "import time; time.sleep(120)  # {token}"

_SPAWN_DETACHED = (
    "import subprocess, sys\n"
    "p = subprocess.Popen( [ sys.executable, '-c', sys.argv[2] ], cwd=sys.argv[1],\n"
    "    start_new_session=True, stdin=subprocess.DEVNULL,\n"
    "    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )\n"
    "print( p.pid, flush=True )\n"
)


def _spawn_orphan( cwd, token ):
    """
    Start a sleeper that does not descend from this test and return its pid.

    A throwaway parent starts it and exits, so the sleeper reparents away.
    The pid is read from the parent's stdout.
    """
    out = subprocess.run(
        [ sys.executable, "-c", _SPAWN_DETACHED, cwd, _SLEEPER.format( token=token ) ],
        capture_output=True, text=True, timeout=20, check=True,
    )
    return int( out.stdout.strip() )


def _stop( pid ):
    """Signal a process this module started, by pid, and wait for it to be gone."""
    try:
        os.kill( pid, 15 )
    except ProcessLookupError:
        return
    for _ in range( 50 ):
        try:
            os.kill( pid, 0 )
        except ProcessLookupError:
            return
        time.sleep( 0.1 )


def _real_guard( token, tree ):
    return kill_deny_reason(
        "Bash", { "command": f'pkill -f "{token}"' }, enabled=True,
        cwd=tree, caller_pid=os.getpid(),
    )


def test_driven_a_real_process_in_another_directory_is_refused_and_a_control_is_not( worktree, elsewhere ):
    token   = "kgprobe-" + uuid.uuid4().hex
    control = "kgprobe-" + uuid.uuid4().hex
    pid     = _spawn_orphan( elsewhere, token )
    try:
        reason = _real_guard( token, worktree )
        assert reason is not None
        assert str( pid ) in reason
        assert elsewhere in reason
        assert _real_guard( control, worktree ) is None          # matches nothing
    finally:
        _stop( pid )


def test_driven_a_real_orphan_inside_my_worktree_is_allowed( worktree ):
    token = "kgprobe-" + uuid.uuid4().hex
    pid   = _spawn_orphan( worktree, token )
    try:
        assert _real_guard( token, worktree ) is None
    finally:
        _stop( pid )


def test_driven_a_real_orphan_inside_the_main_checkout_is_refused( main_checkout ):
    token = "kgprobe-" + uuid.uuid4().hex
    pid   = _spawn_orphan( main_checkout, token )
    try:
        reason = _real_guard( token, main_checkout )
        assert reason is not None
        assert str( pid ) in reason
    finally:
        _stop( pid )


def test_driven_a_real_child_this_test_started_is_allowed_wherever_it_stands( worktree, elsewhere ):
    token = "kgprobe-" + uuid.uuid4().hex
    child = subprocess.Popen(
        [ sys.executable, "-c", _SLEEPER.format( token=token ) ],
        cwd=elsewhere, stdin=subprocess.DEVNULL,
    )
    try:
        assert _real_guard( token, worktree ) is None
    finally:
        child.terminate()
        child.wait( timeout=10 )
