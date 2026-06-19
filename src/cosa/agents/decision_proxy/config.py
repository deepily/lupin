#!/usr/bin/env python3
"""
Configuration for the Decision Proxy Agent.

Generic trust framework configuration: level thresholds, decay rates,
circuit breaker parameters, active hours, and timezone. No domain-specific
constants — those belong in the domain layer (e.g., swe_team/proxy/config.py).

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

from cosa.agents.utils.proxy_agents.base_config import (   # noqa: F401
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    RECONNECT_MAX_ATTEMPTS,
    RECONNECT_BACKOFF_FACTOR,
    get_credentials,
    get_anthropic_api_key,
)


# ============================================================================
# Decision-Proxy-Specific Defaults
# ============================================================================

DEFAULT_SESSION_ID = "decision proxy"
DEFAULT_PROFILE    = "swe_team"

# WebSocket subscription events for decision proxy
SUBSCRIBED_EVENTS = [
    "notification_queue_update",
    "job_state_transition",
    "sys_ping"
]


# ============================================================================
# Trust Mode
# ============================================================================

TRUST_MODE_CHOICES = [ "shadow", "suggest", "active" ]
DEFAULT_TRUST_MODE = "shadow"


# ============================================================================
# Trust Levels
# ============================================================================

TRUST_LEVELS = {
    1 : { "name": "Shadow",                "min_decisions": 0,    "description": "Predict only, log, don't act" },
    2 : { "name": "Suggest",               "min_decisions": 50,   "description": "Queue as provisional, human ratifies" },
    3 : { "name": "Act + Notify",          "min_decisions": 200,  "description": "Commit decision, async audit" },
    4 : { "name": "Autonomous + Audit",    "min_decisions": 500,  "description": "10% random audit" },
    5 : { "name": "Full Autonomy",         "min_decisions": 1000, "description": "Circuit breaker only safety net" },
}

# Default thresholds (configurable via lupin-app.ini)
DEFAULT_L2_THRESHOLD = 50
DEFAULT_L3_THRESHOLD = 200
DEFAULT_L4_THRESHOLD = 500
DEFAULT_L5_THRESHOLD = 1000

# Trust decay
DEFAULT_DECAY_HALF_LIFE_DAYS   = 14
DEFAULT_ROLLING_WINDOW_DAYS    = 30

# Circuit breaker defaults
DEFAULT_CB_ERROR_RATE_THRESHOLD        = 0.15
DEFAULT_CB_CONFIDENCE_COLLAPSE_THRESHOLD = 0.3
DEFAULT_CB_AUTO_DEMOTION_LEVELS        = 2
DEFAULT_CB_RECOVERY_COOLDOWN_SECONDS   = 3600

# Active hours (when user is typically available)
DEFAULT_ACTIVE_HOURS_START = 9    # 09:00
DEFAULT_ACTIVE_HOURS_END   = 22   # 22:00
DEFAULT_TIMEZONE           = "America/Chicago"

# Audit sampling rate at L4
DEFAULT_L4_AUDIT_SAMPLE_RATE = 0.10  # 10%


# ============================================================================
# Phase 0: Embedding / Vector Search
# ============================================================================

DEFAULT_SIMILARITY_THRESHOLD  = 0.75
DEFAULT_PROXY_LANCEDB_TABLE   = "proxy_decisions"


# ============================================================================
# Phase 1: Beta-Bernoulli Rate Thresholds
# ============================================================================

DEFAULT_BETA_L2_RATE_THRESHOLD = 0.70
DEFAULT_BETA_L3_RATE_THRESHOLD = 0.80
DEFAULT_BETA_L4_RATE_THRESHOLD = 0.90
DEFAULT_BETA_L5_RATE_THRESHOLD = 0.95


# ============================================================================
# Phase 1: Minimum Samples per Level
# ============================================================================

DEFAULT_BETA_L2_MIN_SAMPLES = 20
DEFAULT_BETA_L3_MIN_SAMPLES = 50
DEFAULT_BETA_L4_MIN_SAMPLES = 100
DEFAULT_BETA_L5_MIN_SAMPLES = 200


# ============================================================================
# Phase 1: Case-Based Reasoning (CBR)
# ============================================================================

DEFAULT_CBR_TOP_K                = 5
DEFAULT_CBR_CONFIDENCE_THRESHOLD = 0.60


# ============================================================================
# Phase 2: Thompson Sampling
# ============================================================================

DEFAULT_THOMPSON_ENABLED           = False
DEFAULT_THOMPSON_ACT_THRESHOLD     = 0.90
DEFAULT_THOMPSON_SUGGEST_THRESHOLD = 0.70


# ============================================================================
# Phase 2: GP/BALD Active Query Selection (Optional — deferred)
# ============================================================================

DEFAULT_BALD_ENABLED               = False
DEFAULT_BALD_DEFER_THRESHOLD       = 0.50


# ============================================================================
# Phase 3: Conformal Prediction
# ============================================================================

DEFAULT_CONFORMAL_ENABLED = False
DEFAULT_CONFORMAL_ALPHA   = 0.10    # Significance level (1 - coverage)


# ============================================================================
# Phase 3: ICRL (In-Context Reinforcement Learning)
# ============================================================================

DEFAULT_ICRL_ENABLED = False
DEFAULT_ICRL_TOP_K   = 5


# ============================================================================
# Factory: INI Config → Runtime Config Dict
# ============================================================================

def trust_proxy_config_from_config_mgr( config_mgr ):
    """
    Read all generic trust proxy INI keys into a config dict.

    Requires:
        - config_mgr is a ConfigurationManager instance with LUPIN_CONFIG_MGR_CLI_ARGS

    Ensures:
        - Returns dict with all 36 generic trust proxy config values
        - Falls back to module-level defaults for any missing keys

    Args:
        config_mgr: ConfigurationManager instance

    Returns:
        dict: Config values keyed by runtime parameter names
    """
    return {
        # Core decision proxy settings
        "enabled"                          : config_mgr.get( "decision proxy enabled",                                             default=False,                                    return_type="boolean" ),
        "active_hours_start"               : config_mgr.get( "decision proxy active hours start",                                   default=DEFAULT_ACTIVE_HOURS_START,                return_type="int" ),
        "active_hours_end"                 : config_mgr.get( "decision proxy active hours end",                                     default=DEFAULT_ACTIVE_HOURS_END,                  return_type="int" ),
        "timezone"                         : config_mgr.get( "decision proxy timezone",                                             default=DEFAULT_TIMEZONE ),
        # Count-based trust level thresholds
        "l2_threshold"                     : config_mgr.get( "swe team trust proxy l2 threshold",                                   default=DEFAULT_L2_THRESHOLD,                     return_type="int" ),
        "l3_threshold"                     : config_mgr.get( "swe team trust proxy l3 threshold",                                   default=DEFAULT_L3_THRESHOLD,                     return_type="int" ),
        "l4_threshold"                     : config_mgr.get( "swe team trust proxy l4 threshold",                                   default=DEFAULT_L4_THRESHOLD,                     return_type="int" ),
        "l5_threshold"                     : config_mgr.get( "swe team trust proxy l5 threshold",                                   default=DEFAULT_L5_THRESHOLD,                     return_type="int" ),
        # Trust decay
        "decay_half_life_days"             : config_mgr.get( "swe team trust proxy decay half life days",                           default=DEFAULT_DECAY_HALF_LIFE_DAYS,             return_type="int" ),
        "rolling_window_days"              : config_mgr.get( "swe team trust proxy rolling window days",                            default=DEFAULT_ROLLING_WINDOW_DAYS,              return_type="int" ),
        # Circuit breaker
        "cb_error_rate_threshold"          : config_mgr.get( "swe team trust proxy circuit breaker error rate threshold",           default=DEFAULT_CB_ERROR_RATE_THRESHOLD,           return_type="float" ),
        "cb_confidence_collapse_threshold" : config_mgr.get( "swe team trust proxy circuit breaker confidence collapse threshold", default=DEFAULT_CB_CONFIDENCE_COLLAPSE_THRESHOLD, return_type="float" ),
        "cb_auto_demotion_levels"          : config_mgr.get( "swe team trust proxy circuit breaker auto demotion levels",           default=DEFAULT_CB_AUTO_DEMOTION_LEVELS,          return_type="int" ),
        "cb_recovery_cooldown_seconds"     : config_mgr.get( "swe team trust proxy circuit breaker recovery cooldown seconds",     default=DEFAULT_CB_RECOVERY_COOLDOWN_SECONDS,     return_type="int" ),
        # Audit
        "l4_audit_sample_rate"             : config_mgr.get( "swe team trust proxy l4 audit sample rate",                           default=DEFAULT_L4_AUDIT_SAMPLE_RATE,             return_type="float" ),
        # Phase 0: Embedding / vector search
        "similarity_threshold"             : config_mgr.get( "swe team trust proxy similarity threshold",                           default=DEFAULT_SIMILARITY_THRESHOLD,             return_type="float" ),
        "proxy_lancedb_table"              : config_mgr.get( "swe team trust proxy lancedb table",                                  default=DEFAULT_PROXY_LANCEDB_TABLE ),
        # Phase 1: Beta-Bernoulli rate thresholds
        "beta_l2_rate_threshold"           : config_mgr.get( "swe team trust proxy beta l2 rate threshold",                         default=DEFAULT_BETA_L2_RATE_THRESHOLD,            return_type="float" ),
        "beta_l3_rate_threshold"           : config_mgr.get( "swe team trust proxy beta l3 rate threshold",                         default=DEFAULT_BETA_L3_RATE_THRESHOLD,            return_type="float" ),
        "beta_l4_rate_threshold"           : config_mgr.get( "swe team trust proxy beta l4 rate threshold",                         default=DEFAULT_BETA_L4_RATE_THRESHOLD,            return_type="float" ),
        "beta_l5_rate_threshold"           : config_mgr.get( "swe team trust proxy beta l5 rate threshold",                         default=DEFAULT_BETA_L5_RATE_THRESHOLD,            return_type="float" ),
        # Phase 1: Minimum samples per level
        "beta_l2_min_samples"              : config_mgr.get( "swe team trust proxy beta l2 min samples",                            default=DEFAULT_BETA_L2_MIN_SAMPLES,              return_type="int" ),
        "beta_l3_min_samples"              : config_mgr.get( "swe team trust proxy beta l3 min samples",                            default=DEFAULT_BETA_L3_MIN_SAMPLES,              return_type="int" ),
        "beta_l4_min_samples"              : config_mgr.get( "swe team trust proxy beta l4 min samples",                            default=DEFAULT_BETA_L4_MIN_SAMPLES,              return_type="int" ),
        "beta_l5_min_samples"              : config_mgr.get( "swe team trust proxy beta l5 min samples",                            default=DEFAULT_BETA_L5_MIN_SAMPLES,              return_type="int" ),
        # Phase 1: CBR
        "cbr_top_k"                        : config_mgr.get( "swe team trust proxy cbr top k",                                      default=DEFAULT_CBR_TOP_K,                        return_type="int" ),
        "cbr_confidence_threshold"         : config_mgr.get( "swe team trust proxy cbr confidence threshold",                       default=DEFAULT_CBR_CONFIDENCE_THRESHOLD,          return_type="float" ),
        # Phase 2: Thompson Sampling
        "thompson_enabled"                 : config_mgr.get( "swe team trust proxy thompson enabled",                               default=DEFAULT_THOMPSON_ENABLED,                  return_type="boolean" ),
        "thompson_act_threshold"           : config_mgr.get( "swe team trust proxy thompson act threshold",                         default=DEFAULT_THOMPSON_ACT_THRESHOLD,            return_type="float" ),
        "thompson_suggest_threshold"       : config_mgr.get( "swe team trust proxy thompson suggest threshold",                     default=DEFAULT_THOMPSON_SUGGEST_THRESHOLD,        return_type="float" ),
        # Phase 2: GP/BALD (deferred — config keys reserved)
        "bald_enabled"                     : config_mgr.get( "swe team trust proxy bald enabled",                                   default=DEFAULT_BALD_ENABLED,                     return_type="boolean" ),
        "bald_defer_threshold"             : config_mgr.get( "swe team trust proxy bald defer threshold",                           default=DEFAULT_BALD_DEFER_THRESHOLD,              return_type="float" ),
        # Phase 3: Conformal prediction
        "conformal_enabled"                : config_mgr.get( "swe team trust proxy conformal enabled",                              default=DEFAULT_CONFORMAL_ENABLED,                 return_type="boolean" ),
        "conformal_alpha"                  : config_mgr.get( "swe team trust proxy conformal alpha",                                default=DEFAULT_CONFORMAL_ALPHA,                   return_type="float" ),
        # Phase 3: ICRL
        "icrl_enabled"                     : config_mgr.get( "swe team trust proxy icrl enabled",                                   default=DEFAULT_ICRL_ENABLED,                     return_type="boolean" ),
        "icrl_top_k"                       : config_mgr.get( "swe team trust proxy icrl top k",                                     default=DEFAULT_ICRL_TOP_K,                       return_type="int" ),
    }
