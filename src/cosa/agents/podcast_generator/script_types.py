#!/usr/bin/env python3
"""
Script-type profiles for the podcast generator.

Each type is a frozen profile: prompts, length, analysis kind and review default.
Precedence for any value is request, then profile, then INI.
"""

from dataclasses import dataclass
from typing import Optional

from .config import PodcastConfig
from .prompts.script_generation import CONTENT_ANALYSIS_SYSTEM_PROMPT, SCRIPT_GENERATION_SYSTEM_PROMPT
from .prompts.status_report import STATUS_DIGEST_SYSTEM_PROMPT, STATUS_REPORT_SYSTEM_PROMPT

RESEARCH_CRITICAL = "research_critical"
STATUS_REPORT     = "status_report"
DEFAULT_TYPE      = RESEARCH_CRITICAL

REVIEW_ASK      = "ask"
REVIEW_ONE_SHOT = "one_shot"
REVIEW_MODES    = ( REVIEW_ASK, REVIEW_ONE_SHOT )

ANALYSIS_RESEARCH = "research"
ANALYSIS_DIGEST   = "status_digest"

# Fallbacks used when the INI key is absent; they match lupin-app.ini.
STATUS_DEFAULT_DURATION  = 5
STATUS_DEFAULT_MIN       = 6
STATUS_DEFAULT_MAX       = 10
STATUS_DEFAULT_AUDIENCE  = "general"


@dataclass( frozen=True )
class ScriptTypeProfile:
    """
    One script type: what it writes, how it analyses and whether it stops for review.

    The ini_* fields name the INI keys that hold the type's numbers. None means the
    type uses the generic podcast keys that PodcastConfig.from_config already read.
    """

    name                   : str
    review_default         : str
    analysis_kind          : str
    system_prompt          : str
    analysis_system_prompt : str
    ini_duration_key       : Optional[ str ] = None
    ini_min_key            : Optional[ str ] = None
    ini_max_key            : Optional[ str ] = None
    ini_audience_key       : Optional[ str ] = None


PROFILES = {
    RESEARCH_CRITICAL : ScriptTypeProfile(
        name                   = RESEARCH_CRITICAL,
        review_default         = REVIEW_ASK,
        analysis_kind          = ANALYSIS_RESEARCH,
        system_prompt          = SCRIPT_GENERATION_SYSTEM_PROMPT,
        analysis_system_prompt = CONTENT_ANALYSIS_SYSTEM_PROMPT,
    ),
    STATUS_REPORT : ScriptTypeProfile(
        name                   = STATUS_REPORT,
        review_default         = REVIEW_ONE_SHOT,
        analysis_kind          = ANALYSIS_DIGEST,
        system_prompt          = STATUS_REPORT_SYSTEM_PROMPT,
        analysis_system_prompt = STATUS_DIGEST_SYSTEM_PROMPT,
        ini_duration_key       = "podcast status report target duration minutes",
        ini_min_key            = "podcast status report min exchanges",
        ini_max_key            = "podcast status report max exchanges",
        ini_audience_key       = "podcast status report audience",
    ),
}


def get_profile( script_type: Optional[ str ] ) -> ScriptTypeProfile:
    """
    Look up a profile by name, refusing an unknown name.

    Requires:
        - script_type is a profile name, or None for the default type

    Raises:
        - ValueError naming the unknown type and the valid ones
    """
    name = DEFAULT_TYPE if script_type is None else script_type
    if name not in PROFILES:
        raise ValueError( f"Unknown script_type {script_type!r}; valid types: {', '.join( PROFILES )}" )
    return PROFILES[ name ]


def validate_review( review: Optional[ str ] ) -> Optional[ str ]:
    """
    Return review unchanged when it is None or a known mode.

    Raises:
        - ValueError naming the unknown mode and the valid ones
    """
    if review is not None and review not in REVIEW_MODES:
        raise ValueError( f"Unknown review {review!r}; valid modes: {', '.join( REVIEW_MODES )}" )
    return review


def effective_review( config: PodcastConfig ) -> str:
    """
    Return the review mode a config runs with: its own, else its profile's default.

    Raises:
        - ValueError when config.script_type or config.review is unknown
    """
    review = validate_review( config.review )
    return review if review is not None else get_profile( config.script_type ).review_default


def resolve_podcast_config(
    config_mgr,
    script_type      : Optional[ str ] = None,
    review           : Optional[ str ] = None,
    audience         : Optional[ str ] = None,
    audience_context : Optional[ str ] = None,
    debug            : bool = False,
) -> PodcastConfig:
    """
    Build a PodcastConfig from the INI and apply the script type and the request.

    Requires:
        - config_mgr is a ConfigurationManager

    Ensures:
        - request values beat profile values, and profile values beat the INI
        - the returned config carries the resolved script_type and a concrete review mode

    Raises:
        - ValueError when script_type or review is unknown
    """
    profile = get_profile( script_type )
    review  = validate_review( review )
    config  = PodcastConfig.from_config( config_mgr, debug=debug )

    def _read( key, default, rtype ):
        return config_mgr.get( key, default=str( default ), silent=True, return_type=rtype )

    if profile.ini_duration_key is not None:
        config.target_duration_minutes = _read( profile.ini_duration_key, STATUS_DEFAULT_DURATION, "int" )
        config.min_exchanges           = _read( profile.ini_min_key,      STATUS_DEFAULT_MIN,      "int" )
        config.max_exchanges           = _read( profile.ini_max_key,      STATUS_DEFAULT_MAX,      "int" )
        config.audience                = _read( profile.ini_audience_key, STATUS_DEFAULT_AUDIENCE, "string" )

    if audience:         config.audience         = audience
    if audience_context: config.audience_context = audience_context

    config.script_type = profile.name
    config.review      = review if review is not None else profile.review_default
    return config
