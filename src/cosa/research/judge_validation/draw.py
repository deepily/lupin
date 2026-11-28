"""
Draw the judge's validation sample: stratified, seeded and blind to the arm.

The recorded design draws a set number of pairs per card type. The true class of a pair (the
forecast is wrong or right) is known only after labelling. So each type's draw is oversampled on
a proxy: half comes from pairs whose two texts differ, half from pairs whose texts match. Each
drawn pair keeps its inclusion probability. No output carries an arm or model field, and every
file's order is shuffled.

The two readers who set the truth labels get two files. The first holds each card with its
options and the answer, and no forecast. The second holds the forecasts, keyed by pair id.
The sample sizes are inputs: the manager records them before any card is drawn.
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
MISMATCH_SHARE  = 0.5
SAMPLE_FILE     = "sample.jsonl"
DRAW_FILE       = "draw.json"
ANSWERS_FILE    = "reader-answers.jsonl"
FORECASTS_FILE  = "reader-forecasts.jsonl"
CARD_FIELDS     = ( "response_type", "message", "abstract", "options", "answer" )
BLIND_FIELDS    = ( "pair_id", "notification_id", "response_type", "field_key", "predicted_text", "actual_text" )
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


def split( mismatched, matched, size, mismatch_share=MISMATCH_SHARE ):
    """
    Share one card type's sample between the mismatched pairs and the matched ones.

    Requires:
        - mismatched and matched are population counts; size is a positive integer; mismatch_share is in [0, 1]

    Ensures:
        - returns ( from mismatched, from matched ), neither above its population
        - the mismatched side aims at round( size * mismatch_share ), and either side takes up what the
          other cannot fill, so the two add to min( size, mismatched + matched )
    """
    first  = min( mismatched, round( size * mismatch_share ) )
    second = min( matched, size - first )
    first  = min( mismatched, size - second )
    return first, second


def draw_sample( pairs, seed, per_type=PER_TYPE, mismatch_share=MISMATCH_SHARE ):
    """
    Draw the validation sample from every forecast-and-answer pair.

    Requires:
        - pairs is a list of dicts holding BLIND_FIELDS and literal_mismatch (bool), with pair_id unique
        - seed is an integer; per_type and mismatch_share are as split takes them

    Ensures:
        - returns ( sample, receipt )
        - sample rows hold BLIND_FIELDS, stratum, pattern and inclusion, and nothing else, in a seeded order
        - stratum is "<response_type>/mismatch" or "<response_type>/match", by literal_mismatch
        - within a stratum the pairs are drawn without replacement, each with probability inclusion
        - receipt holds seed, per_type, mismatch_share, drawn and, per stratum, population, drawn and inclusion
        - the same pairs, in any order, with the same arguments give the same sample

    Raises:
        - ValueError when pairs is empty or a pair_id repeats
    """
    if not pairs: raise ValueError( "there are no pairs to draw from" )
    by_id = { pair[ "pair_id" ]: pair for pair in pairs }
    if len( by_id ) != len( pairs ): raise ValueError( "a pair_id appears more than once" )
    members = {}
    for pair_id, pair in by_id.items():
        sides = members.setdefault( pair[ "response_type" ], ( [], [] ) )
        sides[ 0 if pair[ "literal_mismatch" ] else 1 ].append( pair_id )
    sample, strata = [], {}
    for kind in sorted( members ):
        counts = split( len( members[ kind ][ 0 ] ), len( members[ kind ][ 1 ] ), per_type, mismatch_share )
        for side, ids, count in zip( ( "mismatch", "match" ), members[ kind ], counts ):
            if not ids: continue
            name      = f"{kind}/{side}"
            chosen    = seeded_ids( ids, count, f"{seed}:{name}" ) if count else []
            inclusion = len( chosen ) / len( ids )
            strata[ name ] = { "population": len( ids ), "drawn": len( chosen ), "inclusion": inclusion }
            for pair_id in chosen:
                row = { field: by_id[ pair_id ][ field ] for field in BLIND_FIELDS }
                row.update( stratum=name, pattern=pattern_of( by_id[ pair_id ] ), inclusion=inclusion )
                sample.append( row )
    random.Random( seed ).shuffle( sample )
    return sample, { "seed": seed, "per_type": per_type, "mismatch_share": mismatch_share, "drawn": len( sample ), "strata": strata }


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
    Build the two files the truth readers get.

    Requires:
        - sample comes from draw_sample; cards is card_rows' answer for every card in it

    Ensures:
        - returns ( answers, forecasts ), each shuffled by seed
        - answers holds one row per card: notification_id, the card and the answer, and no forecast
        - forecasts holds one row per pair: pair_id, notification_id, field_key and predicted_text
        - neither holds a stratum, an inclusion figure, an arm or a model
    """
    answers   = [ dict( cards[ card ], notification_id=card ) for card in sorted( { row[ "notification_id" ] for row in sample } ) ]
    forecasts = [ { field: row[ field ] for field in ( "pair_id", "notification_id", "field_key", "predicted_text" ) }
                  for row in sorted( sample, key=lambda row: row[ "pair_id" ] ) ]
    random.Random( f"{seed}:answers" ).shuffle( answers )
    random.Random( f"{seed}:forecasts" ).shuffle( forecasts )
    return answers, forecasts


