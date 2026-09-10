"""
THE MULTIPLEXER'S QUESTIONS FIXTURE IS WHAT THE ASKING TOOLS BUILD — P0 5ebd2aff step 2 (row 4311c503).

Every multiplexer Action Required test reads `response_options` from
src/tests/unit/multiplexer/fixtures/action_required_questions_payload.json. A hand-typed option list is
how that client came to believe `response_options` was a string list, so this test rebuilds each payload
with the server's own builders and fails if the file has drifted from them.

It also pins each case's `answers` to the shape legacy sends (notifications.js getCurrentQuestionAnswer:
`question.multi_select ? answers : answers[ 0 ]`, saved by saveCurrentQuestionAnswer under the header),
and `wire_value` to that answer as JavaScript's JSON.stringify writes it.
"""

import json

import cosa.utils.util as cu
from cosa.utils.notification_utils import convert_open_ended_batch_for_api, convert_questions_for_api

FIXTURE_PATH = cu.get_project_root() + "/src/tests/unit/multiplexer/fixtures/action_required_questions_payload.json"


def _fixture():
    """
    Load the fixture the multiplexer tests read.

    Requires:
        - FIXTURE_PATH exists and holds JSON

    Ensures:
        - returns the parsed fixture dict
    """
    with open( FIXTURE_PATH, encoding="utf-8" ) as f:
        return json.load( f )


def test_the_multiple_choice_payload_is_what_convert_questions_for_api_builds():
    case = _fixture()[ "multiple_choice" ]
    assert case[ "response_options" ] == convert_questions_for_api( case[ "questions_in" ] )


def test_the_batch_payload_is_what_convert_open_ended_batch_for_api_builds():
    case = _fixture()[ "open_ended_batch" ]
    assert case[ "response_options" ] == convert_open_ended_batch_for_api( case[ "questions_in" ] )


def test_each_wire_value_is_its_answers_as_json_stringify_writes_them():
    for name, case in _fixture().items():
        if name.startswith( "_" ): continue
        assert case[ "wire_value" ] == json.dumps( case[ "answers" ], separators=( ",", ":" ), ensure_ascii=False ), name


def test_a_multiple_choice_answer_keys_every_question_by_header_with_a_list_only_for_multi_select():
    case    = _fixture()[ "multiple_choice" ]
    answers = case[ "answers" ][ "answers" ]
    questions = case[ "response_options" ][ "questions" ]
    assert set( answers ) == { q[ "header" ] for q in questions }
    assert any( q[ "multi_select" ] for q in questions ) and not all( q[ "multi_select" ] for q in questions ), \
        "the fixture must hold both a single-select and a multi-select question"
    for q in questions:
        value  = answers[ q[ "header" ] ]
        labels = { opt[ "label" ] for opt in q[ "options" ] }
        if q[ "multi_select" ]:
            assert isinstance( value, list ) and value and set( value ) <= labels
        else:
            assert isinstance( value, str ) and value in labels


def test_a_batch_answer_keys_every_question_by_header_with_a_string():
    case    = _fixture()[ "open_ended_batch" ]
    answers = case[ "answers" ][ "answers" ]
    assert set( answers ) == { q[ "header" ] for q in case[ "response_options" ][ "questions" ] }
    assert all( isinstance( value, str ) and value for value in answers.values() )
