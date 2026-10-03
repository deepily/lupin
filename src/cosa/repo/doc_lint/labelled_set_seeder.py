"""
Seeding script for the labelled before/after set (row 13878d1c; build spec on row dad61023, parts 1 to 4).

A script, never a model, chooses what is removed or weakened in a real docstring. A blind writer
model then rewords the cut text, seeing neither the span nor the original. A second seat checks the
result. Four phases, each its own command:

    plan      script only, no model call: unit split, picks, cuts, weak texts, writer tasks
    write     blind writer calls, one shot each, under a per-model call cap that refuses
    verify    writes the second seat's input files, and checks nothing is missing
    assemble  joins writer output and the second seat's file into pairs, keys and a manifest
    manifest  writes the dev-visible root manifest

Re-running plan with the same inputs and seeds gives byte-identical output. Phase 2 outputs are kept
in a ledger and are never regenerated silently.

Known limits (stated, not hidden):
    - a weaken tests only the five coded classes; a clean result says nothing about subtler weakening
    - the writer is still a Claude model, so a family effect is untouched (no human arm is built)
    - the "has a verb" test in the cut-repair rule is a word-list heuristic, not a parser
    - phase 2 stops before the reserve set and the Dart set: they need a second call-cap figure from Rick
"""

import argparse
import difflib
import hashlib
import json
import math
import os
import random
import re
import secrets
import sys

import cosa.utils.util as cu
from cosa.repo.doc_lint import claim_extractor, labelled_pairs, model_transport

# One table; every number is a parameter and none is hard-coded where it is used.
SIZES = {
    "dev" : { "pairs": 70,  "delete": 14, "weaken": 14, "short": 12, "class_floor": 2, "relocate": 8,  "paraphrase": 34 },
    "A"   : { "pairs": 150, "delete": 32, "weaken": 32, "short": 16, "class_floor": 4, "relocate": 20, "paraphrase": 66 },
    "B"   : { "pairs": 190, "delete": 47, "weaken": 47, "short": 59, "class_floor": 5, "relocate": 30, "paraphrase": 66 },
}
STRATA_BANDS = ( ( "S", 3, 6 ), ( "M", 7, 12 ), ( "L", 13, 10 ** 9 ) )
STRATA_MIX   = { "S": 0.3, "M": 0.4, "L": 0.3 }
KINDS        = ( "weaken", "delete", "relocate", "paraphrase" )
SEEDED_KINDS = ( "weaken", "delete" )
SHORT_WORDS  = ( 2, 3 )
WEAKEN_CLASSES = ( "negation", "quantifier", "modal", "number", "qualifier" )

SHARED_CALL_LEDGER = "/mnt/DATA01/include/www.deepily.ai/projects-data/lupin/fable-call-ledger.jsonl"
WRITER_SPLITS      = ( "dev", "gate" )

REWORD_INSTRUCTION       = "Reword every sentence. Keep the meaning, add nothing, drop nothing."
DESIGN_PROSE_INSTRUCTION = "Write this sentence as a paragraph of design prose."
INSTRUCTIONS             = { "reword": REWORD_INSTRUCTION, "design": DESIGN_PROSE_INSTRUCTION }
WRITER_SYSTEM_PROMPT     = "You rewrite text exactly as instructed. Reply with the rewritten text only."

# (strong, weak, ambiguous). A pair flagged ambiguous is excluded: it would change style, not meaning.
WEAKEN_TABLE = {
    "negation"   : [ ( "is", "is not", False ), ( "are", "are not", False ), ( "does", "does not", False ),
                     ( "never", "sometimes", False ), ( "can", "cannot", True ) ],
    "quantifier" : [ ( "always", "usually", False ), ( "all", "most", False ), ( "every", "some", False ),
                     ( "each", "some", False ), ( "any", "some", True ) ],
    "modal"      : [ ( "must", "may", False ), ( "shall", "should", False ), ( "will", "might", False ),
                     ( "should", "could", True ) ],
    "qualifier"  : [ ( "only", "", False ), ( "exactly", "", False ), ( "at least", "", False ) ],
}
NUMBER_WORDS = { "one": "two", "two": "three", "three": "four", "four": "five", "five": "six" }
NUMBER_REGEX = re.compile( r"\b\d+\b" )

OPENERS     = ( "which", "when", "if", "unless", "because", "while", "until", "before", "after", "where", "but", "and then", "so that" )
OPENER_RE   = re.compile( r"(?<=\s)(?:" + "|".join( OPENERS ) + r")(?=\s)" )
PUNCT_RE    = re.compile( r"[,;:—]" )
PAREN_RE    = re.compile( r"\([^()\n]*\)" )
SENTENCE_RE = re.compile( r"(?<=[.!?])\s+" )
EDGE_PUNCT  = " \t\n.,;:!?"
PRONOUNS    = frozenset( "this it that these those they such its".split() )
START_DANGLERS = frozenset( "and or but which that of to with for because so while".split() )
END_DANGLERS   = frozenset( "and or but if when which that the a an of to with for in on because so while".split() )
AUX_VERBS   = frozenset( "is are was were be been am do does did has have had can could may might must shall should will would".split() )
VERB_SUFFIXES = ( "s", "ed", "ing" )

DEFAULT_STOPLIST = os.path.join( os.path.dirname( os.path.abspath( __file__ ) ), "labelled_set_stoplist.txt" )
GATE_SPLITS      = ( "gate", "gate-reserve" )


def read_jsonl( path ):
    """Return the records of a JSON Lines file, skipping blank lines."""
    with open( path, encoding="utf-8" ) as f:
        return [ json.loads( line ) for line in f if line.strip() ]


def write_jsonl( path, rows ):
    """Write rows as JSON Lines with sorted keys, so the same rows give the same bytes."""
    os.makedirs( os.path.dirname( os.path.abspath( path ) ), exist_ok=True )
    with open( path, "w", encoding="utf-8" ) as f:
        for row in rows: f.write( json.dumps( row, sort_keys=True ) + "\n" )


def write_json( path, obj ):
    """Write one JSON document with sorted keys and a trailing newline."""
    os.makedirs( os.path.dirname( os.path.abspath( path ) ), exist_ok=True )
    with open( path, "w", encoding="utf-8" ) as f:
        f.write( json.dumps( obj, sort_keys=True, indent=2 ) + "\n" )


def sha256_file( path ):
    """Return the sha256 hex digest of a file's bytes."""
    with open( path, "rb" ) as f: return hashlib.sha256( f.read() ).hexdigest()


def load_stoplist( path ):
    """
    Read the stoplist file: one word per line, '#' lines and blanks ignored, lower-cased.

    Requires:
        - path names a readable text file
    """
    with open( path, encoding="utf-8" ) as f:
        return frozenset( line.strip().lower() for line in f if line.strip() and not line.startswith( "#" ) )


