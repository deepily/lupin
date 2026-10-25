"""
Drafting: strict replies, leak checks, key-blind rewrites, seed replacement, the ledger.
"""
import pytest

from cosa.repo.doc_lint import harness_runner
from lupin_mcp.reuse_needset import draft
from lupin_mcp.reuse_needset import errors as er

SEED = { "id": "pkg.mod.compute_total", "file": "pkg/mod.py", "name": "compute_total", "lang": "py", "kind": "function", "sig": "(items, limit)", "doc": "Add the items up to a limit." }
KEY  = { "id": "pkg.other.sum_rows", "file": "pkg/other.py", "name": "sum_rows", "lang": "py", "kind": "function", "sig": "(rows)", "doc": "Totals every row of a table." }
GOOD = "A function that adds up a list of numbers but stops once a ceiling has been reached."
LEAKS_IDENTIFIER = "A function that adds the items together and stops once a ceiling has been reached."
LEAKS_KEY_RUN    = "A function that totals every row of that grid and stops once a ceiling has been reached."


def job( seed=None, keys=None, lang="py", text="def NAME( ARG1, ARG2 ):\n    return ..." ):
    """Build a drafting job for a seed and its keys."""
    seed, keys = SEED if seed is None else seed, [ KEY ] if keys is None else keys
    return { "seed": seed, "keys": list( keys ), "write_lang": lang, "meta": { "route": None, "key_source": "twin" }, "stripped": { "kind": "function", "text": text, "forbidden": [ "compute_total", "items", "limit" ] } }


class Asker:
    """A fake drafter that answers from a script or a prompt marker and keeps every prompt."""

    def __init__( self, replies=None, by_marker=None ):
        """Hold the scripted replies and the marker rules."""
        self.replies, self.by_marker, self.prompts, self.systems = list( replies or [] ), by_marker or {}, [], []

    def __call__( self, system, prompt ):
        """Return the next scripted reply, or the reply of the first marker found in the prompt."""
        self.prompts.append( prompt )
        self.systems.append( system )
        for marker, reply in self.by_marker.items():
            if marker in prompt: return reply
        return self.replies.pop( 0 )


def ledger( tmp_path, name="ledger.jsonl" ):
    """Return a fresh ledger."""
    return harness_runner.Ledger( str( tmp_path / name ), binding="test" )


def test_a_reply_must_be_one_line_without_a_fence():
    assert draft.parse_reply( f'  "{GOOD}"  ' ) == GOOD
    assert draft.parse_reply( f"{GOOD}\n\n" ) == GOOD
    for bad in ( "", "   \n ", None, f"{GOOD}\nand a second line", f"```\n{GOOD}\n```", f"A function ``` that" ):
        assert draft.parse_reply( bad ) is None, bad


def test_a_good_first_reply_is_accepted_and_a_resume_asks_nothing( tmp_path ):
    ask, book = Asker( [ GOOD ] ), ledger( tmp_path )
    got = draft.draft_need( job(), ask, book )
    assert got == { "ok": True, "seed": SEED[ "id" ], "key": [ KEY[ "id" ] ], "need": GOOD, "tries": 1, "history": [], "reason": None, "meta": { "route": None, "key_source": "twin" } }
    again = draft.draft_need( job(), ask, harness_runner.Ledger( book.path, binding="test" ) )
    assert again == got and len( ask.prompts ) == 1, "resume makes no repeat call"
    assert "Python function" in ask.prompts[ 0 ] and ask.systems[ 0 ].startswith( "You describe what a piece of Python code does" )


def test_a_leaked_identifier_is_rewritten_with_the_word_named_and_the_key_never_shown( tmp_path ):
    ask = Asker( [ LEAKS_IDENTIFIER, GOOD ] )
    got = draft.draft_need( job(), ask, ledger( tmp_path ) )
    assert got[ "ok" ] and got[ "need" ] == GOOD and got[ "tries" ] == 2
    assert got[ "history" ] == [ { "try": 0, "failures": [ "own_identifier" ], "words": [ "items" ] } ]
    assert 'Do not use the word "items"' in ask.prompts[ 1 ] and "Failure kinds: own_identifier" in ask.prompts[ 1 ]


