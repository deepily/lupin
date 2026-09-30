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
import subprocess

import pytest
import yaml

import cosa.utils.util as cu
from cosa.rest import flow_ratio_settings as frs


ENV_KEY = "LUPIN_FLOW_RATIO_DIR"

# The naming this repo gives the service that runs the app. Every rest service in every
# compose file carries it, on the service key and on container_name alike.
REST_SERVICE_PREFIX = "lupin-rest"


# ── THE POPULATION IS DERIVED, AND THAT IS THE FIX FOR WHAT THIS FILE MISSED ──────────
#
# 🔴 THIS FILE USED TO NAME ITS POPULATION BY HAND — `REST_SERVICES = ( "lupin-rest-dev",
# "lupin-rest-test" )`, with a fixture that opened `docker-compose.yml` and nothing else —
# and the comment above it said the list was explicit "so one cannot be added and silently
# left unmounted".
#
# That is exactly what then happened, and the hand-written list is why. `lupin-rest` in
# `docker-compose.cloud-gpu.yml` — the service deployed to lupin-host-test — has never
# carried either the env var or the mount. It was not "added and left unmounted"; it was
# never in the corpus, so no assertion here could see it. Measured 2026-09-26 in the
# running container on that VM: `LUPIN_FLOW_RATIO_DIR` absent, `override_path()` resolving
# to `/projects-data/lupin/flow-ratio/...` which does not exist there, and therefore
# `manager_pull_disabled` reading True off the INI fallback where dev reads False off the
# file — so a MANAGER could not pull a row it did not own into in_progress (row fbd1b273).
#
# ⇒ An enumeration cannot force a deliberate addition; it can only silently exclude. So
# the population is now derived twice over — every TRACKED compose file, and inside each,
# every service whose name says it runs the app — and `test_the_population_is_not_a_corpus`
# below states the denominator, so a guard that has quietly stopped watching something
# reports it rather than passing.


def _tracked_compose_files():
    """
    Every compose file the repo TRACKS, newest population read at test time.

    Tracked rather than globbed on purpose: a tracked compose file is one the fleet
    deploys from, which is precisely the set that must carry the mount. An untracked
    local experiment is nobody's deployment and is not this guard's business.

    🔴 IT ASKS GIT FOR EVERY yml/yaml AND FILTERS ON THE BASENAME, rather than handing git
    the pathspec `docker-compose*.yml`. That pathspec looks equivalent and is NARROWER, in
    exactly the way this file has already been burned once. Per `git help glossary`: with no
    directory prefix the pattern is fnmatched against the WHOLE path, so it matches only
    paths that LITERALLY BEGIN `docker-compose`. A nested `docker/docker-compose.vm.yml`
    would not match, and neither would `compose.yaml` — the Compose Spec's own default
    filename. Either one would be silently absent from the population and every assertion
    below would pass over a corpus one file short, which is precisely how
    `docker-compose.cloud-gpu.yml` went unwatched (row fbd1b273).

    ⇒ The predicate is "a compose file", so express THAT and let git enumerate the files.
    Today's answer is unchanged — the repo tracks 3 `.yml` and 2 are compose files — so this
    moves no result. It removes a way for the guard to go blind later without saying so.

    Ensures:
        - returns a sorted list of repo-relative paths whose BASENAME names a compose file
        - REFUSES (raises) if git cannot answer, rather than falling back to a glob — a
          silently narrower population is the defect this whole section exists to close
    """
    root   = cu.get_project_root()
    result = subprocess.run(
        [ "git", "-C", root, "ls-files", "*.yml", "*.yaml" ],
        capture_output=True, text=True, check=True,
    )
    return sorted(
        line for line in result.stdout.splitlines()
        if line.strip() and _names_a_compose_file( os.path.basename( line.strip() ) )
    )


def _names_a_compose_file( basename ):
    """
    Whether a filename is a Docker Compose file, by the two shapes Compose itself accepts.

    Requires:
        - basename is a filename with no directory part

    Ensures:
        - True for `docker-compose.yml`, `docker-compose.<anything>.yml`, `compose.yaml`
          and their .yml/.yaml counterparts
        - False for a yaml that merely mentions composing (`.docview.yml`, a CI workflow)
        - pinned in BOTH directions by its own test, so it cannot silently widen into
          "every yaml is a compose file" — which would make the population meaningless in
          the other direction
    """
    stem = basename.rsplit( ".", 1 )[ 0 ]
    return stem == "compose" or stem == "docker-compose" or stem.startswith( "docker-compose." )


