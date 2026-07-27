"""
The session-bridge directory has ONE resolution point, and it cannot be hijacked — row `8ccc20ab`.

WHAT THE ROW ASKED FOR: `register_session.py` Phase 2 resolved its directory as a
bare `os.path.expanduser( "~/.claude/sessions" )` — no env override, no injectable
parameter, no module constant a test could patch. A unit test drove the real
`main()`, and Phase 2 merged a fixture into three LIVE seats' identity files.
A test could not reach a fake directory because there wasn't one to reach.

🔴 WHAT THE FIRST DRAFT OF THE FIX DID, AND WHY `TestTheSeamCannotBeHijacked`
EXISTS. The obvious variable name — `LUPIN_SESSIONS_DIR` — is already pinned to
the REAL directory, fleet-wide:

    ~/.config/systemd/user/tmux-server.service:36
        Environment=LUPIN_SESSIONS_DIR=%h/.claude/sessions

set for the out-of-tree `~/.local/bin/reconcile-bridges.py` (2026-07-14). The tmux
server inherits it, every `claude` inherits it, every pytest run inherits it. A
resolver preferring that variable therefore resolves to the real directory **no
matter what `$HOME` says** — silently defeating the isolation lever the existing
tests actually use. The draft did exactly that and one pytest run deposited a
fixture-valued `cc-1332865.json` into the operator's live bridge directory.

⇒ A seam is not automatically an improvement. A seam whose lever is already held
down by something else is a REGRESSION wearing a fix's shape, and nothing in the
row could have predicted it — it had to be measured against the live environment.
These tests pin BOTH halves: the seam works, AND it does not take precedence over
`$HOME`.

⚠️ THE CONTACT DETECTOR HERE WATCHES THE WHOLE DIRECTORY, not `cc-*.json`.
The sibling detector in `test_register_session_no_bridge_witness.py` globs
`cc-*.json` — 18 of the 4,836 entries in the real directory when this was written.
It reported "no contact" while `_spawn_listener` was depositing
`cc-listener-abc-123.spawn-lock` and `.stderr` beside the bridges, because those
are not `.json`. A receipt narrower than its claim reads true anyway.
"""

import hashlib
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir


SEAM_VAR = "LUPIN_HOOK_SESSIONS_DIR"

# The variable that is ALREADY pinned fleet-wide. This module must never read it.
HIJACKED_VAR = "LUPIN_SESSIONS_DIR"

# Captured AT IMPORT, before any fixture rewrites $HOME — this must name the
# operator's REAL bridge directory or the detector below is watching a decoy.
REAL_SESSIONS_DIR = Path( os.path.expanduser( "~/.claude/sessions" ) )

REPO_ROOT  = Path( __file__ ).resolve().parents[ 3 ]
SEAM_MODULE = REPO_ROOT / "src" / "lupin_cli" / "claude_code" / "hooks" / "lib" / "sessions_dir.py"


# ══════════════════════════════════════════════════════════════════════════════
# Contact detector — whole-directory, content-hashed
# ══════════════════════════════════════════════════════════════════════════════

# ⚠️ NAMED BLIND SPOT — these two are FLEET-SHARED append-only logs that every
# live listener and idle-waiter writes to continuously. A change to them during a
# test is NOT attributable to that test, so watching them makes the detector fire
# on other people's work: measured 2026-07-27, `cc-listeners.log` changed under a
# test that only wrote and deleted a .py file.
#
# They are excluded so the detector reports contact, not concurrency — and named
# HERE rather than dropped silently, because a receipt narrower than its claim
# reads true anyway. Everything else in the directory IS watched, including the
# per-session `cc-listener-*.spawn-lock` / `.stderr` artefacts the `cc-*.json`
# glob missed.
_UNATTRIBUTABLE = frozenset( { "cc-listeners.log", "cc-idle-waiters.log" } )


def _real_dir_fingerprint():
    """
    Content fingerprint of every attributable entry in the real bridge directory.

    Hashes CONTENT, not names or a count: bug `2508b1ce` turned on exactly that
    distinction — a merge into a live seat's bridge leaves the file count
    unchanged, so a count-based check clears while identity is being rewritten.
    Size alone is likewise insufficient; a merge can swap one id for another of
    equal length.

    Globs `*`, not `cc-*.json`, because the narrower glob is how
    `cc-listener-*.spawn-lock` / `.stderr` writes went unseen — minus the
    fleet-shared logs named in `_UNATTRIBUTABLE` above.
    """
    if not REAL_SESSIONS_DIR.is_dir():
        return { }
    out = { }
    for p in sorted( REAL_SESSIONS_DIR.glob( "*" ) ):
        if p.name in _UNATTRIBUTABLE:
            continue
        if p.is_dir():
            out[ p.name ] = "<dir>"
            continue
        try:
            out[ p.name ] = hashlib.sha256( p.read_bytes() ).hexdigest()
        except OSError:
            out[ p.name ] = "<unreadable>"
    return out


