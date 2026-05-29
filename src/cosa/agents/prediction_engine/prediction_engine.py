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
        """Lazy-load the LanceDB embedding store."""
        if self._embedding_store is None:
            try:
                from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings

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

        # Generate embedding for the message
        embedding = self._generate_embedding( message )

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
                return self._predict_open_ended_batch( message, category, embedding )

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

        # Majority vote
        votes = {}
        max_similarity = 0.0

        for similarity_pct, record in similar_cases:
            decision_value = record.get( "decision_value", "" )
            # Extract binary from potential qualified value
            binary_value = "yes" if decision_value.lower().startswith( "yes" ) else "no"
            votes[ binary_value ] = votes.get( binary_value, 0 ) + 1
            max_similarity = max( max_similarity, similarity_pct / 100.0 )

        # Winner and consistency
        total_votes = sum( votes.values() )
        winner      = max( votes, key=votes.get )
        consistency = votes[ winner ] / total_votes if total_votes > 0 else 0.0

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
        # header_votes: { "Header": { "OptionA": count, "OptionB": count } }
        header_votes    = {}
        max_similarity  = 0.0
        valid_cases     = 0
        is_multi_select = False

        for similarity_pct, record in similar_cases:
            decision_value = record.get( "decision_value", "" )
            parsed         = self._parse_mc_decision_value( decision_value )
            if parsed is None:
                continue

            valid_cases += 1
            max_similarity = max( max_similarity, similarity_pct / 100.0 )

            answers = parsed.get( "answers", {} )
            for header, option in answers.items():
                if header not in header_votes:
                    header_votes[ header ] = {}

                if isinstance( option, list ):
                    # Multi-select: count each individual option
                    is_multi_select = True
                    for item in option:
                        header_votes[ header ][ item ] = header_votes[ header ].get( item, 0 ) + 1
                else:
                    # Single-select: count the option directly
                    header_votes[ header ][ option ] = header_votes[ header ].get( option, 0 ) + 1

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
            predicted_answers, avg_consistency = self._tally_multi_select_votes( header_votes, valid_cases )
        else:
            predicted_answers  = {}
            consistency_sum    = 0.0
            header_count       = 0

            for header, option_votes in header_votes.items():
                winner       = max( option_votes, key=option_votes.get )
                total_votes  = sum( option_votes.values() )
                consistency  = option_votes[ winner ] / total_votes if total_votes > 0 else 0.0
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

    def _tally_multi_select_votes( self, header_option_counts: Dict[str, Dict[str, int]],
                                      valid_cases: int ) -> tuple:
        """
        Tally multi-select votes: select options chosen by >= 50% of cases.

        Requires:
            - header_option_counts: { "Header": { "OptionA": count, "OptionB": count } }
            - valid_cases: int, total number of valid cases (> 0)

        Ensures:
            - Returns ( predicted_answers, avg_consistency ) tuple
            - predicted_answers: { "Header": ["OptionA", "OptionB"] } (list values)
            - Options included if count / valid_cases >= 0.5
            - At least one option per header (highest count as fallback)
            - avg_consistency based on mean inclusion rate of selected options
        """
        predicted_answers = {}
        consistency_sum   = 0.0
        header_count      = 0

        for header, option_counts in header_option_counts.items():
            threshold = valid_cases * 0.5
            selected  = [ opt for opt, count in option_counts.items() if count >= threshold ]

            # Fallback: if no option meets threshold, pick the highest-count option
            if not selected:
                best_option = max( option_counts, key=option_counts.get )
                selected    = [ best_option ]

            # Consistency = mean inclusion rate of selected options
            inclusion_rates = [ option_counts[ opt ] / valid_cases for opt in selected ]
            consistency     = sum( inclusion_rates ) / len( inclusion_rates ) if inclusion_rates else 0.0

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

        max_similarity = similar_cases[ 0 ][ 0 ] / 100.0
        top_case       = similar_cases[ 0 ][ 1 ]

        # Tier 1 — Exact match check (normalized)
        top_question = top_case.get( "question", "" )
        if top_question.strip().lower() == message.strip().lower():
            decision_value = top_case.get( "decision_value", "" )

            if self.debug:
                print( f"[PredictionEngine] OE exact match: q='{top_question[:60]}', answer='{decision_value[:60]}'" )

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

        # Format cases as numbered XML blocks
        case_lines = []
        for i, ( similarity_pct, record ) in enumerate( similar_cases, 1 ):
            question       = record.get( "question", "" )
            decision_value = record.get( "decision_value", "" )
            sim_score      = round( similarity_pct / 100.0, 2 )
            case_lines.append(
                f'<case n="{i}" similarity="{sim_score}">\n'
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

        max_similarity = similar_cases[ 0 ][ 0 ] / 100.0
        top_case       = similar_cases[ 0 ][ 1 ]

        # Tier 1 — Exact match check (normalized)
        top_question = top_case.get( "question", "" )
        if top_question.strip().lower() == message.strip().lower():
            decision_value = top_case.get( "decision_value", "" )

            # Parse JSON to get dict with answers
            predicted = self._parse_batch_decision_value( decision_value )

            if self.debug:
                print( f"[PredictionEngine] OEB exact match: q='{top_question[:60]}'" )

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
                from cosa.agents.llm_client import LlmClientFactory
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

            # Extract the message from metadata if available
            message = prediction_result.metadata.get( "original_message", "" ) if prediction_result.metadata else ""
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
