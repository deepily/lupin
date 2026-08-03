#!/usr/bin/env python3
"""
DIRECT fuzzy-matcher probe + STABILITY SWEEP (Lane 2 close, no channel contention,
no Rick auth): replicate expeditor._handle_fuzzy_file_match's NON-interactive
resolution core (expeditor.py:1022-1181) for a user's scope + a description, and
report whether it resolves to the real KISS explainer. Skips the interactive
_ask_for_arg by injecting the description directly.

phi-4 is an LLM, so a single run is not demo-confidence. RUNS_PER_PHRASING sweeps
each phrasing N times; 10/10 CORRECT is the bar Mr Radio set for Rick's one shot.
"""
import sys, os
lupin_root = os.environ[ "LUPIN_ROOT" ]
src = os.path.join( lupin_root, "src" )
if src not in sys.path: sys.path.insert( 0, src )

import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager
from cosa.agents.io_models.utils.fuzzy_file_prefilter import prefilter_docs_map_by_keywords
from cosa.agents.io_models.xml_models import FuzzyFileMatchResponse
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor
from cosa.agents.llm_client_factory import LlmClientFactory

USER  = "ricardo.felipe.ruiz@gmail.com"
AGENT = "Podcast Generator"
RUNS_PER_PHRASING = 5
EXPECT_SUBSTR = "kiss"   # the resolved path must contain this to count CORRECT
DESCRIPTIONS = [
    "the explainer I wrote about the KISS protocol",
    "an explainer document that discusses the KISS protocol and how it saved me a ton of tokens on a daily basis",
]

config_mgr   = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
project_root = cu.get_project_root()
source_extensions = ( ".md", ".yaml", ".yml", ".txt" )

def build_docs_map():
    docs_map = {}
    research_dir = project_root + f"/io/deep-research/{USER}"
    if os.path.exists( research_dir ):
        for f in os.listdir( research_dir ):
            if f.endswith( source_extensions ):
                docs_map[ f"io/deep-research/{USER}/{f}" ] = f"{research_dir}/{f}"
    pres_dir = project_root + f"/io/presentations/{USER}"
    if os.path.exists( pres_dir ):
        for f in os.listdir( pres_dir ):
            if f.endswith( ( ".yaml", ".yml" ) ):
                docs_map[ f"io/presentations/{USER}/{f}" ] = f"{pres_dir}/{f}"
    raw = config_mgr.get( f"{AGENT.lower()} source search paths", default=None )
    if raw is None:
        raw = config_mgr.get( "podcast generator source search paths", default="/src" )
    for d in [ x.strip() for x in ( raw or "" ).split( "," ) if x.strip() ]:
        ad = project_root + d
        if not os.path.exists( ad ): continue
        for root, _dirs, files in os.walk( ad ):
            for f in files:
                if f.endswith( source_extensions ):
                    ap = os.path.join( root, f ); rp = os.path.relpath( ap, project_root )
                    docs_map.setdefault( rp, ap )
    return docs_map

def resolve_once( description, docs_map ):
    """Return (verdict, detail). verdict in CORRECT|WRONG|NO_MATCH|MULTI|ARBITRARY|EXCEPTION."""
    filtered, arbitrary = prefilter_docs_map_by_keywords( dict( docs_map ), description, debug=False )
    if arbitrary:
        return "ARBITRARY", "prefilter arbitrary → would ask exact path"
    template_path = config_mgr.get( "prompt template for fuzzy file matching" )
    template = cu.get_file_as_string( project_root + template_path )
    template = PromptTemplateProcessor( debug=False ).process_template( template, "fuzzy file matching" )
    file_list = "\n".join( f"- {rel}" for rel in sorted( filtered.keys() ) )
    prompt = template.format( description=description, file_list=file_list )
    try:
        llm = LlmClientFactory().get_client( config_mgr.get( "llm spec key for fuzzy file matching" ), debug=False, verbose=False )
        resp = llm.run( prompt )
        matches = FuzzyFileMatchResponse.from_xml( resp ).get_matches_list()
        if not matches:
            return "NO_MATCH", "no match"
        if len( matches ) == 1:
            ok = EXPECT_SUBSTR in matches[ 0 ].lower()
            return ( "CORRECT" if ok else "WRONG" ), matches[ 0 ]
        return "MULTI", str( matches )
    except Exception as e:
        return "EXCEPTION", f"{type(e).__name__}: {e}"

def main():
    docs_map = build_docs_map()
    print( f"docs_map size: {len( docs_map )} (search-paths empty ⇒ user scope only)\n" )
    overall_correct = 0; overall_total = 0
    for desc in DESCRIPTIONS:
        tally = {}
        print( "=" * 78 )
        print( f"PHRASING: {desc!r}" )
        for i in range( RUNS_PER_PHRASING ):
            v, d = resolve_once( desc, docs_map )
            tally[ v ] = tally.get( v, 0 ) + 1
            overall_total += 1
            if v == "CORRECT": overall_correct += 1
            print( f"  run {i+1}/{RUNS_PER_PHRASING}: {v:9s} {d if v!='CORRECT' else ''}" )
        c = tally.get( "CORRECT", 0 )
        print( f"  → {c}/{RUNS_PER_PHRASING} CORRECT   tally={tally}" )
    print( "=" * 78 )
    print( f"SWEEP RESULT: {overall_correct}/{overall_total} CORRECT (target = {overall_total}/{overall_total})" )

if __name__ == "__main__":
    main()
