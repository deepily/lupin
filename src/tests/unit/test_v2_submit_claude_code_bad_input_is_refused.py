"""
Row a4014235 — a bad-input ValueError from a builder that `_refusing_bad_input` does not wrap
degrades to a queued receptionist job reported as "waiting".

This file measures the claude-code family. `ClaudeCodeJob.__init__` raises ValueError for a
task_type that is neither BOUNDED nor INTERACTIVE; `_build_claude_code` is not wrapped, so the
flow's generic `except Exception` sends the caller to the receptionist and the executor queues
a real receptionist job. The two doors this replaced answered 400 for that input.
"""

import pytest

from tests.helpers.v2_submit_harness import Queue, make_client

CC_COMMAND = "agent router go to claude code"


def test_a_bad_claude_code_task_type_is_refused_and_queues_nothing( tmp_path ):
    queue  = Queue()
    client = make_client( queue, tmp_path )

    response = client.post( "/api/v2/submit", json={
        "command" : CC_COMMAND,
        "args"    : { "prompt": "say hi", "task_type": "NOT_A_TASK_TYPE" },
        "speak"   : False,
    } )
    body = response.json()

    # What the caller must be able to key on: a terminal failure naming the bad value, and
    # nothing on the queue. A "waiting" with a job id for a refused submit is the defect.
    assert body[ "status" ] == "failed", body
    assert "task_type" in body[ "error" ], body
    assert queue.pushed == [ ], f"a refused submit queued {len( queue.pushed )} job(s)"
