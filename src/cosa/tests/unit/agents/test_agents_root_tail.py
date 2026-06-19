"""
Coverage-completion unit tests for the agents/root TAIL (CoSA 100% campaign):
  - DateAndTimeAgent  (date_and_time_agent.py)
  - MathAgent         (math_agent.py)
  - WeatherAgent      (weather_agent.py)
  - TokenCounter      (token_counter.py)
  - HeartbeatPokerJob._notify default-seam arc (heartbeat_poker_job.py:282)

The three agents are thin AgentBase subclasses; following the calculator package's
pattern (Tiffany 💍), AgentBase.__init__ is stubbed via `_seed_init` so construction
is hermetic (no config/template/LLM/network). Collaborators (LupinSearch, tiktoken,
config_mgr, AgentBase.run_formatter) are mocked. These close the exact missing lines
the de-poisoned legacy test_*.py files (shallow, 19-50%) leave open; the legacy files
are flagged for the later harvest→delete pass.

Authored by Rachel 🕊️ for the CoSA 100% coverage campaign (agents/root tail lane).
"""

import sys
import types
from unittest.mock import Mock, patch

import pytest

from cosa.agents.agent_base import AgentBase
from cosa.agents.date_and_time_agent import DateAndTimeAgent
from cosa.agents.math_agent import MathAgent
from cosa.agents.weather_agent import WeatherAgent
from cosa.agents.token_counter import TokenCounter
from cosa.agents.heartbeat_poker_job import HeartbeatPokerJob


def _seed_init( self, *args, **kwargs ):
    """AgentBase.__init__ stub seeding only what the tail agents read in __init__."""
    self.prompt_template     = "PROMPT[{question}]"
    self.question            = kwargs.get( "question", "" )
    self.last_question_asked = kwargs.get( "last_question_asked" ) or kwargs.get( "question", "" )
    self.debug               = kwargs.get( "debug", False )
    self.verbose             = kwargs.get( "verbose", False )


# ===========================================================================
# DateAndTimeAgent
# ===========================================================================

def test_date_and_time_init_builds_prompt_and_tags():
    """__init__ formats the prompt from self.question and sets the XML response tags."""
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = DateAndTimeAgent( question="what time is it" )
    assert agent.prompt == "PROMPT[what time is it]"
    assert agent.xml_response_tag_names == [ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ]


def test_date_and_time_restore_not_implemented():
    """restore_from_serialized_state is an explicit NotImplementedError seam."""
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = DateAndTimeAgent( question="q" )
    with pytest.raises( NotImplementedError ):
        agent.restore_from_serialized_state( "/tmp/x.json" )


# ===========================================================================
# MathAgent
# ===========================================================================

def test_math_init_uses_last_question_asked():
    """MathAgent formats the prompt from last_question_asked (voice specificity)."""
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = MathAgent( question="q", last_question_asked="what is 2 plus 2", debug=True, verbose=True )
    assert agent.prompt == "PROMPT[what is 2 plus 2]"
    assert "code" in agent.xml_response_tag_names


def test_math_restore_not_implemented():
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = MathAgent( question="q" )
    with pytest.raises( NotImplementedError ):
        agent.restore_from_serialized_state( "/tmp/x.json" )


def test_math_apply_formatting_terse_returns_raw():
    """terse_output=True → raw output returned verbatim (debug+verbose print arc)."""
    cfg = Mock()
    cfg.get.return_value = True
    assert MathAgent.apply_formatting( "42", cfg, debug=True, verbose=True ) == "42"


def test_math_apply_formatting_verbose_returns_none():
    """terse_output=False → None signals 'use the default LLM formatter'."""
    cfg = Mock()
    cfg.get.return_value = False
    assert MathAgent.apply_formatting( "42", cfg, debug=True, verbose=True ) is None


