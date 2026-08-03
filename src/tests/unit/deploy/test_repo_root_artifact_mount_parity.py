"""
Unit tests for bug b5b6d252 bucket A — the repo-root deploy artifacts the unit
suite asserts about must be MOUNTED into the containers that run it.

THE DEFECT
    src/tests/unit/ contains tests that read the repo's own deploy config —
    docker-compose*.yml, the Dockerfile, .dockerignore, .docview.yml. The
    containers mounted ./src, ./io, ./.git and pytest.ini, but none of those
    repo-ROOT files. So 19 tests passed on the host and failed in-container with
    FileNotFoundError, and the scheduled :8000 merge gate published that as
    "27 failed" — environment noise wearing a test failure's clothes.

    The row's own observation is what makes a static fix insufficient:
    "the count GROWS as file-reading tests are added — test_external_scope_
    mount_parity.py landed 2026-07-25 and contributed 6 of the 27 the very next
    day." A one-time mount fixes today and re-breaks on the next such test.

SO THIS FILE IS A COMPARATOR, NOT A CHECKLIST
    · the DECLARED arm asserts the known artifacts are mounted in BOTH services
    · the DISCOVERED arm scans src/tests/unit/ for references to repo-root
      deploy artifacts and asserts every name it finds is declared AND mounted
    The second arm is the one that survives contact with a growing suite: a new
    test that reads a new repo-root file goes red HERE, at commit time, instead
    of six weeks later inside a scheduled run nobody trusts.

⚠️ NOT COVERED BY THIS FILE — buckets B and C of b5b6d252:
    B (7 tests) the container lacks bq / gcloud / terraform / tmux. No mount
      fixes that; it is image toolchain, folded into row 719962ed. Notably
      test_pilot_ac_instruments is CORRECT to fail there — the instruments
      really are absent — so it must not be silenced.
    C (3 tests) genuine test-harness bugs (lupin-app.ini under a pytest tmpdir).

Venue: :7999 / AI-discretionary. Pure file reads.
"""
import os
import re

import pytest
import yaml

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
COMPOSE_PATH = os.path.join( PROJECT_ROOT, "docker-compose.yml" )
UNIT_TEST_DIR = os.path.join( PROJECT_ROOT, "src/tests/unit" )

# Services that run the unit suite. Both, deliberately: the dev container was
# missing these too, and a parity defect fixed on one side is a parity defect.
SERVICES_RUNNING_UNIT_TESTS = [ "lupin-rest-dev", "lupin-rest-test" ]

# The DECLARED manifest — every path outside ./src that the unit suite reads.
DECLARED_REPO_ROOT_ARTIFACTS = [
    "docker-compose.yml",
    "docker-compose.cloud-gpu.yml",
    "docker-compose.cloud-test.yml",
    "docker",                      # directory: covers docker/**/Dockerfile, claude-config, scripts
    ".dockerignore",
    ".docview.yml",
    ".gitleaks.toml",
    ".stylelintrc.json",
    "alembic.ini",
    "cloud-test.env.example",
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "tsconfig.json",
    "tsconfig.diagnostic.json",
    "tsconfig.nav.json",
]

# ⚠️ THE FIRST VERSION OF THIS FILE GUESSED, AND THE GUESS WAS WRONG.
#
# It declared six artifacts and discovered more by matching filename PATTERNS I
# had thought of (docker-compose*.yml, .dockerignore, .docview.yml). It went
# green. Then the recreated container ran the real tests and
# test_no_hardcoded_gcp_identifiers died on `.gitleaks.toml` — a seventh
# artifact no pattern of mine covered.
#
# Measured properly, that test does not read a LIST at all. It walks
# `git ls-files`, filters to executable surfaces, and READS EVERY ONE:
#     scanned surfaces 2294   missing in container 16
# Sixteen, not six. A hand-picked mount list can never satisfy a whole-repo
# reader, and a comparator built from hand-picked patterns will keep certifying
# it as complete — which is this file's own subject, committed by this file.
#
# So the discovered arm below no longer guesses. It derives the universe from
# the SAME predicate the real test uses, which makes it wrong only if the test
# is wrong.
COVERAGE_PREDICATE_NOTE = "derived from git ls-files + the executable-surface predicate, not from a pattern list"


def _compose():
    with open( COMPOSE_PATH ) as f:
        return yaml.safe_load( f )


def _mounted_targets( service_name ):
    """
    Container-side paths this service mounts.

    Ensures:
        - returns a set of destination paths (the ':'-separated middle field)
        - raises KeyError if the service is absent, rather than returning an
          empty set — "service not found" and "service mounts nothing" have
          different remedies and must not collapse
    """
    svc = _compose()[ "services" ][ service_name ]
    targets = set()
    for vol in svc.get( "volumes", [] ):
        if isinstance( vol, str ) and ":" in vol:
            targets.add( vol.split( ":" )[ 1 ] )
        elif isinstance( vol, dict ) and "target" in vol:
            targets.add( vol[ "target" ] )
    return targets


