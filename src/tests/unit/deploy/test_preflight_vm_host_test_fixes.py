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
import shutil
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
      *Config.Labels*) printf %s "$FAKE_LABEL" ;;
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
            "FAKE_UNSAFE": "", "PREFLIGHT_VM_COMPOSE": COMPOSE, "LUPIN_ROOT": ROOT,
            # LUPIN_ROOT is the real tree, so the project-scope file is pinned to a path that
            # does not exist: a .mcp.json added to the repo root must not reach these tests.
            "PREFLIGHT_VM_PROJECT_MCP_JSON": str( tmp_path / "project.mcp.json" ) }
    return { "home": home, "env": env, "fr": fr, "msrc": msrc, "project_mcp": tmp_path / "project.mcp.json" }


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


# ── A3b: the voice server's registration (row c9252819) ──────────────────────
# The venue starts with no ~/.claude.json, which is a host nobody runs Claude Code on,
# and with no project .mcp.json.

VOICE_VAR   = "LUPIN_CONFIG_MGR_CLI_ARGS"
VOICE_VALUE = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"
VOICE_BAD   = VOICE_VALUE.replace( "Lupin:+Development", "Lupin:+No-Such" )
VOICE_VERB  = "from the dev box: src/scripts/lupin-vm.sh install-voice"


def _register( venue, user_env=None, local=None ):
    doc = {}
    if user_env is not None: doc[ "mcpServers" ] = { "cosa-voice": { "command": "/v/bin/python", "env": user_env } }
    if local is not None:    doc[ "projects" ]   = { "/mnt/lupin-data/lupin": { "mcpServers": { "cosa-voice": { "env": local } } } }
    ( venue[ "home" ] / ".claude.json" ).write_text( json.dumps( doc ) )


def _blocking( out ):
    # The script's own count of blocking results, from its summary line.
    hits = re.findall( r"blocking=(\d+)", out )
    assert len( hits ) == 1, out
    return int( hits[ 0 ] )


def test_A3b_no_registration_warns_and_does_not_block( venue ):
    out = _run( venue )
    hit = _line( out, "no cosa-voice registration in" )
    assert "[UNKN]" in hit and "treated as blocking" not in hit and ".claude.json" in hit
    assert VOICE_VERB in out
    assert "project.mcp.json" not in out, "an absent project file is silent"


def test_A3b_good_registration_passes_and_prints_the_scope_and_value( venue ):
    baseline = _blocking( _run( venue ) )
    _register( venue, { "LUPIN_ROOT": "/r", VOICE_VAR: VOICE_VALUE }, local={ VOICE_VAR: VOICE_VALUE } )
    out = _run( venue )
    hit = _line( out, "carries LUPIN_CONFIG_MGR_CLI_ARGS and it resolves" )
    assert "[OK]" in hit and f"user {VOICE_VALUE};local:/mnt/lupin-data/lupin {VOICE_VALUE}" in hit
    assert VOICE_VERB not in out
    assert _blocking( out ) == baseline


def test_A3b_registration_without_the_variable_blocks_with_the_dev_box_verb( venue ):
    # The defect as it was on the VM: PYTHONPATH and LUPIN_ROOT, no settings pointer.
    baseline = _blocking( _run( venue ) )
    _register( venue, { "PYTHONPATH": "/r/src", "LUPIN_ROOT": "/r" } )
    out = _run( venue )
    hit = _line( out, f"without a usable {VOICE_VAR}" )
    assert "[FAIL]" in hit and "(scope: user)" in hit
    assert VOICE_VERB in out
    assert _blocking( out ) == baseline + 1


def test_A3b_a_local_scope_entry_without_the_variable_blocks_beside_a_good_user_entry( venue ):
    baseline = _blocking( _run( venue ) )
    _register( venue, { VOICE_VAR: VOICE_VALUE }, local={ "LUPIN_ROOT": "/r" } )
    out = _run( venue )
    hit = _line( out, f"without a usable {VOICE_VAR}" )
    assert "[FAIL]" in hit and "(scope: local:/mnt/lupin-data/lupin)" in hit
    assert "claude mcp remove cosa-voice -s local" in out
    assert _blocking( out ) == baseline + 1


@pytest.mark.parametrize( "value, why", [
    ( "x",                                                                  "no config_path= in the value" ),
    ( "config_path=/src/conf/lupin-app.ini config_block_id=Lupin:+Development", "no splainer_path= in the value" ),
    ( VOICE_BAD,                                                            "no [Lupin: No-Such] block" ),
] )
def test_A3b_a_value_that_names_nothing_blocks( venue, value, why ):
    baseline = _blocking( _run( venue ) )
    _register( venue, { VOICE_VAR: value } )
    out = _run( venue )
    hit = _line( out, "does not resolve" )
    assert "[FAIL]" in hit and f"[user: {why}" in hit
    assert _blocking( out ) == baseline + 1