@pytest.fixture( autouse=True )
def detect_real_dir_contact():
    """
    Every test in this file must leave the operator's real bridge directory
    byte-identical. This asserts the claim that matters — the real dir was NOT
    TOUCHED — rather than the weaker "we used tmp", which a tmp_path-shaped
    assertion is all that can be made.
    """
    before = _real_dir_fingerprint()
    yield
    after   = _real_dir_fingerprint()
    created = sorted( set( after ) - set( before ) )
    removed = sorted( set( before ) - set( after ) )
    changed = sorted( n for n in ( set( before ) & set( after ) ) if before[ n ] != after[ n ] )

    assert not ( created or removed or changed ), (
        f"🔴 THIS TEST TOUCHED THE OPERATOR'S REAL BRIDGE DIRECTORY ({REAL_SESSIONS_DIR}) — row 8ccc20ab.\n"
        f"  created: {created}\n  removed: {removed}\n  CHANGED (merged into a live seat): {changed}\n"
        "A changed file is the dangerous case: it rewrites a RUNNING session's identity, "
        "leaves the file count unchanged, and can null that seat's voice_persona."
    )


@pytest.fixture
def isolated_home( monkeypatch, tmp_path ):
    """$HOME redirected, seam UNSET — the pre-existing isolation lever, on its own."""
    home = tmp_path / "home"
    ( home / ".claude" / "sessions" ).mkdir( parents=True )
    monkeypatch.setenv( "HOME", str( home ) )
    monkeypatch.delenv( SEAM_VAR, raising=False )
    return home


# ══════════════════════════════════════════════════════════════════════════════
# 1. The resolver itself
# ══════════════════════════════════════════════════════════════════════════════

class TestTheResolver:

    def test_default_is_derived_from_HOME_at_call_time( self, isolated_home ):
        """
        Not `Path.home()` frozen at import — the whole point of `_logs_dir()`'s
        lesson (row 6fc8d78d) is that an import-time constant ignores a fixture
        that runs later.
        """
        assert sessions_dir() == isolated_home / ".claude" / "sessions"

    def test_default_matches_the_pre_seam_hardcoded_value( self, monkeypatch ):
        """Production leaves the seam unset; the default must be byte-identical
        to what all eleven call sites resolved before this module existed, or the
        container's ~/.claude/sessions bind-mount silently moves."""
        monkeypatch.delenv( SEAM_VAR, raising=False )
        assert str( sessions_dir() ) == os.path.expanduser( "~/.claude/sessions" )

    def test_the_seam_variable_wins_when_set( self, monkeypatch, tmp_path ):
        monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
        monkeypatch.setenv( SEAM_VAR, str( tmp_path / "seam" ) )
        assert sessions_dir() == tmp_path / "seam"

    def test_an_empty_seam_variable_falls_back_to_the_default( self, isolated_home, monkeypatch ):
        """An exported-but-blank variable must not resolve to Path("") — that
        would put bridges in the CWD, which is worse than either branch."""
        monkeypatch.setenv( SEAM_VAR, "" )
        assert sessions_dir() == isolated_home / ".claude" / "sessions"

    def test_it_resolves_at_call_time_not_once( self, monkeypatch, tmp_path ):
        """Two different answers from two calls, no re-import."""
        monkeypatch.setenv( SEAM_VAR, str( tmp_path / "a" ) )
        first = sessions_dir()
        monkeypatch.setenv( SEAM_VAR, str( tmp_path / "b" ) )
        assert first == tmp_path / "a" and sessions_dir() == tmp_path / "b"


# ══════════════════════════════════════════════════════════════════════════════
# 2. 🔴 The seam cannot be hijacked by the fleet-pinned variable
# ══════════════════════════════════════════════════════════════════════════════

