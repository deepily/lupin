"""
The smoke admin credentials probe of the container preflight, run as a sourced function.

A stub `docker` function stands in for the container: it prints the names of the variables the
container would report empty, or fails. Venue: :7999 (unit); no docker and no container needed.
"""

import os
import subprocess

ROOT   = os.environ[ "LUPIN_ROOT" ]
PROBE  = os.path.join( ROOT, "src/scripts/lib/preflight-smoke-admin-probe.sh" )
SCRIPT = os.path.join( ROOT, "src/scripts/preflight-test-container.sh" )

DRIVER = """
CONTAINER=c1
run_cmd()  { "$@"; }
say_ok()   { echo "OK: $1"; }
say_warn() { echo "WARN: $1"; }
remedy()   { echo "REMEDY: $1"; }
docker() {
    printf '%s\\n' "$*" > "$ARGS_FILE"
    case "$STUB" in
        fail) return 1 ;;
        *)    printf '%s' "$STUB" ;;
    esac
}
source "$PROBE"
probe_smoke_admin_credentials
"""


def _run( tmp_path, stub ):
    args_file = tmp_path / "args.txt"
    env = dict( os.environ, PROBE=PROBE, STUB=stub, ARGS_FILE=str( args_file ) )
    out = subprocess.run( [ "bash", "-c", DRIVER ], env=env, capture_output=True, text=True, timeout=30 ).stdout
    return out, ( args_file.read_text() if args_file.exists() else "" )


def test_both_variables_set_is_ok( tmp_path ):
    out, _args = _run( tmp_path, "" )
    assert out.startswith( "OK: smoke admin credentials are set" ) and "WARN" not in out


def test_one_empty_variable_is_named_alone( tmp_path ):
    out, _args = _run( tmp_path, "LUPIN_TEST_ADMIN_PASSWORD " )
    assert "WARN: smoke admin credentials are empty in the container: LUPIN_TEST_ADMIN_PASSWORD (" in out
    assert "LUPIN_TEST_ADMIN_EMAIL" not in out


def test_both_empty_names_both_and_gives_the_recreate_remedy( tmp_path ):
    out, _args = _run( tmp_path, "LUPIN_TEST_ADMIN_EMAIL LUPIN_TEST_ADMIN_PASSWORD " )
    assert "empty in the container: LUPIN_TEST_ADMIN_EMAIL LUPIN_TEST_ADMIN_PASSWORD (" in out
    assert "bash -ic" in out and "--force-recreate lupin-rest-test" in out


def test_an_unreadable_container_is_a_warning_not_ok( tmp_path ):
    out, _args = _run( tmp_path, "fail" )
    assert "WARN: smoke admin credentials could not be read from container 'c1'" in out and "OK" not in out


def test_the_probe_asks_the_container_for_both_names_and_never_for_values( tmp_path ):
    """The command tests both names inside the container and prints only a name."""
    _out, args = _run( tmp_path, "" )
    assert args.startswith( "exec c1 sh -c " )
    assert "LUPIN_TEST_ADMIN_EMAIL LUPIN_TEST_ADMIN_PASSWORD" in args
    assert "printf '%s ' \"$n\"" in args and "echo" not in args


def test_the_container_preflight_sources_and_calls_the_probe():
    text = open( SCRIPT ).read()
    assert "lib/preflight-smoke-admin-probe.sh" in text
    assert text.index( "probe_smoke_admin_credentials" ) < text.index( "# ── Summary" )