def _rest_services( compose, path ):
    """
    Every service in one parsed compose file that runs the app.

    THE PREDICATE, not a list: a service key OR container_name beginning
    `lupin-rest`. Both are checked and required to agree when both are present, so a
    service cannot slip past by carrying the prefix on only the half this looked at.

    Ensures:
        - returns { service_name: service_body } for the app services in this file
        - may legitimately be EMPTY (a compose file that deploys no rest service), which
          is why the denominator test below asserts about the union rather than each file
    """
    found = {}
    for name, body in ( compose.get( "services" ) or {} ).items():
        if not isinstance( body, dict ): continue
        container = body.get( "container_name" )
        by_key    = name.startswith( REST_SERVICE_PREFIX )
        by_name   = isinstance( container, str ) and container.startswith( REST_SERVICE_PREFIX )
        if by_key or by_name:
            assert not ( container and by_key != by_name ), (
                f"{path}: service {name!r} has container_name {container!r} — the key and "
                f"the container name disagree about whether this is a rest service. One of "
                f"them is a typo, and either way this guard would have watched the wrong set."
            )
            found[ name ] = body
    return found


def _load( path ):
    """The parsed compose file at a repo-relative path."""
    with open( os.path.join( cu.get_project_root(), path ), "r" ) as handle:
        return yaml.safe_load( handle )


def _rest_service_ids():
    """
    Every ( compose file, service name ) pair this file asserts about, collected at
    import so pytest can parametrize on it and NAME each one in its report.
    """
    pairs = []
    for path in _tracked_compose_files():
        for name in sorted( _rest_services( _load( path ), path ) ):
            pairs.append( ( path, name ) )
    return pairs


REST_SERVICE_IDS = _rest_service_ids()


@pytest.fixture( scope="module" )
def composes():
    """Every tracked compose file, parsed, keyed by repo-relative path."""
    return { path: _load( path ) for path in _tracked_compose_files() }


def _service( composes, path, name ):
    services = ( composes[ path ].get( "services" ) or {} )
    assert name in services, (
        f"service {name!r} is missing from {path}; known services: {sorted( services )}"
    )
    return services[ name ]


def _mount_source( service, path, name ):
    """
    The HOST path this service mounts at the directory its env var names.

    WHY THIS IS A HELPER AND NOT AN INLINE LOOKUP. Every test below that needs the SOURCE
    needs the env value first, and the obvious `_bind_targets( service )[ value ]` raises
    KeyError when the var is absent — so the three dependent tests reddened with a bare
    KeyError while the one test that knows WHY reddened with the real message. Measured
    2026-09-26 on a deliberate revert arm: 4 reds, 1 legible. A cascade is fine and even
    desirable; a cascade that loses the diagnosis on the way down is not.

    Ensures:
        - asserts the env var is set, naming the service and the file
        - asserts a bind mount exists at that exact target, listing the ones that do
        - returns the host source string
    """
    value   = _env_value( service, ENV_KEY )
    assert value, (
        f"{path}: {name} does not set {ENV_KEY}, so there is no target "
        f"to look up. See test_the_service_declares_the_flow_ratio_env_var for what that "
        f"costs at runtime."
    )
    targets = _bind_targets( service )
    assert value in targets, (
        f"{path}: {name} sets {ENV_KEY}={value} but mounts nothing at "
        f"that target. Mounted targets: {sorted( targets )}"
    )
    return targets[ value ]



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


def _is_read_only( service, target ):
    """
    Whether the bind at `target` is declared READ-ONLY, in either compose form.

    Ensures:
        - short form: a trailing `:ro` mode field
        - long form: `read_only: true`
        - returns False when the target is not a bind at all (the callers have already
          asserted it is one, so this is not a silent pass — it is a narrower question)
    """
    for volume in service.get( "volumes" ) or []:
        if isinstance( volume, str ):
            parts = volume.split( ":" )
            if len( parts ) >= 2 and parts[ 1 ] == target:
                return "ro" in parts[ 2: ]
            continue
        if isinstance( volume, dict ) and volume.get( "target" ) == target:
            return bool( volume.get( "read_only" ) )
    return False


