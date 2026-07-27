"""
Smoke tests for lupin-rest-test container deployment state.

These probes detect docker-compose.yml drift — cases where a bind-mount
(e.g., .git from Bug 9a, credentials from Bug 4) has been edited into the
compose file but the running container was `docker restart`-ed rather than
recreated. `docker restart` preserves the prior container's mount set;
only `docker rm -f` + `docker compose up -d` picks up new mounts.

The 5 blocking probes exercise the minimum surface TFE/BFE Phase 3 needs:
running container, .git mount in inspect output, git sees work tree, git
worktree add succeeds, claude-agent-sdk credentials present.

One WARN-only probe checks `gh auth status` so Phase 5 (`gh pr create`)
visibility lands before a live job trips on missing auth.

Wraps src/scripts/preflight-test-container.sh so the shell script and the
pytest tier stay in lockstep.

Paired design doc: src/rnd/v0.1.6/2026.04.18-container-preflight-smoke.md
"""

import os
import subprocess

import pytest

CONTAINER = os.environ.get( "PREFLIGHT_CONTAINER", "lupin-rest-test" )


def _docker_available():
    try:
        result = subprocess.run(
            [ "docker", "info" ],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except ( FileNotFoundError, OSError, subprocess.TimeoutExpired ):
        # docker binary missing from PATH (test container reality), or daemon
        # unreachable — treat as "not available".
        return False


# Module-level gate: preflight is by-design a host-only tier. It tests
# docker-compose.yml drift against the running container, which requires the
# host's docker daemon. When this file is collected inside the test container
# itself, the docker socket is not mounted, so all 7 probes would skip
# individually and report as 7 skip lines in the suite summary. Lifting the
# gate to module-level collapses that to ONE skip entry — same coverage from
# the host, cleaner report on :8000 / :7999 in-container invocations.
if not _docker_available():
    pytest.skip(
        "docker daemon not reachable — preflight runs from host only "
        "(by-design when invoked from inside the test container)",
        allow_module_level=True
    )


def _docker_exec( *args ):
    return subprocess.run(
        [ "docker", "exec", CONTAINER, *args ],
        capture_output=True,
        text=True,
        timeout=15
    )


def test_container_is_running():
    """Probe 1: `docker ps` shows CONTAINER running."""
    result = subprocess.run(
        [ "docker", "ps", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Names}}" ],
        capture_output=True,
        text=True,
        timeout=10
    )
    names = result.stdout.strip().splitlines()
    assert CONTAINER in names, (
        f"Container '{CONTAINER}' is not running. "
        f"Remedy: docker compose up -d {CONTAINER}"
    )


def test_git_mount_present_in_inspect():
    """Probe 2: `.git` bind-mount is in the running container's mount set."""
    result = subprocess.run(
        [ "docker", "inspect", CONTAINER, "--format",
          '{{range .Mounts}}{{.Source}}->{{.Destination}}\n{{end}}' ],
        capture_output=True,
        text=True,
        timeout=10
    )
    mounts = result.stdout
    assert "/.git->/var/lupin/.git" in mounts, (
        f"'.git' bind-mount not in {CONTAINER} mount set — container predates "
        f"docker-compose.yml edit. Remedy: docker rm -f {CONTAINER} && "
        f"docker compose up -d {CONTAINER}\n"
        f"Observed mounts:\n{mounts}"
    )


def test_git_sees_work_tree():
    """Probe 3: `git rev-parse --is-inside-work-tree` returns `true` inside container."""
    result = _docker_exec( "sh", "-c", "cd /var/lupin && git rev-parse --is-inside-work-tree" )
    assert result.returncode == 0 and "true" in result.stdout, (
        f"git does not see /var/lupin as a work tree. stderr: {result.stderr!r}. "
        f"Remedy: docker rm -f {CONTAINER} && docker compose up -d {CONTAINER}"
    )


