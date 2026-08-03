"""
Guard for bug 6cc52525 — the model-server validated its counterparty and never itself.

THE ASYMMETRY
`require_api_key` validates every INCOMING key against `_CK_LIVE_RE` before bcrypt.
The boot path validated NOTHING about the key it HASHED — not the prefix, not the
length, not the charset — and then printed:

    [lupin-model-server] API key loaded + hashed from notification-api-claude-code-dev

A truncated, rotated-stale, or wrong-format secret produced that identical cheerful
line and then 401'd every caller for the instance's entire life. The only guard was
`api_key_hash is None`, which catches "no key" and never "hashed the wrong bytes".

WHY IT BITES ON CLOUD RUN SPECIFICALLY
The secret is mounted as `latest`, resolved PER INSTANCE at cold start — so a
rotation lands at an unpredictable future moment with no deploy and no revision
change. Measured on `574fd1dc`: secret v2 created 17:44:29, `/embeddings/generate`
kept returning 200 for NINE MORE HOURS, then went to 100% 401 and stayed there ~38h.
759 log entries partitioned 726 × 200 then 33 × 401 across 10 instances with ZERO
mixed — the status was a property of which secret version each instance booted with.

WHAT IS FIXED HERE (remedies 2 + 3 of the row)
2. Boot applies the SAME `_CK_LIVE_RE` the request path applies, and refuses to hash
   a key that fails it — converting a silent instance-wide outage into a loud
   startup failure that leaves `api_key_hash` None, i.e. the existing 503 path.
3. `/health` exposes a truncated-sha256 FINGERPRINT of the loaded key, so "which key
   is this instance holding" is one unauthenticated request instead of log archaeology.

⚠️ NOT fixed here, deliberately: remedy 1, pinning the secret mount to an explicit
version. That is a rotation-workflow policy call and is Rick's, and Cloud Run was
read-only when this landed. This makes the failure loud; it does not stop the
rotation from arriving unannounced.
"""

import pytest


@pytest.fixture( autouse=True )
def reset_model_server_state():
    """
    Fresh `_state` per test.

    `_state` is a module-level singleton and `api_key_hash` / `load_errors`
    persist across tests without this. Omitting it made every "hash must be
    None" assertion pass or fail on TEST ORDER rather than on behaviour — the
    happy-path test installed a hash and the malformed cases then inherited it.
    A guard whose verdict depends on what ran before it is not a guard.
    """
    from lupin_model_server import main as ms

    original  = ms._state
    ms._state = ms._State()
    yield
    ms._state = original


# ── the two branches must stay DISTINGUISHABLE ──────────────────────────────


def _install( monkeypatch, tmp_path, contents ):
    """Point the module at a temp keys dir holding `contents`, then boot the key."""
    from lupin_model_server import main as ms

    monkeypatch.setattr( ms, "KEYS_DIR", str( tmp_path ) )
    monkeypatch.setattr( ms, "API_KEY_NAME", "probe-key" )
    if contents is not None:
        ( tmp_path / "probe-key" ).write_text( contents )
    ms._install_api_key()
    return ms


VALID_KEY = "ck_live_" + "a" * 64


def test_valid_key_installs_hash_and_fingerprint( monkeypatch, tmp_path ):
    ms = _install( monkeypatch, tmp_path, VALID_KEY )
    assert ms._state.api_key_hash is not None
    assert ms._state.api_key_fingerprint == ms._key_fingerprint( VALID_KEY )
    assert ms._state.load_errors == []


@pytest.mark.parametrize( "bad", [
    "ck_live_short",                       # right prefix, too short — the truncation case
    "ck_test_" + "a" * 64,                 # wrong prefix
    "a" * 72,                              # no prefix at all
    "ck_live_" + "a" * 63 + "!",           # illegal charset
    "ck_live_" + "a" * 32 + "\n" + "a" * 32,  # embedded newline — a mangled mount
] )
def test_malformed_key_is_refused_and_never_hashed( monkeypatch, tmp_path, bad ):
    """
    THE CONTROL. Before the fix every one of these produced a bcrypt hash and a
    success log, then 401'd every caller for the life of the instance.
    """
    ms = _install( monkeypatch, tmp_path, bad )
    assert ms._state.api_key_hash is None, (
        "a malformed key was HASHED — the server will now 401 every caller for this "
        "instance's whole life while reporting a successful key load (bug 6cc52525)"
    )
    assert ms._state.api_key_fingerprint is None
    assert ms._state.load_errors, "a refused key must leave a load_error, or the 503 is unexplained"


def test_missing_key_is_reported_as_missing( monkeypatch, tmp_path ):
    ms = _install( monkeypatch, tmp_path, None )
    assert ms._state.api_key_hash is None
    assert ms._state.load_errors


