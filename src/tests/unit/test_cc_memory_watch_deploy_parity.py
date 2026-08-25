"""
Guard: the RUNNING memory watcher must be the code in the repo.

WHY THIS EXISTS. lupin-cc-memory-watch.service does not run
src/cosa/utils/cc_memory_watch.py. It runs a COPY under
~/.local/lib/lupin-cc-memory-watch, reached via the unit's PYTHONPATH. So
editing the tracked file changes nothing about what is sampling memory until
somebody copies it across and restarts the service — and nothing announced
that gap.

Measured 2026-08-25: the two files were byte-identical (sha256 21f833dbd3dd…),
and the only reason they agreed was that a person had reconciled them by hand
ninety minutes earlier. That is a state, not a mechanism. A grep across
src/tests for the deployed path returned nothing.

⚠️ AND THERE IS NO INSTALLER. No script under src/scripts references the
deployed path, and the unit's own Documentation= line points at
src/scripts/watch-cc-memory.sh, which does not exist. The copy is done by
hand, which makes drift MORE likely, not less — so the failure message below
carries the exact commands rather than pointing at a tool that is not there.

The consequence of drift is quiet and expensive: the watcher keeps running,
keeps writing plausible samples, and reports a quantity the repo no longer
computes. That is how ab2a321c could have been "landed" for a full day while
the log went on recording the old noun.
"""
import hashlib
import os
from pathlib import Path

import pytest

import cosa.utils.util as cu

# Overridable so this is not welded to one operator's home directory; the
# default is the path lupin-cc-memory-watch.service actually puts on PYTHONPATH.
DEPLOYED_ENV     = "LUPIN_CC_MEMORY_WATCH_DEPLOYED"
DEPLOYED_DEFAULT = Path.home() / ".local" / "lib" / "lupin-cc-memory-watch" / "cc_memory_watch.py"

TRACKED = Path( cu.get_project_root() ) / "src" / "cosa" / "utils" / "cc_memory_watch.py"


def deployed_path():
    """
    Resolve where the service's copy of the watcher lives.

    Requires:
        - nothing; the path need not exist

    Ensures:
        - returns the LUPIN_CC_MEMORY_WATCH_DEPLOYED override when set and non-blank
        - otherwise returns the service's default install location
    """
    override = os.environ.get( DEPLOYED_ENV )
    if override and override.strip(): return Path( override )
    return DEPLOYED_DEFAULT


def sha256_of( path ):
    """
    Hash a file's bytes.

    Requires:
        - path names a readable file

    Ensures:
        - returns the lowercase hex sha256 digest
    """
    return hashlib.sha256( path.read_bytes() ).hexdigest()


class TestDeployedWatcherMatchesRepo:

    def test_tracked_watcher_exists( self ):
        # If this moves, the guard below silently stops guarding anything.
        assert TRACKED.is_file(), f"tracked watcher missing at {TRACKED}"

    def test_deployed_copy_is_byte_identical_to_the_tracked_file( self ):
        deployed = deployed_path()
        if not deployed.is_file():
            # Skip LOUDLY and specifically: a fresh box or CI has no install, and
            # going red there would train people to ignore this test. Run with
            # `-rs` to see this reason rather than a bare 's'.
            pytest.skip(
                f"no deployed watcher at {deployed} — nothing installed on this box, "
                f"so there is no deploy/repo pair to compare. Set {DEPLOYED_ENV} to "
                f"point at one if it lives elsewhere."
            )

        deployed_sha = sha256_of( deployed )
        tracked_sha  = sha256_of( TRACKED )
        assert deployed_sha == tracked_sha, (
            f"THE RUNNING WATCHER IS NOT THE CODE IN THE REPO.\n"
            f"  deployed {deployed}\n"
            f"           sha256 {deployed_sha}\n"
            f"  tracked  {TRACKED}\n"
            f"           sha256 {tracked_sha}\n"
            f"The service samples the DEPLOYED copy, so edits to the tracked file "
            f"have not taken effect. There is no installer script; reconcile by hand:\n"
            f"  cp {TRACKED} {deployed}\n"
            f"  systemctl --user restart lupin-cc-memory-watch.service\n"
            f"Then confirm the log is emitting what you expect before trusting it."
        )


class TestDeployedPathResolution:

    def test_env_override_wins_when_set( self, monkeypatch ):
        monkeypatch.setenv( DEPLOYED_ENV, "/somewhere/else/cc_memory_watch.py" )
        assert deployed_path() == Path( "/somewhere/else/cc_memory_watch.py" )

    def test_blank_override_falls_back_to_the_service_default( self, monkeypatch ):
        # A blank env var is a common accident ("export FOO=") and must not
        # redirect the guard at Path(""), which exists as the cwd and would
        # make the comparison meaningless.
        monkeypatch.setenv( DEPLOYED_ENV, "   " )
        assert deployed_path() == DEPLOYED_DEFAULT

    def test_unset_override_uses_the_service_default( self, monkeypatch ):
        monkeypatch.delenv( DEPLOYED_ENV, raising=False )
        assert deployed_path() == DEPLOYED_DEFAULT

    def test_sha256_of_reads_bytes_not_text( self, tmp_path ):
        f = tmp_path / "x.bin"
        f.write_bytes( b"\xff\xfe binary" )
        assert sha256_of( f ) == hashlib.sha256( b"\xff\xfe binary" ).hexdigest()