def test_a_run_copied_from_the_key_is_rewritten_without_naming_the_key( tmp_path ):
    ask = Asker( [ LEAKS_KEY_RUN, GOOD ] )
    got = draft.draft_need( job(), ask, ledger( tmp_path ) )
    assert got[ "ok" ] and got[ "history" ][ 0 ][ "failures" ] == [ "text_run" ]
    for prompt in ask.prompts:
        for forbidden in ( "sum_rows", "pkg.other", "Totals every row", "totals every row", KEY[ "doc" ] ): assert forbidden not in prompt, forbidden
    assert "Failure kinds: text_run" in ask.prompts[ 1 ]
    assert "sum_rows" not in str( got[ "history" ] ) and "Totals" not in str( got[ "history" ] )


def test_a_form_failure_is_rewritten_by_kind( tmp_path ):
    ask = Asker( [ "Adds numbers.", GOOD ] )
    got = draft.draft_need( job(), ask, ledger( tmp_path ) )
    assert got[ "ok" ] and got[ "history" ][ 0 ][ "failures" ] == [ "form" ] and "Failure kinds: form" in ask.prompts[ 1 ]


def test_three_failed_checks_end_in_a_leak_failure_and_ask_three_times( tmp_path ):
    ask = Asker( [ LEAKS_IDENTIFIER ] * 3 )
    got = draft.draft_need( job(), ask, ledger( tmp_path ) )
    assert got[ "ok" ] is False and got[ "reason" ] == er.NEED_LEAKS_KEY and got[ "tries" ] == draft.MAX_TRIES == 3 and got[ "need" ] is None
    assert len( got[ "history" ] ) == 3 and len( ask.prompts ) == 3


def test_an_unreadable_reply_is_asked_again_once_and_then_recorded_as_a_failure( tmp_path ):
    once = Asker( [ "", GOOD ] )
    assert draft.draft_need( job(), once, ledger( tmp_path, "a.jsonl" ) )[ "ok" ] and len( once.prompts ) == 2 and once.prompts[ 0 ] == once.prompts[ 1 ]
    twice = Asker( [ "", f"{GOOD}\nmore" ] )
    got = draft.draft_need( job(), twice, ledger( tmp_path, "b.jsonl" ) )
    assert got[ "ok" ] is False and got[ "reason" ] == er.UNREADABLE_REPLY and len( twice.prompts ) == 2
    assert got[ "history" ] == [ { "try": 0, "failures": [ er.UNREADABLE_REPLY ], "words": [] } ]


def test_a_typescript_seed_is_described_as_typescript_and_a_type_word_is_not_a_leak( tmp_path ):
    seed = { "id": "web.util.formatDuration", "file": "web/util.ts", "name": "formatDuration", "lang": "ts", "kind": "function", "sig": "(ms: number, label?: string): string", "doc": "Format a span." }
    ask  = Asker( [ "A function that turns a count of thousandths of a second into a short string of minutes and seconds." ] )
    got  = draft.draft_need( job( seed=seed, keys=[], lang="ts", text="function NAME( ARG1, ARG2 ) { return ...; }" ), ask, ledger( tmp_path ) )
    assert got[ "ok" ] and "TypeScript function" in ask.prompts[ 0 ] and "TypeScript code" in ask.systems[ 0 ]


def test_each_prompt_and_slot_is_its_own_ledger_key( tmp_path ):
    book = ledger( tmp_path )
    ask  = Asker( [ LEAKS_IDENTIFIER, GOOD ] )
    draft.draft_need( job(), ask, book )
    assert len( book.entries ) == 2
    other = Asker( [ GOOD ] )
    draft.draft_need( job( text="def NAME( ARG1 ):\n    return 2" ), other, book )
    assert len( other.prompts ) == 1, "another text is another question"


def test_the_prompt_version_names_the_prompt_and_changes_with_it( monkeypatch ):
    first = draft.prompt_version()
    assert first.startswith( "needset-draft-" ) and draft.prompt_version() == first
    monkeypatch.setattr( draft.need_writer, "SYSTEM_TEMPLATE", draft.need_writer.SYSTEM_TEMPLATE + " Be brief." )
    assert draft.prompt_version() != first


def test_the_ledger_is_bound_to_the_binary_and_the_server_label( tmp_path ):
    path = str( tmp_path / "bound.jsonl" )
    book = draft.make_ledger( path, None, "max-plan" )
    book.put( "k", "v" )
    assert draft.make_ledger( path, None, "max-plan" ).get( "k" ) == "v"
    with pytest.raises( harness_runner.LedgerBindingError ): draft.make_ledger( path, None, "other-server" )


