"""
Guard for bug be706f10 — AXIS-A ships src/ to a container that does not bind it,
and the health-gate reports success.

THE SHAPE
`deploy-cloud-test.sh` AXIS-A is a BIND-MOUNT SYNC: git archive -> SCP -> extract
on the VM -> chown -> `docker restart`. That only deploys code if the container
actually binds the extracted directory.

`docker-compose.cloud-test.yml` stopped mounting `./src` on 2026-07-07 — correctly,
and deliberately: a live bind would SHADOW the self-consistent baked image for the
v0.2.0 pgvector leg. What was never done was sweeping the deploy script that
depended on that mount.

⇒ AXIS-A extracts code the container cannot see, restarts the SAME baked image, and
the health-gate passes — because the container IS healthy, just running old code.
A deploy that reports success and deployed nothing.

WHY REMEDY (3), NOT (1)
The row offered: (1) delete AXIS-A, (2) restore the mount [a trap — re-arms the
shadow], (3) make AXIS-A assert its own precondition.

**(3) is the only remedy that is correct while the on-VM compose file is unread.**
Nobody has read the VM's copy — it may legitimately differ from this repo's. Under
that uncertainty:
  · (1) deletes a path that might be working on the VM, on an unread premise.
  · (3) is right under BOTH possibilities — if the VM binds ./src the assertion
    passes and AXIS-A proceeds; if it does not, a false green becomes a named
    refusal.

⚠️ And the assertion interrogates the LIVE CONTAINER via `docker inspect`, NOT this
repo's compose file. Reading the repo to answer a question about what the VM runs is
the precise failure this lane keeps finding (see 70794d58, b39c350d, ce89669e). The
compose file is a declaration; the running container is the fact.

BEHAVIOUR CHANGE, stated rather than buried: code-only deploys that previously
reported SUCCESS now FAIL. They were not deploying anything — the green was the bug.

ROLLBACK IS TRANSITIVELY COVERED: `rollback_code` restores src.bak-* and restarts
under the same assumption, but it runs only after `deploy_code`, which now dies at
the precondition under `set -euo pipefail` before the health-gate is ever reached.
"""

import re
from pathlib import Path

REPO_ROOT   = Path( __file__ ).resolve().parents[ 4 ]
SCRIPT_REL  = "src/scripts/deploy-cloud-test.sh"
COMPOSE_REL = "docker-compose.cloud-test.yml"
SRC_TARGET  = "/var/lupin/src"

SCRIPT = ( REPO_ROOT / SCRIPT_REL ).read_text()
LINES  = SCRIPT.splitlines()


def _lineno( pattern, start=0 ):
    """1-indexed line number of the first line matching `pattern`, or None."""
    for i in range( start, len( LINES ) ):
        if re.search( pattern, LINES[ i ] ) and not LINES[ i ].strip().startswith( "#" ):
            return i + 1
    return None


def _func_body( name ):
    """Source of a shell function, from `name() {` to the closing brace at column 0."""
    start = _lineno( rf"^{name}\(\)\s*\{{" )
    assert start, f"function {name}() not found in {SCRIPT_REL}"
    body = []
    for line in LINES[ start: ]:
        if line == "}": break
        body.append( line )
    return "\n".join( body )


# ---------------------------------------------------------------------------
# THE PREMISE — this guard is only load-bearing while the mount is genuinely absent.
# ---------------------------------------------------------------------------

def test_premise_cloud_test_still_does_not_bind_the_source_tree():
    """
    If someone re-adds `./src:/var/lupin/src` to cloud-test, the 2026-07-07 shadow
    ruling has been reversed and THAT is the thing to review — not this test. Fail
    loudly pointing at the ruling rather than let the guard pass for a dead reason.
    """
    import yaml
    svc     = yaml.safe_load( ( REPO_ROOT / COMPOSE_REL ).read_text() )[ "services" ][ "lupin-rest" ]
    targets = set()
    for v in svc.get( "volumes" ) or []:
        spec  = v if isinstance( v, str ) else f"{v.get( 'source' )}:{v.get( 'target' )}"
        parts = spec.split( ":" )
        if len( parts ) >= 2: targets.add( parts[ 1 ] )

    assert SRC_TARGET not in targets, (
        f"{COMPOSE_REL} now binds {SRC_TARGET} again. That REVERSES the 2026-07-07 ruling "
        f"('a live ./src bind would SHADOW the baked cutover code'). Review that reversal — "
        f"restoring the mount was named in bug be706f10 explicitly as the trap to reject. "
        f"Do not simply delete this test."
    )


# ---------------------------------------------------------------------------
# THE CONTROL — fails when the precondition is removed.
# ---------------------------------------------------------------------------

