"""
A Jev back end for the claim judge.

Where claim_judge asks Claude for a word per claim, this asks Jev one yes/no question per claim.
Two thresholds turn the probability into present, absent or uncertain. Uncertain claims take the
same path as the Claude judge's: they go to the escalation model, and a claim still uncertain
fails closed to absent. Only the new docstring, the linked design document and one claim
sentence are sent to TypeSafe.
"""

import inspect
import sys
from collections import namedtuple

from . import claim_judge, jev_transport, model_transport

JevResult = namedtuple( "JevResult", [ "judgements", "model", "scores" ] )

INSTRUCTIONS = "Does the text state this claim: {claim}"
CRITERIA     = {
    "true"  : "The text, or the design document, says the claim, even in different words.",
    "false" : "Neither says it, or one says something weaker, narrower or opposite. A sentence that is only related to the claim does not state it.",
}


def check_thresholds( t_lo, t_hi ):
    """
    Refuse thresholds that do not split the probability range into three bands.

    Requires:
        - t_lo and t_hi are the two cut points; the harness has no default for either

    Raises:
        - ValueError unless 0 <= t_lo < t_hi <= 1 and both are numbers
    """
    if type( t_lo ) not in ( int, float ) or type( t_hi ) not in ( int, float ) or not 0 <= t_lo < t_hi <= 1:
        raise ValueError( f"thresholds must satisfy 0 <= t_lo < t_hi <= 1, got t_lo={t_lo!r} t_hi={t_hi!r}" )


def verdict_for( noul, t_lo, t_hi ):
    """
    Map a probability of yes to a verdict word.

    Requires:
        - noul is a number from 0 to 1; thresholds already passed check_thresholds

    Ensures:
        - noul at or above t_hi is present, at or below t_lo is absent, anything between is uncertain
    """
    if noul >= t_hi: return "present"
    if noul <= t_lo: return "absent"
    return "uncertain"


def build_state( new_text, design_text ):
    """Return the state sent to Jev: the new docstring, plus the design document when there is one."""
    state = { "new_text": new_text }
    if design_text is not None: state[ "design_doc" ] = design_text
    return state


async def judge_claims_jev( claims, new_text, design_text, jev_model, t_lo, t_hi, escalation_model,
                            query_fn=None, post_fn=None, sleep_fn=None, environ=None ):
    """
    Judge every claim with Jev, escalate the uncertain ones, and fail closed on the rest.

    Requires:
        - claims is a list of extractor Claims; new_text is a str; design_text is a str or None
        - jev_model is a pinned Jev id; escalation_model is a Claude model id; neither has a default
        - t_lo and t_hi pass check_thresholds
        - post_fn, sleep_fn and environ are test stand-ins for the HTTP call, the backoff wait and os.environ

    Ensures:
        - returns a JevResult( judgements, model, scores ): one Judgement per claim in order, the
          model string every answer carried, and one noul per claim or None where Jev gave none
        - a claim Jev could not answer (retries ran out, malformed body) is uncertain, so it
          escalates like any uncertain claim, and keeps the Jev failure as its reason if it still fails closed
        - verdict is present or absent only; uncertain never leaves this function
        - an empty claim list makes no call and returns no model string

    Raises:
        - ValueError if a model id is empty or the thresholds are bad
        - jev_transport.JevConfigError if the key is absent or Jev refuses the key or the request:
          a configuration failure is not a verdict
        - model_transport.ModelCallError if the escalation call itself fails
    """
    if not jev_model or not escalation_model: raise ValueError( "jev and escalation model ids are required: the harness has no default" )
    check_thresholds( t_lo, t_hi )
    if not claims: return JevResult( [], None, [] )
    state   = build_state( new_text, design_text )
    first   = []
    scores  = []
    reasons = {}
    for i, claim in enumerate( claims ):
        try:
            noul, _ = jev_transport.ask_noul( jev_model, state, INSTRUCTIONS.format( claim=claim.text ), CRITERIA,
                                              post_fn=post_fn, sleep_fn=sleep_fn, environ=environ )
        except jev_transport.JevCallError as e:
            first.append( "uncertain" )
            scores.append( None )
            reasons[ i ] = f"jev gave no answer: {e}"
            continue
        first.append( verdict_for( noul, t_lo, t_hi ) )
        scores.append( noul )
    judgements = await claim_judge.finish_judgements( claims, first, new_text, design_text, escalation_model,
                                                      first_reasons=reasons, query_fn=query_fn )
    scored = [ j._replace( noul=score ) for j, score in zip( judgements, scores ) ]
    return JevResult( scored, jev_model, scores )


class JevBackend:
    """
    The judge back end the runner takes in place of the Claude judge.

    Requires:
        - jev_model, escalation_model and the thresholds pass judge_claims_jev's checks

    Ensures:
        - key_id names the Jev model, both thresholds and the escalation model, so a ledger row is
          never reused under other thresholds or another model
        - judge returns Judgements, each carrying the noul Jev gave (None when it gave none)
    """

    def __init__( self, jev_model, t_lo, t_hi, escalation_model, post_fn=None, sleep_fn=None, environ=None ):
        if not jev_model or not escalation_model: raise ValueError( "jev and escalation model ids are required: the harness has no default" )
        check_thresholds( t_lo, t_hi )
        self.jev_model        = jev_model
        self.t_lo             = t_lo
        self.t_hi             = t_hi
        self.escalation_model = escalation_model
        self.post_fn          = post_fn
        self.sleep_fn         = sleep_fn
        self.environ          = environ
        self.prompt_version   = PROMPT_VERSION
        self.key_id           = f"{jev_model}@{t_lo}-{t_hi}+{escalation_model}"

    async def judge( self, claims, new_text, design_text, query_fn=None ):
        """Judge the claims with Jev and return one Judgement per claim."""
        result = await judge_claims_jev( claims, new_text, design_text, self.jev_model, self.t_lo, self.t_hi, self.escalation_model,
                                         query_fn=query_fn, post_fn=self.post_fn, sleep_fn=self.sleep_fn, environ=self.environ )
        return result.judgements


PROMPT_VERSION = model_transport.prompt_version( "jev", inspect.getsource( sys.modules[ __name__ ] ), inspect.getsource( jev_transport ) )
