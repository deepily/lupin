"""
Every task-store row is filed by a persona, as Rick ruled on 9 Nov 2026.

Before this, three automated filers wrote their own tool name as the creator:
"wiki-librarian tick", "duplicate-check-daily" and "heartbeat-arbiter@lupin.deepily.ai".
Measured 9 Nov over 4,676 rows: 194 + 189 + 137 rows, 11 of them still live. The
holding area groups by creator, so those rows sat under a heading that named a tool.

The fix has three parts, and each has a test here:
  1. one stamp, filer_created_by, "<persona> (<tool>)";
  2. persona_from_created_by reads the persona out of that stamp;
  3. the create door refuses an API-key caller whose creator, with no session id,
     names no persona. A seat's "<name> <session id>" keeps the soft-flag path.
     The door's own tests are in test_tasks_router.py, beside its fixtures.
"""

import pytest
from unittest.mock import MagicMock

from cosa.rest import task_store_rules as rules
from cosa.repo.symindex import librarian_tick as lt
from cosa.agents.shared import worktree_straggler_tickets as st
from lupin_mcp import duplicate_check_filing as ff


ROSTER = { "cheech", "mr radio", "krishna" }


# ---------------------------------------------------------------------------
# 1. The stamp
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "persona, tool, expected", [
    ( "Cheech",   "wiki-librarian tick",                "cheech (wiki-librarian tick)" ),
    ( "Mr Radio", " heartbeat-arbiter@lupin.deepily.ai ", "mr radio (heartbeat-arbiter@lupin.deepily.ai)" ),
    ( "María",    "duplicate-check-daily",              "maria (duplicate-check-daily)" ),
] )
def test_the_stamp_is_the_canonical_persona_then_the_tool_in_brackets( persona, tool, expected ):
    assert rules.filer_created_by( persona, tool ) == expected


@pytest.mark.parametrize( "persona", [ None, "", "   " ] )
def test_a_stamp_with_no_persona_is_refused( persona ):
    with pytest.raises( ValueError, match="needs a persona" ):
        rules.filer_created_by( persona, "wiki-librarian tick" )


@pytest.mark.parametrize( "tool", [ None, "", "  ", "tick (v2)", "a)b", 7 ] )
def test_a_stamp_with_a_blank_or_bracketed_tool_is_refused( tool ):
    with pytest.raises( ValueError, match="plain tool name" ):
        rules.filer_created_by( "cheech", tool )


# ---------------------------------------------------------------------------
# 2. Reading the persona back
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "created_by, persona", [
    ( "cheech (wiki-librarian tick)",                   "cheech" ),
    ( "mr radio (heartbeat-arbiter@lupin.deepily.ai)",  "mr radio" ),
    ( "rick (rick)",                                    "rick" ),        # a login's stamp, already in the store
    ( "mr radio 8353ea70",                              "mr radio" ),    # a seat's stamp, unchanged
    ( "Cheech 8db4923d",                                "cheech" ),
    ( "wiki-librarian tick",                            "wiki librarian tick" ),
] )
def test_the_persona_is_read_out_of_every_stamp_shape( created_by, persona ):
    assert rules.persona_from_created_by( created_by ) == persona


def test_a_tool_stamp_carries_no_session_id_so_the_store_reads_its_caller_as_a_worker():
    assert rules.session_id_from_created_by( "cheech (wiki-librarian tick)" ) is None


# ---------------------------------------------------------------------------
# 3. The refusal, as a rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "created_by", [ "wiki-librarian tick", "duplicate-check-daily",
                                          "heartbeat-arbiter@lupin.deepily.ai", "ziggy (some tool)", "", None ] )
def test_a_creator_with_no_session_that_names_no_persona_is_refused( created_by ):
    refusal = rules.creator_refusal( created_by, known_keys=ROSTER, approver_keys={ "rick" } )
    assert refusal is not None and repr( created_by ) in refusal and "1c56470f" in refusal


