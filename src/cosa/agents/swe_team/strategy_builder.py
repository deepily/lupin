"""
Shared builder for the INI-configured EngineeringStrategy.

Three call sites need the same strategy: the SWE team orchestrator, the bug fix
expediter orchestrator and the decision proxy entry point.
Every setting comes from the INI: trust model, thresholds, circuit breaker, category caps,
audit rate and accepted senders.
Building it here keeps the three call sites from drifting apart.
"""

import logging

logger = logging.getLogger( __name__ )


def build_ini_engineering_strategy( trust_mode, debug=False, on_trip_callback=None ):
    """
    Build an EngineeringStrategy with every setting read from the INI.

    Requires:
        - trust_mode is one of "shadow", "suggest", "active"
        - on_trip_callback is None or a callable( category, reason )

    Ensures:
        - Returns ( strategy, swe_cfg ) where swe_cfg is the SWE proxy config dict, empty if the INI read failed
        - A key absent because the INI read failed keeps the built-in value
        - Only an unknown trust model is refused; any other INI read failure is logged and the defaults are used

    Raises:
        - InvalidTrustModelError if the INI names a trust model outside the accepted choices
        - ImportError if the proxy modules are unavailable
    """
    from cosa.agents.swe_team.proxy import EngineeringStrategy
    from cosa.agents.decision_proxy.trust_tracker import TrustTracker
    from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker
    from cosa.agents.decision_proxy.errors import InvalidTrustModelError

    # Read INI config via factory functions (non-fatal fallback to defaults)
    proxy_cfg = {}
    swe_cfg   = {}
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        from cosa.agents.decision_proxy.config import trust_proxy_config_from_config_mgr
        from cosa.agents.swe_team.proxy.config import swe_proxy_config_from_config_mgr

        cfg_mgr   = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        proxy_cfg = trust_proxy_config_from_config_mgr( cfg_mgr )
        swe_cfg   = swe_proxy_config_from_config_mgr( cfg_mgr )
    except InvalidTrustModelError:
        # An unknown trust model is refused at startup, not run on defaults; other INI read failures stay non-fatal
        raise
    except Exception as e:
        logger.warning( f"INI config read failed, using defaults: {e}" )

    # Beta rate thresholds and minimum samples; keys absent (INI read failed) keep the built-in values
    beta_kwargs = {}
    if "beta_l2_rate_threshold" in proxy_cfg:
        beta_kwargs[ "rate_thresholds" ] = { lvl : proxy_cfg[ f"beta_l{lvl}_rate_threshold" ] for lvl in ( 2, 3, 4, 5 ) }
        beta_kwargs[ "min_samples" ]     = { lvl : proxy_cfg[ f"beta_l{lvl}_min_samples" ] for lvl in ( 2, 3, 4, 5 ) }

    # Build TrustTracker with INI values
    trust_tracker = TrustTracker(
        rolling_window_days  = proxy_cfg.get( "rolling_window_days", 30 ),
        decay_half_life_days = proxy_cfg.get( "decay_half_life_days", 14 ),
        l2_threshold         = proxy_cfg.get( "l2_threshold", 50 ),
        l3_threshold         = proxy_cfg.get( "l3_threshold", 200 ),
        l4_threshold         = proxy_cfg.get( "l4_threshold", 500 ),
        l5_threshold         = proxy_cfg.get( "l5_threshold", 1000 ),
        trust_model          = proxy_cfg.get( "trust_model", "count" ),
        **beta_kwargs,
        debug                = debug,
    )

    # Build CircuitBreaker with INI values
    circuit_breaker = CircuitBreaker(
        trust_tracker                 = trust_tracker,
        error_rate_threshold          = proxy_cfg.get( "cb_error_rate_threshold", 0.15 ),
        confidence_collapse_threshold = proxy_cfg.get( "cb_confidence_collapse_threshold", 0.3 ),
        auto_demotion_levels          = proxy_cfg.get( "cb_auto_demotion_levels", 2 ),
        recovery_cooldown_seconds     = proxy_cfg.get( "cb_recovery_cooldown_seconds", 3600 ),
        on_trip_callback              = on_trip_callback,
        debug                         = debug,
    )

    # INI cap keys; a key absent (INI read failed) keeps the built-in cap
    cap_levels = {
        cat : swe_cfg[ f"{cat}_cap_level" ]
        for cat in ( "deployment", "destructive", "architecture" ) if f"{cat}_cap_level" in swe_cfg
    }

    # INI audit rate; a key absent (INI read failed) keeps the strategy's own default
    audit_kwargs = { "l4_audit_rate": proxy_cfg[ "l4_audit_sample_rate" ] } if "l4_audit_sample_rate" in proxy_cfg else {}

    strategy = EngineeringStrategy(
        **audit_kwargs,
        cap_levels       = cap_levels,
        trust_tracker    = trust_tracker,
        circuit_breaker  = circuit_breaker,
        accepted_senders = swe_cfg.get( "accepted_senders" ),
        trust_mode       = trust_mode,
        debug            = debug,
    )
    return strategy, swe_cfg
