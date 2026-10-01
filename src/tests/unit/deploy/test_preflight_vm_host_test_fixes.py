"""
preflight-vm.sh asserts the four lupin-host-test fixes hand-applied 2026-09-30 — row 31344c5f.

  A8   settings.json heartbeat + task_store block      (Stop poke silently off without it)
  A9   fleet-roster.env has a COSA_VOICE_MANAGERS__ line (no manager ⇒ store writes 403)
  C9   flow-ratio override present AND holding 24h / 2.0 (WARN — values ruled 2026-09-30, row 08691779)
  C10  git rev-parse HEAD works in every external mount (dubious-ownership trap)
  C11  every worked-on project has a roster line        (WARN)

Every assertion is proven to FAIL on a planted bad fixture and PASS on a good one, at two
altitudes: the pure lib helpers, and the assembled script run against a fake `docker` on PATH.
The compose half pins the durable safe.directory env to the bind table it must mirror.

Venue: :7999-eligible. No SSH, no network, no real docker.
"""
import json
import os
import re
import stat
import subprocess

import pytest
import yaml

import cosa.utils.util as cu

ROOT    = cu.get_project_root()
LIB     = f"{ROOT}/src/scripts/lib/preflight-vm-lib.sh"
SCRIPT  = f"{ROOT}/src/scripts/preflight-vm.sh"
COMPOSE = f"{ROOT}/docker-compose.cloud-gpu.yml"

GOOD_SETTINGS = { "heartbeat": { "enabled": True, "owed_source_from_store": True }, "task_store": { "enabled": True } }


def _lib( snippet ):
    return subprocess.run( [ "bash", "-c", f"source '{LIB}'; {snippet}" ], capture_output=True, text=True, timeout=30 )


# ── lib: settings ────────────────────────────────────────────────────────────

def test_settings_good_passes( tmp_path ):
    f = tmp_path / "s.json"; f.write_text( json.dumps( GOOD_SETTINGS ) )
    r = _lib( f"pfv_heartbeat_settings_status '{f}'" )
    assert ( r.returncode, r.stdout ) == ( 0, "OK" )


@pytest.mark.parametrize( "body,missing", [
    ( {},                                                                                   "heartbeat.enabled,heartbeat.owed_source_from_store,task_store.enabled" ),
    ( { **GOOD_SETTINGS, "heartbeat": { "enabled": False, "owed_source_from_store": True } }, "heartbeat.enabled" ),
    ( { **GOOD_SETTINGS, "heartbeat": { "enabled": True } },                                "heartbeat.owed_source_from_store" ),
    ( { **GOOD_SETTINGS, "task_store": {} },                                                "task_store.enabled" ),
    ( { **GOOD_SETTINGS, "task_store": "yes" },                                             "task_store.enabled" ),
    ( { **GOOD_SETTINGS, "heartbeat": { "enabled": "true", "owed_source_from_store": True } }, "heartbeat.enabled" ),
    ( [],                                                                                   "heartbeat.enabled,heartbeat.owed_source_from_store,task_store.enabled" ),
] )
def test_settings_bad_fails_naming_the_key( tmp_path, body, missing ):
    f = tmp_path / "s.json"; f.write_text( json.dumps( body ) )
    r = _lib( f"pfv_heartbeat_settings_status '{f}'" )
    assert ( r.returncode, r.stdout ) == ( 1, missing )


def test_settings_unreadable_and_unparseable( tmp_path ):
    r = _lib( f"pfv_heartbeat_settings_status '{tmp_path}/nope.json'" )
    assert ( r.returncode, r.stdout ) == ( 2, "UNREADABLE" )
    f = tmp_path / "bad.json"; f.write_text( "{not json" )
    r = _lib( f"pfv_heartbeat_settings_status '{f}'" )
    assert ( r.returncode, r.stdout ) == ( 3, "UNPARSEABLE" )


# ── lib: roster ──────────────────────────────────────────────────────────────

def test_roster_key_spelling():
    r = _lib( "pfv_roster_project_key weil-nda-drafting-suite; printf ' '; pfv_roster_project_key lupin.mobile" )
    assert r.stdout == "WEIL_NDA_DRAFTING_SUITE LUPIN_MOBILE"


