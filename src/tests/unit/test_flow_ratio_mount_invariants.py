"""
Both rest services must carry the flow-ratio mount AND the env var that names it.

WHY THIS FILE EXISTS. `flow_ratio_settings` persists the operator's ratio window and
threshold to a file. Inside a container `fleet_data_root()` resolves to
`/projects-data/lupin`, which does not exist and is not writable — measured 2026-09-01,
`PermissionError [Errno 13]`, so EVERY settings PATCH answered 500 in the deployed
environment. The fix is `LUPIN_FLOW_RATIO_DIR` plus a bind mount, copying the pattern
`dm.py` already uses for the DM corpus.

That fix lives entirely in `docker-compose.yml`, where nothing was checking it. No
Python test would notice a regression, because the CODE would still be correct — it is
the deployment that would be wrong.

THREE WAYS IT BREAKS, AND EACH NEEDS ITS OWN ASSERTION:

    mount alone        the env var is free to drift to a path nothing mounts
    env var alone      it names a path that may not be mounted at all
    one service only   dev passes, test is missed — and that reproduces the
                       two-servers-two-values failure the module docstring exists to
                       prevent, with the board reporting "allow" while the OTHER server
                       refuses the create

⚠️ THE TARGET-EQUALS-VALUE CHECK IS THE ONE THAT EARNS ITS KEEP. Presence checks pass
happily while the two disagree, and that mismatch is worse than the bug it replaced: the
write SUCCEEDS into container-local scratch and is lost at the next bounce, silently,
where the original failure was a loud 500.

⚠️ WHAT THIS DOES NOT CHECK, so a green is not over-read: it reads the compose FILE, not
a running container. Mounts and env resolve at container CREATE, so this passing says
the DECLARATION is correct — never that any container was recreated to pick it up. A
container started before the declaration landed still fails at runtime while this test
is green. That runtime half is the storage leg, and it needs both containers up.

Venue: :7999-eligible — parses a yaml file, no server, no network, no state.
"""

import os

import pytest
import yaml

import cosa.utils.util as cu
from cosa.rest import flow_ratio_settings as frs


# The services that import flow_ratio_settings and therefore need the mount. Named
# explicitly rather than derived: a new rest service must be a deliberate addition here,
# so one cannot be added and silently left unmounted.
REST_SERVICES = ( "lupin-rest-dev", "lupin-rest-test" )

ENV_KEY = "LUPIN_FLOW_RATIO_DIR"


@pytest.fixture( scope="module" )
def compose():
    """The parsed docker-compose.yml, read from the project root."""
    path = os.path.join( cu.get_project_root(), "docker-compose.yml" )
    with open( path, "r" ) as handle:
        return yaml.safe_load( handle )


def _service( compose, name ):
    services = compose.get( "services" ) or {}
    assert name in services, (
        f"service {name!r} is missing from docker-compose.yml; known services: "
        f"{sorted( services )}"
    )
    return services[ name ]


def _env_value( service, key ):
    """The env value for `key`, tolerating both the mapping and list-of-strings forms."""
    env = service.get( "environment" )
    if isinstance( env, dict ):
        return env.get( key )
    if isinstance( env, list ):
        for entry in env:
            if isinstance( entry, str ) and entry.split( "=", 1 )[ 0 ] == key:
                parts = entry.split( "=", 1 )
                return parts[ 1 ] if len( parts ) == 2 else None
    return None


