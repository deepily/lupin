"""
Three wrong readings in the VM preflight, measured after a deploy.

The compose check printed unknown-blocking for a key that compose defaults.
Section E read the Vertex variables from the ssh shell, so a container with all three set looked unset.
The mount check counted only git-backed mounts (6 of 7) and called them all the external mounts.
Each test was red before the fix. Venue: the :7999 dev server. No ssh, no network, no real docker.
"""
import os
import stat
import subprocess

import pytest

import cosa.utils.util as cu

ROOT   = cu.get_project_root()
SCRIPT = f"{ROOT}/src/scripts/preflight-vm.sh"

MOUNTS = [
    ( "/mnt/lupin-data/lupin",                    "/var/external-projects/lupin" ),
    ( "/mnt/lupin-data/google/parallel-search",   "/var/external-projects/google/parallel-search" ),
    ( "/mnt/lupin-data/planning-is-prompting",    "/var/external-projects/planning-is-prompting" ),
]
NO_GIT = "/var/external-projects/planning-is-prompting"

FAKE_DOCKER = r'''#!/bin/bash
case "$1" in
  ps) echo "$FAKE_CONTAINER" ;;
  inspect)
    case "$*" in
      *Config.Labels*) printf %s "" ;;
      *State.Running*) echo true ;;
      *Source*) cat "$FAKE_MOUNTS_SRC" ;;
      *Destination*) cut -f2 "$FAKE_MOUNTS_SRC" ;;
    esac ;;
  exec)
    shift 2
    case "$*" in
      *"/proc/1/environ"*) [ -f "$FAKE_ENVIRON_FILE" ] && cat "$FAKE_ENVIRON_FILE" || exit 1 ;;
      *".git"*)
        for w in $FAKE_NOGIT; do case "$*" in *"$w/.git"*) exit 0 ;; esac; done
        echo HEAD ;;
      "git -C "*) echo deadbeef ;;
      sh*ls*) echo x ;;
      *) exit 1 ;;
    esac ;;
  *) exit 1 ;;
esac
'''


@pytest.fixture
def venue( tmp_path ):
    """A fake venue: a stand-in docker, three external mounts, an empty home."""
    home = tmp_path / "home"; ( home / ".claude" / "projects" ).mkdir( parents=True )
    bindir = tmp_path / "bin"; bindir.mkdir()
    fake = bindir / "docker"; fake.write_text( FAKE_DOCKER ); fake.chmod( fake.stat().st_mode | stat.S_IEXEC )
    msrc = tmp_path / "mounts.tsv"; msrc.write_text( "".join( f"{s}\t{t}\n" for s, t in MOUNTS ) )
    ambient = { k: v for k, v in os.environ.items()
                if not k.startswith( ( "PREFLIGHT_VM_", "CLAUDE_CODE_USE_VERTEX", "CLOUD_ML_REGION", "ANTHROPIC_VERTEX", "VERTEX_REGION" ) ) }
    env = { **ambient, "HOME": str( home ), "PATH": f"{bindir}:{os.environ['PATH']}",
            "PREFLIGHT_VM_CONTAINER": "fake-rest", "FAKE_CONTAINER": "fake-rest", "FAKE_MOUNTS_SRC": str( msrc ),
            "FAKE_NOGIT": "", "FAKE_ENVIRON_FILE": str( tmp_path / "no-environ" ),
            "PREFLIGHT_VM_COMPOSE": f"{ROOT}/docker-compose.cloud-gpu.yml", "LUPIN_ROOT": ROOT,
            "PREFLIGHT_VM_ENVFILE": str( tmp_path / "cloud-gpu.env" ),
            "PREFLIGHT_VM_PROJECT_MCP_JSON": str( tmp_path / "project.mcp.json" ) }
    ( tmp_path / "cloud-gpu.env" ).write_text( "LUPIN_GCP_PROJECT_ID=proj-x\n" )
    return { "env": env, "tmp": tmp_path }


def _run( venue ):
    r = subprocess.run( [ "bash", SCRIPT, "--phase", "pre" ], env=venue[ "env" ], capture_output=True, text=True, timeout=120 )
    return r.stdout