@pytest.mark.parametrize( "path,service_name", REST_SERVICE_IDS )
def test_the_flow_ratio_bind_is_writable( composes, path, service_name ):
    """
    THE MOUNT MUST BE WRITABLE, and this is the one assertion in this file that the
    compose-parity guard cannot make for us.

    `test_env_key_parity` and `test_mount_parity` in
    `src/tests/unit/deploy/test_compose_service_parity.py` compare each dimension against
    the dev services and would pass a `:ro` mount happily — presence is all they ask. But a
    read-only bind reproduces the ORIGINAL 2026-09-01 symptom exactly: every
    `PATCH /api/tasks/flow-ratio/settings` and every
    `PATCH /api/tasks/approval-settings` answers 500 on a PermissionError, with the mount
    present and correctly targeted, and with a completely different cause from the missing
    directory that produced it the first time. Somebody debugging that would check the
    mount, see it, and look elsewhere.

    Suggested by Rachel 🕊️ in her phase-2 pre-work review (row fbd1b273) as the second of
    two candidate checks that earn their place beside the parity arms. The first — env value
    equals a mount target in the same service — is
    `test_the_env_var_names_a_path_the_service_actually_mounts` above, now generalized to
    every rest service in every tracked compose file rather than the two it used to watch.
    """
    service = _service( composes, path, service_name )
    value   = _env_value( service, ENV_KEY )
    _mount_source( service, path, service_name )        # asserts the bind exists first

    assert not _is_read_only( service, value ), (
        f"{path}: {service_name} mounts {value} READ-ONLY. The settings writers would fail "
        f"with PermissionError and every operator save would answer 500 — the same symptom "
        f"as the missing directory this mount exists to fix, from a different cause."
    )


def test_the_compose_filename_predicate_both_directions():
    """
    `_names_a_compose_file` decides the whole population, so it is pinned BOTH ways.

    A predicate that only ever gets checked on today's two filenames is indistinguishable
    from `return True`, and `return True` would sweep every tracked yaml into a guard that
    then fails on the first CI workflow. Pinned in the same shape as the parity file's
    `test_prefix_coverage_helper_both_directions`.
    """
    for name in ( "docker-compose.yml", "docker-compose.yaml", "docker-compose.cloud-gpu.yml",
                  "docker-compose.vm.yml", "compose.yml", "compose.yaml" ):
        assert _names_a_compose_file( name ) is True, f"{name} should be recognised"

    for name in ( ".docview.yml", "ci.yml", "docker-composer.yml", "compose-notes.yml",
                  "my-docker-compose.yml", "pre-commit-config.yaml" ):
        assert _names_a_compose_file( name ) is False, (
            f"{name} must NOT be recognised — widening this predicate silently widens the "
            f"population into files that were never deployments."
        )


def test_the_read_only_helper_both_directions():
    """
    `_is_read_only` in all four shapes, including the one the tests cannot otherwise reach.

    WHY IT NEEDS ITS OWN TEST: `test_the_flow_ratio_bind_is_writable` calls `_mount_source`
    first, which asserts the bind exists — so the helper's final "target is not a bind here"
    return is unreachable from that path. An unreachable line is a branch-coverage hole, and
    the honest fix is to exercise it rather than to pragma it away.
    """
    short_ro = { "volumes": [ "/host/a:/ctr/a:ro" ] }
    short_rw = { "volumes": [ "/host/a:/ctr/a" ] }
    long_ro  = { "volumes": [ { "type": "bind", "source": "/host/a", "target": "/ctr/a",
                                "read_only": True } ] }
    long_rw  = { "volumes": [ { "type": "bind", "source": "/host/a", "target": "/ctr/a" } ] }

    assert _is_read_only( short_ro, "/ctr/a" ) is True
    assert _is_read_only( short_rw, "/ctr/a" ) is False
    assert _is_read_only( long_ro,  "/ctr/a" ) is True
    assert _is_read_only( long_rw,  "/ctr/a" ) is False

    # The unreachable-from-the-guard cases: a target this service does not mount at all,
    # and a service with no volumes key whatsoever.
    assert _is_read_only( short_ro, "/ctr/somewhere-else" ) is False
    assert _is_read_only( {},       "/ctr/a" )              is False


