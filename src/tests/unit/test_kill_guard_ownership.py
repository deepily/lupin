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
import tempfile
import time
import uuid

import pytest

from lupin_cli.claude_code.hooks.lib import kill_guard
from lupin_cli.claude_code.hooks.lib.kill_guard import kill_deny_reason, CLAUDE_COMM

@pytest.fixture( autouse=True )
def _isolated_hook_log( tmp_path, monkeypatch ):
    """A failed probe writes a hook-log line; keep it out of the real log directory."""
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", str( tmp_path / "hooklogs" ) )


CALLER = 4000   # stand-in for the caller's claude pid in the stubbed tests


class _Expired( BaseException ):
    """Raised by an alarm; a BaseException, so the fail-open handler cannot swallow it."""


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

_SLEEPER = (
    "import os, time  # {token}\n"
    "end = time.time() + 300\n"
    "while time.time() < end and not os.path.exists( {stop!r} ): time.sleep( 0.05 )\n"
)

_SPAWN_DETACHED = (
    "import subprocess, sys\n"
    "p = subprocess.Popen( [ sys.executable, '-c', sys.argv[2] ], cwd=sys.argv[1],\n"
    "    start_new_session=True, stdin=subprocess.DEVNULL,\n"
    "    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )\n"
    "print( p.pid, flush=True )\n"
)


_SPAWN_DETACHED_AS = (
    "import subprocess, sys\n"
    "p = subprocess.Popen( [ sys.argv[1], '-c', sys.argv[3] ], cwd=sys.argv[2],\n"
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
        [ sys.executable, "-c", _SPAWN_DETACHED, cwd, _SLEEPER.format( token=token, stop=_stop_file( token ) ) ],
        capture_output=True, text=True, timeout=20, check=True,
    )
    return int( out.stdout.strip() )


def _stop_file( token ):
    """The path whose appearance ends the sleeper that carries `token`."""
    return os.path.join( tempfile.gettempdir(), token + ".stop" )


def _stop( pid, token ):
    """
    End a sleeper this module started, without sending it any signal.

    The sleeper polls for its stop file, so creating the file asks it to leave.
    The argv token is read first, so a recycled pid is never touched.
    The wait ends when the process is gone or only a zombie.
    """
    try:
        with open( f"/proc/{pid}/cmdline", "rb" ) as handle:
            if token.encode() not in handle.read():
                return
    except OSError:
        return
    with open( _stop_file( token ), "w" ) as handle:
        handle.write( "stop\n" )
    try:
        for _ in range( 100 ):
            try:
                with open( f"/proc/{pid}/stat" ) as handle:
                    if handle.read().rsplit( ")", 1 )[ 1 ].split()[ 0 ] == "Z":
                        return
            except OSError:
                return
            time.sleep( 0.1 )
    finally:
        try:
            os.unlink( _stop_file( token ) )
        except OSError:
            pass


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
        _stop( pid, token )


def test_driven_a_real_orphan_inside_my_worktree_is_allowed( worktree ):
    token = "kgprobe-" + uuid.uuid4().hex
    pid   = _spawn_orphan( worktree, token )
    try:
        assert _real_guard( token, worktree ) is None
    finally:
        _stop( pid, token )


def test_driven_a_real_orphan_inside_the_main_checkout_is_refused( main_checkout ):
    token = "kgprobe-" + uuid.uuid4().hex
    pid   = _spawn_orphan( main_checkout, token )
    try:
        reason = _real_guard( token, main_checkout )
        assert reason is not None
        assert str( pid ) in reason
    finally:
        _stop( pid, token )


def test_driven_a_real_child_this_test_started_is_allowed_wherever_it_stands( worktree, elsewhere ):
    token = "kgprobe-" + uuid.uuid4().hex
    child = subprocess.Popen(
        [ sys.executable, "-c", _SLEEPER.format( token=token, stop=_stop_file( token ) ) ],
        cwd=elsewhere, stdin=subprocess.DEVNULL,
    )
    try:
        assert _real_guard( token, worktree ) is None
    finally:
        child.terminate()
        child.wait( timeout=10 )


# ---------------------------------------------------------------------------
# The selector the probe receives: redirections and quoted spans (review findings F1, F2)
# ---------------------------------------------------------------------------

def _selector_seen( command, worktree ):
    """The selector list the guard hands pgrep for the first sweep in `command`."""
    seen = []
    kill_deny_reason(
        "Bash", { "command": command }, enabled=True, comm_reader=_comm(),
        pgrep_probe=lambda selector: seen.append( list( selector ) ) or [],
        cwd=worktree, proc=FakeProc(), caller_pid=CALLER,
    )
    return seen[ 0 ] if seen else None


@pytest.mark.parametrize( "command", [
    "pkill -f TOK 2>/dev/null",
    "pkill -f TOK 2>&1",
    "pkill -f TOK > /dev/null",
    "pkill -f TOK >/dev/null",
    "pkill -f TOK >> /tmp/out.log",
    "pkill -f TOK 2>/dev/null || true",
    "pkill -f TOK > /dev/null 2>&1 || true",
    "pkill -f TOK &> /tmp/out.log",
    "pkill -f TOK < /dev/null",
] )
def test_a_redirection_is_not_part_of_the_pattern( command, worktree ):
    assert _selector_seen( command, worktree ) == [ "-f", "TOK" ]


@pytest.mark.parametrize( "command, expected", [
    ( 'pkill -f "TOK|zzz"',                  [ "-f", "TOK|zzz" ] ),
    ( "pkill -f 'zzz|TOK'",                  [ "-f", "zzz|TOK" ] ),
    ( 'pkill -f "TOK;"',                     [ "-f", "TOK;" ] ),
    ( 'pkill -f "a&b"',                      [ "-f", "a&b" ] ),
    ( 'pkill -f "pytest|vitest" 2>/dev/null', [ "-f", "pytest|vitest" ] ),
    ( "pkill -f 'has (parens) and `tick`'",  [ "-f", "has (parens) and `tick`" ] ),
    ( 'pkill -f ">TOK"',                     [ "-f", ">TOK" ] ),
    ( 'pkill -f "a b" -9',                   [ "-f", "a b" ] ),
    ( r"pkill -f TOK\|zzz",                  [ "-f", "TOK|zzz" ] ),
    ( r"pkill -f a\;b",                      [ "-f", "a;b" ] ),
    ( r"pkill -f a\&b -9",                   [ "-f", "a&b" ] ),
    ( r"pkill -f foo\ bar",                  [ "-f", "foo bar" ] ),
] )
def test_a_quoted_pattern_is_kept_whole_whatever_it_holds( command, expected, worktree ):
    assert _selector_seen( command, worktree ) == expected


def test_a_quoted_pattern_does_not_swallow_the_next_command( worktree ):
    command = 'pkill -f "TOK|zzz"; echo done'
    assert _selector_seen( command, worktree ) == [ "-f", "TOK|zzz" ]


def test_an_unbalanced_quote_still_falls_back_to_a_whitespace_split( worktree ):
    assert _selector_seen( 'pkill -f "TOK zzz', worktree ) == [ "-f", '"TOK', "zzz" ]


@pytest.mark.parametrize( "suffix", [
    "2>/dev/null", "2>&1", "> /dev/null", "2>/dev/null || true", "> /dev/null 2>&1 || true",
] )
def test_driven_a_redirect_does_not_hide_a_foreign_process( suffix, worktree, elsewhere ):
    token = "kgprobe-" + uuid.uuid4().hex
    pid   = _spawn_orphan( elsewhere, token )
    try:
        reason = kill_deny_reason(
            "Bash", { "command": f"pkill -f {token} {suffix}" }, enabled=True,
            cwd=worktree, caller_pid=os.getpid(),
        )
        assert reason is not None
        assert str( pid ) in reason
    finally:
        _stop( pid, token )


