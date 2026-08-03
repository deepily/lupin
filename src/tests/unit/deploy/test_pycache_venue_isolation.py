"""
Guard for bug b39c350d — a shared `__pycache__` across two repo roots.

THE MECHANISM
`./src` is bind-mounted into the container, so `src/**/__pycache__` is shared by
two interpreters whose repo roots differ (host `/mnt/DATA01/…`, container
`/var/lupin/…`). A `.pyc` bakes `co_filename` as an ABSOLUTE path, and both
venues see identical source mtime+size, so pytest's/Python's cache-validity
check passes in both and NEITHER recompiles. The venue that did not write the
cache runs code naming a path that does not exist for it.

MEASURED — full census of the shared tree, 4008 first-party entries, every one
classified by reading `co_filename` out of the bytecode (not by grepping for it,
which is the instrument this bug breaks):

    host-written  (/mnt/DATA01/…)  2202
    container     (/var/lupin/…)    708
    RELATIVE                        565
    pre-rename    (genie-in-the-box) 129
    unmarshalable (Python 3.10 tags) 402   <- different cache tag, cannot collide
    unreadable    (PermissionError)    2

...and the consequence, measured with `linecache.getlines`, which is the exact
call a traceback uses to render a source line, run on the host at the repo root:

    container-written   0/708 render source   -> 708 frames would show NO SOURCE
    pre-rename          0/129 render source   -> 129 frames would show NO SOURCE
    host-written    2177/2177 render          (control; 25 orphans excluded — their
                                               .py was deleted, so no cache could
                                               render them)
    RELATIVE          528/565 at repo root
                       10/565 from cwd=/      <- resolved against CWD at READ time

⇒ The row previously listed traceback degradation as REASONING. It is now
measured: ~21% of first-party cache entries would render a frame with no source
on the host today. Coverage keys on the same `co_filename`, so its line mapping
is degraded by the same mechanism (asserted as following from the shared key —
a coverage run was NOT performed, and that boundary is deliberate).

THE REMEDY THIS PINS
Send each venue's bytecode to a venue-local directory via `PYTHONPYCACHEPREFIX`,
so the directory stops being shared at all. Two properties were CONFIRMED rather
than assumed, because the whole remedy rests on them:

  1. With `pycache_prefix` set, `__cached__` resolves under the prefix and an
     EXISTING in-tree `__pycache__` entry is IGNORED, not merely left un-updated.
     ⇒ the 4008 pre-existing shared entries go inert without being purged. This
     is what makes the remedy sufficient where "stop the container writing"
     (remedy 3 in the row) was not.
  2. pytest's assertion-rewriting hook honors it — the `*-pytest-*.pyc` lands
     under the prefix and the in-tree `__pycache__` gains nothing.

⚠️ NOT purging the existing 4008 entries is deliberate. Peers run tests against
this working tree continuously; deleting `__pycache__` under a live pytest run is
the same shape as bug 70794d58 (an act that is correct in isolation and
destructive because someone else's process is using the thing right now). The
prefix makes them inert, which achieves the goal without the blast radius.

⚠️ An env change lands only on a container RECREATE, never a `docker restart`.
Until each container is recreated, the compose file declares the fix and the
running process does not have it.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path( __file__ ).resolve().parents[ 4 ]

COMPOSE_FILES = [
    "docker-compose.yml",
    "docker-compose.cloud-gpu.yml",
    "docker-compose.cloud-test.yml",
]

SRC_TARGET = "/var/lupin/src"


def _services( compose_rel ):
    return yaml.safe_load( ( REPO_ROOT / compose_rel ).read_text() )[ "services" ]


def _mounts_src_tree( svc ):
    """
    True when the service bind-mounts the WHOLE source tree (and therefore shares
    `src/**/__pycache__`). A read-only leaf mount such as
    `./src/conf/keys:/var/lupin/src/conf/keys:ro` is NOT the hazard — it carries
    no __pycache__ — so matching on the target prefix alone would over-report and
    demand the env var on services that do not need it.
    """
    for v in svc.get( "volumes" ) or []:
        spec = v if isinstance( v, str ) else f"{v.get( 'source' )}:{v.get( 'target' )}"
        parts = spec.split( ":" )
        if len( parts ) >= 2 and parts[ 1 ] == SRC_TARGET:
            return True
    return False


def _src_mounting_services():
    found = []
    for compose_rel in COMPOSE_FILES:
        for name, svc in _services( compose_rel ).items():
            if _mounts_src_tree( svc ):
                found.append( ( compose_rel, name, svc ) )
    return found


def test_the_premise_holds_some_service_still_mounts_the_source_tree():
    """
    If nothing bind-mounts `./src` any more, this whole guard's reason has
    evaporated and it should be deleted rather than left passing vacuously — a
    parametrized test over an empty list passes without asserting anything.
    """
    found = _src_mounting_services()
    assert found, (
        "No service bind-mounts ./src:/var/lupin/src any more. b39c350d's premise is gone — "
        "delete this file rather than leaving it green over an empty parameter list."
    )


@pytest.mark.parametrize(
    "compose_rel,service",
    [ ( c, n ) for c, n, _ in _src_mounting_services() ],
)
def test_src_mounting_service_sends_bytecode_out_of_the_shared_tree( compose_rel, service ):
    svc    = _services( compose_rel )[ service ]
    env    = svc.get( "environment" ) or {}
    prefix = env.get( "PYTHONPYCACHEPREFIX" ) if isinstance( env, dict ) else None

    assert prefix, (
        f"{compose_rel}:{service} bind-mounts the source tree but sets no PYTHONPYCACHEPREFIX. "
        f"Its bytecode lands in src/**/__pycache__, which the host also writes — and a .pyc "
        f"bakes an absolute co_filename that is valid for only one of the two repo roots "
        f"(bug b39c350d). Measured today: 708/708 container-written entries render NO SOURCE "
        f"in a host traceback."
    )

    # The prefix must be OUTSIDE the bind-mounted tree, or it is still shared and
    # the declaration is decorative.
    assert not prefix.startswith( SRC_TARGET ), (
        f"{compose_rel}:{service} sets PYTHONPYCACHEPREFIX={prefix}, which is INSIDE the "
        f"bind-mounted {SRC_TARGET}. That relocates the cache without un-sharing it."
    )
