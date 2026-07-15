"""
Vertex spend-ceiling arithmetic: convert a DOLLAR budget into a RATE clamp.

WHY THIS MODULE EXISTS — the cascade's own law, wearing a finance hat:

    A DOLLAR CAP CAN NEVER BE TIGHT, BECAUSE THE DOLLAR ORACLE LAGS.

A GCP budget is an EMAIL, not a brake: it does not enforce, spend sails past
100%, there is no daily budget period (`--calendar-period` is month|quarter|year
only), and billing export arrives HOURS late. By the time "$50 today" fires, it
is already spent.

Cloud Quotas is the only INSTANT brake — enforced at the API layer, per minute,
returning 429. So ENFORCEMENT is RATE-based and DOLLARS are the ALERTING layer
on top. This module is the bridge between the two: it turns "$50/day" into a
tokens-per-minute number you can actually clamp.

=== THE THREE FACTS THE ARITHMETIC RESTS ON (each one falsifiable) ===

1. Anthropic/Claude traffic on Vertex is governed by SHARED MODEL LINEAGE
   quotas, keyed on the `base_model` dimension (e.g. `anthropic-claude-opus`),
   scoped per endpoint. This is NOT the `Openapi*` quota family — that family
   governs the MaaS models (deepseek / gpt-oss) and would not throttle one
   token of Opus spend. A clamp on the wrong family is a brake bolted to the
   wrong axle.

2. The quota is expressed in QPM (queries/min) and TPM (tokens/min), and
   **TPM COUNTS INPUT AND OUTPUT TOGETHER** — one combined bucket.

3. Input and output are billed at DIFFERENT rates (Opus 4.8: $5 vs $25/MTok).

=== THE CONSEQUENCE — AND IT IS THE WHOLE DESIGN ===

Because one combined TPM bucket meters two differently-priced token streams,
the dollar value of a token depends on a MIX we do not know and cannot control.
Picking a mix ratio to make the arithmetic prettier would be inventing a number
- the same sin as inventing a price.

So the clamp is computed at the OUTPUT (most expensive) rate. That is the ONLY
mix-independent guarantee: it bounds spend from above under EVERY possible mix,
including the adversarial 100%-output one. On a realistic input-heavy agentic
mix the true spend lands well BELOW the cap — the clamp under-permits rather
than over-permits, and it errs in the direction that cannot hurt you.

=== WHAT THIS MODULE REFUSES TO DO ===

It will not price a model whose per-token price is not published by a primary
source. An unpriced model cannot be clamped to a dollar figure, and saying so
is a FINDING, not a failure. `clamp_tpm_for_daily_budget` raises on UNPRICED
rather than substituting a plausible-looking guess.
"""

from dataclasses import dataclass
from typing      import Optional

# The longest month. Using 30 would UNDER-estimate the daily rate a 31-day
# month can sustain, which is the one direction a spend ceiling must never err.
DAYS_PER_MONTH_WORST_CASE = 31
MINUTES_PER_DAY           = 1440


@dataclass( frozen=True )
class ModelPrice:
    """
    A per-million-token price with its provenance attached.

    `usd_per_mtok_output is None` means NO PRIMARY SOURCE PUBLISHES A PRICE.
    That is a recorded fact, not a placeholder to be filled in later with a
    number that looks about right.
    """
    model_id             : str
    usd_per_mtok_input   : Optional[ float ]
    usd_per_mtok_output  : Optional[ float ]
    source_url           : str
    source_note          : str

    @property
    def is_priced( self ):
        """Ensures: True iff BOTH directions carry a primary-sourced price."""
        return self.usd_per_mtok_input is not None and self.usd_per_mtok_output is not None


# ---------------------------------------------------------------------------
# PRICES — PRIMARY SOURCES ONLY. Every number below is quoted, not inferred.
# ---------------------------------------------------------------------------

# Anthropic's own published list price. Verbatim from the model-pricing table:
#   "Claude Opus 4.8 | $5 / MTok | ... | $25 / MTok"
# Same page, on partner-operated clouds:
#   "Regional and multi-region endpoints include a 10% premium over global
#    endpoints."
# Opus 4.8 is servable ONLY at `global` (rawPredict 400s in us-central1), so the
# 10% premium DOES NOT APPLY to us — global is both the only servable endpoint
# and the cheapest one.
CLAUDE_OPUS_4_8 = ModelPrice(
    model_id            = "claude-opus-4-8",
    usd_per_mtok_input  = 5.00,
    usd_per_mtok_output = 25.00,
    source_url          = "https://platform.claude.com/docs/en/about-claude/pricing",
    source_note         = (
        "Anthropic published list price, fetched verbatim 2026-07-14. Google Cloud is "
        "PARTNER-OPERATED and is the biller of record; the same page states partner "
        "platforms have independent pricing and points to Google for official rates. "
        "Google does not publish a machine-readable Claude rate that our instruments "
        "can read. The authoritative figure Google will actually BILL is the Cloud "
        "Billing Catalog SKU (cloudbilling.googleapis.com services/{id}/skus) — a READ, "
        "pending GCP re-auth. Treat $5/$25 as the best-sourced estimate until the SKU "
        "read confirms it."
    ),
)

