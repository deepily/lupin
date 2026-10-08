"""
CommonsStore.post must flush its entry before it releases the lock.

The smoke test for two sessions with distinct personas failed about one run in twelve.
An entry body ended in the next entry's header.

`post` opened the topic file with a buffered handle. It released the lock before the handle closed,
so the buffer reached the file after the unlock. A second writer that took the lock in that gap
saw an empty file. It wrote the frontmatter a second time into the middle of the topic.

This test makes the gap certain instead of waiting for it. When the first post releases its lock,
the second post runs at once, as a racing process would. No repeat runs, no threads, no timing.

Seams driven for real: CommonsStore.post and CommonsStore.read over a real file in a temporary directory.
"""
import fcntl

from lupin_mcp import commons_store as cs


def _post( store, body, session ):
    return store.post( topic="coordination", body=body, sender_session_id=session, persona_name=session, persona_icon="x", persona_color="#000000" )


def test_a_second_post_in_the_gap_after_the_first_unlock_leaves_one_frontmatter_and_two_whole_entries( tmp_path, monkeypatch ):
    store = cs.CommonsStore( str( tmp_path ) )
    real  = cs.fcntl.flock
    fired = []

    def flock( fd, operation ):
        real( fd, operation )
        if operation == fcntl.LOCK_UN and not fired:
            fired.append( True )
            _post( store, "second entry", "sess-b" )

    monkeypatch.setattr( cs.fcntl, "flock", flock )
    _post( store, "first entry", "sess-a" )
    monkeypatch.undo()

    text = store._topic_path( "coordination" ).read_text( encoding="utf-8" )
    assert fired == [ True ]
    assert text.count( "topic: coordination" ) == 1, f"frontmatter written {text.count( 'topic: coordination' )} times:\n{text}"
    bodies = sorted( e[ "body" ] for e in store.read( "coordination", limit=100 ) )
    assert bodies == [ "first entry", "second entry" ]