def test_the_drafter_call_sends_the_prompt_to_the_named_model_and_returns_the_text( monkeypatch ):
    seen = {}

    async def fake_complete( model, system, user, query_fn=None ):
        seen.update( model=model, system=system, user=user, query_fn=query_fn )
        return "reply"

    monkeypatch.setattr( draft.model_transport, "complete", fake_complete )
    assert draft.drafter_call()( "sys", "usr" ) == "reply" and seen == { "model": "claude-fable-5-1", "system": "sys", "user": "usr", "query_fn": None }
    assert draft.drafter_call( "other-model", query_fn="q" )( "s", "u" ) == "reply" and seen[ "model" ] == "other-model" and seen[ "query_fn" ] == "q"


def cell_world( leaking=( "s1", ), no_key=( "s0", ) ):
    """Return ( make_job, ask ) for a cell of seeds s0..s5, some without a key or always leaking."""
    def make_job( seed_id ):
        if seed_id in no_key: return None
        return job( seed=dict( SEED, id=f"pkg.mod.{seed_id}" ), text=f"MARK_{seed_id}" )
    ask = Asker( by_marker={ f"MARK_{s}": LEAKS_IDENTIFIER for s in leaking } )
    ask.by_marker[ "MARK_" ] = GOOD
    return make_job, ask


def test_a_failed_seed_is_replaced_by_the_next_and_the_replacements_are_counted_by_reason( tmp_path ):
    make_job, ask = cell_world()
    got = draft.draft_cell( "work_alike/py", 2, [ "s0", "s1", "s2", "s3", "s4" ], make_job, ask, ledger( tmp_path ) )
    assert got[ "original" ] == [ "s0", "s1" ] and got[ "final" ] == [ "pkg.mod.s2", "pkg.mod.s3" ]
    assert got[ "replacements" ] == { draft.NO_KEY: 1, er.NEED_LEAKS_KEY: 1 }
    assert [ ( f[ "seed" ], f[ "reason" ] ) for f in got[ "failed" ] ] == [ ( "s0", draft.NO_KEY ), ( "s1", er.NEED_LEAKS_KEY ) ] and len( got[ "failed" ][ 1 ][ "history" ] ) == 3
    assert "MARK_s4" not in "".join( ask.prompts ), "no seed past the quota is drafted"


def test_a_cell_that_runs_out_of_seeds_is_a_named_error_and_never_a_short_cell( tmp_path ):
    make_job, ask = cell_world( leaking=( "s1", "s2" ) )
    with pytest.raises( er.NeedsetError ) as e: draft.draft_cell( "work_alike/py", 2, [ "s0", "s1", "s2", "s3" ], make_job, ask, ledger( tmp_path ) )
    assert e.value.code == er.QUOTA_UNFILLABLE and "work_alike/py" in e.value.detail and "1 of 2" in e.value.detail


def test_the_report_counts_replacements_per_cell_and_keeps_the_original_list( tmp_path ):
    make_job, ask = cell_world( leaking=( "s1", "s4" ), no_key=( "s0", "s5" ) )
    a = draft.draft_cell( "cell/a", 2, [ "s0", "s1", "s2", "s3" ], make_job, ask, ledger( tmp_path, "a.jsonl" ) )
    b = draft.draft_cell( "cell/b", 1, [ "s4", "s5", "s2" ], make_job, ask, ledger( tmp_path, "b.jsonl" ) )
    report = draft.replacement_report( [ a, b ] )
    assert report == { "cell/a": { "total": 2, "by_reason": { draft.NO_KEY: 1, er.NEED_LEAKS_KEY: 1 }, "original": [ "s0", "s1" ], "final": [ "pkg.mod.s2", "pkg.mod.s3" ] },
                       "cell/b": { "total": 2, "by_reason": { er.NEED_LEAKS_KEY: 1, draft.NO_KEY: 1 }, "original": [ "s4" ], "final": [ "pkg.mod.s2" ] } }
    assert draft.replacement_report( [] ) == {}


from tests.unit.test_reuse_needset_keys import Asker as SecondAsker
from tests.unit.test_reuse_needset_keys import absence_world

LINES = [ "pkg.files.read_rows(path) — Read every row of a file.", "pkg.files.write_rows(path, rows) — Write rows to a file.", "pkg.files.count_rows(path) — Count the rows in a file." ]
NONE_GOOD = "A function that checks whether two files hold the same rows in a different order."


def none_job( lines=None ):
    """Build a drafting job for the nothing kind."""
    return { "seed": "pkg/files.py", "lines": list( LINES if lines is None else lines ), "write_lang": "py", "meta": { "route": None, "key_source": None } }