def test_axis_a_asserts_the_bind_mount_before_shipping_any_code():
    body = _func_body( "deploy_code" )

    assert "assert_container_binds_src" in body, (
        f"{SCRIPT_REL}: deploy_code() ships src/ WITHOUT asserting that the target container "
        f"binds {SRC_TARGET}. With no mount the extracted code is invisible to the container, "
        f"`docker restart` re-runs the same baked image, and the health-gate still passes — a "
        f"deploy that reports success and deployed nothing (bug be706f10)."
    )

    # Ordering: the assertion must precede every code-shipping step, or it guards
    # nothing — a precondition checked after the fact is just a log line.
    #
    # ⚠️ Scoped to deploy_code()'s OWN body, deliberately. A first cut searched the
    # whole file and failed: `--dry-run`'s plan line at :97 PRINTS the string
    # "docker restart $REST_CONTAINER", so a file-wide search matched a log message
    # describing the action and concluded the guard came after it. A predicate that
    # matches prose is not a predicate about behaviour — the same defect this lane
    # has now hit at three separate layers today.
    body_lines = body.splitlines()

    def _at( pattern ):
        for i, line in enumerate( body_lines ):
            if line.strip().startswith( "#" ): continue
            if re.search( pattern, line ): return i
        return None

    guard = _at( r"^\s*assert_container_binds_src\s*$" )
    assert guard is not None, f"{SCRIPT_REL}: precondition call not found inside deploy_code()"

    for label, pattern in (
        ( "git archive",    r"git archive" ),
        ( "scp to the VM",  r"gcloud compute scp" ),
        ( "docker restart", r"docker restart" ),
    ):
        at = _at( pattern )
        assert at is not None and guard < at, (
            f"{SCRIPT_REL}: the bind-mount precondition (deploy_code line {guard}) must run "
            f"BEFORE {label} (line {at}). A precondition checked afterwards guards nothing."
        )


def test_precondition_interrogates_the_live_container_not_the_repo_compose_file():
    """
    The repo's compose file is a DECLARATION; the running container is the FACT, and
    the VM may legitimately carry a divergent copy. Answering "does the VM bind this?"
    by reading a file in this repo is the exact defect class this lane keeps finding.
    """
    body = _func_body( "assert_container_binds_src" )

    assert "docker inspect" in body, (
        f"{SCRIPT_REL}: the precondition must ask the LIVE container via `docker inspect`. "
        f"Anything else answers a question about the VM by reading this repo."
    )
    assert SRC_TARGET in body, f"{SCRIPT_REL}: the precondition must name {SRC_TARGET}"

    # ⚠️ Test for a compose-file READ, not for the WORD "compose". A first cut asserted
    # `"docker-compose" not in body` and failed on the refusal message, which names
    # docker-compose.cloud-test.yml while EXPLAINING why the mount is absent. Prose
    # about a file is not a read of it — the same predicate-matches-prose defect the
    # ordering check above had to be rescued from.
    reads_compose = re.search( r"\$\{?COMPOSE_FILE", body ) or re.search(
        r"(cat|grep|yq|awk|sed|python3?)\b[^\n]*docker-compose[\w.-]*\.ya?ml", body )
    assert not reads_compose, (
        f"{SCRIPT_REL}: the precondition READS a compose file ({reads_compose.group( 0 )!r}). "
        f"A compose file is a declaration; the VM may carry a divergent copy. Assert against "
        f"the running container instead."
    )


def test_the_refusal_names_the_remedy_and_rejects_the_trap():
    """
    A refusal that does not say what to do instead gets worked around, and the
    nearest workaround here is restoring the ./src mount — the one option bug
    be706f10 named specifically to be rejected.
    """
    body = _func_body( "assert_container_binds_src" )
    assert "--deps" in body, (
        f"{SCRIPT_REL}: the refusal must name the image axis (--deps) as the way to deploy code."
    )
    assert re.search( r"[Dd]o NOT.*restor|re-arms", body ), (
        f"{SCRIPT_REL}: the refusal must explicitly reject restoring the ./src mount — that is "
        f"the obvious workaround and it re-arms the shadow trap the 2026-07-07 ruling removed."
    )


def test_failure_is_fatal_so_rollback_cannot_run_on_a_dead_axis():
    """
    `rollback_code` restores src.bak-* and restarts under the SAME mount assumption.
    It is covered transitively only if the precondition actually ABORTS the script.
    """
    assert re.search( r"^set -euo pipefail", SCRIPT, re.MULTILINE ), \
        f"{SCRIPT_REL}: `set -euo pipefail` missing — a failing precondition would not abort"
    assert re.search( r"^die\(\)\s*\{.*exit 1", SCRIPT, re.MULTILINE | re.DOTALL ), \
        f"{SCRIPT_REL}: die() must exit non-zero, or the precondition is advisory"
    assert "die " in _func_body( "assert_container_binds_src" ), \
        f"{SCRIPT_REL}: the precondition must die(), not warn — a warning still deploys nothing"
