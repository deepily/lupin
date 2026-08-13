"""
PredictionEngine — singleton prediction engine for notification responses.

Thread-safe singleton that generates predictions for all notification response types.
Implements Slice 0 (foundation) + Slice 1 (yes_no CBR majority vote)
+ Slice 1.5 (qualified yes/no with comment retrieval)
+ Slice 2 (multiple_choice exclusive CBR majority vote)
+ Slice 3 (multiple_choice inclusive CBR majority vote)
+ Slice 4 (open_ended two-tier: exact match retrieval + LLM synthesis)
+ Slice 5 (open_ended_batch two-tier: compound answer retrieval + LLM synthesis).

Architecture:
    - Initialized at FastAPI boot via lifespan()
    - Called by notifications.py before WebSocket push (predict hook)
    - Called by notifications.py on response submission (record hook)
    - Uses EmbeddingProvider singleton for vector generation
    - Uses LanceDB via ProxyDecisionEmbeddings pattern for CBR retrieval
    - Writes outcomes to prediction_log table via PredictionLogRepository
"""

from threading import Lock
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

import cosa.utils.util as cu

from cosa.agents.prediction_engine.config import (
    DEFAULT_ENABLED,
    DEFAULT_DEBUG,
    DEFAULT_CBR_TOP_K,
    DEFAULT_CBR_SIMILARITY_THRESHOLD,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_LANCEDB_TABLE,
    DEFAULT_EMBEDDING_FALLBACK_PORT,
    DEFAULT_OPEN_ENDED_CBR_TOP_K,
    DEFAULT_OPEN_ENDED_CBR_THRESHOLD,
    DEFAULT_OPEN_ENDED_LLM_SPEC_KEY,
    DEFAULT_HINT_VOTING_ENABLED,
    DEFAULT_HINT_VOTE_MIN_CONFIDENCE_THRESHOLD,
    DEFAULT_HINT_VOTE_APPROVED_WEIGHT,
    DEFAULT_HINT_VOTE_REJECTED_WEIGHT,
    STRATEGY_CBR_MAJORITY,
    STRATEGY_CBR_RETRIEVAL,
    STRATEGY_LLM_SYNTHESIS,
    STRATEGY_COLD_START,
    RESPONSE_TYPE_YES_NO,
    RESPONSE_TYPE_MULTIPLE_CHOICE,
    RESPONSE_TYPE_OPEN_ENDED,
    RESPONSE_TYPE_OPEN_ENDED_BATCH,
)
from cosa.agents.prediction_engine.prediction_result import PredictionResult
from cosa.agents.prediction_engine.notification_category_classifier import NotificationCategoryClassifier
from cosa.agents.prediction_engine.accuracy_comparators import get_comparator, _extract_qualifier


