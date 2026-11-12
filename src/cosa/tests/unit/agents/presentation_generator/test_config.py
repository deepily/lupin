#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.config

Target: PresentationConfig — dataclass + INI-driven from_config() +
get_output_path() path builder. ConfigurationManager is mocked; no real INI
read. get_project_root is patched so no environment dependency.
"""

from unittest.mock import MagicMock, patch

import pytest

from cosa.agents.presentation_generator import config as config_mod
from cosa.agents.presentation_generator.config import PresentationConfig


class TestDefaults:
    def test_default_fields( self ):
        cfg = PresentationConfig()
        assert cfg.content_model           == "claude-opus-4-6"
        assert cfg.automated_content_model == "claude-sonnet-4-6"
        assert cfg.target_duration_minutes == 15
        assert cfg.slides_per_minute       == 1.0
        assert cfg.title_style             == "assertion"
        assert cfg.max_revisions           == 3
        assert cfg.default_theme           == "default"
        assert cfg.audience                == "general"
        assert cfg.veo_model               == "veo-2.0-generate-001"
        assert cfg.pptx_export_enabled     is True


class TestFromConfig:
    def _mgr( self, values ):
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None, return_type="str": values.get( key, default )
        return mgr

    def test_from_config_uses_ini_values_debug( self, capsys ):
        values = {
            "presentation generator content model"           : "claude-x",
            "presentation generator target duration minutes"  : 30,
            "presentation generator slides per minute"        : 2.0,
            "presentation generator title style"              : "topic",
            "presentation generator max revisions"            : 5,
            "presentation generator pptx export enabled"      : False,
        }
        cfg = PresentationConfig.from_config( self._mgr( values ), debug=True )
        assert cfg.content_model           == "claude-x"
        assert cfg.target_duration_minutes == 30
        assert cfg.slides_per_minute       == 2.0
        assert cfg.title_style             == "topic"
        assert cfg.max_revisions           == 5
        assert cfg.pptx_export_enabled     is False
        out = capsys.readouterr().out
        assert "[PresentationConfig] title_style = topic (from INI: presentation generator title style)" in out

    def test_from_config_falls_back_to_defaults_no_debug( self ):
        cfg = PresentationConfig.from_config( self._mgr( {} ), debug=False )
        assert cfg.content_model           == "claude-opus-4-6"
        assert cfg.target_duration_minutes == 15

    def test_every_mapped_key_reaches_its_own_field( self ):
        keys   = config_mod.PRESENTATION_INI_KEYS
        values = { ini_key : f"v{i}" for i, ini_key in enumerate( keys.values() ) }
        kwargs = config_mod.load_kwargs_from_ini( PresentationConfig, self._mgr( values ), keys )
        assert len( keys ) == 16
        assert kwargs == { field : values[ ini_key ] for field, ini_key in keys.items() }

    def test_max_source_chars_reads_the_shared_unprefixed_key( self ):
        cfg = PresentationConfig.from_config( self._mgr( { "agent source content max chars": 123 } ) )
        assert cfg.max_source_chars == 123

    def test_slide_count_is_int_when_set_and_none_when_blank_or_absent( self ):
        key = "presentation generator target slide count"
        assert PresentationConfig.from_config( self._mgr( { key: "12" } ) ).target_slide_count == 12
        assert PresentationConfig.from_config( self._mgr( { key: "" } ) ).target_slide_count is None
        assert PresentationConfig.from_config( self._mgr( {} ) ).target_slide_count is None

    def test_every_default_matches_the_dataclass_default( self ):
        cfg = PresentationConfig.from_config( self._mgr( {} ) )
        assert cfg == PresentationConfig()

    def test_each_field_is_read_with_the_type_of_its_annotation( self ):
        types = {}
        mgr   = MagicMock()
        mgr.get.side_effect = lambda key, default=None, return_type="str": types.setdefault( key, return_type ) and default
        PresentationConfig.from_config( mgr )
        assert types[ "presentation generator pptx export enabled" ]   == "boolean"
        assert types[ "presentation generator slides per minute" ]     == "float"
        assert types[ "presentation generator content max turns" ]     == "int"
        assert types[ "agent source content max chars" ]               == "int"
        assert types[ "presentation generator target slide count" ]    == "string"


class TestGetOutputPath:
    def test_normal_slug( self ):
        cfg = PresentationConfig()
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            path = cfg.get_output_path( "user@x.com", "Three Layer Caching System Design Doc" )
        assert "/proj/io/presentations/user@x.com" in path
        # only first 5 words kept
        assert "three-layer-caching-system-design" in path
        assert path.endswith( ".yaml" )

    def test_md_file_type( self ):
        cfg = PresentationConfig()
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            path = cfg.get_output_path( "u", "Topic", file_type="md" )
        assert path.endswith( ".md" )

    def test_empty_topic_yields_untitled( self ):
        cfg = PresentationConfig()
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            path = cfg.get_output_path( "u", "!!!@@@###" )   # all stripped → no words
        assert "untitled" in path

    def test_empty_timezone_falls_back_to_utc( self ):
        cfg = PresentationConfig()
        fake_now = MagicMock()
        def strftime( fmt ):
            if fmt == "%Z":
                return ""   # empty tz → triggers `or "UTC"`
            return f"2026.01.01-at-00:00-{fmt.split( '-' )[ -1 ]}"
        fake_now.strftime.side_effect = strftime
        fake_dt = MagicMock()
        fake_dt.now.return_value.astimezone.return_value = fake_now
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch.object( config_mod, "datetime", fake_dt ):
            path = cfg.get_output_path( "u", "Topic" )
        # the format string carried "UTC" as tz_name
        assert "UTC" in path


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
