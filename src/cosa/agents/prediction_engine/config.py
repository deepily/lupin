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

# The three-way stance challenger (yes, no, neither). It runs only in shadow, so this switch gates the
# engine method that forecasts with it; the live ask path never calls it.
DEFAULT_THREE_WAY_ENABLED      = False

# Half-life, in days, of the weight an earlier answer carries. 14 is the trust tracker's own figure.
DEFAULT_RECENCY_HALF_LIFE_DAYS = 14

# Whether a multiple-choice card is predicted and scored one field at a time (phase 7). False keeps the
# whole-card predictor and the whole-card scorer exactly as they were.
DEFAULT_PER_FIELD_MC_ENABLED   = False

# Whether the replay leaves a timed-out card, an answer the server filled from the card's own default, out of
# its scores and out of the visible cases its baselines count, and reports the count apart. False keeps every
# row counted exactly as before.
DEFAULT_TIMEOUT_DEFAULTS_EXCLUDED_ENABLED = False

# Whether the lookup engine forecasts neither for a yes/no ask when neither is the likeliest stance, through
# the one three-way vote, instead of abstaining. False keeps today's vote and its abstention.
DEFAULT_LOOKUP_NEITHER_FORECAST_ENABLED = False

# Whether a burst of retry copies among the retrieved cases counts once (phase 11b, candidate recall).
DEFAULT_CANDIDATE_RETRY_DEDUPE_ENABLED = False

# Whether one question template may take at most DEFAULT_CANDIDATE_TEMPLATE_CAP of the neighbour places.
DEFAULT_CANDIDATE_TEMPLATE_CAP_ENABLED = False
DEFAULT_CANDIDATE_TEMPLATE_CAP         = 3

# With either candidate switch on, how many times the neighbour limit is fetched, so that thinned places refill.
CANDIDATE_OVERFETCH_FACTOR             = 5

# Whether the case's category ranks the neighbours instead of filtering them, behind `prediction engine
# category as ranking`. The boost is added to a same-category case's similarity, as a fraction, for ordering only.
DEFAULT_CATEGORY_AS_RANKING            = False
DEFAULT_CATEGORY_RANK_BOOST            = 0.05

# Whether cases sharing words with the ask (BM25 over the stored question) are candidates beside the cosine
# neighbours. "fused" merges the two rankings, "lexical" uses the word ranking alone, to compare the two.
DEFAULT_LEXICAL_CANDIDATES_ENABLED     = False
DEFAULT_LEXICAL_CANDIDATES_MODE        = "fused"
VALID_LEXICAL_CANDIDATES_MODES         = ( "fused", "lexical" )

# The most stored cases the word ranking reads for one ask, above any one account's case count.
LEXICAL_POOL_LIMIT                     = 100000

# Whether a forecast is scored by the complete-action measure (the whole action, not only its stance). False
# keeps the stance-only comparators exactly as they were.
DEFAULT_COMPLETE_ACTION_SCORING_ENABLED = False

# The outcome of a field whose actual pick is not one of the labels the field offered (a typed "Other").
# It is its own outcome, reported beside matches and misses and never counted as a miss.
FIELD_OUTCOME_EXACT            = "exact"
FIELD_OUTCOME_MISS             = "miss"
FIELD_OUTCOME_OTHER_WRITE_IN   = "other_write_in"

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
