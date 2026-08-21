#!/usr/bin/env python3
"""
Unit tests: wait-for-container-restart.sh refuses the OLD process.

THE DEFECT THIS GUARDS ( row 1c36199e, Mr Radio's catch 2026-08-21 ): counting consecutive
health 200s defends against a server answering in bursts. It does NOT defend against the
other lie — right after `docker restart` is issued, the OLD process can answer three times
inside the 1.5-second window three checks at 0.5s spacing covers. No count fixes that.
Identity does: the container's own StartedAt must be newer than the moment we asked.

`docker` is stubbed on PATH, so nothing here starts, stops or inspects a real container.
"""
import os
import subprocess
import textwrap

import pytest

SCRIPT = os.path.join( os.environ[ "LUPIN_ROOT" ], "src/scripts/lib/wait-for-container-restart.sh" )


def _docker_stub( tmp_path, script_body ):
    """Put a fake `docker` first on PATH and return the env to run with."""
    stub = tmp_path / "docker"
    stub.write_text( "#!/usr/bin/env bash\n" + textwrap.dedent( script_body ) )
    stub.chmod( 0o755 )
    env = dict( os.environ )
    env[ "PATH" ] = f"{tmp_path}:{env[ 'PATH' ]}"
    return env


def _run( env, *args, timeout=30 ):
    return subprocess.run(
        [ "bash", SCRIPT, *args, "--interval", "0.05" ],
        capture_output=True, text=True, timeout=timeout, env=env
    )


def test_a_container_started_after_the_restart_passes( tmp_path ):
    env = _docker_stub( tmp_path, """
        echo "2026-08-21T16:00:00.000000000Z"
    """ )
    not_before = 1787328000                     # 2026-08-21 16:00:00 UTC
    result = _run( env, "lupin-rest-dev", str( not_before ), "--timeout", "5" )
    assert result.returncode == 0, result.stderr


def test_the_old_process_is_refused( tmp_path ):
    """THE POINT OF THE FILE. A container that has been up for an hour is not a restart."""
    env = _docker_stub( tmp_path, """
        echo "2026-08-21T15:00:00.000000000Z"
    """ )
    not_before = 1787328000                     # an hour after that StartedAt
    result = _run( env, "lupin-rest-dev", str( not_before ), "--timeout", "2" )
    assert result.returncode == 1, "the old process was accepted as a fresh restart"
    assert "did not report a start newer" in result.stderr
    assert "still the old process" in result.stdout


def test_it_waits_through_the_old_process_and_then_passes( tmp_path ):
    """The realistic shape: old StartedAt for a few polls, then the new one appears."""
    counter = tmp_path / "count"
    counter.write_text( "0" )
    env = _docker_stub( tmp_path, f"""
        n=$( cat {counter} )
        echo $(( n + 1 )) > {counter}
        if [ "$n" -lt 3 ]; then
            echo "2026-08-21T15:00:00.000000000Z"
        else
            echo "2026-08-21T16:00:01.000000000Z"
        fi
    """ )
    result = _run( env, "lupin-rest-dev", "1787328000", "--timeout", "10" )
    assert result.returncode == 0, result.stderr
    assert "still the old process" in result.stdout, "passed without ever seeing the old one"


def test_an_unreadable_container_keeps_waiting_then_fails( tmp_path ):
    """A docker that errors must not be read as success."""
    env = _docker_stub( tmp_path, """
        exit 1
    """ )
    result = _run( env, "nope", "1787328000", "--timeout", "2" )
    assert result.returncode == 1
    assert "could not read StartedAt" in result.stdout


def test_a_never_started_container_is_not_mistaken_for_old_and_fine( tmp_path ):
    """Docker's zero time must keep the wait going, not satisfy it."""
    env = _docker_stub( tmp_path, """
        echo "0001-01-01T00:00:00Z"
    """ )
    result = _run( env, "lupin-rest-dev", "1787328000", "--timeout", "2" )
    assert result.returncode == 1


@pytest.mark.parametrize( "bad", [ ( "lupin-rest-dev", "not-a-number" ), ( "", "1787328000" ) ] )
def test_bad_usage_is_refused( tmp_path, bad ):
    env = _docker_stub( tmp_path, 'echo "2026-08-21T16:00:00.000000000Z"' )
    result = _run( env, bad[ 0 ], bad[ 1 ], "--timeout", "2" )
    assert result.returncode == 2
