"""
Unit tests for R4 — LUPIN_ENV and config_block_id must name the SAME environment.

THE DEFECT THIS CLOSES
    Two knobs with similar names, set side by side in every compose file,
    choosing COUPLED facts:

        LUPIN_ENV        chooses the DATABASE. cloud-test.yml's own comment
                         says it is "never inferred".
        config_block_id  chooses the INI BLOCK (inside LUPIN_CONFIG_MGR_CLI_ARGS).

    Nothing compared them. A disagreement crashes nothing — the app simply
    reads one environment's configuration while addressing another's database.

TWO HALVES, DELIBERATELY
    · This file is the STATIC half: it reads the compose files on disk, so a
      divergence is caught at commit time, inside the gate, by everyone.
    · preflight-vm.sh check C4b is the RUNTIME half: it reads the values out of
      the RUNNING container. Neither subsumes the other — a --force-recreate
      with a stale env-file, or a hand-started container, diverges from the file
      that is supposed to describe it, and the static test cannot see that.

WHY A COMPARATOR AND NOT AN INSPECTION
    All four shipped service blocks agree today. That is a coincidence nobody is
    holding in place, not a property — which is precisely why the assertion has
    to be mechanical. test_shipped_compose_files_all_agree would pass against a
    world with no check at all, so the branch tests below carry the weight, and
    the shipped-file test carries an explicit "did I actually parse anything"
    arm so an empty scan cannot masquerade as a clean one.

Venue: :7999 / AI-discretionary. Pure file reads + bash subprocess. No Docker,
no network, no persistent state.
"""
import os
import re
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
LIB_PATH     = os.path.join( PROJECT_ROOT, "src/scripts/lib/preflight-vm-lib.sh" )

COMPOSE_FILES = [
    "docker-compose.yml",
    "docker-compose.cloud-gpu.yml",
    "docker-compose.cloud-test.yml",
]

# Matches `LUPIN_ENV: testing` and `config_block_id=Lupin:+Testing-GCS`.
RE_LUPIN_ENV = re.compile( r"^\s*LUPIN_ENV:\s*(\S+)\s*$" )
RE_BLOCK_ID  = re.compile( r"config_block_id=(\S+?)[\"'\s]*$" )


def _run_lib( snippet ):
    """
    Source the preflight lib and run a bash snippet.

    Ensures:
        - returns the CompletedProcess; `set -u` is ON so an unset-variable bug
          in the lib fails loudly here rather than evaluating to empty
    """
    full = f"set -uo pipefail; source '{LIB_PATH}'; {snippet}"
    return subprocess.run( [ "bash", "-c", full ], capture_output=True, text=True )


def _agree_rc( lupin_env, block_id ):
    r = _run_lib( f"pfv_env_block_agree '{lupin_env}' '{block_id}'; echo -n $?" )
    assert r.returncode == 0, r.stderr
    return int( r.stdout.strip() )


# ══════════════════════════════════════════════════════════════════════════
# pfv_config_block_id — extraction
# ══════════════════════════════════════════════════════════════════════════

def test_block_id_extracted_from_a_full_cli_args_string():
    args = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing-GCS"
    r = _run_lib( f"pfv_config_block_id '{args}'" )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "Lupin:+Testing-GCS"


def test_absent_block_id_returns_2_not_empty_success():
    """ABSENT and EMPTY must not collapse — they have different remedies."""
    r = _run_lib( "pfv_config_block_id 'config_path=/a splainer_path=/b'" )
    assert r.returncode == 2
    assert r.stdout == ""


# ══════════════════════════════════════════════════════════════════════════
# pfv_env_block_agree — every branch, including one that must return non-zero
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "lupin_env,block_id", [
    ( "testing",     "Lupin:+Testing-GCS" ),   # variant suffix ignored on purpose
    ( "testing",     "Lupin:+Testing"     ),
    ( "development", "Lupin:+Development" ),
    ( "production",  "Lupin:+Production"  ),
    ( "TESTING",     "Lupin:+testing"     ),   # comparison is case-insensitive
] )
def test_agreeing_pairs_return_0( lupin_env, block_id ):
    assert _agree_rc( lupin_env, block_id ) == 0


