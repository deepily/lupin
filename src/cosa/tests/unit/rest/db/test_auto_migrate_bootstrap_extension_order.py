"""
The empty-database bootstrap installs the vector extension before it builds the schema.

A throwaway database cloned from the vector template already has the extension, so the live bootstrap tests
stop seeing a deleted extension line. This test records the statements instead, so it needs no database and
holds in every mode.
"""

from unittest.mock import MagicMock, patch

from cosa.rest.db import auto_migrate
from cosa.rest.postgres_models import Base


def _bootstrap():
    events = [ ]
    conn   = MagicMock()
    conn.execute.side_effect = lambda statement: events.append( ( "execute", str( statement ) ) )
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn
    with patch.object( auto_migrate, "wait_for_database", return_value=( False, False ) ), \
         patch.object( auto_migrate, "_read_current_revision", return_value=None ), \
         patch.object( auto_migrate, "create_engine", return_value=engine ), \
         patch.object( auto_migrate.command, "stamp" ), \
         patch.object( Base.metadata, "create_all", side_effect=lambda bind: events.append( ( "create_all", "" ) ) ):
        result = auto_migrate.run_migrations_to_head( database_url="postgresql+psycopg2://x:y@h:1/d" )
    return events, result


def test_the_extension_is_installed_before_the_schema_is_built():
    events, result = _bootstrap()
    assert result[ "bootstrapped" ] is True
    names = [ name for name, _ in events ]
    assert names == [ "execute", "create_all" ], f"expected one statement then create_all, got {events}"
    assert events[ 0 ][ 1 ] == "CREATE EXTENSION IF NOT EXISTS vector"