def test_git_worktree_add_functional():
    """Probe 4: `git worktree add` (the exact Phase 3 call) works end-to-end."""
    smoke_path = f"/tmp/preflight-smoke-{os.getpid()}"
    add = _docker_exec( "sh", "-c",
                        f"cd /var/lupin && git worktree add {smoke_path} HEAD" )
    try:
        assert add.returncode == 0, (
            f"git worktree add failed inside container: {add.stderr!r}. "
            f"Remedy: verify docker-compose.yml has '- ./.git:/var/lupin/.git', "
            f"then recreate container."
        )
    finally:
        # `remove --force` already deletes the smoke worktree's admin entry — do
        # NOT append `git worktree prune`. An in-container prune wipes the ENTIRE
        # host .git/worktrees registry (bug 47ac0e50: ./.git is mounted but
        # lupin-worktrees/ is not, so every host lane's gitdir reads as missing).
        _docker_exec( "sh", "-c",
                      f"cd /var/lupin && git worktree remove --force {smoke_path} "
                      f">/dev/null 2>&1" )


def test_claude_credentials_mount_present():
    """Probe 5: Claude Agent SDK credentials file is present in container."""
    result = _docker_exec( "test", "-f", "/home/rruiz/.claude/.credentials.json" )
    assert result.returncode == 0, (
        f"claude-agent-sdk credentials mount is missing. Phase 1 delegation "
        f"will fail with 'Not logged in · Please run /login'. "
        f"Remedy: docker rm -f {CONTAINER} && docker compose up -d {CONTAINER}"
    )


def test_worktree_bind_mount_end_to_end():
    """Probe 5b: worktree created inside container is visible on host.

    Creates a real git worktree at the bind-mounted path inside the
    container, then confirms the host side sees it (proves the
    `./.claude/worktrees:/var/lupin/.claude/worktrees` mount is live in
    both directions). Tears down after assertion.
    """
    smoke_name     = f"worktree-preflight-pytest-{os.getpid()}"
    container_path = f"/var/lupin/.claude/worktrees/{smoke_name}"
    host_root      = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
    host_path      = os.path.join( host_root, ".claude", "worktrees", smoke_name )
    try:
        add = _docker_exec(
            "sh", "-c",
            f"cd /var/lupin && git worktree add {container_path} HEAD"
        )
        assert add.returncode == 0, (
            f"git worktree add failed inside container: {add.stderr!r}. "
            f"Remedy: check /var/lupin/.claude/worktrees write permissions."
        )
        assert os.path.isdir( host_path ), (
            f"Worktree created at {container_path} inside container, but host "
            f"does not see it at {host_path}. The "
            f"./.claude/worktrees:/var/lupin/.claude/worktrees bind-mount is "
            f"either missing from docker-compose.yml or not applied to this "
            f"running container. Recreate: docker rm -f {CONTAINER} && "
            f"docker compose up -d {CONTAINER}"
        )
    finally:
        # `remove --force` already deletes the smoke worktree's admin entry — do
        # NOT append `git worktree prune` (bug 47ac0e50: an in-container prune
        # wipes the entire host .git/worktrees registry).
        _docker_exec(
            "sh", "-c",
            f"cd /var/lupin && git worktree remove --force {container_path} "
            f">/dev/null 2>&1"
        )


def test_gh_auth_status_warn_only():
    """Probe 6 (WARN-only): `gh auth status` should show valid GitHub auth.

    Phase 5 (`gh pr create`) will fail if this is not set. We emit a pytest
    warning rather than fail because mounting ~/.config/gh is a future-proof
    decision, not a current blocker.
    """
    result = _docker_exec( "sh", "-c", "gh auth status 2>&1" )
    combined = ( result.stdout or "" ) + ( result.stderr or "" )
    if result.returncode != 0 or not any(
        marker in combined for marker in ( "Logged in", "Active account: true" )
    ):
        pytest.warns( UserWarning )  # no-op; pytest.skip keeps suite green
        pytest.skip(
            "gh CLI has no valid GitHub auth in container — Phase 5 `gh pr create` "
            "will fail when it runs. Remedy (when Phase 5 needs it): add "
            "~/.config/gh bind-mount to docker-compose.yml for dev + test services."
        )


