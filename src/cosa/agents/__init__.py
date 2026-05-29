"""
CoSA Agents Package

This package contains modernized agent implementations providing:
- Better modularity and separation of concerns
- Improved LLM client abstractions
- More consistent error handling
- Support for multiple LLM providers

Previously organized under v010/, now consolidated in the main agents directory.
"""

# NOTE: Imports removed to prevent circular dependency with memory modules
# Direct imports should be used instead, e.g.:
#   from cosa.agents.agent_base import AgentBase
#   from cosa.agents.math_agent import MathAgent
#
# The circular dependency chain was:
# gister.py → agents.llm_client_factory → agents.__init__ → agent_base →
# solution_snapshot → embedding_manager → gist_normalizer → gister.py

# Agent implementations - use direct imports instead:
# from .agent_base import AgentBase
# from .calendaring_agent import CalendaringAgent
# from .date_and_time_agent import DateAndTimeAgent
# from .math_agent import MathAgent
# from .receptionist_agent import ReceptionistAgent
# from .todo_list_agent import TodoListAgent
# from .weather_agent import WeatherAgent
# from .bug_injector import BugInjector
# from .iterative_debugging_agent import IterativeDebuggingAgent

# Dialog utilities - use direct imports instead:
# from .confirmation_dialog import ConfirmationDialogue

# LLM client infrastructure - use direct imports instead:
# from .llm_client import LlmClient
# from .llm_client_factory import LlmClientFactory
# from .token_counter import TokenCounter
# from .llm_completion import LlmCompletion
# from .chat_client import ChatClient
# from .completion_client import CompletionClient

# Base abstractions - use direct imports instead:
# from .base_llm_client import BaseLlmClient
# from .llm_data_types import (MessageRole, LlmMessage, LlmRequest, LlmResponse, LlmStreamChunk)
# from .llm_exceptions import (LlmError, LlmConfigError, LlmAPIError, LlmTimeoutError, etc.)
# from .model_registry import (LlmProvider, ModelConfig, ModelRegistry)

# Utilities - use direct imports instead:
# from .prompt_formatter import PromptFormatter
# from .raw_output_formatter import RawOutputFormatter
# from .runnable_code import RunnableCode
# from .two_word_id_generator import TwoWordIdGenerator

# Note: __all__ list removed to prevent any import-time dependencies