def test_math_run_formatter_terse_uses_raw_output():
    """run_formatter terse path sets answer_conversational to the raw output."""
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = MathAgent( question="q" )
    agent.code_response_dict     = { "output": "144" }
    agent.config_mgr             = Mock()
    agent.config_mgr.get.return_value = True          # terse
    agent.answer_conversational  = None
    result = agent.run_formatter()
    assert result == "144"
    assert agent.answer_conversational == "144"


def test_math_run_formatter_verbose_delegates_to_super():
    """run_formatter verbose path delegates to AgentBase.run_formatter."""
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = MathAgent( question="q" )
    agent.code_response_dict     = { "output": "144" }
    agent.config_mgr             = Mock()
    agent.config_mgr.get.return_value = False         # verbose → super()
    def _super_formatter( self_inner ):
        self_inner.answer_conversational = "one hundred forty-four"
    with patch.object( AgentBase, "run_formatter", _super_formatter ):
        result = agent.run_formatter()
    assert result == "one hundred forty-four"


# ===========================================================================
# WeatherAgent
# ===========================================================================

def test_weather_init_prepends_date_time():
    """prepend_date_and_time=True reformulates the query with a date/time prefix."""
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = WeatherAgent( last_question_asked="weather in DC", prepend_date_and_time=True )
    assert agent.reformulated_last_question_asked.startswith( "It's " )
    assert agent.reformulated_last_question_asked.endswith( "weather in DC" )
    assert agent.prompt is None
    assert agent.xml_response_tag_names == []


def test_weather_init_no_prepend_uses_raw_question():
    """prepend_date_and_time=False uses the raw last_question_asked."""
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = WeatherAgent( last_question_asked="weather in DC", prepend_date_and_time=False )
    assert agent.reformulated_last_question_asked == "weather in DC"


def test_weather_restore_not_implemented():
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = WeatherAgent( last_question_asked="q", prepend_date_and_time=False )
    with pytest.raises( NotImplementedError ):
        agent.restore_from_serialized_state( "/tmp/x.json" )


def test_weather_run_prompt_not_implemented():
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = WeatherAgent( last_question_asked="q", prepend_date_and_time=False )
    with pytest.raises( NotImplementedError ):
        agent.run_prompt()


def test_weather_is_code_runnable_and_prompt_executable():
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = WeatherAgent( last_question_asked="q", prepend_date_and_time=False )
    assert agent.is_code_runnable() is True
    assert agent.is_prompt_executable() is False


def test_weather_run_code_success_collapses_newlines():
    """run_code success path collapses newlines and stores output + answer."""
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = WeatherAgent( last_question_asked="weather", prepend_date_and_time=False )
    fake_search = Mock()
    fake_search.get_results.return_value = "line1\n\nline2\nline3"
    with patch( "cosa.agents.weather_agent.LupinSearch", return_value=fake_search ):
        out = agent.run_code()
    assert out[ "return_code" ] == 0
    assert out[ "output" ] == "line1 line2 line3"
    assert agent.answer == "line1\n\nline2\nline3"
    fake_search.search_and_summarize_the_web.assert_called_once()


def test_weather_run_code_exception_sets_error():
    """run_code catches collaborator failure and records it in the response dict."""
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = WeatherAgent( last_question_asked="weather", prepend_date_and_time=False )
    boom = RuntimeError( "search-down" )
    with patch( "cosa.agents.weather_agent.LupinSearch", side_effect=boom ):
        out = agent.run_code()
    assert out[ "return_code" ] == -1
    assert out[ "output" ] is boom
    assert agent.error is boom


def test_weather_do_all_runs_code_then_formatter():
    """do_all chains run_code → run_formatter and returns answer_conversational."""
    with patch.object( AgentBase, "__init__", _seed_init ):
        agent = WeatherAgent( last_question_asked="weather", prepend_date_and_time=False )
    agent.answer_conversational = "It is sunny."
    with patch.object( agent, "run_code" ) as rc, patch.object( agent, "run_formatter" ) as rf:
        result = agent.do_all()
    rc.assert_called_once()
    rf.assert_called_once()
    assert result == "It is sunny."


