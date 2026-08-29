"""
Compose-service parity — R1 of the configuration-splintering analysis
(src/rnd/v0.1.9/2026.07.26-configuration-splintering-analysis.md).

THE DEFECT THIS EXISTS TO CATCH
-------------------------------
The `lupin-rest` service shape is defined THREE times across TWO compose files,
each list hand-maintained, and no two agree. (It was FOUR across THREE until
2026-08-26, when docker-compose.cloud-test.yml was retired — row 0d175dac. The
defect below is UNCHANGED: it lives between docker-compose.yml and
docker-compose.cloud-gpu.yml, which is the pair that actually regressed.) On 2026-05-12 two doc-viewer binds
were added to docker-compose.yml; they were never copied into
docker-compose.cloud-gpu.yml, and the VM's doc viewer served NOTHING for weeks.
Root cause, in the runbook's own words: "nothing compared the two files."

This is the comparator. It is STATIC — no docker, no VM, no network.

WHAT IT IS NOT
--------------
It is NOT a demand for uniformity. Several divergences are RULED DECISIONS
(cloud-gpu deliberately omits the dev-box-only surfaces — worktree lanes, test
runner config, training env).
The rule is that every divergence be DECLARED AND DATED, not that none exist.

Both maps below are checked in BOTH DIRECTIONS: an entry that is no longer
divergent FAILS, so landing a fix forces the exemption out. A one-way allow-list
rots into a permanent excuse — the lesson recorded on test_external_scope_mount_parity.py.

Venue: :7999-eligible / AI-discretionary. Runs in milliseconds.
"""
import os

import pytest
import yaml

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()

# The four definitions of one service shape.
SERVICES = {
    "dev-dev"    : ( "docker-compose.yml",            "lupin-rest-dev"  ),
    "dev-test"   : ( "docker-compose.yml",            "lupin-rest-test" ),
    "cloud-gpu"  : ( "docker-compose.cloud-gpu.yml",  "lupin-rest"      ),
}