def stratum_of( old ):
    """Return "S", "M" or "L" by the docstring's line count (S 3-6, M 7-12, L 13+), or None under 3 lines."""
    lines = len( old.strip().splitlines() )
    for name, low, high in STRATA_BANDS:
        if low <= lines <= high: return name
    return None


def unit_of( file ):
    """Return the package directory of a file path: the unit that is never split across dev, gate and reserve."""
    return os.path.dirname( file )


def words_of( text ):
    """Count words the way the spec does: split() on whitespace."""
    return len( text.split() )


def is_short( span_words ):
    """Say whether a span of this many words is short (2 or 3)."""
    return SHORT_WORDS[ 0 ] <= span_words <= SHORT_WORDS[ 1 ]


def sentences_of( text ):
    """Split a text into sentences at terminal punctuation followed by whitespace."""
    return [ s for s in SENTENCE_RE.split( text.strip() ) if s ]


def phrase_units( old ):
    """
    Return the phrase units of old as ( start, end ) offsets: clauses, parentheticals and list items.

    Requires:
        - old is a str

    Ensures:
        - boundaries are sentence ends, line ends, punctuation ( , ; : em dash ), parentheses and the coded clause openers
        - a parenthetical is one unit; every offset pair is stripped of edge space and punctuation
        - two adjacent units in one sentence also yield their joined stretch, for longer spans
        - never cuts mid-phrase; offsets index old itself
    """
    regions = []
    cursor  = 0
    for match in PAREN_RE.finditer( old ):
        regions.append( ( cursor, match.start(), False ) )
        regions.append( ( match.start(), match.end(), True ) )
        cursor = match.end()
    regions.append( ( cursor, len( old ), False ) )
    units = []
    for start, end, is_paren in regions:
        if is_paren:
            units.append( ( start, end, True ) )
            continue
        cuts = [ start ]
        for line_match in re.finditer( r"\n[ \t]*\n|(?<=[.!?])\s", old[ start:end ] ): cuts.append( start + line_match.start() )
        for m in PUNCT_RE.finditer( old[ start:end ] ): cuts.append( start + m.start() )
        for m in OPENER_RE.finditer( old[ start:end ] ): cuts.append( start + m.start() )
        cuts = sorted( set( cuts ) ) + [ end ]
        for left, right in zip( cuts, cuts[ 1: ] ):
            units.append( ( left, right, False ) )
    stripped = []
    for left, right, is_paren in units:
        text  = old[ left:right ]
        lead  = len( text ) - len( text.lstrip( EDGE_PUNCT ) )
        tail  = len( text.rstrip( EDGE_PUNCT ) )
        if is_paren: lead, tail = 0, len( text )
        if tail > lead: stripped.append( ( left + lead, left + tail ) )
    out = list( stripped )
    for first, second in zip( stripped, stripped[ 1: ] ):
        between = old[ first[ 1 ]:second[ 0 ] ]
        if not re.search( r"[.!?]\s|\n", between + " " ) and "(" not in between and ")" not in between: out.append( ( first[ 0 ], second[ 1 ] ) )
    return sorted( set( out ) )


def repair( text ):
    """
    Repair spacing and stray punctuation after a cut. Nothing else is edited.

    Ensures:
        - runs of blanks become one space; space before , ; : . ! ? goes; doubled , ; : collapse; a comma before a full stop goes
        - empty parentheses go; a line that starts with , ; : loses it; the first letter of a sentence is capitalised
    """
    text = re.sub( r"\(\s*\)", "", text )
    text = re.sub( r"[ \t]+", " ", text )
    text = re.sub( r"[ \t]+([,;:.!?])", r"\1", text )
    text = re.sub( r"([,;:])(?:\s*[,;:])+", r"\1", text )
    text = re.sub( r",\s*([.!?])", r"\1", text )
    text = re.sub( r"(?m)^[ \t]*[,;:][ \t]*", "", text )
    text = re.sub( r"[ \t]+$", "", text, flags=re.M )
    text = re.sub( r"\n[ \t]+", "\n", text )
    text = re.sub( r"(^|[.!?]\s+)([a-z])", lambda m: m.group( 1 ) + m.group( 2 ).upper(), text )
    return text.strip()


def cut_text( old, span ):
    """Return old with the ( start, end ) span removed and the join repaired."""
    return repair( old[ :span[ 0 ] ] + " " + old[ span[ 1 ]: ] )


def bad_cut( old, cut ):
    """
    Return a reason code when a cut leaves broken text, else None. The reasons are logged by count.

    Ensures:
        - "EMPTY" when nothing is left; "NO_VERB" when a changed sentence has no verb-like word;
          "DANGLING" when a changed sentence starts or ends on a conjunction, article or preposition;
          "ORPHAN" when a pronoun now opens the text or a sentence whose antecedent sentence was cut
    """
    if not cut.strip(): return "EMPTY"
    old_sentences = [ " ".join( s.split() ) for s in sentences_of( old ) ]
    new_sentences = [ " ".join( s.split() ) for s in sentences_of( cut ) ]
    for sentence in new_sentences:
        if sentence in old_sentences: continue
        tokens = [ t.strip( EDGE_PUNCT + "()" ).lower() for t in sentence.split() ]
        tokens = [ t for t in tokens if t ]
        if not tokens: return "EMPTY"
        if not any( t in AUX_VERBS or ( len( t ) > 3 and t.endswith( VERB_SUFFIXES ) ) for t in tokens ): return "NO_VERB"
        if tokens[ 0 ] in START_DANGLERS or tokens[ -1 ] in END_DANGLERS: return "DANGLING"
    first_word = new_sentences[ 0 ].split()[ 0 ].strip( EDGE_PUNCT ).lower()
    if first_word in PRONOUNS and old_sentences[ 0 ].split()[ 0 ].strip( EDGE_PUNCT ).lower() not in PRONOUNS: return "ORPHAN"
    for before, after in zip( old_sentences, old_sentences[ 1: ] ):
        if before not in new_sentences and after in new_sentences and after.split()[ 0 ].strip( EDGE_PUNCT ).lower() in PRONOUNS: return "ORPHAN"
    return None


def quotable_once( old, span_text ):
    """
    Say whether a span passes the harness's own quote test, occurs once in old, and its quote occurs once.

    Ensures:
        - locate_quote is the one imported from the harness, called with the frozen floors
        - the span occurs exactly once after the harness's normalisation; that implies once as written, because
          normalising only maps characters, so the loader's own raw count agrees (a raw-count line here could never fire)
    """
    if claim_extractor.locate_quote( span_text, old ) is None: return False
    normalized, _ = claim_extractor.normalize( old )
    wanted, _     = claim_extractor.normalize( span_text )
    return normalized.count( wanted ) == 1


def span_ok( old, span, stoplist ):
    """Say whether a ( start, end ) span is a seedable span: 2+ words, not all stoplist words, quotable once."""
    text = old[ span[ 0 ]:span[ 1 ] ]
    if words_of( text ) < 2: return False
    if all( w.strip( EDGE_PUNCT + "()" ).lower() in stoplist for w in text.split() ): return False
    return quotable_once( old, text )


