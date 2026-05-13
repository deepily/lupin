"""
Pydantic XML models for the inter-session commons persona disambiguator
(PHI-4 + future Haiku fallback).

Per §8 (PHI-4 Prompt Envelope) of
`src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md`.

**Pydantic-native validation** per `feedback_pydantic_native_validation`:
- Field constraints declared on `Field(min_length=, max_length=, ge=, le=)`
- T2 sanitize-at-boundary via `@field_validator(mode="before")` —
  rejects control chars + XML-escapes `<` `>` `&` BEFORE the value reaches
  the model (per `feedback_sanitize_at_boundary_not_format_strip`).
- 422 / ValidationError at the substitution boundary; downstream code
  doesn't need to re-validate.

**Two models**:
- `PersonaDisambiguationRequest` — outbound envelope. Serializes via
  `to_xml()` to the PHI-4-friendly nested-persona shape:
      <commons_persona_disambiguation>
        <active_personas>
          <persona><name>...</name><icon>...</icon></persona>
          ...
        </active_personas>
        <ambiguous_reference>...</ambiguous_reference>
        <context>... (optional)</context>
      </commons_persona_disambiguation>

- `PersonaDisambiguationResponse` — inbound envelope. `matched_persona`
  may be None on explicit no-match; `confidence` Pydantic-constrained to
  [0.0, 1.0]. Whitelist enforcement (`matched_persona ∈ active_personas`)
  lives in the disambiguator caller, not on the model — runtime
  active_personas state isn't visible to the model.
"""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel


# Field bounds — single source of truth for both the design doc + tests
_MIN_REFERENCE_LEN = 1
_MAX_REFERENCE_LEN = 256
_MAX_CONTEXT_LEN   = 2048
_MIN_PERSONA_NAME  = 1
_MAX_PERSONA_NAME  = 64
_MIN_PERSONA_ICON  = 1
_MAX_PERSONA_ICON  = 8


def _xml_escape( value: str ) -> str:
    """
    Escape XML special chars in the order that prevents double-escape.

    Requires:
        - value is a string

    Ensures:
        - returns a string with `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`
        - ampersand replaced FIRST so `&lt;` etc. don't become `&amp;lt;`
    """
    return value.replace( "&", "&amp;" ).replace( "<", "&lt;" ).replace( ">", "&gt;" )


def _t2_sanitize( value: Optional[ str ] ) -> Optional[ str ]:
    """
    T2 sanitize-at-boundary helper used by `@field_validator(mode='before')`.

    Requires:
        - value is None, OR a string

    Ensures:
        - returns None if value is None (Optional fields)
        - raises ValueError if value contains control chars (other than \\n, \\t)
        - otherwise returns the value with `&` `<` `>` XML-escaped
    """
    if value is None: return None
    if any( ord( c ) < 32 and c not in "\n\t" for c in value ):
        raise ValueError( "control characters not allowed in disambiguator input" )
    return _xml_escape( value )


class PersonaInfo( BaseModel ):
    """
    One persona entry in the `active_personas` list.

    Requires:
        - name is a non-empty string ≤ 64 chars
        - icon is a non-empty string ≤ 8 chars (emoji length includes ZWJ + skin tone)

    Persona names + icons come from server-side config (`voice_persona`
    INI block), NOT from user input. T2 sanitization is therefore not
    applied here — only on the user-controlled `ambiguous_reference` +
    `context` fields on `PersonaDisambiguationRequest`.
    """
    model_config = ConfigDict( extra="ignore" )

    name: str = Field( ..., min_length=_MIN_PERSONA_NAME, max_length=_MAX_PERSONA_NAME )
    icon: str = Field( ..., min_length=_MIN_PERSONA_ICON, max_length=_MAX_PERSONA_ICON )


class PersonaDisambiguationRequest( BaseXMLModel ):
    """
    Outbound request envelope for PHI-4 persona disambiguation.

    Requires (Pydantic-enforced at instantiation):
        - active_personas is a non-empty list of PersonaInfo
        - ambiguous_reference is a non-empty string ≤ 256 chars
        - context is None OR a string ≤ 2048 chars
        - ambiguous_reference + context pass T2 sanitization
          (control chars → ValueError; `<` `>` `&` → XML-escaped)

    Ensures:
        - `to_xml()` produces the nested-persona shape expected by PHI-4
        - context block omitted entirely when context is None
    """

    active_personas     : List[ PersonaInfo ]
    ambiguous_reference : str           = Field( ..., min_length=_MIN_REFERENCE_LEN, max_length=_MAX_REFERENCE_LEN )
    context             : Optional[ str ] = Field( default=None, max_length=_MAX_CONTEXT_LEN )

    @field_validator( "ambiguous_reference", "context", mode="before" )
    @classmethod
    def _sanitize_text_fields( cls, value ):
        """T2 sanitize-at-boundary: reject control chars; XML-escape `<` `>` `&`."""
        return _t2_sanitize( value )

    def to_xml( self, root_tag: str = "commons_persona_disambiguation", pretty: bool = False ) -> str:
        """
        Serialize to the PHI-4-friendly nested-persona XML shape.

        Overrides `BaseXMLModel.to_xml()`. The base implementation uses
        `xmltodict.unparse(model_dump())` which produces the WRONG shape
        for `List[PersonaInfo]` (repeated `<active_personas>` tags rather
        than the nested `<persona>` wrapper PHI-4 expects).

        Returns:
            XML string with `active_personas` wrapping per-persona blocks.
        """
        persona_blocks = "".join(
            f"<persona><name>{_xml_escape( p.name )}</name><icon>{_xml_escape( p.icon )}</icon></persona>"
            for p in self.active_personas
        )
        body  = f"<active_personas>{persona_blocks}</active_personas>"
        # ambiguous_reference + context are ALREADY XML-escaped by the validator,
        # so we DON'T re-escape them here (would produce `&amp;lt;`).
        body += f"<ambiguous_reference>{self.ambiguous_reference}</ambiguous_reference>"
        if self.context is not None:
            body += f"<context>{self.context}</context>"
        return f"<{root_tag}>{body}</{root_tag}>"


class PersonaDisambiguationResponse( BaseXMLModel ):
    """
    Inbound response from PHI-4 persona disambiguation.

    Requires (Pydantic-enforced on `from_xml()` or direct construction):
        - matched_persona is None OR a non-empty string ≤ 64 chars
        - confidence is a float in [0.0, 1.0]

    Ensures:
        - empty `<matched_persona/>` tag → matched_persona == None
        - empty-string `<matched_persona></matched_persona>` → None
        - confidence out-of-range raises ValidationError before
          disambiguator-caller logic acts on it

    Note: the output-whitelist check (`matched_persona ∈ active_personas`)
    lives in the disambiguator caller, NOT on the model — runtime
    active_personas state isn't visible to the model.
    """

    matched_persona : Optional[ str ] = Field( default=None, max_length=_MAX_PERSONA_NAME )
    confidence      : float           = Field( ..., ge=0.0, le=1.0 )

    @field_validator( "matched_persona", mode="before" )
    @classmethod
    def _coerce_empty_to_none( cls, value ):
        """
        xmltodict returns None for empty self-closing tags `<matched_persona/>`
        AND empty-content tags `<matched_persona></matched_persona>`. Both
        cases are valid "no-match" signals — coerce to None for the model.
        """
        if value is None: return None
        if isinstance( value, str ) and value.strip() == "": return None
        return value