def _line( out, needle ):
    hits = [ l for l in out.split( "\n" ) if needle in l ]
    assert hits, f"no line containing {needle!r} in:\n{out}"
    return "\n".join( hits )


def _container_env( venue, text ):
    path = venue[ "tmp" ] / "container-environ"
    path.write_text( text )
    venue[ "env" ][ "FAKE_ENVIRON_FILE" ] = str( path )


VERTEX_ON = "CLAUDE_CODE_USE_VERTEX=1\nCLOUD_ML_REGION=global\nANTHROPIC_VERTEX_PROJECT_ID=proj-x\n"


# ── 1. a defaulted COMPOSE key is not an unknown ─────────────────────────────

def test_a_defaulted_optional_compose_key_does_not_block( venue ):
    line = _line( _run( venue ), "LUPIN_VERTEX_REGION" )
    assert "[UNKN]" not in line and "treated as blocking" not in line, line
    assert "[OK]" in line and "cannot abort" in line, line


def _synthetic_tree( venue, requirement ):
    """Build a one-row contract and a one-key compose file."""
    tree = venue[ "tmp" ] / "tree"; ( tree / "src" / "conf" ).mkdir( parents=True )
    ( tree / "src" / "conf" / "env-contract.tsv" ).write_text( f"SOME_KEY\tCOMPOSE\tcloud-gpu.env\tLITERAL\t{requirement}\tx\n" )
    compose = venue[ "tmp" ] / "compose.yml"
    compose.write_text( "services:\n  fake-svc:\n    container_name: fake-rest\n    environment:\n      SOME_KEY: ${SOME_KEY:-d}\n" )
    venue[ "env" ][ "LUPIN_ROOT" ] = str( tree ); venue[ "env" ][ "PREFLIGHT_VM_COMPOSE" ] = str( compose )


def test_a_defaulted_compose_key_the_contract_calls_required_still_blocks( venue ):
    # The contract says a value is owed, but compose would run without one: the two disagree and nothing here can say which is right.
    _synthetic_tree( venue, "REQUIRED" )
    line = _line( _run( venue ), "SOME_KEY" )
    assert "[UNKN]" in line and "treated as blocking" in line and "DEFAULTED" in line, line


def test_a_defaulted_compose_key_the_contract_calls_optional_passes( venue ):
    _synthetic_tree( venue, "OPTIONAL" )
    line = _line( _run( venue ), "SOME_KEY" )
    assert "[OK]" in line and "[UNKN]" not in line, line


# ── 2. section E reads the container, not the ssh shell ──────────────────────

def test_E_reads_vertex_from_the_container_when_the_ssh_shell_has_none( venue ):
    _container_env( venue, VERTEX_ON )
    out = _run( venue )
    assert "Vertex not enabled in fake-rest" not in out, out
    assert "[OK]" in _line( out, "CLOUD_ML_REGION=global in fake-rest" )
    assert "[OK]" in _line( out, "ANTHROPIC_VERTEX_PROJECT_ID set in fake-rest" )


def test_E_a_regional_value_in_the_container_warns_whatever_the_shell_says( venue ):
    venue[ "env" ][ "CLOUD_ML_REGION" ] = "global"
    _container_env( venue, "CLAUDE_CODE_USE_VERTEX=1\nCLOUD_ML_REGION=us-east5\nANTHROPIC_VERTEX_PROJECT_ID=proj-x\n" )
    line = _line( _run( venue ), "in fake-rest — Opus 4.8" )
    assert "[WARN]" in line and "us-east5" in line, line


def test_E_a_container_without_the_project_id_warns( venue ):
    _container_env( venue, "CLAUDE_CODE_USE_VERTEX=1\nCLOUD_ML_REGION=global\n" )
    assert "[WARN]" in _line( _run( venue ), "ANTHROPIC_VERTEX_PROJECT_ID unset in fake-rest" )


