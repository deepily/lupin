#!/usr/bin/env python3
"""
No model key the VM resolves names a home-LAN address.

[Lupin: Testing-GCS] inherits Development, whose model specs point at 192.168.1.21, a host the GCP VM
cannot reach. Two keys were fixed one at a time (gist, router) and the next one down hung a real job.
This guard reads every key the block resolves. It fails on any whose value, or whose value's own value,
is a spec URL with a private or link-local host. No config seam is mocked.
"""
import ipaddress
import re

import pytest

from cosa.config.configuration_manager import ConfigurationManager
from cosa.agents.gemini_vertex_client import GeminiVertexClient
from cosa.agents.llm_client_factory import LlmClientFactory

BLOCK_ID = "Lupin:+Testing-GCS"
SCHEME   = re.compile( r"^[a-z0-9+.-]+://", re.IGNORECASE )

# A vendor URL is read only for a spec written vendor:model. It may stay on the home network only while
# vendor_users() finds no key in the block that resolves to such a spec.
# A raw LAN URL that must stay in this block, each with the reason. Every other raw URL fails the guard.
VENDOR_URL_KEYS = { "llm vendor url vllm": "vllm", "llm vendor url deepily": "deepily" }
ALLOWED_RAW = {
    "tts local url template" : "no code reads it: git grep finds it only in the INI, the splainer and "
                               "config-key-migration-map.json (measured 2026-10-30)",
}


def _reset_config():
    """Drop both singletons so no other module inherits this block's manager."""
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
    LlmClientFactory._instance = None


@pytest.fixture
def vm_config( monkeypatch ):
    """The real INI, loaded under the VM's block id."""
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS",
                        "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini "
                        f"config_block_id={BLOCK_ID}" )
    _reset_config()
    yield ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    monkeypatch.undo()
    _reset_config()


def _unroutable_host( value ):
    """The host of a URL value when it is a LAN IP literal the VM has no route to, else None.

    Loopback is left alone: 127.0.0.1 on the VM is the VM itself.
    """
    if not isinstance( value, str ): return None
    body = SCHEME.sub( "", value.strip() )
    if body == value.strip(): return None
    host = re.split( r"[@/]", body )[ 0 ].split( ":" )[ 0 ]
    try:
        ip = ipaddress.ip_address( host )
    except ValueError:
        return None
    return host if ( ip.is_private and not ip.is_loopback ) or ip.is_link_local else None


def lan_keys( keys, get ):
    """Every key whose value, or the value that value names, is an unroutable URL.

    Takes the key list and a getter so the finder can be proven on a hand-built table.
    Returns a dict of key -> ( spec key or None, host ).
    """
    flagged = {}
    for key in keys:
        value  = get( key )
        host   = _unroutable_host( value )
        via    = None
        if host is None and isinstance( value, str ) and value.strip() != key:
            host = _unroutable_host( get( value.strip() ) )
            via  = value.strip() if host is not None else None
        if host is not None: flagged[ key ] = ( via, host )
    return flagged


def test_the_guard_can_find_a_lan_key():
    """Positive control: the finder flags what it is handed, so an empty answer means something."""
    table = { "a key": "a/spec", "a/spec": "vllm://192.168.1.21:3001@some/model",
              "direct": "vllm://10.0.0.5:3000@m", "ok key": "ok/spec", "ok/spec": "vertex://global@gemini-3.1-flash-lite",
              "plain": "text", "none": None }

    assert lan_keys( table, table.get ) == { "a key": ( "a/spec", "192.168.1.21" ), "a/spec": ( None, "192.168.1.21" ),
                                             "direct": ( None, "10.0.0.5" ) }
    assert _unroutable_host( "http://127.0.0.1:8001/x" ) is None
    assert _unroutable_host( "vertex://global@gemini-3.1-flash-lite" ) is None


# The specs a Testing-GCS consumer may resolve to: a vertex:// spec, or vendor:model on a cloud vendor.
# The cloud vendors are the factory's own chat-API rows; its completion-API rows ( vllm, deepily ) are the home
# network, and a vendor the factory does not know ( ollama ) is on neither list, so it is not allowed.
CLOUD_SCHEMES      = ( "vertex", )
CLOUD_VENDORS      = tuple( sorted( vendor for vendor, row in LlmClientFactory.VENDOR_CONFIG.items() if row[ "client_type" ] == "chat" ) )
# A direct value of these schemes is a service address, not a model spec. The LAN-address tests above judge its host.
# A value that another key names is a model spec, so only CLOUD_SCHEMES is allowed there.
SERVICE_SCHEMES    = ( "http", "https", "gs" )
# Values that hold a colon and are not model specs. Each key maps to the pattern its value must fully match and
# the reason. A value off the pattern is parsed as a spec like any other, so a model spec planted here is flagged.
NOT_A_SPEC = {
    "stt device id"                                   : ( r"cuda:\d+",                                     "a CUDA device index" ),
    "local embedding device"                          : ( r"cuda:\d+",                                     "a CUDA device index" ),
    "presentation generator nano banana aspect ratio" : ( r"\d+:\d+",                                     "an image aspect ratio" ),
    "peer queue allowed hosts"                        : ( r"lupin-rest-[a-z]+:\d+(,lupin-rest-[a-z]+:\d+)*", "docker service host:port pairs" ),
    "managed bounce server label"                     : ( r":\d+",                                         "a port label" ),
    "app config server name"                          : ( r"127\.0\.0\.1:\d+",                              "this server's own host:port" ),
    "local embedding prose query prefix"              : ( r"search_query:",                               "a text prefix the embedder prepends" ),
    "local embedding prose document prefix"           : ( r"search_document:",                            "a text prefix the embedder prepends" ),
}


