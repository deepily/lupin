#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.config

Targets: HostPersonality / VoiceProfile / PodcastConfig dataclasses, their
from_config INI builders, the get_output_path path/slug logic, and the
LANGUAGE_NAMES constant.

ConfigurationManager is replaced by a faithful fake that honours the
return_type coercion (int/float/boolean/string) so NO real config file is read.
quick_smoke_test() and __main__ are coverage-excluded.
"""

import re

import pytest

import cosa.utils.util as cu

from cosa.agents.shared.config_loader import load_kwargs_from_ini
from cosa.agents.podcast_generator.config import (
    HostPersonality,
    VoiceProfile,
    PodcastConfig,
    PODCAST_INI_KEYS,
    LANGUAGE_NAMES,
    DEFAULT_CURIOUS_HOST,
    DEFAULT_EXPERT_HOST,
)


EXPECTED_PODCAST_KEYS = {
    "script_model"                   : "podcast script model",
    "target_duration_minutes"        : "podcast target duration minutes",
    "min_exchanges"                  : "podcast min exchanges",
    "min_spanish_stopword_ratio"     : "podcast translation min spanish stopword ratio",
    "max_exchanges"                  : "podcast max exchanges",
    "script_max_turns"               : "podcast script max turns",
    "include_intro"                  : "podcast include intro",
    "include_outro"                  : "podcast include outro",
    "prosody_annotation_level"       : "podcast prosody annotation level",
    "max_research_doc_tokens"        : "podcast max research doc tokens",
    "max_source_chars"               : "agent source content max chars",
    "key_topics_to_extract"          : "podcast key topics to extract",
    "examples_per_topic"             : "podcast examples per topic",
    "max_script_revisions"           : "podcast max script revisions",
    "feedback_timeout_seconds"       : "podcast feedback timeout seconds",
    "script_review_timeout_seconds"  : "podcast script review timeout seconds",
    "output_dir_template"            : "podcast output dir template",
    "script_filename_template"       : "podcast script filename template",
    "audio_filename_template"        : "podcast audio filename template",
    "audio_format"                   : "podcast audio format",
    "audio_bitrate"                  : "podcast audio bitrate",
    "silence_between_speakers_ms"    : "podcast silence between speakers ms",
    "audience"                       : "podcast generator audience",
    "stream_thoughts_to_voice"       : "podcast stream thoughts to voice",
    "narrate_progress"               : "podcast narrate progress",
    "publish_to_google_drive"        : "podcast publish to google drive",
    "drive_folder_name"              : "podcast drive folder name",
    "drive_upload_script"            : "podcast drive upload script",
    "drive_upload_source_document"   : "podcast drive upload source document",
    "drive_token_path"               : "podcast drive token path",
    "drive_upload_users"             : "podcast drive upload users",
}


class FakeCfg:
    """
    Minimal ConfigurationManager stand-in.

    Mirrors the real get(key, default, silent, return_type) coercion contract
    used across config.py, and exists(key) for the use_speaker_boost guard.
    """

    def __init__( self, values=None, exists_keys=None ):
        self.values      = values or {}
        self.exists_keys = exists_keys or set()

    def get( self, key, default=None, silent=False, return_type="string" ):
        raw = self.values.get( key, default )
        if return_type == "int":     return int( raw )
        if return_type == "float":   return float( raw )
        if return_type == "boolean": return str( raw ).lower() in ( "true", "1", "yes" )
        return raw

    def exists( self, key ):
        return key in self.exists_keys


# ----------------------------------------------------------------------------
# HostPersonality
# ----------------------------------------------------------------------------
class TestHostPersonality:
    """
    HostPersonality rendering + INI construction.

    Ensures to_prompt_description renders phrases (and the 'none specified'
    fallback), and from_config parses pipe-delimited phrases with/without a
    value plus the debug print.
    """

    def test_to_prompt_description_with_phrases( self ):
        hp = HostPersonality( name="Nora", role="Curious", typical_phrases=[ "Wait...", "Fascinating!" ] )
        desc = hp.to_prompt_description()
        assert "Host: Nora" in desc
        assert "Role: Curious" in desc
        assert "Typical Phrases: Wait..., Fascinating!" in desc

    def test_to_prompt_description_without_phrases( self ):
        hp = HostPersonality( name="Nora", role="Curious", typical_phrases=[] )
        assert "Typical Phrases: none specified" in hp.to_prompt_description()

    def test_from_config_parses_pipe_phrases_and_debug( self, capsys ):
        cfg = FakeCfg( values={
            "podcast host a name"            : "Ada",
            "podcast host a role"            : "Host",
            "podcast host a typical phrases" : "one | two |  | three",
        } )
        hp = HostPersonality.from_config( cfg, prefix="podcast host a", debug=True )
        assert hp.name == "Ada"
        assert hp.typical_phrases == [ "one", "two", "three" ]   # blanks stripped
        assert "[HostPersonality.from_config] Loaded podcast host a: Ada" in capsys.readouterr().out

    def test_from_config_empty_phrases_defaults_to_empty_list( self ):
        cfg = FakeCfg()   # all defaults; phrases default "" -> []
        hp = HostPersonality.from_config( cfg, prefix="podcast host b" )
        assert hp.typical_phrases == []
        assert hp.name == "Host"


# ----------------------------------------------------------------------------
# VoiceProfile
# ----------------------------------------------------------------------------
class TestVoiceProfile:
    """
    VoiceProfile validation + INI construction.

    Ensures __post_init__ range asserts (valid passes; out-of-range raises) and
    from_config coerces floats + resolves use_speaker_boost via the exists guard.
    """

    def test_valid_profile_constructs( self ):
        vp = VoiceProfile( voice_id="abc", stability=0.5, similarity_boost=0.5, style=0.5 )
        assert vp.use_speaker_boost is True

    @pytest.mark.parametrize( "field,bad", [
        ( "stability",        1.5 ),
        ( "similarity_boost", -0.1 ),
        ( "style",            2.0 ),
    ] )
    def test_out_of_range_raises_assertion( self, field, bad ):
        kwargs = dict( voice_id="abc", stability=0.5, similarity_boost=0.5, style=0.5 )
        kwargs[ field ] = bad
        with pytest.raises( AssertionError ):
            VoiceProfile( **kwargs )

    def test_from_config_with_explicit_speaker_boost_key( self, capsys ):
        cfg = FakeCfg(
            values={
                "podcast voice female id"                : "VID123456789",
                "podcast voice female stability"         : "0.5",
                "podcast voice female use speaker boost" : "False",
            },
            exists_keys={ "podcast voice female use speaker boost" },
        )
        vp = VoiceProfile.from_config( cfg, prefix="podcast voice female", debug=True )
        assert vp.voice_id          == "VID123456789"
        assert vp.stability         == 0.5
        assert vp.use_speaker_boost is False                    # exists -> read boolean
        assert "[VoiceProfile.from_config] Loaded" in capsys.readouterr().out

    def test_from_config_without_speaker_boost_key_defaults_true( self ):
        cfg = FakeCfg( values={ "podcast voice male id": "X" } )   # key absent in exists
        vp = VoiceProfile.from_config( cfg, prefix="podcast voice male" )
        assert vp.use_speaker_boost is True                     # exists False -> default True


# ----------------------------------------------------------------------------
# PodcastConfig basics
# ----------------------------------------------------------------------------
class TestPodcastConfigBasics:
    """
    PodcastConfig defaults + host-name accessors + LANGUAGE_NAMES.
    """

    def test_defaults_and_host_names( self ):
        cfg = PodcastConfig()
        assert cfg.script_model            == "claude-opus-4-6"
        assert cfg.target_duration_minutes == 10
        assert cfg.audience                == "academic"
        assert cfg.target_languages        == [ "en" ]
        assert cfg.get_host_a_name()       == "Maria"
        assert cfg.get_host_b_name()       == "Mr. Radio"
        # default factories produce the module-level singletons' values
        assert cfg.host_a_personality.name == DEFAULT_CURIOUS_HOST.name
        assert cfg.host_b_personality.name == DEFAULT_EXPERT_HOST.name

    def test_language_names_constant( self ):
        assert LANGUAGE_NAMES[ "en" ]    == "English"
        assert LANGUAGE_NAMES[ "es-MX" ] == "Mexican Spanish"


# ----------------------------------------------------------------------------
# PodcastConfig.get_output_path
# ----------------------------------------------------------------------------
class TestGetOutputPath:
    """
    get_output_path slug sanitization + language-suffix logic.

    Ensures script vs audio templates, English (no suffix) vs non-English
    (suffix inserted before extension), and special-char slug cleanup.
    """

    def _cfg( self ):
        return PodcastConfig()

    def test_script_english_no_suffix( self ):
        with _patch_root( "/proj" ):
            path = self._cfg().get_output_path( user_id="u@test.com", topic="Quantum Computing", file_type="script", language="en" )
        assert path.startswith( "/proj/io/podcasts/u@test.com/" )
        assert path.endswith( "-script.md" )
        assert "quantum-computing" in path

    def test_script_non_english_inserts_suffix( self ):
        with _patch_root( "/proj" ):
            path = self._cfg().get_output_path( user_id="u@test.com", topic="Quantum", file_type="script", language="es-MX" )
        assert path.endswith( "-script-es-MX.md" )

    def test_audio_english_no_suffix( self ):
        with _patch_root( "/proj" ):
            path = self._cfg().get_output_path( user_id="u@test.com", topic="Quantum", file_type="audio", language="en" )
        assert path.endswith( ".mp3" )
        assert "-en.mp3" not in path

    def test_audio_non_english_inserts_suffix( self ):
        with _patch_root( "/proj" ):
            path = self._cfg().get_output_path( user_id="u@test.com", topic="Quantum", file_type="audio", language="es" )
        assert path.endswith( "-es.mp3" )

    def test_special_chars_sanitized( self ):
        with _patch_root( "/proj" ):
            path = self._cfg().get_output_path(
                user_id="u@test.com",
                topic="Voice Computing: From Sci-Fi? To Reality!!!",
                file_type="script",
            )
        assert ":" not in path and "?" not in path and "!" not in path
        assert "voice-computing-from-sci-fi-to-reality" in path

    def test_tab_and_newline_become_hyphens_not_part_of_the_file_name( self ):
        with _patch_root( "/proj" ):
            path = self._cfg().get_output_path( user_id="u@test.com", topic="tab\there\nand more", file_type="script" )
        name = path.rsplit( "/", 1 )[ -1 ]
        assert "\t" not in name and "\n" not in name
        assert name.endswith( "-tab-here-and-more-script.md" )


# ----------------------------------------------------------------------------
# PodcastConfig.from_config
# ----------------------------------------------------------------------------
class TestPodcastConfigFromConfig:
    """
    PodcastConfig.from_config composes nested objects + typed reads from INI.

    Ensures defaults flow through coercion, comma-separated languages parse,
    audience_context resolves (value vs empty->None), and debug prints.
    """

    def test_defaults_flow_through( self, capsys ):
        cfg = FakeCfg()   # everything defaults
        config = PodcastConfig.from_config( cfg, debug=True )
        assert config.script_model            == "claude-opus-4-6"
        assert config.target_duration_minutes == 10           # "10" -> int
        assert config.include_intro is True                   # "True" -> boolean
        assert config.target_languages        == [ "en" ]
        assert config.audience_context        is None          # empty -> None
        assert config.host_a_personality.name == "Host"        # from FakeCfg defaults
        assert "[PodcastConfig.from_config] Loaded config" in capsys.readouterr().out

    def test_comma_separated_languages_and_audience_context( self ):
        cfg = FakeCfg( values={
            "podcast target languages"               : "en, es-MX , , fr",
            "podcast generator audience context"     : "ML architects",
            "podcast target duration minutes"        : "25",
        } )
        config = PodcastConfig.from_config( cfg )
        assert config.target_languages        == [ "en", "es-MX", "fr" ]   # blanks dropped
        assert config.audience_context        == "ML architects"
        assert config.target_duration_minutes == 25

    def test_every_default_matches_the_dataclass_default( self ):
        config   = PodcastConfig.from_config( FakeCfg() )
        expected = PodcastConfig()
        for field_name in PODCAST_INI_KEYS:
            assert getattr( config, field_name ) == getattr( expected, field_name ), field_name

    def test_every_mapped_key_reaches_its_own_field( self ):
        assert len( PODCAST_INI_KEYS ) == 31
        values = {}
        for i, ( field_name, ini_key ) in enumerate( PODCAST_INI_KEYS.items() ):
            values[ ini_key ] = f"v{i}"
        raw = load_kwargs_from_ini( PodcastConfig, RawCfg( values ), PODCAST_INI_KEYS, silent=True )
        assert raw == { field_name : values[ ini_key ] for field_name, ini_key in PODCAST_INI_KEYS.items() }

    def test_max_source_chars_reads_the_shared_unprefixed_key( self ):
        config = PodcastConfig.from_config( FakeCfg( values={ "agent source content max chars": "123" } ) )
        assert config.max_source_chars == 123

    def test_every_read_is_silent( self ):
        seen = []
        class SilentSpy( FakeCfg ):
            def get( self, key, default=None, silent=False, return_type="string" ):
                if key in PODCAST_INI_KEYS.values(): seen.append( silent )
                return super().get( key, default=default, silent=silent, return_type=return_type )
        PodcastConfig.from_config( SilentSpy() )
        assert len( seen ) == 31
        assert all( seen )


class RawCfg:
    """Returns each key's value as stored, ignoring the requested type."""

    def __init__( self, values ):
        self.values = values

    def get( self, key, default=None, silent=False, return_type="string" ):
        return self.values[ key ]


# ----------------------------------------------------------------------------
# get_project_root patch helper
# ----------------------------------------------------------------------------
import contextlib
from unittest.mock import patch


@contextlib.contextmanager
def _patch_root( root ):
    with patch( "cosa.utils.util.get_project_root", return_value=root ):
        yield


def test_podcast_keys_are_the_literal_strings():
    assert PODCAST_INI_KEYS == EXPECTED_PODCAST_KEYS


def test_podcast_keys_exist_in_the_real_ini():
    ini_text = open( cu.get_project_root() + "/src/conf/lupin-app.ini" ).read()
    for ini_key in EXPECTED_PODCAST_KEYS.values():
        assert re.search( r"^" + re.escape( ini_key ) + r"\s*=", ini_text, re.M ), ini_key