def delete_candidates( old, stoplist ):
    """
    Return the seedable deletions of one docstring, each { span, span_text, cut }.

    Ensures:
        - spans are phrase units that pass span_ok; cuts that bad_cut refuses are left out and counted
    """
    out, refused = [], {}
    for span in phrase_units( old ):
        if not span_ok( old, span, stoplist ): continue
        cut    = cut_text( old, span )
        reason = bad_cut( old, cut )
        if reason is not None:
            refused[ reason ] = refused.get( reason, 0 ) + 1
            continue
        out.append( { "span": span, "span_text": old[ span[ 0 ]:span[ 1 ] ], "cut": cut } )
    return out, refused


def _match_case( weak, strong_text ):
    """Give weak the capital of strong_text's first letter."""
    return weak[ :1 ].upper() + weak[ 1: ] if strong_text[ :1 ].isupper() else weak


def weaken_edits( old ):
    """
    Return every single-word coded edit of old: { class, changed_token, start, end, replacement }.

    Ensures:
        - table pairs flagged ambiguous are never produced
        - a qualifier deletion takes the word and one following space
        - a number edit adds one to a stated integer (under 100) or steps a number word up one
    """
    edits = []
    for cls, rows in WEAKEN_TABLE.items():
        for strong, weak, ambiguous in rows:
            if ambiguous: continue
            for m in re.finditer( r"\b" + re.escape( strong ) + r"\b", old, flags=re.I ):
                end = m.end() + 1 if cls == "qualifier" and old[ m.end():m.end() + 1 ] == " " else m.end()
                edits.append( { "class": cls, "changed_token": m.group( 0 ), "start": m.start(), "end": end,
                                "replacement": _match_case( weak, m.group( 0 ) ) } )
    for m in NUMBER_REGEX.finditer( old ):
        if int( m.group( 0 ) ) < 100: edits.append( { "class": "number", "changed_token": m.group( 0 ), "start": m.start(), "end": m.end(), "replacement": str( int( m.group( 0 ) ) + 1 ) } )
    for m in re.finditer( r"\b(" + "|".join( NUMBER_WORDS ) + r")\b", old, flags=re.I ):
        edits.append( { "class": "number", "changed_token": m.group( 0 ), "start": m.start(), "end": m.end(), "replacement": _match_case( NUMBER_WORDS[ m.group( 0 ).lower() ], m.group( 0 ) ) } )
    return sorted( edits, key=lambda e: ( e[ "start" ], e[ "class" ] ) )


def apply_edit( old, edit ):
    """Return old with one weaken edit applied; the rest of old is untouched."""
    return old[ :edit[ "start" ] ] + edit[ "replacement" ] + old[ edit[ "end" ]: ]


def edit_confined_to_token( old, weak, changed_token ):
    """
    Say whether weak differs from old at exactly one word-level spot, and that spot is the changed token.

    Ensures:
        - one differing opcode over whitespace-split words; a replace or delete must remove only the token's words;
          an insert (negation "is" to "is not") must follow the token
    """
    a, b = old.split(), weak.split()
    ops  = [ op for op in difflib.SequenceMatcher( None, a, b, autojunk=False ).get_opcodes() if op[ 0 ] != "equal" ]
    if len( ops ) != 1: return False
    tag, i1, i2, _, _ = ops[ 0 ]
    token_words = changed_token.lower().split()
    if tag == "insert": return i1 >= 1 and a[ i1 - 1 ].strip( EDGE_PUNCT ).lower() == token_words[ -1 ]
    return [ w.strip( EDGE_PUNCT ).lower() for w in a[ i1:i2 ] ] == token_words


def weaken_candidates( old, stoplist ):
    """
    Return the seedable weakenings of one docstring.

    Ensures:
        - each is { class, changed_token, span, span_text, weak_text }
        - the span is the smallest phrase unit holding the changed word, or a 2 to 3 word window around it
          (a short span); every span passes span_ok and holds the changed token
        - a weak text that is not confined to the changed token is left out
    """
    units = phrase_units( old )
    out   = []
    for edit in weaken_edits( old ):
        weak = apply_edit( old, edit )
        if not edit_confined_to_token( old, weak, edit[ "changed_token" ] ): continue
        holding = [ u for u in units if u[ 0 ] <= edit[ "start" ] and edit[ "end" ] <= u[ 1 ] or u[ 0 ] <= edit[ "start" ] < u[ 1 ] ]
        spans   = [ min( holding, key=lambda u: u[ 1 ] - u[ 0 ] ) ] if holding else []
        words   = list( re.finditer( r"\S+", old ) )
        at      = next( ( i for i, w in enumerate( words ) if w.start() <= edit[ "start" ] < w.end() ), None )
        for size in SHORT_WORDS:
            for lo in range( max( 0, at - size + 1 ), at + 1 ):
                if lo + size <= len( words ) and lo <= at < lo + size:
                    first, last = words[ lo ], words[ lo + size - 1 ]
                    window = ( first.start(), last.end() )
                    if "\n" not in old[ window[ 0 ]:window[ 1 ] ]: spans.append( ( window[ 0 ], window[ 1 ] ) )
        for span in sorted( set( spans ) ):
            stripped = ( span[ 0 ] + ( len( old[ span[ 0 ]:span[ 1 ] ] ) - len( old[ span[ 0 ]:span[ 1 ] ].lstrip( EDGE_PUNCT ) ) ),
                         span[ 1 ] - ( len( old[ span[ 0 ]:span[ 1 ] ] ) - len( old[ span[ 0 ]:span[ 1 ] ].rstrip( EDGE_PUNCT ) ) ) )
            text = old[ stripped[ 0 ]:stripped[ 1 ] ]
            if edit[ "changed_token" ] not in text or not span_ok( old, stripped, stoplist ): continue
            out.append( { "class": edit[ "class" ], "changed_token": edit[ "changed_token" ], "span": stripped, "span_text": text, "weak_text": weak } )
    return out


def relocate_candidates( old ):
    """Return the ( sentence, cut text ) choices for a relocate pair: any one sentence of a text of 2+ sentences, cut whole."""
    sentences = sentences_of( old )
    out = []
    if len( sentences ) < 2: return out
    for sentence in sentences:
        if old.count( sentence ) != 1: continue
        rest = repair( old.replace( sentence, " " ) )
        if rest.strip(): out.append( { "sentence": sentence, "cut": rest } )
    return out


def candidates_for( kind, old, stoplist ):
    """Return the candidates of one docstring for one kind; paraphrase has exactly one (the docstring)."""
    if kind == "delete": return delete_candidates( old, stoplist )[ 0 ]
    if kind == "weaken": return weaken_candidates( old, stoplist )
    if kind == "relocate": return relocate_candidates( old )
    return [ { "text": old } ]