@pytest.mark.parametrize( "text,key,rc", [
    ( 'COSA_VOICE_MANAGERS__LUPIN="Mr. Radio"\n',        "LUPIN", 0 ),
    ( 'COSA_VOICE_MANAGERS__LUPIN="Mr. Radio"\n',        "",      0 ),
    ( 'export COSA_VOICE_MANAGERS__PLAN=Maria\n',        "PLAN",  0 ),
    ( 'COSA_VOICE_MANAGERS__LUPIN="Mr. Radio"\n',        "PLAN",  1 ),
    ( 'COSA_VOICE_MANAGERS__LUPIN=""\n',                 "LUPIN", 1 ),
    ( '# COSA_VOICE_MANAGERS__LUPIN="x"\n',              "LUPIN", 1 ),
    ( '# COSA_VOICE_MANAGERS__LUPIN="x"\n',              "",      1 ),
    ( 'COSA_VOICE_MANAGERS__LUPIN_MOBILE="T"\n',         "LUPIN", 1 ),   # prefix of a longer key is not a match
    ( "",                                                "",      1 ),
] )
def test_roster_declares( tmp_path, text, key, rc ):
    f = tmp_path / "r.env"; f.write_text( text )
    assert _lib( f"pfv_roster_declares '{f}' '{key}'" ).returncode == rc


def test_roster_missing_file_is_3( tmp_path ):
    assert _lib( f"pfv_roster_declares '{tmp_path}/none' ''" ).returncode == 3


def test_cc_project_dirname():
    assert _lib( "pfv_cc_project_dirname /mnt/lupin-data/google/weil-nda-drafting-suite" ).stdout == "-mnt-lupin-data-google-weil-nda-drafting-suite"


# ── the assembled script, against a fake docker ──────────────────────────────

MOUNTS = [
    ( "/mnt/lupin-data/lupin",                        "/var/external-projects/lupin" ),
    ( "/mnt/lupin-data/google/weil-nda-drafting-suite", "/var/external-projects/google/weil-nda-drafting-suite" ),
    ( "/mnt/lupin-data/google/weil-parallel-search",  "/var/external-projects/google/weil-parallel-search" ),
]

FAKE_DOCKER = r'''#!/bin/bash
case "$1" in
  ps) echo "$FAKE_CONTAINER" ;;
  inspect)
    case "$*" in
      *State.Running*) echo true ;;
      *Source*) cat "$FAKE_MOUNTS_SRC" ;;
      *Destination*) cut -f2 "$FAKE_MOUNTS_SRC" ;;
    esac ;;
  exec)
    shift 2
    case "$*" in
      *LUPIN_FLOW_RATIO_DIR*) printf %s "$FAKE_FR_DIR" ;;
      "cat "*flow-ratio-settings.json) [ -f "$FAKE_FR_FILE" ] && cat "$FAKE_FR_FILE" || exit 1 ;;
      *".git"*) echo HEAD ;;
      "git -C "*) m="$3"; case " $FAKE_UNSAFE " in *" $m "*) exit 128 ;; esac; echo deadbeef ;;
      sh*ls*) echo x ;;
      *) exit 1 ;;
    esac ;;
  *) exit 1 ;;
esac
'''


def _override_variables():
    """
    Every environment variable the scripts honor as an OVERRIDE of a path under $HOME, read from their source.

    🔴 WHY THIS IS DERIVED AND NOT LISTED (row 5ad93b8c, 2026-09-30). The venue pinned HOME and two of the
    eleven override variables; the other nine fell through from `os.environ`. `preflight-vm.sh` reads
    `${PREFLIGHT_VM_FLEET_ROSTER:-$HOME/.claude/fleet-roster.env}`, so one ambient `PREFLIGHT_VM_FLEET_ROSTER`
    pointing at a real roster makes test_A9_absent_roster_fails read the real file, find a manager line, and
    miss the `[FAIL]` it expects (measured: 4 tests in this file flip, A9 among them). Isolating HOME alone
    was never the isolation. Deriving the names from the scripts means a new override is scrubbed on arrival.
    """
    names = set()
    for path in ( SCRIPT, LIB ):
        with open( path, encoding="utf-8" ) as handle:
            names.update( re.findall( r"\b(PREFLIGHT_VM_[A-Z0-9_]+|LUPIN_HOST_SESSIONS_DIR)\b", handle.read() ) )
    return names


@pytest.fixture
def venue( tmp_path ):
    """A fully-good fake venue; each test plants ONE defect into it."""
    home = tmp_path / "home"; ( home / ".claude" / "projects" ).mkdir( parents=True )
    bindir = tmp_path / "bin"; bindir.mkdir()
    d = bindir / "docker"; d.write_text( FAKE_DOCKER ); d.chmod( d.stat().st_mode | stat.S_IEXEC )
    ( home / ".claude" / "settings.json" ).write_text( json.dumps( GOOD_SETTINGS ) )
    ( home / ".claude" / "fleet-roster.env" ).write_text( 'COSA_VOICE_MANAGERS__LUPIN="A"\nCOSA_VOICE_MANAGERS__WEIL_NDA_DRAFTING_SUITE="B"\n' )
    ( home / ".claude" / "projects" / "-mnt-lupin-data-google-weil-nda-drafting-suite" ).mkdir()
    ( home / ".claude" / "projects" / "-mnt-lupin-data-lupin" ).mkdir()
    msrc = tmp_path / "mounts.tsv"; msrc.write_text( "".join( f"{s}\t{t}\n" for s, t in MOUNTS ) )
    fr = tmp_path / "frs.json"; fr.write_text( '{"window_hours": 24, "allow_below": 2.0}' )
    ambient = { k: v for k, v in os.environ.items() if k not in _override_variables() }
    env = { **ambient, "HOME": str( home ), "PATH": f"{bindir}:{os.environ['PATH']}",
            "PREFLIGHT_VM_CONTAINER": "fake-rest", "FAKE_CONTAINER": "fake-rest",
            "FAKE_MOUNTS_SRC": str( msrc ), "FAKE_FR_DIR": "/var/lupin/flow-ratio", "FAKE_FR_FILE": str( fr ),
            "FAKE_UNSAFE": "", "PREFLIGHT_VM_COMPOSE": COMPOSE, "LUPIN_ROOT": ROOT }
    return { "home": home, "env": env, "fr": fr, "msrc": msrc }


