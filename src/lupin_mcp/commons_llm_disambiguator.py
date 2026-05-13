"""
LLM-backed persona disambiguator for the inter-session commons.

Per Phase 3 §1 Item B + §8 of
`src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md`.

**Two-tier path (Q5 ratified)**:
1. **Primary**: local PHI-4 via `LlmClientFactory.get_client(spec_key)` —
   zero per-call API cost; ~1s typical latency.
2. **Fallback (stubbed)**: Haiku 4.5 — `_fallback_via_haiku()` raises
   `NotImplementedError` and is caught by the caller → returns None.
   The function EXISTS for future swap-in; wired-but-stubbed per AC7.

**Pydantic-native validation** per `feedback_pydantic_native_validation`:
- Request construction does the T2 sanitize-at-boundary work (control char
  rejection + XML escape) via `PersonaDisambiguationRequest`'s validator.
- Response Pydantic-constrains `confidence` to `[0.0, 1.0]`; out-of-range
  raises ValidationError before the disambiguator logic sees it.

**T2 whitelist** (output validation): `matched_persona` must be in the
runtime `active_personas` list — enforced HERE in the disambiguator (the
Pydantic model can't see runtime state). Returns None on whitelist miss.

**T7 decision audit log**: when `commons llm disambiguator log decisions =
True`, emits a per-decision `print()` record with sanitized inputs +
outputs, for empirical confidence-floor tuning. INI-toggleable for prod
cost-management.

**Templated after** `cosa/agents/notification_proxy/strategies/llm_script_matcher.py`
(F10 — the structurally closest LLM-call-with-XML-response pattern).
"""

from typing import List, Optional

from pydantic import ValidationError

from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError
from cosa.agents.llm_client_factory import LlmClientFactory
from lupin_mcp.commons_xml_models import (
    PersonaDisambiguationRequest,
    PersonaDisambiguationResponse,
    PersonaInfo,
)


# Config keys — single source of truth (mirror INI key spellings)
_KEY_SPEC                = "llm spec key for commons persona disambiguator"
_KEY_FALLBACK_MODEL      = "commons llm disambiguator fallback model name"
_KEY_TIMEOUT             = "commons llm disambiguator timeout seconds"
_KEY_CONFIDENCE_FLOOR    = "commons llm disambiguator confidence floor"
_KEY_LOG_DECISIONS       = "commons llm disambiguator log decisions"

_DEFAULT_CONFIDENCE_FLOOR = 0.7
_DEFAULT_TIMEOUT_SECONDS  = 5.0


# Static system prompt — frames the task for the LLM. Subject to Pass 2
# Adversarial walk tuning when production telemetry surfaces edge cases.
_SYSTEM_PROMPT = (
    "You are a persona disambiguator. You will receive a "
    "<commons_persona_disambiguation> XML block listing active personas, "
    "an ambiguous reference, and optional context. Return ONLY a "
    "<persona_disambiguation_response> XML block with <matched_persona> "
    "(the canonical name from active_personas, or empty for no-match) "
    "and <confidence> (0.0-1.0). Do not explain your reasoning. Do not "
    "return any other text."
)


