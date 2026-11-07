"""
The shared base of the two live task-store adapters.

The wiki librarian tick and the daily duplicate check each reach the store through the
hooks' task_store_client. Both hold the same three collaborators. Both make the same two
calls, a create and an append-only amendment. They differ only in the fields each stamps.
"""


class TaskStoreAdapter:
    """
    The task-store client behind a create and an amend, stamped by the subclass.

    Requires:
        - settings is the dict load_task_store_settings returns
        - api_key is the outbound key string
        - client is the task_store_client module, or a stand-in with create_task and amend_task
        - a subclass sets create_extra and amend_extra to the fields it adds to each call

    Ensures:
        - create and amend return ( ok, status, body ) as the client does
    """

    create_extra = { }
    amend_extra  = { }

    def __init__( self, settings, api_key, client ):
        """Keep the three collaborators."""
        self.settings = settings
        self.api_key  = api_key
        self.client   = client

    def create( self, payload ):
        """Ensures: returns ( ok, status, body ) for one create, the payload plus create_extra."""
        return self.client.create_task( self.settings, self.api_key, { **payload, **self.create_extra } )

    def amend( self, row_id, note ):
        """Ensures: returns ( ok, status, body ) for one amendment, the note plus amend_extra."""
        return self.client.amend_task( self.settings, self.api_key, row_id, { "note": note, **self.amend_extra } )
