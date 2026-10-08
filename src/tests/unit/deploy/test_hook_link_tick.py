"""
The timed git hook link check: the shell script looks and the Python module reports.

The shell half runs against scratch repositories under `tmp_path`, never the real hooks folder. Delivery goes
to a stub HTTP server on a thread, never the real notification server. The python half is called directly
with injected seams so every branch is reached.

Venue: :7999-eligible. No real notification, no crontab write (a stub stands in for `crontab`), no docker.
"""
import datetime
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import types

import pytest

import cosa.utils.hook_link_tick as hlt
import cosa.utils.util as cu

ROOT   = cu.get_project_root()
SCRIPT = f"{ROOT}/src/scripts/hook-link-tick.sh"
LIB    = f"{ROOT}/src/scripts/lib/preflight-vm-lib.sh"
HOOKS  = ( ( "pre-commit", "pre-commit-chain.sh" ), ( "pre-push", "pre-push-chain.sh" ) )
NOW    = datetime.datetime( 2026, 10, 8, 12, 0, 0, tzinfo=datetime.timezone.utc )


# ── scratch repositories ────────────────────────────────────────────────────

def _git( cwd, *args ):
    return subprocess.run( [ "git", "-C", str( cwd ), "-c", "user.name=t", "-c", "user.email=t@t", *args ],
                           capture_output=True, text=True, check=True ).stdout.strip()


def _repo( tmp_path, name="repo", link=True ):
    """A scratch checkout with both chain scripts and, when link is set, both hooks linked."""
    repo    = tmp_path / name
    scripts = repo / "src" / "scripts"
    scripts.mkdir( parents=True )
    subprocess.run( [ "git", "init", "-q", str( repo ) ], check=True )
    for _, script in HOOKS:
        ( scripts / script ).write_text( "#!/usr/bin/env bash\nexit 0\n" ); ( scripts / script ).chmod( 0o755 )
    if link:
        for hook, script in HOOKS: os.symlink( f"../../src/scripts/{script}", repo / ".git" / "hooks" / hook )
    return repo


def _tick( tmp_path, repo, *args, env=None, deliver=False, cwd=None, bare=False ):
    """Run the real tick script on a scratch checkout; delivery is off unless a test turns it on."""
    base = { "PATH": "/usr/bin:/bin" } if bare else dict( os.environ )
    full = { **base, "HOME": str( tmp_path / "home" ), "HOOK_LINK_STATE": str( tmp_path / "state.json" ),
             "LUPIN_DEV_EMAIL": "rick@example.test" }
    if repo is not None: full[ "HOOK_LINK_REPO" ] = str( repo )
    if not deliver: full[ "HOOK_LINK_DELIVER" ] = "0"
    full.update( env or {} )
    ( tmp_path / "home" ).mkdir( exist_ok=True )
    return subprocess.run( [ "bash", SCRIPT, *args ], capture_output=True, text=True, timeout=60, env=full, cwd=cwd )


def _listing( folder ):
    """Every entry under a folder with its link text and mtime, for a before and after check."""
    rows = []
    for name in sorted( os.listdir( folder ) ):
        path = os.path.join( folder, name )
        st   = os.lstat( path )
        rows.append( ( name, os.readlink( path ) if os.path.islink( path ) else None, st.st_mtime_ns, st.st_size ) )
    return rows


# ── a stub notification server ─────────────────────────────────────────────

class _Stub:
    def __init__( self, notify_status=200, dm_status=201 ):
        self.seen = []
        outer     = self

        class Handler( http.server.BaseHTTPRequestHandler ):
            def do_POST( self ):
                length = int( self.headers.get( "Content-Length", 0 ) )
                outer.seen.append( ( self.path, self.rfile.read( length ).decode() ) )
                status = notify_status if self.path.startswith( "/api/notify" ) else dm_status
                self.send_response( status ); self.end_headers(); self.wfile.write( b"{}" )

            def log_message( self, *a ): pass

        self.server = http.server.HTTPServer( ( "127.0.0.1", 0 ), Handler )
        self.base   = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread( target=self.server.serve_forever, daemon=True ).start()

    def close( self ):
        self.server.shutdown(); self.server.server_close()


@pytest.fixture
def stub():
    made = []
    def make( **kw ):
        s = _Stub( **kw ); made.append( s ); return s
    yield make
    for s in made: s.close()


# ── 1. a clean run says nothing ─────────────────────────────────────────────

def test_clean_hooks_print_nothing_and_exit_zero( tmp_path ):
    r = _tick( tmp_path, _repo( tmp_path ) )
    assert ( r.returncode, r.stdout, r.stderr ) == ( 0, "", "" )


def test_relative_and_absolute_links_to_the_right_script_stay_clean( tmp_path ):
    repo = _repo( tmp_path )
    for hook, script in HOOKS:
        ( repo / ".git" / "hooks" / hook ).unlink()
        os.symlink( str( repo / "src" / "scripts" / script ), repo / ".git" / "hooks" / hook )
    assert _tick( tmp_path, repo ).returncode == 0


# ── 2. each broken state gets its own word, exit 2 and a message naming the hook ──────────────

def _break( repo, how ):
    hook, hooks = "pre-push", repo / ".git" / "hooks"
    link        = hooks / hook
    if how == "ABSENT":   link.unlink()
    elif how == "NOT_LINK":
        link.unlink(); link.write_text( "#!/bin/sh\n" ); link.chmod( 0o755 )
    elif how == "WRONG_TARGET":   # a different file that is still inside the checkout
        other = repo / "src" / "other.sh"; other.write_text( "#!/bin/sh\n" )
        link.unlink(); os.symlink( str( other ), link )
    elif how == "DANGLING_FILE":   # the folder is there, the file is not
        link.unlink(); os.symlink( str( repo / "src" / "scripts" / "gone.sh" ), link )
    elif how == "DANGLING_DIR":    # the whole folder is gone
        link.unlink(); os.symlink( str( repo / "nowhere" / "gone.sh" ), link )
    elif how == "OUTSIDE":
        outside = repo.parent / "outside" / "pre-push-chain.sh"; outside.parent.mkdir( exist_ok=True ); outside.write_text( "#!/bin/sh\n" )
        link.unlink(); os.symlink( str( outside ), link )
    elif how == "NOT_EXECUTABLE":
        ( repo / "src" / "scripts" / "pre-push-chain.sh" ).chmod( 0o644 )
    return hook


