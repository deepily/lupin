"""
Compare the stored question vectors with the fresh ones to learn if one model made both.

Each ask with a stored vector in prediction_decisions has a fresh vector in the side file.
The fresh one comes from the same question text and one named model.
Same model and same text give a cosine of 1.0 up to float noise.
A different model gives a much lower cosine.
The report counts the asks by cosine band and shows the norm ratio, new over stored.

Two controls run before any figure is reported.
The positive control embeds the same texts twice now.
It needs a cosine of at least 0.999999 between the two runs, and between a run and the side file.
The negative control pairs each fresh vector with the stored vector of a different ask.
It needs a low median cosine, which shows the measure can tell different texts apart.
A failed control stops the run with no verdict.

The database is read in a read-only transaction and never written. The embedding service answers over
HTTP and nothing here loads a model or touches a GPU.

    python -m cosa.research.preference_replay.vector_comparison --side-file io/question-vectors/2026.11.19-vectors.jsonl
"""

import argparse
import hashlib
import json
import math
import statistics
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text

from cosa.memory.embedding_provider import get_embedding_provider
from cosa.research.preference_replay.question_vectors import load_side_file
from cosa.rest.db.database import get_db
from cosa.rest.postgres_models import Notification

CONTROL_SIZE         = 20
SAME_COSINE_FLOOR    = 0.999999   # two runs of one model on one text
SAME_BAND            = 0.999
NEGATIVE_MEDIAN_MAX  = 0.95       # different texts must sit clearly below the same-text band
BANDS                = ( ( "at or above 0.999", 0.999 ), ( "0.99 to 0.999", 0.99 ), ( "0.9 to 0.99", 0.9 ), ( "below 0.9", float( "-inf" ) ) )


class ControlFailed( RuntimeError ):
    """A positive or negative control did not behave, so no verdict can be given."""


def parse_vector( value: Any ) -> List[ float ]:
    """
    Turn a stored vector, as the driver returns it, into a list of floats.

    Requires:
        - value is a pgvector text such as "[0.1,0.2]", or a sequence of numbers

    Ensures:
        - returns the floats in order
    """
    if isinstance( value, str ): return [ float( part ) for part in value.strip().strip( "[]" ).split( "," ) ]
    return [ float( part ) for part in value ]


def norm( vector: Sequence[ float ] ) -> float:
    """
    Return the Euclidean length of a vector.

    Requires:
        - vector is a sequence of numbers

    Ensures:
        - returns a non-negative float
    """
    return math.sqrt( sum( part * part for part in vector ) )


def cosine( first: Sequence[ float ], second: Sequence[ float ] ) -> float:
    """
    Return the cosine similarity of two vectors of equal length.

    Requires:
        - both vectors have the same length and neither has zero length

    Ensures:
        - returns a float between -1 and 1, up to rounding

    Raises:
        - ValueError when the lengths differ or a vector has zero norm
    """
    if len( first ) != len( second ): raise ValueError( f"vectors differ in width: {len( first )} and {len( second )}" )
    scale = norm( first ) * norm( second )
    if scale == 0.0: raise ValueError( "a vector has zero norm" )
    return sum( a * b for a, b in zip( first, second ) ) / scale


def summarize( values: Sequence[ float ] ) -> Dict[ str, Any ]:
    """
    Give the count, minimum, median and maximum of some numbers.

    Requires:
        - values is a non-empty sequence of numbers

    Ensures:
        - returns a dict with n, min, median and max
    """
    return { "n": len( values ), "min": min( values ), "median": statistics.median( values ), "max": max( values ) }


def band_counts( cosines: Sequence[ float ] ) -> Dict[ str, int ]:
    """
    Count the cosines in each cosine band, highest band first.

    Requires:
        - cosines is a sequence of numbers

    Ensures:
        - returns one count per band; each cosine falls in exactly one band; the counts add up to len( cosines )
    """
    counts = { name: 0 for name, _ in BANDS }
    for value in cosines: counts[ next( ( name for name, floor in BANDS[ :-1 ] if value >= floor ), BANDS[ -1 ][ 0 ] ) ] += 1
    return counts


def compare( stored: Dict[ str, List[ float ] ], fresh: Dict[ str, List[ float ] ] ) -> Dict[ str, Dict[ str, float ] ]:
    """
    Measure cosine and norm ratio, fresh over stored, for each ask that has both.

    Requires:
        - stored and fresh map an ask id to a vector

    Ensures:
        - returns one entry per id in stored, in stored's order, with cosine and norm_ratio

    Raises:
        - KeyError when a stored id has no fresh vector
    """
    return { row_id: { "cosine": cosine( vector, fresh[ row_id ] ), "norm_ratio": norm( fresh[ row_id ] ) / norm( vector ) } for row_id, vector in stored.items() }


def positive_control( provider, pairs: List[ Tuple[ str, str ] ], fresh: Dict[ str, List[ float ] ] ) -> Dict[ str, float ]:
    """
    Embed the same texts twice now and compare the two runs, and a run with the side file.

    Requires:
        - pairs is a non-empty list of ( ask id, text ); fresh holds a vector for each id

    Ensures:
        - returns the lowest cosine between the two runs and the lowest between a run and the side file

    Raises:
        - ControlFailed when either lowest cosine is below SAME_COSINE_FLOOR
    """
    texts  = [ question for _, question in pairs ]
    first  = provider.generate_embeddings_batch( texts, content_type="prose" )
    second = provider.generate_embeddings_batch( texts, content_type="prose" )
    twice  = min( cosine( a, b ) for a, b in zip( first, second ) )
    filed  = min( cosine( a, fresh[ row_id ] ) for a, ( row_id, _ ) in zip( first, pairs ) )
    if twice < SAME_COSINE_FLOOR or filed < SAME_COSINE_FLOOR:
        raise ControlFailed( f"positive control: two runs now give a lowest cosine of {twice:.9f}, a run against the side file {filed:.9f}" )
    return { "twice_now_min_cosine": twice, "run_vs_side_file_min_cosine": filed }


