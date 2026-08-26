#!/usr/bin/env python3
"""
Subject-loss detector for condensed DMs — MEASUREMENT INSTRUMENT (row cf1587cd item 2).

Offline analysis instrument, not send-path code. It exists to produce a RATE from the
real traffic corpus and to be checked against hand labels.

DEFINITION OF SUBJECT-LOSS, written before anything was measured:

    A condensed DM has LOST THE SUBJECT when a reader holding only the delivered text
    can no longer recover WHO a claim is about, and the sender's original text made
    that recoverable.

Three countable signals. A pair is subject-lost if ANY fires:

    A  ATTRIBUTION DROPPED   the original binds claims to a person — a first- or
                             second-person pronoun standing as a grammatical subject,
                             or a fleet persona name — and the delivered PROSE carries
                             no person at all
    B  ROLE-NOUN SUBSTITUTION the delivered prose speaks about "the developer" / "the
                             reviewer" / "the user" — a role that names nobody — where
                             the original never used that frame
    C  INVENTED COMMAND      the delivered prose issues a bare imperative whose verb
                             the original never used, turning a report into an order

DELIBERATELY NOT COUNTED, and reported separately instead:

    "the sender" / "the author" / "the writer" / "the speaker" decode to the sender
    every time, so they are a change of voice rather than a loss of subject. Counting
    them would inflate the rate with cases a reader can still resolve.

    Attribution INVERSION — the delivered text names a person and names the WRONG one.
    Two of the fifty hand-labelled pairs are this shape and no signal here can see it;
    the rate below is therefore a FLOOR, not a total.
"""

import re

import spacy

_NLP = spacy.load( "en_core_web_sm", disable=[ "ner", "lemmatizer" ] )

PERSONAS = [
    "maria", "maría", "mr radio", "mr. radio", "rachel", "tiberius", "rio", "tiffany",
    "krishna", "sam", "clayton", "cheech", "maya", "pocholo", "chloe", "john",
    "arnold", "rick",
]

_PRONOUN = re.compile(
    r"\b(?:i|me|my|mine|myself|we|us|our|ours|you|your|yours|yourself)\b", re.IGNORECASE
)
_PERSONA = re.compile( r"\b(?:" + "|".join( re.escape( p ) for p in PERSONAS ) + r")\b",
                       re.IGNORECASE )

# A role that names NOBODY. "the developer" leaves the reader with a job title where a
# name belonged; these are the substitutions that cost recoverability.
_ANON_ROLE = re.compile(
    r"\bthe\s+(?:developer|engineer|reviewer|manager|worker|user|person|individual|"
    r"team|seat|session|agent|assistant|maintainer|owner|caller|client)\b",
    re.IGNORECASE
)

# A role that decodes to the sender every time — reported, never counted.
_SENDER_ROLE = re.compile(
    r"\bthe\s+(?:sender|author|writer|speaker)\b", re.IGNORECASE
)

_NOTICE = re.compile(
    r"^\s*This DM was condensed in transit\..*$", re.IGNORECASE | re.MULTILINE
)


def strip_tutor_furniture( delivered ):
    """
    Remove what the send path ADDED, so the comparison is prose against prose.

    Requires:
        - delivered is a string

    Ensures:
        - returns the text with the condensed-in-transit notice removed
        - returns a string, never None

    Raises:
        - nothing
    """
    return _NOTICE.sub( "", delivered or "" ).strip()


def prose_only( text ):
    """
    The claim-carrying lines, joined — tables, fences, headings and POINTER LINES out.

    ⚠️ THE POINTER LINES MUST GO. A restored path such as
    `.claude-memento-cheech-80c17315.md` contains a persona name, and counting it as
    attribution made the detector call a subject-less rewrite "attributed" — two of the
    six misses in the first calibration run were exactly that.

    Requires:
        - text is a string

    Ensures:
        - returns the prose lines joined by a space, using the tutor's own structure rule
        - falls back to the raw text if the tutor module cannot be imported

    Raises:
        - nothing
    """
    try:
        from cosa.agents.dm_tutor.sentences import prose_lines
        return " ".join( prose_lines( text ) )
    except Exception:
        return text


def strip_pointers( text ):
    """
    Remove path / URL / filename tokens from prose before any person check.

    ⚠️ WITHOUT THIS THE DETECTOR READS A FILENAME AS AN ATTRIBUTION. The restored
    pointer '.claude-memento-cheech-80c17315.md' carries a persona name inside it,
    and
    a rewrite that had thrown every person away was scored as attributed because of it.
    Two of the six misses in the first calibration run were that one line.

    Requires:
        - text is a string

    Ensures:
        - returns the text with every pointer token blanked, same length semantics not
          preserved (tokens are replaced by a space, which cannot create a new word)
        - falls back to the text unchanged if the tutor module cannot be imported

    Raises:
        - nothing
    """
    try:
        from cosa.agents.dm_tutor.sentences import pointer_tokens
        for token in pointer_tokens( text ):
            text = text.replace( token, " " )
        return text
    except Exception:
        return text