@pytest.mark.parametrize( "how,word", [
    ( "ABSENT", "ABSENT" ), ( "NOT_LINK", "NOT_LINK" ), ( "WRONG_TARGET", "WRONG_TARGET" ),
    ( "DANGLING_FILE", "DANGLING" ), ( "DANGLING_DIR", "DANGLING" ), ( "OUTSIDE", "OUTSIDE" ),
    ( "NOT_EXECUTABLE", "NOT_EXECUTABLE" ),
] )
def test_each_broken_state_is_reported_under_its_own_word( tmp_path, how, word ):
    repo = _repo( tmp_path )
    hook = _break( repo, how )
    r    = _tick( tmp_path, repo )

    assert r.returncode == 5, r.stdout + r.stderr
    assert "1 finding(s)" in r.stdout
    line = [ l for l in r.stdout.splitlines() if l.startswith( f"  hook {hook} " ) ][ 0 ]
    assert { "ABSENT": "not installed", "NOT_LINK": "copied file", "WRONG_TARGET": "not to the script this checkout ships",
             "DANGLING": "dangling link", "OUTSIDE": "outside the checkout", "NOT_EXECUTABLE": "no executable bit" }[ word ] in line
    assert "pre-commit" not in r.stdout.split( "remedy" )[ 0 ].replace( "pre-commit-chain", "" ), "only the broken hook should be named"


def test_a_dangling_link_in_both_flavours_names_where_it_points( tmp_path ):
    repo = _repo( tmp_path )
    _break( repo, "DANGLING_DIR" )
    assert str( repo / "nowhere" / "gone.sh" ) in _tick( tmp_path, repo ).stdout


def test_outside_names_the_path_it_lands_at( tmp_path ):
    repo = _repo( tmp_path )
    _break( repo, "OUTSIDE" )
    assert str( repo.parent / "outside" / "pre-push-chain.sh" ) in _tick( tmp_path, repo ).stdout


def test_two_broken_hooks_give_two_findings( tmp_path ):
    repo = _repo( tmp_path )
    for hook, _ in HOOKS: ( repo / ".git" / "hooks" / hook ).unlink()
    r = _tick( tmp_path, repo )
    assert r.returncode == 5 and "2 finding(s)" in r.stdout
    assert [ h for h, _ in HOOKS if f"hook {h} is not installed" in r.stdout ] == [ h for h, _ in HOOKS ]


# ── 4 and 5. the quiet window and the fingerprint ───────────────────────────────────────────

def test_an_unchanged_finding_inside_the_quiet_window_is_not_sent_again( tmp_path, stub ):
    repo, s = _repo( tmp_path ), stub()
    ( repo / ".git" / "hooks" / "pre-push" ).unlink()
    env     = { "HOOK_LINK_API_BASE": s.base }
    first   = _tick( tmp_path, repo, env=env, deliver=True )
    again   = _tick( tmp_path, repo, env=env, deliver=True )

    assert first.returncode == 2 and again.returncode == 4
    assert len( [ p for p, _ in s.seen if p.startswith( "/api/notify" ) ] ) == 1
    assert "not re-sending" in again.stdout


def test_a_second_broken_hook_is_sent_at_once_inside_the_window( tmp_path, stub ):
    repo, s = _repo( tmp_path ), stub()
    env     = { "HOOK_LINK_API_BASE": s.base }
    ( repo / ".git" / "hooks" / "pre-push" ).unlink()
    assert _tick( tmp_path, repo, env=env, deliver=True ).returncode == 2
    ( repo / ".git" / "hooks" / "pre-commit" ).unlink()
    second = _tick( tmp_path, repo, env=env, deliver=True )

    assert second.returncode == 2
    assert "trigger%3A+new+or+changed+findings" in s.seen[ 1 ][ 0 ], "the alarm should say why it was sent"
    assert len( [ p for p, _ in s.seen if p.startswith( "/api/notify" ) ] ) == 2


def test_the_same_count_of_a_different_finding_is_also_sent( tmp_path, stub ):
    repo, s = _repo( tmp_path ), stub()
    env     = { "HOOK_LINK_API_BASE": s.base }
    ( repo / ".git" / "hooks" / "pre-push" ).unlink()
    assert _tick( tmp_path, repo, env=env, deliver=True ).returncode == 2
    os.symlink( "../../src/scripts/pre-push-chain.sh", repo / ".git" / "hooks" / "pre-push" )
    ( repo / ".git" / "hooks" / "pre-commit" ).unlink()

    assert _tick( tmp_path, repo, env=env, deliver=True ).returncode == 2
    assert len( [ p for p, _ in s.seen if p.startswith( "/api/notify" ) ] ) == 2


def test_the_window_ends_and_the_same_finding_is_sent_again( tmp_path, stub ):
    repo, s = _repo( tmp_path ), stub()
    env     = { "HOOK_LINK_API_BASE": s.base, "HOOK_LINK_RESEND_HOURS": "0" }
    ( repo / ".git" / "hooks" / "pre-push" ).unlink()
    assert _tick( tmp_path, repo, env=env, deliver=True ).returncode == 2
    assert _tick( tmp_path, repo, env=env, deliver=True ).returncode == 2
    assert len( [ p for p, _ in s.seen if p.startswith( "/api/notify" ) ] ) == 2


# ── 6. a failed delivery exits 3 and leaves the fingerprint behind ─────────────────────────

def test_a_failed_delivery_exits_three_and_the_next_tick_retries( tmp_path, stub ):
    repo = _repo( tmp_path )
    ( repo / ".git" / "hooks" / "pre-push" ).unlink()
    bad  = stub( notify_status=500 )
    r    = _tick( tmp_path, repo, env={ "HOOK_LINK_API_BASE": bad.base }, deliver=True )

    assert r.returncode == 3 and "DELIVERY FAILED" in r.stderr
    assert not ( tmp_path / "state.json" ).exists()
    good = stub()
    assert _tick( tmp_path, repo, env={ "HOOK_LINK_API_BASE": good.base }, deliver=True ).returncode == 2
    assert ( tmp_path / "state.json" ).exists()


def test_a_dead_server_is_a_failed_delivery_not_a_crash( tmp_path ):
    repo = _repo( tmp_path )
    ( repo / ".git" / "hooks" / "pre-push" ).unlink()
    r    = _tick( tmp_path, repo, env={ "HOOK_LINK_API_BASE": "http://127.0.0.1:9" }, deliver=True )
    assert r.returncode == 3 and "DELIVERY FAILED" in r.stderr