@pytest.mark.parametrize( "shape", [ '"{token}|zzzz{token2}"', "'zzzz{token2}|{token}'", '"{token}|{token2};"' ] )
def test_driven_a_quoted_pattern_holding_a_metacharacter_does_not_hide_a_foreign_process(
    shape, worktree, elsewhere
):
    token  = "kgprobe-" + uuid.uuid4().hex
    token2 = "kgprobe-" + uuid.uuid4().hex
    pid    = _spawn_orphan( elsewhere, token )
    try:
        pattern = shape.format( token=token, token2=token2 )
        reason  = kill_deny_reason(
            "Bash", { "command": f"pkill -f {pattern}" }, enabled=True,
            cwd=worktree, caller_pid=os.getpid(),
        )
        assert reason is not None
        assert str( pid ) in reason
    finally:
        _stop( pid, token )


def test_driven_the_control_with_a_redirect_and_a_quoted_alternation_matches_nothing( worktree ):
    nothing = "kgprobe-" + uuid.uuid4().hex
    other   = "kgprobe-" + uuid.uuid4().hex
    command = f'pkill -f "{nothing}|{other}" 2>/dev/null || true'
    assert kill_deny_reason(
        "Bash", { "command": command }, enabled=True, cwd=worktree, caller_pid=os.getpid(),
    ) is None


# ---------------------------------------------------------------------------
# Review survivors: the separator prefix, a symlinked cwd, a permission error
# ---------------------------------------------------------------------------

def test_a_sibling_directory_sharing_the_prefix_is_not_inside_the_tree( tmp_path ):
    """`/x/tree2` starts with `/x/tree` and is still another tree."""
    tree    = tmp_path / "tree"
    sibling = tmp_path / "tree2"
    for directory in ( tree, sibling ):
        directory.mkdir()
    ( tree / ".git" ).write_text( "gitdir: /elsewhere\n" )
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: str( sibling ) } )
    reason = _guard( PATTERN, [ 700 ], proc, str( tree ) )
    assert reason is not None
    assert "700" in reason


def test_a_symlinked_payload_cwd_resolves_to_the_real_tree( tmp_path ):
    real = tmp_path / "real-wt"
    real.mkdir()
    ( real / ".git" ).write_text( "gitdir: /elsewhere\n" )
    link = tmp_path / "link-to-wt"
    link.symlink_to( real )
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: str( real ) } )   # /proc reports the real path
    assert _guard( PATTERN, [ 700 ], proc, str( link ) ) is None


def test_the_real_proc_view_reads_a_permission_error_as_unreadable( monkeypatch ):
    def refuse( path, *args, **kwargs ):
        raise PermissionError( 13, "Permission denied", path )
    monkeypatch.setattr( os, "readlink", refuse )
    assert kill_guard._ProcFs().cwd( 1 ) is None


def test_one_unreadable_match_does_not_flip_the_verdict_on_a_foreign_one( worktree, elsewhere, monkeypatch ):
    """A permission error on one pid must not become an allow for the others."""
    real_readlink = os.readlink
    def selective( path, *args, **kwargs ):
        if str( path ) == "/proc/701/cwd":
            raise PermissionError( 13, "Permission denied", path )
        if str( path ) == "/proc/702/cwd":
            return elsewhere
        return real_readlink( path, *args, **kwargs )
    monkeypatch.setattr( os, "readlink", selective )
    real_open = open
    def fake_open( path, *args, **kwargs ):
        if str( path ) in ( "/proc/701/stat", "/proc/702/stat" ):
            import io
            return io.StringIO( f"{str( path ).split( '/' )[ 2 ]} (x) S 1 1 1 0\n" )
        return real_open( path, *args, **kwargs )
    monkeypatch.setattr( "builtins.open", fake_open )
    reason = kill_deny_reason(
        "Bash", { "command": PATTERN }, enabled=True, comm_reader=_comm(),
        pgrep_probe=lambda s: [ "701", "702" ], cwd=worktree, caller_pid=CALLER,
    )
    assert reason is not None
    assert "702" in reason


