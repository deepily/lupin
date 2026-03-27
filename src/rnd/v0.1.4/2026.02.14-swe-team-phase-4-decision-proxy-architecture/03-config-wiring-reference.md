# Decision Proxy — Config Wiring Reference

## INI Key → Runtime Object Mapping

All keys are in `src/conf/lupin-app.ini` under `[Lupin: Baseline]`.

### Generic Trust Proxy Config (14 keys → `decision_proxy/config.py`)

| # | INI Key | Type | Default | Target Object | Target Param |
|---|---------|------|---------|---------------|--------------|
| 1 | `decision proxy enabled` | bool | false | `DecisionProxyConfig` | `enabled` |
| 2 | `decision proxy active hours start` | int | 09 | `DecisionProxyConfig` | `active_hours_start` |
| 3 | `decision proxy active hours end` | int | 22 | `DecisionProxyConfig` | `active_hours_end` |
| 4 | `decision proxy timezone` | str | America/Chicago | `DecisionProxyConfig` | `timezone` |
| 5 | `trust proxy l2 threshold` | int | 50 | `TrustTracker` | `l2_threshold` |
| 6 | `trust proxy l3 threshold` | int | 200 | `TrustTracker` | `l3_threshold` |
| 7 | `trust proxy l4 threshold` | int | 500 | `TrustTracker` | `l4_threshold` |
| 8 | `trust proxy l5 threshold` | int | 1000 | `TrustTracker` | `l5_threshold` |
| 9 | `trust proxy decay half life days` | int | 14 | `TrustTracker` | `decay_half_life_days` |
| 10 | `trust proxy rolling window days` | int | 30 | `TrustTracker` | `rolling_window_days` |
| 11 | `trust proxy circuit breaker error rate threshold` | float | 0.15 | `CircuitBreaker` | `error_rate_threshold` |
| 12 | `trust proxy circuit breaker confidence collapse threshold` | float | 0.3 | `CircuitBreaker` | `confidence_collapse_threshold` |
| 13 | `trust proxy circuit breaker auto demotion levels` | int | 2 | `CircuitBreaker` | `auto_demotion_levels` |
| 14 | `trust proxy circuit breaker recovery cooldown seconds` | int | 3600 | `CircuitBreaker` | `recovery_cooldown_seconds` |

### SWE-Specific Config (4 keys → `swe_team/proxy/config.py`)

| # | INI Key | Type | Default | Target Object | Target Param |
|---|---------|------|---------|---------------|--------------|
| 15 | `swe engineering proxy accepted senders` | csv | 3 emails | `SweProxyConfig` | `accepted_senders` |
| 16 | `swe engineering proxy deployment cap level` | int | 3 | `EngineeringStrategy` | `deployment_cap_level` |
| 17 | `swe engineering proxy destructive cap level` | int | 3 | `EngineeringStrategy` | `destructive_cap_level` |
| 18 | `swe engineering proxy architecture cap level` | int | 3 | `EngineeringStrategy` | `architecture_cap_level` |

### Trust Mode (1 key → `swe_team/job.py`)

| # | INI Key | Type | Default | Target | Notes |
|---|---------|------|---------|--------|-------|
| — | `swe team trust mode` | str | shadow | `SweTeamConfig.trust_mode` | Already in INI, not read at runtime |

### L4 Audit (1 key)

| # | INI Key | Type | Default | Target | Notes |
|---|---------|------|---------|--------|-------|
| — | `trust proxy l4 audit sample rate` | float | 0.10 | `TrustTracker` | Percentage of L4 decisions to audit |

## Factory Functions (Phase 2)

### `from_config_mgr( config_mgr )` — Generic proxy config

**Location**: `src/cosa/agents/decision_proxy/config.py`

```python
@staticmethod
def from_config_mgr( config_mgr ):
    """Read all 14 generic trust proxy INI keys into a config dict."""
    return {
        "enabled"                        : config_mgr.get_bool( "decision proxy enabled" ),
        "active_hours_start"             : config_mgr.get_int( "decision proxy active hours start" ),
        "active_hours_end"               : config_mgr.get_int( "decision proxy active hours end" ),
        "timezone"                       : config_mgr.get( "decision proxy timezone" ),
        "l2_threshold"                   : config_mgr.get_int( "trust proxy l2 threshold" ),
        # ... etc
    }
```

### `swe_proxy_config_from_config_mgr( config_mgr )` — SWE-specific config

**Location**: `src/cosa/agents/swe_team/proxy/config.py`

```python
def swe_proxy_config_from_config_mgr( config_mgr ):
    """Read 4 SWE-specific proxy INI keys."""
    return {
        "accepted_senders"     : config_mgr.get( "swe engineering proxy accepted senders" ).split( "," ),
        "deployment_cap_level" : config_mgr.get_int( "swe engineering proxy deployment cap level" ),
        # ... etc
    }
```

## Wiring Status

| Phase | What's Wired | Status |
|-------|-------------|--------|
| Phase 2 | Factory functions created | PENDING |
| Phase 2 | `trust_mode` read from INI | PENDING |
| Phase 5 | Factory outputs passed to constructors | PENDING |