def test_the_override_variables_are_found_at_all():
    # A scrub list derived by a regex over the scripts is only worth anything if the regex finds them:
    # an empty set scrubs nothing and every test below stays green over a leaking venue.
    found = _override_variables()
    assert { "PREFLIGHT_VM_FLEET_ROSTER", "PREFLIGHT_VM_CC_SETTINGS", "PREFLIGHT_VM_CC_PROJECTS",
             "LUPIN_HOST_SESSIONS_DIR" } <= found, sorted( found )
    assert len( found ) >= 9, sorted( found )


def test_an_ambient_roster_override_cannot_hide_a_missing_roster( request, monkeypatch, tmp_path ):
    # The leak, planted BEFORE the venue is built: a real roster named by the ambient environment. With
    # the override reaching the script, it reads that file, finds a manager line and prints no
    # `[FAIL]`, which is exactly how test_A9_absent_roster_fails could be red in a full tier and green alone.
    real = tmp_path / "somebody-elses-roster.env"
    real.write_text( 'COSA_VOICE_MANAGERS__LUPIN="Real"\n' )
    monkeypatch.setenv( "PREFLIGHT_VM_FLEET_ROSTER", str( real ) )
    venue = request.getfixturevalue( "venue" )
    assert "PREFLIGHT_VM_FLEET_ROSTER" not in venue[ "env" ]
    ( venue[ "home" ] / ".claude" / "fleet-roster.env" ).unlink()
    assert "[FAIL]" in _line( _run( venue ), "fleet-roster.env is missing" )


def _run( venue ):
    r = subprocess.run( [ "bash", SCRIPT, "--phase", "pre" ], env=venue[ "env" ], capture_output=True, text=True, timeout=120 )
    return r.stdout


def _line( out, needle ):
    hits = [ l for l in out.split( "\n" ) if needle in l ]
    assert hits, f"no line containing {needle!r} in:\n{out}"
    return "\n".join( hits )


def test_good_venue_passes_all_five( venue ):
    out = _run( venue )
    assert "[OK]" in _line( out, "settings.json heartbeat.enabled" )
    assert "[OK]" in _line( out, "fleet-roster.env declares at least one" )
    assert "[OK]" in _line( out, "flow-ratio override present" )
    assert "ruled 24h / 2.0" in _line( out, "flow-ratio override present" )
    assert "[OK]" in _line( out, "git rev-parse HEAD succeeds" )
    assert "all 3 external-project mounts" in _line( out, "git rev-parse HEAD succeeds" )
    assert "[OK]" in _line( out, "every worked-on project (2)" )


def test_A8_missing_heartbeat_block_fails_with_remedy( venue ):
    ( venue[ "home" ] / ".claude" / "settings.json" ).write_text( "{}" )
    out = _run( venue )
    assert "[FAIL]" in _line( out, "not wired for the Stop poke" )
    assert "remedy" in out and "owed_source_from_store" in out


def test_A8_unparseable_settings_is_blocking_unknown( venue ):
    ( venue[ "home" ] / ".claude" / "settings.json" ).write_text( "{oops" )
    assert "treated as blocking" in _line( _run( venue ), "cannot read the heartbeat block" )


def test_A9_absent_roster_fails( venue ):
    ( venue[ "home" ] / ".claude" / "fleet-roster.env" ).unlink()
    out = _run( venue )
    assert "[FAIL]" in _line( out, "fleet-roster.env is missing" )
    assert "fleet-roster.env.template" in out


def test_A9_roster_without_manager_line_fails( venue ):
    ( venue[ "home" ] / ".claude" / "fleet-roster.env" ).write_text( "# nothing\n" )
    assert "[FAIL]" in _line( _run( venue ), "has no COSA_VOICE_MANAGERS__<PROJECT> line" )


