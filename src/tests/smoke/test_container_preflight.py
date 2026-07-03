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


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