def quotas( total, mix ):
    """Split total by mix with largest remainders, so the parts sum to total exactly."""
    raw   = { k: total * v for k, v in mix.items() }
    parts = { k: int( math.floor( v ) ) for k, v in raw.items() }
    for k in sorted( raw, key=lambda k: ( -( raw[ k ] - parts[ k ] ), k ) )[ :total - sum( parts.values() ) ]: parts[ k ] += 1
    return parts


class Shortfall( Exception ):
    """The pool cannot supply a kind, stratum, class or short floor; names which."""


def pick( kind, docs, size, short_need, class_floor, mix, used, rng ):
    """
    Choose size docstrings and one candidate each for one kind, meeting the short, class and stratum quotas.

    Requires:
        - docs is a list of { pool_id, old, stratum, cands } sorted by pool_id; used is a set of pool ids already taken

    Ensures:
        - returns a list of ( doc, candidate ) of length size, or raises Shortfall naming what is missing
        - a stratum never exceeds its quota; the short count and each class floor are met or Shortfall is raised
        - a floor is never relaxed
    """
    strata = quotas( size, mix )
    need_c = { c: class_floor for c in WEAKEN_CLASSES } if kind == "weaken" else {}
    need_s = short_need if kind in SEEDED_KINDS else 0
    chosen, taken, count = [], set( used ), { s: 0 for s in strata }
    options = [ ( d, c ) for d in docs for c in d[ "cands" ] if d[ "pool_id" ] not in taken ]
    while len( chosen ) < size:
        best_score, best = -1, []
        for d, c in options:
            if d[ "pool_id" ] in taken or d[ "stratum" ] not in strata or count[ d[ "stratum" ] ] >= strata[ d[ "stratum" ] ]: continue
            score = 0
            if need_s > 0 and is_short( words_of( c[ "span_text" ] ) ): score += 2
            if need_c.get( c.get( "class" ), 0 ) > 0: score += 1
            if score > best_score: best_score, best = score, [ ( d, c ) ]
            elif score == best_score: best.append( ( d, c ) )
        if not best: raise Shortfall( f"{kind}: only {len( chosen )} of {size} pairs can be drawn (strata quota {strata}, drawn {count})" )
        d, c = best[ rng.randrange( len( best ) ) ]
        chosen.append( ( d, c ) )
        taken.add( d[ "pool_id" ] )
        count[ d[ "stratum" ] ] += 1
        if need_s > 0 and is_short( words_of( c[ "span_text" ] ) ): need_s -= 1
        if c.get( "class" ) in need_c: need_c[ c[ "class" ] ] -= 1
    if need_s > 0: raise Shortfall( f"{kind}: {need_s} short spans (2 to 3 words) short of the floor" )
    for cls, left in need_c.items():
        if left > 0: raise Shortfall( f"weaken: class {cls} is {left} short of its floor" )
    return chosen


def split_units( units, seed ):
    """Return units shuffled by seed, deterministic for a sorted input."""
    ordered = sorted( units )
    random.Random( seed ).shuffle( ordered )
    return ordered


def draw_split( docs_by_kind, unit_list, sizes, mix, short_per_kind, used_by_split, rng ):
    """Draw one split's picks from the docs whose units are in unit_list; returns { kind: [ ( doc, cand ) ] }."""
    units = set( unit_list )
    used  = set()
    out   = {}
    for kind in KINDS:
        docs = [ d for d in docs_by_kind[ kind ] if d[ "unit" ] in units ]
        out[ kind ] = pick( kind, docs, sizes[ kind ], short_per_kind, sizes[ "class_floor" ], mix, used, rng )
        used |= { d[ "pool_id" ] for d, _ in out[ kind ] }
    return out


def short_quota( sizes ):
    """Return how many short spans each seeded kind carries: ceil( floor / 2 )."""
    return int( math.ceil( sizes[ "short" ] / 2 ) )


