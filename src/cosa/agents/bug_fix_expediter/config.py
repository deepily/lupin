"""
Configuration for the Bug Fix Expediter agent.

Follows the SweTeamConfig pattern for INI-driven configuration
with from_config() classmethod.
"""

from dataclasses import dataclass, fields
from typing import Optional


@dataclass
class BugFixExpediterConfig:
    """
    Configuration for the Bug Fix Expediter agent.

    Requires:
        - All numeric values must be positive

    Ensures:
        - Provides sensible defaults for all parameters
        - from_config() loads values from ConfigurationManager INI
    """

    # === Model Selection ===
    lead_model                : str   = "claude-opus-4-6"
    worker_model              : str   = "claude-sonnet-4-6"

    # === Extended thinking ===
    # Per-invocation override (via job param or API request body). None = SDK default.
    # Accepts: "low" | "medium" | "high" | "xhigh" | "max" | None.
    # Forwarded to ClaudeAgentOptions.effort in the orchestrator.
    thinking_effort           : Optional[ str ] = None

    # === Execution Limits ===
    max_diagnosis_iterations  : int   = 3
    min_diagnosis_confidence  : float = 0.7
    max_fix_attempts          : int   = 2
    max_file_changes_per_fix  : int   = 20
    wall_clock_timeout_secs   : int   = 600

    # === Budget ===
    budget_usd                : float = 2.00

    # === COSA Integration ===
    feedback_timeout_seconds  : int   = 300
    narrate_progress          : bool  = True

    # === Retry Behavior ===
    auto_retry_on_fix         : bool  = False
    require_user_confirm      : bool  = True

    # === Decision Proxy (Phase 5) ===
    trust_mode                : str   = "shadow"   # "shadow" | "suggest" | "active"

    # === Feature Flags ===
    enabled                   : bool  = False

    @classmethod
    def from_config( cls, config_mgr, debug=False ):
        """
        Create a BugFixExpediterConfig from ConfigurationManager INI values.

        Requires:
            - config_mgr is a valid ConfigurationManager instance

        Ensures:
            - Returns BugFixExpediterConfig with INI values or defaults
            - Type coercion applied based on field type annotations

        Args:
            config_mgr: ConfigurationManager instance
            debug: Enable debug output

        Returns:
            BugFixExpediterConfig: Configured instance
        """
        key_map = {
            "lead_model"               : "bug fix expediter lead model",
            "worker_model"             : "bug fix expediter worker model",
            "max_diagnosis_iterations" : "bug fix expediter max diagnosis iterations",
            "min_diagnosis_confidence" : "bug fix expediter min diagnosis confidence",
            "max_fix_attempts"         : "bug fix expediter max fix attempts",
            "max_file_changes_per_fix" : "bug fix expediter max file changes per fix",
            "wall_clock_timeout_secs"  : "bug fix expediter wall clock timeout seconds",
            "budget_usd"               : "bug fix expediter budget usd",
            "feedback_timeout_seconds" : "bug fix expediter feedback timeout seconds",
            "narrate_progress"         : "bug fix expediter narrate progress",
            "auto_retry_on_fix"        : "bug fix expediter auto retry on fix",
            "require_user_confirm"     : "bug fix expediter require user confirm",
            "trust_mode"               : "bug fix expediter trust mode",
            "enabled"                  : "bug fix expediter enabled",
        }

        kwargs    = {}
        dc_fields = { f.name: f for f in fields( cls ) }

        for field_name, ini_key in key_map.items():
            dc_field   = dc_fields[ field_name ]
            default    = dc_field.default
            field_type = dc_field.type

            if field_type == "bool" or field_type is bool:
                return_type = "boolean"
            elif field_type == "int" or field_type is int:
                return_type = "int"
            elif field_type == "float" or field_type is float:
                return_type = "float"
            else:
                return_type = "string"

            value = config_mgr.get( ini_key, default=default, return_type=return_type )
            kwargs[ field_name ] = value

            if debug: print( f"  [BugFixExpediterConfig] {field_name} = {value} (from INI: {ini_key})" )

        return cls( **kwargs )


def quick_smoke_test():
    """Quick smoke test for BugFixExpediterConfig."""
    import cosa.utils.util as cu

    cu.print_banner( "BugFixExpediterConfig Smoke Test", prepend_nl=True )

    try:
        # 1: Default instantiation
        config = BugFixExpediterConfig()
        assert config.lead_model == "claude-opus-4-6"
        assert config.worker_model == "claude-sonnet-4-6"
        assert config.max_fix_attempts == 2
        assert config.enabled == False
        assert config.trust_mode == "shadow"
        print( "✓ Default config values correct (trust_mode=shadow)" )

        # 2: Custom values
        config = BugFixExpediterConfig( lead_model="custom-model", budget_usd=10.0, enabled=True )
        assert config.lead_model == "custom-model"
        assert config.budget_usd == 10.0
        assert config.enabled == True
        print( "✓ Custom config values work" )

        # 3: from_config (wrapped — may fail without INI keys)
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            config = BugFixExpediterConfig.from_config( config_mgr, debug=True )
            print( f"✓ from_config loaded (lead={config.lead_model})" )
        except Exception as e:
            print( f"⚠ from_config skipped (INI keys may not exist yet): {e}" )

        print( "\n✓ BugFixExpediterConfig smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