# ── KNOWN_DIVERGENT_MOUNTS ────────────────────────────────────────────────
# mount target -> { service_key: "dated reason it is legitimately absent" }
# An absence NOT listed here fails. An entry listed here that is actually
# PRESENT also fails (stale exemption).
KNOWN_DIVERGENT_MOUNTS = {
    "/var/lupin/.git": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "/var/lupin/.claude/worktrees": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/.git.",
    },
    "/var/lupin/pytest.ini": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "/var/lupin/dm-corpus": {
        "cloud-gpu" : "2026-08-13 — same.",
    },
    # ── repo-root deploy artifacts the UNIT SUITE asserts about (bug b5b6d252) ──
    # Mounted read-only into dev + test because 19 unit tests read them and were
    # failing in-container with FileNotFoundError while passing on the host.
    #
    # The exemption is scoped to WHO RUNS THE UNIT SUITE, not to "cloud legs are
    # different". That distinction is load-bearing: a blanket cloud-legs-differ
    # reason would ALSO excuse a cloud leg losing a mount it genuinely needs,
    # which is the KNOWN_DIVERGENT near-miss this file already carries once. If a
    # cloud leg ever runs the unit suite, these entries must go, and the predicate
    # says so rather than leaving it to memory.
    "/var/lupin/docker-compose.yml": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "/var/lupin/docker-compose.cloud-gpu.yml": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/var/lupin/docker": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/var/lupin/.dockerignore": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/var/lupin/.docview.yml": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    # The remaining surfaces test_no_hardcoded_gcp_identifiers READS. It walks
    # git ls-files rather than a list, so the set is 16 files, not the 6 the
    # first pass guessed — see test_repo_root_artifact_mount_parity.py.
    "/var/lupin/.gitleaks.toml": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/var/lupin/.stylelintrc.json": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/var/lupin/alembic.ini": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/var/lupin/package.json": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/var/lupin/package-lock.json": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    # ── node_modules — TEST-ONLY, and the dev absence is NOT the same reason ──
    # Added 2026-07-27 (Krishna, row 719962ed) so the `typescript` tier can resolve
    # c8/tsx/esbuild. node is baked into the image; node_modules is .dockerignore'd
    # and must be bound. The two absences below are deliberately given SEPARATE
    # reasons because they expire on different events — collapsing them into one
    # "not a test venue" line would let the dev entry outlive its cause silently.
    "/var/lupin/node_modules": {
        "dev-dev"   : "2026-07-27 — NOT a ruling that dev should lack it. The mount is "
                      "correct for dev too, but applying it recreates lupin-rest-dev, "
                      "and :7999 is Rick's live dev server — not a bounce this lane may "
                      "take. REMOVE THIS ENTRY the next time :7999 is recreated for any "
                      "other reason; the tier does not run there today, so nothing is lost "
                      "meanwhile.",
        "cloud-gpu" : "2026-07-27 — same: the cloud legs do not run the typescript tier.",
    },
    "/var/lupin/pyproject.toml": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/var/lupin/tsconfig.json": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/var/lupin/tsconfig.diagnostic.json": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/var/lupin/tsconfig.nav.json": {
        "cloud-gpu" : "2026-07-26 — see /var/lupin/docker-compose.yml.",
    },
    "/home/rruiz/.lora_env": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "/home/rruiz/.lupin": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "/var/external-claude/plans": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "/cloudsql": {
        "dev-dev"  : "2026-07-26 — dev runs a local postgres container; the Cloud SQL "
                     "Auth Proxy socket exists only on cloud legs.",
        "dev-test" : "2026-07-26 — same.",
    },
    "/var/lupin/src/conf/keys": {
        "dev-dev"  : "2026-07-26 — on dev the keys dir is already inside the ./src bind; "
                     "the cloud leg binds it separately because it has no ./src bind.",
        "dev-test" : "2026-07-26 — same.",
    },
    # 2026-08-02 — BOTH /home/rruiz/.claude entries DELETED, gap closed, not excused.
    #
    # This table used to carry two entries here: one excusing dev for binding the
    # single .credentials.json FILE while the cloud legs mounted a claude-creds
    # VOLUME, and one excusing the cloud legs for lacking the file target. Both are
    # gone because dev now uses the volume shape too (row c7c60896, ruled 2026-08-02).
    #
    # The divergence was never cosmetic. A single-file bind is resolved ONCE at
    # container start, and Claude Code renews its token by REPLACING the file — so
    # dev and test 401'd roughly three times a day while the cloud legs, on the
    # volume shape, never did. "Same fact, different shape" was the wrong reading:
    # only one of the two shapes worked.
    #
    # This test is what surfaced the leftovers — it failed with "IS NOW PRESENT in
    # dev-dev / dev-test" the moment the mounts converged, which is the entire point
    # of the stale-exemption check.
    # ── the doc-viewer surface: ONE fact, TWO deliberate shapes ────────────
    # NB: cloud-gpu is deliberately NOT exempted here. It satisfies this target by
    # CHILD COVERAGE (see _covered_by_children) — it binds each repo explicitly because
    # /mnt/lupin-data is also the docker data-root. Encoding that as a flat exemption
    # was my first attempt and the control below REFUTED it: a blanket "cloud-gpu may
    # lack this" would equally have masked cloud-gpu losing all four explicit binds,
    # i.e. the exact 2026-05-12 regression. An exemption must not be wider than the
    # divergence it excuses.
}

