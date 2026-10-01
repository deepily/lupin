"""
The reader-test rig: a reader answers from a text, a blind grader scores the answer, and the
means over the runs decide whether the new text is at least as good as the old.

The fake reader answers with the sentence of the text that contains the question's topic word,
or NOT STATED, and the fake grader scores 1 when the key's words occur in the answer. So a text
with sentences removed really does score lower, and the control below shows it.
"""

import asyncio
import json
import re

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from cosa.repo.doc_lint import harness_runner as hn
from cosa.repo.doc_lint import reader_rig as rt

TEXT = ( "Returns None when the row is parked. Raises ValueError if the id is blank. "
         "The chase window is ten minutes." )
QUESTIONS = [
    { "id": "q1", "question": "What does it return for a parked row? (topic: Returns)", "key": "None" },
    { "id": "q2", "question": "What happens when the id is blank? (topic: Raises)", "key": "ValueError" },
    { "id": "q3", "question": "How long is the chase window? (topic: chase)", "key": "ten minutes" },
]
CONFIG = rt.ReaderConfig( "reader-m", "grader-m" )


def tagged( prompt, tag ):
    match = re.search( rf"<{tag}>\n(.*?)\n</{tag}>", prompt, re.DOTALL )
    return match.group( 1 ) if match else ""


class FakeModels:
    def __init__( self, reader_reply=None, grader_reply=None ):
        self.calls        = []
        self.reader_reply = reader_reply
        self.grader_reply = grader_reply

    async def __call__( self, prompt, options ):
        self.calls.append( ( options.model, options.system_prompt, prompt ) )
        if options.system_prompt == rt.READER_SYSTEM:
            topic     = re.search( r"topic: (\w+)", tagged( prompt, "question" ) ).group( 1 )
            sentences = [ s for s in re.split( r"(?<=\.)\s+", tagged( prompt, "text" ) ) if topic.lower() in s.lower() ]
            text      = self.reader_reply or json.dumps( { "answer": sentences[ 0 ] if sentences else "NOT STATED" } )
        else:
            hit  = tagged( prompt, "key" ).lower() in tagged( prompt, "answer" ).lower()
            text = self.grader_reply or json.dumps( { "score": 1 if hit else 0 } )
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )


def go( old, new, questions=QUESTIONS, config=CONFIG, ledger=None, models=None ):
    models = models or FakeModels()
    return asyncio.run( rt.run_reader_test( old, new, questions, config, ledger=ledger, query_fn=models ) ), models


def test_identical_texts_score_alike_and_pass():
    result, _ = go( TEXT, TEXT )
    assert result[ "old_scores" ] == result[ "new_scores" ] == [ 1.0, 1.0, 1.0 ]
    assert result[ "passes" ] is True


def test_a_gutted_text_scores_lower_and_fails():
    gutted = "Returns None when the row is parked."
    result, _ = go( TEXT, gutted )
    assert result[ "old_mean" ] == 1.0 and result[ "new_mean" ] == pytest.approx( 1 / 3 )
    assert result[ "passes" ] is False


def test_a_new_text_that_scores_higher_passes():
    result, _ = go( "Returns None when the row is parked.", TEXT )
    assert result[ "new_mean" ] > result[ "old_mean" ] and result[ "passes" ] is True


def test_each_text_is_read_n_times_per_question_and_graded_blind():
    result, models = go( TEXT, TEXT, config=rt.ReaderConfig( "reader-m", "grader-m", runs=2 ) )
    reads  = [ c for c in models.calls if c[ 1 ] == rt.READER_SYSTEM ]
    grades = [ c for c in models.calls if c[ 1 ] == rt.GRADER_SYSTEM ]
    assert len( reads ) == 2 * 2 * 3 and len( grades ) == 2 * 2 * 3
    assert len( result[ "old_scores" ] ) == len( result[ "new_scores" ] ) == 2
    for _, _, prompt in grades:
        assert "<text>" not in prompt and TEXT not in prompt
        assert "old" not in prompt.lower().replace( "hold", "" ) and "new" not in prompt.lower()


def test_models_are_the_configured_ones():
    _, models = go( TEXT, TEXT )
    assert {ci[ 0 ] for ci in models.calls if ci[ 1 ] == rt.READER_SYSTEM} == { "reader-m" }
    assert {ci[ 0 ] for ci in models.calls if ci[ 1 ] == rt.GRADER_SYSTEM} == { "grader-m" }


def test_a_ledger_makes_a_second_run_free(tmp_path):
    path = str( tmp_path / "l" )
    first, m1 = go( TEXT, TEXT, ledger=hn.Ledger( path ) )
    again, m2 = go( TEXT, TEXT, ledger=hn.Ledger( path ) )
    assert again == first and m1.calls and m2.calls == []


def test_empty_questions_and_missing_model_ids_are_refused():
    with pytest.raises( ValueError, match="questions is empty" ):
        go( TEXT, TEXT, questions=[] )
    with pytest.raises( ValueError, match="no default" ):
        go( TEXT, TEXT, config=rt.ReaderConfig( "", "grader-m" ) )
    with pytest.raises( ValueError, match="no default" ):
        go( TEXT, TEXT, config=rt.ReaderConfig( "reader-m", "" ) )


@pytest.mark.parametrize( "raw", [ "sure", "[]", '{"answer": ""}', '{"answer": 3}', '{"answer": "a", "x": 1}' ] )
def test_a_reader_reply_off_contract_is_refused( raw ):
    with pytest.raises( rt.ReaderParseError ):
        go( TEXT, TEXT, models=FakeModels( reader_reply=raw ) )


@pytest.mark.parametrize( "raw", [ "sure", '{"score": 2}', '{"score": true}', '{"score": 1.0}', '{"score": "1"}', '{"grade": 1}' ] )
def test_a_grader_reply_off_contract_is_refused( raw ):
    with pytest.raises( rt.ReaderParseError ):
        go( TEXT, TEXT, models=FakeModels( grader_reply=raw ) )


def test_fenced_replies_are_accepted():
    assert rt.parse_answer( '```json\n{"answer": "x"}\n```' ) == "x"
    assert rt.parse_score( '```\n{"score": 0}\n```' ) == 0
