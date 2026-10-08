"""
A fake Jev client for the two-question request. It never reaches Jev.

It answers each question from the need in `state` and the candidate's text in the question.
Two different candidates get different answers, and a changed need changes them.
The words they share decide `provides`; the Score's level follows it in four steps.
It can leave a question unanswered, answer it wrongly, refuse a pack with a 422, or fail.
A fake that ignored its input would make every assertion written over it vacuous.
"""
import ast
import re
import threading

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_pair_request as rpr
from lupin_mcp import reuse_tools as rt

STOP_WORDS = frozenset( ( "the", "and", "for", "its", "with", "that", "this", "from", "are", "was" ) )
TIERS      = ( ( 0.7, "3" ), ( 0.4, "2" ), ( 0.15, "1" ), ( 0.0, "0" ) )       # provides at least this gives that level
TOP        = 0.7                                                                 # the chosen level's share; the rest is split evenly
PROVIDES_AT = ( "of the candidate ", ": does it already" )                       # what surrounds the text in the Noul question
COVERAGE_AT = ( "does the candidate ", " cover? Judge" )                         # what surrounds the text in the Score question


def words( text ):
    """Ensures: returns the lower-case words of three or more characters, without stop words."""
    return { w for w in re.findall( r"[a-z0-9]+", text.lower() ) if len( w ) >= 3 and w not in STOP_WORDS }


def candidate_of( instructions ):
    """
    Read the candidate's text back out of a question's instructions.

    Ensures:
        - returns the entry text the builder put there, whole, with any quotes or newlines intact
        - returns None when the instructions hold no candidate
    """
    for before, after in ( PROVIDES_AT, COVERAGE_AT ):
        start = instructions.find( before )
        end   = instructions.find( after )
        if start >= 0 and end > start: return ast.literal_eval( instructions[ start + len( before ):end ] )
    return None


def provides_of( need, text ):
    """Ensures: returns the share of the need's words the candidate's text also holds, 0 to 1."""
    mine = words( need )
    return len( mine & words( text ) ) / len( mine ) if mine else 0.0


def level_of( provides ):
    """Ensures: returns the Score level, "0" to "3", that a provides value maps to."""
    return next( level for floor, level in TIERS if provides >= floor )


def noul_answer( provides ):
    """Ensures: returns a Noul answer holding provides."""
    return { "type": "noul", "noul": round( provides, 4 ) }


def score_answer( provides ):
    """Ensures: returns a Score answer whose chosen level follows provides; the sum is 1."""
    chosen = level_of( provides )
    probs  = { level: ( TOP if level == chosen else round( ( 1 - TOP ) / 3, 4 ) ) for level in ( "0", "1", "2", "3" ) }
    return { "type": "score", "score": sum( int( k ) * v for k, v in probs.items() ), "confidence": 0.7, "legend": "fake", "probabilities": probs }


class PairFake:
    """
    A transport that answers a two-question body from the need and each candidate's text.

    `omit` and `wrong` map "provides" or "coverage" to the entry ids whose answer is left out
    or is the wrong kind of answer. A body with more questions than `refuse_over` raises a 422.
    `fail` is raised by every post. `usage` is ( input, output ) tokens, or None for none.
    """

    def __init__( self, entries, omit=None, wrong=None, refuse_over=None, fail=None, usage=( 100, 20 ) ):
        self.ids        = { rt.sha( e[ "id" ], 16 ): e[ "id" ] for e in entries }
        self.omit       = omit or {}
        self.wrong      = wrong or {}
        self.refuse_over, self.fail, self.usage = refuse_over, fail, usage
        self.bodies, self.lock = [], threading.Lock()

    def post_with_meta( self, body ):
        """
        Answer one body.

        Ensures:
            - returns ( response, meta ) as the live transport does
            - raises what `fail` holds, or a 422 JevConfigError for a body over `refuse_over` questions
        Raises:
            - AssertionError for a state that holds more than the need, a question with no candidate,
              or a question for an entry the fake was not given
        """
        with self.lock: self.bodies.append( body )
        if self.fail is not None: raise self.fail
        assert list( body[ "state" ] ) == [ "need" ], "the need must be the only thing in state"
        if self.refuse_over is not None and len( body[ "questions" ] ) > self.refuse_over:
            raise jt.JevConfigError( "Jev refused the request with status 422", 422 )
        need, answers = body[ "state" ][ "need" ], {}
        for key, question in body[ "questions" ].items():
            text = candidate_of( question[ "instructions" ] )
            assert text is not None, f"question {key!r} holds no candidate"
            assert key[ 2: ] in self.ids, f"question {key!r} is for an unknown entry"
            kind, entry_id = ( "provides" if key.startswith( rpr.PROVIDES_PREFIX ) else "coverage" ), self.ids[ key[ 2: ] ]
            if entry_id in self.omit.get( kind, () ): continue
            if entry_id in self.wrong.get( kind, () ): answers[ key ] = { "type": "choice", "probabilities": { "reuse": 1.0, "extend": 0.0, "unrelated": 0.0 } }
            else: answers[ key ] = noul_answer( provides_of( need, text ) ) if kind == "provides" else score_answer( provides_of( need, text ) )
        response = { "answers": answers, "model": body[ "model" ] }
        if self.usage is not None: response[ "usage" ] = { "input_tokens": self.usage[ 0 ], "output_tokens": self.usage[ 1 ] }
        return response, { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 2 }
