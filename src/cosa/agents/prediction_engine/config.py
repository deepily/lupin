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

# Accuracy comparison thresholds
OPEN_ENDED_SIMILARITY_THRESHOLD = 0.85
MULTI_SELECT_JACCARD_THRESHOLD  = 0.50

# Response type identifiers (matching cosa-voice MCP server)
RESPONSE_TYPE_YES_NO           = "yes_no"
RESPONSE_TYPE_MULTIPLE_CHOICE  = "multiple_choice"
RESPONSE_TYPE_OPEN_ENDED       = "open_ended"
RESPONSE_TYPE_OPEN_ENDED_BATCH = "open_ended_batch"
