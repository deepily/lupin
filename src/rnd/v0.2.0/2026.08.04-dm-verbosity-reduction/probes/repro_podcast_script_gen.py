"""
Reproduce bug e0bb5a94 defect A — "no recoverable JSON object" at podcast script gen.

HYPOTHESIS TO TEST (not to assume): the SDK cuts the response off at max_turns, the
API layer records that in `stop_reason` and NOBODY READS IT, so a TRUNCATED body
reaches a parser that needs a balanced {...} and reports the symptom
("no recoverable JSON") instead of the cause ("the response was cut off").

This probe calls the real script stage and prints what every layer actually saw.
It asserts nothing — it reports, so the evidence decides.
"""
import asyncio, sys, json
sys.path.insert( 0, "src" )

from cosa.agents.podcast_generator.api_client import PodcastAPIClient
from cosa.agents.podcast_generator.config     import PodcastConfig
from cosa.agents.podcast_generator.prompts.script_generation import (
    SCRIPT_GENERATION_SYSTEM_PROMPT, get_script_generation_prompt, parse_script_response,
)
from cosa.agents.podcast_generator.prompts.personality import get_dynamic_duo_description

RESEARCH = ( """
# The Two-Threshold Collision

When two independent limits are set to the same number, the population that survives
one of them is silently selected by the other. This document walks through a concrete
case observed in a message-quality pipeline, why it made an arm comparison unsound,
and what the general lesson is for anyone setting thresholds in a measurement system.
""" + ( "\nA supporting paragraph that adds real substance to the source material so the "
        "script model has enough to talk about across a full-length episode.\n" ) * 40 )

ANALYSIS = {
    "main_topic"                 : "Threshold collisions in measurement systems",
    "key_subtopics"              : [ "selection effects", "arm comparability", "instrument design" ],
    "interesting_facts"          : [ "both arms scored 96.5% under the ceiling" ],
    "discussion_questions"       : [ "when is a filter also a measurement?" ],
    "analogies_suggested"        : [ "a net that sets its own mesh" ],
    "target_audience"            : "engineers",
    "complexity_level"           : "intermediate",
    "estimated_coverage_minutes" : 10.0,
}


async def main():
    from cosa.config.configuration_manager import ConfigurationManager
    cfg    = PodcastConfig.from_config( ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ) )
    client = PodcastAPIClient( config=cfg, debug=True )

    print( f"  config: script_model={cfg.script_model}  script_max_turns={cfg.script_max_turns}" )
    print( f"  target_duration={cfg.target_duration_minutes}min  exchanges={cfg.min_exchanges}-{cfg.max_exchanges}" )
    print()

    system = SCRIPT_GENERATION_SYSTEM_PROMPT + "\n\n" + get_dynamic_duo_description(
        host_a=cfg.host_a_personality, host_b=cfg.host_b_personality )
    user = get_script_generation_prompt(
        content_analysis        = ANALYSIS,
        research_content        = RESEARCH,
        host_a_personality      = cfg.host_a_personality,
        host_b_personality      = cfg.host_b_personality,
        target_duration_minutes = cfg.target_duration_minutes,
        min_exchanges           = cfg.min_exchanges,
        max_exchanges           = cfg.max_exchanges,
        audience                = cfg.audience,
        audience_context        = cfg.audience_context,
        max_source_chars        = cfg.max_source_chars,
    )

    resp = await client.call_for_script( system_prompt=system, user_message=user )

    print( "=" * 78 )
    print( f"  stop_reason    : {resp.stop_reason!r}      <-- captured by api_client, read by NOBODY" )
    print( f"  output_tokens  : {resp.output_tokens}" )
    print( f"  content chars  : {len( resp.content )}" )
    print( f"  starts with    : {resp.content[ :70 ]!r}" )
    print( f"  ENDS with      : {resp.content[ -90: ]!r}" )
    braces = resp.content.count( "{" ) - resp.content.count( "}" )
    print( f"  unbalanced {{ }} : {braces:+d}   (>0 means TRUNCATED mid-object)" )
    print( "=" * 78 )

    try:
        parsed = parse_script_response( resp.content )
        print( f"  PARSE OK — {len( parsed.get( 'segments', [] ) )} segments, title={parsed.get('title')!r}" )
    except Exception as e:
        print( f"  PARSE FAILED — {type( e ).__name__}: {e}" )
        print()
        print( "  ^ this is the message the user sees replaced with 'try again in a few minutes'" )

if __name__ == "__main__":
    asyncio.run( main() )