# ===========================================================================
# TokenCounter
# ===========================================================================

def test_token_counter_init_default_map_and_real_tiktoken():
    """No map → empty dict; tiktoken imports successfully in this env."""
    tc = TokenCounter()
    assert tc.model_tokenizer_map == {}
    assert tc.tiktoken is not None


def test_token_counter_init_stores_supplied_map():
    tc = TokenCounter( model_tokenizer_map={ "m": "cl100k_base" } )
    assert tc.model_tokenizer_map == { "m": "cl100k_base" }


def test_token_counter_init_tiktoken_missing( monkeypatch, capsys ):
    """tiktoken ImportError → self.tiktoken is None + warning printed."""
    monkeypatch.setitem( sys.modules, "tiktoken", None )   # `import tiktoken` raises ImportError
    tc = TokenCounter()
    assert tc.tiktoken is None
    assert "tiktoken not installed" in capsys.readouterr().out


def test_count_tokens_no_tiktoken_uses_char_estimate():
    tc = TokenCounter()
    tc.tiktoken = None
    assert tc.count_tokens( "gpt-4", "abcdefgh" ) == 2     # 8 chars // 4


def test_count_tokens_encoding_for_model_success():
    """Direct encoding_for_model path counts real tokens via the encoder."""
    tc = TokenCounter( model_tokenizer_map={ "alias": "gpt-4" } )
    enc = Mock()
    enc.encode.return_value = [ 1, 2, 3 ]
    fake_tk = Mock()
    fake_tk.encoding_for_model.return_value = enc
    tc.tiktoken = fake_tk
    assert tc.count_tokens( "alias", "hello world" ) == 3
    fake_tk.encoding_for_model.assert_called_once_with( "gpt-4" )   # mapped name used


def test_count_tokens_keyerror_falls_back_to_cl100k():
    """encoding_for_model KeyError → get_encoding('cl100k_base') fallback."""
    enc = Mock()
    enc.encode.return_value = [ 1, 2 ]
    fake_tk = Mock()
    fake_tk.encoding_for_model.side_effect = KeyError( "unknown" )
    fake_tk.get_encoding.return_value = enc
    tc = TokenCounter()
    tc.tiktoken = fake_tk
    assert tc.count_tokens( "exotic-model", "hi there" ) == 2
    fake_tk.get_encoding.assert_called_once_with( "cl100k_base" )


def test_count_tokens_unexpected_exception_falls_back_to_estimate( capsys ):
    """Any other failure → char-based estimate (the broad except arc)."""
    fake_tk = Mock()
    fake_tk.encoding_for_model.side_effect = RuntimeError( "boom" )
    tc = TokenCounter()
    tc.tiktoken = fake_tk
    assert tc.count_tokens( "m", "abcdefghijkl" ) == 3    # 12 // 4
    assert "Error counting tokens" in capsys.readouterr().out


# ===========================================================================
# HeartbeatPokerJob._notify default-seam (line 282)
# ===========================================================================

def test_heartbeat_notify_default_seam_uses_notify_progress():
    """When no _notify_fn is injected, _notify routes through notify_progress."""
    fake = types.SimpleNamespace( _notify_fn=None, notify_progress=Mock() )
    HeartbeatPokerJob._notify( fake, "escalating", priority="urgent" )
    fake.notify_progress.assert_called_once_with( "escalating", priority="urgent" )


def test_heartbeat_notify_injected_fn_seam():
    """When a _notify_fn IS injected, _notify routes through it (sibling arc)."""
    captured = []
    fake = types.SimpleNamespace( _notify_fn=lambda m, p: captured.append( ( m, p ) ),
                                  notify_progress=Mock() )
    HeartbeatPokerJob._notify( fake, "hello", priority="low" )
    assert captured == [ ( "hello", "low" ) ]
    fake.notify_progress.assert_not_called()