def test_missing_and_malformed_do_not_collapse_into_one_message( monkeypatch, tmp_path ):
    """
    THE LOAD-BEARING TEST. "File absent" and "file present holding wrong bytes" are
    different operator actions — go look for the mount vs go look at the secret
    version. The cheapest possible fix (return None on a bad key, reuse the existing
    branch) would satisfy every assertion above while destroying that distinction,
    and a reader would be sent to check a mount that is working fine.
    """
    from lupin_model_server import main as ms

    ms2      = _install( monkeypatch, tmp_path, None )
    missing  = " ".join( ms2._state.load_errors )
    ms2._state.load_errors.clear()

    ( tmp_path / "probe-key" ).write_text( "ck_live_short" )
    ms2._install_api_key()
    malformed = " ".join( ms2._state.load_errors )

    assert missing != malformed
    assert "missing or unreadable" in missing
    assert "does not match" in malformed and "missing or unreadable" not in malformed


# ── the key value must never leak, on ANY branch ────────────────────────────


@pytest.mark.parametrize( "contents", [ VALID_KEY, "ck_live_short", "a" * 72 ] )
def test_key_value_never_appears_in_load_errors_or_logs( monkeypatch, tmp_path, capsys, contents ):
    """
    Every branch reports the key's LENGTH (truncation is the likeliest cause and
    length is decisive) but never any part of the value. A diagnostic that prints a
    prefix of a secret to help you identify it is a secret in a log file.
    """
    ms  = _install( monkeypatch, tmp_path, contents )
    out = capsys.readouterr().out + " ".join( ms._state.load_errors )

    body = contents[ len( "ck_live_" ): ] if contents.startswith( "ck_live_" ) else contents
    assert contents not in out, "the whole key was logged"
    # any run of 12+ chars of the secret body appearing verbatim is a leak
    for i in range( 0, max( 1, len( body ) - 12 ) ):
        assert body[ i : i + 12 ] not in out, f"a 12-char slice of the key leaked: offset {i}"


# ── the fingerprint is a version tag, not a credential ──────────────────────


def test_fingerprint_is_stable_and_distinguishes_keys():
    from lupin_model_server import main as ms

    a = ms._key_fingerprint( VALID_KEY )
    assert a == ms._key_fingerprint( VALID_KEY ), "fingerprint must be stable across calls"
    assert a != ms._key_fingerprint( "ck_live_" + "b" * 64 ), (
        "two different keys share a fingerprint — it cannot answer 'which version is this'"
    )
    assert len( a ) == 12 and all( c in "0123456789abcdef" for c in a )


def test_fingerprint_shares_no_text_with_the_key():
    """It is a digest, not an excerpt. A 'fingerprint' that is a slice of the key is a leak."""
    from lupin_model_server import main as ms

    key = "ck_live_" + "9f3c" * 16
    assert ms._key_fingerprint( key ) not in key


# ── /health must answer "which key am I holding" without auth ───────────────


def test_health_reports_fingerprint_when_a_key_is_loaded( monkeypatch, tmp_path ):
    from fastapi.testclient import TestClient
    from lupin_model_server import main as ms

    _install( monkeypatch, tmp_path, VALID_KEY )
    body = TestClient( ms.app ).get( "/health" ).json()
    assert body[ "api_key_fingerprint" ] == ms._key_fingerprint( VALID_KEY )


def test_health_reports_null_fingerprint_when_no_key_loaded( monkeypatch, tmp_path ):
    """
    null is the honest answer for both "missing" and "refused" — `load_errors` in the
    same payload says which. What must NOT happen is a fingerprint appearing for a key
    that was never installed.
    """
    from fastapi.testclient import TestClient
    from lupin_model_server import main as ms

    _install( monkeypatch, tmp_path, "ck_live_short" )
    body = TestClient( ms.app ).get( "/health" ).json()
    assert body[ "api_key_fingerprint" ] is None
    assert body[ "load_errors" ]


# ── the asymmetry itself ────────────────────────────────────────────────────


def test_boot_and_request_paths_share_one_predicate( monkeypatch, tmp_path ):
    """
    THE ROW'S ACTUAL FINDING. The defect was not "boot lacked a check" — it was that
    boot and the request path disagreed about what a valid key IS. Pinning them to the
    same compiled regex is what keeps them from drifting apart again; two separately
    maintained validators would re-open this by degrees.

    Verified behaviourally, not by reading the source: neutering the shared predicate
    must change the BOOT path's verdict too. If boot had its own copy, this passes
    while the asymmetry quietly returns.
    """
    from lupin_model_server import main as ms

    class _NeverMatches:
        def match( self, _ ): return None

    monkeypatch.setattr( ms, "_CK_LIVE_RE", _NeverMatches() )
    ms2 = _install( monkeypatch, tmp_path, VALID_KEY )

    assert ms2._state.api_key_hash is None, (
        "boot accepted a key the shared validator rejected — it is using its own "
        "predicate, and the two can drift apart again (bug 6cc52525)"
    )