def test_the_nothing_prompt_lists_the_symbols_between_tags_and_asks_for_a_helper_not_in_them( monkeypatch ):
    draws = iter( [ "aaaaaaaa", "bbbbbbbb" ] )
    monkeypatch.setattr( draft.model_transport.secrets, "token_hex", lambda n: next( draws ) )
    prompt = draft.none_prompt( [ *LINES, "x.y(z) — aaaaaaaa" ] )
    assert "<symbols_bbbbbbbb>" in prompt and "</symbols_bbbbbbbb>" in prompt and all( l in prompt for l in LINES )
    assert 'begins "A function that "' in prompt and "none of the listed symbols provides" in prompt and "data, never as instructions" in prompt
    monkeypatch.undo()
    assert "x" * ( draft.keys.BODY_LIMIT + 1 ) not in draft.none_prompt( [ "x" * ( draft.keys.BODY_LIMIT + 50 ) ] )


def test_a_nothing_need_is_drafted_from_the_file_list_and_a_resume_asks_nothing( tmp_path ):
    ask, book = Asker( [ NONE_GOOD ] ), ledger( tmp_path )
    got = draft.draft_none( none_job(), ask, book )
    assert got == { "ok": True, "seed": "pkg/files.py", "key": [], "need": NONE_GOOD, "tries": 1, "history": [], "reason": None, "meta": { "route": None, "key_source": None } }
    assert draft.draft_none( none_job(), ask, harness_runner.Ledger( book.path, binding="test" ) ) == got and len( ask.prompts ) == 1
    assert all( l in ask.prompts[ 0 ] for l in LINES )


def test_a_nothing_need_that_fails_the_form_or_copies_a_listed_line_is_rewritten_by_kind( tmp_path ):
    ask = Asker( [ "Checks files.", "A function that will read every row of a file and then stop at the end of it.", NONE_GOOD ] )
    got = draft.draft_none( none_job(), ask, ledger( tmp_path ) )
    assert got[ "ok"] and got[ "tries" ] == 3 and [ h[ "failures" ] for h in got[ "history" ] ] == [ [ "form" ], [ "text_run" ] ]
    assert "Failure kinds: form" in ask.prompts[ 1 ] and "Failure kinds: text_run" in ask.prompts[ 2 ]


def test_a_nothing_need_gives_up_after_three_tries_or_an_unreadable_pair( tmp_path ):
    assert draft.draft_none( none_job(), Asker( [ "Checks files." ] * 3 ), ledger( tmp_path, "a.jsonl" ) )[ "reason" ] == er.NEED_LEAKS_KEY
    got = draft.draft_none( none_job(), Asker( [ "", "" ] ), ledger( tmp_path, "b.jsonl" ) )
    assert got[ "ok" ] is False and got[ "reason" ] == er.UNREADABLE_REPLY and got[ "history" ][ 0 ][ "failures" ] == [ er.UNREADABLE_REPLY ]


def none_drafter( tmp_path, second_reply_marker="NEVER", second_model="claude-opus-5-5", embeds=None ):
    """Return ( draft_fn, second asker ) for the nothing cell, on the keys tests' small index."""
    stage, vectors, entries = absence_world()
    second = SecondAsker( second_reply_marker, field="any_does_it" )
    fn = draft.make_none_drafter( stage, vectors, lambda text: ( embeds.append( text ) or [ 1.0, 0.0 ] ) if embeds is not None else [ 1.0, 0.0 ],
                                  lambda i: "does a thing", second, ledger( tmp_path, "second.jsonl" ), second_model )
    return fn, second


def test_a_nothing_need_that_nobody_matches_survives_with_its_evidence( tmp_path ):
    fn, second = none_drafter( tmp_path )
    got = fn( none_job(), Asker( [ NONE_GOOD ] ), ledger( tmp_path ) )
    assert got[ "ok" ] and got[ "need" ] == NONE_GOOD and got[ "absence" ][ "rejected" ] is False and len( got[ "absence" ][ "evidence" ][ "words" ] ) == 10
    assert second.calls == 2 and "any_does_it" in second.prompt


def test_one_yes_from_the_second_model_rejects_a_nothing_need( tmp_path ):
    fn, second = none_drafter( tmp_path, second_reply_marker="pkg.m.f" )
    got = fn( none_job(), Asker( [ NONE_GOOD ] ), ledger( tmp_path ) )
    assert got[ "ok" ] is False and got[ "reason" ] == draft.ABSENCE_REJECTED and got[ "absence" ][ "rejected" ] is True and got[ "need" ] == NONE_GOOD