def test_the_direct_message_goes_to_the_named_persona_and_is_marked_a_drill( tmp_path, stub ):
    repo, s = _repo( tmp_path ), stub()
    ( repo / ".git" / "hooks" / "pre-push" ).unlink()
    r       = _tick( tmp_path, repo, env={ "HOOK_LINK_API_BASE": s.base, "HOOK_LINK_DM": "mr radio" }, deliver=True )

    assert r.returncode == 2
    dm = [ json.loads( b ) for p, b in s.seen if p == "/api/dm/send" ][ 0 ]
    assert dm[ "recipient_persona" ] == "mr radio" and dm[ "sender_persona" ] == "hook link DRILL"
    assert "DRILL" in dm[ "body" ] and "pre-push" in dm[ "body" ]


# ── 7. a check that cannot look never reads as clean ───────────────────────────────────────

def test_a_folder_that_is_not_a_repository_exits_one( tmp_path ):
    plain = tmp_path / "plain"; plain.mkdir()
    r     = _tick( tmp_path, plain )
    assert r.returncode == 1 and "HOOK-LINK TICK ERROR" in r.stderr and r.stdout == ""


@pytest.mark.skipif( os.geteuid() == 0, reason="root reads any folder" )
def test_an_unreadable_hooks_folder_exits_one_not_zero( tmp_path ):
    repo  = _repo( tmp_path )
    hooks = repo / ".git" / "hooks"
    hooks.chmod( 0 )
    try:
        r = _tick( tmp_path, repo )
    finally:
        hooks.chmod( 0o755 )
    assert r.returncode == 1 and "not a readable directory" in r.stderr


def test_a_missing_library_exits_one( tmp_path ):
    scratch = tmp_path / "copy"; ( scratch / "src" / "scripts" ).mkdir( parents=True )
    shutil.copy( SCRIPT, scratch / "src" / "scripts" / "hook-link-tick.sh" )
    r = subprocess.run( [ "bash", str( scratch / "src" / "scripts" / "hook-link-tick.sh" ) ], capture_output=True, text=True, timeout=30,
                        env={ **os.environ, "HOOK_LINK_REPO": str( _repo( tmp_path ) ) } )
    assert r.returncode == 1 and "the library" in r.stderr


def test_git_missing_from_path_exits_one_and_says_so( tmp_path ):
    sandbox = tmp_path / "bin"; sandbox.mkdir()
    for tool in ( "dirname", "readlink" ): os.symlink( shutil.which( tool ), sandbox / tool )
    assert shutil.which( "git", path=str( sandbox ) ) is None, "the sandbox still has git, so the test proves nothing"
    r = subprocess.run( [ shutil.which( "bash" ), SCRIPT ], capture_output=True, text=True, timeout=30,
                        env={ "PATH": str( sandbox ), "HOOK_LINK_PATH": str( sandbox ), "HOME": str( tmp_path ), "HOOK_LINK_REPO": str( _repo( tmp_path ) ) } )
    assert r.returncode == 1 and "git is not on PATH" in r.stderr and r.stdout == ""


def test_an_unknown_option_exits_sixty_four( tmp_path ):
    r = _tick( tmp_path, None, "--nonsense" )
    assert r.returncode == 64 and "usage" in r.stderr


# ── 8 and 9. cron has no cwd, no LUPIN_ROOT and a bare PATH; seats share the main hooks ─────

def _own_copy( tmp_path ):
    """A checkout that holds its own copy of the tick, the way the main checkout does under cron."""
    repo = _repo( tmp_path, name="main" )
    ( repo / "src" / "scripts" / "lib" ).mkdir()
    shutil.copy( SCRIPT, repo / "src" / "scripts" / "hook-link-tick.sh" )
    shutil.copy( LIB, repo / "src" / "scripts" / "lib" / "preflight-vm-lib.sh" )
    os.symlink( f"{ROOT}/src/cosa", repo / "src" / "cosa" )
    if os.path.exists( f"{ROOT}/.venv" ): os.symlink( f"{ROOT}/.venv", repo / ".venv" )
    return repo


def test_a_bare_cron_environment_still_finds_the_main_checkout( tmp_path ):
    repo = _own_copy( tmp_path )
    ( repo / ".git" / "hooks" / "pre-push" ).unlink()
    ( tmp_path / "home" ).mkdir()
    r = subprocess.run( [ "bash", str( repo / "src" / "scripts" / "hook-link-tick.sh" ) ], capture_output=True, text=True, timeout=60, cwd="/",
                        env={ "PATH": "/usr/bin:/bin", "HOME": str( tmp_path / "home" ), "HOOK_LINK_DELIVER": "0",
                              "HOOK_LINK_STATE": str( tmp_path / "state.json" ) } )

    assert r.returncode == 5, r.stdout + r.stderr
    assert str( repo / ".git" / "hooks" ) in r.stdout and "DRILL" not in r.stdout


def test_run_from_a_linked_worktree_it_reads_the_shared_hooks_folder( tmp_path ):
    repo = _repo( tmp_path, name="main" )
    _git( repo, "add", "-A" ); _git( repo, "commit", "-q", "-m", "x" )
    linked = tmp_path / "linked"
    _git( repo, "worktree", "add", "-q", "--detach", str( linked ) )
    ( repo / ".git" / "hooks" / "pre-push" ).unlink()
    r = _tick( tmp_path, linked )

    assert r.returncode == 5 and str( repo / ".git" / "hooks" ) in r.stdout
    assert str( linked ) not in r.stdout.replace( str( repo ), "" )


def test_a_clean_main_stays_clean_when_looked_at_from_a_linked_worktree( tmp_path ):
    repo = _repo( tmp_path, name="main" )
    _git( repo, "add", "-A" ); _git( repo, "commit", "-q", "-m", "x" )
    linked = tmp_path / "linked"
    _git( repo, "worktree", "add", "-q", "--detach", str( linked ) )
    assert _tick( tmp_path, linked ).returncode == 0


# ── 10. a moved core.hooksPath is a finding and the moved folder is the one read ──────────

def test_a_moved_hooks_path_is_reported_and_the_moved_folder_is_read( tmp_path ):
    repo  = _repo( tmp_path )
    moved = tmp_path / "moved-hooks"; moved.mkdir()
    for hook, script in HOOKS: os.symlink( str( repo / "src" / "scripts" / script ), moved / hook )
    _git( repo, "config", "core.hooksPath", str( moved ) )
    r     = _tick( tmp_path, repo )

    assert r.returncode == 5 and "1 finding(s)" in r.stdout
    assert f"hook core.hooksPath points git at {moved}, not at this checkout's own hooks folder {repo / '.git' / 'hooks'}" in r.stdout


