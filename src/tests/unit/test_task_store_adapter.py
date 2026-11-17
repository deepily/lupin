"""The shared task-store adapter: each subclass's stamped fields reach the client."""
from cosa.repo.symindex import librarian_tick as lt
from cosa.repo.symindex.task_store_adapter import TaskStoreAdapter
from lupin_mcp import duplicate_check_filing as ff


class Recorder:
    """A client that records each call and answers with a fixed triple."""

    def __init__( self ):
        self.calls = [ ]

    def create_task( self, settings, api_key, payload ):
        self.calls.append( ( "create", settings, api_key, payload ) )
        return True, 201, { "id": "r" }

    def amend_task( self, settings, api_key, row_id, body ):
        self.calls.append( ( "amend", settings, api_key, row_id, body ) )
        return True, 200, { }


def test_the_base_adds_nothing_to_a_create_or_an_amend():
    client = Recorder()
    store  = TaskStoreAdapter( { "s": 1 }, "k", client )
    assert store.create( { "title": "t" } ) == ( True, 201, { "id": "r" } ) and store.amend( "id-1", "n" ) == ( True, 200, { } )
    assert client.calls == [ ( "create", { "s": 1 }, "k", { "title": "t" } ), ( "amend", { "s": 1 }, "k", "id-1", { "note": "n" } ) ]


def test_the_tick_stamps_its_actor_on_both_calls_and_the_filing_stamps_its_reason_on_the_amend_only():
    tick, filing = Recorder(), Recorder()
    lt.LiveStore( { }, "k", tick ).create( { "title": "t", "accountable_manager": "cheech" } )
    lt.LiveStore( { }, "k", tick ).amend( "id-1", "n" )
    store = ff.LiveStore( settings={ }, api_key="k" )
    store.client = filing
    store.create( { "title": "t" } )
    store.amend( "id-1", "n" )
    assert tick.calls[ 0 ][ 3 ] == { "title": "t", "accountable_manager": "cheech", "created_by": "cheech (wiki-librarian tick)", "authority": "standing" }
    assert tick.calls[ 1 ][ 4 ] == { "note": "n", "actor": lt.ACTOR, "authority": "standing" }
    assert filing.calls[ 0 ][ 3 ] == { "title": "t" }
    assert filing.calls[ 1 ][ 4 ] == { "note": "n", "reason": ff.AMEND_REASON, "authority": "standing" }
    assert issubclass( lt.LiveStore, TaskStoreAdapter ) and issubclass( ff.LiveStore, TaskStoreAdapter )


def test_a_stamped_field_beats_the_callers_own_and_the_callers_payload_is_left_alone():
    tick, payload = Recorder(), { "title": "t", "owner_persona": "Mr Radio", "created_by": "someone else", "authority": "user_direct" }
    lt.LiveStore( { }, "k", tick ).create( payload )
    assert tick.calls[ 0 ][ 3 ] == { "title": "t", "owner_persona": "Mr Radio", "created_by": "mr radio (wiki-librarian tick)", "authority": "standing" }
    assert payload == { "title": "t", "owner_persona": "Mr Radio", "created_by": "someone else", "authority": "user_direct" }
