r"""
Rick's offline page for the forecast-pair truth labels of the judge validation.

Section A is a seeded blind share of the pairs. It shows the card, its options, the full answer
and the forecast, and no reader's label. Section B holds every pair on which the two readers
differ about material_error, with both readers' labels beside it. A pair in both sections shows
its reader labels only after it has been labelled in section A. The page needs no network.

Its inputs are the two files draw.py writes for the readers and each reader's labels file. Run:

    python -m cosa.research.judge_validation.pair_page --answers reader-answers.jsonl \\
        --forecasts reader-forecasts.jsonl --labels one=labels.jsonl --labels two=labels.jsonl \\
        --seed <seed> --out pair-labels.html
"""
import argparse
import hashlib
import json
import pathlib
import sys

from cosa.repo.labelling import adjudicate as adj
from cosa.repo.labelling import confirm as cf
from cosa.repo.labelling import errors as er
from cosa.repo.labelling import rick_page as rp
from cosa.utils import jsonl_file
from cosa.utils.file_hash import file_sha256

TEMPLATE_RELATIVE = "/src/cosa/research/judge_validation/pair-page-template.html"
SECTION_BLIND     = "A"
SECTION_DISPUTES  = "B"
SHARE             = 0.2
CHOICES           = ( "yes", "no", "cant_tell" )
KINDS             = ( "false permission", "missed prerequisite", "unwarranted refusal", "different action", "invented condition", "none" )
READER_FIELDS     = ( "material_error", "kind", "atom", "note" )


def read_pairs( answers_path, forecasts_path ):
    """
    Join each forecast to the card and answer it is about.

    Requires:
        - answers_path has one JSON line per pair: pair_id, response_type, message, abstract, options, answer
        - forecasts_path has one JSON line per pair: pair_id, field_key, predicted_text

    Ensures:
        - returns { pair_id: row } where a row holds both files' fields
        - no other field of either file is carried, so an arm or a model cannot reach the page

    Raises:
        - LabellingError BAD_ITEM for no pairs, a pair id repeated in either file, or a pair that only one of the files holds
        - OSError, ValueError or KeyError for a file that cannot be read as stated
    """
    held = []
    for path in ( answers_path, forecasts_path ):
        rows  = jsonl_file.read_jsonl( path )
        by_id = { row[ "pair_id" ]: row for row in rows }
        if len( by_id ) != len( rows ): raise er.LabellingError( er.BAD_ITEM, f"{path}: a pair id appears twice" )
        held.append( by_id )
    cards, forecasts = held
    if not forecasts: raise er.LabellingError( er.BAD_ITEM, "the forecasts file holds no pairs" )
    odd = sorted( set( cards ) ^ set( forecasts ) )
    if odd: raise er.LabellingError( er.BAD_ITEM, f"pairs held by only one file: {len( odd )}, for example {odd[ :3 ]}" )
    return { pair_id: { "pair_id": pair_id, "field_key": row[ "field_key" ], "predicted_text": row[ "predicted_text" ],
                        **{ key: cards[ pair_id ][ key ] for key in ( "response_type", "message", "abstract", "options", "answer" ) } }
             for pair_id, row in forecasts.items() }


def read_reader( path, pair_ids ):
    """
    Read one reader's labels and check there is one for every pair and no other.

    Requires:
        - path has one JSON line per pair: pair_id, material_error, kind, atom, note

    Ensures:
        - returns { pair_id: { material_error, kind, atom, note } }

    Raises:
        - LabellingError BAD_LABEL for a repeated, missing or unknown pair id, or a material_error that is not true or false
    """
    labels = {}
    for row in jsonl_file.read_jsonl( path ):
        pair_id = row[ "pair_id" ]
        if pair_id in labels: raise er.LabellingError( er.BAD_LABEL, f"{path}: pair {pair_id} is labelled twice" )
        if not isinstance( row[ "material_error" ], bool ): raise er.LabellingError( er.BAD_LABEL, f"{path}: pair {pair_id}: material_error is not true or false" )
        labels[ pair_id ] = { key: row[ key ] for key in READER_FIELDS }
    odd = sorted( set( labels ) ^ set( pair_ids ) )
    if odd: raise er.LabellingError( er.BAD_LABEL, f"{path}: labels and pairs differ on {len( odd )} ids, for example {odd[ :3 ]}" )
    return labels


