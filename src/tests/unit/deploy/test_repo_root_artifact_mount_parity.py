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

# The DECLARED manifest — repo-root artifacts the unit suite reads. Adding a
# test that reads a new one means adding it here AND mounting it; the discovered
# arm below enforces that pairing rather than trusting anyone to remember.
DECLARED_REPO_ROOT_ARTIFACTS = [
    "docker-compose.yml",
    "docker-compose.cloud-gpu.yml",
    "docker-compose.cloud-test.yml",
    "docker/lupin/Dockerfile",
    ".dockerignore",
    ".docview.yml",
]

# Filenames that are repo-root deploy artifacts when referenced by a test. Kept
# narrow on purpose: a broad pattern would sweep up unrelated string literals
# and turn this comparator into a nuisance, which is how comparators get deleted.
DISCOVERY_PATTERNS = [
    re.compile( r"\bdocker-compose[A-Za-z0-9._-]*\.yml\b" ),
    re.compile( r"\b\.dockerignore\b" ),
    re.compile( r"\b\.docview\.yml\b" ),
]


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

def _discover_referenced_artifacts():
    """
    Scan the unit-test tree for references to repo-root deploy artifacts.

    Ensures:
        - returns a set of filenames (basenames as written in the source)
        - skips this file, whose DECLARED list would otherwise match itself and
          make the comparison circular
    """
    found = set()
    for dirpath, _dirnames, filenames in os.walk( UNIT_TEST_DIR ):
        if "__pycache__" in dirpath:
            continue
        for fn in filenames:
            if not fn.endswith( ".py" ) or fn == os.path.basename( __file__ ):
                continue
            text = open( os.path.join( dirpath, fn ), errors="ignore" ).read()
            for pat in DISCOVERY_PATTERNS:
                found.update( pat.findall( text ) )
    return found


def test_discovery_actually_finds_something():
    """
    Instrument check. If the patterns drift, the comparator below scans nothing
    and passes — a green meaning the scanner broke, not that the mounts are
    complete. This is the arm b5b6d252's own history argues for: its count grew
    the day after it was filed.
    """
    found = _discover_referenced_artifacts()
    assert len( found ) >= 3, f"scan found only {found} — patterns have drifted"
    assert "docker-compose.yml" in found


def test_every_discovered_artifact_is_declared_and_mounted():
    """
    THE COMPARATOR. A new test that reads a new repo-root deploy artifact fails
    HERE, at commit time, instead of six weeks later inside a scheduled run.
    """
    declared_basenames = { os.path.basename( a ) for a in DECLARED_REPO_ROOT_ARTIFACTS }
    undeclared = sorted( _discover_referenced_artifacts() - declared_basenames )
    assert not undeclared, (
        f"unit tests reference repo-root artifacts that are neither declared "
        f"nor mounted: {undeclared}. Add them to DECLARED_REPO_ROOT_ARTIFACTS "
        f"and mount them read-only in both services in docker-compose.yml."
    )
