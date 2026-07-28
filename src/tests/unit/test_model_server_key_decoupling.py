"""
Regression guards for the model-server credential split (rows 574fd1dc / 6cc52525).

WHAT BROKE, AND WHY A UNIT TEST CAN GUARD IT
--------------------------------------------
One key file served two consumers with incompatible authorities:

  notification-api-claude-code-dev -> bcrypt-checked against THAT DEPLOYMENT'S
       `api_keys` table. Correct value DIFFERS on every host.
  model-server-api                 -> mounted from ONE Secret Manager version
       and bcrypt-hashed at BOOT. Correct value is IDENTICAL everywhere.

On the dev box those coincide by accident (dev's key had been seeded into Secret
Manager), which is exactly why no test caught it: **the defect is invisible on
the machine the tests run on.** So these tests do NOT assert that auth works —
they assert WHICH NAME each call site asks for, which is machine-independent.

⚠️ THE SHARPEST GUARD HERE IS THE NEGATIVE ONE.
`test_prediction_engine_still_uses_the_notifications_key` pins a call site that
must NOT be migrated. `embedding_provider._http_api_key`'s docstring used to say
it "mirrors the pattern in prediction_engine._generate_embedding_via_http", and
that sentence nearly caused an over-migration: the READING IDIOM is shared, the
AUTHORITY is not. prediction_engine POSTs to localhost/api/embeddings/generate —
Lupin's own server, per-database key. Pointing it at the model-server key would
have broken it on every host, trading one outage for a wider one.
"""

import os
import re
import inspect
from unittest import mock

import pytest

from cosa.memory.embedding_provider     import EmbeddingProvider
from cosa.memory.speech_to_text_provider import SpeechToTextProvider

MODEL_SERVER_KEY  = "model-server-api"
NOTIFICATIONS_KEY = "notification-api-claude-code-dev"
ENV_VAR           = "LUPIN_MODEL_SERVER_API_KEY_NAME"


# ── consumer B: both call sites ask for the MODEL SERVER's key ───────────────

@pytest.mark.parametrize(
    "reader",
    [
        pytest.param( EmbeddingProvider._http_api_key,          id="embedding_provider" ),
        pytest.param( SpeechToTextProvider._model_server_api_key, id="speech_to_text_provider" ),
    ],
)
def test_consumer_b_defaults_to_the_model_server_key( reader ):
    """
    With no env override, both model-server callers must ask for
    `model-server-api` — NEVER the notifications key.

    This is the regression guard proper: reverting either call site to the
    shared name re-creates the 38h outage, and would do so silently on dev
    because both files exist there.
    """
    captured = []
    with mock.patch.dict( os.environ, {}, clear=False ):
        os.environ.pop( ENV_VAR, None )
        with mock.patch( "cosa.utils.util.get_api_key", side_effect=lambda n: captured.append( n ) or "ck_live_x" ):
            reader()

    assert captured == [ MODEL_SERVER_KEY ], (
        f"model-server caller asked for {captured!r}; expected [{MODEL_SERVER_KEY!r}]. "
        f"Asking for {NOTIFICATIONS_KEY!r} is bug 574fd1dc: that key is validated "
        f"against a per-deployment api_keys table and cannot match the single "
        f"secret version Cloud Run mounts."
    )


@pytest.mark.parametrize(
    "reader",
    [
        pytest.param( EmbeddingProvider._http_api_key,          id="embedding_provider" ),
        pytest.param( SpeechToTextProvider._model_server_api_key, id="speech_to_text_provider" ),
    ],
)
def test_consumer_b_honours_the_env_override( reader ):
    """
    Both callers read the key NAME from the same env var the model server reads,
    so the two ends cannot drift by editing only one of them.
    """
    captured = []
    with mock.patch.dict( os.environ, { ENV_VAR: "some-other-name" } ):
        with mock.patch( "cosa.utils.util.get_api_key", side_effect=lambda n: captured.append( n ) or "ck_live_x" ):
            reader()

    assert captured == [ "some-other-name" ], (
        f"caller ignored {ENV_VAR} and asked for {captured!r}. The client and the "
        f"model server must resolve the key name from the SAME var, or a rename "
        f"on one end silently 401s every request from the other."
    )


def test_client_and_server_read_the_same_env_var_name():
    """
    The anti-drift property, asserted against the model server's OWN source
    rather than a copy of its var name.

    ⚠️ Reads the file rather than importing it: lupin_model_server ships in a
    separate GPU image and importing it here would pull torch.
    """
    root   = os.environ[ "LUPIN_ROOT" ]
    source = open( f"{root}/src/lupin_model_server/main.py" ).read()

    assert f'os.environ.get( "{ENV_VAR}"' in source, (
        f"{ENV_VAR} is no longer how the model server resolves its key name. "
        f"The clients still use it — one end moved without the other."
    )


# ── consumer A: the call site that must NOT be migrated ──────────────────────

def test_prediction_engine_still_uses_the_notifications_key():
    """
    NEGATIVE GUARD — prediction_engine is consumer A and must keep the
    notifications key.

    It POSTs to `localhost/api/embeddings/generate` — Lupin's OWN server, whose
    key is bcrypt-checked against that deployment's `api_keys` table. The
    model-server key has no `api_keys` row anywhere by design, so migrating this
    call site would 401 it on every host.

    This test exists because the migration nearly happened: embedding_provider's
    docstring described prediction_engine as using "the same pattern", and a
    shared idiom read as a shared authority.
    """
    from cosa.agents.prediction_engine import prediction_engine as pe

    source = inspect.getsource( pe.PredictionEngine._generate_embedding_via_http )

    assert NOTIFICATIONS_KEY in source, (
        "prediction_engine no longer asks for the notifications key. If it was "
        "migrated to the model-server key, revert: it calls Lupin's own API, "
        "which validates against a per-deployment api_keys table."
    )
    assert MODEL_SERVER_KEY not in source, (
        "prediction_engine was migrated to the model-server key. It POSTs to "
        "localhost/api/embeddings/generate (Lupin's own server), not to the "
        "model server — that key has no api_keys row and will 401 everywhere."
    )


# ── the minted key must satisfy the server's own predicate ───────────────────

def test_minted_key_satisfies_the_servers_regex():
    """
    The minter must not emit a key the model server refuses at boot.

    A refused key leaves `api_key_hash` None -> 503 on every authed endpoint,
    and the boot log historically still read healthy (that asymmetry is 6cc52525).
    """
    import importlib.util
    root = os.environ[ "LUPIN_ROOT" ]
    spec = importlib.util.spec_from_file_location(
        "mint_ms_key", f"{root}/src/scripts/mint-model-server-api-key.py"
    )
    mod = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )

    # The server's predicate, restated here from its source so this test fails
    # if the two ever diverge.
    server_re = re.compile( r"^ck_live_[A-Za-z0-9_-]{64,}$" )

    for _ in range( 5 ):
        key = mod.generate_model_server_key()
        assert server_re.match( key ), f"minted key does not satisfy the server's regex: len={len( key )}"

    # Fingerprint predicate parity: the minter and the server must both hash the
    # STRIPPED value, or a deploy check compares two different numbers and reads
    # a mismatch that does not exist (measured 2026-07-28 on the old key:
    # raw 26f45dbc7276 vs stripped 26e3c096d4df).
    key = mod.generate_model_server_key()
    assert mod.key_fingerprint( key ) == mod.key_fingerprint( key + "\n" ), (
        "key_fingerprint is not newline-insensitive; it must hash the STRIPPED "
        "value to stay comparable with the model server's /health fingerprint."
    )