def is_not_a_spec( key, value ):
    """Whether a key is exempt and its value fully matches that key's pattern."""
    return key in NOT_A_SPEC and re.fullmatch( NOT_A_SPEC[ key ][ 0 ], value.strip() ) is not None


def is_cloud_spec( value, named=False ):
    """Whether a colon-bearing value parses as a spec on a cloud scheme or a cloud vendor.

    A value with :// is judged by its scheme. Any other value is vendor:model, and the text before
    the first colon is the vendor. A digit after the colon changes nothing, so ollama:7b-chat is judged by ollama.
    A named spec ( named=True ) may not take a service scheme, so http://nas.local fails there.
    """
    value = value.strip()
    if "://" in value: return value.split( "://", 1 )[ 0 ].lower() in CLOUD_SCHEMES + ( () if named else SERVICE_SCHEMES )
    return value.split( ":", 1 )[ 0 ].lower() in CLOUD_VENDORS


def non_cloud_consumers( keys, get ):
    """Every consumer key whose spec does not parse as cloud, whatever its host is called.

    A consumer is a key whose value, or the value of the key it names, holds a colon and no whitespace.
    Specs that nothing names ( a key with a _params sibling ) are definitions, judged only through their
    consumers. A key listed in NOT_A_SPEC is exempt while its value fits that key's pattern. Returns a dict of key -> ( spec key or None, spec ).
    """
    flagged = {}
    for key in keys:
        value = get( key )
        if not isinstance( value, str ): continue
        value = value.strip()
        if is_not_a_spec( key, value ): continue
        via, spec = None, None
        named     = get( value ) if value != key and value in keys and not is_not_a_spec( value, str( get( value ) ) ) else None
        if isinstance( named, str ) and ":" in named and not re.search( r"\s", named.strip() ):
            via, spec = value, named.strip()
        elif ":" in value and not re.search( r"\s", value ) and f"{key}_params" not in keys:
            spec = value
        if spec is not None and not is_cloud_spec( spec, named=via is not None ): flagged[ key ] = ( via, spec )
    return flagged


def test_the_cloud_allowlist_finder_can_find_a_hostname_consumer():
    """Positive control: hostname, digit-first and host:port specs are flagged."""
    table = { "bad key": "bad/spec", "bad/spec": "vllm://lupin-home-box.local:3001@m", "bad/spec_params": "{}",
              "bad direct": "vllm:some/model", "local direct": "ollama:llama3",
              "local via": "local/spec", "local/spec": "ollama:llama3", "local/spec_params": "{}",
              "digit first": "ollama:7b-chat", "host port": "nas:3000", "unlisted device": "cuda:0",
              "stt device id": "cuda:0",
              "other scheme": "other/spec", "other/spec": "tcp://nas:1@m", "other/spec_params": "{}",
              "ok key": "ok/spec", "ok/spec": "vertex://global@gemini-3.5-flash", "ok vendor": "anthropic:claude",
              "service": "https://api.example.com/v1", "http via": "http/spec", "http/spec": "http://nas.local/v1", "http/spec_params": "{}",
              "plain": "text", "none": None, "unnamed def": "vllm://nas:3000@m", "unnamed def_params": "{}" }

    assert non_cloud_consumers( table, table.get ) == {
        "bad key"      : ( "bad/spec",   "vllm://lupin-home-box.local:3001@m" ),
        "bad direct"   : ( None,         "vllm:some/model" ),
        "local direct" : ( None,         "ollama:llama3" ),
        "local via"    : ( "local/spec", "ollama:llama3" ),
        "digit first"  : ( None,         "ollama:7b-chat" ),
        "host port"    : ( None,         "nas:3000" ),
        "http via"     : ( "http/spec",  "http://nas.local/v1" ),
        "unlisted device" : ( None,      "cuda:0" ),
        "other scheme" : ( "other/spec", "tcp://nas:1@m" ) }


