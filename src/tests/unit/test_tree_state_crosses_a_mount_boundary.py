"""
Guard — the tree-state reader can find `.git` across a bind-mount boundary.

WHAT WAS BROKEN. Every `:8000` E2E artifact — `io/test-suite/artifacts/e2e-*.log` inside
`lupin-rest-test` — carried `[tree-state] UNKNOWN — cannot read HEAD; this run's result
cannot be tied to a tree`. So no E2E green could be tied to a sha at all, which is the
defect the whole tree-state module exists to prevent, live in the one venue that runs the
merge gates.

IT WAS NOT GIT AND NOT THE REPOSITORY. `docker-compose.yml` bind-mounts `/var/lupin/src`
and `/var/lupin/.git` as SEPARATE mounts, and both callers hand the reader a path under
`src/`: the conftest hook passes `/var/lupin/src`, the module entry point passes
`/var/lupin/src/cosa/utils`. Git discovery walks up, reaches the `/var/lupin/src` mount
root, and stops one directory short of the `.git` it was looking for —

    fatal: not a git repository (or any parent up to mount point /var/lupin)
    Stopping at filesystem boundary (GIT_DISCOVERY_ACROSS_FILESYSTEM not set).

Measured in the live container, one variable, both directions: bare -> exit 128; with
`GIT_DISCOVERY_ACROSS_FILESYSTEM=1` -> `c7f2e804`, and `--show-toplevel` -> `/var/lupin`.

WHY THESE TESTS ASSERT THE ENV AND NOT THE OUTPUT. The failure needs a real filesystem
boundary, which a unit test cannot create without mount privileges — and a test that runs
on the host cannot see the defect at all, because the host has no boundary between `src/`
and `.git`. So these drive the one thing that actually changed: what the subprocess is
given. Remove the `env=` and both arms redden.

Venue: :7999-eligible — no network, no mutation, milliseconds.
"""
import os
import subprocess

from cosa.utils.tree_state import _git_reader


def _env_of_one_call( monkeypatch ):
    """Run one read through a captured `subprocess.run` and hand back the env it was given."""
    seen = {}

    class Done:
        returncode = 0
        stdout     = "abc1234\n"

    def capture( *args, **kwargs ):
        seen[ "env" ] = kwargs.get( "env" )
        return Done()

    monkeypatch.setattr( subprocess, "run", capture )
    _git_reader( "/anywhere" )( "rev-parse", "--short", "HEAD" )
    return seen[ "env" ]


def test_the_reader_lets_git_discovery_cross_a_filesystem_boundary( monkeypatch ):
    """
    THE ARM THAT FAILS WITHOUT THE FIX. Without this variable the reader cannot reach
    `/var/lupin/.git` from any path under the separately-mounted `/var/lupin/src`, and
    every E2E artifact reports UNKNOWN.
    """
    env = _env_of_one_call( monkeypatch )
    assert env is not None, "the reader must pass an explicit env, not inherit implicitly"
    assert env[ "GIT_DISCOVERY_ACROSS_FILESYSTEM" ] == "1"


def test_the_reader_still_inherits_the_environment_it_was_called_in( monkeypatch ):
    """
    The env is the CALLER'S plus one variable — never a scratch env built from nothing.
    A reader that hands git an empty environment silently changes which config git reads
    (HOME, GIT_CONFIG_GLOBAL, PATH), so it would answer about a different git than the
    run actually used. That is this module's own failure shape one layer down.
    """
    monkeypatch.setenv( "LUPIN_TREE_STATE_PROBE_MARKER", "carried-through" )
    env = _env_of_one_call( monkeypatch )
    assert env[ "LUPIN_TREE_STATE_PROBE_MARKER" ] == "carried-through"
    assert env[ "PATH" ] == os.environ[ "PATH" ]


def test_crossing_the_boundary_does_not_invent_a_repository_where_there_is_none( tmp_path ):
    """
    THE COST SIDE, measured rather than reasoned about. Crossing mounts widens the walk-up,
    so the question is whether a non-repo directory now yields a confident answer. It does
    not: `tmp_path` has no repository above it, and the reader still returns None — which
    is what makes `tree_state_line` render its UNKNOWN rather than a sha it did not read.
    """
    assert _git_reader( str( tmp_path ) )( "rev-parse", "--short", "HEAD" ) is None