def test_A3b_a_local_value_that_names_nothing_blocks_beside_a_good_user_value( venue ):
    # Every value is resolved, not only the first: the local entry is the one a session
    # started in that directory runs.
    baseline = _blocking( _run( venue ) )
    _register( venue, { VOICE_VAR: VOICE_VALUE }, local={ VOICE_VAR: VOICE_BAD } )
    out = _run( venue )
    hit = _line( out, "does not resolve" )
    assert "[FAIL]" in hit and "[local:/mnt/lupin-data/lupin: no [Lupin: No-Such] block" in hit
    assert "[user:" not in hit
    # install-voice rewrites the user entry only, so the remedy must say how the local one goes.
    assert "claude mcp remove cosa-voice -s local" in out
    assert _blocking( out ) == baseline + 1


def test_A3b_a_value_split_by_a_tab_blocks_though_every_word_is_right( venue ):
    # The settings reader splits on single spaces, so this value gives it no splainer_path.
    baseline = _blocking( _run( venue ) )
    _register( venue, { VOICE_VAR: VOICE_VALUE.replace( " ", "\t", 1 ) } )
    out = _run( venue )
    hit = _line( out, f"without a usable {VOICE_VAR}" )
    assert "[FAIL]" in hit and "(scope: user (value has whitespace other than single spaces))" in hit
    assert _blocking( out ) == baseline + 1


def test_A3b_unparseable_claude_json_is_blocking_unknown( venue ):
    baseline = _blocking( _run( venue ) )
    ( venue[ "home" ] / ".claude.json" ).write_text( "{oops" )
    out = _run( venue )
    hit = _line( out, "is not the shape Claude Code writes" )
    assert "[UNKN]" in hit and "treated as blocking" in hit and "reader rc=3" in hit
    assert _blocking( out ) == baseline + 1


@pytest.mark.parametrize( "which", [ "home", "project" ] )
def test_A3b_a_file_that_exists_and_cannot_be_read_blocks_in_either_place( venue, which ):
    # Not "nothing registered": a file is there and nobody could say what it registers.
    if os.geteuid() == 0: pytest.skip( "root reads a mode-000 file, so the case cannot be built" )
    baseline = _blocking( _run( venue ) )
    f = venue[ "home" ] / ".claude.json" if which == "home" else venue[ "project_mcp" ]
    f.write_text( json.dumps( { "mcpServers": { "cosa-voice": { "env": { VOICE_VAR: VOICE_VALUE } } } } ) )
    f.chmod( 0 )
    try:
        out = _run( venue )
    finally:
        f.chmod( 0o600 )
    hit = _line( out, f"the registration reader could not read {f}" )
    assert "treated as blocking" in hit and "reader rc=4" in hit
    assert _blocking( out ) == baseline + 1


def test_A3b_project_mcp_json_is_held_to_the_same_rule( venue ):
    project  = venue[ "project_mcp" ]
    baseline = _blocking( _run( venue ) )
    def entry( env ): return json.dumps( { "mcpServers": { "cosa-voice": { "env": env } } } )

    project.write_text( json.dumps( { "mcpServers": { "other": {} } } ) )
    assert "project.mcp.json" not in _run( venue ), "a project file that does not register cosa-voice is silent"

    project.write_text( entry( {} ) )
    out = _run( venue )
    hit = _line( out, f"project.mcp.json without a usable {VOICE_VAR}" )
    assert "[FAIL]" in hit and "(scope: project)" in hit
    assert "an entry in a project .mcp.json is removed by hand" in out
    assert _blocking( out ) == baseline + 1

    project.write_text( entry( { VOICE_VAR: VOICE_BAD } ) )
    out = _run( venue )
    hit = _line( out, "project.mcp.json carries" )
    assert "[FAIL]" in hit and "does not resolve: [project: no [Lupin: No-Such] block" in hit
    assert "an entry in a project .mcp.json is removed by hand" in out
    assert _blocking( out ) == baseline + 1

    project.write_text( entry( { VOICE_VAR: VOICE_VALUE } ) )
    out = _run( venue )
    assert "[OK]" in _line( out, "project.mcp.json carries LUPIN_CONFIG_MGR_CLI_ARGS and it resolves" )
    assert _blocking( out ) == baseline

    project.write_text( "{oops" )
    out = _run( venue )
    assert "treated as blocking" in _line( out, "project.mcp.json, or a cosa-voice entry in it, is not the shape" )
    assert _blocking( out ) == baseline + 1


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