# ── KNOWN_DIVERGENT_ENV ───────────────────────────────────────────────────
KNOWN_DIVERGENT_ENV = {
    "LUPIN_DM_CORPUS_DIR": {
        "cloud-gpu" : "2026-08-13 — same.",
    },
    "LUPIN_SERVER_PORT": {
        "cloud-gpu" : "2026-08-13 — same.",
    },
    "CHROME_PATH": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "LUPIN_INTERACTIVE_TESTS": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    # LUPIN_V1_ARM_BASE_URL and LUPIN_PAIRED_N had exemptions here until 2026-08-26. Both
    # were removed from docker-compose.yml with the V1 excision (row e2099400 §2), so an
    # exemption for them would now be an entry excusing a variable that does not exist —
    # which is how this table rots into something nobody trusts.
    "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "GH_TOKEN": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "DB_HOST": {
        "cloud-gpu" : "2026-07-26 — same.",
    },
    "DB_NAME": {
        "dev-dev"  : "2026-07-26 — dev derives the DB from the compose postgres service.",
        "dev-test" : "2026-07-26 — same.",
    },
    "DB_USER": {
        "dev-dev"  : "2026-07-26 — see DB_NAME.",
        "dev-test" : "2026-07-26 — same.",
    },
    "DB_PASSWORD": {
        "dev-dev"  : "2026-07-26 — see DB_NAME.",
        "dev-test" : "2026-07-26 — same.",
    },
    "CLOUD_SQL_CONNECTION_NAME": {
        "dev-dev"  : "2026-07-26 — no Cloud SQL on dev.",
        "dev-test" : "2026-07-26 — same.",
    },
    "LUPIN_CLOUD_BACKED": {
        "dev-dev"  : "2026-07-26 — the cloud-backing trigger; false by absence on dev.",
        "dev-test" : "2026-07-26 — same.",
    },
    "CLAUDE_CODE_OAUTH_TOKEN": {
        "dev-dev"  : "2026-07-26 — dev uses the host's OAuth login via the credentials bind.",
        "dev-test" : "2026-07-26 — same.",
    },
    "LUPIN_DEV_EMAIL": {
        "dev-dev"  : "2026-07-26 UNCLASSIFIED — set on lupin-rest-test but NOT lupin-rest-dev, "
                     "an asymmetry between two services in the SAME file. notify() reads this "
                     "for target-user resolution (401 without it). Not yet determined whether "
                     "dev-dev needs it. Records an open question, not a ruling.",
        "cloud-gpu" : "2026-07-26 UNCLASSIFIED — see above.",
    },
    "LUPIN_MODEL_SERVER_API_KEY_FILE": {
        "cloud-gpu": "2026-07-26 UNCLASSIFIED — present in the other THREE services, absent "
                     "here. cloud-gpu reaches the Cloud Run model server, the same path whose "
                     "key drifted on 07-25 (STT 401). Whether this absence is correct has NOT "
                     "been determined. Records an open question, not a ruling.",
    },
}


def _load_service( filename, service ):
    path = os.path.join( PROJECT_ROOT, filename )
    with open( path ) as fh:
        doc = yaml.safe_load( fh )
    return doc[ "services" ][ service ]


def _mount_target( entry ):
    """
    Container-side path of one compose volume entry.

    Requires:
        - entry is a compose volume item (short "src:dst[:opts]" string or long form dict)
    Ensures:
        - returns the container path, or None when the entry declares none
    """
    if isinstance( entry, dict ):
        return entry.get( "target" )
    parts = str( entry ).split( ":" )
    return parts[ 1 ] if len( parts ) >= 2 else None


def _mounts( svc ):
    out = set()
    for v in svc.get( "volumes" ) or []:
        t = _mount_target( v )
        if t is not None:
            out.add( t )
    return out


def _env_keys( svc ):
    env = svc.get( "environment" )
    return set( env.keys() ) if isinstance( env, dict ) else set()


def _covered_by_prefix( target, present ):
    """
    True when an ancestor bind already covers `target`.

    Requires:
        - target is a container path, present is the set of that service's mount targets
    Ensures:
        - returns True iff some entry in `present` is a proper ancestor directory of target

    WHY THIS EXISTS: dev binds the single glob `/var/external-projects`, while cloud-gpu
    binds four explicit children of it. The same fact in two shapes. Without this, the
    comparator would report four false divergences on a correctly-configured pair —
    an instrument that cries wolf gets muted, and a muted instrument catches nothing.
    """
    for p in present:
        if p != target and target.startswith( p.rstrip( "/" ) + "/" ):
            return True
    return False


