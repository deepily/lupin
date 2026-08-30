"""
Unit tests for src/scripts/seed_proxy_decisions.py — the proxy-decision seeding CLI.

WHY THIS FILE EXISTS (row e2099400): src/scripts is entering the coverage frame, and this was
the second-largest file in it sitting at ZERO — 211 statements nothing measured.

⚠️ THE HAZARD, AND IT IS DESTRUCTIVE RATHER THAN AWKWARD.
This module talks to a real PostgreSQL database and a real embedding store. `clean_seed_data`
DELETES rows; `seed_decisions` and `ratify_suggested` WRITE them. A test that reached the live
database would mutate the developer's data, and `--clean` would remove real records.

The guard is the autouse `no_database` fixture below: it replaces `get_db` with something that
RAISES. A test that forgets to stub the database does not quietly reach one — it fails loudly
naming the omission. The failure mode has to be opted OUT of, not opted into. Same shape as the
HOME redirect in test_lupin_config.py, for the same reason.

Nothing here contacts the network either: `_login` and the embedding endpoint go through
`requests`, which is stubbed for every test that touches them.
"""

import os
import sys
from contextlib import contextmanager

import pytest


def _load_module():
    """Import seed_proxy_decisions under its real name (src/scripts on path) so coverage targets it."""
    root        = os.environ[ "LUPIN_ROOT" ]
    scripts_dir = os.path.join( root, "src", "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import seed_proxy_decisions
    return seed_proxy_decisions


mod = _load_module()


# ── safety net ───────────────────────────────────────────────────────────────────

@pytest.fixture( autouse=True )
def no_database( monkeypatch ):
    """
    Make reaching a real database impossible BY OMISSION.

    Autouse: every test starts with `get_db` wired to an explosion. A test that needs the
    database stubs it deliberately via the `db` fixture. One that forgets fails with a message
    naming what it forgot, instead of connecting to Postgres and deleting seed rows.
    """
    def forbidden( *args, **kwargs ):
        raise AssertionError(
            "This test reached the REAL database. seed_proxy_decisions writes and deletes "
            "rows — stub get_db (use the `db` fixture) rather than letting it connect."
        )

    monkeypatch.setattr( mod, "get_db", forbidden )


@pytest.fixture( autouse=True )
def no_network( monkeypatch ):
    """Same argument for HTTP: an un-stubbed call must fail loudly, not hit a live server."""
    class Forbidden:
        @staticmethod
        def post( *args, **kwargs ):
            raise AssertionError(
                "This test made a REAL HTTP request. Stub mod.requests rather than "
                "contacting a live server."
            )

    monkeypatch.setattr( mod, "requests", Forbidden )


# ── doubles ──────────────────────────────────────────────────────────────────────

class FakeDecision:
    """Stands in for a ProxyDecision ORM row."""

    def __init__( self, id_, metadata_json=None, ratification_state="pending" ):
        self.id                 = id_
        self.metadata_json      = metadata_json
        self.ratification_state = ratification_state


class FakeQuery:
    def __init__( self, rows ):
        self._rows = rows

    def filter( self, *args, **kwargs ):
        return self

    def all( self ):
        return self._rows


class FakeSession:
    def __init__( self, rows=None ):
        self._rows    = rows or []
        self.flushed  = 0

    def query( self, model ):
        return FakeQuery( self._rows )

    def flush( self ):
        self.flushed += 1


class FakeRepo:
    """Records what the script asked the repository to do."""

    def __init__( self, session, pending=None, log_returns=None ):
        self.session       = session
        self._pending      = pending or []
        self._log_returns  = log_returns or []
        self.logged        = []
        self.ratified      = []
        self.deleted       = []

    def log_decision( self, **kwargs ):
        self.logged.append( kwargs )
        if self._log_returns:
            return self._log_returns.pop( 0 )
        return FakeDecision( f"pg-{len( self.logged )}" )

    def get_pending( self, domain=None, limit=None ):
        return self._pending

    def ratify( self, decision_id=None, approved=None, ratified_by=None, feedback=None ):
        self.ratified.append( ( decision_id, approved, ratified_by, feedback ) )

    def delete_pending( self, decision_id ):
        self.deleted.append( decision_id )


class FakeTable:
    def __init__( self ):
        self.deletes = []

    def delete( self, where ):
        self.deletes.append( where )


class FakeStore:
    def __init__( self, similar=None, ensure=True, ensure_raises=False ):
        self.added       = []
        self.states      = []
        self._similar    = similar if similar is not None else []
        self._ensure     = ensure
        self._raises     = ensure_raises
        self._table      = FakeTable()

    def add_decision( self, **kwargs ):
        self.added.append( kwargs )

    def update_ratification_state( self, decision_id, state ):
        self.states.append( ( decision_id, state ) )

    def find_similar( self, embedding, category=None, limit=None, threshold=None ):
        return self._similar

    def _ensure_table( self ):
        if self._raises:
            raise RuntimeError( "store unavailable" )
        return self._ensure


class FakePrediction:
    def __init__( self, verdict=None, confidence=0.0, case_count=0 ):
        self.verdict    = verdict
        self.confidence = confidence
        self.case_count = case_count


# ── fixtures that opt IN to the stubbed collaborators ────────────────────────────

@pytest.fixture
def db( monkeypatch ):
    """
    Wire get_db to a fake session + repository. Returns the repo so a test can assert on
    what the script actually asked the database to do.
    """
    state = {}

    def install( rows=None, pending=None, log_returns=None ):
        session = FakeSession( rows=rows )
        repo    = FakeRepo( session, pending=pending, log_returns=log_returns )

        @contextmanager
        def fake_get_db():
            yield session

        monkeypatch.setattr( mod, "get_db", fake_get_db )
        monkeypatch.setattr( mod, "ProxyDecisionRepository", lambda s: repo )
        state[ "session" ] = session
        state[ "repo" ]    = repo
        return repo

    install.state = state
    return install


@pytest.fixture
def store( monkeypatch ):
    """Replace _get_embedding_store with a fake, returning it for assertions."""
    def install( **kwargs ):
        fake = FakeStore( **kwargs )
        monkeypatch.setattr( mod, "_get_embedding_store", lambda: fake )
        return fake
    return install


@pytest.fixture
def http( monkeypatch ):
    """
    Stub `requests.post` for both endpoints the module calls, and record every call.

    The login endpoint and the embedding endpoint are distinguished by URL, so a test can
    assert the script asked the right one rather than merely that it asked something.
    """
    calls = []

    class Response:
        def __init__( self, payload, error=None ):
            self._payload = payload
            self._error   = error

        def raise_for_status( self ):
            if self._error:
                raise self._error

        def json( self ):
            return self._payload

    class Requests:
        @staticmethod
        def post( url, json=None, headers=None, timeout=None ):
            calls.append( { "url": url, "json": json, "headers": headers } )
            if "/auth/login" in url:
                return Response( { "tokens": { "access_token": "tok-123" } } )
            return Response( { "embedding": [ 0.1, 0.2, 0.3 ] } )

    def install():
        monkeypatch.setattr( mod, "requests", Requests )
        return calls

    install.Response = Response
    return install


@pytest.fixture
def creds( monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "seed@example.com" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )


# ── the safety net itself ────────────────────────────────────────────────────────

def test_an_unstubbed_test_cannot_reach_the_real_database():
    """
    The guard every other test leans on. If this stops raising, a forgotten stub reaches
    Postgres and `clean_seed_data` deletes real rows.
    """
    with pytest.raises( AssertionError, match="REAL database" ):
        with mod.get_db():
            pass


def test_an_unstubbed_test_cannot_make_a_real_http_request():
    with pytest.raises( AssertionError, match="REAL HTTP request" ):
        mod.requests.post( "http://localhost:7999/auth/login" )


# ── the scenario catalog ─────────────────────────────────────────────────────────

def test_the_catalog_covers_every_category_the_table_prints():
    """
    The distribution table iterates a HARD-CODED category list. A catalog category missing
    from that list would be silently dropped from the printed totals.
    """
    printed  = { "deployment", "testing", "deps", "architecture", "destructive", "general" }
    in_use   = { s[ "category" ] for s in mod.SCENARIO_CATALOG }

    assert in_use <= printed, f"catalog categories the table would not print: {in_use - printed}"


def test_every_scenario_carries_the_fields_the_seeder_reads():
    """
    seed_decisions indexes these keys directly, so a missing one is a KeyError mid-write —
    after earlier scenarios have already been inserted.
    """
    required = { "id", "question", "category", "sender_id", "expected_decision",
                 "suggested_ratification", "rationale", "semantic_group" }

    for scenario in mod.SCENARIO_CATALOG:
        missing = required - set( scenario )
        assert not missing, f"{scenario.get( 'id', '?' )} is missing {sorted( missing )}"


def test_scenario_ids_are_unique_because_they_are_the_ratification_key():
    """
    ratify_suggested builds seed_id → suggested_ratification as a dict. A duplicate id would
    silently take the last one's verdict for every row sharing it.
    """
    ids = [ s[ "id" ] for s in mod.SCENARIO_CATALOG ]

    assert len( ids ) == len( set( ids ) ), "duplicate scenario ids would collide in the lookup"


def test_every_suggested_ratification_is_approve_or_reject():
    """
    The summary counts anything that is not "approve" as a reject. A third value would be
    counted as a rejection without anyone noticing.
    """
    values = { s[ "suggested_ratification" ] for s in mod.SCENARIO_CATALOG }

    assert values <= { "approve", "reject" }, f"unexpected ratification values: {values}"


def test_category_summary_totals_match_the_catalog_length():
    summary = mod._get_category_summary()
    total   = sum( s[ "total" ] for s in summary.values() )

    assert total == len( mod.SCENARIO_CATALOG )
    for cat, counts in summary.items():
        assert counts[ "approve" ] + counts[ "reject" ] == counts[ "total" ], \
            f"{cat}: approve+reject does not equal total"


def test_the_distribution_table_prints_a_row_per_category_and_a_total( capsys ):
    mod._print_distribution_table()

    out     = capsys.readouterr().out
    summary = mod._get_category_summary()

    assert "Category" in out and "TOTAL" in out
    for cat in summary:
        assert cat in out
    assert str( len( mod.SCENARIO_CATALOG ) ) in out


# ── _login ───────────────────────────────────────────────────────────────────────

def test_login_returns_a_bearer_header_from_the_token_endpoint( creds, http ):
    calls = http()

    headers = mod._login()

    assert headers == { "Authorization": "Bearer tok-123" }
    assert calls[ 0 ][ "url" ].endswith( "/auth/login" )
    assert calls[ 0 ][ "json" ] == { "email": "seed@example.com", "password": "pw" }


@pytest.mark.parametrize( "missing", [
    "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL",
    "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD",
] )
def test_login_refuses_when_either_credential_is_absent( creds, monkeypatch, missing ):
    """Both halves matter — a missing password must fail as loudly as a missing email."""
    monkeypatch.delenv( missing )

    with pytest.raises( ValueError, match="LUPIN_TEST_INTERACTIVE_MOCK_JOBS" ):
        mod._login()


def test_login_propagates_an_http_failure_rather_than_returning_a_bad_header( creds, http, monkeypatch ):
    Response = http.Response

    class Failing:
        @staticmethod
        def post( url, json=None, headers=None, timeout=None ):
            return Response( {}, error=RuntimeError( "401 Unauthorized" ) )

    monkeypatch.setattr( mod, "requests", Failing )

    with pytest.raises( RuntimeError, match="401" ):
        mod._login()


# ── generate_embedding_via_api ───────────────────────────────────────────────────

def test_the_embedding_call_sends_the_text_and_returns_the_vector( http ):
    calls = http()

    vector = mod.generate_embedding_via_api( "some question", { "Authorization": "Bearer t" } )

    assert vector == [ 0.1, 0.2, 0.3 ]
    assert calls[ 0 ][ "url" ].endswith( "/api/embeddings/generate" )
    assert calls[ 0 ][ "json" ] == { "text": "some question", "content_type": "prose" }
    assert calls[ 0 ][ "headers" ] == { "Authorization": "Bearer t" }


def test_the_embedding_call_passes_a_non_default_content_type( http ):
    calls = http()

    mod.generate_embedding_via_api( "x", {}, content_type="code" )

    assert calls[ 0 ][ "json" ][ "content_type" ] == "code"


# ── _get_embedding_store ─────────────────────────────────────────────────────────

def test_the_store_is_built_from_the_configured_table_name_and_no_path( monkeypatch ):
    """
    The docstring records that passing a db_path made every invocation fail after the July
    cutover. This asserts the table name is read from config and no path is passed.
    """
    captured = {}

    class FakeConfig:
        def __init__( self, env_var_name=None ):
            captured[ "env_var_name" ] = env_var_name

        def get( self, key, default=None ):
            captured[ "key" ]     = key
            captured[ "default" ] = default
            return "configured_table"

    def fake_embeddings( **kwargs ):
        captured[ "kwargs" ] = kwargs
        return "the-store"

    monkeypatch.setattr( mod, "ConfigurationManager", FakeConfig )
    monkeypatch.setattr( mod, "ProxyDecisionEmbeddings", fake_embeddings )

    result = mod._get_embedding_store()

    assert result == "the-store"
    assert captured[ "env_var_name" ] == "LUPIN_CONFIG_MGR_CLI_ARGS"
    assert captured[ "default" ] == "proxy_decisions"
    assert captured[ "kwargs" ][ "table_name" ] == "configured_table"
    assert "db_path" not in captured[ "kwargs" ], "a db_path here is what broke the script in July"


# ── seed_decisions ───────────────────────────────────────────────────────────────

def test_seed_dry_run_writes_nothing_and_touches_no_collaborator( capsys ):
    """
    The whole point of --dry-run. get_db and requests are still the exploding autouse stubs,
    so if the dry run reached either, this test fails rather than silently seeding.
    """
    result = mod.seed_decisions( mod.SCENARIO_CATALOG, dry_run=True )

    out = capsys.readouterr().out
    assert result == []
    assert "[DRY RUN]" in out
    assert f"Would seed {len( mod.SCENARIO_CATALOG )} decisions" in out
    assert mod.SCENARIO_CATALOG[ 0 ][ "id" ] in out


def test_seed_with_an_unknown_category_returns_early_without_writing( capsys ):
    result = mod.seed_decisions( mod.SCENARIO_CATALOG, category_filter="no-such-category" )

    assert result == []
    assert "No scenarios found for category: no-such-category" in capsys.readouterr().out


def test_seed_filters_to_the_requested_category( capsys ):
    result = mod.seed_decisions( mod.SCENARIO_CATALOG, dry_run=True, category_filter="testing" )

    out      = capsys.readouterr().out
    expected = sum( 1 for s in mod.SCENARIO_CATALOG if s[ "category" ] == "testing" )

    assert result == []
    assert f"Would seed {expected} decisions" in out
    for scenario in mod.SCENARIO_CATALOG:
        if scenario[ "category" ] != "testing":
            assert scenario[ "id" ] not in out


def test_seed_logs_a_decision_embeds_it_and_stores_the_vector( creds, http, db, store ):
    """The full write path, asserted on WHAT was written rather than merely that it ran."""
    http()
    scenarios = mod.SCENARIO_CATALOG[ :2 ]
    repo      = db( log_returns=[ FakeDecision( "pg-a" ), FakeDecision( "pg-b" ) ] )
    fake      = store()

    results = mod.seed_decisions( scenarios )

    assert results == [ ( "pg-a", scenarios[ 0 ][ "id" ] ), ( "pg-b", scenarios[ 1 ][ "id" ] ) ]
    assert len( repo.logged ) == 2

    first = repo.logged[ 0 ]
    assert first[ "domain" ]                == "swe"
    assert first[ "question" ]              == scenarios[ 0 ][ "question" ]
    assert first[ "decision_value" ]        == scenarios[ 0 ][ "expected_decision" ]
    assert first[ "requires_ratification" ] is True
    assert first[ "data_origin" ]           == "synthetic_seed"
    # the cleanup marker is what makes --clean able to find these again
    assert first[ "metadata_json" ][ "seed_data" ] is True
    assert first[ "metadata_json" ][ "seed_id" ] == scenarios[ 0 ][ "id" ]

    assert len( fake.added ) == 2
    assert fake.added[ 0 ][ "id" ]                 == "pg-a"
    assert fake.added[ 0 ][ "question_embedding" ] == [ 0.1, 0.2, 0.3 ]
    assert fake.added[ 0 ][ "ratification_state" ] == "pending"


def test_seed_marks_every_row_for_cleanup_or_it_can_never_be_removed( creds, http, db, store ):
    """
    clean_seed_data finds rows ONLY by metadata_json.seed_data — a row written without it is
    unreachable by the cleaner and stays in the database permanently.
    """
    http()
    repo = db()
    store()

    mod.seed_decisions( mod.SCENARIO_CATALOG[ :3 ] )

    for logged in repo.logged:
        assert logged[ "metadata_json" ][ "seed_data" ] is True


# ── ratify_suggested ─────────────────────────────────────────────────────────────

def test_ratify_reports_nothing_to_do_when_no_seed_rows_are_pending( db, store, capsys ):
    db( pending=[] )
    store()

    result = mod.ratify_suggested( "me@example.com" )

    assert result == { "approved": 0, "rejected": 0 }
    assert "No seed decisions found pending ratification." in capsys.readouterr().out


def test_ratify_ignores_pending_rows_that_are_not_seed_data( db, store, capsys ):
    """A real pending decision must not be ratified by a seeding script."""
    db( pending=[
        FakeDecision( "real-1", metadata_json=None ),
        FakeDecision( "real-2", metadata_json={ "seed_data": False } ),
    ] )
    store()

    result = mod.ratify_suggested( "me@example.com" )

    assert result == { "approved": 0, "rejected": 0 }
    assert "No seed decisions found" in capsys.readouterr().out


def test_ratify_applies_each_scenarios_own_suggested_verdict( db, store ):
    approve_id = next( s[ "id" ] for s in mod.SCENARIO_CATALOG if s[ "suggested_ratification" ] == "approve" )
    reject_id  = next( s[ "id" ] for s in mod.SCENARIO_CATALOG if s[ "suggested_ratification" ] == "reject" )

    repo = db( pending=[
        FakeDecision( "pg-1", metadata_json={ "seed_data": True, "seed_id": approve_id } ),
        FakeDecision( "pg-2", metadata_json={ "seed_data": True, "seed_id": reject_id } ),
    ] )
    fake = store()

    result = mod.ratify_suggested( "me@example.com" )

    assert result == { "approved": 1, "rejected": 1 }
    assert repo.ratified[ 0 ][ 0 ] == "pg-1" and repo.ratified[ 0 ][ 1 ] is True
    assert repo.ratified[ 1 ][ 0 ] == "pg-2" and repo.ratified[ 1 ][ 1 ] is False
    assert repo.ratified[ 0 ][ 2 ] == "me@example.com"
    # the store must agree with Postgres, or the two sources of truth drift
    assert fake.states == [ ( "pg-1", "approved" ), ( "pg-2", "rejected" ) ]


def test_ratify_defaults_to_approve_for_a_seed_id_not_in_the_catalog( db, store ):
    """
    A row whose seed_id has since been removed from the catalog still has to resolve to
    something. The code chooses approve; this pins that choice so it cannot change silently.
    """
    repo = db( pending=[
        FakeDecision( "pg-x", metadata_json={ "seed_data": True, "seed_id": "seed-gone-999" } ),
    ] )
    store()

    result = mod.ratify_suggested( "me@example.com" )

    assert result == { "approved": 1, "rejected": 0 }
    assert repo.ratified[ 0 ][ 1 ] is True


# ── verify ───────────────────────────────────────────────────────────────────────

def _install_cbr( monkeypatch, prediction ):
    class FakeCBR:
        def __init__( self, embedding_store=None, top_k=None, debug=None ):
            pass

        def predict( self, question=None, category=None, query_embedding=None ):
            return prediction

    monkeypatch.setattr( mod, "CBRDecisionStore", FakeCBR )


def test_verify_reports_counts_matches_and_a_verdict( creds, http, db, store, monkeypatch, capsys ):
    http()
    db(
        rows=[
            FakeDecision( "r1", metadata_json={ "seed_data": True }, ratification_state="approved" ),
            FakeDecision( "r2", metadata_json={ "seed_data": True }, ratification_state="rejected" ),
            FakeDecision( "r3", metadata_json=None, ratification_state="approved" ),
        ],
        pending=[ FakeDecision( "p1", metadata_json={ "seed_data": True } ) ],
    )
    store( similar=[ ( 91.2, { "ratification_state": "approved", "question": "Should I run tests?" } ) ] )
    _install_cbr( monkeypatch, FakePrediction( verdict="approve", confidence=0.87, case_count=5 ) )

    mod.verify()

    out = capsys.readouterr().out
    assert "Seed pending:  1" in out
    assert "Seed ratified: 2" in out
    assert "Total seed:    3" in out
    assert "Results: 1 matches" in out
    assert "Verdict:    approve" in out
    assert "Cases used: 5" in out


def test_verify_says_the_store_may_be_empty_when_nothing_matches( creds, http, db, store, monkeypatch, capsys ):
    http()
    db( rows=[], pending=[] )
    store( similar=[] )
    _install_cbr( monkeypatch, FakePrediction( verdict=None ) )

    mod.verify()

    out = capsys.readouterr().out
    assert "Results: 0 matches (store may be empty)" in out
    assert "Verdict: None (no cases in store — seed + ratify first)" in out


def test_verify_scores_the_semantic_pair_as_a_pass_on_identical_vectors( creds, db, store, monkeypatch, capsys ):
    """
    Identical embeddings give cosine 1.0, which must read PASS. This pins the direction of the
    comparison — a flipped inequality would report WARN on a perfect match.
    """
    class Requests:
        @staticmethod
        def post( url, json=None, headers=None, timeout=None ):
            class R:
                @staticmethod
                def raise_for_status():
                    pass

                @staticmethod
                def json():
                    if "/auth/login" in url:
                        return { "tokens": { "access_token": "t" } }
                    return { "embedding": [ 1.0, 0.0, 0.0 ] }
            return R

    monkeypatch.setattr( mod, "requests", Requests )
    db( rows=[], pending=[] )
    store( similar=[] )
    _install_cbr( monkeypatch, FakePrediction( verdict=None ) )

    mod.verify()

    out = capsys.readouterr().out
    assert "Cosine similarity: 1.0000 [PASS]" in out


def test_verify_reports_warn_and_does_not_divide_by_zero_on_a_zero_vector( creds, db, store, monkeypatch, capsys ):
    """
    A zero embedding makes both norms zero. The guard must produce 0.0 rather than raise
    ZeroDivisionError inside a verification routine.
    """
    class Requests:
        @staticmethod
        def post( url, json=None, headers=None, timeout=None ):
            class R:
                @staticmethod
                def raise_for_status():
                    pass

                @staticmethod
                def json():
                    if "/auth/login" in url:
                        return { "tokens": { "access_token": "t" } }
                    return { "embedding": [ 0.0, 0.0, 0.0 ] }
            return R

    monkeypatch.setattr( mod, "requests", Requests )
    db( rows=[], pending=[] )
    store( similar=[] )
    _install_cbr( monkeypatch, FakePrediction( verdict=None ) )

    mod.verify()

    assert "Cosine similarity: 0.0000 [WARN]" in capsys.readouterr().out


# ── clean_seed_data ──────────────────────────────────────────────────────────────

def test_clean_reports_nothing_to_do_when_no_seed_rows_exist( db, store, capsys ):
    db( rows=[ FakeDecision( "real", metadata_json=None ) ] )
    store()

    mod.clean_seed_data()

    assert "No seed data found to clean." in capsys.readouterr().out


def test_clean_deletes_only_rows_marked_as_seed_data( db, store, capsys ):
    """
    The blast radius of this function. A real decision must survive it — that is the whole
    reason rows carry the seed_data marker.
    """
    repo = db( rows=[
        FakeDecision( "seed-1", metadata_json={ "seed_data": True } ),
        FakeDecision( "real-1", metadata_json={ "seed_data": False } ),
        FakeDecision( "real-2", metadata_json=None ),
    ] )
    fake = store()

    mod.clean_seed_data()

    assert repo.deleted == [ "seed-1" ], "a non-seed decision was deleted"
    assert fake._table.deletes == [ "id = 'seed-1'" ]
    assert "Deleted 1 seed decisions" in capsys.readouterr().out


def test_clean_resets_a_ratified_row_to_pending_before_deleting_it( db, store ):
    """
    delete_pending only works on pending rows, so a ratified seed row has to be reset first
    or it would be left behind by a cleanup that reported success.
    """
    repo    = db( rows=[ FakeDecision( "seed-r", metadata_json={ "seed_data": True }, ratification_state="approved" ) ] )
    store()

    mod.clean_seed_data()

    assert repo.deleted == [ "seed-r" ]
    assert repo.session.flushed == 1
    assert repo.session._rows[ 0 ].ratification_state == "pending"


def test_clean_escapes_a_quote_in_the_id_before_building_the_delete_clause( db, store ):
    """The delete clause is built by string interpolation, so an embedded quote must be doubled."""
    db( rows=[ FakeDecision( "it's-1", metadata_json={ "seed_data": True } ) ] )
    fake = store()

    mod.clean_seed_data()

    assert fake._table.deletes == [ "id = 'it''s-1'" ]


def test_clean_still_removes_the_postgres_row_when_the_store_delete_fails( db, store, capsys ):
    """
    The embedding-store delete is best-effort by design. A store outage must not leave the
    Postgres row behind — that would make a re-run report nothing to clean while rows remain.
    """
    repo = db( rows=[ FakeDecision( "seed-1", metadata_json={ "seed_data": True } ) ] )
    store( ensure_raises=True )

    mod.clean_seed_data()

    out = capsys.readouterr().out
    assert "Warning: embedding-store delete failed" in out
    assert repo.deleted == [ "seed-1" ], "the Postgres row was skipped because the store failed"


def test_clean_skips_the_store_delete_when_the_table_is_absent( db, store ):
    """_ensure_table returning False means there is no table to delete from — not an error."""
    repo = db( rows=[ FakeDecision( "seed-1", metadata_json={ "seed_data": True } ) ] )
    fake = store( ensure=False )

    mod.clean_seed_data()

    assert fake._table.deletes == []
    assert repo.deleted == [ "seed-1" ]


# ── main ─────────────────────────────────────────────────────────────────────────

def _argv( monkeypatch, *args ):
    monkeypatch.setattr( sys, "argv", [ "seed_proxy_decisions.py", *args ] )


def test_main_defaults_to_seeding_the_whole_catalog( monkeypatch ):
    seen = {}
    monkeypatch.setattr( mod, "seed_decisions", lambda **kw: seen.update( kw ) )
    _argv( monkeypatch )

    mod.main()

    assert seen[ "scenarios" ] is mod.SCENARIO_CATALOG
    assert seen[ "dry_run" ] is False
    assert seen[ "category_filter" ] is None


def test_main_passes_dry_run_and_category_through( monkeypatch ):
    seen = {}
    monkeypatch.setattr( mod, "seed_decisions", lambda **kw: seen.update( kw ) )
    _argv( monkeypatch, "--dry-run", "--category", "testing" )

    mod.main()

    assert seen[ "dry_run" ] is True
    assert seen[ "category_filter" ] == "testing"


def test_main_routes_verify( monkeypatch ):
    called = []
    monkeypatch.setattr( mod, "verify", lambda: called.append( "verify" ) )
    _argv( monkeypatch, "--verify" )

    mod.main()

    assert called == [ "verify" ]


def test_main_routes_clean( monkeypatch ):
    called = []
    monkeypatch.setattr( mod, "clean_seed_data", lambda: called.append( "clean" ) )
    _argv( monkeypatch, "--clean" )

    mod.main()

    assert called == [ "clean" ]


def test_main_routes_ratify_with_the_given_email( monkeypatch ):
    called = []
    monkeypatch.setattr( mod, "ratify_suggested", lambda email: called.append( email ) )
    _argv( monkeypatch, "--ratify", "--user-email", "me@example.com" )

    mod.main()

    assert called == [ "me@example.com" ]


def test_main_refuses_ratify_without_an_email_rather_than_attributing_it_to_nobody( monkeypatch, capsys ):
    """
    Ratification is recorded against a person. Defaulting the attribution would write a
    permanent record crediting no one.
    """
    _argv( monkeypatch, "--ratify" )

    with pytest.raises( SystemExit ):
        mod.main()

    assert "--user-email is required with --ratify" in capsys.readouterr().err


def test_verify_wins_when_several_operation_flags_are_given( monkeypatch ):
    """The if/elif order is a real contract — pinned so a reorder cannot pass silently."""
    called = []
    monkeypatch.setattr( mod, "verify", lambda: called.append( "verify" ) )
    monkeypatch.setattr( mod, "clean_seed_data", lambda: called.append( "clean" ) )
    _argv( monkeypatch, "--verify", "--clean" )

    mod.main()

    assert called == [ "verify" ], "clean ran despite --verify taking precedence"


# ── the hard-coded category list vs the catalog ──────────────────────────────────

def test_the_table_skips_a_printed_category_the_catalog_no_longer_uses( monkeypatch, capsys ):
    """
    The table iterates a HARD-CODED list of six categories and prints only those present in
    the catalog. With every category currently populated, the skip arm never runs — so it is
    exercised here with a catalog trimmed to one category. Without this, a future catalog that
    drops a category would take an untested path while printing the totals people read.
    """
    testing_only = [ s for s in mod.SCENARIO_CATALOG if s[ "category" ] == "testing" ]
    monkeypatch.setattr( mod, "SCENARIO_CATALOG", testing_only )

    mod._print_distribution_table()

    out = capsys.readouterr().out
    assert "testing" in out
    assert "deployment" not in out, "a category absent from the catalog was still printed"
    # the grand total must count only what was printed, not what the hard-coded list names
    assert str( len( testing_only ) ) in out


# ── the import-time bootstrap ────────────────────────────────────────────────────
#
# Lines 39-50 run ONCE, at import, before any test exists, so no ordinary test can reach the
# LUPIN_ROOT-missing arm or the sys.path insert. They are re-executed from source under
# controlled conditions — the only honest way to cover an import-time guard, since the
# alternative is a pragma that asserts nothing.

def _exec_bootstrap():
    """
    Re-execute the module's own source, compiled under its REAL filename so coverage attributes
    the lines to the file.

    The path is resolved from the ALREADY-IMPORTED module, never from LUPIN_ROOT — these tests
    manipulate that variable, so reading the path from it would point the probe at a directory
    the test just invented.
    """
    source_path = mod.__file__
    with open( source_path, encoding="utf-8" ) as handle:
        code = compile( handle.read(), source_path, "exec" )
    namespace = { "__name__": "seed_proxy_bootstrap_probe", "__file__": source_path }
    exec( code, namespace )
    return namespace


def test_the_bootstrap_raises_when_lupin_root_is_not_set( monkeypatch ):
    """
    A standalone run with no LUPIN_ROOT must fail immediately with a usable message, rather
    than stumbling on to a TypeError inside os.path.join( None, "src" ).
    """
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )

    with pytest.raises( RuntimeError, match="LUPIN_ROOT environment variable not set" ):
        _exec_bootstrap()


def test_the_bootstrap_puts_src_on_sys_path_when_it_is_absent( monkeypatch, tmp_path ):
    """
    The insert arm never runs under pytest because conftest has already put src on the path.
    Pointing LUPIN_ROOT at a directory whose src is NOT on the path exercises it.
    """
    fake_root = tmp_path / "fake-root"
    ( fake_root / "src" ).mkdir( parents=True )
    expected  = os.path.join( str( fake_root ), "src" )

    original_path = list( sys.path )
    assert expected not in sys.path
    try:
        monkeypatch.setenv( "LUPIN_ROOT", str( fake_root ) )
        _exec_bootstrap()
        assert sys.path[ 0 ] == expected, "the bootstrap must insert at position 0, not append"
    finally:
        sys.path[ : ] = original_path

    assert expected not in sys.path
