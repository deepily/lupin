"""
Tool wrappers for COSA Deep Research Agent.

Phase 2 will add:
- web_search.py: Claude WebSearch wrapper
  - Async wrapper for Claude's web_search_20250305 tool
  - Handles rate limiting and retries
  - Formats search results for subagent consumption

- web_fetch.py: Claude WebFetch wrapper
  - Async wrapper for Claude's WebFetch tool
  - Extracts relevant content from URLs
  - Handles redirects and errors gracefully
  - Converts HTML to structured text
"""

__all__ = []