def negative_control( stored: Dict[ str, List[ float ] ], fresh: Dict[ str, List[ float ] ] ) -> Dict[ str, float ]:
    """
    Pair each stored vector with the fresh vector of the next ask, a different text.

    Requires:
        - stored holds at least two asks and fresh has a vector for each

    Ensures:
        - returns the median and maximum cosine of those mismatched pairs

    Raises:
        - ControlFailed when the median reaches NEGATIVE_MEDIAN_MAX, since the measure then could not separate texts
    """
    ids     = list( stored )
    values  = [ cosine( stored[ ids[ index ] ], fresh[ ids[ ( index + 1 ) % len( ids ) ] ] ) for index in range( len( ids ) ) ]
    summary = { "mismatched_median_cosine": statistics.median( values ), "mismatched_max_cosine": max( values ) }
    if summary[ "mismatched_median_cosine" ] >= NEGATIVE_MEDIAN_MAX:
        raise ControlFailed( f"negative control: different texts have a median cosine of {summary[ 'mismatched_median_cosine' ]:.4f}" )
    return summary


def read_stored( session, ids: Sequence[ str ] ) -> Tuple[ Dict[ str, List[ float ] ], Dict[ str, str ], Dict[ str, str ] ]:
    """
    Read the stored vector, question and stripped message of each id with a stored vector.

    Requires:
        - session is an active read-only SQLAlchemy session

    Ensures:
        - returns three dicts keyed by id: the vector, the stored question, the stripped notification message
        - an id with no row or a null vector is left out of all three
    """
    sql = text( "SELECT id, question, CAST( question_embedding AS text ) FROM prediction_decisions WHERE id = ANY( :ids ) AND question_embedding IS NOT NULL" )
    vectors, questions, messages = {}, {}, {}
    for row_id, question, vector in session.execute( sql, { "ids": list( ids ) } ).fetchall():
        vectors[ row_id ]   = parse_vector( vector )
        questions[ row_id ] = question
        messages[ row_id ]  = session.get( Notification, row_id ).message.strip()
    return vectors, questions, messages


def report( side_file: str, session, provider, control_size: int = CONTROL_SIZE ) -> Dict[ str, Any ]:
    """
    Build the comparison report, running both controls first.

    Requires:
        - side_file is a file question_vectors wrote; session is read-only; provider embeds over HTTP

    Ensures:
        - returns the controls, the cosine and norm-ratio summaries, the band counts, and the same figures for the
          asks whose stored question equals the stripped message
        - raises before any comparison figure when a control fails

    Raises:
        - ControlFailed when a control fails
    """
    with open( side_file, "rb" ) as handle: digest = hashlib.sha256( handle.read() ).hexdigest()
    header, fresh = load_side_file( side_file )
    stored, questions, messages = read_stored( session, list( fresh ) )
    pairs     = [ ( row_id, messages[ row_id ] ) for row_id in list( stored )[ :control_size ] ]
    controls  = { **positive_control( provider, pairs, fresh ), **negative_control( stored, fresh ) }
    per_ask   = compare( stored, fresh )
    same_text = { row_id: value for row_id, value in per_ask.items() if questions[ row_id ] == messages[ row_id ] }

    def block( rows: Dict[ str, Dict[ str, float ] ] ) -> Dict[ str, Any ]:
        cosines = [ value[ "cosine" ] for value in rows.values() ]
        return { "asks": len( rows ), "cosine": summarize( cosines ), "norm_ratio": summarize( [ value[ "norm_ratio" ] for value in rows.values() ] ),
                 "bands": band_counts( cosines ), "at_or_above_0.999": sum( 1 for value in cosines if value >= SAME_BAND ) }

    return { "side_file_sha256": digest, "model": header[ "model" ], "revision": header[ "revision" ], "controls": controls,
             "all_with_a_stored_vector": block( per_ask ), "stored_question_equals_message": block( same_text ),
             "stored_question_differs_from_message": len( per_ask ) - len( same_text ) }


def main( argv: Optional[ Sequence[ str ] ] = None, printer: Callable = print, session_factory: Optional[ Callable ] = None,
          provider_factory: Optional[ Callable ] = None ) -> int:
    """
    Run the comparison from the command line.

    Requires:
        - argv holds --side-file and optionally --out

    Ensures:
        - the database is read in a read-only transaction and never written
        - prints the report as sorted JSON, and writes it to --out when given
        - returns 0 on success, 3 when a control fails (nothing else is printed)
    """
    parser = argparse.ArgumentParser( description="Compare stored question vectors with the regenerated ones." )
    parser.add_argument( "--side-file", required=True )
    parser.add_argument( "--out" )
    args     = parser.parse_args( argv )
    provider = ( provider_factory or get_embedding_provider )()
    with ( session_factory or get_db )() as session:
        session.execute( text( "SET TRANSACTION READ ONLY" ) )
        try:
            result = report( args.side_file, session, provider )
        except ControlFailed as err:
            printer( f"CONTROL FAILED, no verdict: {err}" )
            return 3
        finally:
            session.rollback()
    body = json.dumps( result, indent=2, sort_keys=True )
    printer( body )
    if args.out:
        with open( args.out, "w", encoding="utf-8" ) as handle: handle.write( body + "\n" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