def test_a_moved_folder_that_is_empty_gives_the_move_plus_both_hooks_absent( tmp_path ):
    repo  = _repo( tmp_path )
    moved = tmp_path / "moved-hooks"; moved.mkdir()
    _git( repo, "config", "core.hooksPath", str( moved ) )
    r     = _tick( tmp_path, repo )
    assert r.returncode == 5 and "3 finding(s)" in r.stdout
    assert f"(folder read: {moved})" in r.stdout


def test_a_relative_hooks_path_inside_the_checkout_is_read_from_the_checkout( tmp_path ):
    repo = _repo( tmp_path )
    ( repo / "myhooks" ).mkdir()
    for hook, script in HOOKS: os.symlink( f"../src/scripts/{script}", repo / "myhooks" / hook )
    _git( repo, "config", "core.hooksPath", "myhooks" )
    r    = _tick( tmp_path, repo )
    assert r.returncode == 5 and "1 finding(s)" in r.stdout and "core.hooksPath" in r.stdout


# ── the reference-transaction hook ────────────────────────────────────────────────────────

def _ref( repo, text="#!/bin/sh\n# branch-guard: reference-transaction hook\n", mode=0o755 ):
    path = repo / ".git" / "hooks" / "reference-transaction"
    path.write_text( text ); path.chmod( mode )
    return path


def test_an_absent_reference_transaction_hook_is_not_a_finding( tmp_path ):
    assert _tick( tmp_path, _repo( tmp_path ) ).returncode == 0


def test_a_good_reference_transaction_hook_is_clean( tmp_path ):
    repo = _repo( tmp_path ); _ref( repo )
    assert _tick( tmp_path, repo ).returncode == 0


def test_a_reference_transaction_hook_without_the_executable_bit_is_a_finding( tmp_path ):
    repo = _repo( tmp_path ); _ref( repo, mode=0o644 )
    r    = _tick( tmp_path, repo )
    assert r.returncode == 5 and "hook reference-transaction is present but has no executable bit" in r.stdout


def test_a_reference_transaction_hook_without_its_marker_is_a_finding( tmp_path ):
    repo = _repo( tmp_path ); _ref( repo, text="#!/bin/sh\nexit 0\n" )
    r    = _tick( tmp_path, repo )
    assert r.returncode == 5 and "does not carry the branch-guard marker line" in r.stdout


def test_a_dangling_reference_transaction_link_is_a_finding( tmp_path ):
    repo = _repo( tmp_path )
    os.symlink( str( tmp_path / "gone" ), repo / ".git" / "hooks" / "reference-transaction" )
    r    = _tick( tmp_path, repo )
    assert r.returncode == 5 and "hook reference-transaction is a dangling link" in r.stdout


# ── 11. the tick never writes under the hooks folder ─────────────────────────────────────

def test_the_tick_never_changes_the_hooks_folder( tmp_path, stub ):
    repo, s = _repo( tmp_path ), stub()
    hooks   = repo / ".git" / "hooks"
    _break( repo, "DANGLING_FILE" ); _break( repo, "NOT_EXECUTABLE" ); _ref( repo, mode=0o644 )
    before  = _listing( hooks )
    r       = _tick( tmp_path, repo, env={ "HOOK_LINK_API_BASE": s.base }, deliver=True )

    assert r.returncode == 2
    assert _listing( hooks ) == before
    assert before, "the listing was empty, so the comparison would be vacuous"


# ── 13. the hazard is real: a dangling hook lets a commit through, and the tick flags that repository ──

def test_a_dangling_hook_lets_a_commit_through_and_the_tick_flags_it( tmp_path ):
    repo   = _repo( tmp_path, link=False )
    marker = tmp_path / "ran"
    chain  = repo / "src" / "scripts" / "pre-commit-chain.sh"
    chain.write_text( f"#!/usr/bin/env bash\ntouch '{marker}'\nexit 1\n" ); chain.chmod( 0o755 )
    ( repo / "f.txt" ).write_text( "x" ); _git( repo, "add", "f.txt" )

    os.symlink( "../../src/scripts/pre-commit-chain.sh", repo / ".git" / "hooks" / "pre-commit" )
    refused = subprocess.run( [ "git", "-C", str( repo ), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "a" ], capture_output=True )
    assert refused.returncode != 0 and marker.exists(), "the working hook should run and refuse"

    marker.unlink(); ( repo / ".git" / "hooks" / "pre-commit" ).unlink()
    os.symlink( "../../src/scripts/gone.sh", repo / ".git" / "hooks" / "pre-commit" )
    passed = subprocess.run( [ "git", "-C", str( repo ), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "a" ], capture_output=True )
    assert passed.returncode == 0 and not marker.exists(), "a dangling hook runs nothing and git raises no error"

    r = _tick( tmp_path, repo )
    assert r.returncode == 5 and "hook pre-commit is a dangling link" in r.stdout


# ── 12. install, status, uninstall ──────────────────────────────────────────────────────────

CRONTAB_STUB = """#!/usr/bin/env bash
# a stand-in for crontab: the file named by CRONTAB_FILE is the crontab
case "$1" in
    -l ) [ -f "$CRONTAB_FILE" ] && cat "$CRONTAB_FILE" || { echo "no crontab for x" >&2; exit 1; } ;;
    -  ) [ -n "${CRONTAB_FAIL:-}" ] && exit 1; cat > "$CRONTAB_FILE" ;;
esac
"""


@pytest.fixture
def cron( tmp_path ):
    stub = tmp_path / "crontab-stub"; stub.write_text( CRONTAB_STUB ); stub.chmod( 0o755 )
    file = tmp_path / "crontab.txt"
    file.write_text( "0 3 * * * /usr/bin/other-job\n" )
    repo = _own_copy( tmp_path )
    env  = { "HOOK_LINK_CRONTAB_CMD": str( stub ), "CRONTAB_FILE": str( file ), "HOOK_LINK_LOG": str( tmp_path / "log" / "t.log" ) }
    return types.SimpleNamespace( repo=repo, file=file, env=env, home=tmp_path / "home" )


def _cron( tmp_path, cron, *args, extra=None ):
    return _tick( tmp_path, cron.repo, *args, env={ **cron.env, **( extra or {} ) } )


