#!/usr/bin/env python3
"""
Shared Claude Code transcript-JSONL reader.

The `Stop`-hook input carries a `transcript_path` pointing at the session's
own conversation transcript (`~/.claude/projects/<encoded-project>/<uuid>.jsonl`).
This module is the ONE place that parses that file, fanned out to two consumers
(canonical §0.3 + arbiter design §8.1 — "build the reader ONCE"):

    (a) the Heartbeat-Hook v2 work-owed oracle (Task* replay — see
        heartbeat_task_state.py), and
    (b) token/context-rate instrumentation (TODO line 11).

**Invariant — NEVER a dependency in the poke path:** every read is wrapped;
a missing / unreadable / malformed transcript yields an EMPTY iteration
rather than raising. A consumer that sees no lines simply finds no signal
(the heartbeat then stays conservative — no false poke). `:7999`-free: this
is a pure local file read, no MCP / commons / server.

Transcript shape (empirically confirmed 2026-06-04 — spike in
04-v2-oracle-livefetch-plan.md §2):
    - One JSON object per line; line `type` ∈ {user, assistant, system,
      attachment, file-history-snapshot, last-prompt, queue-operation}.
    - Tool calls live in `assistant` lines: `message.content` is a list of
      blocks; a tool call is a block with `type=="tool_use"`, plus `name`,
      `input` (dict), and `id`.

Design authority: planning-is-prompting →
    src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md §0.3.
"""
import json
from pathlib import Path


def read_transcript( transcript_path ):
    """
    Yield parsed JSON objects, one per non-empty transcript line.

    Requires:
        - transcript_path is a path-like / string / None

    Ensures:
        - Yields each line that parses to a JSON object (dict)
        - Skips blank lines, unparseable lines, and non-dict JSON values
        - Missing / None / unreadable path → yields nothing (empty)
        - NEVER raises (the poke path must not depend on transcript health)
    """
    if not transcript_path:
        return
    path = Path( transcript_path )
    try:
        if not path.exists():
            return
        with open( path ) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads( line )
                except ValueError:
                    continue
                if isinstance( obj, dict ):
                    yield obj
    except OSError:
        return


def iter_tool_uses( transcript_path, names=None ):
    """
    Yield (name, input, tool_use_id) for every assistant `tool_use` block,
    in transcript order.

    Requires:
        - transcript_path is a path-like / string / None
        - names is None (all tools) or a collection of tool-name strings

    Ensures:
        - Yields one tuple per assistant tool_use block whose name passes the
          `names` filter, in file order (the order tools were invoked)
        - input is the block's `input` dict (or {} if absent/non-dict)
        - Non-assistant lines, non-list content, and non-tool_use blocks are
          skipped
        - NEVER raises
    """
    name_filter = set( names ) if names is not None else None
    for obj in read_transcript( transcript_path ):
        if obj.get( "type" ) != "assistant":
            continue
        message = obj.get( "message" )
        if not isinstance( message, dict ):
            continue
        content = message.get( "content" )
        if not isinstance( content, list ):
            continue
        for block in content:
            if not isinstance( block, dict ) or block.get( "type" ) != "tool_use":
                continue
            name = block.get( "name" )
            if name_filter is not None and name not in name_filter:
                continue
            inp = block.get( "input" )
            yield ( name, inp if isinstance( inp, dict ) else {}, block.get( "id" ) )


def quick_smoke_test():
    """
    Self-contained smoke test over a tmp transcript.

    Ensures:
        - Returns True if read/parse/tool-iter/skip-malformed behave as
          designed; raises AssertionError otherwise.
    """
    import tempfile, os

    lines = [
        json.dumps( { "type": "file-history-snapshot", "snapshot": {} } ),
        "   ",                                              # blank → skipped
        "{ not json",                                       # malformed → skipped
        json.dumps( "a-bare-string" ),                      # non-dict JSON → skipped
        json.dumps( { "type": "user", "message": { "role": "user", "content": "hi" } } ),
        json.dumps( { "type": "assistant", "message": { "role": "assistant", "content": [
            { "type": "text", "text": "thinking" },
            { "type": "tool_use", "name": "TaskCreate", "input": { "subject": "x" }, "id": "tu1" },
            { "type": "tool_use", "name": "Bash",       "input": { "command": "ls" }, "id": "tu2" },
        ] } } ),
        json.dumps( { "type": "assistant", "message": { "role": "assistant", "content": [
            { "type": "tool_use", "name": "TaskUpdate", "input": { "taskId": "1", "status": "completed" }, "id": "tu3" },
        ] } } ),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join( tmp, "t.jsonl" )
        with open( p, "w" ) as f:
            f.write( "\n".join( lines ) )

        objs = list( read_transcript( p ) )
        assert len( objs ) == 4, f"expected 4 dict lines, got {len( objs )}"   # snapshot,user,assistant,assistant

        all_tools = list( iter_tool_uses( p ) )
        assert [ t[ 0 ] for t in all_tools ] == [ "TaskCreate", "Bash", "TaskUpdate" ], all_tools

        task_tools = list( iter_tool_uses( p, names={ "TaskCreate", "TaskUpdate" } ) )
        assert [ t[ 0 ] for t in task_tools ] == [ "TaskCreate", "TaskUpdate" ]
        assert task_tools[ 1 ][ 1 ] == { "taskId": "1", "status": "completed" }
        assert task_tools[ 0 ][ 2 ] == "tu1"

        # Missing file / None → empty, never raises
        assert list( read_transcript( os.path.join( tmp, "nope.jsonl" ) ) ) == [ ]
        assert list( read_transcript( None ) ) == [ ]
        assert list( iter_tool_uses( None ) ) == [ ]

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"transcript_reader smoke: {'PASS' if ok else 'FAIL'}" )