def test_single_file_binds_serve_the_CURRENT_host_file():
    """
    Probe 8: a single-file bind can be PRESENT in `docker inspect` and still serve
    STALE BYTES. Every probe above checks that a mount EXISTS. None checks that it
    carries today's content, and those are different claims.

    THE MECHANISM. Docker binds a single file by INODE, not by path. An editor that
    saves atomically — write-temp-then-rename, which is most of them — leaves the host
    path pointing at a NEW inode while the container's mount still resolves the OLD
    one. `docker inspect` goes on reporting the mount as healthy, because the Source
    string it echoes is the compose declaration and was never a claim about content.
    `docker restart` does not re-resolve it either; only a recreate does.

    OBSERVED 2026-07-27 (row ec3a7fb0): `pytest.ini` was edited on the host to add
    `--strict-markers`; the container served a 1978-byte copy dated Jun 17 for an
    entire scheduled unit tier. Host inode 24726153, container inode 24808682. The
    tier reported on a config it was not running.

    ⇒ The file-level twin of what this module exists to catch, and the quieter half:
    a MISSING mount fails loudly, a STALE one reports success about a file nobody is
    reading. Directory binds (./src, ./io) are immune — the kernel resolves through
    the directory on every open, which is why a conftest.py edit lands and a
    pytest.ini edit does not, in the same commit, in the same container.
    """
    lupin_root = os.environ.get( "LUPIN_ROOT", "." )
    compose    = os.path.join( lupin_root, "docker-compose.yml" )
    if not os.path.exists( compose ):
        pytest.skip( f"docker-compose.yml not readable at {compose}" )

    import yaml
    services = yaml.safe_load( open( compose, encoding="utf-8" ) )[ "services" ]
    volumes  = next(
        ( v.get( "volumes", [] ) for v in services.values()
          if v.get( "container_name" ) == CONTAINER ), []
    )

    stale, compared = [], 0
    for entry in volumes:
        if not isinstance( entry, str ) or not entry.startswith( "./" ): continue
        host_rel, _, rest = entry.partition( ":" )
        dest              = rest.split( ":" )[ 0 ]
        host_path         = os.path.join( lupin_root, host_rel[ 2 : ] )
        if not os.path.isfile( host_path ): continue          # directory binds are immune

        host_sum = subprocess.run( [ "md5sum", host_path ], capture_output=True, text=True, timeout=10 )
        ctr_sum  = _docker_exec( "md5sum", dest )
        if host_sum.returncode or ctr_sum.returncode: continue
        compared += 1
        h, c = host_sum.stdout.split()[ 0 ], ctr_sum.stdout.split()[ 0 ]
        if h != c: stale.append( f"{host_rel} -> {dest}   host={h[ :12 ]}  container={c[ :12 ]}" )

    # A green here means nothing if the loop compared zero files — the same
    # can't-fail shape this probe exists to catch, one level up.
    assert compared > 0, (
        f"probe compared ZERO single-file binds for '{CONTAINER}' — it cannot have "
        "detected staleness, so a pass would be vacuous. Check the compose service name "
        "and that ./-prefixed file binds still exist."
    )
    assert not stale, (
        f"single-file bind mounts are serving STALE content ({len( stale )} of {compared} "
        "compared) — the container is reading a different file than the repo has, and every "
        "mount-presence probe above still passes:\n  "
        + "\n  ".join( stale )
        + f"\n\nRemedy: docker rm -f {CONTAINER} && docker compose up -d {CONTAINER}"
        + "\n(`docker restart` does NOT re-resolve a single-file bind's inode.)"
    )


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
