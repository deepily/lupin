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

TWO VERSIONS LIVE SIDE BY SIDE as of 2026-08-01 (row ca7a2cbf). v1 is the module
above and remains the default. v2 (judge_v2.py) replaces the Directness GRADE with an
EXTRACTION checked against the source text. Choose with `dm quality judge version`;
callers should go through get_dm_quality_judge() rather than naming a class, so the
switch lives in one place.
"""

DEFAULT_JUDGE_VERSION = 1


def get_dm_quality_judge( version=None, **kwargs ):
    """
    Build the DM Quality Judge the configuration asks for.

    Requires:
        - version is 1, 2, or None (None reads `dm quality judge version` from the INI)
        - kwargs are forwarded verbatim to the chosen judge's constructor, so the
          `qualitative_enabled` injection seam the discrimination probe depends on
          reaches either version unchanged

    Ensures:
        - returns a DmQualityJudge (v1) or DmQualityJudgeV2 (v2); both expose the same
          judge(body_text) contract and the same result shape, so no caller branches
        - an unreadable config, or any version value that is not 1 or 2, returns v1 —
          the version key is not a place to fail a DM send, and v1 is the known path
        - the import of each judge is LOCAL to its branch: v2 is not imported at all
          when v1 is selected, so a future v2 import error cannot take down the
          default path

    Args:
        version: 1, 2, or None to read the INI
        kwargs: forwarded to the judge constructor

    Returns:
        A judge instance
    """
    if version is None:
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            version    = config_mgr.get( "dm quality judge version", default=DEFAULT_JUDGE_VERSION, return_type="int" )
        except Exception as e:
            print( f"[dm_quality_judge] could not read the version key ({type( e ).__name__}) — defaulting to v{DEFAULT_JUDGE_VERSION}" )
            version = DEFAULT_JUDGE_VERSION

    if int( version ) == 2:
        from cosa.agents.dm_quality_judge.judge_v2 import DmQualityJudgeV2
        return DmQualityJudgeV2( **kwargs )

    if int( version ) != DEFAULT_JUDGE_VERSION:
        print( f"[dm_quality_judge] unknown version {version!r} — falling back to v{DEFAULT_JUDGE_VERSION}" )

    from cosa.agents.dm_quality_judge.judge import DmQualityJudge
    return DmQualityJudge( **kwargs )
