"""
The audit queue never holds more audits than the ledger's headroom pays for.

582 queued audits at a 2.5M mean is 1.46 billion tokens against about 75M free. Ledgers here are temporary files.
"""
from cosa.repo.symindex.candidates import shadow_audit as sa
from lupin_mcp import duplicate_check_audit as dca
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_shadow as rsh

LIVE = { "verdict": "NO_MATCH", "candidate_ids": [] }


def queue( data, need, **kw ):
    """Ensures: queues one lookup the way the known-miss path does."""
    return sa.enqueue_pending( data, need, "py", "gen", "sha", LIVE, "2026-11-18", **kw )


def test_a_full_queue_refuses_a_new_lookup_and_writes_nothing( tmp_path ):
    assert queue( tmp_path, "one", max_pending=2 ) and queue( tmp_path, "two", max_pending=2 )
    assert queue( tmp_path, "three", max_pending=2 ) is None
    assert sa.pending_count( tmp_path ) == 2


def test_a_lookup_already_queued_is_never_refused_so_a_known_miss_upgrade_still_lands( tmp_path ):
    queue( tmp_path, "one", max_pending=1 )
    assert queue( tmp_path, "one", known_miss=True, tie="ruling", max_pending=1 ) is not None
    assert sa.pending_count( tmp_path ) == 1


def test_a_zero_cap_queues_nothing_and_no_cap_queues_everything( tmp_path ):
    assert queue( tmp_path, "a", max_pending=0 ) is None and sa.pending_count( tmp_path ) == 0
    assert all( queue( tmp_path, f"n{i}" ) for i in range( 5 ) ) and sa.pending_count( tmp_path ) == 5


def test_pending_count_leaves_temporary_files_out( tmp_path ):
    queue( tmp_path, "a" )
    ( tmp_path / "shadow-pending" / f"{sa.TEMP_PREFIX}x.json" ).write_text( "{}", encoding="utf-8" )
    assert sa.pending_count( tmp_path ) == 1


def test_a_sampled_lookup_on_a_full_queue_is_counted_but_not_queued( tmp_path ):
    assert sa.enqueue_if_sampled( tmp_path, "need", "py", "g", "s", LIVE, "2026-11-18", rate=1, max_pending=0 ) is None
    assert sa.enqueue_if_sampled( tmp_path, "need", "py", "g", "s", LIVE, "2026-11-18", rate=1, max_pending=1 ) is not None


def test_the_cap_is_headroom_over_the_mean_sweep_rounded_down( tmp_path ):
    led = rl.AccountLedger.create( tmp_path / "l.jsonl", limit_tokens=100_000_000, by="t", why="fixture" )
    led.begin_run( "r", 25_000_001 )
    assert rsh.pending_cap( led.path ) == 74_999_999 // rsh.MEAN_AUDIT_TOKENS == 29


def test_an_overspent_ledger_caps_at_zero( tmp_path ):
    led = rl.AccountLedger.create( tmp_path / "l.jsonl", limit_tokens=1_000_000, by="t", why="fixture" )
    led.begin_run( "r", 1_000_000 )
    assert rsh.pending_cap( led.path ) == 0


def test_a_missing_ledger_means_no_cap_and_an_unreadable_one_means_zero( tmp_path ):
    assert rsh.pending_cap( tmp_path / "none.jsonl" ) is None
    bad = tmp_path / "bad.jsonl"; bad.write_text( "not json\n", encoding="utf-8" )
    assert rsh.pending_cap( bad ) == 0


def test_the_cap_of_a_context_follows_its_own_ledger_else_the_fleet_ledger( tmp_path, monkeypatch ):
    led = rl.AccountLedger.create( tmp_path / "l.jsonl", limit_tokens=10_000_000, by="t", why="fixture" )
    class Ctx: ledger = led; root = tmp_path
    assert rsh.pending_cap_for( Ctx ) == 4
    Ctx.ledger = None
    monkeypatch.setattr( rl, "ledger_path", lambda root: tmp_path / "fleet.jsonl" )
    assert rsh.pending_cap_for( Ctx ) is None


def test_queue_audits_counts_queue_full_and_queues_no_more_than_the_cap( tmp_path ):
    findings = [ { "id": f"f{i}", "file": "a.py", "name": f"n{i}", "line": 1 } for i in range( 3 ) ]
    receipts = { f"r{i}": { "tool": "check_exists", "query": f"need {i}", "language": "py", "candidate_stage": { "manifest_hash": "g", "ids": [] },
                            "index_sha": "s", "verdict": "NO_MATCH" } for i in range( 3 ) }
    out = dca.queue_audits( findings, lambda f: { "tie": "ruling", "tool": "check_exists", "receipt_id": "r" + f[ "id" ][ 1: ] }, receipts.__getitem__,
                            tmp_path, "2026-11-18", lambda f: f[ "id" ], max_pending=2 )
    assert out[ "counters" ][ dca.QUEUED ] == 2 and out[ "counters" ][ dca.QUEUE_FULL ] == 1
    assert list( out[ "reasons" ] ) == [ "f2" ] and sa.pending_count( tmp_path ) == 2


def test_a_served_lookup_is_offered_to_the_queue_with_the_ledgers_cap( tmp_path, monkeypatch ):
    from lupin_mcp import reuse_tools as rt
    led  = rl.AccountLedger.create( tmp_path / "l.jsonl", limit_tokens=10_000_000, by="t", why="fixture" )
    seen = {}
    monkeypatch.setattr( rsh, "queue_lookup", lambda data, receipt, today, max_pending=None: seen.update( cap=max_pending ) )
    rt._queue_shadow_audit( type( "Ctx", ( ), { "data": tmp_path, "ledger": led } )(), {} )
    assert seen == { "cap": 4 }
