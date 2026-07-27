"""
Ordering guard for f3b5ecf3 — de-hardcoding `container_name` WITHOUT pinning a
per-file compose project name ships the socket deletion (70794d58) as a design.

WHAT THIS FILE REFUSES TO LET LAND
----------------------------------
A commit whose diff is only `container_name:` removals on `cloud-sql-proxy` /
`cloudsql-socket-init`. It is the clean-looking, reviewable-in-ten-seconds change
that Mr Radio's 2026-07-27 ruling says must not exist, and it is exactly what a
reader takes from "de-hardcoding the names is the load-bearing change".

THE MECHANISM, MEASURED (docker compose v2 / docker 24.0.4, throwaway project,
containers named `clay-probe-*`, torn down with `down -v`)
--------------------------------------------------------------------------
Two compose files, both declaring `container_name: clay-probe-sockinit`, a
`shared` volume, and `holder --depends_on(service_completed_successfully)-->
sockinit`. `sockinit` runs `rm -f /shared/*.sock`. Stack A up, then a socket
touched into the volume, then stack B up:

    ARM 1 — SAME project (both files in one directory, no -p, no top-level name:)
        stack B up   -> sockinit RECREATED (bc2b110c -> 12e0a5bb), NO conflict
                     -> live.sock DELETED, audit.log = 2 lines (the rm ran twice)
                     -> one shared volume: probe-sameproj_shared
                     -> and stack A's app container was DESTROYED: compose saw
                        service `holder` redefined with a different
                        container_name, recreated the service, and
                        `clay-probe-holder-a` became "No such object"

    ARM 2 — DISTINCT project (`-p clay-probe-alt`)
        stack B up   -> Error: Conflict. The container name "/clay-probe-sockinit"
                        is already in use by container 31e5269b...
                     -> live.sock SURVIVES, audit.log still 1 line
                     -> A's holder still `running`, separate volume created

THE DISCRIMINATOR IS THE PROJECT NAME, NOT THE CONTAINER NAME
-------------------------------------------------------------
Arm 2 reproduces the measurement the ruling was built on. Arm 1 is the regime the
repo actually invokes: neither cloud compose file declares a top-level `name:`,
no call site passes `-p` or `--project-name`, and `COMPOSE_PROJECT_NAME` appears
nowhere in the tree — so both files resolve to the project named for their shared
directory (`/var/lupin` -> `lupin`). Under that regime the hardcoded name guards
NOTHING: compose does not conflict, it recreates.

WHAT THIS GUARD COVERS, AND WHAT IT DOES NOT
--------------------------------------------
COVERS: the socket-deletion path — the two Cloud SQL services whose identical
hardcoded `container_name`s are today's accidental guard.

DOES NOT COVER: the app-recreate path from ARM 1. Both files define a service
named `lupin-rest` with DIVERGENT container_names (`lupin-rest-cloud-gpu` vs
`lupin-rest-cloud-test`), which is the shape that destroyed `clay-probe-holder-a`.
No hardcoded name protects that, so it is unguardable by the arm below — it is
why a per-file `name:` is the real remedy rather than a tidier way to spell one.
Stated here rather than left implied: this guard's scope is narrower than the
hazard, and a green run is not a claim that the two stacks may be co-run.

WHAT EACH TEST PINS
-------------------
`test_socket_init_rm_premise_holds` pins the PREMISE. Every other test is only
worth running while both files still carry the `rm -f` of the socket; if that
goes, this guard's reason evaporates and we should be told loudly.

`test_live_compose_files_are_isolated_by_at_least_one_mechanism` is the live
assertion — green today via the name-collision arm.

`test_rename_only_diff_is_rejected` is the control that MUST fail: strip the
container names, add nothing, and the checker has to say unsafe. Without it, a
checker that returned `safe=True` unconditionally would pass every other test
here.
"""

from pathlib import Path

import copy
import pytest
import yaml

REPO_ROOT = Path( __file__ ).resolve().parents[ 4 ]

CLOUD_GPU  = "docker-compose.cloud-gpu.yml"
CLOUD_TEST = "docker-compose.cloud-test.yml"

# The two services whose identical hardcoded container_names are the ONLY thing
# standing between a second stack's bring-up and the first stack's live socket.
# Enumerated, not pattern-matched: a new Cloud SQL service appearing here must be
# a deliberate edit to this list, not an accident of a regex.
COLLISION_GUARD_SERVICES = ( "cloudsql-socket-init", "cloud-sql-proxy" )