class PredictionEngine:
    """
    Singleton prediction engine for notification responses.

    Requires:
        - EmbeddingProvider initialized (for vector generation)
        - LanceDB available at configured path (for CBR retrieval)
        - PostgreSQL available (for prediction_log writes)

    Ensures:
        - Thread-safe singleton pattern
        - predict() returns PredictionResult for any notification
        - record_outcome() logs prediction + actual to prediction_log
        - Cold start behavior when insufficient data
    """

    _instance = None
    _lock     = Lock()

    def __new__( cls, *args, **kwargs ):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__( cls )
                    cls._instance._initialized = False
        return cls._instance

    def __init__( self, config_mgr=None, debug=False ):
        """
        Initialize the prediction engine (only runs once due to singleton).

        Requires:
            - config_mgr: ConfigurationManager instance (optional, uses defaults)

        Ensures:
            - Classifier, embedding store, and CBR components initialized
            - Engine ready to accept predict() calls
        """
        if self._initialized:
            return
        self._initialized = True

        self.debug = debug

        # Load config
        if config_mgr:
            self.enabled              = config_mgr.get( "prediction engine enabled", default=str( DEFAULT_ENABLED ), return_type="boolean" )
            self.debug                = config_mgr.get( "prediction engine debug", default=str( DEFAULT_DEBUG ), return_type="boolean" ) or debug
            self.cbr_top_k            = config_mgr.get( "prediction engine cbr top k", default=str( DEFAULT_CBR_TOP_K ), return_type="int" )
            self.similarity_threshold = config_mgr.get( "prediction engine cbr similarity threshold", default=str( DEFAULT_CBR_SIMILARITY_THRESHOLD ), return_type="float" )
            self.confidence_threshold = config_mgr.get( "prediction engine confidence threshold", default=str( DEFAULT_CONFIDENCE_THRESHOLD ), return_type="float" )
            self.lancedb_table        = config_mgr.get( "prediction engine lancedb table", default=DEFAULT_LANCEDB_TABLE )
            self._server_port         = config_mgr.get( "prediction engine embedding fallback port", default=str( DEFAULT_EMBEDDING_FALLBACK_PORT ), return_type="int" )
            # Open-ended prediction config
            self.open_ended_cbr_top_k      = config_mgr.get( "prediction engine open ended cbr top k", default=str( DEFAULT_OPEN_ENDED_CBR_TOP_K ), return_type="int" )
            self.open_ended_cbr_threshold  = config_mgr.get( "prediction engine open ended cbr threshold", default=str( DEFAULT_OPEN_ENDED_CBR_THRESHOLD ), return_type="float" )
            self._llm_spec_key             = config_mgr.get( "prediction engine open ended llm spec key", default=DEFAULT_OPEN_ENDED_LLM_SPEC_KEY )
            self._synthesis_prompt_path    = config_mgr.get( "prediction engine open ended prompt template", default="/src/conf/prompts/prediction-engine-open-ended-synthesis.txt" )
            # Thumbs vote weights (human-confirmed training signal)
            self.hint_vote_approved_weight = config_mgr.get( "prediction hint vote approved weight", default=str( DEFAULT_HINT_VOTE_APPROVED_WEIGHT ), return_type="float" )
            self.hint_vote_rejected_weight = config_mgr.get( "prediction hint vote rejected weight", default=str( DEFAULT_HINT_VOTE_REJECTED_WEIGHT ), return_type="float" )
            # Vote-control gate, carried IN the hint payload so the client cannot drift from INI
            self.hint_voting_enabled                = config_mgr.get( "prediction hint voting enabled", default=str( DEFAULT_HINT_VOTING_ENABLED ), return_type="boolean" )
            self.hint_vote_min_confidence_threshold = config_mgr.get( "prediction hint vote min confidence threshold", default=str( DEFAULT_HINT_VOTE_MIN_CONFIDENCE_THRESHOLD ), return_type="float" )
        else:
            self.enabled              = DEFAULT_ENABLED
            self.cbr_top_k            = DEFAULT_CBR_TOP_K
            self.similarity_threshold = DEFAULT_CBR_SIMILARITY_THRESHOLD
            self.confidence_threshold = DEFAULT_CONFIDENCE_THRESHOLD
            self.lancedb_table        = DEFAULT_LANCEDB_TABLE
            self._server_port         = DEFAULT_EMBEDDING_FALLBACK_PORT
            # Open-ended prediction defaults
            self.open_ended_cbr_top_k     = DEFAULT_OPEN_ENDED_CBR_TOP_K
            self.open_ended_cbr_threshold = DEFAULT_OPEN_ENDED_CBR_THRESHOLD
            self._llm_spec_key            = DEFAULT_OPEN_ENDED_LLM_SPEC_KEY
            self._synthesis_prompt_path   = "/src/conf/prompts/prediction-engine-open-ended-synthesis.txt"
            self.hint_vote_approved_weight = DEFAULT_HINT_VOTE_APPROVED_WEIGHT
            self.hint_vote_rejected_weight = DEFAULT_HINT_VOTE_REJECTED_WEIGHT
            self.hint_voting_enabled                = DEFAULT_HINT_VOTING_ENABLED
            self.hint_vote_min_confidence_threshold = DEFAULT_HINT_VOTE_MIN_CONFIDENCE_THRESHOLD

        # Retained for backend-flag resolution in _get_embedding_store (decision
        # 2b20a6d6). None is legitimate — is_postgres_backend() then builds its own.
        self._config_mgr = config_mgr

        # Initialize classifier
        self.classifier = NotificationCategoryClassifier( debug=self.debug )

        # Initialize embedding store (lazy — created on first use)
        self._embedding_store    = None
        self._embedding_provider = None
        self._llm_client         = None

        if self.debug: print( f"[PredictionEngine] Initialized (enabled={self.enabled}, table={self.lancedb_table})" )

    def _get_embedding_provider( self ):
        """Lazy-load the embedding provider singleton."""
        if self._embedding_provider is None:
            try:
                from cosa.memory.embedding_provider import get_embedding_provider
                self._embedding_provider = get_embedding_provider( debug=self.debug )
            except Exception as e:
                if self.debug: print( f"[PredictionEngine] Failed to load embedding provider: {e}" )
        return self._embedding_provider

    def _get_embedding_store( self ):
        """Lazy-load the decision embedding store (postgres or LanceDB per the backend flag)."""
        if self._embedding_store is None:
            try:
                from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
                from cosa.rest.db.repositories.vector_store_backend import is_postgres_backend

                # Ask the backend BEFORE building a path (decision 2b20a6d6). The path
                # was previously hardcoded here — a THIRD authority for the same fact,
                # unreachable by config. It now comes from the same key the rest of the
                # LanceDB path-builders read, and only when LanceDB is actually active.
                if is_postgres_backend( self._config_mgr ):
                    lancedb_path = None
                elif self._config_mgr is not None:
                    lancedb_path = cu.get_project_root() + self._config_mgr.get( "solution snapshots lancedb path" )
                else:
                    lancedb_path = cu.get_project_root() + "/src/conf/long-term-memory/lupin.lancedb"

                self._embedding_store = ProxyDecisionEmbeddings(
                    db_path       = lancedb_path,
                    table_name    = self.lancedb_table,
                    embedding_dim = 768,
                    debug         = self.debug
                )
            except Exception as e:
                if self.debug: print( f"[PredictionEngine] Failed to load embedding store: {e}" )
        return self._embedding_store

    def predict( self, notification_dict: Dict[str, Any] ) -> PredictionResult:
        """
        Generate a prediction for a notification response.

        Requires:
            - notification_dict contains: message, response_type, sender_id (optional)

        Ensures:
            - Returns PredictionResult (cold_start if insufficient data or disabled)
            - Dispatches to type-specific prediction method
            - Classification always runs (for logging even in cold start)
            - Never raises exceptions (graceful degradation)
        """
        message       = notification_dict.get( "message", "" )
        response_type = notification_dict.get( "response_type", "" )
        sender_id     = notification_dict.get( "sender_id", "" )

        # Classify the notification
        category, class_confidence = self.classifier.classify( message, sender_id=sender_id )

        if self.debug: print( f"[PredictionEngine] predict() type={response_type}, category={category}, conf={class_confidence:.2f}" )

        # If disabled, return cold start with category info
        if not self.enabled:
            return PredictionResult(
                response_type = response_type,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": "engine_disabled" }
            )

        # Generate embedding for the message. An open_ended_batch's notification
        # message is a content-free count preamble ("I have N questions for you.")
        # that collides across unrelated batches (bug cdb5a76f) — embed the
        # per-question content key instead, symmetric with the storage key in
        # _store_decision so retrieval and storage speak the same language.
        if response_type == RESPONSE_TYPE_OPEN_ENDED_BATCH:
            retrieval_text = self._batch_question_key( message, notification_dict.get( "response_options" ) )
        else:
            retrieval_text = message

        embedding = self._generate_embedding( retrieval_text )

        # Dispatch by response type
        try:
            if response_type == RESPONSE_TYPE_YES_NO:
                return self._predict_yes_no( message, category, embedding )

            elif response_type == RESPONSE_TYPE_MULTIPLE_CHOICE:
                options = notification_dict.get( "response_options" )
                return self._predict_multiple_choice( message, category, embedding, options )

            elif response_type == RESPONSE_TYPE_OPEN_ENDED:
                return self._predict_open_ended( message, category, embedding )

            elif response_type == RESPONSE_TYPE_OPEN_ENDED_BATCH:
                # Pass the content key as the match text so exact-match compares
                # batch content to batch content, and stamp it so _store_decision
                # keys the stored case on the same content (not the preamble).
                result = self._predict_open_ended_batch( retrieval_text, category, embedding )
                if result.metadata is not None:
                    result.metadata[ "batch_question_key" ] = retrieval_text
                return result

            # Unknown response type — cold start
            return PredictionResult(
                response_type = response_type,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": f"unsupported_type_{response_type}" }
            )

        except Exception as e:
            if self.debug: print( f"[PredictionEngine] predict() error: {e}" )
            return PredictionResult(
                response_type = response_type,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": "prediction_error", "error": str( e ) }
            )

    def _ratified_weight( self, record ) -> float:
        """
        Vote weight a retrieved CBR case contributes to its decision_value, by the
        user's thumbs up/down ratification (human-confirmed training signal).

        Requires:
            - record is a dict that may carry a "ratification_state" key

        Ensures:
            - "approved" → +hint_vote_approved_weight (human-confirmed up-weight, > 1.0)
            - "rejected" → -hint_vote_rejected_weight (NEGATIVE vote — engine steers away)
            - anything else (pending / not_required / "" / missing) → +1.0 (ordinary case)
        """
        state = ( record.get( "ratification_state" ) or "" ).lower()
        if state == "approved": return  self.hint_vote_approved_weight
        if state == "rejected": return -self.hint_vote_rejected_weight
        return 1.0

    @staticmethod
    def _bounded_consistency( votes: dict, winner ) -> float:
        """
        Majority-vote consistency in [0,1] that tolerates negative (steer-away) votes.

        The classic `winner_votes / total_votes` breaks once rejected cases cast
        negative votes (total can be small, zero, or negative). Normalizing by the
        POSITIVE mass keeps the result bounded and meaningful.

        Requires:
            - votes is a {value: signed_weight} dict, winner is a key in votes

        Ensures:
            - returns winner_tally / sum(positive tallies), clamped to [0,1]
            - returns 0.0 when there is no positive mass (everything steered away)
        """
        positive_mass = sum( v for v in votes.values() if v > 0 )
        if positive_mass <= 0: return 0.0
        return max( 0.0, min( 1.0, votes[ winner ] / positive_mass ) )

    @staticmethod
    def _is_rejected_case( record ) -> bool:
        """
        True when the user thumbs-downed this CBR case (ratification_state="rejected").

        A rejected case must never BE the answer in the open-ended retrieval tiers —
        the engine steers away from it (Stage 3 of the thumbs-vote training signal).
        """
        return ( record.get( "ratification_state" ) or "" ).lower() == "rejected"

    def _select_retrieval_case( self, similar_cases: list, message: str ) -> tuple:
        """
        Ratification-aware case selection for the open-ended retrieval tiers.

        Requires:
            - similar_cases: list of ( similarity_pct, record ), descending similarity
            - message: the current question text

        Ensures:
            - Returns ( candidate_cases, exact_case ):
              - candidate_cases: cases allowed to BE an answer (rejected cases filtered
                out — steer-away); [] when the user thumbs-downed every case
              - exact_case: the ( similarity_pct, record ) whose question matches message
                (normalized), approved cases preferred over ordinary ones, highest
                similarity first within each tier; None when no non-rejected exact
                match exists
        """
        candidate_cases = [ ( s, r ) for s, r in similar_cases if not self._is_rejected_case( r ) ]

        exact_case = None
        for similarity_pct, record in candidate_cases:
            if record.get( "question", "" ).strip().lower() == message.strip().lower():
                state = ( record.get( "ratification_state" ) or "" ).lower()
                if state == "approved":
                    return ( candidate_cases, ( similarity_pct, record ) )
                if exact_case is None:
                    exact_case = ( similarity_pct, record )

        return ( candidate_cases, exact_case )

    @staticmethod
    def _batch_question_key( message: str, response_options: Any ) -> str:
        """
        Build a content-bearing CBR key for an open_ended_batch from its per-question texts.

        The batch's notification message is a content-free count preamble
        ("I have N questions for you.") — correct for TTS, useless as a semantic
        key, because every N-question batch collides on it and can retrieve an
        UNRELATED batch's answers at similarity 1.0 (bug cdb5a76f). Keying on the
        actual question texts ("header: question" per entry) restores batch identity.

        Requires:
            - message is the notification message (the fallback key)
            - response_options is the dict passed to predict() (may be None)

        Ensures:
            - Returns "header: question" per entry, joined by " | ", when
              response_options carries a non-empty "questions" list
            - Falls back to message when response_options is missing / malformed /
              empty, or when no entry yields any text
        """
        if not isinstance( response_options, dict ):
            return message
        questions = response_options.get( "questions" )
        if not isinstance( questions, list ) or not questions:
            return message

        parts = []
        for q in questions:
            if not isinstance( q, dict ):
                continue
            header   = str( q.get( "header",   "" ) ).strip()
            question = str( q.get( "question", "" ) ).strip()
            if header and question:
                parts.append( f"{header}: {question}" )
            elif question:
                parts.append( question )
            elif header:
                parts.append( header )

        if not parts:
            return message
        return " | ".join( parts )

    def _predict_yes_no( self, message: str, category: str, embedding: Optional[list] ) -> PredictionResult:
        """
        Predict yes/no response using CBR majority vote with qualifier retrieval.

        Requires:
            - message: The notification message
            - category: Classified category
            - embedding: Message embedding vector (or None)

        Ensures:
            - Retrieves top-k similar past yes/no responses
            - Majority vote on "yes"/"no" values
            - Confidence = max_similarity * consistency
            - Extracts qualifier from highest-similarity winning-side case
            - Returns cold_start if no similar cases found
        """
        if embedding is None:
            return PredictionResult(
                response_type = RESPONSE_TYPE_YES_NO,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": "no_embedding" }
            )

        store = self._get_embedding_store()
        if store is None:
            return PredictionResult(
                response_type = RESPONSE_TYPE_YES_NO,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": "no_embedding_store" }
            )

        # Find similar past notifications (filtered by response_type)
        try:
            similar_cases = store.find_similar(
                query_embedding = embedding,
                category        = category,
                limit           = self.cbr_top_k,
                threshold       = self.similarity_threshold,
                response_type   = RESPONSE_TYPE_YES_NO
            )
        except Exception as e:
            if self.debug: print( f"[PredictionEngine] find_similar error: {e}" )
            similar_cases = []

        if not similar_cases:
            return PredictionResult(
                response_type      = RESPONSE_TYPE_YES_NO,
                category           = category,
                strategy           = STRATEGY_COLD_START,
                similar_case_count = 0,
                metadata           = { "reason": "no_similar_cases" }
            )

        # Majority vote — ratification-aware (thumbs up/down training signal):
        # approved cases up-weight their value, rejected cases cast a NEGATIVE vote
        # against their value so the engine actively steers away. See _ratified_weight().
        votes = {}
        max_similarity = 0.0

        for similarity_pct, record in similar_cases:
            decision_value = record.get( "decision_value", "" )
            # Extract binary from potential qualified value
            binary_value = "yes" if decision_value.lower().startswith( "yes" ) else "no"
            votes[ binary_value ] = votes.get( binary_value, 0.0 ) + self._ratified_weight( record )
            max_similarity = max( max_similarity, similarity_pct / 100.0 )

        # Winner = highest (most positive) tally; consistency bounded to [0,1] via
        # positive-mass normalization so negative (steer-away) votes can't break it.
        winner      = max( votes, key=votes.get )
        consistency = self._bounded_consistency( votes, winner )

        # Confidence = max_similarity * consistency
        confidence = max_similarity * consistency

        # Qualifier retrieval from winning-side cases
        winning_qualifier    = None
        qualifier_similarity = 0.0

        for similarity_pct, record in similar_cases:
            decision_value = record.get( "decision_value", "" )
            binary_value   = "yes" if decision_value.lower().startswith( "yes" ) else "no"

            if binary_value == winner:
                qualifier = _extract_qualifier( decision_value )
                if qualifier and similarity_pct > qualifier_similarity:
                    winning_qualifier    = qualifier
                    qualifier_similarity = similarity_pct

        if self.debug:
            print( f"[PredictionEngine] yes_no: votes={votes}, winner={winner}, conf={confidence:.3f}, qualifier={winning_qualifier}" )

        return PredictionResult(
            response_type       = RESPONSE_TYPE_YES_NO,
            category            = category,
            strategy            = STRATEGY_CBR_MAJORITY,
            predicted_value     = winner,
            confidence          = confidence,
            similar_case_count  = len( similar_cases ),
            predicted_qualifier = winning_qualifier,
            metadata            = {
                "votes"                : votes,
                "max_similarity"       : round( max_similarity, 3 ),
                "qualifier_similarity" : round( qualifier_similarity / 100.0, 3 ) if winning_qualifier else None,
            }
        )

    @staticmethod
    def _extract_valid_options( options: Any ) -> Optional[Dict[str, Dict]]:
        """
        Extract valid option labels and multi_select flag from the options structure.

        Requires:
            - options: The options parameter from notifications, or None

        Ensures:
            - Returns { header: { "labels": set[str], "multi_select": bool } } if parseable
            - Returns None if options is None or unparseable

        Expected input format:
            {"questions": [{"question": "...", "header": "...", "multi_select": bool,
                            "options": [{"label": "Push", "description": "..."}]}]}
        """
        if options is None:
            return None

        try:
            # Handle string input (JSON)
            if isinstance( options, str ):
                import json
                options = json.loads( options )

            questions = options.get( "questions", [] ) if isinstance( options, dict ) else []
            if not questions:
                return None

            result = {}
            for q in questions:
                header       = q.get( "header", q.get( "question", "" ) )
                multi_select = q.get( "multi_select", q.get( "multiSelect", False ) )
                opt_list     = q.get( "options", [] )
                labels       = { opt[ "label" ] for opt in opt_list if isinstance( opt, dict ) and "label" in opt }

                if header and labels:
                    result[ header ] = { "labels": labels, "multi_select": multi_select }

            return result if result else None

        except ( TypeError, KeyError, ValueError ):
            return None

    def _predict_multiple_choice( self, message: str, category: str,
                                     embedding: Optional[list],
                                     options: Any = None ) -> PredictionResult:
        """
        Predict multiple choice response using CBR majority vote (single or multi-select).

        Requires:
            - message: The notification message
            - category: Classified category
            - embedding: Message embedding vector (or None)
            - options: Response options structure with valid labels for validation

        Ensures:
            - Retrieves top-k similar past multiple_choice responses (filtered by response_type)
            - Detects single vs multi-select from options structure (fallback to data detection)
            - Single-select: per-header majority vote → string values, validated against options
            - Multi-select: per-header option frequency counting → list values, validated against options
            - Confidence = max_similarity * avg_consistency
            - Returns cold_start if no similar cases found or no valid options after filtering
            - predicted_value is {"answers": {"Header": "Option"}} or {"answers": {"Header": ["A", "B"]}}
        """
        if embedding is None:
            return PredictionResult(
                response_type = RESPONSE_TYPE_MULTIPLE_CHOICE,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": "no_embedding" }
            )

        store = self._get_embedding_store()
        if store is None:
            return PredictionResult(
                response_type = RESPONSE_TYPE_MULTIPLE_CHOICE,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": "no_embedding_store" }
            )

        # Extract valid options for validation
        valid_options = self._extract_valid_options( options )

        # Find similar past notifications (filtered by response_type)
        try:
            similar_cases = store.find_similar(
                query_embedding = embedding,
                category        = category,
                limit           = self.cbr_top_k,
                threshold       = self.similarity_threshold,
                response_type   = RESPONSE_TYPE_MULTIPLE_CHOICE
            )
        except Exception as e:
            if self.debug: print( f"[PredictionEngine] find_similar error (MC): {e}" )
            similar_cases = []

        if not similar_cases:
            return PredictionResult(
                response_type      = RESPONSE_TYPE_MULTIPLE_CHOICE,
                category           = category,
                strategy           = STRATEGY_COLD_START,
                similar_case_count = 0,
                metadata           = { "reason": "no_similar_cases" }
            )

        # Determine multi_select from options structure (fallback to data detection)
        options_multi_select = None
        if valid_options:
            options_multi_select = any( v[ "multi_select" ] for v in valid_options.values() )

        # Per-header vote accumulation (type-aware: single vs multi-select)
        # header_votes: { "Header": { "OptionA": count, "OptionB": count } } — raw integer
        # counts (used by metadata + the valid-option fallback, unchanged).
        # header_votes_weighted: same shape with ratification-WEIGHTED floats (approved
        # up-weight, rejected negative/steer-away) — drives BOTH the single-select winner
        # + consistency and (Stage 3) the multi-select tally.
        # positive_case_mass: sum of positive case weights — the weighted analogue of
        # valid_cases, the multi-select inclusion-threshold denominator.
        header_votes          = {}
        header_votes_weighted = {}
        max_similarity        = 0.0
        valid_cases           = 0
        positive_case_mass    = 0.0
        is_multi_select       = False

        for similarity_pct, record in similar_cases:
            decision_value = record.get( "decision_value", "" )
            parsed         = self._parse_mc_decision_value( decision_value )
            if parsed is None:
                continue

            valid_cases += 1
            max_similarity = max( max_similarity, similarity_pct / 100.0 )

            answers     = parsed.get( "answers", {} )
            case_weight = self._ratified_weight( record )   # +approved / -rejected / 1.0
            positive_case_mass += max( case_weight, 0.0 )
            for header, option in answers.items():
                if header not in header_votes:
                    header_votes[ header ]          = {}
                    header_votes_weighted[ header ] = {}

                if isinstance( option, list ):
                    # Multi-select: raw count + ratification-WEIGHTED tally (Stage 3 —
                    # consumed by _tally_multi_select_votes below).
                    is_multi_select = True
                    for item in option:
                        header_votes[ header ][ item ]          = header_votes[ header ].get( item, 0 ) + 1
                        header_votes_weighted[ header ][ item ] = header_votes_weighted[ header ].get( item, 0.0 ) + case_weight
                else:
                    # Single-select: raw count + ratification-WEIGHTED tally (consumed below).
                    header_votes[ header ][ option ]          = header_votes[ header ].get( option, 0 ) + 1
                    header_votes_weighted[ header ][ option ] = header_votes_weighted[ header ].get( option, 0.0 ) + case_weight

        if not header_votes or valid_cases == 0:
            return PredictionResult(
                response_type      = RESPONSE_TYPE_MULTIPLE_CHOICE,
                category           = category,
                strategy           = STRATEGY_COLD_START,
                similar_case_count = len( similar_cases ),
                metadata           = { "reason": "no_valid_mc_cases" }
            )

        # Use options structure to determine multi_select when available
        if options_multi_select is not None:
            is_multi_select = options_multi_select

        # Build predicted answers — branch by single vs multi-select
        if is_multi_select:
            # Ratification-aware (Stage 3): weighted votes + positive-mass denominator.
            predicted_answers, avg_consistency = self._tally_multi_select_votes( header_votes_weighted, positive_case_mass )
            if not predicted_answers:
                # Every option in every header was steered away (thumbs-downed) — no
                # positive signal survives, so there is nothing to predict.
                return PredictionResult(
                    response_type      = RESPONSE_TYPE_MULTIPLE_CHOICE,
                    category           = category,
                    strategy           = STRATEGY_COLD_START,
                    similar_case_count = len( similar_cases ),
                    metadata           = { "reason": "all_multi_select_options_steered_away", "valid_cases": valid_cases }
                )
        else:
            predicted_answers  = {}
            consistency_sum    = 0.0
            header_count       = 0

            for header, weighted_votes in header_votes_weighted.items():
                # Ratification-aware: winner = highest weighted tally; consistency bounded
                # to [0,1] via positive-mass normalization (rejected cases steer away).
                winner      = max( weighted_votes, key=weighted_votes.get )
                consistency = self._bounded_consistency( weighted_votes, winner )
                predicted_answers[ header ] = winner
                consistency_sum += consistency
                header_count    += 1

            avg_consistency = consistency_sum / header_count if header_count > 0 else 0.0

        # Validate predictions against available options
        constrained = False
        if valid_options:
            validated_answers = {}
            for header, prediction in predicted_answers.items():
                option_info = valid_options.get( header )
                if option_info is None:
                    # Header not in options structure — keep as-is (backward compat)
                    validated_answers[ header ] = prediction
                    continue

                valid_labels = option_info[ "labels" ]

                if isinstance( prediction, list ):
                    # Multi-select: filter to valid labels only
                    filtered = [ p for p in prediction if p in valid_labels ]
                    if filtered:
                        if set( filtered ) != set( prediction ):
                            constrained = True
                            if self.debug: print( f"[PredictionEngine] MC constrained '{header}': {prediction} → {filtered}" )
                        validated_answers[ header ] = sorted( filtered )
                    else:
                        # No valid options survived — will trigger cold_start below
                        validated_answers[ header ] = []
                else:
                    # Single-select: winner must be a valid label
                    if prediction in valid_labels:
                        validated_answers[ header ] = prediction
                    else:
                        # Fall back to highest-voted valid option
                        constrained = True
                        option_votes = header_votes.get( header, {} )
                        valid_voted  = { opt: count for opt, count in option_votes.items() if opt in valid_labels }
                        if valid_voted:
                            fallback = max( valid_voted, key=valid_voted.get )
                            if self.debug: print( f"[PredictionEngine] MC constrained '{header}': '{prediction}' → '{fallback}'" )
                            validated_answers[ header ] = fallback
                        else:
                            validated_answers[ header ] = None

            predicted_answers = validated_answers

            # Check if any header ended up empty after validation
            has_empty = any(
                ( v is None ) or ( isinstance( v, list ) and len( v ) == 0 )
                for v in predicted_answers.values()
            )
            if has_empty:
                return PredictionResult(
                    response_type      = RESPONSE_TYPE_MULTIPLE_CHOICE,
                    category           = category,
                    strategy           = STRATEGY_COLD_START,
                    similar_case_count = len( similar_cases ),
                    metadata           = { "reason": "no_valid_options_after_filtering", "valid_cases": valid_cases }
                )

        confidence = max_similarity * avg_consistency

        if self.debug:
            mode = "multi" if is_multi_select else "single"
            extra = " (constrained)" if constrained else ""
            print( f"[PredictionEngine] MC({mode}){extra}: predicted={predicted_answers}, conf={confidence:.3f}, cases={valid_cases}" )

        return PredictionResult(
            response_type      = RESPONSE_TYPE_MULTIPLE_CHOICE,
            category           = category,
            strategy           = STRATEGY_CBR_MAJORITY,
            predicted_value    = { "answers": predicted_answers },
            confidence         = confidence,
            similar_case_count = len( similar_cases ),
            metadata           = {
                "votes"          : { h: dict( v ) for h, v in header_votes.items() },
                "max_similarity" : round( max_similarity, 3 ),
                "valid_cases"    : valid_cases,
                "multi_select"   : is_multi_select,
                "constrained"    : constrained,
            }
        )

    def _tally_multi_select_votes( self, header_option_votes: Dict[str, Dict[str, float]],
                                      positive_case_mass: float ) -> tuple:
        """
        Tally multi-select votes (ratification-aware): select options whose weighted
        vote reaches >= 50% of the positive case mass.

        Approved cases contribute +approved_weight per option they selected, rejected
        cases a NEGATIVE weight (steer-away), ordinary cases +1.0 — see _ratified_weight().
        With no ratified cases this reduces exactly to the original raw-count behavior
        (all weights 1.0, positive_case_mass == valid_cases).

        Requires:
            - header_option_votes: { "Header": { "OptionA": signed_weight, ... } }
            - positive_case_mass: sum of positive case weights across valid cases (>= 0)

        Ensures:
            - Returns ( predicted_answers, avg_consistency ) tuple
            - predicted_answers: { "Header": ["OptionA", "OptionB"] } (list values)
            - Options included if weighted_vote / positive_case_mass >= 0.5
            - Options with non-positive weighted votes are NEVER selected (steered away)
            - Headers where every option was steered away are omitted entirely —
              predicted_answers may be {} when everything was thumbs-downed
            - Fallback: highest positively-weighted option when none meets the threshold
            - avg_consistency based on mean inclusion rate of selected options, in [0,1]
        """
        predicted_answers = {}
        consistency_sum   = 0.0
        header_count      = 0

        for header, option_votes in header_option_votes.items():
            threshold = positive_case_mass * 0.5
            selected  = [ opt for opt, weight in option_votes.items() if weight > 0 and weight >= threshold ]

            # Fallback: no option meets the threshold — pick the highest positively-weighted
            # option. A header with NO positive option was steered away entirely → omit it.
            if not selected:
                positive_votes = { opt: weight for opt, weight in option_votes.items() if weight > 0 }
                if not positive_votes:
                    continue
                selected = [ max( positive_votes, key=positive_votes.get ) ]

            # Consistency = mean inclusion rate of selected options (clamped: float noise
            # in summed config weights could nudge a vote a hair above the positive mass).
            inclusion_rates = [ min( option_votes[ opt ] / positive_case_mass, 1.0 ) for opt in selected ]
            consistency     = sum( inclusion_rates ) / len( inclusion_rates )

            predicted_answers[ header ] = sorted( selected )
            consistency_sum += consistency
            header_count    += 1

        avg_consistency = consistency_sum / header_count if header_count > 0 else 0.0

        return ( predicted_answers, avg_consistency )

    def _predict_open_ended( self, message: str, category: str, embedding: Optional[list] ) -> PredictionResult:
        """
        Predict open-ended response using two-tier retrieval + LLM synthesis.

        Requires:
            - message: The notification message (question to predict answer for)
            - category: Classified category
            - embedding: Message embedding vector (or None)

        Ensures:
            - Tier 1: Exact normalized question match → STRATEGY_CBR_RETRIEVAL
            - Tier 2: Top K similar cases → LLM synthesis → STRATEGY_LLM_SYNTHESIS
            - Falls back to cold_start if no embedding, store, or similar cases
            - Falls back to retrieval if LLM call fails
        """
        if embedding is None:
            return PredictionResult(
                response_type = RESPONSE_TYPE_OPEN_ENDED,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": "no_embedding" }
            )

        store = self._get_embedding_store()
        if store is None:
            return PredictionResult(
                response_type = RESPONSE_TYPE_OPEN_ENDED,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": "no_embedding_store" }
            )

        # Retrieve top K similar cases using open-ended-specific thresholds (filtered by response_type)
        try:
            similar_cases = store.find_similar(
                query_embedding = embedding,
                category        = category,
                limit           = self.open_ended_cbr_top_k,
                threshold       = self.open_ended_cbr_threshold,
                response_type   = RESPONSE_TYPE_OPEN_ENDED
            )
        except Exception as e:
            if self.debug: print( f"[PredictionEngine] find_similar error (OE): {e}" )
            similar_cases = []

        if not similar_cases:
            return PredictionResult(
                response_type      = RESPONSE_TYPE_OPEN_ENDED,
                category           = category,
                strategy           = STRATEGY_COLD_START,
                similar_case_count = 0,
                metadata           = { "reason": "no_similar_cases" }
            )

        # Ratification-aware (Stage 3): rejected (thumbs-downed) cases can never BE the
        # answer; approved exact matches are preferred. Rejected cases still reach LLM
        # synthesis as anti-exemplars via user_verdict annotations (_build_synthesis_prompt).
        candidate_cases, exact_case = self._select_retrieval_case( similar_cases, message )

        if not candidate_cases:
            return PredictionResult(
                response_type      = RESPONSE_TYPE_OPEN_ENDED,
                category           = category,
                strategy           = STRATEGY_COLD_START,
                similar_case_count = len( similar_cases ),
                metadata           = { "reason": "all_cases_rejected" }
            )

        max_similarity = candidate_cases[ 0 ][ 0 ] / 100.0
        top_case       = candidate_cases[ 0 ][ 1 ]
        top_question   = top_case.get( "question", "" )

        # Tier 1 — Exact match (normalized; approved-preferred, rejected never)
        if exact_case is not None:
            exact_similarity = exact_case[ 0 ] / 100.0
            exact_question   = exact_case[ 1 ].get( "question", "" )
            decision_value   = exact_case[ 1 ].get( "decision_value", "" )

            if self.debug:
                print( f"[PredictionEngine] OE exact match: q='{exact_question[:60]}', answer='{decision_value[:60]}'" )

            return PredictionResult(
                response_type      = RESPONSE_TYPE_OPEN_ENDED,
                category           = category,
                strategy           = STRATEGY_CBR_RETRIEVAL,
                predicted_value    = decision_value,
                confidence         = exact_similarity,
                similar_case_count = len( similar_cases ),
                metadata           = {
                    "max_similarity"    : round( exact_similarity, 3 ),
                    "top_case_question" : exact_question[ :100 ],
                    "case_count"        : len( similar_cases ),
                    "tier"              : "exact_match",
                    "original_message"  : message,
                }
            )

        # Tier 2 — LLM synthesis
        try:
            prompt   = self._build_synthesis_prompt( message, similar_cases )
            client   = self._get_llm_client()
            if client is None:
                raise RuntimeError( "LLM client unavailable" )

            response = client.run( prompt )

            from cosa.agents.prediction_engine.xml_models import OpenEndedSynthesisResponse
            parsed = OpenEndedSynthesisResponse.from_xml( response, root_tag="open_ended_synthesis_response" )

            llm_confidence  = parsed.get_confidence_float()
            final_confidence = min( max_similarity, llm_confidence )

            if self.debug:
                print( f"[PredictionEngine] OE LLM synthesis: answer='{parsed.predicted_answer[:60]}', conf={final_confidence:.3f}" )

            return PredictionResult(
                response_type      = RESPONSE_TYPE_OPEN_ENDED,
                category           = category,
                strategy           = STRATEGY_LLM_SYNTHESIS,
                predicted_value    = parsed.predicted_answer,
                confidence         = final_confidence,
                similar_case_count = len( similar_cases ),
                metadata           = {
                    "max_similarity"       : round( max_similarity, 3 ),
                    "top_case_question"    : top_question[ :100 ],
                    "case_count"           : len( similar_cases ),
                    "synthesis_reasoning"  : parsed.reasoning[ :200 ],
                    "tier"                 : "llm_synthesis",
                    "original_message"     : message,
                }
            )

        except Exception as e:
            # Fallback to top case retrieval on LLM failure
            if self.debug: print( f"[PredictionEngine] OE LLM synthesis failed, falling back to retrieval: {e}" )

            decision_value = top_case.get( "decision_value", "" )
            return PredictionResult(
                response_type      = RESPONSE_TYPE_OPEN_ENDED,
                category           = category,
                strategy           = STRATEGY_CBR_RETRIEVAL,
                predicted_value    = decision_value,
                confidence         = max_similarity,
                similar_case_count = len( similar_cases ),
                metadata           = {
                    "max_similarity"    : round( max_similarity, 3 ),
                    "top_case_question" : top_question[ :100 ],
                    "case_count"        : len( similar_cases ),
                    "tier"              : "llm_fallback",
                    "llm_error"         : str( e )[ :200 ],
                    "original_message"  : message,
                }
            )

    def _build_synthesis_prompt( self, message: str, similar_cases: list ) -> str:
        """
        Build the LLM prompt for open-ended answer synthesis.

        Requires:
            - message: Current question text
            - similar_cases: List of ( similarity_pct, record ) tuples from CBR retrieval

        Ensures:
            - Returns a complete prompt string with template + context injected
            - {{PYDANTIC_XML_EXAMPLE}} replaced with XML example from OpenEndedSynthesisResponse
            - Cases formatted as numbered XML blocks
        """
        # Load prompt template
        template_raw = cu.get_file_as_string(
            cu.get_project_root() + self._synthesis_prompt_path
        )

        # Replace {{PYDANTIC_XML_EXAMPLE}} with model example
        from cosa.agents.prediction_engine.xml_models import OpenEndedSynthesisResponse
        xml_example    = OpenEndedSynthesisResponse.get_example_for_template().to_xml()
        xml_with_stop  = xml_example.rstrip() + "</stop>"
        template_ready = template_raw.replace( "{{PYDANTIC_XML_EXAMPLE}}", xml_with_stop )

        # Format cases as numbered XML blocks. Ratified cases carry a user_verdict
        # attribute (Stage 3): "approved" = human-confirmed (weight heavily);
        # "rejected" = explicitly thumbs-downed (anti-exemplar — steer away).
        case_lines = []
        for i, ( similarity_pct, record ) in enumerate( similar_cases, 1 ):
            question       = record.get( "question", "" )
            decision_value = record.get( "decision_value", "" )
            sim_score      = round( similarity_pct / 100.0, 2 )
            state          = ( record.get( "ratification_state" ) or "" ).lower()
            verdict_attr   = f' user_verdict="{state}"' if state in ( "approved", "rejected" ) else ""
            case_lines.append(
                f'<case n="{i}" similarity="{sim_score}"{verdict_attr}>\n'
                f'    <question>{question}</question>\n'
                f'    <response>{decision_value}</response>\n'
                f'</case>'
            )
        formatted_cases = "\n".join( case_lines )

        # Inject runtime context
        prompt = template_ready.format(
            current_question = message,
            case_count       = len( similar_cases ),
            formatted_cases  = formatted_cases,
        )

        return prompt

    def _predict_open_ended_batch( self, message: str, category: str, embedding: Optional[list] ) -> PredictionResult:
        """
        Predict open_ended_batch response using two-tier retrieval + LLM synthesis.

        Requires:
            - message: The notification message
            - category: Classified category
            - embedding: Message embedding vector (or None)

        Ensures:
            - Same two-tier approach as _predict_open_ended
            - Decision values are JSON-parsed to dicts when possible
            - Returns cold_start if insufficient data
        """
        import json

        if embedding is None:
            return PredictionResult(
                response_type = RESPONSE_TYPE_OPEN_ENDED_BATCH,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": "no_embedding" }
            )

        store = self._get_embedding_store()
        if store is None:
            return PredictionResult(
                response_type = RESPONSE_TYPE_OPEN_ENDED_BATCH,
                category      = category,
                strategy      = STRATEGY_COLD_START,
                metadata      = { "reason": "no_embedding_store" }
            )

        try:
            similar_cases = store.find_similar(
                query_embedding = embedding,
                category        = category,
                limit           = self.open_ended_cbr_top_k,
                threshold       = self.open_ended_cbr_threshold,
                response_type   = RESPONSE_TYPE_OPEN_ENDED_BATCH
            )
        except Exception as e:
            if self.debug: print( f"[PredictionEngine] find_similar error (OEB): {e}" )
            similar_cases = []

        if not similar_cases:
            return PredictionResult(
                response_type      = RESPONSE_TYPE_OPEN_ENDED_BATCH,
                category           = category,
                strategy           = STRATEGY_COLD_START,
                similar_case_count = 0,
                metadata           = { "reason": "no_similar_cases" }
            )

        # Ratification-aware (Stage 3): rejected (thumbs-downed) cases can never BE the
        # answer; approved exact matches are preferred. Rejected cases still reach LLM
        # synthesis as anti-exemplars via user_verdict annotations (_build_synthesis_prompt).
        candidate_cases, exact_case = self._select_retrieval_case( similar_cases, message )

        if not candidate_cases:
            return PredictionResult(
                response_type      = RESPONSE_TYPE_OPEN_ENDED_BATCH,
                category           = category,
                strategy           = STRATEGY_COLD_START,
                similar_case_count = len( similar_cases ),
                metadata           = { "reason": "all_cases_rejected" }
            )

        max_similarity = candidate_cases[ 0 ][ 0 ] / 100.0
        top_case       = candidate_cases[ 0 ][ 1 ]
        top_question   = top_case.get( "question", "" )

        # Tier 1 — Exact match (normalized; approved-preferred, rejected never)
        if exact_case is not None:
            exact_similarity = exact_case[ 0 ] / 100.0
            exact_question   = exact_case[ 1 ].get( "question", "" )
            decision_value   = exact_case[ 1 ].get( "decision_value", "" )

            # Parse JSON to get dict with answers
            predicted = self._parse_batch_decision_value( decision_value )

            if self.debug:
                print( f"[PredictionEngine] OEB exact match: q='{exact_question[:60]}'" )

            return PredictionResult(
                response_type      = RESPONSE_TYPE_OPEN_ENDED_BATCH,
                category           = category,
                strategy           = STRATEGY_CBR_RETRIEVAL,
                predicted_value    = predicted,
                confidence         = exact_similarity,
                similar_case_count = len( similar_cases ),
                metadata           = {
                    "max_similarity"    : round( exact_similarity, 3 ),
                    "top_case_question" : exact_question[ :100 ],
                    "case_count"        : len( similar_cases ),
                    "tier"              : "exact_match",
                    "original_message"  : message,
                }
            )

        # Tier 2 — LLM synthesis
        try:
            prompt = self._build_synthesis_prompt( message, similar_cases )
            client = self._get_llm_client()
            if client is None:
                raise RuntimeError( "LLM client unavailable" )

            response = client.run( prompt )

            from cosa.agents.prediction_engine.xml_models import OpenEndedSynthesisResponse
            parsed = OpenEndedSynthesisResponse.from_xml( response, root_tag="open_ended_synthesis_response" )

            llm_confidence   = parsed.get_confidence_float()
            final_confidence = min( max_similarity, llm_confidence )

            # Try to JSON-parse the predicted_answer for batch format
            predicted = self._parse_batch_decision_value( parsed.predicted_answer )

            if self.debug:
                print( f"[PredictionEngine] OEB LLM synthesis: conf={final_confidence:.3f}" )

            return PredictionResult(
                response_type      = RESPONSE_TYPE_OPEN_ENDED_BATCH,
                category           = category,
                strategy           = STRATEGY_LLM_SYNTHESIS,
                predicted_value    = predicted,
                confidence         = final_confidence,
                similar_case_count = len( similar_cases ),
                metadata           = {
                    "max_similarity"      : round( max_similarity, 3 ),
                    "top_case_question"   : top_question[ :100 ],
                    "case_count"          : len( similar_cases ),
                    "synthesis_reasoning" : parsed.reasoning[ :200 ],
                    "tier"                : "llm_synthesis",
                    "original_message"    : message,
                }
            )

        except Exception as e:
            if self.debug: print( f"[PredictionEngine] OEB LLM synthesis failed, falling back to retrieval: {e}" )

            decision_value = top_case.get( "decision_value", "" )
            predicted      = self._parse_batch_decision_value( decision_value )

            return PredictionResult(
                response_type      = RESPONSE_TYPE_OPEN_ENDED_BATCH,
                category           = category,
                strategy           = STRATEGY_CBR_RETRIEVAL,
                predicted_value    = predicted,
                confidence         = max_similarity,
                similar_case_count = len( similar_cases ),
                metadata           = {
                    "max_similarity"    : round( max_similarity, 3 ),
                    "top_case_question" : top_question[ :100 ],
                    "case_count"        : len( similar_cases ),
                    "tier"              : "llm_fallback",
                    "llm_error"         : str( e )[ :200 ],
                    "original_message"  : message,
                }
            )

    @staticmethod
    def _parse_batch_decision_value( decision_value: str ) -> Any:
        """
        Parse a batch decision_value string into a dict or return raw string.

        Requires:
            - decision_value: String (possibly JSON with "answers" key)

        Ensures:
            - Returns dict with "answers" key if valid JSON batch format
            - Returns raw string otherwise
        """
        import json
        if not decision_value or not decision_value.strip():
            return decision_value

        try:
            parsed = json.loads( decision_value )
            if isinstance( parsed, dict ) and "answers" in parsed:
                return parsed
        except ( json.JSONDecodeError, TypeError ):
            pass

        return decision_value

    def _get_llm_client( self ):
        """
        Lazy-load the LLM client for open-ended synthesis.

        Ensures:
            - Returns LlmClient instance or None on failure
            - Caches client for reuse
        """
        if self._llm_client is None:
            try:
                from cosa.agents.llm_client_factory import LlmClientFactory
                factory          = LlmClientFactory()
                self._llm_client = factory.get_client( self._llm_spec_key, debug=self.debug )
            except Exception as e:
                if self.debug: print( f"[PredictionEngine] Failed to load LLM client: {e}" )
        return self._llm_client

    @staticmethod
    def _cosine_similarity( vec_a, vec_b ):
        """
        Compute cosine similarity between two L2-normalized vectors.

        For L2-normalized vectors (as produced by EmbeddingProvider),
        dot product equals cosine similarity.

        Requires:
            - vec_a and vec_b are lists/arrays of equal length

        Ensures:
            - Returns float similarity score
        """
        import numpy as np
        return float( np.dot( np.array( vec_a ), np.array( vec_b ) ) )

    def _enrich_with_embedding_similarity( self, actual_dict: dict,
                                            prediction_result: 'PredictionResult',
                                            response_type: str ) -> None:
        """
        Compute embedding similarity between predicted and actual text, inject into actual_dict.

        Requires:
            - actual_dict: The normalized actual response dict (mutable)
            - prediction_result: The PredictionResult from predict()
            - response_type: RESPONSE_TYPE_OPEN_ENDED or RESPONSE_TYPE_OPEN_ENDED_BATCH

        Ensures:
            - For open_ended: injects actual_dict["_embedding_similarity"] = float
            - For open_ended_batch: injects actual_dict["_embedding_similarity"] = {"H1": float, ...}
            - Graceful degradation on any failure (no exception propagation)
            - Transient keys (prefixed with _) are stripped before DB write by record_outcome()
        """
        try:
            predicted_value = prediction_result.predicted_value
            if predicted_value is None:
                return

            if response_type == RESPONSE_TYPE_OPEN_ENDED:
                # Single text comparison
                predicted_text = predicted_value if isinstance( predicted_value, str ) else str( predicted_value )
                actual_text    = actual_dict.get( "value", "" )

                if not predicted_text or not actual_text:
                    return

                pred_emb   = self._generate_embedding( predicted_text )
                actual_emb = self._generate_embedding( actual_text )

                if pred_emb is not None and actual_emb is not None:
                    similarity = self._cosine_similarity( pred_emb, actual_emb )
                    actual_dict[ "_embedding_similarity" ] = round( similarity, 4 )

            elif response_type == RESPONSE_TYPE_OPEN_ENDED_BATCH:
                # Per-header text comparison
                pred_answers   = predicted_value.get( "answers", {} ) if isinstance( predicted_value, dict ) else {}
                actual_answers = actual_dict.get( "answers", {} )

                if not pred_answers or not actual_answers:
                    return

                header_sims = {}
                for header in actual_answers:
                    pred_text   = str( pred_answers.get( header, "" ) )
                    actual_text = str( actual_answers.get( header, "" ) )

                    if not pred_text or not actual_text:
                        continue

                    pred_emb   = self._generate_embedding( pred_text )
                    actual_emb = self._generate_embedding( actual_text )

                    if pred_emb is not None and actual_emb is not None:
                        header_sims[ header ] = round( self._cosine_similarity( pred_emb, actual_emb ), 4 )

                if header_sims:
                    actual_dict[ "_embedding_similarity" ] = header_sims

        except Exception as e:
            if self.debug: print( f"[PredictionEngine] _enrich_with_embedding_similarity error: {e}" )

    @staticmethod
    def _parse_mc_decision_value( decision_value: str ) -> Optional[dict]:
        """
        Parse a multiple_choice decision_value string into a dict.

        Requires:
            - decision_value is a string (possibly JSON)

        Ensures:
            - Returns dict with "answers" key if valid JSON with answers
            - Returns None for empty, non-JSON, or invalid formats
        """
        if not decision_value or not decision_value.strip():
            return None

        import json
        try:
            parsed = json.loads( decision_value )
            if isinstance( parsed, dict ) and "answers" in parsed:
                return parsed
            return None
        except ( json.JSONDecodeError, TypeError ):
            return None

    def record_outcome( self, notification_id: str, prediction_result: PredictionResult,
                        actual_value: Any, response_type: str ) -> None:
        """
        Record the prediction outcome to the prediction_log table.

        Requires:
            - notification_id: UUID string of the notification
            - prediction_result: The PredictionResult from predict()
            - actual_value: The actual response from the user
            - response_type: The response type string

        Ensures:
            - Writes a complete prediction_log row with prediction + outcome
            - Stores embedding in LanceDB for future CBR retrieval
            - Accuracy comparison computed and logged
            - Never raises exceptions (graceful degradation)
        """
        try:
            # Normalize actual_value to dict
            if isinstance( actual_value, str ):
                actual_dict = { "value": actual_value }
            elif isinstance( actual_value, dict ):
                actual_dict = actual_value
            else:
                actual_dict = { "value": str( actual_value ) }

            # Enrich open-ended types with embedding similarity (injects transient _embedding_similarity key)
            if response_type in ( RESPONSE_TYPE_OPEN_ENDED, RESPONSE_TYPE_OPEN_ENDED_BATCH ):
                self._enrich_with_embedding_similarity( actual_dict, prediction_result, response_type )

            # Compare prediction against actual (data-driven dispatch for multi-select MC)
            comparator = get_comparator( response_type, actual_value=actual_dict )
            predicted_dict = prediction_result._wrap_predicted_value()
            accuracy_match, accuracy_detail = comparator( predicted_dict, actual_dict )

            # Strip transient keys (prefixed with _) before DB write
            db_actual = { k: v for k, v in actual_dict.items() if not k.startswith( "_" ) }

            # Write to prediction_log
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository

            with get_db() as session:
                repo = PredictionLogRepository( session )

                repo.log_prediction(
                    notification_id       = notification_id,
                    response_type         = prediction_result.response_type,
                    category              = prediction_result.category,
                    predicted_value       = predicted_dict,
                    prediction_confidence = prediction_result.confidence,
                    prediction_strategy   = prediction_result.strategy,
                    similar_case_count    = prediction_result.similar_case_count,
                    sender_id             = None,  # Filled by caller if needed
                )

                # Update with outcome
                repo.update_outcome(
                    notification_id = notification_id,
                    actual_value    = db_actual,
                    accuracy_match  = accuracy_match,
                    accuracy_detail = accuracy_detail
                )

                session.commit()

            # Store in LanceDB for future CBR retrieval
            self._store_decision( notification_id, prediction_result, actual_value, response_type )

            if self.debug:
                print( f"[PredictionEngine] Recorded outcome: id={notification_id}, match={accuracy_match}" )

        except Exception as e:
            if self.debug: print( f"[PredictionEngine] record_outcome error: {e}" )

    def _store_decision( self, notification_id: str, prediction_result: PredictionResult,
                         actual_value: Any, response_type: str ) -> None:
        """
        Store the actual response in LanceDB for future CBR retrieval.

        Ensures:
            - Generates embedding for the original question
            - Stores decision_value as the actual response
            - Uses response_type-specific formatting
        """
        try:
            store    = self._get_embedding_store()
            provider = self._get_embedding_provider()
            if store is None or provider is None:
                return

            # Extract the storage key from metadata. For an open_ended_batch prefer
            # the content-bearing batch_question_key over the count-preamble
            # original_message — storing the preamble is what let unrelated batches
            # collide at similarity 1.0 (bug cdb5a76f). Retrieval embeds the same key.
            meta    = prediction_result.metadata or {}
            message = meta.get( "batch_question_key" ) or meta.get( "original_message", "" )
            if not message:
                return  # Can't store without the original message

            embedding = provider.generate_embedding( message, content_type="prose" )

            # Format decision_value based on response type
            import json
            if isinstance( actual_value, str ):
                # MC responses arrive as JSON strings from the browser (e.g., '{"answers":{"Commit":"Commit only"}}')
                # Try to parse and extract structured answers before falling back to _other wrapping
                if response_type == RESPONSE_TYPE_MULTIPLE_CHOICE:
                    try:
                        parsed = json.loads( actual_value )
                        if isinstance( parsed, dict ) and "answers" in parsed:
                            decision_value = json.dumps( { "answers": parsed[ "answers" ] } )
                        else:
                            decision_value = json.dumps( { "answers": { "_other": actual_value } } )
                    except ( json.JSONDecodeError, TypeError ):
                        decision_value = json.dumps( { "answers": { "_other": actual_value } } )
                else:
                    decision_value = actual_value
            elif isinstance( actual_value, dict ):
                answers = actual_value.get( "answers" )
                if answers:
                    decision_value = json.dumps( { "answers": answers } )
                else:
                    value = actual_value.get( "value", "" )
                    if value:
                        decision_value = str( value )
                    else:
                        decision_value = str( actual_value )
            else:
                decision_value = str( actual_value )

            store.add_decision(
                id                 = notification_id,
                question           = message,
                category           = prediction_result.category,
                decision_value     = decision_value,
                ratification_state = "not_required",
                question_embedding = embedding,
                created_at         = datetime.now( timezone.utc ).isoformat(),
                data_origin        = "organic",
                response_type      = response_type
            )

        except Exception as e:
            if self.debug: print( f"[PredictionEngine] _store_decision error: {e}" )

    @staticmethod
    def _decision_value_from_predicted( predicted_value ) -> str:
        """
        Serialize a hint's predicted_value to the CBR decision_value string format.

        Ensures:
            - dict with "answers" → json.dumps({"answers": ...}) (MC / batch shape)
            - dict with "value"   → str(value) (yes_no envelope shape)
            - other dict          → json.dumps(dict)
            - non-dict            → str(predicted_value) (yes/no/open-ended scalar)
        """
        import json
        if isinstance( predicted_value, dict ):
            answers = predicted_value.get( "answers" )
            if answers is not None:
                return json.dumps( { "answers": answers } )
            value = predicted_value.get( "value" )
            return str( value ) if value is not None else json.dumps( predicted_value )
        return str( predicted_value )

    def record_hint_vote( self, notification_id, question, predicted_value, category, response_type, vote ):
        """
        Record a user thumbs up/down on a prediction hint as a human-confirmed CBR case.

        up → ratification_state="approved" (reinforce that answer in future retrieval);
        down → "rejected" (the ratification-aware tally casts a NEGATIVE vote against that
        value — the engine steers away). The case is keyed deterministically on the
        notification id so a re-vote flips its state IN PLACE (idempotent) instead of
        duplicating; first vote inserts via the proven add_decision path.

        Requires:
            - notification_id, question non-empty; vote in {"up","down"}
            - predicted_value is the hint's predicted value (str or {"answers": {...}})

        Ensures:
            - writes/updates exactly one organic case; returns
              {case_id, ratification_state, updated}

        Raises:
            - ValueError if vote is not "up"/"down"
            - RuntimeError if the embedding store/provider is unavailable
        """
        if vote not in ( "up", "down" ):
            raise ValueError( f"vote must be 'up' or 'down', got {vote!r}" )

        store    = self._get_embedding_store()
        provider = self._get_embedding_provider()
        if store is None or provider is None:
            raise RuntimeError( "embedding store/provider unavailable — cannot record hint vote" )

        ratification_state = "approved" if vote == "up" else "rejected"
        case_id            = f"hintvote-{notification_id}"

        # Re-vote: flip the existing case's state in place (idempotent). First vote: insert.
        #
        # This is a CHECK-THEN-ACT: exists() → (update | add). Now that callers
        # offload record_hint_vote via asyncio.to_thread, two concurrent votes
        # could both see exists()==False and both insert → a duplicate/clobbered
        # case. Hold the store's shared re-entrant write-lock ACROSS the whole
        # exists()→write compound to make it atomic; the nested
        # update_ratification_state/add_decision re-acquire the same RLock cleanly.
        with store._write_lock:
            if store.exists( case_id ):
                store.update_ratification_state( case_id, ratification_state )
                return { "case_id": case_id, "ratification_state": ratification_state, "updated": True }

            decision_value = self._decision_value_from_predicted( predicted_value )
            embedding      = provider.generate_embedding( question, content_type="prose" )
            store.add_decision(
                id                 = case_id,
                question           = question,
                category           = category or "general",
                decision_value     = decision_value,
                ratification_state = ratification_state,
                question_embedding = embedding,
                created_at         = datetime.now( timezone.utc ).isoformat(),
                data_origin        = "organic",
                response_type      = response_type or ""
            )
            return { "case_id": case_id, "ratification_state": ratification_state, "updated": False }

    def get_accuracy_summary( self, window_days: int = 30, category: Optional[str] = None,
                              response_type: Optional[str] = None ) -> Dict[str, Any]:
        """
        Get accuracy statistics from the prediction_log table.

        Requires:
            - window_days: Number of days to look back

        Ensures:
            - Returns dict with accuracy metrics
            - Safe to call even if no predictions exist
        """
        try:
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository

            with get_db() as session:
                repo = PredictionLogRepository( session )
                return repo.get_accuracy_summary(
                    window_days   = window_days,
                    category      = category,
                    response_type = response_type
                )
        except Exception as e:
            if self.debug: print( f"[PredictionEngine] get_accuracy_summary error: {e}" )
            return {
                "window_days"       : window_days,
                "total_predictions" : 0,
                "total_responded"   : 0,
                "accuracy_rate"     : 0.0,
                "error"             : str( e )
            }

    def _generate_embedding( self, text: str ) -> Optional[list]:
        """
        Generate embedding vector for a text string.

        Tries local EmbeddingProvider first (works inside server process),
        then falls back to HTTP call to /api/embeddings/generate (works
        from any external process without loading a second GPU model).

        Requires:
            - text is a non-empty string

        Ensures:
            - Returns list of floats (768-dim) or None on failure
            - Tries local provider first, then HTTP fallback
        """
        if not text or not text.strip():
            return None

        # Strategy 1: Local EmbeddingProvider (in-process GPU)
        provider = self._get_embedding_provider()
        if provider is not None:
            try:
                embedding = provider.generate_embedding( text, content_type="prose" )
                if embedding is not None:
                    return embedding
            except Exception as e:
                if self.debug: print( f"[PredictionEngine] Local embedding failed, trying HTTP fallback: {e}" )

        # Strategy 2: HTTP fallback to server's embedding endpoint
        if self.debug: print( "[PredictionEngine] Using HTTP embedding fallback" )
        return self._generate_embedding_via_http( text )

    def _generate_embedding_via_http( self, text: str ) -> Optional[list]:
        """
        Generate embedding via HTTP call to the FastAPI embeddings endpoint.

        Used as fallback when local GPU loading fails (e.g., CUDA OOM from
        external process while server already occupies the GPU).

        Requires:
            - text is a non-empty string
            - FastAPI server running on self._server_port
            - API key file exists at src/conf/keys/notification-api-claude-code-dev

        Ensures:
            - Returns list of floats (768-dim) or None on failure
            - Uses X-API-Key auth (require_api_key_or_jwt on embeddings endpoint)
        """
        import requests

        api_key = cu.get_api_key( "notification-api-claude-code-dev" )
        if not api_key:
            if self.debug: print( "[PredictionEngine] HTTP fallback: no API key found" )
            return None

        try:
            response = requests.post(
                f"http://localhost:{self._server_port}/api/embeddings/generate",
                json    = { "text": text, "content_type": "prose" },
                headers = { "X-API-Key": api_key },
                timeout = 10
            )
            if response.status_code == 200:
                return response.json()[ "embedding" ]
            else:
                if self.debug: print( f"[PredictionEngine] HTTP fallback returned {response.status_code}: {response.text}" )
        except Exception as e:
            if self.debug: print( f"[PredictionEngine] HTTP embedding fallback failed: {e}" )

        return None

    @classmethod
    def reset( cls ):
        """
        Reset the singleton instance (for testing only).

        Ensures:
            - Next call to PredictionEngine() creates a fresh instance
        """
        with cls._lock:
            cls._instance = None