class CommonsLlmDisambiguator:
    """
    LLM-backed persona disambiguator.

    Requires:
        - `config_mgr` is a ConfigurationManager exposing `.get(key, default=None)`
          for the 5 INI keys above
        - PHI-4 (or the configured spec key) is reachable via LlmClientFactory

    Ensures:
        - `disambiguate(active_personas, ambiguous_reference, context=None)`
          returns the canonical persona name from `active_personas`, OR None
          on no-match / whitelist-miss / confidence-below-floor / parse-error
          / input validation error / fallback NotImplementedError.
        - NEVER raises publicly. Internal errors caught, debug-logged, return None.
    """

    def __init__(
        self,
        config_mgr,
        debug   : bool = False,
        verbose : bool = False,
    ):
        self.config_mgr = config_mgr
        self.debug      = debug
        self.verbose    = verbose

        self.llm_spec_key      = config_mgr.get( _KEY_SPEC )
        self.confidence_floor  = float( config_mgr.get( _KEY_CONFIDENCE_FLOOR, default=_DEFAULT_CONFIDENCE_FLOOR ) )
        self.timeout_seconds   = float( config_mgr.get( _KEY_TIMEOUT,          default=_DEFAULT_TIMEOUT_SECONDS ) )
        self.log_decisions     = bool(  config_mgr.get( _KEY_LOG_DECISIONS,    default=False ) )

        self._llm_factory = LlmClientFactory( debug=debug, verbose=verbose )
        self._client      = None  # Lazy — constructed on first call

    # ─── Public API ─────────────────────────────────────────────────────────

    def disambiguate(
        self,
        active_personas     : List[ PersonaInfo ],
        ambiguous_reference : str,
        context             : Optional[ str ] = None,
    ) -> Optional[ str ]:
        """
        Resolve an ambiguous persona reference against `active_personas`.

        Requires:
            - `active_personas` is a non-empty list of PersonaInfo
            - `ambiguous_reference` is a non-empty string ≤ 256 chars
              (Pydantic-enforced at PersonaDisambiguationRequest construction)
            - `context` is None or a string ≤ 2048 chars

        Ensures:
            - Returns the canonical persona name (from active_personas) on
              high-confidence match.
            - Returns None on: input ValidationError, LLM error, parse error,
              fallback NotImplementedError, output-whitelist miss, or
              confidence < INI floor.
            - Emits T7 decision audit log when `log_decisions` is True.

        Raises:
            - None publicly.
        """
        # 1. Build + validate request (T2 sanitize-at-boundary)
        try:
            request = PersonaDisambiguationRequest(
                active_personas     = active_personas,
                ambiguous_reference = ambiguous_reference,
                context             = context,
            )
        except ValidationError as e:
            if self.debug: print( f"[commons_llm_disambiguator] input ValidationError: {e!r} → None" )
            return None

        request_xml = request.to_xml()
        prompt      = f"{_SYSTEM_PROMPT}\n\n{request_xml}"

        # 2. Invoke PHI-4 (lazy client construction)
        try:
            client       = self._get_client()
            response_xml = client.run( prompt )
            response     = PersonaDisambiguationResponse.from_xml( response_xml )
        except ( TimeoutError, XMLParsingError, ValidationError, ValueError ) as e:
            if self.debug: print( f"[commons_llm_disambiguator] PHI-4 failed: {e!r} — routing to Haiku fallback" )
            # AC7: fallback is wired-but-stubbed — raises NotImplementedError; we catch + return None
            try:
                return self._fallback_via_haiku( active_personas, ambiguous_reference, context )
            except NotImplementedError as nie:
                if self.debug: print( f"[commons_llm_disambiguator] Haiku fallback stubbed: {nie!r} → None" )
                return None

        # 3. T2 whitelist: matched_persona must be in active_personas (canonical names)
        matched = response.matched_persona
        if matched is not None:
            canonical_names = { p.name for p in active_personas }
            if matched not in canonical_names:
                self._maybe_log_decision( ambiguous_reference, active_personas, matched, response.confidence, "whitelist-miss" )
                return None

        # 4. Confidence floor (F5-fit)
        if response.confidence < self.confidence_floor:
            self._maybe_log_decision( ambiguous_reference, active_personas, matched, response.confidence, "below-floor" )
            return None

        # 5. T7 audit log on the successful return path
        self._maybe_log_decision( ambiguous_reference, active_personas, matched, response.confidence, "accepted" )
        return matched

    # ─── Stubbed Haiku fallback (AC7 — wired-but-stubbed per Q5) ────────────

    def _fallback_via_haiku(
        self,
        active_personas     : List[ PersonaInfo ],
        ambiguous_reference : str,
        context             : Optional[ str ] = None,
    ) -> Optional[ str ]:
        """
        Stubbed Haiku 4.5 fallback (Q5 wired-but-stubbed). To be implemented
        in a future phase if PHI-4 telemetry shows insufficient precision.

        Raises:
            - NotImplementedError, always.
        """
        raise NotImplementedError(
            "Haiku fallback stubbed for future phase — see Phase 3 §1 Item B / Q5 ratification"
        )

    # ─── Internal helpers ───────────────────────────────────────────────────

    def _get_client( self ):
        """Lazy LLM-client construction so unit tests can replace it via mocking."""
        if self._client is None:
            self._client = self._llm_factory.get_client(
                self.llm_spec_key,
                debug   = self.debug,
                verbose = self.verbose,
            )
        return self._client

    def _maybe_log_decision(
        self,
        ambiguous_reference : str,
        active_personas     : List[ PersonaInfo ],
        matched             : Optional[ str ],
        confidence          : float,
        outcome             : str,
    ) -> None:
        """
        T7 decision audit log. Fires only when `log_decisions` is True.

        Per AC6 — sanitized `ambiguous_reference` is already escaped at the
        Pydantic-validator level; we just log the field.
        """
        if not self.log_decisions: return
        print(
            f"[commons_llm_disambiguator] decision outcome={outcome} "
            f"matched={matched!r} confidence={confidence:.3f} "
            f"active_count={len( active_personas )} "
            f"reference={ambiguous_reference!r}"
        )