def _has_person( text ):
    """
    True when the text names or points at a person.

    Requires:
        - text is a string

    Ensures:
        - returns True for a first/second-person pronoun or a fleet persona name

    Raises:
        - nothing
    """
    return bool( _PRONOUN.search( text ) ) or bool( _PERSONA.search( text ) )


def _person_is_subject( text ):
    """
    True when a person stands as the grammatical SUBJECT of some sentence.

    The tightening that separates a message ABOUT people from one that merely mentions
    one in passing: a rewrite may drop an incidental "I" without costing the reader
    anything, but dropping the subject of the claim is the defect.

    Requires:
        - text is a string

    Ensures:
        - returns True when some token in nsubj / nsubjpass position is a first- or
          second-person pronoun, a possessive attached to one, or a persona name
        - returns False on any parse failure

    Raises:
        - nothing
    """
    try:
        if not text.strip(): return False
        for tok in _NLP( text ):
            if tok.dep_ not in ( "nsubj", "nsubjpass", "poss" ): continue
            if _PRONOUN.fullmatch( tok.text ) or _PERSONA.fullmatch( tok.text ): return True
    except Exception:
        return False
    return False


def _anon_role_is_subject( text ):
    """
    True when an anonymous role noun stands as the SUBJECT of some sentence.

    The tightening that keeps "the session ID was not found" out: there the head noun
    is "ID", so nobody has been replaced by a role — the phrase merely contains one.

    Requires:
        - text is a string

    Ensures:
        - returns True only when a token in nsubj / nsubjpass position is the HEAD of a
          matched anonymous-role phrase
        - returns False on any parse failure

    Raises:
        - nothing
    """
    try:
        if not text.strip(): return False
        doc = _NLP( text )
        for match in _ANON_ROLE.finditer( text ):
            span = doc.char_span( match.start(), match.end(), alignment_mode="expand" )
            if span is None: continue
            if span.root.dep_ in ( "nsubj", "nsubjpass" ): return True
    except Exception:
        return False
    return False


def _imperative_sentences( text ):
    """
    The bare commands in a text, as ( sentence, root-verb-lower ) pairs.

    Requires:
        - text is a string

    Ensures:
        - a sentence qualifies when its ROOT is a base-form verb (tag VB) with no
          nsubj / nsubjpass / expl child and the sentence is not a question
        - returns [] on any parse failure

    Raises:
        - nothing
    """
    out = []
    try:
        if not text.strip(): return []
        for sent in _NLP( text ).sents:
            root = sent.root
            if root.pos_ != "VERB" or root.tag_ != "VB": continue
            if sent.text.strip().endswith( "?" ): continue
            if any( c.dep_ in ( "nsubj", "nsubjpass", "expl" ) for c in root.children ): continue
            out.append( ( sent.text.strip(), root.text.lower() ) )
    except Exception:
        return []
    return out


def _verbs_used( text ):
    """
    Every verb surface form in a text, lowercased.

    Requires:
        - text is a string

    Ensures:
        - returns a set of lowercase strings
        - returns an empty set on any parse failure

    Raises:
        - nothing
    """
    try:
        return { t.text.lower() for t in _NLP( text ) if t.pos_ in ( "VERB", "AUX" ) }
    except Exception:
        return set()


def classify( original, delivered ):
    """
    Label one ( submitted, delivered ) pair.

    Requires:
        - original and delivered are strings

    Ensures:
        - returns a dict with booleans a / b / c, the reported-only `sender_role`,
          and `subject_lost` = a or b or c
        - never raises

    Raises:
        - nothing
    """
    orig  = strip_pointers( prose_only( original or "" ) )
    deliv = strip_pointers( prose_only( strip_tutor_furniture( delivered ) ) )

    a = _person_is_subject( orig ) and not _has_person( deliv )

    b = _anon_role_is_subject( deliv ) and not bool( _ANON_ROLE.search( orig ) )

    orig_verbs = _verbs_used( orig )
    c = any( verb not in orig_verbs for _, verb in _imperative_sentences( deliv ) )

    sender_role = bool( _SENDER_ROLE.search( deliv ) ) and not bool( _SENDER_ROLE.search( orig ) )

    return { "a": a, "b": b, "c": c, "sender_role": sender_role,
             "subject_lost": bool( a or b or c ) }
