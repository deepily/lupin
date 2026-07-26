"""
Unit tests for R2 — `lupin-vm.sh creds-status`, which prints every authority for
the notification API key side by side.

WHY THE VERB EXISTS
    "The notification API key" is FIVE surfaces over TWO independent validators:
        1. src/conf/keys/notification-api-claude-code-dev   (value, comparable)
        2. $LUPIN_API_KEY                                   (value, comparable)
        3. whatever ~/.lupin/config's api_key_file names    (value, comparable)
        4. Secret Manager                                   (value, comparable)
        5. the api_keys bcrypt row in the server's DB       (HASH — exercise only)

    BOTH of 2026-07-25's outages were the same defect at a DIFFERENT validator —
    STT 401 (Secret Manager version eight months stale) and DM
    missing_auth_header (the key file held the dev box's key, unregistered in the
    VM's database). Each surface looked fine alone. Nothing compared them.

THE ASYMMETRY THAT SHAPES THE DESIGN
    Surface 5 is a one-way hash. It can NEVER be compared, only EXERCISED — which
    is why the acceptance probe is the design rather than a shortcut. And the
    probe needs its wrong-key control, because a 200 alone does not prove the key
    was checked; only a 401 on a bad key proves the header is enforced at all.

WHAT THIS FILE TESTS
    The three pure lib helpers the verb is built from, every branch, including
    inputs that make each return non-zero. The verb's own output shape is
    exercised live (host + a deliberately-divergent fixture) rather than here,
    because it reaches curl and gcloud.

Venue: :7999 / AI-discretionary. Pure bash subprocess, tmp files only.
"""
import os
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
LIB_PATH     = os.path.join( PROJECT_ROOT, "src/scripts/lib/preflight-vm-lib.sh" )


def _run( snippet ):
    """
    Source the lib and run a bash snippet.

    Ensures:
        - returns CompletedProcess; `set -u` is ON so an unset-variable bug in
          the lib fails loudly here instead of evaluating to empty
    """
    full = f"set -uo pipefail; source '{LIB_PATH}'; {snippet}"
    return subprocess.run( [ "bash", "-c", full ], capture_output=True, text=True )


# ══════════════════════════════════════════════════════════════════════════
# pfv_secret_fingerprint — a comparable handle that is not the secret
# ══════════════════════════════════════════════════════════════════════════

def test_fingerprint_is_stable_and_discriminates():
    a = _run( "pfv_secret_fingerprint 'hunter2'" ).stdout
    b = _run( "pfv_secret_fingerprint 'hunter2'" ).stdout
    c = _run( "pfv_secret_fingerprint 'hunter3'" ).stdout
    assert a.startswith( "sha256:" )
    assert a == b, "same value must fingerprint identically or comparison is meaningless"
    assert a != c, "different values must differ or the comparator cannot see a divergence"


def test_fingerprint_never_contains_the_secret():
    """The tool exists to be run while someone is confused — i.e. while they are
    most likely to paste its output somewhere."""
    r = _run( "pfv_secret_fingerprint 'ck_live_SUPERSECRET_VALUE'" )
    assert "SUPERSECRET" not in r.stdout
    assert "ck_live" not in r.stdout


def test_empty_value_is_its_own_state_not_a_fingerprint():
    r = _run( "pfv_secret_fingerprint ''" )
    assert r.stdout == "EMPTY"
    assert r.returncode == 2


# ══════════════════════════════════════════════════════════════════════════
# pfv_read_secret_file — four states, never collapsed
#
# The 2026-07-25 outage was a key file that EXISTED and was UNREADABLE (mode
# 600, uid 1001): os.path.exists() said yes and a plain cat printed nothing,
# with no error. A reader returning "" for all three cannot tell the operator
# which of three different things to do.
# ══════════════════════════════════════════════════════════════════════════

def test_readable_file_yields_its_contents( tmp_path ):
    f = tmp_path / "k"
    f.write_text( "ck_live_abc\n" )
    r = _run( f"pfv_read_secret_file '{f}'" )
    assert r.returncode == 0
    assert r.stdout == "ck_live_abc"


def test_absent_unreadable_and_empty_are_three_distinct_answers( tmp_path ):
    missing = tmp_path / "nope"
    empty   = tmp_path / "empty";  empty.write_text( "" )
    noperm  = tmp_path / "noperm"; noperm.write_text( "x" ); os.chmod( noperm, 0o000 )
    try:
        r_missing = _run( f"pfv_read_secret_file '{missing}'" )
        r_empty   = _run( f"pfv_read_secret_file '{empty}'" )
        r_noperm  = _run( f"pfv_read_secret_file '{noperm}'" )
    finally:
        os.chmod( noperm, 0o600 )

    assert ( r_missing.stdout, r_missing.returncode ) == ( "ABSENT",     1 )
    assert ( r_noperm.stdout,  r_noperm.returncode  ) == ( "UNREADABLE", 2 )
    assert ( r_empty.stdout,   r_empty.returncode   ) == ( "EMPTY",      3 )
    # And the three must not merely differ in text — the RETURN CODES must too,
    # since a caller branching on rc is the whole point.
    assert len( { r_missing.returncode, r_noperm.returncode, r_empty.returncode } ) == 3


# ══════════════════════════════════════════════════════════════════════════
# pfv_fingerprints_agree — and its refusal to claim agreement from one value
# ══════════════════════════════════════════════════════════════════════════

def _fp( value ):
    return _run( f"pfv_secret_fingerprint '{value}'" ).stdout


def test_matching_surfaces_agree():
    a, b = _fp( "same" ), _fp( "same" )
    assert _run( f"pfv_fingerprints_agree '{a}' '{b}'" ).returncode == 0


def test_diverging_surfaces_are_detected():
    """THE DEFECT the verb exists to surface — both 07-25 outages were this."""
    a, b = _fp( "dev-box-key" ), _fp( "vm-key" )
    assert _run( f"pfv_fingerprints_agree '{a}' '{b}'" ).returncode == 1


@pytest.mark.parametrize( "args,label", [
    ( "",                          "no surfaces at all" ),
    ( "'ABSENT' 'UNREADABLE'",     "only non-values" ),
] )
def test_fewer_than_two_values_is_not_agreement( args, label ):
    """
    A lone surface cannot corroborate itself. Reporting "agrees" from one value
    is how a single stale key reads as verified — which is the shape of the
    Secret Manager half of the 07-25 pair.
    """
    assert _run( f"pfv_fingerprints_agree {args}".strip() ).returncode == 2, label


def test_one_value_plus_absent_surfaces_is_still_not_agreement():
    a = _fp( "only-one" )
    assert _run( f"pfv_fingerprints_agree '{a}' 'ABSENT' 'UNAVAILABLE'" ).returncode == 2


def test_absent_surfaces_do_not_manufacture_a_disagreement():
    """
    An absent surface is a fact about COVERAGE, not a claim about the value.
    Counting it as a mismatch would make the verb cry wolf on every host without
    gcloud — and a comparator that cries wolf gets ignored, which is the failure
    mode this whole class of work exists to prevent.
    """
    a, b = _fp( "same" ), _fp( "same" )
    assert _run( f"pfv_fingerprints_agree '{a}' 'ABSENT' '{b}' 'UNAVAILABLE'" ).returncode == 0
