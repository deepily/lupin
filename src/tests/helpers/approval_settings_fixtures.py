#!/usr/bin/env python3
"""
An in-memory stand-in for the `approval_settings` table, for the unit tier.

WHY THIS EXISTS (row 80513825). The approval settings used to live in a JSON file each test
pointed at a temp path. They now live in a database table, and the unit tier must not need a
database, so `tests/conftest.py` swaps `task_approval_settings._backend` for `MemoryBackend`
around EVERY test. That swap is also the isolation guard: a test that forgets to set anything
reads an empty store, never the real one.

⚠️ THE OLD FILE IS NOT A FIXTURE ANY MORE. Writing `task-approval-settings.json` changes
nothing the code reads — that is the property the row exists to give, and
`test_the_override_file_is_not_read.py` asserts it. Seed values with `seed()` instead.
"""
import copy

import cosa.rest.task_approval_settings as approval


class MemoryBackend:
    """
    Same two-method contract as `task_approval_settings._DbBackend`.

    Requires:
        - values are JSON-like; they are deep-copied in and out so a caller cannot mutate the
          "table" through a reference, which a real database would not allow either
    """

    def __init__( self, rows=None ):
        self.rows        = copy.deepcopy( rows ) if rows else {}
        self.updated_by  = {}
        self.write_calls = 0
        self.fail_with   = None

    def load( self ):
        if self.fail_with is not None: raise self.fail_with
        return copy.deepcopy( self.rows )

    def write( self, updates, updated_by ):
        if self.fail_with is not None: raise self.fail_with
        self.write_calls += 1
        for key, value in updates.items():
            self.rows[ key ]       = copy.deepcopy( value )
            self.updated_by[ key ] = updated_by


def seed( body ):
    """
    Put `body` (a dict of setting -> value) into the current in-memory store.

    Ensures:
        - the store holds EXACTLY `body`; whatever was there is replaced
        - the module's read cache is dropped, so the next read sees it
    """
    approval._backend.rows = copy.deepcopy( body )
    approval._invalidate_cache()


def stamped_json( body ):
    """
    `body` as JSON carrying the stamp the OLD validated writer put on the file.

    Only the legacy-file import still looks at a stamp; this builds a file it will trust.

    Ensures:
        - a dict body carries `STAMP_KEY` when this process can compute one (needs
          JWT_SECRET_KEY); otherwise, or for a non-dict, `body` is returned unchanged
    """
    import json
    if isinstance( body, dict ):
        stamp = approval._expected_stamp( body )
        if stamp is not None: body = { **body, approval.STAMP_KEY: stamp }
    return json.dumps( body )


class SettingsHandle:
    """
    A test-side handle over the in-memory approval-settings store — NOT a file.

    Older tests drove the settings by writing a JSON file and reading it back. The store is a
    table now, so this keeps their `write_text` / `read_text` / `exists` shape while every byte
    lands in the in-memory backend. Nothing here touches the filesystem, and writing the real
    override file changes nothing the code reads (`test_the_override_file_is_not_read.py`).

    Ensures:
        - write_text( text ) REPLACES the store with the JSON object in `text`, minus any
          `_stamp`; text that is not a JSON object raises ValueError — the store cannot hold a
          corrupt value, which is the point, so a test of "corrupt file" belongs to the
          import path instead
        - read_text() is the store as JSON; exists() is whether anything is stored
    """

    def write_text( self, text ):
        import json
        body = json.loads( text )
        if not isinstance( body, dict ):
            raise ValueError( "the settings store holds a JSON object, not " + type( body ).__name__ )
        body.pop( approval.STAMP_KEY, None )
        seed( body )

    def read_text( self ):
        import json
        return json.dumps( approval._backend.rows )

    def exists( self ):
        return bool( approval._backend.rows )