# ── B7: the two git hooks are links to the scripts the checkout ships ──────────────────────────

HOOKS = ( ( "pre-commit", "pre-commit-chain.sh" ), ( "pre-push", "pre-push-chain.sh" ) )


def _hook_status( hooks_dir, hook, script ):
    r = _lib( f"pfv_git_hook_status '{hooks_dir}' '{hook}' '{script}'" )
    return r.returncode, r.stdout.strip()


def test_hook_status_matches_a_relative_and_an_absolute_link( tmp_path ):
    script = tmp_path / "src" / "scripts" / "pre-push-chain.sh"; script.parent.mkdir( parents=True ); script.write_text( "#!/bin/sh\n" )
    hooks  = tmp_path / ".git" / "hooks"; hooks.mkdir( parents=True )
    os.symlink( "../../src/scripts/pre-push-chain.sh", hooks / "pre-push" )
    os.symlink( str( script ), hooks / "pre-commit" )

    assert _hook_status( hooks, "pre-push", script )   == ( 0, "MATCH" )
    assert _hook_status( hooks, "pre-commit", script ) == ( 0, "MATCH" )


def test_hook_status_names_each_way_a_hook_can_be_wrong( tmp_path ):
    script = tmp_path / "pre-push-chain.sh"; script.write_text( "#!/bin/sh\n" )
    other  = tmp_path / "other.sh"; other.write_text( "#!/bin/sh\n" )
    hooks  = tmp_path / "hooks"; hooks.mkdir()

    assert _hook_status( hooks, "pre-push", tmp_path / "gone.sh" ) == ( 2, "NO_SCRIPT" )
    assert _hook_status( hooks, "pre-push", script )               == ( 3, "ABSENT" )

    ( hooks / "pre-push" ).write_text( script.read_text() )
    assert _hook_status( hooks, "pre-push", script )               == ( 4, "NOT_LINK" )

    ( hooks / "pre-push" ).unlink(); os.symlink( str( other ), hooks / "pre-push" )
    assert _hook_status( hooks, "pre-push", script )               == ( 5, f"WRONG_TARGET\t{other}" )

    ( hooks / "pre-push" ).unlink(); os.symlink( str( tmp_path / "dangling.sh" ), hooks / "pre-push" )
    assert _hook_status( hooks, "pre-push", script )               == ( 5, f"WRONG_TARGET\t{tmp_path / 'dangling.sh'}" )


@pytest.fixture
def hooked( venue, tmp_path ):
    """The good venue with a hooks folder of its own, both hooks linked to the real scripts."""
    hooks = tmp_path / "hooks"; hooks.mkdir()
    for hook, script in HOOKS: os.symlink( f"{ROOT}/src/scripts/{script}", hooks / hook )
    venue[ "env" ][ "PREFLIGHT_VM_GIT_HOOKS_DIR" ] = str( hooks )
    venue[ "hooks" ] = hooks
    return venue


def test_B7_both_hooks_linked_pass( hooked ):
    out = _run( hooked )
    for hook, script in HOOKS:
        assert "[OK]" in _line( out, f"git hook {hook} links to src/scripts/{script}" )


@pytest.mark.parametrize( "hook,script", HOOKS )
def test_B7_a_missing_hook_warns_by_name_with_the_link_command( hooked, hook, script ):
    ( hooked[ "hooks" ] / hook ).unlink()
    out = _run( hooked )

    assert "[WARN]" in _line( out, f"git hook {hook} is not installed" )
    assert f"ln -sf {ROOT}/src/scripts/{script} {hooked[ 'hooks' ]}/{hook}" in out
    kept = [ h for h, _ in HOOKS if h != hook ][ 0 ]
    assert "[OK]" in _line( out, f"git hook {kept} links to" )


def test_B7_a_hook_that_links_elsewhere_warns_and_names_where( hooked, tmp_path ):
    other = tmp_path / "other.sh"; other.write_text( "#!/bin/sh\n" )
    ( hooked[ "hooks" ] / "pre-push" ).unlink(); os.symlink( str( other ), hooked[ "hooks" ] / "pre-push" )
    out = _run( hooked )

    assert "[WARN]" in _line( out, f"git hook pre-push links to {other}, not to src/scripts/pre-push-chain.sh" )


def test_B7_a_copied_hook_file_warns_that_it_is_not_a_link( hooked ):
    ( hooked[ "hooks" ] / "pre-commit" ).unlink(); ( hooked[ "hooks" ] / "pre-commit" ).write_text( "#!/bin/sh\n" )
    out = _run( hooked )

    assert "[WARN]" in _line( out, "git hook pre-commit in" )
    assert "is a file, not a link" in _line( out, "git hook pre-commit in" )


