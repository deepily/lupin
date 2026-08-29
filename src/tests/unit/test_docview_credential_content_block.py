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
    _credential_field_carries_secret_material,
    _decode_json_unicode_escapes,
    _is_secrets_path,
    _json_carried_in_a_string,
    _object_declares_a_credential,
    _opens_a_json_container,
    _parsed_value_carries_a_credential,
    _prefix_looks_like_credential,
    credential_verdict,
    _strip_leadin_noise,
    _the_window_may_be_hiding_the_signature,
    _value_is_secret_material,
    is_credential_file,
    CREDENTIAL_MAX_NESTED_PARSES,
    CREDENTIAL_MAX_SNIFF_BYTES,
    CREDENTIAL_SNIFF_BYTES,
)


SERVICE_ACCOUNT_KEY = {
    "type"                        : "service_account",
    "project_id"                  : "not-a-real-project-000000",
    "private_key_id"              : "0123456789abcdef0123456789abcdef01234567",
    "private_key"                 : "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADAN\n-----END PRIVATE KEY-----\n",
    "client_email"                : "svc@not-a-real-project-000000.iam.gserviceaccount.com",
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


@pytest.mark.parametrize( "lead", [
    "",
    " ", "\n", "\t", "\r\n  ",
    # mark FIRST — the direction the position-0 strip handled
    "﻿", "﻿\n  ", "﻿﻿",
    # 🔴 AMENDED (Tiffany, second review): mark AFTER whitespace. Every mixed case
    # above puts the mark first, which is exactly the direction the fix covered — so
    # this table was green at ff6c9e46 while eight shapes were still SERVING. A table
    # that only walks the passing direction is not a table.
    " ﻿", "\n﻿", "\t﻿", "\r\n  ﻿", "﻿ ﻿",
    # a non-BOM invisible: the strip must close the CLASS, not one codepoint
    "​", "⁠", "‎", " ",
] )
def test_leading_whitespace_and_marks_do_not_smuggle_a_credential( lead ):
    """
    The narrowing keys on the opening brace, so anything that can sit BEFORE that
    brace is a candidate bypass — in ANY ORDER, and not only the byte-order mark.
    Whitespace was handled by lstrip(); the mark was added at position 0; neither
    covered whitespace-then-mark or the other invisible format characters.
    """
    assert _prefix_looks_like_credential( lead + json.dumps( ADC_USER_CREDENTIAL ) )


@pytest.mark.parametrize( "lead,lead_label", [
    ( " ﻿",   "space then BOM" ),
    ( "\n﻿", "newline then BOM" ),
    ( "\t﻿", "tab then BOM" ),
    ( "​",   "zero-width space" ),
] )
@pytest.mark.parametrize( "payload,payload_label", [
    ( ADC_USER_CREDENTIAL, "ADC user credential" ),
    ( SA_KEY_NO_PEM,       "service-account key with no PEM header" ),
] )
def test_an_invisible_leadin_does_not_smuggle_a_credential_THROUGH_THE_FILE_PATH(
    tmp_path, lead, lead_label, payload, payload_label
):
    """
    THE EIGHT SHAPES STILL SERVING AT ff6c9e46, driven end-to-end through
    is_credential_file rather than the decision helper, because that is the surface
    the doc viewer actually calls.

    MEASURED at ff6c9e46: all eight SERVED a complete valid credential. The
    position-0 mark strip could not see them — a space, tab or newline in front of
    the mark shielded it, and U+200B was never named at all.
    """
    path = tmp_path / "creds.json"
    path.write_text( lead + json.dumps( payload ), encoding="utf-8" )

    assert is_credential_file( str( path ) ), \
        f"{lead_label} + {payload_label} was SERVED"


def test_stripping_invisible_leadins_does_not_buy_a_false_positive( tmp_path ):
    """
    Closing the class must not start blocking documents. A doc that opens with an
    invisible character and TALKS ABOUT credentials is still a document.
    """
    path = tmp_path / "notes.md"
    path.write_text(
        "​# Auth notes\n\nHow we rotate a refresh_token and a client_secret.\n",
        encoding="utf-8",
    )
    assert not is_credential_file( str( path ) )


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


# ─────────────────────────────────────────────────────────────────────────────
# AXIS 3 — DEPTH. Bug 2d57a998: the check read the TOP LEVEL of the parsed
# object only, and six shapes carrying real credential material walked through.
#
# WHY THE EARLIER TABLES COULD NOT REACH THIS: both of them varied what sits in
# FRONT of the payload (whitespace, BOM, other invisible marks) and held the
# payload itself at a flat top-level object. A top-level-only check fails on
# NESTED payloads, so no number of lead-ins can find it. The lead-in fix above
# is sound — 15 attacks against it all blocked — and it says nothing about depth.
#
# The first shape is the one that matters most: it is not a synthetic nesting,
# it is the file the GCP console hands you when you create an OAuth client, and
# it is committed by accident under exactly that name.
# ─────────────────────────────────────────────────────────────────────────────

# The client_secret_<...>.json download, in the shape the console actually emits:
# every field one level down under "installed", and no "type" field at all.
GCP_CONSOLE_CLIENT_SECRET_INSTALLED = {
    "installed" : {
        "client_id"                   : "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com",
        "project_id"                  : "not-a-real-project-000000",
        "auth_uri"                    : "https://accounts.google.com/o/oauth2/auth",
        "token_uri"                   : "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url" : "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret"               : "GOCSPX-9dQ2mVn4rTb7xLpKs0WyZaEuHc",
        "redirect_uris"               : [ "http://localhost" ],
    }
}

# The web-application variant of the same download.
GCP_CONSOLE_CLIENT_SECRET_WEB = {
    "web" : {
        "client_id"                   : "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com",
        "project_id"                  : "not-a-real-project-000000",
        "auth_uri"                    : "https://accounts.google.com/o/oauth2/auth",
        "token_uri"                   : "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url" : "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret"               : "GOCSPX-9dQ2mVn4rTb7xLpKs0WyZaEuHc",
        "javascript_origins"          : [ "http://localhost:7999" ],
    }
}


def _adc_with_the_signature_past_the_first_window():
    """A real ADC behind one big leading field, so the signature sits past 8192."""
    padded = { "notes" : "x" * ( CREDENTIAL_SNIFF_BYTES * 2 ) }
    padded.update( ADC_USER_CREDENTIAL )
    return json.dumps( padded )


# Each entry is one of the six shapes Clayton measured as SERVED, named as he
# named it. Fixed together, not one at a time: 1-4 are the depth-and-container
# hole, 5-6 are the truncated branch reading a bounded window of raw text.
SIX_SHAPES_THAT_STILL_SERVED = [
    ( "1 GCP console client_secret json, fields under 'installed'",
      json.dumps( GCP_CONSOLE_CLIENT_SECRET_INSTALLED, indent=2 ) ),
    ( "2 the same download, 'web' variant",
      json.dumps( GCP_CONSOLE_CLIENT_SECRET_WEB, indent=2 ) ),
    ( "3 service-account key nested under a config wrapper, no PEM header",
      json.dumps( { "gcp" : SA_KEY_NO_PEM } ) ),
    ( "4 a credential inside a JSON array",
      json.dumps( [ ADC_USER_CREDENTIAL ] ) ),
    ( "5 an ADC whose signature sits past the first sniff window",
      _adc_with_the_signature_past_the_first_window() ),
    ( "6 a truncated object whose key is spelled with JSON \\u escapes",
      '{"\\u0072efresh_token": "1//0abcdefghijklmnop", "client_id": "764086051850-6qr4p' ),
]


@pytest.mark.parametrize( "label,body", SIX_SHAPES_THAT_STILL_SERVED,
                          ids=[ entry[ 0 ][ : 1 ] for entry in SIX_SHAPES_THAT_STILL_SERVED ] )
def test_the_six_shapes_that_still_served_are_all_REFUSED( tmp_path, label, body ):
    """
    THE HEADLINE for this bug. All six measured SERVED before the depth fix, on
    this exact fixture set, and all six must refuse now.
    """
    path = tmp_path / "fixture.json"
    path.write_text( body, encoding="utf-8" )

    assert is_credential_file( str( path ) ), f"shape SERVED a credential: {label}"


def test_the_gcp_console_download_is_refused_under_its_real_name( tmp_path ):
    """
    The name the console gives it, so the fixture is the whole real case: the
    file as downloaded, under the filename it downloads as.
    """
    path = tmp_path / "client_secret_764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com.json"
    path.write_text( json.dumps( GCP_CONSOLE_CLIENT_SECRET_INSTALLED, indent=2 ), encoding="utf-8" )

    assert is_credential_file( str( path ) )


def test_depth_is_not_capped_at_a_tuned_number():
    """
    "Arbitrary depth" asserted, not assumed. A credential thirty wrappers down is
    the same credential — a bounded walk would have to pick a number, and the
    number would be the next hole.
    """
    buried = ADC_USER_CREDENTIAL
    for _ in range( 30 ):
        buried = { "wrapper" : buried }

    assert _prefix_looks_like_credential( json.dumps( buried ) )


def test_a_credential_nested_inside_an_array_inside_an_object_is_refused():
    """Containers alternate; the walk must cross both kinds, not just objects."""
    nested = { "accounts" : [ { "keys" : [ SA_KEY_NO_PEM ] } ] }

    assert _prefix_looks_like_credential( json.dumps( nested ) )


def test_a_truncated_ARRAY_of_credentials_still_BLOCKS():
    """
    The truncated branch keyed on `{` alone, so an array that ran past the window
    was read as prose and served. A truncated array is still a truncated
    credential file.
    """
    truncated = json.dumps( [ ADC_USER_CREDENTIAL ] )[ : 140 ]

    assert truncated.startswith( "[" )
    assert '"client_secret"' in truncated, "fixture must carry a signature field to act on"
    assert _prefix_looks_like_credential( truncated )


def test_a_lead_in_mark_in_front_of_a_NESTED_credential_still_BLOCKS():
    """
    The two fixes have to hold at the same time. This is the cell neither table
    had: an invisible lead-in AND a nested payload.
    """
    assert _prefix_looks_like_credential( " ﻿" + json.dumps( GCP_CONSOLE_CLIENT_SECRET_INSTALLED ) )


# ─── the accepted limit, stated rather than assumed ──────────────────────────

def test_a_credential_past_the_SECOND_window_is_SERVED_and_that_is_the_stated_limit( tmp_path ):
    """
    ⚠️ ACCEPTED LIMIT, asserted so it stays a decision instead of drifting into an
    assumption. The read widens once to CREDENTIAL_MAX_SNIFF_BYTES; material past
    that mark is not seen. Closing it would mean refusing every large JSON
    document on the grounds it might be hiding something.

    If this test ever goes red, the bound moved — that is a change to state, not
    a failure to fix.
    """
    padded = { "notes" : "x" * ( CREDENTIAL_MAX_SNIFF_BYTES + 1024 ) }
    padded.update( ADC_USER_CREDENTIAL )
    path = tmp_path / "huge.json"
    path.write_text( json.dumps( padded ), encoding="utf-8" )

    assert not is_credential_file( str( path ) )


def test_the_second_read_is_what_catches_the_past_the_window_shape( tmp_path ):
    """
    The widened read fires on a filled window that opens a JSON container, and on
    nothing else — a short file and a long document are both decided in one pass.
    """
    assert not _the_window_may_be_hiding_the_signature( '{"short": "file"}' )
    assert not _the_window_may_be_hiding_the_signature( "p" * CREDENTIAL_SNIFF_BYTES )
    assert _the_window_may_be_hiding_the_signature( "{" + "p" * ( CREDENTIAL_SNIFF_BYTES - 1 ) )
    assert _the_window_may_be_hiding_the_signature( " ﻿[" + "p" * CREDENTIAL_SNIFF_BYTES )


# ─── NO FALSE POSITIVES at depth — the cost of the fix, decided deliberately ──

def test_an_openapi_spec_naming_client_secret_at_depth_is_STILL_SERVED( tmp_path ):
    """
    The price of searching at any depth: a bare key NAME can no longer be enough
    to refuse on, or every spec that documents an OAuth flow becomes a credential.
    A spec carries an OBJECT under the field; a credential carries the secret.
    """
    path = tmp_path / "openapi.json"
    path.write_text( json.dumps( {
        "openapi"    : "3.0.0",
        "components" : { "securitySchemes" : { "oauth" : { "type" : "oauth2", "flows" : {
            "clientCredentials" : { "tokenUrl" : "/token", "x-params" : {
                "client_secret" : { "type" : "string", "description" : "the client secret" },
                "refresh_token" : { "type" : "string" },
            } } } } } },
    } ) )

    assert not is_credential_file( str( path ) )


@pytest.mark.parametrize( "placeholder", [
    "<your client secret>", "<REDACTED>", "${CLIENT_SECRET}", "{{ client_secret }}", "   ",
] )
def test_a_template_showing_a_credential_field_is_STILL_SERVED( tmp_path, placeholder ):
    """
    A setup guide that shows the field with a placeholder in it is a document.
    This is a SHAPE test, not a list of words — a real secret cannot be written
    this way and still be the secret.
    """
    path = tmp_path / "example.json"
    path.write_text( json.dumps( { "installed" : { "client_secret" : placeholder } } ) )

    assert not is_credential_file( str( path ) )


def test_a_field_carrying_a_schema_rather_than_a_secret_is_not_credential_material():
    """The unit under the trade above: only a real string counts."""
    assert _value_is_secret_material( "GOCSPX-9dQ2mVn4rTb7xLpKs0WyZaEuHc" )
    assert not _value_is_secret_material( { "type": "string" } )
    assert not _value_is_secret_material( [ "client_secret" ] )
    assert not _value_is_secret_material( 42 )
    assert not _value_is_secret_material( None )


def test_a_declared_credential_type_at_depth_needs_no_secret_string():
    """
    The type value is decisive on its own — a service-account key whose fields
    were stripped to nothing is still announcing what it is.
    """
    assert _object_declares_a_credential( { "type" : "external_account" } )
    assert not _object_declares_a_credential( { "type" : "report" } )
    assert not _object_declares_a_credential( { "type" : 3 } )


def test_a_parsed_scalar_carries_nothing_to_decide_on():
    """A JSON file that is just a string or a number has no object to inspect."""
    assert not _parsed_value_carries_a_credential( "client_secret" )
    assert not _parsed_value_carries_a_credential( 7 )
    assert not _parsed_value_carries_a_credential( None )


def test_text_without_escapes_comes_back_unchanged():
    """The decoder only puts escapes back; it must not rewrite anything else."""
    assert _decode_json_unicode_escapes( '{"refresh_token": "1//0abc"}' ) == '{"refresh_token": "1//0abc"}'
    assert _decode_json_unicode_escapes( '{"\\u0072efresh_token"' ) == '{"refresh_token"'


# ─── which lead-in strip is load-bearing, and which one cannot fail ──────────
#
# Extra 1 🪨 observed that gutting the lead-in strip at ONE call site leaves this
# suite green, and read that as the tests proving nothing. Half right: it IS a gap in
# my tests, and it is NOT evidence the two sites are redundant. Measured, the sites
# differ — but only on the FALSE-POSITIVE side, which is why no blocking test could
# separate them.
#
#   lead-in + payload                     full    early strip gutted
#   plain mark  + a template              SERVED  SERVED
#   SPACE+mark  + a template              SERVED  *** BLOCK ***   <- the difference
#   SPACE+mark  + a real credential       BLOCK   BLOCK
#
# WHY: with the early strip, `json.loads` succeeds, so the decision goes through the
# PARSED path, where a placeholder value is recognised as a template. Without it, the
# parse fails on the mark and the decision falls to the TRUNCATED branch — a raw
# substring scan with no placeholder rule — which sees `"client_secret"` and refuses a
# document. The early strip is what keeps the strong path reachable; blocking a real
# credential still works either way, via the weaker path.

PLACEHOLDER_TEMPLATE = {
    "client_id"     : "<your client id>",
    "client_secret" : "<your client secret>",
}

SPEC_NAMING_THE_FIELD = {
    "components" : { "parameters" : { "client_secret" : { "in" : "query", "schema" : { "type" : "string" } } } },
}


@pytest.mark.parametrize( "lead,lead_label", [
    ( " ﻿",   "space then mark" ),
    ( "\t﻿", "tab then mark" ),
    ( "\n﻿", "newline then mark" ),
    ( "​",   "zero-width space" ),
] )
@pytest.mark.parametrize( "payload,payload_label", [
    ( PLACEHOLDER_TEMPLATE,    "a template showing the field" ),
    ( SPEC_NAMING_THE_FIELD,   "a spec naming the field" ),
] )
def test_an_invisible_leadin_must_not_turn_a_DOCUMENT_into_a_refusal(
    tmp_path, lead, lead_label, payload, payload_label
):
    """
    THE ARM THAT PINS THE EARLY STRIP. Gut `_strip_leadin_noise` in
    `_prefix_looks_like_credential` and these go RED — a document becomes a refusal
    because the parse failed on an invisible character and the raw-text fallback took
    over. Every other lead-in test in this file passes with that line gone.
    """
    path = tmp_path / "notes.json"
    path.write_text( lead + json.dumps( payload ), encoding="utf-8" )

    assert not is_credential_file( str( path ) ), \
        f"{lead_label} + {payload_label} was refused"


def test_the_narrowing_strip_is_DEFENSIVE_and_cannot_currently_fire():
    """
    ⚠️ STATED, not asserted away. The SECOND `_strip_leadin_noise` call — the one at
    the brace narrowing — cannot change an answer today, because the first call has
    already stripped the same prefix by the time control reaches it. Gutting it alone
    leaves this suite green, and that is correct rather than a missing test.

    It is kept as defense in depth for the case where the truncated branch is reached
    with an unstripped prefix, which no current path produces. Recorded here because a
    line that cannot fail is indistinguishable from an absent one, and the next reader
    deserves to know which of the two strips is doing the work.
    """
    already_stripped = _strip_leadin_noise( " ﻿" + '{"client_secret": "s3cret"}' )

    assert _strip_leadin_noise( already_stripped ) == already_stripped
    assert already_stripped.startswith( "{" )


# ─────────────────────────────────────────────────────────────────────────────
# AXIS 4 — PAYLOAD. Bugs b17ffefd and 0cbf69c0: the walk crossed objects and
# arrays and then STOPPED, twice over.
#
#   · it stopped at a STRING, so a whole credential carried as JSON text inside
#     another JSON file was never opened (b17ffefd, shapes A1-A3)
#   · it stopped at a LIST under a credential key, because the value test wants a
#     string and the walk only descends into objects (b17ffefd A7, 0cbf69c0)
#
# WHY AXIS 3 COULD NOT REACH THIS: axis 3 varies the DEPTH and the CONTAINER of a
# payload that is always a plain object with plain string fields. Both holes here
# are about what the payload is MADE OF, which that axis holds fixed. Same lesson
# as axis 3 learning it from axis 1 and 2: a table that varies one thing proves
# one thing.
#
# All six shapes below were measured SERVED at ce943c5d, on these exact fixtures.
# ─────────────────────────────────────────────────────────────────────────────

# The terraform / kubernetes / compose shape: the whole key is one string value.
CREDENTIAL_AS_A_JSON_STRING = { "google_credentials" : json.dumps( SA_KEY_NO_PEM ) }

TFVARS_SHAPED_FILE = {
    "project"            : "not-a-real-project-000000",
    "region"             : "us-central1",
    "google_credentials" : json.dumps( SA_KEY_NO_PEM ),
}

CREDENTIAL_AS_A_STRING_INSIDE_AN_ARRAY = [ { "env" : json.dumps( ADC_USER_CREDENTIAL ) } ]

TWO_LEVELS_OF_STRING_NESTING = {
    "outer" : json.dumps( { "inner" : json.dumps( SA_KEY_NO_PEM ) } )
}

# 0cbf69c0's shape: the key material is a LIST of lines and there is no `type`
# field to catch the object on its declaration instead.
PRIVATE_KEY_AS_A_LIST_OF_LINES = {
    "private_key" : [
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ",
        "DGx0ArLmT7dEwlYCJoJqzZ0nQ5eYbHkPvNsRxUiFgAoIBAQCkfz",
    ],
}

# the same, with a `type` that is NOT a credential type — so the type arm cannot
# be what does the work here
PRIVATE_KEY_AS_A_LIST_WITH_A_DECOY_TYPE = {
    "type"        : "svc",
    "private_key" : [ "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ" ],
}


SIX_PAYLOAD_SHAPES_THAT_STILL_SERVED = [
    ( "A1  a service-account key carried as a JSON STRING under a config key",
      CREDENTIAL_AS_A_JSON_STRING ),
    ( "A1b the same string inside a terraform-tfvars-shaped file",
      TFVARS_SHAPED_FILE ),
    ( "A2  an ADC carried as a JSON STRING inside an array",
      CREDENTIAL_AS_A_STRING_INSIDE_AN_ARRAY ),
    ( "A3  two levels of string nesting",
      TWO_LEVELS_OF_STRING_NESTING ),
    ( "A7  private_key as a LIST, with a decoy type value",
      PRIVATE_KEY_AS_A_LIST_WITH_A_DECOY_TYPE ),
    ( "L1  private_key as a LIST of PEM-less lines, no type field at all",
      PRIVATE_KEY_AS_A_LIST_OF_LINES ),
]


@pytest.mark.parametrize( "label,payload", SIX_PAYLOAD_SHAPES_THAT_STILL_SERVED,
                          ids=[ entry[ 0 ].split()[ 0 ] for entry in SIX_PAYLOAD_SHAPES_THAT_STILL_SERVED ] )
def test_the_six_payload_shapes_that_still_served_are_all_REFUSED( tmp_path, label, payload ):
    """
    THE HEADLINE for both payload bugs, driven end-to-end through the surface the
    doc viewer actually calls. All six measured SERVED at ce943c5d.
    """
    path = tmp_path / "fixture.json"
    path.write_text( json.dumps( payload ), encoding="utf-8" )

    assert is_credential_file( str( path ) ), f"shape SERVED a credential: {label}"


def test_a_credential_smuggled_in_a_string_is_found_under_an_innocent_name( tmp_path ):
    """
    The real filename this arrives under. `terraform.tfvars.json` is a config file
    nobody thinks of as a key, and the key is sitting in it as a string.
    """
    path = tmp_path / "terraform.tfvars.json"
    path.write_text( json.dumps( TFVARS_SHAPED_FILE ), encoding="utf-8" )

    assert is_credential_file( str( path ) )


def test_a_list_of_secret_lines_is_secret_material_and_a_list_of_placeholders_is_not():
    """
    The unit under 0cbf69c0. The placeholder rule survives the list arm item by
    item — a template written as an array of lines is still a template.
    """
    assert _credential_field_carries_secret_material( [ "MIIEvQIBADANBgkqhkiG9w0B" ] )
    assert _credential_field_carries_secret_material( [ [ "MIIEvQIBADANBgkqhkiG9w0B" ] ] )
    assert _credential_field_carries_secret_material( "MIIEvQIBADANBgkqhkiG9w0B" )

    assert not _credential_field_carries_secret_material( [ "<your key here>", "${KEY_BODY}" ] )
    assert not _credential_field_carries_secret_material( [] )
    assert not _credential_field_carries_secret_material( [ { "type" : "string" } ] )
    assert not _credential_field_carries_secret_material( None )


def test_the_scalar_value_test_still_answers_only_about_a_scalar():
    """
    ⚠️ THE LINE THAT WAS TEMPTING TO MOVE. Row 0cbf69c0 says a list of secret
    strings should count, and the shortest way to get there is to make
    `_value_is_secret_material` say yes to a list. That would flip the assertion
    Tiffany pinned at the depth fix — a list is not a string, and that function
    answers about ONE value.

    So the list arm lives one layer up, in the field test, and this stays true.
    """
    assert not _value_is_secret_material( [ "client_secret" ] )
    assert not _value_is_secret_material( [ "MIIEvQIBADANBgkqhkiG9w0B" ] )


def test_a_string_that_is_not_json_is_not_re_parsed():
    """The cheap opener test is what keeps ordinary prose out of the parser."""
    assert _opens_a_json_container( '{"a": 1}' )
    assert _opens_a_json_container( "  ﻿[1, 2]" )
    assert not _opens_a_json_container( "just a sentence about client_secret" )
    assert not _opens_a_json_container( "" )


def test_a_string_that_opens_a_container_but_does_not_parse_carries_nothing():
    """
    Returning None must mean "nothing here to walk", and the walk must survive it
    rather than treating a broken string as a signature.
    """
    assert _json_carried_in_a_string( '{"a": 1}' ) == { "a" : 1 }
    assert _json_carried_in_a_string( '{"a": ' ) is None

    assert not _parsed_value_carries_a_credential( { "note" : '{"client_secret": ' } )


def test_an_ordinary_document_carrying_json_in_a_string_is_STILL_SERVED( tmp_path ):
    """
    Re-parsing strings must not start refusing documents. A config file that
    carries an embedded JSON blob with nothing secret in it is a document.
    """
    path = tmp_path / "settings.json"
    path.write_text( json.dumps( {
        "name"    : "widget",
        "options" : json.dumps( { "retries" : 3, "type" : "report" } ),
        "schema"  : json.dumps( { "client_secret" : { "type" : "string" } } ),
    } ) )

    assert not is_credential_file( str( path ) )


def test_a_template_carried_inside_a_string_is_STILL_SERVED( tmp_path ):
    """
    The placeholder rule has to survive the trip through a string, or every setup
    guide that ships an example blob becomes a credential.
    """
    path = tmp_path / "example.tfvars.json"
    path.write_text( json.dumps( {
        "google_credentials" : json.dumps( { "type" : "service", "private_key" : "<paste yours>" } ),
    } ) )

    assert not is_credential_file( str( path ) )


# ─── the accepted costs of the payload fix, decided rather than discovered ────

def test_documentation_that_embeds_a_WHOLE_REAL_KEY_in_a_string_is_now_REFUSED( tmp_path ):
    """
    ⚠️ ACCEPTED COST, asserted so it stays a decision. A document whose example is
    a REAL key rather than a placeholder is now refused — the detector cannot tell
    a key quoted for teaching from a key stored for use, and a real key pasted into
    a doc is a real key that is being served.

    A template keeps working (asserted above), which is the shape documentation
    should be using anyway.
    """
    path = tmp_path / "how-to-auth.json"
    path.write_text( json.dumps( {
        "title"   : "How to configure the exporter",
        "example" : json.dumps( SA_KEY_NO_PEM ),
    } ) )

    assert is_credential_file( str( path ) )


def _a_file_with_json_shaped_decoys( decoy_count ):
    """A credential string at the bottom of the stack, behind `decoy_count` decoys."""
    payload = { "credential" : json.dumps( SA_KEY_NO_PEM ) }
    for index in range( decoy_count ):
        payload[ f"decoy_{index}" ] = json.dumps( { "n" : index } )
    return json.dumps( payload )


def test_json_shaped_decoys_do_not_hide_a_credential_within_the_budget( tmp_path ):
    """A handful of embedded blobs is ordinary, and the credential is still found."""
    path = tmp_path / "config.json"
    path.write_text( _a_file_with_json_shaped_decoys( 10 ), encoding="utf-8" )

    assert is_credential_file( str( path ) )


def test_a_credential_past_the_RE_PARSE_BUDGET_is_SERVED_and_that_is_the_stated_limit( tmp_path ):
    """
    ⚠️ ACCEPTED LIMIT, asserted rather than assumed — the same treatment the 1 MiB
    read bound gets. Re-parsing is capped at CREDENTIAL_MAX_NESTED_PARSES per file,
    so a document that spends the whole budget on JSON-shaped strings before the
    walk reaches the credential serves it.

    Removing the cap turns one serve/refuse decision on a hostile file into
    thousands of parses, which is a worse thing to own than this limit.

    If this ever goes red the budget or the walk order moved — that is a change to
    state, not a failure to fix.
    """
    path = tmp_path / "many-blobs.json"
    path.write_text( _a_file_with_json_shaped_decoys( CREDENTIAL_MAX_NESTED_PARSES * 2 ),
                     encoding="utf-8" )

    assert not is_credential_file( str( path ) )


def test_the_re_parse_budget_is_generous_next_to_any_real_nesting():
    """
    The number itself, stated. The measured shapes carry one or two levels; the cap
    is two orders of magnitude above that, so it bounds a hostile file without ever
    being reached by a real one.
    """
    assert CREDENTIAL_MAX_NESTED_PARSES == 64


# ── Row de013b80: two follow-ups Tiffany found reviewing the payload fix ──────
#
# BOTH ARE NEW GAPS, NOT REGRESSIONS. Neither serves a credential that was blocked
# before the payload fix — the first needs the nested-string walk to exist at all,
# and the second is inherited from the top-level parse. Both are reproduced below
# before being fixed, because the row was filed on her word and said so.

_NESTED_LEADINS = [
    ( "﻿", "BOM"                    ),
    ( "​", "zero-width space"       ),
    ( "⁠", "word joiner"            ),
    ( " ﻿", "space then BOM"        ),
    ( "\n\t﻿", "newline, tab, BOM"  ),
]


@pytest.mark.parametrize( "lead,lead_label", _NESTED_LEADINS )
@pytest.mark.parametrize( "payload,label", [
    ( ADC_USER_CREDENTIAL, "ADC user credential"                     ),
    ( SA_KEY_NO_PEM,       "service-account key with no PEM header"  ),
] )
def test_a_leadin_inside_a_CARRIED_credential_string_still_BLOCKS(
        tmp_path, lead, lead_label, payload, label ):
    """
    THE RED for finding 1 of row de013b80.

    The payload fix taught the walk to re-parse a string that carries JSON, which is
    how terraform tfvars, kubernetes secrets and compose env files carry a key. Two
    functions do that job and they disagreed about which text they were judging:
    `_opens_a_json_container` strips the invisible lead-in before saying "worth
    parsing", and `_json_carried_in_a_string` then parsed the RAW string — so it
    failed ON THE VERY CHARACTER THE GATE HAD JUST REMOVED, returned None, and the
    credential inside was SERVED.

    MEASURED before the fix: served with the BOM, served with the zero-width space,
    and BLOCKED with no lead-in at all — which is exactly why it hid. Every fixture
    written for the payload fix was clean-led.
    """
    path = tmp_path / "terraform.tfvars.json"
    path.write_text( json.dumps( { "google_credentials": lead + json.dumps( payload ) } ),
                     encoding="utf-8" )

    assert is_credential_file( str( path ) ), f"{label} behind a {lead_label} was SERVED"


@pytest.mark.parametrize( "lead,lead_label", _NESTED_LEADINS )
def test_a_leadin_inside_a_carried_credential_in_a_LIST_still_BLOCKS( tmp_path, lead, lead_label ):
    """
    The same miss one container over. The walk reaches list items exactly as it
    reaches object values, so a fix that only looked at dict values would leave this
    open — and a reader would reasonably believe the class was closed.
    """
    path = tmp_path / "secrets.json"
    path.write_text( json.dumps( [ lead + json.dumps( SA_KEY_NO_PEM ) ] ), encoding="utf-8" )

    assert is_credential_file( str( path ) ), f"a key behind a {lead_label} in a list was SERVED"


def test_the_carried_parse_reads_the_same_text_the_gate_judged():
    """
    The two functions, side by side. This is the invariant the bug broke, stated
    directly rather than only through its symptom: if the gate says a string is worth
    parsing, the parse must succeed on the text the gate was looking at.
    """
    carried = "﻿" + json.dumps( SA_KEY_NO_PEM )

    assert _opens_a_json_container( carried ) is True
    assert _json_carried_in_a_string( carried ) is not None


def test_stripping_the_leadin_before_the_carried_parse_buys_no_false_positive():
    """
    THE OVER-REACH GUARD. Stripping more aggressively must not start blocking prose.
    An ordinary document whose text happens to begin with a mark is still a document.
    """
    assert _json_carried_in_a_string( "﻿not json at all" ) is None
    assert _json_carried_in_a_string( "﻿{\"type\": \"tokenizer\"}" ) == { "type": "tokenizer" }


# ── Finding 2: nesting deep enough to break the parser ────────────────────────
_TOO_DEEP = 20000


def test_a_document_too_deeply_nested_to_parse_does_not_CRASH( tmp_path ):
    """
    THE RED for finding 2. `json.loads` raises RecursionError at roughly 20000 levels
    — a 39 KiB file of open brackets does it — and it escaped the detector, so the
    reader got a 500 instead of a verdict.

    ⚠️ NOT because of the exception's ancestry. My first version of this docstring
    said RecursionError inherits from BaseException and not Exception, which is
    FALSE: RecursionError -> RuntimeError -> Exception -> BaseException. Tiffany
    corrected it. It escaped because of WHERE the broad handler sits — `is_credential_file`
    wraps the FILE READ and calls the predicate after the try block, so nothing at all
    guarded the decision.

    A crash is not a verdict. This asserts the detector ANSWERS.
    """
    path = tmp_path / "deep.json"
    path.write_text( "[" * _TOO_DEEP + "]" * _TOO_DEEP, encoding="utf-8" )

    assert is_credential_file( str( path ) ) is False     # answers, and this one carries nothing


@pytest.mark.parametrize( "inner,label", [
    ( '{"type": "service_account", "private_key": "MIIEvQIBADANBgkqhkiG9w0BAQEF"}',
      "service-account key" ),
    ( '{"refresh_token": "1//0eXaMpLeReFrEsHtOkEnMaTeRiAl"}',
      "ADC refresh token" ),
] )
def test_a_credential_buried_under_too_much_nesting_still_BLOCKS( tmp_path, inner, label ):
    """
    Not crashing is only half of it. The refusal must still FAIL CLOSED — burying a
    key under enough brackets to break the parser must not become a way to serve it.
    The unparseable-container branch does that work, and this pins that RecursionError
    reaches that branch rather than some quieter path.
    """
    path = tmp_path / "deep-key.json"
    path.write_text( "[" * _TOO_DEEP + inner + "]" * _TOO_DEEP, encoding="utf-8" )

    assert is_credential_file( str( path ) ), f"{label} under {_TOO_DEEP} levels was SERVED"


def test_the_recursion_guard_covers_the_CARRIED_parse_too():
    """
    Two parse sites, and a fix applied to one of them is the partial mutation this
    lane keeps hitting. The carried-string parse must swallow it as well, or a deep
    document reached through a nested string crashes where a top-level one does not.
    """
    assert _json_carried_in_a_string( "[" * _TOO_DEEP + "]" * _TOO_DEEP ) is None


def test_ordinary_nesting_is_untouched():
    """
    The depth that matters is absurd, and normal documents must not pay for it. A
    thousand levels is already far past anything real and still parses.
    """
    assert _json_carried_in_a_string( "[" * 1000 + "]" * 1000 ) is not None


def test_an_error_raised_while_DECIDING_still_BLOCKS( tmp_path, monkeypatch ):
    """
    THE GAP THE WRONG DIAGNOSIS UNCOVERED (row de013b80, Tiffany's correction).

    `is_credential_file` promises in its own docstring: "Raises: nothing; every
    failure path blocks instead". That was true of READING and false of DECIDING —
    the `except Exception` wraps only the `open`/`read`, and the predicate is called
    after the try block. So for the whole life of this check, any error raised while
    deciding left the module and the reader got a 500.

    A 500 is not a serve, so nothing leaked. But it is not a verdict either, and a
    check whose fail-closed guarantee stops one line short of the decision is one
    refactor away from a caller reading the raise as absence.
    """
    path = tmp_path / "ordinary.json"
    path.write_text( '{"type": "tokenizer"}', encoding="utf-8" )

    def _explode( _prefix ):
        raise ValueError( "the decision itself blew up" )

    monkeypatch.setattr( "cosa.rest.routers._scope_registry._prefix_looks_like_credential",
                         _explode )

    assert is_credential_file( str( path ) ) is True


def test_the_recursion_error_ancestry_claim_I_made_was_wrong():
    """
    Pinned as a fact rather than left in prose, because the wrong version of it is
    written into a commit message that cannot be edited. RecursionError IS an
    Exception; a broad handler catches it. Placement was the whole story.
    """
    assert issubclass( RecursionError, Exception )
    assert RecursionError.__mro__[ : 4 ] == ( RecursionError, RuntimeError, Exception, BaseException )


# ── Row ee1670bc: the refusal has to say WHICH refusal it is ─────────────────
#
# `is_credential_file` answers one bit and two different facts were collapsing into it.
# An unreadable file blocked, correctly, and the viewer then told the reader the file's
# CONTENT was credential material — a true refusal with a false explanation, which sends
# whoever is debugging to hunt for a key that was never there. THE FLOOR DOES NOT MOVE:
# both outcomes still refuse. Only the explanation became available.

def test_a_real_credential_reads_credential( tmp_path ):
    path = tmp_path / "key.json"
    path.write_text( json.dumps( SA_KEY_NO_PEM ), encoding="utf-8" )

    assert credential_verdict( str( path ) ) == "credential"


def test_an_ordinary_document_reads_clean( tmp_path ):
    path = tmp_path / "notes.md"
    path.write_text( "# Notes\nnothing secret here\n", encoding="utf-8" )

    assert credential_verdict( str( path ) ) == "clean"


def test_a_missing_file_reads_unreadable_NOT_credential( tmp_path ):
    """
    THE RED for ee1670bc, at the layer that decides it. Before the split this was
    indistinguishable from a real key, and the doc viewer said so out loud.
    """
    assert credential_verdict( str( tmp_path / "gone.json" ) ) == "unreadable"


def test_a_non_utf8_file_reads_unreadable_NOT_credential( tmp_path ):
    path = tmp_path / "binary.txt"
    path.write_bytes( b"\xff\xfe\x00\x01not utf-8 at all" )

    assert credential_verdict( str( path ) ) == "unreadable"


def test_an_error_while_deciding_reads_unreadable_NOT_credential( tmp_path, monkeypatch ):
    """
    We could not complete the decision. That is a statement about our ability to tell,
    never about the file's content — so it must not borrow the credential verdict.
    """
    path = tmp_path / "ordinary.json"
    path.write_text( '{"type": "tokenizer"}', encoding="utf-8" )

    monkeypatch.setattr( "cosa.rest.routers._scope_registry._prefix_looks_like_credential",
                         lambda _p: ( _ for _ in () ).throw( ValueError( "boom" ) ) )

    assert credential_verdict( str( path ) ) == "unreadable"


@pytest.mark.parametrize( "verdict_case,label", [
    ( "credential",  "a real key"        ),
    ( "unreadable",  "an unreadable file" ),
] )
def test_is_credential_file_still_BLOCKS_on_both_refusing_verdicts( tmp_path, verdict_case, label ):
    """
    THE CONTRACT THAT MUST NOT MOVE. `is_credential_file` is now defined as
    `credential_verdict(...) != "clean"`, so every mutation proof written against it
    keeps holding — including the unreadable case, which is the one a careless split
    would quietly turn into a serve.
    """
    if verdict_case == "credential":
        path = tmp_path / "key.json"
        path.write_text( json.dumps( SA_KEY_NO_PEM ), encoding="utf-8" )
    else:
        path = tmp_path / "missing.json"          # never created

    assert is_credential_file( str( path ) ) is True, f"{label} was SERVED"


def test_is_credential_file_serves_only_on_clean( tmp_path ):
    path = tmp_path / "notes.md"
    path.write_text( "# Notes\n", encoding="utf-8" )

    assert is_credential_file( str( path ) ) is False
