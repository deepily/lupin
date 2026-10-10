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
    ( 'pkill -f "has (parens) and `tick`"',  [ "-f", "has (parens) and `tick`" ] ),
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
    ( f"killall -q {_NONE}",               "resolved", [ [ "-x", _NONE ] ] ),
    ( f"killall -e {_NONE}",               "resolved", [ [ "-x", _NONE ] ] ),
    ( f"killall -v -w -i -l {_NONE}",      "resolved", [ [ "-x", _NONE ] ] ),
    ( f"killall -y 5m {_NONE}",            "resolved", [ [ "-x", _NONE ] ] ),
    ( f"killall -o 5m {_NONE}",            "resolved", [ [ "-x", _NONE ] ] ),
    ( f"killall -Z ctx {_NONE}",           "resolved", [ [ "-x", _NONE ] ] ),
    ( f"killall -g {_NONE}",               "resolved", [ [ "-x", _NONE ] ] ),
    ( f"killall -s TERM {_NONE}",          "resolved", [ [ "-x", _NONE ] ] ),
    ( f"killall -TERM {_NONE}",            "resolved", [ [ "-x", _NONE ] ] ),
    ( f"killall -9 {_NONE}",               "resolved", [ [ "-x", _NONE ] ] ),
    ( f"killall -u 0 {_NONE}",             "resolved", [ [ "-x", "-u", "0", _NONE ] ] ),
    ( f"killall -I {_NONE}",               "resolved", [ [ "-x", "-i", _NONE ] ] ),
    ( f"killall -r {_NONE}.*",             "resolved", [ [ f"{_NONE}.*" ] ] ),
    ( f"killall {_NONE}-a {_NONE}-b",      "resolved", [ [ "-x", f"{_NONE}-a" ], [ "-x", f"{_NONE}-b" ] ] ),
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
        assert "rejected" in reason
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
