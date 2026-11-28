"""
Draw the judge's validation sample: uniform per card type, seeded and blind to the arm.

The population is only the pairs a comparator would send to the judge. The stance or the
picked options already match, and the two texts differ. Only the arms the manager ruled
eligible for that card type count. Cancelled or empty answers are left out. Each card type gets a set
number of pairs, drawn without replacement with equal probability. No output carries an arm or a
model field, and every file's order is shuffled.

The two readers who set the truth labels get two files, both keyed by pair id. The first holds
the card, its options and the answer, and no forecast. The second holds the forecasts. The
sample sizes are inputs: the manager records them before any card is drawn.
"""

import argparse
import json
import pathlib
import random
import sys

from cosa.utils import jsonl_file
from cosa.utils.atomic_json import write_json_atomic
from cosa.utils.file_hash import file_sha256
from lupin_mcp.duplicate_check_self_consistency import draw as seeded_ids

PER_TYPE        = 80
CHOICE_TYPES    = ( "yes_no", "multiple_choice" )
OPEN_TYPES      = ( "open_ended", "open_ended_batch" )
ELIGIBLE_ARMS   = { "answer_history": CHOICE_TYPES + OPEN_TYPES, "B1-full": CHOICE_TYPES, "C0-full": CHOICE_TYPES, "B1": OPEN_TYPES, "C0": OPEN_TYPES }
CANCELLED       = "[cancelled]"
SAMPLE_FILE     = "sample.jsonl"
DRAW_FILE       = "draw.json"
ANSWERS_FILE    = "reader-answers.jsonl"
FORECASTS_FILE  = "reader-forecasts.jsonl"
CARD_FIELDS     = ( "response_type", "message", "abstract", "options", "answer" )
BLIND_FIELDS    = ( "pair_id", "notification_id", "response_type", "field_key", "predicted_text", "actual_text", "refers_to_earlier" )
NO_CONDITION    = "no condition added"
EXIT_REFUSED    = 1


def pattern_of( pair ):
    """
    Name how a pair's two texts differ, the secondary breakdown of the report.

    Requires:
        - pair has predicted_text and actual_text, each a string or None

    Ensures:
        - returns "same" for equal words ignoring case and outer space (both empty included),
          "only_predicted" when the answer has no text, "only_actual" when the forecast has none,
          and "differ" otherwise
    """
    predicted = ( pair[ "predicted_text" ] or "" ).strip().lower()
    actual    = ( pair[ "actual_text" ]    or "" ).strip().lower()
    if predicted == actual: return "same"
    if not actual:          return "only_predicted"
    if not predicted:       return "only_actual"
    return "differ"


def exclusion_of( pair, arm, answer ):
    """
    Say why a pair is outside the population, or that it is inside.

    Requires:
        - pair has response_type, actual_text and literal_mismatch, and option_mismatch when multiple choice
        - arm is the name of the arm that made the forecast; answer is the card's stored answer

    Ensures:
        - returns None for a pair the judge would be asked about, otherwise one of:
        - "arm" when the arm is not eligible for the card type
        - "cancelled_or_empty" when the card's answer is cancelled or blank, the actual text is cancelled,
          or the actual text is blank on a card type other than yes/no
        - "not_judged" when the two texts are the same, or the picked options differ

    Raises:
        - KeyError when a multiple-choice pair has no option_mismatch
    """
    kind = pair[ "response_type" ]
    if kind not in ELIGIBLE_ARMS.get( arm, () ): return "arm"
    actual = ( pair[ "actual_text" ] or "" ).strip()
    if answer.strip() in ( "", CANCELLED ) or actual == CANCELLED or ( kind != "yes_no" and not actual ): return "cancelled_or_empty"
    if not pair[ "literal_mismatch" ] or ( kind == "multiple_choice" and pair[ "option_mismatch" ] ): return "not_judged"
    return None