def test_status_before_install_says_not_installed_and_exits_one( tmp_path, cron ):
    r = _cron( tmp_path, cron, "--status" )
    assert r.returncode == 1 and "NOT INSTALLED" in r.stdout


def test_install_writes_one_tagged_line_after_a_backup_and_keeps_the_other_job( tmp_path, cron ):
    r    = _cron( tmp_path, cron, "--install" )
    text = cron.file.read_text()

    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 3 * * * /usr/bin/other-job" in text and text.count( "# hook-link-tick" ) == 1
    assert f"{cron.repo}/src/scripts/hook-link-tick.sh" in text
    backups = list( ( cron.home / ".claude" ).glob( "crontab-backup-*.txt" ) )
    assert len( backups ) == 1 and backups[ 0 ].read_text() == "0 3 * * * /usr/bin/other-job\n"
    assert _cron( tmp_path, cron, "--status" ).returncode == 0


def test_install_twice_leaves_one_line( tmp_path, cron ):
    _cron( tmp_path, cron, "--install" ); first = cron.file.read_text()
    r = _cron( tmp_path, cron, "--install" )
    assert r.returncode == 0 and "already installed" in r.stdout
    assert cron.file.read_text() == first and first.count( "# hook-link-tick" ) == 1


def test_install_carries_the_persona_named_at_install_time( tmp_path, cron ):
    _cron( tmp_path, cron, "--install", extra={ "HOOK_LINK_DM": "mr radio" } )
    assert "HOOK_LINK_DM='mr radio' " in cron.file.read_text()


def test_install_refuses_when_the_backup_cannot_be_written( tmp_path, cron ):
    ( cron.home ).mkdir( exist_ok=True )
    ( cron.home / ".claude" ).write_text( "a file where the backup folder should be" )
    before = cron.file.read_text()
    r      = _cron( tmp_path, cron, "--install" )
    assert r.returncode == 1 and "ABORTED" in r.stderr and cron.file.read_text() == before


def test_install_reports_a_crontab_that_refuses_the_write( tmp_path, cron ):
    r = _cron( tmp_path, cron, "--install", extra={ "CRONTAB_FAIL": "1" } )
    assert r.returncode == 1 and "INSTALL FAILED" in r.stderr


def test_install_refuses_when_the_checkout_has_no_script( tmp_path, cron ):
    ( cron.repo / "src" / "scripts" / "hook-link-tick.sh" ).unlink()
    r = subprocess.run( [ "bash", SCRIPT, "--install" ], capture_output=True, text=True, timeout=30,
                        env={ **os.environ, **cron.env, "HOME": str( cron.home ), "HOOK_LINK_REPO": str( cron.repo ) } )
    assert r.returncode == 1 and "INSTALL REFUSED" in r.stderr and "hook-link-tick" not in cron.file.read_text()


def test_uninstall_removes_only_its_own_line_after_a_backup( tmp_path, cron ):
    _cron( tmp_path, cron, "--install" )
    r = _cron( tmp_path, cron, "--uninstall" )
    assert r.returncode == 0 and cron.file.read_text() == "0 3 * * * /usr/bin/other-job\n"
    assert len( list( ( cron.home / ".claude" ).glob( "crontab-backup-*.txt" ) ) ) >= 1


def test_uninstall_when_not_installed_removes_nothing( tmp_path, cron ):
    before = cron.file.read_text()
    r      = _cron( tmp_path, cron, "--uninstall" )
    assert r.returncode == 0 and "not installed" in r.stdout and cron.file.read_text() == before


def test_uninstall_aborts_when_the_backup_cannot_be_written( tmp_path, cron ):
    _cron( tmp_path, cron, "--install" )
    for p in ( cron.home / ".claude" ).glob( "crontab-backup-*.txt" ): p.unlink()
    shutil.rmtree( cron.home / ".claude" ); ( cron.home / ".claude" ).write_text( "blocked" )
    before = cron.file.read_text()
    r      = _cron( tmp_path, cron, "--uninstall" )
    assert r.returncode == 1 and "ABORTED" in r.stderr and cron.file.read_text() == before


def test_uninstall_reports_a_crontab_that_refuses_the_write( tmp_path, cron ):
    _cron( tmp_path, cron, "--install" )
    r = _cron( tmp_path, cron, "--uninstall", extra={ "CRONTAB_FAIL": "1" } )
    assert r.returncode == 1 and "UNINSTALL FAILED" in r.stderr


RECORDING_CRONTAB = """#!/usr/bin/env bash
echo "$@" >> "$CRONTAB_CALLS"
exit 0
"""


def test_a_bare_tick_never_calls_crontab( tmp_path ):
    stub  = tmp_path / "recording-crontab"; stub.write_text( RECORDING_CRONTAB ); stub.chmod( 0o755 )
    calls = tmp_path / "calls.txt"
    env   = { "HOOK_LINK_CRONTAB_CMD": str( stub ), "CRONTAB_CALLS": str( calls ) }
    clean, broken = _repo( tmp_path, name="clean" ), _repo( tmp_path, name="broken" )
    ( broken / ".git" / "hooks" / "pre-push" ).unlink()

    assert _tick( tmp_path, clean, env=env ).returncode == 0
    assert _tick( tmp_path, broken, env=env ).returncode == 5
    assert not calls.exists(), f"a bare tick called crontab: {calls.read_text() if calls.exists() else ''}"
    _tick( tmp_path, clean, "--status", env=env )
    assert calls.read_text().strip() == "-l", "the recording stub did not record, so the zero above proves nothing"


def test_print_install_prints_the_line_and_changes_nothing( tmp_path, cron ):
    before = cron.file.read_text()
    r      = _cron( tmp_path, cron, "--print-install" )
    assert r.returncode == 0 and "# hook-link-tick" in r.stdout and "--uninstall" in r.stdout
    assert cron.file.read_text() == before


# ── python half: parsing, wording, fingerprint, decision ─────────────────────────────────

def _f( hook="pre-push", word="ABSENT", folder="/h", lands="" ):
    return { "hook": hook, "word": word, "folder": folder, "lands": lands }


def test_read_findings_parses_four_and_three_field_lines_and_skips_blanks():
    got = hlt.read_findings( "pre-push\tABSENT\t/h\t\n\npre-commit\tWRONG_TARGET\t/h\t/x\nreference-transaction\tREF_NO_MARKER\t/h\n" )
    assert got == [ _f(), _f( "pre-commit", "WRONG_TARGET", "/h", "/x" ), _f( "reference-transaction", "REF_NO_MARKER" ) ]


