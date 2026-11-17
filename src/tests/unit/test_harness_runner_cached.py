"""harness_runner.cached: the one ledger get-or-compute call."""
import asyncio

from cosa.repo.doc_lint import harness_runner


class _Store:
    def __init__( self, held=None ):
        self.held = dict( held or {} )
        self.puts = []

    def get( self, key ): return self.held.get( key )

    def put( self, key, value ):
        self.puts.append( key )
        self.held[ key ] = value


def _make( calls, value ):
    async def make():
        calls.append( 1 )
        return value
    return make


def test_a_stored_value_is_returned_without_calling_make():
    calls, store = [], _Store( { "k": "old" } )
    assert asyncio.run( harness_runner.cached( store, "k", _make( calls, "new" ) ) ) == "old" and calls == [] and store.puts == []


def test_a_missing_value_is_made_stored_and_returned_and_then_served_from_the_ledger():
    calls, store = [], _Store()
    assert asyncio.run( harness_runner.cached( store, "k", _make( calls, "new" ) ) ) == "new" and store.held == { "k": "new" }
    assert asyncio.run( harness_runner.cached( store, "k", _make( calls, "other" ) ) ) == "new" and calls == [ 1 ]


def test_without_a_ledger_make_always_runs_and_nothing_is_stored():
    calls = []
    assert asyncio.run( harness_runner.cached( None, "k", _make( calls, 5 ) ) ) == 5 and calls == [ 1 ]