def draw_blind( pair_ids, seed, share=SHARE ):
    """
    Draw section A, the share Rick labels without seeing any label.

    Requires:
        - pair_ids are distinct strings; seed is non-empty text; share is above 0 and below 1

    Ensures:
        - returns { seed, share, population, ids, ids_sha256 }, the ids drawn by confirm.blind_sample_ids and sorted
        - the same ids and seed give the same draw whatever their order
    """
    ids = cf.blind_sample_ids( list( pair_ids ), seed, share )
    return { "seed": seed, "share": share, "population": len( pair_ids ), "ids": ids, "ids_sha256": rp.ids_sha256( ids ) }


def disputed_ids( first, second ):
    """
    Name the pairs on which the two readers differ about material_error.

    Requires:
        - first and second are read_reader results over the same pairs

    Ensures:
        - returns the pair ids, sorted; a difference in kind, atom or note alone is not a dispute
    """
    as_choices = lambda labels: [ { "item_id": i, "choice": str( row[ "material_error" ] ), "symbols": [] } for i, row in labels.items() ]
    return adj.disputes( as_choices( first ), as_choices( second ) )


def options_text( options ):
    """
    Write a card's stored options as the lines the page shows.

    Requires:
        - options is None, or a stored schema { "questions": [ { header, question, options: [ { label, description } ] } ] }

    Ensures:
        - returns "" for None
        - returns each question as "header: question" and each of its options as "- label: description"
        - any other shape is returned as indented JSON, so nothing on the card is hidden
    """
    if options is None: return ""
    try:
        lines = []
        for question in options[ "questions" ]:
            lines.append( f"{question[ 'header' ]}: {question[ 'question' ]}" )
            for option in question.get( "options" ) or []:
                detail = option.get( "description" )
                lines.append( f"- {option[ 'label' ]}" + ( f": {detail}" if detail else "" ) )
        return "\n".join( lines )
    except ( KeyError, TypeError, AttributeError ):
        return json.dumps( options, indent=1, ensure_ascii=False )


def answer_text( answer ):
    """
    Write the stored answer as the lines the page shows.

    Requires:
        - answer is a string or None; a multiple-choice or batch answer is JSON text { "answers": { header: value } }

    Ensures:
        - returns "header: value" lines for such JSON, a list value joined by commas
        - returns any other string unchanged, and "" for None
    """
    if answer is None: return ""
    try:
        picked = json.loads( answer )[ "answers" ].items()
    except ( ValueError, KeyError, TypeError, AttributeError ):
        return answer
    return "\n".join( f"{header}: {', '.join( map( str, value ) ) if isinstance( value, list ) else value}" for header, value in picked )


def page_items( pairs, blind_ids, dispute_ids, readers ):
    """
    Build what the page embeds, section A first.

    Requires:
        - pairs is read_pairs' result; blind_ids and dispute_ids are ids of it
        - readers maps each reader's name to its read_reader result

    Ensures:
        - returns one dict per section entry, in id order within a section: key, pair_id, section, card_type, card_text, abstract, options, question, answer, forecast, readers
        - key is "<section>:<pair_id>", unique even for a pair that is in both sections
        - a section A entry has an empty readers list, whatever the readers said
        - a section B entry lists each reader's name, material_error, kind, atom and note
    """
    out = []
    for section, ids in ( ( SECTION_BLIND, blind_ids ), ( SECTION_DISPUTES, dispute_ids ) ):
        for pair_id in sorted( ids ):
            pair  = pairs[ pair_id ]
            shown = [] if section == SECTION_BLIND else [ dict( labels[ pair_id ], name=name ) for name, labels in readers.items() ]
            out.append( { "key": f"{section}:{pair_id}", "pair_id": pair_id, "section": section, "card_type": pair[ "response_type" ],
                          "card_text": pair[ "message" ], "abstract": pair[ "abstract" ] or "", "options": options_text( pair[ "options" ] ),
                          "question": pair[ "field_key" ], "answer": answer_text( pair[ "answer" ] ), "forecast": pair[ "predicted_text" ] or "",
                          "readers": shown } )
    return out