def eligible( pairs, key, cards ):
    """
    Keep the population the sample is drawn from.

    Requires:
        - key is { pair_id: { arm } }; cards is card_rows' answer for every card of the pairs

    Ensures:
        - returns ( kept, dropped ); dropped counts the pairs left out under each of exclusion_of's reasons
        - no field of the key is added to a kept pair

    Raises:
        - ValueError when a pair has no key, or a multiple-choice pair has no option_mismatch
    """
    kept, dropped = [], { "arm": 0, "cancelled_or_empty": 0, "not_judged": 0 }
    for pair in pairs:
        if pair[ "pair_id" ] not in key: raise ValueError( f"pair {pair[ 'pair_id' ]} has no key" )
        try:
            reason = exclusion_of( pair, key[ pair[ "pair_id" ] ][ "arm" ], cards[ pair[ "notification_id" ] ][ "answer" ] )
        except KeyError as error:
            raise ValueError( f"pair {pair[ 'pair_id' ]} lacks the field {error}" ) from error
        if reason is None: kept.append( pair )
        else: dropped[ reason ] += 1
    return kept, dropped


def draw_sample( pairs, seed, per_type=PER_TYPE ):
    """
    Draw the validation sample from the eligible pairs, uniformly within each card type.

    Requires:
        - pairs is a list of dicts holding BLIND_FIELDS, with pair_id unique; seed is an integer
        - a yes/no pair also holds stance, the stance the answer took
        - per_type is a positive integer

    Ensures:
        - returns ( sample, receipt )
        - sample rows hold BLIND_FIELDS, stratum, pattern and inclusion, plus stance for yes/no, and nothing else,
          in a seeded order
        - stratum is the card type; min( per_type, its pairs ) are drawn without replacement, so every pair of
          a type has the same chance, which is inclusion
        - receipt holds seed, per_type, drawn and, per stratum, population, drawn and inclusion
        - the same pairs, in any order, with the same arguments give the same sample

    Raises:
        - ValueError when pairs is empty or a pair_id repeats, or a drawn pair lacks a field
    """
    if not pairs: raise ValueError( "there are no pairs to draw from" )
    by_id = { pair[ "pair_id" ]: pair for pair in pairs }
    if len( by_id ) != len( pairs ): raise ValueError( "a pair_id appears more than once" )
    members = {}
    for pair_id, pair in by_id.items(): members.setdefault( pair[ "response_type" ], [] ).append( pair_id )
    sample, strata = [], {}
    for name in sorted( members ):
        chosen    = seeded_ids( members[ name ], per_type, f"{seed}:{name}" )
        inclusion = len( chosen ) / len( members[ name ] )
        strata[ name ] = { "population": len( members[ name ] ), "drawn": len( chosen ), "inclusion": inclusion }
        for pair_id in chosen:
            wanted = BLIND_FIELDS + ( ( "stance", ) if name == "yes_no" else () )
            try:
                row = { field: by_id[ pair_id ][ field ] for field in wanted }
            except KeyError as error:
                raise ValueError( f"pair {pair_id} lacks the field {error}" ) from error
            row.update( stratum=name, pattern=pattern_of( by_id[ pair_id ] ), inclusion=inclusion )
            sample.append( row )
    random.Random( seed ).shuffle( sample )
    return sample, { "seed": seed, "per_type": per_type, "drawn": len( sample ), "strata": strata }


def card_rows( cards_path, notification_ids ):
    """
    Read the cards and answers the readers label against.

    Requires:
        - cards_path names a JSON Lines file with one row per card holding CARD_FIELDS and notification_id

    Ensures:
        - returns { id: { CARD_FIELDS } } for the ids asked, and carries no other field of a row

    Raises:
        - ValueError when a card is not in the file
    """
    held = { row[ "notification_id" ]: row for row in jsonl_file.read_jsonl( pathlib.Path( cards_path ) ) }
    for given in notification_ids:
        if given not in held:
            raise ValueError( f"card {given} is not in the cards file" )
    return { given: { field: held[ given ][ field ] for field in CARD_FIELDS } for given in notification_ids }