def test_B7_a_checkout_without_the_script_says_it_predates_the_hook( hooked, tmp_path ):
    # An older checkout: a tree that has the preflight and its library and no hook scripts.
    old = tmp_path / "old"
    ( old / "src" / "scripts" / "lib" ).mkdir( parents=True )
    for rel in ( "src/scripts/preflight-vm.sh", "src/scripts/lib/preflight-vm-lib.sh" ): shutil.copy( f"{ROOT}/{rel}", old / rel )
    hooked[ "env" ][ "LUPIN_ROOT" ] = str( old )
    r = subprocess.run( [ "bash", str( old / "src/scripts/preflight-vm.sh" ), "--phase", "pre" ], env=hooked[ "env" ], capture_output=True, text=True, timeout=120 )

    assert "[WARN]" in _line( r.stdout, "this checkout has no src/scripts/pre-push-chain.sh" )
    assert "it predates the pre-push hook" in r.stdout


# B7 without the override: the folder comes from git, so these build a real repository.

@pytest.fixture
def cloned( venue, tmp_path ):
    """A scratch git tree with the preflight, its library and both hook scripts; no override."""
    tree = tmp_path / "clone"
    ( tree / "src" / "scripts" / "lib" ).mkdir( parents=True )
    for rel in ( "src/scripts/preflight-vm.sh", "src/scripts/lib/preflight-vm-lib.sh", "src/scripts/pre-commit-chain.sh", "src/scripts/pre-push-chain.sh" ):
        shutil.copy( f"{ROOT}/{rel}", tree / rel )
    subprocess.run( [ "git", "init", "-q", str( tree ) ], check=True, capture_output=True, timeout=60 )
    venue[ "env" ][ "LUPIN_ROOT" ] = str( tree )
    venue[ "env" ][ "GIT_CONFIG_NOSYSTEM" ] = "1"      # HOME is already the venue's, so no user config reaches git either
    venue[ "tree" ] = tree
    return venue


def _run_clone( cloned ):
    r = subprocess.run( [ "bash", str( cloned[ "tree" ] / "src/scripts/preflight-vm.sh" ), "--phase", "pre" ], env=cloned[ "env" ], capture_output=True, text=True, timeout=120 )
    return r.stdout


def _link_both( tree, folder ):
    folder.mkdir( parents=True, exist_ok=True )
    for hook, script in HOOKS: os.symlink( str( tree / "src" / "scripts" / script ), folder / hook )


def test_B7_with_no_override_reads_the_clones_own_hooks_folder( cloned ):
    tree = cloned[ "tree" ]
    out  = _run_clone( cloned )
    assert "[WARN]" in _line( out, f"git hook pre-push is not installed in {tree}/.git/hooks" )
    assert f"ln -sf {tree}/src/scripts/pre-push-chain.sh {tree}/.git/hooks/pre-push" in out

    _link_both( tree, tree / ".git" / "hooks" )
    out = _run_clone( cloned )
    for hook, script in HOOKS: assert "[OK]" in _line( out, f"git hook {hook} links to src/scripts/{script}" )


def test_B7_follows_an_absolute_core_hooks_path( cloned, tmp_path ):
    tree, moved = cloned[ "tree" ], tmp_path / "moved-hooks"
    _link_both( tree, tree / ".git" / "hooks" )
    subprocess.run( [ "git", "-C", str( tree ), "config", "core.hooksPath", str( moved ) ], check=True, timeout=60 )

    out = _run_clone( cloned )
    assert "[WARN]" in _line( out, f"git hook pre-push is not installed in {moved}" )
    assert f"ln -sf {tree}/src/scripts/pre-push-chain.sh {moved}/pre-push" in out

    _link_both( tree, moved )
    out = _run_clone( cloned )
    for hook, script in HOOKS: assert "[OK]" in _line( out, f"git hook {hook} links to src/scripts/{script}" )


def test_B7_follows_a_relative_core_hooks_path( cloned ):
    tree = cloned[ "tree" ]
    subprocess.run( [ "git", "-C", str( tree ), "config", "core.hooksPath", "tools/hooks" ], check=True, timeout=60 )

    out = _run_clone( cloned )
    assert "[WARN]" in _line( out, f"git hook pre-commit is not installed in {tree}/tools/hooks" )

    _link_both( tree, tree / "tools" / "hooks" )
    out = _run_clone( cloned )
    for hook, script in HOOKS: assert "[OK]" in _line( out, f"git hook {hook} links to src/scripts/{script}" )


