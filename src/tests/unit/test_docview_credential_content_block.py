"""
Bug afdc938f — the doc viewer served service-account keys.

THE SHAPE OF THE MISS, because it is the whole reason this file is content-driven:
`023e72cb` fixed `\\bcredentials\\b` failing on `application_default_credentials.json`
(an underscore is a word character). That fix was correct and it was scoped to the
one FILENAME that had been caught, not to the credential FAMILY. Tiffany then
measured seven more still served. Patching a family by literal name is a fix that
has to be applied again every time someone invents a name — so the detector here
keys on the CONTENT, and the names are kept only as a cheap first pass.

THE FOUR CONSTRAINTS this is built to (Tiffany, adopted):
  1. Key on the FIELDS, not the filename.
  2. FAIL CLOSED — unreadable, unparseable, truncated, wrong encoding all BLOCK. A
     content check that serves the file it could not read looks like protection and
     is not.
  3. Do NOT gate on the `.json` extension, or `key.txt` walks straight through and
     the filename dependency is back one layer down.
  4. BOUND the read.

Venue: :7999-eligible — pure predicate + tmp_path, no server, no network.
"""

import json
import os

import pytest

from cosa.rest.routers._scope_registry import (
    _is_secrets_path,
    _prefix_looks_like_credential,
    is_credential_file,
    CREDENTIAL_SNIFF_BYTES,
)


SERVICE_ACCOUNT_KEY = {
    "type"                        : "service_account",
    "project_id"                  : "hello-world-foo-423219",
    "private_key_id"              : "0123456789abcdef0123456789abcdef01234567",
    "private_key"                 : "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADAN\n-----END PRIVATE KEY-----\n",
    "client_email"                : "svc@hello-world-foo-423219.iam.gserviceaccount.com",
    "client_id"                   : "123456789012345678901",
    "token_uri"                   : "https://oauth2.googleapis.com/token",
}

ADC_USER_CREDENTIAL = {
    "client_id"     : "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com",
    "client_secret" : "d-FL95Q19q7MQmFpd7hHD0Ty",
    "refresh_token" : "1//0abcdefghijklmnopqrstuvwxyz",
    "type"          : "authorized_user",
}

# The seven Tiffany measured as SERVED, plus the four that already blocked.
SEVEN_THAT_WERE_SERVED = [
    "service-account.json",
    "sa_key.json",
    "service_account.json",
    "svc-acct.json",
    "gcp-sa.json",
    "token.json",
    "keyfile.json",
]

FOUR_THAT_ALREADY_BLOCKED = [
    "client_secret_123.json",
    "id_rsa",
    "private_key.pem",
    "application_default_credentials.json",
]


# ─────────────────────────────────────────────────────────────────────────────
# AXIS 1 — CONTENT. The detector that does not care what the file is called.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "filename", SEVEN_THAT_WERE_SERVED + FOUR_THAT_ALREADY_BLOCKED )
def test_a_service_account_key_is_refused_under_every_name( tmp_path, filename ):
    """
    THE HEADLINE. Every one of the seven names that served today is refused when the
    file's CONTENT is a service-account key — and so are the four that already
    blocked, so the fix does not regress them.
    """
    path = tmp_path / filename
    path.write_text( json.dumps( SERVICE_ACCOUNT_KEY, indent=2 ) )

    assert is_credential_file( str( path ) ), f"{filename} served a service-account key"


@pytest.mark.parametrize( "filename", SEVEN_THAT_WERE_SERVED )
def test_an_adc_user_credential_is_refused_under_every_name( tmp_path, filename ):
    """The other credential shape: refresh_token + client_secret, no private_key."""
    path = tmp_path / filename
    path.write_text( json.dumps( ADC_USER_CREDENTIAL ) )

    assert is_credential_file( str( path ) )


def test_a_key_in_a_txt_file_is_refused( tmp_path ):
    """
    Constraint 3, asserted. Gating the content check on `.json` would let this
    through and re-introduce the filename dependency one layer down.
    """
    path = tmp_path / "key.txt"
    path.write_text( json.dumps( SERVICE_ACCOUNT_KEY ) )

    assert is_credential_file( str( path ) )


def test_a_credential_under_a_wholly_innocent_name_is_refused( tmp_path ):
    """The case nobody predicts — which is the case content-checking exists for."""
    for innocent in ( "notes.md", "config.yaml", "readme.txt", "data.json" ):
        path = tmp_path / innocent
        path.write_text( json.dumps( SERVICE_ACCOUNT_KEY ) )
        assert is_credential_file( str( path ) ), f"{innocent} served a key"


