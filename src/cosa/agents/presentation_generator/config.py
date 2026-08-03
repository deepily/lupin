#!/usr/bin/env python3
"""
Configuration for Presentation Generator Agent.

PresentationConfig dataclass with INI-driven from_config() classmethod.
Follows PodcastConfig pattern but simpler — no nested dataclasses.
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime

import cosa.utils.util as cu


@dataclass
class PresentationConfig:
    """
    Configuration for presentation generation pipeline.

    Requires:
        - target_duration_minutes is a positive integer
        - slides_per_minute is a positive float
        - title_style is "assertion" or "topic"
        - audience is one of: beginner, general, expert, academic

    Ensures:
        - All fields have sensible defaults
        - from_config() loads from INI with type coercion
        - get_output_path() generates timestamped file paths
    """

    # Model selection
    content_model            : str   = "claude-opus-4-6"
    automated_content_model  : str   = "claude-sonnet-4-6"
    # Bounded-CC (in-process sdk_query) turn cap for each content-phase LLM call
    # (analysis/outline/elaboration/mermaid/matplotlib/d2/json). Each call is
    # single-shot; the bounded path REQUIRES an explicit max_turns.
    content_max_turns        : int   = 5

    # Presentation parameters
    target_duration_minutes  : int   = 15
    slides_per_minute        : float = 1.0
    title_style              : str   = "assertion"
    max_revisions            : int   = 3

    # Theme
    default_theme            : str   = "default"
    templates_path           : str   = "/src/cosa/agents/presentation_generator/templates/themes/"

    # Output
    output_dir_template      : str   = "io/presentations/{user}"

    # Target audience
    audience                 : str   = "general"

    # Video generation (Veo)
    veo_model                : str   = "veo-2.0-generate-001"

    # PPTX export (requires Marp CLI binary in PATH)
    pptx_export_enabled      : bool  = True

    # Fail-open review window: on timeout OR an undeliverable ask (503), each of
    # the 4 gates continues on its own via response_default rather than
    # dead-lettering the job. Mirror of the podcast script-review timeout
    # (600s = 10 min, Rick's requirement).
    review_timeout_seconds   : int   = 600

    @classmethod
    def from_config( cls, config_mgr, debug=False ):
        """
        Load PresentationConfig from INI via ConfigurationManager.

        Requires:
            - config_mgr is a valid ConfigurationManager instance

        Ensures:
            - Returns PresentationConfig with INI values or defaults
            - Type coercion applied for int/float fields

        Returns:
            PresentationConfig: Configured instance
        """
        def _get( key, default=None, return_type="str" ):
            val = config_mgr.get( f"presentation generator {key}", default=default, return_type=return_type )
            if debug: print( f"  Config: presentation generator {key} = {val}" )
            return val

        return cls(
            content_model           = _get( "content model",           default="claude-opus-4-6" ),
            automated_content_model = _get( "automated content model", default="claude-sonnet-4-6" ),
            content_max_turns       = _get( "content max turns",        default=5,     return_type="int" ),
            target_duration_minutes = _get( "target duration minutes", default=15,    return_type="int" ),
            slides_per_minute       = _get( "slides per minute",       default=1.0,   return_type="float" ),
            title_style             = _get( "title style",             default="assertion" ),
            max_revisions           = _get( "max revisions",           default=3,     return_type="int" ),
            default_theme           = _get( "default theme",           default="default" ),
            templates_path          = _get( "templates path",          default="/src/cosa/agents/presentation_generator/templates/themes/" ),
            output_dir_template     = _get( "output dir template",     default="io/presentations/{user}" ),
            audience                = _get( "audience",                default="general" ),
            veo_model               = _get( "veo model",              default="veo-2.0-generate-001" ),
            pptx_export_enabled     = _get( "pptx export enabled",    default=True, return_type="boolean" ),
            review_timeout_seconds  = _get( "review timeout seconds", default=600,  return_type="int" ),
        )

    def get_output_path( self, user_id, topic, file_type="yaml" ):
        """
        Generate output file path with timestamp and sanitized topic.

        Requires:
            - user_id is a non-empty string
            - topic is a non-empty string
            - file_type is "yaml", "md", or other extension

        Ensures:
            - Returns absolute path under project root
            - Directory path uses user_id substitution
            - Filename includes timestamp and sanitized topic

        Returns:
            str: Absolute file path
        """
        # Build output directory
        output_dir = self.output_dir_template.replace( "{user}", user_id )
        base_path  = cu.get_project_root() + "/" + output_dir

        # Sanitize topic for filename slug (4-5 words max, lowercase-hyphenated)
        sanitized = re.sub( r"[^a-zA-Z0-9 -]", "", topic.lower() ).strip()
        words     = sanitized.split()[ :5 ]
        slug      = "-".join( words ) if words else "untitled"

        # Timestamp in project convention: YYYY.MM.DD-at-HH:MM-TZ
        now = datetime.now().astimezone()
        tz_name = now.strftime( "%Z" ) or "UTC"
        timestamp = now.strftime( f"%Y.%m.%d-at-%H:%M-{tz_name}" )

        # Build filename: 2026.04.07-at-16:33-EST-strategy-and-design.yaml
        filename = f"{timestamp}-{slug}.{file_type}"

        return os.path.join( base_path, filename )


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for PresentationConfig."""
    import cosa.utils.util as cu

    cu.print_banner( "PresentationConfig Smoke Test", prepend_nl=True )

    try:
        # Test 1: Default instantiation
        print( "Testing default instantiation..." )
        config = PresentationConfig()
        assert config.content_model == "claude-opus-4-6"
        assert config.target_duration_minutes == 15
        assert config.slides_per_minute == 1.0
        assert config.title_style == "assertion"
        assert config.max_revisions == 3
        assert config.default_theme == "default"
        assert config.audience == "general"
        print( "  PASS" )

        # Test 2: get_output_path
        print( "Testing get_output_path..." )
        path = config.get_output_path( "test-user", "Three Layer Caching" )
        assert "presentations/test-user" in path
        assert "three-layer-caching" in path
        assert path.endswith( ".yaml" )
        print( f"  Path: {path}" )
        print( "  PASS" )

        # Test 3: get_output_path with md extension
        print( "Testing get_output_path with md extension..." )
        path_md = config.get_output_path( "test-user", "Test Topic", file_type="md" )
        assert path_md.endswith( ".md" )
        print( "  PASS" )

        # Test 4: from_config with real ConfigurationManager
        print( "Testing from_config with ConfigurationManager..." )
        from cosa.config.configuration_manager import ConfigurationManager
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        loaded = PresentationConfig.from_config( config_mgr, debug=True )
        assert loaded.content_model == "claude-opus-4-6"
        assert loaded.target_duration_minutes == 15
        assert loaded.slides_per_minute == 1.0
        assert loaded.title_style == "assertion"
        print( "  PASS" )

        print( "\nAll PresentationConfig smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