def test_the_population_is_not_a_corpus():
    """
    THE DENOMINATOR, stated out loud — the guard this file was missing.

    A guard that cannot say how many things it watches is telling you about its corpus,
    not about the surface. This one says: how many compose files were found, how many rest
    services in total, and which files contributed. It fails on an EMPTY population and on
    a compose file that tracks no rest service at all, because both are ways for the four
    assertions below to become vacuous while staying green.

    ⚠️ It deliberately does NOT assert a fixed count. A number here would have to be edited
    by whoever adds a service — which is the hand-maintained list this file just removed,
    reintroduced one line lower down. What it asserts is that every tracked compose file
    contributed at least one watched service, which is the property that broke.
    """
    files = _tracked_compose_files()
    assert files, (
        "no tracked docker-compose*.yml found. `git ls-files` returned nothing, so every "
        "assertion in this file would pass over an empty population."
    )

    per_file = { path: sorted( _rest_services( _load( path ), path ) ) for path in files }
    assert REST_SERVICE_IDS, (
        f"no rest service found in any tracked compose file. Watched files: {files}. "
        f"Either the {REST_SERVICE_PREFIX!r} naming changed, or this guard is now watching "
        f"nothing while reporting green."
    )

    unwatched = [ path for path, names in per_file.items() if not names ]
    assert not unwatched, (
        f"tracked compose file(s) {unwatched} declare no service named {REST_SERVICE_PREFIX}*, "
        f"so nothing in them is checked. If one genuinely deploys no rest service, say so "
        f"here explicitly — an unexplained zero is how docker-compose.cloud-gpu.yml went "
        f"unwatched until row fbd1b273. Population: { {p: len(n) for p, n in per_file.items()} }"
    )


@pytest.mark.parametrize( "path,service_name", REST_SERVICE_IDS )
def test_the_service_declares_the_flow_ratio_env_var( composes, path, service_name ):
    """
    HALF ONE, on EVERY rest service in EVERY tracked compose file. Without it the module
    falls back to `fleet_data_root()`, which is unwritable in a container — the original
    defect, returning as a 500 on every operator save — and which also drops
    `manager_pull_disabled` back to its closed-side INI fallback (row fbd1b273).
    """
    value = _env_value( _service( composes, path, service_name ), ENV_KEY )
    assert value, (
        f"{path}: {service_name} does not set {ENV_KEY}. Without it the settings modules "
        f"fall back to fleet_data_root(), which inside the container resolves to "
        f"/projects-data/lupin — nonexistent and unwritable — so every "
        f"PATCH /api/tasks/flow-ratio/settings answers 500, and every task-approval "
        f"override key silently falls through to its INI fallback. On lupin-host-test that "
        f"made manager_pull_disabled read True where dev reads False, and a manager could "
        f"not pull a row it did not own into in_progress."
    )


@pytest.mark.parametrize( "path,service_name", REST_SERVICE_IDS )
def test_the_env_var_names_a_path_the_service_actually_mounts( composes, path, service_name ):
    """
    HALF TWO, and the check this file exists for: the mount TARGET must equal the env VALUE.

    A presence check passes while the two disagree, and that mismatch is worse than the
    bug it replaced — the write SUCCEEDS into container-local scratch and vanishes at the
    next bounce, silently, where the original failure was loud.
    """
    service = _service( composes, path, service_name )
    value   = _env_value( service, ENV_KEY )
    targets = _bind_targets( service )

    assert value in targets, (
        f"{path}: {service_name} sets {ENV_KEY}={value} but declares no bind mount with "
        f"that TARGET. The write would land in container-local scratch and vanish at the "
        f"next bounce — silently. Mounted targets: {sorted( targets )}"
    )


