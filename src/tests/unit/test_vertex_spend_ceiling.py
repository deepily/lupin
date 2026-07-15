"""
Red-first tests for the Vertex spend-ceiling clamp arithmetic.

THE STANDARD (Rio's, adopted cascade-wide):
    "An observation is evidence only if it could have come out otherwise."

A clamp number with no test is a wish. So every test below is written to have a
DEFECT IT COULD CATCH, and the mutation that turns it red is named in the
docstring. The three mutations that matter:

  M1. Clamp at the INPUT price ($5) instead of the OUTPUT price ($25).
      -> permits 5x the intended spend. The budget is silently blown.
      -> CAUGHT BY: test_roundtrip_invariant_* (the clamp prices back over budget)

  M2. Round the clamp UP instead of down.
      -> permits a rate fractionally above the budget, forever.
      -> CAUGHT BY: test_roundtrip_invariant_* and test_clamp_floors_never_ceilings

  M3. Silently substitute a plausible price for an UNPRICED model.
      -> the whole point of the refusal. A fabricated price yields a
         confident-looking clamp that guards nothing.
      -> CAUGHT BY: test_unpriced_model_*

The roundtrip invariant is the load-bearing assertion: clamp a budget, then
price the clamp back, and it must NEVER exceed the budget. It is a green that
could very easily have been red — M1 and M2 both trip it.
"""

import pytest

from cosa.utils.vertex_spend_ceiling import (
    CLAUDE_OPUS_4_8,
    DEEPSEEK_V3_2_MAAS,
    GPT_OSS_120B_MAAS,
    DAYS_PER_MONTH_WORST_CASE,
    MINUTES_PER_DAY,
    ModelPrice,
    UnpricedModelError,
    binding_daily_usd,
    clamp_tpm_for_daily_budget,
    max_daily_usd_at_tpm,
)

RICK_DAILY_USD   = 50.0
RICK_MONTHLY_USD = 1000.0


# ---------------------------------------------------------------------------
# ModelPrice.is_priced — both branches
# ---------------------------------------------------------------------------

def test_opus_is_priced():
    """Opus 4.8 carries a primary-sourced price in BOTH directions."""
    assert CLAUDE_OPUS_4_8.is_priced is True
    assert CLAUDE_OPUS_4_8.usd_per_mtok_input  == 5.00
    assert CLAUDE_OPUS_4_8.usd_per_mtok_output == 25.00


def test_maas_models_are_unpriced():
    """
    The MaaS models have NO published price. This is a FINDING, recorded as a
    test so it cannot be quietly forgotten and back-filled with a guess.
    """
    assert DEEPSEEK_V3_2_MAAS.is_priced is False
    assert GPT_OSS_120B_MAAS.is_priced  is False


def test_half_priced_model_is_not_priced():
    """
    A model with an input price but no output price is NOT priced. Since the
    clamp is computed at the OUTPUT rate, a missing output price is fatal —
    is_priced must not be satisfied by the input side alone.
    Mutation: `or` instead of `and` in is_priced -> this goes red.
    """
    half = ModelPrice( "half", 1.0, None, "u", "n" )
    assert half.is_priced is False

    other_half = ModelPrice( "other", None, 1.0, "u", "n" )
    assert other_half.is_priced is False


# ---------------------------------------------------------------------------
# THE ROUNDTRIP SAFETY INVARIANT — the load-bearing test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "daily_usd", [ 0.01, 1.0, 12.5, 33.33, 50.0, 137.77, 1000.0 ] )
def test_roundtrip_invariant_clamp_never_exceeds_budget( daily_usd ):
    """
    THE INVARIANT: clamp a budget to a TPM, price that TPM back at the worst-case
    (all-output) rate, and it must NEVER exceed the budget you asked for.

    Goes RED under M1 (input price -> prices back at ~5x the budget) and under
    M2 (round up -> prices back fractionally over). This is the assertion that
    makes the clamp a brake instead of a wish.
    """
    tpm         = clamp_tpm_for_daily_budget( CLAUDE_OPUS_4_8, daily_usd )
    priced_back = max_daily_usd_at_tpm( CLAUDE_OPUS_4_8, tpm )

    assert priced_back <= daily_usd, (
        f"clamp of {tpm} TPM prices back to ${priced_back:.4f}/day, which BREACHES "
        f"the ${daily_usd}/day budget. The clamp permits more than it was asked to."
    )