def seed_search( pool, stoplist, gate_sizes, dev_sizes, mix, split_seed_start, tries, draw_seed, exclude=frozenset() ):
    """
    Search split seeds until dev, gate and reserve can each fill every kind and stratum.

    Requires:
        - pool is a list of { id, file, symbol, old }; ids unique

    Ensures:
        - units go whole to one of dev, gate, reserve; no file and no unit is shared
        - returns ( split_seed, { "dev": picks, "gate": picks, "gate-reserve": picks } )
        - gate and reserve use the same sizes and floors

    Raises:
        - Shortfall naming the last failure when no seed in the range works
    """
    docs = []
    for row in sorted( pool, key=lambda r: r[ "id" ] ):
        if row[ "id" ] in exclude: continue
        stratum = stratum_of( row[ "old" ] )
        if stratum is None: continue
        docs.append( { "pool_id": row[ "id" ], "file": row[ "file" ], "symbol": row[ "symbol" ], "old": row[ "old" ], "stratum": stratum, "unit": unit_of( row[ "file" ] ) } )
    docs_by_kind = { kind: [ dict( d, cands=candidates_for( kind, d[ "old" ], stoplist ) ) for d in docs ] for kind in KINDS }
    for kind in KINDS: docs_by_kind[ kind ] = [ d for d in docs_by_kind[ kind ] if d[ "cands" ] ]
    units  = sorted( { d[ "unit" ] for d in docs } )
    last   = None
    for attempt in range( tries ):
        seed    = split_seed_start + attempt
        shuffled = split_units( units, seed )
        third   = max( 1, len( shuffled ) // 3 )
        parts   = { "dev": shuffled[ :third ], "gate": shuffled[ third:2 * third ], "gate-reserve": shuffled[ 2 * third: ] }
        try:
            picks = {}
            for name, sizes in ( ( "dev", dev_sizes ), ( "gate", gate_sizes ), ( "gate-reserve", gate_sizes ) ):
                picks[ name ] = draw_split( docs_by_kind, parts[ name ], sizes, mix, short_quota( sizes ), None, random.Random( f"{draw_seed}|{name}|{seed}" ) )
            return seed, picks
        except Shortfall as e:
            last = e
    raise Shortfall( f"no split seed in {split_seed_start}..{split_seed_start + tries - 1} fills dev, gate and reserve; last: {last}" )


def build_split_plan( name, picks, seed ):
    """
    Turn one split's picks into pair records and writer tasks.

    Ensures:
        - pair ids p000.. are assigned after a seeded shuffle across kinds, so id order says nothing about kind
        - task ids are random-looking and unrelated to pair ids; the writer sees one text per task
        - the same instruction string serves delete, weaken and paraphrase texts; relocate also has a design-prose task
        - returns ( plan dict, writer task rows )
    """
    rng   = random.Random( f"{seed}|{name}|shuffle" )
    items = [ ( kind, d, c ) for kind in KINDS for d, c in picks[ kind ] ]
    rng.shuffle( items )
    pairs, tasks, task_rows = [], {}, []

    def new_task( role, pair_id, instruction, text ):
        task_id = "t%016x" % rng.getrandbits( 64 )
        tasks[ task_id ] = { "pair_id": pair_id, "role": role, "sha256": task_sha( INSTRUCTIONS[ instruction ], text ) }
        task_rows.append( { "task_id": task_id, "instruction": INSTRUCTIONS[ instruction ], "text": text } )

    for index, ( kind, d, c ) in enumerate( items ):
        pair_id = "p%03d" % index
        span_text = c.get( "span_text", "" )
        rec = { "id": pair_id, "pool_id": d[ "pool_id" ], "file": d[ "file" ], "symbol": d[ "symbol" ], "old": d[ "old" ], "kind": kind,
                "weaken_class": c.get( "class" ), "changed_token": c.get( "changed_token" ), "stratum": d[ "stratum" ],
                "x_span_in_old": span_text, "span_words": words_of( span_text ) if span_text else 0, "span_chars": len( span_text ),
                "short": is_short( words_of( span_text ) ) if span_text else False }
        if kind == "delete": new_task( "new", pair_id, "reword", c[ "cut" ] )
        elif kind == "weaken": new_task( "new", pair_id, "reword", c[ "weak_text" ] )
        elif kind == "paraphrase": new_task( "new", pair_id, "reword", c[ "text" ] )
        else:
            rec[ "x_span_in_old" ] = c[ "sentence" ]
            new_task( "new", pair_id, "reword", c[ "cut" ] )
            new_task( "linked_doc", pair_id, "design", c[ "sentence" ] )
        pairs.append( rec )
    rng.shuffle( task_rows )
    plan = { "split": name, "pairs": pairs, "tasks": tasks, "units": sorted( { d[ "unit" ] for _, d, _ in items } ) }
    plan[ "plan_sha256" ] = plan_hash( plan )
    return plan, task_rows


def refuse_gate_out_in_repo( path ):
    """
    Refuse an output directory that sits inside the repo, for the gate and reserve files.

    Raises:
        - ValueError if the real path of path is the project root or under it
    """
    root = os.path.realpath( cu.get_project_root() )
    real = os.path.realpath( path )
    if real == root or real.startswith( root + os.sep ): raise ValueError( f"{path} is inside the repo; gate and reserve files go outside it" )


def check_writer_model( writer, other_ids ):
    """
    Refuse a writer model that is any judge, extractor or escalation model (rule R.2).

    Raises:
        - ValueError if writer is empty or equals, ignoring case and edge space, one of other_ids
    """
    if not writer or not writer.strip(): raise ValueError( "--writer-model is required" )
    for role, model in other_ids.items():
        if model and model.strip().lower() == writer.strip().lower(): raise ValueError( f"writer model {writer!r} is the {role} model: rule R.2 forbids it" )


def task_sha( instruction, text ):
    """Return the sha256 of one writer task's instruction and text, so an output can be tied to the task it answered."""
    return hashlib.sha256( ( instruction + "\0" + text ).encode( "utf-8" ) ).hexdigest()


def plan_hash( plan ):
    """
    Return the sha256 of a split's plan: its units, its picks (file, span, class, stratum) and every task's content sha.

    Ensures:
        - a changed unit, span, class, stratum or task text changes the hash; the same plan gives the same hash
    """
    body = { "units": plan[ "units" ], "pairs": [ [ p[ "id" ], p[ "pool_id" ], p[ "file" ], p[ "kind" ], p[ "x_span_in_old" ], p[ "weaken_class" ], p[ "stratum" ] ] for p in plan[ "pairs" ] ],
             "tasks": sorted( [ tid, meta[ "pair_id" ], meta[ "role" ], meta[ "sha256" ] ] for tid, meta in plan[ "tasks" ].items() ) }
    return hashlib.sha256( json.dumps( body, sort_keys=True ).encode( "utf-8" ) ).hexdigest()


def check_plan_hash( plan ):
    """
    Refuse a plan whose stored plan_sha256 is not what its content hashes to now.

    Raises:
        - ValueError naming the split when the plan was edited after it was drawn
    """
    if plan.get( "plan_sha256" ) != plan_hash( plan ): raise ValueError( f"plan for {plan[ 'split' ]} does not match the hash taken when it was drawn" )


def check_ledger_identity( rows, model=None ):
    """
    Refuse a writer ledger whose rows disagree on the writer model or prompt, with each other or with now.

    Requires:
        - rows are writer-ledger rows; model is the writer model expected, or None to take the first row's

    Raises:
        - ValueError naming which differs: the model, or the prompt hash
    """
    if not rows: return
    want_model = rows[ 0 ][ "model" ] if model is None else model
    for row in rows:
        if row[ "model" ] != want_model: raise ValueError( f"ledger row {row[ 'task_id' ]} was written by model {row[ 'model' ]!r}, not {want_model!r}" )
        if row.get( "prompt_hash" ) != prompt_hash(): raise ValueError( f"ledger row {row[ 'task_id' ]} was written under prompt hash {row.get( 'prompt_hash' )!r}, not the current {prompt_hash()!r}" )


def prompt_hash():
    """Return the sha256 of the writer system prompt and the two instruction strings."""
    return hashlib.sha256( "\0".join( [ WRITER_SYSTEM_PROMPT, REWORD_INSTRUCTION, DESIGN_PROSE_INSTRUCTION ] ).encode( "utf-8" ) ).hexdigest()


def disjoint( picks_by_split ):
    """Say whether the splits share no file and no unit."""
    seen_files, seen_units = {}, {}
    for name, picks in picks_by_split.items():
        for kind in KINDS:
            for d, _ in picks[ kind ]:
                if seen_files.setdefault( d[ "file" ], name ) != name or seen_units.setdefault( d[ "unit" ], name ) != name: return False
    return True


def cmd_plan( args ):
    """
    Phase 1: no model call. Writes plan.json and writer_tasks.jsonl per split; gate and reserve go outside the repo.

    Returns the process exit code: 0 done, 2 refused.
    """
    gate_sizes = SIZES[ args.option ]
    dev_sizes  = SIZES[ "dev" ]
    if args.sizes_json:
        override = json.loads( args.sizes_json )
        gate_sizes, dev_sizes = override.get( "gate", gate_sizes ), override.get( "dev", dev_sizes )
    try:
        refuse_gate_out_in_repo( args.gate_out )
        stoplist = load_stoplist( args.stoplist )
        exclude  = frozenset( json.loads( open( args.exclude, encoding="utf-8" ).read() ) ) if args.exclude else frozenset()
        seed, picks = seed_search( read_jsonl( args.pool ), stoplist, gate_sizes, dev_sizes, STRATA_MIX, args.split_seed, args.split_tries, args.seed, exclude )
    except ( ValueError, Shortfall ) as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    if not disjoint( picks ):  # pragma: no cover - seed_search builds disjoint unit sets; this is the assertion the spec asks for
        print( "REFUSED: dev, gate and reserve share a file or a unit", file=sys.stderr )
        return 2
    plan_hashes = {}
    for name in ( "dev", "gate", "gate-reserve" ):
        plan, task_rows = build_split_plan( name, picks[ name ], args.seed if name == "dev" else args.gate_seed )
        base = os.path.join( args.out if name == "dev" else args.gate_out, name )
        plan[ "pool_sha" ] = sha256_file( args.pool )
        if name != "dev": plan[ "split_seed" ] = seed
        write_json( os.path.join( base, "plan.json" ), plan )
        write_jsonl( os.path.join( base, "writer_tasks.jsonl" ), task_rows )
        if name != "dev": plan_hashes[ name ] = plan[ "plan_sha256" ]
    write_json( os.path.join( args.gate_out, "plan-hashes.json" ), { "gate_plan_sha256": plan_hashes[ "gate" ], "reserve_plan_sha256": plan_hashes[ "gate-reserve" ] } )
    return 0


def writer_ledger_row( task_id, model, text ):
    """Return the writer-ledger row of one call: task id, model id, prompt hash, output sha256 (never the text)."""
    return { "task_id": task_id, "model": model, "prompt_hash": prompt_hash(), "output_sha256": hashlib.sha256( text.encode( "utf-8" ) ).hexdigest() }


async def run_writer( tasks, model, ledger_path, outputs_path, query_fn=None ):
    """
    Phase 2 body: one blind call per task not already in the ledger, each retried once on failure.

    Requires:
        - model_transport.set_budget has been called with a cap for model

    Ensures:
        - every ledger row is checked (content sha, model, prompt hash) before the first call; a mismatch is a ValueError and no call is made
        - a task already in the ledger is never called again
        - the ledger's rows must agree on model and prompt hash with each other and with now, or ValueError
        - a failed or empty call is retried once; still failing, the task is recorded as dropped
        - a CallBudgetExceeded is not retried and ends the run
        - returns { "called": n, "dropped": [ task_id ] }
    """
    rows = read_jsonl( ledger_path ) if os.path.exists( ledger_path ) else []
    check_ledger_identity( rows, model )
    done = { r[ "task_id" ]: r for r in rows }
    for task in tasks:
        if task[ "task_id" ] in done and done[ task[ "task_id" ] ].get( "task_sha" ) != task_sha( task[ "instruction" ], task[ "text" ] ):
            raise ValueError( f"task {task[ 'task_id' ]} is in the ledger for different text: the plan was redrawn into the same files" )
    called, dropped = 0, []
    for task in tasks:
        sha = task_sha( task[ "instruction" ], task[ "text" ] )
        if task[ "task_id" ] in done: continue
        text = None
        for _ in range( 2 ):
            try:
                text = await model_transport.complete( model, WRITER_SYSTEM_PROMPT, task[ "instruction" ] + "\n\n" + task[ "text" ], query_fn=query_fn )
                called += 1
                break
            except model_transport.ModelCallError:
                called += 1
        with open( ledger_path, "a", encoding="utf-8" ) as f:
            row = dict( writer_ledger_row( task[ "task_id" ], model, text ), task_sha=sha ) if text is not None else { "task_id": task[ "task_id" ], "model": model, "prompt_hash": prompt_hash(), "task_sha": sha, "dropped": True }
            f.write( json.dumps( row, sort_keys=True ) + "\n" )
        if text is None: dropped.append( task[ "task_id" ] )
        else:
            with open( outputs_path, "a", encoding="utf-8" ) as f: f.write( json.dumps( { "task_id": task[ "task_id" ], "text": text, "task_sha": sha }, sort_keys=True ) + "\n" )
    return { "called": called, "dropped": dropped }


def cmd_write( args, query_fn=None ):
    """
    Phase 2: blind writer calls. Refuses without a cap, off the shared ledger, past the approved count, or for reserve.

    Returns the exit code: 0 done, 2 refused, 3 a call cap stopped the run.

    --approved-calls bounds the pending TASKS. A task that fails is called a second time, so calls can reach twice
    the approved count before the model cap stops them. The 10% hold of spec part 3 item 3 (cap, minus 10%, minus
    calls spent, read from the ledger) is not enforced here: it rests on the number the approver gives.
    A plan edited after it was drawn, a ledger written by another model or prompt, or a ledger row for different
    task text (a plan redrawn into the same files) is refused with exit 2.
    """
    import asyncio
    if args.split not in WRITER_SPLITS:
        print( f"REFUSED: the call cap covers {', '.join( WRITER_SPLITS )} only; {args.split} needs a second figure from Rick", file=sys.stderr )
        return 2
    try:
        check_writer_model( args.writer_model, { "extractor": args.extractor_model, "judge": args.judge_model, "escalation": args.escalation_model } )
        caps = { m: int( n ) for m, _, n in ( c.rpartition( "=" ) for c in args.model_cap ) }
        if args.writer_model not in caps: raise ValueError( f"--model-cap {args.writer_model}=N is required" )
        if os.path.realpath( args.call_ledger ) != os.path.realpath( SHARED_CALL_LEDGER ): raise ValueError( f"--call-ledger must be the shared ledger {SHARED_CALL_LEDGER}" )
        model_transport.set_budget( args.call_ledger, caps )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    base   = os.path.join( args.base, args.split )
    tasks  = read_jsonl( os.path.join( base, "writer_tasks.jsonl" ) )
    ledger = os.path.join( base, "writer_ledger.jsonl" )
    try: check_plan_hash( json.loads( open( os.path.join( base, "plan.json" ), encoding="utf-8" ).read() ) )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    done   = { r[ "task_id" ] for r in read_jsonl( ledger ) } if os.path.exists( ledger ) else set()
    pending = [ t for t in tasks if t[ "task_id" ] not in done ]
    if len( pending ) > args.approved_calls:
        print( f"REFUSED: {len( pending )} calls are pending and only {args.approved_calls} are approved", file=sys.stderr )
        return 2
    try:
        result = asyncio.run( run_writer( tasks, args.writer_model, ledger, os.path.join( base, "writer_outputs.jsonl" ), query_fn ) )
    except model_transport.CallBudgetExceeded as e:
        print( f"STOPPED: {e}", file=sys.stderr )
        return 3
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    print( f"writer calls={result[ 'called' ]} dropped={len( result[ 'dropped' ] )}" )
    return 0


def checked_outputs( base, plan ):
    """
    Return { task_id: text } for every task of the plan, or raise.

    Raises:
        - ValueError if the plan was edited after it was drawn, a task has no output, or an output answers
          different text than the plan's task now holds (the plan was redrawn into the same files)
    """
    check_plan_hash( plan )
    path    = os.path.join( base, "writer_outputs.jsonl" )
    rows    = { r[ "task_id" ]: r for r in read_jsonl( path ) } if os.path.exists( path ) else {}
    missing = sorted( t for t in plan[ "tasks" ] if t not in rows )
    if missing: raise ValueError( f"{len( missing )} writer task(s) have no output" )
    stale = sorted( t for t, meta in plan[ "tasks" ].items() if rows[ t ].get( "task_sha" ) != meta[ "sha256" ] )
    if stale: raise ValueError( f"{len( stale )} writer output(s) answer different text than the plan's task: the plan was redrawn into the same files" )
    return { t: rows[ t ][ "text" ] for t in plan[ "tasks" ] }


def cmd_verify( args ):
    """
    Phase 3: write the second seat's input (no kind labels) and a separate span file, and report what is missing.

    Returns 0 when written. Reads writer_outputs.jsonl; refuses (2) while a task has no output.
    """
    base = os.path.join( args.base, args.split )
    plan = json.loads( open( os.path.join( base, "plan.json" ), encoding="utf-8" ).read() )
    try: outputs = checked_outputs( base, plan )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    by_pair = { p[ "id" ]: { "id": p[ "id" ], "old": p[ "old" ], "new": "", "linked_doc": "" } for p in plan[ "pairs" ] }
    for task_id, meta in plan[ "tasks" ].items(): by_pair[ meta[ "pair_id" ] ][ meta[ "role" ] ] = outputs[ task_id ]
    write_jsonl( os.path.join( base, "verify-input.jsonl" ), [ by_pair[ p[ "id" ] ] for p in plan[ "pairs" ] ] )
    write_jsonl( os.path.join( base, "verify-spans.jsonl" ), [ { "id": p[ "id" ], "x_span_in_old": p[ "x_span_in_old" ] } for p in plan[ "pairs" ] ] )
    return 0


def check_verification( plan, rows ):
    """
    Return the list of problems in the second seat's file: a pair with no row, or any false field.

    Ensures:
        - a seeded pair needs claim_absent_in_new true; an unseeded one needs no_claim_missing true; every pair needs grammar_ok true
    """
    by_id = { r[ "id" ]: r for r in rows }
    bad = []
    for p in plan[ "pairs" ]:
        row = by_id.get( p[ "id" ] )
        if row is None: bad.append( f"{p[ 'id' ]}: no verification row" )
        elif p[ "kind" ] in SEEDED_KINDS and row.get( "claim_absent_in_new" ) is not True: bad.append( f"{p[ 'id' ]}: claim_absent_in_new is not true" )
        elif p[ "kind" ] not in SEEDED_KINDS and row.get( "no_claim_missing" ) is not True: bad.append( f"{p[ 'id' ]}: no_claim_missing is not true" )
        elif row.get( "grammar_ok" ) is not True: bad.append( f"{p[ 'id' ]}: grammar_ok is not true" )
    return bad


def recount( plan ):
    """Count seeded pairs per kind by span-word band (2-3, 4-6, 7+), and per weaken class."""
    bands = lambda w: "2-3" if w <= 3 else ( "4-6" if w <= 6 else "7+" )
    counts = { "bands": {}, "classes": {}, "kinds": {} }
    for p in plan[ "pairs" ]:
        counts[ "kinds" ][ p[ "kind" ] ] = counts[ "kinds" ].get( p[ "kind" ], 0 ) + 1
        if p[ "kind" ] in SEEDED_KINDS:
            key = p[ "kind" ] + ":" + bands( p[ "span_words" ] )
            counts[ "bands" ][ key ] = counts[ "bands" ].get( key, 0 ) + 1
        if p[ "weaken_class" ]: counts[ "classes" ][ p[ "weaken_class" ] ] = counts[ "classes" ].get( p[ "weaken_class" ], 0 ) + 1
    return counts


def cmd_assemble( args ):
    """
    Phase 4: join the plan, writer output and the second seat's file into pairs, keys and a split manifest.

    Returns 0 done; 2 refused (missing or false verification row, missing writer output, or a loader failure).
    Layout: dev/pairs.jsonl and keys/dev-keys.jsonl; gate files go under --out too (pass --out outside the repo).
    """
    base    = os.path.join( args.base, args.split )
    plan    = json.loads( open( os.path.join( base, "plan.json" ), encoding="utf-8" ).read() )
    ledger  = read_jsonl( os.path.join( base, "writer_ledger.jsonl" ) )
    try:
        outputs = checked_outputs( base, plan )
        check_ledger_identity( ledger )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    problems = check_verification( plan, read_jsonl( args.verification ) )
    if problems:
        print( "REFUSED: " + "; ".join( problems[ :5 ] ), file=sys.stderr )
        return 2
    new, linked = {}, {}
    for task_id, meta in plan[ "tasks" ].items(): ( new if meta[ "role" ] == "new" else linked )[ meta[ "pair_id" ] ] = outputs[ task_id ]
    pair_rows, key_rows = [], []
    for p in plan[ "pairs" ]:
        pair_rows.append( { "id": p[ "id" ], "file": p[ "file" ], "symbol": p[ "symbol" ], "old": p[ "old" ], "new": new[ p[ "id" ] ], "linked_doc": linked.get( p[ "id" ], "" ) } )
        seeded = p[ "kind" ] in SEEDED_KINDS
        key_rows.append( { "id": p[ "id" ], "kind": p[ "kind" ], "weaken_class": p[ "weaken_class" ], "changed_token": p[ "changed_token" ], "seeded_positive": seeded,
                           "must_pass_relocated": p[ "kind" ] == "relocate", "x_span_in_old": p[ "x_span_in_old" ], "span_words": p[ "span_words" ], "span_chars": p[ "span_chars" ],
                           "short": p[ "short" ], "stratum": p[ "stratum" ], "writer": ledger[ 0 ][ "model" ], "arm": "scripted", "injection": None, "bucket": p[ "kind" ] } )
    pairs_path = os.path.join( args.out, args.split, "pairs.jsonl" )
    keys_path  = os.path.join( args.out, "keys", args.split + "-keys.jsonl" )
    if args.split in GATE_SPLITS:
        try: refuse_gate_out_in_repo( args.out )
        except ValueError as e:
            print( f"REFUSED: {e}", file=sys.stderr )
            return 2
    write_jsonl( pairs_path, pair_rows )
    write_jsonl( keys_path, key_rows )
    try:
        labelled_pairs.load_pairs( pairs_path, keys_path, gate=args.split in GATE_SPLITS )
    except ValueError as e:
        print( f"REFUSED: the assembled set does not load: {e}", file=sys.stderr )
        return 2
    info = { "split": args.split, "pairs_sha256": sha256_file( pairs_path ), "keys_sha256": sha256_file( keys_path ), "counts": recount( plan ),
             "writer": ledger[ 0 ][ "model" ], "writer_prompt_hash": prompt_hash(), "writer_calls": len( ledger ), "human_arm": "no human arm" }
    write_json( os.path.join( args.out, args.split + "-info.json" ), info )
    return 0


def cmd_manifest( args ):
    """
    Write the dev-visible root MANIFEST.json.

    The gate-hashes file holds gate_pairs_sha256, gate_keys_sha256 and reserve_plan_sha256 (written by plan into the gate
    store as plan-hashes.json); the reserve pairs and keys hashes are optional, since no reserve writer call is made.

    Holds: the dev files and shas, the dev seed, the writer id, prompt hash, floors, dev counts, the gate and
    reserve pairs/keys sha256 values, the harness commit, the stoplist sha.
    Never holds: the gate seed, the split seed, a gate or reserve file list, a gate sha filename, gate counts by class.
    Returns 0, or 2 when the commit is not 40 hex digits.
    """
    if not re.fullmatch( r"[0-9a-f]{40}", args.harness_commit ):
        print( "REFUSED: --harness-commit must be a 40-digit hex sha", file=sys.stderr )
        return 2
    dev  = json.loads( open( args.dev_info, encoding="utf-8" ).read() )
    hashes = json.loads( open( args.gate_hashes, encoding="utf-8" ).read() )
    manifest = { "dev": { "pairs_sha256": dev[ "pairs_sha256" ], "keys_sha256": dev[ "keys_sha256" ], "counts": dev[ "counts" ], "seed": args.seed },
                 "writer": dev[ "writer" ], "writer_prompt_hash": dev[ "writer_prompt_hash" ], "human_arm": dev[ "human_arm" ],
                 "floors": { "min_quote_words": claim_extractor.MIN_QUOTE_WORDS, "min_quote_chars": claim_extractor.MIN_QUOTE_CHARS },
                 "stoplist": { "path": os.path.basename( args.stoplist ), "sha256": sha256_file( args.stoplist ) },
                 "gate_pairs_sha256": hashes[ "gate_pairs_sha256" ], "gate_keys_sha256": hashes[ "gate_keys_sha256" ],
                 "reserve_plan_sha256": hashes[ "reserve_plan_sha256" ], "reserve_pairs_sha256": hashes.get( "reserve_pairs_sha256" ), "reserve_keys_sha256": hashes.get( "reserve_keys_sha256" ),
                 "harness_commit": args.harness_commit }
    write_json( os.path.join( args.out, "MANIFEST.json" ), manifest )
    return 0


def cmd_natural( args ):
    """
    Validate natural.jsonl and write it as its own arm of hand-labelled real removals.

    Requires:
        - each row of --natural is { id, file, symbol, old, new, x_span_in_old, found_by }; found_by names who found it

    Ensures:
        - every x_span_in_old occurs once in old exactly as typed (the loader's own rule: a person types this span,
          so whitespace can differ from old) and passes quotable_once, or the whole file is refused (exit 2)
        - writes natural/pairs.jsonl and keys/natural-keys.jsonl, arm "natural", never joined to a pooled count
        - the keys carry found_by, because the manifest names who found each item

    Returns 0 done, 2 refused.
    """
    rows = read_jsonl( args.natural )
    bad  = [ r[ "id" ] for r in rows if r[ "old" ].count( r[ "x_span_in_old" ] ) != 1 or not quotable_once( r[ "old" ], r[ "x_span_in_old" ] ) ]
    if bad:
        print( f"REFUSED: natural span(s) not quotable once in old: {', '.join( bad )}", file=sys.stderr )
        return 2
    write_jsonl( os.path.join( args.out, "natural", "pairs.jsonl" ), [ { "id": r[ "id" ], "file": r[ "file" ], "symbol": r[ "symbol" ], "old": r[ "old" ], "new": r[ "new" ], "linked_doc": "" } for r in rows ] )
    write_jsonl( os.path.join( args.out, "keys", "natural-keys.jsonl" ), [ { "id": r[ "id" ], "kind": "natural", "weaken_class": None, "changed_token": None, "seeded_positive": True, "must_pass_relocated": False,
                                                                         "x_span_in_old": r[ "x_span_in_old" ], "span_words": words_of( r[ "x_span_in_old" ] ), "span_chars": len( r[ "x_span_in_old" ] ),
                                                                         "short": is_short( words_of( r[ "x_span_in_old" ] ) ), "stratum": stratum_of( r[ "old" ] ), "writer": "human", "arm": "natural",
                                                                         "injection": None, "bucket": "natural", "found_by": r[ "found_by" ] } for r in rows ] )
    return 0


def build_parser():
    """Return the command-line parser: one subcommand per phase."""
    parser = argparse.ArgumentParser( description="Seed the labelled before/after set." )
    sub    = parser.add_subparsers( dest="command", required=True )
    p = sub.add_parser( "plan" )
    p.add_argument( "--pool", required=True ); p.add_argument( "--out", required=True ); p.add_argument( "--gate-out", required=True )
    p.add_argument( "--option", choices=( "A", "B" ), required=True )
    p.add_argument( "--seed", type=int, required=True ); p.add_argument( "--gate-seed", type=int, required=True )
    p.add_argument( "--split-seed", type=int, required=True ); p.add_argument( "--split-tries", type=int, default=50 )
    p.add_argument( "--stoplist", default=DEFAULT_STOPLIST ); p.add_argument( "--exclude" ); p.add_argument( "--sizes-json" )
    w = sub.add_parser( "write" )
    w.add_argument( "--base", required=True ); w.add_argument( "--split", required=True )
    w.add_argument( "--writer-model", required=True )
    for name in ( "extractor", "judge", "escalation" ): w.add_argument( f"--{name}-model", required=True )
    w.add_argument( "--model-cap", action="append", default=[] ); w.add_argument( "--call-ledger", required=True )
    w.add_argument( "--approved-calls", type=int, required=True )
    v = sub.add_parser( "verify" )
    v.add_argument( "--base", required=True ); v.add_argument( "--split", required=True )
    a = sub.add_parser( "assemble" )
    a.add_argument( "--base", required=True ); a.add_argument( "--split", required=True ); a.add_argument( "--out", required=True ); a.add_argument( "--verification", required=True )
    n = sub.add_parser( "natural" )
    n.add_argument( "--natural", required=True ); n.add_argument( "--out", required=True )
    m = sub.add_parser( "manifest" )
    m.add_argument( "--dev-info", required=True ); m.add_argument( "--gate-hashes", required=True ); m.add_argument( "--out", required=True )
    m.add_argument( "--seed", type=int, required=True ); m.add_argument( "--harness-commit", required=True ); m.add_argument( "--stoplist", default=DEFAULT_STOPLIST )
    return parser


def main( argv, query_fn=None ):
    """Run one phase; returns its exit code."""
    args = build_parser().parse_args( argv )
    if args.command == "write": return cmd_write( args, query_fn )
    return { "plan": cmd_plan, "verify": cmd_verify, "assemble": cmd_assemble, "natural": cmd_natural, "manifest": cmd_manifest }[ args.command ]( args )


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main( sys.argv[ 1: ] ) )
