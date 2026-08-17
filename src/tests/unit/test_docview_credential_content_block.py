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
    _decode_json_unicode_escapes,
    _is_secrets_path,
    _object_declares_a_credential,
    _parsed_value_carries_a_credential,
    _prefix_looks_like_credential,
    _strip_leadin_noise,
    _the_window_may_be_hiding_the_signature,
    _value_is_secret_material,
    is_credential_file,
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