def _covered_by_children( target, present ):
    """
    True when the service satisfies a DIRECTORY target by binding its children instead.

    Requires:
        - target is a container path, present is the set of that service's mount targets
    Ensures:
        - returns True iff at least one entry in `present` is a proper descendant of target
        - returns False when `present` contains no descendant — so stripping ALL the
          children makes this False and the parity check FIRES

    WHY THIS EXISTS: dev binds `/var/external-projects` as one glob; cloud-gpu binds four
    explicit children, because on the VM that host dir is also the docker data-root and a
    glob would expose the OAuth login and the sync bundles to the doc viewer (runbook §7c).
    Same fact, two shapes.

    WHY IT IS A PREDICATE AND NOT AN EXEMPTION: a flat "cloud-gpu may lack the parent"
    entry is TRUE regardless of whether the children are there — so it would keep passing
    if all four were deleted, which is the 2026-05-12 doc-viewer regression itself. This
    form is false the moment the children go, which is the whole point.
    """
    prefix = target.rstrip( "/" ) + "/"
    return any( p.startswith( prefix ) for p in present )


@pytest.fixture( scope="module" )
def parsed():
    return { key: _load_service( f, s ) for key, ( f, s ) in SERVICES.items() }


def test_all_four_services_parse( parsed ):
    """Instrument check — a parse failure must not read as parity."""
    assert set( parsed ) == set( SERVICES )
    for key, svc in parsed.items():
        assert _mounts( svc ), f"{key} parsed with ZERO mounts — parser or file is wrong"


def test_mount_parity( parsed ):
    """
    Every mount target present in ANY service must be present in EVERY service,
    unless covered by an ancestor bind or declared in KNOWN_DIVERGENT_MOUNTS.
    """
    per_service = { k: _mounts( v ) for k, v in parsed.items() }
    universe    = set().union( *per_service.values() )

    undeclared = []
    for target in sorted( universe ):
        for key, present in per_service.items():
            if target in present:                       continue
            if _covered_by_prefix( target, present ):   continue
            if _covered_by_children( target, present ): continue
            if key in KNOWN_DIVERGENT_MOUNTS.get( target, {} ): continue
            undeclared.append( f"{target}  absent from  {key}" )

    assert not undeclared, (
        "compose mount divergence with no dated KNOWN_DIVERGENT_MOUNTS entry:\n  "
        + "\n  ".join( undeclared )
        + "\n\nEither copy the mount across, or add a dated entry with the reason."
    )


def test_env_key_parity( parsed ):
    per_service = { k: _env_keys( v ) for k, v in parsed.items() }
    universe    = set().union( *per_service.values() )

    undeclared = []
    for key_name in sorted( universe ):
        for svc_key, present in per_service.items():
            if key_name in present:                              continue
            if svc_key in KNOWN_DIVERGENT_ENV.get( key_name, {} ): continue
            undeclared.append( f"{key_name}  absent from  {svc_key}" )

    assert not undeclared, (
        "compose environment-key divergence with no dated KNOWN_DIVERGENT_ENV entry:\n  "
        + "\n  ".join( undeclared )
        + "\n\nEither set it, or add a dated entry with the reason."
    )


def test_no_stale_mount_exemptions( parsed ):
    """
    REVERSE ARM — an exemption that is no longer needed must fail, so landing a
    fix forces the excuse out. A one-way allow-list rots into a permanent excuse.
    """
    per_service = { k: _mounts( v ) for k, v in parsed.items() }
    stale = []
    for target, svc_map in KNOWN_DIVERGENT_MOUNTS.items():
        for svc_key in svc_map:
            assert svc_key in per_service, f"KNOWN_DIVERGENT_MOUNTS names unknown service {svc_key!r}"
            if target in per_service[ svc_key ]:
                stale.append( f"{target}  IS NOW PRESENT in  {svc_key}" )
    assert not stale, (
        "stale KNOWN_DIVERGENT_MOUNTS entries — the gap they excused is closed:\n  "
        + "\n  ".join( stale ) + "\n\nDelete these entries."
    )