@pytest.mark.parametrize( "path,service_name", REST_SERVICE_IDS )
def test_the_mount_source_is_outside_the_repo_checkout( composes, path, service_name ):
    """
    The HOST side must not live inside the checkout.

    Runtime state left the tree because `git clean -xdf` lists gitignored files as
    "would remove" — measured 2026-07-26, 448 runtime files including cargo-bearing
    holds. A source under the repo would put the operator's saved threshold on that list.
    The CONTAINER-side path may sit under /var/lupin (dm-corpus does); it is the SOURCE
    that matters, and conflating the two is how this was nearly got wrong once already.

    ⚠️ A relative source (`./io`) is resolved against the compose file's directory, which
    IS the checkout — so the leading-dot form is rejected by the same rule rather than
    slipping through as a path this does not recognise. That resolution was ADDED when the
    population widened, and it is a TIGHTENING: the previous cut called `realpath` on the
    raw string, resolving a relative source against whatever directory pytest happened to
    run from. A candidate `./flow-ratio` bind would have passed that and fails this.

    🔴 THE ASSUMPTION I DROPPED WHEN cloud-gpu JOINED THIS POPULATION, named rather than
    left for a reader to infer (Rachel 🕊️'s finding 3, row fbd1b273). For a source on
    ANOTHER machine — `/mnt/lupin-data/...` on the GCP VM — this box cannot check that the
    path exists, is a directory, or is writable. `realpath` on a nonexistent path returns it
    unchanged, so the not-inside-the-checkout test still answers correctly, and that is ALL
    it answers for an off-box source. It is a weak instance of a real check, not a loosened
    one: nothing was relaxed for the dev pair, and no new latitude was given to anybody.
    ⇒ The off-box half is unreachable from a compose parser at all, so it is carried by the
    post-deploy checklist on row fbd1b273 instead: a `docker inspect` of the recreated
    container plus asking it what `override_path()` resolved to. If you are reading this
    because you want the guard to cover it, the answer is that no unit test can, and the
    honest place for it is the deploy step.
    """
    service = _service( composes, path, service_name )
    value   = _env_value( service, ENV_KEY )
    source  = _bind_targets( service )[ value ]

    repo_root = os.path.realpath( cu.get_project_root() )
    resolved  = os.path.realpath( os.path.join( repo_root, source ) )
    assert not resolved.startswith( repo_root + os.sep ), (
        f"{path}: {service_name} mounts {source} — inside the repo checkout {repo_root}. "
        f"`git clean -xdf` would list it for removal; runtime state belongs outside."
    )


