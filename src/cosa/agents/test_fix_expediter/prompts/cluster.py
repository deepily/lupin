"""
Clustering prompt for TFE Phase 0.

**Step 6 scaffolding: stub only.** Full prompt implementation in step 7.

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/10-prompt-design.md#1-promptsclusterpy--failure-clustering
"""


CLUSTER_SYSTEM_PROMPT_STUB = """You are a test-failure triage analyst.
(STUB — full prompt in step 7)
"""


def build_cluster_prompt_stub( snapshot, heuristic_seeds, max_clusters: int ) -> str:
    """
    Build the user prompt for LLM clustering refinement.

    **STATUS**: Stub. Full implementation in step 7.
    """
    return f"(STUB) Refine these {len( heuristic_seeds )} clusters (max {max_clusters})"