def get_prediction_engine( config_mgr=None, debug=False ) -> PredictionEngine:
    """
    Convenience function to get the PredictionEngine singleton.

    Requires:
        - config_mgr: ConfigurationManager (only needed for first call)

    Ensures:
        - Returns the singleton PredictionEngine instance
        - Thread-safe initialization
    """
    return PredictionEngine( config_mgr=config_mgr, debug=debug )


# Register PredictionEngine.reset as the invalidator for /api/init hot-reload.
# Mirrors the existing reset semantics (drop singleton, next call rebuilds).
from cosa.config.cache_registry import register_invalidator as _register_invalidator
_register_invalidator( "prediction_engine", PredictionEngine.reset )


def quick_smoke_test():
    """Quick smoke test for PredictionEngine."""
    import cosa.utils.util as du

    du.print_banner( "PredictionEngine Smoke Test", prepend_nl=True )

    try:
        # Reset any existing singleton
        PredictionEngine.reset()

        # Test 1: Singleton creation
        print( "Testing singleton creation..." )
        engine1 = PredictionEngine( debug=True )
        engine2 = PredictionEngine( debug=True )
        assert engine1 is engine2, "Singleton pattern broken"
        print( "✓ Singleton pattern works" )

        # Test 2: Cold start prediction (no embedding store)
        print( "Testing cold start prediction..." )
        result = engine1.predict( {
            "message"       : "Should I proceed with the deployment?",
            "response_type" : "yes_no",
            "sender_id"     : "test@lupin.deepily.ai"
        } )
        assert result.response_type == "yes_no"
        assert result.category in [ "permission", "workflow", "uncategorized" ]
        assert result.strategy in [ STRATEGY_COLD_START, STRATEGY_CBR_MAJORITY ]
        print( f"✓ Cold start prediction: category={result.category}, strategy={result.strategy}" )

        # Test 3: Multiple choice returns prediction (cold_start or cbr)
        print( "Testing multiple_choice dispatch..." )
        result = engine1.predict( {
            "message"       : "Pick a database",
            "response_type" : "multiple_choice",
            "sender_id"     : "test@lupin.deepily.ai"
        } )
        assert result.response_type == "multiple_choice"
        assert result.strategy in [ STRATEGY_COLD_START, STRATEGY_CBR_MAJORITY ]
        print( f"✓ Multiple choice dispatch: strategy={result.strategy}" )

        # Test 4: Disabled engine
        print( "Testing disabled engine..." )
        engine1.enabled = False
        result = engine1.predict( {
            "message"       : "Should I proceed?",
            "response_type" : "yes_no"
        } )
        assert result.strategy == STRATEGY_COLD_START
        assert result.metadata.get( "reason" ) == "engine_disabled"
        engine1.enabled = True
        print( "✓ Disabled engine returns cold start with reason" )

        # Test 5: Convenience function
        print( "Testing get_prediction_engine()..." )
        engine3 = get_prediction_engine()
        assert engine3 is engine1
        print( "✓ get_prediction_engine() returns same singleton" )

        # Test 6: PredictionResult with qualifier populates hint_dict
        print( "Testing PredictionResult qualifier in hint_dict..." )
        qualified_result = PredictionResult(
            response_type       = RESPONSE_TYPE_YES_NO,
            category            = "permission",
            strategy            = STRATEGY_CBR_MAJORITY,
            predicted_value     = "yes",
            confidence          = 0.9,
            similar_case_count  = 3,
            predicted_qualifier = "only the old files"
        )
        hint = qualified_result.to_hint_dict()
        assert hint[ "predicted_qualifier" ] == "only the old files"
        print( "✓ Qualifier appears in hint_dict" )

        # Test 7: HTTP embedding fallback
        print( "Testing HTTP embedding fallback..." )
        embedding = engine1._generate_embedding_via_http( "Should I proceed with the deployment?" )
        if embedding is not None:
            assert isinstance( embedding, list ), "HTTP embedding should return a list"
            assert len( embedding ) == 768, f"Expected 768-dim vector, got {len( embedding )}"
            print( f"✓ HTTP embedding fallback works (768-dim vector returned)" )
        else:
            print( "⚠ HTTP embedding fallback unavailable (server not running or no API key)" )

        # Test 8: Open-ended dispatch (cold start — no embedding store)
        print( "Testing open_ended dispatch..." )
        result = engine1.predict( {
            "message"       : "What naming convention should I use?",
            "response_type" : "open_ended",
            "sender_id"     : "test@lupin.deepily.ai"
        } )
        assert result.response_type == "open_ended"
        assert result.strategy in [ STRATEGY_COLD_START, STRATEGY_CBR_RETRIEVAL, STRATEGY_LLM_SYNTHESIS ]
        print( f"✓ Open-ended dispatch: strategy={result.strategy}" )

        # Test 9: Open-ended batch dispatch (cold start)
        print( "Testing open_ended_batch dispatch..." )
        result = engine1.predict( {
            "message"       : "Provide project details",
            "response_type" : "open_ended_batch",
            "sender_id"     : "test@lupin.deepily.ai"
        } )
        assert result.response_type == "open_ended_batch"
        assert result.strategy in [ STRATEGY_COLD_START, STRATEGY_CBR_RETRIEVAL, STRATEGY_LLM_SYNTHESIS ]
        print( f"✓ Open-ended batch dispatch: strategy={result.strategy}" )

        # Cleanup
        PredictionEngine.reset()

        print( "\n✓ All PredictionEngine smoke tests passed!" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        du.print_stack_trace( e, caller="prediction_engine.quick_smoke_test()" )
        PredictionEngine.reset()


if __name__ == "__main__":
    quick_smoke_test()
