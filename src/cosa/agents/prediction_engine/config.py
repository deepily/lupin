"""
Default constants for the Prediction Engine.

Centralized configuration defaults that can be overridden via lupin-app.ini.
These values serve as fallbacks when config keys are missing.
"""

# Feature toggle
DEFAULT_ENABLED                = True
DEFAULT_DEBUG                  = False

# CBR (Case-Based Reasoning) parameters
DEFAULT_CBR_TOP_K              = 5
DEFAULT_CBR_SIMILARITY_THRESHOLD = 0.75
DEFAULT_CONFIDENCE_THRESHOLD   = 0.60

# Retrieval metric for the engine's neighbour search: "dot" (today's scale) or "cosine".
# Phase 4 flips the INI key to cosine in the commit that retunes the floors and top k.
DEFAULT_RETRIEVAL_METRIC       = "dot"
VALID_RETRIEVAL_METRICS        = ( "dot", "cosine" )

# Whether the display gate reads calibrated confidence (from the committed calibration file)
# instead of raw confidence. False in the foundation; a measured change turns it on.
DEFAULT_CALIBRATION_ENABLED    = False

# Whether a missing embedding, a failed forecast write and a swallowed store error write a named
# abstention reason on the forecast row and a [PREDICTION-FAILURE] log line (phase 11, failure half).
DEFAULT_FAILURE_VISIBILITY_ENABLED = False

# Yes/no prior-weighted vote. "no" is predicted only when the
# no tally beats the yes tally by at least this margin (in vote-weight units; an
# ordinary neighbour counts 1.0). 1.35 = ln( 527 / 137 ), the log-odds of the 79.4%
# yes prior (527 yes of 664 answered rows). With top-5 unit votes it
# means a no-win needs a lead of 2 or more.
DEFAULT_YES_NO_NO_MARGIN       = 1.35

# Prediction-hint thumbs up/down voting → human-confirmed training signal.
# A thumbs-up case (ratification_state="approved") contributes APPROVED_WEIGHT to its
# decision_value in the CBR majority tally; a thumbs-down case ("rejected") casts a
# NEGATIVE vote of magnitude REJECTED_WEIGHT against its value (steer-away — Rick's
# decision 2026-06-03). Ordinary (pending/not_required) cases contribute 1.0.
DEFAULT_HINT_VOTING_ENABLED                   = True
DEFAULT_HINT_VOTE_MIN_CONFIDENCE_THRESHOLD    = 0.50
DEFAULT_HINT_VOTE_APPROVED_WEIGHT             = 2.0
DEFAULT_HINT_VOTE_REJECTED_WEIGHT             = 2.0

# HTTP embedding fallback (when local GPU is unavailable)
DEFAULT_EMBEDDING_FALLBACK_PORT = 7999

# LanceDB vector store
DEFAULT_LANCEDB_TABLE          = "prediction_decisions"

# LLM synthesis (open-ended prediction)
DEFAULT_OPEN_ENDED_CBR_TOP_K        = 5
DEFAULT_OPEN_ENDED_CBR_THRESHOLD    = 0.85
DEFAULT_OPEN_ENDED_LLM_SPEC_KEY    = "kaitchup/phi_4_14b"

# Prediction strategies (enum-like constants)
STRATEGY_CBR_MAJORITY          = "cbr_majority_vote"
STRATEGY_CBR_RETRIEVAL         = "cbr_retrieval"
STRATEGY_LLM_SYNTHESIS         = "llm_synthesis"
STRATEGY_OPTION_SCORING        = "option_embedding_scoring"
STRATEGY_COLD_START            = "cold_start"
STRATEGY_ERROR                 = "error"
STRATEGY_TEST_OVERRIDE         = "test_override"

# Forecast ledger: who made the forecast row, and which build of the predictor
FORECAST_SOURCE_FOUNDATION     = "foundation_sync"
FORECAST_SOURCE_TEST_OVERRIDE  = "test_override"
PREDICTOR_VERSION              = "foundation-sync-1"

# The state a forecast card shows, and the display decision stored on the forecast row (they are one value)
HINT_STATE_READY                 = "ready"
HINT_STATE_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
HINT_STATE_BELOW_THRESHOLD       = "below_threshold"
HINT_STATE_UNAVAILABLE           = "unavailable"

# Accuracy comparison thresholds
# Default for INI key "prediction engine open ended match threshold" (Rick's ruling 6 Nov 2026, row 35a79890;
# fitted on 133 labelled pairs: precision 0.79, recall 0.65 at 0.75, against recall 0.29 at 0.85)
OPEN_ENDED_SIMILARITY_THRESHOLD = 0.75
MULTI_SELECT_JACCARD_THRESHOLD  = 0.50

# Response type identifiers (matching cosa-voice MCP server)
RESPONSE_TYPE_YES_NO           = "yes_no"
RESPONSE_TYPE_MULTIPLE_CHOICE  = "multiple_choice"
RESPONSE_TYPE_OPEN_ENDED       = "open_ended"
RESPONSE_TYPE_OPEN_ENDED_BATCH = "open_ended_batch"
