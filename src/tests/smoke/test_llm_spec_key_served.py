"""
Smoke test: every CONSUMED vLLM spec key names a model the target port is
actually serving.

WHY THIS EXISTS (row 357c283f). On 2026-07-31 a config cutover (commit
5499fdbf) repointed ~29 `llm spec key for ...` settings at
`confidentialmind/mistral_small_24b`, whose connection string is
`vllm://192.168.1.21:3001@ConfidentialMind/Mistral-Small-3.2-24B-...` — but
:3001 was serving Phi-4, not that model. Every exercised path 404'd. The
mismatch was invisible to unit tests (no server) and to the container-preflight
probes (they check that a MOUNT is declared, not that a MODEL is served). Commit
0565c8a2 reverted it. This test is the guard so the next such mismatch fails a
test instead of Rick's demo.

WHAT IT CHECKS. For each spec key with a LIVE CONSUMER, resolve its
`vllm://host:port@model` connection string (env-expanded exactly as the app
resolves it via ConfigurationManager.get), GET `http://host:port/v1/models`,
and assert the model name is in the served list.

FAIL, NEVER SKIP, ON AN UNREACHABLE PORT. A skip is exactly how this class of
defect hides — a down model server would silently pass. If the port is down the
model is not being served, which is the failure this test is here to surface.
This is by design a host/preflight-tier test run where the model servers are
expected up (the demo box), NOT a unit-gate test.

SCOPE — "live consumer" = a config setting whose VALUE references the spec key
(the `llm spec key for ...` / `formatter llm spec for ...` / `... model` family,
including list-valued settings). A DEFINED-but-unreferenced spec key (e.g. the
PARKED `confidentialmind/mistral_small_24b`, held by 0565c8a2 for a possible
future resume) is intentionally OUT OF SCOPE and never probed — parking a key
must not trip this test. Source-code string-literal consumers are also out of
scope on purpose: a key name can appear in a *comment* (judge.py mentions the
parked 24B key by name precisely to say "do not reuse this"), and a source grep
cannot tell a real call from a mention — it would false-trip the very parked key
this test must leave alone.

Paired row: 357c283f-4689-4c08-a952-9bd9b05a9c43.
"""

import os
import re
import json
import urllib.request
import urllib.error

import pytest

from cosa.config.configuration_manager import ConfigurationManager

_PROBE_TIMEOUT_SECONDS = 5

# The router/qwen LoRA connection strings embed ${LUPIN_ROUTER_LORA_*_PATH}, which
# ConfigurationManager.get expands via os.path.expandvars against os.environ. At
# runtime the app process gets those vars because the container sources ~/.lora_env
# at startup, and peft_trainer.py auto-writes that file after each training run.
# This test must resolve the spec THE SAME WAY the app does — NOT by trusting the
# caller to have sourced something. So it loads ~/.lora_env itself. A DEFECT this
# closes: an earlier version passed only in a shell that had sourced the file and
# failed everywhere else (host/containers/:8000 gate), because it asserted about the
# test process's own shell env instead of the config resolution the app performs.
_LORA_ENV_CANDIDATES = ( os.path.expanduser( "~/.lora_env" ), "/home/rruiz/.lora_env" )


def _load_lora_env_if_present():
    """
    Load ~/.lora_env into os.environ so ${LUPIN_ROUTER_LORA_*_PATH} resolves the way
    the running app resolves it. Never clobbers an already-set var (a real
    environment wins). Returns the file it loaded, or None if none is present.
    """
    for path in _LORA_ENV_CANDIDATES:
        if os.path.isfile( path ):
            with open( path, encoding="utf-8" ) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith( "#" ) or "=" not in line:
                        continue
                    if line.startswith( "export " ):
                        line = line[ len( "export " ): ]
                    key, val = line.split( "=", 1 )
                    os.environ.setdefault(
                        key.strip(), val.strip().strip( '"' ).strip( "'" )
                    )
            return path
    return None