@pytest.mark.parametrize( "lupin_env,block_id", [
    ( "testing",     "Lupin:+Development" ),
    ( "development", "Lupin:+Testing-GCS" ),
    ( "production",  "Lupin:+Testing"     ),
] )
def test_disagreeing_pairs_return_1( lupin_env, block_id ):
    assert _agree_rc( lupin_env, block_id ) == 1


@pytest.mark.parametrize( "lupin_env,block_id", [
    ( "",        "Lupin:+Testing"  ),   # env missing
    ( "testing", ""                ),   # block id missing
    ( "testing", "Weird:+Testing"  ),   # unreadable shape
    ( "testing", "Lupin:+"         ),   # prefix present, nothing after it
] )
def test_undeterminable_pairs_return_2_never_0( lupin_env, block_id ):
    """
    An unreadable input must NOT be reported as agreement. A comparator that
    answers "fine" whenever it cannot parse is quietest exactly when something
    has changed underneath it — which is the failure this whole check exists to
    prevent, reintroduced inside the cure.
    """
    assert _agree_rc( lupin_env, block_id ) == 2


def test_variant_suffix_is_ignored_but_the_stem_is_not():
    """
    The rule ignores everything after the first '-'. Assert BOTH halves: that a
    variant does not cry wolf, AND that the check still fires on a stem
    mismatch carrying the same variant — otherwise "ignore the suffix" could
    have been implemented as "ignore the whole thing".
    """
    assert _agree_rc( "testing",     "Lupin:+Testing-GCS" ) == 0
    assert _agree_rc( "development", "Lupin:+Testing-GCS" ) == 1


# ══════════════════════════════════════════════════════════════════════════
# The shipped compose files
# ══════════════════════════════════════════════════════════════════════════

def _scan_compose_pairs():
    """
    Pair each `LUPIN_ENV:` line with the `config_block_id=` that follows it in
    the same service block.

    Ensures:
        - returns a list of ( file, line_no, lupin_env, block_id ) tuples
        - a LUPIN_ENV with no following block id yields block_id None, so the
          caller can fail on it rather than silently skipping the pair
    """
    pairs = []
    for fname in COMPOSE_FILES:
        path = os.path.join( PROJECT_ROOT, fname )
        if not os.path.exists( path ):
            continue
        lines = open( path ).read().split( "\n" )
        for i, line in enumerate( lines ):
            m = RE_LUPIN_ENV.match( line )
            if not m:
                continue
            block_id = None
            # The two knobs sit inside one `environment:` block; scan forward a
            # bounded window rather than to EOF so a later service's block id
            # cannot be mis-paired with this service's LUPIN_ENV.
            for follow in lines[ i : i + 15 ]:
                b = RE_BLOCK_ID.search( follow )
                if b:
                    block_id = b.group( 1 )
                    break
            pairs.append( ( fname, i + 1, m.group( 1 ), block_id ) )
    return pairs


def test_scan_finds_every_known_pair():
    """
    Instrument check. If the regexes drift with the compose format, the
    agreement test below would scan nothing and pass — a green that means the
    parser broke, not that the config is right.
    """
    pairs = _scan_compose_pairs()
    assert len( pairs ) >= 4, f"expected >=4 LUPIN_ENV blocks, scanned {len( pairs )}: {pairs}"
    files_seen = { p[ 0 ] for p in pairs }
    assert "docker-compose.cloud-gpu.yml" in files_seen
    assert "docker-compose.yml" in files_seen


def test_shipped_compose_files_all_agree():
    pairs = _scan_compose_pairs()
    assert pairs, "no LUPIN_ENV/config_block_id pairs scanned — see test_scan_finds_every_known_pair"

    problems = []
    for fname, line_no, lupin_env, block_id in pairs:
        if block_id is None:
            problems.append( f"{fname}:{line_no} LUPIN_ENV={lupin_env} has NO config_block_id in its block" )
            continue
        rc = _agree_rc( lupin_env, block_id )
        if rc != 0:
            verdict = "DISAGREE" if rc == 1 else "UNDETERMINABLE"
            problems.append( f"{fname}:{line_no} {verdict}: LUPIN_ENV={lupin_env} vs config_block_id={block_id}" )
    assert not problems, "LUPIN_ENV / config_block_id mismatches:\n  " + "\n  ".join( problems )
