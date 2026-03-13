"""
Smoke test wrapper for CJ Flow background consumer thread.

Delegates to the inline quick_smoke_test() at queue_consumer.py:109 which
tests thread startup and graceful shutdown — all fully mocked with no
server or LLM dependencies.

Created: 2026-02-17 (Session 221 — Smoke Test Coverage Audit)
Converted to Pattern A: 2026-02-17 (Session 222 — Consistency Cleanup)
"""

from cosa.rest.queue_consumer import quick_smoke_test


def test_queue_consumer():
    """Pytest entry point — delegates to source module QST."""
    quick_smoke_test()


if __name__ == "__main__":
    quick_smoke_test()
