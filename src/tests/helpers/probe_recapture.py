"""
Capture the stream of one real probe run as the fixture the probe tests replay.

Run it by hand when the probe's prompt version changes. It makes one model call:
    LUPIN_ROOT=<tree> PYTHONPATH=<tree>/src python -m tests.helpers.probe_recapture <out.json> <tree> <model>
"""
import asyncio
import json
import sys

from claude_agent_sdk import query as sdk_query

from lupin_mcp.reuse_needset import agent_probe as ap
from tests.helpers import sdk_stream_capture as cap

NEED     = "Say whether a moment falls inside a fixed daily window of hours in the Eastern time zone."
FILE     = "src/lupin_mcp/reuse_needset/smoke.py"
RESULT   = { "verdict": "REUSE", "shortlist": [
    { "id": "lupin_mcp.reuse_needset.smoke.in_window", "file": FILE, "p": 0.9 },
    { "id": "lupin_mcp.reuse_needset.smoke.lifted_by", "file": FILE, "p": 0.3 } ] }
STRIPPED = "RateLimitEvent and the thinking-only message were removed: they carry billing state and a signature, and no test reads them"
PLACEHOLDER_ROOT = "/root"


def keep( message ):
    """Say whether a captured message belongs in the fixture."""
    if type( message ).__name__ == "RateLimitEvent": return False
    blocks = getattr( message, "content", None )
    return not ( isinstance( blocks, list ) and blocks and all( type( b ).__name__ == "ThinkingBlock" for b in blocks ) )


def scrub( text, root, home ):
    """Return text with the tree path and the home path replaced by placeholders."""
    return text.replace( root, PLACEHOLDER_ROOT ).replace( home, "/home/user" )


async def capture( root, model, home, query_fn=sdk_query ):
    """
    Run the probe once and return the fixture document.

    Requires:
        - root is a read-only tree holding the file named by `FILE`; query_fn is the SDK query or a stand-in

    Ensures:
        - returns the need, the shortlist, the placeholder root, the model, the prompt version and the kept messages with paths scrubbed
    """
    seen = []

    async def recording( prompt, options ):
        async for m in query_fn( prompt=prompt, options=options ):
            seen.append( m )
            yield m

    await ap.run_probe( NEED, RESULT, root, model, query_fn=recording )
    text = scrub( json.dumps( cap.encode( [ m for m in seen if keep( m ) ] ) ), root, home )
    return { "need": NEED, "result": RESULT, "root": PLACEHOLDER_ROOT, "model": model, "prompt_version": ap.prompt_version(), "stripped": STRIPPED, "messages": json.loads( text ) }


def main( argv, home, query_fn=sdk_query ):
    """Write the fixture document to argv[ 0 ] for the tree argv[ 1 ] and the model argv[ 2 ]."""
    out, root, model = argv
    doc = asyncio.run( capture( root, model, home, query_fn ) )
    with open( out, "w", encoding="utf-8" ) as f: f.write( json.dumps( doc, indent=1, sort_keys=True ) + "\n" )
    return doc


if __name__ == "__main__":  # pragma: no cover  reason: the command line entry; main is tested with a stand-in
    import os
    main( sys.argv[ 1: ], os.path.expanduser( "~" ) )
