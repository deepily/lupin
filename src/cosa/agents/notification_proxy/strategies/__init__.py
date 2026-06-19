"""
Response strategies for the Notification Proxy Agent.

Strategies:
    - LlmScriptMatcherStrategy: Phi-4 fuzzy matching against Q&A scripts (primary)
    - ExpediterRuleStrategy: Rule-based answers for known expediter patterns (fallback)
    - LLMFallbackStrategy: Anthropic SDK fallback for unknown questions (cloud)
"""
