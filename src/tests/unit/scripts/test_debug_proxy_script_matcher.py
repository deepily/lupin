"""
Coverage ramp for `src/scripts/debug/debug_proxy_script_matcher.py` — 179 statements,
previously a flat 0.0% (assigned by Mr Radio 🦉 2026-08-30 for the 96% push).

🔴 WHAT THIS FILE IS, STATED PLAINLY. The script under test is a debug one-shot that nothing
imports. These tests were written to move a coverage number, not because the script earned
tests on merit. Every branch below is really executed and really asserted, but nobody should
read this suite as evidence the script is well-covered infrastructure.

🔴 IMPORTING THIS SCRIPT *IS* RUNNING IT. Apart from two print helpers it has no functions and
no `__main__` guard: the five diagnostic steps sit at module level and construct a real
`LlmScriptMatcherStrategy`, which reaches for a Phi-4 vLLM server. So the stand-ins go in
BEFORE the import, on the SOURCE modules — `LlmScriptMatcherStrategy`, `resolve_script_path`
and `ScriptMatcherResponse` are all bound by `from … import …`, which copies the reference at
import time, and patching them on the script afterwards would be too late to matter.

The script's own Q&A file is not stubbed: `resolve_script_path` is pointed at a real JSON file
written into pytest's tmp_path, so the `open()` and `json.load()` under test run for real
against a fixture whose shape the test controls. Only the LLM is faked.

Each test re-imports from a clean `sys.modules` so the module body runs again under that
test's scripted world.
"""

import importlib
import json
import os
import sys

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts", "debug" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

MODULE_NAME  = "debug_proxy_script_matcher"
STRATEGY_MOD = "cosa.agents.notification_proxy.strategies.llm_script_matcher"
XML_MOD      = "cosa.agents.notification_proxy.xml_models"

# The sender the script's simulated notification carries. A strategy that accepts this string
# makes can_handle() succeed; anything else drives the mismatch diagnosis.
CRUD_SENDER = "crud.agent@lupin.deepily.ai"

RAISE = object()   # sentinel: "raise instead of returning"


class _FakeClient:
    """
    Stands in for the strategy's LLM client.

    The script monkey-patches `strategy._client.run` to instrument it, then restores the
    original, so `run` must be a settable attribute on a real object — not a bound method of
    a class that forbids assignment.
    """

    def __init__( self, raw="<response/>" ):
        self.raw   = raw
        self.calls = []
        self.run   = self._run

    def _run( self, prompt, **kwargs ):
        self.calls.append( prompt )
        return self.raw


class _FakeStrategy:
    """
    Stands in for LlmScriptMatcherStrategy.

    Requires:
        - answer is the value respond() returns, or RAISE to make it throw
        - calls_client controls whether respond() goes through _client.run, which decides
          whether the script captures a raw response at all
    """

    def __init__( self, available=True, accepted=( CRUD_SENDER, ), can_handle=True,
                  answer="yes", calls_client=True, raw="<response/>", entries=2 ):
        self.available        = available
        self.llm_spec_key     = "phi4-script-matcher"
        self.accepted_senders = list( accepted )
        self._entries         = [ { "n": i } for i in range( entries ) ]
        self._client          = _FakeClient( raw=raw )
        self._can_handle      = can_handle
        self._answer          = answer
        self._calls_client    = calls_client

    def can_handle( self, notification ):
        return self._can_handle

    def respond( self, notification ):
        if self._calls_client: self._client.run( "PROMPT-BODY" )
        if self._answer is RAISE: raise RuntimeError( "llm exploded" )
        return self._answer


class _FakeParsed:
    """Stands in for a parsed ScriptMatcherResponse."""

    def __init__( self, matched_entry="delete_confirm", answer="yes", confidence="0.90" ):
        self.matched_entry = matched_entry
        self.answer        = answer
        self.confidence    = confidence
        self.reasoning     = "because the pattern matched"

    def get_confidence_float( self ):
        return float( self.confidence )

    def is_match( self ):
        return self.matched_entry != "none"


def _script_file( tmp_path, entries=2 ):
    """
    Write a crud.json-shaped Q&A file and return its path.

    Ensures:
        - the file is real, so the script's own open()/json.load() run unstubbed
    """
    payload = {
        "profile_name" : "crud",
        "sender_ids"   : [ CRUD_SENDER ],
        "entries"      : [
            {
                "question_pattern" : f"pattern {i}",
                "answer"           : "yes",
                "arg_name"         : f"arg{i}",
                "response_types"   : [ "yes_no" ],
            }
            for i in range( entries )
        ],
    }
    path = tmp_path / "crud.json"
    path.write_text( json.dumps( payload ) )
    return str( path )