def reader_files( sample, cards, seed ):
    """
    Build the two files the truth readers get, both keyed by pair id.

    Requires:
        - sample comes from draw_sample; cards is card_rows' answer for every card in it

    Ensures:
        - returns ( answers, forecasts ), each shuffled by seed
        - answers holds one row per pair: pair_id, notification_id, field_key, actual_text, the card and
          the answer, and no forecast
        - a yes/no answers row also holds stance, and its blank actual_text reads NO_CONDITION
        - forecasts holds one row per pair: pair_id, notification_id, field_key and predicted_text
        - neither holds a stratum, an inclusion figure, an arm, a model or refers_to_earlier
    """
    ordered   = sorted( sample, key=lambda row: row[ "pair_id" ] )
    keys      = ( "pair_id", "notification_id", "field_key" )
    answers   = [ dict( cards[ row[ "notification_id" ] ], **{ field: row[ field ] for field in keys + ( "actual_text", ) } ) for row in ordered ]
    for row, shown in zip( ordered, answers ):
        if row[ "response_type" ] != "yes_no": continue
        shown[ "stance" ] = row[ "stance" ]
        if not ( row[ "actual_text" ] or "" ).strip(): shown[ "actual_text" ] = NO_CONDITION
    forecasts = [ { field: row[ field ] for field in keys + ( "predicted_text", ) } for row in ordered ]
    random.Random( f"{seed}:answers" ).shuffle( answers )
    random.Random( f"{seed}:forecasts" ).shuffle( forecasts )
    return answers, forecasts


def write_sample( pairs_path, key_path, cards_path, out_dir, seed, per_type=PER_TYPE ):
    """
    Draw from a pairs file and write the sample, the two reader files and the receipt, once.

    Requires:
        - pairs_path and cards_path name JSON Lines files of pairs and of cards; key_path the sealed key; out_dir a folder

    Ensures:
        - writes SAMPLE_FILE, ANSWERS_FILE, FORECASTS_FILE and DRAW_FILE under out_dir, making the folder
        - DRAW_FILE also records what was left out and the sha256 of the pairs, key, cards and the three files written
        - returns the receipt

    Raises:
        - FileExistsError when any of the four is already there, and writes nothing
        - ValueError as eligible, draw_sample and card_rows raise it, and writes nothing
    """
    out   = pathlib.Path( out_dir )
    names = ( SAMPLE_FILE, ANSWERS_FILE, FORECASTS_FILE )
    for name in names + ( DRAW_FILE, ):
        if ( out / name ).exists(): raise FileExistsError( f"{out / name} exists: a sample is drawn once" )
    pairs              = jsonl_file.read_jsonl( pathlib.Path( pairs_path ) )
    cards              = card_rows( cards_path, sorted( { pair[ "notification_id" ] for pair in pairs } ) )
    kept, dropped      = eligible( pairs, json.loads( pathlib.Path( key_path ).read_text( encoding="utf-8" ) ), cards )
    sample, receipt    = draw_sample( kept, seed, per_type )
    answers, forecasts = reader_files( sample, cards, seed )
    out.mkdir( parents=True, exist_ok=True )
    for name, rows in zip( names, ( sample, answers, forecasts ) ):
        with open( out / name, "x", encoding="utf-8" ) as handle:
            handle.writelines( json.dumps( row, sort_keys=True ) + "\n" for row in rows )
    receipt.update( dropped=dropped, pairs_sha256=file_sha256( str( pairs_path ) ), key_sha256=file_sha256( str( key_path ) ), cards_sha256=file_sha256( str( cards_path ) ), files={ name: file_sha256( str( out / name ) ) for name in names } )
    write_json_atomic( str( out / DRAW_FILE ), receipt, indent=2, trailing_newline=True, sort_keys=True )
    return receipt


def main( argv=None ):
    """
    Run the draw from the command line.

    Ensures:
        - prints the receipt and returns 0, or prints the refusal and returns EXIT_REFUSED
    """
    parser = argparse.ArgumentParser( description="Draw the judge validation sample." )
    parser.add_argument( "--pairs", required=True )
    parser.add_argument( "--key", required=True, help="the sealed key, read for the arm filter only" )
    parser.add_argument( "--cards", required=True, help="one row per card, written beside the pairs" )
    parser.add_argument( "--out-dir", required=True )
    parser.add_argument( "--seed", type=int, required=True )
    parser.add_argument( "--per-type", type=int, default=PER_TYPE, help="the size recorded on the row" )
    args = parser.parse_args( argv )
    try:
        receipt = write_sample( args.pairs, args.key, args.cards, args.out_dir, args.seed, args.per_type )
    except ( ValueError, FileExistsError ) as error:
        print( error, file=sys.stderr )
        return EXIT_REFUSED
    print( json.dumps( receipt, indent=2, sort_keys=True ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