# NO PRIMARY SOURCE FOUND. Google's Vertex/Agent-Platform pricing page lists ONLY
# Google's own models; the MaaS partner rates are not published there. Every
# figure found in the wild came from third-party aggregators, and THEY DISAGREE
# WITH EACH OTHER. An unpriced model cannot be clamped to a dollar figure.
DEEPSEEK_V3_2_MAAS = ModelPrice(
    model_id            = "deepseek-ai/deepseek-v3.2-maas",
    usd_per_mtok_input  = None,
    usd_per_mtok_output = None,
    source_url          = "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing",
    source_note         = "NOT LISTED on Google's pricing page (Google models only). Aggregators disagree. UNPRICED.",
)

GPT_OSS_120B_MAAS = ModelPrice(
    model_id            = "openai/gpt-oss-120b-maas",
    usd_per_mtok_input  = None,
    usd_per_mtok_output = None,
    source_url          = "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing",
    source_note         = "NOT LISTED on Google's pricing page (Google models only). Aggregators disagree. UNPRICED.",
)


class UnpricedModelError( ValueError ):
    """Raised when a dollar clamp is requested for a model with no published price."""


def binding_daily_usd( daily_usd, monthly_usd, days_in_month=DAYS_PER_MONTH_WORST_CASE ):
    """
    Reconcile a daily target against a monthly target and return the one that BINDS.

    Rick asked for BOTH "$50/day" AND "max $1,000/month". Those two numbers are
    not simultaneously satisfiable as hard caps: $50/day sustained across a
    31-day month is $1,550 — it BLOWS the $1,000 ceiling. Whichever implies the
    lower daily rate is the real ceiling; the other is a burst allowance.

    Requires:
        - daily_usd is a positive number
        - monthly_usd is a positive number
        - days_in_month is a positive integer

    Ensures:
        - returns min( daily_usd, monthly_usd / days_in_month )
        - the returned rate, sustained every day, breaches NEITHER target

    Raises:
        - ValueError if any argument is not strictly positive
    """
    if daily_usd <= 0:    raise ValueError( f"daily_usd must be > 0, got {daily_usd}" )
    if monthly_usd <= 0:  raise ValueError( f"monthly_usd must be > 0, got {monthly_usd}" )
    if days_in_month <= 0: raise ValueError( f"days_in_month must be > 0, got {days_in_month}" )

    monthly_implied_daily = monthly_usd / days_in_month

    return min( daily_usd, monthly_implied_daily )


def clamp_tpm_for_daily_budget( price, daily_usd, minutes_per_day=MINUTES_PER_DAY ):
    """
    Convert a daily dollar budget into a combined-TPM clamp for the Cloud Quotas override.

    Computed at the OUTPUT rate — the most expensive direction. Because the Vertex
    TPM bucket counts input and output TOGETHER while they bill at different rates,
    the output rate is the ONLY assumption that bounds spend from above under EVERY
    input/output mix. Any cheaper assumption smuggles in a mix ratio we did not measure.

    Requires:
        - price is a ModelPrice
        - price.is_priced is True  (an unpriced model cannot be clamped to dollars)
        - daily_usd is a positive number
        - minutes_per_day is a positive number

    Ensures:
        - returns an int TPM such that sustaining it for a full day costs
          AT MOST daily_usd, under any input/output mix
        - the result is FLOORED, never rounded up (rounding up would permit
          a rate that breaches the budget)

    Raises:
        - UnpricedModelError if the model has no primary-sourced price
        - ValueError if daily_usd or minutes_per_day is not strictly positive
    """
    if not price.is_priced:
        raise UnpricedModelError(
            f"{price.model_id} has NO published per-token price from a primary source "
            f"({price.source_note}). An unpriced model cannot be clamped to a dollar "
            f"figure. Do not invent a price to make the arithmetic look finished."
        )
    if daily_usd <= 0:      raise ValueError( f"daily_usd must be > 0, got {daily_usd}" )
    if minutes_per_day <= 0: raise ValueError( f"minutes_per_day must be > 0, got {minutes_per_day}" )

    # Worst case: every metered token is billed as an OUTPUT token.
    tokens_per_day = ( daily_usd / price.usd_per_mtok_output ) * 1_000_000

    return int( tokens_per_day // minutes_per_day )


def max_daily_usd_at_tpm( price, tpm, minutes_per_day=MINUTES_PER_DAY ):
    """
    Inverse of the clamp: what does a given TPM permit, in dollars/day, worst case?

    This is the function that makes the "default quota is not a ceiling" claim
    CHECKABLE rather than rhetorical. Feed it the live default TPM and it reports
    the daily spend that default permits.

    Requires:
        - price.is_priced is True
        - tpm >= 0
        - minutes_per_day is a positive number

    Ensures:
        - returns the max USD/day sustainable at `tpm`, billing every token at
          the output rate

    Raises:
        - UnpricedModelError if the model has no primary-sourced price
        - ValueError if tpm is negative or minutes_per_day is not strictly positive
    """
    if not price.is_priced:
        raise UnpricedModelError( f"{price.model_id} is UNPRICED — cannot value a TPM in dollars." )
    if tpm < 0:              raise ValueError( f"tpm must be >= 0, got {tpm}" )
    if minutes_per_day <= 0: raise ValueError( f"minutes_per_day must be > 0, got {minutes_per_day}" )

    tokens_per_day = tpm * minutes_per_day

    return ( tokens_per_day / 1_000_000 ) * price.usd_per_mtok_output