def test_E_a_container_without_vertex_skips_the_region_checks_even_if_the_shell_has_it( venue ):
    venue[ "env" ][ "CLAUDE_CODE_USE_VERTEX" ] = "1"; venue[ "env" ][ "CLOUD_ML_REGION" ] = "us-east5"
    _container_env( venue, "SOME_OTHER=1\n" )
    out = _run( venue )
    assert "[OK]" in _line( out, "Vertex not enabled in fake-rest" )
    assert "in fake-rest — Opus 4.8" not in out, out
    assert "[WARN]" in _line( out, "CLOUD_ML_REGION='us-east5' in the host shell" )


def test_E_an_unreadable_container_environment_is_not_a_pass( venue ):
    out = _run( venue )      # the fake has no /proc/1/environ to give
    line = _line( out, "cannot read the environment of fake-rest" )
    assert "[UNKN]" in line and "[OK]" not in line, line
    assert "Vertex not enabled in fake-rest" not in out and "in fake-rest — Opus 4.8" not in out, out


def test_E_a_per_model_region_override_in_the_container_warns( venue ):
    _container_env( venue, VERTEX_ON + "VERTEX_REGION_CLAUDE_5_OPUS=us-east5\n" )
    assert "[WARN]" in _line( _run( venue ), "VERTEX_REGION_CLAUDE_5_OPUS is set in fake-rest" )


def test_E_no_per_model_override_in_the_container_passes_even_if_the_shell_sets_one( venue ):
    venue[ "env" ][ "VERTEX_REGION_CLAUDE_5_OPUS" ] = "us-east5"
    _container_env( venue, VERTEX_ON )
    assert "[OK]" in _line( _run( venue ), "no per-model Vertex region override set in fake-rest" )


# ── 3. the external-mount count names its population ─────────────────────────

def test_C10_the_count_names_the_git_backed_mounts_and_the_one_that_is_not( venue ):
    venue[ "env" ][ "FAKE_NOGIT" ] = NO_GIT
    line = _line( _run( venue ), "git rev-parse HEAD succeeds" )
    assert "[OK]" in line and "all 2 git-backed external-project mounts" in line, line
    assert "3 external mounts in all" in line and f"not git-backed: {NO_GIT}" in line, line


def test_C10_when_every_mount_is_git_backed_the_line_does_not_mention_any_other( venue ):
    line = _line( _run( venue ), "git rev-parse HEAD succeeds" )
    assert "all 3 external-project mounts" in line and "not git-backed" not in line, line


# ── 2b. the host shell stays a witness, beside the container ─────────────────

def test_E_the_host_shell_is_still_read_and_the_line_names_it( venue ):
    venue[ "env" ].update( CLAUDE_CODE_USE_VERTEX="1", CLOUD_ML_REGION="us-east5", VERTEX_REGION_CLAUDE_5_OPUS="us-east5" )
    venue[ "env" ].pop( "ANTHROPIC_VERTEX_PROJECT_ID", None )
    _container_env( venue, VERTEX_ON )
    out = _run( venue )
    assert "[WARN]" in _line( out, "CLOUD_ML_REGION='us-east5' in the host shell" )
    assert "[WARN]" in _line( out, "ANTHROPIC_VERTEX_PROJECT_ID unset in the host shell" )
    assert "[WARN]" in _line( out, "VERTEX_REGION_CLAUDE_5_OPUS is set in the host shell" )
    assert "[OK]" in _line( out, "CLOUD_ML_REGION=global in fake-rest" )


def test_E_a_good_host_shell_passes_each_host_line( venue ):
    venue[ "env" ].update( CLAUDE_CODE_USE_VERTEX="1", CLOUD_ML_REGION="global", ANTHROPIC_VERTEX_PROJECT_ID="proj-x" )
    out = _run( venue )
    assert "[OK]" in _line( out, "CLOUD_ML_REGION=global in the host shell" )
    assert "[OK]" in _line( out, "ANTHROPIC_VERTEX_PROJECT_ID set in the host shell" )
    assert "[OK]" in _line( out, "no per-model Vertex region override set in the host shell" )


def test_E_a_host_shell_without_vertex_skips_only_the_host_checks( venue ):
    _container_env( venue, VERTEX_ON )
    out = _run( venue )
    assert "[OK]" in _line( out, "Vertex not enabled in the host shell" )
    assert "[OK]" in _line( out, "CLOUD_ML_REGION=global in fake-rest" )