def test_read_findings_refuses_a_short_line_by_name():
    with pytest.raises( ValueError, match="not a finding line: 'pre-push\\\\tABSENT'" ):
        hlt.read_findings( "pre-push\tABSENT" )


def test_every_state_word_the_shell_can_write_has_a_sentence():
    shell = open( SCRIPT ).read() + open( LIB ).read()
    words = [ "ABSENT", "NOT_LINK", "WRONG_TARGET", "DANGLING", "OUTSIDE", "NOT_EXECUTABLE", "NO_SCRIPT",
              "HOOKS_PATH_MOVED", "REF_NOT_EXECUTABLE", "REF_NO_MARKER" ]
    assert all( w in shell for w in words ), "a word was renamed in the shell, so this list is stale"
    assert sorted( hlt._SENTENCES ) == sorted( words )


def test_sentence_fills_the_landing_place_and_the_folder_and_says_nowhere_when_empty():
    assert hlt.sentence( _f( word="DANGLING", lands="/gone" ) ) == "is a dangling link to /gone: nothing exists there, so git runs no check"
    assert hlt.sentence( _f( word="OUTSIDE", lands="" ) ) == "links to nowhere, outside the checkout"
    assert hlt.sentence( _f( word="HOOKS_PATH_MOVED", folder="/m", lands="/own" ) ).startswith( "points git at /m, not at this checkout's own hooks folder /own" )


def test_an_unknown_state_word_is_named_not_hidden():
    assert hlt.sentence( _f( word="SURPRISE" ) ) == "is in state SURPRISE"


def test_fingerprint_ignores_order_and_sees_every_field():
    a, b = _f( "pre-push" ), _f( "pre-commit" )
    assert hlt.fingerprint( [ a, b ] ) == hlt.fingerprint( [ b, a ] )
    assert len( { hlt.fingerprint( [ x ] ) for x in ( a, _f( word="NOT_LINK" ), _f( folder="/other" ), _f( lands="/l" ), _f( "pre-commit" ) ) } ) == 5


def test_decide_sends_on_a_changed_fingerprint_even_inside_the_window():
    state = { "fingerprint": "old", "last_sent_ts": NOW.isoformat() }
    assert hlt.decide( "new", state, NOW, 6 ) == ( True, "new or changed findings" )


@pytest.mark.parametrize( "state", [ { "fingerprint": "fp" }, { "fingerprint": "fp", "last_sent_ts": "garbage" }, { "fingerprint": "fp", "last_sent_ts": None } ] )
def test_decide_sends_when_the_last_send_time_is_unreadable( state ):
    assert hlt.decide( "fp", state, NOW, 6 ) == ( True, "no readable last-send time" )


def test_decide_holds_inside_the_window_and_sends_at_its_edge():
    sent = ( NOW - datetime.timedelta( hours=5.9 ) ).isoformat()
    assert hlt.decide( "fp", { "fingerprint": "fp", "last_sent_ts": sent }, NOW, 6 )[ 0 ] is False
    sent = ( NOW - datetime.timedelta( hours=6 ) ).isoformat()
    send, why = hlt.decide( "fp", { "fingerprint": "fp", "last_sent_ts": sent }, NOW, 6 )
    assert send is True and "still open 6h after the last alarm" in why


def test_report_lines_mark_a_drill_and_count_the_findings():
    plain = hlt.report_lines( [ _f() ], NOW, False )
    drill = hlt.report_lines( [ _f(), _f( "pre-commit" ) ], NOW, True )
    assert plain[ 0 ].endswith( "1 finding(s)" ) and drill[ 0 ].endswith( "2 finding(s)  [DRILL]" )
    assert plain[ -1 ] == f"  remedy: {hlt.REMEDY}" and "hook pre-push is not installed" in plain[ 1 ]


def test_the_payload_names_the_hook_the_state_the_folder_and_the_remedy_and_nothing_from_the_environment( monkeypatch ):
    monkeypatch.setenv( "HOOK_LINK_SECRET_PROBE", "s3cret-value" )
    spoken, abstract, direct = hlt.build_payload( [ _f( "pre-push", "DANGLING", "/h", "/gone" ) ], "new or changed findings", False )
    for text in ( abstract, direct ): assert "pre-push" in text and "DANGLING" in text and "/h" in text and "install-git-hooks.sh" in text
    assert "s3cret-value" not in spoken + abstract + direct and "DRILL" not in spoken + abstract + direct
    assert "1 finding(s)" in spoken and "| pre-push | DANGLING | /h | /gone |" in abstract


def test_a_drill_payload_says_drill_in_all_three_places():
    spoken, abstract, direct = hlt.build_payload( [ _f() ], "x", True )
    assert spoken.startswith( "Drill" ) and abstract.startswith( "**DRILL" ) and direct.startswith( "[DRILL" )


# ── python half: transport ───────────────────────────────────────────────────────────────────

def test_post_query_and_post_json_reach_a_real_listener_and_return_status_and_text( stub ):
    s = stub()
    assert hlt.post_query( s.base, "k", "/api/notify", { "a": "b c" } ) == ( 200, "{}" )
    assert hlt.post_json( s.base, "k", "/api/dm/send", { "x": 1 } ) == ( 201, "{}" )
    assert s.seen[ 0 ][ 0 ] == "/api/notify?a=b+c" and json.loads( s.seen[ 1 ][ 1 ] ) == { "x": 1 }


def test_an_http_error_status_comes_back_as_data( stub ):
    assert hlt.post_json( stub( dm_status=503 ).base, "k", "/api/dm/send", {} )[ 0 ] == 503


def test_a_refused_connection_comes_back_as_status_zero():
    status, detail = hlt.post_json( "http://127.0.0.1:9", "k", "/x", {} )
    assert status == 0 and detail


def test_api_key_reads_through_the_hook_library( monkeypatch ):
    fake = types.ModuleType( "lupin_cli.claude_code.hooks.lib.task_store_client" ); fake.read_api_key = lambda: "the-key"
    monkeypatch.setitem( sys.modules, "lupin_cli.claude_code.hooks.lib.task_store_client", fake )
    assert hlt._api_key() == "the-key"


