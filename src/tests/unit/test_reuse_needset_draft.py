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
    return { "seed": seed, "keys": list( keys ), "write_lang": lang, "stripped": { "kind": "function", "text": text, "forbidden": [ "compute_total", "items", "limit" ] } }


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
    assert got == { "ok": True, "seed": SEED[ "id" ], "key": [ KEY[ "id" ] ], "need": GOOD, "tries": 1, "history": [], "reason": None }
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