def _bind_targets( service ):
    """
    Every bind-mount target this service declares, as { target: source }.

    BOTH COMPOSE FORMS, because this file uses both. The first cut of this parser
    handled only the short `src:dst[:mode]` string on the stated assumption that "this
    project uses the short form throughout" — which is FALSE: the sessions mount is
    long-form (`{type: bind, source: ..., target: ...}`).

    It surfaced rather than hid, which is the only reason the assumption got caught:
    the parser REFUSED an entry it did not understand instead of skipping it, so the
    author's wrong premise came back as five red tests rather than as a green suite
    silently measuring a subset of the mounts. Keep that property — a `continue` here
    would make every assertion below vacuous for any mount written the other way.

    Ensures:
        - handles the short string form and the long mapping form
        - a mapping without both source and target is REFUSED, not skipped
        - a non-bind long-form entry (a named volume) is skipped deliberately, since it
          has no host path to check
    """
    targets = {}
    for volume in service.get( "volumes" ) or []:
        if isinstance( volume, str ):
            parts = volume.split( ":" )
            if len( parts ) >= 2:
                targets[ parts[ 1 ] ] = parts[ 0 ]
            continue

        assert isinstance( volume, dict ), (
            f"volume entry {volume!r} is neither a string nor a mapping; this test does "
            f"not understand it and will not silently skip it."
        )
        if volume.get( "type" ) not in ( None, "bind" ):
            continue                      # a named volume has no host path to judge
        source, target = volume.get( "source" ), volume.get( "target" )
        assert source and target, (
            f"bind entry {volume!r} is missing source or target; refusing rather than "
            f"skipping, so the assertions below cannot go vacuous."
        )
        targets[ target ] = source
    return targets


@pytest.mark.parametrize( "service_name", REST_SERVICES )
def test_the_service_declares_the_flow_ratio_env_var( compose, service_name ):
    """
    HALF ONE, on both services. Without it the module falls back to `fleet_data_root()`,
    which is unwritable in a container — the original defect, returning as a 500 on every
    operator save.
    """
    value = _env_value( _service( compose, service_name ), ENV_KEY )
    assert value, (
        f"{service_name} does not set {ENV_KEY}. Without it flow_ratio_settings falls "
        f"back to fleet_data_root(), which inside the container resolves to "
        f"/projects-data/lupin — nonexistent and unwritable — so every "
        f"PATCH /api/tasks/flow-ratio/settings answers 500."
    )


@pytest.mark.parametrize( "service_name", REST_SERVICES )
def test_the_env_var_names_a_path_the_service_actually_mounts( compose, service_name ):
    """
    HALF TWO, on both services, and the check this file exists for: the mount TARGET
    must equal the env VALUE.

    A presence check passes while the two disagree, and that mismatch is worse than the
    bug it replaced — the write SUCCEEDS into container-local scratch and vanishes at the
    next bounce, silently, where the original failure was loud.
    """
    service = _service( compose, service_name )
    value   = _env_value( service, ENV_KEY )
    targets = _bind_targets( service )

    assert value in targets, (
        f"{service_name} sets {ENV_KEY}={value} but declares no bind mount with that "
        f"TARGET. The write would land in container-local scratch and vanish at the next "
        f"bounce — silently. Mounted targets: {sorted( targets )}"
    )


@pytest.mark.parametrize( "service_name", REST_SERVICES )
def test_the_mount_source_is_outside_the_repo_checkout( compose, service_name ):
    """
    The HOST side must not live inside the checkout.

    Runtime state left the tree because `git clean -xdf` lists gitignored files as
    "would remove" — measured 2026-07-26, 448 runtime files including cargo-bearing
    holds. A source under the repo would put the operator's saved threshold on that list.
    The CONTAINER-side path may sit under /var/lupin (dm-corpus does); it is the SOURCE
    that matters, and conflating the two is how this was nearly got wrong once already.
    """
    service = _service( compose, service_name )
    value   = _env_value( service, ENV_KEY )
    source  = _bind_targets( service )[ value ]

    repo_root = os.path.realpath( cu.get_project_root() )
    assert not os.path.realpath( source ).startswith( repo_root + os.sep ), (
        f"{service_name} mounts {source} — inside the repo checkout {repo_root}. "
        f"`git clean -xdf` would list it for removal; runtime state belongs outside."
    )