def test_notify_target_prefers_the_environment_then_the_config( monkeypatch ):
    assert hlt._notify_target( { "LUPIN_DEV_EMAIL": "a@b.test" } ) == "a@b.test"
    seen = []
    fake = types.ModuleType( "cosa.utils.config_loader" )
    fake.get_api_config = lambda env: seen.append( env ) or { "global_notification_recipient": "cfg@x.test" }
    monkeypatch.setitem( sys.modules, "cosa.utils.config_loader", fake )
    assert hlt._notify_target( { "LUPIN_ENV": "prod" } ) == "cfg@x.test" and seen == [ "prod" ]
    assert hlt._notify_target( {} ) == "cfg@x.test" and seen[ -1 ] == "local"


# ── python half: deliver ─────────────────────────────────────────────────────────────────────

class _Err:
    def __init__( self ): self.text = ""
    def write( self, s ): self.text += s; return len( s )
    def flush( self ): pass


def _seams( notify=200, dm=201, key="k", target="t@x.test" ):
    calls = []
    def query( base, k, path, params ): calls.append( ( "notify", base, k, params ) ); return notify, "n"
    def body( base, k, path, payload ): calls.append( ( "dm", base, k, payload ) ); return dm, "d"
    return calls, dict( query=query, body=body, api_key=lambda: key, target_of=lambda env: target )


def test_deliver_sends_one_notification_and_no_message_by_default( capsys ):
    calls, seams = _seams()
    assert hlt.deliver( [ _f() ], "why", False, {}, _Err(), **seams ) == { "notify": True }
    assert [ c[ 0 ] for c in calls ] == [ "notify" ] and calls[ 0 ][ 1 ] == hlt.DEFAULT_API_BASE
    assert calls[ 0 ][ 3 ][ "target_user" ] == "t@x.test" and calls[ 0 ][ 3 ][ "priority" ] == "high"
    assert "delivered (HTTP 200)" in capsys.readouterr().out


def test_deliver_sends_the_message_to_the_persona_and_strips_a_trailing_slash( capsys ):
    calls, seams = _seams()
    env = { "HOOK_LINK_DM": " mr radio ", "HOOK_LINK_API_BASE": "http://h:1/" }
    assert hlt.deliver( [ _f() ], "why", False, env, _Err(), channels=( "notify", "dm" ), **seams ) == { "notify": True, "dm": True }
    assert [ c[ 0 ] for c in calls ] == [ "notify", "dm" ] and calls[ 1 ][ 1 ] == "http://h:1"
    assert calls[ 1 ][ 3 ][ "recipient_persona" ] == "mr radio" and calls[ 1 ][ 3 ][ "sender_persona" ] == "hook link tick"
    assert "DM to mr radio: delivered (HTTP 201)" in capsys.readouterr().out


def test_deliver_sends_only_the_channels_it_is_asked_for():
    calls, seams = _seams()
    assert hlt.deliver( [ _f() ], "why", False, { "HOOK_LINK_DM": "p" }, _Err(), channels=( "dm", ), **seams ) == { "dm": True }
    assert [ c[ 0 ] for c in calls ] == [ "dm" ]


def test_deliver_reports_each_channel_on_its_own():
    err = _Err()
    calls, seams = _seams( notify=500, dm=500 )
    assert hlt.deliver( [ _f() ], "why", False, { "HOOK_LINK_DM": "p" }, err, channels=( "notify", "dm" ), **seams ) == { "notify": False, "dm": False }
    assert "notify to t@x.test: HTTP 500" in err.text and "DM to p: HTTP 500" in err.text
    calls, seams = _seams( dm=500 )
    assert hlt.deliver( [ _f() ], "why", False, { "HOOK_LINK_DM": "p" }, _Err(), channels=( "notify", "dm" ), **seams ) == { "notify": True, "dm": False }


def test_deliver_with_no_recipient_fails_and_sends_no_notification():
    err = _Err()
    calls, seams = _seams( target="" )
    assert hlt.deliver( [ _f() ], "why", False, {}, err, **seams ) == { "notify": False }
    assert calls == [] and "no target user" in err.text


def test_deliver_survives_a_key_reader_and_a_target_reader_that_raise():
    def boom(*a): raise RuntimeError( "x" )
    calls, seams = _seams()
    seams[ "api_key" ] = boom; seams[ "target_of" ] = boom
    err = _Err()
    assert hlt.deliver( [ _f() ], "why", False, {}, err, **seams ) == { "notify": False } and "no target user" in err.text
    seams[ "target_of" ] = lambda env: "t@x.test"
    assert hlt.deliver( [ _f() ], "why", False, {}, _Err(), **seams ) == { "notify": True } and calls[ 0 ][ 2 ] == ""


# ── python half: main ────────────────────────────────────────────────────────────────────────

FINDING = "pre-push\tABSENT\t/h\t\n"


def _file( tmp_path, text ):
    path = tmp_path / "findings.tsv"; path.write_text( text ); return str( path )


def _main( tmp_path, text, environ=None, now=NOW, **seams ):
    out, err = _Err(), _Err()
    env      = { "HOOK_LINK_STATE": str( tmp_path / "state" / "s.json" ), **( environ or {} ) }
    rc       = hlt.main( [ _file( tmp_path, text ) ], env, now, out, err, **seams )
    return rc, out.text, err.text


def _ledger( tmp_path ):
    return json.loads( ( tmp_path / "state" / "s.json" ).read_text() )[ "channels" ]


def test_main_needs_exactly_one_argument():
    err = _Err()
    assert hlt.main( [], {}, NOW, _Err(), err ) == 1 and "usage" in err.text
    assert hlt.main( [ "a", "b" ], {}, NOW, _Err(), _Err() ) == 1


def test_main_reads_sys_argv_and_os_environ_when_given_none( tmp_path, monkeypatch ):
    monkeypatch.setattr( sys, "argv", [ "x", _file( tmp_path, "" ) ] )
    assert hlt.main() == 0


def test_main_reports_an_unreadable_or_malformed_findings_file_as_exit_one( tmp_path ):
    err = _Err()
    assert hlt.main( [ str( tmp_path / "missing.tsv" ) ], {}, NOW, _Err(), err ) == 1 and "could not be read" in err.text
    rc, out, err = _main( tmp_path, "just-one-field\n" )
    assert rc == 1 and out == "" and "not a finding line" in err


def test_main_prints_nothing_for_an_empty_file( tmp_path ):
    assert _main( tmp_path, "" ) == ( 0, "", "" )


