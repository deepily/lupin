#!/usr/bin/env python3
"""
Configuration for COSA SWE Team Agent.

Design decisions:
- Opus 4.6 for Lead and Architect agents (planning, extended thinking)
- Sonnet 4.5 for Coder, Reviewer, Tester, Debugger (cost optimization)
- Safety limits from architecture design doc Section 7.2
- Configurable limits to prevent runaway execution
"""

from dataclasses import dataclass, fields
from typing import Literal, Optional


@dataclass
class SweTeamConfig:
    """
    Configuration for the SWE Team multi-agent engineering system.

    Requires:
        - All numeric values must be positive
        - Model IDs must be valid Anthropic model identifiers

    Ensures:
        - Provides sensible defaults for all parameters
        - Safety limits enforced at configuration level
    """

    # === Model Selection ===
    lead_model   : str = "claude-opus-4-6"
    worker_model : str = "claude-sonnet-4-6"

    # === Execution Limits ===
    max_iterations_per_task   : int = 10
    max_tokens_per_session    : int = 500_000
    wall_clock_timeout_secs   : int = 1800
    max_consecutive_failures  : int = 3
    max_file_changes_per_task : int = 20
    require_test_pass         : bool = True

    # === Budget ===
    budget_usd : float = 5.00

    # === COSA Integration ===
    feedback_timeout_seconds : int  = 300
    narrate_progress         : bool = True

    # === User Check-In ===
    enable_checkins      : bool = True   # Pause between tasks for user input
    checkin_timeout      : int  = 30     # Seconds before auto-continue
    enable_user_messages : bool = True   # Accept user messages via WebSocket during execution

    # === Decision Proxy ===
    trust_mode : str = "shadow"    # "disabled", "shadow", "suggest", "active"

    # === Feature Flags ===
    enabled  : bool = False
    dry_run  : bool = False

    @classmethod
    def from_config( cls, config_mgr, debug=False ):
        """
        Create a SweTeamConfig from ConfigurationManager INI values.

        Reads each field from ConfigManager with "swe team" prefix,
        falling back to the dataclass default for missing keys.

        Requires:
            - config_mgr is a valid ConfigurationManager instance

        Ensures:
            - Returns a fully populated SweTeamConfig
            - Missing INI keys fall back to dataclass defaults
            - Type coercion handles str, int, bool, float

        Args:
            config_mgr: ConfigurationManager instance
            debug: Enable debug output

        Returns:
            SweTeamConfig: Configured instance
        """
        key_map = {
            "lead_model"                : "swe team lead model",
            "worker_model"              : "swe team worker model",
            "max_iterations_per_task"   : "swe team max iterations per task",
            "max_tokens_per_session"    : "swe team max tokens per session",
            "wall_clock_timeout_secs"   : "swe team wall clock timeout seconds",
            "max_consecutive_failures"  : "swe team max consecutive failures",
            "max_file_changes_per_task" : "swe team max file changes per task",
            "require_test_pass"         : "swe team require test pass",
            "budget_usd"                : "swe team budget usd",
            "feedback_timeout_seconds"  : "swe team feedback timeout seconds",
            "narrate_progress"          : "swe team narrate progress",
            "enable_checkins"           : "swe team enable checkins",
            "checkin_timeout"           : "swe team checkin timeout",
            "enable_user_messages"      : "swe team enable user messages",
            "trust_mode"                : "swe team trust mode",
            "enabled"                   : "swe team enabled",
        }

        kwargs    = {}
        dc_fields = { f.name: f for f in fields( cls ) }

        for field_name, ini_key in key_map.items():
            dc_field = dc_fields[ field_name ]
            default  = dc_field.default

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

            if debug:
                print( f"  [SweTeamConfig] {field_name} = {value} (from INI: {ini_key})" )

        return cls( **kwargs )


def quick_smoke_test():
    """Quick smoke test for SweTeamConfig."""
    import cosa.utils.util as cu

    cu.print_banner( "SweTeamConfig Smoke Test", prepend_nl=True )

    try:
        # Test 1: Default instantiation
        print( "Testing default config..." )
        config = SweTeamConfig()
        assert config.lead_model == "claude-opus-4-6"
        assert config.worker_model == "claude-sonnet-4-6"
        assert config.enabled is False
        print( "✓ Default config created" )

        # Test 2: Safety limit defaults
        print( "Testing safety limit defaults..." )
        assert config.max_iterations_per_task == 10
        assert config.max_tokens_per_session == 500_000
        assert config.wall_clock_timeout_secs == 1800
        assert config.max_consecutive_failures == 3
        assert config.max_file_changes_per_task == 20
        assert config.require_test_pass is True
        print( "✓ Safety limits have correct defaults" )

        # Test 3: Custom values
        print( "Testing custom config values..." )
        custom = SweTeamConfig(
            lead_model="custom-opus",
            worker_model="custom-sonnet",
            budget_usd=10.00,
            max_iterations_per_task=5,
            dry_run=True
        )
        assert custom.lead_model == "custom-opus"
        assert custom.budget_usd == 10.00
        assert custom.dry_run is True
        print( "✓ Custom config values work" )

        # Test 4: COSA integration defaults
        print( "Testing COSA integration..." )
        assert config.feedback_timeout_seconds == 300
        assert config.narrate_progress is True
        print( "✓ COSA integration defaults correct" )

        print( "\n✓ SweTeamConfig smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