def _fresh_import( monkeypatch, script_path, strategy=None, strategy_raises=False,
                   parsed=None, parse_raises=False ):
    """
    Import the script from scratch with the LLM surface stubbed.

    Requires:
        - script_path is what resolve_script_path() should return (need not exist)

    Ensures:
        - returns the imported module
        - no LLM client is constructed and no network call is made
    """
    def fake_resolve( name ):
        return script_path

    def fake_strategy_ctor( **kwargs ):
        if strategy_raises: raise RuntimeError( "strategy construction failed" )
        return strategy if strategy is not None else _FakeStrategy()

    class _FakeXml:
        @staticmethod
        def from_xml( raw ):
            if parse_raises: raise ValueError( "malformed xml" )
            return parsed if parsed is not None else _FakeParsed()

    monkeypatch.setattr( f"{STRATEGY_MOD}.resolve_script_path", fake_resolve )
    monkeypatch.setattr( f"{STRATEGY_MOD}.LlmScriptMatcherStrategy", fake_strategy_ctor )
    monkeypatch.setattr( f"{XML_MOD}.ScriptMatcherResponse", _FakeXml )

    sys.modules.pop( MODULE_NAME, None )
    module = importlib.import_module( MODULE_NAME )
    sys.modules.pop( MODULE_NAME, None )
    return module


def test_all_five_steps_pass_on_the_happy_path( monkeypatch, capsys, tmp_path ):
    """Script loads, strategy is available, sender matches, respond() answers yes."""
    _fresh_import( monkeypatch, _script_file( tmp_path ) )

    out = capsys.readouterr().out
    assert "All 5 steps passed" in out
    assert "[FAIL]" not in out


def test_script_load_failure_is_reported_and_fails_step_one( monkeypatch, capsys, tmp_path ):
    """A missing Q&A file drives the step-1 exception arm rather than crashing the script."""
    _fresh_import( monkeypatch, str( tmp_path / "does-not-exist.json" ) )

    out = capsys.readouterr().out
    assert "ERROR loading crud.json" in out
    assert "One or more steps failed" in out


def test_fewer_than_two_entries_fails_step_one( monkeypatch, capsys, tmp_path ):
    """
    The step-1 verdict is `len(entries) >= 2`, so a one-entry file loads cleanly and still
    fails — the arm a "file opens correctly" test would miss.
    """
    _fresh_import( monkeypatch, _script_file( tmp_path, entries=1 ) )

    out = capsys.readouterr().out
    assert "ERROR loading crud.json" not in out
    assert "[FAIL] crud.json loaded successfully" in out


def test_strategy_construction_failure_skips_the_later_steps( monkeypatch, capsys, tmp_path ):
    """
    When the strategy cannot be built, steps 4 and 5 take their `strategy is None` arms and
    say so instead of raising.
    """
    _fresh_import( monkeypatch, _script_file( tmp_path ), strategy_raises=True )

    out = capsys.readouterr().out
    assert "ERROR creating strategy" in out
    assert out.count( "SKIPPED: Strategy not created" ) == 2


def test_unavailable_llm_warns_and_skips_respond( monkeypatch, capsys, tmp_path ):
    """
    A constructed-but-unavailable strategy is the common real-world case (Phi-4 down): the
    script warns at step 2 and takes the `not available` arm at step 5.
    """
    strategy = _FakeStrategy( available=False, can_handle=False )
    _fresh_import( monkeypatch, _script_file( tmp_path ), strategy=strategy )

    out = capsys.readouterr().out
    assert "WARNING: LLM client is NOT available." in out
    assert "SKIPPED: LLM client not available" in out


def test_sender_mismatch_reports_root_cause( monkeypatch, capsys, tmp_path ):
    """
    can_handle() False with a sender the strategy does not accept — the diagnosis the script
    was written to produce.
    """
    strategy = _FakeStrategy( can_handle=False, accepted=( "someone.else@lupin.deepily.ai", ) )
    _fresh_import( monkeypatch, _script_file( tmp_path ), strategy=strategy )

    out = capsys.readouterr().out
    assert "ROOT CAUSE: Sender ID mismatch!" in out
    assert "sender accepted?   : False" in out


def test_can_handle_false_with_accepted_sender_skips_root_cause( monkeypatch, capsys, tmp_path ):
    """
    The other arm of the same branch: the sender IS accepted and can_handle() still says no,
    so the mismatch explanation must NOT be printed — it would be a wrong diagnosis.
    """
    strategy = _FakeStrategy( can_handle=False )
    _fresh_import( monkeypatch, _script_file( tmp_path ), strategy=strategy )

    out = capsys.readouterr().out
    assert "sender accepted?   : True" in out
    assert "ROOT CAUSE: Sender ID mismatch!" not in out


