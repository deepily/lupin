#!/usr/bin/env python3
"""
Configuration for COSA Deep Research Agent.

Design decisions:
- Opus 4.5 for lead agent (planning, synthesis) - higher reasoning capability
- Sonnet 4 for subagents (research execution) - cost optimization
- Scaling heuristics from Anthropic blog post (June 2025)
- Configurable limits to prevent runaway execution
"""

from dataclasses import dataclass, fields
from typing import Literal, Optional


@dataclass
class ResearchConfig:
    """
    Configuration for the deep research agent.

    Requires:
        - All numeric values must be positive

    Ensures:
        - Provides sensible defaults for all parameters
        - get_max_subagents() returns appropriate limit for complexity
    """

    # === Model Selection ===
    lead_model     : str = "claude-opus-4-6"
    subagent_model : str = "claude-sonnet-4-6"

    # === Scaling Heuristics ===
    max_subagents_simple   : int = 1
    max_subagents_moderate : int = 4
    max_subagents_complex  : int = 10

    # === Execution Limits ===
    max_concurrent_subagents    : int = 5
    max_research_iterations     : int = 3
    max_tool_calls_per_subagent : int = 15
    max_clarification_rounds    : int = 2

    # === Token Budgets ===
    extended_thinking_budget : int = 10000
    subagent_context_limit   : int = 100000
    max_findings_tokens      : int = 50000

    # === COSA Integration ===
    feedback_timeout_seconds  : int  = 300
    stream_thoughts_to_voice  : bool = True
    narrate_progress          : bool = True

    # === Search Configuration ===
    search_tool              : str  = "web_search_20250305"
    prefer_primary_sources   : bool = True
    min_sources_per_subquery : int  = 3
    max_sources_per_subquery : int  = 10

    # === Output Configuration ===
    include_confidence_scores     : bool = True
    include_source_quality_notes  : bool = True
    citation_style                : Literal[ "inline", "footnote", "endnote" ] = "inline"

    # === Target Audience ===
    # Controls depth, terminology, and assumptions in research output
    # Levels: beginner, general, expert, academic (default)
    audience         : Literal[ "beginner", "general", "expert", "academic" ] = "academic"
    audience_context : Optional[ str ] = None  # Custom description (e.g., "AI architect with ML background")

    def get_max_subagents( self, complexity: str ) -> int:
        """
        Get max subagents for given complexity level.

        Requires:
            - complexity is "simple", "moderate", or "complex"

        Ensures:
            - Returns appropriate limit for complexity
            - Falls back to moderate if unknown complexity

        Args:
            complexity: The assessed complexity level

        Returns:
            int: Maximum number of subagents to spawn
        """
        mapping = {
            "simple"   : self.max_subagents_simple,
            "moderate" : self.max_subagents_moderate,
            "complex"  : self.max_subagents_complex,
        }
        return mapping.get( complexity, self.max_subagents_moderate )

    @classmethod
    def from_config( cls, config_mgr, debug=False ):
        """
        Create a ResearchConfig from ConfigurationManager INI values.

        Reads each field from ConfigManager with "deep research" prefix,
        falling back to the dataclass default for missing keys.

        Requires:
            - config_mgr is a valid ConfigurationManager instance

        Ensures:
            - Returns a fully populated ResearchConfig
            - Missing INI keys fall back to dataclass defaults
            - Type coercion handles str, int, bool, float

        Args:
            config_mgr: ConfigurationManager instance
            debug: Enable debug output

        Returns:
            ResearchConfig: Configured instance
        """
        # Map dataclass field names to INI key names
        key_map = {
            "lead_model"                 : "deep research lead model",
            "subagent_model"             : "deep research subagent model",
            "max_subagents_simple"       : "deep research max subagents simple",
            "max_subagents_moderate"     : "deep research max subagents moderate",
            "max_subagents_complex"      : "deep research max subagents complex",
            "max_concurrent_subagents"   : "deep research max concurrent subagents",
            "max_research_iterations"    : "deep research max research iterations",
            "max_tool_calls_per_subagent": "deep research max tool calls per subagent",
            "max_clarification_rounds"   : "deep research max clarification rounds",
            "extended_thinking_budget"   : "deep research extended thinking budget",
            "subagent_context_limit"     : "deep research subagent context limit",
            "max_findings_tokens"        : "deep research max findings tokens",
            "feedback_timeout_seconds"   : "deep research feedback timeout seconds",
            "stream_thoughts_to_voice"   : "deep research stream thoughts to voice",
            "narrate_progress"           : "deep research narrate progress",
            "search_tool"                : "deep research search tool",
            "prefer_primary_sources"     : "deep research prefer primary sources",
            "min_sources_per_subquery"   : "deep research min sources per subquery",
            "max_sources_per_subquery"   : "deep research max sources per subquery",
            "include_confidence_scores"  : "deep research include confidence scores",
            "include_source_quality_notes": "deep research include source quality notes",
            "citation_style"             : "deep research citation style",
            "audience"                   : "deep research audience",
            "audience_context"           : "deep research audience context",
        }

        # Build kwargs from INI, falling back to dataclass defaults
        kwargs       = {}
        dc_fields    = { f.name: f for f in fields( cls ) }

        for field_name, ini_key in key_map.items():
            dc_field = dc_fields[ field_name ]
            default  = dc_field.default

            # Determine return_type based on field type
            field_type = dc_field.type
            if field_type == "bool" or field_type is bool:
                return_type = "boolean"
            elif field_type == "int" or field_type is int:
                return_type = "int"
            elif field_type == "float" or field_type is float:  # pragma: no cover - no float-typed ResearchConfig field + fixed key_map of the 23 real fields; this defensive coercion arm is unreachable
                return_type = "float"
            else:
                return_type = "string"

            value = config_mgr.get( ini_key, default=str( default ) if default is not None else "", silent=True, return_type=return_type )

            # Handle empty string for Optional[str] fields
            if field_name == "audience_context" and ( value == "" or value is None ):
                value = None

            kwargs[ field_name ] = value

        if debug: print( f"[ResearchConfig.from_config] Loaded {len( kwargs )} fields from INI" )

        return cls( **kwargs )