# The substring of `cloudsql-socket-init`'s command that makes the whole hazard
# real. Matched against the command the container actually runs.
SOCKET_RM_FRAGMENT = "rm -f /cloudsql/"


def _load( rel ):
    return yaml.safe_load( ( REPO_ROOT / rel ).read_text() )


def _project_name( doc ):
    """
    The compose project name a file pins for itself. `None` means the file pins
    nothing and the project is decided by the INVOCATION (directory basename, -p,
    or COMPOSE_PROJECT_NAME) — which is not a property of the file and therefore
    not a guarantee.
    """
    name = doc.get( "name" )
    if name is None: return None
    name = str( name ).strip()
    return name if name else None


def _container_name( doc, service ):
    services = doc.get( "services", {} )
    if service not in services: return None
    return services[ service ].get( "container_name" )


def is_project_isolated( gpu_doc, test_doc ):
    """
    True iff BOTH files pin a project name and the two differ. This is the only
    invocation-independent guarantee available: it survives an operator who
    forgets `-p`, which the repo's call sites all do.
    """
    gpu_name  = _project_name( gpu_doc )
    test_name = _project_name( test_doc )
    if gpu_name is None or test_name is None: return False
    return gpu_name != test_name


def has_name_collision_guard( gpu_doc, test_doc ):
    """
    True iff every Cloud SQL service in COLLISION_GUARD_SERVICES carries the SAME
    non-empty hardcoded container_name in both files.

    Sameness is the point, not presence: docker refuses the duplicate name before
    the second stack's socket-init is created, so the `rm` never runs. Two
    DIFFERENT hardcoded names would let both inits run against one volume, which
    is the deletion, spelled tidily.
    """
    for service in COLLISION_GUARD_SERVICES:
        gpu_cn  = _container_name( gpu_doc,  service )
        test_cn = _container_name( test_doc, service )
        if not gpu_cn or not test_cn: return False
        if gpu_cn != test_cn:         return False
    return True


def evaluate_dual_stack_isolation( gpu_doc, test_doc ):
    """
    Requires:
        - gpu_doc and test_doc are parsed compose documents (dicts)

    Ensures:
        - returns a dict with keys `project_isolated`, `name_collision_guard`,
          and `safe`, where `safe` is the disjunction of the two arms
        - never raises on a document missing `services` or `name`
    """
    project_isolated = is_project_isolated( gpu_doc, test_doc )
    collision_guard  = has_name_collision_guard( gpu_doc, test_doc )
    return {
        "project_isolated"     : project_isolated,
        "name_collision_guard" : collision_guard,
        "safe"                 : project_isolated or collision_guard,
    }


@pytest.fixture
def live_docs():
    return _load( CLOUD_GPU ), _load( CLOUD_TEST )


def _strip_container_names( doc ):
    """The rename-only diff, applied in memory."""
    out = copy.deepcopy( doc )
    for service in COLLISION_GUARD_SERVICES:
        out.get( "services", {} ).get( service, {} ).pop( "container_name", None )
    return out


def test_socket_init_rm_premise_holds( live_docs ):
    """
    PREMISE. Both files still run the socket `rm`. If they stop, this guard is
    protecting a hazard that no longer exists and should say so loudly rather
    than keep passing for a reason that has expired.
    """
    for doc, rel in zip( live_docs, ( CLOUD_GPU, CLOUD_TEST ) ):
        command = doc[ "services" ][ "cloudsql-socket-init" ][ "command" ]
        joined  = " ".join( command ) if isinstance( command, list ) else str( command )
        assert SOCKET_RM_FRAGMENT in joined, f"{rel}: cloudsql-socket-init no longer deletes the socket — re-read this guard's premise"


def test_live_compose_files_are_isolated_by_at_least_one_mechanism( live_docs ):
    """
    THE LIVE ASSERTION. Goes red the moment a rename-only diff lands.
    """
    gpu_doc, test_doc = live_docs
    result = evaluate_dual_stack_isolation( gpu_doc, test_doc )
    assert result[ "safe" ], (
        "Neither isolation mechanism holds: the two cloud compose files share a "
        "compose project and no longer share a hardcoded container_name. Under "
        "one project name docker RECREATES rather than conflicts, so stack 2's "
        "socket-init deletes stack 1's live socket. Pin a distinct top-level "
        "`name:` in each file IN THIS SAME COMMIT."
    )


def test_todays_guard_is_the_name_collision_arm( live_docs ):
    """
    Pins WHICH arm is load-bearing right now, so a future reader does not assume
    the files are project-isolated when they are only accidentally name-guarded.
    """
    gpu_doc, test_doc = live_docs
    result = evaluate_dual_stack_isolation( gpu_doc, test_doc )
    assert result[ "name_collision_guard" ] is True
    assert result[ "project_isolated"     ] is False, "files now pin distinct project names — update this guard's narrative, the accidental arm is no longer what protects us"