def test_respond_returning_none_prints_the_diagnosis_list( monkeypatch, capsys, tmp_path ):
    """respond() gave nothing back — the script enumerates the four possible causes."""
    strategy = _FakeStrategy( answer=None )
    _fresh_import( monkeypatch, _script_file( tmp_path ), strategy=strategy )

    out = capsys.readouterr().out
    assert "DIAGNOSIS: respond() returned None" in out
    assert "1. Phi-4 returned matched_entry='none'" in out


def test_respond_raising_is_caught_and_fails_step_five( monkeypatch, capsys, tmp_path ):
    """An exception inside respond() is a diagnostic result, not a crash."""
    strategy = _FakeStrategy( answer=RAISE )
    _fresh_import( monkeypatch, _script_file( tmp_path ), strategy=strategy )

    out = capsys.readouterr().out
    assert "EXCEPTION during respond(): llm exploded" in out
    assert "[FAIL] respond() completed" in out


def test_malformed_xml_is_reported_as_a_parse_error( monkeypatch, capsys, tmp_path ):
    """The raw response came back but would not parse — Phi-4 returned bad XML."""
    _fresh_import( monkeypatch, _script_file( tmp_path ), parse_raises=True )

    out = capsys.readouterr().out
    assert "XML PARSE ERROR: malformed xml" in out
    assert "This means Phi-4 returned malformed XML." in out


def test_no_raw_response_captured_skips_the_parsing_block( monkeypatch, capsys, tmp_path ):
    """
    respond() answered without going through the client, so there is nothing to parse — the
    script must say so rather than parse None.
    """
    strategy = _FakeStrategy( calls_client=False )
    _fresh_import( monkeypatch, _script_file( tmp_path ), strategy=strategy )

    out = capsys.readouterr().out
    assert "(No raw response captured" in out
    assert "XML PARSING DIAGNOSTIC" not in out


def test_a_non_yes_answer_is_reported_as_a_failed_check( monkeypatch, capsys, tmp_path ):
    """
    respond() answered, but not with "yes".

    The script scores those separately — it got AN answer (pass) that was the WRONG answer
    (fail) — so both lines must appear.
    """
    strategy = _FakeStrategy( answer="no" )
    _fresh_import( monkeypatch, _script_file( tmp_path ), strategy=strategy )

    out = capsys.readouterr().out
    assert "[PASS] respond() returned an answer" in out
    assert "[FAIL] Answer is 'no'" in out


def test_the_instrumented_client_captures_the_prompt_and_is_restored( monkeypatch, capsys, tmp_path ):
    """
    Reads what the script DOES to the client, not just what it prints.

    The script wraps `_client.run` to capture the prompt and must put the original back; a
    wrapper left installed would leak into any later use of that strategy.
    """
    strategy = _FakeStrategy( raw="<response><answer>yes</answer></response>" )
    before   = strategy._client.run

    _fresh_import( monkeypatch, _script_file( tmp_path ), strategy=strategy )

    assert strategy._client.run is before
    assert strategy._client.calls == [ "PROMPT-BODY" ]

    out = capsys.readouterr().out
    assert "--- FULL EXPANDED PROMPT ---" in out
    assert "<response><answer>yes</answer></response>" in out


def test_import_inserts_src_on_a_path_that_lacks_it( monkeypatch, capsys, tmp_path ):
    """
    Covers the bootstrap's `sys.path.insert` arm, which every other test skips because the
    conftest has already put `src` on the path.

    Removing that exact entry first makes the script take the other branch; it re-inserts the
    path itself before importing cosa, so nothing downstream is disturbed.
    """
    src_path = os.path.join( _ROOT, "src" )
    monkeypatch.setattr( sys, "path", [ p for p in sys.path if p != src_path ] )
    assert src_path not in sys.path

    _fresh_import( monkeypatch, _script_file( tmp_path ) )

    assert src_path in sys.path
    assert "All 5 steps passed" in capsys.readouterr().out


def test_parsed_fields_are_printed_from_the_response( monkeypatch, capsys, tmp_path ):
    """
    The XML diagnostic renders the parsed object's own fields.

    Values here are deliberately distinct from the defaults so the assertions cannot pass on a
    script that prints a hardcoded line.
    """
    parsed = _FakeParsed( matched_entry="none", answer="maybe", confidence="0.25" )
    _fresh_import( monkeypatch, _script_file( tmp_path ), parsed=parsed )

    out = capsys.readouterr().out
    assert "matched_entry : 'none'" in out
    assert "answer        : 'maybe'" in out
    assert "confidence    : '0.25' (0.25)" in out
    assert "is_match()    : False" in out
