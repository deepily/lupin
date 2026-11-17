"""
CoSA Agents Package

This package contains modernized agent implementations providing:
- Better modularity and separation of concerns
- Improved LLM client abstractions
- More consistent error handling
- Support for multiple LLM providers

Previously organized under v010/, now consolidated in the main agents directory.
"""

# Imports are absent here, to prevent a circular dependency with the memory modules.
# Import each agent, client and utility directly from its own module, for example from cosa.agents.agent_base.
#
# The circular dependency chain was:
# gister.py → agents.llm_client_factory → agents.__init__ → agent_base →
# solution_snapshot → embedding_manager → gist_normalizer → gister.py
#
# No __all__ list is defined here, to avoid any import-time dependencies.