"""
Reproduce bug e0bb5a94 defect A against the REAL demo seed doc (Krishna, 2026-08-13).

Mr Radio refuted the max_turns-truncation hypothesis on a SYNTHETIC ~13KB doc
(end_turn, balanced braces, 20 segments). The filed failure was 2/2 on the DEMO
SEED FILE, which is the 67KB `2026.07.25 KISS explainer` — 5x larger, untested.

This runs the FAITHFUL demo path on that seed: real analysis stage -> real script
stage, and reports what every layer saw (stop_reason, tokens, brace balance, parse
result). It asserts nothing — the evidence decides.
"""
import asyncio, sys, json

sys.path.insert( 0, "src" )

from cosa.agents.podcast_generator.api_client import PodcastAPIClient
from cosa.agents.podcast_generator.config     import PodcastConfig
from cosa.agents.podcast_generator.prompts.script_generation import (
    SCRIPT_GENERATION_SYSTEM_PROMPT, CONTENT_ANALYSIS_SYSTEM_PROMPT,
    get_content_analysis_prompt, parse_analysis_response,
    get_script_generation_prompt, parse_script_response,
)
from cosa.agents.podcast_generator.prompts.personality import get_dynamic_duo_description
from cosa.config.configuration_manager import ConfigurationManager

SEED_PATH = "io/deep-research/ricardo.felipe.ruiz@gmail.com/2026.07.25-the-kiss-protocol-how-a-brevity-mandate-got-built-v1.md"


def _report( tag, resp ):
    braces = resp.content.count( "{" ) - resp.content.count( "}" )
    print( "=" * 78 )
    print( f"  [{tag}] stop_reason   : {resp.stop_reason!r}      <-- captured by api_client, read by NOBODY" )
    print( f"  [{tag}] output_tokens : {resp.output_tokens}" )
    print( f"  [{tag}] content chars : {len( resp.content )}" )
    print( f"  [{tag}] starts with   : {resp.content[ :70 ]!r}" )
    print( f"  [{tag}] ENDS with     : {resp.content[ -110: ]!r}" )
    print( f"  [{tag}] unbalanced {{}} : {braces:+d}   (>0 means TRUNCATED mid-object)" )
    print( "=" * 78 )
    return braces


async def main():
    with open( SEED_PATH, encoding="utf-8" ) as fh:
        research = fh.read()
    print( f"  SEED: {SEED_PATH}" )
    print( f"  seed chars: {len( research )}" )

    cfg    = PodcastConfig.from_config( ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ) )
    client = PodcastAPIClient( config=cfg, debug=True )
    print( f"  config: script_model={cfg.script_model}  script_max_turns={cfg.script_max_turns}  max_source_chars={cfg.max_source_chars}" )
    print( f"  target_duration={cfg.target_duration_minutes}min  exchanges={cfg.min_exchanges}-{cfg.max_exchanges}" )
    print()

    # ── Stage 1: real content analysis on the seed ──────────────────────────
    a_user = get_content_analysis_prompt(
        research_content = research,
        audience         = cfg.audience,
        audience_context = cfg.audience_context,
        max_source_chars = cfg.max_source_chars,
    )
    a_resp = await client.call_for_analysis( system_prompt=CONTENT_ANALYSIS_SYSTEM_PROMPT, user_message=a_user )
    _report( "ANALYSIS", a_resp )
    try:
        analysis = parse_analysis_response( a_resp.content )
        print( f"  ANALYSIS PARSE OK — main_topic={analysis.get('main_topic')!r}, subtopics={len(analysis.get('key_subtopics',[]))}" )
    except Exception as e:
        print( f"  ANALYSIS PARSE FAILED — {type(e).__name__}: {e}" )
        print( "  (analysis died first — script stage never reached in the real path)" )
        return
    print()

    # ── Stage 2: real script generation (the filed failure site) ────────────
    system = SCRIPT_GENERATION_SYSTEM_PROMPT + "\n\n" + get_dynamic_duo_description(
        host_a=cfg.host_a_personality, host_b=cfg.host_b_personality )
    s_user = get_script_generation_prompt(
        content_analysis        = analysis,
        research_content        = research,
        host_a_personality      = cfg.host_a_personality,
        host_b_personality      = cfg.host_b_personality,
        target_duration_minutes = cfg.target_duration_minutes,
        min_exchanges           = cfg.min_exchanges,
        max_exchanges           = cfg.max_exchanges,
        audience                = cfg.audience,
        audience_context        = cfg.audience_context,
        max_source_chars        = cfg.max_source_chars,
    )
    s_resp = await client.call_for_script( system_prompt=system, user_message=s_user )
    _report( "SCRIPT", s_resp )
    try:
        parsed = parse_script_response( s_resp.content )
        print( f"  SCRIPT PARSE OK — {len( parsed.get( 'segments', [] ) )} segments, title={parsed.get('title')!r}" )
    except Exception as e:
        print( f"  SCRIPT PARSE FAILED — {type(e).__name__}: {e}" )
        print( "  ^ THIS is defect A reproduced: the message the user sees replaced with 'try again in a few minutes'" )


if __name__ == "__main__":
    asyncio.run( main() )