def vendor_users( keys, get, vendor ):
    """Every key whose value, or the value it names, is a vendor:model spec.

    A vendor:model spec is the only shape that reads `llm vendor url <vendor>`; a vendor:// spec carries its own host.
    Returns a dict of key -> the spec string.
    """
    prefix = re.compile( rf"^{re.escape( vendor )}:(?!//)", re.IGNORECASE )
    users  = {}
    for key in keys:
        value = get( key )
        if not isinstance( value, str ): continue
        for spec in ( value.strip(), get( value.strip() ) ):
            if isinstance( spec, str ) and prefix.match( spec.strip() ):
                users[ key ] = spec.strip()
                break
    return users


def _vm_lan_findings( vm_config ):
    """Split the block's LAN hits into consumers and raw URL values.

    A spec definition ( a raw hit with a <key>_params sibling ) is inherited from Development.
    It matters only when a consumer names it, so it is dropped from the raw list. Allowed raw URLs are dropped too.
    """
    keys   = vm_config.get_keys()
    found  = lan_keys( keys, lambda key: vm_config.get( key, default=None, silent=True ) )
    consumers = { key: hit for key, hit in found.items() if hit[ 0 ] is not None }
    raw       = { key: hit for key, hit in found.items()
                  if hit[ 0 ] is None and f"{key}_params" not in keys and key not in ALLOWED_RAW and key not in VENDOR_URL_KEYS }
    return consumers, raw


def test_no_resolved_model_key_names_a_lan_address( vm_config ):
    """No key the VM resolves names a spec that points at a host it has no route to."""
    consumers, _ = _vm_lan_findings( vm_config )

    assert not consumers, f"{len( consumers )} keys resolve to an unroutable host:\n" + "\n".join(
        f"  {key} -> {via} @ {host}" for key, ( via, host ) in sorted( consumers.items() ) )


def test_every_testing_gcs_consumer_uses_a_cloud_spec( vm_config ):
    """No consumer resolves to a spec outside the cloud allowlist, IP literal or not."""
    keys = vm_config.get_keys()
    bad  = non_cloud_consumers( keys, lambda key: vm_config.get( key, default=None, silent=True ) )

    assert not bad, f"{len( bad )} consumers resolve to a non-cloud spec:\n" + "\n".join(
        f"  {key} -> {via} = {spec}" for key, ( via, spec ) in sorted( bad.items() ) )


def test_a_planted_hostname_spec_reddens_the_cloud_allowlist_on_the_real_block( vm_config ):
    """Mutant: the real vm_agents spec planted on a home hostname flags its 26 consumers."""
    keys    = vm_config.get_keys()
    real    = lambda key: vm_config.get( key, default=None, silent=True )
    planted = lambda key: "vllm://lupin-home-box.local:3001@m" if key == "vm_agents/gemini_flash" else real( key )

    flagged = non_cloud_consumers( keys, planted )

    assert sorted( flagged ) == sorted( key for key in keys if real( key ) == "vm_agents/gemini_flash" )
    assert len( flagged ) == 26
    assert not set( flagged ) & set( lan_keys( keys, planted ) ), "the IP-literal finder is blind to a hostname: that is the gap this closes"


@pytest.mark.parametrize( "planted_spec", [ "ollama:llama3", "ollama:7b-chat", "nas:3000", "http://nas.local/v1" ] )
def test_a_planted_local_spec_reddens_the_cloud_allowlist_on_the_real_block( vm_config, planted_spec ):
    """Mutant: the vm_agents spec planted as a local vendor or host:port flags its 26 consumers.

    Neither ollama nor nas is a chat row of the factory's VENDOR_CONFIG, and a digit after the colon is no exemption.
    """
    keys    = vm_config.get_keys()
    real    = lambda key: vm_config.get( key, default=None, silent=True )
    planted = lambda key: planted_spec if key == "vm_agents/gemini_flash" else real( key )

    flagged = non_cloud_consumers( keys, planted )

    assert planted_spec.split( ":" )[ 0 ] not in CLOUD_VENDORS
    assert sorted( flagged ) == sorted( key for key in keys if real( key ) == "vm_agents/gemini_flash" )
    assert { spec for _, spec in flagged.values() } == { planted_spec }


@pytest.mark.parametrize( "exempt_key", sorted( NOT_A_SPEC ) )
@pytest.mark.parametrize( "planted_spec", [ "ollama:7b-chat", "vllm://nas.local" ] )
def test_a_planted_spec_on_an_exempt_key_reddens_the_cloud_allowlist( vm_config, exempt_key, planted_spec ):
    """Mutant: a model spec planted on an exempt key is flagged, as the exemption is a pattern."""
    keys    = vm_config.get_keys()
    real    = lambda key: vm_config.get( key, default=None, silent=True )
    planted = lambda key: planted_spec if key == exempt_key else real( key )

    assert exempt_key not in non_cloud_consumers( keys, real )
    assert non_cloud_consumers( keys, planted )[ exempt_key ] == ( None, planted_spec )


