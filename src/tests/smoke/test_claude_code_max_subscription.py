"""
Smoke test: proves the Claude Code CLI inside lupin-rest-test uses the
Claude Max subscription path (flat-rate), NOT per-token API billing.

This is the BLOCKING gate for the TFE-to-CC work (see
`src/rnd/v0.1.6/2026.04.10-test-fix-expediter/19-tfe-to-cc-design.md`).
If this test fails — meaning cost_usd > 0 — then the CLI is falling back
to an API key and the whole Max-subscription cost-reduction thesis for
bridging TFE Phases 1/3 to Claude Code is wrong. Investigate before
writing any TFE-to-CC orchestrator code.

What it does:
  1. Authenticate against :8000 (test server).
  2. POST /api/claude-code/queue/submit with a trivial BOUNDED prompt
     ("write 'hello-from-smoke' to /tmp/cc-smoke-<pid>.txt inside the
     container").
  3. Poll GET /api/job-history/<cc-job-id> until terminal (done/dead)
     or timeout.
  4. Assert terminal state is success AND reported cost_usd == 0.0.
  5. Verify the sentinel file was actually written (end-to-end tool
     path works, not just subscription auth).
  6. Clean up (best-effort) — delete the job history row + sentinel
     file.

The test is tolerant of the server being offline (pytest.skip) so it
doesn't fail CI in environments where lupin-rest-test isn't up. It
should only run as a deliberate deployment probe.

Filed 2026-04-19 Session be57a252. Paired doc:
  `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/19-tfe-to-cc-design.md`
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Optional

import pytest


# ────────────────────────────────────────────────────────────────────────────
# Test RETIRED 2026-05-11 (session 77e1bb27, Mr. Radio)
# ────────────────────────────────────────────────────────────────────────────
# The `cost_usd == 0.0` premise this test was built on is unsalvageable.
#
# Empirically verified end-to-end on 2026-05-11:
#   - User has NO ANTHROPIC_API_KEY anywhere (host or test container).
#   - User has a valid Max OAuth credentials file (`subscriptionType: "max"`),
#     bind-mounted into the test container.
#   - Yet `claude -p ...` non-interactive invocations report a non-zero
#     `total_cost_usd` on every call, both on host (~$0.32) AND in container
#     (~$0.05). Different prompts → different reported costs, all > 0.
#
# Insight (user, 2026-05-11 EVE): the cost field is COUNTERFACTUAL API
# pricing reported as informational metadata, not actual billing. Nothing
# is being billed — there's no API key for the CLI to bill against. The
# actual call is being authorized + paid for by the Max OAuth subscription
# at its flat rate. The CLI just always reports "what this WOULD cost via
# API" in its result envelope regardless of which auth path was used.
#
# Consequence: `cost_usd == 0.0` cannot validate "we're on the subscription
# path" from the CLI's own output. The test as authored cannot pass on any
# valid CC CLI invocation. Retire it.
#
# The test file is kept (rather than deleted) as the audit trail for the
# four architecture-correctness fixes applied this session — these patterns
# remain useful for future CC-related smoke tests that need to work both on
# host (with `docker exec`) and inside the test container (where the docker
# CLI doesn't exist and `localhost:8000` is unreachable):
#   1. `_running_inside_container()` helper (detects `/.dockerenv`)
#   2. `_container_running()` short-circuits inside container
#   3. `TEST_SERVER_BASE` honors `LUPIN_API_URL`
#   4. Sentinel verify + cleanup branch in-container vs host-side
#   5. `_extract_cost_usd()` reads `cost_summary` inside `metadata_json`
#
# Companion CoSA fix (uncommitted, separate commit context):
#   `src/cosa/agents/claude_code/job.py` Bounded path now puts `cost_summary`
#   into `self.artifacts` (parity with the dry-run path) — this is a
#   correctness improvement independent of this retirement.
#
# Paired doc: `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/19-tfe-to-cc-design.md`
# should be amended to drop the "cost reduction via subscription" thesis or
# pivot it to a more verifiable invariant (e.g., "no ANTHROPIC_API_KEY in
# container env" — provable from `env | grep ANTHROPIC_API_KEY` returning
# empty).
# ────────────────────────────────────────────────────────────────────────────

pytestmark = pytest.mark.skip(
    reason = (
        "RETIRED 2026-05-11: cost_usd == 0.0 premise is invalid. CC CLI reports "
        "counterfactual API pricing as metadata on every -p invocation regardless "
        "of which auth path actually paid (OAuth subscription vs API key). With "
        "no ANTHROPIC_API_KEY present, Max OAuth is paying the flat rate but the "
        "CLI still populates total_cost_usd > 0. See module docstring + the "
        "retirement block at the top of this file for full forensic trail."
    )
)


TEST_SERVER_BASE = os.environ.get( "LUPIN_API_URL", "http://localhost:8000" )
SUBMIT_ENDPOINT  = f"{TEST_SERVER_BASE}/api/claude-code/submit"
AUTH_ENDPOINT    = f"{TEST_SERVER_BASE}/auth/login"
JOB_ENDPOINT     = f"{TEST_SERVER_BASE}/api/job-history"
TEST_CONTAINER   = "lupin-rest-test"

POLL_INTERVAL_S  = 2.0
POLL_TIMEOUT_S   = 180  # 3 min — trivial CC job should finish in <30s typically


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────

def _http_post_json( url: str, body: dict, headers: dict, timeout: int = 15 ) -> dict:
    """POST JSON; return parsed JSON response. Raises urllib HTTPError on non-2xx."""
    req = urllib.request.Request(
        url,
        data    = json.dumps( body ).encode(),
        headers = { "Content-Type": "application/json", **headers },
        method  = "POST",
    )
    with urllib.request.urlopen( req, timeout=timeout ) as r:
        return json.loads( r.read().decode() )


def _http_get_json( url: str, headers: dict, timeout: int = 15 ) -> dict:
    req = urllib.request.Request( url, headers=headers )
    with urllib.request.urlopen( req, timeout=timeout ) as r:
        return json.loads( r.read().decode() )


def _http_delete( url: str, headers: dict, timeout: int = 15 ) -> None:
    req = urllib.request.Request( url, headers=headers, method="DELETE" )
    try:
        with urllib.request.urlopen( req, timeout=timeout ):
            pass
    except urllib.error.HTTPError:
        pass  # best-effort cleanup


def _server_reachable() -> bool:
    try:
        with urllib.request.urlopen( f"{TEST_SERVER_BASE}/health", timeout=3 ):
            return True
    except Exception:
        return False


def _running_inside_container() -> bool:
    """True when this pytest process is itself running inside a Docker container.
    Detected via the canonical `/.dockerenv` marker file Docker writes at container
    image build / runtime."""
    return os.path.exists( "/.dockerenv" )


def _container_running() -> bool:
    # When pytest is scheduled via /api/test-suite/submit it runs INSIDE the test
    # container, where the `docker` CLI does not exist. In that case we ARE the
    # container we'd otherwise be probing — short-circuit to True.
    if _running_inside_container():
        return True
    try:
        out = subprocess.run(
            [ "docker", "ps", "--filter", f"name=^{TEST_CONTAINER}$", "--format", "{{.Names}}" ],
            capture_output=True, text=True, timeout=5,
        )
        return TEST_CONTAINER in out.stdout
    except Exception:
        return False


def _extract_cost_usd( job: dict ) -> Optional[ float ]:
    """
    Pull cost_usd from the persisted job record — tolerant of where it lands.

    ClaudeCodeJob.do_all persists cost into several candidate locations
    depending on the code path; check each.
    """
    # Direct on artifacts
    artifacts = job.get( "artifacts" ) or {}
    if isinstance( artifacts, dict ):
        if "cost_usd" in artifacts:
            return float( artifacts[ "cost_usd" ] )
        if "total_cost_usd" in artifacts:
            return float( artifacts[ "total_cost_usd" ] )
        cost_summary = artifacts.get( "cost_summary" )
        if isinstance( cost_summary, dict ) and "total_cost_usd" in cost_summary:
            return float( cost_summary[ "total_cost_usd" ] )

    # Top-level cost_summary
    cost_summary = job.get( "cost_summary" )
    if isinstance( cost_summary, dict ) and "total_cost_usd" in cost_summary:
        return float( cost_summary[ "total_cost_usd" ] )

    # Metadata fallback — DB job_history.metadata_json may carry either a bare
    # cost_usd or a nested cost_summary dict (see _build_metadata_json + the
    # CC job's `self.artifacts` shape; the production Bounded path lands here).
    metadata = job.get( "metadata_json" ) or {}
    if isinstance( metadata, dict ):
        if "cost_usd" in metadata:
            return float( metadata[ "cost_usd" ] )
        cs = metadata.get( "cost_summary" )
        if isinstance( cs, dict ) and "total_cost_usd" in cs:
            return float( cs[ "total_cost_usd" ] )

    return None


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────

@pytest.fixture( scope="module" )
def auth_token() -> str:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip(
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_{EMAIL,PASSWORD} not set; "
            "source ~/.lupin/test-env.sh before running this test."
        )
    if not _server_reachable():
        pytest.skip(
            f"Test server not reachable at {TEST_SERVER_BASE}/health — "
            f"skipping (deployment-only probe)."
        )

    resp = _http_post_json(
        AUTH_ENDPOINT,
        body    = { "email": email, "password": password },
        headers = {},
        timeout = 10,
    )
    token = resp.get( "tokens", {} ).get( "access_token" )
    if not token:
        pytest.fail( f"Auth succeeded but no access_token in response keys: {list( resp.keys() )}" )
    return token


@pytest.fixture( scope="module" )
def auth_headers( auth_token ) -> dict:
    return { "Authorization": f"Bearer {auth_token}" }


@pytest.fixture( scope="module", autouse=True )
def _require_container():
    if not _container_running():
        pytest.skip( f"Container {TEST_CONTAINER} not running — smoke test is deployment-only." )


# ────────────────────────────────────────────────────────────────────────
# The test
# ────────────────────────────────────────────────────────────────────────

def test_claude_code_bounded_job_uses_max_subscription( auth_headers ):
    """
    Gate test for TFE-to-CC. Submits a trivial BOUNDED ClaudeCodeJob
    and asserts the reported per-run cost is $0.00 (i.e., flat Max
    subscription, not per-token API billing).

    Also verifies end-to-end: the sentinel file is actually written
    inside the container. This rules out the "auth is fine but tool
    access is broken" failure mode.
    """
    sentinel_path = f"/tmp/cc-smoke-{os.getpid()}-{int( time.time() )}.txt"
    sentinel_body = "hello-from-smoke-test"

    prompt = (
        f"Your task is a one-line file-write sanity check. "
        f"Use the Write tool to create the file {sentinel_path} "
        f"with exactly this content: {sentinel_body}\n"
        f"After writing, do not run any other tools. Respond with a "
        f"one-line confirmation: 'Wrote {sentinel_path}'."
    )

    try:
        # 1. Submit
        submit_resp = _http_post_json(
            SUBMIT_ENDPOINT,
            body = {
                "prompt"      : prompt,
                "project"     : "lupin",
                "task_type"   : "BOUNDED",
                "max_turns"   : 5,
                "dry_run"     : False,
            },
            headers = auth_headers,
            timeout = 15,
        )
        job_id = submit_resp.get( "job_id" )
        assert job_id and job_id.startswith( "cc-" ), (
            f"Expected cc-* job id, got: {submit_resp!r}"
        )

        # 2. Poll for terminal state
        deadline = time.time() + POLL_TIMEOUT_S
        job      = None
        last_state = None
        while time.time() < deadline:
            try:
                job = _http_get_json( f"{JOB_ENDPOINT}/{job_id}", auth_headers )
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    # Job may not be persisted yet; keep polling
                    time.sleep( POLL_INTERVAL_S )
                    continue
                raise

            state = job.get( "state" ) or job.get( "status" ) or "?"
            last_state = state
            if state in ( "done", "dead", "completed", "failed", "stalled" ):
                break
            time.sleep( POLL_INTERVAL_S )

        assert job is not None, f"Job {job_id} never returned a persisted record"
        state = job.get( "state" ) or job.get( "status" ) or "?"
        assert state in ( "done", "completed" ), (
            f"Job {job_id} ended in non-success state: {state!r}. "
            f"Last poll: {last_state!r}. Job detail (first 500 chars): "
            f"{json.dumps( job )[ :500 ]}"
        )

        # 3. Cost assertion — THE critical check
        cost = _extract_cost_usd( job )
        assert cost is not None, (
            f"Could not extract cost_usd from job record. This means the "
            f"ClaudeCodeJob is not reporting cost in any of the expected "
            f"locations (artifacts.cost_usd, cost_summary.total_cost_usd, "
            f"metadata_json.cost_usd). Adjust _extract_cost_usd() to "
            f"match current persistence schema. Job keys: {list( job.keys() )}"
        )
        assert cost == 0.0, (
            f"Expected cost_usd == 0.0 (flat Max subscription). Got {cost!r}. "
            f"This means the Claude Code CLI inside the container is "
            f"billing per-token via API key, NOT the Max OAuth subscription. "
            f"Investigate: (a) is ~/.claude/.credentials.json bind-mount "
            f"present? (b) is ANTHROPIC_API_KEY set in docker-compose for "
            f"the test container? (c) is the OAuth session expired? "
            f"TFE-to-CC cost-reduction thesis depends on this assertion."
        )

        # 4. End-to-end: sentinel file must exist inside the container
        if _running_inside_container():
            # pytest is itself running inside lupin-rest-test — read the file
            # directly. /tmp is the same filesystem the CC job wrote to.
            try:
                with open( sentinel_path, "r" ) as f:
                    sentinel_content = f.read()
            except FileNotFoundError:
                pytest.fail(
                    f"Sentinel file {sentinel_path} not found (in-container read). "
                    f"Job reported success but Write tool path may be broken."
                )
            assert sentinel_body in sentinel_content, (
                f"Sentinel file exists but contents differ. "
                f"Expected substring: {sentinel_body!r}. "
                f"Actual: {sentinel_content!r}"
            )
        else:
            check = subprocess.run(
                [ "docker", "exec", TEST_CONTAINER, "cat", sentinel_path ],
                capture_output=True, text=True, timeout=10,
            )
            assert check.returncode == 0, (
                f"Sentinel file {sentinel_path} not found inside {TEST_CONTAINER}. "
                f"Job reported success but Write tool path may be broken. "
                f"docker exec stderr: {check.stderr!r}"
            )
            assert sentinel_body in check.stdout, (
                f"Sentinel file exists but contents differ. "
                f"Expected substring: {sentinel_body!r}. "
                f"Actual: {check.stdout!r}"
            )

    finally:
        # Best-effort cleanup
        try:
            if _running_inside_container():
                if os.path.exists( sentinel_path ):
                    os.remove( sentinel_path )
            else:
                subprocess.run(
                    [ "docker", "exec", TEST_CONTAINER, "rm", "-f", sentinel_path ],
                    capture_output=True, timeout=5,
                )
        except Exception:
            pass
        if "job_id" in locals() and job_id:
            _http_delete( f"{JOB_ENDPOINT}/{job_id}", auth_headers )


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v", "-s" ] ) )