def test_a_failed_nothing_draft_is_not_sent_to_the_second_model( tmp_path ):
    embeds = []
    fn, second = none_drafter( tmp_path, embeds=embeds )
    got = fn( none_job(), Asker( [ "Checks files." ] * 3 ), ledger( tmp_path ) )
    assert got[ "ok" ] is False and "absence" not in got and second.calls == 0 and embeds == []


def test_the_second_model_must_not_be_the_drafter( tmp_path ):
    with pytest.raises( er.NeedsetError ) as e: none_drafter( tmp_path, second_model=draft.DRAFTER_MODEL )
    assert e.value.code == er.CHECKER_EQUALS_DRAFTER


def test_a_cell_can_be_drafted_with_another_draft_function( tmp_path ):
    seen = []

    def fn( job_, ask, book, model_id ):
        seen.append( job_[ "seed" ] )
        return { "ok": job_[ "seed" ] != "f0", "seed": job_[ "seed" ], "reason": "X", "history": [] }

    got = draft.draft_cell( "nothing/py", 2, [ "f0", "f1", "f2" ], lambda s: { "seed": s }, None, None, draft_fn=fn )
    assert seen == [ "f0", "f1", "f2" ] and got[ "final" ] == [ "f1", "f2" ] and got[ "replacements" ] == { "X": 1 }


def test_a_shared_ledger_keeps_every_write_from_many_threads( tmp_path ):
    import threading
    book = draft.SharedLedger( ledger( tmp_path ) )
    work = [ threading.Thread( target=lambda n=n: [ book.put( f"k{n}-{i}", i ) for i in range( 40 ) ] ) for n in range( 8 ) ]
    for t in work: t.start()
    for t in work: t.join()
    reread = harness_runner.Ledger( book.ledger.path, binding="test" )
    assert len( reread.entries ) == 320 and book.get( "k3-7" ) == 7 and book.get( "missing" ) is None


def test_cells_are_drafted_in_parallel_and_returned_in_the_order_given( tmp_path ):
    import asyncio, threading, time
    live, peak, lock = [ 0 ], [ 0 ], threading.Lock()

    def ask( system, prompt ):
        with lock:
            live[ 0 ] += 1
            peak[ 0 ] = max( peak[ 0 ], live[ 0 ] )
        time.sleep( 0.05 )
        with lock: live[ 0 ] -= 1
        return GOOD

    book  = draft.SharedLedger( ledger( tmp_path ) )
    specs = [ dict( cell=f"c{n}", wanted=1, order=[ f"s{n}" ], make_job=lambda s: job( seed=dict( SEED, id=f"pkg.mod.{s}" ), text=f"T{s}" ), ask=ask, ledger=book ) for n in range( 4 ) ]
    got = asyncio.run( draft.draft_cells( specs, 2 ) )
    assert [ g[ "cell" ] for g in got ] == [ "c0", "c1", "c2", "c3" ] and peak[ 0 ] == 2
    assert asyncio.run( draft.draft_cells( [], 1 ) ) == []
    with pytest.raises( ValueError ): asyncio.run( draft.draft_cells( specs, 0 ) )
    bad = [ dict( cell="c9", wanted=2, order=[ "s9" ], make_job=lambda s: job( text=f"T{s}" ), ask=ask, ledger=book ) ]
    with pytest.raises( er.NeedsetError ) as e: asyncio.run( draft.draft_cells( bad, 1 ) )
    assert e.value.code == er.QUOTA_UNFILLABLE


def test_one_text_and_slot_with_two_prompts_are_two_questions( tmp_path ):
    book, ask = ledger( tmp_path ), Asker( [ "first answer", "second answer" ] )
    one = draft.ask_ledgered( ask, book, "v", "m", "sys", "prompt one", "same text", "0.0" )
    two = draft.ask_ledgered( ask, book, "v", "m", "sys", "prompt two", "same text", "0.0" )
    assert ( one, two ) == ( "first answer", "second answer" ) and len( ask.prompts ) == 2
    assert draft.ask_ledgered( ask, book, "v", "m", "sys", "prompt one", "same text", "0.0" ) == "first answer" and len( ask.prompts ) == 2
    fenced = draft.ask_ledgered( ask, book, "v", "m", "sys", "prompt with a random suffix abc", "same text", "0.0", key_new="prompt one" )
    assert fenced == "first answer" and len( ask.prompts ) == 2, "key_new stands in for a prompt that carries a random suffix"