@pytest.mark.parametrize( "body", [
    '{"window_hours": 120, "allow_below": 1.1}',     # dev's old values
    '{"window_hours": 24, "allow_below": 1.0}',      # the shipped default
    '{"window_hours": 24, "allow_below": 2.5}',
    '{"window_hours": 48, "allow_below": 2.0}',
    '{"window_hours": 24}',                          # a key absent
    '{"allow_below": 2.0}',
    '{"window_hours": "24", "allow_below": 2.0}',    # a string is not the number
    '{"window_hours": true, "allow_below": 2.0}',    # nor is a boolean (True == 1 in python)
] )
def test_C9_any_value_but_24h_2_0_warns_and_names_what_it_found( venue, body ):
    venue[ "fr" ].write_text( body )
    line = _line( _run( venue ), "NOT the ruled 24h / 2.0" )
    assert "[WARN]" in line
    assert "[OK]" not in line


@pytest.mark.parametrize( "body,rc,out", [
    ( '{"window_hours": 24, "allow_below": 2.0}',   0, "OK" ),
    ( '{"window_hours": 24.0, "allow_below": 2}',   0, "OK" ),                       # same numbers, other spelling
    ( '{"window_hours": 120, "allow_below": 1.1}',  1, "window_hours=120, allow_below=1.1" ),
    ( '{"window_hours": 24}',                       1, "window_hours=24, allow_below=absent" ),
    ( '{"window_hours": true, "allow_below": 2.0}', 1, "window_hours=True, allow_below=2.0" ),
    ( '[]',                                         3, "UNPARSEABLE" ),
    ( '{not json',                                  3, "UNPARSEABLE" ),
] )
def test_flow_ratio_status_is_exactly_24h_2_0( body, rc, out ):
    r = _lib( f"pfv_flow_ratio_status '{body}'" )
    assert ( r.returncode, r.stdout ) == ( rc, out )


def test_C9_unparseable_override_warns_instead_of_passing( venue ):
    venue[ "fr" ].write_text( "{not json" )
    assert "[WARN]" in _line( _run( venue ), "NOT the ruled 24h / 2.0" )


def test_C9_missing_flow_ratio_file_warns( venue ):
    venue[ "fr" ].unlink()
    assert "[WARN]" in _line( _run( venue ), "no flow-ratio override" )


def test_C9_unset_flow_ratio_dir_warns( venue ):
    venue[ "env" ][ "FAKE_FR_DIR" ] = ""
    assert "[WARN]" in _line( _run( venue ), "LUPIN_FLOW_RATIO_DIR is unset" )


def test_C10_dubious_ownership_mount_fails_naming_it( venue ):
    venue[ "env" ][ "FAKE_UNSAFE" ] = "/var/external-projects/google/weil-nda-drafting-suite"
    out = _run( venue )
    hit = _line( out, "dubious ownership" )
    assert "[FAIL]" in hit and "weil-nda-drafting-suite" in hit
    assert "GIT_CONFIG_COUNT" in out


def test_C10_no_git_mounts_is_unknown( venue ):
    venue[ "msrc" ].write_text( "/mnt/x\t/var/elsewhere\n" )
    assert "[UNKN]" in _line( _run( venue ), "no git-backed /var/external-projects mount" )


def test_C11_worked_project_without_roster_line_warns( venue ):
    ( venue[ "home" ] / ".claude" / "projects" / "-mnt-lupin-data-google-weil-parallel-search" ).mkdir()
    hit = _line( _run( venue ), "no roster line" )
    assert "[WARN]" in hit and "COSA_VOICE_MANAGERS__WEIL_PARALLEL_SEARCH" in hit
    assert "WEIL_NDA" not in hit


def test_C11_nothing_worked_is_unknown_not_pass( venue ):
    for p in ( venue[ "home" ] / ".claude" / "projects" ).iterdir(): p.rmdir()
    assert "[UNKN]" in _line( _run( venue ), "per-project roster coverage not assessed" )


# ── compose: durable safe.directory mirrors the bind table ───────────────────

def test_compose_safe_directory_env_covers_exactly_the_external_binds():
    svc   = yaml.safe_load( open( COMPOSE ) )[ "services" ][ "lupin-rest" ]
    env   = svc[ "environment" ]
    binds = sorted( v[ "target" ] for v in svc[ "volumes" ]
                    if isinstance( v, dict ) and v[ "target" ].startswith( "/var/external-projects/" ) )
    assert binds, "no external binds found — the comparison would be vacuous"
    n = int( env[ "GIT_CONFIG_COUNT" ] )
    assert n == len( binds )
    assert [ env[ f"GIT_CONFIG_KEY_{i}" ] for i in range( n ) ] == [ "safe.directory" ] * n
    assert sorted( env[ f"GIT_CONFIG_VALUE_{i}" ] for i in range( n ) ) == binds
