"""
The Claude Code parity probe warns when a container's CLI is far behind the host's.

Each case runs the real shell function with a fake `claude` and a fake `docker` found first.
"""

import os
import subprocess
import textwrap

import pytest

ROOT  = os.environ[ "LUPIN_ROOT" ]
PROBE = ROOT + "/src/scripts/lib/claude-cli-parity-probe.sh"
CHECK = ROOT + "/src/scripts/check-claude-cli-parity.sh"


def _shims( tmp_path, host, image, running=True ):
    """
    Write a fake claude and a fake docker into tmp_path and return a path that finds them.

    Requires:
        - host and image are version strings, or "" to make that command print nothing
    Ensures:
        - fake docker answers `ps` with the container name when running, and `exec` with image
    """
    ( tmp_path / "claude" ).write_text( f"#!/bin/sh\n[ -n '{host}' ] && echo '{host} (Claude Code)'\nexit 0\n" )
    ( tmp_path / "docker" ).write_text( textwrap.dedent( f"""\
        #!/bin/sh
        case "$1" in
            ps)   {'echo lupin-rest-dev' if running else 'true'} ;;
            exec) [ -n '{image}' ] && echo '{image}'; exit 0 ;;
        esac
        """ ) )
    for name in ( "claude", "docker" ): os.chmod( tmp_path / name, 0o755 )
    return f"{tmp_path}:{os.environ[ 'PATH' ]}"


def _run( argv, path, extra_env=None ):
    return subprocess.run( argv, capture_output=True, text=True, env={ **os.environ, "PATH": path, **( extra_env or {} ) } )


def _probe( path, extra_env=None ):
    return _run( [ "bash", "-c", f"source {PROBE}; probe_claude_cli_parity lupin-rest-dev" ], path, extra_env )


@pytest.mark.parametrize( "host, image, lag", [
    ( "2.1.317", "2.1.317", "0" ),
    ( "2.1.317", "2.1.161", "156" ),
    ( "2.1.317", "2.1.400", "0" ),
    ( "2.2.5",   "2.1.400", "11" ),
    ( "2.1.317", "2.2.0",   "0" ),
    ( "2.9.1",   "10.0.0",  "0" ),
] )
def test_the_lag_is_the_patch_difference_inside_one_minor_and_the_limit_plus_one_across_minors( host, image, lag ):
    out = subprocess.run( [ "bash", "-c", f"source {PROBE}; cli_version_lag {host} {image}" ], capture_output=True, text=True )
    assert out.stdout.strip() == lag


def test_an_image_at_the_host_version_is_ok( tmp_path ):
    done = _probe( _shims( tmp_path, "2.1.317", "2.1.317" ) )
    assert done.returncode == 0 and "[OK]" in done.stdout


def test_an_image_far_behind_warns_and_names_the_remedy( tmp_path ):
    done = _probe( _shims( tmp_path, "2.1.317", "2.1.161" ) )
    assert done.returncode == 1 and "[WARN]" in done.stdout and "bundles Claude Code 2.1.161, host runs 2.1.317" in done.stdout and "remedy:" in done.stdout


def test_the_limit_is_read_from_the_environment( tmp_path ):
    path = _shims( tmp_path, "2.1.317", "2.1.310" )
    assert _probe( path ).returncode == 0 and _probe( path, { "CLAUDE_CLI_MAX_LAG": "5" } ).returncode == 1


@pytest.mark.parametrize( "host, image", [ ( "", "2.1.317" ), ( "2.1.317", "" ) ] )
def test_an_unreadable_version_is_return_2_not_a_pass( tmp_path, host, image ):
    done = _probe( _shims( tmp_path, host, image ) )
    assert done.returncode == 2 and "[WARN]" in done.stdout


def test_the_standalone_script_aborts_with_2_when_the_container_is_not_running( tmp_path ):
    done = _run( [ "bash", CHECK ], _shims( tmp_path, "2.1.317", "2.1.317", running=False ) )
    assert done.returncode == 2 and "[ABORT]" in done.stdout


def test_the_standalone_script_reports_through_the_probe( tmp_path ):
    done = _run( [ "bash", CHECK ], _shims( tmp_path, "2.1.317", "2.1.161" ) )
    assert done.returncode == 1 and "[WARN]" in done.stdout


def test_the_standalone_script_aborts_with_2_when_docker_is_unreachable( tmp_path ):
    shims = _shims( tmp_path, "2.1.317", "2.1.317" )
    ( tmp_path / "docker" ).write_text( "#!/bin/sh\nexit 1\n" )
    done  = _run( [ "bash", CHECK ], shims )
    assert done.returncode == 2 and "[ABORT]" in done.stdout


@pytest.mark.parametrize( "image, ok, warn", [ ( "2.1.317", 1, 0 ), ( "2.1.161", 0, 1 ), ( "", 0, 1 ) ] )
def test_the_probe_reports_through_the_callers_say_functions_as_the_preflight_does( tmp_path, image, ok, warn ):
    script = f'ok=0; warn=0; say_ok() {{ ok=$((ok+1)); }}; say_warn() {{ warn=$((warn+1)); }}; source {PROBE}; probe_claude_cli_parity lupin-rest-dev >/dev/null; echo "$ok $warn"'
    done   = _run( [ "bash", "-c", script ], _shims( tmp_path, "2.1.317", image ) )
    assert done.stdout.split() == [ str( ok ), str( warn ) ]


def test_the_preflight_sources_the_probe_and_calls_it_without_failing_the_run():
    text = open( ROOT + "/src/scripts/preflight-test-container.sh" ).read()
    assert 'source "$(dirname "${BASH_SOURCE[0]}")/lib/claude-cli-parity-probe.sh"' in text and 'probe_claude_cli_parity "${CONTAINER}" || true' in text