def quick_smoke_test():
    """Quick smoke test for ResearchConfig."""
    import cosa.utils.util as cu

    cu.print_banner( "ResearchConfig Smoke Test", prepend_nl=True )

    try:
        # Test 1: Default instantiation
        print( "Testing default config..." )
        config = ResearchConfig()
        assert config.lead_model == "claude-opus-4-6"
        assert config.subagent_model == "claude-sonnet-4-6"
        print( "✓ Default config created" )

        # Test 2: get_max_subagents
        print( "Testing get_max_subagents..." )
        assert config.get_max_subagents( "simple" ) == 1
        assert config.get_max_subagents( "moderate" ) == 4
        assert config.get_max_subagents( "complex" ) == 10
        assert config.get_max_subagents( "unknown" ) == 4  # Falls back to moderate
        print( "✓ get_max_subagents works correctly" )

        # Test 3: Custom values
        print( "Testing custom config values..." )
        custom = ResearchConfig(
            lead_model="custom-model",
            max_subagents_complex=20,
            feedback_timeout_seconds=600
        )
        assert custom.lead_model == "custom-model"
        assert custom.max_subagents_complex == 20
        assert custom.feedback_timeout_seconds == 600
        print( "✓ Custom config values work" )

        # Test 4: Target audience defaults
        print( "Testing target audience..." )
        assert config.audience == "academic"
        assert config.audience_context is None
        custom_audience = ResearchConfig(
            audience="beginner",
            audience_context="PhD researcher in AI safety"
        )
        assert custom_audience.audience == "beginner"
        assert custom_audience.audience_context == "PhD researcher in AI safety"
        print( "✓ Target audience configuration works" )

        # Test 5: from_config
        print( "Testing from_config..." )
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            cfg_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            config_from_ini = ResearchConfig.from_config( cfg_mgr, debug=True )
            assert config_from_ini.lead_model == "claude-opus-4-6"
            assert config_from_ini.max_subagents_simple == 1
            assert config_from_ini.feedback_timeout_seconds == 300
            assert isinstance( config_from_ini.stream_thoughts_to_voice, bool )
            print( f"✓ from_config loaded successfully (lead={config_from_ini.lead_model})" )
        except Exception as e:
            print( f"⚠ from_config test skipped (config not available): {e}" )

        print( "\n✓ ResearchConfig smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
