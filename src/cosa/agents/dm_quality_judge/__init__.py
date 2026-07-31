"""
DM Quality Judge — grades a peer-DM body for brevity/directness/tone.

Phase 2 of the DM Verbosity Reduction plan (Rick 2026-07-31 —
src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/). A HYBRID engine:

    - Length  : deterministic Python bucket (LLMs are bad at counting).
    - Directness + Tone : a fixed-rubric Mistral judge call.
    - Overall : Python combination (equal weight to the quantitative vs the
                qualitative CATEGORY), round-half-up, bucketed to 5 Likert levels.

Modeled directly on the house LlmAnswerVerifier/VerificationResponse pattern
(cosa/agents/notification_proxy/). LLM I/O is always text — the model emits a
grade LABEL ("good", "exemplary", ...), never a number; Python does all the
arithmetic. A judge-call failure returns a safe all-🤷/0 fallback (the DM still
sends).
"""
