"""
Clustering prompt stub for the first TFE step, which groups failures into clusters.

Stub only. The full prompt is not written yet.

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/10-prompt-design.md#1-promptsclusterpy--failure-clustering
"""


CLUSTER_SYSTEM_PROMPT_STUB = """You are a test-failure triage analyst.
(STUB — full prompt in step 7)
"""


def build_cluster_prompt_stub( snapshot, heuristic_seeds, max_clusters: int ) -> str:
    """
    Build the user prompt for LLM clustering refinement.

    Stub. The full implementation is not written yet.
    """
    return f"(STUB) Refine these {len( heuristic_seeds )} clusters (max {max_clusters})"