def write_sample( pairs_path, cards_path, out_dir, seed, per_type=PER_TYPE, mismatch_share=MISMATCH_SHARE ):
    """
    Draw from a pairs file and write the sample, the two reader files and the receipt, once.

    Requires:
        - pairs_path and cards_path name JSON Lines files of pairs and of cards; out_dir is a folder path

    Ensures:
        - writes SAMPLE_FILE, ANSWERS_FILE, FORECASTS_FILE and DRAW_FILE under out_dir, making the folder
        - DRAW_FILE also records the sha256 of the pairs file, the cards file and the three files written
        - returns the receipt

    Raises:
        - FileExistsError when any of the four is already there, and writes nothing
        - ValueError as draw_sample and card_rows raise it, and writes nothing
    """
    out   = pathlib.Path( out_dir )
    names = ( SAMPLE_FILE, ANSWERS_FILE, FORECASTS_FILE )
    for name in names + ( DRAW_FILE, ):
        if ( out / name ).exists(): raise FileExistsError( f"{out / name} exists: a sample is drawn once" )
    sample, receipt    = draw_sample( jsonl_file.read_jsonl( pathlib.Path( pairs_path ) ), seed, per_type, mismatch_share )
    cards              = card_rows( cards_path, sorted( { row[ "notification_id" ] for row in sample } ) )
    answers, forecasts = reader_files( sample, cards, seed )
    out.mkdir( parents=True, exist_ok=True )
    for name, rows in zip( names, ( sample, answers, forecasts ) ):
        with open( out / name, "x", encoding="utf-8" ) as handle:
            handle.writelines( json.dumps( row, sort_keys=True ) + "\n" for row in rows )
    receipt.update( pairs_sha256=file_sha256( str( pairs_path ) ), cards_sha256=file_sha256( str( cards_path ) ), files={ name: file_sha256( str( out / name ) ) for name in names } )
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
    parser.add_argument( "--cards", required=True, help="one row per card, written beside the pairs" )
    parser.add_argument( "--out-dir", required=True )
    parser.add_argument( "--seed", type=int, required=True )
    parser.add_argument( "--per-type", type=int, default=PER_TYPE, help="the size recorded on the row" )
    parser.add_argument( "--mismatch-share", type=float, default=MISMATCH_SHARE )
    args = parser.parse_args( argv )
    try:
        receipt = write_sample( args.pairs, args.cards, args.out_dir, args.seed, args.per_type, args.mismatch_share )
    except ( ValueError, FileExistsError ) as error:
        print( error, file=sys.stderr )
        return EXIT_REFUSED
    print( json.dumps( receipt, indent=2, sort_keys=True ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