class TestTheSeamCannotBeHijacked:

    def test_LUPIN_SESSIONS_DIR_does_not_override_HOME( self, isolated_home, monkeypatch ):
        """
        🔴 THE CONTROL FOR THE REGRESSION THAT NEARLY SHIPPED.

        `LUPIN_SESSIONS_DIR` is exported to every process in the fleet by
        `tmux-server.service`, pinned to the REAL directory. Reading it here would
        mean `$HOME` redirection — the isolation every existing test relies on —
        stops working the moment this module is imported.

        This simulates the live fleet environment exactly: the pinned variable set
        to the real directory, `$HOME` redirected. The resolver must follow `$HOME`.
        """
        monkeypatch.setenv( HIJACKED_VAR, str( REAL_SESSIONS_DIR ) )
        resolved = sessions_dir()
        assert resolved == isolated_home / ".claude" / "sessions", (
            f"🔴 {HIJACKED_VAR} hijacked the seam: resolved to {resolved} while $HOME "
            f"was {isolated_home}. That variable is pinned fleet-wide by "
            "tmux-server.service, so honoring it defeats $HOME redirection for every "
            "test at once. See sessions_dir.py's docstring."
        )

    def test_the_seam_module_never_reads_the_pinned_variable( self ):
        """
        Source-level, because the behavioural test above passes for the wrong
        reason if someone later reads the pinned variable as a SECOND fallback
        (below HOME) — that would still be a live path into production for any
        caller whose HOME is not redirected.
        """
        source = SEAM_MODULE.read_text()
        code   = [ l for l in source.splitlines()
                   if HIJACKED_VAR in l and "os.environ" in l ]
        assert not code, (
            f"{SEAM_MODULE.name} reads {HIJACKED_VAR}: {code}\n"
            "That variable belongs to the out-of-tree reconcile-bridges.py and is "
            "pinned to the real directory fleet-wide."
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. register_session.main() honors the seam — the row's actual claim
# ══════════════════════════════════════════════════════════════════════════════

class TestRegisterSessionHonorsTheSeam:

    def test_a_healthy_payload_writes_its_bridge_into_the_seam_not_HOME( self, monkeypatch, tmp_path ):
        """
        The gate that would have caught `2508b1ce`. Drives the REAL `main()` with a
        healthy payload — the same call that merged into three live seats — and
        asserts the bridge lands in the seam directory.

        `$HOME` is redirected TOO, so a regression fails SAFELY (into the tmp home)
        instead of into the operator's live directory. That is deliberate: a test
        proving a directory redirect must not need production as its control.
        """
        home = tmp_path / "home"
        seam = tmp_path / "seam"
        ( home / ".claude" / "sessions" ).mkdir( parents=True )
        seam.mkdir()
        monkeypatch.setenv( "HOME", str( home ) )
        monkeypatch.setenv( SEAM_VAR, str( seam ) )

        import importlib
        module = importlib.import_module( "lupin_cli.claude_code.hooks.register_session" )
        monkeypatch.setattr( module, "read_hook_input",
                             lambda: { "session_id": "seam-probe-1", "cwd": "/tmp",
                                       "transcript_path": "/x" } )
        monkeypatch.setattr( module, "emit_json", lambda *a, **k: None )

        buffer = io.StringIO()
        with redirect_stderr( buffer ):
            try:
                module.main()
            except SystemExit:
                pass
            except Exception:                                     # noqa: BLE001
                pass   # downstream tmux/network/persona failures are not what this asserts

        in_seam = sorted( p.name for p in seam.glob( "cc-*.json" ) )
        in_home = sorted( p.name for p in ( home / ".claude" / "sessions" ).glob( "*" ) )

        assert in_seam, (
            f"main() wrote no bridge into the seam ({seam}). "
            f"Entries that landed in $HOME/.claude/sessions instead: {in_home}. "
            "If this list is non-empty, Phase 2 is resolving its directory from $HOME "
            "rather than through sessions_dir() — row 8ccc20ab."
        )
        assert not in_home, (
            f"main() ALSO wrote into $HOME/.claude/sessions: {in_home}. "
            "Every path main() writes must resolve through the one seam; a partially "
            "seamed hook is the 'receipt narrower than its claim' failure."
        )

    def test_the_bridge_carries_the_payloads_session_id( self, monkeypatch, tmp_path ):
        """
        Guards against the assertion above passing on an empty or unrelated file:
        the bridge in the seam must be the one THIS payload produced.
        """
        home = tmp_path / "home"
        seam = tmp_path / "seam"
        ( home / ".claude" / "sessions" ).mkdir( parents=True )
        seam.mkdir()
        monkeypatch.setenv( "HOME", str( home ) )
        monkeypatch.setenv( SEAM_VAR, str( seam ) )

        import importlib
        module = importlib.import_module( "lupin_cli.claude_code.hooks.register_session" )
        monkeypatch.setattr( module, "read_hook_input",
                             lambda: { "session_id": "seam-probe-2", "cwd": "/tmp",
                                       "transcript_path": "/x" } )
        monkeypatch.setattr( module, "emit_json", lambda *a, **k: None )
        with redirect_stderr( io.StringIO() ):
            try:
                module.main()
            except SystemExit:
                pass
            except Exception:                                     # noqa: BLE001
                pass

        bridges = list( seam.glob( "cc-*.json" ) )
        assert len( bridges ) == 1, f"expected exactly one bridge, got {[ b.name for b in bridges ]}"
        assert json.loads( bridges[ 0 ].read_text() )[ "session_id" ] == "seam-probe-2"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Every module resolves through the one seam
# ══════════════════════════════════════════════════════════════════════════════

# The probe program, run in a FRESH interpreter. Each entry reports where that
# module ACTUALLY resolves the bridge directory.
#
# ⚠️ `listener_processes` is deliberately NOT `sessions_dir()` re-imported — that
# would be a test containing a copy of the thing it verifies, and it would pass
# with `listener_processes` reverted to an import-time constant. It EXERCISES the
# real lock helper and reports where the lock file landed. Mock the boundary, not
# the behaviour under test.
_PROBE_PROGRAM = """
import json
from pathlib import Path

out = {}

from lupin_cli.claude_code.hooks.lib import session_bridge as _sb
out["session_bridge"] = str( _sb.SESSION_DIR )

from lupin_cli.claude_code.hooks.lib import hook_common as _hc
out["hook_common"] = str( _hc.SESSION_DIR )
out["hook_common_buffer"] = str( _hc.get_buffer_path( "probe123" ).parent )

from lupin_cli.claude_code.hooks.lib import cc_notification_listener as _cnl
out["cc_notification_listener"] = str( _cnl.SESSION_DIR )
out["cc_listener_centralized"]  = str( _cnl.CENTRALIZED_LOG.parent )

from lupin_cli.claude_code.hooks.lib import idle_waiter as _iw
out["idle_waiter"] = str( _iw._LOG_DIR )

from lupin_cli.claude_code.hooks.lib import board_sweep as _bs
out["board_sweep"] = str( _bs.SWEEP_DIR )

from lupin_mcp import session_spawner as _ss
out["session_spawner"] = str( _ss.SESSION_DIR )

from lupin_cli.claude_code.hooks.lib import subagent_governance as _sg
out["subagent_governance"] = str( _sg._session_dir() )

# Exercised, not re-derived: acquire the real lock and report where it landed.
from lupin_cli.claude_code.hooks.lib.listener_processes import listener_spawn_lock
_target = Path( out["session_bridge"] )
_target.mkdir( parents=True, exist_ok=True )
with listener_spawn_lock( "probeLOCK" ):
    _found = list( _target.glob( "cc-listener-probeLOCK.spawn-lock" ) )
out["listener_processes"] = str( _found[0].parent ) if _found else "<lock landed elsewhere>"

print( json.dumps( out ) )
"""

# Names the probe must report; a silently-dropped key is a silently-unmeasured writer.
_RESOLVER_KEYS = {
    "session_bridge", "hook_common", "hook_common_buffer", "cc_notification_listener",
    "cc_listener_centralized", "idle_waiter", "board_sweep", "session_spawner",
    "subagent_governance", "listener_processes",
}


class TestEveryModuleResolvesThroughTheSeam:
    """
    The row's own NOT-ESTABLISHED item: *"A fix that seams only `register_session`
    may leave writers behind."* Ten resolution points, measured in a FRESH
    interpreter — import-time constants cannot be tested any other way, and testing
    them in-process would silently pass on values bound before the fixture ran.
    """

    @staticmethod
    def _resolve_in_subprocess( env_overrides ):
        env = dict( os.environ )
        env.update( env_overrides )
        env[ "PYTHONPATH" ] = str( REPO_ROOT / "src" ) + os.pathsep + env.get( "PYTHONPATH", "" )
        out = subprocess.run( [ sys.executable, "-c", _PROBE_PROGRAM ], env=env,
                              capture_output=True, text=True, timeout=180 )
        assert out.returncode == 0, f"probe failed:\n{out.stderr[ -3000: ]}"
        return json.loads( out.stdout.strip().splitlines()[ -1 ] )

    def test_all_ten_move_together_under_the_seam( self, tmp_path ):
        target   = tmp_path / "seam"
        resolved = self._resolve_in_subprocess( { SEAM_VAR: str( target ) } )
        stragglers = { k: v for k, v in resolved.items() if v != str( target ) }
        assert not stragglers, (
            f"these resolution points ignored {SEAM_VAR} and stayed on their own path: "
            f"{stragglers}\nEach is a writer that a seamed test still cannot isolate."
        )

    def test_all_ten_default_to_the_unchanged_production_path( self, tmp_path ):
        """
        The other half: the seam must not have MOVED production. Byte-identical to
        the pre-seam value, or the container bind-mount breaks.

        ⚠️ Read-only assertion by construction — the probe's only write is the lock
        file, and with the seam unset that would land in the REAL directory. So this
        variant asserts against the expanduser default while pointing $HOME at tmp,
        which yields the same code path with nothing at stake.
        """
        home = tmp_path / "prodhome"
        ( home / ".claude" / "sessions" ).mkdir( parents=True )
        resolved = self._resolve_in_subprocess( { SEAM_VAR: "", "HOME": str( home ) } )
        expected = str( home / ".claude" / "sessions" )
        drifted  = { k: v for k, v in resolved.items() if v != expected }
        assert not drifted, (
            f"with the seam UNSET these did not fall back to $HOME/.claude/sessions: "
            f"{drifted} (expected {expected}). A site that ignores $HOME too is one a "
            "test cannot isolate by ANY lever."
        )

    def test_the_probe_can_fail( self, tmp_path ):
        """
        🔴 NEGATIVE CONTROL. `_resolve_in_subprocess` is the instrument the two
        tests above trust completely. If it silently returned the same dict for any
        input — a swallowed import, a stale interpreter, an expression that
        evaluates to a constant — both would pass while measuring nothing.

        Two DIFFERENT seam values must produce two DIFFERENT answers, and the key
        set must be complete: a dropped key is a writer measured by nobody.
        """
        a = self._resolve_in_subprocess( { SEAM_VAR: str( tmp_path / "aaa" ) } )
        b = self._resolve_in_subprocess( { SEAM_VAR: str( tmp_path / "bbb" ) } )
        assert a != b, "the subprocess probe returns the same answer regardless of input"
        assert set( a ) == _RESOLVER_KEYS, (
            f"the probe dropped resolution points silently: missing "
            f"{sorted( _RESOLVER_KEYS - set( a ) )}, unexpected {sorted( set( a ) - _RESOLVER_KEYS )}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 5. No new hardcoded site can be added without noticing
# ══════════════════════════════════════════════════════════════════════════════

class TestNoNewHardcodedResolution:
    """
    'One place cannot forget' only holds while there IS one place. This is the
    guard that keeps the twelfth site from being written by hand — the failure the
    row describes as the lesson learned in one module and never carried to the other.
    """

    # Files legitimately allowed to name the path literally.
    _ALLOWED = { "sessions_dir.py" }

    @staticmethod
    def _offending_lines():
        import re
        pattern = re.compile(
            r'expanduser\(\s*f?"~/\.claude/sessions'
            r'|Path\.home\(\)\s*/\s*"\.claude"\s*/\s*"sessions"'
        )
        hits = [ ]
        for path in ( REPO_ROOT / "src" ).rglob( "*.py" ):
            rel = path.relative_to( REPO_ROOT )
            if rel.parts[ 1 ] in ( "rnd", "tests" ):        # src/rnd, src/tests
                continue
            if path.name in TestNoNewHardcodedResolution._ALLOWED:
                continue
            for n, line in enumerate( path.read_text( errors="ignore" ).splitlines(), 1 ):
                if pattern.search( line ):
                    hits.append( f"{rel}:{n}: {line.strip()}" )
        return hits

    def test_no_module_outside_the_seam_constructs_the_path_itself( self ):
        offenders = self._offending_lines()
        assert not offenders, (
            "these construct the bridge directory by hand instead of calling "
            "sessions_dir() — row 8ccc20ab:\n  " + "\n  ".join( offenders )
        )

    def test_the_scanner_can_find_an_offender( self, tmp_path, monkeypatch ):
        """
        🔴 NEGATIVE CONTROL for the scanner. A source scan that matches nothing —
        wrong root, wrong glob, an over-eager skip list — passes exactly like a
        clean tree. This plants a known offender and requires it be found.
        """
        planted = REPO_ROOT / "src" / "lupin_cli" / "_seam_scanner_control.py"
        planted.write_text( 'import os\nD = os.path.expanduser( "~/.claude/sessions" )\n' )
        try:
            offenders = self._offending_lines()
        finally:
            planted.unlink()
        assert any( "_seam_scanner_control.py" in o for o in offenders ), (
            f"the scanner did not find a planted offender — it is not looking where it claims. "
            f"found: {offenders}"
        )
