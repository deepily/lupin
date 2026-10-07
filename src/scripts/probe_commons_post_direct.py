#!/usr/bin/env python3
"""
Probe `CommonsStore.post()` directly with bodies of escalating length.

The probe finds out whether a truncation cap lives in the fastmcp transport layer
or in the store itself.

Evidence: src/rnd/v0.1.7/2026.05.17-commons-dm-topic-case-and-truncation/90-execution-log.md

**What it does not test**: the fastmcp transport (commons_post called via MCP).
That is the inline MCP-tool probe, done separately from a live Claude Code session.

**What it tests**: the layer below fastmcp. `CommonsStore.post()` reads the body
string in-process and writes it to disk under flock. If this layer truncates, the
earlier code review that found no length cap was wrong. If it survives every
length cleanly, the cap is specific to fastmcp.

**Usage**:
    export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin
    python3 src/scripts/probe_commons_post_direct.py

It writes to a temporary directory, so `io/commons/` is not touched, and cleans up after.
"""

import os
import sys
import tempfile
from pathlib import Path


_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT is None:                                                # pragma: no cover
    raise RuntimeError( "LUPIN_ROOT environment variable not set." )   # pragma: no cover
_SRC_PATH = os.path.join( _LUPIN_ROOT, "src" )
if _SRC_PATH not in sys.path:                                          # pragma: no cover
    sys.path.insert( 0, _SRC_PATH )                                    # pragma: no cover

from lupin_mcp.commons_store import CommonsStore


PROBE_LENGTHS = [ 100, 500, 1_000, 4_000, 8_000, 16_000, 32_000, 64_000, 128_000 ]


def make_body( n: int ) -> str:
    """Generate a deterministic body of exactly `n` chars."""
    prefix = f"PROBE-LEN-{n}-"
    return prefix + "x" * ( n - len( prefix ) )


def run_probe() -> int:
    print( "=" * 70 )
    print( "Sub-bug B Candidate V — direct CommonsStore.post probe" )
    print( "=" * 70 )

    with tempfile.TemporaryDirectory() as tmp_root:
        store = CommonsStore( Path( tmp_root ) )
        topic = "probe-direct"

        results = [ ]
        for n in PROBE_LENGTHS:
            sent_body = make_body( n )
            sent_len  = len( sent_body )

            try:
                store.post(
                    topic             = topic,
                    body              = sent_body,
                    sender_session_id = "probe",
                    persona_name      = "Probe",
                    persona_icon      = "🧪",
                    persona_color     = "#888888",
                    metadata          = { "probe_len": n, "kind": "probe" },
                )
                # Read back the most recent entry
                entries = store.read( topic=topic, limit=1 )
                if not entries:
                    raise RuntimeError( "post succeeded but read returned empty" )
                returned_body = entries[ 0 ][ "body" ]
                returned_len  = len( returned_body )
                survived      = returned_len == sent_len
                results.append( ( sent_len, returned_len, survived, None ) )
            except Exception as e:
                results.append( ( sent_len, 0, False, str( e ) ) )

        print( "" )
        print( f"{'sent':>10} | {'returned':>10} | {'survived':>10} | error" )
        print( "-" * 70 )
        for sent_len, returned_len, survived, err in results:
            status = "✅" if survived else "❌"
            err_text = err or ""
            print( f"{sent_len:>10} | {returned_len:>10} | {status:>10} | {err_text}" )

        print( "" )
        all_survived = all( r[ 2 ] for r in results )
        if all_survived:
            print( "All lengths survived direct CommonsStore.post path." )
            print( "→ Truncation cap is FASTMCP-SPECIFIC (not in commons_store)." )
        else:
            first_fail = next( ( r for r in results if not r[ 2 ] ), None )
            print( f"FAIL at sent_len={first_fail[ 0 ]} → returned_len={first_fail[ 1 ]}" )
            print( "→ Truncation cap exists IN commons_store too — code review missed it." )

    return 0


if __name__ == "__main__":                                            # pragma: no cover
    sys.exit( run_probe() )                                           # pragma: no cover
