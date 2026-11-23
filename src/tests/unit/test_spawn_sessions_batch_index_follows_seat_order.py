"""
`{batch_index}` is the seat's position in one spawn; `{index}` is the session-name slot.

A manager used `{index}` to pick one brief per seat. But `{index}` is the lowest free name slot.
So with a seat already on the manifest, two new seats got 2 and 3, not 1 and 2.
The prompts below come from the real `spawn_sessions` path through a fake runner (dry run).
"""

import json

from lupin_mcp import session_spawner


class _Runner:
    """Records every argv; the rendered brief is the element after `--prompt`."""
    def __init__( self ): self.argvs = []
    def __call__( self, argv, env=None ):
        self.argvs.append( argv )
        class _R: returncode = 0; stdout = ""; stderr = ""
        return _R()


def _prompts( runner ):
    return [ a[ a.index( "--prompt" ) + 1 ] for a in runner.argvs ]


def _spawn( tmp_path, count, template="B{batch_index}/I{index}" ):
    runner = _Runner()
    res    = session_spawner.spawn_sessions(
        count, template, "mgr-sid", script_path="x", project=None,
        runner=runner, session_dir=tmp_path, dry_run=True )
    return res, _prompts( runner )


def test_two_and_three_seat_spawns_number_batch_index_from_one_in_launch_order( tmp_path ):
    _, two   = _spawn( tmp_path, 2 )
    _, three = _spawn( tmp_path, 3 )
    assert two   == [ "B1/I1", "B2/I2" ]
    assert three == [ "B1/I1", "B2/I2", "B3/I3" ]


def test_batch_index_restarts_at_one_when_the_manager_already_has_seats( tmp_path ):
    # A seat already holds slot 1 and slot 3 is occupied too: {index} is offset, {batch_index} is not.
    base = "cc-reviewer-" + session_spawner._slug( "mgr-sid" )
    manifest = session_spawner._manifest_path( "mgr-sid", tmp_path )
    manifest.write_text( json.dumps( [ { "session_name": f"{base}-1" } ] ) )
    _, prompts = _spawn( tmp_path, 2 )
    assert prompts == [ "B1/I2", "B2/I3" ], "index is the name slot (offset); batch_index is the position"
