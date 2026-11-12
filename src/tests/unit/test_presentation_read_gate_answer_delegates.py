"""
The presentation gate reader leaves the rule to the shared reader and keeps its own error.
"""
import logging

import pytest

from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent, VoiceGateNotAnsweredError
from cosa.agents.utils.voice_io import VoiceGateNoDefaultError

READ = PresentationOrchestratorAgent._read_gate_answer


def test_an_answer_the_gate_received_comes_back_untouched():
    assert READ( { "answers": { "Narrative Arc": "Revise" } }, "Narrative Arc", "Gate 1" ) == "Revise"


def test_an_empty_answer_is_still_an_answer():
    assert READ( { "answers": { "Narrative Arc": "" } }, "Narrative Arc", "Gate 1" ) == ""


def test_a_missing_header_raises_the_presentation_error_naming_the_gate_header_and_payload_keys():
    with pytest.raises( VoiceGateNotAnsweredError ) as exc:
        READ( { "answers": {}, "default_used": False }, "Slide Outline", "Gate 2" )
    assert "Gate 2" in str( exc.value ) and "'Slide Outline'" in str( exc.value ) and "['answers', 'default_used']" in str( exc.value )


def test_the_refusal_keeps_the_shared_readers_error_as_its_cause():
    with pytest.raises( VoiceGateNotAnsweredError ) as exc:
        READ( { "answers": {} }, "Slide Outline", "Gate 2" )
    assert isinstance( exc.value.__cause__, VoiceGateNoDefaultError )


def test_a_payload_that_is_not_a_dict_names_its_type_in_the_refusal():
    with pytest.raises( VoiceGateNotAnsweredError, match="list" ): READ( [ "x" ], "Slide Outline", "Gate 2" )


def test_an_answer_from_a_declared_default_is_logged_once_by_the_shared_reader( caplog ):
    result = { "answers": { "Visual Review": "Continue" }, "default_used": True, "default_source": "answer_timeout" }
    with caplog.at_level( logging.WARNING ):
        assert READ( result, "Visual Review", "Gate 4" ) == "Continue"
    warnings = [ r for r in caplog.records if "DECLARED DEFAULT" in r.getMessage() ]
    assert len( warnings ) == 1 and warnings[ 0 ].name == "cosa.agents.utils.voice_io"