@pytest.mark.parametrize( "path", sorted( { p for p, _ in REST_SERVICE_IDS } ) )
def test_the_services_in_one_compose_file_share_one_host_directory( composes, path ):
    """
    HALF THREE, and it is a PER-FILE invariant — deliberately, because that is what the
    thing being protected actually is.

    Within one compose file the services are co-deployed on one machine, and the whole
    claim of the persisted override is that an operator's slider move on one server is
    honoured by the create gate on the other. Two host directories there give two live
    thresholds that agree until they don't.

    ACROSS files they are DIFFERENT MACHINES — `docker-compose.yml` runs on the dev box,
    `docker-compose.cloud-gpu.yml` on lupin-host-test — and requiring one shared host path
    would be asserting that a GCP VM and the dev box share a filesystem. That is why this
    is parametrized per file instead of collapsing the union: the earlier cut of this test
    compared every service in one file and would have failed the moment a second file
    joined the population, for a reason that is not a defect.

    🔴 THE COMPOSE FILE IS A PROXY FOR THE HOST, AND A PROXY IS WHAT IT IS (Rachel 🕊️'s
    point, row fbd1b273). The invariant `flow_ratio_settings` actually states is "one box,
    one data root" — not "one directory per file". Today the two coincide, because each
    compose file deploys to exactly one machine. If that ever stops being true — two hosts'
    services described in one file, or one host's services split across two — this test
    keeps passing while the real invariant breaks, and it will not say so. There is nothing
    in a compose file that names the machine it lands on, so a unit test cannot close that
    gap; what it can do is state the assumption where the next reader will hit it.

    ⚠️ AND ONE INSTANCE OF THIS TEST CANNOT FAIL TODAY: `docker-compose.cloud-gpu.yml` holds
    a single rest service, so its set of sources has one element and is trivially size 1.
    Disclosed rather than left to be discovered — it is carried for the population, not for
    the check, and the `assert sources` line above it is what stops it going vacuous if the
    population ever empties.
    """
    sources = {}
    for name in sorted( _rest_services( composes[ path ], path ) ):
        service         = _service( composes, path, name )
        value           = _env_value( service, ENV_KEY )
        sources[ name ] = _bind_targets( service )[ value ]

    assert sources, f"{path}: no rest service to compare — the assertion below would be vacuous."
    assert len( set( sources.values() ) ) == 1, (
        f"{path}: its rest services mount DIFFERENT host directories for the flow-ratio "
        f"settings: {sources}. Services co-deployed on one machine must share one, or the "
        f"two servers hold two different live thresholds."
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

def test_the_host_fallback_appends_the_same_subdirectory_the_mount_uses( composes ):
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
    # ⚠️ ONE service is enough here and it must be, because the leaf is a property of the
    # MODULE, not of any one deployment. Every watched service's leaf is checked to agree
    # first, so reading the first pair is a sample of a set already proven uniform rather
    # than an arbitrary pick.
    leaves = {}
    for path, name in REST_SERVICE_IDS:
        service            = _service( composes, path, name )
        value              = _env_value( service, ENV_KEY )
        source             = _bind_targets( service )[ value ]
        leaves[ (path, name) ] = source.rstrip( "/" ).rpartition( "/" )[ 2 ]

    assert len( set( leaves.values() ) ) == 1, (
        f"the watched services' flow-ratio host directories have DIFFERENT leaf names: "
        f"{leaves}. The module appends ONE subdirectory ({frs.OVERRIDE_SUBDIR!r}), so at "
        f"most one of these can be the directory a host-side override_path() lands in."
    )
    mount_leaf = next( iter( leaves.values() ) )

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


# 🔴 THE SUBDIRECTORY IS ANCHORED TO THE MOUNT; THE FILENAME WAS ANCHORED TO ITSELF.
#
# Found by an independent mutation pass, 2026-09-02 (Tiberius 👑). Two arms against
# `override_path()`'s two components, run over the whole sixteen-file population:
#
#     OVERRIDE_SUBDIR   "flow-ratio" -> "flow_ratio"          KILLED, by the test above
#     OVERRIDE_FILENAME "flow-ratio-settings.json"
#                       -> "flow_ratio_settings.json"         SURVIVED everything
#
# The guard above is HALF a parity check and the halves are not equally strong. It derives
# the expected subdirectory from the COMPOSE MOUNT — an independent source that a rename
# cannot move — and that half is genuinely falsifiable. Its closing assertion then reads
#
#     assert host_path == os.path.join( root, mount_leaf, frs.OVERRIDE_FILENAME )
#
# and `override_path()` BUILDS host_path out of `OVERRIDE_FILENAME`. Both sides move
# together, so that clause is true for every possible filename — the same unfalsifiable
# shape as the fallback-constant assertions in test_flow_ratio_settings.py, in the same
# feature, found the same night. It is correct about the subdirectory and says nothing
# about the filename.
#
# WHY A FILENAME DRIFT IS NOT HARMLESS, even though reads and writes would agree with each
# other. The servers already hold a file at the shipped name — measured in both running
# containers and recorded in the docstring above:
#
#     lupin-rest-dev    /var/lupin/flow-ratio/flow-ratio-settings.json
#     lupin-rest-test   /var/lupin/flow-ratio/flow-ratio-settings.json
#
# A rename lands the next deployment on a file that does not exist, so the operator's
# persisted override silently stops being read and the INI default is reported as the live
# threshold. That is the SAME failure the subdirectory defect would have produced — an
# empty override read as an intentional one — reached through the other component. And it
# is quiet in exactly the same way: nothing errors, a plausible number is displayed.
#
# ⇒ The filename has no independent source to derive from — the mount names a DIRECTORY,
# not a file — so it is pinned by a LITERAL, and the literal is the control. Do NOT rewrite
# this to reference `frs.OVERRIDE_FILENAME`; that is precisely the defect being closed.

def test_the_override_filename_is_the_one_the_servers_already_hold():
    """
    The shipped filename is pinned by a literal, independently of the module constant.

    Ensures:
        - reddens if OVERRIDE_FILENAME is renamed, which the parity test above cannot do
          because it compares the constant against a path built from that same constant
    """
    assert frs.OVERRIDE_FILENAME == "flow-ratio-settings.json", (
        "the override filename changed. Both running containers hold "
        "/var/lupin/flow-ratio/flow-ratio-settings.json; a rename makes the next "
        "deployment read a file that does not exist and report the INI default as the "
        "operator's live threshold. If the change is deliberate, migrate the deployed "
        "files and update this literal — do NOT make this assertion reference "
        "frs.OVERRIDE_FILENAME, which would make it unfalsifiable again."
    )


def test_the_two_constants_compose_to_the_deployed_path():
    """
    `<subdir>/<filename>` is the tail the servers actually use, pinned end to end.

    The test above pins the filename and the parity test pins the subdirectory against the
    compose mount. This one pins their COMPOSITION, so a change that splits the difference
    — moving a separator between the two constants, say — cannot pass both while producing
    a third path.

    Ensures:
        - the joined tail equals the measured container path's tail, by literal
    """
    tail = f"{frs.OVERRIDE_SUBDIR}/{frs.OVERRIDE_FILENAME}"
    assert tail == "flow-ratio/flow-ratio-settings.json", (
        f"the module composes {tail!r}, but both rest containers hold "
        f"/var/lupin/flow-ratio/flow-ratio-settings.json. The mount hands the container "
        f"that directory as its whole world, so a container reading any other tail reads "
        f"nothing at all."
    )