def test_clamp_floors_never_ceilings():
    """
    The clamp must FLOOR. A budget whose exact TPM is fractional must round DOWN.

    $50/day / $25 per MTok = 2,000,000 tok/day / 1440 min = 1388.88... TPM.
    Floor -> 1388. Ceil -> 1389, which permits 1389*1440*25/1e6 = $50.004/day.
    Mutation: round() or math.ceil() -> this goes red.
    """
    tpm = clamp_tpm_for_daily_budget( CLAUDE_OPUS_4_8, RICK_DAILY_USD )
    assert tpm == 1388, f"expected floor(1388.88)=1388, got {tpm}"

    # And prove the ceil would actually have breached — the defect is real, not theoretical.
    assert max_daily_usd_at_tpm( CLAUDE_OPUS_4_8, 1389 ) > RICK_DAILY_USD


def test_clamp_at_output_price_not_input_price():
    """
    Directly pins the clamp to the OUTPUT rate. If someone "optimizes" this to
    the input rate (or a blended mix), the permitted spend jumps ~5x.
    Mutation: usd_per_mtok_input in the clamp -> tpm becomes 6944 -> this goes red.
    """
    tpm = clamp_tpm_for_daily_budget( CLAUDE_OPUS_4_8, RICK_DAILY_USD )

    at_output_rate = int( ( ( RICK_DAILY_USD / 25.00 ) * 1_000_000 ) // MINUTES_PER_DAY )
    at_input_rate  = int( ( ( RICK_DAILY_USD /  5.00 ) * 1_000_000 ) // MINUTES_PER_DAY )

    assert tpm == at_output_rate
    assert tpm != at_input_rate
    assert at_input_rate == 6944  # the 5x-too-permissive number we must never ship


# ---------------------------------------------------------------------------
# THE $50/day vs $1,000/month CONFLICT — Rick's two targets cannot both be hard caps
# ---------------------------------------------------------------------------

def test_rick_daily_and_monthly_targets_are_inconsistent():
    """
    $50/day sustained across a 31-day month is $1,550 — it BLOWS the $1,000/month
    ceiling. The monthly target therefore BINDS, and $50/day is a burst allowance,
    not a sustainable rate. Surfacing this is the point.
    """
    sustained_month = RICK_DAILY_USD * DAYS_PER_MONTH_WORST_CASE
    assert sustained_month == 1550.0
    assert sustained_month > RICK_MONTHLY_USD

    binding = binding_daily_usd( RICK_DAILY_USD, RICK_MONTHLY_USD )
    assert binding == pytest.approx( 1000.0 / 31 )   # ~$32.26/day
    assert binding < RICK_DAILY_USD                  # the monthly cap is the real ceiling


def test_binding_returns_daily_when_daily_is_the_tighter_one():
    """The other branch of the min(): a generous monthly cap leaves the daily binding."""
    binding = binding_daily_usd( daily_usd=10.0, monthly_usd=100_000.0 )
    assert binding == 10.0


def test_binding_daily_usd_uses_longest_month():
    """
    Worst-case month = 31 days. Using 30 would permit a daily rate that breaches
    the monthly cap in any 31-day month — the one direction a ceiling must never err.
    """
    assert DAYS_PER_MONTH_WORST_CASE == 31

    on_31 = binding_daily_usd( 50.0, 1000.0, days_in_month=31 )
    on_30 = binding_daily_usd( 50.0, 1000.0, days_in_month=30 )
    assert on_31 < on_30                       # 31-day assumption is the stricter one
    assert on_30 * 31 > RICK_MONTHLY_USD       # and the 30-day one would overspend


# ---------------------------------------------------------------------------
# THE HEADROOM CLAIM — "the defaults are not a ceiling; they are the absence of one"
# ---------------------------------------------------------------------------

def test_default_openapi_tpm_permits_absurd_daily_spend_at_opus_prices():
    """
    Makes the headroom claim CHECKABLE instead of rhetorical.

    The Openapi (MaaS) family default is 52,000 tok/min = ~74.9M tokens/day. If a
    Claude-lineage quota carried a comparable default, that rate priced at Opus
    output rates is ~$1,872/day — roughly 37x Rick's $50/day target.

    NOTE: 52k is the MaaS default, NOT a measured Claude default. The live Claude
    default is still unread (GCP re-auth pending). This test pins the ARITHMETIC,
    not a claim about Claude's actual quota value.
    """
    tokens_per_day = 52_000 * MINUTES_PER_DAY
    assert tokens_per_day == 74_880_000

    worst_case_usd = max_daily_usd_at_tpm( CLAUDE_OPUS_4_8, 52_000 )
    assert worst_case_usd == pytest.approx( 1872.0 )
    assert worst_case_usd > RICK_DAILY_USD * 37


def test_max_daily_usd_at_zero_tpm_is_zero():
    """A fully-closed quota permits zero spend. Boundary: tpm=0 is legal, not an error."""
    assert max_daily_usd_at_tpm( CLAUDE_OPUS_4_8, 0 ) == 0.0


# ---------------------------------------------------------------------------
# THE REFUSAL — an unpriced model cannot be clamped to a dollar figure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "unpriced", [ DEEPSEEK_V3_2_MAAS, GPT_OSS_120B_MAAS ] )
def test_unpriced_model_cannot_be_clamped( unpriced ):
    """
    Refuses rather than guesses. The predecessor seat would not invent a price to
    make the arithmetic look finished; this test makes that refusal STRUCTURAL.
    """
    with pytest.raises( UnpricedModelError, match="NO published per-token price" ):
        clamp_tpm_for_daily_budget( unpriced, RICK_DAILY_USD )


def test_unpriced_model_cannot_be_valued_at_a_tpm():
    """The inverse direction refuses too — you cannot price a TPM you have no rate for."""
    with pytest.raises( UnpricedModelError, match="UNPRICED" ):
        max_daily_usd_at_tpm( DEEPSEEK_V3_2_MAAS, 1000 )


# ---------------------------------------------------------------------------
# Guard branches — every raise is reachable and reached
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "bad", [ 0.0, -1.0 ] )
def test_clamp_rejects_nonpositive_budget( bad ):
    with pytest.raises( ValueError, match="daily_usd must be > 0" ):
        clamp_tpm_for_daily_budget( CLAUDE_OPUS_4_8, bad )


@pytest.mark.parametrize( "bad", [ 0.0, -1.0 ] )
def test_clamp_rejects_nonpositive_minutes( bad ):
    with pytest.raises( ValueError, match="minutes_per_day must be > 0" ):
        clamp_tpm_for_daily_budget( CLAUDE_OPUS_4_8, RICK_DAILY_USD, minutes_per_day=bad )


@pytest.mark.parametrize( "bad", [ 0.0, -1.0 ] )
def test_max_daily_rejects_nonpositive_minutes( bad ):
    with pytest.raises( ValueError, match="minutes_per_day must be > 0" ):
        max_daily_usd_at_tpm( CLAUDE_OPUS_4_8, 1000, minutes_per_day=bad )


def test_max_daily_rejects_negative_tpm():
    with pytest.raises( ValueError, match="tpm must be >= 0" ):
        max_daily_usd_at_tpm( CLAUDE_OPUS_4_8, -1 )


@pytest.mark.parametrize( "bad", [ 0.0, -1.0 ] )
def test_binding_rejects_nonpositive_daily( bad ):
    with pytest.raises( ValueError, match="daily_usd must be > 0" ):
        binding_daily_usd( bad, RICK_MONTHLY_USD )


@pytest.mark.parametrize( "bad", [ 0.0, -1.0 ] )
def test_binding_rejects_nonpositive_monthly( bad ):
    with pytest.raises( ValueError, match="monthly_usd must be > 0" ):
        binding_daily_usd( RICK_DAILY_USD, bad )


@pytest.mark.parametrize( "bad", [ 0, -1 ] )
def test_binding_rejects_nonpositive_days( bad ):
    with pytest.raises( ValueError, match="days_in_month must be > 0" ):
        binding_daily_usd( RICK_DAILY_USD, RICK_MONTHLY_USD, days_in_month=bad )