def test_rename_only_diff_is_rejected( live_docs ):
    """
    CONTROL THAT MUST FAIL. Strip the container names, pin nothing: unsafe.
    """
    gpu_doc, test_doc = live_docs
    result = evaluate_dual_stack_isolation( _strip_container_names( gpu_doc ), _strip_container_names( test_doc ) )
    assert result[ "name_collision_guard" ] is False
    assert result[ "project_isolated"     ] is False
    assert result[ "safe"                 ] is False


def test_rename_plus_distinct_project_names_is_accepted( live_docs ):
    """
    The correct one-commit shape is ACCEPTED — otherwise this guard would just be
    "never change these files", which blocks the ruled remedy instead of the
    dangerous half of it.
    """
    gpu_doc, test_doc = live_docs
    gpu_stripped  = _strip_container_names( gpu_doc  )
    test_stripped = _strip_container_names( test_doc )
    gpu_stripped [ "name" ] = "lupin-cloud-gpu"
    test_stripped[ "name" ] = "lupin-cloud-test"
    result = evaluate_dual_stack_isolation( gpu_stripped, test_stripped )
    assert result[ "project_isolated" ] is True
    assert result[ "safe"             ] is True


def test_identical_project_names_are_not_isolation( live_docs ):
    """
    ARM 1 of the measurement, as a unit assertion: two files pinning the SAME
    project name are the regime where the socket was deleted and the first
    stack's app container was destroyed.
    """
    gpu_doc, test_doc = live_docs
    gpu_stripped  = _strip_container_names( gpu_doc  )
    test_stripped = _strip_container_names( test_doc )
    gpu_stripped [ "name" ] = "lupin"
    test_stripped[ "name" ] = "lupin"
    result = evaluate_dual_stack_isolation( gpu_stripped, test_stripped )
    assert result[ "project_isolated" ] is False
    assert result[ "safe"             ] is False


def test_blank_project_name_is_treated_as_unpinned():
    """
    `name: ""` (or whitespace) pins nothing — compose falls back to the
    invocation. A checker that counted it as a pinned value would bless the
    unguarded regime on a typo.
    """
    gpu_doc  = { "name" : "   ", "services" : {} }
    test_doc = { "name" : "lupin-cloud-test", "services" : {} }
    assert is_project_isolated( gpu_doc, test_doc ) is False


def test_one_sided_container_name_is_not_a_guard():
    """
    A hardcoded name in ONE file only cannot collide with anything, so it cannot
    stop the second init from running.
    """
    gpu_doc = {
        "services" : {
            "cloudsql-socket-init" : { "container_name" : "lupin-cloudsql-socket-init" },
            "cloud-sql-proxy"      : { "container_name" : "lupin-cloudsql-proxy"       },
        }
    }
    test_doc = {
        "services" : {
            "cloudsql-socket-init" : {},
            "cloud-sql-proxy"      : { "container_name" : "lupin-cloudsql-proxy" },
        }
    }
    assert has_name_collision_guard( gpu_doc, test_doc ) is False


def test_divergent_container_names_are_not_a_guard():
    """
    Two DIFFERENT hardcoded names let both stacks run their inits against one
    volume — the deletion as a design, which is option (c) and was rejected.
    """
    gpu_doc = {
        "services" : {
            "cloudsql-socket-init" : { "container_name" : "gpu-sockinit"  },
            "cloud-sql-proxy"      : { "container_name" : "shared-proxy"  },
        }
    }
    test_doc = {
        "services" : {
            "cloudsql-socket-init" : { "container_name" : "test-sockinit" },
            "cloud-sql-proxy"      : { "container_name" : "shared-proxy"  },
        }
    }
    assert has_name_collision_guard( gpu_doc, test_doc ) is False


def test_missing_service_is_not_a_guard():
    """A file that does not define the service cannot be guarding it."""
    gpu_doc  = { "services" : { "cloud-sql-proxy" : { "container_name" : "p" } } }
    test_doc = { "services" : { "cloud-sql-proxy" : { "container_name" : "p" } } }
    assert has_name_collision_guard( gpu_doc, test_doc ) is False


def test_missing_name_key_is_unpinned():
    """No `name:` at all is the repo's current state — unpinned, not isolated."""
    assert is_project_isolated( { "services" : {} }, { "services" : {} } ) is False