def test_no_stale_env_exemptions( parsed ):
    per_service = { k: _env_keys( v ) for k, v in parsed.items() }
    stale = []
    for key_name, svc_map in KNOWN_DIVERGENT_ENV.items():
        for svc_key in svc_map:
            assert svc_key in per_service, f"KNOWN_DIVERGENT_ENV names unknown service {svc_key!r}"
            if key_name in per_service[ svc_key ]:
                stale.append( f"{key_name}  IS NOW SET in  {svc_key}" )
    assert not stale, (
        "stale KNOWN_DIVERGENT_ENV entries:\n  " + "\n  ".join( stale ) + "\n\nDelete these entries."
    )


def test_prefix_coverage_helper_both_directions():
    """
    The helper is load-bearing — it is what stops the dev glob from reporting four
    false divergences. Pinned in BOTH directions so it cannot silently widen into
    "everything is covered", which would make test_mount_parity vacuous.
    """
    present = { "/var/external-projects", "/var/lupin/src" }
    assert _covered_by_prefix( "/var/external-projects/lupin", present ) is True
    assert _covered_by_prefix( "/var/lupin/src/conf/keys",     present ) is True
    # NOT covered: a sibling, an unrelated path, and the path itself.
    assert _covered_by_prefix( "/var/external-claude/plans",   present ) is False
    assert _covered_by_prefix( "/cloudsql",                    present ) is False
    assert _covered_by_prefix( "/var/external-projects",       present ) is False
    # A prefix that is not a PATH-SEGMENT boundary must not count.
    assert _covered_by_prefix( "/var/lupin/srcXXX", { "/var/lupin/src" } ) is False


def test_child_coverage_helper_both_directions():
    """
    The predicate that replaced a too-broad exemption. Pinned in BOTH directions:
    it must be TRUE while the explicit child binds exist and FALSE the moment they
    are all removed — that falsifiability is the entire reason it is a predicate
    rather than a KNOWN_DIVERGENT entry.
    """
    with_children = { "/var/external-projects/lupin", "/var/lupin/io" }
    assert _covered_by_children( "/var/external-projects", with_children ) is True

    # Strip the children => the 2026-05-12 regression shape => must go False.
    without = { "/var/lupin/io" }
    assert _covered_by_children( "/var/external-projects", without ) is False

    # The target itself is NOT its own child (else every target self-satisfies).
    assert _covered_by_children( "/var/external-projects", { "/var/external-projects" } ) is False

    # A sibling sharing a name prefix but not a path segment must not count.
    assert _covered_by_children( "/var/external", { "/var/external-projects/lupin" } ) is False


def test_mount_target_parser_handles_both_compose_forms():
    assert _mount_target( "./src:/var/lupin/src" )          == "/var/lupin/src"
    assert _mount_target( "./src:/var/lupin/src:ro" )       == "/var/lupin/src"
    assert _mount_target( { "target": "/cloudsql" } )       == "/cloudsql"
    assert _mount_target( { "source": "x" } )               is None
    assert _mount_target( "just-a-volume-name" )            is None


def test_the_doc_viewer_regression_would_be_caught( parsed ):
    """
    CONTROL — the instrument is proven against the ACTUAL 2026-05-12 regression.
    Simulate cloud-gpu losing its doc-viewer binds and assert the comparator fires.
    A parity test that has never been shown to fail is not evidence.
    """
    per_service = { k: _mounts( v ) for k, v in parsed.items() }
    injured     = { t for t in per_service[ "cloud-gpu" ]
                    if not t.startswith( "/var/external-projects" ) }
    per_service[ "cloud-gpu" ] = injured

    universe = set().union( *per_service.values() )
    found = [
        f"{t} absent from cloud-gpu"
        for t in sorted( universe )
        if t not in injured
        and not _covered_by_prefix( t, injured )
        and not _covered_by_children( t, injured )
        and "cloud-gpu" not in KNOWN_DIVERGENT_MOUNTS.get( t, {} )
    ]
    assert found, "the comparator did NOT fire on the exact regression it exists to catch"
    assert any( "external-projects" in f for f in found )
