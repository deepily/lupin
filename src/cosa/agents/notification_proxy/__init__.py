"""
Notification Proxy Agent — auto-responds to expediter notifications.

Connects via WebSocket, listens for response-required notifications,
and answers them using a hybrid strategy: rules for known expediter
patterns, LLM fallback for unknowns.

Usage:
    python -m cosa.agents.notification_proxy
    python -m cosa.agents.notification_proxy --profile deep_research --debug
"""
