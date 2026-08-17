"""
Fixtures for Rachel's review findings F1, F3 and F5 (2026-08-17).

They live in their own file rather than in test_secret_scan.py because she is editing
that file and its fixture on her branch to close F4, and two people editing one file at
once is how a peer's work gets swept into somebody else's commit.

F1 — MY DEFINITION OF A SECRET HAD DRIFTED FROM THE DOC-VIEWER DETECTOR'S. Three shapes
that detector refuses were invisible here, and it was my own precision heuristics doing
it: a service-account key pasted as a JSON string reads as "template" because it contains
braces, and key material split across list entries reads as "structure". A credential
payload is neither.

F3 — THE WHOLE TEST TREE WAS INVISIBLE to both the scanner and the gate. The reason was
sound (this suite plants fake secrets on purpose) but the rule was far wider than the
reason. It now excludes this scanner's own fixtures by name and nothing else. Tiffany
found a live sandbox project id sitting in test fixtures the same afternoon, so "it is
only a test file" is not a reason to stop looking.

F5 — A NUMERIC VALUE WAS NEVER FILTERED, so a read-window constant named
CREDENTIAL_SNIFF_BYTES was reported as a candidate. Named trade: a purely numeric secret,
a PIN or a numeric account id, is now missed.

Every value below is synthetic.
"""

import sys

import pytest

import cosa.utils.util as cu

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )

import secret_scan


# ── F1: credential payloads the doc-viewer detector blocks and this one used to drop ──
PAYLOAD_SHAPES = [
    ( "service-account key as a JSON string in python",
      "svc.py",
      'google_credentials = "{\\"type\\": \\"service_account\\", \\"private_key\\": '
      '\\"-----BEGIN PRIVATE KEY-----MIIEvQIBADANBgkqhkiG9w0\\"}"\n' ),

    ( "the same blob inside a JSON config file",
      "conf/creds.json",
      '{"type": "service_account", "private_key": "-----BEGIN PRIVATE KEY-----MIIEvQIBADANBgkq"}\n' ),

    ( "key material as a list of lines",
      "conf/creds.json",
      '  "private_key": ["MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw", "ggSjAgEAAoIBAQDX"]\n' ),

    ( "quoted JSON key with an ordinary value (the leading quote used to break the match)",
      "conf/creds.json",
      '  "password": "Xq7vNb2Rt9zLm4w"\n' ),

    ( "control the detector already blocked",
      "svc.py",
      'client_secret = "GOCSPX-1a2b3c4d5e6f7g8h9i"\n' ),
]


@pytest.mark.parametrize( "name,path,text", PAYLOAD_SHAPES,
                          ids=[ c[ 0 ] for c in PAYLOAD_SHAPES ] )
def test_credential_payload_is_not_mistaken_for_a_container( name, path, text ):
    assert secret_scan.scan_text( text, path ), f"BLIND SPOT — payload read as a container: {name}"


# ── F5: a number is not a secret ──────────────────────────────────────────────────
NUMERIC = [
    ( "read-window constant",     "reg.py", "CREDENTIAL_SNIFF_BYTES = 8192\n" ),
    ( "underscore-grouped",       "reg.py", "CREDENTIAL_MAX_SNIFF_BYTES = 1_048_576\n" ),
    ( "float",                    "conf.py", "token_refresh_secret_margin = 0.75\n" ),
    ( "negative",                 "conf.py", "password_attempts_secret = -1\n" ),
]


@pytest.mark.parametrize( "name,path,text", NUMERIC, ids=[ c[ 0 ] for c in NUMERIC ] )
def test_a_number_is_not_a_credential( name, path, text ):
    found = secret_scan.scan_text( text, path )
    assert not found, f"FALSE POSITIVE — numeric value reported: {name} ({found})"


def test_a_long_digit_string_is_still_a_candidate():
    """
    The trade has a limit worth pinning: this filter rejects a NUMERIC LITERAL, not a
    quoted digit string, so an all-digits API id in quotes is still seen. A bare numeric
    PIN is the case we accept losing.
    """
    assert secret_scan.scan_text( 'api_key = "8461930275048213"\n', "svc.py" )


# ── F3: the test tree is scanned again, except this scanner's own planted fixtures ──
def test_the_test_tree_is_visible_to_the_scan():
    assert secret_scan._is_text_path( "src/tests/unit/fixtures/thing.json" )
    assert secret_scan._is_text_path( "src/tests/integration/test_live_thing.py" )
    assert secret_scan._is_text_path( "src/cosa/tests/unit/agents/test_something.py" )


def test_this_scanners_own_planted_fixtures_stay_excluded():
    """Excluded by NAME. Anything wider hides a real credential in a real fixture."""
    assert not secret_scan._is_text_path( "src/tests/unit/test_secret_scan.py" )
    assert not secret_scan._is_text_path( "src/tests/unit/fixtures/secret_scan_last_full_scan.json" )