@pytest.mark.parametrize( "created_by", [ "cheech (wiki-librarian tick)", "Mr Radio", "rick (rick)", "rick" ] )
def test_a_creator_with_no_session_that_names_a_persona_or_an_approver_passes( created_by ):
    assert rules.creator_refusal( created_by, known_keys=ROSTER, approver_keys={ "rick" } ) is None


def test_a_seat_with_a_session_id_is_never_refused_even_off_roster():
    # Policy 1: a new persona's founding row must land; it is soft-flagged downstream.
    assert rules.creator_refusal( "ziggy 5a1f17f8", known_keys=ROSTER ) is None


def test_the_hook_mirrors_unknown_persona_passes_only_while_its_session_id_is_hex():
    # task_store_mirror._identity sends "<persona> <first 8 of the session id>", with persona
    # "unknown" when the bridge has none. A real session id is a hex uuid, so that row lands and is
    # soft-flagged downstream. A non-hex id has no session tail, so it is judged and refused.
    assert rules.creator_refusal( "unknown 8db4923d", known_keys=ROSTER ) is None
    assert rules.creator_refusal( "unknown test-ses", known_keys=ROSTER ) is not None


def test_with_no_roster_given_the_configured_pool_is_used( monkeypatch ):
    monkeypatch.setattr( rules, "_KNOWN_PERSONA_KEYS", { "cheech" } )
    assert rules.creator_refusal( "cheech (wiki-librarian tick)" ) is None
    assert rules.creator_refusal( "krishna (wiki-librarian tick)" ) is not None


# ---------------------------------------------------------------------------
# 1. Each of the three filers uses the stamp
# ---------------------------------------------------------------------------

class _Client:
    def __init__( self ): self.calls = [ ]
    def create_task( self, settings, api_key, payload ):
        self.calls.append( payload ); return True, 201, { "id": "x" }


def test_the_librarian_files_as_the_rows_manager( ):
    client = _Client()
    lt.LiveStore( { }, "k", client ).create( { "title": "t", "owner_persona": "cheech", "accountable_manager": "Mr Radio" } )
    assert client.calls[ 0 ][ "created_by" ] == "mr radio (wiki-librarian tick)"


def test_the_librarian_refuses_to_file_a_row_that_names_no_persona( ):
    with pytest.raises( ValueError, match="needs a persona" ):
        lt.LiveStore( { }, "k", _Client() ).create( { "title": "t" } )


def test_the_duplicate_check_files_as_its_triage_owner( ):
    f   = { "id": "d-1", "name": "a1", "file": "a.py", "line": 3, "text": "def a1(): pass",
            "others": [ ], "window": { "start": "aaa", "end": "bbb" } }
    row = ff.triage_payload( [ f ], { "owner": "cheech", "note": "n" }, __import__( "datetime" ).date( 2026, 11, 9 ) )
    assert row[ "created_by" ] == "cheech (duplicate-check-daily)"


def test_the_arbiter_files_straggler_rows_as_the_rows_chaser( monkeypatch ):
    seen = { }

    class _Repo:
        def __init__( self, session ): pass
        def create_item( self, **kw ):
            seen.update( kw ); return MagicMock( id="new-id" )

    class _Session:
        def __enter__( self ): return self
        def __exit__( self, *a ): return False
        def flush( self ): pass

    import cosa.rest.db.database as database
    import cosa.rest.db.repositories.task_repository as task_repository
    monkeypatch.setattr( database, "get_db", lambda: _Session() )
    monkeypatch.setattr( task_repository, "TaskRepository", _Repo )
    st.RepositoryStragglerStore().create( "t", "b", owner="Krishna", accountable="Mr Radio", project="lupin", correlation_key="worktree:x" )
    assert seen[ "created_by" ] == "mr radio (heartbeat-arbiter@lupin.deepily.ai)"
    assert rules.persona_from_created_by( seen[ "created_by" ] ) == "mr radio"


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
