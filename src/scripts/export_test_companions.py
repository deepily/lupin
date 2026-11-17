#!/usr/bin/env python3
"""
Print the companion users and API keys of the connected database as SQL.

The VM's destructive-test server has an empty dev database, so seed_test_companions.py has nothing to copy.
The real rows live in the :7999 database. This script runs inside the :7999 container, which already holds
that database's credentials, and prints one SQL script. `lupin-vm.sh test-server seed-companions` pipes the
script into the pgvector test container. The :7999 password never enters the test container, and no value
reaches a log or a command line.

Run with --check to print only counts and the emails it could not find. Nothing is written anywhere.

Exit codes: 0 ok, 2 the primary admin is missing (with --check, any companion is missing).
"""

import json
import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )
scripts_path = os.path.join( src_path, "scripts" )
if scripts_path not in sys.path: sys.path.insert( 0, scripts_path )

from cosa.rest.user_id_generator import email_to_user_uuid
from seed_test_companions import COMPANION_EMAILS, ADMIN_EMAIL

USER_COLUMNS = [ "id", "email", "password_hash", "created_at", "email_verified", "is_active", "roles" ]
KEY_COLUMNS  = [ "id", "user_id", "key_hash", "description", "is_active", "created_at", "last_used_at" ]
USER_TYPES   = "id uuid, email text, password_hash text, created_at timestamptz, email_verified boolean, is_active boolean, roles jsonb"
PLACEHOLDER_COLUMNS = [ "id", "email", "password_hash", "email_verified", "is_active", "roles" ]
PLACEHOLDER_TYPES   = "id uuid, email text, password_hash text, email_verified boolean, is_active boolean, roles jsonb"
PLACEHOLDER_HASH    = "!placeholder-no-login"                         # not a bcrypt hash, so no password can match it
KEY_TYPES    = "id uuid, user_id uuid, key_hash text, description text, is_active boolean, created_at timestamptz, last_used_at timestamptz"


def sql_literal( text ):
    """
    Quote text as a PostgreSQL string literal.

    Requires:
        - text is a string; the server runs with standard_conforming_strings on, so a backslash is an ordinary character

    Ensures:
        - returns the text in single quotes with every single quote doubled
    """
    return "'" + text.replace( "'", "''" ) + "'"


def fetch_rows():
    """
    Read the companion users and their API keys from the connected database.

    Requires:
        - cosa is importable and the environment names a reachable database
    Ensures:
        - returns ( users, keys ), each a list of dicts keyed by USER_COLUMNS / KEY_COLUMNS
        - reads only; nothing is written
    """
    from sqlalchemy import text
    from cosa.rest.db.database import engine

    with engine.connect() as conn:
        users = [ dict( r ) for r in conn.execute( text( f"SELECT {', '.join( USER_COLUMNS )} FROM users WHERE email = ANY( :emails )" ), { "emails": list( COMPANION_EMAILS ) } ).mappings() ]
        keys  = [ dict( r ) for r in conn.execute( text(
            f"SELECT {', '.join( 'a.' + c for c in KEY_COLUMNS )} FROM api_keys a JOIN users u ON a.user_id = u.id WHERE u.email = ANY( :emails )"
        ), { "emails": list( COMPANION_EMAILS ) } ).mappings() ]
    return users, keys


def _upsert( table, columns, types, rows, extra_select=( "", "" ), extra_set="", on_conflict=None ):
    """Ensures: returns one insert carrying the rows as a JSON literal; an upsert by default."""
    payload  = sql_literal( json.dumps( rows, default=str ) )
    updates  = ", ".join( f"{c} = EXCLUDED.{c}" for c in columns if c not in ( "id", "created_at", "last_used_at" ) )
    conflict = on_conflict or f"ON CONFLICT ( id ) DO UPDATE SET {updates}{extra_set}"
    return (
        f"INSERT INTO {table} ( {', '.join( columns )}{extra_select[ 0 ]} )\n"
        f"SELECT {', '.join( columns )}{extra_select[ 1 ]} FROM jsonb_to_recordset( {payload}::jsonb ) AS t( {types} )\n"
        f"{conflict};"
    )


def placeholder_rows( emails ):
    """
    Describe a disabled stand-in account for each email.

    Requires:
        - emails is a list of email strings
    Ensures:
        - returns one dict per email, in order, with the stable id mock auth derives from the email
        - each account is inactive and unverified, holds only the user role, and has a hash no password matches
    """
    return [ { "id": email_to_user_uuid( e ), "email": e, "password_hash": PLACEHOLDER_HASH,
               "email_verified": False, "is_active": False, "roles": [ "user" ] } for e in emails ]


def build_sql( users, keys, placeholders=() ):
    """
    Build the SQL script that makes the target hold these companions.

    Requires:
        - users and keys are lists of dicts as fetch_rows returns them
        - placeholders is a list of dicts as placeholder_rows returns them
    Ensures:
        - returns one script: a transaction holding the users upsert (marked protected), then the keys upsert
        - an empty keys list writes no keys statement
        - placeholders are inserted protected, and only when no row has that email or id; an existing row is never touched
        - the script holds credential hashes, so the caller must pipe it and never print it
    """
    parts = [ "BEGIN;", _upsert( "users", USER_COLUMNS, USER_TYPES, users, ( ", is_protected", ", TRUE" ), ", is_protected = TRUE" ) ]
    if placeholders: parts.append( _upsert( "users", PLACEHOLDER_COLUMNS, PLACEHOLDER_TYPES, list( placeholders ), ( ", is_protected", ", TRUE" ), on_conflict="ON CONFLICT DO NOTHING" ) )
    if keys: parts.append( _upsert( "api_keys", KEY_COLUMNS, KEY_TYPES, keys, ( "", "" ), "" ) )
    parts.append( "COMMIT;" )
    return "\n".join( parts ) + "\n"


def main( argv=None, out=print, err=None, fetch=fetch_rows ):
    """
    Print the companion SQL, or with --check print counts only.

    Requires:
        - argv is None or a list holding at most --check
    Ensures:
        - --check prints one line, `companions: users=N api_keys=M missing=[...] placeholders=P`, and no row value
        - every missing companion except the primary admin gets a disabled placeholder row in the script
        - without --check, prints the SQL script and returns 0 when the primary admin was found
        - returns 2, printing nothing to out, when the primary admin is missing
    """
    err   = err or ( lambda text: print( text, file=sys.stderr ) )
    check = "--check" in ( argv if argv is not None else sys.argv[ 1: ] )
    users, keys = fetch()
    found   = { u[ "email" ] for u in users }
    missing = [ e for e in COMPANION_EMAILS if e not in found ]
    for email in missing: err( f"companion {email} not found in the source database" + ( "" if email == ADMIN_EMAIL else "; a disabled placeholder stands in" ) )
    holders = placeholder_rows( [ e for e in missing if e != ADMIN_EMAIL ] )
    if check:
        out( f"companions: users={len( users )} api_keys={len( keys )} missing={missing} placeholders={len( holders )}" )
        return 2 if ADMIN_EMAIL in missing else 0
    if ADMIN_EMAIL in missing:
        err( "PRIMARY ADMIN missing from the source database — nothing exported" )
        return 2
    out( build_sql( users, keys, holders ).rstrip( "\n" ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