def test_a_bare_pem_private_key_is_refused( tmp_path ):
    """No JSON at all — the PEM header is decisive and needs no parsing."""
    for header in ( "-----BEGIN PRIVATE KEY-----",
                    "-----BEGIN RSA PRIVATE KEY-----",
                    "-----BEGIN OPENSSH PRIVATE KEY-----",
                    "-----BEGIN EC PRIVATE KEY-----",
                    "-----BEGIN ENCRYPTED PRIVATE KEY-----" ):
        path = tmp_path / "harmless.md"
        path.write_text( f"# notes\n\n{header}\nMIIEvQIBADAN\n" )
        assert is_credential_file( str( path ) ), f"{header} served"


# ─────────────────────────────────────────────────────────────────────────────
# FAIL CLOSED — constraint 2
# ─────────────────────────────────────────────────────────────────────────────

def test_an_unreadable_file_BLOCKS( tmp_path ):
    """
    A check that serves what it could not read is worse than no check: it looks like
    protection. Chmod 000 so the open genuinely fails.
    """
    path = tmp_path / "unreadable.json"
    path.write_text( json.dumps( SERVICE_ACCOUNT_KEY ) )
    os.chmod( path, 0o000 )

    try:
        if os.access( str( path ), os.R_OK ):
            pytest.skip( "running as root — the permission bit cannot be exercised" )
        assert is_credential_file( str( path ) ), "an unreadable file must BLOCK, never serve"
    finally:
        os.chmod( path, 0o644 )


def test_a_missing_file_BLOCKS( tmp_path ):
    assert is_credential_file( str( tmp_path / "does-not-exist.json" ) )


def test_a_non_utf8_file_BLOCKS( tmp_path ):
    """Wrong encoding is "I could not tell", which must never mean "so I served it"."""
    path = tmp_path / "binary.json"
    path.write_bytes( b"\xff\xfe\x00\x01 not utf-8 at all \xc3\x28" )

    assert is_credential_file( str( path ) )


SA_KEY_NO_PEM = {
    "type"           : "service_account",
    "project_id"     : "some-project",
    "private_key_id" : "0123456789abcdef",
    # base64 body with NO PEM header — so the PEM branch cannot do the work here.
    "private_key"    : "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ",
    "client_email"   : "svc@some-project.iam.gserviceaccount.com",
}


@pytest.mark.parametrize( "payload,label", [
    ( ADC_USER_CREDENTIAL, "ADC user credential" ),
    ( SA_KEY_NO_PEM,       "service-account key with no PEM header" ),
    ( SERVICE_ACCOUNT_KEY, "service-account key with a PEM header" ),
] )
def test_a_BOM_prefixed_credential_BLOCKS( tmp_path, payload, label ):
    """
    THE BYPASS I INTRODUCED, found by Tiffany. A UTF-8 byte-order mark read under
    encoding="utf-8" arrives as a literal \\ufeff, and it is NOT whitespace — so
    `lstrip()` leaves it. That defeated both branches at once: json.loads raised on
    the leading mark, and the `startswith("{")` narrowing I added for the prose
    false-positive then concluded "this is prose, serve it".

    MEASURED before the fix: the first two payloads here were SERVED. The third
    blocked anyway, because its PEM header fires before any parsing — which is
    exactly why the hole hid, and why the table now covers the no-PEM shapes.
    """
    path = tmp_path / "creds.json"
    path.write_text( json.dumps( payload ), encoding="utf-8-sig" )

    assert path.read_bytes().startswith( b"\xef\xbb\xbf" ), "fixture must actually carry a BOM"
    assert is_credential_file( str( path ) ), f"BOM-prefixed {label} was SERVED"


def test_a_BOM_does_not_start_a_false_positive( tmp_path ):
    """Stripping the BOM must not make ordinary BOM'd documents look like keys."""
    path = tmp_path / "notes.md"
    path.write_text( "# Notes\n\nOrdinary document.\n", encoding="utf-8-sig" )
    assert not is_credential_file( str( path ) )


@pytest.mark.parametrize( "lead", [ "", " ", "\n", "\t", "\r\n  ", "﻿", "﻿\n  " ] )
def test_leading_whitespace_and_marks_do_not_smuggle_a_credential( lead ):
    """
    The narrowing keys on the opening brace, so anything that can sit BEFORE that
    brace is a candidate bypass. Whitespace was already handled by lstrip(); the BOM
    was not, and is the one that got through.
    """
    assert _prefix_looks_like_credential( lead + json.dumps( ADC_USER_CREDENTIAL ) )