# ── remedy lines name the compose SERVICE, not the container (row fae0bc51, original bug) ──────────────

REAL_CONTAINER = "lupin-rest-cloud-gpu"


def _compose_services():
    with open( COMPOSE, encoding="utf-8" ) as handle:
        return set( yaml.safe_load( handle )[ "services" ] )


def _recreate_target( out, needle ):
    """The word after `--force-recreate` or `--no-deps` on the remedy that follows the finding."""
    hit = out[ out.index( needle ): ].split( "\n" )
    remedy = next( l for l in hit if "docker compose" in l )
    return re.search( r"--no-deps(?:\s+--force-recreate)?\s+(\S+)", remedy ).group( 1 )


def test_the_service_lookup_finds_the_service_the_real_compose_file_declares():
    r = _lib( f"pfv_compose_service '{COMPOSE}' {REAL_CONTAINER}" )
    assert ( r.returncode, r.stdout.strip() ) == ( 0, "lupin-rest" )
    assert r.stdout.strip() in _compose_services()


def test_the_service_lookup_answers_nothing_for_an_unknown_container_or_file( tmp_path ):
    assert _lib( f"pfv_compose_service '{COMPOSE}' no-such-container" ).returncode == 1
    assert _lib( f"pfv_compose_service '{tmp_path}/nope.yml' {REAL_CONTAINER}" ).returncode == 1


def test_the_service_lookup_reads_a_quoted_container_name( tmp_path ):
    f = tmp_path / "c.yml"
    f.write_text( "services:\n  first:\n    image: x\n    container_name: 'one'\n  second:   # note\n    container_name: \"two\"\n" )
    assert _lib( f"pfv_compose_service '{f}' two" ).stdout.strip() == "second"
    assert _lib( f"pfv_compose_service '{f}' one" ).stdout.strip() == "first"


@pytest.fixture
def real_container( venue ):
    venue[ "env" ].update( { "PREFLIGHT_VM_CONTAINER": REAL_CONTAINER, "FAKE_CONTAINER": REAL_CONTAINER } )
    return venue


def test_the_schema_drift_remedy_names_a_declared_service( real_container ):
    """Kills the mutant that prints the container name in the schema-drift remedy."""
    out    = _run( real_container )
    target = _recreate_target( out, "SCHEMA DRIFT" )
    assert target == "lupin-rest" and target in _compose_services() and target != REAL_CONTAINER


def test_the_container_not_running_remedy_names_a_declared_service( real_container ):
    real_container[ "env" ][ "FAKE_CONTAINER" ] = ""
    out    = _run( real_container )
    target = _recreate_target( out, "is not running" )
    assert target == "lupin-rest" and target in _compose_services()


def test_a_label_on_the_running_container_names_the_service( real_container ):
    real_container[ "env" ][ "FAKE_LABEL" ] = "labelled-service"
    assert _recreate_target( _run( real_container ), "SCHEMA DRIFT" ) == "labelled-service"


def test_the_override_beats_the_label_and_the_compose_file( real_container ):
    real_container[ "env" ].update( { "FAKE_LABEL": "labelled-service", "PREFLIGHT_VM_SERVICE": "forced-service" } )
    assert _recreate_target( _run( real_container ), "SCHEMA DRIFT" ) == "forced-service"


def test_with_no_label_and_no_compose_entry_the_remedy_prints_a_placeholder_not_a_guess( venue ):
    """The container `fake-rest` has no label and no compose service."""
    out    = _run( venue )
    target = _recreate_target( out, "SCHEMA DRIFT" )
    assert target.startswith( "<service" ) and "fake-rest" in out[ out.index( "SCHEMA DRIFT" ): ]
    assert "--force-recreate fake-rest" not in out and "--force-recreate lupin-rest" not in out


def test_no_compose_remedy_in_the_script_prints_the_container_name():
    """Only `docker exec`, `inspect`, `logs` and `ps` may take the container name."""
    with open( SCRIPT, encoding="utf-8" ) as handle:
        lines = handle.read().split( "\n" )
    compose_lines = [ l for l in lines if ( "docker compose" in l or "--force-recreate" in l or "up -d --no-deps" in l ) and not l.lstrip().startswith( "#" ) ]
    assert len( compose_lines ) >= 8, "the guard found too few remedy lines to be measuring the script"
    assert [ l for l in compose_lines if "$CONTAINER" in l ] == []
    named = [ l for l in compose_lines if "up -d --no-deps" in l ]
    assert len( named ) >= 8 and all( "$SERVICE" in l for l in named )