def test_main_delivers_writes_the_ledger_and_then_goes_quiet( tmp_path ):
    calls, seams = _seams()
    rc, out, err = _main( tmp_path, FINDING, **seams )
    entry        = _ledger( tmp_path )[ "notify" ]

    assert rc == 2 and "1 finding(s)" in out and entry[ "fingerprint" ] == hlt.fingerprint( [ _f() ] ) and entry[ "findings" ] == 1
    rc, out, _ = _main( tmp_path, FINDING, now=NOW + datetime.timedelta( hours=1 ), **seams )
    assert rc == 4 and "notify: identical findings delivered" in out and len( calls ) == 1


def test_a_failed_direct_message_is_retried_alone_and_the_notification_is_not_sent_again( tmp_path ):
    env          = { "HOOK_LINK_DM": "p" }
    calls, seams = _seams( dm=500 )
    rc, out, err = _main( tmp_path, FINDING, env, **seams )
    assert rc == 3 and "dm did not arrive" in err and "Channels that arrived are not sent again" in err
    assert sorted( _ledger( tmp_path ) ) == [ "notify" ]

    calls2, seams2 = _seams()
    rc, out, err = _main( tmp_path, FINDING, env, now=NOW + datetime.timedelta( minutes=10 ), **seams2 )
    assert rc == 2 and [ c[ 0 ] for c in calls2 ] == [ "dm" ]
    assert sorted( _ledger( tmp_path ) ) == [ "dm", "notify" ]
    calls3, seams3 = _seams()
    assert _main( tmp_path, FINDING, env, now=NOW + datetime.timedelta( minutes=20 ), **seams3 )[ 0 ] == 4 and calls3 == []


def test_a_failed_notification_is_retried_alone_while_the_direct_message_stays_quiet( tmp_path ):
    env          = { "HOOK_LINK_DM": "p" }
    calls, seams = _seams( notify=500 )
    rc, _, err   = _main( tmp_path, FINDING, env, **seams )
    assert rc == 3 and "notify did not arrive" in err and sorted( _ledger( tmp_path ) ) == [ "dm" ]
    calls2, seams2 = _seams()
    assert _main( tmp_path, FINDING, env, now=NOW + datetime.timedelta( minutes=10 ), **seams2 )[ 0 ] == 2
    assert [ c[ 0 ] for c in calls2 ] == [ "notify" ]


def test_a_changed_finding_set_sends_every_channel_again( tmp_path ):
    env          = { "HOOK_LINK_DM": "p" }
    calls, seams = _seams()
    assert _main( tmp_path, FINDING, env, **seams )[ 0 ] == 2
    assert _main( tmp_path, FINDING + "pre-commit\tABSENT\t/h\t\n", env, now=NOW + datetime.timedelta( minutes=10 ), **seams )[ 0 ] == 2
    assert [ c[ 0 ] for c in calls ] == [ "notify", "dm", "notify", "dm" ]


def test_main_does_not_write_a_ledger_when_nothing_arrived( tmp_path ):
    calls, seams = _seams( notify=500 )
    rc, out, err = _main( tmp_path, FINDING, **seams )
    assert rc == 3 and "Detection worked; the alarm did not reach every channel" in err
    assert not ( tmp_path / "state" / "s.json" ).exists()


def test_main_with_delivery_off_prints_exits_five_and_sends_and_records_nothing( tmp_path ):
    calls, seams = _seams()
    rc, out, _ = _main( tmp_path, FINDING, { "HOOK_LINK_DELIVER": "0" }, **seams )
    assert rc == 5 and "delivery disabled" in out and "nothing sent" in out and calls == [] and not ( tmp_path / "state" ).exists()


def test_a_corrupt_or_misshapen_ledger_reads_as_empty( tmp_path ):
    ( tmp_path / "state" ).mkdir()
    for text in ( "{not json", "[1, 2]", '{"channels": "x"}', '{"channels": {"notify": "x"}}' ):
        ( tmp_path / "state" / "s.json" ).write_text( text )
        calls, seams = _seams()
        assert _main( tmp_path, FINDING, **seams )[ 0 ] == 2 and len( calls ) == 1, text


def test_a_drill_marks_its_output_and_writes_its_ledger_beside_the_real_one_not_over_it( tmp_path, monkeypatch ):
    monkeypatch.setattr( hlt, "DEFAULT_STATE_PATH", str( tmp_path / "real.json" ) )
    calls, seams = _seams()
    out, err = _Err(), _Err()
    rc = hlt.main( [ _file( tmp_path, FINDING ) ], { "HOOK_LINK_DRILL": "1" }, NOW, out, err, **seams )
    assert rc == 2 and "[DRILL]" in out.text
    assert ( tmp_path / "real.json.drill" ).exists() and not ( tmp_path / "real.json" ).exists()
    rc = hlt.main( [ _file( tmp_path, FINDING ) ], { }, NOW, _Err(), err, **seams )
    assert rc == 2 and ( tmp_path / "real.json" ).exists(), "a real run must not be silenced by the drill's ledger"


def test_a_resend_window_that_is_not_a_number_exits_one_with_a_named_error( tmp_path ):
    calls, seams = _seams()
    rc, out, err = _main( tmp_path, FINDING, { "HOOK_LINK_RESEND_HOURS": "six" }, **seams )
    assert rc == 1 and "HOOK_LINK_RESEND_HOURS is not a number: 'six'" in err and calls == []


def test_a_clean_run_ignores_a_bad_resend_window( tmp_path ):
    assert _main( tmp_path, "", { "HOOK_LINK_RESEND_HOURS": "six" } ) == ( 0, "", "" )


def test_main_builds_a_timestamp_when_none_is_given( tmp_path ):
    calls, seams = _seams()
    rc = hlt.main( [ _file( tmp_path, FINDING ) ], { "HOOK_LINK_STATE": str( tmp_path / "s.json" ) }, None, _Err(), _Err(), **seams )
    assert rc == 2 and json.loads( ( tmp_path / "s.json" ).read_text() )[ "channels" ][ "notify" ][ "last_sent_ts" ]


def test_a_ledger_that_cannot_be_written_warns_but_the_delivery_still_counts( tmp_path ):
    calls, seams = _seams()
    blocker      = tmp_path / "blocker"; blocker.write_text( "a file where a folder should be" )
    err          = _Err()
    rc           = hlt.main( [ _file( tmp_path, FINDING ) ], { "HOOK_LINK_STATE": str( blocker / "s.json" ) }, NOW, _Err(), err, **seams )
    assert rc == 2 and "could not write the send ledger" in err.text