def test_a_truncated_key_still_BLOCKS():
    """
    The bounded read must not become an escape hatch: a key larger than the sniff
    window arrives here as unparseable JSON, and a key does not become safe because
    the read stopped early.
    """
    truncated = json.dumps( SERVICE_ACCOUNT_KEY )[ : 120 ]
    assert "private_key" in truncated or "service_account" in truncated
    assert _prefix_looks_like_credential( truncated )


def test_a_key_beyond_the_sniff_window_still_BLOCKS( tmp_path ):
    """A real file padded past the window — the signature is still in the prefix."""
    padded = dict( SERVICE_ACCOUNT_KEY )
    padded[ "padding" ] = "x" * ( CREDENTIAL_SNIFF_BYTES * 2 )
    path = tmp_path / "big.json"
    path.write_text( json.dumps( padded ) )

    assert is_credential_file( str( path ) )


# ─────────────────────────────────────────────────────────────────────────────
# NO FALSE POSITIVES — the reason content beats a name rule in BOTH directions
# ─────────────────────────────────────────────────────────────────────────────

def test_a_tokenizer_named_token_json_is_STILL_SERVED( tmp_path ):
    """
    The case a name-only blocklist has to get wrong. `token.json` is a legitimate
    tokenizer file in ML repos; it carries no key material, so it is served — while a
    credential under the same name is refused (asserted above).
    """
    path = tmp_path / "token.json"
    path.write_text( json.dumps( {
        "version" : "1.0",
        "model"   : { "type": "BPE", "vocab": { "hello": 1, "world": 2 } },
    } ) )

    assert not is_credential_file( str( path ) ), "a tokenizer is a document, not a key"


def test_ordinary_documents_are_served( tmp_path ):
    for name, body in (
        ( "notes.md",     "# Notes\n\nNothing secret here.\n" ),
        ( "config.yaml",  "debug: true\nport: 7999\n" ),
        ( "data.json",    json.dumps( { "rows": [ 1, 2, 3 ], "type": "report" } ) ),
        ( "empty.txt",    "" ),
    ):
        path = tmp_path / name
        path.write_text( body )
        assert not is_credential_file( str( path ) ), f"{name} was wrongly refused"


def test_a_json_type_field_that_is_not_a_credential_type_is_served( tmp_path ):
    """`"type": "report"` must not trip the type check."""
    path = tmp_path / "thing.json"
    path.write_text( json.dumps( { "type": "report", "rows": 3 } ) )
    assert not is_credential_file( str( path ) )


def test_prose_mentioning_a_credential_field_is_served( tmp_path ):
    """
    Documentation ABOUT credentials is a document. It is not JSON, carries no PEM
    header, and must not be refused — this file itself would otherwise be blocked.
    """
    path = tmp_path / "guide.md"
    path.write_text(
        "# Auth guide\n\nA service-account key carries a private_key field and\n"
        "`\"type\": \"service_account\"`. Never commit one.\n"
    )
    assert not is_credential_file( str( path ) )


# ─────────────────────────────────────────────────────────────────────────────
# AXIS 2 — NAMES. Kept as the cheap first pass, generalised not enumerated.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "filename", [
    "service-account.json", "service_account.json", "sa_key.json",
    "svc-acct.json", "gcp-sa.json",
] )
def test_the_service_account_name_family_is_blocked_by_name_too( filename ):
    """Belt and suspenders: content is the fix, names still catch the careless case."""
    assert _is_secrets_path( filename ), f"{filename} passed the name blocklist"


@pytest.mark.parametrize( "filename", FOUR_THAT_ALREADY_BLOCKED )
def test_the_previously_blocked_names_still_block( filename ):
    """No regression on what 023e72cb and its predecessors already caught."""
    assert _is_secrets_path( filename )


@pytest.mark.parametrize( "filename", [
    "secretive_methods.py", "credentialism.txt", "key_values.txt", "pem-helper.py",
    "tokenizer.json", "token.json", "keyfile.json",
] )
def test_ambiguous_names_are_NOT_blocked_by_name( filename ):
    """
    `token.json` and `keyfile.json` are deliberately absent from the name patterns:
    blocking them by name would refuse legitimate documents. Content decides them,
    and gets both directions right.
    """
    assert not _is_secrets_path( filename ), f"{filename} was blocked on its name alone"


def test_a_service_account_key_in_a_subdirectory_is_blocked_by_name():
    assert _is_secrets_path( "deploy/keys/service-account.json" )
