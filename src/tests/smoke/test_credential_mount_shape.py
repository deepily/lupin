#!/usr/bin/env python3
"""
Mount-shape tests for the container Claude Code credential (row c7c60896).

These test a PROPERTY OF THE MOUNT SHAPE using throwaway containers and
scratch files. They do not read, write, or depend on the real
~/.claude/.credentials.json, and they touch no shared infrastructure — so
they stay valid before, during and after the compose change lands.

Background: lupin-rest-dev and lupin-rest-test bind the credential as a
SINGLE FILE, read-only. Claude Code REPLACES that file when it refreshes a
token (measured 2026-08-01: the host inode moved 9437194 -> 9437190 across
`claude auth login`). You cannot rename over a bind-mounted file, so the
container can never persist a refresh and its OAuth re-revokes on a
schedule with no self-heal path.

Venue: :7999 tier — fast, ephemeral, no persistent state, no monopoly.
Requires a working docker CLI; skipped cleanly when unavailable.
"""

import json
import os
import shutil
import subprocess
import pytest


IMAGE       = "alpine"
CTR_PATH    = "/home/u/.claude/.credentials.json"
ORIGINAL    = json.dumps( { "token": "ORIGINAL" } )
REFRESHED   = json.dumps( { "token": "REFRESHED" } )

pytestmark = pytest.mark.skipif(
    shutil.which( "docker" ) is None,
    reason="docker CLI not available"
)


def _run_in_container( mounts: list, script: str, user: str = None ) -> subprocess.CompletedProcess:
    """
    Run a shell snippet in a throwaway container with the given -v mounts.

    Requires:
        - mounts is a list of docker -v argument strings
        - script is a POSIX sh snippet
        - user, if given, is a "uid:gid" string

    Ensures:
        - container is removed regardless of outcome (--rm)
        - returns the CompletedProcess with captured output
    """
    cmd = [ "docker", "run", "--rm" ]
    if user:
        cmd += [ "--user", user ]
    for m in mounts:
        cmd += [ "-v", m ]
    cmd += [ IMAGE, "sh", "-c", script ]
    return subprocess.run( cmd, capture_output=True, text=True, timeout=120 )


@pytest.fixture
def cred_dir( tmp_path ):
    """A scratch directory holding only a fake credential file."""
    d = tmp_path / "creds"
    d.mkdir()
    ( d / ".credentials.json" ).write_text( ORIGINAL )
    return d


@pytest.fixture
def cred_file( tmp_path ):
    """A standalone scratch credential file, for the single-file shape."""
    f = tmp_path / "single.json"
    f.write_text( ORIGINAL )
    return f


REPLACE_BY_RENAME = (
    f"printf '%s' '{REFRESHED}' > /tmp/new.json && "
    f"mv /tmp/new.json {CTR_PATH} && echo RENAME_OK || echo RENAME_FAIL"
)


class TestSingleFileBindCannotPersistARefresh:
    """Pins WHY the current production shape is broken."""

    def test_readonly_single_file_rejects_refresh( self, cred_file ):
        """Today's shape: the refresh cannot land at all."""
        r = _run_in_container(
            [ f"{cred_file}:{CTR_PATH}:ro" ], REPLACE_BY_RENAME
        )
        assert "RENAME_FAIL" in r.stdout
        assert cred_file.read_text() == ORIGINAL

    def test_readwrite_single_file_still_rejects_refresh( self, cred_file ):
        """
        Dropping :ro is NOT sufficient — the kernel refuses to replace a
        mount point, which is exactly the write Claude Code performs.
        This is the test that killed the cheap fix.
        """
        r = _run_in_container(
            [ f"{cred_file}:{CTR_PATH}" ], REPLACE_BY_RENAME
        )
        assert "RENAME_FAIL" in r.stdout, (
            "a read-write single-file bind accepted a rename — if this ever "
            "passes, re-evaluate the cheap fix for c7c60896"
        )
        assert cred_file.read_text() == ORIGINAL


