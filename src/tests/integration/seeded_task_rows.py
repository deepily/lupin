"""
Live task rows for integration tests, inserted straight into the TEST database.

WHY: since the holding area became the default, every row created through the API starts at
`not_approved`, and moving it out is an admission only an approver may make. The park and
staleness tests need a row that is already `queued`, so they get one here instead of asking the
create door for it. Nothing in the firewall or the admit rule is widened, and no operator
credential is involved.

THE GUARD: every write is refused unless the engine's database is named exactly `lupin_db_test`.
The match is on the parsed database name, never a substring, so `lupin_db_test_copy` and
`not_lupin_db_test` are refused, as are dev and production.
"""

from datetime import datetime, timezone

from sqlalchemy.engine import make_url

from cosa.rest.postgres_models import TaskEvent, TaskItem
from lupin_mcp.persona_normalization import canonical_persona_key

TEST_DB_NAME = "lupin_db_test"


def refuse_unless_test_db( db_url ):
    """
    Refuse any database that is not lupin_db_test.

    Requires:
        - db_url is a SQLAlchemy URL object or a URL string

    Ensures:
        - returns None only when the parsed database name equals TEST_DB_NAME exactly

    Raises:
        - RuntimeError naming the database found, when it is anything else or the URL has none
        - sqlalchemy.exc.ArgumentError if the string is not a URL at all
    """
    name = make_url( db_url ).database
    if name != TEST_DB_NAME:
        raise RuntimeError(
            f"SAFETY: seeded task rows may only be written to {TEST_DB_NAME}, "
            f"this engine points at {name!r}"
        )


class SeededRows:
    """
    Rows inserted for one test, removed when the test ends.

    Requires:
        - db_url names lupin_db_test (checked on construction, and again before each write)
        - session_factory is a callable returning a context manager that yields a Session and
          commits on a clean exit (cosa.rest.db.database.get_db)
    """

    def __init__( self, db_url, session_factory ):
        refuse_unless_test_db( db_url )
        self.db_url          = db_url
        self.session_factory = session_factory
        self.ids             = []

    def create( self, persona, title, status="queued", created_by="itest seed" ):
        """
        Insert one task row owned by `persona`, plus the creation event the API would write.

        Ensures:
            - the row exists with the given status, priority P5, epic key "epic:unassigned"
            - owner_persona and accountable_manager are stored as `canonical_persona_key( persona )`,
              the key the create door stores and the owed query reads by; a raw "ac6-1f" would
              never match the server's "ac6 1f" and the row would read as not owed
            - returns { "id", "status", "updated_ts" } as strings, the fields the tests read
              from a create response
        """
        refuse_unless_test_db( self.db_url )
        owner_key = canonical_persona_key( persona )
        with self.session_factory() as session:
            item = TaskItem(
                item_class          = "task",
                title               = title,
                project             = "lupin",
                owner_persona       = owner_key,
                accountable_manager = owner_key,
                created_by          = created_by,
                status              = status,
                priority            = "P5",
                correlation_key     = "epic:unassigned",
            )
            session.add( item )
            session.flush()
            session.add( TaskEvent(
                item_id    = item.id,
                ts         = datetime.now( timezone.utc ),
                actor      = created_by,
                transition = f"->{status}",
                authority  = "standing",
            ) )
            session.flush()
            session.refresh( item )
            row = { "id": str( item.id ), "status": item.status, "updated_ts": item.updated_ts.isoformat() }
        self.ids.append( row[ "id" ] )
        return row

    def delete_all( self ):
        """
        Delete every row this object inserted. Events go with them (ON DELETE CASCADE).

        Ensures:
            - the tracked ids are cleared, so a second call deletes nothing
        """
        if not self.ids: return
        refuse_unless_test_db( self.db_url )
        with self.session_factory() as session:
            session.query( TaskItem ).filter( TaskItem.id.in_( self.ids ) ).delete( synchronize_session=False )
        self.ids = []