# ---------------------------------------------------------------------------
# Own-children scoping keys on the shell's own pid, not on any -P value (review F4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "scope", [ "-P 1", "-P 1346", "--parent 1", "-P 99999" ] )
def test_P_with_a_literal_pid_is_not_own_children_scoping( scope, worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( f"pkill {scope} -f TOK", [ 700 ], proc, worktree ) is not None


@pytest.mark.parametrize( "scope", [
    "-P $$", "-P ${$}", "-P $PPID", "-P ${PPID}", "-P $BASHPID", "-P $!", "--ppid $$", '-P "$$"',
] )
def test_P_with_the_shells_own_pid_is_own_children_scoping( scope, worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( f"pkill {scope} -f TOK", [ 700 ], proc, worktree ) is None


# ---------------------------------------------------------------------------
# `timeout` is a transparent wrapper (review F6)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "prefix", [
    "timeout 5", "timeout 5s", "timeout 1.5m", "timeout -s KILL 5", "timeout --signal=KILL 5",
    "timeout -k 2 10", "sudo timeout 5", "env FOO=1 timeout 5",
] )
def test_a_timeout_wrapper_does_not_hide_a_foreign_match( prefix, worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( f"{prefix} pkill -f TOK", [ 700 ], proc, worktree ) is not None


def test_a_timeout_wrapper_does_not_hide_a_literal_claude_pid():
    reason = kill_deny_reason(
        "Bash", { "command": "timeout 5 kill 4242" }, enabled=True, comm_reader=lambda pid: CLAUDE_COMM,
    )
    assert reason is not None


def test_the_hatch_is_honoured_behind_a_timeout_wrapper( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    command = "timeout 5 env LUPIN_ALLOW_UNSCOPED_KILL=1 pkill -f TOK"
    assert _guard( command, [ 700 ], proc, worktree ) is None


def test_the_word_timeout_as_an_argument_is_not_a_wrapper( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( "echo timeout 5 pkill -f TOK", [ 700 ], proc, worktree ) is None


# ---------------------------------------------------------------------------
# A probe that cannot answer still allows, and says so (review: the probe row)
# ---------------------------------------------------------------------------

@pytest.fixture
def hook_log( tmp_path, monkeypatch ):
    """Redirect the hook log and return a reader of the lines written to it."""
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", str( tmp_path / "hooklogs" ) )
    def lines():
        import json
        path = tmp_path / "hooklogs" / "hook-events.jsonl"
        if not path.exists():
            return []
        return [ json.loads( line ) for line in path.read_text().splitlines() if line.strip() ]
    return lines


class _Completed:
    def __init__( self, returncode, stdout="" ):
        self.returncode = returncode
        self.stdout     = stdout


@pytest.mark.parametrize( "code", [ 3, 4 ] )
def test_a_pgrep_failure_exit_allows_and_writes_one_log_line( code, monkeypatch, hook_log ):
    monkeypatch.setattr( kill_guard.subprocess, "run", lambda *a, **k: _Completed( code ) )
    assert kill_guard._default_pgrep_probe( [ "-f", "x" ] ) == []
    written = hook_log()
    assert len( written ) == 1
    assert written[ 0 ][ "hook" ] == "kill_guard_probe_failed"
    assert written[ 0 ][ "exit_code" ] == code
    assert written[ 0 ][ "selector" ] == [ "-f", "x" ]


def test_pgrep_exit_one_is_no_match_and_writes_nothing( monkeypatch, hook_log ):
    monkeypatch.setattr( kill_guard.subprocess, "run", lambda *a, **k: _Completed( 1 ) )
    assert kill_guard._default_pgrep_probe( [ "-f", "x" ] ) == []
    assert hook_log() == []


def test_pgrep_exit_zero_returns_the_pids_and_writes_nothing( monkeypatch, hook_log ):
    monkeypatch.setattr( kill_guard.subprocess, "run", lambda *a, **k: _Completed( 0, "12\n34\n" ) )
    assert kill_guard._default_pgrep_probe( [ "-f", "x" ] ) == [ "12", "34" ]
    assert hook_log() == []


def test_a_pgrep_timeout_allows_and_writes_one_log_line( monkeypatch, hook_log ):
    def slow( *args, **kwargs ):
        raise subprocess.TimeoutExpired( "pgrep", 5 )
    monkeypatch.setattr( kill_guard.subprocess, "run", slow )
    assert kill_guard._default_pgrep_probe( [ "-f", "x" ] ) == []
    written = hook_log()
    assert len( written ) == 1
    assert "timeout" in written[ 0 ][ "reason" ]


def test_a_missing_pgrep_allows_and_writes_one_log_line( monkeypatch, hook_log ):
    def missing( *args, **kwargs ):
        raise FileNotFoundError( "pgrep" )
    monkeypatch.setattr( kill_guard.subprocess, "run", missing )
    assert kill_guard._default_pgrep_probe( [ "-f", "x" ] ) == []
    written = hook_log()
    assert len( written ) == 1
    assert "pgrep" in written[ 0 ][ "reason" ]


def test_an_empty_selector_is_not_a_probe_failure( hook_log ):
    assert kill_guard._default_pgrep_probe( [] ) == []
    assert hook_log() == []


def test_a_log_write_that_fails_does_not_break_the_probe( monkeypatch ):
    monkeypatch.setattr( kill_guard.subprocess, "run", lambda *a, **k: _Completed( 3 ) )
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", "/proc/definitely/not/writable" )
    assert kill_guard._default_pgrep_probe( [ "-f", "x" ] ) == []


# ---------------------------------------------------------------------------
# The ownership view is built only when a sweep is on the line (review F9)
# ---------------------------------------------------------------------------

def test_the_ownership_view_is_not_built_for_a_command_with_no_sweep( worktree, monkeypatch ):
    calls = []
    monkeypatch.setattr( kill_guard, "_resolve_ownership", lambda *a, **k: calls.append( 1 ) )
    for command in ( "ls -la", "git status", "kill %1" ):
        kill_deny_reason(
            "Bash", { "command": command }, enabled=True, comm_reader=_comm(),
            pgrep_probe=lambda s: [], cwd=worktree, proc=FakeProc(), caller_pid=CALLER,
        )
    assert calls == []


# ---------------------------------------------------------------------------
# The selector is the SHELL's view of the options pkill and killall accept, and
# a selector pgrep rejects is refused, never read as "no match"
# ---------------------------------------------------------------------------

class _Spy:
    """Wraps the real probe and records every selector it was handed."""

    def __init__( self ):
        self.selectors = []

    def __call__( self, selector ):
        self.selectors.append( list( selector ) )
        return kill_guard._default_pgrep_probe( selector )


def _run_real( command, cwd, spy ):
    """The guard over `command` with the real pgrep and real /proc, selector recorded."""
    return kill_deny_reason(
        "Bash", { "command": command }, enabled=True, comm_reader=None,
        pgrep_probe=spy, cwd=cwd, caller_pid=os.getpid(),
    )


# ( command, outcome, the selectors pgrep must have been handed )
_NONE = "none-of-these-match-" + uuid.uuid4().hex
_OPTION_TABLE = [
    # selecting options are translated, output-only ones are dropped
    ( f"pkill -e -f {_NONE}",              "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill -l -f {_NONE}",              "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill -a -f {_NONE}",              "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill -w -f {_NONE}",              "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill -c {_NONE}",                 "resolved", [ [ _NONE ] ] ),
    ( f"pkill -q 1 -f {_NONE}",            "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill -U 0 -f {_NONE}",            "resolved", [ [ "-U", "0", "-f", _NONE ] ] ),
    ( f"pkill -G 0 -f {_NONE}",            "resolved", [ [ "-G", "0", "-f", _NONE ] ] ),
    ( f"pkill -u 0 -f {_NONE}",            "resolved", [ [ "-u", "0", "-f", _NONE ] ] ),
    ( f"pkill -g 1 -f {_NONE}",            "resolved", [ [ "-g", "1", "-f", _NONE ] ] ),
    ( f"pkill -s 1 -f {_NONE}",            "resolved", [ [ "-s", "1", "-f", _NONE ] ] ),
    ( f"pkill -t pts/0 -f {_NONE}",        "resolved", [ [ "-t", "pts/0", "-f", _NONE ] ] ),
    ( f"pkill -P 1234 {_NONE}",            "resolved", [ [ "-P", "1234", _NONE ] ] ),
    ( f"pkill -P1234 -f {_NONE}",          "resolved", [ [ "-P", "1234", "-f", _NONE ] ] ),
    ( f"pkill --parent=1234 -f {_NONE}",   "resolved", [ [ "-P", "1234", "-f", _NONE ] ] ),
    ( f"pkill --uid 0 --full {_NONE}",     "resolved", [ [ "-U", "0", "-f", _NONE ] ] ),
    ( f"pkill -fx {_NONE}",                "resolved", [ [ "-f", "-x", _NONE ] ] ),
    ( f"pkill -9 -f {_NONE}",              "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill -9f {_NONE}",                "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill -KILL -f {_NONE}",           "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill -SIGTERM -f {_NONE}",        "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill --signal TERM -f {_NONE}",   "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill --signal=9 -f {_NONE}",      "resolved", [ [ "-f", _NONE ] ] ),
    ( f"pkill -f {_NONE}\\ more",          "resolved", [ [ "-f", f"{_NONE} more" ] ] ),
    ( f'pkill -f "{_NONE} more"',          "resolved", [ [ "-f", f"{_NONE} more" ] ] ),
    # killall: names are exact comm matches, one probe per name
    ( f"killall -q {_NONE}",               "resolved", [ [ "-x", _NONE[ :15 ] ] ] ),
    ( f"killall -e {_NONE}",               "resolved", [ [ "-x", _NONE[ :15 ] ] ] ),
    ( f"killall -v -w -i -l {_NONE}",      "resolved", [ [ "-x", _NONE[ :15 ] ] ] ),
    ( f"killall -y 5m {_NONE}",            "resolved", [ [ "-x", _NONE[ :15 ] ] ] ),
    ( f"killall -o 5m {_NONE}",            "resolved", [ [ "-x", _NONE[ :15 ] ] ] ),
    ( f"killall -Z ctx {_NONE}",           "resolved", [ [ "-x", _NONE[ :15 ] ] ] ),
    ( f"killall -g {_NONE}",               "resolved", [ [ "-x", _NONE[ :15 ] ] ] ),
    ( f"killall -s TERM {_NONE}",          "resolved", [ [ "-x", _NONE[ :15 ] ] ] ),
    ( f"killall -TERM {_NONE}",            "resolved", [ [ "-x", _NONE[ :15 ] ] ] ),
    ( f"killall -9 {_NONE}",               "resolved", [ [ "-x", _NONE[ :15 ] ] ] ),
    ( f"killall -u 0 {_NONE}",             "resolved", [ [ "-x", "-u", "0", _NONE[ :15 ] ] ] ),
    ( f"killall -I {_NONE}",               "resolved", [ [ "-x", "-i", _NONE[ :15 ] ] ] ),
    ( f"killall -r {_NONE}.*",             "resolved", [ [ f"{_NONE}.*" ] ] ),
    ( "killall kgnone-a kgnone-b",         "resolved", [ [ "-x", "kgnone-a" ], [ "-x", "kgnone-b" ] ] ),
    # what cannot become a valid selector is refused, with the remedy
    ( "pkill -f ${VAR_" + uuid.uuid4().hex[ :6 ] + "}", "refused", None ),
    ( f"pkill -f `echo {_NONE}`",          "refused", None ),
    ( f"pkill -f 'a b' {_NONE}",           "refused", None ),
    ( f"pkill -f {_NONE} second",          "refused", None ),
    ( f"pkill --nosuchoption {_NONE}",     "refused", None ),
    # scoped to the shell's own children, or nothing to select on: no probe at all
    ( f"pkill -P $$ -f {_NONE}",           "allowed", [] ),
    ( "pkill",                             "allowed", [] ),
    ( "pkill -9",                          "allowed", [] ),
    ( "killall",                           "allowed", [] ),
]


@pytest.mark.parametrize( "command, outcome, selectors", _OPTION_TABLE, ids=[ row[ 0 ].replace( _NONE, "NONE" ) for row in _OPTION_TABLE ] )
def test_every_option_form_is_resolved_refused_or_allowed_on_purpose( command, outcome, selectors, worktree ):
    spy    = _Spy()
    reason = _run_real( command, worktree, spy )
    if outcome == "refused":
        assert reason is not None
        assert "rejected" in reason or "cannot read" in reason
        assert "LUPIN_ALLOW_UNSCOPED_KILL=1" in reason
        assert "/proc/<pid>/comm" in reason
        return
    assert reason is None
    assert spy.selectors == selectors


def test_the_refusal_comes_after_the_own_children_skip( worktree ):
    spy = _Spy()
    assert _run_real( "pkill -P $$ -f ${VAR}", worktree, spy ) is None
    assert spy.selectors == []


def test_a_probe_the_selector_was_rejected_by_raises_for_the_guard_to_refuse( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", str( tmp_path ) )
    monkeypatch.setattr( kill_guard.subprocess, "run", lambda *a, **k: _Completed( 2 ) )
    with pytest.raises( kill_guard._SelectorRejected ) as caught:
        kill_guard._default_pgrep_probe( [ "-f", "a", "b" ] )
    assert caught.value.selector == [ "-f", "a", "b" ]
    assert caught.value.exit_code == 2


def test_a_rejected_selector_is_refused_on_the_claude_only_path_too( ):
    """No cwd in the payload: the legacy path must refuse as well."""
    def reject( selector ):
        raise kill_guard._SelectorRejected( selector, 2 )
    reason = kill_deny_reason(
        "Bash", { "command": "pkill -f a b" }, enabled=True, comm_reader=_comm(), pgrep_probe=reject,
    )
    assert reason is not None
    assert "rejected" in reason


def test_a_rejection_in_a_later_sweep_is_still_refused( worktree ):
    def probe( selector ):
        if selector == [ "-f", "bad" ]:
            raise kill_guard._SelectorRejected( selector, 2 )
        return []
    reason = kill_deny_reason(
        "Bash", { "command": "pkill -f good; pkill -f bad" }, enabled=True, comm_reader=_comm(),
        pgrep_probe=probe, cwd=worktree, proc=FakeProc(), caller_pid=CALLER,
    )
    assert reason is not None
    assert "rejected" in reason


def test_pkill_s_selects_a_session_and_killall_s_is_a_signal():
    assert kill_guard._sweep_selector( " -s 1 -f x" ) == [ "-s", "1", "-f", "x" ]
    assert kill_guard._sweep_selectors( "killall", " -s TERM x" ) == [ [ "-x", "x" ] ]


@pytest.mark.parametrize( "args, expected", [
    ( " -V",                        [] ),
    ( " --help",                    [] ),
    ( " -f --",                     [ [ "-f" ] ] ),
    ( " -f -- -weird-pattern",      [ [ "-f", "--", "-weird-pattern" ] ] ),
    ( " --delimiter , x",           [ [ "x" ] ] ),
    ( " --ns 1 --nslist pid x",     [ [ "--ns", "1", "--nslist", "pid", "x" ] ] ),
    ( " --ns=1 x",                  [ [ "--ns", "1", "x" ] ] ),
    ( " -fq 1 y",                   [ [ "-f", "y" ] ] ),
] )
def test_unusual_pkill_argument_shapes( args, expected ):
    assert kill_guard._sweep_selectors( "pkill", args ) == expected


@pytest.mark.parametrize( "args, expected", [
    ( " -V",                    [] ),
    ( " --user=bob x",          [ [ "-x", "-u", "bob", "x" ] ] ),
    ( " --regexp x y",          [ [ "x" ], [ "y" ] ] ),
    ( " -eq x",                 [ [ "-x", "x" ] ] ),
    ( " -- -x",                 [ [ "-x", "-x" ] ] ),
    ( " --signal=TERM x",       [ [ "-x", "x" ] ] ),
    ( " --older-than 5m x",     [ [ "-x", "x" ] ] ),
    ( " --bogus x",             [ [ "-x", "x" ] ] ),
    ( " --ignore-case x",       [ [ "-x", "-i", "x" ] ] ),
    ( " -ubob x",               [ [ "-x", "-u", "bob", "x" ] ] ),
    ( " -rI x",                 [ [ "-i", "x" ] ] ),
] )
def test_unusual_killall_argument_shapes( args, expected ):
    assert kill_guard._sweep_selectors( "killall", args ) == expected


# --- the sleeper's life no longer depends on a clock the box can stall -------

def test_driven_the_sleeper_outlives_a_slow_test_and_ends_on_the_stop_file( worktree, elsewhere ):
    token = "kgprobe-" + uuid.uuid4().hex
    pid   = _spawn_orphan( elsewhere, token )
    try:
        time.sleep( 1.5 )                                   # longer than any scheduling hiccup a test sees
        assert os.path.exists( f"/proc/{pid}" )
        assert _real_guard( token, worktree ) is not None   # still there to be found
    finally:
        _stop( pid, token )
    assert not os.path.exists( f"/proc/{pid}" ) or open( f"/proc/{pid}/stat" ).read().split( ")" )[ -1 ].split()[ 0 ] == "Z"


# --- driven: selecting by parent, user, group, session, pidfile, exact name --

def _stat_field( pid, index ):
    with open( f"/proc/{pid}/stat" ) as handle:
        return handle.read().rsplit( ")", 1 )[ 1 ].split()[ index ]


def _denied_for( command, worktree, pid ):
    reason = kill_deny_reason(
        "Bash", { "command": command }, enabled=True, cwd=worktree, caller_pid=os.getpid(),
    )
    assert reason is not None, command
    assert str( pid ) in reason, command
    return reason


def test_driven_selecting_by_parent_user_group_session_and_pidfile_still_finds_the_foreign_process(
    worktree, elsewhere, tmp_path
):
    token = "kgprobe-" + uuid.uuid4().hex
    pid   = _spawn_orphan( elsewhere, token )
    try:
        ppid    = _stat_field( pid, 1 )       # state is field 0, ppid is field 1
        pgrp    = _stat_field( pid, 2 )
        session = _stat_field( pid, 3 )
        pidfile = tmp_path / "kg.pid"
        pidfile.write_text( f"{pid}\n" )
        for option in (
            f"-P {ppid}", f"-U {os.getuid()}", f"-u {os.geteuid()}", f"-G {os.getgid()}",
            f"-g {pgrp}", f"-s {session}", f"-F {pidfile}",
        ):
            _denied_for( f"pkill {option} -f {token} 2>/dev/null || true", worktree, pid )
        # the control for each selecting option: same option, a pattern that matches nothing
        control = "kgprobe-" + uuid.uuid4().hex
        for option in ( f"-P {ppid}", f"-U {os.getuid()}", f"-G {os.getgid()}", f"-g {pgrp}", f"-s {session}" ):
            assert kill_deny_reason(
                "Bash", { "command": f"pkill {option} -f {control}" }, enabled=True,
                cwd=worktree, caller_pid=os.getpid(),
            ) is None
    finally:
        _stop( pid, token )


def _spawn_named( cwd, name, token, tmp_path ):
    """A detached sleeper whose comm is `name`, a symlink to this interpreter."""
    link = tmp_path / name
    if not link.exists():
        link.symlink_to( sys.executable )
    stop = os.path.join( tempfile.gettempdir(), token + ".stop" )
    code = _SLEEPER.format( token=token, stop=stop )
    out  = subprocess.run(
        [ sys.executable, "-c", _SPAWN_DETACHED_AS, str( link ), cwd, code ],
        capture_output=True, text=True, timeout=20, check=True,
    )
    return int( out.stdout.strip() )


def test_driven_killall_matches_the_exact_comm_and_not_a_longer_sibling( worktree, elsewhere, tmp_path ):
    base    = "kgq" + uuid.uuid4().hex[ :8 ]
    token_a = "kgprobe-" + uuid.uuid4().hex
    token_b = "kgprobe-" + uuid.uuid4().hex
    sibling = _spawn_named( elsewhere, base + "xy", token_a, tmp_path )
    try:
        assert open( f"/proc/{sibling}/comm" ).read().strip() == base + "xy"
        # only the longer sibling runs: `killall <base>` would signal nothing, so it must be allowed
        assert kill_deny_reason(
            "Bash", { "command": f"killall -q {base}" }, enabled=True, cwd=worktree, caller_pid=os.getpid(),
        ) is None
        exact = _spawn_named( elsewhere, base, token_b, tmp_path )
        try:
            _denied_for( f"killall -q {base} 2>/dev/null", worktree, exact )
        finally:
            _stop( exact, token_b )
    finally:
        _stop( sibling, token_a )


# ---------------------------------------------------------------------------
# Expansions the guard cannot read are refused, in a pattern or an option value
# ---------------------------------------------------------------------------

_UNREADABLE_FORMS = [
    "pkill -f $'TOK zed'",
    'pkill -f "$PAT"',
    'pkill -f "${PAT}"',
    'pkill -f "$(echo TOK)"',
    "pkill -f $(echo TOK)",
    'pkill -f "`echo TOK`"',
    "pkill -f ${VAR}",
    "pkill -f $PAT",
    "pkill -f $1",
    "pkill -f $$",
    'pkill -f "a${B}c"',
    "pkill -u $USER -f TOK",
    'pkill -u "$USER" -f TOK',
    "pkill -u ${USER} -f TOK",
    "pkill -U $(id -u) -f TOK",
    "pkill -g $PGID -f TOK",
    "pkill -P $PARENT -f TOK",
    'killall -r "$P"',
    "killall -u $USER TOK",
    "killall $NAME",
]


@pytest.mark.parametrize( "command", _UNREADABLE_FORMS )
def test_an_expansion_the_guard_cannot_read_is_refused_without_a_probe( command, worktree ):
    spy    = _Spy()
    reason = _run_real( command, worktree, spy )
    assert reason is not None
    assert "cannot read" in reason
    assert "LUPIN_ALLOW_UNSCOPED_KILL=1" in reason
    assert spy.selectors == []


_READABLE_DOLLARS = [
    ( f"pkill -f '{_NONE}$b'",       [ [ "-f", f"{_NONE}$b" ] ] ),
    ( f'pkill -f "{_NONE}$"',        [ [ "-f", f"{_NONE}$" ] ] ),
    ( f"pkill -f {_NONE}$",          [ [ "-f", f"{_NONE}$" ] ] ),
    ( f"pkill -f {_NONE}\\$bar",    [ [ "-f", f"{_NONE}$bar" ] ] ),
    ( f'pkill -f "{_NONE}$|{_NONE}2$"', [ [ "-f", f"{_NONE}$|{_NONE}2$" ] ] ),
    ( f"pkill -f '{_NONE}$(not run)'", [ [ "-f", f"{_NONE}$(not run)" ] ] ),
    ( f"pkill -f '{_NONE}`y`'",      [ [ "-f", f"{_NONE}`y`" ] ] ),
    ( f'pkill -f "{_NONE}$\'x\'"',    [ [ "-f", f"{_NONE}$'x'" ] ] ),
]


@pytest.mark.parametrize( "command, selectors", _READABLE_DOLLARS )
def test_a_dollar_that_is_not_an_expansion_is_a_pattern( command, selectors, worktree ):
    spy = _Spy()
    assert _run_real( command, worktree, spy ) is None
    assert spy.selectors == selectors


def test_own_children_scoping_still_comes_before_the_expansion_check( worktree ):
    spy = _Spy()
    assert _run_real( 'pkill -P $$ -f "$PAT"', worktree, spy ) is None
    assert spy.selectors == []


# ---------------------------------------------------------------------------
# The command word is judged by its basename, wherever a command can start
# ---------------------------------------------------------------------------

_COMMAND_FORMS = [
    "pkill -f TOK",
    "/usr/bin/pkill -f TOK",
    "/bin/killall -q TOK",
    r"\pkill -f TOK",
    '"pkill" -f TOK',
    "'/usr/bin/pkill' -f TOK",
    "command pkill -f TOK",
    "env -i pkill -f TOK",
    "env -u X pkill -f TOK",
    "env FOO=1 pkill -f TOK",
    "sudo -n pkill -f TOK",
    "sudo -E pkill -f TOK",
    "sudo -u root pkill -f TOK",
    "nice -n 5 pkill -f TOK",
    "ionice -c3 pkill -f TOK",
    "stdbuf -oL pkill -f TOK",
    "time pkill -f TOK",
    "nohup pkill -f TOK &",
    "doas pkill -f TOK",
    "if true; then pkill -f TOK; fi",
    "if true; then echo x; else pkill -f TOK; fi",
    "if pkill -f TOK; then echo gone; fi",
    "! pkill -f TOK",
    "case x in x) pkill -f TOK ;; esac",
    "while true; do pkill -f TOK; done",
    "true && pkill -f TOK",
    "true || pkill -f TOK",
    "echo x | pkill -f TOK",
    "(pkill -f TOK)",
    "{ pkill -f TOK; }",
    "echo a\npkill -f TOK",
]


@pytest.mark.parametrize( "command", _COMMAND_FORMS, ids=[ c.replace( "\n", "\\n" ) for c in _COMMAND_FORMS ] )
def test_a_command_word_named_pkill_is_a_sweep_wherever_a_command_can_start( command, worktree, elsewhere ):
    proc   = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    reason = _guard( command, [ 700 ], proc, worktree )
    assert reason is not None
    assert "700" in reason


_NOT_COMMANDS = [
    "echo pkill -f TOK",
    "echo /usr/bin/pkill -f TOK",
    "grep pkill notes.txt",
    "env FOO=1 grep pkill TOK",
    "sudo -u root grep pkill TOK",
    "man pkill",
    "which pkill",
    "cat pkill-notes.txt",
    "pkill-helper -f TOK",
    "mypkill -f TOK",
    "git commit -m 'pkill -f TOK'",
    "ls /usr/bin/pkill",
    "echo wow! pkill -f TOK",
]


@pytest.mark.parametrize( "command", _NOT_COMMANDS )
def test_a_word_named_pkill_that_is_not_a_command_is_not_a_sweep( command, worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( command, [ 700 ], proc, worktree ) is None


# ---------------------------------------------------------------------------
# A prefix value is read the way a shell word is: quoted spans and escapes belong to it
# ---------------------------------------------------------------------------

_QUOTED_PREFIX_FORMS = [
    'FOO="a b" pkill -f TOK',
    "FOO='a b' pkill -f TOK",
    r"FOO=a\ b pkill -f TOK",
    'A="a b" B=c sudo pkill -f TOK',
    'env A="a b" pkill -f TOK',
    "env 'A=b' pkill -f TOK",
    'timeout "5" pkill -f TOK',
    # forms that were refused before and must stay refused
    "FOO=x pkill -f TOK",
    'sudo -u "root" pkill -f TOK',
    'nice -n "5" pkill -f TOK',
    # the same words, a little further in
    'sudo -u "a b" pkill -f TOK',
    'env -u "A B" pkill -f TOK',
    'FOO="a  b" BAR=\'c d\' env X="e f" nice -n "5" pkill -f TOK',
    'timeout -s KILL "5" pkill -f TOK',
    "FOO=\"a b\" /usr/bin/pkill -f TOK",
]


@pytest.mark.parametrize( "command", _QUOTED_PREFIX_FORMS )
def test_a_quoted_or_escaped_prefix_value_does_not_hide_a_sweep( command, worktree, elsewhere ):
    proc   = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    reason = _guard( command, [ 700 ], proc, worktree )
    assert reason is not None
    assert "700" in reason


@pytest.mark.parametrize( "command", [
    'FOO="a pkill -f TOK b" ls',
    "echo FOO=\"a b\" pkill -f TOK",
    'FOO="a b" ls pkill',
    "# FOO='it's' pkill -f TOK",
])
def test_a_quoted_prefix_value_that_holds_the_words_is_not_a_sweep( command, worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( command, [ 700 ], proc, worktree ) is None


def _real_guard_command( command, tree ):
    return kill_deny_reason( "Bash", { "command": command }, enabled=True, cwd=tree, caller_pid=os.getpid() )


@pytest.mark.parametrize( "template", [ 'FOO="a b" pkill -f "{}"', 'env A="a b" pkill -f "{}"' ] )
def test_driven_a_real_process_behind_a_quoted_prefix_is_refused_and_a_control_is_not( template, worktree, elsewhere ):
    token   = "kgprobe-" + uuid.uuid4().hex
    control = "kgprobe-" + uuid.uuid4().hex
    pid     = _spawn_orphan( elsewhere, token )
    try:
        reason = _real_guard_command( template.format( token ), worktree )
        assert reason is not None
        assert str( pid ) in reason
        assert _real_guard_command( template.format( control ), worktree ) is None
    finally:
        _stop( pid, token )


@pytest.mark.parametrize( "command", [
    "/bin/kill 4242", r"\kill 4242", "sudo -n kill 4242", "if true; then kill 4242; fi", "! kill 4242",
] )
def test_a_literal_kill_of_a_claude_pid_is_found_behind_the_same_prefixes( command ):
    reason = kill_deny_reason(
        "Bash", { "command": command }, enabled=True, comm_reader=lambda pid: CLAUDE_COMM,
    )
    assert reason is not None
    assert "4242" in reason


def test_a_listing_behind_a_path_still_feeds_a_kill_downstream():
    reason = kill_deny_reason(
        "Bash", { "command": "/usr/bin/pgrep -f TOK | xargs /bin/kill" }, enabled=True,
        comm_reader=lambda pid: "bash",
    )
    assert reason is not None


# ---------------------------------------------------------------------------
# killall: every name is probed, and a long name is probed on the kernel's 15
# ---------------------------------------------------------------------------

def _names_probe( matches ):
    """A probe that answers per selector and records every selector it saw."""
    seen = []
    def probe( selector ):
        seen.append( list( selector ) )
        return list( matches.get( tuple( selector ), [] ) )
    probe.seen = seen
    return probe


def test_killall_with_two_names_denies_when_only_the_first_matches( worktree, elsewhere ):
    probe = _names_probe( { ( "-x", "FIRST" ): [ "700" ] } )
    proc  = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    reason = kill_deny_reason(
        "Bash", { "command": "killall FIRST SECOND" }, enabled=True, comm_reader=_comm(),
        pgrep_probe=probe, cwd=worktree, proc=proc, caller_pid=CALLER,
    )
    assert reason is not None
    assert "700" in reason
    assert probe.seen == [ [ "-x", "FIRST" ], [ "-x", "SECOND" ] ]


def test_killall_with_two_names_denies_when_only_the_first_matches_a_seat_without_a_cwd():
    probe = _names_probe( { ( "-x", "FIRST" ): [ "700" ] } )
    reason = kill_deny_reason(
        "Bash", { "command": "killall FIRST SECOND" }, enabled=True,
        comm_reader=lambda pid: CLAUDE_COMM, pgrep_probe=probe,
    )
    assert reason is not None
    assert "700" in reason


def test_killall_without_a_cwd_still_reads_s_as_a_signal_and_probes_the_name():
    probe = _names_probe( {} )
    assert kill_deny_reason(
        "Bash", { "command": "killall -s TERM NAME" }, enabled=True,
        comm_reader=lambda pid: CLAUDE_COMM, pgrep_probe=probe,
    ) is None
    assert probe.seen == [ [ "-x", "NAME" ] ]


def test_a_killall_name_longer_than_the_kernel_comm_is_probed_on_its_first_15():
    assert kill_guard._sweep_selectors( "killall", " abcdefghijklmnopqrstuvwxyz" ) == [ [ "-x", "abcdefghijklmno" ] ]
    assert kill_guard._sweep_selectors( "killall", " -r abcdefghijklmnopqrstuvwxyz" ) == [ [ "abcdefghijklmnopqrstuvwxyz" ] ]


def test_driven_killall_of_a_name_longer_than_the_comm_finds_the_foreign_process( worktree, elsewhere, tmp_path ):
    long_name = "kgqlong" + uuid.uuid4().hex[ :14 ]         # 21 characters, comm keeps 15
    token     = "kgprobe-" + uuid.uuid4().hex
    pid       = _spawn_named( elsewhere, long_name, token, tmp_path )
    try:
        assert len( long_name ) > 15
        assert open( f"/proc/{pid}/comm" ).read().strip() == long_name[ :15 ]
        _denied_for( f"killall -q {long_name}", worktree, pid )
        control = "kgqnone" + uuid.uuid4().hex[ :14 ]
        assert kill_deny_reason(
            "Bash", { "command": f"killall -q {control}" }, enabled=True, cwd=worktree, caller_pid=os.getpid(),
        ) is None
    finally:
        _stop( pid, token )


# ---------------------------------------------------------------------------
# Ordinary trailers are not patterns: a comment, a here-string, a real-time signal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "command", [
    "pkill -f TOK # stop it",
    "pkill -f TOK <<< x",
    "pkill -f TOK <<<x",
    "pkill -RTMIN+1 -f TOK",
    "pkill -SIGRTMIN+1 -f TOK",
    "pkill -RTMAX-2 -f TOK",
] )
def test_a_comment_a_here_string_or_a_realtime_signal_is_not_part_of_the_pattern( command, worktree ):
    assert _selector_seen( command, worktree ) == [ "-f", "TOK" ]


def test_a_hash_inside_a_word_is_part_of_the_pattern( worktree ):
    assert _selector_seen( "pkill -f a#b", worktree ) == [ "-f", "a#b" ]


# ---------------------------------------------------------------------------
# The command matcher runs before every Bash call, so it must not backtrack
# ---------------------------------------------------------------------------

def _bounded( command, seconds=10 ):
    """Run the guard over `command` and return how long it took, failing instead of hanging."""
    import signal as signal_module
    def expired( *args ):
        raise _Expired( f"the guard did not finish within {seconds} s" )
    previous = signal_module.signal( signal_module.SIGALRM, expired )
    signal_module.alarm( seconds )
    started = time.perf_counter()
    try:
        kill_deny_reason(
            "Bash", { "command": command }, enabled=True, comm_reader=lambda pid: "bash",
            pgrep_probe=lambda selector: [],
        )
    finally:
        signal_module.alarm( 0 )
        signal_module.signal( signal_module.SIGALRM, previous )
    return time.perf_counter() - started


@pytest.mark.parametrize( "command", [
    " ".join( [ "sudo -n nice -n 5 env -i" ] * 60 ) + " ls",
    " ".join( [ "env -i FOO=1" ] * 200 ) + " ls",
    " ".join( [ "sudo -u root" ] * 200 ) + " ls",
    " ".join( [ "timeout 5 nice -n 1 ionice -c3" ] * 100 ) + " ls",
    "sudo " + " ".join( f"-o{i} v{i}" for i in range( 1000 ) ) + " ls",
    "env " + "-a b " * 500 + "-",
] )
def test_a_long_run_of_wrappers_and_options_does_not_backtrack( command ):
    assert _bounded( command ) < 2.0


# ---------------------------------------------------------------------------
# The guard is linear in the length of the command
# ---------------------------------------------------------------------------

def _ordinary_heredoc( size ):
    lines = max( size // 40, 1 )
    return "cat > notes.txt <<'EOF'\n" + "\n".join( f"ordinary line {i} of plain text" for i in range( lines ) ) + "\nEOF\n"


_LINEAR_SHAPES = {
    "newline run"          : lambda size: "\n" * size,
    "space run"            : lambda size: " " * size,
    "tab run"              : lambda size: "\t" * size,
    "mixed whitespace"     : lambda size: " \n\t" * ( size // 3 ),
    "letter then newlines" : lambda size: "x" + "\n" * size,
    "pkill then whitespace": lambda size: "pkill -f x" + " \n" * ( size // 2 ),
    "ordinary heredoc"     : _ordinary_heredoc,
    "pgrep one per line"   : lambda size: "pgrep x; " * ( size // 9 ),
    "pgrep pipeline"       : lambda size: "pgrep x | " * ( size // 10 ),
    "listings in quotes"   : lambda size: "echo 'a; pgrep x; " * ( size // 16 ),
    "for loops"            : lambda size: "for p in $(pgrep x); do echo $p; " * ( size // 34 ),
    "nested wrappers"      : lambda size: "sudo -n nice -n 5 env -i " * ( size // 24 ) + "ls",
    "quoted assignments"   : lambda size: 'FOO="a b" ' * ( size // 10 ) + "pkill -f x",
    "env quoted values"    : lambda size: 'env A="a b" ' * ( size // 12 ) + "pkill -f x",
    "escaped assignments"  : lambda size: r"FOO=a\ b " * ( size // 9 ) + "pkill -f x",
    "quoted wrapper values": lambda size: 'sudo -u "a b" ' * ( size // 14 ) + "pkill -f x",
    "unclosed quote run"   : lambda size: 'FOO="a ' * ( size // 7 ),
}


def _best_of( command, repeats=3, seconds=20 ):
    """The fastest of a few runs; an alarm fails a guard that will not finish instead of hanging."""
    import signal as signal_module
    def expired( *args ):
        raise _Expired( f"the guard did not finish within {seconds} s on {len( command )} characters" )
    previous = signal_module.signal( signal_module.SIGALRM, expired )
    best     = None
    try:
        for _ in range( repeats ):
            signal_module.alarm( seconds )
            started = time.perf_counter()
            kill_deny_reason(
                "Bash", { "command": command }, enabled=True, comm_reader=lambda pid: "bash",
                pgrep_probe=lambda selector: [],
            )
            elapsed = time.perf_counter() - started
            best    = elapsed if best is None else min( best, elapsed )
    finally:
        signal_module.alarm( 0 )
        signal_module.signal( signal_module.SIGALRM, previous )
    return best


@pytest.mark.parametrize( "shape", sorted( _LINEAR_SHAPES ) )
def test_the_guard_time_grows_in_proportion_to_the_command( shape ):
    """
    Doubling the command twice must cost about four times as much, not sixteen.

    A quadratic guard reads 16 here; a linear one reads 4. The bound is 9, so a loaded box
    does not make a linear guard fail, and a quadratic one never passes.
    """
    build = _LINEAR_SHAPES[ shape ]
    base  = 8000
    small = _best_of( build( base ) )
    large = _best_of( build( base * 4 ), repeats=1 )
    assert large / max( small, 0.002 ) < 9, f"{shape}: {small * 1000:.1f} ms -> {large * 1000:.1f} ms for 4x the input"


def test_a_4000_line_ordinary_heredoc_costs_well_under_a_second():
    command = _ordinary_heredoc( 4000 * 40 )
    assert command.count( "\n" ) > 4000
    assert _best_of( command ) < 1.0


_SIX_REGEXES = (
    "_KILL_LITERAL_RE", "_UNSCOPED_LISTING_RE", "_PATTERN_SWEEP_RE",
    "_KILL_SUBST_RE", "_KILL_VERB_RE", "_INLINE_FLAG_RE",
)
_WHITESPACE_SHAPES = {
    "newlines"        : lambda size: "\n" * size,
    "letter+newlines" : lambda size: "x" + "\n" * size,
    "mixed"           : lambda size: " \n\t" * ( size // 3 ),
    "crlf"            : lambda size: "\r\n" * ( size // 2 ),
    "spaces"          : lambda size: " " * size,
}


def _search_seconds( regex, text, seconds=20 ):
    """One `regex.search( text )`, failing instead of hanging when it will not finish."""
    import signal as signal_module
    def expired( *args ):
        raise _Expired( f"{regex.pattern[ :30 ]!r} did not finish within {seconds} s on {len( text )} characters" )
    previous = signal_module.signal( signal_module.SIGALRM, expired )
    try:
        signal_module.alarm( seconds )
        started = time.perf_counter()
        regex.search( text )
        return time.perf_counter() - started
    finally:
        signal_module.alarm( 0 )
        signal_module.signal( signal_module.SIGALRM, previous )


@pytest.mark.parametrize( "shape", sorted( _WHITESPACE_SHAPES ) )
@pytest.mark.parametrize( "name", _SIX_REGEXES )
def test_each_module_regex_is_linear_on_a_whitespace_run( name, shape ):
    """The six regexes were each quadratic on a run of newlines: every one is pinned on its own."""
    regex = getattr( kill_guard, name )
    build = _WHITESPACE_SHAPES[ shape ]
    small = min( _search_seconds( regex, build( 8000 ) ) for _ in range( 3 ) )
    large = _search_seconds( regex, build( 32000 ) )
    assert large / max( small, 0.002 ) < 9, f"{name} on {shape}: {small * 1000:.1f} ms -> {large * 1000:.1f} ms for 4x"


# ---------------------------------------------------------------------------
# A wrapper is judged by its basename too (`/usr/bin/sudo`, `\sudo`, `~/bin/pkill`)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "command", [
    "/usr/bin/sudo pkill -f TOK",
    r"\sudo pkill -f TOK",
    "/usr/bin/sudo -n /usr/bin/env -i pkill -f TOK",
    "~/bin/pkill -f TOK",
    "/usr/bin/sudo ~/bin/pkill -f TOK",
    "/usr/bin/nice -n 5 pkill -f TOK",
    "'/usr/bin/sudo' pkill -f TOK",
] )
def test_a_wrapper_with_a_path_or_a_tilde_does_not_hide_a_sweep( command, worktree, elsewhere ):
    proc   = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    reason = _guard( command, [ 700 ], proc, worktree )
    assert reason is not None
    assert "700" in reason


def test_a_path_wrapper_does_not_turn_an_argument_into_a_command( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( "/usr/bin/sudo -u root grep pkill TOK", [ 700 ], proc, worktree ) is None


# ---------------------------------------------------------------------------
# A quoted mention is text, not a command
# ---------------------------------------------------------------------------

def _mention_forms( repeats ):
    """Commit-message shapes that only talk about a sweep, at `repeats` mentions."""
    many = lambda piece: piece * repeats
    return {
        "double-quoted listing"   : 'git commit -m "note: ' + many( "pgrep -f foo; " ) + 'done"',
        "double-quoted pipeline"  : 'git commit -m "' + many( "run pgrep -f foo | xargs kill; " ) + 'done"',
        "single-quoted listing"   : "git commit -m '" + many( "pgrep -f foo; " ) + "done'",
        "single-quoted pipeline"  : "git commit -m '" + many( "pgrep -f foo | xargs kill; " ) + "done'",
        "escaped inner quotes"    : 'git commit -m "see ' + many( '\\"pgrep -f foo\\"; ' ) + 'done"',
        "pkill mentions"          : 'git commit -m "' + many( "ran pkill -f foo; " ) + 'done"',
        "kill mentions"           : "git commit -m '" + many( "then kill 4242; " ) + "done'",
        "loop mentions"           : "git commit -m '" + many( "for p in $(pgrep foo); do kill $p; done; " ) + "done'",
        "echo then real command"  : "echo '" + many( "pgrep -f foo; " ) + "' && ls",
    }


def _never_probed( selector ):
    raise AssertionError( f"a quoted mention reached pgrep: {selector!r}" )


@pytest.mark.parametrize( "repeats", [ 60, 600 ] )
@pytest.mark.parametrize( "form", sorted( _mention_forms( 1 ) ) )
def test_a_quoted_mention_of_a_sweep_is_allowed_and_cheap( form, repeats, worktree ):
    command = _mention_forms( repeats )[ form ]
    started = time.perf_counter()
    reason  = kill_deny_reason(
        "Bash", { "command": command }, enabled=True, comm_reader=lambda pid: CLAUDE_COMM,
        pgrep_probe=_never_probed, cwd=worktree, proc=FakeProc(), caller_pid=CALLER,
    )
    assert reason is None
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize( "command", [
    "echo \\'; pgrep x | xargs kill; echo \\'",
    "echo \\\"; pgrep x | xargs kill; echo \\\"",
    "# it's here\npgrep x | xargs kill",
    "ls # don't\npgrep x | xargs kill",
    "echo 'a; pgrep x | xargs kill",
    "echo \"it's\"; pgrep x | xargs kill; echo \"ok\"",
    "echo \"$(pgrep x | xargs kill)\"",
    "echo \"`pgrep x | xargs kill`\"",
    "git commit -m 'note'; pgrep x | xargs kill",
    "git commit -m \"a\" && pgrep x | xargs kill",
] )
def test_a_real_sweep_beside_quotes_is_still_refused( command, worktree ):
    reason = kill_deny_reason(
        "Bash", { "command": command }, enabled=True, comm_reader=lambda pid: "bash",
        pgrep_probe=lambda selector: [], cwd=worktree, proc=FakeProc(), caller_pid=CALLER,
    )
    assert reason is not None


@pytest.mark.parametrize( "command", [
    "echo \\'; pkill -f TOK; echo \\'",
    "# it's\npkill -f TOK",
    "echo \"it's\"; pkill -f TOK; echo \"ok\"",
    "echo \"$(pkill -f TOK)\"",
    "git commit -m 'x'; pkill -f TOK",
] )
def test_a_real_pkill_beside_quotes_still_reaches_the_ownership_check( command, worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    assert _guard( command, [ 700 ], proc, worktree ) is not None


@pytest.mark.parametrize( "command, spans", [
    ( "echo 'a b' \"c d\"",              [ ( 5, 10, "'" ), ( 11, 16, '"' ) ] ),
    ( "echo \\'x\\'",                    [] ),
    ( "echo 'a\\'",                      [ ( 5, 9, "'" ) ] ),
    ( "echo \"a\\\"b\"",                 [ ( 5, 11, '"' ) ] ),
    ( "ls # it's\necho 'x'",             [ ( 15, 18, "'" ) ] ),
    ( "echo 'unterminated",              [] ),
    ( "echo $'a\\'b'",                   [ ( 6, 12, "'" ) ] ),
] )
def test_quote_spans_follow_the_shell( command, spans ):
    assert [ ( a, b, q ) for a, b, q, _ in kill_guard._quote_spans( command ) ] == spans


def test_a_double_quoted_span_with_a_substitution_is_live_and_one_without_is_a_mention():
    plain = kill_guard._quote_spans( 'echo "a; pgrep x"' )
    live  = kill_guard._quote_spans( 'echo "a; $(pgrep x)"' )
    tick  = kill_guard._quote_spans( 'echo "a; `pgrep x`"' )
    assert kill_guard._is_mention( 'echo "a; pgrep x"', 10 ) is True
    assert kill_guard._is_mention( 'echo "a; $(pgrep x)"', 10 ) is False
    assert kill_guard._is_mention( 'echo "a; `pgrep x`"', 10 ) is False
    assert kill_guard._is_mention( "echo 'a; $(pgrep x)'", 10 ) is True
    assert kill_guard._is_mention( "echo 'a'; pgrep x", 12 ) is False
    assert ( len( plain ), len( live ), len( tick ) ) == ( 1, 1, 1 )


@pytest.mark.parametrize( "command", [
    '"pkill" -f TOK',
    "'pkill' -f TOK",
    '"/usr/bin/pkill" -f TOK',
    'true; "pkill" -f TOK',
    "sudo 'pkill' -f TOK",
    'if true; then "/usr/bin/pkill" -f TOK; fi',
] )
def test_a_quoted_command_word_is_a_sweep_not_a_mention( command, worktree, elsewhere ):
    """The quotes sit around the verb itself; the command still starts outside them."""
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    reason = _guard( command, [ 700 ], proc, worktree )
    assert reason is not None
    assert "700" in reason


def test_a_hatch_that_is_only_mentioned_does_not_open_the_guard( worktree, elsewhere ):
    proc = FakeProc( ppids={ 700: 1 }, cwds={ 700: elsewhere } )
    command = "echo 'x; LUPIN_ALLOW_UNSCOPED_KILL=1 pkill'; pkill -f TOK"
    assert _guard( command, [ 700 ], proc, worktree ) is not None
    assert kill_guard._hatch_in_prefix( command ) is False
    assert kill_guard._hatch_in_prefix( "LUPIN_ALLOW_UNSCOPED_KILL=1 pkill -f TOK" ) is True


def test_a_mention_is_skipped_on_the_claude_only_path_and_for_a_kill_substitution():
    seat = lambda pid: CLAUDE_COMM
    for command in ( "echo 'then pkill -f foo'", "echo 'x; kill $(pgrep foo)'" ):
        assert kill_deny_reason(
            "Bash", { "command": command }, enabled=True, comm_reader=seat, pgrep_probe=_never_probed,
        ) is None
    assert kill_deny_reason(
        "Bash", { "command": "kill $(pgrep foo)" }, enabled=True, comm_reader=lambda pid: "bash",
    ) is not None