def render_page( items, title ):
    """
    Build the one-file page.

    Requires:
        - items is page_items' result; title is non-empty text

    Ensures:
        - returns the HTML with the items embedded and no reference to any outside script, style, font or address
        - the page id is rick_page.page_id of the item keys

    Raises:
        - LabellingError BAD_ITEM for no items or a blank title
    """
    return rp.fill_page( TEMPLATE_RELATIVE, items, title, [ item[ "key" ] for item in items ],
                         { "__CHOICES_JSON__": rp.embed_json( list( CHOICES ) ), "__KINDS_JSON__": rp.embed_json( list( KINDS ) ) } )


def main( argv=None ):
    """
    Build Rick's page from the reader files.

    Requires:
        - argv holds --answers, --forecasts, --labels name=file twice, --seed and --out, with optional --title and --share

    Ensures:
        - writes the page to --out and its receipt to <out>.receipt.json: the draw, the disputed ids, the page id and the sha256 of every input and of the page
        - prints the receipt and returns 0
        - returns 2, writing nothing, for a file that cannot be read, labels that do not fit the pairs, other than two readers, or an output that exists
    """
    ap = argparse.ArgumentParser( description="Build Rick's page for the forecast-pair truth labels." )
    ap.add_argument( "--answers", required=True )
    ap.add_argument( "--forecasts", required=True )
    ap.add_argument( "--labels", action="append", required=True, metavar="NAME=FILE" )
    ap.add_argument( "--seed", required=True )
    ap.add_argument( "--share", type=float, default=SHARE )
    ap.add_argument( "--out", required=True )
    ap.add_argument( "--title", default="Forecast pairs: is there a material error?" )
    args = ap.parse_args( argv )
    out, receipt_path = pathlib.Path( args.out ), pathlib.Path( args.out + ".receipt.json" )
    try:
        files = dict( spec.split( "=", 1 ) for spec in args.labels )
        if len( files ) != 2 or len( args.labels ) != 2: raise er.LabellingError( er.BAD_ITEM, "--labels names two different readers" )
        pairs   = read_pairs( args.answers, args.forecasts )
        readers = { name: read_reader( path, pairs ) for name, path in files.items() }
        draw    = draw_blind( list( pairs ), args.seed, args.share )
        differ  = disputed_ids( *readers.values() )
        items   = page_items( pairs, draw[ "ids" ], differ, readers )
        html    = render_page( items, args.title )
        inputs  = { name: file_sha256( path )
                    for name, path in [ ( "answers", args.answers ), ( "forecasts", args.forecasts ), *files.items() ] }
    except ( OSError, ValueError, KeyError, TypeError, er.LabellingError ) as error:
        return er.fail( f"cannot build the page: {error!r}", 2 )
    if out.exists() or receipt_path.exists(): return er.fail( f"refused: {out} or its receipt exists, and a page is never overwritten", 2 )
    receipt = { "draw": draw, "disputed_ids": differ, "items": len( items ), "page_id": rp.page_id( [ item[ "key" ] for item in items ] ),
                "inputs_sha256": inputs, "page_sha256": hashlib.sha256( html.encode( "utf-8" ) ).hexdigest() }
    out.write_text( html, encoding="utf-8" )
    receipt_path.write_text( json.dumps( receipt, indent=1, sort_keys=True ) + "\n", encoding="utf-8" )
    print( json.dumps( receipt, indent=1, sort_keys=True ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