class TestDedicatedDirectoryMountShape:
    """Pins the proposed replacement, including the failure modes it must not have."""

    def test_refresh_persists_to_host( self, cred_dir ):
        """A directory bind lets the container's refresh reach the host."""
        r = _run_in_container(
            [ f"{cred_dir}:/home/u/.claude" ], REPLACE_BY_RENAME
        )
        assert "RENAME_OK" in r.stdout
        assert json.loads( ( cred_dir / ".credentials.json" ).read_text() )[ "token" ] == "REFRESHED"

    def test_coexists_with_nested_sessions_bind( self, cred_dir, tmp_path ):
        """
        Production nests a sessions/ bind inside ~/.claude. Replacing the
        credential bind must not shadow it.
        """
        sessions = tmp_path / "sessions"
        sessions.mkdir()
        ( sessions / "marker.txt" ).write_text( "session-data" )

        r = _run_in_container(
            [ f"{cred_dir}:/home/u/.claude", f"{sessions}:/home/u/.claude/sessions" ],
            f"cat {CTR_PATH} && cat /home/u/.claude/sessions/marker.txt && " + REPLACE_BY_RENAME
        )
        assert "session-data" in r.stdout, "nested sessions bind was shadowed"
        assert "RENAME_OK" in r.stdout

    def test_refresh_preserves_host_ownership_when_run_as_host_uid( self, cred_dir ):
        """
        THE ONE THAT MATTERS MOST (Maria, 2026-08-01).

        Run as the host uid — the way the compute containers are configured —
        a refresh must leave the host credential owned by the host user, so
        Rick's own `claude auth login` can still write it.
        """
        host_uid = os.getuid()
        host_gid = os.getgid()

        r = _run_in_container(
            [ f"{cred_dir}:/home/u/.claude" ],
            REPLACE_BY_RENAME,
            user=f"{host_uid}:{host_gid}"
        )
        assert "RENAME_OK" in r.stdout

        st = ( cred_dir / ".credentials.json" ).stat()
        assert st.st_uid == host_uid and st.st_gid == host_gid, (
            f"refresh left the host credential owned by {st.st_uid}:{st.st_gid}, "
            f"not {host_uid}:{host_gid}"
        )

    def test_root_container_would_steal_the_credential( self, cred_dir ):
        """
        The negative control, and the reason the uid matters.

        A container running as ROOT refreshes the token and leaves the host
        file owned by root:root. Rick's own login then fails to write it,
        and it surfaces as "auth randomly stopped working" with no obvious
        cause — a worse failure than the one being fixed.

        This test PASSES by demonstrating the hazard. If it ever starts
        failing, docker's ownership semantics changed and the guard below
        can be revisited.
        """
        r = _run_in_container( [ f"{cred_dir}:/home/u/.claude" ], REPLACE_BY_RENAME )
        assert "RENAME_OK" in r.stdout

        st = ( cred_dir / ".credentials.json" ).stat()
        assert st.st_uid == 0, (
            "expected a root container to leave a root-owned file; docker's "
            "ownership behaviour appears to have changed"
        )
        assert st.st_uid != os.getuid()

    def test_compute_containers_run_as_the_host_uid( self ):
        """
        The guard that makes the two tests above load-bearing: assert the
        REAL containers run as the host uid. This is what would actually
        regress — a compose change dropping the user directive would arm
        the hazard pinned above.
        """
        host_uid = os.getuid()
        checked  = []

        for ctr in ( "lupin-rest-dev", "lupin-rest-test" ):
            probe = subprocess.run(
                [ "docker", "exec", ctr, "id", "-u" ],
                capture_output=True, text=True, timeout=60
            )
            if probe.returncode != 0:
                continue  # container not up on this box; nothing to assert
            checked.append( ctr )
            assert probe.stdout.strip() == str( host_uid ), (
                f"{ctr} runs as uid {probe.stdout.strip()}, not the host uid {host_uid}. "
                f"With a directory-mounted credential, its token refresh would take "
                f"ownership of the host file and break the host's own login."
            )

        if not checked:
            pytest.skip( "neither compute container is running on this box" )


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