# ══════════════════════════════════════════════════════════════════════════
# The declared arm
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "service", SERVICES_RUNNING_UNIT_TESTS )
def test_every_declared_artifact_is_mounted( service ):
    targets = _mounted_targets( service )
    missing = [
        a for a in DECLARED_REPO_ROOT_ARTIFACTS
        if f"/var/lupin/{a}" not in targets
    ]
    assert not missing, (
        f"{service} does not mount {missing} — tests reading them will fail "
        f"in-container with FileNotFoundError while passing on the host"
    )


@pytest.mark.parametrize( "service", SERVICES_RUNNING_UNIT_TESTS )
def test_declared_artifacts_are_mounted_read_only( service ):
    """
    The suite only ever reads these. A writable mount would let a test rewrite
    the deploy config it is asserting about — and a test that can edit its own
    oracle is not a test.
    """
    svc = _compose()[ "services" ][ service ]
    writable = []
    for vol in svc.get( "volumes", [] ):
        if not isinstance( vol, str ):
            continue
        parts = vol.split( ":" )
        if len( parts ) >= 2 and parts[ 1 ].replace( "/var/lupin/", "" ) in DECLARED_REPO_ROOT_ARTIFACTS:
            if len( parts ) < 3 or "ro" not in parts[ 2 ]:
                writable.append( vol )
    assert not writable, f"{service} mounts deploy artifacts WRITABLE: {writable}"


def test_the_two_services_agree():
    """
    A parity defect fixed on one container only is still a parity defect — and
    the dev container was missing these too.
    """
    dev  = _mounted_targets( "lupin-rest-dev" )
    test = _mounted_targets( "lupin-rest-test" )
    for artifact in DECLARED_REPO_ROOT_ARTIFACTS:
        target = f"/var/lupin/{artifact}"
        assert ( target in dev ) == ( target in test ), \
            f"{artifact} is mounted in one service but not the other"


# ══════════════════════════════════════════════════════════════════════════
# The discovered arm — the one that survives a growing suite
# ══════════════════════════════════════════════════════════════════════════

def _scanned_surfaces_outside_src():
    """
    Every path test_no_hardcoded_gcp_identifiers actually READS, minus what the
    ./src bind already covers.

    Ensures:
        - returns a sorted list of repo-relative paths
        - asserts the predicate returned something; an empty universe would make
          the comparator vacuously green, which is exactly the failure this file
          committed in its first version
    """
    import importlib.util

    path = os.path.join( PROJECT_ROOT, "src/tests/unit/test_no_hardcoded_gcp_identifiers.py" )
    spec = importlib.util.spec_from_file_location( "_gcp_guard", path )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )

    surfaces = mod.scanned_files()
    assert surfaces, "the guard's own predicate returned NO files — instrument broken, not clean"
    return sorted( f for f in surfaces if not f.startswith( "src/" ) )


def _is_covered( rel_path, mount_targets ):
    """True when rel_path sits at, or under, any mounted target."""
    container_path = f"/var/lupin/{rel_path}"
    if container_path in mount_targets:
        return True
    return any( container_path.startswith( t.rstrip( "/" ) + "/" ) for t in mount_targets )


def test_the_guard_predicate_yields_a_real_universe():
    """
    Instrument check. If scanned_files() ever returns nothing — a moved file, a
    broken git call — the comparator below passes over an empty set and
    certifies mounts it never examined.
    """
    outside_src = _scanned_surfaces_outside_src()
    assert len( outside_src ) >= 10, f"only {len( outside_src )} surfaces outside ./src — predicate broke"
    assert ".gitleaks.toml" in outside_src, \
        "the artifact that exposed the first version's blind spot is no longer in the universe"


@pytest.mark.parametrize( "service", SERVICES_RUNNING_UNIT_TESTS )
def test_every_scanned_surface_outside_src_is_mounted( service ):
    """
    THE COMPARATOR, rebuilt on the guard's OWN predicate.

    The first version matched filename patterns I had thought of, went green,
    and missed `.gitleaks.toml` — which the real test then found in a recreated
    container. Deriving the universe from git ls-files + the executable-surface
    filter makes this wrong only if the guard itself is wrong, instead of wrong
    whenever someone adds a file shape I did not anticipate.
    """
    targets   = _mounted_targets( service )
    unmounted = [ f for f in _scanned_surfaces_outside_src() if not _is_covered( f, targets ) ]
    assert not unmounted, (
        f"{service} does not mount {len( unmounted )} file(s) that "
        f"test_no_hardcoded_gcp_identifiers READS: {unmounted}. "
        f"They raise FileNotFoundError in-container while passing on the host."
    )
