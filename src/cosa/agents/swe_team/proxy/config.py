#!/usr/bin/env python3
"""
Configuration for the SWE Engineering Proxy domain layer.

SWE-specific constants: accepted senders, category cap levels.
Generic trust config lives in decision_proxy/config.py.

Dependency Rule:
    This module imports from decision_proxy (Layer 3) for base config re-exports.
    This module NEVER imports from notification_proxy.
"""

# ============================================================================
# SWE Team Sender Patterns
# ============================================================================

DEFAULT_ACCEPTED_SENDERS = [
    "swe.lead@lupin.deepily.ai",
    "swe.coder@lupin.deepily.ai",
    "swe.tester@lupin.deepily.ai",
]

# ============================================================================
# Category Cap Levels (max trust level for high-risk categories)
# ============================================================================

# Deployment, destructive, and architecture decisions are capped at L3
# (Act + Notify) — they always require human awareness even at peak trust.
DEFAULT_DEPLOYMENT_CAP_LEVEL    = 3
DEFAULT_DESTRUCTIVE_CAP_LEVEL   = 3
DEFAULT_ARCHITECTURE_CAP_LEVEL  = 3

# Testing, deps, and general can reach full autonomy (L5)
DEFAULT_TESTING_CAP_LEVEL       = 5
DEFAULT_DEPS_CAP_LEVEL          = 5
DEFAULT_GENERAL_CAP_LEVEL       = 5


# ============================================================================
# Factory: INI Config → SWE Proxy Config Dict
# ============================================================================

def swe_proxy_config_from_config_mgr( config_mgr ):
    """
    Read SWE-specific proxy INI keys into a config dict.

    Requires:
        - config_mgr is a ConfigurationManager instance with LUPIN_CONFIG_MGR_CLI_ARGS

    Ensures:
        - Returns dict with 4 SWE-specific proxy config values
        - accepted_senders is parsed as comma-separated list (stripped)
        - Falls back to module-level defaults for any missing keys

    Args:
        config_mgr: ConfigurationManager instance

    Returns:
        dict: SWE proxy config values
    """
    raw_senders = config_mgr.get(
        "swe engineering proxy accepted senders",
        default=",".join( DEFAULT_ACCEPTED_SENDERS ),
    )
    accepted_senders = [ s.strip() for s in raw_senders.split( "," ) if s.strip() ]

    return {
        "accepted_senders"       : accepted_senders,
        "deployment_cap_level"   : config_mgr.get( "swe engineering proxy deployment cap level",   default=DEFAULT_DEPLOYMENT_CAP_LEVEL,   return_type="int" ),
        "destructive_cap_level"  : config_mgr.get( "swe engineering proxy destructive cap level",  default=DEFAULT_DESTRUCTIVE_CAP_LEVEL,  return_type="int" ),
        "architecture_cap_level" : config_mgr.get( "swe engineering proxy architecture cap level", default=DEFAULT_ARCHITECTURE_CAP_LEVEL, return_type="int" ),
    }