@pytest.mark.parametrize( "exempt_key", sorted( NOT_A_SPEC ) )
def test_a_spec_appended_to_an_exempt_keys_real_value_is_flagged( vm_config, exempt_key ):
    """Mutant: a real value plus a trailing model spec is flagged: the pattern is whole-value."""
    keys     = vm_config.get_keys()
    real     = lambda key: vm_config.get( key, default=None, silent=True )
    appended = f"{real( exempt_key )},ollama:7b"
    planted  = lambda key: appended if key == exempt_key else real( key )

    assert exempt_key not in non_cloud_consumers( keys, real )
    assert non_cloud_consumers( keys, planted )[ exempt_key ] == ( None, appended )


def test_every_not_a_spec_exemption_still_fits_its_value_in_this_block( vm_config ):
    """An exemption for a key that is gone or off its value pattern is stale and must go."""
    keys  = vm_config.get_keys()
    value = lambda key: vm_config.get( key, default=None, silent=True )

    stale = sorted( key for key in NOT_A_SPEC if key not in keys or not is_not_a_spec( key, str( value( key ) ) ) )

    assert not stale, f"stale exemptions: {stale}"


def test_the_cloud_vendors_are_the_factorys_chat_rows():
    """Pin the derived set to a literal, so a new local row cannot slip in as cloud."""
    assert CLOUD_VENDORS == ( "anthropic", "google-gla", "groq", "mistralai", "openai" )


def test_no_raw_url_value_names_a_lan_address( vm_config ):
    """No plain URL value the VM resolves is on the home network unless ALLOWED_RAW says why."""
    _, raw = _vm_lan_findings( vm_config )

    assert not raw, f"{len( raw )} raw URL values are on the home network:\n" + "\n".join(
        f"  {key} @ {host}" for key, ( _, host ) in sorted( raw.items() ) )


def test_the_vendor_user_finder_can_find_a_user():
    """Positive control: a vendor:model spec is found, direct or through a key; vendor:// is not."""
    table = { "direct": "vllm:some/model", "via": "a/spec", "a/spec": "deepily:other", "own host": "vllm://10.0.0.5:3000@m",
              "other vendor": "groq:llama", "plain": "text", "none": None }

    assert vendor_users( table, table.get, "vllm" ) == { "direct": "vllm:some/model" }
    assert vendor_users( table, table.get, "deepily" ) == { "via": "deepily:other", "a/spec": "deepily:other" }


@pytest.mark.parametrize( "key,vendor", sorted( VENDOR_URL_KEYS.items() ) )
def test_a_vendor_url_on_the_home_network_is_unused_in_this_block( vm_config, key, vendor ):
    """The vendor URL stays only while no key resolved here names a spec that reads it."""
    keys  = vm_config.get_keys()
    users = vendor_users( keys, lambda name: vm_config.get( name, default=None, silent=True ), vendor )

    assert key in keys, f"{key} no longer exists in this block: drop it from VENDOR_URL_KEYS"
    assert not users, f"{key} is on the home network and these keys read it: {sorted( users.items() )}"


def test_the_vm_agent_spec_is_pinned_and_every_consumer_uses_it( vm_config, monkeypatch ):
    """The 26 former Phi-4 consumers share one pinned Gemini Flash spec.

    The router/vox key takes the router spec. The model, region and knobs are literals, so a wrong model string
    or a deleted params key turns this red.
    """
    monkeypatch.setenv( "LUPIN_GCP_PROJECT_ID", "test-project" )
    keys = vm_config.get_keys()
    get  = lambda key: vm_config.get( key, default=None, silent=True )
    on_flash  = sorted( key for key in keys if get( key ) == "vm_agents/gemini_flash" )
    on_router = sorted( key for key in keys if get( key ) == "agent_router/flash_lite" )
    client    = LlmClientFactory().get_client( "vm_agents/gemini_flash" )

    assert len( on_flash ) == 26
    assert on_router == [ "llm spec key for agent router", "router and vox command model" ]
    assert isinstance( client, GeminiVertexClient )
    assert client.model_name == "gemini-3.5-flash"
    assert client.location == "global"
    assert client._gen_config_kwargs == { "temperature": 0.0, "max_output_tokens": 4096, "seed": 20261030 }


def test_every_allowed_raw_url_is_still_a_lan_url_in_this_block( vm_config ):
    """An allowance for a key that no longer hits is stale and must go."""
    found = lan_keys( vm_config.get_keys(), lambda key: vm_config.get( key, default=None, silent=True ) )

    assert set( ALLOWED_RAW ) <= set( found ), f"stale allowances: {sorted( set( ALLOWED_RAW ) - set( found ) )}"


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
