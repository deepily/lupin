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
        - a subclass that files rows sets filer_tool to its own name, so each row is filed by a persona

    Ensures:
        - create and amend return ( ok, status, body ) as the client does
    """

    create_extra = { }
    amend_extra  = { }
    filer_tool   = None

    def __init__( self, settings, api_key, client ):
        """Keep the three collaborators."""
        self.settings = settings
        self.api_key  = api_key
        self.client   = client

    def create( self, payload ):
        """
        Send one create: the payload, create_extra and, with filer_tool set, the persona stamp.

        Requires:
            - payload names accountable_manager or owner_persona when filer_tool is set

        Ensures:
            - returns ( ok, status, body ) for the create
            - with filer_tool set, created_by is "<persona> (<filer_tool>)" for the payload's accountable
              manager, or its owner when it names no manager (task_store_rules.filer_created_by)

        Raises:
            - ValueError when filer_tool is set and the payload names no persona to file as
        """
        stamp = { }
        if self.filer_tool is not None:
            from cosa.rest.task_store_rules import filer_created_by
            persona = payload.get( "accountable_manager" ) or payload.get( "owner_persona" )
            stamp   = { "created_by": filer_created_by( persona, self.filer_tool ) }
        return self.client.create_task( self.settings, self.api_key, { **payload, **self.create_extra, **stamp } )

    def amend( self, row_id, note ):
        """Ensures: returns ( ok, status, body ) for one amendment, the note plus amend_extra."""
        return self.client.amend_task( self.settings, self.api_key, row_id, { "note": note, **self.amend_extra } )