def _config_mgr():
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


def _discover_consumed_vllm_specs( config_mgr ):
    """
    Map every vLLM spec key that a config setting references → its metadata.

    Requires:
        - config_mgr is an initialized ConfigurationManager

    Ensures:
        - returns dict { spec_key : { "conn": <env-expanded connection string>,
                                      "consumers": [ setting_key, ... ] } }
        - only spec keys whose value starts with "vllm://" are considered
        - only spec keys referenced (as a whole token) by at least one OTHER
          setting's value are included; a key's own definition and its
          "<key>_params" sibling never count as a consumer
    """
    keys = config_mgr.get_keys()

    # Defined vLLM spec keys: value (env-expanded by get) starts with vllm://
    defined = {}
    for k in keys:
        v = config_mgr.get( k, default="", silent=True )
        if isinstance( v, str ) and v.startswith( "vllm://" ):
            defined[ k ] = v

    # A setting consumes a spec key when the key name appears as a whole token in
    # the setting's value (handles bare `= key` and list/JSON `[ "key" ]` forms).
    consumed = {}
    for spec_key in defined:
        token = re.compile( re.escape( spec_key ) + r"(?![A-Za-z0-9_])" )
        for k in keys:
            if k == spec_key or k == f"{spec_key}_params":
                continue
            v = config_mgr.get( k, default="", silent=True )
            if isinstance( v, str ) and token.search( v ):
                consumed.setdefault(
                    spec_key, { "conn": defined[ spec_key ], "consumers": [] }
                )[ "consumers" ].append( k )

    return consumed


def _parse_vllm( conn ):
    """
    Split a vLLM connection string into (host_port, model_name).

    Requires:
        - conn starts with "vllm://" and contains one "@" after the authority

    Ensures:
        - returns ( "host:port", "model_name" )

    Raises:
        - AssertionError if conn is not a well-formed vllm:// spec
    """
    assert conn.startswith( "vllm://" ), f"not a vllm:// spec: {conn!r}"
    body = conn[ len( "vllm://" ): ]
    assert "@" in body, f"vllm:// spec missing '@<model>': {conn!r}"
    assert "${" not in body, (
        f"vllm:// spec has an UNRESOLVED env var: {conn!r}. This test already "
        f"auto-loads ~/.lora_env, so this means that file is absent AND the var is "
        f"unset in the environment — the running app could not resolve the model "
        f"path either. Remedy: ensure ~/.lora_env exists (peft_trainer.py writes it) "
        f"or the var is set in the app's environment."
    )
    host_port, model_name = body.split( "@", 1 )
    return host_port, model_name


def _served_models( host_port ):
    """
    Return the list of model ids a vLLM server is serving.

    Requires:
        - host_port is "host:port" for a reachable vLLM /v1/models endpoint

    Ensures:
        - returns list[str] of served model ids

    Raises:
        - AssertionError (NOT a skip) if the endpoint is unreachable or does not
          answer /v1/models — an unreachable server is not serving the model,
          which is the failure this test exists to surface.
    """
    url = f"http://{host_port}/v1/models"
    try:
        with urllib.request.urlopen( url, timeout=_PROBE_TIMEOUT_SECONDS ) as resp:
            payload = json.load( resp )
    except ( urllib.error.URLError, OSError, json.JSONDecodeError ) as e:
        raise AssertionError(
            f"vLLM endpoint {url} is UNREACHABLE ({type( e ).__name__}: {e}). "
            f"An unreachable server serves no model — failing rather than "
            f"skipping, because a skip is how a down model server hides. Remedy: "
            f"bring the model server on {host_port} back up (do not restart it "
            f"blindly — confirm which model it should serve first)."
        )
    return [ m.get( "id" ) for m in payload.get( "data", [] ) ]


_LOADED_LORA_ENV = _load_lora_env_if_present()
_CONSUMED        = _discover_consumed_vllm_specs( _config_mgr() )