def test_both_services_share_one_host_directory( compose ):
    """
    HALF THREE: :7999 and :8000 must resolve to the SAME host path.

    The whole claim of the persisted override is that an operator's slider move on one
    server is honoured by the create gate on the other. Two different host directories
    give two live thresholds that agree until they don't — the board reporting "allow"
    while the other server refuses the create, which is precisely the drift the
    one-module design was built to make impossible.
    """
    sources = {}
    for name in REST_SERVICES:
        service         = _service( compose, name )
        value           = _env_value( service, ENV_KEY )
        sources[ name ] = _bind_targets( service )[ value ]

    assert len( set( sources.values() ) ) == 1, (
        f"the rest services mount DIFFERENT host directories for the flow-ratio "
        f"settings: {sources}. They must share one, or :7999 and :8000 hold two "
        f"different live thresholds."
    )


def test_the_env_key_matches_the_one_the_module_actually_reads():
    """
    Tie the compose key to the module's own constant, so a rename cannot pass here.

    Without this, every assertion above would keep asserting about a string nothing
    reads — green, well-named, and measuring a variable that no longer exists.
    """
    assert frs._SETTINGS_DIR_ENV == ENV_KEY, (
        f"flow_ratio_settings reads {frs._SETTINGS_DIR_ENV!r} but this file (and "
        f"docker-compose.yml) use {ENV_KEY!r}."
    )


# ---------------------------------------------------------------------------
# HALF FOUR: the host fallback must land in the mount, not one level above it.
# ---------------------------------------------------------------------------

def test_the_host_fallback_appends_the_same_subdirectory_the_mount_uses( compose ):
    """
    The two branches of `override_path()` must name ONE file. For three days they did not.

    MEASURED 2026-09-01, in the running containers and on the host:

        lupin-rest-dev    /var/lupin/flow-ratio/flow-ratio-settings.json
        lupin-rest-test   /var/lupin/flow-ratio/flow-ratio-settings.json
        host, BEFORE      <fleet_data_root>/flow-ratio-settings.json      <-- one level up
        host, AFTER       <fleet_data_root>/flow-ratio/flow-ratio-settings.json

    The mount hands the container `<fleet_data_root>/flow-ratio` as its whole world, so a
    fallback that stopped at `<fleet_data_root>` named a file no server ever writes —
    while the module's own docstring claimed "both name the SAME physical directory".
    `dm.py`, the resolver this was copied from, appends its subdirectory
    (`fleet_data_root()/dm-corpus`) and is correct; the copy dropped it.

    WHY NOBODY NOTICED: the wrong branch is only reachable from a HOST process, and no
    host-side caller reads this file yet. `<fleet_data_root>/flow-ratio-settings.json` did
    not exist, so there was nothing to migrate and nothing to go wrong — until the first
    host-side reader, which would have read an empty override and silently reported the
    INI default as the live threshold.

    This test derives the expected subdirectory from the COMPOSE MOUNT rather than
    hardcoding it, so moving the mount moves the assertion with it. It compares the two
    branches' RELATIVE tails, which is why the suite's tmp_path redirection of
    `fleet_data_root()` does not disturb it — the earlier cut of this test compared
    absolute paths and failed against a pytest tmp dir, measuring the harness.
    """
    service    = _service( compose, REST_SERVICES[ 0 ] )
    value      = _env_value( service, ENV_KEY )
    mount_leaf = _bind_targets( service )[ value ].rstrip( "/" ).rpartition( "/" )[ 2 ]

    assert frs.OVERRIDE_SUBDIR == mount_leaf, (
        f"the module appends {frs.OVERRIDE_SUBDIR!r} but the compose mount's host "
        f"directory is named {mount_leaf!r}. A host-side `override_path()` would land "
        f"outside the mount, naming a file no server reads or writes."
    )

    monkeypatched_root = str( frs.fleet_data_root() ).rstrip( "/" )
    host_path          = frs.override_path()

    assert host_path == os.path.join( monkeypatched_root, mount_leaf, frs.OVERRIDE_FILENAME ), (
        f"the host fallback resolved to {host_path!r}, which is not "
        f"<fleet_data_root>/{mount_leaf}/{frs.OVERRIDE_FILENAME}. The env-var branch and "
        f"the fallback branch name two different files again."
    )