def test_at_least_one_consumed_vllm_spec_discovered():
    """
    Guard against a vacuous pass: if discovery found nothing, the parametrized
    test below has zero cases and trivially "passes" while checking nothing. The
    top-level `agent router` is the load-bearing invariant — it must always have
    a live consumer — so anchor on it by name.
    """
    assert _CONSUMED, (
        "No CONSUMED vLLM spec keys discovered — the served-model test would run "
        "zero cases and pass vacuously. Check ConfigurationManager.get_keys() and "
        "the config block."
    )
    assert "deepily/ministral_8b_2410_ft_lora" in _CONSUMED, (
        "The top-level 'agent router' spec key (deepily/ministral_8b_2410_ft_lora) "
        "has no live consumer — either the router was re-pointed or discovery is "
        f"broken. Discovered: {sorted( _CONSUMED )}"
    )


@pytest.mark.parametrize(
    "spec_key",
    sorted( _CONSUMED ),
    ids=sorted( _CONSUMED ),
)
def test_consumed_vllm_spec_model_is_served( spec_key ):
    """Each consumed spec key's model is actually served by its target port."""
    meta               = _CONSUMED[ spec_key ]
    host_port, model   = _parse_vllm( meta[ "conn" ] )
    served             = _served_models( host_port )
    assert model in served, (
        f"Spec key '{spec_key}' (consumed by {len( meta[ 'consumers' ] )} "
        f"setting(s), e.g. {sorted( meta[ 'consumers' ] )[ 0 ]!r}) resolves to "
        f"model '{model}' but http://{host_port} serves only {served}. This is "
        f"the exact config-vs-serving mismatch of row 357c283f: a live agent is "
        f"pointed at a model its target port is not serving, so every request on "
        f"that path 404s. Remedy: point the spec key at a served model, or serve "
        f"the named model on {host_port}."
    )


# ── Controls: prove the instrument can actually FAIL (row-feedback: every ──────
# ── harness needs a control that MUST fail if the check is broken). ────────────

def test_control_bogus_model_is_reported_unserved():
    """
    Discrimination control: against a REAL live port (a consumed endpoint), a
    model name that cannot exist must be reported NOT served. If this passed
    vacuously the main assertion's `model in served` would be meaningless.
    """
    any_conn         = next( iter( _CONSUMED.values() ) )[ "conn" ]
    host_port, _     = _parse_vllm( any_conn )
    served           = _served_models( host_port )
    assert "__deepily_model_that_cannot_exist__" not in served, (
        "A deliberately-bogus model name appeared in the served list — the "
        "served-model probe is not discriminating and the main test is vacuous."
    )


def test_control_unreachable_port_fails_not_skips():
    """
    Fail-don't-skip control: an unreachable port must raise AssertionError, not
    skip. Port 9 (discard) is reserved and refuses TCP, so this is deterministic.
    """
    with pytest.raises( AssertionError, match="UNREACHABLE" ):
        _served_models( "127.0.0.1:9" )


def test_control_unresolved_env_var_is_a_failure():
    """
    A vllm:// spec whose env var is unset must be flagged, not silently probed
    against a literal ${...} path.
    """
    with pytest.raises( AssertionError, match="UNRESOLVED env var" ):
        _parse_vllm( "vllm://192.168.1.21:3000@${LUPIN_DEFINITELY_UNSET_VAR}" )


def test_control_parse_rejects_non_vllm_spec():
    """Malformed-input control: a non-vllm:// string is rejected, not parsed."""
    with pytest.raises( AssertionError, match="not a vllm:// spec" ):
        _parse_vllm( "http://192.168.1.21:3000/v1" )


def test_control_parse_rejects_spec_missing_model():
    """Malformed-input control: a vllm:// spec with no '@<model>' is rejected."""
    with pytest.raises( AssertionError, match="missing '@<model>'" ):
        _parse_vllm( "vllm://192.168.1.21:3000" )


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
